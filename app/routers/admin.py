from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.database import SessionLocal

router = APIRouter(prefix="/admin", tags=["admin"])


class RuleUpdate(BaseModel):
    capacity: int | None = None
    refill_rate: float | None = None
    window_seconds: int | None = None
    algorithm: str | None = None


@router.patch("/rules/{api_key}")
async def update_rule(api_key: str, body: RuleUpdate) -> dict:
    """Used by scripts/staleness_test.py to mutate a live rule."""
    sets: list[str] = []
    params: dict = {"api_key": api_key}

    if body.capacity is not None:
        sets.append("capacity = :capacity")
        params["capacity"] = body.capacity
    if body.refill_rate is not None:
        sets.append("refill_rate = :refill_rate")
        params["refill_rate"] = body.refill_rate
    if body.window_seconds is not None:
        sets.append("window_seconds = :window_seconds")
        params["window_seconds"] = body.window_seconds
    if body.algorithm is not None:
        if body.algorithm not in ("fixed_window", "token_bucket"):
            raise HTTPException(400, "Invalid algorithm")
        sets.append("algorithm = :algorithm")
        params["algorithm"] = body.algorithm

    if not sets:
        raise HTTPException(400, "No fields to update")

    sql = text(
        f"""
        UPDATE rate_limit_rules r
           SET {', '.join(sets)}
          FROM api_keys ak
         WHERE r.api_key_id = ak.id
           AND ak.api_key = :api_key
        RETURNING r.id
        """
    )
    async with SessionLocal() as session:
        result = await session.execute(sql, params)
        await session.commit()
        row = result.first()

    if row is None:
        raise HTTPException(404, "Rule not found")
    return {"updated": True}