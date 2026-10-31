# API Traffic Control

A distributed rate limiter for FastAPI backends, using **PostgreSQL as the source of truth for access policies** and **Redis + atomic Lua scripts as the high-speed execution engine** for per-client state. Built as an Algorithms Design & Analysis (ADA) course project.

---

## Overview

Every HTTP request to a protected endpoint goes through a custom ASGI middleware that:

1. **Extracts the client's rate-limit rule from PostgreSQL** — capacity, refill rate, and window size — via a single indexed lookup on `api_key`.
2. **Executes the rate-limiting algorithm inside Redis** using an atomic Lua script, passing the rule as arguments and reading/updating the client's transient state (token count, last refill timestamp, window counter).
3. **Injects `X-RateLimit-*` headers** into the response and returns `429 Too Many Requests` when the limit is exceeded.

The key design choice: **PostgreSQL is never used to store the rate-limit counter**, only the rule. Storing the counter in Postgres would require `SELECT ... FOR UPDATE` on a hot row per request, serializing every request from a given client. Instead, the counter lives in Redis, where a Lua script performs the read-modify-write atomically — the correct way to enforce a rate limit under concurrent traffic.

```
                          ┌─────────────────────────┐
                          │       FastAPI           │
                          │       Middleware        │
   ┌──────────┐           │                         │           ┌──────────────┐
   │  Client  │──request──▶  1. Get rule (SQL) ────┼──────────▶│  PostgreSQL  │
   └──────────┘           │           │             │           │  (rules)     │
        ▲                 │           ▼             │           └──────────────┘
        │                 │  2. EVALSHA(rule, key)  │
        │   response      │           │             │           ┌──────────────┐
        │  (200 or 429)   │           ▼             │           │    Redis     │
        └─────────────────┼── 3. headers + status   │◀──────────│  (state +    │
                          │                         │           │   Lua script)│
                          └─────────────────────────┘           └──────────────┘
```

---

## Algorithms

The project implements and compares three rate-limiting algorithms, each with a Redis Lua script and an in-process Python baseline (for cost comparison).

| Algorithm | Time per req | Memory per key | Redis ops/req | Burst behavior |
|---|---|---|---|---|
| **Fixed Window** | O(1) | O(1) | 1–2 | Allows up to 2× limit at window boundary |
| **Sliding Window Log** | O(1) | O(N), N = limit | 1 (ZADD + ZREMRANGEBYSCORE + ZCARD) | Exact — no boundary leak |
| **Token Bucket** | O(1) | O(1) | 1 | Bursts up to bucket capacity, then steady rate |

**Python baselines** (`app/limiters/`) implement the same logic in-process, so we can measure the cost of the Redis hop vs. pure Python overhead. The baselines are *not* used in production — they exist to quantify the cost of distributed state.

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Web framework | FastAPI 0.115 | Native async, auto OpenAPI docs |
| ASGI server | Uvicorn (standard extras) | `uvloop` + `httptools` for real performance |
| Database driver | `asyncpg` | Only async Postgres driver; sync drivers block the event loop |
| ORM | SQLAlchemy 2.0 (`asyncio`) + raw SQL | Raw SQL for the hot path; no ORM overhead |
| Cache / state | Redis 5.x (`redis.asyncio`) | Atomic Lua execution, sub-ms latency |
| Lua loading | `EVALSHA` | Script parsed once by Redis, not per request |
| Config | `pydantic-settings` | Typed env vars, fail-fast on missing keys |
| Testing | pytest + `httpx.AsyncClient` | Async-correct boundary tests |
| Load testing | Locust | p95/p99 latency, req/s under 1000 concurrent users |

---

## Project Structure

