#!/usr/bin/env python3
"""Descriptor-bound lifecycle transactions for the standalone installer."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, NoReturn

MARKER_LIMIT = 16 * 1024
EXPECTED_NAME = "banana-claude"
TREE_FILE_LIMIT = 32 * 1024 * 1024
TREE_TOTAL_LIMIT = 128 * 1024 * 1024
TREE_ENTRY_LIMIT = 20_000
REQUIRED_REFERENCE_NAMES = frozenset(
    {
        "cost-tracking.md",
        "gemini-models.md",
        "mcp-tools.md",
        "models.json",
        "post-processing.md",
        "presets.md",
        "prompt-engineering.md",
        "review-and-recovery.md",
    }
)
REQUIRED_SCRIPT_NAMES = frozenset(
    {
        "approval_store.py",
        "banana_core.py",
        "batch.py",
        "cost_tracker.py",
        "doctor.py",
        "edit.py",
        "generate.py",
        "legacy_cleanup.py",
        "mcp_server.py",
        "portfolio.py",
        "presets.py",
        "typeset.py",
    }
)

TreeEntry = tuple[str, int, int, int, int, int, int, str]
TreeSnapshot = dict[str, TreeEntry]
SourceEntry = tuple[int, int, int, int, int, int, int, int]
SourceManifestEntry = tuple[str, int, int, int, int, int, int, int, str]
SourceManifest = dict[str, SourceManifestEntry]


class LifecycleError(RuntimeError):
    """Secret-safe installer transaction failure."""


class PostPublicationInterrupted(LifecycleError):
    """A signal-like interruption arrived after a no-replace publication."""


def _fail() -> NoReturn:
    raise LifecycleError("installer transaction failed safely")


def _directory_flags() -> int:
    if not hasattr(os, "O_DIRECTORY"):
        _fail()
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _identity_text(metadata: os.stat_result) -> str:
    device, inode = _identity(metadata)
    return f"{device}:{inode}"


def _require_identity_text(metadata: os.stat_result, expected: str) -> None:
    if _identity_text(metadata) != expected:
        _fail()


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return _identity(left) == _identity(right)


def _require_private_directory(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
    ):
        _fail()


def _tree_entry(metadata: os.stat_result, kind: str, digest: str = "") -> TreeEntry:
    return (
        kind,
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IMODE(metadata.st_mode),
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        digest,
    )


def _source_entry(metadata: os.stat_result) -> SourceEntry:
    return (
        stat.S_IFMT(metadata.st_mode),
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IMODE(metadata.st_mode),
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _source_manifest_entry(
    metadata: os.stat_result,
    kind: str,
    digest: str,
) -> SourceManifestEntry:
    return (
        kind,
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IMODE(metadata.st_mode),
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        digest,
    )


def _validate_basename(name: str) -> None:
    if not name or name in {".", ".."} or Path(name).name != name:
        _fail()


def _path_matches_metadata(path: Path, metadata: os.stat_result) -> bool:
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(current.st_mode) and _same_identity(current, metadata)


def _require_path_matches(path: Path, metadata: os.stat_result) -> None:
    if not _path_matches_metadata(path, metadata):
        _fail()


def _entry_identity(
    parent_descriptor: int, name: str
) -> tuple[os.stat_result, tuple[int, int]]:
    metadata = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    return metadata, _identity(metadata)


def _rename_no_replace(
    source_name: str,
    destination_name: str,
    *,
    source_parent: int,
    destination_parent: int,
) -> None:
    """Atomically rename one entry without replacing a competing destination."""
    _validate_basename(source_name)
    _validate_basename(destination_name)
    library = ctypes.CDLL(None, use_errno=True)
    rename_function: Any
    exclusive_flag: int
    if sys.platform.startswith("linux"):
        rename_function = getattr(library, "renameat2", None)
        exclusive_flag = 1
    elif sys.platform == "darwin":
        rename_function = getattr(library, "renameatx_np", None)
        exclusive_flag = 0x00000004
    else:
        _fail()
    if rename_function is None:
        _fail()
    rename_function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename_function.restype = ctypes.c_int
    result = rename_function(
        source_parent,
        os.fsencode(source_name),
        destination_parent,
        os.fsencode(destination_name),
        exclusive_flag,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), destination_name)


def _read_bounded(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total <= maximum:
        chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    raw = b"".join(chunks)
    if len(raw) > maximum:
        _fail()
    return raw


def _list_entries(directory_descriptor: int) -> list[str]:
    os.lseek(directory_descriptor, 0, os.SEEK_SET)
    return os.listdir(directory_descriptor)


def _validate_marker(directory_descriptor: int, marker_name: str) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(marker_name, flags, dir_fd=directory_descriptor)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > MARKER_LIMIT
        ):
            _fail()
        raw = _read_bounded(descriptor, MARKER_LIMIT)
        value: Any = json.loads(raw.decode("utf-8"))
        if not (
            isinstance(value, dict)
            and value.get("name") == EXPECTED_NAME
            and isinstance(value.get("version"), str)
            and bool(value["version"].strip())
        ):
            _fail()
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _open_bound_directory(path: Path) -> tuple[int, os.stat_result]:
    descriptor = os.open(path, _directory_flags())
    try:
        held = os.fstat(descriptor)
        _require_path_matches(path, held)
        return descriptor, held
    except BaseException:
        os.close(descriptor)
        raise


def managed_identity(path: Path, marker_name: str) -> str:
    descriptor, metadata = _open_bound_directory(path)
    try:
        _validate_marker(descriptor, marker_name)
        current = os.stat(path, follow_symlinks=False)
        if not _same_identity(metadata, current):
            _fail()
        return _identity_text(metadata)
    finally:
        os.close(descriptor)


def canonical_directory(path: Path) -> str:
    resolved = path.resolve(strict=True)
    descriptor, metadata = _open_bound_directory(resolved)
    try:
        _require_path_matches(resolved, metadata)
        return str(resolved)
    finally:
        os.close(descriptor)


def directory_identity(path: Path) -> str:
    descriptor, metadata = _open_bound_directory(path)
    try:
        _require_path_matches(path, metadata)
        return _identity_text(metadata)
    finally:
        os.close(descriptor)


def unique_absent_path(parent: Path, prefix: str, expected_parent_identity: str) -> str:
    _validate_basename(prefix)
    descriptor, metadata = _open_bound_directory(parent)
    try:
        _require_identity_text(metadata, expected_parent_identity)
        _require_path_matches(parent, metadata)
        for _ in range(16):
            name = f"{prefix}-{os.urandom(16).hex()}"
            if _destination_is_absent(descriptor, name):
                return str(parent / name)
        _fail()
    finally:
        os.close(descriptor)


def _destination_is_absent(parent_descriptor: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return True
    return False


def move_verified_managed(
    source: Path,
    destination: Path,
    marker_name: str,
    expected_identity: str,
    expected_source_parent_identity: str,
    expected_destination_parent_identity: str,
) -> None:
    _validate_basename(source.name)
    _validate_basename(destination.name)
    descriptors: list[int] = []
    source_metadata: os.stat_result | None = None
    source_parent = -1
    destination_parent = -1
    published = False
    try:
        source_parent, source_parent_metadata = _open_bound_directory(source.parent)
        descriptors.append(source_parent)
        destination_parent, destination_parent_metadata = _open_bound_directory(
            destination.parent
        )
        descriptors.append(destination_parent)
        _require_identity_text(source_parent_metadata, expected_source_parent_identity)
        _require_identity_text(
            destination_parent_metadata, expected_destination_parent_identity
        )
        source_descriptor = os.open(
            source.name,
            _directory_flags(),
            dir_fd=source_parent,
        )
        descriptors.append(source_descriptor)
        source_metadata = os.fstat(source_descriptor)
        if _identity_text(source_metadata) != expected_identity:
            _fail()
        source_entry = os.stat(
            source.name,
            dir_fd=source_parent,
            follow_symlinks=False,
        )
        if not stat.S_ISDIR(source_entry.st_mode) or not _same_identity(
            source_entry, source_metadata
        ):
            _fail()
        _validate_marker(source_descriptor, marker_name)
        if not _destination_is_absent(destination_parent, destination.name):
            _fail()

        _require_path_matches(source.parent, source_parent_metadata)
        _require_path_matches(destination.parent, destination_parent_metadata)
        current_source = os.stat(
            source.name,
            dir_fd=source_parent,
            follow_symlinks=False,
        )
        if not _same_identity(current_source, source_metadata):
            _fail()
        _rename_no_replace(
            source.name,
            destination.name,
            source_parent=source_parent,
            destination_parent=destination_parent,
        )
        published = True
        moved_entry = os.stat(
            destination.name,
            dir_fd=destination_parent,
            follow_symlinks=False,
        )
        if not _same_identity(moved_entry, source_metadata):
            _fail()
        if not _destination_is_absent(source_parent, source.name):
            _fail()
        _require_path_matches(source.parent, source_parent_metadata)
        _require_path_matches(destination.parent, destination_parent_metadata)
        public_destination = os.stat(destination, follow_symlinks=False)
        if not _same_identity(public_destination, source_metadata):
            _fail()
        os.fsync(source_parent)
        os.fsync(destination_parent)
        _require_path_matches(source.parent, source_parent_metadata)
        _require_path_matches(destination.parent, destination_parent_metadata)
        committed_destination = os.stat(destination, follow_symlinks=False)
        if not _same_identity(committed_destination, source_metadata):
            _fail()
    except (KeyboardInterrupt, SystemExit) as error:
        if published:
            raise PostPublicationInterrupted() from error
        raise
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def verify_managed_move(
    source: Path,
    destination: Path,
    marker_name: str,
    expected_identity: str,
    expected_source_parent_identity: str,
    expected_destination_parent_identity: str,
) -> str:
    """Prove a completed managed move without inferring from a helper status."""
    _validate_basename(source.name)
    _validate_basename(destination.name)
    _validate_basename(marker_name)
    descriptors: list[int] = []
    try:
        source_parent, source_parent_metadata = _open_bound_directory(source.parent)
        descriptors.append(source_parent)
        destination_parent, destination_parent_metadata = _open_bound_directory(
            destination.parent
        )
        descriptors.append(destination_parent)
        _require_identity_text(source_parent_metadata, expected_source_parent_identity)
        _require_identity_text(
            destination_parent_metadata, expected_destination_parent_identity
        )
        if not _destination_is_absent(source_parent, source.name):
            _fail()
        destination_descriptor = os.open(
            destination.name,
            _directory_flags(),
            dir_fd=destination_parent,
        )
        descriptors.append(destination_descriptor)
        destination_metadata = os.fstat(destination_descriptor)
        _require_identity_text(destination_metadata, expected_identity)
        destination_entry = os.stat(
            destination.name,
            dir_fd=destination_parent,
            follow_symlinks=False,
        )
        if not _same_identity(destination_entry, destination_metadata):
            _fail()
        _validate_marker(destination_descriptor, marker_name)
        _require_path_matches(source.parent, source_parent_metadata)
        _require_path_matches(destination.parent, destination_parent_metadata)
        public_destination = os.stat(destination, follow_symlinks=False)
        if not _same_identity(public_destination, destination_metadata):
            _fail()
        os.fsync(destination_descriptor)
        os.fsync(source_parent)
        os.fsync(destination_parent)
        _require_path_matches(source.parent, source_parent_metadata)
        _require_path_matches(destination.parent, destination_parent_metadata)
        committed_destination = os.stat(destination, follow_symlinks=False)
        if not _same_identity(committed_destination, destination_metadata):
            _fail()
        return _identity_text(destination_metadata)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _snapshot_tree(directory_descriptor: int) -> TreeSnapshot:
    """Fingerprint every staged entry through held, non-following descriptors."""
    snapshot: TreeSnapshot = {}
    visited_directories: set[tuple[int, int]] = set()
    total_bytes = 0

    def add_directory(
        parent_descriptor: int,
        name: str,
        relative: str,
    ) -> None:
        nonlocal total_bytes
        if len(snapshot) >= TREE_ENTRY_LIMIT:
            _fail()
        descriptor = os.open(name, _directory_flags(), dir_fd=parent_descriptor)
        try:
            before = os.fstat(descriptor)
            public_before = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if not stat.S_ISDIR(before.st_mode) or not _same_identity(
                before, public_before
            ):
                _fail()
            identity = _identity(before)
            if identity in visited_directories:
                _fail()
            visited_directories.add(identity)
            snapshot[relative] = _tree_entry(before, "directory")
            names = sorted(_list_entries(descriptor))
            for child_name in names:
                _validate_basename(child_name)
                child_relative = f"{relative}/{child_name}"
                child = os.stat(
                    child_name,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
                if stat.S_ISDIR(child.st_mode):
                    add_directory(descriptor, child_name, child_relative)
                elif stat.S_ISREG(child.st_mode) and child.st_nlink == 1:
                    add_file(descriptor, child_name, child_relative)
                else:
                    _fail()
            if sorted(_list_entries(descriptor)) != names:
                _fail()
            after = os.fstat(descriptor)
            public_after = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                _identity(after) != identity
                or not _same_identity(after, public_after)
                or after.st_mtime_ns != before.st_mtime_ns
                or after.st_ctime_ns != before.st_ctime_ns
            ):
                _fail()
        finally:
            os.close(descriptor)

    def add_file(parent_descriptor: int, name: str, relative: str) -> None:
        nonlocal total_bytes
        if len(snapshot) >= TREE_ENTRY_LIMIT:
            _fail()
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        try:
            before = os.fstat(descriptor)
            public_before = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or not _same_identity(before, public_before)
                or before.st_size > TREE_FILE_LIMIT
                or total_bytes + before.st_size > TREE_TOTAL_LIMIT
            ):
                _fail()
            raw = _read_bounded(descriptor, TREE_FILE_LIMIT)
            after = os.fstat(descriptor)
            public_after = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                len(raw) != before.st_size
                or not _same_identity(before, after)
                or not _same_identity(after, public_after)
                or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
                or after.st_ctime_ns != before.st_ctime_ns
            ):
                _fail()
            total_bytes += len(raw)
            snapshot[relative] = _tree_entry(
                before,
                "file",
                hashlib.sha256(raw).hexdigest(),
            )
        finally:
            os.close(descriptor)

    root_names = sorted(_list_entries(directory_descriptor))
    for root_name in root_names:
        _validate_basename(root_name)
        root_entry = os.stat(
            root_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if stat.S_ISDIR(root_entry.st_mode):
            add_directory(directory_descriptor, root_name, root_name)
        elif stat.S_ISREG(root_entry.st_mode) and root_entry.st_nlink == 1:
            add_file(directory_descriptor, root_name, root_name)
        else:
            _fail()
    if sorted(_list_entries(directory_descriptor)) != root_names:
        _fail()
    return snapshot


def _snapshot_digest(snapshot: TreeSnapshot) -> str:
    encoded = json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _open_regular_at(parent_descriptor: int, name: str) -> tuple[int, os.stat_result]:
    _validate_basename(name)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    try:
        metadata = os.fstat(descriptor)
        public = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > TREE_FILE_LIMIT
            or not _same_identity(metadata, public)
        ):
            _fail()
        return descriptor, metadata
    except BaseException:
        os.close(descriptor)
        raise


def _source_inventory_digest(entries: dict[str, SourceEntry]) -> str:
    encoded = json.dumps(
        entries,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_source_directory(
    descriptor: int,
) -> tuple[SourceManifestEntry, dict[str, SourceEntry]]:
    before = os.fstat(descriptor)
    if not stat.S_ISDIR(before.st_mode):
        _fail()
    names = sorted(_list_entries(descriptor))
    entries: dict[str, SourceEntry] = {}
    for name in names:
        _validate_basename(name)
        entries[name] = _source_entry(
            os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        )
    after = os.fstat(descriptor)
    if _source_entry(after) != _source_entry(before):
        _fail()
    return (
        _source_manifest_entry(
            after,
            "directory",
            _source_inventory_digest(entries),
        ),
        entries,
    )


def _snapshot_source_regular(
    parent_descriptor: int,
    name: str,
    *,
    budget: list[int],
) -> SourceManifestEntry:
    descriptor, before = _open_regular_at(parent_descriptor, name)
    try:
        if (
            budget[0] >= TREE_ENTRY_LIMIT
            or budget[1] + before.st_size > TREE_TOTAL_LIMIT
        ):
            _fail()
        raw = _read_bounded(descriptor, TREE_FILE_LIMIT)
        after = os.fstat(descriptor)
        public = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            len(raw) != before.st_size
            or _source_entry(after) != _source_entry(before)
            or _source_entry(public) != _source_entry(after)
        ):
            _fail()
        budget[0] += 1
        budget[1] += len(raw)
        return _source_manifest_entry(
            after,
            "file",
            hashlib.sha256(raw).hexdigest(),
        )
    finally:
        os.close(descriptor)


def _snapshot_selected_source_directory(
    source_root: int,
    name: str,
    suffixes: set[str],
    *,
    required_names: frozenset[str],
    budget: list[int],
) -> SourceManifest:
    _validate_basename(name)
    descriptor = os.open(name, _directory_flags(), dir_fd=source_root)
    try:
        public_before = os.stat(name, dir_fd=source_root, follow_symlinks=False)
        opened_before = os.fstat(descriptor)
        if not stat.S_ISDIR(opened_before.st_mode) or not _same_identity(
            opened_before, public_before
        ):
            _fail()
        directory_entry, inventory = _snapshot_source_directory(descriptor)
        suffix_names = sorted(
            child_name
            for child_name in inventory
            if Path(child_name).suffix in suffixes
        )
        selected_names = sorted(required_names)
        if suffix_names != selected_names:
            _fail()
        manifest: SourceManifest = {name: directory_entry}
        for child_name in selected_names:
            child_entry = inventory[child_name]
            if child_entry[0] != stat.S_IFREG or child_entry[4] != 1:
                _fail()
            manifest[f"{name}/{child_name}"] = _snapshot_source_regular(
                descriptor,
                child_name,
                budget=budget,
            )
        directory_after, inventory_after = _snapshot_source_directory(descriptor)
        public_after = os.stat(name, dir_fd=source_root, follow_symlinks=False)
        if (
            directory_after != directory_entry
            or inventory_after != inventory
            or not _same_identity(os.fstat(descriptor), public_after)
        ):
            _fail()
        return manifest
    finally:
        os.close(descriptor)


def _snapshot_source_manifest(source_root: int) -> SourceManifest:
    budget = [0, 0]
    root_entry, root_inventory = _snapshot_source_directory(source_root)
    expected_root_names = {"SKILL.md", "references", "scripts"}
    if set(root_inventory) != expected_root_names:
        _fail()
    manifest: SourceManifest = {
        ".": root_entry,
        "SKILL.md": _snapshot_source_regular(
            source_root,
            "SKILL.md",
            budget=budget,
        ),
    }
    manifest.update(
        _snapshot_selected_source_directory(
            source_root,
            "references",
            {".md", ".json"},
            required_names=REQUIRED_REFERENCE_NAMES,
            budget=budget,
        )
    )
    manifest.update(
        _snapshot_selected_source_directory(
            source_root,
            "scripts",
            {".py"},
            required_names=REQUIRED_SCRIPT_NAMES,
            budget=budget,
        )
    )
    root_after, root_inventory_after = _snapshot_source_directory(source_root)
    if root_after != root_entry or root_inventory_after != root_inventory:
        _fail()
    return manifest


def _require_stage_matches_source_manifest(
    staged_entries: TreeSnapshot,
    source_manifest: SourceManifest,
    marker_name: str,
) -> None:
    if any(
        not isinstance(path, str) or not isinstance(entry, tuple) or len(entry) != 9
        for path, entry in source_manifest.items()
    ) or any(
        not isinstance(path, str) or not isinstance(entry, tuple) or len(entry) != 8
        for path, entry in staged_entries.items()
    ):
        _fail()
    source_files = {
        path: entry for path, entry in source_manifest.items() if entry[0] == "file"
    }
    staged_files = {
        path: entry
        for path, entry in staged_entries.items()
        if entry[0] == "file" and path != marker_name
    }
    if set(staged_files) != set(source_files):
        _fail()
    for path, staged_entry in staged_files.items():
        source_entry = source_files[path]
        if staged_entry[4] != source_entry[5] or staged_entry[7] != source_entry[8]:
            _fail()


def _revalidate_source_manifest(
    source: Path,
    source_descriptor: int,
    source_metadata: os.stat_result,
    expected: SourceManifest,
) -> None:
    _require_path_matches(source, source_metadata)
    if _snapshot_source_manifest(source_descriptor) != expected:
        _fail()
    _require_path_matches(source, source_metadata)


def _copy_regular_at(
    source_parent: int,
    destination_parent: int,
    name: str,
    *,
    mode: int,
    budget: list[int],
) -> TreeEntry:
    source_descriptor, source_before = _open_regular_at(source_parent, name)
    destination_descriptor: int | None = None
    try:
        if (
            budget[0] >= TREE_ENTRY_LIMIT
            or budget[1] + source_before.st_size > TREE_TOTAL_LIMIT
        ):
            _fail()
        budget[0] += 1
        budget[1] += source_before.st_size
        raw = _read_bounded(source_descriptor, TREE_FILE_LIMIT)
        source_after = os.fstat(source_descriptor)
        source_public = os.stat(
            name,
            dir_fd=source_parent,
            follow_symlinks=False,
        )
        if (
            len(raw) != source_before.st_size
            or not _same_identity(source_before, source_after)
            or not _same_identity(source_after, source_public)
            or source_after.st_size != source_before.st_size
            or source_after.st_mtime_ns != source_before.st_mtime_ns
            or source_after.st_ctime_ns != source_before.st_ctime_ns
        ):
            _fail()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        destination_descriptor = os.open(
            name,
            flags,
            mode,
            dir_fd=destination_parent,
        )
        written = 0
        while written < len(raw):
            count = os.write(destination_descriptor, raw[written:])
            if count <= 0:
                _fail()
            written += count
        os.fchmod(destination_descriptor, mode)
        os.fsync(destination_descriptor)
        destination_metadata = os.fstat(destination_descriptor)
        destination_public = os.stat(
            name,
            dir_fd=destination_parent,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(destination_metadata.st_mode)
            or destination_metadata.st_nlink != 1
            or destination_metadata.st_size != len(raw)
            or stat.S_IMODE(destination_metadata.st_mode) != mode
            or not _same_identity(destination_metadata, destination_public)
        ):
            _fail()
        return _tree_entry(
            destination_metadata,
            "file",
            hashlib.sha256(raw).hexdigest(),
        )
    finally:
        if destination_descriptor is not None:
            os.close(destination_descriptor)
        os.close(source_descriptor)


def _copy_selected_directory(
    source_root: int,
    destination_root: int,
    name: str,
    suffixes: set[str],
    *,
    required_names: frozenset[str],
    file_mode: int,
    budget: list[int],
) -> tuple[TreeEntry, dict[str, TreeEntry]]:
    source_descriptor = os.open(name, _directory_flags(), dir_fd=source_root)
    destination_descriptor: int | None = None
    copied: dict[str, TreeEntry] = {}
    try:
        source_metadata = os.fstat(source_descriptor)
        source_public = os.stat(name, dir_fd=source_root, follow_symlinks=False)
        if not _same_identity(source_metadata, source_public):
            _fail()
        os.mkdir(name, 0o700, dir_fd=destination_root)
        destination_descriptor = os.open(
            name,
            _directory_flags(),
            dir_fd=destination_root,
        )
        destination_before = os.fstat(destination_descriptor)
        _require_private_directory(destination_before)
        if _list_entries(destination_descriptor):
            _fail()
        source_names = sorted(_list_entries(source_descriptor))
        source_entries: dict[str, SourceEntry] = {}
        suffix_names: list[str] = []
        for child_name in source_names:
            _validate_basename(child_name)
            child = os.stat(
                child_name,
                dir_fd=source_descriptor,
                follow_symlinks=False,
            )
            source_entries[child_name] = _source_entry(child)
            if Path(child_name).suffix not in suffixes:
                continue
            suffix_names.append(child_name)
            if not stat.S_ISREG(child.st_mode) or child.st_nlink != 1:
                _fail()
        selected_names = sorted(required_names)
        if sorted(suffix_names) != selected_names:
            _fail()
        for child_name in selected_names:
            try:
                copied[child_name] = _copy_regular_at(
                    source_descriptor,
                    destination_descriptor,
                    child_name,
                    mode=file_mode,
                    budget=budget,
                )
            except OSError:
                _fail()
        if sorted(_list_entries(source_descriptor)) != source_names:
            _fail()
        source_entries_after = {
            child_name: _source_entry(
                os.stat(
                    child_name,
                    dir_fd=source_descriptor,
                    follow_symlinks=False,
                )
            )
            for child_name in source_names
        }
        if source_entries_after != source_entries:
            _fail()
        source_after = os.fstat(source_descriptor)
        source_public_after = os.stat(
            name,
            dir_fd=source_root,
            follow_symlinks=False,
        )
        if (
            not _same_identity(source_metadata, source_after)
            or not _same_identity(source_after, source_public_after)
            or source_after.st_mtime_ns != source_metadata.st_mtime_ns
            or source_after.st_ctime_ns != source_metadata.st_ctime_ns
        ):
            _fail()
        os.fsync(destination_descriptor)
        destination_after = os.fstat(destination_descriptor)
        destination_public = os.stat(
            name,
            dir_fd=destination_root,
            follow_symlinks=False,
        )
        _require_private_directory(destination_after)
        if not _same_identity(
            destination_before, destination_after
        ) or not _same_identity(destination_after, destination_public):
            _fail()
        return _tree_entry(destination_after, "directory"), copied
    finally:
        if destination_descriptor is not None:
            os.close(destination_descriptor)
        os.close(source_descriptor)


def _write_new_regular_at(
    parent_descriptor: int,
    name: str,
    raw: bytes,
    *,
    mode: int,
) -> TreeEntry:
    _validate_basename(name)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(name, flags, mode, dir_fd=parent_descriptor)
    try:
        written = 0
        while written < len(raw):
            count = os.write(descriptor, raw[written:])
            if count <= 0:
                _fail()
            written += count
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        public = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size != len(raw)
            or stat.S_IMODE(metadata.st_mode) != mode
            or not _same_identity(metadata, public)
        ):
            _fail()
        return _tree_entry(metadata, "file", hashlib.sha256(raw).hexdigest())
    finally:
        os.close(descriptor)


def build_stage(
    source: Path,
    staged: Path,
    marker_name: str,
    version: str,
    expected_staged_parent_identity: str,
) -> tuple[str, str]:
    """Create and populate one stage without reopening its public path for writes."""
    _validate_basename(staged.name)
    _validate_basename(marker_name)
    if not version.strip() or any(ord(character) < 0x20 for character in version):
        _fail()
    descriptors: list[int] = []
    source_descriptor = -1
    staged_parent = -1
    staged_descriptor = -1
    try:
        source_descriptor, source_metadata = _open_bound_directory(source)
        descriptors.append(source_descriptor)
        source_manifest = _snapshot_source_manifest(source_descriptor)
        staged_parent, staged_parent_metadata = _open_bound_directory(staged.parent)
        descriptors.append(staged_parent)
        _require_identity_text(staged_parent_metadata, expected_staged_parent_identity)
        if not _destination_is_absent(staged_parent, staged.name):
            _fail()
        os.mkdir(staged.name, 0o700, dir_fd=staged_parent)
        staged_descriptor = os.open(
            staged.name,
            _directory_flags(),
            dir_fd=staged_parent,
        )
        descriptors.append(staged_descriptor)
        staged_metadata = os.fstat(staged_descriptor)
        _require_private_directory(staged_metadata)
        staged_public = os.stat(
            staged.name,
            dir_fd=staged_parent,
            follow_symlinks=False,
        )
        if not _same_identity(staged_metadata, staged_public):
            _fail()
        if _list_entries(staged_descriptor):
            _fail()

        build_budget = [1, 0]
        expected_entries: TreeSnapshot = {
            "SKILL.md": _copy_regular_at(
                source_descriptor,
                staged_descriptor,
                "SKILL.md",
                mode=0o600,
                budget=build_budget,
            )
        }
        reference_directory, reference_files = _copy_selected_directory(
            source_descriptor,
            staged_descriptor,
            "references",
            {".md", ".json"},
            required_names=REQUIRED_REFERENCE_NAMES,
            file_mode=0o600,
            budget=build_budget,
        )
        expected_entries["references"] = reference_directory
        expected_entries.update(
            {f"references/{name}": entry for name, entry in reference_files.items()}
        )
        script_directory, script_files = _copy_selected_directory(
            source_descriptor,
            staged_descriptor,
            "scripts",
            {".py"},
            required_names=REQUIRED_SCRIPT_NAMES,
            file_mode=0o700,
            budget=build_budget,
        )
        expected_entries["scripts"] = script_directory
        expected_entries.update(
            {f"scripts/{name}": entry for name, entry in script_files.items()}
        )
        marker = (
            json.dumps(
                {"name": EXPECTED_NAME, "version": version},
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        if len(marker) > MARKER_LIMIT or build_budget[0] >= TREE_ENTRY_LIMIT:
            _fail()
        build_budget[0] += 1
        build_budget[1] += len(marker)
        if build_budget[1] > TREE_TOTAL_LIMIT:
            _fail()
        marker_entry = _write_new_regular_at(
            staged_descriptor,
            marker_name,
            marker,
            mode=0o600,
        )
        expected_entries[marker_name] = marker_entry
        _require_stage_matches_source_manifest(
            expected_entries,
            source_manifest,
            marker_name,
        )
        _validate_marker(staged_descriptor, marker_name)
        snapshot = _snapshot_tree(staged_descriptor)
        if snapshot != expected_entries:
            _fail()
        os.fsync(staged_descriptor)
        os.fsync(staged_parent)
        _require_path_matches(source, source_metadata)
        _require_path_matches(staged.parent, staged_parent_metadata)
        _require_path_matches(staged, staged_metadata)
        _require_private_directory(os.fstat(staged_descriptor))
        if _snapshot_tree(staged_descriptor) != snapshot:
            _fail()
        _require_path_matches(source, source_metadata)
        _require_path_matches(staged.parent, staged_parent_metadata)
        _require_path_matches(staged, staged_metadata)
        _require_private_directory(os.fstat(staged_descriptor))
        staged_identity = _identity_text(staged_metadata)
        snapshot_digest = _snapshot_digest(snapshot)
        _revalidate_source_manifest(
            source,
            source_descriptor,
            source_metadata,
            source_manifest,
        )
        return staged_identity, snapshot_digest
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def install_staged(
    staged: Path,
    target: Path,
    marker_name: str,
    expected_staged_identity: str,
    expected_staged_parent_identity: str,
    expected_target_parent_identity: str,
    expected_snapshot_digest: str,
) -> str:
    _validate_basename(staged.name)
    _validate_basename(target.name)
    _validate_basename(marker_name)
    descriptors: list[int] = []
    staged_parent = -1
    staged_descriptor = -1
    target_parent = -1
    staged_metadata: os.stat_result | None = None
    original_entries: TreeSnapshot = {}
    published = False
    try:
        staged_parent, staged_parent_metadata = _open_bound_directory(staged.parent)
        descriptors.append(staged_parent)
        target_parent, target_parent_metadata = _open_bound_directory(target.parent)
        descriptors.append(target_parent)
        _require_identity_text(staged_parent_metadata, expected_staged_parent_identity)
        _require_identity_text(target_parent_metadata, expected_target_parent_identity)
        staged_descriptor = os.open(
            staged.name,
            _directory_flags(),
            dir_fd=staged_parent,
        )
        descriptors.append(staged_descriptor)
        staged_metadata = os.fstat(staged_descriptor)
        _require_private_directory(staged_metadata)
        _require_identity_text(staged_metadata, expected_staged_identity)
        staged_entry = os.stat(
            staged.name,
            dir_fd=staged_parent,
            follow_symlinks=False,
        )
        if not _same_identity(staged_entry, staged_metadata):
            _fail()
        _validate_marker(staged_descriptor, marker_name)
        original_entries = _snapshot_tree(staged_descriptor)
        if _snapshot_digest(original_entries) != expected_snapshot_digest:
            _fail()
        if marker_name not in original_entries or "SKILL.md" not in original_entries:
            _fail()
        if not _destination_is_absent(target_parent, target.name):
            _fail()

        _require_path_matches(staged.parent, staged_parent_metadata)
        _require_path_matches(target.parent, target_parent_metadata)
        _require_path_matches(staged, staged_metadata)
        _rename_no_replace(
            staged.name,
            target.name,
            source_parent=staged_parent,
            destination_parent=target_parent,
        )
        published = True
        installed_entry = os.stat(
            target.name,
            dir_fd=target_parent,
            follow_symlinks=False,
        )
        if not _same_identity(installed_entry, staged_metadata):
            _fail()
        if not _destination_is_absent(staged_parent, staged.name):
            _fail()
        _require_path_matches(staged.parent, staged_parent_metadata)
        _require_path_matches(target.parent, target_parent_metadata)
        _require_path_matches(target, staged_metadata)
        _validate_marker(staged_descriptor, marker_name)
        if _snapshot_tree(staged_descriptor) != original_entries:
            _fail()
        os.fsync(staged_descriptor)
        os.fsync(staged_parent)
        os.fsync(target_parent)
        _require_path_matches(staged.parent, staged_parent_metadata)
        _require_path_matches(target.parent, target_parent_metadata)
        _require_path_matches(target, staged_metadata)
        _require_private_directory(os.fstat(staged_descriptor))
        if _snapshot_tree(staged_descriptor) != original_entries:
            _fail()
        _validate_marker(staged_descriptor, marker_name)
        _require_path_matches(staged.parent, staged_parent_metadata)
        _require_path_matches(target.parent, target_parent_metadata)
        _require_path_matches(target, staged_metadata)
        _require_private_directory(os.fstat(staged_descriptor))
        return _identity_text(staged_metadata)
    except (KeyboardInterrupt, SystemExit) as error:
        if published:
            raise PostPublicationInterrupted() from error
        raise
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def verify_installed(
    target: Path,
    marker_name: str,
    expected_identity: str,
    expected_parent_identity: str,
    expected_snapshot_digest: str,
) -> str:
    """Recheck the complete install receipt at the shell acceptance point."""
    _validate_basename(target.name)
    _validate_basename(marker_name)
    descriptors: list[int] = []
    try:
        parent_descriptor, parent_metadata = _open_bound_directory(target.parent)
        descriptors.append(parent_descriptor)
        _require_identity_text(parent_metadata, expected_parent_identity)
        target_descriptor = os.open(
            target.name,
            _directory_flags(),
            dir_fd=parent_descriptor,
        )
        descriptors.append(target_descriptor)
        target_metadata = os.fstat(target_descriptor)
        _require_private_directory(target_metadata)
        _require_identity_text(target_metadata, expected_identity)
        target_public = os.stat(
            target.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if not _same_identity(target_metadata, target_public):
            _fail()
        _validate_marker(target_descriptor, marker_name)
        if (
            _snapshot_digest(_snapshot_tree(target_descriptor))
            != expected_snapshot_digest
        ):
            _fail()
        os.fsync(target_descriptor)
        os.fsync(parent_descriptor)
        _require_path_matches(target.parent, parent_metadata)
        _require_path_matches(target, target_metadata)
        _require_private_directory(os.fstat(target_descriptor))
        _validate_marker(target_descriptor, marker_name)
        if (
            _snapshot_digest(_snapshot_tree(target_descriptor))
            != expected_snapshot_digest
        ):
            _fail()
        _require_path_matches(target.parent, parent_metadata)
        _require_path_matches(target, target_metadata)
        _require_private_directory(os.fstat(target_descriptor))
        return _identity_text(target_metadata)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _usage() -> int:
    print("installer_lifecycle_usage_error", file=sys.stderr)
    return 2


def _print_help() -> int:
    print(
        "Usage: installer_lifecycle.py "
        "{canonical,directory-identity,unique-path,identity,stage-source,"
        "verify-install,move,verify-move,install} ...\n"
        "Internal descriptor-bound transaction helper for install.sh."
    )
    return 0


def main(arguments: list[str] | None = None) -> int:
    values = sys.argv[1:] if arguments is None else arguments
    try:
        if values in (["--help"], ["-h"]):
            return _print_help()
        if len(values) == 2 and values[0] == "canonical":
            print(canonical_directory(Path(values[1])))
            return 0
        if len(values) == 2 and values[0] == "directory-identity":
            print(directory_identity(Path(values[1])))
            return 0
        if len(values) == 4 and values[0] == "unique-path":
            print(unique_absent_path(Path(values[1]), values[2], values[3]))
            return 0
        if len(values) == 3 and values[0] == "identity":
            print(managed_identity(Path(values[1]), values[2]))
            return 0
        if len(values) == 6 and values[0] == "stage-source":
            identity, digest = build_stage(
                Path(values[1]),
                Path(values[2]),
                values[3],
                values[4],
                values[5],
            )
            print(identity, digest)
            return 0
        if len(values) == 6 and values[0] == "verify-install":
            print(
                verify_installed(
                    Path(values[1]),
                    values[2],
                    values[3],
                    values[4],
                    values[5],
                )
            )
            return 0
        if len(values) == 7 and values[0] == "move":
            move_verified_managed(
                Path(values[1]),
                Path(values[2]),
                values[3],
                values[4],
                values[5],
                values[6],
            )
            return 0
        if len(values) == 7 and values[0] == "verify-move":
            print(
                verify_managed_move(
                    Path(values[1]),
                    Path(values[2]),
                    values[3],
                    values[4],
                    values[5],
                    values[6],
                )
            )
            return 0
        if len(values) == 8 and values[0] == "install":
            print(
                install_staged(
                    Path(values[1]),
                    Path(values[2]),
                    values[3],
                    values[4],
                    values[5],
                    values[6],
                    values[7],
                )
            )
            return 0
        return _usage()
    except PostPublicationInterrupted:
        print("installer_postpublication_interrupted", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("installer_prepublication_interrupted", file=sys.stderr)
        return 130
    except SystemExit:
        print("installer_prepublication_interrupted", file=sys.stderr)
        return 1
    except (LifecycleError, OSError, UnicodeError, ValueError):
        print("installer_transaction_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
