# Phase 4, Group 5: Tests

## Context

This group creates the full test suite for the Email Poller service. Tests should be written alongside each group during implementation (test Group N modules before moving to Group N+1), but this plan consolidates all test files for reference.

**Test pattern reference:** `tests/conftest.py` -- the root conftest adds `llm_worker/` to `sys.path` for imports. We need the same for `email_poller/`.

**Test infrastructure:**
- `fakeredis.aioredis` for Redis (already a test dependency, used in `tests/conftest.py`)
- `unittest.mock.AsyncMock` for mocking async clients
- `email.mime.text.MIMEText` for building synthetic email messages in tests
- `pytest-asyncio` for async test functions

---

## Files to Create

### 1. `tests/test_email_poller/__init__.py`

Empty file.

### 2. `tests/test_email_poller/conftest.py`

Shared fixtures for email poller tests.

```python
"""Shared test fixtures for email poller tests."""

import pytest
import pytest_asyncio
import fakeredis.aioredis

from poller.config import EmailAccountConfig, EmailPollerSettings


@pytest.fixture
def sample_account() -> EmailAccountConfig:
    """A sample email account config for testing."""
    return EmailAccountConfig(
        provider="gmail",
        email="test@gmail.com",
        password="app-password-123",
        user_id=12345,
        folder="INBOX",
        filter_senders=["noreply@spam.com"],
        filter_subjects=["unsubscribe", "newsletter"],
    )


@pytest.fixture
def email_poller_config() -> EmailPollerSettings:
    """Email poller settings for testing."""
    return EmailPollerSettings(
        redis_url="redis://localhost:6379",
        core_api_url="http://localhost:8000",
        poll_interval_seconds=10,
        email_accounts="[]",
        imap_timeout_seconds=5,
        dedup_ttl_seconds=3600,
    )


@pytest.fixture
def sample_email() -> dict:
    """A sample parsed email dict."""
    return {
        "message_id": "<test-123@mail.gmail.com>",
        "subject": "Dinner on Friday at 7pm",
        "sender": "friend@example.com",
        "body": "Hey, let's meet for dinner this Friday at 7pm at the Italian place.",
    }


@pytest_asyncio.fixture
async def mock_redis():
    """Fake Redis client for testing."""
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()
```

### 3. `tests/test_email_poller/test_config.py`

Tests for `poller/config.py`.

```python
"""Tests for email poller configuration."""

import pytest
from poller.config import parse_email_accounts, EmailAccountConfig


class TestParseEmailAccounts:
    def test_valid_single_account(self):
        raw = '[{"provider":"gmail","email":"a@b.com","password":"p","user_id":1}]'
        accounts = parse_email_accounts(raw)
        assert len(accounts) == 1
        assert accounts[0].email == "a@b.com"
        assert accounts[0].provider == "gmail"
        assert accounts[0].user_id == 1

    def test_empty_array(self):
        assert parse_email_accounts("[]") == []

    def test_invalid_json(self):
        assert parse_email_accounts("not json") == []

    def test_not_an_array(self):
        assert parse_email_accounts('{"key": "value"}') == []

    def test_unknown_provider_skipped(self):
        raw = '[{"provider":"yahoo","email":"a@b.com","password":"p","user_id":1}]'
        accounts = parse_email_accounts(raw)
        assert len(accounts) == 0

    def test_missing_required_field_skipped(self):
        raw = '[{"provider":"gmail","email":"a@b.com"}]'
        accounts = parse_email_accounts(raw)
        assert len(accounts) == 0

    def test_multiple_accounts_partial_valid(self):
        raw = """[
            {"provider":"gmail","email":"a@b.com","password":"p","user_id":1},
            {"provider":"bad","email":"x@y.com","password":"p","user_id":2},
            {"provider":"outlook","email":"c@d.com","password":"q","user_id":3}
        ]"""
        accounts = parse_email_accounts(raw)
        assert len(accounts) == 2
        assert accounts[0].provider == "gmail"
        assert accounts[1].provider == "outlook"

    def test_defaults(self):
        raw = '[{"provider":"gmail","email":"a@b.com","password":"p","user_id":1}]'
        account = parse_email_accounts(raw)[0]
        assert account.folder == "INBOX"
        assert account.filter_senders == []
        assert account.filter_subjects == []
```