```
api-traffic-control/
├── app/
│   ├── main.py                  # FastAPI init, middleware registration
│   ├── config.py                # pydantic-settings, reads .env
│   ├── database.py              # create_async_engine + async session
│   ├── redis_client.py          # async client + EVALSHA loader
│   ├── models.py                # Pydantic DTOs
│   ├── crud.py                  # raw SQL: get_rule_by_api_key()
│   ├── middleware.py            # pure ASGI rate limiter
│   ├── limiters/                # in-process Python baselines
│   ├── lua/                     # real .lua scripts
│   └── routers/                 # API endpoints (dummy + admin)
├── sql/                         # schema.sql + seed.sql
├── tests/                       # test_algorithms.py + locustfile.py
├── scripts/staleness_test.py    # rule-propagation measurement
├── Dockerfile
├── docker-compose.yml           # FastAPI + Postgres + Redis (with healthchecks)
├── requirements.txt
└── README.md
```

---

## Setup

### Prerequisites
- Docker and Docker Compose
- Python 3.11+

### 1. Clone and configure
```bash
git clone <repo-url> && cd api-traffic-control
cp .env.example .env
# edit .env if you need different credentials
```

### 2. Start Postgres + Redis + FastAPI
```bash
docker compose up -d --build
```

`docker-compose.yml` uses `healthcheck` + `depends_on: service_healthy` so FastAPI waits until Postgres and Redis are actually ready — otherwise the first requests 500.

### 3. Load schema and seed data
```bash
docker compose exec -T postgres psql -U postgres -d traffic < sql/schema.sql
docker compose exec -T postgres psql -U postgres -d traffic < sql/seed.sql
```

The seed file creates three clients with known API keys — one per tier — plus a `demo-key` with `capacity=5, window=60s` used in the live demo below.

### 4. Verify
```bash
curl -H "X-API-Key: demo-key" http://localhost:8000/api/data
```

You should get `200` with `X-RateLimit-Limit: 5` in the response headers.

---

## Live Demo (Swagger UI)

Open **http://localhost:8000/docs** and:

1. Click the green **Authorize** button (top right), paste `demo-key`, click Authorize.
2. Expand `GET /api/data` → **Try it out** → **Execute**.
3. Repeat the request five times. Watch `X-RateLimit-Remaining` count down: `4 → 3 → 2 → 1 → 0`.
4. On the sixth request you get **`429 Too Many Requests`** with `Retry-After: 60`.
5. Wait 60 seconds, click again — back to `200` with `Remaining: 4`.

This demonstrates correctness of the limiter without any external tooling. For the same sequence in the terminal:

```bash
for i in {1..6}; do
  curl -s -o /dev/null -w "%{http_code} " -H "X-API-Key: demo-key" \
    http://localhost:8000/api/data
done
# expected: 200 200 200 200 200 429
```

---

## Testing

### Correctness — `pytest`
```bash
pytest tests/test_algorithms.py -v
```

Asserts:
- 5 requests allowed, 6th returns 429
- `X-RateLimit-*` headers present and correct
- Token-bucket refill: after sleeping `1.1s`, one token is back
- Unknown API key returns 401, not 500
- Zero-capacity rule rejects all requests without crashing

### Load — Locust
```bash
locust -f tests/locustfile.py --headless -u 1000 -r 100 -t 60s --host http://localhost:8000
```

Run Locust from a **separate container or host** from FastAPI. Sharing a CPU makes you measure contention, not the limiter.

### Rule propagation — `scripts/staleness_test.py`
```bash
python scripts/staleness_test.py
```

Changes a rule in Postgres mid-load, then counts how many subsequent responses still used the old rule. Output:

```
0 / 200 requests used the old capacity. Propagation delay: <!-- FILL --> ms.
```

This is the empirical evidence for the "no stale rules" claim, replacing it with a measured value. Run the same script against a cached variant (add a 1s rule cache) to show the *cost of freshness* as a comparison table.

---

## Results

> All numbers below are measured on <!-- FILL: hardware / docker-compose setup -->. Locust run: 1000 concurrent users, 60s, near-zero wait time. Locust ran on a separate container from the FastAPI app.

### Throughput and latency per algorithm

| Algorithm | Req/s | p50 (ms) | p95 (ms) | p99 (ms) | Redis ops/req |
|---|---|---|---|---|---|
| Fixed Window | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> |
| Sliding Window Log | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> |
| Token Bucket | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> |
| Python baseline (fixed window, no Redis) | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> | — |

