import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.db import (
    check_rate_limit,
    get_conn,
    increment_usage,
    resolve_api_key,
    write_audit,
)
from app.core.metrics import ws_active_subscriptions

router = APIRouter(tags=["ws"])


@router.websocket("/ws/subscribe")
async def ws_subscribe(websocket: WebSocket, topic: str) -> None:
    api_key = websocket.headers.get("X-API-Key") or websocket.query_params.get("api_key")
    auth = resolve_api_key(api_key or "")
    if not auth:
        await websocket.accept()
        await websocket.send_json({"error": "Invalid API key"})
        await websocket.close(code=1008, reason="Invalid API key")
        return

    if check_rate_limit(auth["api_key_id"]):
        await websocket.accept()
        await websocket.send_json({"error": "Rate limit exceeded"})
        await websocket.close(code=1008, reason="Rate limit exceeded")
        return

    increment_usage(auth["api_key_id"], topic)

    # Subscription gating: auto-create ACTIVE subscription on connect,
    # reject if an existing subscription for this topic is PAUSED.
    if auth["user_id"] is not None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, status FROM subscriptions WHERE user_id=%s AND topic=%s ORDER BY id DESC LIMIT 1",
                    (auth["user_id"], topic),
                )
                sub = cur.fetchone()
                if sub:
                    if sub["status"] != "ACTIVE":
                        await websocket.accept()
                        await websocket.send_json({"error": "Subscription is paused"})
                        await websocket.close(code=1008, reason="Subscription is paused")
                        return
                else:
                    cur.execute(
                        "INSERT INTO subscriptions (user_id, topic) VALUES (%s, %s)",
                        (auth["user_id"], topic),
                    )
            conn.commit()

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
