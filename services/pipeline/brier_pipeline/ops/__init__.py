"""Ops seams for E6 Trust + Ops (NFR-5, NFR-6, AC-5, PRD §18).

Modules:
    alerts  — Alerter seam: record_alert, raise_alert, FakeAlerter,
               BetterStackAlerter (stdlib urllib REST, ADR-0014).
    spend   — Spend-meter engine: guard_and_record_spend, evaluate_spend,
               SpendCapExceeded (NFR-5 hard caps + 70% alert threshold).

Pattern: every external destination sits behind the Alerter protocol.
FakeAlerter is the CI/test path; BetterStackAlerter is the production path,
blocked-by-design without BRIER_BETTER_STACK_TOKEN (ADR-0014).
"""
