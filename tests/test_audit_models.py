from datetime import UTC, datetime

from bearmemori.storage.models import Actor, AuditEntry


def test_actor_values():
    assert Actor.TELEGRAM.value == "telegram"
    assert Actor.WEBAPP.value == "webapp"
    assert Actor.API.value == "api"
    assert Actor.REFLECTION.value == "reflection"


def test_audit_entry_roundtrip():
    entry = AuditEntry(
        id=1,
        memory_id="mem_abc",
        action="create",
        actor=Actor.API,
        timestamp=datetime(2026, 4, 26, tzinfo=UTC),
        title_snapshot="hello",
        category_snapshot="general",
    )
    dumped = entry.model_dump(mode="json")
    assert dumped["actor"] == "api"
    assert dumped["action"] == "create"
    assert dumped["title_snapshot"] == "hello"
