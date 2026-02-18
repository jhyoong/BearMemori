import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
import redis.asyncio

# Group 3 imports (database):
from shared_lib.config import load_config
from core_svc.database import init_db

# Group 5 imports (routers):
from core_svc.routers.memories import router as memories_router
from core_svc.routers.tasks import router as tasks_router
from core_svc.routers.reminders import router as reminders_router
from core_svc.routers.events import router as events_router
from core_svc.routers.search import router as search_router
from core_svc.routers.settings import router as settings_router
from core_svc.routers.audit import router as audit_router
from core_svc.routers.llm_jobs import router as llm_jobs_router
from core_svc.routers.backup import router as backup_router

# Group 6 imports (scheduler):
from core_svc.scheduler import run_scheduler


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

    # Connect to Redis (Group 4)
    app.state.redis = await redis.asyncio.from_url(config.redis_url)

    # Start scheduler (Group 6)
    app.state.scheduler_task = asyncio.create_task(
        run_scheduler(app.state.db, app.state.redis)
    )

    yield

    # SHUTDOWN
    # Stop scheduler (Group 6)
    app.state.scheduler_task.cancel()
    try:
        await app.state.scheduler_task
    except asyncio.CancelledError:
        pass

    # Close database connection (Group 3)
    await app.state.db.close()

    # Close Redis connection (Group 4)
    await app.state.redis.close()


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
