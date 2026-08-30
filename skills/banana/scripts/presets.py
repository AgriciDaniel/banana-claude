#!/usr/bin/env python3
"""Manage private visual-system presets for Banana Claude."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import re
import stat
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from banana_core import (
    BananaError,
    SecretSafeArgumentParser,
    _atomic_write,
    _atomic_write_at,
    _directory_path_matches_fd,
    _exclusive_rename_at,
    _open_secure_directory,
    get_model,
    normalize_image_size,
    validate_approval_text,
    validate_aspect_ratio,
)

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
PRESET_MIGRATION_BACKUP_PATTERN = re.compile(
    r"\A(?P<name>[A-Za-z0-9][A-Za-z0-9_-]{0,63})"
    r"\.v1-\d{8}T\d{12}Z-[0-9a-f]{12}-[0-9a-f]{16}\.json\Z"
)
SCALAR_FIELDS = (
    "description",
    "visual_thesis",
    "signature_element",
    "typography",
    "photography",
    "illustration",
    "copy_rules",
)
LIST_FIELDS = ("locks", "freedoms", "anti_references")
PRESET_KEYS = frozenset(
    {
        "schema_version",
        "name",
        *SCALAR_FIELDS,
        "palette",
        *LIST_FIELDS,
        "references",
        "default_model",
        "default_aspect_ratio",
        "default_image_size",
    }
)
REFERENCE_KEYS = frozenset({"path", "role", "purpose", "subject_id"})
REFERENCE_ROLES = frozenset({"object", "character", "style"})
MAX_SCALAR_LENGTH = 2_000
MAX_LIST_ITEMS = 64
MAX_LIST_ITEM_LENGTH = 500
MAX_PALETTE_ITEMS = 32
MAX_REFERENCE_PATH_LENGTH = 4_096
MAX_REFERENCE_LABEL_LENGTH = 120
MAX_REFERENCE_JSON_CHARS = 16_384
MAX_PRESET_BYTES = 1 * 1024 * 1024
MAX_PRESET_BACKUP_SCAN_ENTRIES = 4_096
LEGACY_PRESET_KEYS = frozenset(
    {
        "name",
        "description",
        "colors",
        "style",
        "typography",
        "lighting",
        "mood",
        "default_ratio",
        "default_resolution",
    }
)


def presets_directory() -> Path:
    configured = os.environ.get("BANANA_HOME")
    selected = Path(configured).expanduser() if configured else Path.home() / ".banana"
    root = Path(os.path.abspath(selected))
    return root / "presets"


def _verify_existing_directory_components(path: Path) -> None:
    """Reject existing redirects without creating or changing path components."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    try:
        for component in absolute.parts[1:]:
            if component in {"", ".", ".."}:
                raise OSError("unsafe preset state component")
            current /= component
            try:
                metadata = os.lstat(current)
            except FileNotFoundError:
                return
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise OSError("preset state path contains a redirect")
    except OSError as exc:
        raise BananaError(
            "unsafe_preset_state_directory",
            f"Preset state directory could not be opened safely at {absolute}.",
        ) from exc


def _open_existing_preset_directory(path: Path) -> int | None:
    """Open an existing directory without following any lexical path component."""
    absolute = Path(os.path.abspath(path))
    if os.name == "nt" or not hasattr(os, "O_DIRECTORY"):
        _verify_existing_directory_components(absolute)
        try:
            metadata = os.lstat(absolute)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise BananaError(
                "unsafe_preset_state_directory",
                f"Preset state directory could not be opened safely at {absolute}.",
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise BananaError(
                "unsafe_preset_state_directory",
                f"Preset state directory could not be opened safely at {absolute}.",
            )
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
            if component in {"", ".", ".."}:
                raise OSError("unsafe preset state component")
            entry_metadata = os.stat(
                component,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
            if stat.S_ISLNK(entry_metadata.st_mode) or not stat.S_ISDIR(
                entry_metadata.st_mode
            ):
                raise OSError("preset state path contains a redirect")
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            opened_metadata = os.fstat(next_descriptor)
            if not stat.S_ISDIR(opened_metadata.st_mode) or (
                opened_metadata.st_dev,
                opened_metadata.st_ino,
            ) != (entry_metadata.st_dev, entry_metadata.st_ino):
                os.close(next_descriptor)
                raise OSError("preset state component identity changed")
            os.close(descriptor)
            descriptor = next_descriptor
        if not _directory_path_matches_fd(absolute, descriptor):
            raise OSError("preset state directory identity changed")
        return descriptor
    except FileNotFoundError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except (BananaError, OSError) as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise BananaError(
            "unsafe_preset_state_directory",
            f"Preset state directory could not be opened safely at {absolute}.",
        ) from exc


def _validate_preset_name(name: str) -> str:
    if not NAME_PATTERN.fullmatch(name):
        raise BananaError(
            "invalid_preset_name",
            "Preset names must be 1 to 64 letters, numbers, hyphens, or underscores and start with a letter or number.",
        )
    return name


def _uncreated_preset_path(name: str) -> Path:
    """Resolve a preset path without creating or changing local state."""
    return presets_directory() / f"{_validate_preset_name(name)}.json"


def _secure_directory() -> Path:
    directory = presets_directory()
    _make_private_directory(directory.parent, parents=True)
    _make_private_directory(directory)
    return directory


def preset_path(name: str) -> Path:
    return _secure_directory() / f"{_validate_preset_name(name)}.json"


def _preset_directory_identity(
    path: Path,
    descriptor: int | None,
) -> tuple[int, int]:
    metadata = os.lstat(path) if descriptor is None else os.fstat(descriptor)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise BananaError(
            "unsafe_preset_state_directory",
            "A preset migration directory is not one real directory.",
        )
    return metadata.st_dev, metadata.st_ino


def _preset_directory_binding_verified(
    path: Path,
    descriptor: int | None,
    expected_identity: tuple[int, int],
) -> bool:
    try:
        metadata = os.lstat(path) if descriptor is None else os.fstat(descriptor)
    except OSError:
        return False
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_dev, metadata.st_ino) != expected_identity
    ):
        return False
    return bool(descriptor is None or _directory_path_matches_fd(path, descriptor))


