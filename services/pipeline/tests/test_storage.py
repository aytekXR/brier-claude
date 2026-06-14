"""Tests for brier_pipeline.transcription.storage — LocalFSStorage and R2Storage seam.

All tests are dependency-free and network-free:
  - LocalFSStorage uses a real temporary filesystem.
  - R2Storage is tested via an injected fake S3 client; no boto3, no network.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from brier_pipeline.transcription.storage import LocalFSStorage, R2Storage
from brier_pipeline.transcription.transcriber import AUDIO_KEY_PREFIX, AUDIO_TTL_DAYS

# ---------------------------------------------------------------------------
# Fake S3 client for R2Storage injection
# ---------------------------------------------------------------------------


class FakeS3Client:
    """In-test fake that records S3 API calls and holds an in-memory object store."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("put_object", kwargs))
        key = str(kwargs["Key"])
        self._store[key] = bytes(kwargs["Body"])
        return {}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_object", kwargs))
        key = str(kwargs["Key"])
        if key not in self._store:
            raise KeyError(f"No object at {key!r}")

        class _Body:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

        return {"Body": _Body(self._store[key])}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete_object", kwargs))
        self._store.pop(str(kwargs.get("Key", "")), None)
        return {}

    def put_bucket_lifecycle_configuration(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("put_bucket_lifecycle_configuration", kwargs))
        return {}


# ---------------------------------------------------------------------------
# LocalFSStorage — basic round-trip + safety
# ---------------------------------------------------------------------------


def test_localfs_put_get_roundtrip(tmp_path: Path) -> None:
    store = LocalFSStorage(tmp_path)
    key = "transcripts/vid123"
    body = b"hello world"
    returned_key = store.put(key, body)
    assert returned_key == key
    assert store.get(key) == body


def test_localfs_delete(tmp_path: Path) -> None:
    store = LocalFSStorage(tmp_path)
    key = "audio/vid456"
    store.put(key, b"audio bytes")
    assert (tmp_path / key).exists()
    store.delete(key)
    assert not (tmp_path / key).exists()


def test_localfs_delete_missing_is_noop(tmp_path: Path) -> None:
    store = LocalFSStorage(tmp_path)
    # Should not raise even if the file doesn't exist.
    store.delete("audio/nonexistent")


def test_localfs_path_traversal_rejected(tmp_path: Path) -> None:
    store = LocalFSStorage(tmp_path)
    with pytest.raises(ValueError, match="Unsafe storage key"):
        store.put("../escape", b"bad")


def test_localfs_path_traversal_in_segment_rejected(tmp_path: Path) -> None:
    store = LocalFSStorage(tmp_path)
    with pytest.raises(ValueError, match="Unsafe storage key"):
        store.get("audio/../../etc/passwd")


# ---------------------------------------------------------------------------
# LocalFSStorage.sweep_expired_audio
# ---------------------------------------------------------------------------


def _set_mtime(path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime))


def test_sweep_deletes_old_audio_keeps_recent_and_transcripts(tmp_path: Path) -> None:
    store = LocalFSStorage(tmp_path)
    now = 1_750_000_000.0  # fixed reference epoch seconds

    # Old audio file (31 days old — beyond the 30-day TTL)
    old_audio_key = f"{AUDIO_KEY_PREFIX}old-video"
    store.put(old_audio_key, b"old audio")
    _set_mtime(tmp_path / old_audio_key, now - 31 * 86400)

    # Recent audio file (5 days old — within the TTL)
    recent_audio_key = f"{AUDIO_KEY_PREFIX}new-video"
    store.put(recent_audio_key, b"new audio")
    _set_mtime(tmp_path / recent_audio_key, now - 5 * 86400)

    # Transcript file (old mtime, but must NEVER be deleted)
    transcript_key = "transcripts/old-video"
    store.put(transcript_key, b"transcript json")
    _set_mtime(tmp_path / transcript_key, now - 60 * 86400)

    deleted = store.sweep_expired_audio(older_than_days=AUDIO_TTL_DAYS, now=now)

    assert deleted == 1
    assert not (tmp_path / old_audio_key).exists(), "Old audio must be deleted"
    assert (tmp_path / recent_audio_key).exists(), "Recent audio must be kept"
    assert (tmp_path / transcript_key).exists(), "Transcript must never be deleted"


def test_sweep_returns_zero_when_audio_dir_absent(tmp_path: Path) -> None:
    store = LocalFSStorage(tmp_path)
    assert store.sweep_expired_audio(now=1_750_000_000.0) == 0


def test_sweep_deletes_all_when_all_old(tmp_path: Path) -> None:
    store = LocalFSStorage(tmp_path)
    now = 1_750_000_000.0

    for vid in ("vid-a", "vid-b", "vid-c"):
        key = f"{AUDIO_KEY_PREFIX}{vid}"
        store.put(key, b"data")
        _set_mtime(tmp_path / key, now - 40 * 86400)

    deleted = store.sweep_expired_audio(older_than_days=30, now=now)
    assert deleted == 3
    assert not any((tmp_path / AUDIO_KEY_PREFIX).iterdir())