### 4. `tests/test_email_poller/test_imap_client.py`

Tests for `poller/imap_client.py`. Uses synthetic emails built with `email.mime`.

```python
"""Tests for IMAP client and email parsing."""

import email.mime.text
import email.mime.multipart
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from poller.imap_client import (
    parse_email,
    extract_plain_text,
    strip_html_tags,
    fetch_unseen_emails,
    MAX_BODY_LENGTH,
)
from poller.config import EmailAccountConfig


def _make_plain_email(
    subject="Test Subject",
    sender="sender@example.com",
    body="Hello world",
    message_id="<test-1@example.com>",
) -> bytes:
    """Build a plain text email as raw bytes."""
    msg = email.mime.text.MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["Message-ID"] = message_id
    return msg.as_bytes()


def _make_html_email(html_body, message_id="<html-1@example.com>") -> bytes:
    """Build an HTML-only email as raw bytes."""
    msg = email.mime.text.MIMEText(html_body, "html")
    msg["Subject"] = "HTML Email"
    msg["From"] = "sender@example.com"
    msg["Message-ID"] = message_id
    return msg.as_bytes()


def _make_multipart_email(
    plain_body="Plain text version",
    html_body="<p>HTML version</p>",
    message_id="<multi-1@example.com>",
) -> bytes:
    """Build a multipart email with both plain and HTML parts."""
    msg = email.mime.multipart.MIMEMultipart("alternative")
    msg["Subject"] = "Multipart Email"
    msg["From"] = "sender@example.com"
    msg["Message-ID"] = message_id
    msg.attach(email.mime.text.MIMEText(plain_body, "plain"))
    msg.attach(email.mime.text.MIMEText(html_body, "html"))
    return msg.as_bytes()


class TestParseEmail:
    def test_plain_text_email(self):
        raw = _make_plain_email(subject="Lunch tomorrow", body="Meet at noon")
        result = parse_email(raw)
        assert result is not None
        assert result["subject"] == "Lunch tomorrow"
        assert result["body"] == "Meet at noon"
        assert result["sender"] == "sender@example.com"
        assert result["message_id"] == "<test-1@example.com>"

    def test_missing_message_id_returns_none(self):
        msg = email.mime.text.MIMEText("body")
        msg["Subject"] = "No ID"
        msg["From"] = "a@b.com"
        # No Message-ID header
        result = parse_email(msg.as_bytes())
        assert result is None

    def test_invalid_bytes_returns_none(self):
        result = parse_email(b"\x00\x01\x02 not valid email")
        # Should not crash, may return None or a partial result
        # The key thing is no exception is raised


class TestExtractPlainText:
    def test_prefers_plain_over_html(self):
        raw = _make_multipart_email(
            plain_body="Plain version",
            html_body="<p>HTML version</p>",
        )
        msg = email.message_from_bytes(raw)
        text = extract_plain_text(msg)
        assert "Plain version" in text

    def test_falls_back_to_html(self):
        raw = _make_html_email("<p>Only HTML</p>")
        msg = email.message_from_bytes(raw)
        text = extract_plain_text(msg)
        assert "Only HTML" in text
        assert "<p>" not in text  # Tags should be stripped

    def test_truncates_long_body(self):
        long_body = "x" * (MAX_BODY_LENGTH + 1000)
        raw = _make_plain_email(body=long_body)
        msg = email.message_from_bytes(raw)
        text = extract_plain_text(msg)
        assert len(text) == MAX_BODY_LENGTH


class TestStripHtmlTags:
    def test_removes_simple_tags(self):
        assert "Hello" in strip_html_tags("<p>Hello</p>")

    def test_removes_nested_tags(self):
        result = strip_html_tags("<div><span>Content</span></div>")
        assert "Content" in result
        assert "<" not in result

    def test_empty_string(self):
        assert strip_html_tags("") == ""


class TestFetchUnseenEmails:
    @pytest.mark.asyncio
    async def test_delegates_to_thread(self):
        account = EmailAccountConfig(
            provider="gmail",
            email="test@gmail.com",
            password="pass",
            user_id=1,
        )
        mock_results = [{"message_id": "<1>", "subject": "Hi", "sender": "a@b.com", "body": ""}]
        with patch("poller.imap_client._fetch_sync", return_value=mock_results):
            result = await fetch_unseen_emails(account, imap_timeout=10)
            assert result == mock_results
```

