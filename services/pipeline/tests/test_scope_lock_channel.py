"""A2#7: YouTube-only scope lock — analyst channel_id must be a YouTube ID.

Scope lock (CLAUDE.md): crypto + YouTube only. Real YouTube channel IDs start
with 'UC'. The guard is a prefix check (fixture IDs use 'UC' with shorter
bodies than the canonical 24-char form) whose job is to reject non-YouTube
identifiers (handles, other platforms) at registry write time.
"""

from __future__ import annotations

from typing import Any

import pytest

from brier_pipeline.ingestion import registry
from brier_pipeline.ingestion.registry import add_analyst


def test_assert_youtube_channel_accepts_uc_prefix() -> None:
    # Both the canonical-length form and the shorter fixture form pass.
    registry._assert_youtube_channel("UCabcdefghijklmnopqrstuv")
    registry._assert_youtube_channel("UCfix-northchain-0001")


@pytest.mark.parametrize(
    "bad",
    ["@northchain", "northchain", "https://youtube.com/@x", "BIST123", "uc-lowercase", ""],
)
def test_assert_youtube_channel_rejects_non_youtube(bad: str) -> None:
    with pytest.raises(ValueError, match="YouTube"):
        registry._assert_youtube_channel(bad)


def test_add_analyst_rejects_non_youtube_channel(db_conn: Any) -> None:
    # The guard fires before any INSERT, so nothing is written (db_conn rolls back).
    with pytest.raises(ValueError, match="YouTube"):
        add_analyst(db_conn, channel_id="@handle", display_name="X", slug="x-scope-lock")
