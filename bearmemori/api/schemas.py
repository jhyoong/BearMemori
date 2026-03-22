from pydantic import BaseModel, Field


class TriageRequest(BaseModel):
    conversation: list[dict] = Field(min_length=1)
    memory_hint: dict | None = None


class ConfirmRequest(BaseModel):
    pending_id: str


class SearchRequest(BaseModel):
    query: str
    category: str | None = None
    top_k: int = 5


class UpdateMemoryRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    needs_review: bool | None = None


class CreateMemoryRequest(BaseModel):
    category: str
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)


class BulkDeleteRequest(BaseModel):
    record_ids: list[str]


class BulkUpdateRequest(BaseModel):
    record_ids: list[str]
    updates: dict
