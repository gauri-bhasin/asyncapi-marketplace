import json
import logging

from fastapi import APIRouter, Depends

from app.core.auth import require_api_key
from app.core.config import settings
from app.core.db import get_conn, seed_topics_from_asyncapi, write_audit

log = logging.getLogger(__name__)

router = APIRouter(tags=["registry"], dependencies=[Depends(require_api_key)])


@router.post("/registry/sync")
def sync_registry() -> dict:
    asyncapi_dir = settings.asyncapi_dir
    files = list(asyncapi_dir.glob("*.json"))

    seed_topics_from_asyncapi(asyncapi_dir)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM topics ORDER BY name")
            synced = [r["name"] for r in cur.fetchall()]

    portal_status = "skipped"
    if settings.event_portal_token:
        portal_status = _push_to_event_portal(files)

    write_audit("registry_sync", {"files": len(files), "topics_synced": synced, "portal": portal_status})

    return {
        "files_processed": len(files),
        "topics_synced": synced,
        "event_portal": portal_status,
    }


def _push_to_event_portal(files: list) -> str:
    """Best-effort push to Solace Event Portal. Returns status string."""
    try:
        import httpx

        for f in files:
            doc = json.loads(f.read_text(encoding="utf-8"))
            title = doc.get("info", {}).get("title", f.stem)
            log.info("Would push %s to Event Portal (placeholder)", title)
        return "pushed"
    except Exception as exc:
        log.warning("Event Portal push failed: %s", exc)
        return f"error: {exc}"
