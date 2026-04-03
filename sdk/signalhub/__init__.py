import json
import threading
from datetime import datetime
from urllib.parse import quote

import requests
import websocket


class Agent:
    def __init__(self, api_key: str, base_url: str = "http://localhost:8000") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key, "Content-Type": "application/json"}

    def discover(self, query: str) -> dict:
        resp = requests.post(
            f"{self.base_url}/search/semantic",
            headers=self._headers(),
            json={"query": query},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def replay(self, topic: str, since: str, until: str) -> list[dict]:
        url = (
            f"{self.base_url}/topics/{quote(topic, safe='')}/replay"
            f"?since={quote(since, safe='')}&until={quote(until, safe='')}"
        )
        resp = requests.get(url, headers=self._headers(), timeout=20)
        resp.raise_for_status()
        return resp.json()

    def subscribe(self, topic: str, on_event) -> websocket.WebSocketApp:
        ws_base = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_base}/ws/subscribe?topic={quote(topic, safe='')}&api_key={quote(self.api_key, safe='')}"

        def _on_message(_ws, message: str) -> None:
            payload = json.loads(message)
            if payload.get("type") == "heartbeat":
                return
            on_event(payload)

        app = websocket.WebSocketApp(ws_url, on_message=_on_message)
        thread = threading.Thread(target=app.run_forever, daemon=True)
        thread.start()
        return app


__all__ = ["Agent", "datetime"]
