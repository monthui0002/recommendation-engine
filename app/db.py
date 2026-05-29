from app.core.database import create_indexes, db, mongo_client


async def close_mongo_connection() -> None:
    mongo_client.close()


__all__ = ["create_indexes", "db", "mongo_client", "close_mongo_connection"]
