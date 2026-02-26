import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import psycopg
from jsonschema import validate


ASYNCAPI_DIR = Path("/app/shared/asyncapi")

TOPIC_TO_FILE = {
    "marketplace.weather.current_conditions.v1": "weather_current_conditions.v1.json",
    "marketplace.crypto.price_updated.v1": "crypto_price_updated.v1.json",
}


def setup_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(message)s",
    )


def log_json(level: str, message: str, **kwargs: Any) -> None:
    payload = {"level": level, "message": message, "ts": utc_now_iso(), **kwargs}
    getattr(logging, level.lower())(json.dumps(payload))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_schema(topic: str) -> dict[str, Any]:
    file_name = TOPIC_TO_FILE[topic]
    spec_path = ASYNCAPI_DIR / file_name
    with spec_path.open("r", encoding="utf-8") as handle:
        doc = json.load(handle)
    schema_name = "EventEnvelopeWeather" if "weather" in topic else "EventEnvelopeCrypto"
    return doc["components"]["schemas"][schema_name]


def validate_event(topic: str, event: dict[str, Any]) -> None:
    schema = load_schema(topic)
    validate(instance=event, schema=schema)


class SolacePublisher:
    def __init__(self) -> None:
        self.host = os.getenv("SOLACE_HOST", "localhost")
        self.port = int(os.getenv("SOLACE_PORT", "1883"))
        self.username = os.getenv("SOLACE_USERNAME", "admin")
        self.password = os.getenv("SOLACE_PASSWORD", "admin")
        self.client_id = f"connector-{uuid.uuid4()}"
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, self.client_id)
        self.client.username_pw_set(self.username, self.password)
        self.client.connect(self.host, self.port, keepalive=60)
        self.client.loop_start()

    def publish(self, topic: str, event: dict[str, Any]) -> None:
        payload = json.dumps(event)
        info = self.client.publish(topic=topic, payload=payload, qos=1)
        info.wait_for_publish()
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"publish failed rc={info.rc}")


def get_db() -> psycopg.Connection:
    db_url = os.getenv("DATABASE_URL", "postgresql+psycopg://marketplace:marketplace@localhost:5432/marketplace")
    # psycopg doesn't accept sqlalchemy-style prefix.
    dsn = db_url.replace("postgresql+psycopg://", "postgresql://")
    return psycopg.connect(dsn)


def ensure_dlq_table() -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
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


def write_dlq(event: dict[str, Any], reason: str) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dlq_events (event_id, topic, reason, payload)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (
                    event.get("event_id"),
                    event.get("topic", "unknown"),
                    reason,
                    json.dumps(event),
                ),
            )
        conn.commit()


def publish_with_retry(publisher: SolacePublisher, topic: str, event: dict[str, Any], max_attempts: int = 3) -> None:
    last_error: Exception | None = None
    for _ in range(max_attempts):
        try:
            validate_event(topic, event)
            publisher.publish(topic, event)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1)
    write_dlq(event, reason=str(last_error))
    log_json("error", "event sent to dlq", topic=topic, event_id=event.get("event_id"), error=str(last_error))
