from contextlib import asynccontextmanager
from fastapi import FastAPI

# Future imports (commented out until Groups 3-6 are complete):
# from shared.config import load_config
# from core.database import init_db
# import redis.asyncio
# from core.scheduler import run_scheduler
# from core.routers import (
#     memories_router,
#     tasks_router,
#     reminders_router,
#     events_router,
#     search_router,
#     settings_router,
#     audit_router,
#     llm_jobs_router,
#     backup_router,
# )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    Handles startup and shutdown logic.
    """
    # STARTUP
    # TODO (Group 3): Load config and initialize database
    # config = load_config()
    # app.state.db = await init_db(config.database_path)

    # TODO (Group 4): Connect to Redis
    # app.state.redis = await redis.asyncio.from_url(config.redis_url)

    # TODO (Group 6): Start scheduler
    # app.state.scheduler_task = asyncio.create_task(run_scheduler(app.state.db))

    yield

    # SHUTDOWN
    # TODO (Group 6): Cancel scheduler task
    # app.state.scheduler_task.cancel()

    # TODO (Group 3): Close database connection
    # await app.state.db.close()

    # TODO (Group 4): Close Redis connection
    # await app.state.redis.close()


app = FastAPI(
    title="Life Organiser Core",
    version="0.1.0",
    lifespan=lifespan
)


# Router includes (to be added in Group 5):
# app.include_router(memories_router, prefix="/memories", tags=["memories"])
# app.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
# app.include_router(reminders_router, prefix="/reminders", tags=["reminders"])
# app.include_router(events_router, prefix="/events", tags=["events"])
# app.include_router(search_router, prefix="/search", tags=["search"])
# app.include_router(settings_router, prefix="/settings", tags=["settings"])
# app.include_router(audit_router, prefix="/audit", tags=["audit"])
# app.include_router(llm_jobs_router, prefix="/llm-jobs", tags=["llm-jobs"])
# app.include_router(backup_router, prefix="/backup", tags=["backup"])


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
