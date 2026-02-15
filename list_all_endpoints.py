"""List all registered endpoints in the application."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'core'))
sys.path.insert(0, str(Path(__file__).parent / 'shared'))

from core.main import app


def main():
    """List all registered endpoints."""
    print("\n=== All Registered Endpoints ===\n")

    openapi_schema = app.openapi()
    paths = openapi_schema.get("paths", {})

    # Group by router prefix
    routers = {}
    for path in sorted(paths.keys()):
        # Determine which router this belongs to
        prefix = "/" + path.split("/")[1] if "/" in path[1:] else "root"
        if prefix not in routers:
            routers[prefix] = []
        routers[prefix].append(path)

    # Print endpoints grouped by router
    for prefix in sorted(routers.keys()):
        print(f"\n{prefix}:")
        for path in routers[prefix]:
            methods = list(paths[path].keys())
            print(f"  {path} [{', '.join(m.upper() for m in methods)}]")

    print(f"\n\nTotal endpoints: {len(paths)}")
    print(f"Total routers: {len(routers)}")
    print()


if __name__ == "__main__":
    main()
