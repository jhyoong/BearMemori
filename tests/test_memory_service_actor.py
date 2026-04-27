from unittest.mock import MagicMock

from bearmemori.core.memory_service import MemoryService
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryDraft


def _make_service(tmp_path):
    db = MemoryDatabase(str(tmp_path / "t.db"))
    db.initialize()
    vec = MagicMock()
    return MemoryService(db=db, vector_store=vec), db


def test_service_create_propagates_actor(tmp_path):
    service, db = _make_service(tmp_path)
    draft = MemoryDraft(category=MemoryCategory.GENERAL, title="hi", content="c")
    record = service.create(draft, actor=Actor.TELEGRAM)
    entries = db.list_audit(memory_id=record.id)
    assert entries[0].actor == Actor.TELEGRAM


def test_service_update_propagates_actor(tmp_path):
    service, db = _make_service(tmp_path)
    record = service.create(
        MemoryDraft(category=MemoryCategory.GENERAL, title="x", content="c"),
        actor=Actor.API,
    )
    service.update(record.id, {"title": "y"}, actor=Actor.WEBAPP)
    entries = db.list_audit(memory_id=record.id, action="update")
    assert entries[0].actor == Actor.WEBAPP


def test_service_delete_propagates_actor(tmp_path):
    service, db = _make_service(tmp_path)
    record = service.create(
        MemoryDraft(category=MemoryCategory.GENERAL, title="x", content="c"),
        actor=Actor.API,
    )
    service.delete(record.id, actor=Actor.REFLECTION)
    entries = db.list_audit(memory_id=record.id, action="delete")
    assert entries[0].actor == Actor.REFLECTION


def test_service_bulk_delete_propagates_actor(tmp_path):
    service, db = _make_service(tmp_path)
    ids = []
    for i in range(3):
        rec = service.create(
            MemoryDraft(category=MemoryCategory.GENERAL, title=f"t{i}", content="c"),
            actor=Actor.API,
        )
        ids.append(rec.id)
    service.bulk_delete(ids, actor=Actor.WEBAPP)
    entries = db.list_audit(action="delete")
    assert {e.actor for e in entries} == {Actor.WEBAPP}
    assert len(entries) == 3
