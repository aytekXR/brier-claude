"""Object storage behind a small interface (mock-first convention).

Transcripts are persistent; audio objects carry a 30-day TTL lifecycle rule
(FR-103, NFR-4). Production target is Cloudflare R2; LocalFS serves dev/tests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Storage(ABC):
    @abstractmethod
    def put(self, key: str, body: bytes) -> str:
        """Store an object; returns the storage pointer recorded in Postgres."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Fetch an object by key."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove an object (used by the audio TTL sweep)."""


class LocalFSStorage(Storage):
    """Filesystem adapter for dev and tests (data/local/ by default)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, key: str, body: bytes) -> str:
        # TASK: E1-T1 (needed by the pipeline-demo to store fixture transcripts)
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        # TASK: E1-T1
        raise NotImplementedError

    def delete(self, key: str) -> None:
        # TASK: E1-T1
        raise NotImplementedError


class R2Storage(Storage):
    """Cloudflare R2 adapter (zero egress). Not used until E2."""

    def __init__(self, account_id: str, access_key_id: str, secret_access_key: str) -> None:
        self.account_id = account_id
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key

    def put(self, key: str, body: bytes) -> str:
        # TASK: E2-T5
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        # TASK: E2-T5
        raise NotImplementedError

    def delete(self, key: str) -> None:
        # TASK: E2-T5
        raise NotImplementedError
