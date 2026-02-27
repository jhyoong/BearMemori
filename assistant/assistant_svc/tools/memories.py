"""Memory-related tools for the assistant agent."""

import logging

logger = logging.getLogger(__name__)

SEARCH_MEMORIES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_memories",
        "description": "Search the user's memories using full-text search. Returns up to 10 matching memories with their tags and relevance scores.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant memories",
                }
            },
            "required": ["query"],
        },
    },
}


async def search_memories(client, *, query: str, owner_user_id: int, **kwargs) -> list[dict]:
    """Search memories and return formatted results."""
    results = await client.search_memories(query=query, owner_user_id=owner_user_id)
    return [
        {
            "memory_id": r.memory.id,
            "content": r.memory.content,
            "tags": [t.tag for t in r.memory.tags],
            "score": r.score,
        }
        for r in results
    ]


GET_MEMORY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_memory",
        "description": "Get full details of a specific memory by its ID, including all tags.",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "The ID of the memory to retrieve",
                }
            },
            "required": ["memory_id"],
        },
    },
}


async def get_memory(client, *, memory_id: str, **kwargs) -> dict | None:
    """Get a memory by ID and return formatted result."""
    mem = await client.get_memory(memory_id)
    if mem is None:
        return {"error": "Memory not found"}
    return {
        "id": mem.id,
        "content": mem.content,
        "status": mem.status,
        "is_pinned": mem.is_pinned,
        "tags": [t.tag for t in mem.tags],
        "created_at": str(mem.created_at),
    }
