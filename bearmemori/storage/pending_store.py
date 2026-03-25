import uuid
from datetime import UTC, datetime

from bearmemori.storage.models import MemoryDraft, PendingMemory


class PendingStore:
    def __init__(self, default_ttl: int = 86400):
        self._store: dict[str, PendingMemory] = {}
        self._default_ttl = default_ttl

    def add(
        self,
        draft: MemoryDraft,
        ttl: int | None = None,
        chat_id: str = "",
        image_bytes: bytes | None = None,
    ) -> str:
        pending_id = f"pend_{uuid.uuid4().hex[:12]}"
        ttl_seconds = ttl if ttl is not None else self._default_ttl
        self._store[pending_id] = PendingMemory(
            pending_id=pending_id,
            draft=draft,
            ttl_seconds=ttl_seconds,
            chat_id=chat_id,
            image_bytes=image_bytes,
        )
        return pending_id

    def set_message_id(self, pending_id: str, message_id: int) -> None:
        item = self._store.get(pending_id)
        if item is not None:
            item.message_id = message_id

    def cleanup_with_details(self) -> list[PendingMemory]:
        expired = [item for item in self._store.values() if self._is_expired(item)]
        for item in expired:
            del self._store[item.pending_id]
        return expired

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
        expired = [pid for pid, item in self._store.items() if self._is_expired(item)]
        for pid in expired:
            del self._store[pid]
        return len(expired)

    def _is_expired(self, item: PendingMemory) -> bool:
        now = datetime.now(UTC)
        elapsed = (now - item.created_at).total_seconds()
        return elapsed >= item.ttl_seconds
