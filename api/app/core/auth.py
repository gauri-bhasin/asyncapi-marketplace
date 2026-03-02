from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from .db import check_rate_limit, increment_usage, resolve_api_key


@dataclass
class AuthContext:
    api_key_id: int
    user_id: int | None
    key_hash: str


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> AuthContext:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )

    resolved = resolve_api_key(x_api_key)
    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
        )

    if check_rate_limit(resolved["api_key_id"]):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "message": "Rate limit exceeded. Try again in the next minute window.",
                "retry_after_seconds": 60,
            },
        )

    increment_usage(resolved["api_key_id"])

    return AuthContext(
        api_key_id=resolved["api_key_id"],
        user_id=resolved["user_id"],
        key_hash=resolved["key_hash"],
    )


def require_user(auth: AuthContext = Depends(require_api_key)) -> AuthContext:
    """Like require_api_key but also mandates a user-linked key."""
    if auth.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint requires a user-linked API key. Create a user via POST /users first.",
        )
    return auth
