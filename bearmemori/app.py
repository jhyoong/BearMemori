import logging

from bearmemori.config import Settings
from bearmemori.core.cleanup import PendingCleanupTask
from bearmemori.core.confirm import ConfirmHandler
from bearmemori.core.followup import FollowUpManager
from bearmemori.core.processor import Processor
from bearmemori.core.queue import QueueManager
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
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)


class Application:
    def __init__(
        self,
        bus: EventBus,
        db: MemoryDatabase,
        vector_store: VectorStore,
        pending_store: PendingStore,
        queue_manager: QueueManager,
        processor: Processor,
        followup_manager: FollowUpManager,
        confirm_handler: ConfirmHandler,
        cleanup_task: PendingCleanupTask,
        telegram: TelegramInterface,
        settings: Settings,
        scheduler: ReminderScheduler,
    ) -> None:
        self.bus = bus
        self.db = db
        self.vector_store = vector_store
        self.pending_store = pending_store
        self.queue_manager = queue_manager
        self.processor = processor
        self.followup_manager = followup_manager
        self.confirm_handler = confirm_handler
        self.cleanup_task = cleanup_task
        self.telegram = telegram
        self.settings = settings
        self.scheduler = scheduler


def create_application(settings: Settings) -> Application:
    bus = EventBus()

    db = MemoryDatabase(settings.database_path)
    db.initialize()

    vector_store = VectorStore(
        persist_dir=settings.chroma_persist_dir,
        embedding_model=settings.embedding_model,
    )
    vector_store.init()

    pending_store = PendingStore(default_ttl=settings.pending_ttl_seconds)

    llm = LLMClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
    )

    queue_manager = QueueManager(bus, max_size=settings.queue_max_size)
    processor = Processor(bus=bus, llm=llm, pending_store=pending_store)
    followup_manager = FollowUpManager(bus)
    confirm_handler = ConfirmHandler(
        bus=bus, pending_store=pending_store, db=db, vector_store=vector_store,
    )
    cleanup_task = PendingCleanupTask(bus=bus, pending_store=pending_store)
    telegram = TelegramInterface(
        bus=bus,
        token=settings.telegram_bot_token,
        allowed_user_id=settings.telegram_allowed_user_id,
    )
    scheduler = ReminderScheduler(
        bus=bus,
        db=db,
        poll_interval_seconds=settings.reminder_poll_interval_seconds,
    )

    bus.on(InputReceived, queue_manager.handle_input)
    bus.on(FollowUpRequired, followup_manager.handle_followup_required)
    bus.on(MemoryPending, telegram.handle_memory_pending)
    bus.on(MemoryConfirmed, confirm_handler.handle_confirmed)
    bus.on(MemoryDiscarded, confirm_handler.handle_discarded)
    bus.on(SendMessage, telegram.handle_send_message)
    bus.on(ReminderDue, telegram.handle_reminder_due)

    return Application(
        bus=bus,
        db=db,
        vector_store=vector_store,
        pending_store=pending_store,
        queue_manager=queue_manager,
        processor=processor,
        followup_manager=followup_manager,
        confirm_handler=confirm_handler,
        cleanup_task=cleanup_task,
        telegram=telegram,
        settings=settings,
        scheduler=scheduler,
    )
