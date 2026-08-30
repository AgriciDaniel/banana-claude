#!/usr/bin/env python3
"""Private, concurrency-safe image output cost ledger for Banana Claude."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import hmac
import json
import math
import os
import re
import stat
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, NoReturn, cast

from banana_core import (
    BananaError,
    SecretSafeArgumentParser,
    _atomic_write,
    _atomic_write_at,
    _directory_path_matches_fd,
    _exclusive_rename_at,
    _open_secure_directory,
    enforce_json_nesting_limit,
    estimate_image_cost,
    get_model,
    normalize_image_size,
    validate_approval_text,
)

MAX_LEDGER_BYTES = 10 * 1024 * 1024
MAX_LEDGER_MODEL_CHARS = 512
MAX_LEDGER_RESOLUTION_CHARS = 128
MAX_LEDGER_LABEL_CHARS = 80
MAX_LEDGER_INTERACTION_ID_CHARS = 512
_LEDGER_IDENTITY_UNCHECKED = object()
ACTIVE_LEDGER_KEYS = frozenset(
    {"schema_version", "total_cost", "total_images", "entries", "daily"}
)
ACTIVE_DAILY_KEYS = frozenset({"count", "estimated_image_output_usd"})
GENERATED_ENTRY_KEYS = frozenset(
    {
        "ts",
        "model",
        "resolution",
        "count",
        "estimated_image_output_usd",
        "image_output_rate_usd",
        "estimate_basis",
        "estimate_is_invoice_cap",
        "batch",
        "label",
    }
)
GENERATED_ENTRY_OPTIONAL_KEYS = frozenset({"interaction_id_sha256", "attempt_sha256"})
MIGRATED_ENTRY_KEYS = frozenset(
    {
        "ts",
        "model",
        "resolution",
        "count",
        "estimated_image_output_usd",
        "image_output_rate_usd",
        "estimate_basis",
        "estimate_is_invoice_cap",
        "label",
        "legacy_prompt_redacted",
        "legacy_metadata_incomplete",
    }
)
LEGACY_TOP_LEVEL_KEYS = frozenset({"total_cost", "total_images", "entries", "daily"})
LEGACY_ENTRY_KEYS = frozenset({"ts", "model", "res", "cost", "prompt"})
LEGACY_DAILY_KEYS = frozenset({"count", "cost"})
MIGRATION_FINGERPRINT_DOMAIN = b"banana-claude:cost-ledger:v1.4.1-to-schema-1\0"
MIGRATION_BACKUP_NAME = re.compile(
    r"\Acosts\.v1-\d{8}T\d{12}Z-[0-9a-f]{12}-[0-9a-f]{16}\.json\Z"
)


def banana_home() -> Path:
    configured = os.environ.get("BANANA_HOME")
    selected = Path(configured).expanduser() if configured else Path.home() / ".banana"
    return Path(os.path.abspath(selected))


def ledger_path() -> Path:
    return banana_home() / "costs.json"


def lock_path() -> Path:
    return banana_home() / "costs.lock"


def empty_ledger() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "total_cost": 0.0,
        "total_images": 0,
        "entries": [],
        "daily": {},
    }


def _nonnegative_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value)) and value >= 0


def _costs_match(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=0.00005)


def _safe_retained_text(value: Any, *, max_length: int) -> bool:
    if type(value) is not str:
        return False
    try:
        return bool(
            validate_approval_text(
                value,
                field="Retained ledger text",
                max_length=max_length,
                error_code="invalid_cost_ledger",
            )
            == value
        )
    except BananaError:
        return False


def _valid_sha256_digest(value: Any) -> bool:
    return bool(
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _normalize_raw_interaction_ids(ledger: Any) -> tuple[Any, bool]:
    """Replace a prior schema-1 raw ID field with its one-way digest in memory."""
    if type(ledger) is not dict or type(ledger.get("entries")) is not list:
        return ledger, False
    normalized_entries: list[Any] = []
    changed = False
    for raw_entry in ledger["entries"]:
        if type(raw_entry) is not dict or "interaction_id" not in raw_entry:
            normalized_entries.append(raw_entry)
            continue
        if "interaction_id_sha256" in raw_entry:
            return ledger, False
        raw_identifier = raw_entry.get("interaction_id")
        if not _safe_retained_text(
            raw_identifier,
            max_length=MAX_LEDGER_INTERACTION_ID_CHARS,
        ):
            return ledger, False
        normalized_entry = dict(raw_entry)
        normalized_entry.pop("interaction_id")
        normalized_entry["interaction_id_sha256"] = hashlib.sha256(
            cast(str, raw_identifier).encode("utf-8")
        ).hexdigest()
        normalized_entries.append(normalized_entry)
        changed = True
    if not changed:
        return ledger, False
    normalized_ledger = dict(ledger)
    normalized_ledger["entries"] = normalized_entries
    return normalized_ledger, True


def _generated_entry_day(entry: dict[str, Any]) -> str | None:
    keys = frozenset(entry)
    if not GENERATED_ENTRY_KEYS <= keys or not keys <= (
        GENERATED_ENTRY_KEYS | GENERATED_ENTRY_OPTIONAL_KEYS
    ):
        return None
    if not _safe_retained_text(entry.get("model"), max_length=MAX_LEDGER_MODEL_CHARS):
        return None
    if not _safe_retained_text(
        entry.get("resolution"), max_length=MAX_LEDGER_RESOLUTION_CHARS
    ):
        return None
    if not _safe_retained_text(entry.get("label"), max_length=MAX_LEDGER_LABEL_CHARS):
        return None
    if entry.get(
        "estimate_basis"
    ) != "recorded_image_outputs" or not _safe_retained_text(
        entry.get("estimate_basis"), max_length=64
    ):
        return None
    if "interaction_id_sha256" in entry and not _valid_sha256_digest(
        entry.get("interaction_id_sha256")
    ):
        return None
    if "attempt_sha256" in entry and not _valid_sha256_digest(
        entry.get("attempt_sha256")
    ):
        return None
    if type(entry.get("batch")) is not bool:
        return None
    return _canonical_generated_day(entry.get("ts"))


def _migrated_entry_day(entry: dict[str, Any]) -> str | None:
    if frozenset(entry) != MIGRATED_ENTRY_KEYS:
        return None
    if not _safe_retained_text(entry.get("model"), max_length=MAX_LEDGER_MODEL_CHARS):
        return None
    if not _safe_retained_text(
        entry.get("resolution"), max_length=MAX_LEDGER_RESOLUTION_CHARS
    ):
        return None
    if entry.get(
        "label"
    ) != "migrated legacy image generation" or not _safe_retained_text(
        entry.get("label"), max_length=MAX_LEDGER_LABEL_CHARS
    ):
        return None
    if entry.get(
        "estimate_basis"
    ) != "legacy_recorded_image_output" or not _safe_retained_text(
        entry.get("estimate_basis"), max_length=64
    ):
        return None
    if entry.get("count") != 1 or type(entry.get("count")) is not int:
        return None
    if entry.get("legacy_prompt_redacted") is not True:
        return None
    if entry.get("legacy_metadata_incomplete") is not True:
        return None
    return _canonical_legacy_timestamp_day(entry.get("ts"))


def _canonical_generated_day(value: Any) -> str | None:
    if type(value) is not str or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return None
    if parsed.isoformat(timespec="seconds") != value:
        return None
    return parsed.strftime("%Y-%m-%d")


def _canonical_legacy_timestamp_day(value: Any) -> str | None:
    if type(value) is not str or len(value) != 19:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    if parsed.strftime("%Y-%m-%dT%H:%M:%S") != value:
        return None
    return parsed.strftime("%Y-%m-%d")


def _canonical_day(value: Any) -> str | None:
    if type(value) is not str or len(value) != 10:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return value if parsed.strftime("%Y-%m-%d") == value else None


def _active_entry_summary(entry: Any) -> tuple[str, int, float] | None:
    if type(entry) is not dict:
        return None
    typed_entry = cast(dict[str, Any], entry)
    day = _generated_entry_day(typed_entry)
    migrated = False
    if day is None:
        day = _migrated_entry_day(typed_entry)
        migrated = day is not None
    if day is None:
        return None

    count = typed_entry.get("count")
    if type(count) is not int or count < 1:
        return None
    cost = typed_entry.get("estimated_image_output_usd")
    rate = typed_entry.get("image_output_rate_usd")
    if not _nonnegative_number(cost) or not _nonnegative_number(rate):
        return None
    if typed_entry.get("estimate_is_invoice_cap") is not False:
        return None
    numeric_cost = float(cast(int | float, cost))
    numeric_rate = float(cast(int | float, rate))
    expected_cost = numeric_rate if migrated else round(numeric_rate * count, 4)
    if not _costs_match(numeric_cost, expected_cost):
        return None
    return day, count, numeric_cost


def _ledger_schema_is_valid(ledger: Any) -> bool:
    if type(ledger) is not dict or frozenset(ledger) != ACTIVE_LEDGER_KEYS:
        return False
    if (
        type(ledger.get("schema_version")) is not int
        or ledger.get("schema_version") != 1
    ):
        return False
    if not _nonnegative_number(ledger.get("total_cost")):
        return False
    total_images = ledger.get("total_images")
    if type(total_images) is not int or total_images < 0:
        return False
    entries = ledger.get("entries")
    if type(entries) is not list:
        return False
    entry_count_total = 0
    entry_cost_total = 0.0
    entry_daily: dict[str, tuple[int, float]] = {}
    for entry in entries:
        summary = _active_entry_summary(entry)
        if summary is None:
            return False
        day, count, cost = summary
        entry_count_total += count
        entry_cost_total += cost
        prior_count, prior_cost = entry_daily.get(day, (0, 0.0))
        entry_daily[day] = (prior_count + count, prior_cost + cost)
    if entry_count_total != total_images:
        return False
    if not _costs_match(
        float(cast(int | float, ledger["total_cost"])), entry_cost_total
    ):
        return False

    daily = ledger.get("daily")
    if type(daily) is not dict:
        return False
    daily_count_total = 0
    daily_cost_total = 0.0
    seen_days: set[str] = set()
    for day, data in daily.items():
        canonical_day = _canonical_day(day)
        if (
            canonical_day is None
            or type(data) is not dict
            or frozenset(data) != ACTIVE_DAILY_KEYS
        ):
            return False
        daily_count_value = data.get("count")
        if type(daily_count_value) is not int or daily_count_value < 1:
            return False
        daily_cost_value = data.get("estimated_image_output_usd")
        if not _nonnegative_number(daily_cost_value):
            return False
        numeric_cost = float(cast(int | float, daily_cost_value))
        expected = entry_daily.get(canonical_day)
        if (
            expected is None
            or expected[0] != daily_count_value
            or not _costs_match(expected[1], numeric_cost)
        ):
            return False
        daily_count_total += daily_count_value
        daily_cost_total += numeric_cost
        seen_days.add(canonical_day)
    if seen_days != set(entry_daily):
        return False
    if daily_count_total != total_images:
        return False
    if not _costs_match(
        float(cast(int | float, ledger["total_cost"])), daily_cost_total
    ):
        return False
    return True


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
            "unsafe_cost_state_directory",
            f"Cost state directory could not be secured at {path}.",
        ) from exc


def _open_existing_state_directory(path: Path) -> int | None:
    absolute = Path(os.path.abspath(path))
    if os.name == "nt" or not hasattr(os, "O_DIRECTORY"):
        current = Path(absolute.anchor)
        try:
            for component in absolute.parts[1:]:
                current /= component
                metadata = os.lstat(current)
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                    raise OSError("state path contains a redirect")
        except OSError as exc:
            raise BananaError(
                "unsafe_cost_state_directory",
                f"Cost state directory could not be opened safely at {absolute}.",
            ) from exc
        return None

    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor: int | None = None
    try:
        descriptor = os.open(absolute.anchor or "/", flags)
        for component in absolute.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            metadata = os.fstat(next_descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(next_descriptor)
                raise OSError("state path component is not a directory")
            os.close(descriptor)
            descriptor = next_descriptor
        if not _directory_path_matches_fd(absolute, descriptor):
            raise OSError("state directory identity changed")
        return descriptor
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise BananaError(
            "unsafe_cost_state_directory",
            f"Cost state directory could not be opened safely at {absolute}.",
        ) from exc


def _secure_directory(path: Path) -> None:
    descriptor = _open_state_directory(path)
    if descriptor is not None:
        os.close(descriptor)


def _state_leaf_metadata(
    directory_descriptor: int | None,
    path: Path,
    *,
    error_code: str,
    description: str,
    require_single_link: bool = True,
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
        or (require_single_link and metadata.st_nlink != 1)
    ):
        raise BananaError(
            error_code,
            f"{description} must be one regular, privately linked file.",
        )
    return metadata


def _opened_state_leaf_matches(
    directory_descriptor: int | None,
    path: Path,
    descriptor: int,
    expected: os.stat_result,
    *,
    require_single_link: bool = True,
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
        and (current.st_nlink == 1 if require_single_link else current.st_nlink >= 1)
        and stat.S_ISREG(opened.st_mode)
        and (opened.st_nlink == 1 if require_single_link else opened.st_nlink >= 1)
        and (current.st_dev, current.st_ino) == expected_identity
        and (opened.st_dev, opened.st_ino) == expected_identity
    )


def _read_ledger_bytes(
    path: Path,
    directory_descriptor: int | None = None,
    *,
    require_single_link: bool = False,
) -> bytes:
    owned_directory_descriptor: int | None = None
    if directory_descriptor is None:
        directory_descriptor = _open_existing_state_directory(path.parent)
        owned_directory_descriptor = directory_descriptor
    existing: os.stat_result | None = None
    try:
        existing = _state_leaf_metadata(
            directory_descriptor,
            path,
            error_code="corrupt_cost_ledger",
            description="Cost ledger",
            require_single_link=require_single_link,
        )
    except BananaError:
        if owned_directory_descriptor is not None:
            os.close(owned_directory_descriptor)
        raise
    if existing is None:
        if owned_directory_descriptor is not None:
            os.close(owned_directory_descriptor)
        raise BananaError(
            "corrupt_cost_ledger",
            f"Cost ledger disappeared before it could be read at {path}.",
        )
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
        if not _opened_state_leaf_matches(
            directory_descriptor,
            path,
            descriptor,
            existing,
            require_single_link=require_single_link,
        ):
            raise BananaError(
                "corrupt_cost_ledger",
                f"Cost ledger identity changed while it was opened at {path}.",
            )
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            raw = handle.read(MAX_LEDGER_BYTES + 1)
            if not _opened_state_leaf_matches(
                directory_descriptor,
                path,
                handle.fileno(),
                existing,
                require_single_link=require_single_link,
            ):
                raise BananaError(
                    "corrupt_cost_ledger",
                    f"Cost ledger identity changed while it was read at {path}.",
                )
    except OSError as exc:
        raise BananaError(
            "corrupt_cost_ledger",
            f"Cost ledger is unreadable at {path}. Move it aside or repair it before continuing.",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if owned_directory_descriptor is not None:
            os.close(owned_directory_descriptor)
    if len(raw) > MAX_LEDGER_BYTES:
        raise BananaError(
            "corrupt_cost_ledger",
            f"Cost ledger exceeds the {MAX_LEDGER_BYTES}-byte safety limit at {path}.",
        )
    return raw


def _migration_backup_residue(
    state_directory_descriptor: int | None,
    state_directory: Path,
) -> dict[str, Any] | None:
    """Detect one strict migration-backup residue without selecting a restore."""
    backup_directory = state_directory / "backups"
    backup_directory_descriptor: int | None = None
    try:
        if state_directory_descriptor is None:
            try:
                before = os.lstat(backup_directory)
            except FileNotFoundError:
                return None
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise BananaError(
                    "unsafe_cost_state_directory",
                    "The cost migration backup location is not one real directory.",
                )
            iterator = os.scandir(backup_directory)
            directory_identity = (before.st_dev, before.st_ino)
            path_binding_verified = True
        else:
            flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                flags |= os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            try:
                backup_directory_descriptor = os.open(
                    "backups",
                    flags,
                    dir_fd=state_directory_descriptor,
                )
            except FileNotFoundError:
                return None
            directory_metadata = os.fstat(backup_directory_descriptor)
            if not stat.S_ISDIR(directory_metadata.st_mode):
                raise BananaError(
                    "unsafe_cost_state_directory",
                    "The cost migration backup location is not one real directory.",
                )
            path_binding_verified = _directory_path_matches_fd(
                backup_directory,
                backup_directory_descriptor,
            )
            if not path_binding_verified:
                raise BananaError(
                    "unsafe_cost_state_directory",
                    "The cost migration backup directory identity changed during inspection.",
                )
            directory_identity = (
                directory_metadata.st_dev,
                directory_metadata.st_ino,
            )
            iterator = os.scandir(backup_directory_descriptor)

        with iterator:
            for entry in iterator:
                if MIGRATION_BACKUP_NAME.fullmatch(entry.name) is None:
                    continue
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise BananaError(
                        "cost_migration_recovery_required",
                        "A cost migration backup residue could not be inspected safely.",
                        details={
                            "recovery_required": True,
                            "active_ledger_present": False,
                            "automatic_restore_attempted": False,
                            "backup_directory": str(backup_directory),
                        },
                    ) from exc
                if state_directory_descriptor is None:
                    after = os.lstat(backup_directory)
                    if (
                        stat.S_ISLNK(after.st_mode)
                        or not stat.S_ISDIR(after.st_mode)
                        or (after.st_dev, after.st_ino) != directory_identity
                    ):
                        raise BananaError(
                            "unsafe_cost_state_directory",
                            "The cost migration backup directory identity changed during inspection.",
                        )
                elif not _directory_path_matches_fd(
                    backup_directory,
                    cast(int, backup_directory_descriptor),
                ):
                    raise BananaError(
                        "unsafe_cost_state_directory",
                        "The cost migration backup directory identity changed during inspection.",
                    )
                return {
                    "recovery_required": True,
                    "active_ledger_present": False,
                    "automatic_restore_attempted": False,
                    "backup_directory": str(backup_directory),
                    "backup_directory_device": directory_identity[0],
                    "backup_directory_inode": directory_identity[1],
                    "backup_directory_path_binding_verified": (path_binding_verified),
                    "observed_backup": {
                        "path": str(backup_directory / entry.name),
                        "name": entry.name,
                        "device": metadata.st_dev,
                        "inode": metadata.st_ino,
                        "links": metadata.st_nlink,
                        "regular_file": stat.S_ISREG(metadata.st_mode),
                        "symbolic_link": stat.S_ISLNK(metadata.st_mode),
                        "verify_device_and_inode": True,
                    },
                }
        if state_directory_descriptor is None:
            after = os.lstat(backup_directory)
            if (
                stat.S_ISLNK(after.st_mode)
                or not stat.S_ISDIR(after.st_mode)
                or (after.st_dev, after.st_ino) != directory_identity
            ):
                raise BananaError(
                    "unsafe_cost_state_directory",
                    "The cost migration backup directory identity changed during inspection.",
                )
        elif not _directory_path_matches_fd(
            backup_directory,
            cast(int, backup_directory_descriptor),
        ):
            raise BananaError(
                "unsafe_cost_state_directory",
                "The cost migration backup directory identity changed during inspection.",
            )
        return None
    except BananaError:
        raise
    except OSError as exc:
        raise BananaError(
            "unsafe_cost_state_directory",
            "The cost migration backup location could not be inspected safely.",
        ) from exc
    finally:
        if backup_directory_descriptor is not None:
            os.close(backup_directory_descriptor)


def _parse_ledger_bytes(raw: bytes, path: Path) -> Any:
    try:
        enforce_json_nesting_limit(raw)
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise BananaError(
            "corrupt_cost_ledger",
            f"Cost ledger is not valid UTF-8 JSON at {path}. Move it aside or repair it before continuing.",
        ) from exc


def _require_cost_lock_binding(
    directory_descriptor: int | None,
    path: Path,
    lock_descriptor: int,
) -> None:
    held = os.fstat(lock_descriptor)
    if not _opened_state_leaf_matches(
        directory_descriptor,
        path,
        lock_descriptor,
        held,
    ):
        raise BananaError(
            "unsafe_cost_lock",
            "Cost ledger lock public identity changed while the transaction was active.",
        )


@contextmanager
def ledger_lock() -> Iterator[tuple[int | None, int]]:
    """Lock a stable sidecar file so atomic replacement cannot drop the lock."""
    directory = banana_home()
    directory_descriptor = _open_state_directory(directory)
    path = directory / "costs.lock"
    try:
        existing = _state_leaf_metadata(
            directory_descriptor,
            path,
            error_code="unsafe_cost_lock",
            description="Cost ledger lock",
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
                error_code="unsafe_cost_lock",
                description="Cost ledger lock",
            )
            if existing is None:
                raise
            descriptor = open_lock(flags & ~(os.O_CREAT | os.O_EXCL))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise BananaError(
                "unsafe_cost_lock",
                f"Cost ledger lock must be one regular, privately linked file at {path}.",
            )
        if existing is not None and not _opened_state_leaf_matches(
            directory_descriptor,
            path,
            descriptor,
            existing,
        ):
            raise BananaError(
                "unsafe_cost_lock",
                f"Cost ledger lock identity changed while it was opened at {path}.",
            )
        if existing is None:
            created = _state_leaf_metadata(
                directory_descriptor,
                path,
                error_code="unsafe_cost_lock",
                description="Cost ledger lock",
            )
            if created is None or not _opened_state_leaf_matches(
                directory_descriptor,
                path,
                descriptor,
                created,
            ):
                raise BananaError(
                    "unsafe_cost_lock",
                    f"Cost ledger lock identity could not be verified at {path}.",
                )
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        if os.name != "nt" and stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600:
            raise BananaError(
                "unsafe_cost_lock",
                f"Cost ledger lock permissions could not be secured at {path}.",
            )
        handle = os.fdopen(descriptor, "a+b")
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
            "unsafe_cost_lock",
            f"Cost ledger lock cannot be opened safely at {path}.",
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
                "unsafe_cost_state_directory",
                "Cost state directory identity changed while its lock was held.",
            )
        _require_cost_lock_binding(
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


def load_ledger(
    directory_descriptor: int | None = None,
    *,
    rewrite_raw_interaction_ids: bool = False,
    lock_descriptor: int | None = None,
) -> dict[str, Any]:
    path = banana_home() / "costs.json"
    owned_directory_descriptor: int | None = None
    if directory_descriptor is None:
        directory_descriptor = _open_state_directory(path.parent)
        owned_directory_descriptor = directory_descriptor
    existing: os.stat_result | None = None
    try:
        if lock_descriptor is not None:
            _require_cost_lock_binding(
                directory_descriptor,
                banana_home() / "costs.lock",
                lock_descriptor,
            )
        existing = _state_leaf_metadata(
            directory_descriptor,
            path,
            error_code="corrupt_cost_ledger",
            description="Cost ledger",
        )
        if existing is None:
            residue = _migration_backup_residue(
                directory_descriptor,
                path.parent,
            )
            if residue is not None:
                raise BananaError(
                    "cost_migration_recovery_required",
                    "The active cost ledger is absent while a legacy migration backup remains. Refusing to treat recorded history as empty.",
                    details=residue,
                )
            if lock_descriptor is not None:
                _require_cost_lock_binding(
                    directory_descriptor,
                    banana_home() / "costs.lock",
                    lock_descriptor,
                )
            return empty_ledger()
        parsed = _parse_ledger_bytes(
            _read_ledger_bytes(
                path,
                directory_descriptor,
                require_single_link=True,
            ),
            path,
        )
        ledger, raw_interaction_ids_normalized = _normalize_raw_interaction_ids(parsed)
        if not _ledger_schema_is_valid(ledger):
            raise BananaError(
                "corrupt_cost_ledger", f"Cost ledger has an invalid schema at {path}."
            )
        normalized = cast(dict[str, Any], ledger)
        if raw_interaction_ids_normalized and rewrite_raw_interaction_ids:
            save_ledger(
                normalized,
                directory_descriptor=directory_descriptor,
                lock_descriptor=lock_descriptor,
                expected_ledger_identity=(existing.st_dev, existing.st_ino),
            )
        if lock_descriptor is not None:
            _require_cost_lock_binding(
                directory_descriptor,
                banana_home() / "costs.lock",
                lock_descriptor,
            )
        return normalized
    finally:
        if owned_directory_descriptor is not None:
            os.close(owned_directory_descriptor)


def save_ledger(
    ledger: dict[str, Any],
    *,
    replace: bool = True,
    directory_descriptor: int | None = None,
    lock_descriptor: int | None = None,
    expected_ledger_identity: tuple[int, int] | None | object = (
        _LEDGER_IDENTITY_UNCHECKED
    ),
) -> None:
    if not _ledger_schema_is_valid(ledger):
        raise BananaError(
            "invalid_cost_ledger",
            "Refusing to write a cost ledger that does not satisfy the closed schema-1 contract.",
        )
    path = banana_home() / "costs.json"
    serialized = (json.dumps(ledger, indent=2, sort_keys=True) + "\n").encode("utf-8")
    owned_directory_descriptor: int | None = None
    if directory_descriptor is None:
        directory_descriptor = _open_state_directory(path.parent)
        owned_directory_descriptor = directory_descriptor
    existing: os.stat_result | None = None
    try:
        if lock_descriptor is not None:
            _require_cost_lock_binding(
                directory_descriptor,
                banana_home() / "costs.lock",
                lock_descriptor,
            )
        existing = _state_leaf_metadata(
            directory_descriptor,
            path,
            error_code="corrupt_cost_ledger",
            description="Cost ledger",
        )
        observed_identity = (
            (existing.st_dev, existing.st_ino) if existing is not None else None
        )
        if (
            expected_ledger_identity is not _LEDGER_IDENTITY_UNCHECKED
            and observed_identity != expected_ledger_identity
        ):
            raise BananaError(
                "cost_ledger_changed",
                "Cost ledger changed after it was read. No replacement was attempted.",
            )
        if directory_descriptor is None:
            _atomic_write(path, serialized, replace=replace)
        else:
            if lock_descriptor is not None:
                _require_cost_lock_binding(
                    directory_descriptor,
                    banana_home() / "costs.lock",
                    lock_descriptor,
                )
            _atomic_write_at(
                directory_descriptor,
                path.name,
                serialized,
                replace=replace and existing is not None,
                expected_directory=banana_home(),
                expected_destination_identity=(
                    expected_ledger_identity
                    if expected_ledger_identity is not _LEDGER_IDENTITY_UNCHECKED
                    else observed_identity
                ),
            )
    except BananaError as exc:
        if exc.code == "output_directory_changed":
            raise BananaError(
                "unsafe_cost_state_directory",
                "Cost state directory identity changed before ledger publication.",
            ) from exc
        if not replace and exc.code == "output_exists":
            raise BananaError(
                "migration_source_changed",
                "The legacy cost ledger path was recreated during migration. Its bytes were preserved and the migrated ledger was not installed.",
            ) from exc
        if replace and existing is None and exc.code == "output_exists":
            raise BananaError(
                "corrupt_cost_ledger",
                "Cost ledger appeared concurrently and was not replaced.",
            ) from exc
        raise
    else:
        if lock_descriptor is not None:
            _require_cost_lock_binding(
                directory_descriptor,
                banana_home() / "costs.lock",
                lock_descriptor,
            )
    finally:
        if owned_directory_descriptor is not None:
            os.close(owned_directory_descriptor)


def _ledger_identity(directory_descriptor: int | None) -> tuple[int, int] | None:
    path = banana_home() / "costs.json"
    existing = _state_leaf_metadata(
        directory_descriptor,
        path,
        error_code="corrupt_cost_ledger",
        description="Cost ledger",
    )
    if existing is None:
        return None
    return existing.st_dev, existing.st_ino


def _legacy_validation_error(reason: str) -> BananaError:
    return BananaError(
        "invalid_legacy_cost_ledger",
        f"Cost ledger is not an exact, internally consistent Banana Claude 1.4.1 ledger: {reason}",
    )


def _convert_legacy_ledger(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or frozenset(value) != LEGACY_TOP_LEVEL_KEYS:
        raise _legacy_validation_error(
            "the top-level fields do not match the legacy format"
        )

    total_cost = value.get("total_cost")
    if not _nonnegative_number(total_cost):
        raise _legacy_validation_error("total_cost must be a finite nonnegative number")
    total_images = value.get("total_images")
    if (
        isinstance(total_images, bool)
        or not isinstance(total_images, int)
        or total_images < 0
    ):
        raise _legacy_validation_error("total_images must be a nonnegative integer")

    legacy_entries = value.get("entries")
    if not isinstance(legacy_entries, list):
        raise _legacy_validation_error("entries must be a list")
    converted_entries: list[dict[str, Any]] = []
    entry_cost_total = 0.0
    entry_daily_counts: dict[str, int] = {}
    entry_daily_costs: dict[str, float] = {}
    for index, entry in enumerate(legacy_entries):
        if not isinstance(entry, dict) or frozenset(entry) != LEGACY_ENTRY_KEYS:
            raise _legacy_validation_error(
                f"entry {index} fields do not match the legacy format"
            )
        if not all(
            type(entry.get(field)) is str for field in ("ts", "model", "res", "prompt")
        ):
            raise _legacy_validation_error(f"entry {index} text fields must be strings")
        timestamp = cast(str, entry["ts"])
        try:
            parsed_timestamp = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S")
        except ValueError as exc:
            raise _legacy_validation_error(
                f"entry {index} timestamp is not in the legacy format"
            ) from exc
        entry_cost = entry.get("cost")
        if not _nonnegative_number(entry_cost):
            raise _legacy_validation_error(
                f"entry {index} cost must be a finite nonnegative number"
            )
        cost = float(cast(float | int, entry_cost))
        entry_cost_total += cost
        day = parsed_timestamp.strftime("%Y-%m-%d")
        entry_daily_counts[day] = entry_daily_counts.get(day, 0) + 1
        entry_daily_costs[day] = entry_daily_costs.get(day, 0.0) + cost
        converted_entries.append(
            {
                "ts": timestamp,
                "model": cast(str, entry["model"]),
                "resolution": cast(str, entry["res"]),
                "count": 1,
                "estimated_image_output_usd": entry_cost,
                "image_output_rate_usd": entry_cost,
                "estimate_basis": "legacy_recorded_image_output",
                "estimate_is_invoice_cap": False,
                "label": "migrated legacy image generation",
                "legacy_prompt_redacted": True,
                "legacy_metadata_incomplete": True,
            }
        )

    if total_images != len(legacy_entries):
        raise _legacy_validation_error(
            "total_images does not equal the number of legacy entries"
        )
    if not _costs_match(float(cast(float | int, total_cost)), entry_cost_total):
        raise _legacy_validation_error(
            "total_cost does not reconcile with the legacy entries"
        )

    legacy_daily = value.get("daily")
    if not isinstance(legacy_daily, dict):
        raise _legacy_validation_error("daily must be an object")
    converted_daily: dict[str, dict[str, Any]] = {}
    daily_count_total = 0
    daily_cost_total = 0.0
    for daily_index, (day, record) in enumerate(legacy_daily.items()):
        if type(day) is not str:
            raise _legacy_validation_error("daily keys must be date strings")
        try:
            datetime.strptime(day, "%Y-%m-%d")
        except ValueError as exc:
            raise _legacy_validation_error(
                f"daily key {daily_index} is not in the legacy date format"
            ) from exc
        if not isinstance(record, dict) or frozenset(record) != LEGACY_DAILY_KEYS:
            raise _legacy_validation_error(
                f"daily record {daily_index} fields do not match the legacy format"
            )
        count = record.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise _legacy_validation_error(
                f"daily record {daily_index} count must be a nonnegative integer"
            )
        cost_value = record.get("cost")
        if not _nonnegative_number(cost_value):
            raise _legacy_validation_error(
                f"daily record {daily_index} cost must be a finite nonnegative number"
            )
        daily_count_total += count
        daily_cost_total += float(cast(float | int, cost_value))
        converted_daily[day] = {
            "count": count,
            "estimated_image_output_usd": cost_value,
        }

    if daily_count_total != total_images:
        raise _legacy_validation_error(
            "daily counts do not reconcile with total_images"
        )
    if not _costs_match(float(cast(float | int, total_cost)), daily_cost_total):
        raise _legacy_validation_error("daily costs do not reconcile with total_cost")
    if frozenset(converted_daily) != frozenset(entry_daily_counts):
        raise _legacy_validation_error(
            "daily dates do not reconcile with entry timestamps"
        )
    for day, expected_count in entry_daily_counts.items():
        actual = converted_daily[day]
        if actual["count"] != expected_count:
            raise _legacy_validation_error(
                "a daily count does not reconcile with its dated entries"
            )
        if not _costs_match(
            float(cast(float | int, actual["estimated_image_output_usd"])),
            entry_daily_costs[day],
        ):
            raise _legacy_validation_error(
                "a daily cost does not reconcile with its dated entries"
            )

    return {
        "schema_version": 1,
        "total_cost": total_cost,
        "total_images": total_images,
        "entries": converted_entries,
        "daily": converted_daily,
    }


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _migration_fingerprint(raw: bytes, converted: dict[str, Any]) -> str:
    canonical = _canonical_json_bytes(converted)
    digest = hashlib.sha256()
    digest.update(MIGRATION_FINGERPRINT_DOMAIN)
    digest.update(len(raw).to_bytes(8, "big"))
    digest.update(raw)
    digest.update(len(canonical).to_bytes(8, "big"))
    digest.update(canonical)
    return digest.hexdigest()


def _migration_proposal(raw: bytes, path: Path) -> dict[str, Any]:
    legacy = _parse_ledger_bytes(raw, path)
    converted = _convert_legacy_ledger(legacy)
    if not _ledger_schema_is_valid(converted):
        raise _legacy_validation_error(
            "the converted values do not satisfy the closed active schema"
        )
    fingerprint = _migration_fingerprint(raw, converted)
    return {
        "action": "migrate-v1",
        "source_format": "banana-claude-1.4.1-unversioned",
        "target_schema_version": 1,
        "network_called": False,
        "migration_fingerprint": fingerprint,
        "summary": {
            "total_cost": converted["total_cost"],
            "total_images": converted["total_images"],
            "entry_count": len(cast(list[Any], converted["entries"])),
            "daily_record_count": len(cast(dict[str, Any], converted["daily"])),
            "legacy_prompt_fields_redacted": len(cast(list[Any], converted["entries"])),
        },
        "proposed_ledger": converted,
    }


def _bounded_descriptor_read(
    descriptor: int,
    *,
    limit: int,
    error_code: str,
    message: str,
) -> bytes:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        total = 0
        while total <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    except OSError as exc:
        raise BananaError(error_code, message) from exc
    raw = b"".join(chunks)
    if len(raw) > limit:
        raise BananaError(error_code, message)
    return raw


def _bounded_recovery_descriptor_read(descriptor: int, *, limit: int) -> bytes:
    """Read a held recovery descriptor without re-entering a failed read hook."""
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        total = 0
        while total <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    except OSError as exc:
        raise BananaError(
            "migration_recovery_failed",
            "A held cost-ledger descriptor could not be read during recovery.",
        ) from exc
    raw = b"".join(chunks)
    if len(raw) > limit:
        raise BananaError(
            "migration_recovery_failed",
            "A held cost-ledger descriptor exceeded its recovery safety limit.",
        )
    return raw


def _descriptor_entry_matches(
    directory_descriptor: int,
    name: str,
    file_descriptor: int,
) -> bool:
    try:
        path_metadata = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        descriptor_metadata = os.fstat(file_descriptor)
    except OSError:
        return False
    return (
        stat.S_ISREG(path_metadata.st_mode)
        and path_metadata.st_nlink == 1
        and descriptor_metadata.st_nlink == 1
        and path_metadata.st_dev == descriptor_metadata.st_dev
        and path_metadata.st_ino == descriptor_metadata.st_ino
    )


def _open_confirmed_source_at(
    directory_descriptor: int,
    path: Path,
) -> tuple[int, bytes]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor: int | None = None
    succeeded = False
    try:
        descriptor = os.open(path.name, flags, dir_fd=directory_descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise BananaError(
                "unsafe_legacy_cost_ledger",
                "Legacy cost ledger migration requires one regular, privately linked source file.",
            )
        if not _descriptor_entry_matches(
            directory_descriptor,
            path.name,
            descriptor,
        ):
            raise BananaError(
                "migration_source_changed",
                "The legacy cost ledger path changed while it was opened for migration.",
            )
        raw = _bounded_descriptor_read(
            descriptor,
            limit=MAX_LEDGER_BYTES,
            error_code="corrupt_cost_ledger",
            message="The legacy cost ledger could not be read within its safety limit.",
        )
        succeeded = True
        return descriptor, raw
    except OSError as exc:
        raise BananaError(
            "unsafe_legacy_cost_ledger",
            "Legacy cost ledger could not be opened without following links.",
        ) from exc
    except BananaError:
        raise
    finally:
        if descriptor is not None and not succeeded:
            os.close(descriptor)


def _open_private_child_directory_at(
    parent_descriptor: int,
    name: str,
    path: Path,
) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor: int | None = None
    created = False
    try:
        try:
            descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        except FileNotFoundError:
            os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
            created = True
            descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        os.fchmod(descriptor, 0o700)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or not _directory_path_matches_fd(path, descriptor)
        ):
            raise OSError("backup directory identity or permissions changed")
        if created:
            os.fsync(descriptor)
            os.fsync(parent_descriptor)
        return descriptor
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise BananaError(
            "migration_backup_failed",
            "The migration backup directory could not be held securely.",
        ) from exc


def _active_ledger_bytes(ledger: dict[str, Any]) -> bytes:
    return (json.dumps(ledger, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _link_held_ledger_descriptor_at(
    source_descriptor: int,
    destination_directory_descriptor: int,
    destination_name: str,
) -> None:
    if not sys.platform.startswith("linux"):
        raise BananaError(
            "migration_recovery_unavailable",
            "This platform cannot bind cost recovery publication to the held legacy inode.",
        )
    library = ctypes.CDLL(None, use_errno=True)
    try:
        operation: Any = library.linkat
    except AttributeError as exc:
        raise BananaError(
            "migration_recovery_unavailable",
            "This platform cannot bind cost recovery publication to the held legacy inode.",
        ) from exc
    operation.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    operation.restype = ctypes.c_int
    if (
        operation(
            source_descriptor,
            b"",
            destination_directory_descriptor,
            os.fsencode(destination_name),
            0x1000,
        )
        == 0
    ):
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(
            error_number,
            os.strerror(error_number),
            destination_name,
        )
    unsupported_errors = {errno.ENOSYS, errno.EINVAL, errno.EPERM}
    for attribute in ("ENOTSUP", "EOPNOTSUPP"):
        value = getattr(errno, attribute, None)
        if isinstance(value, int):
            unsupported_errors.add(value)
    if error_number in unsupported_errors:
        raise BananaError(
            "migration_recovery_unavailable",
            "The cost-ledger filesystem cannot bind recovery publication to the held legacy inode.",
        )
    raise OSError(error_number, os.strerror(error_number), destination_name)


def _observed_recovery_file(
    directory_descriptor: int,
    directory: Path,
    name: str,
    *,
    expected_identity: tuple[int, int] | None = None,
) -> dict[str, Any] | None:
    try:
        metadata = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except OSError:
        return None
    directory_bound = _directory_path_matches_fd(directory, directory_descriptor)
    identity = (metadata.st_dev, metadata.st_ino)
    return {
        "path": str(directory / name) if directory_bound else None,
        "last_known_path": str(directory / name),
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "links": metadata.st_nlink,
        "regular_file": stat.S_ISREG(metadata.st_mode),
        "path_binding_verified": directory_bound,
        "path_unknown": not directory_bound,
        "matches_intended_identity": (
            identity == expected_identity if expected_identity is not None else None
        ),
        "verify_device_and_inode": True,
    }


def _recover_interrupted_ledger_claim(
    *,
    source_directory_descriptor: int,
    source_path: Path,
    source_descriptor: int,
    backup_directory_descriptor: int,
    backup_path: Path,
    expected_raw: bytes,
) -> tuple[bool, dict[str, Any]]:
    """Publish an independent recovery copy without replacing a racer."""
    held_metadata = os.fstat(source_descriptor)
    expected_identity = (held_metadata.st_dev, held_metadata.st_ino)
    source_directory_bound = _directory_path_matches_fd(
        source_path.parent,
        source_directory_descriptor,
    )
    backup_directory_bound = _directory_path_matches_fd(
        backup_path.parent,
        backup_directory_descriptor,
    )
    backup_entry = _observed_recovery_file(
        backup_directory_descriptor,
        backup_path.parent,
        backup_path.name,
        expected_identity=expected_identity,
    )
    active_entry = _observed_recovery_file(
        source_directory_descriptor,
        source_path.parent,
        source_path.name,
        expected_identity=expected_identity,
    )
    details: dict[str, Any] = {
        "attempted": True,
        "recovery_copy_publication_attempted": False,
        "source_directory_binding_verified": source_directory_bound,
        "backup_directory_binding_verified": backup_directory_bound,
        "intended_legacy_ledger": {
            "device": held_metadata.st_dev,
            "inode": held_metadata.st_ino,
            "last_observed_link_count": held_metadata.st_nlink,
            "verify_device_and_inode": True,
        },
        "observed_active_entry": active_entry,
        "observed_backup_entry": backup_entry,
        "restored": False,
    }
    try:
        held_raw = _bounded_recovery_descriptor_read(
            source_descriptor,
            limit=MAX_LEDGER_BYTES,
        )
    except BaseException as recovery_error:
        details.update(
            {
                "held_bytes_verified": False,
                "cleanup_status": "recovery_bytes_inspection_failed",
                "recovery_exception_type": type(recovery_error).__name__,
            }
        )
        return False, details
    held_bytes_verified = held_raw == expected_raw
    details["held_bytes_verified"] = held_bytes_verified
    try:
        if os.name != "nt":
            os.fchmod(source_descriptor, 0o600)
        held_metadata = os.fstat(source_descriptor)
    except OSError as recovery_error:
        details.update(
            {
                "cleanup_status": "retained_backup_permissions_unverified",
                "recovery_exception_type": type(recovery_error).__name__,
            }
        )
        return False, details
    backup_private = bool(
        os.name == "nt" or stat.S_IMODE(held_metadata.st_mode) == 0o600
    )
    source_directory_bound = _directory_path_matches_fd(
        source_path.parent,
        source_directory_descriptor,
    )
    backup_directory_bound = _directory_path_matches_fd(
        backup_path.parent,
        backup_directory_descriptor,
    )
    backup_entry = _observed_recovery_file(
        backup_directory_descriptor,
        backup_path.parent,
        backup_path.name,
        expected_identity=expected_identity,
    )
    active_entry = _observed_recovery_file(
        source_directory_descriptor,
        source_path.parent,
        source_path.name,
        expected_identity=expected_identity,
    )
    details.update(
        {
            "source_directory_binding_verified": source_directory_bound,
            "backup_directory_binding_verified": backup_directory_bound,
            "observed_active_entry": active_entry,
            "observed_backup_entry": backup_entry,
        }
    )
    details["retained_backup_private_mode_verified"] = backup_private
    backup_exact = bool(
        backup_entry is not None
        and backup_entry["regular_file"] is True
        and backup_entry["matches_intended_identity"] is True
        and backup_directory_bound
        and held_bytes_verified
        and held_metadata.st_nlink == 1
        and backup_private
    )
    details["retained_backup_identity_verified"] = backup_exact
    if active_entry is not None:
        active_exact, active_details = _exact_cost_publication(
            source_directory_descriptor=source_directory_descriptor,
            source_path=source_path,
            expected_raw=expected_raw,
            disallowed_identity=expected_identity,
        )
        details["active_recovered_legacy_publication"] = active_details
        details["active_entry_exact_recovered_legacy"] = active_exact
        if active_exact:
            restored = bool(active_exact and backup_exact)
            details.update(
                {
                    "restored": restored,
                    "backup_retained": backup_exact,
                    "cleanup_status": (
                        "exact_independent_active_copy_and_backup_inode_retained"
                        if restored
                        else "active_copy_exact_backup_identity_unverified"
                    ),
                }
            )
            return restored, details
        details["cleanup_status"] = "active_entry_present_no_overwrite"
        return False, details
    if (
        not source_directory_bound
        or not backup_exact
        or not stat.S_ISREG(held_metadata.st_mode)
        or held_metadata.st_nlink != 1
    ):
        details["cleanup_status"] = "retained_backup_could_not_be_restored_safely"
        return False, details
    publication_error: BaseException | None = None
    try:
        details["recovery_copy_publication_attempted"] = True
        _atomic_write_at(
            source_directory_descriptor,
            source_path.name,
            expected_raw,
            replace=False,
            expected_directory=source_path.parent,
        )
    except BaseException as recovery_error:
        publication_error = recovery_error

    active_exact, active_details = _exact_cost_publication(
        source_directory_descriptor=source_directory_descriptor,
        source_path=source_path,
        expected_raw=expected_raw,
        disallowed_identity=expected_identity,
    )
    try:
        current_active = _observed_recovery_file(
            source_directory_descriptor,
            source_path.parent,
            source_path.name,
            expected_identity=expected_identity,
        )
        retained_backup = _observed_recovery_file(
            backup_directory_descriptor,
            backup_path.parent,
            backup_path.name,
            expected_identity=expected_identity,
        )
        retained_raw = _bounded_recovery_descriptor_read(
            source_descriptor,
            limit=MAX_LEDGER_BYTES,
        )
        retained_metadata = os.fstat(source_descriptor)
        backup_still_exact = bool(
            retained_backup is not None
            and retained_backup["matches_intended_identity"] is True
            and retained_backup["regular_file"] is True
            and retained_metadata.st_nlink == 1
            and retained_raw == expected_raw
            and (os.name == "nt" or stat.S_IMODE(retained_metadata.st_mode) == 0o600)
            and _directory_path_matches_fd(
                backup_path.parent,
                backup_directory_descriptor,
            )
        )
        restored = bool(active_exact and backup_still_exact)
        details.update(
            {
                "restored": restored,
                "active_recovered_legacy_publication": active_details,
                "active_entry_exact_recovered_legacy": active_exact,
                "observed_active_entry": current_active,
                "observed_backup_entry": retained_backup,
                "retained_backup_identity_verified": backup_still_exact,
                "cleanup_status": (
                    "exact_independent_active_copy_and_backup_inode_retained"
                    if restored
                    else (
                        "active_entry_present_no_overwrite"
                        if current_active is not None
                        else "recovery_copy_verification_failed"
                    )
                ),
            }
        )
        if publication_error is not None:
            details["recovery_publication_exception_type"] = type(
                publication_error
            ).__name__
        if restored:
            os.fsync(source_directory_descriptor)
            os.fsync(backup_directory_descriptor)
        return restored, details
    except BaseException as recovery_error:
        details["cleanup_status"] = "recovery_copy_failed_backup_retained"
        details["recovery_error"] = (
            recovery_error.as_dict()
            if isinstance(recovery_error, BananaError)
            else {
                "error": "migration_recovery_failed",
                "message": "The exact legacy ledger recovery copy could not be verified safely.",
                "exception_type": type(recovery_error).__name__,
            }
        )
        return False, details


def _exact_cost_publication(
    *,
    source_directory_descriptor: int,
    source_path: Path,
    expected_raw: bytes,
    disallowed_identity: tuple[int, int] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Verify one exact private single-link ledger through its held parent."""
    details: dict[str, Any] = {
        "expected_bytes_verified": False,
        "path_binding_verified": False,
    }
    if not _directory_path_matches_fd(
        source_path.parent,
        source_directory_descriptor,
    ):
        details["inspection_status"] = "source_directory_unbound"
        return False, details
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor: int | None = None
    try:
        descriptor = os.open(
            source_path.name,
            flags,
            dir_fd=source_directory_descriptor,
        )
        metadata = os.fstat(descriptor)
        raw = _bounded_recovery_descriptor_read(
            descriptor,
            limit=MAX_LEDGER_BYTES,
        )
        path_bound = _descriptor_entry_matches(
            source_directory_descriptor,
            source_path.name,
            descriptor,
        )
        identity = (metadata.st_dev, metadata.st_ino)
        distinct_identity = bool(
            disallowed_identity is None or identity != disallowed_identity
        )
        exact = bool(
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_nlink == 1
            and (os.name == "nt" or stat.S_IMODE(metadata.st_mode) == 0o600)
            and raw == expected_raw
            and path_bound
            and distinct_identity
        )
        details.update(
            {
                "device": metadata.st_dev,
                "inode": metadata.st_ino,
                "links": metadata.st_nlink,
                "regular_file": stat.S_ISREG(metadata.st_mode),
                "private_mode_verified": bool(
                    os.name == "nt" or stat.S_IMODE(metadata.st_mode) == 0o600
                ),
                "expected_bytes_verified": raw == expected_raw,
                "path_binding_verified": path_bound,
                "independent_inode_verified": distinct_identity,
                "inspection_status": "exact" if exact else "mismatch",
            }
        )
        return exact, details
    except FileNotFoundError:
        details["inspection_status"] = "absent"
        return False, details
    except BaseException as inspection_error:
        details.update(
            {
                "inspection_status": "inspection_failed",
                "inspection_exception_type": type(inspection_error).__name__,
            }
        )
        return False, details
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _recover_interrupted_cost_migration(
    *,
    source_directory_descriptor: int,
    source_path: Path,
    source_descriptor: int,
    backup_directory_descriptor: int,
    backup_path: Path,
    expected_legacy_raw: bytes,
    expected_migrated_raw: bytes,
    publication_attempted: bool,
    publication_succeeded: bool,
) -> tuple[bool, dict[str, Any]]:
    restored, details = _recover_interrupted_ledger_claim(
        source_directory_descriptor=source_directory_descriptor,
        source_path=source_path,
        source_descriptor=source_descriptor,
        backup_directory_descriptor=backup_directory_descriptor,
        backup_path=backup_path,
        expected_raw=expected_legacy_raw,
    )
    held_metadata = os.fstat(source_descriptor)
    active_exact, active_details = _exact_cost_publication(
        source_directory_descriptor=source_directory_descriptor,
        source_path=source_path,
        expected_raw=expected_migrated_raw,
        disallowed_identity=(held_metadata.st_dev, held_metadata.st_ino),
    )
    backup_verified = bool(
        details.get("retained_backup_identity_verified") is True
        and details.get("held_bytes_verified") is True
        and details.get("backup_directory_binding_verified") is True
    )
    migrated_safe = bool(active_exact and backup_verified)
    details.update(
        {
            "publication_attempted": publication_attempted,
            "publication_succeeded": publication_succeeded,
            "active_migrated_publication": active_details,
            "active_entry_exact_migrated_publication": active_exact,
            "migration_state_safe": restored or migrated_safe,
        }
    )
    if migrated_safe:
        details["cleanup_status"] = "exact_migrated_active_and_legacy_backup_retained"
    return restored or migrated_safe, details


