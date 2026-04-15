import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from starlette.staticfiles import StaticFiles

from bearmemori.api.routes import create_app as create_api_app
from bearmemori.config import Settings
from bearmemori.core.cleanup import PendingCleanupTask
from bearmemori.core.memory_service import MemoryService
from bearmemori.core.confirm import ConfirmHandler
from bearmemori.core.followup import FollowUpManager
from bearmemori.core.processor import Processor
from bearmemori.core.queue import QueueManager
from bearmemori.core.reflection import ReflectionTask
from bearmemori.core.scheduler import ReminderScheduler
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import (
    FollowUpRequired,
    InputReceived,
    MemoryConfirmed,
    MemoryDiscarded,
    MemoryPending,
    ReminderDue,
    SendMessage,
)
from bearmemori.interfaces.telegram import TelegramInterface
from bearmemori.llm.client import LLMClient
from bearmemori.mcp.server import create_mcp_app
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore
from bearmemori.webapp.auth import WebappAuthMiddleware
from bearmemori.webapp.router import create_webapp_router

logger = logging.getLogger(__name__)


def create_application(settings: Settings) -> FastAPI:
    bus = EventBus()

    db = MemoryDatabase(settings.database_path)
    db.initialize()

    vector_store = VectorStore(
        persist_dir=settings.chroma_persist_dir,
        embedding_model=settings.embedding_model,
    )
    vector_store.init()

    # Ensure image storage directory exists
    Path(settings.image_storage_dir).mkdir(parents=True, exist_ok=True)

    pending_store = PendingStore(default_ttl=settings.pending_ttl_seconds)

    llm = LLMClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        user_timezone=settings.user_timezone,
    )

    queue_manager = QueueManager(bus, max_size=settings.queue_max_size)
    processor = Processor(bus=bus, llm=llm, pending_store=pending_store)
    followup_manager = FollowUpManager(bus)
    confirm_handler = ConfirmHandler(
        bus=bus,
        pending_store=pending_store,
        db=db,
        vector_store=vector_store,
        image_storage_dir=settings.image_storage_dir,
    )
    cleanup_task = PendingCleanupTask(
        bus=bus,
        pending_store=pending_store,
        interval_seconds=settings.cleanup_interval_seconds,
    )
    # Telegram interface and event wiring (skipped in API-only mode)
    telegram: TelegramInterface | None = None
    if not settings.api_only_mode:
        telegram = TelegramInterface(
            bus=bus,
            token=settings.telegram_bot_token,
            allowed_user_id=settings.telegram_allowed_user_id,
            db=db,
            image_storage_dir=settings.image_storage_dir,
            vector_store=vector_store,
        )
        bus.on(MemoryPending, telegram.handle_memory_pending)
        bus.on(SendMessage, telegram.handle_send_message)
        bus.on(ReminderDue, telegram.handle_reminder_due)

    scheduler = ReminderScheduler(
        bus=bus,
        db=db,
        poll_interval_seconds=settings.reminder_poll_interval_seconds,
    )

    reflection_task = ReflectionTask(
        db=db,
        vector_store=vector_store,
        llm=llm,
        bus=bus,
        settings=settings,
    )

    bus.on(InputReceived, queue_manager.handle_input)
    bus.on(FollowUpRequired, followup_manager.handle_followup_required)
    bus.on(MemoryConfirmed, confirm_handler.handle_confirmed)
    bus.on(MemoryDiscarded, confirm_handler.handle_discarded)

    memory_service = MemoryService(
        db=db,
        vector_store=vector_store,
        image_storage_dir=settings.image_storage_dir,
    )

    # Create FastAPI app
    api = create_api_app(
        db=db,
        vector_store=vector_store,
        pending_store=pending_store,
        memory_service=memory_service,
        llm=llm,
        reflection_task=reflection_task,
        user_timezone=settings.user_timezone,
        image_storage_dir=settings.image_storage_dir,
    )

    # Mount webapp if secret is configured
    if settings.webapp_secret:
        webapp_auth = WebappAuthMiddleware(
            None, settings.webapp_secret, secure_cookie=settings.webapp_secure_cookie
        )
        webapp_router = create_webapp_router(
            db,
            vector_store,
            webapp_auth,
            memory_service=memory_service,
            image_storage_dir=settings.image_storage_dir,
            user_timezone=settings.user_timezone,
        )
        api.include_router(webapp_router)
        api.add_middleware(
            WebappAuthMiddleware,
            secret=settings.webapp_secret,
            secure_cookie=settings.webapp_secure_cookie,
        )

        static_dir = Path(__file__).parent / "webapp" / "static"
        api.mount("/webapp/static", StaticFiles(directory=str(static_dir)), name="webapp-static")

        @api.get("/", include_in_schema=False)
        async def root_redirect():
            return RedirectResponse(url="/webapp/login")

    mcp_asgi = create_mcp_app(
        db=db,
        vector_store=vector_store,
        settings=settings,
        llm=llm,
        pending_store=pending_store,
        reflection_task=reflection_task,
        memory_service=memory_service,
    )
    api.mount("/mcp", mcp_asgi)

    # Store components in app state for access by __main__.py
    api.state.bus = bus
    api.state.db = db
    api.state.vector_store = vector_store
    api.state.pending_store = pending_store
    api.state.queue_manager = queue_manager
    api.state.processor = processor
    api.state.followup_manager = followup_manager
    api.state.confirm_handler = confirm_handler
    api.state.cleanup_task = cleanup_task
    api.state.telegram = telegram
    api.state.settings = settings
    api.state.scheduler = scheduler
    api.state.reflection_task = reflection_task

    return api
