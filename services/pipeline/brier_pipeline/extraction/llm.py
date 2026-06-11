"""LiteLLM router glue. Config lives at litellm.config.yaml (repo root).

Present per the locked stack; UNUSED until E3. Haiku-class for both extraction
passes with structured outputs, Sonnet-class for arbitration, provider-swappable
in config. Spend is subject to the hard monthly budget caps (NFR-5).
"""

from __future__ import annotations

from typing import Any


def completion(model_name: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Route a chat completion through LiteLLM per litellm.config.yaml."""
    # TASK: E3-T2
    raise NotImplementedError
