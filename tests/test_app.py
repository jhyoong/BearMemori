from unittest.mock import MagicMock, patch

import pytest

from bearmemori.app import create_application
from bearmemori.config import Settings


@pytest.fixture
def settings():
    return Settings(
        telegram_bot_token="fake-token",
        telegram_allowed_user_id=12345,
        llm_base_url="http://localhost:11434/v1",
        llm_model="llama3",
        database_path=":memory:",
    )


def test_create_application(settings, tmp_path):
    settings.database_path = str(tmp_path / "test.db")
    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs = MagicMock()
        mock_vs_cls.return_value = mock_vs
        app = create_application(settings)
    assert app.bus is not None
    assert app.db is not None
    assert app.processor is not None
    assert app.queue_manager is not None
    assert app.followup_manager is not None


def test_application_has_scheduler(settings, tmp_path):
    settings.database_path = str(tmp_path / "test.db")
    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs = MagicMock()
        mock_vs_cls.return_value = mock_vs
        app = create_application(settings)
    assert app.scheduler is not None


def test_application_has_vector_store_and_pending_store(settings, tmp_path):
    settings.database_path = str(tmp_path / "test.db")
    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs = MagicMock()
        mock_vs_cls.return_value = mock_vs
        app = create_application(settings)
    assert app.vector_store is not None
    assert app.pending_store is not None


def test_event_wiring_includes_pending_events(settings, tmp_path):
    from bearmemori.events.domain import MemoryConfirmed, MemoryDiscarded, MemoryPending

    settings.database_path = str(tmp_path / "test.db")
    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs = MagicMock()
        mock_vs_cls.return_value = mock_vs
        app = create_application(settings)
    bus = app.bus
    assert len(bus._handlers[MemoryPending]) > 0
    assert len(bus._handlers[MemoryConfirmed]) > 0
    assert len(bus._handlers[MemoryDiscarded]) > 0


def test_application_has_confirm_and_cleanup(settings, tmp_path):
    settings.database_path = str(tmp_path / "test.db")
    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs = MagicMock()
        mock_vs_cls.return_value = mock_vs
        app = create_application(settings)
    assert app.confirm_handler is not None
    assert app.cleanup_task is not None
