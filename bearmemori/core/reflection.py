import asyncio
import json
import logging
import uuid
import zoneinfo
from datetime import UTC, datetime
from pathlib import Path

from bearmemori.events.domain import SendMessage
from bearmemori.storage.models import Actor, MemoryRecord

logger = logging.getLogger(__name__)


def _is_within_window(current_hour: int, start_hour: int, end_hour: int) -> bool:
    """Return True if current_hour is within [start_hour, end_hour).

    If start_hour == end_hour, always returns True (no restriction).
    """
    if start_hour == end_hour:
        return True
    return start_hour <= current_hour < end_hour


def _is_candidate(record: MemoryRecord, settings) -> bool:
    """Return True if the record should be reviewed by reflection."""
    age_days = (datetime.now(UTC) - record.created_at).days
    if record.importance <= 2 and age_days >= settings.reflection_low_importance_age_days:
        return True
    if record.needs_review and age_days >= settings.reflection_needs_review_age_days:
        return True
    if 3 <= record.importance <= 7 and age_days >= settings.reflection_mid_importance_age_days:
        return True
    return False


class ReflectionTask:
    def __init__(self, db, vector_store, llm, bus, settings) -> None:
        self._db = db
        self._vector_store = vector_store
        self._llm = llm
        self._bus = bus
        self._settings = settings

    async def run_once(self, triggered_by: str = "scheduler") -> dict:
        run_id = f"ref_{uuid.uuid4().hex[:8]}"
        started_at = datetime.now(UTC)
        logger.info("Reflection run started: %s (triggered_by=%s)", run_id, triggered_by)

        all_records = self._db.list_all(limit=10000)
        candidates = [r for r in all_records if _is_candidate(r, self._settings)]

        archived = 0
        reranked = 0
        kept_unchanged = 0
        decisions = []

        for record in candidates:
            try:
                decision = await self._llm.reflect_memory(record)
            except Exception as e:
                logger.warning("reflect_memory failed for %s: %s", record.id, e)
                continue

            action = decision.get("action", "keep")
            new_importance = decision.get("new_importance")
            reason = decision.get("reason", "")

            old_importance = record.importance

            if action == "archive":
                record.archived = True
                self._db.update(record, actor=Actor.REFLECTION)
                self._vector_store.delete(record.id)
                archived += 1
            elif new_importance is not None:
                clamped = max(1, min(10, int(new_importance)))
                if clamped != record.importance:
                    record.importance = clamped
                    self._db.update(record, actor=Actor.REFLECTION)
                    self._vector_store.update(record)
                    reranked += 1
                else:
                    kept_unchanged += 1
            else:
                kept_unchanged += 1

            decisions.append(
                {
                    "memory_id": record.id,
                    "action": action,
                    "old_importance": old_importance,
                    "new_importance": new_importance,
                    "reason": reason,
                }
            )

        finished_at = datetime.now(UTC)
        summary = {
            "run_id": run_id,
            "triggered_by": triggered_by,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "candidates_evaluated": len(candidates),
            "archived": archived,
            "reranked": reranked,
            "kept_unchanged": kept_unchanged,
            "decisions": decisions,
        }

        self._write_log(summary)
        await self._notify(summary)

        logger.info(
            "Reflection run complete: %s — archived=%d reranked=%d kept=%d",
            run_id,
            archived,
            reranked,
            kept_unchanged,
        )
        return summary

    def _write_log(self, summary: dict) -> None:
        log_path = self._settings.reflection_log_path
        if not log_path:
            return
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(json.dumps(summary) + "\n")
        except OSError as e:
            logger.error("Failed to write reflection log: %s", e)

    async def _notify(self, summary: dict) -> None:
        archived = summary["archived"]
        reranked = summary["reranked"]
        kept = summary["kept_unchanged"]
        run_id = summary["run_id"]
        triggered_by = summary["triggered_by"]

        archived_titles = [d["memory_id"] for d in summary["decisions"] if d["action"] == "archive"]

        lines = [
            f"Reflection complete ({run_id}, triggered by {triggered_by}):",
            f"  Archived: {archived}",
            f"  Reranked: {reranked}",
            f"  Kept unchanged: {kept}",
        ]
        if archived_titles:
            lines.append("  Archived memories: " + ", ".join(archived_titles[:10]))

        await self._bus.emit(SendMessage(chat_id="", text="\n".join(lines)))

    async def run(self) -> None:
        logger.info(
            "Reflection scheduler started (poll every %ds, window %d-%d)",
            self._settings.reflection_poll_interval_seconds,
            self._settings.reflection_start_hour,
            self._settings.reflection_end_hour,
        )
        while True:
            await asyncio.sleep(self._settings.reflection_poll_interval_seconds)
            try:
                tz = zoneinfo.ZoneInfo(self._settings.user_timezone)
                now_local_hour = datetime.now(tz).hour
            except Exception:
                now_local_hour = datetime.now(UTC).hour  # fallback to UTC

            if _is_within_window(
                now_local_hour,
                self._settings.reflection_start_hour,
                self._settings.reflection_end_hour,
            ):
                try:
                    await self.run_once(triggered_by="scheduler")
                except Exception:
                    logger.exception("Error during reflection run")
