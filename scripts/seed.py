import argparse
import asyncio
import csv
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId
from pymongo import UpdateOne

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.embeddings import get_embedding, inferred_tags


DATA_DIR = ROOT / "data"
POSITIVE_RATING_THRESHOLD = 3.5
BATCH_SIZE = 5000


def read_csv(name: str) -> list[dict[str, str]]:
    path = DATA_DIR / name
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def parse_epoch(value: str) -> datetime:
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def split_genres(value: str) -> list[str]:
    if not value or value == "(no genres listed)":
        return []
    return value.split("|")


async def insert_many(collection: Any, docs: list[dict[str, Any]]) -> None:
    for start in range(0, len(docs), BATCH_SIZE):
        await collection.insert_many(docs[start : start + BATCH_SIZE])


async def bulk_write(collection: Any, operations: list[UpdateOne]) -> None:
    for start in range(0, len(operations), BATCH_SIZE):
        await collection.bulk_write(operations[start : start + BATCH_SIZE], ordered=False)


async def existing_id_map(collection: Any, key: str) -> dict[int, ObjectId]:
    docs = await collection.find({key: {"$exists": True}}, {key: 1}).to_list(length=None)
    return {int(doc[key]): doc["_id"] for doc in docs}


async def seed(reset: bool = False) -> None:
    from app.db import create_indexes, db
    from app.services.recommendations import implicit_weight
    from app.utils import utcnow

    movies = read_csv("movies.csv")
    ratings = read_csv("ratings.csv")
    tags = read_csv("tags.csv")
    links = read_csv("links.csv")

    if reset:
        await db.users.delete_many({})
        await db.items.delete_many({})
        await db.interactions.delete_many({})
        await db.explorations.delete_many({})
        await db.user_profiles.delete_many({})
        await db.failed_interaction_events.delete_many({})
    await create_indexes()

    ratings_by_movie: dict[int, list[float]] = defaultdict(list)
    first_rating_at_by_movie: dict[int, datetime] = {}
    user_ids: set[int] = set()
    first_seen_by_user: dict[int, datetime] = {}
    liked_genres_by_user: dict[int, Counter[str]] = defaultdict(Counter)

    for row in ratings:
        user_id = int(row["userId"])
        movie_id = int(row["movieId"])
        rating = float(row["rating"])
        timestamp = parse_epoch(row["timestamp"])
        user_ids.add(user_id)
        ratings_by_movie[movie_id].append(rating)
        first_seen_by_user[user_id] = min(first_seen_by_user.get(user_id, timestamp), timestamp)
        first_rating_at_by_movie[movie_id] = min(
            first_rating_at_by_movie.get(movie_id, timestamp), timestamp
        )

    movie_genres = {int(row["movieId"]): split_genres(row["genres"]) for row in movies}
    for row in ratings:
        rating = float(row["rating"])
        if rating >= POSITIVE_RATING_THRESHOLD:
            liked_genres_by_user[int(row["userId"])].update(movie_genres.get(int(row["movieId"]), []))

    tags_by_movie: dict[int, Counter[str]] = defaultdict(Counter)
    for row in tags:
        user_ids.add(int(row["userId"]))
        tag = row["tag"].strip().lower()
        if tag:
            tags_by_movie[int(row["movieId"])][tag] += 1

    links_by_movie = {
        int(row["movieId"]): {
            "imdbId": row["imdbId"] or None,
            "tmdbId": int(row["tmdbId"]) if row["tmdbId"] else None,
        }
        for row in links
    }

    now = utcnow()
    user_id_map = await existing_id_map(db.users, "movielensUserId") if not reset else {}
    for user_id in user_ids:
        user_id_map.setdefault(user_id, ObjectId())

    user_docs = []
    for user_id in sorted(user_ids):
        preferences = [genre for genre, _count in liked_genres_by_user[user_id].most_common(5)]
        user_docs.append(
            {
                "_id": user_id_map[user_id],
                "movielensUserId": user_id,
                "name": f"MovieLens User {user_id}",
                "age": 0,
                "preferences": preferences,
                "createdAt": first_seen_by_user.get(user_id, now),
            }
        )

    movie_id_map = await existing_id_map(db.items, "movieId") if not reset else {}
    for row in movies:
        movie_id_map.setdefault(int(row["movieId"]), ObjectId())

    item_docs = []
    embedding_by_movie: dict[int, list[float]] = {}
    for row in movies:
        movie_id = int(row["movieId"])
        genres = split_genres(row["genres"])
        free_tags = [tag for tag, _count in tags_by_movie[movie_id].most_common(10)]
        semantic_tags = inferred_tags(f"{row['title']} {' '.join(genres)} {' '.join(free_tags)}")
        tags_for_search = sorted(set(genres + free_tags + semantic_tags))
        movie_ratings = ratings_by_movie.get(movie_id, [])
        avg_rating = sum(movie_ratings) / len(movie_ratings) if movie_ratings else 0
        popularity = round(avg_rating * math.log1p(len(movie_ratings)), 4)
        description = f"{row['title']} genres: {', '.join(genres) or 'unknown'}"
        if free_tags:
            description += f"; user tags: {', '.join(free_tags)}"
        embedding = get_embedding(f"{row['title']} {' '.join(genres)} {' '.join(free_tags)}")
        embedding_by_movie[movie_id] = embedding
        link = links_by_movie.get(movie_id, {})
        item_docs.append(
            {
                "_id": movie_id_map[movie_id],
                "movieId": movie_id,
                "title": row["title"],
                "type": "movie",
                "genres": genres,
                "tags": tags_for_search,
                "description": description,
                "embedding": embedding,
                "popularity": popularity,
                "ratingCount": len(movie_ratings),
                "avgRating": round(avg_rating, 4),
                "businessMargin": 0,
                "available": True,
                "imdbId": link.get("imdbId"),
                "tmdbId": link.get("tmdbId"),
                "createdAt": first_rating_at_by_movie.get(movie_id, now),
            }
        )

    profile_sums: dict[int, list[float]] = {}
    profile_weights: dict[int, float] = defaultdict(float)
    interactions = []
    for row in ratings:
        user_id = int(row["userId"])
        movie_id = int(row["movieId"])
        rating = float(row["rating"])
        timestamp = parse_epoch(row["timestamp"])
        weighted_score = implicit_weight("rate", rating)
        interactions.append(
            {
                "userId": user_id_map[user_id],
                "itemId": movie_id_map[movie_id],
                "movielensUserId": user_id,
                "movieId": movie_id,
                "type": "rate",
                "score": rating,
                "weightedScore": weighted_score,
                "timestamp": timestamp,
            }
        )

        if rating >= POSITIVE_RATING_THRESHOLD:
            embedding = embedding_by_movie[movie_id]
            current = profile_sums.setdefault(user_id, [0.0] * 1536)
            for index, value in enumerate(embedding):
                current[index] += value * weighted_score
            profile_weights[user_id] += weighted_score

    profile_docs = []
    seed_profile_docs = []
    for user_id, vector_sum in profile_sums.items():
        total_weight = profile_weights[user_id]
        if total_weight <= 0:
            continue
        seed_profile_docs.append(
            {
                "userId": user_id_map[user_id],
                "movielensUserId": user_id,
                "embedding": [value / total_weight for value in vector_sum],
                "interactionWeight": total_weight,
                "updatedAt": now,
            }
        )

    if reset:
        await insert_many(db.users, user_docs)
        await insert_many(db.items, item_docs)
        await insert_many(db.interactions, interactions)
        await insert_many(db.user_profiles, seed_profile_docs)
        profile_count = len(seed_profile_docs)
    else:
        user_ops = []
        for doc in user_docs:
            doc_id = doc.pop("_id")
            created_at = doc.pop("createdAt")
            user_ops.append(
                UpdateOne(
                    {"movielensUserId": doc["movielensUserId"]},
                    {
                        "$set": doc,
                        "$setOnInsert": {"_id": doc_id, "createdAt": created_at},
                    },
                    upsert=True,
                )
            )

        item_ops = []
        for doc in item_docs:
            doc_id = doc.pop("_id")
            created_at = doc.pop("createdAt")
            # Do not set poster here: poster is usually enriched later and must be preserved.
            item_ops.append(
                UpdateOne(
                    {"movieId": doc["movieId"]},
                    {
                        "$set": doc,
                        "$setOnInsert": {"_id": doc_id, "createdAt": created_at},
                    },
                    upsert=True,
                )
            )

        interaction_ops = [
            UpdateOne(
                {
                    "movielensUserId": doc["movielensUserId"],
                    "movieId": doc["movieId"],
                    "type": "rate",
                    "timestamp": doc["timestamp"],
                },
                {"$set": doc},
                upsert=True,
            )
            for doc in interactions
        ]

        await bulk_write(db.users, user_ops)
        await bulk_write(db.items, item_ops)
        await bulk_write(db.interactions, interaction_ops)
        profile_count = await rebuild_user_profiles()

    print("MovieLens seed complete" if reset else "MovieLens upsert complete")
    print(f"Users: {len(user_docs)}")
    print(f"Movies: {len(item_docs)}")
    print(f"Ratings/interactions: {len(interactions)}")
    print(f"User profiles: {profile_count}")
    print("Example MovieLens userId: 1")
    print("Example MovieLens movieId: 1")
    print(f"Example Mongo userId: {user_id_map[1]}")
    print(f"Example Mongo itemId: {movie_id_map[1]}")


