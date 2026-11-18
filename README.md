# API Traffic Control: Distributed Atomic Rate Limiter

An algorithmic and distributed systems implementation of high-throughput API rate limiting using PostgreSQL for durable policy configuration and Redis with atomic pre-compiled Lua scripts (EVALSHA) for sub-millisecond, race-free state evaluation.

Grounded in theoretical research from:
Saleem, U. (2026). *A Comparative Survey of API Rate-Limiting Algorithms: Token Bucket, Leaky Bucket, and Sliding Window*. Research Square. DOI: 10.21203/rs.3.rs-10948293/v1.

---

## Academic Metadata

- **Institution:** Faculty of Technology, University of Delhi
- **Course:** Analysis and Design of Algorithms (ADA)
- **Course Code:** 2932812301
- **Authors:**
  - Sudhanshu Shekhar Jha (Roll No. 25293916104)
  - Tapendu Das (Roll No. 25293916107)
- **Date:** 17 November 2026
- **Repository:** https://github.com/sudhanshu25099-code/api-traffic-control

---

## Problem Statement

Rate limiting is an online decision problem: for every incoming HTTP request, an API gateway must decide whether to admit (`HTTP 200`) or reject (`HTTP 429 Too Many Requests`) within sub-millisecond overhead. Under concurrent load across multiple asynchronous coroutines or distributed server instances, naive counter implementations suffer from race conditions that allow significant over-admission.

### Formal Definition
- **Input:** Continuous request stream $(k, t)$ where $k$ is the client API key and $t$ is the arrival timestamp, evaluated against a tenant policy (algorithm, limit $C$, window $W$ or replenishment rate $r$).
- **Output:** `ALLOW` (HTTP 200 with quota headers) or `REJECT` (HTTP 429 with `Retry-After` header); `HTTP 401 Unauthorized` for unregistered keys.
- **Constraints:** $C \ge 1, W > 0, r > 0$; zero over-admission under concurrent bursts; $O(1)$ time and space complexity per key.

---

## Architectural Design: Decoupling Policy from State

A primary failure mode in distributed rate limiting is database lock contention. Storing transient counters in a relational database requires `SELECT ... FOR UPDATE` row locks, which serializes concurrent requests and collapses throughput.

This project implements a dual-tier architecture:
1. **Durable Policy Tier (PostgreSQL):** Stores client metadata, tier assignments, quota limits, and window sizes. Policies are fetched via a single indexed query ($O(\log K)$) on `api_key` (~1.5 ms). No counters are written to PostgreSQL.
2. **Transient State Tier (Redis + Lua):** Counters and timestamps reside in Redis memory. Evaluation is executed via pre-compiled Lua scripts (`EVALSHA`), guaranteeing single-threaded atomic execution (~0.8 ms) without distributed locks.

```
                          +-------------------------+
                          |   FastAPI Application   |
                          |   ASGI Rate Middleware  |
   +----------+           |                         |           +--------------+
   |  Client  |--Request->| 1. Read Policy (SQL) ---+---------->|  PostgreSQL  |
   +----------+           |           |             |           |  (Policies)  |
        ^                 |           v             |           +--------------+
        |                 | 2. EVALSHA(script, key) |
        |    Response     |           |             |           +--------------+
        |  (200 or 429)   |           v             |           |    Redis     |
        +-----------------| 3. Inject RFC Headers --+<----------|  (Transient  |
                          |                         |           |  State, Lua) |
                          +-------------------------+           +--------------+
```

---

## Algorithmic Mechanics and Complexity

Two production algorithms are implemented in atomic Redis Lua scripts, compared against in-process memory and relational row-lock baselines.

| Algorithm | Best Time | Average Time | Worst Time | Space / Key | Burst Tolerance |
|---|---|---|---|---|---|
| **Fixed Window Counter (Redis Lua)** | Omega(1) | Theta(1) | O(1) | O(1) (56 B measured) | Permits up to 2x limit at window boundary |
| **Token Bucket (Redis Lua)** | Omega(1) | Theta(1) | O(1) | O(1) (112 B measured) | Smooths traffic; allows bursts up to capacity C |
| **Sliding Window Log (Baseline)** | O(1) | O(k) | O(n) | O(n) (97 KB at n=1,000) | Strict zero-burst ceiling |
| **In-Process Counter (Baseline)** | O(1) | O(1) | O(1) | O(1) per worker | Broken under concurrency (60% to 100% leak) |
| **PostgreSQL Row-Lock (Baseline)** | O(1) | O(1) + wait | O(n) wait | 1 row | Serializes requests; throughput collapses |

