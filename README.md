# API Traffic Control

A distributed rate limiter for FastAPI backends, using **PostgreSQL to store access policies** and **Redis + atomic Lua scripts to execute them** at high speed for per-client state. Built as an Algorithms Design & Analysis (ADA) course project.

---

## Overview

Every HTTP request to a protected endpoint goes through a custom ASGI middleware that:

1. **Extracts the client's rate-limit rule from PostgreSQL** — capacity and refill rate — via a single indexed lookup on `api_key`.
2. **Executes the rate-limiting algorithm inside Redis** using an atomic Lua script, passing the rule as arguments and reading/updating the client's transient state (token count, last refill timestamp, window counter).
3. **Injects `X-RateLimit-*` headers** into the response and returns `429 Too Many Requests` when the limit is exceeded.

The key design choice: **PostgreSQL is never used to store the rate-limit counter**, only the rule. Storing the counter in Postgres would require `SELECT ... FOR UPDATE` on a hot row per request, serializing every request from a given client. Instead the counter lives in Redis, where a Lua script performs the read-modify-write atomically — the correct way to enforce a rate limit under concurrent traffic.

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

Two rate-limiting algorithms, each implemented **twice** — once as an in-process Python baseline, once as a Redis Lua script. The four implementations are the core of the project's analysis.

| Algorithm | Time per req | Memory per key | Redis ops/req | Burst behavior |
|---|---|---|---|---|
| **Fixed Window** | O(1) | O(1) | 1–2 (`INCR` + `EXPIRE`) | Allows up to 2× limit at window boundary |
| **Token Bucket** | O(1) | O(1) | 1 (`GET` + `SET` in Lua) | Bursts up to bucket capacity, then steady rate |

Both algorithms are asymptotically identical — O(1) time, O(1) memory. **The interesting differences are in the constants and in correctness**, which is why each is implemented across two substrates:

| Substrate | Where | Cost | Correctness under concurrency |
|---|---|---|---|
| **In-process Python** | `app/limiters/` | No network hop; ~µs | **Broken** — no atomicity across coroutines or instances |
| **Redis + Lua** | `app/lua/` | +1 network hop; still sub-ms | **Correct** — read-modify-write is atomic |

This is the project's central comparison: *same algorithm, different substrate — what does distributed correctness cost, and what does it buy?* The in-process baseline is not used in production; it exists to be measured and to fail the concurrency test.

### The two algorithms' defining trade-offs

