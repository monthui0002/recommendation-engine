from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from app.services.cache import with_cache
from app.services.recommendations import top_popular_items
from app.services.search import movie_by_imdb_id, movie_search

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/movies/popular")
async def popular_movies(
    limit: int = Query(20, ge=1, le=100, description="Max results to return"),
) -> dict[str, Any]:
    items = await with_cache(
        f"search:popular:v1:limit={limit}",
        300,
        lambda: top_popular_items(limit),
    )
    return {
        "type": "popular",
        "count": len(items),
        "items": items,
    }


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


@router.get("/movies/imdb/{imdb_id}")
async def get_movie_by_imdb_id(imdb_id: str) -> dict[str, Any]:
    movie = await movie_by_imdb_id(imdb_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")
    return {"item": movie}
