from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from bearmemori.app import Application, create_application
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
    application = cast(Application, app.state.application)
    assert application.bus is not None
    assert application.db is not None
    assert application.processor is not None
    assert application.queue_manager is not None
    assert application.followup_manager is not None


def test_application_has_scheduler(settings, tmp_path):
    settings.database_path = str(tmp_path / "test.db")
    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs = MagicMock()
        mock_vs_cls.return_value = mock_vs
        app = create_application(settings)
    application = cast(Application, app.state.application)
    assert application.scheduler is not None


def test_application_has_vector_store_and_pending_store(settings, tmp_path):
    settings.database_path = str(tmp_path / "test.db")
    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs = MagicMock()
        mock_vs_cls.return_value = mock_vs
        app = create_application(settings)
    application = cast(Application, app.state.application)
    assert application.vector_store is not None
    assert application.pending_store is not None


def test_event_wiring_includes_pending_events(settings, tmp_path):
    from bearmemori.events.domain import MemoryConfirmed, MemoryDiscarded, MemoryPending

    settings.database_path = str(tmp_path / "test.db")
    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs = MagicMock()
        mock_vs_cls.return_value = mock_vs
        app = create_application(settings)
    application = cast(Application, app.state.application)
    bus = application.bus
    assert len(bus._handlers[MemoryPending]) > 0
    assert len(bus._handlers[MemoryConfirmed]) > 0
    assert len(bus._handlers[MemoryDiscarded]) > 0


def test_application_has_confirm_and_cleanup(settings, tmp_path):
    settings.database_path = str(tmp_path / "test.db")
    with patch("bearmemori.app.VectorStore") as mock_vs_cls:
        mock_vs = MagicMock()
        mock_vs_cls.return_value = mock_vs
        app = create_application(settings)
    application = cast(Application, app.state.application)
    assert application.confirm_handler is not None
    assert application.cleanup_task is not None


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
