# Group 2: Core Service Scaffolding

## Goal

Create the Core service package structure, FastAPI application entrypoint, and Dockerfile. At the end of this group, the Core service has a runnable FastAPI app with a health check endpoint, but no routers or database yet.

**Depends on:** Group 1 (shared package)
**Blocks:** Groups 3-6 (database, helpers, routers, scheduler)

---

## Context

The Core service is the central service in the architecture. It owns the SQLite database, exposes a REST API consumed by all other services, runs the scheduler, and manages image files. It is the only service that writes to the database.

The Core service uses FastAPI with a `lifespan` context manager for startup/shutdown logic. It runs via uvicorn on port 8000.

---

## Steps

### Step 2.1: Create core package structure

**Files to create:**
- `core/pyproject.toml`
- `core/core/__init__.py`
- `core/core/routers/__init__.py`

**`core/pyproject.toml` details:**
- Package name: `life-organiser-core`
- Requires Python >= 3.12
- Dependencies:
  - `fastapi>=0.110.0`
  - `uvicorn[standard]>=0.27.0`
  - `aiosqlite>=0.20.0`
  - `redis[hiredis]>=5.0`
  - `life-organiser-shared` as path dependency: `life-organiser-shared = {path = "../shared", develop = true}`
- Use `[build-system]` with `hatchling` or `setuptools`

**`core/core/__init__.py`:** Empty file.

**`core/core/routers/__init__.py`:** Empty file.

---

### Step 2.2: Create core main.py (FastAPI entrypoint)

**File:** `core/core/main.py`

**Structure:**

```
Import FastAPI, asynccontextmanager
Import shared config
Import database module (will be created in Group 3)
Import redis.asyncio
Import scheduler (will be created in Group 6)
Import all routers (will be created in Group 5)

@asynccontextmanager
async def lifespan(app):
    # STARTUP
    1. Load config from shared.config
    2. Initialize database: call database.init_db(config.database_path)
    3. Store db connection in app.state.db
    4. Connect to Redis: redis.asyncio.from_url(config.redis_url)
    5. Store redis client in app.state.redis
    6. Start scheduler as background task: asyncio.create_task(scheduler.run(...))
    7. Store scheduler task in app.state.scheduler_task

    yield

    # SHUTDOWN
    1. Cancel scheduler task
    2. Close database connection
    3. Close Redis connection

app = FastAPI(title="Life Organiser Core", lifespan=lifespan)

# Include routers (added as they are built in Group 5)
app.include_router(memories_router, prefix="/memories", tags=["memories"])
app.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
app.include_router(reminders_router, prefix="/reminders", tags=["reminders"])
app.include_router(events_router, prefix="/events", tags=["events"])
app.include_router(search_router, prefix="/search", tags=["search"])
app.include_router(settings_router, prefix="/settings", tags=["settings"])
app.include_router(audit_router, prefix="/audit", tags=["audit"])
app.include_router(llm_jobs_router, prefix="/llm-jobs", tags=["llm-jobs"])
app.include_router(backup_router, prefix="/backup", tags=["backup"])

@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Notes:**
- Initially, comment out router includes and scheduler until those groups are built. The app should be runnable with just the health endpoint.
- Use `app.state` to share DB and Redis connections with routers via FastAPI dependency injection.

---

### Step 2.3: Create core Dockerfile

**File:** `core/Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy and install shared package
COPY shared/ /app/shared/
RUN pip install --no-cache-dir -e /app/shared/

# Copy and install core package
COPY core/ /app/core/
RUN pip install --no-cache-dir -e /app/core/

# Create data directories
RUN mkdir -p /data/db /data/images

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Notes:**
- `curl` is needed for Docker health check (`curl -f http://localhost:8000/health`)
- Data directories (`/data/db`, `/data/images`) are created in the image but will be mounted as volumes in docker-compose

---

## Acceptance Criteria

1. `core/` is a valid Python package with `pyproject.toml`
2. Running `python -m uvicorn core.main:app` starts the server (with router includes commented out initially)
3. `GET /health` returns `{"status": "ok"}`
4. Dockerfile builds without errors
5. The shared package is importable from within the core service
