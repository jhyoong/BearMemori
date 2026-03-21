import pytest
from bearmemori.events.bus import EventBus
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
