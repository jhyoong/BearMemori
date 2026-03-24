"""Tests for current_time passthrough in triage route."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from bearmemori.api.routes import create_app


@pytest.fixture
def client():
    db = MagicMock()
    vector_store = MagicMock()
    pending_store = MagicMock()
    app = create_app(
        db=db,
        vector_store=vector_store,
        pending_store=pending_store,
        llm_base_url="http://fake",
        llm_api_key="key",
        llm_model="model",
    )
    return TestClient(app)


def test_triage_route_passes_current_time(client):
    """POST /memory/triage should forward current_time to run_triage."""
    with patch(
        "bearmemori.api.routes.run_triage",
        new_callable=AsyncMock,
    ) as mock_triage:
        from bearmemori.core.triage import TriageResult

        mock_triage.return_value = TriageResult(should_save=False)

        response = client.post(
            "/memory/triage",
            json={
                "conversation": [{"role": "user", "content": "Remind me in 10 minutes"}],
                "current_time": "Monday, March 24, 2026, 07:33 PM +0800 (Asia/Singapore)",
            },
        )

        assert response.status_code == 200
        call_kwargs = mock_triage.call_args.kwargs
        expected = "Monday, March 24, 2026, 07:33 PM +0800 (Asia/Singapore)"
        assert call_kwargs.get("current_time") == expected
