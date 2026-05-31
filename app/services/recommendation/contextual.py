import re
from typing import Any

from bson import ObjectId

from app.config import get_settings
from app.db import db
from app.services.ids import resolve_item_id
from app.services.timeouts import with_timeout
from app.services.embeddings import inferred_tags

from .common import local_vector_search, public_item, seen_item_ids, top_popular_items


settings = get_settings()
_TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "of",
    "part",
    "episode",
    "movie",
    "film",
}
_FRANCHISE_TITLE_PATTERNS = {
    "marvel": [
        "ant[- ]?man",
        "avengers",
        "black panther",
        "captain america",
        "doctor strange",
        "guardians of the galaxy",
        "hulk",
        "iron man",
        "marvel",
        "spider[- ]?man",
        "thor",
        "wolverine",
        "x[- ]?men",
    ],
    "star wars": ["star wars"],
    "lord of the rings": ["hobbit", "lord of the rings"],
    "harry potter": ["fantastic beasts", "harry potter"],
    "batman": ["batman", "dark knight"],
}


def title_tokens(title: str | None) -> set[str]:
    if not title:
        return set()
    return {
        token
        for token in re.findall(r"[a-z0-9]+", title.lower())
        if len(token) > 2 and token not in _TITLE_STOPWORDS and not token.isdigit()
    }


def context_similarity_boost(context_item: dict[str, Any], candidate_item: dict[str, Any]) -> float:
    context_labels = semantic_labels(context_item)
    candidate_labels = semantic_labels(candidate_item)
    label_overlap = len(context_labels & candidate_labels)

    context_title_tokens = title_tokens(context_item.get("title"))
    candidate_title_tokens = title_tokens(candidate_item.get("title"))
    title_overlap = len(context_title_tokens & candidate_title_tokens)

    return 1 + min(label_overlap * 0.45 + title_overlap * 0.9, 3.0)


def semantic_labels(item: dict[str, Any]) -> set[str]:
    text = " ".join(
        [
            str(item.get("title") or ""),
            " ".join(item.get("tags") or []),
            " ".join(item.get("genres") or []),
        ]
    )
    return set(item.get("tags") or []) | set(item.get("genres") or []) | set(inferred_tags(text))


def franchise_title_filters(labels: set[str]) -> list[dict[str, Any]]:
    filters = []
    for label in labels:
        for pattern in _FRANCHISE_TITLE_PATTERNS.get(label, []):
            filters.append({"title": {"$regex": pattern, "$options": "i"}})
    return filters


async def contextual_item_rec(
    context: str | int | ObjectId,
    user_id: ObjectId | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Item-to-item recommendations for a detail page context.
    Uses the current movie embedding first, then falls back to genre/tag overlap.
    """
    try:
        context_oid = await resolve_item_id(context)
        context_item = await with_timeout(
            db.items.find_one(
                {"_id": context_oid},
                {"embedding": 1, "tags": 1, "genres": 1, "title": 1},
            ),
            timeout_ms=20000,
        )
    except Exception:
        return []
    if not context_item:
        return []

    seen_ids = await seen_item_ids(user_id) if user_id else []
    excluded_ids = list(set(seen_ids + [context_oid]))
    docs: list[dict[str, Any]] = []
    embedding = context_item.get("embedding") or []

    if len(embedding) == 1536:
        pipeline: list[dict[str, Any]] = [
            {
                "$vectorSearch": {
                    "index": settings.vector_index_name,
                    "path": "embedding",
                    "queryVector": embedding,
                    "numCandidates": max(limit * 40, 200),
                    "limit": max(limit * 8, 80),
                }
            },
            {"$match": {"_id": {"$nin": excluded_ids}, "available": True}},
            {"$addFields": {"recScore": {"$meta": "vectorSearchScore"}}},
            {"$limit": limit},
        ]
        try:
            docs = await with_timeout(
                db.items.aggregate(pipeline).to_list(length=max(limit * 2, 40)),
                timeout_ms=3000,
            )
        except Exception:
            try:
                docs = await with_timeout(local_vector_search(embedding, excluded_ids, limit), timeout_ms=8000)
            except Exception:
                docs = []

    lexical_docs: list[dict[str, Any]] = []
    labels = semantic_labels(context_item)
    if labels:
        lexical_should = [{"tags": {"$in": list(labels)}}, {"genres": {"$in": list(labels)}}]
        lexical_should.extend(franchise_title_filters(labels))
        try:
            lexical_docs = await with_timeout(
                db.items.find(
                    {
                        "_id": {"$nin": excluded_ids},
                        "available": True,
                        "$or": lexical_should,
                    }
                )
                .sort("popularity", -1)
                .limit(max(limit * 3, 60))
                .to_list(length=max(limit * 3, 60)),
                timeout_ms=3000,
            )
        except Exception:
            lexical_docs = []

    merged_docs: dict[ObjectId, dict[str, Any]] = {doc["_id"]: doc for doc in docs}
    for doc in lexical_docs:
        merged_docs.setdefault(doc["_id"], doc)
    docs = list(merged_docs.values())

    if not docs:
        labels = list(labels)
        if not labels:
            return await top_popular_items(limit)
        try:
            docs = await with_timeout(
                db.items.find(
                    {
                        "_id": {"$nin": excluded_ids},
                        "available": True,
                        "$or": [{"tags": {"$in": labels}}, {"genres": {"$in": labels}}],
                    }
                )
                .sort("popularity", -1)
                .limit(max(limit * 2, 40))
                .to_list(length=max(limit * 2, 40)),
                timeout_ms=3000,
            )
        except Exception:
            return await top_popular_items(limit)

    recs = []
    for doc in docs:
        item = public_item(doc)
        boost = context_similarity_boost(context_item, doc)
        if "recScore" in doc:
            score = float(doc.get("recScore", 0)) * boost
        else:
            # For lexical context matches, relevance should come from overlap first.
            # Popularity is only a light tie-breaker so broad genres do not drown
            # franchise matches such as Avengers/Iron Man/Thor.
            score = boost + (float(doc.get("popularity", 0)) * 0.03)
        recs.append({"item": item, "score": score, "source": "context"})
    return sorted(recs, key=lambda rec: rec["score"], reverse=True)[:limit]
