from contextlib import asynccontextmanager
from fastapi import FastAPI

# Group 3 imports (database):
from shared.config import load_config
from core.database import init_db

# Group 5 imports (routers):
from core.routers.memories import router as memories_router
from core.routers.tasks import router as tasks_router
from core.routers.reminders import router as reminders_router
from core.routers.events import router as events_router
from core.routers.search import router as search_router
from core.routers.settings import router as settings_router
from core.routers.audit import router as audit_router
from core.routers.llm_jobs import router as llm_jobs_router
from core.routers.backup import router as backup_router

# Future imports (commented out until Groups 4-6 are complete):
# import redis.asyncio
# from core.scheduler import run_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    Handles startup and shutdown logic.
    """
    # STARTUP
    # Load config and initialize database (Group 3)
    config = load_config()
    app.state.db = await init_db(config.database_path)

    # TODO (Group 4): Connect to Redis
    # app.state.redis = await redis.asyncio.from_url(config.redis_url)

    # TODO (Group 6): Start scheduler
    # app.state.scheduler_task = asyncio.create_task(run_scheduler(app.state.db))

    yield

    # SHUTDOWN
    # TODO (Group 6): Cancel scheduler task
    # app.state.scheduler_task.cancel()

    # Close database connection (Group 3)
    await app.state.db.close()

    # TODO (Group 4): Close Redis connection
    # await app.state.redis.close()


app = FastAPI(
    title="Life Organiser Core",
    version="0.1.0",
    lifespan=lifespan
)


# Router includes (Group 5):
app.include_router(memories_router, prefix="/memories")
app.include_router(tasks_router, prefix="/tasks")
app.include_router(reminders_router, prefix="/reminders")
app.include_router(events_router, prefix="/events")
app.include_router(search_router, prefix="/search")
app.include_router(settings_router, prefix="/settings")
app.include_router(audit_router, prefix="/audit")
app.include_router(llm_jobs_router, prefix="/llm_jobs")
app.include_router(backup_router, prefix="/backup")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
