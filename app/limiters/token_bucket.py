import time
from fastapi import HTTPException
from app.redis_client import redis_pool
# Import the Lua script written by Tapendu
from app.lua.scripts import TOKEN_BUCKET_LUA_SCRIPT 

async def token_bucket_limiter(client_ip: str, capacity: int = 5, refill_rate: float = 1.0):
    now = time.time()
    redis_key = f"rate_limit:tb:{client_ip}"

    allowed = await redis_pool.eval(
        TOKEN_BUCKET_LUA_SCRIPT, 
        1, 
        redis_key, 
        capacity, 
        refill_rate, 
        now
    )
    
    if not allowed:
        raise HTTPException(
            status_code=429, 
            detail={"error": "Too Many Requests", "algorithm": "Token Bucket", "message": "Bucket empty"}
        )