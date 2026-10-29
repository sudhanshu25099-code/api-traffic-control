import time
from fastapi import HTTPException
from app.redis_client import redis_pool

async def fixed_window_limiter(client_ip: str, limit: int = 5, window_size: int = 10):
    current_window = int(time.time() // window_size)
    redis_key = f"rate_limit:fw:{client_ip}:{current_window}"
    
    current_count = await redis_pool.incr(redis_key)
    
    if current_count == 1:
        await redis_pool.expire(redis_key, window_size)
        
    if current_count > limit:
        raise HTTPException(
            status_code=429, 
            detail={"error": "Too Many Requests", "algorithm": "Fixed Window", "retry_after_seconds": window_size}
        )