### Algorithmic Formulations
- **Fixed Window Counter:** Executes `INCR key`. On the first request ($n = 1$), sets `EXPIRE key window`. Admits if $n \le C$.
- **Token Bucket:** Computes continuous token refill lazily on request arrival: $\Delta t = t_{now} - t_{last}$, $\text{tokens} = \min(C, \text{tokens} + \Delta t \cdot r)$. Admits and decrements if $\text{tokens} \ge 1$. Uses `redis.call('TIME')` to prevent host clock drift.

---

## Tech Stack and Versions

As benchmarked on AMD Ryzen AI 5 340 (6 cores / 12 threads), 16 GB DDR5 RAM, Windows 11 24H2 (Build 26300):

- **Application Runtime:** Python 3.11.10-slim (Docker container), Python 3.13.15 (Host)
- **Web Framework:** FastAPI 0.115.6 (Pure ASGI Middleware)
- **ASGI Server:** Uvicorn 0.32.1
- **Database Engine:** PostgreSQL 16.15 (`postgres:16-alpine`)
- **Database Drivers:** asyncpg 0.30.0, SQLAlchemy 2.0.36 (asyncio)
- **State Store:** Redis 7.4.12 (`redis:7-alpine`) with Lua 5.1 engine
- **Load Testing:** Locust 2.32.5
- **Testing Framework:** pytest 8.3.4, pytest-asyncio 0.24.0, httpx 0.28.1
- **Frontend:** HTML5, CSS3, Vanilla ES6 JavaScript (Hallmark Design System)

---

## Project Structure

```
api-traffic-control/
|-- app/
|   |-- limiters/                # In-process Python baseline limiters (demonstrates race conditions)
|   |   |-- fixed_window.py
|   |   `-- token_bucket.py
|   |-- lua/                     # Pre-compiled Redis Lua scripts executed via EVALSHA
|   |   |-- fixed_window.lua
|   |   `-- token_bucket.lua
|   |-- routers/                 # FastAPI routing (data endpoints, admin key management)
|   |   |-- admin.py
|   |   `-- api.py
|   |-- config.py                # Environment configuration via pydantic-settings
|   |-- crud.py                  # Raw async SQL queries for PostgreSQL policy lookups
|   |-- database.py              # Async SQLAlchemy engine and session management
|   |-- main.py                  # Application entry point and lifespan handlers
|   |-- middleware.py            # High-performance pure ASGI rate-limiting middleware
|   |-- models.py                # Pydantic schema validation models
|   `-- redis_client.py          # Redis connection pool and EVALSHA script loader
|-- docs/
|   |-- benchmark_sweep_results.csv # Locust sweep data from 10 to 2,000 users
|   `-- project_report.html         # Formatted engineering and academic research report
|-- frontend/                    # Interactive Test Lab and Plan Management Dashboard
|   |-- base.css
|   |-- index.html
|   |-- style.css
|   `-- tokens.css
|-- scripts/
|   `-- staleness_test.py        # Live database policy mutation and propagation benchmark
|-- sql/
|   |-- schema.sql               # PostgreSQL tables, constraints, and B-tree indexes
|   `-- seed.sql                 # Seed client keys for Free, Pro, and Enterprise tiers
|-- tests/
|   |-- locustfile.py            # Locust load generation scenario
|   `-- test_algorithms.py       # Pytest unit and integration test suite
|-- docker-compose.yml           # Multi-container orchestration (App, PostgreSQL, Redis)
|-- Dockerfile                   # Multi-stage Python 3.11 container build
|-- requirements.txt             # Locked production dependencies
`-- README.md                    # Project documentation
```

---

## Local Setup and Execution

