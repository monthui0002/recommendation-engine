from bson import ObjectId

from app.db import db
from app.utils import ensure_object_id


def is_int_like(value: str | int | ObjectId) -> bool:
    if isinstance(value, int):
        return True
    return isinstance(value, str) and value.isdigit()


async def resolve_user_id(value: str | int | ObjectId) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if is_int_like(value):
        user = await db.users.find_one({"movielensUserId": int(value)}, {"_id": 1})
        if user:
            return user["_id"]
    user_oid = ensure_object_id(str(value))
    user = await db.users.find_one({"_id": user_oid}, {"_id": 1})
    if not user:
        raise ValueError("User not found")
    return user_oid


async def resolve_item_id(value: str | int | ObjectId) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if is_int_like(value):
        item = await db.items.find_one({"movieId": int(value)}, {"_id": 1})
        if item:
            return item["_id"]
    return ensure_object_id(str(value))


async def user_exists(value: str | int | ObjectId) -> bool:
    try:
        user_id = await resolve_user_id(value)
    except ValueError:
        return False
    return await db.users.count_documents({"_id": user_id}, limit=1) > 0