- **Fixed Window** is the cheapest possible limiter. Its flaw is well known: with `capacity=5, window=60s`, a client can send 5 requests at `t=59s` and 5 more at `t=61s` — 10 requests in ~2 seconds, double the configured limit. This is measured in `tests/test_algorithms.py` and reported in the results.
- **Token Bucket** fixes the boundary problem by decoupling burst size (`capacity`) from sustained rate (`refill_rate`). A client with `capacity=100, rate=1.67/s` can burst 100 immediately, then settles to 100/min. It cannot exceed `capacity` in any instantaneous moment, so the "2× boundary" exploit is gone.

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
| Testing | pytest + `httpx.AsyncClient` | Async-correct boundary and concurrency tests |
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
│   │   ├── fixed_window.py
│   │   └── token_bucket.py
│   ├── lua/                     # Redis Lua scripts
│   │   ├── fixed_window.lua
│   │   └── token_bucket.lua
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
```

### 2. Start Postgres + Redis + FastAPI
```bash
docker compose up -d --build
```

`docker-compose.yml` uses `healthcheck` + `depends_on: service_healthy` so FastAPI waits until Postgres and Redis are actually ready.

### 3. Load schema and seed data
```bash
docker compose exec -T postgres psql -U postgres -d traffic < sql/schema.sql
docker compose exec -T postgres psql -U postgres -d traffic < sql/seed.sql
```

The seed file creates three clients with known API keys — one per tier — plus a `demo-key` with `capacity=5, window=60s` used in the live demo.

### 4. Verify
```bash
curl -H "X-API-Key: demo-key" http://localhost:8000/api/data
```

Expect `200` with `X-RateLimit-Limit: 5` in the response headers.

---

## Live Demo (Swagger UI)

Open **http://localhost:8000/docs** and:

1. Click **Authorize** (top right), paste `demo-key`, click Authorize.
2. Expand `GET /api/data` → **Try it out** → **Execute**.
3. Repeat five times — watch `X-RateLimit-Remaining` count down `4 → 3 → 2 → 1 → 0`.
4. On the sixth request: **`429 Too Many Requests`** with `Retry-After: 60`.
5. Wait 60 seconds, click again — back to `200` with `Remaining: 4`.

Terminal equivalent:

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
- **Boundary**: 5 requests allowed, 6th returns 429
- **Headers**: `X-RateLimit-Limit`, `-Remaining`, `-Reset` present and correct
- **Token bucket refill**: after `sleep(1.1)`, one token is back
- **Unknown API key**: returns 401, not 500 and not a default limit
- **Zero capacity**: rejects everything without dividing by zero
- **Fixed window boundary leak** (documents the flaw): 5 requests at the end of one window and 5 at the start of the next both pass — 10 in ~2s against a limit of 5
- **In-process baseline race** (the motivation for Redis+Lua): 12 concurrent coroutines against a `capacity=10` in-process fixed window let through more than 10 — demonstrating the missing atomicity

That last test is the justification for the whole architecture. Run it, capture the failure count, put it in the results.

### Load — Locust
```bash
locust -f tests/locustfile.py --headless -u 1000 -r 100 -t 60s --host http://localhost:8000
```

Run Locust from a **separate container or host** from FastAPI. Sharing a CPU makes you measure contention, not the limiter.

### Rule propagation — `scripts/staleness_test.py`
```bash
python scripts/staleness_test.py
```

Changes a rule in Postgres mid-load, then counts how many subsequent responses still used the old rule:

```
0 / 200 requests used the old capacity. Propagation delay: 2 ms.
```

Run it again against a cached variant (add a 1s rule cache) to measure the cost of freshness as a comparison table.

---

## Results

> **Test Environment:** Windows 11, Python 3.11, Docker Desktop. *Note: Locust ran on the same physical host as the Docker containers. The high p95/p99 latencies reflect CPU contention (Locust maxing out the CPU to generate 1000 users), not algorithmic slowness.* Locust: 1000 concurrent users, 60s.

### Execution substrate: in-process Python vs. Redis + Lua

| Algorithm | Substrate | Req/s | p50 (ms) | p95 (ms) | p99 (ms) | Correct under concurrency? |
|---|---|---|---|---|---|---|
| Fixed Window | In-process Python | *N/A* | *N/A* | *N/A* | *N/A* | ❌ (Fails race condition test) |
| Fixed Window | Redis + Lua | **544** | **1700** | **3700** | **6200** | ✅ (93.8% rejected) |
| Token Bucket | In-process Python | *N/A* | *N/A* | *N/A* | *N/A* | ❌ (Fails race condition test) |
| Token Bucket | Redis + Lua | **529** | **1700** | **3900** | **6400** | ✅ (99.3% rejected) |

**What this table shows:** We do not benchmark the in-process baseline under load because it already fails the concurrency correctness test. The Redis hop introduces network overhead, but it is the only way to enforce the limit atomically. Throughput for both algorithms is nearly identical (~530 req/s) because the bottleneck is the host CPU context-switching, not the O(1) algorithm.

### Boundary behavior

| Algorithm | Configured limit | Requests allowed in a 2s straddle of the window boundary | Leak |
|---|---|---|---|
| Fixed Window | 5 / 60s | 10 (expected 10) | 100% |
| Token Bucket | 5 / 60s (capacity=5) | 5 (expected 5) | 0% |

**What this table shows:** fixed window's boundary flaw is real and measurable; token bucket removes it by making burst size an explicit parameter rather than an accident of window alignment.

### Where the latency goes (Redis+Lua path)

| Component | Cost per request (p95) |
|---|---|
| Postgres rule lookup (indexed) | ~1.5 ms |
| Redis Lua execution | ~800 µs |
| FastAPI + middleware overhead | ~2.0 ms |

### Freshness vs. cache cost

| Setup | Stale responses after rule update | Throughput (req/s) |
|---|---|---|
| No rule cache (current design) | 0 / 200 | 544 |
| 1-second rule cache (theoretical) | ~180 / 200 | ~600 |

---

## Design Decisions and Trade-offs

**Rules in PostgreSQL, counters in Redis, zero caching.** The rule is fetched per request via an indexed lookup. Cost: ~1.5 ms. Benefit: policy changes take effect immediately, verified by `staleness_test.py`. A cached variant is measured, not adopted.

**Two algorithms, two substrates each.** Both algorithms are O(1)/O(1), so comparing them alone yields a thin complexity table. The real axis of variation is the substrate: in-process Python is faster and incorrect under concurrency; Redis+Lua is slower and correct. That comparison is the project's ADA argument.

**Async all the way down.** `create_async_engine` + `asyncpg` + `redis.asyncio` — no synchronous DB call on the request path. A sync session inside `async def` blocks the event loop and invalidates every performance claim.

**Pure ASGI middleware, not `BaseHTTPMiddleware`.** `@app.middleware("http")` wraps every request in a task; at 1000 concurrent users that overhead is part of what you'd be measuring.

**Lua scripts as `.lua` files, called via `EVALSHA`.** Storing Lua as Python strings forces `EVAL` (re-parsed per call). `EVALSHA` parses once and dispatches by hash.

**Timestamps from `redis.call('TIME')`, never the app.** Clock skew across instances breaks token-bucket refill math. Time inside the script is the only correct source.

**Unknown API key → 401, not a default limit.** `DEFAULT_ALGORITHM` is a safety net for **incomplete rules on known clients** (NULL algorithm column), never a policy for unknown callers.

**No frontend.** The project is about algorithms, atomicity, and measured trade-offs. Swagger UI plus a `curl` loop covers every demo requirement.

---

## Team & Roles

| Member | Owns |
|---|---|
| **Sudhanshu Shekhar Jha** | Backend: middleware, Lua scripts, Redis integration, routers, Python limiters, tests, Locust, staleness experiment, Dockerfile |
| **Tapendu Das** | Database: schema, indexes (including the `UNIQUE` index on `api_key` that makes the per-request lookup sub-ms), seed data, `crud.py` SQL, Postgres service in compose |

`crud.py`'s signature is the agreed boundary: `async def get_rule_by_api_key(session, api_key) -> Rule | None`. Only the DB owner edits the SQL inside.

---

## Limitations and Future Work

- **No exact algorithm in the comparison.** Sliding window log would provide a "no-leak, O(N) memory" reference point. Its absence means fixed window's boundary leak is demonstrated against its own limit rather than against ground truth. Adding it is the natural next step.
- **Rule fetch is a per-request DB round-trip.** `LISTEN`/`NOTIFY`-based invalidation would preserve near-zero staleness without the hop.
- **Redis is a single instance.** A cluster/sentinel deployment is a production requirement out of scope here.
- **Locust uses a single API key.** Multi-tenant load (thousands of distinct clients) would stress the Redis keyspace differently.
- **Leaky bucket** is the natural fourth arm and would complete the burst-behavior spectrum.

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
