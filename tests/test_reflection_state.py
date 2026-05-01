from datetime import UTC, datetime

from bearmemori.core.reflection_state import ReflectionState


def test_load_returns_none_when_missing(tmp_path):
    state = ReflectionState(str(tmp_path / "state.json"))
    assert state.load_last_run() is None


def test_save_then_load_roundtrip(tmp_path):
    state = ReflectionState(str(tmp_path / "state.json"))
    now = datetime.now(UTC)
    state.save_last_run(now)
    loaded = state.load_last_run()
    assert loaded is not None
    assert loaded.isoformat() == now.isoformat()


def test_save_creates_parent_dirs(tmp_path):
    nested = tmp_path / "deep" / "deeper" / "state.json"
    state = ReflectionState(str(nested))
    state.save_last_run(datetime.now(UTC))
    assert nested.exists()
