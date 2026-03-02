import hashlib
import json
import os
import time
from datetime import datetime

import chromadb
import paho.mqtt.client as mqtt
import psycopg
from psycopg.rows import dict_row


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
    dsn = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://marketplace:marketplace@localhost:5432/marketplace",
    ).replace("postgresql+psycopg://", "postgresql://")
    return psycopg.connect(dsn, row_factory=dict_row)


def get_collection() -> chromadb.Collection:
    client = chromadb.HttpClient(
        host=os.getenv("CHROMA_HOST", "localhost"),
        port=int(os.getenv("CHROMA_PORT", "8001")),
    )
    return client.get_or_create_collection("topic_index")


def ensure_tables() -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
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
                """
            )
        conn.commit()


def text_for_embedding(event: dict, topic_meta: dict | None) -> str:
    topic_desc = (topic_meta or {}).get("description", "")
    tags = " ".join((topic_meta or {}).get("tags", []))
    payload_keys = " ".join(event.get("payload", {}).keys())
    source = event.get("source", "")
    return f"{event['topic']} {topic_desc} {tags} {payload_keys} {source}"


def upsert_event(event: dict, collection: chromadb.Collection) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO events (event_id, topic, ts, source, tags, payload, raw_event)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING id
                """,
                (
                    event["event_id"],
                    event["topic"],
                    datetime.fromisoformat(event["ts"].replace("Z", "+00:00")),
                    event["source"],
                    json.dumps(event.get("tags", {})),
                    json.dumps(event.get("payload", {})),
                    json.dumps(event),
                ),
            )
            inserted = cur.fetchone()
            if not inserted:
                conn.commit()
                return

            cur.execute("SELECT name, description, tags FROM topics WHERE name=%s", (event["topic"],))
            topic_meta = cur.fetchone()
        conn.commit()

    embed_text = text_for_embedding(event, topic_meta)
    collection.upsert(
        ids=[event["event_id"]],
        embeddings=[deterministic_embedding(embed_text)],
        documents=[embed_text],
        metadatas=[
            {
                "topic": event["topic"],
                "ts": event["ts"],
                "source": event["source"],
            }
        ],
    )


def on_connect(client: mqtt.Client, userdata: object, flags: object, reason_code: object, properties: object = None) -> None:
    # paho v2 may pass ReasonCode objects; compare string form safely.
    if str(reason_code) == "Success":
        client.subscribe("marketplace.weather.current_conditions.v1", qos=1)
        client.subscribe("marketplace.crypto.price_updated.v1", qos=1)


def main() -> None:
    ensure_tables()
    collection = get_collection()

    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "marketplace-indexer")
    mqtt_client.username_pw_set(
        os.getenv("SOLACE_USERNAME", "admin"),
        os.getenv("SOLACE_PASSWORD", "admin"),
    )

    def _on_message(_: mqtt.Client, __: object, msg: mqtt.MQTTMessage) -> None:
        try:
            event = json.loads(msg.payload.decode("utf-8"))
            upsert_event(event, collection)
            print(json.dumps({"level": "info", "message": "indexed event", "event_id": event["event_id"]}))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"level": "error", "message": "indexer failed", "error": str(exc)}))

    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = _on_message

    solace_host = os.getenv("SOLACE_HOST", "localhost")
    solace_port = int(os.getenv("SOLACE_PORT", "1883"))
    for attempt in range(1, 31):
        try:
            mqtt_client.connect(solace_host, solace_port, 60)
            print(json.dumps({"level": "info", "message": "Connected to Solace MQTT"}))
            break
        except (ConnectionRefusedError, OSError) as exc:
            print(json.dumps({"level": "warning", "message": f"Solace not ready (attempt {attempt}/30)", "error": str(exc)}))
            time.sleep(5)
    else:
        raise ConnectionError(f"Could not connect to Solace at {solace_host}:{solace_port} after 30 attempts")

    mqtt_client.loop_start()

    while True:
        time.sleep(5)


if __name__ == "__main__":
    main()
