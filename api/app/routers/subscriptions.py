import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import AuthContext, require_user
from app.core.db import get_conn, write_audit

router = APIRouter(tags=["subscriptions"], dependencies=[Depends(require_user)])


class CreateSubscriptionRequest(BaseModel):
    topic: str
    filters: dict | None = None


class PatchSubscriptionRequest(BaseModel):
    status: str  # ACTIVE | PAUSED


@router.post("/subscriptions")
def create_subscription(
    payload: CreateSubscriptionRequest,
    auth: AuthContext = Depends(require_user),
) -> dict:
    filters_val = payload.filters or {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO subscriptions (user_id, topic, filters)
                VALUES (%s, %s, %s::jsonb)
                RETURNING id, user_id, topic, filters, status, created_at, updated_at
                """,
                (auth.user_id, payload.topic, json.dumps(filters_val)),
            )
            row = cur.fetchone()
        conn.commit()

    write_audit("subscription_created", {"user_id": auth.user_id, "topic": payload.topic, "sub_id": row["id"]})
    return _fmt(row)


@router.get("/me/subscriptions")
def list_subscriptions(auth: AuthContext = Depends(require_user)) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, topic, filters, status, created_at, updated_at FROM subscriptions WHERE user_id=%s ORDER BY created_at DESC",
                (auth.user_id,),
            )
            return [_fmt(r) for r in cur.fetchall()]


@router.patch("/subscriptions/{sub_id}")
def update_subscription(
    sub_id: int,
    payload: PatchSubscriptionRequest,
    auth: AuthContext = Depends(require_user),
) -> dict:
    if payload.status not in ("ACTIVE", "PAUSED"):
        raise HTTPException(status_code=400, detail="status must be ACTIVE or PAUSED")

    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE subscriptions SET status=%s, updated_at=%s
                WHERE id=%s AND user_id=%s
                RETURNING id, user_id, topic, filters, status, created_at, updated_at
                """,
                (payload.status, now, sub_id, auth.user_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Subscription not found")
        conn.commit()

    write_audit("subscription_updated", {"sub_id": sub_id, "status": payload.status})
    return _fmt(row)


def _fmt(row: dict) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "topic": row["topic"],
        "filters": row["filters"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }
