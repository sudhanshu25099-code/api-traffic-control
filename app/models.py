from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


Algorithm = Literal["fixed_window", "token_bucket"]


class Rule(BaseModel):
    """Access policy for one API key — the static parameters from Postgres."""
    api_key: str
    client_name: str
    tier: str
    algorithm: Algorithm
    capacity: int
    refill_rate: float
    window_seconds: int


@dataclass(frozen=True)
class Decision:
    """Result of one rate-limit evaluation."""
    allowed: bool
    remaining: int
    reset_at: int  # unix seconds
    limit: int