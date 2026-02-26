# v1.0.0 - AsyncAPI Marketplace

## Highlights

- End-to-end local event marketplace using Solace PubSub+, FastAPI, React, Postgres, and Chroma.
- Two live connectors:
  - Weather (`marketplace.weather.current_conditions.v1`)
  - Crypto (`marketplace.crypto.price_updated.v1`)
- AsyncAPI-driven topic registry seeded from local specs in `shared/asyncapi/`.
- API key auth with `X-API-Key`.
- Topic browsing, history, replay, semantic search, and deterministic agent recommendations.
- WebSocket live subscription flow from UI to backend.
- OpenTelemetry instrumentation (basic) and Prometheus-style `/metrics` endpoint.

## Included Services

- `solace` broker
- `postgres` database
- `chroma` vector store
- `api` marketplace backend
- `weather-connector`, `crypto-connector`
- `indexer`
- `web` frontend

## API Endpoints

- `POST /apikeys`
- `GET /topics`
- `GET /topics/{name}`
- `GET /topics/{name}/history?limit=100`
- `GET /topics/{name}/replay?since=<iso>&until=<iso>`
- `WS /ws/subscribe?topic=<name>`
- `POST /search/semantic`
- `POST /agent/recommend`
- `GET /health`
- `GET /metrics`

## Test Coverage (v1 minimal)

- Schema validation unit tests for both topic payload envelopes.
- API health unit test.

## Known Limitations

- Frontend Docker build can be slow on some Windows environments; local frontend fallback is documented in README.
- WebSocket auto-reconnect after browser refresh is not implemented in v1.
- Semantic score normalization is basic and deterministic.

## Upgrade Path to v2

- Improve frontend UX: auto-reconnect, better replay/date input, richer status badges.
- Harden backend reliability: connector retry/backoff, websocket resilience, migration tooling.
- Add deeper tests: integration and websocket behavior tests.
- Optional Gemini-backed recommendation path behind env feature flag.
