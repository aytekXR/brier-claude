"""Object storage behind a small interface (mock-first convention).

Transcripts are persistent; audio objects carry a 30-day TTL lifecycle rule
(FR-103, NFR-4). Production target is Cloudflare R2; LocalFS serves dev/tests.
"""

from __future__ import annotations

import re
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


# Keys must not escape the root via path traversal.
_UNSAFE_KEY_RE = re.compile(r"(^|/)\.\.")


def _safe_path(root: Path, key: str) -> Path:
    """Resolve key relative to root, rejecting path-traversal attempts."""
    if _UNSAFE_KEY_RE.search(key):
        raise ValueError(f"Unsafe storage key rejected: {key!r}")
    return root / key


class LocalFSStorage(Storage):
    """Filesystem adapter for dev and tests (data/local/ by default).

    Keys are relative paths; parent directories are created on put().
    Attempting to use '..' in a key raises ValueError.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, key: str, body: bytes) -> str:
        """Write body to <root>/<key>; return the key as the storage pointer."""
        dest = _safe_path(self.root, key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        return key

    def get(self, key: str) -> bytes:
        """Read and return the object at <root>/<key>."""
        path = _safe_path(self.root, key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        """Remove the object at <root>/<key>; no-op if absent."""
        path = _safe_path(self.root, key)
        path.unlink(missing_ok=True)


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
