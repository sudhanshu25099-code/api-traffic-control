INSERT INTO clients (name, tier) VALUES
    ('Demo Corp',      'free'),
    ('Pro Inc',        'pro'),
    ('Enterprise Ltd', 'enterprise')
ON CONFLICT (name) DO NOTHING;

INSERT INTO api_keys (client_id, api_key)
SELECT id, 'demo-key'        FROM clients WHERE name = 'Demo Corp'      ON CONFLICT (api_key) DO NOTHING;
INSERT INTO api_keys (client_id, api_key)
SELECT id, 'pro-key'         FROM clients WHERE name = 'Pro Inc'        ON CONFLICT (api_key) DO NOTHING;
INSERT INTO api_keys (client_id, api_key)
SELECT id, 'enterprise-key'  FROM clients WHERE name = 'Enterprise Ltd' ON CONFLICT (api_key) DO NOTHING;

-- demo-key : fixed_window, 5 req / 60s  (used in Swagger live demo)
INSERT INTO rate_limit_rules (api_key_id, algorithm, capacity, refill_rate, window_seconds)
SELECT id, 'fixed_window', 5, 0, 60 FROM api_keys WHERE api_key = 'demo-key'
ON CONFLICT (api_key_id) DO NOTHING;

-- pro-key  : token_bucket, capacity 100, refill ~1.67/s
INSERT INTO rate_limit_rules (api_key_id, algorithm, capacity, refill_rate, window_seconds)
SELECT id, 'token_bucket', 100, 1.67, 60 FROM api_keys WHERE api_key = 'pro-key'
ON CONFLICT (api_key_id) DO NOTHING;

-- enterprise-key : fixed_window, 1000 req / 60s
INSERT INTO rate_limit_rules (api_key_id, algorithm, capacity, refill_rate, window_seconds)
SELECT id, 'fixed_window', 1000, 0, 60 FROM api_keys WHERE api_key = 'enterprise-key'
ON CONFLICT (api_key_id) DO NOTHING;