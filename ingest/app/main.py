import hashlib
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import psycopg
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from jsonschema import ValidationError, validate
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from app.security import verify_github_signature, verify_sentry_token

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://signalhub:signalhub@localhost:5432/signalhub",
).replace("postgresql+psycopg://", "postgresql://")
SOLACE_HOST = os.getenv("SOLACE_HOST", "localhost")
SOLACE_PORT = int(os.getenv("SOLACE_PORT", "1883"))
SOLACE_USERNAME = os.getenv("SOLACE_USERNAME", "admin")
SOLACE_PASSWORD = os.getenv("SOLACE_PASSWORD", "admin")
GITHUB_WEBHOOK_SECRET = (os.getenv("GITHUB_WEBHOOK_SECRET", "") or "").strip()
SENTRY_WEBHOOK_TOKEN = (os.getenv("SENTRY_WEBHOOK_TOKEN", "") or "").strip()
ASYNCAPI_DIR = Path(os.getenv("ASYNCAPI_DIR", "/app/shared/asyncapi"))

TOPIC_GITHUB = "marketplace.ops.github.deployment.v1"
TOPIC_SENTRY = "marketplace.ops.sentry.error_event.v1"

webhooks_received_total = Counter(
    "webhooks_received_total",
    "Total webhooks received by source",
    ["source"],
)
webhook_errors_total = Counter(
    "webhook_errors_total",
    "Total webhook processing errors by source",
    ["source"],
)
dlq_events_total = Counter(
    "dlq_events_total",
    "Total events sent to DLQ by source",
    ["source"],
)

MQTT_CLIENT: mqtt.Client | None = None
SCHEMAS: dict[str, dict[str, Any]] = {}


def get_conn() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


