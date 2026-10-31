"""
Run with:
    locust -f tests/locustfile.py --headless -u 1000 -r 100 -t 60s \
           --host http://localhost:8000

Set LOCUST_API_KEY to target a specific tier. Default: enterprise-key (1000/min).
Run Locust on a container/host separate from FastAPI — otherwise you
measure CPU contention, not the limiter.
"""
import os

from locust import HttpUser, between, task

API_KEY = os.getenv("LOCUST_API_KEY", "enterprise-key")


class ApiUser(HttpUser):
    wait_time = between(0, 0.1)

    def on_start(self) -> None:
        self.headers = {"X-API-Key": API_KEY}

    @task(3)
    def light(self) -> None:
        self.client.get("/api/data", headers=self.headers, name="/api/data")

    @task(1)
    def heavy(self) -> None:
        self.client.get(
            "/api/heavy-computation",
            headers=self.headers,
            name="/api/heavy-computation",
        )