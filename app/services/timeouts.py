import asyncio
from collections.abc import Awaitable
from typing import TypeVar

from app.core.config import get_settings


T = TypeVar("T")
settings = get_settings()


async def with_timeout(awaitable: Awaitable[T], timeout_ms: int | None = None) -> T:
    timeout = (timeout_ms or settings.infra_timeout_ms) / 1000
    return await asyncio.wait_for(awaitable, timeout=timeout)
