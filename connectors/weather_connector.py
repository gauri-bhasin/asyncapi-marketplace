import random
import time
import uuid
from datetime import datetime, timezone

import httpx

from common import SolacePublisher, log_json, publish_with_retry


TOPIC = "marketplace.weather.current_conditions.v1"


def build_event(data: dict, lat: str, lon: str) -> dict:
    current = data["current"]
    return {
        "event_id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": "open-meteo",
        "topic": TOPIC,
        "tags": {"geo": f"{lat},{lon}", "entity": "weather"},
        "payload": {
            "temperature_c": current["temperature_2m"],
            "windspeed_kmh": current["wind_speed_10m"],
            "winddirection_deg": current["wind_direction_10m"],
            "weathercode": current["weather_code"],
            "is_day": current["is_day"],
        },
    }


def run() -> None:
    lat = "52.52"
    lon = "13.41"
    publisher = SolacePublisher()
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,wind_speed_10m,wind_direction_10m,weather_code,is_day"
    )

    with httpx.Client(timeout=10.0) as client:
        while True:
            try:
                resp = client.get(url)
                resp.raise_for_status()
                event = build_event(resp.json(), lat, lon)
                publish_with_retry(publisher, TOPIC, event)
                log_json("info", "weather event published", event_id=event["event_id"], topic=TOPIC)
            except Exception as exc:  # noqa: BLE001
                log_json("error", "weather connector error", topic=TOPIC, error=str(exc))
            time.sleep(random.randint(20, 30))
