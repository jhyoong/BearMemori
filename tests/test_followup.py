import pytest

from bearmemori.core.followup import FollowUpManager
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, InputReceived, SendMessage


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def manager(bus):
    return FollowUpManager(bus)


@pytest.mark.asyncio
async def test_followup_required_tracks_conversation(manager, bus):
    sent = []
    bus.on(SendMessage, lambda e: sent.append(e))

    event = FollowUpRequired(
        question="What changed?",
        source_chat_id="123",
        context={"messages": [{"role": "user", "content": "something"}]},
    )
    await manager.handle_followup_required(event)

    assert "123" in manager._active
    assert len(sent) == 1
    assert sent[0].text == "What changed?"


@pytest.mark.asyncio
async def test_check_followup_adds_context(manager):
    event = FollowUpRequired(
        question="What changed?",
        source_chat_id="123",
        context={"messages": [{"role": "user", "content": "something"}]},
    )
    await manager.handle_followup_required(event)

    input_event = InputReceived(input_type="text", content="the theme", source_chat_id="123")
    result = manager.check_followup(input_event)

    assert result is not None
    assert result.context is not None
    assert result.context["messages"][-1]["content"] == "something"
    assert "123" not in manager._active


@pytest.mark.asyncio
async def test_check_followup_returns_none_when_no_active(manager):
    input_event = InputReceived(input_type="text", content="hello", source_chat_id="456")
    result = manager.check_followup(input_event)
    assert result is None