def _retain_substituted_ledger_source(
    *,
    source_descriptor: int,
    raw: bytes,
    fingerprint: str,
    backup_directory_descriptor: int,
    backup_directory: Path,
) -> dict[str, Any]:
    """Retain exact reviewed ledger bytes after a source-name substitution."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = os.urandom(8).hex()
    held_metadata = os.fstat(source_descriptor)
    intended_identity = (held_metadata.st_dev, held_metadata.st_ino)
    recovery_entries: list[dict[str, Any]] = []
    link_name = f"costs.intended-recovery-{timestamp}-{fingerprint[:12]}-{suffix}.json"
    link_error: BananaError | None = None
    try:
        _link_held_ledger_descriptor_at(
            source_descriptor,
            backup_directory_descriptor,
            link_name,
        )
        linked = _observed_recovery_file(
            backup_directory_descriptor,
            backup_directory,
            link_name,
            expected_identity=intended_identity,
        )
        current_held = os.fstat(source_descriptor)
        if (
            linked is None
            or linked["regular_file"] is not True
            or linked["matches_intended_identity"] is not True
            or (current_held.st_dev, current_held.st_ino) != intended_identity
            or current_held.st_nlink < 1
        ):
            raise BananaError(
                "migration_backup_failed",
                "The intended legacy ledger recovery link could not be verified.",
            )
        os.fsync(backup_directory_descriptor)
        linked["method"] = "held_inode_link"
        linked["exact_reviewed_bytes"] = True
        recovery_entries.append(linked)
        return {
            "retained": True,
            "method": "held_inode_link",
            "recovery_entries": recovery_entries,
        }
    except BananaError as exc:
        link_error = exc
    except OSError:
        link_error = BananaError(
            "migration_backup_failed",
            "The intended legacy ledger inode could not be linked into private recovery.",
        )
    observed_link = _observed_recovery_file(
        backup_directory_descriptor,
        backup_directory,
        link_name,
        expected_identity=intended_identity,
    )
    if observed_link is not None:
        observed_link["method"] = "observed_link_after_error"
        observed_link["exact_reviewed_bytes"] = bool(
            observed_link["matches_intended_identity"] is True
        )
        recovery_entries.append(observed_link)

    copy_name = f"costs.intended-copy-{timestamp}-{fingerprint[:12]}-{suffix}.json"
    copy_descriptor: int | None = None
    try:
        copy_identity = _atomic_write_at(
            backup_directory_descriptor,
            copy_name,
            raw,
            replace=False,
            expected_directory=backup_directory,
        )
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        copy_descriptor = os.open(
            copy_name,
            flags,
            dir_fd=backup_directory_descriptor,
        )
        copy_metadata = os.fstat(copy_descriptor)
        copy_raw = _bounded_descriptor_read(
            copy_descriptor,
            limit=MAX_LEDGER_BYTES,
            error_code="migration_backup_failed",
            message="The reviewed legacy ledger recovery copy could not be read safely.",
        )
        if (
            not stat.S_ISREG(copy_metadata.st_mode)
            or copy_metadata.st_nlink != 1
            or (copy_metadata.st_dev, copy_metadata.st_ino) != copy_identity
            or stat.S_IMODE(copy_metadata.st_mode) != 0o600
            or copy_raw != raw
            or not _descriptor_entry_matches(
                backup_directory_descriptor,
                copy_name,
                copy_descriptor,
            )
        ):
            raise BananaError(
                "migration_backup_failed",
                "The reviewed legacy ledger recovery copy could not be verified.",
            )
        os.fsync(copy_descriptor)
        os.fsync(backup_directory_descriptor)
        copied = _observed_recovery_file(
            backup_directory_descriptor,
            backup_directory,
            copy_name,
            expected_identity=copy_identity,
        )
        if copied is None:
            raise BananaError(
                "migration_backup_failed",
                "The reviewed legacy ledger recovery copy became unobservable.",
            )
        copied.update(
            {
                "method": "exact_reviewed_bytes_copy",
                "exact_reviewed_bytes": True,
            }
        )
        recovery_entries.append(copied)
        return {
            "retained": True,
            "method": "exact_reviewed_bytes_copy",
            "recovery_entries": recovery_entries,
            "held_inode_link_error": (
                link_error.as_dict() if link_error is not None else None
            ),
        }
    except (BananaError, OSError) as exc:
        normalized = (
            exc
            if isinstance(exc, BananaError)
            else BananaError(
                "migration_backup_failed",
                "The reviewed legacy ledger bytes could not be copied into private recovery.",
            )
        )
        return {
            "retained": any(
                entry.get("exact_reviewed_bytes") is True for entry in recovery_entries
            ),
            "method": "partial_or_unavailable",
            "recovery_entries": recovery_entries,
            "held_inode_link_error": (
                link_error.as_dict() if link_error is not None else None
            ),
            "copy_error": normalized.as_dict(),
        }
    finally:
        if copy_descriptor is not None:
            os.close(copy_descriptor)


def _migrate_confirmed_with_descriptors(
    path: Path,
    confirmation: str,
    *,
    state_directory_descriptor: int | None,
    lock_descriptor: int,
) -> tuple[Path, dict[str, Any], str]:
    try:
        source_directory_descriptor = _open_secure_directory(path.parent)
    except BananaError as exc:
        raise BananaError(
            "migration_source_directory_changed",
            "The legacy ledger directory could not be opened without following redirects.",
        ) from exc
    if source_directory_descriptor is None:
        raise BananaError(
            "migration_descriptor_support_required",
            "Legacy ledger migration requires descriptor-relative directory operations on this host.",
        )

    source_descriptor: int | None = None
    backup_directory_descriptor: int | None = None
    backup_descriptor: int | None = None
    claimed = False
    completed = False
    publication_attempted = False
    publication_succeeded = False
    intended_recovery: dict[str, Any] | None = None
    backup_name = ""
    backup_path: Path | None = None
    expected_legacy_raw: bytes | None = None
    expected_migrated_raw: bytes | None = None
    try:
        _require_cost_lock_binding(
            state_directory_descriptor,
            banana_home() / "costs.lock",
            lock_descriptor,
        )
        if not _directory_path_matches_fd(path.parent, source_directory_descriptor):
            raise BananaError(
                "migration_source_directory_changed",
                "The legacy ledger directory changed before migration started.",
            )
        source_descriptor, raw = _open_confirmed_source_at(
            source_directory_descriptor,
            path,
        )
        proposal = _migration_proposal(raw, path)
        expected_legacy_raw = raw
        expected_migrated_raw = _active_ledger_bytes(
            cast(dict[str, Any], proposal["proposed_ledger"])
        )
        fingerprint = cast(str, proposal["migration_fingerprint"])
        if not hmac.compare_digest(confirmation, fingerprint):
            raise BananaError(
                "migration_confirmation_mismatch",
                "Migration confirmation does not match the current legacy ledger and exact proposal. Run migrate-v1 --dry-run again.",
            )

        backup_directory = path.parent / "backups"
        if not _directory_path_matches_fd(
            path.parent,
            source_directory_descriptor,
        ):
            raise BananaError(
                "migration_source_directory_changed",
                "The legacy ledger directory changed before backup setup.",
            )
        backup_directory_descriptor = _open_private_child_directory_at(
            source_directory_descriptor,
            "backups",
            backup_directory,
        )
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_name = (
            f"costs.v1-{timestamp}-{fingerprint[:12]}-{os.urandom(8).hex()}.json"
        )
        backup_path = backup_directory / backup_name

        source_metadata = os.fstat(source_descriptor)
        if source_metadata.st_nlink != 1 or not _descriptor_entry_matches(
            source_directory_descriptor,
            path.name,
            source_descriptor,
        ):
            raise BananaError(
                "migration_source_changed",
                "The legacy cost ledger changed before it could be claimed.",
            )
        revalidated_raw = _bounded_descriptor_read(
            source_descriptor,
            limit=MAX_LEDGER_BYTES,
            error_code="migration_source_changed",
            message="The legacy cost ledger changed during confirmation.",
        )
        revalidated_proposal = _migration_proposal(revalidated_raw, path)
        if revalidated_raw != raw or not hmac.compare_digest(
            cast(str, revalidated_proposal["migration_fingerprint"]),
            fingerprint,
        ):
            raise BananaError(
                "migration_source_changed",
                "The legacy cost ledger changed during confirmation.",
            )
        if not _directory_path_matches_fd(
            path.parent,
            source_directory_descriptor,
        ):
            raise BananaError(
                "migration_source_directory_changed",
                "The legacy ledger directory changed before backup claim.",
            )
        if not _directory_path_matches_fd(
            backup_directory,
            backup_directory_descriptor,
        ):
            raise BananaError(
                "migration_backup_directory_changed",
                "The migration backup directory changed before backup claim.",
            )

        _require_cost_lock_binding(
            state_directory_descriptor,
            banana_home() / "costs.lock",
            lock_descriptor,
        )
        try:
            _exclusive_rename_at(
                source_directory_descriptor,
                path.name,
                backup_directory_descriptor,
                backup_name,
            )
        except BaseException as exc:
            if isinstance(exc, Exception):
                raise
            backup_entry_exact = _descriptor_entry_matches(
                backup_directory_descriptor,
                backup_name,
                source_descriptor,
            )
            active_entry_exact = _descriptor_entry_matches(
                source_directory_descriptor,
                path.name,
                source_descriptor,
            )
            if backup_entry_exact and not active_entry_exact:
                restored, recovery = _recover_interrupted_ledger_claim(
                    source_directory_descriptor=source_directory_descriptor,
                    source_path=path,
                    source_descriptor=source_descriptor,
                    backup_directory_descriptor=backup_directory_descriptor,
                    backup_path=backup_path,
                    expected_raw=raw,
                )
                if restored:
                    raise
                raise BananaError(
                    "migration_recovery_failed",
                    "The interrupted cost-ledger claim could not be restored automatically. The exact retained legacy identity is recorded for recovery.",
                    details={
                        "recovery_required": True,
                        "migration_recovery": recovery,
                    },
                ) from exc
            raise
        claimed = True

        source_metadata = os.fstat(source_descriptor)
        if not stat.S_ISREG(source_metadata.st_mode) or source_metadata.st_nlink != 1:
            intended_recovery = _retain_substituted_ledger_source(
                source_descriptor=source_descriptor,
                raw=raw,
                fingerprint=fingerprint,
                backup_directory_descriptor=backup_directory_descriptor,
                backup_directory=backup_directory,
            )
            raise BananaError(
                "migration_source_changed",
                "The claimed legacy ledger is not one regular file.",
            )
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        backup_descriptor = os.open(
            backup_name,
            flags,
            dir_fd=backup_directory_descriptor,
        )
        backup_metadata = os.fstat(backup_descriptor)
        if (
            not stat.S_ISREG(backup_metadata.st_mode)
            or backup_metadata.st_nlink != 1
            or backup_metadata.st_dev != source_metadata.st_dev
            or backup_metadata.st_ino != source_metadata.st_ino
        ):
            intended_recovery = _retain_substituted_ledger_source(
                source_descriptor=source_descriptor,
                raw=raw,
                fingerprint=fingerprint,
                backup_directory_descriptor=backup_directory_descriptor,
                backup_directory=backup_directory,
            )
            raise BananaError(
                "migration_source_changed",
                "The claimed legacy ledger backup identity did not match its source.",
            )
        os.fchmod(backup_descriptor, 0o600)
        backup_metadata = os.fstat(backup_descriptor)
        if (
            backup_metadata.st_nlink != 1
            or stat.S_IMODE(backup_metadata.st_mode) != 0o600
        ):
            raise BananaError(
                "migration_backup_failed",
                "The private legacy ledger backup permissions could not be verified.",
            )
        claimed_raw = _bounded_descriptor_read(
            backup_descriptor,
            limit=MAX_LEDGER_BYTES,
            error_code="migration_source_changed",
            message="The claimed legacy ledger backup could not be reread safely.",
        )
        claimed_proposal = _migration_proposal(claimed_raw, backup_path)
        if (
            claimed_raw != raw
            or not _descriptor_entry_matches(
                backup_directory_descriptor,
                backup_name,
                backup_descriptor,
            )
            or not hmac.compare_digest(
                cast(str, claimed_proposal["migration_fingerprint"]),
                fingerprint,
            )
        ):
            raise BananaError(
                "migration_source_changed",
                "The claimed legacy ledger backup failed exact revalidation.",
            )
        os.fsync(backup_descriptor)
        os.fsync(backup_directory_descriptor)

        if not _directory_path_matches_fd(
            path.parent,
            source_directory_descriptor,
        ):
            raise BananaError(
                "migration_source_directory_changed",
                "The legacy ledger directory changed after backup claim.",
            )
        if not _directory_path_matches_fd(
            backup_directory,
            backup_directory_descriptor,
        ):
            raise BananaError(
                "migration_backup_directory_changed",
                "The migration backup directory changed after backup claim.",
            )

        converted = cast(dict[str, Any], proposal["proposed_ledger"])
        _require_cost_lock_binding(
            state_directory_descriptor,
            banana_home() / "costs.lock",
            lock_descriptor,
        )
        publication_attempted = True
        try:
            _atomic_write_at(
                source_directory_descriptor,
                path.name,
                _active_ledger_bytes(converted),
                replace=False,
                expected_directory=path.parent,
            )
        except BananaError as exc:
            if exc.code == "output_exists":
                retained_details = (
                    {"retained_source": str(backup_path)}
                    if _directory_path_matches_fd(
                        backup_directory,
                        backup_directory_descriptor,
                    )
                    else None
                )
                raise BananaError(
                    "migration_source_changed",
                    "The legacy cost ledger path was recreated during migration. The competing active bytes and exact backup were preserved.",
                    details=retained_details,
                ) from exc
            if exc.code == "output_directory_changed":
                raise BananaError(
                    "migration_source_directory_changed",
                    "The legacy ledger directory changed during active publication.",
                ) from exc
            raise
        publication_succeeded = True

        active_flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            active_flags |= os.O_NOFOLLOW
        active_descriptor = os.open(
            path.name,
            active_flags,
            dir_fd=source_directory_descriptor,
        )
        try:
            active_metadata = os.fstat(active_descriptor)
            active_raw = _bounded_descriptor_read(
                active_descriptor,
                limit=MAX_LEDGER_BYTES,
                error_code="migration_publication_failed",
                message="The migrated ledger could not be revalidated after publication.",
            )
            if (
                not stat.S_ISREG(active_metadata.st_mode)
                or active_metadata.st_nlink != 1
                or (os.name != "nt" and stat.S_IMODE(active_metadata.st_mode) != 0o600)
                or active_raw != _active_ledger_bytes(converted)
                or not _descriptor_entry_matches(
                    source_directory_descriptor,
                    path.name,
                    active_descriptor,
                )
            ):
                raise BananaError(
                    "migration_publication_failed",
                    "The migrated ledger failed final active-file verification.",
                )
        finally:
            os.close(active_descriptor)

        final_backup_raw = _bounded_descriptor_read(
            backup_descriptor,
            limit=MAX_LEDGER_BYTES,
            error_code="migration_backup_failed",
            message="The private legacy ledger backup failed final verification.",
        )
        if (
            final_backup_raw != raw
            or (
                os.name != "nt"
                and stat.S_IMODE(os.fstat(backup_descriptor).st_mode) != 0o600
            )
            or not _descriptor_entry_matches(
                backup_directory_descriptor,
                backup_name,
                backup_descriptor,
            )
            or not _directory_path_matches_fd(
                path.parent,
                source_directory_descriptor,
            )
            or not _directory_path_matches_fd(
                backup_directory,
                backup_directory_descriptor,
            )
        ):
            raise BananaError(
                "migration_directory_changed",
                "A migration directory changed before final identity verification.",
            )
        _require_cost_lock_binding(
            state_directory_descriptor,
            banana_home() / "costs.lock",
            lock_descriptor,
        )
        completed = True
        return backup_path, proposal, fingerprint
    except OSError as exc:
        raise BananaError(
            "migration_io_failed",
            "Descriptor-bound legacy ledger migration failed safely.",
        ) from exc
    except BaseException as exc:
        if isinstance(exc, Exception):
            raise
        if (
            claimed
            and not completed
            and source_descriptor is not None
            and backup_directory_descriptor is not None
            and backup_path is not None
            and expected_legacy_raw is not None
            and expected_migrated_raw is not None
        ):
            safe, recovery = _recover_interrupted_cost_migration(
                source_directory_descriptor=source_directory_descriptor,
                source_path=path,
                source_descriptor=source_descriptor,
                backup_directory_descriptor=backup_directory_descriptor,
                backup_path=backup_path,
                expected_legacy_raw=expected_legacy_raw,
                expected_migrated_raw=expected_migrated_raw,
                publication_attempted=publication_attempted,
                publication_succeeded=publication_succeeded,
            )
            if safe:
                raise
            raise BananaError(
                "migration_recovery_failed",
                "The interrupted cost-ledger migration could not prove an exact active ledger or restore the exact retained legacy ledger safely.",
                details={
                    "recovery_required": True,
                    "interrupted_exception_type": type(exc).__name__,
                    "migration_recovery": recovery,
                    "intended_recovery": intended_recovery,
                },
            ) from exc
        raise
    finally:
        active_error = sys.exc_info()[1]
        if (
            claimed
            and not completed
            and isinstance(active_error, BananaError)
            and source_descriptor is not None
            and backup_directory_descriptor is not None
            and backup_path is not None
        ):
            intended_metadata = os.fstat(source_descriptor)
            intended_identity: dict[str, Any] = {
                "device": intended_metadata.st_dev,
                "inode": intended_metadata.st_ino,
                "verify_device_and_inode": True,
            }
            backup_directory_bound = _directory_path_matches_fd(
                backup_path.parent,
                backup_directory_descriptor,
            )
            source_directory_bound = _directory_path_matches_fd(
                path.parent,
                source_directory_descriptor,
            )
            intended_backup_bound = (
                backup_directory_bound
                and _descriptor_entry_matches(
                    backup_directory_descriptor,
                    backup_name,
                    source_descriptor,
                )
            )
            intended_active_bound = (
                source_directory_bound
                and _descriptor_entry_matches(
                    source_directory_descriptor,
                    path.name,
                    source_descriptor,
                )
            )
            if intended_backup_bound:
                intended_identity.update(
                    {
                        "path": str(backup_path),
                        "path_binding_verified": True,
                    }
                )
            elif intended_active_bound:
                intended_identity.update(
                    {
                        "path": str(path),
                        "path_binding_verified": True,
                    }
                )
            else:
                intended_identity.update(
                    {
                        "path": None,
                        "last_known_path": str(backup_path),
                        "path_binding_verified": False,
                        "path_unknown": True,
                        "last_observed_link_count": intended_metadata.st_nlink,
                    }
                )

            def observed_entry(
                directory_descriptor: int,
                name: str,
                entry_path: Path,
                directory_bound: bool,
            ) -> dict[str, Any] | None:
                try:
                    metadata = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                except OSError:
                    return None
                return {
                    "path": str(entry_path) if directory_bound else None,
                    "last_known_path": str(entry_path),
                    "device": metadata.st_dev,
                    "inode": metadata.st_ino,
                    "mode": stat.S_IFMT(metadata.st_mode),
                    "links": metadata.st_nlink,
                    "path_binding_verified": directory_bound,
                    "verify_device_and_inode": True,
                }

            active_error.details.update(
                {
                    "recovery_required": True,
                    "migration_cleanup_complete": False,
                    "migration_automatic_restore_attempted": False,
                    "intended_legacy_ledger": intended_identity,
                    "observed_active_entry": observed_entry(
                        source_directory_descriptor,
                        path.name,
                        path,
                        source_directory_bound,
                    ),
                    "observed_backup_entry": observed_entry(
                        backup_directory_descriptor,
                        backup_name,
                        backup_path,
                        backup_directory_bound,
                    ),
                    "intended_recovery": intended_recovery,
                }
            )
        if backup_descriptor is not None:
            os.close(backup_descriptor)
        if source_descriptor is not None:
            os.close(source_descriptor)
        if backup_directory_descriptor is not None:
            os.close(backup_directory_descriptor)
        os.close(source_directory_descriptor)


def _attempt_entries(
    ledger: dict[str, Any],
    attempt_sha256: str,
) -> list[dict[str, Any]]:
    return [
        cast(dict[str, Any], candidate)
        for candidate in cast(list[Any], ledger["entries"])
        if type(candidate) is dict and candidate.get("attempt_sha256") == attempt_sha256
    ]


def _attempt_entry_matches(
    entry: dict[str, Any],
    *,
    model: str,
    resolution: str,
    count: int,
    cost: float,
    unit_cost: float,
    batch: bool,
    label: str,
    interaction_id_sha256: str | None,
) -> bool:
    observed_cost = entry.get("estimated_image_output_usd")
    observed_unit_cost = entry.get("image_output_rate_usd")
    interaction_matches = (
        "interaction_id_sha256" not in entry
        if interaction_id_sha256 is None
        else entry.get("interaction_id_sha256") == interaction_id_sha256
    )
    return bool(
        entry.get("model") == model
        and entry.get("resolution") == resolution
        and type(entry.get("count")) is int
        and entry.get("count") == count
        and _nonnegative_number(observed_cost)
        and float(cast(int | float, observed_cost)) == cost
        and _nonnegative_number(observed_unit_cost)
        and float(cast(int | float, observed_unit_cost)) == unit_cost
        and type(entry.get("batch")) is bool
        and entry.get("batch") is batch
        and entry.get("label") == label
        and interaction_matches
    )


def _recorded_result(
    ledger: dict[str, Any],
    entry: dict[str, Any],
    *,
    attempt_sha256: str | None,
    idempotent_replay: bool,
    reconciled_after_save_error: bool,
) -> dict[str, Any]:
    public_entry = {
        key: value for key, value in entry.items() if key != "interaction_id_sha256"
    }
    result: dict[str, Any] = {
        "status": "recorded",
        "logged": True,
        "idempotent_replay": idempotent_replay,
        "reconciled_after_save_error": reconciled_after_save_error,
        "entry": public_entry,
        "estimated_image_output_usd": entry["estimated_image_output_usd"],
        "image_output_rate_usd": entry["image_output_rate_usd"],
        "estimate_basis": "recorded_image_outputs",
        "estimate_is_invoice_cap": False,
        "total_cost": ledger["total_cost"],
        "total_images": ledger["total_images"],
    }
    if attempt_sha256 is not None:
        result["attempt_sha256"] = attempt_sha256
    return result


def _safe_recording_error(error: BaseException) -> dict[str, Any]:
    if isinstance(error, BananaError):
        return {"error": error.code, "message": error.message}
    return {
        "error": "cost_ledger_save_failed",
        "exception_type": type(error).__name__,
    }


def _raise_attempt_reconciliation_error(
    *,
    status: str,
    attempt_sha256: str,
    reason: str,
    save_error: BaseException | None = None,
    reconciliation_error: BaseException | None = None,
) -> NoReturn:
    details: dict[str, Any] = {
        "status": status,
        "attempt_sha256": attempt_sha256,
        "reason": reason,
    }
    if save_error is not None:
        details["save_error"] = _safe_recording_error(save_error)
    if reconciliation_error is not None:
        details["reconciliation_error"] = _safe_recording_error(reconciliation_error)
    if status == "not_recorded":
        raise BananaError(
            "cost_recording_not_recorded",
            "The cost attempt is conclusively absent from the locked ledger.",
            details=details,
        ) from save_error
    raise BananaError(
        "cost_recording_unknown_requires_reconciliation",
        "The cost attempt could not be reconciled to one exact ledger entry.",
        details=details,
    ) from save_error


def reconcile_generation_attempt(
    *,
    model: str,
    resolution: str,
    count: int = 1,
    label: str = "image generation",
    batch: bool = False,
    interaction_id: str | None = None,
    attempt_sha256: str,
) -> dict[str, Any]:
    """Classify one prior cost attempt without creating a ledger entry."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise BananaError("invalid_count", "Count must be positive.")
    if type(label) is not str:
        raise BananaError("invalid_cost_label", "Cost label must be a string.")
    checked_label = validate_approval_text(
        label.strip()[:MAX_LEDGER_LABEL_CHARS] or "image generation",
        field="Cost label",
        max_length=MAX_LEDGER_LABEL_CHARS,
        error_code="invalid_cost_label",
    )
    interaction_id_sha256: str | None = None
    if interaction_id not in (None, ""):
        checked_interaction_id = validate_approval_text(
            interaction_id,
            field="Interaction ID",
            max_length=MAX_LEDGER_INTERACTION_ID_CHARS,
            error_code="invalid_interaction_id",
        )
        interaction_id_sha256 = hashlib.sha256(
            checked_interaction_id.encode("utf-8")
        ).hexdigest()
    if not _valid_sha256_digest(attempt_sha256):
        raise BananaError(
            "invalid_cost_attempt_digest",
            "Cost attempt digest must be one full lowercase SHA-256 digest.",
        )
    selected, info = get_model(model)
    normalized = normalize_image_size(resolution, info)
    normalized_batch = bool(batch)
    unit_cost = estimate_image_cost(selected, normalized, batch=normalized_batch)
    entry_cost = round(unit_cost * count, 4)

    try:
        with ledger_lock() as (directory_descriptor, lock_descriptor):
            ledger = load_ledger(
                directory_descriptor,
                lock_descriptor=lock_descriptor,
                rewrite_raw_interaction_ids=False,
            )
            matching_attempts = _attempt_entries(ledger, attempt_sha256)
            if not matching_attempts:
                _raise_attempt_reconciliation_error(
                    status="not_recorded",
                    attempt_sha256=attempt_sha256,
                    reason="attempt_digest_conclusively_absent",
                )
            if len(matching_attempts) == 1 and _attempt_entry_matches(
                matching_attempts[0],
                model=selected,
                resolution=normalized,
                count=count,
                cost=entry_cost,
                unit_cost=unit_cost,
                batch=normalized_batch,
                label=checked_label,
                interaction_id_sha256=interaction_id_sha256,
            ):
                return _recorded_result(
                    ledger,
                    matching_attempts[0],
                    attempt_sha256=attempt_sha256,
                    idempotent_replay=True,
                    reconciled_after_save_error=False,
                )
            _raise_attempt_reconciliation_error(
                status="unknown_requires_reconciliation",
                attempt_sha256=attempt_sha256,
                reason="attempt_digest_not_unique_or_payload_mismatch",
            )
    except BananaError as reconciliation_error:
        if reconciliation_error.code in {
            "cost_recording_not_recorded",
            "cost_recording_unknown_requires_reconciliation",
        }:
            raise
        _raise_attempt_reconciliation_error(
            status="unknown_requires_reconciliation",
            attempt_sha256=attempt_sha256,
            reason="ledger_could_not_be_read_safely",
            reconciliation_error=reconciliation_error,
        )
    except BaseException as reconciliation_error:
        _raise_attempt_reconciliation_error(
            status="unknown_requires_reconciliation",
            attempt_sha256=attempt_sha256,
            reason="ledger_could_not_be_read_safely",
            reconciliation_error=reconciliation_error,
        )


