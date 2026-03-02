from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.auth import require_api_key
from app.core.config import settings
from app.core.db import get_conn, init_db, run_migrations, seed_topics_from_asyncapi
from app.core.metrics import connector_errors_total, dlq_events_total, events_ingested_total
from app.routers import agent, auth, ops, registry, search, subscriptions, topics, users, ws


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    run_migrations()
    seed_topics_from_asyncapi(settings.asyncapi_dir)
    yield


app = FastAPI(title="AsyncAPI Marketplace", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
trace.set_tracer_provider(TracerProvider())
FastAPIInstrumentor.instrument_app(app)

# V1 routers
app.include_router(auth.router)
app.include_router(topics.router)
app.include_router(search.router)
app.include_router(agent.router)
app.include_router(ws.router)

# V2 routers
app.include_router(users.router)
app.include_router(subscriptions.router)
app.include_router(ops.router)
app.include_router(registry.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM events")
            events_ingested_total.set(cur.fetchone()["c"])
            cur.execute("SELECT COUNT(*) AS c FROM dlq_events")
            dlq_events_total.set(cur.fetchone()["c"])
            cur.execute(
                "SELECT COUNT(*) AS c FROM audit_logs WHERE action IN ('connector_error_weather', 'connector_error_crypto')"
            )
            connector_errors_total.set(cur.fetchone()["c"])
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


@app.get("/protected/ping", dependencies=[Depends(require_api_key)])
def protected_ping() -> dict[str, str]:
    return {"message": "pong"}