### Prerequisites
- Docker Engine and Docker Compose (Docker Desktop on Windows/macOS, or Docker Compose v2 on Linux).
- Optional for host development: Python 3.11+, Git, curl.

### Step 1: Clone Repository and Configure Environment
Clone the repository and copy the environment configuration:
```bash
git clone https://github.com/sudhanshu25099-code/api-traffic-control.git
cd api-traffic-control
cp .env.example .env
```

Ensure `.env` matches your local ports and credentials:
```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=traffic
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

REDIS_HOST=redis
REDIS_PORT=6379

DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/traffic
REDIS_URL=redis://redis:6379/0
```

### Step 2: Start Containers with Docker Compose
Start the application, PostgreSQL, and Redis in isolated containers:
```bash
docker compose up -d --build
```

Healthchecks ensure the FastAPI application waits until both PostgreSQL and Redis are fully initialized and healthy. Verify running containers:
```bash
docker compose ps
```

### Step 3: Initialize Database Schema and Seed Data
Execute the SQL migrations inside the running PostgreSQL container:
```bash
docker compose exec -T postgres psql -U postgres -d traffic < sql/schema.sql
docker compose exec -T postgres psql -U postgres -d traffic < sql/seed.sql
```

The seed script creates the following client accounts:
- `demo-key`: Fixed Window, capacity 5, window 60s (Free Tier)
- `pro-key`: Token Bucket, capacity 100, refill rate 1.67 tokens/s (Pro Tier)
- `enterprise-key`: Fixed Window, capacity 1000, window 60s (Enterprise Tier)

### Step 4: Verify API Endpoints
Send an authorized request using `curl`:
```bash
curl -i -H "X-API-Key: demo-key" http://localhost:8000/api/data
```

Expected HTTP response headers:
```http
HTTP/1.1 200 OK
content-type: application/json
x-ratelimit-limit: 5
x-ratelimit-remaining: 4
x-ratelimit-reset: 60
```

When 5 requests are exhausted within the window, the 6th returns:
```http
HTTP/1.1 429 Too Many Requests
retry-after: 60
x-ratelimit-limit: 5
x-ratelimit-remaining: 0
x-ratelimit-reset: 60
```

Interactive OpenAPI Swagger documentation is available at:
`http://localhost:8000/docs`

### Step 5: Launch the Frontend Test Lab
The frontend is a lightweight client interface that connects directly to the backend. It can be opened directly or served using Python's static server:
```bash
cd frontend
python -m http.server 3000
```
Open `http://localhost:3000` in your web browser. The dashboard includes live plan displays, key input forms, and an in-browser test lab running boundary and concurrency validations.

---

## Verification and Benchmarking

### 1. Correctness Test Suite (pytest)
Run unit and integration tests inside the application container:
```bash
docker compose exec app pytest tests/test_algorithms.py -v
```

The suite validates:
- `test_fixed_window_allows_then_rejects`: First $C$ allowed, $(C+1)$-th rejected with 429.
- `test_fixed_window_race_condition`: Contrasts in-process over-admission with Redis Lua isolation.
- `test_token_bucket_refill`: Validates continuous fractional refill math.
- `test_token_bucket_zero_capacity`: Edge case verification (rejects safely with zero divide errors).
- `test_headers_present`: RFC compliance for `X-RateLimit-*` headers.
- `test_unknown_key_returns_401`: Unauthorized access rejection.
- `test_boundary_returns_429`: Rapid burst rejection and `Retry-After` calculation.

### 2. Live Rule Invalidation Test (`scripts/staleness_test.py`)
To test zero-staleness dynamic policy updates without restarting or flushing caches:
```bash
docker compose exec app python scripts/staleness_test.py
```
This mutates a client limit in PostgreSQL mid-flight and measures subsequent requests. Empirical result: **0 out of 200 stale requests**, confirming policy propagation in under 2 ms.

### 3. Locust Load Testing Sweep
Execute multi-user load testing across 10 to 2,000 concurrent virtual users:
```bash
locust -f tests/locustfile.py --headless -u 1000 -r 100 -t 60s --host http://localhost:8000
```

---

## Experimental Results and Empirical Findings

