from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import close_mongo_connection, create_indexes
from app.routes.interactions import router as interactions_router
from app.routes.metrics import router as metrics_router
from app.routes.recommendations import router as recommendations_router
from app.routes.search import router as search_router
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(recommendations_router)
app.include_router(interactions_router)
app.include_router(metrics_router)
app.include_router(search_router)

STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def ui() -> FileResponse:
    if not (STATIC_DIR / "index.html").exists():
        return FileResponse(Path("client/index.html"))
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    from app.core.config import get_settings

    _settings = get_settings()
    uvicorn.run("app.main:app", host="0.0.0.0", port=_settings.port, reload=True)
