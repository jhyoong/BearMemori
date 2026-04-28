import asyncio
import json
import logging
import uuid
import zoneinfo
from datetime import UTC, datetime
from pathlib import Path

from bearmemori.core.reflection_state import ReflectionState
from bearmemori.events.domain import SendMessage
from bearmemori.storage.models import MemoryRecord

logger = logging.getLogger(__name__)


def _is_within_window(current_hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour == end_hour:
        return True
    return start_hour <= current_hour < end_hour


def _is_age_candidate(record: MemoryRecord, settings) -> bool:
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
        self._state = ReflectionState(settings.reflection_state_path)

    async def run_once(self, triggered_by: str = "scheduler") -> dict:
        run_id = f"ref_{uuid.uuid4().hex[:8]}"
        started_at = datetime.now(UTC)
        logger.info("Reflection run started: %s (triggered_by=%s)", run_id, triggered_by)

        last_run = self._state.load_last_run()
        all_records = self._db.list_all(limit=10000)

        if last_run is None:
            in_scope = list(all_records)
        else:
            in_scope = [r for r in all_records if r.created_at > last_run]

        skip_ids = self._db.memory_ids_in_pending_proposals()

        merge_count, consumed = await self._duplicate_pass(in_scope, all_records, skip_ids)
        archive_count, rerank_count = await self._archive_rerank_pass(in_scope, skip_ids, consumed)

        finished_at = datetime.now(UTC)
        self._state.save_last_run(finished_at)

        summary = {
            "run_id": run_id,
            "triggered_by": triggered_by,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "scanned": len(in_scope),
            "skipped": len(skip_ids),
            "proposals_created": merge_count + archive_count + rerank_count,
            "merge_proposals": merge_count,
            "archive_proposals": archive_count,
            "rerank_proposals": rerank_count,
        }
        self._write_log(summary)
        await self._notify(summary)
        logger.info(
            "Reflection run complete: %s — proposals=%d (merge=%d archive=%d rerank=%d)",
            run_id,
            summary["proposals_created"],
            merge_count,
            archive_count,
            rerank_count,
        )
        return summary

    async def _duplicate_pass(self, in_scope, all_records, skip_ids):
        # Filled in by Task 2.
        return 0, set()

    async def _archive_rerank_pass(self, in_scope, skip_ids, consumed_ids):
        # Filled in by Task 3.
        return 0, 0

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
        lines = [
            f"Reflection complete ({summary['run_id']}, triggered by {summary['triggered_by']}):",
            f"  Proposals created: {summary['proposals_created']}",
            f"    merge: {summary['merge_proposals']}",
            f"    archive: {summary['archive_proposals']}",
            f"    rerank: {summary['rerank_proposals']}",
        ]
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
                now_local_hour = datetime.now(UTC).hour

            if _is_within_window(
                now_local_hour,
                self._settings.reflection_start_hour,
                self._settings.reflection_end_hour,
            ):
                try:
                    await self.run_once(triggered_by="scheduler")
                except Exception:
                    logger.exception("Error during reflection run")