### 5. `tests/test_email_poller/test_filters.py`

Tests for `poller/filters.py`.

```python
"""Tests for email filtering."""

from poller.config import EmailAccountConfig
from poller.filters import should_skip


def _account(**overrides) -> EmailAccountConfig:
    defaults = {
        "provider": "gmail",
        "email": "test@gmail.com",
        "password": "pass",
        "user_id": 1,
        "filter_senders": [],
        "filter_subjects": [],
    }
    defaults.update(overrides)
    return EmailAccountConfig(**defaults)


class TestShouldSkip:
    def test_no_filters_returns_false(self):
        account = _account()
        email_data = {"sender": "anyone@example.com", "subject": "Hello"}
        assert should_skip(email_data, account) is False

    def test_sender_match(self):
        account = _account(filter_senders=["noreply@spam.com"])
        email_data = {"sender": "noreply@spam.com", "subject": "Buy now"}
        assert should_skip(email_data, account) is True

    def test_sender_match_case_insensitive(self):
        account = _account(filter_senders=["NOREPLY@SPAM.COM"])
        email_data = {"sender": "noreply@spam.com", "subject": "Buy now"}
        assert should_skip(email_data, account) is True

    def test_sender_substring_match(self):
        account = _account(filter_senders=["spam.com"])
        email_data = {"sender": "offers@spam.com", "subject": "Deal"}
        assert should_skip(email_data, account) is True

    def test_subject_match(self):
        account = _account(filter_subjects=["newsletter"])
        email_data = {"sender": "news@site.com", "subject": "Weekly Newsletter #42"}
        assert should_skip(email_data, account) is True

    def test_subject_match_case_insensitive(self):
        account = _account(filter_subjects=["NEWSLETTER"])
        email_data = {"sender": "news@site.com", "subject": "weekly newsletter"}
        assert should_skip(email_data, account) is True

    def test_no_match(self):
        account = _account(
            filter_senders=["spam.com"],
            filter_subjects=["newsletter"],
        )
        email_data = {"sender": "friend@gmail.com", "subject": "Dinner Friday"}
        assert should_skip(email_data, account) is False

    def test_empty_sender_and_subject(self):
        account = _account(filter_senders=["spam"])
        email_data = {"sender": None, "subject": None}
        assert should_skip(email_data, account) is False
```

### 6. `tests/test_email_poller/test_dedup.py`

Tests for `poller/dedup.py`.

