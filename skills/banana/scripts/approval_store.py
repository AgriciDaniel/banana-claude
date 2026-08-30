#!/usr/bin/env python3
"""Private, single-use approval capabilities for paid Banana requests."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from banana_core import (
    BananaError,
    _atomic_write,
    _atomic_write_at,
    _directory_path_matches_fd,
    _open_secure_directory,
)

APPROVAL_TTL_MINUTES = 30
MAX_RECORDS = 1000
CONSUMED_RETENTION_HOURS = 24
MAX_REGISTRY_BYTES = 5 * 1024 * 1024
REGISTRY_KEYS = frozenset({"schema_version", "records"})
RECORD_KEYS = frozenset(
    {"request_fingerprint", "kind", "issued_at", "expires_at", "consumed_at"}
)


def banana_home() -> Path:
    configured = os.environ.get("BANANA_HOME")
    selected = Path(configured).expanduser() if configured else Path.home() / ".banana"
    return Path(os.path.abspath(selected))


def registry_path() -> Path:
    return banana_home() / "approvals.json"


def lock_path() -> Path:
    return banana_home() / "approvals.lock"


def _open_state_directory(path: Path) -> int | None:
    descriptor: int | None = None
    try:
        descriptor = _open_secure_directory(path)
        if descriptor is None:
            absolute = Path(os.path.abspath(path))
            current = Path(absolute.anchor)
            for component in absolute.parts[1:]:
                current /= component
                component_metadata = os.lstat(current)
                if stat.S_ISLNK(component_metadata.st_mode) or not stat.S_ISDIR(
                    component_metadata.st_mode
                ):
                    raise OSError("state path contains a redirect")
            before = os.lstat(path)
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise OSError("state root is not a real directory")
            path.chmod(0o700)
            after = os.lstat(path)
            if (
                stat.S_ISLNK(after.st_mode)
                or not stat.S_ISDIR(after.st_mode)
                or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            ):
                raise OSError("state root identity changed")
            return None
        os.fchmod(descriptor, 0o700)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or not _directory_path_matches_fd(path, descriptor)
        ):
            raise OSError("directory permissions are not 0700")
        return descriptor
    except (BananaError, OSError) as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise BananaError(
            "unsafe_approval_state_directory",
            f"Approval state directory could not be secured at {path}.",
        ) from exc


def _state_leaf_metadata(
    directory_descriptor: int | None,
    path: Path,
    *,
    error_code: str,
    description: str,
) -> os.stat_result | None:
    try:
        if directory_descriptor is None:
            metadata = os.lstat(path)
        else:
            metadata = os.stat(
                path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BananaError(
            error_code, f"{description} cannot be inspected safely."
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise BananaError(
            error_code,
            f"{description} must be one regular, privately linked file.",
        )
    return metadata


def _opened_leaf_matches(
    directory_descriptor: int | None,
    path: Path,
    descriptor: int,
    expected: os.stat_result,
) -> bool:
    try:
        current = (
            os.lstat(path)
            if directory_descriptor is None
            else os.stat(
                path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        )
        opened = os.fstat(descriptor)
    except OSError:
        return False
    expected_identity = (expected.st_dev, expected.st_ino)
    return (
        stat.S_ISREG(current.st_mode)
        and not stat.S_ISLNK(current.st_mode)
        and current.st_nlink == 1
        and stat.S_ISREG(opened.st_mode)
        and opened.st_nlink == 1
        and (current.st_dev, current.st_ino) == expected_identity
        and (opened.st_dev, opened.st_ino) == expected_identity
    )


def _require_approval_lock_binding(
    directory_descriptor: int | None,
    path: Path,
    lock_descriptor: int,
) -> None:
    held = os.fstat(lock_descriptor)
    if not _opened_leaf_matches(
        directory_descriptor,
        path,
        lock_descriptor,
        held,
    ):
        raise BananaError(
            "unsafe_approval_lock",
            "Approval lock public identity changed while the transaction was active.",
        )


@contextmanager
def approval_lock() -> Iterator[tuple[int | None, int]]:
    """Hold a stable file lock while reading and replacing the registry."""
    directory = banana_home()
    directory_descriptor = _open_state_directory(directory)
    path = directory / "approvals.lock"
    try:
        existing = _state_leaf_metadata(
            directory_descriptor,
            path,
            error_code="unsafe_approval_lock",
            description="Approval lock",
        )
    except BananaError:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        raise
    flags = os.O_RDWR
    if existing is None:
        flags |= os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor: int | None = None

    def open_lock(open_flags: int) -> int:
        if directory_descriptor is None:
            return os.open(path, open_flags, 0o600)
        return os.open(
            path.name,
            open_flags,
            0o600,
            dir_fd=directory_descriptor,
        )

    try:
        try:
            descriptor = open_lock(flags)
        except FileExistsError:
            if existing is not None:
                raise
            existing = _state_leaf_metadata(
                directory_descriptor,
                path,
                error_code="unsafe_approval_lock",
                description="Approval lock",
            )
            if existing is None:
                raise
            descriptor = open_lock(flags & ~(os.O_CREAT | os.O_EXCL))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OSError("lock is not one regular, privately linked file")
        if existing is not None and not _opened_leaf_matches(
            directory_descriptor,
            path,
            descriptor,
            existing,
        ):
            raise OSError("lock identity changed while it was opened")
        if existing is None:
            created = _state_leaf_metadata(
                directory_descriptor,
                path,
                error_code="unsafe_approval_lock",
                description="Approval lock",
            )
            if created is None or not _opened_leaf_matches(
                directory_descriptor,
                path,
                descriptor,
                created,
            ):
                raise OSError("new lock identity could not be verified")
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
            if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600:
                raise OSError("lock permissions are not 0600")
        handle = os.fdopen(descriptor, "r+b")
        descriptor = None
    except BananaError:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
            directory_descriptor = None
        raise
    except OSError as exc:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
            directory_descriptor = None
        raise BananaError(
            "unsafe_approval_lock",
            f"Approval lock cannot be opened safely at {path}.",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        if directory_descriptor is not None and not _directory_path_matches_fd(
            directory, directory_descriptor
        ):
            raise BananaError(
                "unsafe_approval_state_directory",
                "Approval state directory identity changed while its lock was held.",
            )
        _require_approval_lock_binding(
            directory_descriptor,
            path,
            handle.fileno(),
        )
        yield directory_descriptor, handle.fileno()
    finally:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def _empty_registry() -> dict[str, Any]:
    return {"schema_version": 1, "records": {}}


def _load_registry(
    directory_descriptor: int | None,
    *,
    lock_descriptor: int,
) -> tuple[dict[str, Any], tuple[int, int] | None]:
    path = banana_home() / "approvals.json"
    _require_approval_lock_binding(
        directory_descriptor,
        banana_home() / "approvals.lock",
        lock_descriptor,
    )
    existing = _state_leaf_metadata(
        directory_descriptor,
        path,
        error_code="corrupt_approval_registry",
        description="Approval registry",
    )
    if existing is None:
        return _empty_registry(), None
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor: int | None = None
    try:
        if directory_descriptor is None:
            descriptor = os.open(path, flags)
        else:
            descriptor = os.open(path.name, flags, dir_fd=directory_descriptor)
        if not _opened_leaf_matches(
            directory_descriptor,
            path,
            descriptor,
            existing,
        ):
            raise BananaError(
                "corrupt_approval_registry",
                f"Approval registry identity changed while it was opened at {path}.",
            )
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            raw = handle.read(MAX_REGISTRY_BYTES + 1)
            if not _opened_leaf_matches(
                directory_descriptor,
                path,
                handle.fileno(),
                existing,
            ):
                raise BananaError(
                    "corrupt_approval_registry",
                    f"Approval registry identity changed while it was read at {path}.",
                )
    except OSError as exc:
        raise BananaError(
            "corrupt_approval_registry",
            f"Approval registry is unreadable at {path}. Move it aside or repair it before planning paid work.",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) > MAX_REGISTRY_BYTES:
        raise BananaError(
            "corrupt_approval_registry",
            f"Approval registry exceeds the {MAX_REGISTRY_BYTES}-byte safety limit at {path}.",
        )
    try:
        registry = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise BananaError(
            "corrupt_approval_registry",
            f"Approval registry is not valid UTF-8 JSON at {path}. Move it aside or repair it before planning paid work.",
        ) from exc
    if (
        not isinstance(registry, dict)
        or set(registry) != REGISTRY_KEYS
        or type(registry.get("schema_version")) is not int
        or registry.get("schema_version") != 1
        or not isinstance(registry.get("records"), dict)
    ):
        raise BananaError(
            "corrupt_approval_registry",
            f"Approval registry has an invalid schema at {path}.",
        )
    for digest, record in registry["records"].items():
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not isinstance(record, dict)
            or set(record) != RECORD_KEYS
            or not isinstance(record.get("request_fingerprint"), str)
            or not 1 <= len(record["request_fingerprint"]) <= 256
            or record.get("kind") not in {"single", "portfolio"}
            or not isinstance(record.get("issued_at"), str)
            or len(record["issued_at"]) > 128
            or not isinstance(record.get("expires_at"), str)
            or len(record["expires_at"]) > 128
            or (
                record.get("consumed_at") is not None
                and not isinstance(record.get("consumed_at"), str)
            )
            or (
                isinstance(record.get("consumed_at"), str)
                and len(record["consumed_at"]) > 128
            )
        ):
            raise BananaError(
                "corrupt_approval_registry",
                "Approval registry contains an invalid record.",
            )
        try:
            issued_at = _parse_time(record["issued_at"])
            expires_at = _parse_time(record["expires_at"])
            consumed_at = (
                _parse_time(record["consumed_at"])
                if record["consumed_at"] is not None
                else None
            )
        except (TypeError, ValueError) as exc:
            raise BananaError(
                "corrupt_approval_registry",
                "Approval registry contains an invalid timestamp.",
            ) from exc
        if expires_at < issued_at or (
            consumed_at is not None and consumed_at < issued_at
        ):
            raise BananaError(
                "corrupt_approval_registry",
                "Approval registry contains an inconsistent timeline.",
            )
    _require_approval_lock_binding(
        directory_descriptor,
        banana_home() / "approvals.lock",
        lock_descriptor,
    )
    return registry, (existing.st_dev, existing.st_ino)


def _save_registry(
    registry: dict[str, Any],
    directory_descriptor: int | None,
    *,
    lock_descriptor: int,
    expected_registry_identity: tuple[int, int] | None,
) -> None:
    path = banana_home() / "approvals.json"
    serialized = (json.dumps(registry, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _require_approval_lock_binding(
        directory_descriptor,
        banana_home() / "approvals.lock",
        lock_descriptor,
    )
    existing = _state_leaf_metadata(
        directory_descriptor,
        path,
        error_code="corrupt_approval_registry",
        description="Approval registry",
    )
    observed_identity = (
        (existing.st_dev, existing.st_ino) if existing is not None else None
    )
    if observed_identity != expected_registry_identity:
        raise BananaError(
            "approval_registry_changed",
            "Approval registry changed after it was read. No replacement was attempted.",
        )
    try:
        if directory_descriptor is None:
            _atomic_write(path, serialized)
        else:
            _require_approval_lock_binding(
                directory_descriptor,
                banana_home() / "approvals.lock",
                lock_descriptor,
            )
            _atomic_write_at(
                directory_descriptor,
                path.name,
                serialized,
                replace=existing is not None,
                expected_directory=banana_home(),
                expected_destination_identity=expected_registry_identity,
            )
    except BananaError as exc:
        if exc.code == "output_directory_changed":
            raise BananaError(
                "unsafe_approval_state_directory",
                "Approval state directory identity changed before registry publication.",
            ) from exc
        if exc.code == "output_exists" and existing is None:
            raise BananaError(
                "corrupt_approval_registry",
                "Approval registry appeared concurrently and was not replaced.",
            ) from exc
        raise
    _require_approval_lock_binding(
        directory_descriptor,
        banana_home() / "approvals.lock",
        lock_descriptor,
    )


def _token_digest(approval_id: str) -> str:
    if (
        not isinstance(approval_id, str)
        or not approval_id.startswith("bap_")
        or len(approval_id) > 256
    ):
        raise BananaError(
            "invalid_approval",
            "Approval ID is malformed. Create and approve a new plan.",
        )
    return hashlib.sha256(approval_id.encode("utf-8")).hexdigest()


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is not a string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _prune(registry: dict[str, Any], now: datetime) -> None:
    records = registry["records"]
    retention_cutoff = now - timedelta(hours=CONSUMED_RETENTION_HOURS)
    remove: list[str] = []
    for digest, record in records.items():
        try:
            expires_at = _parse_time(record.get("expires_at"))
            consumed_at = (
                _parse_time(record["consumed_at"])
                if record.get("consumed_at")
                else None
            )
        except (AttributeError, TypeError, ValueError):
            raise BananaError(
                "corrupt_approval_registry",
                "Approval registry contains an invalid record.",
            )
        if expires_at < now and (consumed_at is None or consumed_at < retention_cutoff):
            remove.append(digest)
        elif consumed_at is not None and consumed_at < retention_cutoff:
            remove.append(digest)
    for digest in remove:
        records.pop(digest, None)


def issue_approval(request_fingerprint: str, *, kind: str) -> dict[str, str]:
    """Issue and persist a short-lived capability bound to one request hash."""
    if kind not in {"single", "portfolio"}:
        raise BananaError("invalid_approval_kind", "Unsupported approval kind.")
    if (
        not isinstance(request_fingerprint, str)
        or not request_fingerprint
        or len(request_fingerprint) > 256
    ):
        raise BananaError(
            "invalid_request_fingerprint",
            "Cannot issue approval without a request fingerprint.",
        )
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=APPROVAL_TTL_MINUTES)
    approval_id = "bap_" + secrets.token_urlsafe(24)
    digest = _token_digest(approval_id)
    record = {
        "request_fingerprint": request_fingerprint,
        "kind": kind,
        "issued_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "consumed_at": None,
    }
    with approval_lock() as (directory_descriptor, lock_descriptor):
        registry, registry_identity = _load_registry(
            directory_descriptor,
            lock_descriptor=lock_descriptor,
        )
        _prune(registry, now)
        if len(registry["records"]) >= MAX_RECORDS:
            raise BananaError(
                "approval_capacity_reached",
                "Approval registry capacity is occupied by live capabilities. Consume them or wait for expiry before planning another paid request.",
            )
        registry["records"][digest] = record
        _save_registry(
            registry,
            directory_descriptor,
            lock_descriptor=lock_descriptor,
            expected_registry_identity=registry_identity,
        )
    return {
        "approval_id": approval_id,
        "approval_expires_at": expires_at.isoformat(),
        "approval_scope": "single_use",
    }


def consume_approval(approval_id: str, request_fingerprint: str, *, kind: str) -> None:
    """Atomically consume an approval before any provider request is attempted."""
    digest = _token_digest(approval_id)
    now = datetime.now(timezone.utc)
    with approval_lock() as (directory_descriptor, lock_descriptor):
        registry, registry_identity = _load_registry(
            directory_descriptor,
            lock_descriptor=lock_descriptor,
        )
        _prune(registry, now)
        record = registry["records"].get(digest)
        if not isinstance(record, dict):
            raise BananaError(
                "approval_not_found",
                "Approval is unknown or expired. Create and approve a new plan.",
            )
        try:
            expires_at = _parse_time(record.get("expires_at"))
        except (TypeError, ValueError) as exc:
            raise BananaError(
                "corrupt_approval_registry",
                "Approval registry contains an invalid timestamp.",
            ) from exc
        if record.get("consumed_at"):
            raise BananaError(
                "approval_already_used",
                "This approval has already been used. Create and approve a new plan.",
            )
        if expires_at < now:
            raise BananaError(
                "approval_expired",
                "This approval has expired. Create and approve a new plan.",
            )
        if record.get("kind") != kind:
            raise BananaError(
                "approval_scope_mismatch",
                "Approval was issued for a different execution surface.",
            )
        if record.get("request_fingerprint") != request_fingerprint:
            raise BananaError(
                "plan_mismatch",
                "Approval does not match this exact request. Create and approve a new plan before execution.",
            )
        record["consumed_at"] = now.isoformat()
        _save_registry(
            registry,
            directory_descriptor,
            lock_descriptor=lock_descriptor,
            expected_registry_identity=registry_identity,
        )
