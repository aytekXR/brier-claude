"""Notifier seam for dispute ticket confirmations (FR-405, US-006).

Protocol: Notifier.send(to, subject, body)
  - FakeNotifier  — records sent messages; the CI/test path.
  - ResendNotifier — stdlib urllib POST to https://api.resend.com/emails;
                     an injected http_post callable defaults to the real one;
                     raises RuntimeError when BRIER_RESEND_API_KEY is absent.
                     No 'resend' SDK, nothing added to pyproject.toml (ADR-0010).

Pattern mirrors brier_pipeline/extraction/llm.py and brier_pipeline/qa/queue.py:
external dependency behind a small interface, fake is first-class, CI never
hits the network.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


class Notifier(Protocol):
    """Minimal notification seam for dispute ticket confirmations."""

    def send(self, *, to: str, subject: str, body: str) -> None:
        """Send a notification message.

        Args:
            to:      Recipient address (email or other identifier).
            subject: Short subject line.
            body:    Plain-text body.
        """
        ...


@dataclass
class SentMessage:
    """Record of a message sent via FakeNotifier."""

    to: str
    subject: str
    body: str


@dataclass
class FakeNotifier:
    """In-memory notifier; the CI/test path (mock-first convention).

    Records every send() call in self.sent so tests can assert on it.
    """

    sent: list[SentMessage] = field(default_factory=list)

    def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append(SentMessage(to=to, subject=subject, body=body))


def _resend_api_key() -> str:
    return os.environ.get("BRIER_RESEND_API_KEY", "")


def _default_http_post(
    url: str, payload: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    """Default HTTP POST using stdlib urllib; the real Resend path.

    Args:
        url:     Full request URL.
        payload: JSON-serialisable request body dict.
        headers: Request headers dict.

    Returns:
        Parsed JSON response dict.

    Raises:
        urllib.error.HTTPError: On non-2xx response.
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req) as resp:
        return dict(json.loads(resp.read().decode("utf-8")))


class ResendNotifier:
    """Resend transactional email via stdlib REST (ADR-0010).

    POSTs to https://api.resend.com/emails with an injected http_post
    callable. The real path requires BRIER_RESEND_API_KEY; a clear
    RuntimeError is raised when the key is absent so CI fails loudly
    instead of silently dropping messages.

    No 'resend' SDK, nothing added to pyproject.toml (ADR-0010).
    """

    RESEND_URL = "https://api.resend.com/emails"
    FROM_ADDRESS = "disputes@brier.app"

    def __init__(
        self,
        *,
        from_address: str = FROM_ADDRESS,
        http_post: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]] | None = None,
    ) -> None:
        self._from_address = from_address
        self._http_post = http_post if http_post is not None else _default_http_post

    def send(self, *, to: str, subject: str, body: str) -> None:
        """Send a transactional email via the Resend REST API (ADR-0010).

        Raises:
            RuntimeError: When BRIER_RESEND_API_KEY is not set. This is the
                expected failure mode in CI — the FakeNotifier is the CI path.
        """
        key = _resend_api_key()
        if not key:
            raise RuntimeError(
                "ResendNotifier requires BRIER_RESEND_API_KEY to be set. "
                "In CI and tests, inject FakeNotifier instead "
                "(see docs/adr/0010-resend-transactional-email-via-stdlib-rest.md)."
            )
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "from": self._from_address,
            "to": [to],
            "subject": subject,
            "text": body,
        }
        self._http_post(self.RESEND_URL, payload, headers)
