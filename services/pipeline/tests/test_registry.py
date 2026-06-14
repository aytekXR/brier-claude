"""E2-T1 analyst registry tests.

Categories:
  1. Pure function tests (scope-lock, roster file validation) — no DB.
  2. DB tests via db_conn (rolled-back) — CRUD round-trips, soft-remove,
     import_roster idempotency, CLI smoke.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg
import pytest

from brier_pipeline.ingestion import registry
from brier_pipeline.ingestion.registry import (
    add_analyst,
    get_analyst,
    import_roster,
    list_analysts,
    remove_analyst,
    set_jurisdiction_flag,
    update_status,
)
from brier_pipeline.models import AnalystStatus

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "data" / "fixtures"
ROSTER_PATH = FIXTURES / "roster.json"


# ---------------------------------------------------------------------------
# Helper: insert a unique analyst and return its id
# ---------------------------------------------------------------------------


def _add_unique(
    conn: psycopg.Connection[Any],
    *,
    suffix: str = "a",
    status: str = "active",
    jurisdiction_flag: str | None = None,
) -> int:
    return add_analyst(
        conn,
        channel_id=f"UCtest-reg-{suffix}",
        display_name=f"Test Analyst {suffix}",
        slug=f"test-analyst-{suffix}",
        status=status,
        jurisdiction_flag=jurisdiction_flag,
    )


# ---------------------------------------------------------------------------
# 1. Pure / file tests (no DB required)
# ---------------------------------------------------------------------------


class TestScopeLock:
    """_assert_in_scope raises for every Turkey/BIST blocklist entry."""

    @pytest.mark.parametrize(
        "flag",
        [
            "TR",
            "TUR",
            "turkey",
            "Turkey",
            "TURKEY",
            "türkiye",
            "Türkiye",
            "turkiye",
            "Turkiye",
            "BIST",
            "bist",
            "istanbul",
            "Istanbul",
            "ISTANBUL",
            "ankara",
            "ANKARA",
        ],
    )
    def test_blocked_flag_raises(self, flag: str) -> None:
        with pytest.raises(ValueError, match="Scope-lock violation"):
            registry._assert_in_scope(flag)

    @pytest.mark.parametrize("flag", [None, "US", "GB", "SG", "AE", "BR", "JP", "AU", "CA"])
    def test_allowed_flag_passes(self, flag: str | None) -> None:
        registry._assert_in_scope(flag)  # must not raise


class TestRosterFile:
    """Validates data/fixtures/roster.json without a DB."""

    def test_roster_is_valid_json(self) -> None:
        data = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, list)

    def test_roster_has_exactly_50_entries(self) -> None:
        data = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        assert len(data) == 50, f"Expected 50 entries, got {len(data)}"

    def test_roster_slugs_unique(self) -> None:
        data = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        slugs = [e["slug"] for e in data]
        assert len(slugs) == len(set(slugs)), "Duplicate slugs found in roster.json"

    def test_roster_channel_ids_unique(self) -> None:
        data = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        ids = [e["channel_id"] for e in data]
        assert len(ids) == len(set(ids)), "Duplicate channel_ids found in roster.json"

    def test_roster_no_turkey_bist_jurisdiction(self) -> None:
        data = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        for entry in data:
            jf: str | None = entry.get("jurisdiction_flag")
            # Must not raise; any Turkey/BIST flag would be a defect.
            registry._assert_in_scope(jf)

    def test_roster_contains_three_fixture_analysts(self) -> None:
        """The three seed analysts must be present verbatim (channel_id, slug, display_name)."""
        data = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        by_cid = {e["channel_id"]: e for e in data}

        assert "UCfix-northchain-0001" in by_cid
        assert by_cid["UCfix-northchain-0001"]["slug"] == "northchain"
        assert by_cid["UCfix-northchain-0001"]["display_name"] == "NorthChain"

        assert "UCfix-aylinmarkets-0002" in by_cid
        assert by_cid["UCfix-aylinmarkets-0002"]["slug"] == "aylin-markets"
        assert by_cid["UCfix-aylinmarkets-0002"]["display_name"] == "Aylin Markets"

        assert "UCfix-vectoredge-0003" in by_cid
        assert by_cid["UCfix-vectoredge-0003"]["slug"] == "vectoredge"
        assert by_cid["UCfix-vectoredge-0003"]["display_name"] == "VectorEdge"

    def test_roster_required_fields_present(self) -> None:
        data = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        required = {"channel_id", "display_name", "slug", "status", "jurisdiction_flag"}
        for i, entry in enumerate(data):
            missing = required - entry.keys()
            assert not missing, f"Entry {i} missing fields: {missing}"


# ---------------------------------------------------------------------------
# 2. DB tests — all rolled back via db_conn
# ---------------------------------------------------------------------------


def test_add_and_get_by_id(db_conn: Any) -> None:
    """add_analyst inserts a row; get_analyst by id returns the Analyst."""
    new_id = _add_unique(db_conn, suffix="id1", jurisdiction_flag="US")
    analyst = get_analyst(db_conn, analyst_id=new_id)
    assert analyst is not None
    assert analyst.id == new_id
    assert analyst.slug == "test-analyst-id1"
    assert analyst.channel_id == "UCtest-reg-id1"
    assert analyst.status == AnalystStatus.ACTIVE
    assert analyst.jurisdiction_flag == "US"


def test_add_and_get_by_slug(db_conn: Any) -> None:
    """get_analyst by slug returns the correct row."""
    _add_unique(db_conn, suffix="slug1", jurisdiction_flag="GB")
    analyst = get_analyst(db_conn, slug="test-analyst-slug1")
    assert analyst is not None
    assert analyst.display_name == "Test Analyst slug1"
    assert analyst.jurisdiction_flag == "GB"


def test_add_and_get_by_channel_id(db_conn: Any) -> None:
    """get_analyst by channel_id returns the correct row."""
    _add_unique(db_conn, suffix="cid1")
    analyst = get_analyst(db_conn, channel_id="UCtest-reg-cid1")
    assert analyst is not None
    assert analyst.slug == "test-analyst-cid1"


def test_get_analyst_not_found_returns_none(db_conn: Any) -> None:
    """get_analyst returns None for an unknown id/slug/channel_id."""
    assert get_analyst(db_conn, analyst_id=9999999) is None
    assert get_analyst(db_conn, slug="no-such-slug") is None
    assert get_analyst(db_conn, channel_id="UCtest-nonexistent") is None


def test_get_analyst_requires_exactly_one_selector(db_conn: Any) -> None:
    """get_analyst raises ValueError for zero or multiple selectors."""
    with pytest.raises(ValueError, match="Exactly one selector"):
        get_analyst(db_conn)

    with pytest.raises(ValueError, match="Exactly one selector"):
        get_analyst(db_conn, analyst_id=1, slug="foo")


def test_list_analysts_ordered_by_id(db_conn: Any) -> None:
    """list_analysts returns rows ordered by id ascending."""
    # Add two analysts; their ids will be ascending.
    id_a = _add_unique(db_conn, suffix="lista")
    id_b = _add_unique(db_conn, suffix="listb")
    all_analysts = list_analysts(db_conn)
    ids = [a.id for a in all_analysts]
    # The two new rows must appear in order.
    pos_a = ids.index(id_a)
    pos_b = ids.index(id_b)
    assert pos_a < pos_b


def test_list_analysts_status_filter(db_conn: Any) -> None:
    """list_analysts with status= filters correctly."""
    _add_unique(db_conn, suffix="lsa", status="active")
    _add_unique(db_conn, suffix="lsp", status="paused")

    active = list_analysts(db_conn, status="active")
    paused = list_analysts(db_conn, status="paused")

    active_slugs = {a.slug for a in active}
    paused_slugs = {a.slug for a in paused}

    assert "test-analyst-lsa" in active_slugs
    assert "test-analyst-lsp" not in active_slugs
    assert "test-analyst-lsp" in paused_slugs
    assert "test-analyst-lsa" not in paused_slugs


def test_update_status(db_conn: Any) -> None:
    """update_status changes the analyst's status."""
    aid = _add_unique(db_conn, suffix="upst")
    update_status(db_conn, aid, "paused")
    analyst = get_analyst(db_conn, analyst_id=aid)
    assert analyst is not None
    assert analyst.status == AnalystStatus.PAUSED


