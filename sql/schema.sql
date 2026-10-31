CREATE TABLE IF NOT EXISTS clients (
    id      SERIAL PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE,
    tier    TEXT NOT NULL CHECK (tier IN ('free', 'pro', 'enterprise'))
);

CREATE TABLE IF NOT EXISTS api_keys (
    id         SERIAL PRIMARY KEY,
    client_id  INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    api_key    TEXT NOT NULL UNIQUE,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_api_keys_key ON api_keys(api_key);

CREATE TABLE IF NOT EXISTS rate_limit_rules (
    id             SERIAL PRIMARY KEY,
    api_key_id     INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    algorithm      TEXT NOT NULL CHECK (algorithm IN ('fixed_window', 'token_bucket')),
    capacity       INTEGER NOT NULL CHECK (capacity >= 0),
    refill_rate    DOUBLE PRECISION NOT NULL DEFAULT 0,
    window_seconds INTEGER NOT NULL DEFAULT 60,
    UNIQUE(api_key_id)
);