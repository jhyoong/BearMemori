"""Main entry point for the assistant service."""

import asyncio
import logging
import signal

import openai
import redis.asyncio as aioredis

from assistant_svc.agent import Agent
from assistant_svc.briefing import BriefingBuilder
from assistant_svc.config import AssistantConfig, load_config
from assistant_svc.context import ContextManager
from assistant_svc.core_client import AssistantCoreClient
from assistant_svc.digest import DigestScheduler
from assistant_svc.interfaces.telegram import TelegramInterface
from assistant_svc.tools import ToolRegistry
from assistant_svc.tools.memories import (
    search_memories, SEARCH_MEMORIES_SCHEMA,
    get_memory, GET_MEMORY_SCHEMA,
)
from assistant_svc.tools.tasks import (
    list_tasks, LIST_TASKS_SCHEMA,
    create_task, CREATE_TASK_SCHEMA,
)
from assistant_svc.tools.reminders import (
    list_reminders, LIST_REMINDERS_SCHEMA,
    create_reminder, CREATE_REMINDER_SCHEMA,
)
from assistant_svc.tools.events import list_events, LIST_EVENTS_SCHEMA

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def build_components(config: AssistantConfig) -> dict:
    """Create all service components from configuration."""
    # Redis
    redis_client = aioredis.from_url(config.redis_url)

    # Core API client
    core_client = AssistantCoreClient(base_url=config.core_api_url)

    # Context manager
    context_manager = ContextManager(
        redis=redis_client,
        context_window_tokens=config.context_window_tokens,
        briefing_budget_tokens=config.briefing_budget_tokens,
        response_reserve_tokens=config.response_reserve_tokens,
        session_timeout_seconds=config.session_timeout_seconds,
    )

    # Briefing builder
    briefing_builder = BriefingBuilder(
        core_client=core_client,
        context_manager=context_manager,
        budget_tokens=config.briefing_budget_tokens,
    )

    # Tool registry
    tool_registry = ToolRegistry()
    tool_registry.register("search_memories", search_memories, SEARCH_MEMORIES_SCHEMA)
    tool_registry.register("get_memory", get_memory, GET_MEMORY_SCHEMA)
    tool_registry.register("list_tasks", list_tasks, LIST_TASKS_SCHEMA)
    tool_registry.register("create_task", create_task, CREATE_TASK_SCHEMA)
    tool_registry.register("list_reminders", list_reminders, LIST_REMINDERS_SCHEMA)
    tool_registry.register("create_reminder", create_reminder, CREATE_REMINDER_SCHEMA)
    tool_registry.register("list_events", list_events, LIST_EVENTS_SCHEMA)

    # OpenAI client
    openai_client = openai.AsyncOpenAI(
        base_url=config.openai_base_url,
        api_key=config.openai_api_key,
    )

    # Agent
    agent = Agent(
        openai_client=openai_client,
        model=config.openai_model,
        core_client=core_client,
        context_manager=context_manager,
        briefing_builder=briefing_builder,
        tool_registry=tool_registry,
    )

    # Parse allowed user IDs
    allowed_ids = set()
    if config.assistant_allowed_user_ids:
        for uid in config.assistant_allowed_user_ids.split(","):
            uid = uid.strip()
            if uid:
                allowed_ids.add(int(uid))

    # Interface
    interface = TelegramInterface(
        agent=agent,
        bot_token=config.assistant_telegram_bot_token,
        allowed_user_ids=allowed_ids,
    )

    # Digest scheduler
    digest_scheduler = DigestScheduler(
        redis=redis_client,
        briefing_builder=briefing_builder,
        interface=interface,
        core_client=core_client,
        user_ids=list(allowed_ids),
        default_hour=config.digest_default_hour,
    )

    return {
        "redis": redis_client,
        "core_client": core_client,
        "context_manager": context_manager,
        "briefing_builder": briefing_builder,
        "tool_registry": tool_registry,
        "openai_client": openai_client,
        "agent": agent,
        "interface": interface,
        "digest_scheduler": digest_scheduler,
    }


async def run(components: dict) -> None:
    """Start the assistant service."""
    interface = components["interface"]
    digest = components["digest_scheduler"]

    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("Received shutdown signal")
        stop_event.set()
        digest.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    # Start interface and digest scheduler
    digest_task = asyncio.create_task(digest.run())

    try:
        await interface.start()
        await stop_event.wait()
    finally:
        await interface.stop()
        digest.stop()
        digest_task.cancel()
        try:
            await digest_task
        except asyncio.CancelledError:
            pass
        await components["core_client"].close()
        await components["openai_client"].close()
        await components["redis"].aclose()
        logger.info("Assistant service shut down")


def main() -> None:
    """Entry point."""
    config = load_config()
    components = build_components(config)
    asyncio.run(run(components))


if __name__ == "__main__":
    main()