async def rebuild_user_profiles() -> int:
    from app.db import db
    from app.services.recommendations import implicit_weight
    from app.utils import utcnow

    await db.user_profiles.delete_many({})
    profile_sums: dict[ObjectId, list[float]] = {}
    profile_weights: dict[ObjectId, float] = defaultdict(float)

    cursor = db.interactions.find(
        {
            "type": {"$in": ["rate", "click", "search_click", "watch_complete", "like", "watchlist_add"]},
            "$or": [
                {"type": {"$ne": "rate"}},
                {"type": "rate", "score": {"$gte": POSITIVE_RATING_THRESHOLD}},
            ],
        },
        {"userId": 1, "itemId": 1, "type": 1, "score": 1, "weightedScore": 1, "movielensUserId": 1},
    )

    item_cache: dict[ObjectId, dict[str, Any]] = {}
    async for interaction in cursor:
        item_id = interaction["itemId"]
        item = item_cache.get(item_id)
        if item is None:
            item = await db.items.find_one({"_id": item_id}, {"embedding": 1})
            if not item:
                continue
            item_cache[item_id] = item

        embedding = item.get("embedding") or []
        if len(embedding) != 1536:
            continue
        weight = interaction.get("weightedScore")
        if weight is None:
            weight = implicit_weight(interaction.get("type", ""), interaction.get("score"))
        weight = float(weight or 0)
        if weight <= 0:
            continue

        current = profile_sums.setdefault(interaction["userId"], [0.0] * 1536)
        for index, value in enumerate(embedding):
            current[index] += value * weight
        profile_weights[interaction["userId"]] += weight

    now = utcnow()
    profile_docs = []
    for user_id, vector_sum in profile_sums.items():
        total_weight = profile_weights[user_id]
        if total_weight <= 0:
            continue
        profile_doc: dict[str, Any] = {
            "userId": user_id,
            "embedding": [value / total_weight for value in vector_sum],
            "interactionWeight": total_weight,
            "updatedAt": now,
        }
        user = await db.users.find_one({"_id": user_id}, {"movielensUserId": 1})
        if user and user.get("movielensUserId") is not None:
            profile_doc["movielensUserId"] = user["movielensUserId"]
        profile_docs.append(profile_doc)

    await insert_many(db.user_profiles, profile_docs)
    return len(profile_docs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import or update MovieLens ml-latest-small data.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing collections before seeding. Default is safe upsert.",
    )
    args = parser.parse_args()
    asyncio.run(seed(reset=args.reset))
