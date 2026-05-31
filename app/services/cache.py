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


async def invalidate_user_cache(*user_ids: str | int | None) -> None:
    cursor = 0
    keys: list[str] = []
    patterns = [f"rec:{user_id}:*" for user_id in {str(uid) for uid in user_ids if uid is not None}]
    if not patterns:
        return

    while True:
        cursor, batch = await with_timeout(
            redis_client.scan(cursor=cursor, match="rec:*", count=100)
        )
        for key in batch:
            if any(_matches_rec_pattern(key, pattern) for pattern in patterns):
                keys.append(key)
        if cursor == 0:
            break
    if keys:
        await with_timeout(redis_client.delete(*keys))


def _matches_rec_pattern(key: str, pattern: str) -> bool:
    prefix = pattern.removesuffix("*")
    return key.startswith(prefix)


async def close_redis_connection() -> None:
    await redis_client.aclose()
