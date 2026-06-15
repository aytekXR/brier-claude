"""Alerter seam for ops monitoring (PRD §18, ADR-0014).

Protocol: Alerter.dispatch(alert: Alert)
  - FakeAlerter       — records dispatched alerts; the CI/test path.
  - BetterStackAlerter — stdlib urllib POST to Better Stack ingest endpoint;
                         raises RuntimeError when BRIER_BETTER_STACK_TOKEN is
                         absent (blocked-by-design, ADR-0014).

record_alert(conn, ...)  — INSERT into alerts with ON CONFLICT (dedup_key) DO
                           NOTHING; returns True iff a new row was inserted.
raise_alert(conn, alerter, ...) — deduplicating gate: records + dispatches once.

Pattern mirrors brier_pipeline/disputes/notify.py:
external destination behind a small interface, fake is first-class, CI never
hits the network. The alerts table is the durable queryable record (ADR-0014).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from brier_pipeline import config
from brier_pipeline.models import Alert


class Alerter(Protocol):
    """Minimal alerting seam for ops events (PRD §18, ADR-0014)."""

    def dispatch(self, alert: Alert) -> None:
        """Dispatch an alert to the configured destination.

        Args:
            alert: The Alert model to dispatch.
        """
        ...


@dataclass
class FakeAlerter:
    """In-memory alerter; the CI/test path (mock-first convention).

    Records every dispatch() call in self.dispatched so tests can assert on it.
    """

    dispatched: list[Alert] = field(default_factory=list)

    def dispatch(self, alert: Alert) -> None:
        self.dispatched.append(alert)


def _default_http_post(
    url: str, payload: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    """Default HTTP POST using stdlib urllib; the real Better Stack path.

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


class BetterStackAlerter:
    """Better Stack monitoring alerts via stdlib REST (ADR-0014).

    POSTs to the Better Stack ingest endpoint with an injected http_post
    callable. The real path requires BRIER_BETTER_STACK_TOKEN; a clear
    RuntimeError is raised when the token is absent so CI fails loudly
    instead of silently dropping alerts.

    No SDK, nothing added to pyproject.toml (ADR-0014).
    """

    BETTER_STACK_URL = "https://in.logs.betterstack.com"

    def __init__(
        self,
        *,
        ingest_url: str = BETTER_STACK_URL,
        http_post: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]] | None = None,
    ) -> None:
        self._ingest_url = ingest_url
        self._http_post = http_post if http_post is not None else _default_http_post

    def dispatch(self, alert: Alert) -> None:
        """Dispatch an alert to Better Stack via REST (ADR-0014).

        Raises:
            RuntimeError: When BRIER_BETTER_STACK_TOKEN is not set. This is the
                expected failure mode in CI — FakeAlerter is the CI path.
        """
        token = config.better_stack_token()
        if not token:
            raise RuntimeError(
                "BetterStackAlerter requires BRIER_BETTER_STACK_TOKEN to be set. "
                "In CI and tests, inject FakeAlerter instead "
                "(see docs/adr/0014-monitoring-alerting-via-stdlib-rest.md)."
            )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "dt": alert.created_at.isoformat() if alert.created_at else None,
            "kind": alert.kind,
            "severity": alert.severity,
            "subject": alert.subject,
            "summary": alert.summary,
            "dedup_key": alert.dedup_key,
            "detail": alert.detail,
        }
        self._http_post(self._ingest_url, payload, headers)


