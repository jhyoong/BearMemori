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
