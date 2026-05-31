from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from bson import ObjectId
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


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
    impression = "impression"
    click = "click"
    watchlist_add = "watchlist_add"
    watch_start = "watch_start"
    watch_progress = "watch_progress"
    watch_complete = "watch_complete"
    rate = "rate"
    watchlist_remove = "watchlist_remove"
    like = "like"
    dislike = "dislike"
    hide = "hide"
    search_click = "search_click"
    share = "share"


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
    poster: Optional[str] = None

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
    completionRate: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
        validation_alias=AliasChoices("completionRate", "completion_rate"),
    )
    source: Optional[str] = None
    positionSeconds: Optional[float] = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("positionSeconds", "position_seconds"),
    )
    durationSeconds: Optional[float] = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("durationSeconds", "duration_seconds"),
    )
    clientEventId: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("clientEventId", "client_event_id"),
    )
    recommendationId: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("recommendationId", "recommendation_id"),
    )
    contextItemId: Optional[str | int | PyObjectId] = Field(
        default=None,
        validation_alias=AliasChoices("contextItemId", "context_item_id"),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class InteractionEventCreate(MongoModel):
    userId: str | int | PyObjectId
    itemId: str | int | PyObjectId
    score: Optional[float] = None
    completionRate: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
        validation_alias=AliasChoices("completionRate", "completion_rate"),
    )
    source: Optional[str] = None
    positionSeconds: Optional[float] = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("positionSeconds", "position_seconds"),
    )
    durationSeconds: Optional[float] = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("durationSeconds", "duration_seconds"),
    )
    clientEventId: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("clientEventId", "client_event_id"),
    )
    recommendationId: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("recommendationId", "recommendation_id"),
    )
    contextItemId: Optional[str | int | PyObjectId] = Field(
        default=None,
        validation_alias=AliasChoices("contextItemId", "context_item_id"),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


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
