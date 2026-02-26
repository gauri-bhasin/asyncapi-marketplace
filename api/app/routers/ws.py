import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.db import get_conn, validate_api_key
from app.core.metrics import ws_active_subscriptions


router = APIRouter(tags=["ws"])


def write_audit(action: str, details: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_logs (action, details) VALUES (%s, %s::jsonb)",
                (action, json.dumps(details)),
            )
        conn.commit()


@router.websocket("/ws/subscribe")
async def ws_subscribe(websocket: WebSocket, topic: str) -> None:
    api_key = websocket.headers.get("X-API-Key") or websocket.query_params.get("api_key")
    if not validate_api_key(api_key or ""):
        await websocket.close(code=1008, reason="Invalid API key")
        return

    await websocket.accept()
    ws_active_subscriptions.inc()
    write_audit("ws_subscribe", {"topic": topic, "ts": datetime.now(timezone.utc).isoformat()})

    last_seen_id = 0
    try:
        while True:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, event_id, ts, source, topic, tags, payload
                        FROM events
                        WHERE topic=%s AND id > %s
                        ORDER BY id ASC
                        LIMIT 200
                        """,
                        (topic, last_seen_id),
                    )
                    rows = cur.fetchall()
            for row in rows:
                last_seen_id = row["id"]
                await websocket.send_json(
                    {
                        "event_id": row["event_id"],
                        "ts": row["ts"].isoformat(),
                        "source": row["source"],
                        "topic": row["topic"],
                        "tags": row["tags"],
                        "payload": row["payload"],
                    }
                )
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        ws_active_subscriptions.dec()
        write_audit("ws_unsubscribe", {"topic": topic, "ts": datetime.now(timezone.utc).isoformat()})
