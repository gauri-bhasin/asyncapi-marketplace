from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import AuthContext, require_user
from app.core.db import get_conn, issue_api_key, write_audit

router = APIRouter(tags=["users"])


class CreateUserRequest(BaseModel):
    username: str
    display_name: str = ""


@router.post("/users")
def create_user(payload: CreateUserRequest) -> dict:
    """Create a developer user and return an initial API key."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM users WHERE username=%s",
                (payload.username,),
            )
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="Username already taken")

            cur.execute(
                "INSERT INTO users (username, display_name) VALUES (%s, %s) RETURNING id, username, display_name, created_at",
                (payload.username, payload.display_name),
            )
            user = cur.fetchone()
        conn.commit()

    raw_key = issue_api_key(user_id=user["id"], label="initial")
    write_audit("user_created", {"user_id": user["id"], "username": user["username"]})

    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "created_at": user["created_at"].isoformat(),
        },
        "api_key": raw_key,
    }


@router.get("/me", dependencies=[Depends(require_user)])
def get_me(auth: AuthContext = Depends(require_user)) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, display_name, created_at FROM users WHERE id=%s",
                (auth.user_id,),
            )
            user = cur.fetchone()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            cur.execute(
                "SELECT COUNT(*) AS c FROM api_keys WHERE user_id=%s AND revoked=FALSE",
                (auth.user_id,),
            )
            key_count = cur.fetchone()["c"]

            cur.execute(
                "SELECT COUNT(*) AS c FROM subscriptions WHERE user_id=%s",
                (auth.user_id,),
            )
            sub_count = cur.fetchone()["c"]

    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "created_at": user["created_at"].isoformat(),
        "active_keys": key_count,
        "subscriptions": sub_count,
    }
