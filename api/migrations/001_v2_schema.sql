-- V2 schema: users, extended api_keys, usage counters, subscriptions, connectors, DLQ replay

CREATE TABLE IF NOT EXISTS users (
    id          BIGSERIAL PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS user_id  BIGINT REFERENCES users(id);
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS label    TEXT NOT NULL DEFAULT '';
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS revoked  BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS usage_counters (
    id          BIGSERIAL PRIMARY KEY,
    api_key_id  BIGINT NOT NULL REFERENCES api_keys(id),
    topic       TEXT NOT NULL DEFAULT '*',
    window_start TIMESTAMPTZ NOT NULL,
    counter     INT NOT NULL DEFAULT 0,
    UNIQUE(api_key_id, topic, window_start)
);
CREATE INDEX IF NOT EXISTS idx_usage_counters_lookup
    ON usage_counters(api_key_id, topic, window_start);

CREATE TABLE IF NOT EXISTS subscriptions (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),
    topic       TEXT NOT NULL,
    filters     JSONB NOT NULL DEFAULT '{}'::jsonb,
    status      TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'PAUSED')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user       ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_topic ON subscriptions(user_id, topic);

CREATE TABLE IF NOT EXISTS connectors (
    id                    BIGSERIAL PRIMARY KEY,
    name                  TEXT NOT NULL UNIQUE,
    connector_type        TEXT NOT NULL,
    topic                 TEXT NOT NULL,
    poll_interval_seconds INT NOT NULL DEFAULT 25,
    source_config_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled               BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE dlq_events ADD COLUMN IF NOT EXISTS replayed    BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE dlq_events ADD COLUMN IF NOT EXISTS replayed_at TIMESTAMPTZ;

INSERT INTO connectors (name, connector_type, topic, poll_interval_seconds, source_config_json, enabled)
VALUES
    ('weather-berlin', 'weather', 'marketplace.weather.current_conditions.v1', 25,
     '{"latitude":"52.52","longitude":"13.41"}'::jsonb, TRUE),
    ('crypto-btc-usd', 'crypto', 'marketplace.crypto.price_updated.v1', 25,
     '{"product_id":"BTC-USD"}'::jsonb, TRUE)
ON CONFLICT (name) DO NOTHING;
