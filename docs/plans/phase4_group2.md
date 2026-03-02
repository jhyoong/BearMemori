# Phase 4, Group 2: IMAP Client + Email Parsing

## Context

This group implements the IMAP fetching and email parsing logic. It uses only the Python standard library (`imaplib`, `email`) and wraps blocking IMAP calls with `asyncio.to_thread()` so the rest of the async poller loop is not blocked.

**Dependencies from Group 1:**
- `email_poller/poller/config.py` -- `EmailAccountConfig` (has `provider`, `email`, `password`, `folder`), `IMAP_HOSTS` dict

**No external IMAP library is needed.** The stdlib `imaplib.IMAP4_SSL` is sufficient.

**Design decisions:**
- Max 50 emails fetched per poll cycle to avoid long-running IMAP sessions
- Body truncated to 4000 chars (LLM context is limited)
- HTML fallback: strip tags with regex, no BeautifulSoup dependency
- Parse failures return None and are logged, never crash the poller

---

## Files to Create

### 1. `email_poller/poller/imap_client.py`

```python
"""IMAP client for fetching unseen emails."""

import asyncio
import email
import email.header
import email.policy
import imaplib
import logging
import re
from typing import Any

from poller.config import EmailAccountConfig, IMAP_HOSTS

logger = logging.getLogger(__name__)

MAX_EMAILS_PER_POLL = 50
MAX_BODY_LENGTH = 4000


async def fetch_unseen_emails(
    account: EmailAccountConfig,
    imap_timeout: int,
) -> list[dict[str, Any]]:
    """Fetch unseen emails from the given IMAP account.

    Runs the blocking IMAP operations in a thread to avoid blocking the
    async event loop. Returns a list of dicts with keys:
    message_id, subject, sender, body.
    """
    return await asyncio.to_thread(_fetch_sync, account, imap_timeout)


def _fetch_sync(
    account: EmailAccountConfig,
    imap_timeout: int,
) -> list[dict[str, Any]]:
    """Synchronous IMAP fetch. Called via asyncio.to_thread()."""
    host = IMAP_HOSTS[account.provider]
    mail = None
    try:
        mail = imaplib.IMAP4_SSL(host, 993, timeout=imap_timeout)
        mail.login(account.email, account.password)
        mail.select(account.folder, readonly=True)

        _, data = mail.search(None, "UNSEEN")
        if not data or not data[0]:
            return []

        msg_nums = data[0].split()
        # Limit to most recent N emails
        msg_nums = msg_nums[-MAX_EMAILS_PER_POLL:]

        results: list[dict[str, Any]] = []
        for num in msg_nums:
            _, msg_data = mail.fetch(num, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw_bytes = msg_data[0][1]
            parsed = parse_email(raw_bytes)
            if parsed:
                results.append(parsed)

        return results
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass


def parse_email(raw_bytes: bytes) -> dict[str, Any] | None:
    """Parse raw RFC822 email bytes into a dict.

    Returns dict with keys: message_id, subject, sender, body.
    Returns None if parsing fails.
    """
    try:
        msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)

        message_id = msg.get("Message-ID", "")
        sender = msg.get("From", "")
        subject = _decode_header(msg.get("Subject", ""))
        body = extract_plain_text(msg)

        if not message_id:
            logger.warning("Email missing Message-ID, skipping")
            return None

        return {
            "message_id": message_id.strip(),
            "subject": subject,
            "sender": sender,
            "body": body,
        }
    except Exception:
        logger.exception("Failed to parse email")
        return None


def _decode_header(value: str) -> str:
    """Decode an email header value that may have encoded parts."""
    if not value:
        return ""
    parts = email.header.decode_header(value)
    decoded_parts: list[str] = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded_parts.append(part)
    return " ".join(decoded_parts)


def extract_plain_text(msg: email.message.Message) -> str:
    """Extract the plain text body from an email message.

    Prefers text/plain parts. Falls back to text/html with tags stripped.
    Truncates to MAX_BODY_LENGTH chars.
    """
    plain_parts: list[str] = []
    html_parts: list[str] = []

    for part in msg.walk():
        content_type = part.get_content_type()
        if content_type == "text/plain":
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                plain_parts.append(payload.decode(charset, errors="replace"))
        elif content_type == "text/html":
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                html_parts.append(payload.decode(charset, errors="replace"))

    if plain_parts:
        text = "\n".join(plain_parts)
    elif html_parts:
        text = strip_html_tags("\n".join(html_parts))
    else:
        text = ""

    return text[:MAX_BODY_LENGTH]


def strip_html_tags(html: str) -> str:
    """Remove HTML tags from a string, replacing them with spaces."""
    return re.sub(r"<[^>]+>", " ", html).strip()
```

**Key implementation notes:**
- `_fetch_sync()` always calls `mail.logout()` in a `finally` block to prevent leaked connections
- `select(folder, readonly=True)` prevents the poller from accidentally modifying email flags (the UNSEEN search still works because `readonly=True` only prevents flag changes by the client; the search is server-side)
- `email.policy.default` gives modern `EmailMessage` objects with better header handling
- `_decode_header()` handles RFC 2047 encoded subjects (e.g., `=?UTF-8?Q?...?=`)

---

## Verification

```bash
pytest tests/test_email_poller/test_imap_client.py -v
```
