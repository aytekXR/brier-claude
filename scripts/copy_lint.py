#!/usr/bin/env python3
"""Regulatory copy lint — the automated half of PRD AC-7.

Brier never outputs buy/sell/hold or any recommendation language. This script
scans user-visible strings for a forbidden vocabulary and fails the build on
any hit. It runs in `make check` and CI.

What counts as user-visible (and is scanned):
  * string literals and template literals in apps/web/**/*.ts{,x}
  * JSX text nodes in apps/web/**/*.tsx
  * string VALUES in data/fixtures/*.json (keys are identifiers, exempt)
  * string VALUES in data/fixtures/*.jsonl (JSON Lines; keys are exempt)
  * docs/METHODOLOGY.md (rendered verbatim on /methodology)

What is exempt by construction: code identifiers, import paths, JSON keys,
comments. Only the contents of strings, JSX text, JSON values, and rendered
markdown are inspected.

Escape hatch: a line containing `copy-lint-ignore` (in any comment style) is
skipped. Use it only with a stated reason, e.g. quoting an analyst's own words
inside a receipt:  // copy-lint-ignore: verbatim quote under review

Usage: python3 scripts/copy_lint.py [paths...]   (defaults to the repo tree)
Exit code 0 = clean, 1 = violations found. Stdlib only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Iterable, Iterator, NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent

IGNORE_MARKER = "copy-lint-ignore"

# The forbidden list, per the regulatory firewall. "signal" is forbidden in
# rendered copy because on this site it can only read as a recommendation.
FORBIDDEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("buy", re.compile(r"\bbuy(?:s|ing)?\b", re.IGNORECASE)),
    ("sell", re.compile(r"\bsell(?:s|ing)?\b", re.IGNORECASE)),
    ("hold", re.compile(r"\bhold(?:s|ing)?\b", re.IGNORECASE)),
    ("should invest", re.compile(r"\bshould\s+invest(?:ing)?\b", re.IGNORECASE)),
    ("trade now", re.compile(r"\btrade\s+now\b", re.IGNORECASE)),
    ("signal", re.compile(r"\bsignals?\b", re.IGNORECASE)),
    ("moon", re.compile(r"\bmoon(?:s|ing|ed)?\b", re.IGNORECASE)),
    ("guaranteed", re.compile(r"\bguarantee[ds]?\b", re.IGNORECASE)),
    ("financial advice", re.compile(r"\bfinancial\s+advice\b", re.IGNORECASE)),
)

# Visible-text extraction for TypeScript/TSX. Identifiers stay exempt because
# only the *contents* of these matches are scanned.
TS_STRING_PATTERNS = (
    re.compile(r"'((?:[^'\\\n]|\\.)*)'"),
    re.compile(r'"((?:[^"\\\n]|\\.)*)"'),
    re.compile(r"`((?:[^`\\]|\\.)*)`", re.DOTALL),  # template literals span lines
)
JSX_TEXT_PATTERN = re.compile(r">([^<>{}]+)<")


class Violation(NamedTuple):
    path: Path
    line: int
    term: str
    excerpt: str


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _ignored_lines(text: str) -> set[int]:
    return {
        i for i, line in enumerate(text.splitlines(), start=1) if IGNORE_MARKER in line
    }


def _check_segment(
    path: Path, text: str, segment: str, seg_offset: int, ignored: set[int]
) -> Iterator[Violation]:
    for term, pattern in FORBIDDEN:
        for match in pattern.finditer(segment):
            line = _line_of(text, seg_offset + match.start())
            if line in ignored:
                continue
            snippet = segment[max(0, match.start() - 30) : match.end() + 30]
            excerpt = " ".join(snippet.split())
            yield Violation(path, line, term, excerpt)


def scan_typescript(path: Path) -> Iterator[Violation]:
    text = path.read_text(encoding="utf-8")
    ignored = _ignored_lines(text)
    patterns: tuple[re.Pattern[str], ...] = TS_STRING_PATTERNS
    if path.suffix == ".tsx":
        patterns = patterns + (JSX_TEXT_PATTERN,)
    for pattern in patterns:
        for m in pattern.finditer(text):
            yield from _check_segment(path, text, m.group(1), m.start(1), ignored)


def _walk_json_strings(node: object) -> Iterator[str]:
    """Recursively yield every string value in a JSON-parsed structure.

    Keys in dicts are identifiers and are exempt; only values are yielded.
    """
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _walk_json_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_json_strings(item)


def scan_json(path: Path) -> Iterator[Violation]:
    text = path.read_text(encoding="utf-8")
    ignored = _ignored_lines(text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        yield Violation(path, exc.lineno, "invalid-json", exc.msg)
        return

    for value in _walk_json_strings(data):
        for term, pattern in FORBIDDEN:
            match = pattern.search(value)
            if match is None:
                continue
            # Locate the offending value in the raw text for a line number.
            line = 1
            needle = json.dumps(value)[1:-1]
            pos = text.find(needle)
            if pos != -1:
                line = _line_of(text, pos)
            if line in ignored:
                continue
            yield Violation(path, line, term, " ".join(value.split())[:80])


def scan_jsonl(path: Path) -> Iterator[Violation]:
    """Scan a JSON Lines file, one JSON object per line.

    A line that fails to parse yields a Violation with term ``invalid-jsonl``
    (not a fatal error, so the rest of the file continues to be scanned).
    String values inside each record are checked against FORBIDDEN patterns.
    """
    text = path.read_text(encoding="utf-8")
    ignored = _ignored_lines(text)

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            yield Violation(path, lineno, "invalid-jsonl", exc.msg)
            continue

        for value in _walk_json_strings(record):
            for term, pattern in FORBIDDEN:
                match = pattern.search(value)
                if match is None:
                    continue
                if lineno in ignored:
                    continue
                excerpt = " ".join(value.split())[:80]
                yield Violation(path, lineno, term, excerpt)


def scan_markdown(path: Path) -> Iterator[Violation]:
    text = path.read_text(encoding="utf-8")
    ignored = _ignored_lines(text)
    yield from _check_segment(path, text, text, 0, ignored)


def collect_files(root: Path) -> Iterator[tuple[Path, str]]:
    web = root / "apps" / "web"
    if web.is_dir():
        for path in sorted(web.rglob("*")):
            if path.suffix not in {".ts", ".tsx"}:
                continue
            if any(part in {"node_modules", ".next"} for part in path.parts):
                continue
            yield path, "ts"
    fixtures = root / "data" / "fixtures"
    if fixtures.is_dir():
        for path in sorted(fixtures.rglob("*.json")):
            yield path, "json"
        for path in sorted(fixtures.rglob("*.jsonl")):
            yield path, "jsonl"
    methodology = root / "docs" / "METHODOLOGY.md"
    if methodology.is_file():
        yield methodology, "md"


def scan_tree(root: Path) -> list[Violation]:
    scanners = {
        "ts": scan_typescript,
        "json": scan_json,
        "jsonl": scan_jsonl,
        "md": scan_markdown,
    }
    violations: list[Violation] = []
    for path, kind in collect_files(root):
        violations.extend(scanners[kind](path))
    return violations


def main(argv: Iterable[str]) -> int:
    roots = [Path(arg).resolve() for arg in argv] or [REPO_ROOT]
    violations: list[Violation] = []
    for root in roots:
        violations.extend(scan_tree(root))

    if violations:
        for v in violations:
            rel = (
                v.path.relative_to(REPO_ROOT)
                if v.path.is_relative_to(REPO_ROOT)
                else v.path
            )
            print(
                f'{rel}:{v.line}: forbidden term "{v.term}" in user-visible copy: …{v.excerpt}…'
            )
        print(
            f"copy-lint: {len(violations)} violation(s). See PRD AC-7; the product never outputs recommendation language."
        )
        return 1
    print("copy-lint: clean (PRD AC-7 automated gate)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
