"""Tool registry for the assistant agent."""

import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

ToolFunction = Callable[..., Coroutine[Any, Any, dict | str | list | None]]


class ToolRegistry:
    """Registry mapping tool names to functions and OpenAI schemas."""

    def __init__(self):
        self._tools: dict[str, ToolFunction] = {}
        self._schemas: dict[str, dict] = {}

    def register(self, name: str, func: ToolFunction, schema: dict) -> None:
        self._tools[name] = func
        self._schemas[name] = schema

    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_function(self, name: str) -> ToolFunction:
        return self._tools[name]

    def get_schema(self, name: str) -> dict:
        return self._schemas[name]

    def get_all_schemas(self) -> list[dict]:
        return list(self._schemas.values())

    async def execute(self, name: str, client, **kwargs) -> dict | str | list | None:
        func = self._tools[name]
        return await func(client, **kwargs)
