# AsyncAPI Marketplace

A real-time event marketplace powered by **Solace PubSub+**, **FastAPI**, **PostgreSQL**, **ChromaDB**, and a **React + Vite** UI.

---

## V2 Features

| Area | What's new |
|------|-----------|
| **User & API Key Management** | `POST /users` creates a developer account with an initial API key. Manage keys via `GET /me/apikeys`, `POST /me/apikeys`, rotate, and revoke endpoints. |
| **Quotas & Rate Limiting** | Per-key, per-minute usage counters. Exceeding the limit returns **429** with a clear JSON error. Default: 120 req/min (configurable via `RATE_LIMIT_PER_MINUTE`). |
| **Subscriptions** | First-class subscription objects. `POST /subscriptions`, `GET /me/subscriptions`, `PATCH /subscriptions/{id}` (ACTIVE/PAUSED). WebSocket auto-creates a subscription on connect; paused subscriptions block WS. |
| **Connector Registry** | Config-driven `connectors` table replaces hard-coded entrypoints. A single **connector-runner** service loads enabled connectors from the DB and runs them in threads. Weather + Crypto seeded by default. |
| **Ops Console** | `GET /ops/dlq` (paginated), `POST /ops/dlq/{id}/replay` (republish to Solace + mark replayed), `GET /ops/audit` (paginated). UI pages at `/ops/dlq` and `/ops/audit`. |
| **Registry Sync** | `POST /registry/sync` reloads local AsyncAPI JSON into the topics table. Optional Event Portal push when `EVENT_PORTAL_TOKEN` is set. |
| **DB Migrations** | Numbered SQL migrations in `api/migrations/` run automatically on startup via a `_migrations` tracking table. |

### Backward Compatibility

All V1 endpoints (`POST /apikeys`, `GET /topics`, `GET /topics/{name}/history`, `/topics/{name}/replay`, `POST /search/semantic`, `POST /agent/recommend`, `WS /ws/subscribe`) continue to work unchanged. Anonymous API keys (issued via `POST /apikeys`) can still access V1 endpoints; V2 user-specific endpoints require a user-linked key.

---

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env

# 2. Build & run everything
docker compose up --build

# 3. Open the UI
open http://localhost:5173
```

### Demo Steps

1. **Create account** — on the homepage enter a username and click **Create Account**.
2. **Browse catalog** — the two seeded topics (weather, crypto) appear immediately.
3. **Subscribe** — click a topic, then **Subscribe WebSocket** to see live events.
4. **Manage keys** — navigate to **API Keys** to create, rotate, or revoke keys.
5. **Subscriptions** — view and pause/resume subscriptions from the **Subscriptions** page.
6. **Ops console** — check **DLQ** for dead-lettered events (replay if needed), **Audit** for all recorded actions.
7. **Registry sync** — `curl -X POST http://localhost:8000/registry/sync -H "X-API-Key: <key>"` to re-sync AsyncAPI specs.

---

## Architecture

```
┌────────────┐     MQTT      ┌───────────────┐     MQTT     ┌──────────┐
│  connector │ ──────────▸   │  Solace       │ ◂────────── │  indexer  │
│   runner   │               │  PubSub+      │              │          │
└────────────┘               └───────────────┘              └──────────┘
       │                                                          │
       │  Postgres                                    Postgres + Chroma
       ▼                                                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          PostgreSQL + ChromaDB                          │
└─────────────────────────────────────────────────────────────────────────┘
       ▲                                                          ▲
       │  HTTP / WS                                               │
┌──────────────┐                                          ┌──────────────┐
│  FastAPI API │ ◂─────── HTTP ───────────────────────▸   │  React UI    │
│  (port 8000) │                                          │  (port 5173) │
└──────────────┘                                          └──────────────┘
```

### Services (docker compose)

| Service | Purpose |
|---------|---------|
| `solace` | Solace PubSub+ broker (MQTT on 1883, admin on 8080) |
| `postgres` | PostgreSQL 16 |
| `chroma` | ChromaDB vector store |
| `api` | FastAPI backend — REST + WebSocket |
| `connector-runner` | Config-driven connector runner (weather + crypto) |
| `indexer` | MQTT subscriber → Postgres + Chroma |
| `web` | React + Vite frontend |

---

## API Reference (V2 additions)

### Users

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/users` | No | Create user + initial API key |
| GET | `/me` | User | Current user profile |

### API Keys

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/apikeys` | No | V1 compat — anonymous key |
| GET | `/me/apikeys` | User | List your keys |
| POST | `/me/apikeys` | User | Create a new key |
| POST | `/me/apikeys/{id}/rotate` | User | Rotate key (new secret, same ID) |
| DELETE | `/me/apikeys/{id}` | User | Revoke key |

### Subscriptions

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/subscriptions` | User | Create subscription |
| GET | `/me/subscriptions` | User | List your subscriptions |
| PATCH | `/subscriptions/{id}` | User | Set status ACTIVE / PAUSED |

### Ops

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/ops/dlq?limit=&offset=&status=` | Key | Paginated DLQ |
| POST | `/ops/dlq/{id}/replay` | Key | Republish to Solace + mark replayed |
| GET | `/ops/audit?limit=&offset=` | Key | Paginated audit log |

### Registry

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/registry/sync` | Key | Re-sync AsyncAPI JSON → topics table |

---

## Configuration

All configuration via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_PER_MINUTE` | 120 | Max requests per API key per minute |
| `EVENT_PORTAL_TOKEN` | *(empty)* | Solace Event Portal token (optional) |
| `DATABASE_URL` | see .env.example | Postgres connection string |
| `SOLACE_HOST` / `SOLACE_PORT` | solace / 1883 | Broker address |

---

## DB Migrations

SQL files in `api/migrations/` are applied automatically on API startup.  
A `_migrations` table tracks which files have been applied.  
To add a migration, create `api/migrations/002_your_change.sql`.