def ensure_tables() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
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
                """
            )
        conn.commit()


def load_schemas() -> dict[str, dict[str, Any]]:
    schema_map: dict[str, dict[str, Any]] = {}
    for file_path in ASYNCAPI_DIR.glob("*.json"):
        doc = json.loads(file_path.read_text(encoding="utf-8"))
        schema = doc.get("components", {}).get("schemas", {}).get("EventEnvelope")
        for channel_name in doc.get("channels", {}).keys():
            if schema:
                schema_map[channel_name] = schema
    return schema_map


def validate_envelope(topic: str, envelope: dict[str, Any]) -> None:
    schema = SCHEMAS.get(topic)
    if not schema:
        raise ValueError(f"No schema found for topic: {topic}")
    validate(instance=envelope, schema=schema)


def publish(topic: str, payload: dict[str, Any]) -> None:
    if not MQTT_CLIENT:
        raise RuntimeError("MQTT client unavailable")
    rc = MQTT_CLIENT.publish(topic, json.dumps(payload), qos=1).rc
    if rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"MQTT publish failed with rc={rc}")


def dlq(topic: str, payload: dict[str, Any], err: str, source: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dlq_events (event_id, topic, reason, payload)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (
                    str(uuid.uuid4()),
                    topic,
                    err[:1000],
                    json.dumps(payload),
                ),
            )
        conn.commit()
    dlq_events_total.labels(source=source).inc()


def parse_github_event(raw: dict[str, Any], event_type: str) -> dict[str, Any] | None:
    if event_type not in {"push", "deployment", "deployment_status", "workflow_run"}:
        return None
    repo = ((raw.get("repository") or {}).get("full_name")) or "unknown/repo"
    ref = str(raw.get("ref") or "")
    deployment = raw.get("deployment") or {}
    deployment_status = raw.get("deployment_status") or {}
    workflow_run = raw.get("workflow_run") or {}
    env = (
        deployment.get("environment")
        or deployment_status.get("environment")
        or workflow_run.get("environment")
        or (ref.split("/")[-1] if ref.startswith("refs/heads/") else "")
    )
    commit = (
        raw.get("after")
        or (raw.get("head_commit") or {}).get("id")
        or deployment.get("sha")
        or workflow_run.get("head_sha")
        or ""
    )
    deploy_id = str(
        deployment.get("id")
        or deployment_status.get("deployment", {}).get("id")
        or workflow_run.get("id")
        or ""
    )
    ts = (
        deployment_status.get("created_at")
        or raw.get("deployment", {}).get("created_at")
        or (raw.get("head_commit") or {}).get("timestamp")
        or workflow_run.get("updated_at")
        or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )
    tags = {
        "repo": repo,
        "env": env,
        "service": repo.split("/")[-1],
        "release": raw.get("release", {}).get("tag_name") or "",
        "deploy_id": deploy_id,
        "commit": commit,
    }
    return {
        "event_id": str(uuid.uuid4()),
        "ts": ts,
        "source": "github",
        "topic": TOPIC_GITHUB,
        "tags": tags,
        "payload": {"event_type": event_type, **raw},
    }


def parse_sentry_event(raw: dict[str, Any]) -> dict[str, Any]:
    data = raw.get("data") or raw
    issue = data.get("issue") or {}
    event = data.get("event") or {}
    entry_data = {}
    entries = event.get("entries") or []
    if entries:
        entry_data = (entries[0] or {}).get("data") or {}
    exception_values = ((entry_data.get("values") or [{}])[0]) if entry_data else {}
    stack_frames = ((exception_values.get("stacktrace") or {}).get("frames") or [])
    top_frame = stack_frames[-1] if stack_frames else {}
    stacktrace_summary = ""
    if top_frame:
        stacktrace_summary = (
            f"{top_frame.get('filename', 'unknown')}:{top_frame.get('function', 'unknown')}:"
            f"{top_frame.get('lineno', 'unknown')}"
        )

    project = (data.get("project") or {}).get("slug") or raw.get("project") or "unknown"
    env = event.get("environment") or "unknown"
    release = event.get("release") or issue.get("shortId") or ""
    fingerprint = (
        ((event.get("fingerprint") or [None])[0])
        or (issue.get("metadata") or {}).get("value")
        or str(issue.get("id") or uuid.uuid4())
    )
    message = (
        event.get("message")
        or (exception_values.get("value") if exception_values else None)
        or (issue.get("metadata") or {}).get("value")
        or (issue.get("title") or "Sentry error")
    )
    title = issue.get("title") or (issue.get("metadata") or {}).get("title") or "Sentry issue"
    culprit = issue.get("culprit") or event.get("culprit") or ""
    ts = event.get("timestamp") or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    tags = {
        "env": str(env),
        "service": str(project),
        "release": str(release),
        "fingerprint": str(fingerprint),
    }
    return {
        "event_id": str(uuid.uuid4()),
        "ts": ts,
        "source": "sentry",
        "topic": TOPIC_SENTRY,
        "tags": tags,
        "payload": {
            "project": project,
            "level": event.get("level") or "error",
            "title": title,
            "message": message,
            "culprit": culprit,
            "stacktrace_summary": stacktrace_summary,
            "issue_id": issue.get("id"),
            "raw": raw,
        },
    }


def _connect_mqtt_with_retries(max_attempts: int = 10, delay_seconds: float = 2.0) -> None:
    import time
    last: Exception | None = None
    for attempt in range(max_attempts):
        try:
            MQTT_CLIENT.connect(SOLACE_HOST, SOLACE_PORT, 60)
            return
        except OSError as e:
            last = e
            if attempt < max_attempts - 1:
                time.sleep(delay_seconds)
    raise last  # type: ignore[misc]


@asynccontextmanager
async def lifespan(_: FastAPI):
    global MQTT_CLIENT, SCHEMAS
    ensure_tables()
    SCHEMAS = load_schemas()
    trace.set_tracer_provider(TracerProvider())
    MQTT_CLIENT = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="signalhub-ingest")
    MQTT_CLIENT.username_pw_set(SOLACE_USERNAME, SOLACE_PASSWORD)
    _connect_mqtt_with_retries()
    MQTT_CLIENT.loop_start()
    yield
    if MQTT_CLIENT:
        MQTT_CLIENT.loop_stop()
        MQTT_CLIENT.disconnect()


app = FastAPI(title="signalhub-ingest", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)


@app.post("/webhooks/github")
async def ingest_github(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> dict[str, str]:
    webhooks_received_total.labels(source="github").inc()
    body = await request.body()
    ok, reason = verify_github_signature(GITHUB_WEBHOOK_SECRET, body, x_hub_signature_256)
    if not ok:
        logging.warning("github webhook 401: %s (secret_set=%s)", reason, bool((GITHUB_WEBHOOK_SECRET or "").strip()))
        webhook_errors_total.labels(source="github").inc()
        raise HTTPException(status_code=401, detail="Invalid GitHub signature")

    raw = json.loads(body.decode("utf-8") or "{}")
    envelope = parse_github_event(raw, x_github_event or "")
    if envelope is None:
        return {"status": "ignored", "reason": "event_not_supported"}

    try:
        validate_envelope(TOPIC_GITHUB, envelope)
        publish(TOPIC_GITHUB, envelope)
    except (ValidationError, Exception) as exc:  # noqa: BLE001
        webhook_errors_total.labels(source="github").inc()
        dlq(TOPIC_GITHUB, envelope, str(exc), source="github")
        raise HTTPException(status_code=400, detail=f"Failed to ingest GitHub event: {exc}") from exc
    return {"status": "ok", "source": "github", "topic": TOPIC_GITHUB}


@app.post("/webhooks/sentry")
async def ingest_sentry(
    request: Request,
    x_sentry_token: str | None = Header(default=None),
) -> dict[str, str]:
    webhooks_received_total.labels(source="sentry").inc()
    if not verify_sentry_token(SENTRY_WEBHOOK_TOKEN, x_sentry_token):
        webhook_errors_total.labels(source="sentry").inc()
        raise HTTPException(status_code=401, detail="Invalid Sentry token")
    raw = await request.json()
    envelope = parse_sentry_event(raw)
    try:
        validate_envelope(TOPIC_SENTRY, envelope)
        publish(TOPIC_SENTRY, envelope)
    except (ValidationError, Exception) as exc:  # noqa: BLE001
        webhook_errors_total.labels(source="sentry").inc()
        dlq(TOPIC_SENTRY, envelope, str(exc), source="sentry")
        raise HTTPException(status_code=400, detail=f"Failed to ingest Sentry event: {exc}") from exc
    return {"status": "ok", "source": "sentry", "topic": TOPIC_SENTRY}


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "signalhub-ingest",
        "docs": "Use /health to check readiness. Webhooks: POST /webhooks/github, POST /webhooks/sentry.",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)
