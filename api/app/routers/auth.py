from fastapi import APIRouter

from app.core.db import issue_api_key


router = APIRouter(tags=["auth"])


@router.post("/apikeys")
def create_apikey() -> dict[str, str]:
    return {"api_key": issue_api_key()}