```python
"""Tests for email deduplication."""

import pytest

from poller.dedup import dedup_key, is_duplicate, mark_seen


class TestDedupKey:
    def test_format(self):
        assert dedup_key("user@gmail.com") == "email_poller:seen:user@gmail.com"


class TestDedup:
    @pytest.mark.asyncio
    async def test_unseen_not_duplicate(self, mock_redis):
        result = await is_duplicate(mock_redis, "a@b.com", "<msg-1>")
        assert result is False

    @pytest.mark.asyncio
    async def test_after_mark_seen_is_duplicate(self, mock_redis):
        await mark_seen(mock_redis, "a@b.com", "<msg-1>", ttl_seconds=3600)
        result = await is_duplicate(mock_redis, "a@b.com", "<msg-1>")
        assert result is True

    @pytest.mark.asyncio
    async def test_different_accounts_independent(self, mock_redis):
        await mark_seen(mock_redis, "a@b.com", "<msg-1>", ttl_seconds=3600)
        result = await is_duplicate(mock_redis, "x@y.com", "<msg-1>")
        assert result is False

    @pytest.mark.asyncio
    async def test_ttl_is_set(self, mock_redis):
        await mark_seen(mock_redis, "a@b.com", "<msg-1>", ttl_seconds=7200)
        key = dedup_key("a@b.com")
        ttl = await mock_redis.ttl(key)
        assert ttl > 0
        assert ttl <= 7200
```

### 7. `tests/test_email_poller/test_core_client.py`

Tests for `poller/core_client.py`.

```python
"""Tests for core API client."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from aiohttp import ClientSession

from poller.core_client import CoreClient, CoreClientError


class TestCoreClient:
    @pytest.mark.asyncio
    async def test_create_llm_job_success(self):
        mock_resp = AsyncMock()
        mock_resp.status = 201
        mock_resp.json = AsyncMock(return_value={"id": "job-1", "status": "queued"})

        mock_session = AsyncMock(spec=ClientSession)
        mock_session.post = MagicMock()
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)

        client = CoreClient("http://core:8000", mock_session)
        result = await client.create_llm_job("email_extract", {"subject": "Hi"}, user_id=1)

        assert result == {"id": "job-1", "status": "queued"}
        mock_session.post.assert_called_once_with(
            "http://core:8000/llm_jobs",
            json={"job_type": "email_extract", "payload": {"subject": "Hi"}, "user_id": 1},
        )

    @pytest.mark.asyncio
    async def test_create_llm_job_error(self):
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="Internal Server Error")

        mock_session = AsyncMock(spec=ClientSession)
        mock_session.post = MagicMock()
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)

        client = CoreClient("http://core:8000", mock_session)
        with pytest.raises(CoreClientError, match="500"):
            await client.create_llm_job("email_extract", {"subject": "Hi"}, user_id=1)
```

### 8. `tests/test_email_poller/test_poller.py`

Tests for `poller/poller.py` (the polling loop).

