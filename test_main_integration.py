"""Integration test for main.py router registration."""

import sys
from pathlib import Path

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent / 'core'))
sys.path.insert(0, str(Path(__file__).parent / 'shared'))

from core.main import app


def test_app_metadata():
    """Test that app has correct metadata."""
    assert app.title == "Life Organiser Core"
    assert app.version == "0.1.0"
    print("✓ App metadata is correct")


def test_routers_in_openapi():
    """Test that all routers are registered by checking OpenAPI schema."""
    # Get OpenAPI schema
    openapi_schema = app.openapi()
    paths = openapi_schema.get("paths", {})

    # Define expected router prefixes and their expected tags
    expected_routers = [
        ("/memories", "memories"),
        ("/tasks", "tasks"),
        ("/reminders", "reminders"),
        ("/events", "events"),
        ("/search", "search"),
        ("/settings", "settings"),
        ("/audit", "audit"),
        ("/llm_jobs", "llm_jobs"),
        ("/backup", "backup"),
    ]

    for prefix, tag in expected_routers:
        # Check if any path starts with this prefix
        matching_paths = [path for path in paths.keys() if path.startswith(prefix)]
        assert len(matching_paths) > 0, \
            f"No paths found with prefix {prefix} in OpenAPI schema"
        print(f"✓ Router '{tag}' is registered at {prefix} ({len(matching_paths)} endpoint(s))")

    # Verify we have all expected routers
    assert len(expected_routers) == 9, "Expected 9 routers"


def test_router_routes():
    """Test that routes are properly registered with the app."""
    # Get all routes from the app
    routes = app.routes

    # Define expected prefixes
    expected_prefixes = [
        "/memories",
        "/tasks",
        "/reminders",
        "/events",
        "/search",
        "/settings",
        "/audit",
        "/llm_jobs",
        "/backup",
    ]

    # Check that we have routes for each prefix
    for prefix in expected_prefixes:
        matching_routes = [
            route for route in routes
            if hasattr(route, 'path') and route.path.startswith(prefix)
        ]
        assert len(matching_routes) > 0, \
            f"No routes found with prefix {prefix}"

    print(f"✓ All {len(expected_prefixes)} routers have routes registered")


def test_health_endpoint():
    """Test that health endpoint exists."""
    openapi_schema = app.openapi()
    paths = openapi_schema.get("paths", {})

    assert "/health" in paths, "Health endpoint not found"
    assert "get" in paths["/health"], "Health endpoint must support GET"
    print("✓ Health endpoint is registered")


def main():
    """Run all integration tests."""
    print("\n=== Testing Router Registration ===\n")

    try:
        test_app_metadata()
        test_health_endpoint()
        test_routers_in_openapi()
        test_router_routes()

        print("\n=== All Integration Tests Passed ===\n")
        return 0
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}\n")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
