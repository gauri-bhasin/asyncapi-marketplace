import hashlib
import json
import os
import secrets
import time
import asyncio
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import chromadb
import psycopg
from chromadb.config import Settings as ChromaSettings
from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from pydantic import BaseModel
from psycopg.rows import dict_row
import sentry_sdk

SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=True,
    )

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://signalhub:signalhub@localhost:5432/signalhub",
).replace("postgresql+psycopg://", "postgresql://")
ASYNCAPI_DIR = Path(os.getenv("ASYNCAPI_DIR", "/app/shared/asyncapi"))
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8001"))
API_KEY_PREFIX = os.getenv("API_KEY_PREFIX", "sh_")
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))

events_ingested_total = Gauge("events_ingested_total", "Total events in store")
ws_active_subscriptions = Gauge("ws_active_subscriptions", "Active websocket subscriptions")
dlq_events_total = Gauge("dlq_events_total", "Total DLQ events")
webhooks_received_total = Gauge("webhooks_received_total", "Total webhooks received")
stories_generated_total = Gauge("stories_generated_total", "Total stories generated")
api_calls_total = Counter("api_calls_total", "Counted API calls", ["endpoint"])

RATE_BUCKETS: dict[int, dict[str, float]] = defaultdict(lambda: {"tokens": float(RATE_LIMIT_PER_MINUTE), "last": time.time()})
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


class SearchBody(BaseModel):
    query: str


class RecommendBody(BaseModel):
    goal: str


def deterministic_embedding(text: str, dim: int = 128) -> list[float]:
    values = [0.0] * dim
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = digest[0] % dim
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        values[idx] += sign * (1.0 + digest[2] / 255.0)
    norm = sum(v * v for v in values) ** 0.5
    return [v / norm for v in values] if norm else values


def get_conn() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def get_conn_for_health(timeout_seconds: int = 2) -> psycopg.Connection:
    """Connection with short timeout so /health fails fast when DB is down."""
    return psycopg.connect(
        DATABASE_URL, row_factory=dict_row, connect_timeout=timeout_seconds
    )


