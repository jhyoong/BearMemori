"""Integration tests for main.py router registration."""

from core_svc.main import app


def test_app_metadata():
    """App has correct title and version."""
    assert app.title == "Life Organiser Core"
    assert app.version == "0.1.0"


def test_all_routers_in_openapi():
    """All expected routers appear in the OpenAPI schema."""
    openapi_schema = app.openapi()
    paths = openapi_schema.get("paths", {})

    expected_prefixes = [
        "/memories", "/tasks", "/reminders", "/events",
        "/search", "/settings", "/audit", "/llm_jobs", "/backup",
    ]

    for prefix in expected_prefixes:
        matching = [p for p in paths if p.startswith(prefix)]
        assert len(matching) > 0, f"No paths found for {prefix}"


def test_router_routes():
    """Routes are properly registered with the app."""
    expected_prefixes = [
        "/memories", "/tasks", "/reminders", "/events",
        "/search", "/settings", "/audit", "/llm_jobs", "/backup",
    ]

    for prefix in expected_prefixes:
        matching = [
            r for r in app.routes
            if hasattr(r, "path") and r.path.startswith(prefix)
        ]
        assert len(matching) > 0, f"No routes for {prefix}"


def test_health_endpoint():
    """Health endpoint is registered."""
    openapi_schema = app.openapi()
    paths = openapi_schema.get("paths", {})
    assert "/health" in paths
    assert "get" in paths["/health"]
