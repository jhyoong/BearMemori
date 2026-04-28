import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class ReflectionState:
    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def load_last_run(self) -> datetime | None:
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text())
            ts = data.get("last_run")
            if ts is None:
                return None
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except (OSError, ValueError, json.JSONDecodeError) as e:
            logger.warning("Failed to read reflection state at %s: %s", self._path, e)
            return None

    def save_last_run(self, when: datetime) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({"last_run": when.isoformat()}))
        except OSError as e:
            logger.error("Failed to write reflection state at %s: %s", self._path, e)