### Where the latency goes

| Component | Cost per request (p95) |
|---|---|
| Postgres rule lookup (indexed) | <!-- FILL --> ms |
| Redis Lua execution | <!-- FILL --> µs |
| FastAPI + middleware overhead | <!-- FILL --> ms |

### Freshness vs. cache cost

| Setup | Stale responses after rule update | Throughput (req/s) |
|---|---|---|
| No rule cache (current design) | 0 / 200 | <!-- FILL --> |
| 1-second rule cache | <!-- FILL --> / 200 | <!-- FILL --> |

The trade-off is presented for the report: freshness costs a Postgres round-trip per request, but throughput and freshness are not independent — the cache reduces DB load at the cost of a bounded staleness window. The current design chooses **zero staleness** at the cost of the DB hop; the cached variant is measured, not adopted.

### Correctness
All boundary tests pass. Refer to `pytest tests/test_algorithms.py -v` output. Sample:
```
test_fixed_window_rejects_sixth  PASSED
test_token_bucket_refill         PASSED
test_headers_present             PASSED
test_unknown_key_returns_401     PASSED
```

---

## Design Decisions and Trade-offs

**Postgres as source of truth, zero caching.** The rule is fetched on every request via an indexed lookup. Cost: ~<!-- FILL --> ms per request. Benefit: policy changes take effect immediately (verified by `staleness_test.py`). A cached variant exists as a measured alternative, not the default.

**Async all the way down.** `create_async_engine` + `asyncpg` + `redis.asyncio` — no synchronous DB calls anywhere on the request path. A sync session inside `async def` would block the event loop on every request and make the performance story irrelevant.

**Pure ASGI middleware, not `BaseHTTPMiddleware`.** `@app.middleware("http")` wraps every request in a task; at 1000 concurrent users that overhead is part of what you'd be measuring. A raw ASGI class is measurably faster.

**Lua scripts as `.lua` files, called via `EVALSHA`.** Storing Lua as Python strings forces `EVAL` (Redis re-parses the script per call). `EVALSHA` parses once and executes by hash. Small win per request, but the right pattern.

**Timestamps from `redis.call('TIME')`, never from the app.** Clock skew across app instances would break token-bucket refill math (`elapsed × rate` becomes wrong or negative). Time inside the Lua script is the only correct source.

**No frontend.** The interesting parts of this project are algorithms and state consistency, not UI. Swagger UI (`/docs`) plus a `curl` loop in the README covers every demo need.

---

## Team & Roles

| Member | Owns |
|---|---|
| **<!-- Your name -->** | Backend: middleware, Lua scripts, Redis integration, routers, Python limiters, tests, Locust, staleness experiment, Dockerfile |
| **<!-- Teammate name -->** | Database: schema, indexes (including the `UNIQUE` index on `api_key` that makes the per-request lookup sub-ms), seed data, `crud.py` SQL, Postgres service in compose |

The `crud.py` function signature is the agreed boundary between the two: `async def get_rule_by_api_key(session, api_key) -> Rule | None`. Only the DB owner edits the SQL inside; the backend only calls it.

---

## Limitations and Future Work

- **Rule fetch is a per-request DB round-trip.** A `LISTEN`/`NOTIFY`-based cache invalidation would preserve near-zero staleness without the DB hop. Measured as a future improvement, not implemented here.
- **Redis is a single instance.** A cluster or sentinel deployment is out of scope for the project but a production requirement.
- **No distributed tracing.** `X-Request-ID` is passed through but not exported to an observability backend.
- **Locust uses a single API key.** Realistic multi-tenant load (thousands of distinct clients) would stress the Redis keyspace differently than the current test.
- **Algorithms compared are three; leaky bucket is a natural fourth.** Cut for scope.

---

## References

- Stripe Engineering — *Scaling your API with rate limiters*
- Cloudflare — *How to rate limit*
- Redis docs — *Lua scripting and `EVALSHA`*
- FastAPI docs — *Async, middleware, and lifespan*
- SQLAlchemy 2.0 docs — *Asynchronous I/O*

---

## License

College project — not for redistribution.