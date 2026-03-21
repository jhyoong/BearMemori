import logging

from bearmemori.config import Settings
from bearmemori.core.followup import FollowUpManager
from bearmemori.core.processor import Processor
from bearmemori.core.queue import QueueManager
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, InputReceived, SendMessage
from bearmemori.interfaces.telegram import TelegramInterface
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase

logger = logging.getLogger(__name__)


class Application:
    def __init__(
        self,
        bus: EventBus,
        db: MemoryDatabase,
        queue_manager: QueueManager,
        processor: Processor,
        followup_manager: FollowUpManager,
        telegram: TelegramInterface,
        settings: Settings,
    ) -> None:
        self.bus = bus
        self.db = db
        self.queue_manager = queue_manager
        self.processor = processor
        self.followup_manager = followup_manager
        self.telegram = telegram
        self.settings = settings


def create_application(settings: Settings) -> Application:
    bus = EventBus()

    db = MemoryDatabase(settings.database_path)
    db.initialize()

    llm = LLMClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )

    queue_manager = QueueManager(bus, max_size=settings.queue_max_size)
    processor = Processor(bus=bus, llm=llm, db=db, embedding_model=settings.embedding_model)
    followup_manager = FollowUpManager(bus)
    telegram = TelegramInterface(bus=bus, token=settings.telegram_bot_token)

    # Wire events
    bus.on(InputReceived, queue_manager.handle_input)
    bus.on(FollowUpRequired, followup_manager.handle_followup_required)
    bus.on(SendMessage, telegram.handle_send_message)

    return Application(
        bus=bus,
        db=db,
        queue_manager=queue_manager,
        processor=processor,
        followup_manager=followup_manager,
        telegram=telegram,
        settings=settings,
    )