def _preset_entry_metadata(
    directory_descriptor: int | None,
    path: Path,
) -> os.stat_result | None:
    try:
        return (
            os.lstat(path)
            if directory_descriptor is None
            else os.stat(
                path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BananaError(
            "unsafe_preset_state_directory",
            "A preset state entry could not be inspected safely.",
        ) from exc


def _preset_migration_residue(
    requested_name: str | None,
) -> dict[str, Any] | None:
    """Detect one strict migration residue without selecting a restore source."""
    if requested_name is not None:
        requested_name = _validate_preset_name(requested_name)
    active_directory = presets_directory()
    backup_directory = active_directory.parent / "backups" / "presets"
    active_directory_descriptor: int | None = None
    backup_directory_descriptor: int | None = None
    try:
        active_directory_descriptor = _open_existing_preset_directory(active_directory)
        active_directory_identity = _preset_directory_identity(
            active_directory,
            active_directory_descriptor,
        )

        def active_metadata(name: str) -> os.stat_result | None:
            return _preset_entry_metadata(
                active_directory_descriptor,
                active_directory / f"{name}.json",
            )

        if requested_name is not None and active_metadata(requested_name) is not None:
            if not _preset_directory_binding_verified(
                active_directory,
                active_directory_descriptor,
                active_directory_identity,
            ):
                raise BananaError(
                    "unsafe_preset_state_directory",
                    "The active preset directory changed during residue inspection.",
                )
            return None

        try:
            backup_directory_descriptor = _open_existing_preset_directory(
                backup_directory
            )
        except FileNotFoundError:
            if not _preset_directory_binding_verified(
                active_directory,
                active_directory_descriptor,
                active_directory_identity,
            ):
                raise BananaError(
                    "unsafe_preset_state_directory",
                    "The active preset directory changed during residue inspection.",
                )
            return None
        backup_directory_identity = _preset_directory_identity(
            backup_directory,
            backup_directory_descriptor,
        )
        iterator = os.scandir(
            backup_directory
            if backup_directory_descriptor is None
            else backup_directory_descriptor
        )
        inspected_entries = 0
        with iterator:
            for entry in iterator:
                inspected_entries += 1
                if inspected_entries > MAX_PRESET_BACKUP_SCAN_ENTRIES:
                    if (
                        requested_name is not None
                        and active_metadata(requested_name) is not None
                    ):
                        if not _preset_directory_binding_verified(
                            active_directory,
                            active_directory_descriptor,
                            active_directory_identity,
                        ):
                            raise BananaError(
                                "unsafe_preset_state_directory",
                                "The active preset directory changed during residue inspection.",
                            )
                        return None
                    if not _preset_directory_binding_verified(
                        active_directory,
                        active_directory_descriptor,
                        active_directory_identity,
                    ) or not _preset_directory_binding_verified(
                        backup_directory,
                        backup_directory_descriptor,
                        backup_directory_identity,
                    ):
                        raise BananaError(
                            "unsafe_preset_state_directory",
                            "A preset migration directory changed during residue inspection.",
                        )
                    return {
                        "recovery_required": True,
                        "preset_name": requested_name,
                        "active_preset_present": False,
                        "automatic_restore_attempted": False,
                        "inspection_complete": False,
                        "inspection_status": "backup_entry_limit_exceeded",
                        "inspected_entries": MAX_PRESET_BACKUP_SCAN_ENTRIES,
                        "observed_backup": None,
                    }
                match = PRESET_MIGRATION_BACKUP_PATTERN.fullmatch(entry.name)
                if match is None:
                    continue
                candidate_name = match.group("name")
                if requested_name is not None and candidate_name != requested_name:
                    continue
                if active_metadata(candidate_name) is not None:
                    continue
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise BananaError(
                        "preset_migration_recovery_required",
                        "A preset migration backup residue could not be inspected safely.",
                        details={
                            "recovery_required": True,
                            "preset_name": candidate_name,
                            "active_preset_present": False,
                            "automatic_restore_attempted": False,
                            "inspection_complete": False,
                            "inspection_status": "matching_backup_unstable",
                        },
                    ) from exc
                if not _preset_directory_binding_verified(
                    active_directory,
                    active_directory_descriptor,
                    active_directory_identity,
                ) or not _preset_directory_binding_verified(
                    backup_directory,
                    backup_directory_descriptor,
                    backup_directory_identity,
                ):
                    raise BananaError(
                        "unsafe_preset_state_directory",
                        "A preset migration directory changed during residue inspection.",
                    )
                if active_metadata(candidate_name) is not None:
                    continue
                if not _preset_directory_binding_verified(
                    active_directory,
                    active_directory_descriptor,
                    active_directory_identity,
                ) or not _preset_directory_binding_verified(
                    backup_directory,
                    backup_directory_descriptor,
                    backup_directory_identity,
                ):
                    raise BananaError(
                        "unsafe_preset_state_directory",
                        "A preset migration directory changed during residue inspection.",
                    )
                return {
                    "recovery_required": True,
                    "preset_name": candidate_name,
                    "active_preset_present": False,
                    "automatic_restore_attempted": False,
                    "inspection_complete": True,
                    "inspection_status": "strict_migration_backup_observed",
                    "inspected_entries": inspected_entries,
                    "backup_directory": str(backup_directory),
                    "backup_directory_device": backup_directory_identity[0],
                    "backup_directory_inode": backup_directory_identity[1],
                    "backup_directory_path_binding_verified": True,
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
        if not _preset_directory_binding_verified(
            active_directory,
            active_directory_descriptor,
            active_directory_identity,
        ) or not _preset_directory_binding_verified(
            backup_directory,
            backup_directory_descriptor,
            backup_directory_identity,
        ):
            raise BananaError(
                "unsafe_preset_state_directory",
                "A preset migration directory changed during residue inspection.",
            )
        return None
    except BananaError:
        raise
    except OSError as exc:
        raise BananaError(
            "unsafe_preset_state_directory",
            "Preset migration residue could not be inspected safely.",
        ) from exc
    finally:
        if backup_directory_descriptor is not None:
            os.close(backup_directory_descriptor)
        if active_directory_descriptor is not None:
            os.close(active_directory_descriptor)


def _require_no_preset_migration_residue(name: str | None) -> None:
    residue = _preset_migration_residue(name)
    if residue is None:
        return
    raise BananaError(
        "preset_migration_recovery_required",
        "An active preset is absent while a legacy migration backup may remain. Refusing to mask an interrupted migration.",
        details=residue,
    )


def _atomic_json(
    path: Path,
    value: dict[str, Any],
    *,
    replace: bool = True,
) -> None:
    serialized = (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    try:
        _atomic_write(path, serialized, replace=replace)
    except BananaError as exc:
        core_error = {"core_write_error": exc.as_dict()}
        if exc.code == "output_exists":
            raise BananaError(
                "preset_exists",
                f"Preset '{path.stem}' exists. Pass --force to replace it.",
                details=core_error,
            ) from exc
        raise BananaError(
            "preset_write_failed",
            f"Preset '{path.stem}' could not be written safely.",
            details=core_error,
        ) from exc


def _read_preset_bytes(path: Path, *, name: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    directory_descriptor: int | None = None
    descriptor: int | None = None
    try:
        directory_descriptor = _open_existing_preset_directory(path.parent)
        entry_metadata = (
            os.lstat(path)
            if directory_descriptor is None
            else os.stat(
                path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        )
        if stat.S_ISLNK(entry_metadata.st_mode) or not stat.S_ISREG(
            entry_metadata.st_mode
        ):
            raise BananaError(
                "invalid_preset",
                f"Preset '{name}' must be a regular file.",
            )
        descriptor = (
            os.open(path, flags)
            if directory_descriptor is None
            else os.open(path.name, flags, dir_fd=directory_descriptor)
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino)
            != (entry_metadata.st_dev, entry_metadata.st_ino)
            or (
                directory_descriptor is not None
                and not _directory_path_matches_fd(path.parent, directory_descriptor)
            )
        ):
            raise BananaError(
                "invalid_preset",
                f"Preset '{name}' changed while it was opened.",
            )
        raw = _bounded_preset_descriptor_read(descriptor, name=name)
        current_metadata = (
            os.lstat(path)
            if directory_descriptor is None
            else os.stat(
                path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        )
        if (
            stat.S_ISLNK(current_metadata.st_mode)
            or not stat.S_ISREG(current_metadata.st_mode)
            or (current_metadata.st_dev, current_metadata.st_ino)
            != (metadata.st_dev, metadata.st_ino)
            or (
                directory_descriptor is not None
                and not _directory_path_matches_fd(path.parent, directory_descriptor)
            )
        ):
            raise BananaError(
                "invalid_preset",
                f"Preset '{name}' changed while it was read.",
            )
    except FileNotFoundError as exc:
        _require_no_preset_migration_residue(name)
        raise BananaError(
            "preset_not_found", f"Preset '{name}' was not found."
        ) from exc
    except BananaError:
        raise
    except OSError as exc:
        raise BananaError(
            "invalid_preset", f"Preset '{name}' cannot be read: {exc}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)
    return raw


def _decode_preset_json(raw: bytes, *, name: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise BananaError(
            "invalid_preset",
            f"Preset '{name}' is not valid bounded UTF-8 JSON.",
        ) from exc


def _checked_text(
    value: Any,
    *,
    field: str,
    max_length: int,
    allow_empty: bool = True,
) -> str:
    if allow_empty and value == "":
        return ""
    return validate_approval_text(
        value,
        field=f"Preset field '{field}'",
        max_length=max_length,
        error_code="invalid_preset",
    )


def _checked_string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise BananaError(
            "invalid_preset", f"Preset field '{field}' must be a list of strings."
        )
    if len(value) > MAX_LIST_ITEMS:
        raise BananaError(
            "invalid_preset",
            f"Preset field '{field}' must contain at most {MAX_LIST_ITEMS} entries.",
        )
    return [
        _checked_text(
            item,
            field=f"{field}[{index}]",
            max_length=MAX_LIST_ITEM_LENGTH,
            allow_empty=False,
        )
        for index, item in enumerate(value)
    ]


def _checked_references(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise BananaError(
            "invalid_preset",
            "Preset field 'references' must be a list of reference objects.",
        )
    if len(value) > MAX_LIST_ITEMS:
        raise BananaError(
            "invalid_preset",
            f"Preset field 'references' must contain at most {MAX_LIST_ITEMS} entries.",
        )
    checked: list[dict[str, str]] = []
    for index, item in enumerate(value):
        field = f"references[{index}]"
        if not isinstance(item, dict):
            raise BananaError(
                "invalid_preset",
                f"Preset field '{field}' must be an object with path, role, and purpose.",
            )
        unknown = sorted(str(key) for key in set(item) - REFERENCE_KEYS)
        if unknown:
            raise BananaError(
                "invalid_preset",
                f"Preset field '{field}' contains unsupported keys: {', '.join(unknown)}.",
            )
        missing = sorted({"path", "role", "purpose"} - set(item))
        if missing:
            raise BananaError(
                "invalid_preset",
                f"Preset field '{field}' is missing required keys: {', '.join(missing)}.",
            )
        path = _checked_text(
            item["path"],
            field=f"{field}.path",
            max_length=MAX_REFERENCE_PATH_LENGTH,
            allow_empty=False,
        )
        role = _checked_text(
            item["role"],
            field=f"{field}.role",
            max_length=MAX_REFERENCE_LABEL_LENGTH,
            allow_empty=False,
        )
        if role not in REFERENCE_ROLES:
            raise BananaError(
                "invalid_preset",
                f"Preset field '{field}.role' must be object, character, or style.",
            )
        purpose = _checked_text(
            item["purpose"],
            field=f"{field}.purpose",
            max_length=MAX_REFERENCE_LABEL_LENGTH,
            allow_empty=False,
        )
        reference = {"path": path, "role": role, "purpose": purpose}
        if "subject_id" in item:
            reference["subject_id"] = _checked_text(
                item["subject_id"],
                field=f"{field}.subject_id",
                max_length=MAX_REFERENCE_LABEL_LENGTH,
                allow_empty=False,
            )
        checked.append(reference)
    return checked


def validate_preset(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != 2
    ):
        raise BananaError("invalid_preset", "Preset must use schema_version 2.")
    unknown = sorted(str(key) for key in set(value) - PRESET_KEYS)
    if unknown:
        raise BananaError(
            "invalid_preset", f"Preset contains unsupported keys: {', '.join(unknown)}."
        )
    name = value.get("name")
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise BananaError("invalid_preset", "Preset has an invalid name.")
    palette = value.get("palette", [])
    if (
        not isinstance(palette, list)
        or len(palette) > MAX_PALETTE_ITEMS
        or any(
            not isinstance(item, str) or not HEX_PATTERN.fullmatch(item)
            for item in palette
        )
    ):
        raise BananaError(
            "invalid_preset",
            "Palette entries must be six-digit hex colors such as #2563EB.",
        )
    raw_model = value.get("default_model")
    if "default_model" in value:
        _checked_text(
            value["default_model"],
            field="default_model",
            max_length=120,
            allow_empty=False,
        )
    model, model_info = get_model(raw_model)
    raw_size = value.get("default_image_size")
    if "default_image_size" in value:
        _checked_text(
            value["default_image_size"],
            field="default_image_size",
            max_length=16,
            allow_empty=False,
        )
    raw_ratio = value.get("default_aspect_ratio", "1:1")
    _checked_text(
        raw_ratio, field="default_aspect_ratio", max_length=16, allow_empty=False
    )

    checked: dict[str, Any] = {
        "schema_version": 2,
        "name": name,
        **{
            field: _checked_text(
                value.get(field, ""), field=field, max_length=MAX_SCALAR_LENGTH
            )
            for field in SCALAR_FIELDS
        },
        "palette": list(palette),
        **{
            field: _checked_string_list(value.get(field, []), field=field)
            for field in LIST_FIELDS
        },
        "references": _checked_references(value.get("references", [])),
        "default_model": model,
        "default_aspect_ratio": validate_aspect_ratio(raw_ratio, model_info),
        "default_image_size": normalize_image_size(raw_size, model_info),
    }
    return checked


def _legacy_v1_proposal(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != LEGACY_PRESET_KEYS:
        raise BananaError(
            "invalid_legacy_preset",
            "Legacy migration accepts only the exact unversioned Banana Claude 1.4.1 preset shape.",
        )
    if value.get("name") != name:
        raise BananaError(
            "invalid_legacy_preset",
            f"Legacy preset name must exactly match the requested preset '{name}'.",
        )
    scalar_fields = (
        "name",
        "description",
        "style",
        "typography",
        "lighting",
        "mood",
        "default_ratio",
        "default_resolution",
    )
    if any(not isinstance(value.get(field), str) for field in scalar_fields):
        raise BananaError(
            "invalid_legacy_preset", "Every legacy preset text field must be a string."
        )
    colors = value.get("colors")
    if not isinstance(colors, list) or any(
        not isinstance(color, str) for color in colors
    ):
        raise BananaError(
            "invalid_legacy_preset", "Legacy preset colors must be a list of strings."
        )

    default_model, _model_info = get_model()
    proposal = {
        "schema_version": 2,
        "name": name,
        "description": value["description"],
        "visual_thesis": value["style"],
        "signature_element": "",
        "palette": colors,
        "typography": value["typography"],
        "photography": f"Lighting: {value['lighting']}; Mood: {value['mood']}",
        "illustration": "",
        "copy_rules": "",
        "locks": [],
        "freedoms": [],
        "references": [],
        "anti_references": [],
        "default_model": default_model,
        "default_aspect_ratio": value["default_ratio"],
        "default_image_size": value["default_resolution"],
    }
    try:
        return validate_preset(proposal)
    except BananaError as exc:
        raise BananaError(
            "invalid_legacy_preset",
            f"Legacy preset cannot be migrated safely: {exc.message}",
        ) from exc


def _migration_fingerprint(raw: bytes, proposal: dict[str, Any]) -> str:
    canonical_proposal = json.dumps(
        proposal,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(b"banana-claude-preset-v1-to-v2\x00")
    digest.update(len(raw).to_bytes(8, "big"))
    digest.update(raw)
    digest.update(len(canonical_proposal).to_bytes(8, "big"))
    digest.update(canonical_proposal)
    return digest.hexdigest()


def _migration_disclosure(default_model: str) -> dict[str, Any]:
    return {
        "direct": {
            "name": "name",
            "description": "description",
            "colors": "palette",
            "style": "visual_thesis",
            "typography": "typography",
            "default_ratio": "default_aspect_ratio",
            "default_resolution": "default_image_size",
        },
        "combined": {
            "lighting + mood": "photography, labeled as Lighting and Mood",
        },
        "initialized_empty": [
            "signature_element",
            "illustration",
            "copy_rules",
            "locks",
            "freedoms",
            "references",
            "anti_references",
        ],
        "default_model": f"set to the current catalog default, {default_model}",
    }


def _migration_material(name: str) -> tuple[Path, bytes, dict[str, Any], str]:
    path = _uncreated_preset_path(name)
    raw = _read_preset_bytes(path, name=name)
    proposal = _legacy_v1_proposal(name, _decode_preset_json(raw, name=name))
    return path, raw, proposal, _migration_fingerprint(raw, proposal)


def _make_private_directory(path: Path, *, parents: bool = False) -> None:
    del parents
    descriptor: int | None = None
    try:
        _verify_existing_directory_components(path)
        descriptor = _open_secure_directory(path)
        if descriptor is None:
            _verify_existing_directory_components(path)
            before = os.lstat(path)
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise OSError("path is not a real directory")
            if os.name != "nt":
                path.chmod(0o700)
            after = os.lstat(path)
            if (
                stat.S_ISLNK(after.st_mode)
                or not stat.S_ISDIR(after.st_mode)
                or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            ):
                raise OSError("directory identity changed")
            return
        if os.name != "nt":
            os.fchmod(descriptor, 0o700)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or (os.name != "nt" and stat.S_IMODE(metadata.st_mode) != 0o700)
            or not _directory_path_matches_fd(path, descriptor)
        ):
            raise OSError("directory identity or permissions changed")
    except (BananaError, OSError) as exc:
        raise BananaError(
            "unsafe_preset_state_directory",
            f"Private preset state directory could not be secured at {path}.",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _preset_lock_entry_metadata(
    directory_descriptor: int | None,
    path: Path,
) -> os.stat_result | None:
    try:
        metadata = (
            os.lstat(path)
            if directory_descriptor is None
            else os.stat(
                path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BananaError(
            "preset_migration_failed",
            f"Cannot inspect preset lock '{path.stem}' safely.",
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise BananaError(
            "preset_migration_failed",
            f"Preset lock '{path.stem}' must be one regular, privately linked file.",
        )
    return metadata


def _opened_preset_lock_matches(
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


@contextmanager
def _preset_lock(name: str) -> Iterator[None]:
    banana_home = presets_directory().parent
    locks_root = banana_home / ".locks"
    locks_directory = locks_root / "presets"
    _make_private_directory(banana_home, parents=True)
    _make_private_directory(locks_root)
    _make_private_directory(locks_directory)
    path = locks_directory / f"{name}.lock"
    directory_descriptor = _open_existing_preset_directory(locks_directory)
    fallback_parent_metadata = (
        os.lstat(locks_directory) if directory_descriptor is None else None
    )
    descriptor: int | None = None
    handle: Any | None = None
    expected: os.stat_result | None = None
    locked = False

    def parent_matches() -> bool:
        if directory_descriptor is not None:
            return _directory_path_matches_fd(locks_directory, directory_descriptor)
        try:
            current = os.lstat(locks_directory)
        except OSError:
            return False
        return bool(
            fallback_parent_metadata is not None
            and stat.S_ISDIR(current.st_mode)
            and not stat.S_ISLNK(current.st_mode)
            and (current.st_dev, current.st_ino)
            == (fallback_parent_metadata.st_dev, fallback_parent_metadata.st_ino)
        )

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
        base_flags = os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            base_flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            base_flags |= os.O_NONBLOCK
        for _attempt in range(8):
            existing = _preset_lock_entry_metadata(directory_descriptor, path)
            open_flags = base_flags
            if existing is None:
                open_flags |= os.O_CREAT | os.O_EXCL
            try:
                descriptor = open_lock(open_flags)
            except FileExistsError:
                if existing is not None:
                    raise
                continue
            except FileNotFoundError:
                if existing is None:
                    raise
                continue
            current = _preset_lock_entry_metadata(directory_descriptor, path)
            if current is None:
                raise OSError("lock entry disappeared while it was opened")
            if existing is not None and (
                current.st_dev,
                current.st_ino,
            ) != (existing.st_dev, existing.st_ino):
                raise OSError("lock identity changed while it was opened")
            if not _opened_preset_lock_matches(
                directory_descriptor,
                path,
                descriptor,
                current,
            ):
                raise OSError("opened lock does not match its public entry")
            expected = current
            break
        else:
            raise OSError("lock entry remained unstable during exclusive open")

        if descriptor is None or expected is None or not parent_matches():
            raise OSError("lock parent identity changed before locking")
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
            if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600:
                raise OSError("lock permissions are not 0600")
        if (
            not _opened_preset_lock_matches(
                directory_descriptor,
                path,
                descriptor,
                expected,
            )
            or not parent_matches()
        ):
            raise OSError("lock identity changed before locking")
        handle = os.fdopen(descriptor, "a+b")
        descriptor = None
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
        locked = True
        if (
            not _opened_preset_lock_matches(
                directory_descriptor,
                path,
                handle.fileno(),
                expected,
            )
            or not parent_matches()
        ):
            raise OSError("lock identity changed while flock was acquired")
        yield
        if (
            not _opened_preset_lock_matches(
                directory_descriptor,
                path,
                handle.fileno(),
                expected,
            )
            or not parent_matches()
        ):
            raise OSError("lock identity changed while flock was held")
    except BananaError:
        raise
    except OSError as exc:
        raise BananaError(
            "preset_migration_failed", f"Cannot lock preset '{name}': {exc}"
        ) from exc
    finally:
        if locked and os.name == "nt" and handle is not None:
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        elif locked and handle is not None:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        if handle is not None:
            handle.close()
        if descriptor is not None:
            os.close(descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def _bounded_preset_descriptor_read(descriptor: int, *, name: str) -> bytes:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_PRESET_BYTES:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, MAX_PRESET_BYTES + 1 - total),
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    except OSError as exc:
        raise BananaError(
            "invalid_preset",
            f"Preset '{name}' could not be read within its safety limit.",
        ) from exc
    raw = b"".join(chunks)
    if len(raw) > MAX_PRESET_BYTES:
        raise BananaError(
            "preset_too_large",
            f"Preset '{name}' exceeds the {MAX_PRESET_BYTES}-byte safety limit.",
        )
    return raw


def _bounded_preset_recovery_read(descriptor: int, *, name: str) -> bytes:
    """Read a held recovery descriptor without re-entering a failed read hook."""
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_PRESET_BYTES:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, MAX_PRESET_BYTES + 1 - total),
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    except OSError as exc:
        raise BananaError(
            "preset_migration_recovery_failed",
            f"Preset '{name}' could not be read safely during recovery.",
        ) from exc
    raw = b"".join(chunks)
    if len(raw) > MAX_PRESET_BYTES:
        raise BananaError(
            "preset_migration_recovery_failed",
            f"Preset '{name}' exceeded its recovery safety limit.",
        )
    return raw


def _preset_descriptor_entry_matches(
    directory_descriptor: int,
    entry_name: str,
    file_descriptor: int,
) -> bool:
    try:
        path_metadata = os.stat(
            entry_name,
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


def _open_confirmed_preset_source_at(
    directory_descriptor: int,
    source: Path,
    *,
    name: str,
) -> tuple[int, bytes]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor: int | None = None
    succeeded = False
    try:
        descriptor = os.open(source.name, flags, dir_fd=directory_descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise BananaError(
                "unsafe_legacy_preset",
                "Legacy preset migration requires one regular, privately linked source file.",
            )
        if not _preset_descriptor_entry_matches(
            directory_descriptor,
            source.name,
            descriptor,
        ):
            raise BananaError(
                "migration_fingerprint_mismatch",
                "The legacy preset path changed while it was opened for migration.",
            )
        raw = _bounded_preset_descriptor_read(descriptor, name=name)
        succeeded = True
        return descriptor, raw
    except OSError as exc:
        raise BananaError(
            "unsafe_legacy_preset",
            "Legacy preset could not be opened without following links.",
        ) from exc
    finally:
        if descriptor is not None and not succeeded:
            os.close(descriptor)


def _open_preset_child_directory_at(
    parent_descriptor: int,
    entry_name: str,
    path: Path,
    *,
    create: bool,
    error_code: str,
) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor: int | None = None
    try:
        try:
            entry_metadata = os.stat(
                entry_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            entry_metadata = None
        if entry_metadata is not None and stat.S_ISLNK(entry_metadata.st_mode):
            raise BananaError(
                "unsafe_preset_state_directory",
                f"Private preset state directory must not be a symbolic link: {path}",
            )
        try:
            descriptor = os.open(entry_name, flags, dir_fd=parent_descriptor)
        except FileNotFoundError:
            if not create:
                raise
            os.mkdir(entry_name, mode=0o700, dir_fd=parent_descriptor)
            descriptor = os.open(entry_name, flags, dir_fd=parent_descriptor)
        os.fchmod(descriptor, 0o700)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or not _directory_path_matches_fd(path, descriptor)
        ):
            raise OSError("backup directory identity or permissions changed")
        return descriptor
    except BananaError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise BananaError(
            error_code,
            "A preset migration directory could not be held securely.",
        ) from exc


def _fsync_preset_directory_chain(
    *directory_descriptors: int,
    error_code: str,
) -> None:
    """Persist newly created private directory ancestry from leaf to root."""
    try:
        for descriptor in directory_descriptors:
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise OSError("preset state ancestry contains a non-directory")
            os.fsync(descriptor)
    except OSError as exc:
        raise BananaError(
            error_code,
            "Private preset state directory ancestry could not be persisted safely.",
        ) from exc


def _restore_claimed_preset_at(
    source_directory_descriptor: int,
    source_path: Path,
    backup_directory_descriptor: int,
    backup_name: str,
    backup_descriptor: int,
    *,
    expected_raw: bytes,
    name: str,
) -> bool:
    """Publish an independent private copy while retaining the backup inode."""
    expected_identity: tuple[int, int] | None = None
    try:
        held_metadata = os.fstat(backup_descriptor)
        if os.name != "nt":
            os.fchmod(backup_descriptor, 0o600)
            held_metadata = os.fstat(backup_descriptor)
        backup_metadata = os.stat(
            backup_name,
            dir_fd=backup_directory_descriptor,
            follow_symlinks=False,
        )
        expected_identity = (held_metadata.st_dev, held_metadata.st_ino)
        held_raw = _bounded_preset_recovery_read(backup_descriptor, name=name)
        if (
            not stat.S_ISREG(held_metadata.st_mode)
            or held_metadata.st_nlink != 1
            or (os.name != "nt" and stat.S_IMODE(held_metadata.st_mode) != 0o600)
            or not stat.S_ISREG(backup_metadata.st_mode)
            or backup_metadata.st_nlink != 1
            or (backup_metadata.st_dev, backup_metadata.st_ino) != expected_identity
            or held_raw != expected_raw
            or not _preset_descriptor_entry_matches(
                backup_directory_descriptor,
                backup_name,
                backup_descriptor,
            )
        ):
            raise OSError("claimed backup path is not bound to its held descriptor")
    except BaseException:
        return False
    publication_error: BaseException | None = None
    try:
        _atomic_write_at(
            source_directory_descriptor,
            source_path.name,
            expected_raw,
            replace=False,
            expected_directory=source_path.parent,
        )
    except BaseException as exc:
        publication_error = exc

    active_exact, _active_details = _exact_preset_publication(
        source_directory_descriptor=source_directory_descriptor,
        source_path=source_path,
        expected_raw=expected_raw,
        name=name,
        disallowed_identity=expected_identity,
    )
    if publication_error is not None and not active_exact:
        return False
    try:
        backup_metadata = os.stat(
            backup_name,
            dir_fd=backup_directory_descriptor,
            follow_symlinks=False,
        )
        held_metadata = os.fstat(backup_descriptor)
        held_raw = _bounded_preset_recovery_read(backup_descriptor, name=name)
        if (
            not active_exact
            or not stat.S_ISREG(backup_metadata.st_mode)
            or (backup_metadata.st_dev, backup_metadata.st_ino) != expected_identity
            or held_metadata.st_nlink != 1
            or held_raw != expected_raw
            or (os.name != "nt" and stat.S_IMODE(held_metadata.st_mode) != 0o600)
            or not _preset_descriptor_entry_matches(
                backup_directory_descriptor,
                backup_name,
                backup_descriptor,
            )
            or not _directory_path_matches_fd(
                source_path.parent,
                source_directory_descriptor,
            )
        ):
            return False
        os.fsync(source_directory_descriptor)
        os.fsync(backup_directory_descriptor)
    except BaseException:
        return False
    return True


def _link_held_preset_descriptor_at(
    source_descriptor: int,
    destination_directory_descriptor: int,
    destination_name: str,
) -> None:
    """Atomically link a held inode, failing closed where that is unavailable."""
    if not sys.platform.startswith("linux"):
        raise BananaError(
            "preset_migration_recovery_unavailable",
            "This platform cannot bind preset recovery publication to the held legacy inode.",
        )

    library = ctypes.CDLL(None, use_errno=True)
    try:
        operation: Any = library.linkat
    except AttributeError as exc:
        raise BananaError(
            "preset_migration_recovery_unavailable",
            "This platform cannot bind preset recovery publication to the held legacy inode.",
        ) from exc
    operation.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    operation.restype = ctypes.c_int
    at_empty_path = 0x1000
    if (
        operation(
            source_descriptor,
            b"",
            destination_directory_descriptor,
            os.fsencode(destination_name),
            at_empty_path,
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
            "preset_migration_recovery_unavailable",
            "The preset filesystem cannot bind recovery publication to the held legacy inode.",
        )
    raise OSError(error_number, os.strerror(error_number), destination_name)


def _retain_substituted_preset_source(
    *,
    name: str,
    source_descriptor: int,
    raw: bytes,
    fingerprint: str,
    backup_directory_descriptor: int,
    backup_directory: Path,
) -> dict[str, Any]:
    """Retain reviewed bytes when the claimed source entry was substituted."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = os.urandom(8).hex()
    recovery_name = (
        f"{name}.intended-recovery-{timestamp}-{fingerprint[:12]}-{suffix}.json"
    )
    recovery_path = backup_directory / recovery_name
    held_metadata = os.fstat(source_descriptor)
    intended_identity = (held_metadata.st_dev, held_metadata.st_ino)
    recovery_entries: list[dict[str, Any]] = []
    link_published = False
    link_error: BananaError | None = None
    try:
        _link_held_preset_descriptor_at(
            source_descriptor,
            backup_directory_descriptor,
            recovery_name,
        )
        link_published = True
        recovery_metadata = os.stat(
            recovery_name,
            dir_fd=backup_directory_descriptor,
            follow_symlinks=False,
        )
        current_held = os.fstat(source_descriptor)
        if (
            not stat.S_ISREG(recovery_metadata.st_mode)
            or (recovery_metadata.st_dev, recovery_metadata.st_ino) != intended_identity
            or (current_held.st_dev, current_held.st_ino) != intended_identity
            or current_held.st_nlink < 1
        ):
            raise BananaError(
                "preset_backup_failed",
                "The intended legacy inode recovery link could not be verified.",
            )
        os.fsync(backup_directory_descriptor)
        link_receipt = _preset_recovery_entry_receipt(
            method="held_inode_link",
            path=recovery_path,
            directory_descriptor=backup_directory_descriptor,
            directory_path=backup_directory,
            expected_identity=intended_identity,
            publication_succeeded=True,
            verification_complete=True,
            exact_reviewed_bytes=True,
        )
        if not link_receipt["path_binding_verified"]:
            raise BananaError(
                "preset_backup_failed",
                "The intended legacy inode recovery path could not be verified.",
            )
        recovery_entries.append(link_receipt)
        return {
            "retained": True,
            "method": "held_inode_link",
            "path": str(recovery_path),
            "path_binding_verified": link_receipt["path_binding_verified"],
            "device": recovery_metadata.st_dev,
            "inode": recovery_metadata.st_ino,
            "link_count": current_held.st_nlink,
            "exact_reviewed_bytes": True,
            "recovery_entries": recovery_entries,
        }
    except BananaError as exc:
        link_error = exc
    except OSError:
        link_error = BananaError(
            "preset_backup_failed",
            "The intended legacy inode could not be linked into private recovery.",
        )

    link_receipt = _preset_recovery_entry_receipt(
        method="held_inode_link",
        path=recovery_path,
        directory_descriptor=backup_directory_descriptor,
        directory_path=backup_directory,
        expected_identity=intended_identity,
        publication_succeeded=link_published,
        verification_complete=False,
        exact_reviewed_bytes=True,
    )
    if link_published or link_receipt["entry_observed"]:
        recovery_entries.append(link_receipt)

    copy_name = f"{name}.intended-copy-{timestamp}-{fingerprint[:12]}-{suffix}.json"
    copy_path = backup_directory / copy_name
    copy_descriptor: int | None = None
    copy_identity: tuple[int, int] | None = None
    copy_published = False
    try:
        copy_identity = _atomic_write_at(
            backup_directory_descriptor,
            copy_name,
            raw,
            replace=False,
            expected_directory=backup_directory,
        )
        copy_published = True
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        copy_descriptor = os.open(
            copy_name,
            flags,
            dir_fd=backup_directory_descriptor,
        )
        copy_metadata = os.fstat(copy_descriptor)
        copy_raw = _bounded_preset_descriptor_read(copy_descriptor, name=name)
        if (
            not stat.S_ISREG(copy_metadata.st_mode)
            or copy_metadata.st_nlink != 1
            or (copy_metadata.st_dev, copy_metadata.st_ino) != copy_identity
            or stat.S_IMODE(copy_metadata.st_mode) != 0o600
            or copy_raw != raw
            or not _preset_descriptor_entry_matches(
                backup_directory_descriptor,
                copy_name,
                copy_descriptor,
            )
        ):
            raise BananaError(
                "preset_backup_failed",
                "The intended legacy byte recovery copy could not be verified.",
            )
        os.fsync(copy_descriptor)
        os.fsync(backup_directory_descriptor)
        copy_receipt = _preset_recovery_entry_receipt(
            method="exact_reviewed_bytes_copy",
            path=copy_path,
            directory_descriptor=backup_directory_descriptor,
            directory_path=backup_directory,
            expected_identity=copy_identity,
            publication_succeeded=True,
            verification_complete=True,
            exact_reviewed_bytes=True,
        )
        if not copy_receipt["path_binding_verified"]:
            raise BananaError(
                "preset_backup_failed",
                "The intended legacy byte recovery copy path could not be verified.",
            )
        recovery_entries.append(copy_receipt)
        return {
            "retained": True,
            "method": "exact_reviewed_bytes_copy",
            "path": str(copy_path),
            "path_binding_verified": copy_receipt["path_binding_verified"],
            "device": copy_metadata.st_dev,
            "inode": copy_metadata.st_ino,
            "link_count": copy_metadata.st_nlink,
            "mode": stat.S_IMODE(copy_metadata.st_mode),
            "exact_reviewed_bytes": True,
            "held_inode_link_error": (
                link_error.as_dict() if link_error is not None else None
            ),
            "recovery_entries": recovery_entries,
        }
    except (BananaError, OSError) as exc:
        normalized = (
            exc
            if isinstance(exc, BananaError)
            else BananaError(
                "preset_backup_failed",
                "The intended legacy bytes could not be copied into private recovery.",
            )
        )
        copy_receipt = _preset_recovery_entry_receipt(
            method="exact_reviewed_bytes_copy",
            path=copy_path,
            directory_descriptor=backup_directory_descriptor,
            directory_path=backup_directory,
            expected_identity=copy_identity,
            publication_succeeded=copy_published,
            verification_complete=False,
            exact_reviewed_bytes=False,
        )
        if copy_published or copy_receipt["entry_observed"]:
            recovery_entries.append(copy_receipt)
        retained_entry = next(
            (
                entry
                for entry in recovery_entries
                if entry["path_binding_verified"] and entry["exact_reviewed_bytes"]
            ),
            None,
        )
        return {
            "retained": retained_entry is not None,
            "method": (
                retained_entry["method"]
                if retained_entry is not None
                else "unavailable"
            ),
            "path": (
                retained_entry["path"] if retained_entry is not None else str(copy_path)
            ),
            "path_binding_verified": (
                retained_entry["path_binding_verified"]
                if retained_entry is not None
                else False
            ),
            "exact_reviewed_bytes": retained_entry is not None,
            "held_inode_link_error": (
                link_error.as_dict() if link_error is not None else None
            ),
            "copy_error": normalized.as_dict(),
            "recovery_entries": recovery_entries,
        }
    finally:
        if copy_descriptor is not None:
            os.close(copy_descriptor)


def _preset_recovery_entry_receipt(
    *,
    method: str,
    path: Path,
    directory_descriptor: int,
    directory_path: Path,
    expected_identity: tuple[int, int] | None,
    publication_succeeded: bool,
    verification_complete: bool,
    exact_reviewed_bytes: bool,
) -> dict[str, Any]:
    """Describe one observed recovery name without conflating its bindings."""
    identity = _preset_entry_identity(directory_descriptor, path.name)
    observed_identity = (
        identity
        if identity is not None and not identity.get("inspection_failed", False)
        else None
    )
    entry_observed = observed_identity is not None
    identity_binding_verified = bool(
        observed_identity is not None
        and expected_identity is not None
        and observed_identity["regular_file"]
        and (observed_identity["device"], observed_identity["inode"])
        == expected_identity
    )
    directory_binding_verified = _directory_path_matches_fd(
        directory_path,
        directory_descriptor,
    )
    receipt: dict[str, Any] = {
        "method": method,
        "path": str(path),
        "publication_succeeded": publication_succeeded,
        "verification_complete": verification_complete,
        "entry_observed": entry_observed,
        "identity_binding_verified": identity_binding_verified,
        "directory_binding_verified": directory_binding_verified,
        "path_binding_verified": (
            directory_binding_verified and identity_binding_verified
        ),
        "exact_reviewed_bytes": (exact_reviewed_bytes and identity_binding_verified),
        "identity": identity,
    }
    if observed_identity is not None:
        receipt.update(
            {
                "device": observed_identity["device"],
                "inode": observed_identity["inode"],
                "link_count": observed_identity["link_count"],
            }
        )
    return receipt


def _preset_entry_identity(
    directory_descriptor: int,
    entry_name: str,
) -> dict[str, Any] | None:
    try:
        metadata = os.stat(
            entry_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None
    except OSError:
        return {"inspection_failed": True}
    return {
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "link_count": metadata.st_nlink,
        "regular_file": stat.S_ISREG(metadata.st_mode),
        "symbolic_link": stat.S_ISLNK(metadata.st_mode),
    }


def _recover_claimed_preset(
    *,
    source_directory_descriptor: int,
    source_path: Path,
    backup_directory_descriptor: int,
    backup_path: Path,
    backup_descriptor: int,
    source_directory_bound: bool,
    backup_directory_bound: bool,
    publication_attempted: bool,
    publication_succeeded: bool,
    expected_legacy_raw: bytes,
    expected_migrated_raw: bytes,
    name: str,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "attempted": True,
        "publication_attempted": publication_attempted,
        "publication_succeeded": publication_succeeded,
        "source_directory_binding_verified": source_directory_bound,
        "backup_directory_binding_verified": backup_directory_bound,
        "backup_last_known_path": str(backup_path),
        "backup_entry_name": backup_path.name,
        "restored": False,
    }
    try:
        held_metadata = os.fstat(backup_descriptor)
        exact_identity: dict[str, Any] = {
            "device": held_metadata.st_dev,
            "inode": held_metadata.st_ino,
            "link_count": held_metadata.st_nlink,
            "regular_file": stat.S_ISREG(held_metadata.st_mode),
        }
        details["exact_legacy_identity"] = exact_identity
        backup_directory_metadata = os.fstat(backup_directory_descriptor)
        source_directory_metadata = os.fstat(source_directory_descriptor)
        details["held_backup_directory_identity"] = {
            "device": backup_directory_metadata.st_dev,
            "inode": backup_directory_metadata.st_ino,
        }
        details["held_source_directory_identity"] = {
            "device": source_directory_metadata.st_dev,
            "inode": source_directory_metadata.st_ino,
        }
        backup_entry = _preset_entry_identity(
            backup_directory_descriptor,
            backup_path.name,
        )
        active_entry = _preset_entry_identity(
            source_directory_descriptor,
            source_path.name,
        )
        details["backup_entry"] = backup_entry
        details["active_entry"] = active_entry
        expected_identity = (held_metadata.st_dev, held_metadata.st_ino)
        try:
            held_raw = _bounded_preset_recovery_read(
                backup_descriptor,
                name=name,
            )
        except BaseException as inspection_error:
            details.update(
                {
                    "held_bytes_verified": False,
                    "backup_retained": None,
                    "retained_location": "unknown",
                    "cleanup_status": "recovery_bytes_inspection_failed",
                    "recovery_exception_type": type(inspection_error).__name__,
                    "migration_state_safe": False,
                }
            )
            return details
        held_bytes_verified = held_raw == expected_legacy_raw
        details["held_bytes_verified"] = held_bytes_verified
        if os.name != "nt":
            os.fchmod(backup_descriptor, 0o600)
        held_metadata = os.fstat(backup_descriptor)
        backup_private = bool(
            os.name == "nt" or stat.S_IMODE(held_metadata.st_mode) == 0o600
        )
        source_directory_bound = bool(
            source_directory_bound
            and _directory_path_matches_fd(
                source_path.parent,
                source_directory_descriptor,
            )
        )
        backup_directory_bound = bool(
            backup_directory_bound
            and _directory_path_matches_fd(
                backup_path.parent,
                backup_directory_descriptor,
            )
        )
        backup_entry = _preset_entry_identity(
            backup_directory_descriptor,
            backup_path.name,
        )
        active_entry = _preset_entry_identity(
            source_directory_descriptor,
            source_path.name,
        )
        details.update(
            {
                "source_directory_binding_verified": source_directory_bound,
                "backup_directory_binding_verified": backup_directory_bound,
                "backup_entry": backup_entry,
                "active_entry": active_entry,
            }
        )
        details["retained_backup_private_mode_verified"] = backup_private
        details["exact_legacy_identity"] = {
            "device": held_metadata.st_dev,
            "inode": held_metadata.st_ino,
            "link_count": held_metadata.st_nlink,
            "regular_file": stat.S_ISREG(held_metadata.st_mode),
        }

        def entry_is_exact(entry: dict[str, Any] | None) -> bool:
            return bool(
                entry is not None
                and not entry.get("inspection_failed", False)
                and entry.get("regular_file") is True
                and entry.get("symbolic_link") is False
                and (entry.get("device"), entry.get("inode")) == expected_identity
            )

        backup_entry_bound = bool(
            entry_is_exact(backup_entry)
            and held_bytes_verified
            and held_metadata.st_nlink == 1
            and backup_entry is not None
            and backup_entry.get("link_count") == 1
            and backup_private
        )
        active_entry_exact = entry_is_exact(active_entry)
        details["backup_entry_identity_verified"] = backup_entry_bound
        details["backup_public_path_binding_verified"] = bool(
            backup_directory_bound and backup_entry_bound
        )
        details["active_entry_exact_legacy_identity"] = active_entry_exact

        active_present = active_entry is not None
        details["active_entry_present"] = active_present
        if active_present:
            active_migrated_exact, active_migrated_details = _exact_preset_publication(
                source_directory_descriptor=source_directory_descriptor,
                source_path=source_path,
                expected_raw=expected_migrated_raw,
                name=name,
                disallowed_identity=expected_identity,
            )
            active_recovered_exact, active_recovered_details = (
                _exact_preset_publication(
                    source_directory_descriptor=source_directory_descriptor,
                    source_path=source_path,
                    expected_raw=expected_legacy_raw,
                    name=name,
                    disallowed_identity=expected_identity,
                )
            )
            details["active_migrated_publication"] = active_migrated_details
            details["active_entry_exact_migrated_publication"] = active_migrated_exact
            details["active_recovered_legacy_publication"] = active_recovered_details
            details["active_entry_exact_recovered_legacy"] = active_recovered_exact
            details["backup_retained"] = backup_entry_bound
            legacy_safe = bool(
                active_recovered_exact
                and backup_entry_bound
                and source_directory_bound
                and backup_directory_bound
            )
            migrated_safe = bool(
                active_migrated_exact
                and backup_entry_bound
                and source_directory_bound
                and backup_directory_bound
            )
            if legacy_safe:
                details["restored"] = True
                details["retained_location"] = (
                    "verified_independent_active_copy_and_backup_inode"
                )
                details["cleanup_status"] = (
                    "exact_independent_active_copy_and_backup_inode_retained"
                )
            elif migrated_safe:
                details["retained_location"] = (
                    "verified_migrated_active_and_backup_inode"
                )
                details["cleanup_status"] = (
                    "exact_migrated_active_and_legacy_backup_retained"
                )
            elif backup_entry_bound and backup_directory_bound:
                details["retained_location"] = "verified_backup_entry"
                details["cleanup_status"] = "backup_retained_active_entry_present"
            elif backup_entry_bound:
                details["retained_location"] = "held_backup_directory_entry"
                details["cleanup_status"] = (
                    "backup_retained_active_entry_present_directory_unbound"
                )
            else:
                details["retained_location"] = "linked_path_not_safely_located"
                details["cleanup_status"] = (
                    "active_entry_present_exact_backup_not_located"
                )
            details["migration_state_safe"] = bool(legacy_safe or migrated_safe)
            return details

        if (
            not source_directory_bound
            or not backup_directory_bound
            or not backup_entry_bound
            or held_metadata.st_nlink != 1
        ):
            details["backup_retained"] = backup_entry_bound
            if backup_entry_bound:
                details["retained_location"] = "held_backup_directory_entry"
            elif held_metadata.st_nlink >= 1:
                details["retained_location"] = "linked_path_not_safely_located"
            else:
                details["retained_location"] = "held_descriptor_only"
            details["cleanup_status"] = "backup_retained_unbound_no_restore"
            details["migration_state_safe"] = False
            return details

        try:
            restored = _restore_claimed_preset_at(
                source_directory_descriptor,
                source_path,
                backup_directory_descriptor,
                backup_path.name,
                backup_descriptor,
                expected_raw=expected_legacy_raw,
                name=name,
            )
        except BananaError as exc:
            current_held = os.fstat(backup_descriptor)
            current_backup = _preset_entry_identity(
                backup_directory_descriptor,
                backup_path.name,
            )
            current_active = _preset_entry_identity(
                source_directory_descriptor,
                source_path.name,
            )
            current_expected = (current_held.st_dev, current_held.st_ino)
            current_backup_exact = bool(
                current_backup is not None
                and current_backup.get("regular_file") is True
                and (
                    current_backup.get("device"),
                    current_backup.get("inode"),
                )
                == current_expected
            )
            current_active_exact = bool(
                current_active is not None
                and current_active.get("regular_file") is True
                and (
                    current_active.get("device"),
                    current_active.get("inode"),
                )
                == current_expected
            )
            details["backup_entry"] = current_backup
            details["active_entry"] = current_active
            details["active_entry_present"] = current_active is not None
            details["active_entry_exact_legacy_identity"] = current_active_exact
            details["backup_retained"] = current_backup_exact
            if current_backup_exact and current_active_exact:
                details["retained_location"] = "verified_active_and_held_backup_entries"
            elif current_backup_exact:
                details["retained_location"] = "verified_backup_entry"
            elif current_active_exact:
                details["retained_location"] = "verified_active_entry"
            else:
                details["retained_location"] = "linked_path_not_safely_located"
            details["cleanup_status"] = "restore_failed_backup_retained"
            details["recovery_error"] = exc.as_dict()
            details["migration_state_safe"] = False
            return details

        if not restored:
            current_held = os.fstat(backup_descriptor)
            details["active_entry"] = _preset_entry_identity(
                source_directory_descriptor,
                source_path.name,
            )
            details["active_entry_present"] = details["active_entry"] is not None
            current_backup = _preset_entry_identity(
                backup_directory_descriptor,
                backup_path.name,
            )
            details["backup_entry"] = current_backup
            details["backup_retained"] = bool(
                current_backup is not None
                and current_backup.get("regular_file") is True
                and (
                    current_backup.get("device"),
                    current_backup.get("inode"),
                )
                == (current_held.st_dev, current_held.st_ino)
            )
            details["retained_location"] = (
                "verified_backup_entry"
                if details["backup_retained"]
                else "linked_path_not_safely_located"
            )
            details["cleanup_status"] = "backup_retained_active_entry_race"
            details["migration_state_safe"] = False
            return details

        restored_metadata = os.fstat(backup_descriptor)
        active_recovered_exact, active_recovered_details = _exact_preset_publication(
            source_directory_descriptor=source_directory_descriptor,
            source_path=source_path,
            expected_raw=expected_legacy_raw,
            name=name,
            disallowed_identity=(
                restored_metadata.st_dev,
                restored_metadata.st_ino,
            ),
        )
        restored_raw = _bounded_preset_recovery_read(
            backup_descriptor,
            name=name,
        )
        retained_backup_exact = bool(
            restored_metadata.st_nlink == 1
            and restored_raw == expected_legacy_raw
            and (os.name == "nt" or stat.S_IMODE(restored_metadata.st_mode) == 0o600)
            and _preset_descriptor_entry_matches(
                backup_directory_descriptor,
                backup_path.name,
                backup_descriptor,
            )
            and _directory_path_matches_fd(
                backup_path.parent,
                backup_directory_descriptor,
            )
        )
        recovered = bool(active_recovered_exact and retained_backup_exact)
        details["restored"] = recovered
        details["backup_retained"] = retained_backup_exact
        details["retained_location"] = (
            "verified_independent_active_copy_and_backup_inode"
            if recovered
            else "recovery_copy_or_backup_verification_failed"
        )
        details["cleanup_status"] = (
            "exact_independent_active_copy_and_backup_inode_retained"
            if recovered
            else "recovery_copy_verification_failed"
        )
        details["exact_legacy_identity"] = {
            "device": restored_metadata.st_dev,
            "inode": restored_metadata.st_ino,
            "link_count": restored_metadata.st_nlink,
            "regular_file": stat.S_ISREG(restored_metadata.st_mode),
        }
        details["active_entry"] = _preset_entry_identity(
            source_directory_descriptor,
            source_path.name,
        )
        details["backup_entry"] = _preset_entry_identity(
            backup_directory_descriptor,
            backup_path.name,
        )
        details["active_entry_present"] = True
        details["active_entry_exact_legacy_identity"] = False
        details["active_entry_exact_recovered_legacy"] = active_recovered_exact
        details["active_recovered_legacy_publication"] = active_recovered_details
        details["backup_entry_identity_verified"] = retained_backup_exact
        details["backup_public_path_binding_verified"] = retained_backup_exact
        details["held_bytes_verified"] = restored_raw == expected_legacy_raw
        details["migration_state_safe"] = recovered
        return details
    except BaseException as exc:
        details["backup_retained"] = None
        details["retained_location"] = "unknown"
        details["cleanup_status"] = "recovery_inspection_failed"
        details["recovery_error"] = BananaError(
            "preset_migration_recovery_failed",
            "Preset migration recovery could not be inspected safely.",
        ).as_dict()
        details["recovery_exception_type"] = type(exc).__name__
        details["migration_state_safe"] = False
        return details


def _exact_preset_publication(
    *,
    source_directory_descriptor: int,
    source_path: Path,
    expected_raw: bytes,
    name: str,
    disallowed_identity: tuple[int, int] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Verify one exact private single-link preset through its held directory."""
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
        raw = _bounded_preset_recovery_read(descriptor, name=name)
        path_bound = _preset_descriptor_entry_matches(
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
                "link_count": metadata.st_nlink,
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


def _serialized_preset(proposal: dict[str, Any]) -> bytes:
    return (
        json.dumps(proposal, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _migrate_confirmed_preset_with_descriptors(
    name: str,
    source: Path,
    confirmation: str,
) -> tuple[Path, dict[str, Any], str]:
    banana_home = presets_directory().parent
    try:
        home_directory_descriptor = _open_secure_directory(banana_home)
    except BananaError as exc:
        raise BananaError(
            "preset_source_directory_changed",
            "The preset state directory could not be opened without following redirects.",
        ) from exc
    if home_directory_descriptor is None:
        raise BananaError(
            "preset_migration_unavailable",
            "This platform cannot bind confirmed preset migration to held source and backup directories. No preset was changed.",
        )

    source_directory_descriptor: int | None = None
    source_descriptor: int | None = None
    backup_root_descriptor: int | None = None
    backup_directory_descriptor: int | None = None
    backup_descriptor: int | None = None
    claimed = False
    completed = False
    publication_attempted = False
    publication_succeeded = False
    backup_name = ""
    backup_path: Path | None = None
    backups_root: Path | None = None
    backup_directory: Path | None = None
    expected_legacy_raw: bytes | None = None
    expected_migrated_raw: bytes | None = None

    def attach_recovery(error: BananaError) -> None:
        if not claimed or completed:
            return
        if (
            source_directory_descriptor is None
            or source_descriptor is None
            or backup_directory_descriptor is None
            or backup_path is None
            or backups_root is None
            or backup_directory is None
            or expected_legacy_raw is None
            or expected_migrated_raw is None
        ):
            recovery: dict[str, Any] = {
                "attempted": False,
                "publication_attempted": publication_attempted,
                "publication_succeeded": publication_succeeded,
                "cleanup_status": "recovery_context_unavailable",
            }
        else:
            try:
                recovery = _recover_claimed_preset(
                    source_directory_descriptor=source_directory_descriptor,
                    source_path=source,
                    backup_directory_descriptor=backup_directory_descriptor,
                    backup_path=backup_path,
                    backup_descriptor=source_descriptor,
                    source_directory_bound=_directory_path_matches_fd(
                        source.parent,
                        source_directory_descriptor,
                    ),
                    backup_directory_bound=_directory_path_matches_fd(
                        backup_directory,
                        backup_directory_descriptor,
                    ),
                    publication_attempted=publication_attempted,
                    publication_succeeded=publication_succeeded,
                    expected_legacy_raw=expected_legacy_raw,
                    expected_migrated_raw=expected_migrated_raw,
                    name=name,
                )
            except Exception as exc:
                recovery = {
                    "attempted": True,
                    "publication_attempted": publication_attempted,
                    "publication_succeeded": publication_succeeded,
                    "cleanup_status": "recovery_inspection_failed",
                    "recovery_exception_type": type(exc).__name__,
                }
        error.details = {**error.details, "migration_recovery": recovery}

    try:
        if not _directory_path_matches_fd(banana_home, home_directory_descriptor):
            raise BananaError(
                "preset_source_directory_changed",
                "The preset state directory changed before migration started.",
            )
        source_directory_descriptor = _open_preset_child_directory_at(
            home_directory_descriptor,
            "presets",
            source.parent,
            create=False,
            error_code="preset_source_directory_changed",
        )
        if not _directory_path_matches_fd(
            source.parent,
            source_directory_descriptor,
        ):
            raise BananaError(
                "preset_source_directory_changed",
                "The preset source directory changed before migration started.",
            )
        source_descriptor, raw = _open_confirmed_preset_source_at(
            source_directory_descriptor,
            source,
            name=name,
        )
        proposal = _legacy_v1_proposal(name, _decode_preset_json(raw, name=name))
        expected_legacy_raw = raw
        expected_migrated_raw = _serialized_preset(proposal)
        fingerprint = _migration_fingerprint(raw, proposal)
        if fingerprint != confirmation:
            raise BananaError(
                "migration_fingerprint_mismatch",
                "The preset changed after review. Run migrate-v1 --dry-run again.",
            )

        backups_root = banana_home / "backups"
        backup_directory = backups_root / "presets"
        if not _directory_path_matches_fd(
            banana_home,
            home_directory_descriptor,
        ) or not _directory_path_matches_fd(
            source.parent,
            source_directory_descriptor,
        ):
            raise BananaError(
                "preset_source_directory_changed",
                "A preset source directory changed before backup setup.",
            )
        backup_root_descriptor = _open_preset_child_directory_at(
            home_directory_descriptor,
            "backups",
            backups_root,
            create=True,
            error_code="preset_backup_directory_changed",
        )
        backup_directory_descriptor = _open_preset_child_directory_at(
            backup_root_descriptor,
            "presets",
            backup_directory,
            create=True,
            error_code="preset_backup_directory_changed",
        )
        _fsync_preset_directory_chain(
            backup_directory_descriptor,
            backup_root_descriptor,
            home_directory_descriptor,
            error_code="preset_backup_directory_changed",
        )
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_name = (
            f"{name}.v1-{timestamp}-{fingerprint[:12]}-{os.urandom(8).hex()}.json"
        )
        backup_path = backup_directory / backup_name

        source_metadata = os.fstat(source_descriptor)
        if source_metadata.st_nlink != 1 or not _preset_descriptor_entry_matches(
            source_directory_descriptor,
            source.name,
            source_descriptor,
        ):
            raise BananaError(
                "migration_fingerprint_mismatch",
                "The preset changed before it could be claimed.",
            )
        revalidated_raw = _bounded_preset_descriptor_read(
            source_descriptor,
            name=name,
        )
        revalidated_proposal = _legacy_v1_proposal(
            name,
            _decode_preset_json(revalidated_raw, name=name),
        )
        if (
            revalidated_raw != raw
            or revalidated_proposal != proposal
            or _migration_fingerprint(revalidated_raw, revalidated_proposal)
            != fingerprint
        ):
            raise BananaError(
                "migration_fingerprint_mismatch",
                "The preset changed during confirmation.",
            )
        if not _directory_path_matches_fd(
            source.parent,
            source_directory_descriptor,
        ):
            raise BananaError(
                "preset_source_directory_changed",
                "The preset source directory changed before backup claim.",
            )
        if not _directory_path_matches_fd(
            banana_home,
            home_directory_descriptor,
        ):
            raise BananaError(
                "preset_source_directory_changed",
                "The preset state directory changed before backup claim.",
            )
        if not _directory_path_matches_fd(
            backups_root,
            backup_root_descriptor,
        ):
            raise BananaError(
                "preset_backup_directory_changed",
                "The preset backup root changed before backup claim.",
            )
        if not _directory_path_matches_fd(
            backup_directory,
            backup_directory_descriptor,
        ):
            raise BananaError(
                "preset_backup_directory_changed",
                "The preset backup directory changed before backup claim.",
            )

        intended_identity = {
            "device": source_metadata.st_dev,
            "inode": source_metadata.st_ino,
            "link_count": source_metadata.st_nlink,
        }
        try:
            _exclusive_rename_at(
                source_directory_descriptor,
                source.name,
                backup_directory_descriptor,
                backup_name,
            )
        except FileExistsError as exc:
            raise BananaError(
                "preset_backup_failed",
                "The private migration backup destination was already claimed. The active legacy preset was preserved.",
                details={
                    "claim_completed": False,
                    "backup_path": str(backup_path),
                    "intended_legacy_identity": intended_identity,
                    "existing_backup_identity": _preset_entry_identity(
                        backup_directory_descriptor,
                        backup_name,
                    ),
                },
            ) from exc
        except BananaError as exc:
            raise BananaError(
                "preset_backup_failed",
                "The legacy preset could not be claimed with atomic no-replace semantics.",
                details={
                    "claim_completed": False,
                    "backup_path": str(backup_path),
                    "intended_legacy_identity": intended_identity,
                    "claim_error": exc.as_dict(),
                },
            ) from exc
        except OSError as exc:
            raise BananaError(
                "preset_backup_failed",
                "The legacy preset could not be claimed with atomic no-replace semantics.",
                details={
                    "claim_completed": False,
                    "backup_path": str(backup_path),
                    "intended_legacy_identity": intended_identity,
                },
            ) from exc
        except BaseException as exc:
            if isinstance(exc, Exception):
                raise
            source_directory_bound = _directory_path_matches_fd(
                source.parent,
                source_directory_descriptor,
            )
            backup_directory_bound = _directory_path_matches_fd(
                backup_directory,
                backup_directory_descriptor,
            )
            backup_entry_exact = _preset_descriptor_entry_matches(
                backup_directory_descriptor,
                backup_name,
                source_descriptor,
            )
            active_entry_exact = _preset_descriptor_entry_matches(
                source_directory_descriptor,
                source.name,
                source_descriptor,
            )
            if backup_entry_exact and not active_entry_exact:
                claimed = True
                recovery = _recover_claimed_preset(
                    source_directory_descriptor=source_directory_descriptor,
                    source_path=source,
                    backup_directory_descriptor=backup_directory_descriptor,
                    backup_path=backup_path,
                    backup_descriptor=source_descriptor,
                    source_directory_bound=source_directory_bound,
                    backup_directory_bound=backup_directory_bound,
                    publication_attempted=False,
                    publication_succeeded=False,
                    expected_legacy_raw=raw,
                    expected_migrated_raw=_serialized_preset(proposal),
                    name=name,
                )
                if recovery.get("restored") is True:
                    raise
                raise BananaError(
                    "preset_migration_recovery_failed",
                    "The interrupted preset claim could not be restored automatically. The exact retained legacy identity is recorded for recovery.",
                    details={"migration_recovery": recovery},
                ) from exc
            raise
        claimed = True

        source_metadata = os.fstat(source_descriptor)
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
            not stat.S_ISREG(source_metadata.st_mode)
            or source_metadata.st_nlink != 1
            or not stat.S_ISREG(backup_metadata.st_mode)
            or backup_metadata.st_nlink != 1
            or backup_metadata.st_dev != source_metadata.st_dev
            or backup_metadata.st_ino != source_metadata.st_ino
        ):
            intended_recovery = _retain_substituted_preset_source(
                name=name,
                source_descriptor=source_descriptor,
                raw=raw,
                fingerprint=fingerprint,
                backup_directory_descriptor=backup_directory_descriptor,
                backup_directory=backup_directory,
            )
            raise BananaError(
                "migration_fingerprint_mismatch",
                "The claimed legacy preset backup identity did not match its source.",
                details={
                    "claim_completed": True,
                    "backup_path": str(backup_path),
                    "intended_legacy_identity": {
                        "device": source_metadata.st_dev,
                        "inode": source_metadata.st_ino,
                        "link_count": source_metadata.st_nlink,
                    },
                    "claimed_backup_identity": {
                        "device": backup_metadata.st_dev,
                        "inode": backup_metadata.st_ino,
                        "link_count": backup_metadata.st_nlink,
                        "regular_file": stat.S_ISREG(backup_metadata.st_mode),
                    },
                    "intended_recovery": intended_recovery,
                    "intended_path_unknown": True,
                    "cleanup_status": (
                        "substituted_claim_and_intended_source_retained_for_review"
                        if intended_recovery["retained"]
                        else "substituted_claim_retained_intended_recovery_failed"
                    ),
                },
            )
        os.fchmod(backup_descriptor, 0o600)
        backup_metadata = os.fstat(backup_descriptor)
        if (
            backup_metadata.st_nlink != 1
            or stat.S_IMODE(backup_metadata.st_mode) != 0o600
        ):
            raise BananaError(
                "preset_backup_failed",
                "The private legacy preset backup permissions could not be verified.",
            )
        claimed_raw = _bounded_preset_descriptor_read(
            backup_descriptor,
            name=name,
        )
        claimed_proposal = _legacy_v1_proposal(
            name,
            _decode_preset_json(claimed_raw, name=name),
        )
        if (
            claimed_raw != raw
            or claimed_proposal != proposal
            or not _preset_descriptor_entry_matches(
                backup_directory_descriptor,
                backup_name,
                backup_descriptor,
            )
            or _migration_fingerprint(claimed_raw, claimed_proposal) != fingerprint
        ):
            raise BananaError(
                "migration_fingerprint_mismatch",
                "The claimed legacy preset backup failed exact revalidation.",
            )
        os.fsync(backup_descriptor)
        os.fsync(backup_directory_descriptor)

        if not _directory_path_matches_fd(
            source.parent,
            source_directory_descriptor,
        ):
            raise BananaError(
                "preset_source_directory_changed",
                "The preset source directory changed after backup claim.",
            )
        if not _directory_path_matches_fd(
            banana_home,
            home_directory_descriptor,
        ):
            raise BananaError(
                "preset_source_directory_changed",
                "The preset state directory changed after backup claim.",
            )
        if not _directory_path_matches_fd(
            backups_root,
            backup_root_descriptor,
        ):
            raise BananaError(
                "preset_backup_directory_changed",
                "The preset backup root changed after backup claim.",
            )
        if not _directory_path_matches_fd(
            backup_directory,
            backup_directory_descriptor,
        ):
            raise BananaError(
                "preset_backup_directory_changed",
                "The preset backup directory changed after backup claim.",
            )

        publication_attempted = True
        try:
            _atomic_write_at(
                source_directory_descriptor,
                source.name,
                _serialized_preset(proposal),
                replace=False,
                expected_directory=source.parent,
            )
        except BananaError as exc:
            if exc.code == "output_exists":
                retained_details = (
                    {"backup_path": str(backup_path)}
                    if _directory_path_matches_fd(
                        backup_directory,
                        backup_directory_descriptor,
                    )
                    else None
                )
                raise BananaError(
                    "migration_fingerprint_mismatch",
                    "The preset path was recreated during migration. The competing active bytes and exact backup were preserved.",
                    details=retained_details,
                ) from exc
            if exc.code == "output_directory_changed":
                raise BananaError(
                    "preset_source_directory_changed",
                    "The preset source directory changed during active publication.",
                ) from exc
            raise
        publication_succeeded = True

        active_flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            active_flags |= os.O_NOFOLLOW
        active_descriptor = os.open(
            source.name,
            active_flags,
            dir_fd=source_directory_descriptor,
        )
        try:
            active_metadata = os.fstat(active_descriptor)
            active_raw = _bounded_preset_descriptor_read(
                active_descriptor,
                name=name,
            )
            if (
                not stat.S_ISREG(active_metadata.st_mode)
                or active_metadata.st_nlink != 1
                or (os.name != "nt" and stat.S_IMODE(active_metadata.st_mode) != 0o600)
                or active_raw != _serialized_preset(proposal)
                or not _preset_descriptor_entry_matches(
                    source_directory_descriptor,
                    source.name,
                    active_descriptor,
                )
            ):
                raise BananaError(
                    "preset_migration_failed",
                    "The migrated preset failed final active-file verification.",
                )
        finally:
            os.close(active_descriptor)

        final_backup_raw = _bounded_preset_descriptor_read(
            backup_descriptor,
            name=name,
        )
        if (
            final_backup_raw != raw
            or (
                os.name != "nt"
                and stat.S_IMODE(os.fstat(backup_descriptor).st_mode) != 0o600
            )
            or not _preset_descriptor_entry_matches(
                backup_directory_descriptor,
                backup_name,
                backup_descriptor,
            )
            or not _directory_path_matches_fd(
                source.parent,
                source_directory_descriptor,
            )
            or not _directory_path_matches_fd(
                banana_home,
                home_directory_descriptor,
            )
            or not _directory_path_matches_fd(
                backups_root,
                backup_root_descriptor,
            )
            or not _directory_path_matches_fd(
                backup_directory,
                backup_directory_descriptor,
            )
        ):
            raise BananaError(
                "preset_migration_directory_changed",
                "A preset migration directory changed before final identity verification.",
            )
        completed = True
        return backup_path, proposal, fingerprint
    except BananaError as exc:
        attach_recovery(exc)
        raise
    except OSError as exc:
        error = BananaError(
            "preset_migration_failed",
            "Descriptor-bound preset migration failed safely.",
        )
        attach_recovery(error)
        raise error from exc
    except Exception as exc:
        error = BananaError(
            "preset_migration_failed",
            "Descriptor-bound preset migration failed safely.",
        )
        attach_recovery(error)
        raise error from exc
    except BaseException as exc:
        error = BananaError(
            "preset_migration_recovery_failed",
            "The interrupted preset migration could not prove an exact migrated preset or restore the exact retained legacy preset safely.",
            details={"interrupted_exception_type": type(exc).__name__},
        )
        attach_recovery(error)
        interruption_recovery = error.details.get("migration_recovery")
        if (
            isinstance(interruption_recovery, dict)
            and interruption_recovery.get("migration_state_safe") is True
        ):
            raise
        raise error from exc
    finally:
        if backup_descriptor is not None:
            os.close(backup_descriptor)
        if source_descriptor is not None:
            os.close(source_descriptor)
        if backup_directory_descriptor is not None:
            os.close(backup_directory_descriptor)
        if backup_root_descriptor is not None:
            os.close(backup_root_descriptor)
        if source_directory_descriptor is not None:
            os.close(source_directory_descriptor)
        os.close(home_directory_descriptor)


def _parse_references(raw_values: list[str]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_values):
        if len(raw) > MAX_REFERENCE_JSON_CHARS:
            raise BananaError(
                "invalid_preset",
                f"Reference {index + 1} exceeds the {MAX_REFERENCE_JSON_CHARS}-character JSON limit.",
            )
        try:
            parsed = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            raise BananaError(
                "invalid_preset",
                f"Reference {index + 1} must be a valid bounded JSON object.",
            ) from exc
        if not isinstance(parsed, dict):
            raise BananaError(
                "invalid_preset", f"Reference {index + 1} must be a JSON object."
            )
        references.append(parsed)
    return references


def load_preset(name: str) -> dict[str, Any]:
    path = preset_path(name)
    raw = _read_preset_bytes(path, name=name)
    preset = validate_preset(_decode_preset_json(raw, name=name))
    if preset["name"] != name:
        raise BananaError(
            "invalid_preset",
            "Preset embedded name does not match its requested filename.",
        )
    return preset


def cmd_list(_args: argparse.Namespace) -> None:
    directory = _secure_directory()
    _require_no_preset_migration_residue(None)
    paths = sorted(directory.glob("*.json"))
    output = []
    for path in paths:
        try:
            preset = load_preset(path.stem)
            output.append(
                {"name": preset["name"], "description": preset.get("description", "")}
            )
        except BananaError as exc:
            output.append({"name": path.stem, "error": exc.code})
    print(json.dumps({"presets": output}, indent=2))


def cmd_show(args: argparse.Namespace) -> None:
    print(json.dumps(load_preset(args.name), indent=2, ensure_ascii=False))


def _split_colors(raw: str) -> list[str]:
    colors = [item.strip() for item in raw.split(",") if item.strip()]
    if any(not HEX_PATTERN.fullmatch(item) for item in colors):
        raise BananaError(
            "invalid_palette", "Colors must be comma-separated six-digit hex values."
        )
    return colors


def cmd_create(args: argparse.Namespace) -> None:
    path = preset_path(args.name)
    preset = validate_preset(
        {
            "schema_version": 2,
            "name": args.name,
            "description": args.description,
            "visual_thesis": args.visual_thesis,
            "signature_element": args.signature_element,
            "palette": _split_colors(args.colors),
            "typography": args.typography,
            "photography": args.photography,
            "illustration": args.illustration,
            "copy_rules": args.copy_rules,
            "locks": args.lock,
            "freedoms": args.freedom,
            "references": _parse_references(args.reference),
            "anti_references": args.anti_reference,
            "default_model": args.model,
            "default_aspect_ratio": args.ratio,
            "default_image_size": args.resolution,
        }
    )
    with _preset_lock(args.name):
        _require_no_preset_migration_residue(args.name)
        if path.exists() and not args.force:
            raise BananaError(
                "preset_exists",
                f"Preset '{args.name}' exists. Pass --force to replace it.",
            )
        _atomic_json(path, preset, replace=args.force)
    print(
        json.dumps(
            {"created": True, "path": str(path), "preset": preset},
            indent=2,
            ensure_ascii=False,
        )
    )


def cmd_migrate_v1(args: argparse.Namespace) -> None:
    path, raw, proposal, fingerprint = _migration_material(args.name)
    disclosure = _migration_disclosure(str(proposal["default_model"]))
    if args.dry_run:
        print(
            json.dumps(
                {
                    "migration": "preset_v1_to_v2",
                    "name": args.name,
                    "source_path": str(path),
                    "dry_run": True,
                    "will_write": False,
                    "network_called": False,
                    "requires_review": True,
                    "fingerprint": fingerprint,
                    "mapping": disclosure,
                    "proposal": proposal,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if args.confirm != fingerprint:
        raise BananaError(
            "migration_fingerprint_mismatch",
            "Confirmation does not match the reviewed migration. Run migrate-v1 --dry-run again.",
        )

    with _preset_lock(args.name):
        backup_path, current_proposal, current_fingerprint = (
            _migrate_confirmed_preset_with_descriptors(
                args.name,
                path,
                args.confirm,
            )
        )

    print(
        json.dumps(
            {
                "migration": "preset_v1_to_v2",
                "name": args.name,
                "migrated": True,
                "network_called": False,
                "requires_review": False,
                "fingerprint": current_fingerprint,
                "backup_path": str(backup_path),
                "mapping": disclosure,
                "preset": current_proposal,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def _open_preset_for_delete_at(
    directory_descriptor: int,
    path: Path,
    *,
    name: str,
) -> tuple[int, bytes]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor: int | None = None
    succeeded = False
    try:
        try:
            entry_metadata = os.stat(
                path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError as exc:
            _require_no_preset_migration_residue(name)
            raise BananaError(
                "preset_not_found",
                f"Preset '{name}' was not found.",
            ) from exc
        if (
            stat.S_ISLNK(entry_metadata.st_mode)
            or not stat.S_ISREG(entry_metadata.st_mode)
            or entry_metadata.st_nlink != 1
        ):
            raise BananaError(
                "unsafe_preset_delete",
                f"Preset '{name}' must be one regular, privately linked file before deletion.",
            )
        descriptor = os.open(path.name, flags, dir_fd=directory_descriptor)
        opened_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_metadata.st_mode)
            or opened_metadata.st_nlink != 1
            or (opened_metadata.st_dev, opened_metadata.st_ino)
            != (entry_metadata.st_dev, entry_metadata.st_ino)
            or not _preset_descriptor_entry_matches(
                directory_descriptor,
                path.name,
                descriptor,
            )
            or not _directory_path_matches_fd(path.parent, directory_descriptor)
        ):
            raise BananaError(
                "preset_delete_changed",
                f"Preset '{name}' changed while deletion opened it.",
            )
        raw = _bounded_preset_descriptor_read(descriptor, name=name)
        succeeded = True
        return descriptor, raw
    except BananaError:
        raise
    except OSError as exc:
        raise BananaError(
            "unsafe_preset_delete",
            f"Preset '{name}' could not be opened for identity-bound deletion.",
        ) from exc
    finally:
        if descriptor is not None and not succeeded:
            os.close(descriptor)


def _delete_preset_with_recovery(name: str, path: Path) -> Path:
    banana_home = presets_directory().parent
    try:
        home_directory_descriptor = _open_secure_directory(banana_home)
    except BananaError as exc:
        raise BananaError(
            "preset_delete_changed",
            "The preset state directory could not be opened without following redirects.",
        ) from exc
    if home_directory_descriptor is None:
        raise BananaError(
            "preset_delete_unavailable",
            "This platform cannot remove a preset with identity-bound recovery semantics. No preset was deleted.",
        )

    source_directory_descriptor: int | None = None
    source_descriptor: int | None = None
    backup_root_descriptor: int | None = None
    backup_directory_descriptor: int | None = None
    backup_path: Path | None = None
    backup_directory: Path | None = None
    source_raw: bytes | None = None
    intended_recovery: dict[str, Any] | None = None
    moved = False

    def attach_recovery(error: BananaError) -> None:
        nonlocal intended_recovery
        if (
            source_directory_descriptor is None
            or source_descriptor is None
            or backup_directory_descriptor is None
            or backup_directory is None
            or backup_path is None
            or source_raw is None
        ):
            return
        try:
            intended = os.fstat(source_descriptor)
            intended_identity = (intended.st_dev, intended.st_ino)
            recovery_entry = _preset_entry_identity(
                backup_directory_descriptor,
                backup_path.name,
            )
            active_entry = _preset_entry_identity(
                source_directory_descriptor,
                path.name,
            )
            recovery_exact = bool(
                recovery_entry is not None
                and recovery_entry.get("regular_file") is True
                and (
                    recovery_entry.get("device"),
                    recovery_entry.get("inode"),
                )
                == intended_identity
            )
            active_exact = bool(
                active_entry is not None
                and active_entry.get("regular_file") is True
                and (active_entry.get("device"), active_entry.get("inode"))
                == intended_identity
            )
            source_directory_bound = _directory_path_matches_fd(
                path.parent,
                source_directory_descriptor,
            )
            recovery_directory_bound = _directory_path_matches_fd(
                backup_directory,
                backup_directory_descriptor,
            )
            recovery_path_exact = recovery_exact and recovery_directory_bound
            active_path_exact = active_exact and source_directory_bound
            if (
                not recovery_path_exact
                and not active_path_exact
                and intended_recovery is None
            ):
                try:
                    intended_recovery = _retain_substituted_preset_source(
                        name=name,
                        source_descriptor=source_descriptor,
                        raw=source_raw,
                        fingerprint=hashlib.sha256(source_raw).hexdigest(),
                        backup_directory_descriptor=backup_directory_descriptor,
                        backup_directory=backup_directory,
                    )
                except Exception as exc:
                    intended_recovery = {
                        "retained": False,
                        "method": "unavailable",
                        "path_binding_verified": False,
                        "exact_reviewed_bytes": False,
                        "recovery_entries": [],
                        "retention_error": BananaError(
                            "preset_delete_recovery_failed",
                            "The reviewed preset could not be retained before its held descriptor closed.",
                            details={"exception_type": type(exc).__name__},
                        ).as_dict(),
                    }
            intended_recovery_retained = bool(
                intended_recovery is not None
                and intended_recovery.get("retained") is True
                and intended_recovery.get("path_binding_verified") is True
                and intended_recovery.get("exact_reviewed_bytes") is True
            )
            exact_reviewed_bytes_retained = bool(
                recovery_path_exact
                or active_path_exact
                or intended_recovery_retained
                or intended.st_nlink >= 1
            )
            byte_erasure_performed = bool(
                intended.st_nlink == 0 and not exact_reviewed_bytes_retained
            )
            if recovery_path_exact:
                cleanup_status = "exact_preset_retained_in_recoverable_backup"
            elif active_path_exact:
                cleanup_status = "exact_preset_retained_at_active_entry"
            elif intended_recovery_retained:
                cleanup_status = "exact_reviewed_preset_retained_in_private_recovery"
            elif intended.st_nlink >= 1:
                cleanup_status = "exact_preset_link_retained_at_unknown_path"
            else:
                cleanup_status = "exact_reviewed_preset_erased_on_descriptor_close"
            recovery = {
                "deletion_confirmed": False,
                "claim_completed": moved,
                "cleanup_status": cleanup_status,
                "intended_preset_identity": {
                    "device": intended.st_dev,
                    "inode": intended.st_ino,
                    "link_count": intended.st_nlink,
                    "regular_file": stat.S_ISREG(intended.st_mode),
                },
                "active_entry": active_entry,
                "active_entry_exact_preset": active_exact,
                "active_path_exact_preset": active_path_exact,
                "source_directory_binding_verified": source_directory_bound,
                "recovery_path": str(backup_path),
                "recovery_entry": recovery_entry,
                "recovery_entry_exact_preset": recovery_exact,
                "recovery_path_exact_preset": recovery_path_exact,
                "recovery_directory_binding_verified": recovery_directory_bound,
                "intended_recovery": intended_recovery,
                "exact_reviewed_bytes_retained": exact_reviewed_bytes_retained,
                "byte_erasure_performed": byte_erasure_performed,
            }
        except Exception as exc:
            recovery = {
                "deletion_confirmed": False,
                "cleanup_status": "delete_recovery_inspection_failed",
                "recovery_exception_type": type(exc).__name__,
                "byte_erasure_performed": None,
            }
        error.details = {**error.details, "delete_recovery": recovery}

    try:
        source_directory_descriptor = _open_preset_child_directory_at(
            home_directory_descriptor,
            "presets",
            path.parent,
            create=False,
            error_code="preset_delete_changed",
        )
        source_descriptor, source_raw = _open_preset_for_delete_at(
            source_directory_descriptor,
            path,
            name=name,
        )
        backups_root = banana_home / "backups"
        backup_directory = backups_root / "deleted-presets"
        backup_root_descriptor = _open_preset_child_directory_at(
            home_directory_descriptor,
            "backups",
            backups_root,
            create=True,
            error_code="preset_delete_failed",
        )
        backup_directory_descriptor = _open_preset_child_directory_at(
            backup_root_descriptor,
            "deleted-presets",
            backup_directory,
            create=True,
            error_code="preset_delete_failed",
        )
        _fsync_preset_directory_chain(
            backup_directory_descriptor,
            backup_root_descriptor,
            home_directory_descriptor,
            error_code="preset_delete_failed",
        )
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_name = f"{name}.deleted-{timestamp}-{os.urandom(8).hex()}.json"
        backup_path = backup_directory / backup_name

        if (
            not _directory_path_matches_fd(
                path.parent,
                source_directory_descriptor,
            )
            or not _directory_path_matches_fd(
                backup_directory,
                backup_directory_descriptor,
            )
            or not _preset_descriptor_entry_matches(
                source_directory_descriptor,
                path.name,
                source_descriptor,
            )
        ):
            raise BananaError(
                "preset_delete_changed",
                f"Preset '{name}' changed before its recoverable removal.",
            )
        try:
            _exclusive_rename_at(
                source_directory_descriptor,
                path.name,
                backup_directory_descriptor,
                backup_name,
            )
        except FileExistsError as exc:
            raise BananaError(
                "preset_delete_failed",
                "The recoverable deletion destination was already claimed. No preset was deleted.",
            ) from exc
        except BananaError as exc:
            raise BananaError(
                "preset_delete_failed",
                "The preset could not be removed with atomic no-replace semantics. No exact deletion was claimed.",
                details={"claim_error": exc.as_dict()},
            ) from exc
        moved = True

        intended = os.fstat(source_descriptor)
        recovery_entry = os.stat(
            backup_name,
            dir_fd=backup_directory_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(intended.st_mode)
            or intended.st_nlink != 1
            or not stat.S_ISREG(recovery_entry.st_mode)
            or recovery_entry.st_nlink != 1
            or (recovery_entry.st_dev, recovery_entry.st_ino)
            != (intended.st_dev, intended.st_ino)
        ):
            raise BananaError(
                "preset_delete_changed",
                "The preset source was substituted during deletion. No exact deletion was claimed; recovery details identify every observed or retained entry.",
            )
        os.fchmod(source_descriptor, 0o600)
        os.fsync(source_descriptor)
        _fsync_preset_directory_chain(
            backup_directory_descriptor,
            backup_root_descriptor,
            home_directory_descriptor,
            error_code="preset_delete_failed",
        )
        try:
            active_entry = os.stat(
                path.name,
                dir_fd=source_directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            active_entry = None
        if (
            active_entry is not None
            or not _preset_descriptor_entry_matches(
                backup_directory_descriptor,
                backup_name,
                source_descriptor,
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
                "preset_delete_changed",
                "Preset deletion could not complete final identity verification. Recovery details identify any retained entries.",
            )
        return backup_path
    except BananaError as exc:
        attach_recovery(exc)
        raise
    except OSError as exc:
        error = BananaError(
            "preset_delete_failed",
            "Preset deletion failed safely. No exact deletion was claimed.",
        )
        attach_recovery(error)
        raise error from exc
    except Exception as exc:
        error = BananaError(
            "preset_delete_failed",
            "Preset deletion failed safely. No exact deletion was claimed.",
        )
        attach_recovery(error)
        raise error from exc
    finally:
        if source_descriptor is not None:
            os.close(source_descriptor)
        if backup_directory_descriptor is not None:
            os.close(backup_directory_descriptor)
        if backup_root_descriptor is not None:
            os.close(backup_root_descriptor)
        if source_directory_descriptor is not None:
            os.close(source_directory_descriptor)
        os.close(home_directory_descriptor)


def cmd_delete(args: argparse.Namespace) -> None:
    if not args.confirm:
        raise BananaError(
            "confirmation_required", "Pass --confirm to delete the preset."
        )
    path = preset_path(args.name)
    with _preset_lock(args.name):
        backup_path = _delete_preset_with_recovery(args.name, path)
    print(
        json.dumps(
            {
                "deleted": True,
                "name": args.name,
                "active_entry_removed": True,
                "byte_erasure_performed": False,
                "recoverable_backup_path": str(backup_path),
            }
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = SecretSafeArgumentParser(description="Banana Claude visual-system presets")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List presets")
    show = sub.add_parser("show", help="Show and validate a preset")
    show.add_argument("name")

    create = sub.add_parser("create", help="Create a preset")
    create.add_argument("name")
    create.add_argument("--description", default="")
    create.add_argument("--visual-thesis", default="")
    create.add_argument("--signature-element", default="")
    create.add_argument("--colors", default="")
    create.add_argument("--typography", default="")
    create.add_argument("--photography", default="")
    create.add_argument("--illustration", default="")
    create.add_argument("--copy-rules", default="")
    create.add_argument("--lock", action="append", default=[])
    create.add_argument("--freedom", action="append", default=[])
    create.add_argument(
        "--reference",
        action="append",
        default=[],
        help="Reference JSON object with path, role, purpose, and optional subject_id; repeat as needed",
    )
    create.add_argument("--anti-reference", action="append", default=[])
    create.add_argument("--model", default="gemini-3.1-flash-image")
    create.add_argument("--ratio", default="16:9")
    create.add_argument("--resolution", default="1K")
    create.add_argument("--force", action="store_true")

    migrate = sub.add_parser(
        "migrate-v1", help="Review or confirm a legacy 1.4.1 preset migration"
    )
    migrate.add_argument("name")
    migration_action = migrate.add_mutually_exclusive_group(required=True)
    migration_action.add_argument("--dry-run", action="store_true")
    migration_action.add_argument("--confirm", metavar="FINGERPRINT")

    delete = sub.add_parser("delete", help="Delete a preset")
    delete.add_argument("name")
    delete.add_argument("--confirm", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    commands = {
        "list": cmd_list,
        "show": cmd_show,
        "create": cmd_create,
        "migrate-v1": cmd_migrate_v1,
        "delete": cmd_delete,
    }
    try:
        commands[args.command](args)
        return 0
    except BananaError as exc:
        print(json.dumps(exc.as_dict()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
