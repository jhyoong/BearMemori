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
    app = create_application(settings)
    assert app.bus is not None
    assert app.db is not None
    assert app.processor is not None
    assert app.queue_manager is not None
    assert app.followup_manager is not None


def test_application_has_scheduler(settings, tmp_path):
    settings.database_path = str(tmp_path / "test.db")
    app = create_application(settings)
    assert app.scheduler is not None