def get_chroma_collection() -> chromadb.Collection:
    client = chromadb.HttpClient(
        host=CHROMA_HOST,
        port=CHROMA_PORT,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection("signalhub_index")


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_api_key() -> str:
    raw = f"{API_KEY_PREFIX}{secrets.token_urlsafe(24)}"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO api_keys (user_label, api_key_hash) VALUES (%s, %s)",
                ("anonymous", hash_api_key(raw)),
            )
        conn.commit()
    return raw


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def ensure_schema() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS topics (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL,
                    tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
                    asyncapi_json JSONB NOT NULL,
                    sample_event_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                    id BIGSERIAL PRIMARY KEY,
                    user_label TEXT NOT NULL,
                    api_key_hash TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    last_used_at TIMESTAMPTZ NULL
                );
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id BIGSERIAL PRIMARY KEY,
                    api_key_id BIGINT NOT NULL REFERENCES api_keys(id),
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    last_seen_at TIMESTAMPTZ NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id UUID PRIMARY KEY,
                    topic TEXT NOT NULL,
                    ts TIMESTAMPTZ NOT NULL,
                    source TEXT NOT NULL,
                    tags_json JSONB NOT NULL,
                    payload_json JSONB NOT NULL,
                    payload_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_events_topic_ts ON events(topic, ts DESC);
                CREATE TABLE IF NOT EXISTS dlq_events (
                    id BIGSERIAL PRIMARY KEY,
                    event_id TEXT,
                    topic TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    replayed BOOLEAN NOT NULL DEFAULT FALSE,
                    replayed_at TIMESTAMPTZ NULL
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id BIGSERIAL PRIMARY KEY,
                    api_key_id BIGINT NULL REFERENCES api_keys(id),
                    action TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    metadata_json JSONB NOT NULL,
                    ts TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS deployments (
                    id UUID PRIMARY KEY,
                    repo TEXT NOT NULL,
                    env TEXT NOT NULL,
                    commit TEXT NOT NULL,
                    deploy_ref TEXT NOT NULL,
                    ts TIMESTAMPTZ NOT NULL,
                    raw_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS incidents (
                    id UUID PRIMARY KEY,
                    title TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    suspected_deploy_id UUID NULL,
                    confidence DOUBLE PRECISION NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS stories (
                    id UUID PRIMARY KEY,
                    incident_id UUID NOT NULL REFERENCES incidents(id),
                    story_text TEXT NOT NULL,
                    story_json JSONB NOT NULL,
                    ts TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
        conn.commit()


def seed_topics() -> None:
    files = list(ASYNCAPI_DIR.glob("*.json"))
    if not files:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            for file_path in files:
                doc = json.loads(file_path.read_text(encoding="utf-8"))
                channels = doc.get("channels", {})
                messages = doc.get("components", {}).get("messages", {})
                sample = {}
                for msg in messages.values():
                    examples = msg.get("examples") or []
                    if examples:
                        sample = examples[0].get("payload", {})
                        break
                for channel_name, channel in channels.items():
                    tags = sorted(set(channel_name.split(".") + doc.get("info", {}).get("title", "").lower().split()))
                    cur.execute(
                        """
                        INSERT INTO topics (name, description, tags, asyncapi_json, sample_event_json)
                        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                        ON CONFLICT (name) DO UPDATE SET
                            description = EXCLUDED.description,
                            tags = EXCLUDED.tags,
                            asyncapi_json = EXCLUDED.asyncapi_json,
                            sample_event_json = EXCLUDED.sample_event_json
                        """,
                        (
                            channel_name,
                            channel.get("description", ""),
                            tags,
                            json.dumps(doc),
                            json.dumps(sample),
                        ),
                    )
        conn.commit()


def resolve_api_key(raw: str | None) -> dict[str, Any]:
    if not raw:
        raise HTTPException(status_code=401, detail="Missing API key")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM api_keys WHERE api_key_hash=%s LIMIT 1", (hash_api_key(raw),))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=401, detail="Invalid API key")
            cur.execute("UPDATE api_keys SET last_used_at=now() WHERE id=%s", (row["id"],))
        conn.commit()
    return row


def consume_rate_token(api_key_id: int) -> None:
    bucket = RATE_BUCKETS[api_key_id]
    now = time.time()
    elapsed = now - bucket["last"]
    refill = elapsed * (RATE_LIMIT_PER_MINUTE / 60.0)
    bucket["tokens"] = min(float(RATE_LIMIT_PER_MINUTE), bucket["tokens"] + refill)
    bucket["last"] = now
    if bucket["tokens"] < 1.0:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    bucket["tokens"] -= 1.0


def write_audit(api_key_id: int, action: str, topic: str, metadata: dict[str, Any]) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_logs (api_key_id, action, topic, metadata_json)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (api_key_id, action, topic, json.dumps(metadata)),
            )
        conn.commit()


def require_key(x_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    row = resolve_api_key(x_api_key)
    consume_rate_token(row["id"])
    return row


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("SKIP_DB_INIT", "0") != "1":
        ensure_schema()
        seed_topics()
    trace.set_tracer_provider(TracerProvider())
    yield


app = FastAPI(title="signalhub-api", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
FastAPIInstrumentor.instrument_app(app)


@app.get("/sentry-debug")
async def trigger_error() -> dict[str, str]:
    1 / 0  # will be captured by Sentry
    return {"status": "ok"}


@app.post("/apikeys")
def create_api_key() -> dict[str, str]:
    api_calls_total.labels(endpoint="/apikeys").inc()
    return {"api_key": issue_api_key()}


@app.get("/topics")
def get_topics(_auth: dict = Depends(require_key)) -> list[dict]:
    api_calls_total.labels(endpoint="/topics").inc()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name, description, tags, created_at FROM topics ORDER BY name")
            return cur.fetchall()


@app.get("/topics/{name}")
def get_topic(name: str, _auth: dict = Depends(require_key)) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, description, tags, asyncapi_json, sample_event_json, created_at FROM topics WHERE name=%s",
                (name,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Topic not found")
            return row


@app.get("/topics/{name}/history")
def topic_history(name: str, limit: int = Query(default=100, ge=1, le=1000), auth: dict = Depends(require_key)) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_id::text AS event_id, topic, ts::text AS ts, source, tags_json, payload_json
                FROM events
                WHERE topic=%s
                ORDER BY ts DESC
                LIMIT %s
                """,
                (name, limit),
            )
            rows = cur.fetchall()
    write_audit(auth["id"], "history", name, {"limit": limit})
    return rows


@app.get("/topics/{name}/replay")
def topic_replay(name: str, since: str, until: str, auth: dict = Depends(require_key)) -> list[dict]:
    since_dt = parse_iso(since)
    until_dt = parse_iso(until)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_id::text AS event_id, topic, ts::text AS ts, source, tags_json, payload_json
                FROM events
                WHERE topic=%s AND ts BETWEEN %s AND %s
                ORDER BY ts ASC
                LIMIT 2000
                """,
                (name, since_dt, until_dt),
            )
            rows = cur.fetchall()
    write_audit(auth["id"], "replay", name, {"since": since, "until": until, "count": len(rows)})
    return rows


@app.get("/incidents")
def list_incidents(_auth: dict = Depends(require_key)) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM incidents ORDER BY created_at DESC LIMIT 200")
            return cur.fetchall()


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str, _auth: dict = Depends(require_key)) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM incidents WHERE id=%s::uuid", (incident_id,))
            incident = cur.fetchone()
            if not incident:
                raise HTTPException(status_code=404, detail="Incident not found")
            cur.execute(
                """
                SELECT id::text AS id, incident_id::text AS incident_id, story_text, story_json, ts
                FROM stories WHERE incident_id=%s::uuid ORDER BY ts DESC
                """,
                (incident_id,),
            )
            incident["stories"] = cur.fetchall()
            return incident


@app.get("/incidents/{incident_id}/replay")
def incident_replay(incident_id: str, window_minutes: int = Query(default=30, ge=5, le=240), auth: dict = Depends(require_key)) -> dict:
    """Replay deploy + error + story events around an incident's suspected deploy."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM incidents WHERE id=%s::uuid", (incident_id,))
            incident = cur.fetchone()
            if not incident:
                raise HTTPException(status_code=404, detail="Incident not found")

            deploy_ts = None
            if incident.get("suspected_deploy_id"):
                cur.execute(
                    "SELECT ts FROM deployments WHERE id=%s::uuid",
                    (str(incident["suspected_deploy_id"]),),
                )
                row = cur.fetchone()
                if row:
                    deploy_ts = row["ts"]

            center_ts = deploy_ts or incident["created_at"]
            since_ts = center_ts - timedelta(minutes=window_minutes)
            until_ts = center_ts + timedelta(minutes=window_minutes)

            cur.execute(
                """
                SELECT event_id::text AS event_id, topic, ts::text AS ts, source, tags_json, payload_json
                FROM events
                WHERE topic='marketplace.ops.github.deployment.v1'
                  AND ts BETWEEN %s AND %s
                ORDER BY ts ASC
                """,
                (since_ts, until_ts),
            )
            deploy_events = cur.fetchall()

            cur.execute(
                """
                SELECT event_id::text AS event_id, topic, ts::text AS ts, source, tags_json, payload_json
                FROM events
                WHERE topic='marketplace.ops.sentry.error_event.v1'
                  AND ts BETWEEN %s AND %s
                ORDER BY ts ASC
                """,
                (since_ts, until_ts),
            )
            error_events = cur.fetchall()

            cur.execute(
                """
                SELECT event_id::text AS event_id, topic, ts::text AS ts, source, tags_json, payload_json
                FROM events
                WHERE topic='marketplace.ops.incident.story.v1'
                  AND ts BETWEEN %s AND %s
                ORDER BY ts ASC
                """,
                (since_ts, until_ts),
            )
            story_events = cur.fetchall()

    write_audit(auth["id"], "incident_replay", "incident", {"incident_id": incident_id, "window_minutes": window_minutes})
    return {
        "incident_id": incident_id,
        "center_ts": center_ts.isoformat(),
        "window_minutes": window_minutes,
        "deploy_events": deploy_events,
        "error_events": error_events,
        "story_events": story_events,
    }


@app.post("/search/semantic")
def semantic_search(body: SearchBody, _auth: dict = Depends(require_key)) -> dict:
    collection = get_chroma_collection()
    result = collection.query(query_embeddings=[deterministic_embedding(body.query)], n_results=8)
    items = []
    for idx, doc in enumerate(result.get("documents", [[]])[0]):
        metadata = (result.get("metadatas", [[]])[0] or [{}])[idx]
        distance = (result.get("distances", [[]])[0] or [0.0])[idx]
        items.append({"snippet": doc, "metadata": metadata, "score": float(1.0 / (1.0 + distance))})
    return {"query": body.query, "results": items}


@app.post("/agent/recommend")
def agent_recommend(body: RecommendBody, auth: dict = Depends(require_key)) -> dict:
    search = semantic_search(SearchBody(query=body.goal), auth)
    top_results = search["results"][:3]
    topics: list[str] = [item["metadata"].get("topic", "") for item in top_results if item.get("metadata")]

    recent_activity: dict[str, dict[str, Any]] = {}
    if topics:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        topic,
                        COUNT(*) AS recent_event_count,
                        MAX(ts) AS last_event_ts
                    FROM events
                    WHERE topic = ANY(%s) AND ts > now() - interval '90 minutes'
                    GROUP BY topic
                    """,
                    (topics,),
                )
                for row in cur.fetchall():
                    recent_activity[row["topic"]] = {
                        "recent_event_count": int(row["recent_event_count"]),
                        "last_event_ts": row["last_event_ts"].isoformat(),
                    }

    recommendations = []
    for item in top_results:
        meta = item.get("metadata") or {}
        topic = meta.get("topic", "")
        stats = recent_activity.get(topic, {})
        recent_count = stats.get("recent_event_count", 0)
        has_recent = recent_count > 0
        # Slightly tighten the replay window when there is fresh activity
        replay_window = 20 if has_recent else 45
        recommendations.append(
            {
                "topic": topic,
                "score": item["score"],
                "replay_window_minutes": replay_window,
                "has_recent_events": has_recent,
                "recent_event_count": recent_count,
                "last_event_ts": stats.get("last_event_ts"),
                "subscribe_action": {"action": "subscribe", "topic": topic},
            }
        )

    write_audit(
        auth["id"],
        "agent_recommend",
        "semantic",
        {
            "goal": body.goal,
            "count": len(recommendations),
            "topics": topics,
        },
    )
    return {"goal": body.goal, "recommended_topics": recommendations}


@app.websocket("/ws/subscribe")
async def ws_subscribe(websocket: WebSocket, topic: str, api_key: str = Query(default="")):
    try:
        row = resolve_api_key(api_key)
        consume_rate_token(row["id"])
    except HTTPException:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO subscriptions (api_key_id, topic, status) VALUES (%s, %s, 'active')", (row["id"], topic))
        conn.commit()
    write_audit(row["id"], "subscribe_ws", topic, {"transport": "websocket"})
    ws_active_subscriptions.inc()
    cursor = datetime.now(UTC)
    try:
        while True:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if topic.endswith(">"):
                        cur.execute(
                            """
                            SELECT event_id::text AS event_id, topic, ts::text AS ts, source, tags_json, payload_json
                            FROM events WHERE topic LIKE %s AND ts > %s ORDER BY ts ASC LIMIT 200
                            """,
                            (topic[:-1] + "%", cursor),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT event_id::text AS event_id, topic, ts::text AS ts, source, tags_json, payload_json
                            FROM events WHERE topic=%s AND ts > %s ORDER BY ts ASC LIMIT 200
                            """,
                            (topic, cursor),
                        )
                    rows = cur.fetchall()
                    cur.execute(
                        "UPDATE subscriptions SET last_seen_at=now() WHERE api_key_id=%s AND topic=%s AND status='active'",
                        (row["id"], topic),
                    )
                conn.commit()
            for evt in rows:
                cursor = parse_iso(evt["ts"])
                await websocket.send_json(evt)
            await websocket.send_json({"type": "heartbeat", "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z")})
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    finally:
        ws_active_subscriptions.dec()


def _check_db() -> bool:
    try:
        with get_conn_for_health() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone() is not None
    except Exception:  # noqa: BLE001
        return False


def _check_chroma() -> bool:
    try:
        _ = get_chroma_collection()
        return True
    except Exception:  # noqa: BLE001
        return False


def _check_broker() -> bool:
    import socket
    host = os.getenv("SOLACE_HOST", "localhost")
    port = int(os.getenv("SOLACE_PORT", "1883"))
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


@app.get("/health")
def health() -> dict[str, Any]:
    health_timeout_seconds = 5  # cap total time so tests don't hang when services are down
    db_ok = False
    chroma_ok = False
    broker_ok = False

    def _run_checks() -> tuple[bool, bool, bool]:
        return _check_db(), _check_chroma(), _check_broker()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_checks)
        try:
            db_ok, chroma_ok, broker_ok = future.result(timeout=health_timeout_seconds)
        except (FuturesTimeout, Exception):  # noqa: BLE001
            db_ok, chroma_ok, broker_ok = False, False, False

    return {"status": "ok" if db_ok and chroma_ok and broker_ok else "degraded", "db": db_ok, "broker": broker_ok, "chroma": chroma_ok}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM events")
            events_ingested_total.set(cur.fetchone()["c"])
            cur.execute("SELECT COUNT(*) AS c FROM dlq_events")
            dlq_events_total.set(cur.fetchone()["c"])
            cur.execute("SELECT COUNT(*) AS c FROM audit_logs WHERE action LIKE 'webhook_%'")
            webhooks_received_total.set(cur.fetchone()["c"])
            cur.execute("SELECT COUNT(*) AS c FROM stories")
            stories_generated_total.set(cur.fetchone()["c"])
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)
