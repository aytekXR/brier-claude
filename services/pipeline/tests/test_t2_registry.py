"""T2 registry failure-path & edge regression tests (cluster: registry).

Covers the failure paths and round-trips NOT already part of the main
test_registry.py happy-path suite:

  - update_status with a nonexistent analyst_id raises ValueError 'not found'
  - set_jurisdiction_flag with a nonexistent analyst_id raises ValueError 'not found'
  - remove_analyst with a nonexistent analyst_id raises ValueError 'not found'
  - add_analyst with a duplicate channel_id raises psycopg.errors.UniqueViolation
  - add_analyst with a duplicate slug raises psycopg.errors.UniqueViolation
  - notify_email round-trip: set value, then None
  - get_analyst with zero selectors raises ValueError (exactly-one rule)
  - get_analyst with more than one selector raises ValueError (exactly-one rule)

DB id prefix: UC-t2-reg  (all channel_ids in this file start with that string;
they start with 'UC' so the scope-lock guard passes).

UniqueViolation notes: a psycopg.errors.UniqueViolation aborts the current
transaction.  Each duplicate-insert test is isolated in its own test function
so the db_conn fixture's rollback handles the aborted state cleanly.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from brier_pipeline.ingestion.registry import (
    add_analyst,
    get_analyst,
    remove_analyst,
    set_jurisdiction_flag,
    update_status,
)

# Cluster prefix for all DB identifiers in this file.
_PFX = "UC-t2-reg"

# A nonexistent analyst id that will never match any seeded row.
_MISSING_ID = 999_999_999


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _insert(
    conn: psycopg.Connection[Any],
    *,
    suffix: str,
    notify_email: str | None = None,
) -> int:
    """Insert a uniquely prefixed test analyst and return its new id."""
    return add_analyst(
        conn,
        channel_id=f"{_PFX}-{suffix}",
        display_name=f"T2 Reg {suffix}",
        slug=f"t2-reg-{suffix}",
        notify_email=notify_email,
    )


# ---------------------------------------------------------------------------
# update_status: nonexistent analyst_id raises ValueError mentioning 'not found'
# ---------------------------------------------------------------------------


def test_update_status_nonexistent_raises_not_found(db_conn: psycopg.Connection[Any]) -> None:
    """update_status on a nonexistent analyst_id raises ValueError mentioning 'not found'."""
    with pytest.raises(ValueError, match="not found"):
        update_status(db_conn, analyst_id=_MISSING_ID, status="active")


# ---------------------------------------------------------------------------
# set_jurisdiction_flag: nonexistent analyst_id raises ValueError mentioning 'not found'
# ---------------------------------------------------------------------------


def test_set_jurisdiction_flag_nonexistent_raises_not_found(
    db_conn: psycopg.Connection[Any],
) -> None:
    """set_jurisdiction_flag on a nonexistent analyst_id raises ValueError 'not found'."""
    with pytest.raises(ValueError, match="not found"):
        set_jurisdiction_flag(db_conn, analyst_id=_MISSING_ID, jurisdiction_flag="US")


def test_set_jurisdiction_flag_nonexistent_none_raises_not_found(
    db_conn: psycopg.Connection[Any],
) -> None:
    """set_jurisdiction_flag(None) on a nonexistent analyst_id also raises ValueError 'not found'.

    Passing None clears the flag but the row-not-found check still fires.
    """
    with pytest.raises(ValueError, match="not found"):
        set_jurisdiction_flag(db_conn, analyst_id=_MISSING_ID, jurisdiction_flag=None)


# ---------------------------------------------------------------------------
# remove_analyst: nonexistent analyst_id raises ValueError mentioning 'not found'
# ---------------------------------------------------------------------------


def test_remove_analyst_nonexistent_raises_not_found(db_conn: psycopg.Connection[Any]) -> None:
    """remove_analyst on a nonexistent analyst_id raises ValueError mentioning 'not found'."""
    with pytest.raises(ValueError, match="not found"):
        remove_analyst(db_conn, analyst_id=_MISSING_ID)


# ---------------------------------------------------------------------------
# Duplicate channel_id raises psycopg.errors.UniqueViolation
#
# Each duplicate test lives in its own function so the db_conn fixture's
# conn.rollback() handles the aborted-transaction state cleanly.
# ---------------------------------------------------------------------------


def test_duplicate_channel_id_raises_unique_violation(db_conn: psycopg.Connection[Any]) -> None:
    """add_analyst raises UniqueViolation when channel_id already exists (different slug)."""
    # First insert succeeds.
    _insert(db_conn, suffix="dup-ch")

    # Second insert with the same channel_id but a different slug must fail.
    with pytest.raises(psycopg.errors.UniqueViolation):
        add_analyst(
            db_conn,
            channel_id=f"{_PFX}-dup-ch",  # same channel_id — will collide
            display_name="Dup Channel Alt",
            slug="t2-reg-dup-ch-alt",  # different slug
        )
    # Transaction is now aborted; db_conn fixture will rollback on teardown.


# ---------------------------------------------------------------------------
# Duplicate slug raises psycopg.errors.UniqueViolation
# ---------------------------------------------------------------------------


def test_duplicate_slug_raises_unique_violation(db_conn: psycopg.Connection[Any]) -> None:
    """add_analyst raises UniqueViolation when slug already exists (different channel_id)."""
    # First insert succeeds.
    _insert(db_conn, suffix="dup-sl")

    # Second insert with the same slug but a different channel_id must fail.
    with pytest.raises(psycopg.errors.UniqueViolation):
        add_analyst(
            db_conn,
            channel_id=f"{_PFX}-dup-sl-alt",  # different channel_id
            display_name="Dup Slug Alt",
            slug="t2-reg-dup-sl",  # same slug — will collide
        )
    # Transaction is now aborted; db_conn fixture will rollback on teardown.


# ---------------------------------------------------------------------------
# notify_email round-trip
# ---------------------------------------------------------------------------


def test_notify_email_round_trip_set(db_conn: psycopg.Connection[Any]) -> None:
    """add_analyst with notify_email='probe@example.com' persists; get_analyst returns it."""
    analyst_id = _insert(db_conn, suffix="em-set", notify_email="probe@example.com")
    analyst = get_analyst(db_conn, analyst_id=analyst_id)
    assert analyst is not None
    assert analyst.notify_email == "probe@example.com"


def test_notify_email_round_trip_none(db_conn: psycopg.Connection[Any]) -> None:
    """add_analyst with notify_email=None -> get_analyst returns notify_email is None."""
    analyst_id = _insert(db_conn, suffix="em-none", notify_email=None)
    analyst = get_analyst(db_conn, analyst_id=analyst_id)
    assert analyst is not None
    assert analyst.notify_email is None


# ---------------------------------------------------------------------------
# get_analyst: zero selectors raises ValueError (exactly-one rule)
# ---------------------------------------------------------------------------


def test_get_analyst_zero_selectors_raises(db_conn: psycopg.Connection[Any]) -> None:
    """get_analyst() with no keyword selectors raises ValueError (exactly-one rule)."""
    with pytest.raises(ValueError, match="Exactly one selector"):
        get_analyst(db_conn)


# ---------------------------------------------------------------------------
# get_analyst: more than one selector raises ValueError (exactly-one rule)
# ---------------------------------------------------------------------------


def test_get_analyst_two_selectors_id_and_slug_raises(db_conn: psycopg.Connection[Any]) -> None:
    """get_analyst with analyst_id AND slug raises ValueError (exactly-one rule)."""
    with pytest.raises(ValueError, match="Exactly one selector"):
        get_analyst(db_conn, analyst_id=1, slug="some-slug")


def test_get_analyst_two_selectors_id_and_channel_raises(
    db_conn: psycopg.Connection[Any],
) -> None:
    """get_analyst with analyst_id AND channel_id raises ValueError (exactly-one rule)."""
    with pytest.raises(ValueError, match="Exactly one selector"):
        get_analyst(db_conn, analyst_id=1, channel_id=f"{_PFX}-xyz")


def test_get_analyst_two_selectors_slug_and_channel_raises(
    db_conn: psycopg.Connection[Any],
) -> None:
    """get_analyst with slug AND channel_id raises ValueError (exactly-one rule)."""
    with pytest.raises(ValueError, match="Exactly one selector"):
        get_analyst(db_conn, slug="some-slug", channel_id=f"{_PFX}-xyz")


def test_get_analyst_all_three_selectors_raises(db_conn: psycopg.Connection[Any]) -> None:
    """get_analyst with all three selectors raises ValueError (exactly-one rule)."""
    with pytest.raises(ValueError, match="Exactly one selector"):
        get_analyst(db_conn, analyst_id=1, slug="some-slug", channel_id=f"{_PFX}-xyz")