def record_generation(
    *,
    model: str,
    resolution: str,
    count: int = 1,
    label: str = "image generation",
    batch: bool = False,
    interaction_id: str | None = None,
    attempt_sha256: str | None = None,
) -> dict[str, Any]:
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise BananaError("invalid_count", "Count must be positive.")
    if type(label) is not str:
        raise BananaError("invalid_cost_label", "Cost label must be a string.")
    label_candidate = label.strip()[:MAX_LEDGER_LABEL_CHARS] or "image generation"
    checked_label = validate_approval_text(
        label_candidate,
        field="Cost label",
        max_length=MAX_LEDGER_LABEL_CHARS,
        error_code="invalid_cost_label",
    )
    interaction_id_sha256: str | None = None
    if interaction_id not in (None, ""):
        checked_interaction_id = validate_approval_text(
            interaction_id,
            field="Interaction ID",
            max_length=MAX_LEDGER_INTERACTION_ID_CHARS,
            error_code="invalid_interaction_id",
        )
        interaction_id_sha256 = hashlib.sha256(
            checked_interaction_id.encode("utf-8")
        ).hexdigest()
    if attempt_sha256 is not None and not _valid_sha256_digest(attempt_sha256):
        raise BananaError(
            "invalid_cost_attempt_digest",
            "Cost attempt digest must be one full lowercase SHA-256 digest.",
        )
    selected, info = get_model(model)
    normalized = normalize_image_size(resolution, info)
    unit_cost = estimate_image_cost(selected, normalized, batch=batch)
    entry_cost = round(unit_cost * count, 4)
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    entry = {
        "ts": now.isoformat(timespec="seconds"),
        "model": selected,
        "resolution": normalized,
        "count": count,
        "estimated_image_output_usd": entry_cost,
        "image_output_rate_usd": unit_cost,
        "estimate_basis": "recorded_image_outputs",
        "estimate_is_invoice_cap": False,
        "batch": bool(batch),
        "label": checked_label,
    }
    if interaction_id_sha256:
        entry["interaction_id_sha256"] = interaction_id_sha256
    if attempt_sha256 is not None:
        entry["attempt_sha256"] = attempt_sha256

    with ledger_lock() as (directory_descriptor, lock_descriptor):
        ledger_identity = _ledger_identity(directory_descriptor)
        ledger = load_ledger(
            directory_descriptor,
            lock_descriptor=lock_descriptor,
        )
        if attempt_sha256 is not None:
            prior_attempts = _attempt_entries(ledger, attempt_sha256)
            if len(prior_attempts) == 1 and _attempt_entry_matches(
                prior_attempts[0],
                model=selected,
                resolution=normalized,
                count=count,
                cost=entry_cost,
                unit_cost=unit_cost,
                batch=bool(batch),
                label=checked_label,
                interaction_id_sha256=interaction_id_sha256,
            ):
                return _recorded_result(
                    ledger,
                    prior_attempts[0],
                    attempt_sha256=attempt_sha256,
                    idempotent_replay=True,
                    reconciled_after_save_error=False,
                )
            if prior_attempts:
                _raise_attempt_reconciliation_error(
                    status="unknown_requires_reconciliation",
                    attempt_sha256=attempt_sha256,
                    reason="attempt_digest_not_unique_or_payload_mismatch",
                )
        ledger["entries"].append(entry)
        ledger["total_cost"] = round(float(ledger["total_cost"]) + entry_cost, 4)
        ledger["total_images"] = int(ledger["total_images"]) + count
        daily = ledger["daily"].setdefault(
            day, {"count": 0, "estimated_image_output_usd": 0.0}
        )
        daily["count"] = int(daily.get("count", 0)) + count
        daily["estimated_image_output_usd"] = round(
            float(daily.get("estimated_image_output_usd", 0.0)) + entry_cost,
            4,
        )
        try:
            save_ledger(
                ledger,
                directory_descriptor=directory_descriptor,
                lock_descriptor=lock_descriptor,
                expected_ledger_identity=ledger_identity,
            )
        except Exception as save_error:
            if attempt_sha256 is None:
                raise
            try:
                reconciled = load_ledger(
                    directory_descriptor,
                    lock_descriptor=lock_descriptor,
                )
            except Exception as reconciliation_error:
                _raise_attempt_reconciliation_error(
                    status="unknown_requires_reconciliation",
                    attempt_sha256=attempt_sha256,
                    reason="ledger_could_not_be_reread_safely",
                    save_error=save_error,
                    reconciliation_error=reconciliation_error,
                )
            reconciled_attempts = _attempt_entries(reconciled, attempt_sha256)
            if len(reconciled_attempts) == 1 and _attempt_entry_matches(
                reconciled_attempts[0],
                model=selected,
                resolution=normalized,
                count=count,
                cost=entry_cost,
                unit_cost=unit_cost,
                batch=bool(batch),
                label=checked_label,
                interaction_id_sha256=interaction_id_sha256,
            ):
                return _recorded_result(
                    reconciled,
                    reconciled_attempts[0],
                    attempt_sha256=attempt_sha256,
                    idempotent_replay=False,
                    reconciled_after_save_error=True,
                )
            if not reconciled_attempts:
                _raise_attempt_reconciliation_error(
                    status="not_recorded",
                    attempt_sha256=attempt_sha256,
                    reason="attempt_digest_conclusively_absent",
                    save_error=save_error,
                )
            _raise_attempt_reconciliation_error(
                status="unknown_requires_reconciliation",
                attempt_sha256=attempt_sha256,
                reason="attempt_digest_not_unique_or_payload_mismatch",
                save_error=save_error,
            )
    return _recorded_result(
        ledger,
        entry,
        attempt_sha256=attempt_sha256,
        idempotent_replay=False,
        reconciled_after_save_error=False,
    )


