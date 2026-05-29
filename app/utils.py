from datetime import datetime, timezone
from typing import Any

from bson import ObjectId


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def ensure_object_id(value: str | ObjectId) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if ObjectId.is_valid(value):
        return ObjectId(value)
    raise ValueError("Invalid ObjectId")


def serialize_doc(doc: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in doc.items():
        public_key = "id" if key == "_id" else key
        if isinstance(value, ObjectId):
            result[public_key] = str(value)
        elif isinstance(value, datetime):
            result[public_key] = value.isoformat()
        elif isinstance(value, list):
            result[public_key] = [
                str(item) if isinstance(item, ObjectId) else item for item in value
            ]
        else:
            result[public_key] = value
    return result
