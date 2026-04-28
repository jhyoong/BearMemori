import asyncio
import json
import logging
import uuid
import zoneinfo
from datetime import UTC, datetime
from pathlib import Path

from bearmemori.core.reflection_state import ReflectionState
from bearmemori.events.domain import SendMessage
from bearmemori.storage.models import MemoryRecord, ReflectionProposal

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

    async def _duplicate_pass(
        self,
        in_scope: list[MemoryRecord],
        all_records: list[MemoryRecord],
        skip_ids: set[str],
    ) -> tuple[int, set[str]]:
        threshold = self._settings.reflection_duplicate_similarity_threshold
        top_k = self._settings.reflection_duplicate_top_k
        cooldown = self._settings.reflection_reject_cooldown_days

        by_id = {r.id: r for r in all_records}
        seen_groups: set[tuple[str, ...]] = set()
        consumed: set[str] = set()
        proposals_created = 0

        for memory in in_scope:
            if memory.id in skip_ids or memory.id in consumed:
                continue

            query_text = f"{memory.title}: {memory.content}"
            try:
                neighbors = self._vector_store.search(query_text, top_k=top_k)
            except Exception as e:
                logger.warning("vector_store.search failed for %s: %s", memory.id, e)
                continue

            group_ids: set[str] = {memory.id}
            for n in neighbors:
                nid = n.get("id")
                if nid is None or nid == memory.id or nid in skip_ids:
                    continue
                distance = n.get("distance")
                if distance is None:
                    continue
                similarity = 1.0 - float(distance)
                if similarity < threshold:
                    continue
                other = by_id.get(nid)
                if other is None or other.archived:
                    continue
                if other.category != memory.category:
                    continue
                group_ids.add(nid)

            if len(group_ids) < 2:
                continue

            key = tuple(sorted(group_ids))
            if key in seen_groups:
                continue
            seen_groups.add(key)

            if self._db.merge_group_recently_rejected(memory_ids=list(key), cooldown_days=cooldown):
                continue

            records = [by_id[i] for i in key]
            try:
                decision = await self._llm.reflect_duplicates(records)
            except Exception as e:
                logger.warning("reflect_duplicates failed for %s: %s", key, e)
                continue

            if not decision.get("is_duplicate"):
                continue

            keep_id = decision.get("keep_id")
            if keep_id not in group_ids:
                keep_id = sorted(group_ids)[0]

            proposal = ReflectionProposal(
                id=f"prop_{uuid.uuid4().hex[:12]}",
                proposal_type="merge",
                status="pending",
                memory_ids=list(key),
                recommended_keep_id=keep_id,
                reasoning=decision.get("reasoning", ""),
                created_at=datetime.now(UTC),
            )
            self._db.create_proposal(proposal)
            proposals_created += 1
            consumed.update(group_ids)

        return proposals_created, consumed

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