def test_sweep_keeps_all_when_all_recent(tmp_path: Path) -> None:
    store = LocalFSStorage(tmp_path)
    now = 1_750_000_000.0

    for vid in ("vid-x", "vid-y"):
        key = f"{AUDIO_KEY_PREFIX}{vid}"
        store.put(key, b"data")
        _set_mtime(tmp_path / key, now - 1 * 86400)

    deleted = store.sweep_expired_audio(older_than_days=30, now=now)
    assert deleted == 0
    assert len(list((tmp_path / AUDIO_KEY_PREFIX).iterdir())) == 2


# ---------------------------------------------------------------------------
# R2Storage — injected fake client (no network, no boto3)
# ---------------------------------------------------------------------------


def _make_r2(bucket: str = "brier") -> tuple[R2Storage, FakeS3Client]:
    fake = FakeS3Client()
    r2 = R2Storage(
        account_id="test-acct",
        access_key_id="fake-key",
        secret_access_key="fake-secret",
        bucket=bucket,
        client_factory=lambda: fake,
    )
    return r2, fake


def test_r2_put_delegates_correctly() -> None:
    r2, fake = _make_r2()
    key = "audio/vid789"
    body = b"audio bytes"
    returned = r2.put(key, body)
    assert returned == key
    assert len(fake.calls) == 1
    method, kwargs = fake.calls[0]
    assert method == "put_object"
    assert kwargs["Bucket"] == "brier"
    assert kwargs["Key"] == key
    assert kwargs["Body"] == body


def test_r2_get_returns_body() -> None:
    r2, fake = _make_r2()
    key = "transcripts/vid789"
    body = b"transcript json"
    r2.put(key, body)
    result = r2.get(key)
    assert result == body
    # Two calls: put_object + get_object
    methods = [c[0] for c in fake.calls]
    assert "get_object" in methods
    get_call = next(k for m, k in fake.calls if m == "get_object")
    assert get_call["Bucket"] == "brier"
    assert get_call["Key"] == key


def test_r2_put_get_roundtrip() -> None:
    r2, _ = _make_r2()
    body = b"\x00\x01\x02\x03binary"
    r2.put("audio/bin-test", body)
    assert r2.get("audio/bin-test") == body


def test_r2_delete_delegates_correctly() -> None:
    r2, fake = _make_r2()
    key = "audio/to-delete"
    r2.put(key, b"temp")
    fake.calls.clear()
    r2.delete(key)
    assert len(fake.calls) == 1
    method, kwargs = fake.calls[0]
    assert method == "delete_object"
    assert kwargs["Bucket"] == "brier"
    assert kwargs["Key"] == key


def test_r2_ensure_audio_ttl_lifecycle_calls_put_bucket_lifecycle() -> None:
    r2, fake = _make_r2("my-bucket")
    r2.ensure_audio_ttl_lifecycle()
    assert len(fake.calls) == 1
    method, kwargs = fake.calls[0]
    assert method == "put_bucket_lifecycle_configuration"
    assert kwargs["Bucket"] == "my-bucket"
    # Verify the lifecycle rule targets the audio prefix with the correct TTL
    rules = kwargs["LifecycleConfiguration"]["Rules"]
    assert len(rules) == 1
    rule = rules[0]
    assert rule["Status"] == "Enabled"
    assert rule["Filter"]["Prefix"] == AUDIO_KEY_PREFIX
    assert rule["Expiration"]["Days"] == AUDIO_TTL_DAYS


def test_r2_client_cached_across_calls() -> None:
    """Client factory must only be called once regardless of how many operations run."""
    call_count = 0
    fake = FakeS3Client()

    def counting_factory() -> FakeS3Client:
        nonlocal call_count
        call_count += 1
        return fake

    r2 = R2Storage(
        account_id="acct",
        access_key_id="key",
        secret_access_key="secret",
        client_factory=counting_factory,
    )
    r2.put("audio/a", b"1")
    r2.get("audio/a")
    r2.delete("audio/a")
    assert call_count == 1, "Client factory should be called exactly once (lazy caching)"


# ---------------------------------------------------------------------------
# R2Storage default path — RuntimeError when boto3 absent (ADR-0004)
# ---------------------------------------------------------------------------


def test_r2_default_raises_runtime_error_when_boto3_absent() -> None:
    """The default client_factory must raise RuntimeError (not ImportError) mentioning
    both 'boto3' and '0004' so operators know what to do.  boto3 is intentionally
    absent in this environment (ADR-0004 pending approval).
    """
    r2 = R2Storage("acct", "id", "secret")  # no client_factory injected
    with pytest.raises(RuntimeError) as exc_info:
        r2.get("some/key")
    msg = str(exc_info.value)
    assert "boto3" in msg, f"Expected 'boto3' in error message; got: {msg!r}"
    assert "0004" in msg, f"Expected '0004' (ADR reference) in error message; got: {msg!r}"
