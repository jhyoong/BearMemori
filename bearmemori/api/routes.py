import uuid

from fastapi import FastAPI, HTTPException

from bearmemori.api.schemas import (
    MemoryCreate,
    MemoryResponse,
    MemoryUpdate,
    ReminderResponse,
    SearchRequest,
)
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Memory


def create_app(db: MemoryDatabase) -> FastAPI:
    app = FastAPI(title="BearMemori", version="0.3.0")

    @app.get("/memories", response_model=list[MemoryResponse])
    def list_memories(
        memory_type: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        return db.list_memories(memory_type=memory_type, tag=tag, limit=limit, offset=offset)

    @app.post("/memories/search", response_model=list[MemoryResponse])
    def search_memories(body: SearchRequest):
        if body.mode == "keyword":
            return db.search_keyword(body.query, limit=body.limit)
        # semantic and hybrid search added in Task 13
        return db.search_keyword(body.query, limit=body.limit)

    @app.get("/memories/{memory_id}", response_model=MemoryResponse)
    def get_memory(memory_id: str):
        memory = db.get(memory_id)
        if not memory:
            raise HTTPException(status_code=404, detail="Memory not found")
        return memory

    @app.post("/memories", response_model=MemoryResponse, status_code=201)
    def create_memory(body: MemoryCreate):
        memory = Memory(
            id=str(uuid.uuid4()),
            content=body.content,
            raw_input=body.raw_input or body.content,
            memory_type=body.memory_type,
            tags=body.tags,
            source=body.source,
            metadata=body.metadata,
        )
        db.create(memory)
        return memory

    @app.put("/memories/{memory_id}", response_model=MemoryResponse)
    def update_memory(memory_id: str, body: MemoryUpdate):
        memory = db.get(memory_id)
        if not memory:
            raise HTTPException(status_code=404, detail="Memory not found")
        if body.content is not None:
            memory.content = body.content
        if body.memory_type is not None:
            memory.memory_type = body.memory_type
        if body.tags is not None:
            memory.tags = body.tags
        if body.metadata is not None:
            memory.metadata = body.metadata
        db.update(memory)
        return memory

    @app.delete("/memories/{memory_id}", status_code=204)
    def delete_memory(memory_id: str):
        memory = db.get(memory_id)
        if not memory:
            raise HTTPException(status_code=404, detail="Memory not found")
        db.delete(memory_id)

    @app.get("/reminders", response_model=list[ReminderResponse])
    def list_active_reminders():
        return db.get_active_reminders()

    @app.get("/reminders/due", response_model=list[ReminderResponse])
    def list_due_reminders():
        return db.get_due_reminders()

    return app
