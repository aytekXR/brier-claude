"""Self-test for scripts/copy_lint.py — the AC-7 firewall must actually bite.

The lint is fully implemented in the skeleton (unlike the pipeline stubs), so
it gets real tests now. Forbidden vocabulary below appears only inside test
fixtures written to tmp_path; copy_lint never scans this directory.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "copy_lint.py"

spec = importlib.util.spec_from_file_location("copy_lint", SCRIPT)
assert spec is not None and spec.loader is not None
copy_lint: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(copy_lint)


def _web_file(root: Path, name: str, content: str) -> Path:
    path = root / "apps" / "web" / "app" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_flags_jsx_text(tmp_path: Path) -> None:
    _web_file(tmp_path, "page.tsx", "export default () => <p>Time to buy the dip</p>;\n")
    violations = copy_lint.scan_tree(tmp_path)
    assert [v.term for v in violations] == ["buy"]


def test_flags_string_literals_and_templates(tmp_path: Path) -> None:
    _web_file(
        tmp_path,
        "copy.ts",
        'export const tagline = "guaranteed gains";\n'
        "export const cta = `trade now while it lasts`;\n",
    )
    terms = sorted(v.term for v in copy_lint.scan_tree(tmp_path))
    assert terms == ["guaranteed", "trade now"]


def test_identifiers_are_exempt(tmp_path: Path) -> None:
    _web_file(
        tmp_path,
        "logic.ts",
        "const buySignal = 1;\nfunction holdPosition(sellOrder: number) { return sellOrder; }\n",
    )
    assert copy_lint.scan_tree(tmp_path) == []


def test_ignore_marker_skips_line(tmp_path: Path) -> None:
    _web_file(
        tmp_path,
        "quote.tsx",
        'export const quote = "I would buy here"; '
        "// copy-lint-ignore: verbatim analyst quote shown as evidence on a receipt\n",
    )
    assert copy_lint.scan_tree(tmp_path) == []


def test_word_boundaries_avoid_false_positives(tmp_path: Path) -> None:
    _web_file(
        tmp_path,
        "safe.tsx",
        "export default () => <p>Stakeholder placeholder threshold moonshot sells-adjacent: "
        "none of these words appear alone</p>;\n",
    )
    # "sells-adjacent" DOES contain the standalone token "sells"; everything
    # else must pass. This pins the exact boundary behavior.
    terms = [v.term for v in copy_lint.scan_tree(tmp_path)]
    assert terms == ["sell"]


def test_json_values_flagged_keys_exempt(tmp_path: Path) -> None:
    fixtures = tmp_path / "data" / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "sample.json").write_text(
        '{"sell_count": 3, "bio": "tells viewers to sell everything"}', encoding="utf-8"
    )
    violations = copy_lint.scan_tree(tmp_path)
    assert [v.term for v in violations] == ["sell"]


def test_markdown_scanned(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir(parents=True)
    (docs / "METHODOLOGY.md").write_text("Scores are not a signal.\n", encoding="utf-8")
    assert [v.term for v in copy_lint.scan_tree(tmp_path)] == ["signal"]


def test_real_tree_is_clean() -> None:
    """The shipped repo passes its own firewall (PRD AC-7)."""
    assert copy_lint.scan_tree(REPO_ROOT) == []
