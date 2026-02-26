from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import require_api_key
from app.routers.search import semantic_search, SearchRequest


router = APIRouter(tags=["agent"], dependencies=[Depends(require_api_key)])


class RecommendRequest(BaseModel):
    goal: str


@router.post("/agent/recommend")
def recommend_topics(payload: RecommendRequest) -> dict:
    search_result = semantic_search(SearchRequest(query=payload.goal))
    recs = []
    for row in search_result["results"][:3]:
        if not row.get("topic"):
            continue
        recs.append(
            {
                "topic": row["topic"],
                "why": f"Topic matches goal semantics with score {row['score']:.3f}",
                "score": row["score"],
            }
        )
    return {
        "goal": payload.goal,
        "recommended_topics": recs,
        "subscribe_action": {"type": "ws_subscribe", "topics": [r["topic"] for r in recs]},
    }
