import pytest
from datetime import datetime, timedelta
from bearmemori.core.queue import QueueManager
from bearmemori.core.models import QueueItem
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import InputReceived, InputQueued


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def queue(bus):
    return QueueManager(bus, max_size=5)


@pytest.mark.asyncio
async def test_handle_input_queues_item(queue, bus):
    queued_events = []
    bus.on(InputQueued, lambda e: queued_events.append(e))

    event = InputReceived(input_type="text", content="hello", source_chat_id="123")
    await queue.handle_input(event)

    assert queue.size() == 1
    assert len(queued_events) == 1


@pytest.mark.asyncio
async def test_get_next_returns_highest_priority(queue):
    await queue.enqueue(QueueItem(priority=10, input_type="text", content="low", source_chat_id="1"))
    await queue.enqueue(QueueItem(priority=0, input_type="text", content="high", source_chat_id="2"))

    item = await queue.get_next()
    assert item.content == "high"


@pytest.mark.asyncio
async def test_queue_rejects_when_full(queue, bus):
    for i in range(5):
        await queue.enqueue(
            QueueItem(priority=10, input_type="text", content=f"item{i}", source_chat_id="1")
        )

    rejected = await queue.enqueue(
        QueueItem(priority=10, input_type="text", content="overflow", source_chat_id="1")
    )
    assert rejected is False


@pytest.mark.asyncio
async def test_queue_fifo_within_same_priority(queue):
    t1 = datetime.now()
    t2 = t1 + timedelta(seconds=1)
    await queue.enqueue(
        QueueItem(priority=10, input_type="text", content="first", source_chat_id="1", created_at=t1)
    )
    await queue.enqueue(
        QueueItem(priority=10, input_type="text", content="second", source_chat_id="1", created_at=t2)
    )

    item = await queue.get_next()
    assert item.content == "first"
