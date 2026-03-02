import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import AuthContext, require_api_key, require_user
from app.core.config import settings
from app.core.db import get_conn, hash_api_key, issue_api_key, write_audit

router = APIRouter(tags=["auth"])


# ---------- V1 compat --------------------------------------------------

@router.post("/apikeys")
def create_apikey() -> dict[str, str]:
    """V1 compatible: issue an anonymous API key (no user linkage)."""
    return {"api_key": issue_api_key()}


# ---------- V2 key management ------------------------------------------

class CreateKeyRequest(BaseModel):
    label: str = ""


@router.post("/me/apikeys", dependencies=[Depends(require_user)])
def create_user_key(
    payload: CreateKeyRequest,
    auth: AuthContext = Depends(require_user),
) -> dict:
    raw = issue_api_key(user_id=auth.user_id, label=payload.label)
    write_audit("apikey_created", {"user_id": auth.user_id, "label": payload.label})
    return {"api_key": raw, "label": payload.label}


@router.get("/me/apikeys", dependencies=[Depends(require_user)])
def list_user_keys(auth: AuthContext = Depends(require_user)) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, label, revoked, created_at
                FROM api_keys
                WHERE user_id=%s
                ORDER BY created_at DESC
                """,
                (auth.user_id,),
            )
            rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "label": r["label"],
            "revoked": r["revoked"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.post("/me/apikeys/{key_id}/rotate", dependencies=[Depends(require_user)])
def rotate_key(
    key_id: int,
    auth: AuthContext = Depends(require_user),
) -> dict:
    new_raw = f"{settings.api_key_prefix}{secrets.token_urlsafe(24)}"
    new_hash = hash_api_key(new_raw)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE api_keys SET key_hash=%s WHERE id=%s AND user_id=%s AND revoked=FALSE RETURNING id",
                (new_hash, key_id, auth.user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Key not found or already revoked")
        conn.commit()

    write_audit("apikey_rotated", {"user_id": auth.user_id, "key_id": key_id})
    return {"api_key": new_raw, "key_id": key_id}


@router.delete("/me/apikeys/{key_id}", dependencies=[Depends(require_user)])
def revoke_key(
    key_id: int,
    auth: AuthContext = Depends(require_user),
) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE api_keys SET revoked=TRUE WHERE id=%s AND user_id=%s RETURNING id",
                (key_id, auth.user_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Key not found or does not belong to you")
        conn.commit()

    write_audit("apikey_revoked", {"user_id": auth.user_id, "key_id": key_id})
    return {"status": "revoked", "key_id": key_id}
