import pytest

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import MemoryConfirmed, MemoryDiscarded, MemoryPending, ReminderDue
from bearmemori.events.types import Event


class FakeEvent(Event):
    data: str


class AnotherEvent(Event):
    value: int


@pytest.mark.asyncio
async def test_emit_calls_registered_handler():
    bus = EventBus()
    received = []

    async def handler(event: FakeEvent):
        received.append(event.data)

    bus.on(FakeEvent, handler)
    await bus.emit(FakeEvent(data="hello"))

    assert received == ["hello"]


@pytest.mark.asyncio
async def test_emit_calls_multiple_handlers():
    bus = EventBus()
    results = []

    async def handler_a(event: FakeEvent):
        results.append("a")

    async def handler_b(event: FakeEvent):
        results.append("b")

    bus.on(FakeEvent, handler_a)
    bus.on(FakeEvent, handler_b)
    await bus.emit(FakeEvent(data="x"))

    assert sorted(results) == ["a", "b"]


@pytest.mark.asyncio
async def test_emit_does_not_call_unrelated_handlers():
    bus = EventBus()
    called = False

    async def handler(event: FakeEvent):
        nonlocal called
        called = True

    bus.on(FakeEvent, handler)
    await bus.emit(AnotherEvent(value=1))

    assert not called


@pytest.mark.asyncio
async def test_emit_with_no_handlers_does_nothing():
    bus = EventBus()
    await bus.emit(FakeEvent(data="no one listening"))


@pytest.mark.asyncio
async def test_reminder_due_event():
    bus = EventBus()
    received = []
    bus.on(ReminderDue, lambda e: received.append(e))

    await bus.emit(
        ReminderDue(
            memory_id="rem-1",
            content="Take meds",
            source_chat_id="42",
            remind_at_iso="2026-03-21T10:00:00",
        )
    )

    assert len(received) == 1
    assert received[0].memory_id == "rem-1"
    assert received[0].content == "Take meds"


@pytest.mark.asyncio
async def test_memory_pending_event():
    bus = EventBus()
    received = []
    bus.on(MemoryPending, lambda e: received.append(e))
    await bus.emit(
        MemoryPending(
            pending_id="pend_abc123",
            preview_data={
                "title": "Test",
                "category": "general",
                "content": "Test content",
                "tags": [],
            },
            source_chat_id="123",
        )
    )
    assert len(received) == 1
    assert received[0].pending_id == "pend_abc123"


@pytest.mark.asyncio
async def test_memory_confirmed_event():
    bus = EventBus()
    received = []
    bus.on(MemoryConfirmed, lambda e: received.append(e))
    await bus.emit(MemoryConfirmed(pending_id="pend_abc123", source_chat_id="123"))
    assert len(received) == 1
    assert received[0].pending_id == "pend_abc123"


def test_memory_confirmed_needs_review_default():
    event = MemoryConfirmed(pending_id="pend_test", source_chat_id="123")
    assert event.needs_review is False


def test_memory_confirmed_needs_review_set():
    event = MemoryConfirmed(
        pending_id="pend_test", source_chat_id="123", needs_review=True
    )
    assert event.needs_review is True


@pytest.mark.asyncio
async def test_memory_discarded_event():
    bus = EventBus()
    received = []
    bus.on(MemoryDiscarded, lambda e: received.append(e))
    await bus.emit(MemoryDiscarded(pending_id="pend_abc123", source_chat_id="123"))
    assert len(received) == 1
    assert received[0].pending_id == "pend_abc123"