def cmd_log(args: argparse.Namespace) -> None:
    print(
        json.dumps(
            record_generation(
                model=args.model,
                resolution=args.resolution,
                count=args.count,
                label=args.label,
                batch=args.batch,
                interaction_id=args.interaction_id,
                attempt_sha256=args.attempt_sha256,
            )
        )
    )


def cmd_summary(_args: argparse.Namespace) -> None:
    with ledger_lock() as (directory_descriptor, lock_descriptor):
        ledger = load_ledger(
            directory_descriptor,
            rewrite_raw_interaction_ids=True,
            lock_descriptor=lock_descriptor,
        )
    print(f"Total images: {ledger['total_images']}")
    print(f"Estimated image output: ${float(ledger['total_cost']):.4f}")
    print(
        "Recorded-output estimate only, not an invoice cap. "
        "Excludes input, text/thinking output, and Search charges."
    )
    days = sorted(ledger.get("daily", {}), reverse=True)[:7]
    if days:
        print("\nLast 7 recorded days:")
        for day in days:
            data = ledger["daily"][day]
            cost = data["estimated_image_output_usd"]
            print(f"  {day}: {data.get('count', 0)} images, ${float(cost):.4f}")


def cmd_today(_args: argparse.Namespace) -> None:
    with ledger_lock() as (directory_descriptor, lock_descriptor):
        ledger = load_ledger(
            directory_descriptor,
            rewrite_raw_interaction_ids=True,
            lock_descriptor=lock_descriptor,
        )
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = ledger.get("daily", {}).get(
        day, {"count": 0, "estimated_image_output_usd": 0.0}
    )
    cost = data["estimated_image_output_usd"]
    print(
        f"Today ({day}): {data.get('count', 0)} images, estimated image output ${float(cost):.4f}"
    )


