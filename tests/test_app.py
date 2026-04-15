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
    assert app.state.bus is not None
    assert app.state.db is not None
    assert app.state.processor is not None
    assert app.state.queue_manager is not None
    assert app.state.followup_manager is not None


def test_application_has_scheduler(settings, tmp_path):
    settings.database_path = str(tmp_path / "test.db")
    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs = MagicMock()
        mock_vs_cls.return_value = mock_vs
        app = create_application(settings)
    assert app.state.scheduler is not None


def test_application_has_vector_store_and_pending_store(settings, tmp_path):
    settings.database_path = str(tmp_path / "test.db")
    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs = MagicMock()
        mock_vs_cls.return_value = mock_vs
        app = create_application(settings)
    assert app.state.vector_store is not None
    assert app.state.pending_store is not None


def test_event_wiring_includes_pending_events(settings, tmp_path):
    from bearmemori.events.domain import MemoryConfirmed, MemoryDiscarded, MemoryPending

    settings.database_path = str(tmp_path / "test.db")
    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs = MagicMock()
        mock_vs_cls.return_value = mock_vs
        app = create_application(settings)
    bus = app.state.bus
    assert len(bus._handlers[MemoryPending]) > 0
    assert len(bus._handlers[MemoryConfirmed]) > 0
    assert len(bus._handlers[MemoryDiscarded]) > 0


def test_application_has_confirm_and_cleanup(settings, tmp_path):
    settings.database_path = str(tmp_path / "test.db")
    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs = MagicMock()
        mock_vs_cls.return_value = mock_vs
        app = create_application(settings)
    assert app.state.confirm_handler is not None
    assert app.state.cleanup_task is not None


def test_webapp_mounted_when_secret_configured(tmp_path):
    settings = Settings(
        telegram_bot_token="fake-token",
        telegram_allowed_user_id=12345,
        llm_base_url="http://localhost:11434/v1",
        llm_model="llama3",
        database_path=str(tmp_path / "test.db"),
        webapp_secret="test-secret",
    )

    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs_cls.return_value = MagicMock()
        app = create_application(settings)

    route_paths = [r.path for r in app.routes]
    webapp_routes = [r for r in route_paths if r.startswith("/webapp")]
    assert len(webapp_routes) > 0


def test_webapp_not_mounted_when_secret_not_configured(tmp_path):
    settings = Settings(
        telegram_bot_token="fake-token",
        telegram_allowed_user_id=12345,
        llm_base_url="http://localhost:11434/v1",
        llm_model="llama3",
        database_path=str(tmp_path / "test.db"),
        webapp_secret="",
    )

    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs_cls.return_value = MagicMock()
        app = create_application(settings)

    route_paths = [r.path for r in app.routes]
    webapp_routes = [r for r in route_paths if r.startswith("/webapp")]
    assert len(webapp_routes) == 0
