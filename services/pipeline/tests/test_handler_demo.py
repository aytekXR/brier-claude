"""`make handler-demo` driver: the transcribe -> extract chain + the three gates.

Exercises brier_pipeline.handler_demo.run_handler_demo end to end on the dev DB
(rolled back via the db_conn fixture), asserting both the chain produced real
claims and the gate illustration classifies each example correctly.
"""

from __future__ import annotations

from typing import Any

from brier_pipeline import handler_demo


class TestHandlerDemo:
    def test_chain_and_gates(self, db_conn: Any) -> None:
        result = handler_demo.run_handler_demo(db_conn)

        # Part 1: the chain dispatched and persisted claims.
        assert result["transcribe_state"] == "done"
        assert result["transcript_id"] is not None
        assert result["extract_state"] == "done"
        assert len(result["claims"]) >= 1
        assert all(c["quote"] for c in result["claims"])

        # Part 2: the four illustrative claims hit the four distinct dispositions.
        dispositions = [g["disposition"] for g in result["gates"]]
        assert dispositions[0].startswith("PUBLISHED")
        assert dispositions[1].startswith("SKIPPED (EC-3")
        assert dispositions[2].startswith("DROPPED (AC-7")
        assert dispositions[3].startswith("ROUTED to QA (FR-203")

    def test_render_smoke(self, db_conn: Any, capsys: Any) -> None:
        """_render prints the narrative without raising (covers the print path)."""
        result = handler_demo.run_handler_demo(db_conn)
        handler_demo._render(result)
        out = capsys.readouterr().out
        assert "EXTRACTED CLAIMS" in out
        assert "GATE GUARANTEES" in out
