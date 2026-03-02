"""
Config-driven connector runner.

Reads enabled connectors from the Postgres `connectors` table and runs each in
its own thread.  Falls back to creating / seeding the table if it doesn't
exist yet (so the runner is resilient to startup ordering).
"""

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

from common import SolacePublisher, ensure_dlq_table, log_json, publish_with_retry

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _dsn() -> str:
    raw = os.getenv("DATABASE_URL", "postgresql+psycopg://marketplace:marketplace@localhost:5432/marketplace")
    return raw.replace("postgresql+psycopg://", "postgresql://")


def get_db() -> psycopg.Connection:
    return psycopg.connect(_dsn(), row_factory=dict_row)


def ensure_connectors_table() -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS connectors (
                    id                    BIGSERIAL PRIMARY KEY,
                    name                  TEXT NOT NULL UNIQUE,
                    connector_type        TEXT NOT NULL,
                    topic                 TEXT NOT NULL,
                    poll_interval_seconds INT NOT NULL DEFAULT 25,
                    source_config_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
                    enabled               BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                INSERT INTO connectors (name, connector_type, topic, poll_interval_seconds, source_config_json, enabled)
                VALUES
                    ('weather-berlin', 'weather', 'marketplace.weather.current_conditions.v1', 25,
                     '{"latitude":"52.52","longitude":"13.41"}'::jsonb, TRUE),
                    ('crypto-btc-usd', 'crypto', 'marketplace.crypto.price_updated.v1', 25,
                     '{"product_id":"BTC-USD"}'::jsonb, TRUE)
                ON CONFLICT (name) DO NOTHING
                """
            )
        conn.commit()


def load_connectors() -> list[dict]:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM connectors WHERE enabled = TRUE")
            return cur.fetchall()


# ---------------------------------------------------------------------------
# Fetch functions per connector type
# ---------------------------------------------------------------------------

FETCHERS: dict[str, Any] = {}


def _fetch_weather(config: dict, client: httpx.Client) -> tuple[str, dict, dict]:
    """Returns (source, tags, payload)."""
    lat = config.get("latitude", "52.52")
    lon = config.get("longitude", "13.41")
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,wind_speed_10m,wind_direction_10m,weather_code,is_day"
    )
    resp = client.get(url)
    resp.raise_for_status()
    current = resp.json()["current"]
    return (
        "open-meteo",
        {"geo": f"{lat},{lon}", "entity": "weather"},
        {
            "temperature_c": current["temperature_2m"],
            "windspeed_kmh": current["wind_speed_10m"],
            "winddirection_deg": current["wind_direction_10m"],
            "weathercode": current["weather_code"],
            "is_day": current["is_day"],
        },
    )


def _fetch_crypto(config: dict, client: httpx.Client) -> tuple[str, dict, dict]:
    product_id = config.get("product_id", "BTC-USD")
    url = f"https://api.coinbase.com/v2/prices/{product_id}/spot"
    resp = client.get(url)
    resp.raise_for_status()
    data = resp.json()
    return (
        "coinbase",
        {"entity": product_id},
        {
            "product_id": product_id,
            "price": float(data["data"]["amount"]),
            "currency": data["data"]["currency"],
        },
    )


FETCHERS["weather"] = _fetch_weather
FETCHERS["crypto"] = _fetch_crypto


# ---------------------------------------------------------------------------
# Per-connector loop
# ---------------------------------------------------------------------------

def run_connector(connector: dict) -> None:
    name = connector["name"]
    ctype = connector["connector_type"]
    topic = connector["topic"]
    interval = connector["poll_interval_seconds"]
    config = connector["source_config_json"]

    fetch_fn = FETCHERS.get(ctype)
    if not fetch_fn:
        log_json("error", f"Unknown connector type: {ctype}", connector=name)
        return

    publisher = SolacePublisher()

    with httpx.Client(timeout=10.0) as http_client:
        while True:
            try:
                source, tags, payload = fetch_fn(config, http_client)
                event = {
                    "event_id": str(uuid.uuid4()),
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "source": source,
                    "topic": topic,
                    "tags": tags,
                    "payload": payload,
                }
                publish_with_retry(publisher, topic, event)
                log_json("info", "event published", connector=name, event_id=event["event_id"], topic=topic)
            except Exception as exc:  # noqa: BLE001
                log_json("error", "connector error", connector=name, topic=topic, error=str(exc))
            time.sleep(interval)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    from common import setup_logging

    setup_logging()
    ensure_dlq_table()
    ensure_connectors_table()

    connectors = []
    for _attempt in range(30):
        connectors = load_connectors()
        if connectors:
            break
        log_json("info", "Waiting for connectors rows …")
        time.sleep(2)

    if not connectors:
        log_json("warning", "No enabled connectors found – exiting")
        return

    log_json("info", f"Starting {len(connectors)} connector(s)", names=[c["name"] for c in connectors])

    with ThreadPoolExecutor(max_workers=len(connectors)) as pool:
        futures = [pool.submit(run_connector, c) for c in connectors]
        for f in futures:
            f.result()


if __name__ == "__main__":
    main()
