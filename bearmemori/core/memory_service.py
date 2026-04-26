from __future__ import annotations

import logging
import uuid
from pathlib import Path

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryDraft, MemoryRecord
from bearmemori.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(
        self,
        db: MemoryDatabase,
        vector_store: VectorStore,
        image_storage_dir: str = "",
    ) -> None:
        self._db = db
        self._vector_store = vector_store
        self._image_storage_dir = image_storage_dir

    def search(self, query: str, top_k: int = 5, category: str | None = None) -> list[dict]:
        return self._vector_store.search(query=query, top_k=top_k, category=category)

    def retrieve_context(self, query: str, top_k: int = 5, event_days: int = 7) -> dict:
        semantic_results = self._vector_store.search(query=query, top_k=top_k * 2)
        upcoming_events = self._db.get_upcoming_events(days=event_days)

        scored = []
        for r in semantic_results:
            distance = r.get("distance", 1.0)
            similarity = max(0.0, 1.0 - distance)
            importance = r.get("metadata", {}).get("importance", 5) / 10.0
            combined = 0.5 * similarity + 0.5 * importance
            scored.append((combined, r))
        scored.sort(key=lambda x: x[0], reverse=True)

        filtered = []
        for score, r in scored:
            imp = r.get("metadata", {}).get("importance", 5)
            distance = r.get("distance", 1.0)
            similarity = max(0.0, 1.0 - distance)
            if imp <= 2 and similarity < 0.7:
                continue
            filtered.append(r)
            if len(filtered) >= top_k:
                break

        high_imp = [
            r
            for _, r in scored
            if r.get("metadata", {}).get("importance", 5) >= 8 and r not in filtered
        ]
        filtered.extend(high_imp[: max(0, top_k - len(filtered))])

        lines = []
        if filtered:
            lines.append("## Relevant Memories")
            for r in filtered:
                lines.append(f"- {r['document']}")
        if upcoming_events:
            lines.append("\n## Upcoming Events")
            for e in upcoming_events:
                dt = e.event_fields.datetime if e.event_fields else "unknown"
                lines.append(f"- [{dt}] {e.title}: {e.content}")

        items = filtered + [
            {
                "id": e.id,
                "document": f"{e.title}: {e.content}",
                "metadata": {"category": e.category.value},
            }
            for e in upcoming_events
        ]
        return {"context_block": "\n".join(lines) if lines else "", "items": items}

    def list(
        self,
        category: str | None = None,
        needs_review: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        limit = min(limit, 200)
        if category is not None:
            cat = MemoryCategory(category)
            records = self._db.list_by_category(cat, offset=offset, limit=limit)
        else:
            records = self._db.list_all(offset=offset, limit=limit)
        if needs_review is not None:
            records = [r for r in records if r.needs_review == needs_review]
        return records

    def get(self, record_id: str) -> MemoryRecord | None:
        return self._db.get(record_id)

    def create(self, draft: MemoryDraft, actor: Actor = Actor.API) -> MemoryRecord:
        record_id = f"mem_{uuid.uuid4().hex[:12]}"
        record = MemoryRecord.from_draft(draft, record_id=record_id)
        self._db.create(record, actor=actor)
        self._vector_store.add(record)
        logger.info("Created memory: %s", record_id)
        return record

    def update(self, record_id: str, updates: dict) -> MemoryRecord | None:
        record = self._db.get(record_id)
        if record is None:
            return None
        allowed = {
            "title",
            "content",
            "category",
            "tags",
            "needs_review",
            "importance",
            "event_status",
            "event_datetime",
            "event_recurrence",
        }
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key == "category":
                record.category = MemoryCategory(value)
            elif key == "event_status" and record.event_fields:
                record.event_fields.status = value
            elif key == "event_datetime" and record.event_fields:
                record.event_fields.datetime = value
            elif key == "event_recurrence" and record.event_fields:
                record.event_fields.recurrence = value
            else:
                setattr(record, key, value)
        self._db.update(record)
        self._vector_store.update(record)
        return record

    def delete(self, record_id: str, actor: Actor = Actor.API) -> bool:
        self._delete_image(record_id)
        deleted = self._db.delete(record_id, actor=actor)
        if deleted:
            self._vector_store.delete(record_id)
        return deleted

    def bulk_delete(self, record_ids: list[str], actor: Actor = Actor.API) -> int:
        count = 0
        for record_id in record_ids:
            if self.delete(record_id, actor=actor):
                count += 1
        return count

    def bulk_update(self, record_ids: list[str], updates: dict) -> int:
        count = 0
        for record_id in record_ids:
            if self.update(record_id, updates) is not None:
                count += 1
        return count

    def _delete_image(self, record_id: str) -> None:
        if not self._image_storage_dir:
            return
        record = self._db.get(record_id)
        if record and record.image_path:
            file_path = Path(self._image_storage_dir) / record.image_path
            if file_path.exists():
                file_path.unlink()
                logger.info("Deleted image: %s", file_path)
