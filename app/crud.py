from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Rule


_RULE_QUERY = text(
    """
    SELECT ak.api_key,
           c.name   AS client_name,
           c.tier   AS tier,
           r.algorithm,
           r.capacity,
           r.refill_rate,
           r.window_seconds
    FROM api_keys ak
    JOIN clients c          ON c.id = ak.client_id
    JOIN rate_limit_rules r ON r.api_key_id = ak.id
    WHERE ak.api_key = :api_key
      AND ak.active = TRUE
    """
)


async def get_rule_by_api_key(session: AsyncSession, api_key: str) -> Rule | None:
    """Single indexed lookup. Returns None for unknown / inactive keys."""
    row = (await session.execute(_RULE_QUERY, {"api_key": api_key})).mappings().first()
    return Rule(**row) if row else None