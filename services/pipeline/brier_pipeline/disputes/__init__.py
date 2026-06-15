"""Dispute intake module (FR-405, US-006, AC-5, UF-3, EC-12).

Public surface:
  create_dispute(...)   -> Dispute  (models.py)
  record_adjudication(...)
"""

from brier_pipeline.disputes.intake import create_dispute, record_adjudication
from brier_pipeline.models import Correction, Dispute

__all__ = ["Dispute", "Correction", "create_dispute", "record_adjudication"]
