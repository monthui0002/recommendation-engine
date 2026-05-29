from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import close_mongo_connection, create_indexes
from app.routes.interactions import router as interactions_router
from app.routes.metrics import router as metrics_router
from app.routes.recommendations import router as recommendations_router
from app.services.cache import close_redis_connection


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await create_indexes()
    yield
    await close_redis_connection()
    await close_mongo_connection()


app = FastAPI(
    title="Python MongoDB Recommendation Engine",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(recommendations_router)
app.include_router(interactions_router)
app.include_router(metrics_router)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
