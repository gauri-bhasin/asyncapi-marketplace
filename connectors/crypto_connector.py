import os
import random
import time
import uuid
from datetime import datetime, timezone

import httpx

from common import SolacePublisher, log_json, publish_with_retry


TOPIC = "marketplace.crypto.price_updated.v1"


def build_event(data: dict, product_id: str) -> dict:
    amount = float(data["data"]["amount"])
    currency = data["data"]["currency"]
    return {
        "event_id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": "coinbase",
        "topic": TOPIC,
        "tags": {"entity": product_id},
        "payload": {
            "product_id": product_id,
            "price": amount,
            "currency": currency,
        },
    }


def run() -> None:
    product_id = os.getenv("CRYPTO_PRODUCT_ID", "BTC-USD")
    publisher = SolacePublisher()
    url = f"https://api.coinbase.com/v2/prices/{product_id}/spot"

    with httpx.Client(timeout=10.0) as client:
        while True:
            try:
                resp = client.get(url)
                resp.raise_for_status()
                event = build_event(resp.json(), product_id)
                publish_with_retry(publisher, TOPIC, event)
                log_json("info", "crypto event published", event_id=event["event_id"], topic=TOPIC)
            except Exception as exc:  # noqa: BLE001
                log_json("error", "crypto connector error", topic=TOPIC, error=str(exc))
            time.sleep(random.randint(20, 30))
