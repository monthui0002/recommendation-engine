"""
Admin / maintenance routes.
These endpoints should be protected or only called during off-peak hours.
"""

import asyncio
import json
import logging
import urllib.request
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.database import db

router = APIRouter(prefix="/admin", tags=["admin"])
settings = get_settings()
logger = logging.getLogger(__name__)

OMDB_URL = "https://www.omdbapi.com/"
# Max concurrent OMDB requests (free tier: ~1 req/s cap)
_SEMAPHORE = asyncio.Semaphore(5)


def _fetch_omdb(imdb_id: str, api_key: str) -> dict[str, Any]:
    """Blocking OMDB fetch — run inside asyncio.to_thread."""
    url = f"{OMDB_URL}?i=tt{imdb_id.lstrip('t')}&apikey={api_key}"
    with urllib.request.urlopen(url, timeout=8) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


async def _fetch_poster(imdb_id: str) -> str | None:
    """Return poster URL for a given imdbId, or None if unavailable."""
    async with _SEMAPHORE:
        try:
            data = await asyncio.to_thread(_fetch_omdb, imdb_id, settings.omdb_api_key)
            poster = data.get("Poster")
            return poster if poster and poster != "N/A" else None
        except Exception as exc:
            logger.warning("OMDB fetch failed for %s: %s", imdb_id, exc)
            return None


@router.post("/posters/backfill")
async def backfill_posters(
    batch_size: int = Query(50, ge=1, le=200, description="Items per batch"),
    delay_ms: int = Query(200, ge=0, le=2000, description="Delay between batches (ms)"),
    overwrite: bool = Query(False, description="Re-fetch even if poster already exists"),
) -> StreamingResponse:
    """
    Fetch poster URLs from OMDB for all items that have an imdbId but no poster.
    Streams newline-delimited JSON progress updates so the caller can follow along.

    Parameters
    ----------
    batch_size : items to process per round (default 50)
    delay_ms   : pause between batches to respect OMDB rate limits (default 200 ms)
    overwrite  : if True, re-fetch posters even for items that already have one
    """

    async def _run():
        query: dict[str, Any] = {"imdbId": {"$exists": True, "$ne": None}}
        if not overwrite:
            query["$or"] = [{"poster": {"$exists": False}}, {"poster": None}]

        total = await db.items.count_documents(query)
        yield _event("start", {"total": total, "batch_size": batch_size})

        updated = skipped = failed = processed = 0
        cursor = db.items.find(query, {"_id": 1, "imdbId": 1, "title": 1, "poster": 1})

        batch: list[dict] = []
        async for doc in cursor:
            if doc.get("poster"):
                skipped += 1
                continue
    
            batch.append(doc)
            if len(batch) < batch_size:
                continue

            b_updated, b_failed = await _process_batch(batch)
            updated += b_updated
            failed += b_failed
            processed += len(batch)

            yield _event("progress", {
                "processed": processed,
                "total": total,
                "updated": updated,
                "failed": failed,
                "pct": round(processed / total * 100, 1) if total else 100,
            })
            batch = []
            if delay_ms:
                await asyncio.sleep(delay_ms / 1000)

        # Remaining items
        if batch:
            b_updated, b_failed = await _process_batch(batch)
            updated += b_updated
            failed += b_failed
            processed += len(batch)

        yield _event("done", {
            "processed": processed,
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
        })

    return StreamingResponse(_run(), media_type="text/event-stream")


async def _process_batch(docs: list[dict]) -> tuple[int, int]:
    """Fetch posters for a batch concurrently, then bulk-write to MongoDB."""
    tasks = [_fetch_poster(doc["imdbId"]) for doc in docs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    ops = []
    updated = failed = 0
    for doc, result in zip(docs, results):
        if isinstance(result, Exception) or result is None:
            failed += 1
            continue
        ops.append((doc["_id"], result))
        updated += 1

    if ops:
        # Bulk write — one round-trip for the whole batch
        from pymongo import UpdateOne
        await db.items.bulk_write(
            [UpdateOne({"_id": _id}, {"$set": {"poster": poster}}) for _id, poster in ops],
            ordered=False,
        )

    return updated, failed


def _event(event_type: str, data: dict) -> str:
    return json.dumps({"event": event_type, **data}) + "\n"
