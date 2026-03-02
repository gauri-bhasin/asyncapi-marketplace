import json
import secrets
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def get_conn() -> psycopg.Connection:
    return psycopg.connect(settings.psycopg_dsn, row_factory=dict_row)


# ---------------------------------------------------------------------------
# V1 schema bootstrap (kept for backward compatibility)
# ---------------------------------------------------------------------------

def init_db() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id BIGSERIAL PRIMARY KEY,
                    key_hash TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS topics (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                    asyncapi_json JSONB NOT NULL,
                    sample_payload JSONB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id BIGSERIAL PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    topic TEXT NOT NULL,
                    ts TIMESTAMPTZ NOT NULL,
                    source TEXT NOT NULL,
                    tags JSONB NOT NULL,
                    payload JSONB NOT NULL,
                    raw_event JSONB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_topic_ts ON events(topic, ts DESC);
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id BIGSERIAL PRIMARY KEY,
                    action TEXT NOT NULL,
                    details JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS dlq_events (
                    id BIGSERIAL PRIMARY KEY,
                    event_id TEXT,
                    topic TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Migrations runner
# ---------------------------------------------------------------------------

def run_migrations() -> None:
    migrations_dir = Path(__file__).resolve().parent.parent.parent / "migrations"
    if not migrations_dir.exists():
        log.info("No migrations directory found at %s – skipping", migrations_dir)
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS _migrations (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            for sql_file in sorted(migrations_dir.glob("*.sql")):
                cur.execute("SELECT 1 FROM _migrations WHERE name=%s", (sql_file.name,))
                if cur.fetchone():
                    continue
                log.info("Applying migration %s …", sql_file.name)
                cur.execute(sql_file.read_text(encoding="utf-8"))
                cur.execute("INSERT INTO _migrations (name) VALUES (%s)", (sql_file.name,))
        conn.commit()
    log.info("Migrations complete")


# ---------------------------------------------------------------------------
# API-key helpers
# ---------------------------------------------------------------------------

def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_api_key(user_id: int | None = None, label: str = "") -> str:
    """Create a new API key, optionally linked to a user."""
    raw = f"{settings.api_key_prefix}{secrets.token_urlsafe(24)}"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO api_keys (key_hash, user_id, label) VALUES (%s, %s, %s)",
                (hash_api_key(raw), user_id, label),
            )
        conn.commit()
    return raw


def validate_api_key(raw: str) -> bool:
    if not raw:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM api_keys WHERE key_hash=%s AND revoked=FALSE LIMIT 1",
                (hash_api_key(raw),),
            )
            return cur.fetchone() is not None


def resolve_api_key(raw: str) -> dict[str, Any] | None:
    """Return {api_key_id, user_id, key_hash} or None."""
    if not raw:
        return None
    h = hash_api_key(raw)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, revoked FROM api_keys WHERE key_hash=%s LIMIT 1",
                (h,),
            )
            row = cur.fetchone()
            if not row or row["revoked"]:
                return None
            return {"api_key_id": row["id"], "user_id": row["user_id"], "key_hash": h}


# ---------------------------------------------------------------------------
# Rate-limit / usage helpers
# ---------------------------------------------------------------------------

def check_rate_limit(api_key_id: int) -> bool:
    """Return True when the key has exceeded its per-minute quota."""
    window = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT counter FROM usage_counters WHERE api_key_id=%s AND topic='*' AND window_start=%s",
                (api_key_id, window),
            )
            row = cur.fetchone()
            return row is not None and row["counter"] >= settings.rate_limit_per_minute


def increment_usage(api_key_id: int, topic: str = "*") -> None:
    window = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO usage_counters (api_key_id, topic, window_start, counter)
                VALUES (%s, %s, %s, 1)
                ON CONFLICT (api_key_id, topic, window_start)
                DO UPDATE SET counter = usage_counters.counter + 1
                """,
                (api_key_id, topic, window),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Audit helper
# ---------------------------------------------------------------------------

def write_audit(action: str, details: dict[str, Any]) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_logs (action, details) VALUES (%s, %s::jsonb)",
                (action, json.dumps(details)),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Topic seeding
# ---------------------------------------------------------------------------

def seed_topics_from_asyncapi(asyncapi_dir: Path) -> None:
    files = list(asyncapi_dir.glob("*.json"))
    if not files:
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            for file_path in files:
                doc = json.loads(file_path.read_text(encoding="utf-8"))
                for channel_name, channel_obj in doc.get("channels", {}).items():
                    desc = channel_obj.get("description", "")
                    tags = [*doc.get("info", {}).get("title", "").split(), *channel_name.split(".")]
                    examples = (
                        doc.get("components", {})
                        .get("messages", {})
                        .values()
                    )
                    sample_payload: dict[str, Any] = {}
                    for message in examples:
                        if message.get("examples"):
                            sample_payload = message["examples"][0].get("payload", {})
                            break
                    cur.execute(
                        """
                        INSERT INTO topics (name, description, tags, asyncapi_json, sample_payload)
                        VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                        ON CONFLICT (name) DO UPDATE SET
                            description = EXCLUDED.description,
                            tags = EXCLUDED.tags,
                            asyncapi_json = EXCLUDED.asyncapi_json,
                            sample_payload = EXCLUDED.sample_payload
                        """,
                        (
                            channel_name,
                            desc,
                            json.dumps(tags),
                            json.dumps(doc),
                            json.dumps(sample_payload),
                        ),
                    )
        conn.commit()