def test_update_status_invalid_raises(db_conn: Any) -> None:
    """update_status with an invalid status raises ValueError."""
    aid = _add_unique(db_conn, suffix="stinv")
    with pytest.raises(ValueError):
        update_status(db_conn, aid, "invalid_status")


def test_set_jurisdiction_flag(db_conn: Any) -> None:
    """set_jurisdiction_flag updates and clears the flag."""
    aid = _add_unique(db_conn, suffix="jf1")
    set_jurisdiction_flag(db_conn, aid, "SG")
    analyst = get_analyst(db_conn, analyst_id=aid)
    assert analyst is not None
    assert analyst.jurisdiction_flag == "SG"

    # Now clear it.
    set_jurisdiction_flag(db_conn, aid, None)
    analyst2 = get_analyst(db_conn, analyst_id=aid)
    assert analyst2 is not None
    assert analyst2.jurisdiction_flag is None


def test_set_jurisdiction_flag_turkey_raises(db_conn: Any) -> None:
    """set_jurisdiction_flag rejects Turkey/BIST jurisdiction."""
    aid = _add_unique(db_conn, suffix="jftr")
    with pytest.raises(ValueError, match="Scope-lock violation"):
        set_jurisdiction_flag(db_conn, aid, "TR")

    with pytest.raises(ValueError, match="Scope-lock violation"):
        set_jurisdiction_flag(db_conn, aid, "BIST")


