from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongodb_uri: str = "mongodb://localhost:27017/?directConnection=true"
    mongodb_db: str = "recommendation"
    redis_url: str = "redis://localhost:6379/0"
    vector_index_name: str = "items_embedding_vector_index"
    app_env: str = "development"
    interaction_stream: str = "interaction_events"
    interaction_group: str = "recommendation_workers"
    infra_timeout_ms: int = 200
    port: int = 8080

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
