import chromadb
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import require_api_key
from app.core.config import settings
from app.core.embedding import deterministic_embedding


router = APIRouter(tags=["search"], dependencies=[Depends(require_api_key)])


class SearchRequest(BaseModel):
    query: str


@router.post("/search/semantic")
def semantic_search(payload: SearchRequest) -> dict:
    client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    collection = client.get_or_create_collection("topic_index")
    result = collection.query(
        query_embeddings=[deterministic_embedding(payload.query)],
        n_results=5,
        include=["documents", "distances", "metadatas"],
    )
    docs = result.get("documents", [[]])[0]
    dists = result.get("distances", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    rows = []
    for i, doc in enumerate(docs):
        rows.append(
            {
                "topic": (metas[i] or {}).get("topic"),
                "score": 1 - dists[i] if i < len(dists) else 0.0,
                "snippet": doc,
                "metadata": metas[i],
            }
        )
    return {"results": rows}
