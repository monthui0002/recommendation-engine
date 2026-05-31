from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PyObjectId(ObjectId):
    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type: Any, _handler: Any) -> Any:
        from pydantic_core import core_schema

        return core_schema.no_info_plain_validator_function(cls.validate)

    @classmethod
    def validate(cls, value: Any) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        if isinstance(value, str) and ObjectId.is_valid(value):
            return ObjectId(value)
        raise ValueError("Invalid ObjectId")


class ItemType(str, Enum):
    movie = "movie"


class InteractionType(str, Enum):
    view = "view"
    click = "click"
    purchase = "purchase"
    rate = "rate"
    # --- new signals ---
    rec_click = "rec_click"        # click originating from a recommendation row
    impression = "impression"      # item was displayed in a recommendation row
    watchlist_add = "watchlist_add"        # user saved to watchlist
    watchlist_remove = "watchlist_remove"  # user removed from watchlist
    dismiss = "dismiss"            # user explicitly said "not interested"


class MongoModel(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        populate_by_name=True,
        json_encoders={ObjectId: str},
    )


class UserCreate(MongoModel):
    name: str
    age: int
    preferences: list[str] = Field(default_factory=list)


class UserInDB(UserCreate):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ItemCreate(MongoModel):
    movieId: Optional[int] = None
    title: str
    type: ItemType = ItemType.movie
    tags: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    description: str
    embedding: list[float] = Field(default_factory=list)
    popularity: float = 0
    businessMargin: float = Field(default=0, ge=0, le=1)
    available: bool = True
    imdbId: Optional[str] = None
    tmdbId: Optional[int] = None

    @field_validator("embedding")
    @classmethod
    def validate_embedding(cls, value: list[float]) -> list[float]:
        if value and len(value) != 1536:
            raise ValueError("embedding must contain 1536 numbers")
        return value


class ItemInDB(ItemCreate):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InteractionCreate(MongoModel):
    userId: str | int | PyObjectId
    itemId: str | int | PyObjectId
    type: InteractionType
    score: Optional[float] = None
    metadata: Optional[dict] = None  # e.g. {"recType": "hybrid"} for rec_click/dismiss


class InteractionInDB(InteractionCreate):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InteractionResponse(MongoModel):
    id: str
    userId: str
    itemId: str
    type: InteractionType
    score: Optional[float]
    timestamp: datetime


class InteractionQueuedResponse(MongoModel):
    status: str
    eventId: str
    userId: str
    itemId: str


class UserProfileInDB(MongoModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    userId: PyObjectId
    embedding: list[float]
    interactionWeight: float = 0
    updatedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RecommendationResponse(MongoModel):
    userId: str
    type: str
    count: int
    items: list[dict[str, Any]]


class MetricsResponse(MongoModel):
    userId: str
    precisionAtK: float
    diversityScore: float
