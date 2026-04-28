from bearmemori.config import Settings


def test_reflection_defaults():
    s = Settings(
        telegram_bot_token="x",
        telegram_allowed_user_id=1,
    )
    assert s.reflection_start_hour == 2
    assert s.reflection_end_hour == 6
    assert s.reflection_poll_interval_seconds == 3600
    assert s.reflection_low_importance_age_days == 30
    assert s.reflection_needs_review_age_days == 21
    assert s.reflection_mid_importance_age_days == 90
    assert s.reflection_log_path == "data/reflection.log"


def _settings_with_required(**overrides):
    return Settings(api_only_mode=True, **overrides)


def test_reflection_duplicate_settings_have_defaults():
    s = _settings_with_required()
    assert s.reflection_duplicate_similarity_threshold == 0.85
    assert s.reflection_duplicate_top_k == 5
    assert s.reflection_reject_cooldown_days == 30
    assert s.reflection_state_path == "data/reflection_state.json"


def test_reflection_duplicate_settings_can_be_overridden(monkeypatch):
    monkeypatch.setenv("REFLECTION_DUPLICATE_SIMILARITY_THRESHOLD", "0.9")
    monkeypatch.setenv("REFLECTION_DUPLICATE_TOP_K", "10")
    s = _settings_with_required()
    assert s.reflection_duplicate_similarity_threshold == 0.9
    assert s.reflection_duplicate_top_k == 10