def cmd_estimate(args: argparse.Namespace) -> None:
    if args.count < 1:
        raise BananaError("invalid_count", "Count must be positive.")
    selected, info = get_model(args.model)
    normalized = normalize_image_size(args.resolution, info)
    unit = estimate_image_cost(selected, normalized, batch=args.batch)
    print(
        json.dumps(
            {
                "model": selected,
                "resolution": normalized,
                "count": args.count,
                "batch": args.batch,
                "estimated_image_output_usd": round(unit * args.count, 4),
                "image_output_rate_usd": unit,
                "estimate_basis": "nominal_requested_outputs",
                "estimate_is_invoice_cap": False,
                "output_count_uncertain": True,
                "estimate_excludes": [
                    "input tokens",
                    "text and thinking output",
                    "Google Search queries",
                ],
            },
            indent=2,
        )
    )


def cmd_migrate_v1(args: argparse.Namespace) -> None:
    path = ledger_path()
    if path.is_symlink():
        raise BananaError(
            "unsafe_legacy_cost_ledger",
            f"Legacy cost ledger must not be a symbolic link: {path}",
        )
    if not path.exists():
        raise BananaError(
            "legacy_cost_ledger_missing",
            f"No legacy cost ledger exists at {path}.",
        )

    if args.dry_run:
        proposal = _migration_proposal(_read_ledger_bytes(path), path)
        proposal["dry_run"] = True
        proposal["will_write"] = False
        proposal["backup"] = {
            "will_create_on_confirm": True,
            "directory": str(banana_home() / "backups"),
            "contains_original_prompt_text": True,
            "required_directory_mode": "0700",
            "required_file_mode": "0600",
        }
        print(
            json.dumps(
                proposal, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
            )
        )
        return

    confirmation = cast(str, args.confirm)
    with ledger_lock() as (directory_descriptor, lock_descriptor):
        backup, proposal, fingerprint = _migrate_confirmed_with_descriptors(
            path,
            confirmation,
            state_directory_descriptor=directory_descriptor,
            lock_descriptor=lock_descriptor,
        )
        converted = cast(dict[str, Any], proposal["proposed_ledger"])

    print(
        json.dumps(
            {
                "action": "migrate-v1",
                "migrated": True,
                "network_called": False,
                "migration_fingerprint": fingerprint,
                "backup": {
                    "path": str(backup),
                    "contains_original_prompt_text": True,
                    "mode": "0600",
                },
                "active_ledger": {
                    "path": str(path),
                    "schema_version": 1,
                    "legacy_prompt_fields_redacted": len(
                        cast(list[Any], converted["entries"])
                    ),
                },
            },
            indent=2,
            sort_keys=True,
        )
    )