### Concurrency Race Test (Limit = 10, 20 Trials per Concurrency Size)
The table below documents why in-process memory rate limiters are fundamentally broken under concurrent async volume, and demonstrates the mathematical correctness of Redis Lua:

| Test Scenario | Parallel Requests | In-Process Python Allowed | Redis + Lua Allowed | Result |
|---|---|---|---|---|
| **Unit Test (`test_algorithms.py`)** | 20 coroutines (1 run) | 16 allowed | 10 allowed | In-process leaks 60% excess traffic |
| **Burst Sweep (20 trials)** | 20 parallel requests | 20 allowed | 10 allowed | In-process collapses (100% leak) |
| **Burst Sweep (20 trials)** | 100 parallel requests | 100 allowed | 10 allowed | In-process collapses (100% leak) |
| **Burst Sweep (20 trials)** | 1,000 parallel requests | 1,000 allowed | 10 allowed | In-process collapses (100% leak) |

*Redis + Lua maintained exact compliance (standard deviation sigma = 0) across all trials.*

### Multi-Substrate Comparison at 1,000 Concurrent Users

| Substrate | Throughput (req/s) | p50 Latency (ms) | p95 Latency (ms) | p99 Latency (ms) | Correctness |
|---|---|---|---|---|---|
| **Fixed Window (Redis Lua)** | 544.2 | 1,700 | 3,700 | 6,200 | 100% compliant |
| **Token Bucket (Redis Lua)** | 529.1 | 1,700 | 3,900 | 6,400 | 100% compliant |
| **PostgreSQL Row-Lock** | 24.1 | 38,000 | 72,000 | 95,000 | Database lock saturation |
| **In-Process Counter** | 1,520.0 | 580 | 1,450 | 2,300 | Failed: 98% over-admission leak |

### Architectural Takeaways
1. **Little's Law Validation:** Throughput remains flat between 612 req/s and 519 req/s across a 200-fold increase in concurrent users (10 to 2,000). The growth in p95 latency is purely socket queueing in a single container ($L = \lambda W \implies W \approx 1,000 / 544 \approx 1.83\text{ s}$), confirming constant $O(1)$ algorithmic execution.
2. **Database Row Lock Failure:** Implementing rate limiting with `SELECT ... FOR UPDATE` row locks results in severe lock queuing, collapsing throughput from 210 req/s down to 12.8 req/s at 2,000 users.
3. **Memory Footprint:** Fixed Window requires 56 bytes per key, and Token Bucket requires 112 bytes per key. At 10,000 active clients, total Redis memory is ~1.1 MB, compared to ~970 MB for a Sliding Window Log baseline (880x reduction).

---

## Individual Contributions

| Contribution Area | Team Member |
|---|---|
| **Algorithm Design and Mathematical Mechanics** | Sudhanshu Shekhar Jha and Tapendu Das |
| **Backend Implementation (FastAPI, Redis Lua, PostgreSQL)** | Sudhanshu Shekhar Jha |
| **Theoretical Complexity Analysis and Proofs** | Sudhanshu Shekhar Jha |
| **Load and Concurrency Benchmarks, Empirical Graphs** | Tapendu Das |
| **Frontend Test Lab and Hallmark User Interface** | Tapendu Das |
| **Technical Report and Presentation Deck** | Sudhanshu Shekhar Jha and Tapendu Das |

---

## References

1. Saleem, U. (2026). *A Comparative Survey of API Rate-Limiting Algorithms: Token Bucket, Leaky Bucket, and Sliding Window*. Research Square (Preprint). DOI: [10.21203/rs.3.rs-10948293/v1](https://doi.org/10.21203/rs.3.rs-10948293/v1).
2. Bartkov, M., and Borovikov, D. (2022). *Selection of a Suitable Algorithm for the Implementation of Rate-Limiter Based on Bucket4j*. International Journal of Online and Biomedical Engineering (iJOE), 18(4), 52-63.
3. Redis Documentation. *Scripting with Lua and EVALSHA*. https://redis.io/docs/manual/programmability/eval-intro/
4. PostgreSQL Global Development Group. *Explicit Locking and Concurrency Control*. https://www.postgresql.org/docs/current/explicit-locking.html
