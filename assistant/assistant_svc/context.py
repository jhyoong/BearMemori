"""Chat history context management with summarize-and-truncate."""

import json
import logging

import tiktoken

logger = logging.getLogger(__name__)


class ContextManager:
    """Manages chat history in Redis with token-aware truncation."""

    def __init__(
        self,
        redis,
        context_window_tokens: int,
        briefing_budget_tokens: int,
        response_reserve_tokens: int,
        session_timeout_seconds: int,
    ):
        self._redis = redis
        self._context_window_tokens = context_window_tokens
        self._briefing_budget_tokens = briefing_budget_tokens
        self._response_reserve_tokens = response_reserve_tokens
        self._session_timeout_seconds = session_timeout_seconds
        self._encoder = tiktoken.encoding_for_model("gpt-4o")

    def chat_budget_tokens(self, system_prompt_tokens: int) -> int:
        """Available tokens for chat history after subtracting other segments.

        Args:
            system_prompt_tokens: Actual token count of the system prompt
                (including briefing text).
        """
        return (
            self._context_window_tokens
            - self._briefing_budget_tokens
            - self._response_reserve_tokens
            - system_prompt_tokens
        )

    def count_tokens(self, text: str) -> int:
        """Count tokens in a text string."""
        return len(self._encoder.encode(text))

    def count_messages_tokens(self, messages: list[dict]) -> int:
        """Count total tokens across all message contents."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.count_tokens(content)
            elif isinstance(content, (dict, list)):
                total += self.count_tokens(json.dumps(content))
        return total

    def needs_summarization(
        self, messages: list[dict], system_prompt_tokens: int = 0
    ) -> bool:
        """Check if chat history exceeds 70% of the chat budget."""
        threshold = int(self.chat_budget_tokens(system_prompt_tokens) * 0.7)
        return self.count_messages_tokens(messages) > threshold

    async def load_history(self, user_id: int) -> list[dict]:
        """Load chat history from Redis."""
        raw = await self._redis.get(f"assistant:chat:{user_id}")
        if raw is None:
            return []
        return json.loads(raw)

    async def save_history(self, user_id: int, messages: list[dict]) -> None:
        """Save chat history to Redis with 24h TTL."""
        await self._redis.set(
            f"assistant:chat:{user_id}",
            json.dumps(messages),
            ex=86400,
        )

    async def save_session_summary(self, user_id: int, summary: str) -> None:
        """Save session summary to Redis with 7-day TTL."""
        await self._redis.set(
            f"assistant:summary:{user_id}",
            summary,
            ex=604800,
        )

    async def load_session_summary(self, user_id: int) -> str | None:
        """Load previous session summary. Returns None if not found."""
        raw = await self._redis.get(f"assistant:summary:{user_id}")
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else raw
