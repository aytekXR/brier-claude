"""stdlib-REST seam for LLM completions (ADR-0005, proposed).

This module implements the `completion()` interface using only stdlib
`urllib.request` and `json` — no litellm, no anthropic SDK, no new
package dependency. The signature is intentionally compatible with a
LiteLLM router so a provider swap is a transport change, not a reshape.

UNUSED in CI: recorded fixtures + the injected completion boundary in
LlmExtractor are the test path. Real calls require BRIER_ANTHROPIC_API_KEY
and a network path to api.anthropic.com (NFR-5 spend caps apply).

ADR-0005 (proposed) documents the deviation from PRD §18's LiteLLM
reference and the migration path if/when the LiteLLM SDK is approved.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from brier_pipeline import config

_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"


def completion(
    model_name: str,
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """POST a chat completion to the Anthropic Messages API via stdlib urllib.

    Parameters
    ----------
    model_name:
        The Anthropic model identifier, e.g. ``claude-haiku-4-5``.
    messages:
        List of ``{"role": "user"|"assistant", "content": "<text>"}`` dicts.
    system:
        Optional system prompt string (passed as ``"system"`` in the body).
    max_tokens:
        Maximum tokens in the response (default 1024, subject to NFR-5 caps).

    Returns
    -------
    dict[str, Any]
        The raw Anthropic API response dict, e.g.:
        ``{"content": [{"type": "text", "text": "..."}], "model": "...", ...}``

    Raises
    ------
    RuntimeError
        If ``BRIER_ANTHROPIC_API_KEY`` is not set. See ADR-0005 and
        ``docs/adr/0005-llm-extraction-via-stdlib-rest.md``.
    urllib.error.HTTPError
        On a non-2xx response from the Anthropic endpoint.
    """
    api_key = config.anthropic_api_key()
    if not api_key:
        raise RuntimeError(
            "BRIER_ANTHROPIC_API_KEY is not set. "
            "The LLM completion seam requires a real Anthropic API key at runtime. "
            "In CI and tests, inject a fake completion callable instead of calling this directly. "
            "See docs/adr/0005-llm-extraction-via-stdlib-rest.md (ADR-0005, proposed)."
        )

    body: dict[str, Any] = {
        "model": model_name,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system is not None:
        body["system"] = system

    encoded = json.dumps(body).encode("utf-8")
    headers: dict[str, str] = {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    req = urllib.request.Request(
        _ANTHROPIC_MESSAGES_URL,
        data=encoded,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return dict[str, Any](json.loads(resp.read().decode("utf-8")))
