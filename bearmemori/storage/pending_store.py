import uuid
from datetime import datetime, timezone

from bearmemori.storage.models import MemoryDraft, PendingMemory


class PendingStore:
    def __init__(self, default_ttl: int = 86400):
        self._store: dict[str, PendingMemory] = {}
        self._default_ttl = default_ttl

    def add(self, draft: MemoryDraft, ttl: int | None = None) -> str:
        pending_id = f"pend_{uuid.uuid4().hex[:12]}"
        ttl_seconds = ttl if ttl is not None else self._default_ttl
        self._store[pending_id] = PendingMemory(
            pending_id=pending_id,
            draft=draft,
            ttl_seconds=ttl_seconds,
        )
        return pending_id

    def get(self, pending_id: str) -> PendingMemory | None:
        item = self._store.get(pending_id)
        if item is None:
            return None
        if self._is_expired(item):
            del self._store[pending_id]
            return None
        return item

    def remove(self, pending_id: str) -> bool:
        if pending_id in self._store:
            del self._store[pending_id]
            return True
        return False

    def cleanup(self) -> int:
        expired = [
            pid for pid, item in self._store.items() if self._is_expired(item)
        ]
        for pid in expired:
            del self._store[pid]
        return len(expired)

    def _is_expired(self, item: PendingMemory) -> bool:
        now = datetime.now(timezone.utc)
        elapsed = (now - item.created_at).total_seconds()
        return elapsed >= item.ttl_seconds
