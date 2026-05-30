from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from app.services.search import movie_search

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/movies")
async def search_movies(
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Max results to return"),
    mode: Literal["hybrid", "text", "vector"] = Query(
        "hybrid",
        description=(
            "Search mode: "
            "'hybrid' = BM25 + vector via RRF (default), "
            "'text' = Atlas Search BM25 only, "
            "'vector' = Atlas Vector Search only"
        ),
    ),
) -> dict[str, Any]:
    """
    Search movies by text query using Atlas hybrid search.

    Combines Atlas full-text search (BM25) and vector search (ANN)
    and merges results with Reciprocal Rank Fusion (RRF).
    """
    results = await movie_search(q, limit=limit, mode=mode)
    if not results:
        raise HTTPException(status_code=404, detail="No results found")
    return {
        "query": q,
        "mode": mode,
        "count": len(results),
        "items": results,
    }
