"""Embedder seam for semantic claim dedup (FR-205, E3-T5).

The real embedder (SentenceTransformerEmbedder) lazily imports
sentence_transformers inside embed() — never at module load time — so the
dependency (ADR-0008, proposed) is not required until the ADR is approved and
the optional extra is installed.

HashEmbedder is the deterministic, dependency-free CI path: it derives a
384-dim float vector from text via a hash, so tests control similarity via
text content. No model download, no network, no package beyond stdlib.
"""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class Embedder(ABC):
    """Produce a 384-dim embedding vector from a text string."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return a 384-dimensional unit-normalised vector for text."""
        ...


class HashEmbedder(Embedder):
    """Deterministic 384-dim embedder using SHA-256 bytes as floats.

    Used in CI and tests: no model download, no network, no heavy dependency.
    Two identical strings produce identical vectors (cosine sim = 1.0).
    Two different strings produce very different vectors (low cosine sim).

    Repeated calls with the same text return the same vector (deterministic).
    """

    def embed(self, text: str) -> list[float]:
        """Derive a 384-dim unit vector from text via repeated SHA-256."""
        # Build 384 float values from repeated SHA-256 digests of the text.
        # We need 384 * 4 = 1536 bytes; SHA-256 gives 32 bytes per round.
        raw = bytearray()
        seed = text.encode()
        counter = 0
        while len(raw) < 384 * 4:
            h = hashlib.sha256(seed + counter.to_bytes(2, "little")).digest()
            raw.extend(h)
            counter += 1

        # Interpret as 384 little-endian signed ints, then convert to float.
        floats: list[float] = []
        for i in range(384):
            chunk = raw[i * 4 : i * 4 + 4]
            val = int.from_bytes(chunk, "little", signed=True)
            floats.append(float(val))

        # Unit-normalise so cosine similarity = dot product.
        norm = math.sqrt(sum(v * v for v in floats))
        if norm > 0.0:
            floats = [v / norm for v in floats]
        return floats


class SentenceTransformerEmbedder(Embedder):
    """Production embedder: all-MiniLM-L6-v2 via sentence-transformers.

    The import of sentence_transformers happens INSIDE _load_model(), never at
    module load time (ADR-0008 gate).  When the package is absent (CI, dev), a
    clear RuntimeError referencing ADR-0008 is raised — not a silent ImportError.

    sentence-transformers is NOT in pyproject.toml [project.dependencies] or
    any extras until ADR-0008 is approved by the human owner.
    The mypy override (ignore_missing_imports) suppresses type-check errors for
    the absent package without needing per-line suppression comments.
    """

    _MODEL_NAME = "all-MiniLM-L6-v2"
    _ADR_URL = "docs/adr/0008-sentence-transformers-embedding-dependency.md"

    def __init__(self) -> None:
        # _encode is the bound SentenceTransformer.encode method, set on first load.
        # Typed as Callable[[str], Any] to allow iterating the result (numpy array)
        # without per-line type suppression.
        self._encode: Callable[[str], Any] | None = None

    def _load(self) -> None:
        """Lazily import sentence_transformers and load the model (ADR-0008 gate).

        Converts ImportError → RuntimeError so the caller gets a clear, actionable
        message instead of a raw ModuleNotFoundError.
        """
        if self._encode is None:
            try:
                import sentence_transformers

                model = sentence_transformers.SentenceTransformer(self._MODEL_NAME)
                # Store the bound encode method; its return type is opaque here
                # (numpy array), but we iterate it to build list[float] in embed().
                self._encode = model.encode
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is not installed. "
                    "This dependency is ADR-0008-gated (proposed, pending human approval). "
                    f"See {self._ADR_URL}. "
                    "Install the optional extra once the ADR is approved: "
                    "pip install brier-pipeline[embed]"
                ) from exc

    def embed(self, text: str) -> list[float]:
        """Embed text via all-MiniLM-L6-v2 (384 dims). Raises RuntimeError when absent."""
        self._load()  # converts ImportError → RuntimeError; sets _encode
        assert self._encode is not None  # always true after _load() returns
        result = self._encode(text)
        return [float(v) for v in result]