def cmd_reset(args: argparse.Namespace) -> None:
    if not args.confirm:
        raise BananaError(
            "confirmation_required", "Pass --confirm to reset the cost ledger."
        )
    with ledger_lock() as (directory_descriptor, lock_descriptor):
        ledger_identity = _ledger_identity(directory_descriptor)
        save_ledger(
            empty_ledger(),
            directory_descriptor=directory_descriptor,
            lock_descriptor=lock_descriptor,
            expected_ledger_identity=ledger_identity,
        )
    print("Cost ledger reset.")


def build_parser() -> argparse.ArgumentParser:
    parser = SecretSafeArgumentParser(description="Banana Claude private cost ledger")
    sub = parser.add_subparsers(dest="command", required=True)

    log_parser = sub.add_parser("log", help="Log completed image output")
    log_parser.add_argument("--model", required=True)
    log_parser.add_argument("--resolution", required=True)
    log_parser.add_argument("--count", type=int, default=1)
    log_parser.add_argument("--label", default="image generation")
    log_parser.add_argument("--batch", action="store_true")
    log_parser.add_argument("--interaction-id")
    log_parser.add_argument("--attempt-sha256")

    sub.add_parser("summary", help="Show totals and the last seven recorded days")
    sub.add_parser("today", help="Show today's recorded usage")

    estimate_parser = sub.add_parser("estimate", help="Estimate image output cost")
    estimate_parser.add_argument("--model", required=True)
    estimate_parser.add_argument("--resolution", required=True)
    estimate_parser.add_argument("--count", required=True, type=int)
    estimate_parser.add_argument("--batch", action="store_true")

    migration_parser = sub.add_parser(
        "migrate-v1",
        help="Review or confirm migration of an exact unversioned Banana Claude 1.4.1 ledger",
    )
    migration_confirmation = migration_parser.add_mutually_exclusive_group(
        required=True
    )
    migration_confirmation.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the exact redacted proposal and fingerprint without writing",
    )
    migration_confirmation.add_argument(
        "--confirm",
        metavar="FINGERPRINT",
        help="Migrate only if this fingerprint matches the current bytes and proposal",
    )

    reset_parser = sub.add_parser("reset", help="Reset the ledger")
    reset_parser.add_argument("--confirm", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    commands = {
        "log": cmd_log,
        "summary": cmd_summary,
        "today": cmd_today,
        "estimate": cmd_estimate,
        "migrate-v1": cmd_migrate_v1,
        "reset": cmd_reset,
    }
    try:
        commands[args.command](args)
        return 0
    except BananaError as exc:
        print(json.dumps(exc.as_dict()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
