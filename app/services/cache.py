import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import get_settings
from app.core.database import redis_client
from app.services.timeouts import with_timeout


settings = get_settings()


async def with_cache(key: str, ttl: int, fn: Callable[[], Awaitable[Any]]) -> Any:
    try:
        cached = await with_timeout(redis_client.get(key))
        if cached is not None:
            return json.loads(cached)
    except Exception:
        return await fn()

    value = await fn()
    try:
        await with_timeout(redis_client.set(key, json.dumps(value, default=str), ex=ttl))
    except Exception:
        pass
    return value


async def invalidate_user_cache(user_id: str) -> None:
    pattern = f"rec:{user_id}:*"
    cursor = 0
    keys: list[str] = []
    while True:
        cursor, batch = await with_timeout(
            redis_client.scan(cursor=cursor, match=pattern, count=100)
        )
        keys.extend(batch)
        if cursor == 0:
            break
    if keys:
        await with_timeout(redis_client.delete(*keys))


async def close_redis_connection() -> None:
    await redis_client.aclose()
