import asyncio
import csv
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId

from app.db import create_indexes, db
from app.services.embeddings import get_embedding
from app.services.recommendations import implicit_weight
from app.utils import utcnow


ROOT = Path(__file__).resolve().parents[1]
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


async def seed() -> None:
    movies = read_csv("movies.csv")
    ratings = read_csv("ratings.csv")
    tags = read_csv("tags.csv")
    links = read_csv("links.csv")

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
    user_id_map: dict[int, ObjectId] = {user_id: ObjectId() for user_id in user_ids}
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

    movie_id_map: dict[int, ObjectId] = {int(row["movieId"]): ObjectId() for row in movies}
    item_docs = []
    embedding_by_movie: dict[int, list[float]] = {}
    for row in movies:
        movie_id = int(row["movieId"])
        genres = split_genres(row["genres"])
        free_tags = [tag for tag, _count in tags_by_movie[movie_id].most_common(10)]
        tags_for_search = sorted(set(genres + free_tags))
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
    for user_id, vector_sum in profile_sums.items():
        total_weight = profile_weights[user_id]
        if total_weight <= 0:
            continue
        profile_docs.append(
            {
                "userId": user_id_map[user_id],
                "movielensUserId": user_id,
                "embedding": [value / total_weight for value in vector_sum],
                "interactionWeight": total_weight,
                "updatedAt": now,
            }
        )

    await insert_many(db.users, user_docs)
    await insert_many(db.items, item_docs)
    await insert_many(db.interactions, interactions)
    await insert_many(db.user_profiles, profile_docs)

    print("MovieLens seed complete")
    print(f"Users: {len(user_docs)}")
    print(f"Movies: {len(item_docs)}")
    print(f"Ratings/interactions: {len(interactions)}")
    print(f"User profiles: {len(profile_docs)}")
    print("Example MovieLens userId: 1")
    print("Example MovieLens movieId: 1")
    print(f"Example Mongo userId: {user_id_map[1]}")
    print(f"Example Mongo itemId: {movie_id_map[1]}")


if __name__ == "__main__":
    asyncio.run(seed())
