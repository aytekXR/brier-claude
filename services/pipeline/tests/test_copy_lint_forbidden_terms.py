"""A2#6: forbidden_terms_in — the reusable AC-7 firewall matcher.

copy_lint's static file scan never sees DB-sourced strings (extracted claim
quotes/rationales, API copy derived from the database). forbidden_terms_in is
the single source of truth for the FORBIDDEN vocabulary so those strings can be
screened by the runbook's final AC-7 check and the (gated) extract handler.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "copy_lint.py"

spec = importlib.util.spec_from_file_location("copy_lint_ft", SCRIPT)
assert spec is not None and spec.loader is not None
copy_lint: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(copy_lint)


def test_flags_recommendation_terms_in_db_text() -> None:
    assert "buy" in copy_lint.forbidden_terms_in("analysts say you should buy the dip")
    assert "signal" in copy_lint.forbidden_terms_in("a strong signal to act on")
    assert "guaranteed" in copy_lint.forbidden_terms_in("guaranteed gains ahead")


def test_clean_db_text_returns_empty() -> None:
    assert copy_lint.forbidden_terms_in("BTC closed above the stated target by the deadline") == []
    assert copy_lint.forbidden_terms_in("a measured prior over five years of price history") == []
