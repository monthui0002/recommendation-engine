from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.operations import SearchIndexModel
import redis.asyncio as redis

from app.core.config import get_settings


settings = get_settings()
mongo_client = AsyncIOMotorClient(settings.mongodb_uri)
db: AsyncIOMotorDatabase = mongo_client[settings.mongodb_db]
redis_client = redis.from_url(settings.redis_url, decode_responses=True)


async def create_indexes() -> None:
    await db.users.create_index([("createdAt", DESCENDING)])
    await db.users.create_index([("movielensUserId", ASCENDING)], unique=True, sparse=True)
    await db.items.create_index([("movieId", ASCENDING)], unique=True, sparse=True)
    await db.items.create_index([("genres", ASCENDING)])
    await db.items.create_index([("imdbId", ASCENDING)], sparse=True)
    await db.items.create_index([("tmdbId", ASCENDING)], sparse=True)
    await db.items.create_index([("popularity", DESCENDING)])
    await db.items.create_index([("available", ASCENDING), ("popularity", DESCENDING)])
    await db.items.create_index([("tags", ASCENDING)])
    await db.interactions.create_index(
        [("userId", ASCENDING), ("itemId", ASCENDING), ("timestamp", DESCENDING)]
    )
    await db.interactions.create_index([("userId", ASCENDING), ("timestamp", DESCENDING)])
    await db.explorations.create_index([("userId", ASCENDING), ("timestamp", DESCENDING)])
    await db.user_profiles.create_index([("userId", ASCENDING)], unique=True)
    await db.user_profiles.create_index([("updatedAt", DESCENDING)])

    # Atlas Search indexes are separate from normal MongoDB indexes.
    # This works on Atlas/Atlas Local clusters that support Search Index Management.
    try:
        model = SearchIndexModel(
            definition={
                "fields": [
                    {
                        "type": "vector",
                        "path": "embedding",
                        "numDimensions": 1536,
                        "similarity": "cosine",
                    }
                ]
            },
            name=settings.vector_index_name,
            type="vectorSearch",
        )
        await db.items.create_search_index(model=model)
    except Exception:
        pass


async def close_connections() -> None:
    await redis_client.aclose()
    mongo_client.close()