def test_remove_analyst_sets_status_removed(db_conn: Any) -> None:
    """remove_analyst soft-deletes by setting status='removed'."""
    aid = _add_unique(db_conn, suffix="rm1")
    remove_analyst(db_conn, aid)
    analyst = get_analyst(db_conn, analyst_id=aid)
    assert analyst is not None, "Row must still exist after soft-remove"
    assert analyst.status == AnalystStatus.REMOVED


def test_remove_analyst_row_still_exists(db_conn: Any) -> None:
    """After remove_analyst, the row is still queryable (FK integrity)."""
    aid = _add_unique(db_conn, suffix="rm2")
    remove_analyst(db_conn, aid)
    # Row must be findable.
    analyst = get_analyst(db_conn, analyst_id=aid)
    assert analyst is not None
    # Status must be 'removed', not absent.
    assert str(analyst.status) == "removed"


def test_add_analyst_turkey_raises(db_conn: Any) -> None:
    """add_analyst rejects a Turkey/BIST jurisdiction flag."""
    with pytest.raises(ValueError, match="Scope-lock violation"):
        add_analyst(
            db_conn,
            channel_id="UCtest-turkey-001",
            display_name="Test Analyst TR",
            slug="test-tr",
            jurisdiction_flag="TR",
        )

    with pytest.raises(ValueError, match="Scope-lock violation"):
        add_analyst(
            db_conn,
            channel_id="UCtest-turkey-002",
            display_name="Test Analyst Ankara",
            slug="test-ankara",
            jurisdiction_flag="ankara",
        )


def test_import_roster_total_50(db_conn: Any) -> None:
    """import_roster against the fixture roster returns total=50.

    The 3 seed analysts are already present (from make seed), so they count
    as updated. The remaining 47 are new inserts. In every case total==50
    and inserted+updated==50.
    """
    result = import_roster(db_conn, ROSTER_PATH)
    assert result["total"] == 50
    assert result["inserted"] + result["updated"] == 50


def test_import_roster_idempotent(db_conn: Any) -> None:
    """A second import_roster in the same transaction inserts 0 / updates 50."""
    # First import: some inserted, some updated (depends on pre-existing seed data).
    first = import_roster(db_conn, ROSTER_PATH)
    assert first["total"] == 50
    assert first["inserted"] + first["updated"] == 50

    # Second import: nothing new to insert, all 50 must be updates.
    second = import_roster(db_conn, ROSTER_PATH)
    assert second["total"] == 50
    assert second["inserted"] == 0
    assert second["updated"] == 50


def test_import_roster_scope_lock(db_conn: Any, tmp_path: Path) -> None:
    """import_roster rejects a roster containing a Turkey/BIST jurisdiction."""
    bad_roster = [
        {
            "channel_id": "UCtest-bad-001",
            "display_name": "Bad Analyst",
            "slug": "bad-analyst",
            "status": "active",
            "jurisdiction_flag": "TR",
        }
    ]
    bad_file = tmp_path / "bad_roster.json"
    bad_file.write_text(json.dumps(bad_roster), encoding="utf-8")

    with pytest.raises(ValueError, match="Scope-lock violation"):
        import_roster(db_conn, bad_file)


def test_cli_list_smoke(db_conn: Any) -> None:
    """registry.main(['list']) executes without error (read-only smoke)."""
    # This just checks the argparse wiring; we don't capture stdout.
    # main() opens its own connection — that's fine for the list subcommand.
    # We call it directly; it commits nothing that affects db_conn's rollback scope.
    rc = registry.main(["list"])
    assert rc == 0