```python
"""Tests for the email polling loop."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from poller.config import EmailPollerSettings
from poller.poller import run_poller, _poll_account
from poller.core_client import CoreClient, CoreClientError


@pytest.fixture
def poller_config():
    return EmailPollerSettings(
        poll_interval_seconds=1,
        email_accounts='[{"provider":"gmail","email":"t@g.com","password":"p","user_id":1}]',
        dedup_ttl_seconds=3600,
    )


class TestPollAccount:
    @pytest.mark.asyncio
    async def test_new_email_creates_job_and_marks_seen(self, mock_redis, poller_config):
        mock_core = AsyncMock(spec=CoreClient)
        mock_core.create_llm_job = AsyncMock(return_value={"id": "job-1"})

        email_data = {
            "message_id": "<msg-1>",
            "subject": "Dinner Friday",
            "sender": "friend@example.com",
            "body": "Let's eat",
        }

        from poller.config import parse_email_accounts
        account = parse_email_accounts(poller_config.email_accounts)[0]

        with patch("poller.poller.fetch_unseen_emails", return_value=[email_data]):
            await _poll_account(poller_config, mock_redis, mock_core, account)

        mock_core.create_llm_job.assert_called_once_with(
            job_type="email_extract",
            payload={"subject": "Dinner Friday", "body": "Let's eat"},
            user_id=1,
        )

        # Verify marked as seen
        from poller.dedup import is_duplicate
        assert await is_duplicate(mock_redis, "t@g.com", "<msg-1>") is True

    @pytest.mark.asyncio
    async def test_duplicate_email_skipped(self, mock_redis, poller_config):
        mock_core = AsyncMock(spec=CoreClient)

        from poller.config import parse_email_accounts
        from poller.dedup import mark_seen
        account = parse_email_accounts(poller_config.email_accounts)[0]

        # Pre-mark as seen
        await mark_seen(mock_redis, "t@g.com", "<msg-1>", 3600)

        email_data = {
            "message_id": "<msg-1>",
            "subject": "Dinner",
            "sender": "friend@example.com",
            "body": "Let's eat",
        }
        with patch("poller.poller.fetch_unseen_emails", return_value=[email_data]):
            await _poll_account(poller_config, mock_redis, mock_core, account)

        mock_core.create_llm_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_filtered_email_skipped(self, mock_redis, poller_config):
        mock_core = AsyncMock(spec=CoreClient)

        from poller.config import EmailAccountConfig
        account = EmailAccountConfig(
            provider="gmail",
            email="t@g.com",
            password="p",
            user_id=1,
            filter_senders=["spam.com"],
        )

        email_data = {
            "message_id": "<msg-2>",
            "subject": "Buy now",
            "sender": "offer@spam.com",
            "body": "Deal of the day",
        }
        with patch("poller.poller.fetch_unseen_emails", return_value=[email_data]):
            await _poll_account(poller_config, mock_redis, mock_core, account)

        mock_core.create_llm_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_imap_error_does_not_crash(self, mock_redis, poller_config):
        mock_core = AsyncMock(spec=CoreClient)

        from poller.config import parse_email_accounts
        account = parse_email_accounts(poller_config.email_accounts)[0]

        with patch(
            "poller.poller.fetch_unseen_emails",
            side_effect=Exception("IMAP connection refused"),
        ):
            # Should not raise
            await _poll_account(poller_config, mock_redis, mock_core, account)

        mock_core.create_llm_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_core_client_error_continues(self, mock_redis, poller_config):
        mock_core = AsyncMock(spec=CoreClient)
        mock_core.create_llm_job = AsyncMock(side_effect=CoreClientError("500"))

        from poller.config import parse_email_accounts
        account = parse_email_accounts(poller_config.email_accounts)[0]

        emails = [
            {"message_id": "<msg-1>", "subject": "A", "sender": "a@b.com", "body": ""},
            {"message_id": "<msg-2>", "subject": "B", "sender": "c@d.com", "body": ""},
        ]
        with patch("poller.poller.fetch_unseen_emails", return_value=emails):
            # Should not raise despite both failing
            await _poll_account(poller_config, mock_redis, mock_core, account)

        # Both were attempted
        assert mock_core.create_llm_job.call_count == 2


class TestRunPoller:
    @pytest.mark.asyncio
    async def test_shutdown_event_exits_loop(self, mock_redis):
        config = EmailPollerSettings(
            poll_interval_seconds=60,
            email_accounts="[]",
        )
        mock_core = AsyncMock(spec=CoreClient)
        shutdown = asyncio.Event()
        shutdown.set()  # Immediately signal shutdown

        # Should return promptly, not hang
        await asyncio.wait_for(
            run_poller(config, mock_redis, mock_core, shutdown),
            timeout=5,
        )
```

---

## Files to Modify

### 9. `tests/conftest.py`

Add `email_poller/` to `sys.path`, same pattern as the existing `llm_worker/` path addition.

**Add after the existing llm_worker path block (lines 8-12):**
```python
_email_poller_path = os.path.join(PROJECT_ROOT, "email_poller")
if _email_poller_path not in sys.path:
    sys.path.insert(0, _email_poller_path)
```

---

## Verification

```bash
# Run all email poller tests
pytest tests/test_email_poller/ -v

# Run full test suite to check for regressions
pytest --cov=. --cov-report=term-missing
```
