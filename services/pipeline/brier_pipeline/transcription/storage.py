"""Object storage behind a small interface (mock-first convention).

Transcripts are persistent; audio objects carry a 30-day TTL lifecycle rule
(FR-103, NFR-4). Production target is Cloudflare R2; LocalFS serves dev/tests.
"""

from __future__ import annotations

import os
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any

from brier_pipeline.transcription.transcriber import AUDIO_KEY_PREFIX, AUDIO_TTL_DAYS


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

    def sweep_expired_audio(
        self,
        *,
        older_than_days: int = AUDIO_TTL_DAYS,
        now: float | None = None,
    ) -> int:
        """Delete files under AUDIO_KEY_PREFIX whose mtime is older than older_than_days.

        This is the real, dependency-free 30-day TTL mechanism (NFR-4) exercised
        by CI and dev. The 'transcripts/' subtree is NEVER touched. Returns the
        count of files deleted.

        Args:
            older_than_days: Age threshold in days (default AUDIO_TTL_DAYS = 30).
            now: Reference epoch seconds for age computation; defaults to time.time().
                 Injectable for deterministic tests.
        """
        reference_time = now if now is not None else time.time()
        cutoff = reference_time - older_than_days * 86400

        audio_root = self.root / AUDIO_KEY_PREFIX
        if not audio_root.exists():
            return 0

        deleted = 0
        for path in audio_root.rglob("*"):
            if not path.is_file():
                continue
            mtime = os.path.getmtime(path)
            if mtime < cutoff:
                path.unlink()
                deleted += 1

        return deleted


def _default_boto3_client_factory(
    account_id: str,
    access_key_id: str,
    secret_access_key: str,
) -> Callable[[], Any]:
    """Return a factory that lazily creates an S3-compatible client for Cloudflare R2.

    The import of boto3 is INSIDE the returned factory so it does not occur at
    module load time (ADR-0004 gate). If boto3 is absent, a clear RuntimeError
    pointing to the ADR is raised on first use — not a silent ImportError.
    """

    def factory() -> Any:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "boto3 not installed; see docs/adr/0004-boto3-r2-storage-dependency.md"
            ) from exc
        return boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    return factory


class R2Storage(Storage):
    """Cloudflare R2 adapter (S3-compatible, zero egress). ADR-0004 gate.

    boto3 is NOT installed until ADR-0004 is approved by the human owner.
    The seam is complete: put/get/delete/ensure_audio_ttl_lifecycle all delegate
    to a real S3 client, tested via an injected fake client. The default
    client_factory lazily imports boto3 inside its body so that absence of the
    dependency raises a clear RuntimeError (not ImportError at module load time).

    Production TTL enforcement (NFR-4): ensure_audio_ttl_lifecycle() configures
    an S3 lifecycle rule that expires objects under the 'audio/' prefix after
    AUDIO_TTL_DAYS days; 'transcripts/' objects are persistent. LocalFSStorage
    .sweep_expired_audio() is the equivalent for dev/CI.
    """

    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str = "brier",
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.account_id = account_id
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.bucket = bucket
        self._client_factory: Callable[[], Any] = (
            client_factory
            if client_factory is not None
            else _default_boto3_client_factory(account_id, access_key_id, secret_access_key)
        )
        self._client: Any | None = None

    def _get_client(self) -> Any:
        """Return the cached S3 client, building it on first use."""
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def put(self, key: str, body: bytes) -> str:
        """Upload body to R2 at Bucket/Key; return key as the storage pointer."""
        self._get_client().put_object(Bucket=self.bucket, Key=key, Body=body)
        return key

    def get(self, key: str) -> bytes:
        """Download and return the object body at Bucket/Key."""
        response = self._get_client().get_object(Bucket=self.bucket, Key=key)
        return bytes(response["Body"].read())

    def delete(self, key: str) -> None:
        """Delete the object at Bucket/Key."""
        self._get_client().delete_object(Bucket=self.bucket, Key=key)

    def ensure_audio_ttl_lifecycle(self) -> None:
        """Configure an R2 bucket lifecycle rule for the audio TTL (NFR-4).

        Sets a rule that expires all objects under AUDIO_KEY_PREFIX ('audio/')
        after AUDIO_TTL_DAYS (30) days. Objects under 'transcripts/' are not
        covered by this rule and remain persistent.

        This is the PRODUCTION TTL mechanism. The dev/CI equivalent is
        LocalFSStorage.sweep_expired_audio(). Call this once during provisioning
        or re-call idempotently; R2/S3 replaces the whole lifecycle configuration.
        """
        self._get_client().put_bucket_lifecycle_configuration(
            Bucket=self.bucket,
            LifecycleConfiguration={
                "Rules": [
                    {
                        "ID": "audio-ttl-30d",
                        "Status": "Enabled",
                        "Filter": {"Prefix": AUDIO_KEY_PREFIX},
                        "Expiration": {"Days": AUDIO_TTL_DAYS},
                    }
                ]
            },
        )
