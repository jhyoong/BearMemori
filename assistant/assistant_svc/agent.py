"""Core agent with OpenAI tool-calling loop."""

import json
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a personal assistant with access to the user's memories, tasks, reminders, and events from BearMemori.

You help the user by:
- Answering questions about their stored memories
- Finding relevant information from their data
- Creating tasks and reminders when asked (always confirm before writing)
- Providing proactive suggestions based on their context

For write operations (creating tasks, reminders), ALWAYS ask the user to confirm before executing.

## Current Context
{briefing}
"""

SUMMARIZE_PROMPT = "Summarize this conversation concisely, preserving key facts, decisions, and context that would be useful for continuing the conversation:\n\n{conversation}"

MAX_TOOL_ITERATIONS = 10


class Agent:
    """Conversational agent with OpenAI tool-calling."""

    def __init__(
        self,
        openai_client,
        model: str,
        core_client,
        context_manager,
        briefing_builder,
        tool_registry,
    ):
        self._openai = openai_client
        self._model = model
        self._core_client = core_client
        self._context = context_manager
        self._briefing = briefing_builder
        self._tools = tool_registry

    async def handle_message(self, user_id: int, text: str) -> str:
        """Process a user message and return the assistant's response."""
        # 1. Load history
        history = await self._context.load_history(user_id)

        # 3. Build briefing and system prompt
        briefing = await self._briefing.build(user_id)
        system_content = SYSTEM_PROMPT.format(briefing=briefing)
        system_prompt_tokens = self._context.count_tokens(system_content)

        # 2. Summarize if needed (uses actual system prompt token count)
        if history and self._context.needs_summarization(history, system_prompt_tokens):
            history = await self._summarize_history(history)

        # 4. Construct messages
        system_msg = {"role": "system", "content": system_content}
        messages = [system_msg] + history + [{"role": "user", "content": text}]

        # 5. Get tool schemas
        tool_schemas = self._tools.get_all_schemas()
        tools_arg = tool_schemas if tool_schemas else None

        # 6. Tool-calling loop
        response_text = await self._run_tool_loop(messages, tools_arg, user_id)

        # 7. Update and save history
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": response_text})
        await self._context.save_history(user_id=user_id, messages=history)

        return response_text

    async def _run_tool_loop(
        self, messages: list[dict], tools: list[dict] | None, user_id: int
    ) -> str:
        """Call OpenAI in a loop, executing tool calls until we get a text response."""
        for _ in range(MAX_TOOL_ITERATIONS):
            kwargs = {"model": self._model, "messages": messages}
            if tools:
                kwargs["tools"] = tools

            response = await self._openai.chat.completions.create(**kwargs)
            choice = response.choices[0]
            msg = choice.message

            if not msg.tool_calls:
                return msg.content or ""

            # Append assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            # Execute each tool call
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                # Inject owner_user_id
                args["owner_user_id"] = user_id

                try:
                    result = await self._tools.execute(name, self._core_client, **args)
                except Exception as e:
                    logger.exception(f"Tool {name} failed")
                    result = {"error": str(e)}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result) if not isinstance(result, str) else result,
                })

        # If we hit max iterations, return whatever we have
        logger.warning("Hit max tool iterations for user %d", user_id)
        return "I'm having trouble processing your request. Could you try rephrasing?"

    async def _summarize_history(self, history: list[dict]) -> list[dict]:
        """Summarize the oldest half of the history."""
        mid = len(history) // 2
        old_messages = history[:mid]
        recent_messages = history[mid:]

        # Format old messages for summarization
        conversation = "\n".join(
            f"{m['role']}: {m['content']}" for m in old_messages if m.get("content")
        )

        prompt = SUMMARIZE_PROMPT.format(conversation=conversation)
        response = await self._openai.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response.choices[0].message.content or ""

        # Replace old messages with summary
        summary_msg = {"role": "system", "content": f"Summary of earlier conversation: {summary}"}
        return [summary_msg] + recent_messages
