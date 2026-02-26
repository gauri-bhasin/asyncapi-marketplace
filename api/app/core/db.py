import json
import secrets
import hashlib
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import settings


def get_conn() -> psycopg.Connection:
    return psycopg.connect(settings.psycopg_dsn, row_factory=dict_row)


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


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_api_key() -> str:
    raw = f"{settings.api_key_prefix}{secrets.token_urlsafe(24)}"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO api_keys (key_hash) VALUES (%s)", (hash_api_key(raw),))
        conn.commit()
    return raw


def validate_api_key(raw: str) -> bool:
    if not raw:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM api_keys WHERE key_hash=%s LIMIT 1", (hash_api_key(raw),))
            return cur.fetchone() is not None


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
