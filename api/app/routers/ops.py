import json
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import require_api_key
from app.core.config import settings
from app.core.db import get_conn, write_audit

router = APIRouter(tags=["ops"], dependencies=[Depends(require_api_key)])


# ---------------------------------------------------------------------------
# DLQ
# ---------------------------------------------------------------------------

@router.get("/ops/dlq")
def list_dlq(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default="all"),
) -> dict:
    where = ""
    if status == "pending":
        where = "WHERE replayed = FALSE"
    elif status == "replayed":
        where = "WHERE replayed = TRUE"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS total FROM dlq_events {where}")
            total = cur.fetchone()["total"]

            cur.execute(
                f"""
                SELECT id, event_id, topic, reason, payload, created_at, replayed, replayed_at
                FROM dlq_events
                {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cur.fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": r["id"],
                "event_id": r["event_id"],
                "topic": r["topic"],
                "reason": r["reason"],
                "payload": r["payload"],
                "created_at": r["created_at"].isoformat(),
                "replayed": r["replayed"],
                "replayed_at": r["replayed_at"].isoformat() if r["replayed_at"] else None,
            }
            for r in rows
        ],
    }


@router.post("/ops/dlq/{dlq_id}/replay")
def replay_dlq(dlq_id: int) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, event_id, topic, payload, replayed FROM dlq_events WHERE id=%s",
                (dlq_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="DLQ event not found")
            if row["replayed"]:
                raise HTTPException(status_code=409, detail="Already replayed")

    event_payload = row["payload"]
    if not event_payload.get("event_id"):
        event_payload["event_id"] = str(uuid.uuid4())
    if not event_payload.get("ts"):
        event_payload["ts"] = datetime.now(timezone.utc).isoformat()

    _publish_to_solace(row["topic"], event_payload)

    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE dlq_events SET replayed=TRUE, replayed_at=%s WHERE id=%s",
                (now, dlq_id),
            )
        conn.commit()

    write_audit("dlq_replayed", {"dlq_id": dlq_id, "topic": row["topic"]})
    return {"status": "replayed", "dlq_id": dlq_id, "topic": row["topic"]}


def _publish_to_solace(topic: str, payload: dict) -> None:
    client_id = f"api-replay-{uuid.uuid4()}"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)
    client.username_pw_set(settings.solace_username, settings.solace_password)
    client.connect(settings.solace_host, settings.solace_port, keepalive=10)
    client.loop_start()
    try:
        info = client.publish(topic=topic, payload=json.dumps(payload), qos=1)
        info.wait_for_publish(timeout=5)
    finally:
        client.loop_stop()
        client.disconnect()


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

@router.get("/ops/audit")
def list_audit(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM audit_logs")
            total = cur.fetchone()["total"]

            cur.execute(
                """
                SELECT id, action, details, created_at
                FROM audit_logs
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cur.fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": r["id"],
                "action": r["action"],
                "details": r["details"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ],
    }