class SentryAlerter:
    """Sentry error/event monitoring via stdlib REST (PRD §18, ADR-0014).

    Posts a minimal event to the Sentry store endpoint derived from the DSN
    (BRIER_SENTRY_DSN). An injected http_post callable is the test boundary; the
    real path requires the DSN and raises RuntimeError when it is absent so CI
    fails loudly instead of silently dropping events. No 'sentry-sdk', nothing
    added to pyproject.toml (ADR-0014). Axiom (the §18 log sink) follows this
    same Alerter-seam pattern and is deferred behind ADR-0014 (see EX-dept.md).
    """

    def __init__(
        self,
        *,
        http_post: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]] | None = None,
    ) -> None:
        self._http_post = http_post if http_post is not None else _default_http_post

    @staticmethod
    def _store_url_and_key(dsn: str) -> tuple[str, str]:
        """Derive (store_url, public_key) from a Sentry DSN.

        DSN format: ``https://<public_key>@<host>/<project_id>``
        Store URL:  ``https://<host>/api/<project_id>/store/``
        """
        parsed = urllib.parse.urlparse(dsn)
        public_key = parsed.username or ""
        project_id = parsed.path.lstrip("/")
        host = parsed.hostname or ""
        scheme = parsed.scheme or "https"
        port = f":{parsed.port}" if parsed.port else ""
        store_url = f"{scheme}://{host}{port}/api/{project_id}/store/"
        return store_url, public_key

    def dispatch(self, alert: Alert) -> None:
        """Dispatch an alert to Sentry via REST (ADR-0014).

        Raises:
            RuntimeError: When BRIER_SENTRY_DSN is not set. This is the expected
                failure mode in CI — FakeAlerter is the CI path.
        """
        dsn = config.sentry_dsn()
        if not dsn:
            raise RuntimeError(
                "SentryAlerter requires BRIER_SENTRY_DSN to be set. "
                "In CI and tests, inject FakeAlerter instead "
                "(see docs/adr/0014-monitoring-alerting-via-stdlib-rest.md)."
            )
        store_url, public_key = self._store_url_and_key(dsn)
        headers = {
            "Content-Type": "application/json",
            "X-Sentry-Auth": (
                f"Sentry sentry_version=7, sentry_client=brier-stdlib/1.0, sentry_key={public_key}"
            ),
        }
        level = "error" if alert.severity == "critical" else "warning"
        payload: dict[str, Any] = {
            "message": alert.summary,
            "level": level,
            "logger": "brier.ops",
            "tags": {"kind": alert.kind, "subject": alert.subject},
            "extra": alert.detail,
        }
        self._http_post(store_url, payload, headers)


def record_alert(
    conn: Any,
    *,
    kind: str,
    summary: str,
    severity: str = "warning",
    subject: str | None = None,
    dedup_key: str,
    detail: dict[str, Any] | None = None,
) -> bool:
    """Insert an alert row with ON CONFLICT (dedup_key) DO NOTHING.

    Caller owns the transaction (no commit here).

    Args:
        conn:      psycopg connection.
        kind:      Alert kind string (AlertKind enum values).
        summary:   Neutral-register human summary (AC-7).
        severity:  'info' | 'warning' | 'critical'. Default 'warning'.
        subject:   Free-form reference (analyst slug, ticket code, etc.).
        dedup_key: Unique deduplication key; duplicate keys are silently ignored.
        detail:    Optional structured detail dict (stored as JSONB).

    Returns:
        True if a new alert row was inserted; False if dedup_key already exists.
    """
    detail_json = json.dumps(detail or {})
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into alerts (kind, severity, subject, summary, detail, dedup_key)
            values (%s, %s, %s, %s, %s::jsonb, %s)
            on conflict (dedup_key) do nothing
            returning id
            """,
            (kind, severity, subject, summary, detail_json, dedup_key),
        )
        row = cur.fetchone()
    return row is not None


def raise_alert(
    conn: Any,
    alerter: Alerter | None,
    *,
    kind: str,
    summary: str,
    severity: str = "warning",
    subject: str | None = None,
    dedup_key: str,
    detail: dict[str, Any] | None = None,
) -> bool:
    """Deduplicating gate: record alert and dispatch to alerter if newly raised.

    Calls record_alert (idempotent dedup). If a new row was inserted AND
    alerter is not None, builds an Alert model and calls alerter.dispatch().

    Args:
        conn:      psycopg connection (caller owns the transaction).
        alerter:   Alerter implementation, or None to skip external dispatch.
        kind:      Alert kind string (AlertKind enum values).
        summary:   Neutral-register human summary (AC-7).
        severity:  'info' | 'warning' | 'critical'. Default 'warning'.
        subject:   Free-form reference (analyst slug, ticket code, etc.).
        dedup_key: Unique deduplication key.
        detail:    Optional structured detail dict.

    Returns:
        True if the alert was newly raised; False if it was already present.
    """
    newly_recorded = record_alert(
        conn,
        kind=kind,
        summary=summary,
        severity=severity,
        subject=subject,
        dedup_key=dedup_key,
        detail=detail,
    )
    if newly_recorded and alerter is not None:
        alert = Alert(
            kind=kind,
            severity=severity,
            subject=subject,
            summary=summary,
            detail=detail or {},
            dedup_key=dedup_key,
        )
        alerter.dispatch(alert)
    return newly_recorded


def get_alerter() -> Alerter:
    """Return the configured Alerter: the real adapter in production, else the fake.

    BetterStackAlerter is returned when BRIER_BETTER_STACK_TOKEN is set
    (ADR-0014); otherwise FakeAlerter is the CI/dev path. Live job handlers
    (E6 SLA/freshness/erasure checks) call this; tests inject FakeAlerter
    directly. The alerts table is the durable record either way.
    """
    if config.better_stack_token():
        return BetterStackAlerter()
    return FakeAlerter()
