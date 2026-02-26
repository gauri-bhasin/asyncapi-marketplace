from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import require_api_key
from app.core.db import get_conn


router = APIRouter(tags=["topics"], dependencies=[Depends(require_api_key)])


@router.get("/topics")
def list_topics() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT name, description, tags, sample_payload
                FROM topics
                ORDER BY name
                """
            )
            return list(cur.fetchall())


@router.get("/topics/{name}")
def get_topic(name: str) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT name, description, tags, sample_payload, asyncapi_json
                FROM topics
                WHERE name = %s
                """,
                (name,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Topic not found")
            return row


@router.get("/topics/{name}/history")
def get_topic_history(name: str, limit: int = Query(default=100, ge=1, le=1000)) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_id, ts, source, topic, tags, payload
                FROM events
                WHERE topic = %s
                ORDER BY ts DESC
                LIMIT %s
                """,
                (name, limit),
            )
            return list(cur.fetchall())


@router.get("/topics/{name}/replay")
def replay_topic_events(name: str, since: datetime, until: datetime) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_id, ts, source, topic, tags, payload
                FROM events
                WHERE topic = %s
                  AND ts >= %s
                  AND ts <= %s
                ORDER BY ts ASC
                """,
                (name, since, until),
            )
            return list(cur.fetchall())
