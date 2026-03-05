"""Builds pre-loaded context briefing for the assistant."""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class BriefingBuilder:
    """Builds a context briefing from the user's data."""

    def __init__(self, core_client, context_manager, budget_tokens: int):
        self._core_client = core_client
        self._context_manager = context_manager
        self._budget_tokens = budget_tokens

    async def build(self, user_id: int) -> str:
        """Build the briefing string for a user.

        Fetches upcoming tasks, reminders, and the last session summary.
        Formats into compact text within the token budget.
        """
        sections = []

        # 0. Time and timezone context
        try:
            settings = await self._core_client.get_settings(user_id)
            tz_name = settings.timezone
        except Exception:
            tz_name = "UTC"

        try:
            user_tz = ZoneInfo(tz_name)
        except Exception:
            user_tz = ZoneInfo("UTC")

        now_utc = datetime.now(timezone.utc)
        now_user = now_utc.astimezone(user_tz)

        sections.append(
            f"## Time Context\n"
            f"User timezone: {tz_name}\n"
            f"Current time (user): {now_user.strftime('%Y-%m-%d %H:%M %Z')}\n"
            f"Current time (UTC): {now_utc.strftime('%Y-%m-%d %H:%M UTC')}"
        )

        # 1. Upcoming tasks (NOT_DONE, up to 20)
        try:
            tasks = await self._core_client.list_tasks(
                owner_user_id=user_id, state="NOT_DONE"
            )
            tasks = tasks[:20]
        except Exception:
            logger.exception("Failed to fetch tasks for briefing")
            tasks = []

        if tasks:
            lines = ["## Upcoming Tasks"]
            for t in tasks:
                due = f" due:{t.due_at}" if t.due_at else ""
                lines.append(f"- [TASK {t.id}]{due} \"{t.description}\"")
            sections.append("\n".join(lines))
        else:
            sections.append("## Upcoming Tasks\nNo upcoming tasks.")

        # 2. Upcoming reminders (unfired, up to 20)
        try:
            reminders = await self._core_client.list_reminders(
                owner_user_id=user_id, upcoming_only=True
            )
            reminders = reminders[:20]
        except Exception:
            logger.exception("Failed to fetch reminders for briefing")
            reminders = []

        if reminders:
            lines = ["## Upcoming Reminders"]
            for r in reminders:
                lines.append(f"- [REMINDER {r.id}] fires:{r.fire_at} \"{r.text}\"")
            sections.append("\n".join(lines))
        else:
            sections.append("## Upcoming Reminders\nNo upcoming reminders.")

        # 3. Previous session summary
        try:
            summary = await self._context_manager.load_session_summary(user_id)
        except Exception:
            logger.exception("Failed to load session summary")
            summary = None

        if summary:
            sections.append(f"## Previous Conversation\n{summary}")

        # Combine and trim to budget
        briefing = "\n\n".join(sections)
        briefing = self._trim_to_budget(briefing)
        return briefing

    def _trim_to_budget(self, text: str) -> str:
        """Trim briefing text to fit within the token budget."""
        tokens = self._context_manager.count_tokens(text)
        if tokens <= self._budget_tokens:
            return text

        # Trim line by line from the end until within budget
        lines = text.split("\n")
        while lines and self._context_manager.count_tokens("\n".join(lines)) > self._budget_tokens:
            lines.pop()
        return "\n".join(lines)
