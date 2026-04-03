import hashlib
import json
import os
import time
import logging
from datetime import datetime
from uuid import UUID, uuid5, NAMESPACE_DNS

import chromadb
import paho.mqtt.client as mqtt
import psycopg
from chromadb.config import Settings as ChromaSettings
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from prometheus_client import Counter, start_http_server
from psycopg.rows import dict_row

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://signalhub:signalhub@localhost:5432/signalhub",
).replace("postgresql+psycopg://", "postgresql://")
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8001"))
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

events_ingested_total = Counter("events_ingested_total", "Total events ingested into Postgres")
chroma_upserts_total = Counter("chroma_upserts_total", "Total vector upserts into Chroma")


def deterministic_embedding(text: str, dim: int = 128) -> list[float]:
    values = [0.0] * dim
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = digest[0] % dim
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        values[idx] += sign * (1.0 + digest[2] / 255.0)
    norm = sum(v * v for v in values) ** 0.5
    return [v / norm for v in values] if norm else values


def get_db() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def get_collection() -> chromadb.Collection:
    client = chromadb.HttpClient(
        host=CHROMA_HOST,
        port=CHROMA_PORT,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection("signalhub_index")


def ensure_schema() -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS topics (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
                    asyncapi_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    sample_event_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
                """
            )
        conn.commit()


def topic_meta(topic: str) -> dict:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name, description, tags FROM topics WHERE name=%s", (topic,))
            return cur.fetchone() or {}


def embedding_text(event: dict, meta: dict) -> str:
    tags = event.get("tags", {})
    payload = event.get("payload", {})
    topic_tags = " ".join(meta.get("tags") or [])
    payload_text = " ".join(
        str(payload.get(k, "")) for k in ["commit", "message", "fingerprint", "repo", "env", "story_text"]
    )
    return f"{event.get('topic', '')} {meta.get('description', '')} {topic_tags} {tags} {payload_text}"


def maybe_insert_deployment(cur: psycopg.Cursor, event: dict) -> None:
    if event.get("topic") != "marketplace.ops.github.deployment.v1":
        return
    tags = event.get("tags", {})
    deploy_ref = str(tags.get("deploy_id", event["event_id"]))
    try:
        deployment_id = str(UUID(deploy_ref))
    except ValueError:
        deployment_id = str(uuid5(NAMESPACE_DNS, deploy_ref))
    cur.execute(
        """
        INSERT INTO deployments (id, repo, env, commit, deploy_ref, ts, raw_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (id) DO NOTHING
        """,
        (
            deployment_id,
            tags.get("repo", "unknown/repo"),
            tags.get("env", "unknown"),
            tags.get("commit", ""),
            deploy_ref,
            datetime.fromisoformat(event["ts"].replace("Z", "+00:00")),
            json.dumps(event),
        ),
    )


def handle_event(event: dict, collection: chromadb.Collection) -> None:
    payload_hash = hashlib.sha256(
        json.dumps(event.get("payload", {}), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO events (event_id, topic, ts, source, tags_json, payload_json, payload_hash)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING event_id
                """,
                (
                    event["event_id"],
                    event["topic"],
                    datetime.fromisoformat(event["ts"].replace("Z", "+00:00")),
                    event["source"],
                    json.dumps(event.get("tags", {})),
                    json.dumps(event.get("payload", {})),
                    payload_hash,
                ),
            )
            inserted = cur.fetchone()
            if not inserted:
                conn.commit()
                return
            maybe_insert_deployment(cur, event)
        conn.commit()

    meta = topic_meta(event["topic"])
    text = embedding_text(event, meta)
    tags = event.get("tags", {})
    collection.upsert(
        ids=[event["event_id"]],
        embeddings=[deterministic_embedding(text)],
        documents=[text],
        metadatas=[
            {
                "topic": event["topic"],
                "ts": event["ts"],
                "source": event["source"],
                "repo": str(tags.get("repo", "")),
                "env": str(tags.get("env", "")),
                "deploy_id": str(tags.get("deploy_id", "")),
                "fingerprint": str(tags.get("fingerprint", "")),
            }
        ],
    )
    events_ingested_total.inc()
    chroma_upserts_total.inc()


def on_connect(client: mqtt.Client, _userdata: object, _flags: object, reason_code: object, _properties: object = None) -> None:
    if str(reason_code) == "Success":
        # MQTT wildcards are slash-based; subscribe all and filter in storage query paths.
        client.subscribe("#", qos=1)


def main() -> None:
    ensure_schema()
    trace.set_tracer_provider(TracerProvider())
    start_http_server(9102)
    collection = get_collection()

    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="signalhub-indexer")
    mqtt_client.username_pw_set(os.getenv("SOLACE_USERNAME", "admin"), os.getenv("SOLACE_PASSWORD", "admin"))
    mqtt_client.on_connect = on_connect

    def _on_message(_: mqtt.Client, __: object, msg: mqtt.MQTTMessage) -> None:
        try:
            event = json.loads(msg.payload.decode("utf-8"))
            handle_event(event, collection)
            print(json.dumps({"level": "info", "message": "indexed event", "event_id": event.get("event_id")}))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"level": "error", "message": "indexer failed", "error": str(exc)}))

    mqtt_client.on_message = _on_message

    host = os.getenv("SOLACE_HOST", "localhost")
    port = int(os.getenv("SOLACE_PORT", "1883"))
    for attempt in range(1, 31):
        try:
            mqtt_client.connect(host, port, 60)
            break
        except (ConnectionRefusedError, OSError) as exc:
            print(json.dumps({"level": "warning", "message": f"Solace not ready ({attempt}/30)", "error": str(exc)}))
            time.sleep(3)
    else:
        raise ConnectionError(f"Could not connect to Solace at {host}:{port}")

    mqtt_client.loop_start()
    while True:
        time.sleep(3)


if __name__ == "__main__":
    main()
