#!/usr/bin/env python3
"""Safely inspect and retire legacy public Banana Claude installations."""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn, cast

from banana_core import (
    BananaError,
    SecretSafeArgumentParser,
    _exclusive_rename_at,
    enforce_json_nesting_limit,
)

SETTINGS_NAME = "settings.json"
SETTINGS_REVIEWED_RECOVERY_NAME = "settings.reviewed-recovery.json"
LEGACY_MCP_NAME = "nanobanana-mcp"
MANAGED_MARKER = ".banana-claude-install.json"
MAX_SETTINGS_BYTES = 1 * 1024 * 1024
MAX_MARKER_BYTES = 16 * 1024
MAX_SKILL_ENTRIES = 20_000
MAX_SKILL_FILE_BYTES = 16 * 1024 * 1024
MAX_SKILL_TREE_BYTES = 64 * 1024 * 1024
FINGERPRINT_DOMAIN = b"banana-claude-legacy-public-cleanup-v1\x00"
LEGACY_SKILLS = (
    ("banana", "banana-claude-v1.4.1"),
    ("nano-banana", "nano-banana-v2.1.0"),
)
LEGACY_LAYOUT_FILES: dict[str, frozenset[str]] = {
    "banana-claude-v1.4.1": frozenset(
        {
            "SKILL.md",
            "references/cost-tracking.md",
            "references/gemini-models.md",
            "references/mcp-tools.md",
            "references/post-processing.md",
            "references/presets.md",
            "references/prompt-engineering.md",
            "scripts/batch.py",
            "scripts/cost_tracker.py",
            "scripts/edit.py",
            "scripts/generate.py",
            "scripts/presets.py",
            "scripts/setup_mcp.py",
            "scripts/validate_setup.py",
        }
    ),
    "nano-banana-v2.1.0": frozenset(
        {
            "SKILL.md",
            "references/gemini-models.md",
            "references/mcp-tools.md",
            "references/post-processing.md",
            "references/prompt-engineering.md",
            "scripts/setup_mcp.py",
            "scripts/validate_setup.py",
        }
    ),
}
LEGACY_LAYOUT_VERSIONS = {
    "banana-claude-v1.4.1": "1.4.1",
    "nano-banana-v2.1.0": "2.1.0",
}
KNOWN_CREDENTIAL_FIELDS = frozenset(
    {
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_AI_API_KEY",
        "API_KEY",
        "APIKEY",
    }
)


class CleanupError(RuntimeError):
    """Typed, secret-safe failure from legacy inspection or remediation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.details:
            result["details"] = self.details
        return result


@dataclass(frozen=True)
class FileSnapshot:
    device: int
    inode: int
    mode: int
    links: int
    size: int
    modified_ns: int
    changed_ns: int

    @classmethod
    def from_stat(cls, metadata: os.stat_result) -> FileSnapshot:
        return cls(
            device=metadata.st_dev,
            inode=metadata.st_ino,
            mode=metadata.st_mode,
            links=metadata.st_nlink,
            size=metadata.st_size,
            modified_ns=metadata.st_mtime_ns,
            changed_ns=metadata.st_ctime_ns,
        )

    def same_identity(self, metadata: os.stat_result) -> bool:
        return self.device == metadata.st_dev and self.inode == metadata.st_ino

    def fingerprint_material(self) -> dict[str, int]:
        return {
            "device": self.device,
            "inode": self.inode,
            "mode": self.mode,
            "links": self.links,
            "size": self.size,
            "modified_ns": self.modified_ns,
            "changed_ns": self.changed_ns,
        }


@dataclass(frozen=True)
class SettingsInspection:
    path: Path
    status: str
    exists: bool
    safe_to_remediate: bool
    raw: bytes | None = None
    value: dict[str, Any] | None = None
    snapshot: FileSnapshot | None = None
    legacy_server_detected: bool | None = None
    credential_detected: bool | None = None

    def public(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "status": self.status,
            "exists": self.exists,
            "safe_to_remediate": self.safe_to_remediate,
            "legacy_mcp_server_detected": self.legacy_server_detected,
            "embedded_credential_detected": self.credential_detected,
        }


@dataclass(frozen=True)
class SkillInspection:
    name: str
    layout: str
    path: Path
    status: str
    exists: bool
    managed: bool
    legacy_detected: bool
    safe_to_remediate: bool
    snapshot: FileSnapshot | None = None
    tree_digest: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "layout": self.layout,
            "path": str(self.path),
            "status": self.status,
            "exists": self.exists,
            "managed": self.managed,
            "legacy_detected": self.legacy_detected,
            "safe_to_remediate": self.safe_to_remediate,
        }


@dataclass(frozen=True)
class Inspection:
    home: Path
    claude_directory: Path
    skills_directory: Path
    settings: SettingsInspection
    skills: tuple[SkillInspection, ...]

    @property
    def legacy_skills(self) -> tuple[SkillInspection, ...]:
        return tuple(item for item in self.skills if item.legacy_detected)

    @property
    def remediation_required(self) -> bool:
        return bool(self.settings.legacy_server_detected or self.legacy_skills)

    @property
    def blocked(self) -> bool:
        if not self.settings.safe_to_remediate:
            return True
        return any(
            item.legacy_detected and not item.safe_to_remediate for item in self.skills
        )

    @property
    def clean(self) -> bool:
        return not self.remediation_required and not self.blocked

    @property
    def credential_rotation_required(self) -> bool | None:
        return self.settings.credential_detected

    def public(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "operation": "legacy_public_install_scan",
            "read_only": True,
            "clean": self.clean,
            "remediation_required": self.remediation_required,
            "remediation_blocked": self.blocked,
            "settings": self.settings.public(),
            "legacy_skill_locations": [item.public() for item in self.skills],
            "credential_rotation_or_revocation_required": (
                self.credential_rotation_required
            ),
            "credential_removal_revokes_credential": False,
        }


@dataclass
class HeldSkill:
    inspection: SkillInspection
    descriptor: int
    moved: bool = False


@dataclass
class HeldSettingsBackup:
    path: Path
    directory_descriptor: int
    descriptor: int
    replacement: bytes
    active_mode: int

    def close(self) -> None:
        os.close(self.descriptor)
        os.close(self.directory_descriptor)


def _user_home() -> Path:
    configured = os.environ.get("HOME")
    raw = configured if configured else str(Path.home())
    return Path(os.path.abspath(os.path.expanduser(raw)))


def _paths() -> tuple[Path, Path, Path]:
    home = _user_home()
    claude = home / ".claude"
    return home, claude, claude / "skills"


def _optional_lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CleanupError(
            "legacy_cleanup_inspection_failed",
            "A legacy cleanup path could not be inspected safely.",
        ) from exc


def _bounded_read(descriptor: int, maximum: int, *, code: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while total <= maximum:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    except OSError as exc:
        raise CleanupError(
            code,
            "A legacy cleanup file could not be read within its safety limit.",
        ) from exc
    raw = b"".join(chunks)
    if len(raw) > maximum:
        raise CleanupError(
            code,
            "A legacy cleanup file exceeds its safety limit.",
        )
    return raw


def _read_regular_path(
    path: Path,
    *,
    maximum: int,
    code: str,
) -> tuple[bytes, FileSnapshot]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise CleanupError(
                code,
                "A legacy cleanup file is not one regular, privately linked file.",
            )
        snapshot = FileSnapshot.from_stat(metadata)
        raw = _bounded_read(descriptor, maximum, code=code)
        final_metadata = os.fstat(descriptor)
        path_metadata = os.stat(path, follow_symlinks=False)
        if (
            not snapshot.same_identity(final_metadata)
            or not snapshot.same_identity(path_metadata)
            or snapshot.modified_ns != final_metadata.st_mtime_ns
            or snapshot.changed_ns != final_metadata.st_ctime_ns
            or snapshot.size != final_metadata.st_size
        ):
            raise CleanupError(
                code,
                "A legacy cleanup file changed while it was inspected.",
            )
        return raw, snapshot
    except CleanupError:
        raise
    except OSError as exc:
        raise CleanupError(
            code,
            "A legacy cleanup file could not be opened without following links.",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _decode_settings(raw: bytes) -> dict[str, Any]:
    try:
        enforce_json_nesting_limit(raw)
        value: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise CleanupError(
            "unsafe_legacy_settings",
            "Claude settings are not valid bounded UTF-8 JSON.",
        ) from exc
    if not isinstance(value, dict):
        raise CleanupError(
            "unsafe_legacy_settings",
            "Claude settings must be a JSON object before cleanup can continue.",
        )
    return cast(dict[str, Any], value)


def _nonempty_credential(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _contains_known_credential(value: Any) -> bool:
    pending: list[Any] = [value]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            identity = id(current)
            if identity in visited:
                continue
            visited.add(identity)
            for raw_key, child in current.items():
                if isinstance(raw_key, str):
                    key = raw_key.upper().replace("-", "_")
                    if key in KNOWN_CREDENTIAL_FIELDS and _nonempty_credential(child):
                        return True
                if isinstance(child, (dict, list)):
                    pending.append(child)
        elif isinstance(current, list):
            identity = id(current)
            if identity in visited:
                continue
            visited.add(identity)
            pending.extend(
                child for child in current if isinstance(child, (dict, list))
            )
    return False


def _inspect_settings(path: Path) -> SettingsInspection:
    metadata = _optional_lstat(path)
    if metadata is None:
        return SettingsInspection(
            path=path,
            status="absent",
            exists=False,
            safe_to_remediate=True,
            legacy_server_detected=False,
            credential_detected=False,
        )
    if stat.S_ISLNK(metadata.st_mode):
        return SettingsInspection(
            path=path,
            status="unsafe_symlink",
            exists=True,
            safe_to_remediate=False,
        )
    if not stat.S_ISREG(metadata.st_mode):
        return SettingsInspection(
            path=path,
            status="unsafe_nonregular",
            exists=True,
            safe_to_remediate=False,
        )
    if metadata.st_nlink != 1:
        return SettingsInspection(
            path=path,
            status="unsafe_hardlinked",
            exists=True,
            safe_to_remediate=False,
        )
    if metadata.st_size > MAX_SETTINGS_BYTES:
        return SettingsInspection(
            path=path,
            status="unsafe_oversized",
            exists=True,
            safe_to_remediate=False,
        )
    try:
        raw, snapshot = _read_regular_path(
            path,
            maximum=MAX_SETTINGS_BYTES,
            code="unsafe_legacy_settings",
        )
        value = _decode_settings(raw)
    except CleanupError as exc:
        status = (
            "unsafe_invalid_json"
            if "JSON" in exc.message
            else "unsafe_changed_or_unreadable"
        )
        return SettingsInspection(
            path=path,
            status=status,
            exists=True,
            safe_to_remediate=False,
        )
    servers = value.get("mcpServers")
    detected = isinstance(servers, dict) and LEGACY_MCP_NAME in servers
    entry = servers.get(LEGACY_MCP_NAME) if isinstance(servers, dict) else None
    credential = _contains_known_credential(entry) if detected else False
    return SettingsInspection(
        path=path,
        status="legacy_mcp_detected" if detected else "clean",
        exists=True,
        safe_to_remediate=True,
        raw=raw,
        value=value,
        snapshot=snapshot,
        legacy_server_detected=detected,
        credential_detected=credential,
    )


def _valid_managed_marker(skill_path: Path) -> bool:
    marker = skill_path / MANAGED_MARKER
    metadata = _optional_lstat(marker)
    if (
        metadata is None
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size > MAX_MARKER_BYTES
    ):
        return False
    try:
        raw, _snapshot = _read_regular_path(
            marker,
            maximum=MAX_MARKER_BYTES,
            code="invalid_managed_marker",
        )
        enforce_json_nesting_limit(raw)
        value: Any = json.loads(raw.decode("utf-8"))
    except (CleanupError, UnicodeDecodeError, ValueError, RecursionError):
        return False
    return bool(
        isinstance(value, dict)
        and value.get("name") == "banana-claude"
        and isinstance(value.get("version"), str)
        and value["version"].strip()
    )


def _read_skill_file_for_digest(
    path: Path,
    expected: os.stat_result,
) -> bytes:
    if expected.st_size > MAX_SKILL_FILE_BYTES:
        raise CleanupError(
            "unsafe_legacy_skill",
            "A legacy skill file exceeds the bounded file-size limit.",
        )
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != expected.st_dev
            or opened.st_ino != expected.st_ino
            or opened.st_nlink != expected.st_nlink
        ):
            raise CleanupError(
                "unsafe_legacy_skill",
                "A legacy skill file changed while its bytes were reviewed.",
            )
        raw = _bounded_read(
            descriptor,
            MAX_SKILL_FILE_BYTES,
            code="unsafe_legacy_skill",
        )
        final_metadata = os.fstat(descriptor)
        path_metadata = os.stat(path, follow_symlinks=False)
        if (
            final_metadata.st_dev != expected.st_dev
            or final_metadata.st_ino != expected.st_ino
            or final_metadata.st_nlink != expected.st_nlink
            or final_metadata.st_size != expected.st_size
            or final_metadata.st_mtime_ns != expected.st_mtime_ns
            or final_metadata.st_ctime_ns != expected.st_ctime_ns
            or path_metadata.st_dev != expected.st_dev
            or path_metadata.st_ino != expected.st_ino
            or len(raw) != expected.st_size
        ):
            raise CleanupError(
                "unsafe_legacy_skill",
                "A legacy skill file changed while its bytes were reviewed.",
            )
        return raw
    except CleanupError:
        raise
    except OSError as exc:
        raise CleanupError(
            "unsafe_legacy_skill",
            "A legacy skill file could not be read without following links.",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _skill_tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    digest.update(b"banana-claude-legacy-skill-tree-v2\x00")
    pending: list[tuple[Path, str]] = [(root, "")]
    entries_seen = 0
    file_bytes_seen = 0
    try:
        while pending:
            directory, prefix = pending.pop()
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: os.fsencode(item.name))
            for entry in entries:
                entries_seen += 1
                if entries_seen > MAX_SKILL_ENTRIES:
                    raise CleanupError(
                        "unsafe_legacy_skill",
                        "A legacy skill tree exceeds the bounded entry limit.",
                    )
                relative = f"{prefix}/{entry.name}" if prefix else entry.name
                metadata = entry.stat(follow_symlinks=False)
                record = {
                    "path": os.fsencode(relative).hex(),
                    "mode": metadata.st_mode,
                    "links": metadata.st_nlink,
                    "size": metadata.st_size,
                    "modified_ns": metadata.st_mtime_ns,
                    "changed_ns": metadata.st_ctime_ns,
                    "device": metadata.st_dev,
                    "inode": metadata.st_ino,
                }
                digest.update(
                    json.dumps(record, sort_keys=True, separators=(",", ":")).encode(
                        "ascii"
                    )
                )
                digest.update(b"\x00")
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append((Path(entry.path), relative))
                elif stat.S_ISREG(metadata.st_mode):
                    raw = _read_skill_file_for_digest(Path(entry.path), metadata)
                    file_bytes_seen += len(raw)
                    if file_bytes_seen > MAX_SKILL_TREE_BYTES:
                        raise CleanupError(
                            "unsafe_legacy_skill",
                            "A legacy skill tree exceeds the bounded byte limit.",
                        )
                    digest.update(b"regular-file-bytes\x00")
                    digest.update(len(raw).to_bytes(8, "big"))
                    digest.update(raw)
                    digest.update(b"\x00")
    except CleanupError:
        raise
    except OSError as exc:
        raise CleanupError(
            "unsafe_legacy_skill",
            "A legacy skill tree changed or could not be inspected safely.",
        ) from exc
    return digest.hexdigest()


def _legacy_layout_signature_matches(root: Path, name: str, layout: str) -> bool:
    """Recognize only the closed public 1.4.1 or 2.1.0 file layout."""
    expected_files = LEGACY_LAYOUT_FILES[layout]
    expected_directories = frozenset(
        relative.split("/", 1)[0] for relative in expected_files if "/" in relative
    )
    observed_files: set[str] = set()
    observed_directories: set[str] = set()
    pending: list[tuple[Path, str]] = [(root, "")]
    entries_seen = 0
    try:
        while pending:
            directory, prefix = pending.pop()
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: os.fsencode(item.name))
            for entry in entries:
                entries_seen += 1
                if entries_seen > MAX_SKILL_ENTRIES:
                    return False
                relative = f"{prefix}/{entry.name}" if prefix else entry.name
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(metadata.st_mode):
                    observed_directories.add(relative)
                    pending.append((Path(entry.path), relative))
                elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                    observed_files.add(relative)
                else:
                    return False
    except OSError:
        return False
    if (
        frozenset(observed_files) != expected_files
        or frozenset(observed_directories) != expected_directories
    ):
        return False

    skill_path = root / "SKILL.md"
    setup_path = root / "scripts" / "setup_mcp.py"
    try:
        skill_metadata = skill_path.stat(follow_symlinks=False)
        setup_metadata = setup_path.stat(follow_symlinks=False)
        skill_raw = _read_skill_file_for_digest(skill_path, skill_metadata)
        setup_raw = _read_skill_file_for_digest(setup_path, setup_metadata)
        header_end = skill_raw.find(b"\n---\n", 4, 64 * 1024)
        if not skill_raw.startswith(b"---\n") or header_end < 0:
            return False
        header = skill_raw[4:header_end].decode("utf-8")
        header_lines = {line.strip() for line in header.splitlines()}
    except (CleanupError, OSError, UnicodeDecodeError):
        return False
    version = LEGACY_LAYOUT_VERSIONS[layout]
    return bool(
        f"name: {name}" in header_lines
        and (
            f"version: {version}" in header_lines
            or f'version: "{version}"' in header_lines
            or f"version: '{version}'" in header_lines
        )
        and 'mcp-package: "@ycse/nanobanana-mcp"' in header_lines
        and b"@ycse/nanobanana-mcp" in setup_raw
    )


def _inspect_skill(skills_directory: Path, name: str, layout: str) -> SkillInspection:
    path = skills_directory / name
    metadata = _optional_lstat(path)
    if metadata is None:
        return SkillInspection(
            name=name,
            layout=layout,
            path=path,
            status="absent",
            exists=False,
            managed=False,
            legacy_detected=False,
            safe_to_remediate=True,
        )
    if stat.S_ISLNK(metadata.st_mode):
        return SkillInspection(
            name=name,
            layout=layout,
            path=path,
            status="unsafe_symlink",
            exists=True,
            managed=False,
            legacy_detected=True,
            safe_to_remediate=False,
        )
    if not stat.S_ISDIR(metadata.st_mode):
        return SkillInspection(
            name=name,
            layout=layout,
            path=path,
            status="unsafe_nonregular",
            exists=True,
            managed=False,
            legacy_detected=True,
            safe_to_remediate=False,
        )
    managed = name == "banana" and _valid_managed_marker(path)
    try:
        tree_digest = _skill_tree_digest(path)
    except CleanupError:
        return SkillInspection(
            name=name,
            layout=layout,
            path=path,
            status="unsafe_changed_or_unreadable",
            exists=True,
            managed=managed,
            legacy_detected=not managed,
            safe_to_remediate=False,
        )
    recognized = _legacy_layout_signature_matches(path, name, layout)
    return SkillInspection(
        name=name,
        layout=layout,
        path=path,
        status=(
            "managed_current"
            if managed
            else "legacy_recognized"
            if recognized
            else "ambiguous_same_name_unmanaged"
        ),
        exists=True,
        managed=managed,
        legacy_detected=not managed,
        safe_to_remediate=managed or recognized,
        snapshot=FileSnapshot.from_stat(metadata),
        tree_digest=tree_digest,
    )


def inspect_state() -> Inspection:
    home, claude_directory, skills_directory = _paths()
    claude_metadata = _optional_lstat(claude_directory)
    if claude_metadata is not None and not stat.S_ISDIR(claude_metadata.st_mode):
        settings = SettingsInspection(
            path=claude_directory / SETTINGS_NAME,
            status=(
                "unsafe_parent_symlink"
                if stat.S_ISLNK(claude_metadata.st_mode)
                else "unsafe_parent_nonregular"
            ),
            exists=False,
            safe_to_remediate=False,
        )
        skills = tuple(
            SkillInspection(
                name=name,
                layout=layout,
                path=skills_directory / name,
                status="unsafe_parent",
                exists=False,
                managed=False,
                legacy_detected=False,
                safe_to_remediate=False,
            )
            for name, layout in LEGACY_SKILLS
        )
        return Inspection(
            home=home,
            claude_directory=claude_directory,
            skills_directory=skills_directory,
            settings=settings,
            skills=skills,
        )
    settings = _inspect_settings(claude_directory / SETTINGS_NAME)
    skills_metadata = _optional_lstat(skills_directory)
    if skills_metadata is not None and not stat.S_ISDIR(skills_metadata.st_mode):
        skills = tuple(
            SkillInspection(
                name=name,
                layout=layout,
                path=skills_directory / name,
                status=(
                    "unsafe_parent_symlink"
                    if stat.S_ISLNK(skills_metadata.st_mode)
                    else "unsafe_parent_nonregular"
                ),
                exists=False,
                managed=False,
                legacy_detected=True,
                safe_to_remediate=False,
            )
            for name, layout in LEGACY_SKILLS
        )
    else:
        skills = tuple(
            _inspect_skill(skills_directory, name, layout)
            for name, layout in LEGACY_SKILLS
        )
    return Inspection(
        home=home,
        claude_directory=claude_directory,
        skills_directory=skills_directory,
        settings=settings,
        skills=skills,
    )


def _require_remediable(inspection: Inspection) -> None:
    if not inspection.settings.safe_to_remediate:
        raise CleanupError(
            "unsafe_legacy_settings",
            "Claude settings are unsafe to remediate. Refusing all changes.",
            details={"status": inspection.settings.status},
        )
    unsafe_skills = [
        item
        for item in inspection.skills
        if item.legacy_detected and not item.safe_to_remediate
    ]
    if unsafe_skills:
        raise CleanupError(
            "unsafe_legacy_skill",
            "A legacy skill target is not one safely movable directory. Refusing all changes.",
            details={"targets": [item.name for item in unsafe_skills]},
        )
    settings = inspection.settings
    if settings.legacy_server_detected:
        if settings.value is None:
            raise CleanupError(
                "unsafe_legacy_settings",
                "Claude settings could not be validated for cleanup.",
            )
        _serialize_settings(_settings_without_legacy_server(settings.value))


def _fingerprint(inspection: Inspection) -> str:
    _require_remediable(inspection)
    settings = inspection.settings
    settings_material: dict[str, Any] = {
        "status": settings.status,
        "legacy_server": settings.legacy_server_detected,
        "credential": settings.credential_detected,
    }
    if settings.raw is not None and settings.snapshot is not None:
        settings_material["raw_sha256"] = hashlib.sha256(settings.raw).hexdigest()
        settings_material["identity"] = settings.snapshot.fingerprint_material()
    skills_material = []
    for item in inspection.skills:
        material: dict[str, Any] = {
            "name": item.name,
            "layout": item.layout,
            "status": item.status,
            "legacy": item.legacy_detected,
        }
        if item.snapshot is not None:
            material["identity"] = item.snapshot.fingerprint_material()
            material["tree_sha256"] = item.tree_digest
        skills_material.append(material)
    canonical = json.dumps(
        {
            "settings": settings_material,
            "skills": skills_material,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    digest = hashlib.sha256()
    digest.update(FINGERPRINT_DOMAIN)
    digest.update(len(canonical).to_bytes(8, "big"))
    digest.update(canonical)
    return digest.hexdigest()


def _proposed_actions(inspection: Inspection) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if inspection.settings.legacy_server_detected:
        actions.append(
            {
                "action": "remove_legacy_mcp_server",
                "target": str(inspection.settings.path),
                "backup": "unique private sibling backup created at confirmation",
                "preserves_unrelated_settings": True,
            }
        )
    for item in inspection.legacy_skills:
        actions.append(
            {
                "action": "move_legacy_skill",
                "layout": item.layout,
                "target": str(item.path),
                "backup": "unique private sibling backup created at confirmation",
            }
        )
    return actions


def dry_run_result(inspection: Inspection) -> dict[str, Any]:
    fingerprint = _fingerprint(inspection)
    return {
        "schema_version": 1,
        "operation": "legacy_public_install_remediation",
        "dry_run": True,
        "will_write": False,
        "network_called": False,
        "requires_review": inspection.remediation_required,
        "fingerprint": fingerprint,
        "scan": inspection.public(),
        "proposed_actions": _proposed_actions(inspection),
        "credential_rotation_or_revocation_required": (
            inspection.credential_rotation_required
        ),
        "local_cleanup_revokes_credential": False,
    }


def _descriptor_operations_available() -> bool:
    return bool(
        os.name != "nt"
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and os.rename in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
    )


def _directory_path_matches(path: Path, descriptor: int) -> bool:
    try:
        path_metadata = os.stat(path, follow_symlinks=False)
        descriptor_metadata = os.fstat(descriptor)
    except OSError:
        return False
    return bool(
        stat.S_ISDIR(path_metadata.st_mode)
        and path_metadata.st_dev == descriptor_metadata.st_dev
        and path_metadata.st_ino == descriptor_metadata.st_ino
    )


def _open_directory_path(path: Path, *, code: str) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or not _directory_path_matches(
            path, descriptor
        ):
            os.close(descriptor)
            raise OSError("directory identity mismatch")
        return descriptor
    except OSError as exc:
        raise CleanupError(
            code,
            "A legacy cleanup directory could not be held without following links.",
        ) from exc


def _open_directory_at(
    parent_descriptor: int,
    name: str,
    path: Path,
    *,
    code: str,
) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or not _directory_path_matches(
            path, descriptor
        ):
            os.close(descriptor)
            raise OSError("directory identity mismatch")
        return descriptor
    except OSError as exc:
        raise CleanupError(
            code,
            "A legacy cleanup directory changed or could not be held safely.",
        ) from exc


def _entry_matches_directory(
    parent_descriptor: int,
    name: str,
    descriptor: int,
) -> bool:
    try:
        entry_metadata = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        descriptor_metadata = os.fstat(descriptor)
    except OSError:
        return False
    return bool(
        stat.S_ISDIR(entry_metadata.st_mode)
        and entry_metadata.st_dev == descriptor_metadata.st_dev
        and entry_metadata.st_ino == descriptor_metadata.st_ino
    )


def _entry_matches_file(
    parent_descriptor: int,
    name: str,
    descriptor: int,
) -> bool:
    try:
        entry_metadata = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        descriptor_metadata = os.fstat(descriptor)
    except OSError:
        return False
    return bool(
        stat.S_ISREG(entry_metadata.st_mode)
        and entry_metadata.st_nlink == 1
        and descriptor_metadata.st_nlink == 1
        and entry_metadata.st_dev == descriptor_metadata.st_dev
        and entry_metadata.st_ino == descriptor_metadata.st_ino
    )


def _open_settings_at(
    claude_descriptor: int,
    inspection: SettingsInspection,
) -> tuple[int, bytes]:
    if inspection.raw is None or inspection.snapshot is None:
        raise CleanupError(
            "cleanup_state_changed",
            "Claude settings no longer match the reviewed cleanup state.",
        )
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor: int | None = None
    succeeded = False
    try:
        descriptor = os.open(SETTINGS_NAME, flags, dir_fd=claude_descriptor)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or not inspection.snapshot.same_identity(metadata)
            or stat.S_IMODE(metadata.st_mode) != stat.S_IMODE(inspection.snapshot.mode)
            or not _entry_matches_file(
                claude_descriptor,
                SETTINGS_NAME,
                descriptor,
            )
        ):
            raise CleanupError(
                "cleanup_state_changed",
                "Claude settings changed after review. No cleanup was performed.",
            )
        raw = _bounded_read(
            descriptor,
            MAX_SETTINGS_BYTES,
            code="cleanup_state_changed",
        )
        if raw != inspection.raw:
            raise CleanupError(
                "cleanup_state_changed",
                "Claude settings changed after review. No cleanup was performed.",
            )
        succeeded = True
        return descriptor, raw
    except OSError as exc:
        raise CleanupError(
            "cleanup_state_changed",
            "Claude settings changed or could not be opened safely.",
        ) from exc
    finally:
        if descriptor is not None and not succeeded:
            os.close(descriptor)


def _create_private_directory_at(
    parent_descriptor: int,
    parent_path: Path,
    prefix: str,
    fingerprint: str,
) -> tuple[str, Path, int]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for _attempt in range(16):
        name = f"{prefix}-{timestamp}-{fingerprint[:12]}-{os.urandom(12).hex()}"
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            continue
        except OSError as exc:
            raise CleanupError(
                "legacy_backup_failed",
                "A private legacy backup directory could not be created safely.",
            ) from exc
        path = parent_path / name
        descriptor: int | None = None
        try:
            descriptor = _open_directory_at(
                parent_descriptor,
                name,
                path,
                code="legacy_backup_failed",
            )
            os.fchmod(descriptor, 0o700)
            metadata = os.fstat(descriptor)
            if stat.S_IMODE(metadata.st_mode) != 0o700 or not _entry_matches_directory(
                parent_descriptor,
                name,
                descriptor,
            ):
                raise OSError("backup directory verification failed")
            return name, path, descriptor
        except (CleanupError, OSError) as exc:
            retained_details: dict[str, Any] = {
                "path": str(path),
                "path_binding_verified": False,
                "verify_device_and_inode": True,
            }
            if descriptor is not None:
                try:
                    metadata = os.fstat(descriptor)
                    retained_details.update(
                        {
                            "device": metadata.st_dev,
                            "inode": metadata.st_ino,
                            "path_binding_verified": _entry_matches_directory(
                                parent_descriptor,
                                name,
                                descriptor,
                            ),
                        }
                    )
                except OSError:
                    pass
            if descriptor is not None:
                os.close(descriptor)
            if isinstance(exc, CleanupError):
                exc.details["retained_backup_directory"] = retained_details
                raise
            raise CleanupError(
                "legacy_backup_failed",
                "A private legacy backup directory could not be secured.",
                details={"retained_backup_directory": retained_details},
            ) from exc
    raise CleanupError(
        "legacy_backup_failed",
        "A unique private legacy backup directory could not be allocated.",
    )


def _settings_without_legacy_server(settings: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(settings)
    servers = result.get("mcpServers")
    if isinstance(servers, dict):
        servers.pop(LEGACY_MCP_NAME, None)
    return result


def _serialize_settings(settings: dict[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                settings,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise CleanupError(
            "unsafe_legacy_settings",
            "Claude settings cannot be serialized without changing unsupported data.",
        ) from exc


def _publish_exclusive_at(
    directory_descriptor: int,
    directory_path: Path,
    name: str,
    data: bytes,
    mode: int,
) -> None:
    temporary_name = f".{name}.banana-cleanup-{os.urandom(16).hex()}.tmp"
    temporary_path = directory_path / temporary_name
    temporary_exists = False
    publication_may_exist = False
    descriptor: int | None = None
    temporary_identity: tuple[int, int] | None = None
    published_identity: tuple[int, int] | None = None
    active_error: CleanupError | None = None
    active_cause: BaseException | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(
            temporary_name,
            flags,
            0o600,
            dir_fd=directory_descriptor,
        )
        temporary_exists = True
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise CleanupError(
                "settings_publication_failed",
                "The temporary settings output was not one regular file.",
            )
        temporary_identity = (metadata.st_dev, metadata.st_ino)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), mode)
            final_metadata = os.fstat(handle.fileno())
            if (
                final_metadata.st_nlink != 1
                or stat.S_IMODE(final_metadata.st_mode) != mode
            ):
                raise CleanupError(
                    "settings_publication_failed",
                    "The replacement settings permissions could not be preserved.",
                )
        if not _directory_path_matches(directory_path, directory_descriptor):
            raise CleanupError(
                "cleanup_state_changed",
                "The Claude settings directory changed during publication.",
            )
        source_metadata = os.stat(
            temporary_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        held_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(source_metadata.st_mode)
            or source_metadata.st_nlink != 1
            or (source_metadata.st_dev, source_metadata.st_ino) != temporary_identity
            or (held_metadata.st_dev, held_metadata.st_ino) != temporary_identity
            or held_metadata.st_nlink != 1
        ):
            raise CleanupError(
                "settings_publication_failed",
                "The temporary settings output changed before publication.",
            )
        publication_may_exist = True
        try:
            _exclusive_rename_at(
                directory_descriptor,
                temporary_name,
                directory_descriptor,
                name,
            )
        except FileExistsError as exc:
            publication_may_exist = False
            raise CleanupError(
                "cleanup_state_changed",
                "A concurrent settings writer recreated the active path. It was not overwritten.",
            ) from exc
        except BananaError as exc:
            publication_may_exist = False
            raise CleanupError(
                "settings_exclusive_rename_unavailable",
                "This host or filesystem cannot atomically publish replacement settings without overwriting a concurrent writer.",
            ) from exc
        temporary_exists = False
        published_metadata = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        published_identity = (published_metadata.st_dev, published_metadata.st_ino)
        if (
            not stat.S_ISREG(published_metadata.st_mode)
            or published_metadata.st_nlink != 1
            or published_identity != temporary_identity
        ):
            raise CleanupError(
                "settings_publication_failed",
                "The published settings changed before they could be accepted.",
            )
        os.fsync(directory_descriptor)
        if not _directory_path_matches(directory_path, directory_descriptor):
            raise CleanupError(
                "cleanup_state_changed",
                "The Claude settings directory changed after publication.",
            )
        committed_metadata = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        published_identity = (committed_metadata.st_dev, committed_metadata.st_ino)
        if (
            not stat.S_ISREG(committed_metadata.st_mode)
            or committed_metadata.st_nlink != 1
            or published_identity != temporary_identity
        ):
            raise CleanupError(
                "settings_publication_failed",
                "The committed settings changed before they could be accepted.",
            )
    except CleanupError as exc:
        active_error = exc
    except OSError as exc:
        active_error = CleanupError(
            "settings_publication_failed",
            "Replacement settings could not be published safely.",
        )
        active_cause = exc
    finally:
        if descriptor is not None:
            os.close(descriptor)

    if active_error is None:
        return
    observed_temporary: os.stat_result | None = None
    temporary_identity_unknown = False
    if temporary_exists:
        try:
            observed_temporary = os.stat(
                temporary_name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            temporary_exists = False
        except OSError:
            temporary_identity_unknown = True
    if publication_may_exist and published_identity is None:
        try:
            observed_publication = os.stat(
                name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except OSError:
            if temporary_exists and not temporary_identity_unknown:
                publication_may_exist = False
        else:
            published_identity = (
                observed_publication.st_dev,
                observed_publication.st_ino,
            )
    active_error.details["recovery_required"] = (
        temporary_exists or publication_may_exist
    )
    if temporary_identity is not None:
        active_error.details["intended_settings_identity"] = {
            "device": temporary_identity[0],
            "inode": temporary_identity[1],
        }
    if temporary_exists:
        if observed_temporary is None:
            active_error.details["temporary_settings_path"] = str(temporary_path)
            active_error.details["temporary_settings_identity_unknown"] = True
        else:
            active_error.details["temporary_settings_path"] = str(temporary_path)
            active_error.details["temporary_settings_identity"] = {
                "device": observed_temporary.st_dev,
                "inode": observed_temporary.st_ino,
            }
            active_error.details["temporary_settings_path_requires_identity_check"] = (
                True
            )
    if publication_may_exist:
        active_error.details["published_settings_path"] = str(directory_path / name)
        if published_identity is None:
            active_error.details["published_settings_identity_unknown"] = True
        else:
            active_error.details["published_settings_identity"] = {
                "device": published_identity[0],
                "inode": published_identity[1],
            }
            active_error.details["published_settings_path_requires_identity_check"] = (
                True
            )
    if active_cause is not None:
        raise active_error from active_cause
    raise active_error


def _active_settings_are_exact(
    claude_descriptor: int,
    expected: bytes,
    mode: int,
) -> bool:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(SETTINGS_NAME, flags, dir_fd=claude_descriptor)
        metadata = os.fstat(descriptor)
        raw = _bounded_read(
            descriptor,
            MAX_SETTINGS_BYTES,
            code="settings_publication_failed",
        )
        return bool(
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_nlink == 1
            and stat.S_IMODE(metadata.st_mode) == mode
            and raw == expected
            and _entry_matches_file(
                claude_descriptor,
                SETTINGS_NAME,
                descriptor,
            )
        )
    except (CleanupError, OSError):
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _retain_reviewed_settings_copy_at(
    backup_directory_descriptor: int,
    backup_directory_path: Path,
    reviewed_raw: bytes,
) -> int:
    """Publish and hold a private exact-byte copy of reviewed settings."""
    _publish_exclusive_at(
        backup_directory_descriptor,
        backup_directory_path,
        SETTINGS_REVIEWED_RECOVERY_NAME,
        reviewed_raw,
        0o600,
    )
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(
            SETTINGS_REVIEWED_RECOVERY_NAME,
            flags,
            dir_fd=backup_directory_descriptor,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or not _entry_matches_file(
                backup_directory_descriptor,
                SETTINGS_REVIEWED_RECOVERY_NAME,
                descriptor,
            )
            or _bounded_read(
                descriptor,
                MAX_SETTINGS_BYTES,
                code="legacy_backup_failed",
            )
            != reviewed_raw
        ):
            raise CleanupError(
                "legacy_backup_failed",
                "The reviewed settings recovery copy could not be verified.",
            )
        os.fsync(descriptor)
        os.fsync(backup_directory_descriptor)
        retained = descriptor
        descriptor = None
        return retained
    except CleanupError:
        raise
    except OSError as exc:
        raise CleanupError(
            "legacy_backup_failed",
            "The reviewed settings recovery copy could not be held safely.",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _restore_settings_copy_exclusive_at(
    claude_descriptor: int,
    claude_directory: Path,
    reviewed_raw: bytes,
    original_mode: int,
) -> None:
    """Restore reviewed bytes without replacing a concurrent active entry."""
    try:
        os.stat(
            SETTINGS_NAME,
            dir_fd=claude_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise CleanupError(
            "legacy_settings_restore_failed",
            "The active settings path could not be checked before restoration.",
        ) from exc
    else:
        raise CleanupError(
            "legacy_settings_restore_blocked",
            "A concurrent active settings entry was not overwritten. The reviewed original remains in the private recovery backup.",
        )
    _publish_exclusive_at(
        claude_descriptor,
        claude_directory,
        SETTINGS_NAME,
        reviewed_raw,
        original_mode,
    )
    if not _active_settings_are_exact(
        claude_descriptor,
        reviewed_raw,
        original_mode,
    ):
        raise CleanupError(
            "legacy_settings_restore_failed",
            "The restored settings changed before they could be accepted.",
        )


def _remediate_settings_at(
    claude_descriptor: int,
    inspection: Inspection,
    fingerprint: str,
) -> HeldSettingsBackup:
    settings = inspection.settings
    if settings.snapshot is None or settings.value is None or settings.raw is None:
        raise CleanupError(
            "cleanup_state_changed",
            "Claude settings no longer match the reviewed cleanup state.",
        )
    source_descriptor, reviewed_raw = _open_settings_at(
        claude_descriptor,
        settings,
    )
    backup_root_descriptor: int | None = None
    backup_descriptor: int | None = None
    reviewed_recovery_descriptor: int | None = None
    backup_root_name = ""
    backup_root_path: Path | None = None
    claimed = False
    backup_matches_reviewed = False
    completed = False
    original_mode = stat.S_IMODE(settings.snapshot.mode)
    try:
        (
            backup_root_name,
            backup_root_path,
            backup_root_descriptor,
        ) = _create_private_directory_at(
            claude_descriptor,
            inspection.claude_directory,
            "banana-legacy-settings-backup",
            fingerprint,
        )
        if not _directory_path_matches(
            inspection.claude_directory,
            claude_descriptor,
        ) or not _entry_matches_file(
            claude_descriptor,
            SETTINGS_NAME,
            source_descriptor,
        ):
            raise CleanupError(
                "cleanup_state_changed",
                "Claude settings changed before backup. No active data was replaced.",
            )
        revalidated_raw = _bounded_read(
            source_descriptor,
            MAX_SETTINGS_BYTES,
            code="cleanup_state_changed",
        )
        if revalidated_raw != reviewed_raw:
            raise CleanupError(
                "cleanup_state_changed",
                "Claude settings changed before backup. No active data was replaced.",
            )
        try:
            _exclusive_rename_at(
                claude_descriptor,
                SETTINGS_NAME,
                backup_root_descriptor,
                SETTINGS_NAME,
            )
        except BaseException as exc:
            if isinstance(exc, Exception):
                raise
            backup_root_bound = bool(
                backup_root_path is not None
                and _directory_path_matches(
                    backup_root_path,
                    backup_root_descriptor,
                )
            )
            backup_entry_exact = _entry_matches_file(
                backup_root_descriptor,
                SETTINGS_NAME,
                source_descriptor,
            )
            active_entry_exact = _entry_matches_file(
                claude_descriptor,
                SETTINGS_NAME,
                source_descriptor,
            )
            if backup_entry_exact and not active_entry_exact:
                interrupt_restoration_error: BaseException | None = None
                try:
                    _restore_settings_copy_exclusive_at(
                        claude_descriptor,
                        inspection.claude_directory,
                        reviewed_raw,
                        original_mode,
                    )
                except BaseException as recovery_exc:
                    interrupt_restoration_error = recovery_exc
                if _active_settings_are_exact(
                    claude_descriptor,
                    reviewed_raw,
                    original_mode,
                ):
                    raise
                held_metadata = os.fstat(source_descriptor)
                interrupt_recovery_path = (
                    backup_root_path / SETTINGS_NAME
                    if backup_root_path is not None
                    else None
                )
                try:
                    os.stat(
                        SETTINGS_NAME,
                        dir_fd=claude_descriptor,
                        follow_symlinks=False,
                    )
                    observed_active_present = True
                except OSError:
                    observed_active_present = False
                interrupt_details: dict[str, Any] = {
                    "recovery_required": True,
                    "settings_restore_complete": False,
                    "settings_recovery_backup": {
                        "path": (
                            str(interrupt_recovery_path)
                            if backup_root_bound and interrupt_recovery_path is not None
                            else None
                        ),
                        "last_known_path": (
                            str(interrupt_recovery_path)
                            if interrupt_recovery_path is not None
                            else None
                        ),
                        "device": held_metadata.st_dev,
                        "inode": held_metadata.st_ino,
                        "last_observed_link_count": held_metadata.st_nlink,
                        "path_binding_verified": bool(
                            backup_root_bound and backup_entry_exact
                        ),
                        "path_unknown": not (backup_root_bound and backup_entry_exact),
                        "contains_exact_reviewed_bytes": bool(
                            backup_entry_exact
                            and _bounded_read(
                                source_descriptor,
                                MAX_SETTINGS_BYTES,
                                code="legacy_backup_failed",
                            )
                            == reviewed_raw
                        ),
                        "verify_device_and_inode": True,
                    },
                    "observed_active_entry_present": observed_active_present,
                }
                if interrupt_restoration_error is not None:
                    interrupt_details["settings_restore_recovery"] = {
                        "error": (
                            interrupt_restoration_error.code
                            if isinstance(interrupt_restoration_error, CleanupError)
                            else "legacy_settings_restore_interrupted"
                        ),
                        "message": str(interrupt_restoration_error),
                    }
                raise CleanupError(
                    "legacy_settings_restore_failed",
                    "The interrupted settings claim could not be restored automatically. The exact retained settings identity is recorded for recovery.",
                    details=interrupt_details,
                ) from exc
            raise
        claimed = True

        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        backup_descriptor = os.open(
            SETTINGS_NAME,
            flags,
            dir_fd=backup_root_descriptor,
        )
        backup_metadata = os.fstat(backup_descriptor)
        backup_matches_reviewed = bool(
            stat.S_ISREG(backup_metadata.st_mode)
            and backup_metadata.st_nlink == 1
            and backup_metadata.st_dev == settings.snapshot.device
            and backup_metadata.st_ino == settings.snapshot.inode
            and _entry_matches_file(
                backup_root_descriptor,
                SETTINGS_NAME,
                backup_descriptor,
            )
        )
        if not backup_matches_reviewed:
            raise CleanupError(
                "cleanup_state_changed",
                "Claude settings changed while the private backup was claimed.",
            )
        backup_raw = _bounded_read(
            backup_descriptor,
            MAX_SETTINGS_BYTES,
            code="cleanup_state_changed",
        )
        if backup_raw != reviewed_raw:
            backup_matches_reviewed = False
            raise CleanupError(
                "cleanup_state_changed",
                "Claude settings changed while the private backup was claimed.",
            )
        os.fchmod(backup_descriptor, 0o600)
        backup_metadata = os.fstat(backup_descriptor)
        if (
            backup_metadata.st_nlink != 1
            or stat.S_IMODE(backup_metadata.st_mode) != 0o600
        ):
            backup_matches_reviewed = False
            raise CleanupError(
                "legacy_backup_failed",
                "The exact settings backup could not be made private.",
            )
        os.fsync(backup_descriptor)
        os.fsync(backup_root_descriptor)

        replacement = _serialize_settings(
            _settings_without_legacy_server(settings.value)
        )
        _publish_exclusive_at(
            claude_descriptor,
            inspection.claude_directory,
            SETTINGS_NAME,
            replacement,
            original_mode,
        )
        if (
            not _active_settings_are_exact(
                claude_descriptor,
                replacement,
                original_mode,
            )
            or not _directory_path_matches(
                inspection.claude_directory,
                claude_descriptor,
            )
            or backup_root_path is None
            or not _directory_path_matches(
                backup_root_path,
                backup_root_descriptor,
            )
            or stat.S_IMODE(os.fstat(backup_root_descriptor).st_mode) != 0o700
            or stat.S_IMODE(os.fstat(backup_descriptor).st_mode) != 0o600
            or not _entry_matches_file(
                backup_root_descriptor,
                SETTINGS_NAME,
                backup_descriptor,
            )
            or _bounded_read(
                backup_descriptor,
                MAX_SETTINGS_BYTES,
                code="legacy_backup_failed",
            )
            != reviewed_raw
        ):
            raise CleanupError(
                "settings_publication_failed",
                "The active settings or private backup failed final verification.",
            )
        completed = True
        held_backup = HeldSettingsBackup(
            path=backup_root_path / SETTINGS_NAME,
            directory_descriptor=backup_root_descriptor,
            descriptor=backup_descriptor,
            replacement=replacement,
            active_mode=original_mode,
        )
        backup_root_descriptor = None
        backup_descriptor = None
        return held_backup
    except CleanupError:
        raise
    except OSError as exc:
        raise CleanupError(
            "legacy_cleanup_io_failed",
            "Legacy settings cleanup failed safely.",
        ) from exc
    finally:
        active_error = sys.exc_info()[1]
        restoration_failed = False
        restoration_error: CleanupError | None = None
        reviewed_recovery_error: CleanupError | None = None
        active_restored = False
        visible_recovery_path: str | None = None
        intended_source_receipt: dict[str, Any] | None = None
        observed_backup_receipt: dict[str, Any] | None = None
        reviewed_recovery_receipt: dict[str, Any] | None = None
        try:
            if claimed and not completed and backup_root_descriptor is not None:
                if not backup_matches_reviewed and backup_root_path is not None:
                    try:
                        reviewed_recovery_descriptor = (
                            _retain_reviewed_settings_copy_at(
                                backup_root_descriptor,
                                backup_root_path,
                                reviewed_raw,
                            )
                        )
                    except CleanupError as exc:
                        reviewed_recovery_error = exc
                try:
                    _restore_settings_copy_exclusive_at(
                        claude_descriptor,
                        inspection.claude_directory,
                        reviewed_raw,
                        original_mode,
                    )
                    active_restored = True
                except CleanupError as exc:
                    restoration_failed = True
                    restoration_error = exc
                except OSError:
                    restoration_failed = True
                backup_directory_bound = bool(
                    backup_root_path is not None
                    and _directory_path_matches(
                        backup_root_path,
                        backup_root_descriptor,
                    )
                )
                if backup_descriptor is not None:
                    observed = os.fstat(backup_descriptor)
                    observed_bound = bool(
                        backup_directory_bound
                        and _entry_matches_file(
                            backup_root_descriptor,
                            SETTINGS_NAME,
                            backup_descriptor,
                        )
                    )
                    observed_path = (
                        backup_root_path / SETTINGS_NAME
                        if backup_root_path is not None
                        else None
                    )
                    observed_backup_receipt = {
                        "path": (
                            str(observed_path)
                            if observed_bound and observed_path is not None
                            else None
                        ),
                        "last_known_path": (
                            str(observed_path) if observed_path is not None else None
                        ),
                        "device": observed.st_dev,
                        "inode": observed.st_ino,
                        "last_observed_link_count": observed.st_nlink,
                        "path_binding_verified": observed_bound,
                        "path_unknown": not observed_bound,
                        "matches_reviewed_source": backup_matches_reviewed,
                        "verify_device_and_inode": True,
                    }
                    if backup_matches_reviewed and observed_bound:
                        visible_recovery_path = str(observed_path)
                if reviewed_recovery_descriptor is not None:
                    recovery_metadata = os.fstat(reviewed_recovery_descriptor)
                    recovery_bound = bool(
                        backup_directory_bound
                        and _entry_matches_file(
                            backup_root_descriptor,
                            SETTINGS_REVIEWED_RECOVERY_NAME,
                            reviewed_recovery_descriptor,
                        )
                    )
                    recovery_path = (
                        backup_root_path / SETTINGS_REVIEWED_RECOVERY_NAME
                        if backup_root_path is not None
                        else None
                    )
                    reviewed_recovery_receipt = {
                        "path": (
                            str(recovery_path)
                            if recovery_bound and recovery_path is not None
                            else None
                        ),
                        "last_known_path": (
                            str(recovery_path) if recovery_path is not None else None
                        ),
                        "device": recovery_metadata.st_dev,
                        "inode": recovery_metadata.st_ino,
                        "last_observed_link_count": recovery_metadata.st_nlink,
                        "path_binding_verified": recovery_bound,
                        "path_unknown": not recovery_bound,
                        "contains_exact_reviewed_bytes": True,
                        "verify_device_and_inode": True,
                    }
                if not backup_matches_reviewed:
                    intended_metadata = os.fstat(source_descriptor)
                    intended_source_receipt = {
                        "path": None,
                        "last_known_path": str(settings.path),
                        "device": intended_metadata.st_dev,
                        "inode": intended_metadata.st_ino,
                        "last_observed_link_count": intended_metadata.st_nlink,
                        "path_binding_verified": False,
                        "path_unknown": True,
                        "reviewed_bytes_restored_to_active": active_restored,
                        "verify_device_and_inode": True,
                    }
        finally:
            if reviewed_recovery_descriptor is not None:
                os.close(reviewed_recovery_descriptor)
            if backup_descriptor is not None:
                os.close(backup_descriptor)
            os.close(source_descriptor)
            if backup_root_descriptor is not None:
                os.close(backup_root_descriptor)
            if (
                not claimed
                and backup_root_name
                and backup_root_path is not None
                and isinstance(active_error, CleanupError)
            ):
                active_error.details["retained_settings_backup_directory"] = {
                    "path": str(backup_root_path),
                    "path_binding_verified": False,
                    "verify_device_and_inode": True,
                }
        if claimed and not completed and isinstance(active_error, CleanupError):
            active_error.details["settings_restore_complete"] = active_restored
            if restoration_error is not None:
                recovery_error: dict[str, Any] = {
                    "error": restoration_error.code,
                    "message": restoration_error.message,
                }
                if restoration_error.details:
                    recovery_error["details"] = dict(restoration_error.details)
                active_error.details["settings_restore_recovery"] = recovery_error
            if reviewed_recovery_error is not None:
                copy_error: dict[str, Any] = {
                    "error": reviewed_recovery_error.code,
                    "message": reviewed_recovery_error.message,
                }
                if reviewed_recovery_error.details:
                    copy_error["details"] = dict(reviewed_recovery_error.details)
                active_error.details["settings_reviewed_recovery_copy_error"] = (
                    copy_error
                )
            if intended_source_receipt is not None:
                active_error.details["intended_settings_source"] = (
                    intended_source_receipt
                )
            if observed_backup_receipt is not None and not backup_matches_reviewed:
                active_error.details["observed_settings_backup_entry"] = (
                    observed_backup_receipt
                )
            if reviewed_recovery_receipt is not None:
                active_error.details["settings_reviewed_recovery_copy"] = (
                    reviewed_recovery_receipt
                )
            if backup_matches_reviewed and visible_recovery_path is not None:
                active_error.details["settings_recovery_backup"] = visible_recovery_path
            elif backup_matches_reviewed:
                active_error.details["settings_recovery_retained"] = True
        if restoration_failed and active_error is None:
            details: dict[str, Any] = {"settings_restore_complete": False}
            if restoration_error is not None:
                recovery_error = {
                    "error": restoration_error.code,
                    "message": restoration_error.message,
                }
                if restoration_error.details:
                    recovery_error["details"] = dict(restoration_error.details)
                details["settings_restore_recovery"] = recovery_error
            if visible_recovery_path is not None:
                details["settings_recovery_backup"] = visible_recovery_path
            raise CleanupError(
                "legacy_settings_restore_failed",
                "The exact legacy settings remain in a private recovery backup.",
                details=details,
            )


def _hold_legacy_skills(
    skills_descriptor: int,
    inspection: Inspection,
) -> list[HeldSkill]:
    held: list[HeldSkill] = []
    try:
        for item in inspection.legacy_skills:
            descriptor = _open_directory_at(
                skills_descriptor,
                item.name,
                item.path,
                code="cleanup_state_changed",
            )
            held_item = HeldSkill(item, descriptor)
            held.append(held_item)
            if (
                item.snapshot is None
                or not item.snapshot.same_identity(os.fstat(descriptor))
                or not _entry_matches_directory(
                    skills_descriptor,
                    item.name,
                    descriptor,
                )
                or _skill_tree_digest(item.path) != item.tree_digest
            ):
                raise CleanupError(
                    "cleanup_state_changed",
                    "A legacy skill changed after review. No cleanup was performed.",
                )
        return held
    except BaseException:
        for held_item in held:
            os.close(held_item.descriptor)
        raise


def _held_settings_status(
    backup: HeldSettingsBackup,
    claude_descriptor: int,
) -> dict[str, Any]:
    metadata = os.fstat(backup.descriptor)
    directory_bound = _directory_path_matches(
        backup.path.parent,
        backup.directory_descriptor,
    )
    file_bound = directory_bound and _entry_matches_file(
        backup.directory_descriptor,
        SETTINGS_NAME,
        backup.descriptor,
    )
    return {
        "settings_cleanup_committed": True,
        "settings_cleanup_currently_verified": _active_settings_are_exact(
            claude_descriptor,
            backup.replacement,
            backup.active_mode,
        ),
        "settings_backup": {
            "path": str(backup.path) if file_bound else None,
            "last_known_path": str(backup.path),
            "device": metadata.st_dev,
            "inode": metadata.st_ino,
            "last_observed_link_count": metadata.st_nlink,
            "path_binding_verified": file_bound,
            "path_unknown": not file_bound,
            "verify_device_and_inode": True,
        },
    }


def _held_skill_recovery(
    held: list[HeldSkill],
    backup_descriptor: int,
    backup_path: Path,
) -> list[dict[str, Any]]:
    directory_bound = _directory_path_matches(backup_path, backup_descriptor)
    recovery: list[dict[str, Any]] = []
    for item in held:
        if not item.moved:
            continue
        metadata = os.fstat(item.descriptor)
        bound = directory_bound and _entry_matches_directory(
            backup_descriptor,
            item.inspection.name,
            item.descriptor,
        )
        expected_path = backup_path / item.inspection.name
        receipt: dict[str, Any] = {
            "name": item.inspection.name,
            "path": str(expected_path) if bound else None,
            "last_known_path": str(expected_path),
            "device": metadata.st_dev,
            "inode": metadata.st_ino,
            "last_observed_link_count": metadata.st_nlink,
            "path_binding_verified": bound,
            "path_unknown": not bound,
            "verify_device_and_inode": True,
            "tree_digest": item.inspection.tree_digest,
        }
        if not bound:
            observed_descriptor: int | None = None
            try:
                flags = os.O_RDONLY
                if hasattr(os, "O_DIRECTORY"):
                    flags |= os.O_DIRECTORY
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                observed_descriptor = os.open(
                    item.inspection.name,
                    flags,
                    dir_fd=backup_descriptor,
                )
                observed_metadata = os.fstat(observed_descriptor)
                observed_bound = bool(
                    directory_bound
                    and _entry_matches_directory(
                        backup_descriptor,
                        item.inspection.name,
                        observed_descriptor,
                    )
                )
                receipt["observed_nonmatching_recovery_entry"] = {
                    "path": str(expected_path) if observed_bound else None,
                    "last_known_path": str(expected_path),
                    "device": observed_metadata.st_dev,
                    "inode": observed_metadata.st_ino,
                    "last_observed_link_count": observed_metadata.st_nlink,
                    "path_binding_verified": observed_bound,
                    "path_unknown": not observed_bound,
                    "verify_device_and_inode": True,
                }
            except OSError:
                pass
            finally:
                if observed_descriptor is not None:
                    os.close(observed_descriptor)
        recovery.append(receipt)
    return recovery


def _remediate_posix(
    inspection: Inspection,
    fingerprint: str,
) -> dict[str, Any]:
    claude_descriptor = _open_directory_path(
        inspection.claude_directory,
        code="cleanup_state_changed",
    )
    skills_descriptor: int | None = None
    skill_backup_descriptor: int | None = None
    skill_backup_name = ""
    skill_backup_path: Path | None = None
    held_skills: list[HeldSkill] = []
    settings_backup: HeldSettingsBackup | None = None
    completed = False
    try:
        if not _directory_path_matches(
            inspection.claude_directory,
            claude_descriptor,
        ):
            raise CleanupError(
                "cleanup_state_changed",
                "The Claude settings directory changed after review.",
            )
        if inspection.legacy_skills:
            skills_descriptor = _open_directory_at(
                claude_descriptor,
                "skills",
                inspection.skills_directory,
                code="cleanup_state_changed",
            )
            held_skills = _hold_legacy_skills(skills_descriptor, inspection)
            (
                skill_backup_name,
                skill_backup_path,
                skill_backup_descriptor,
            ) = _create_private_directory_at(
                skills_descriptor,
                inspection.skills_directory,
                "banana-legacy-skills-backup",
                fingerprint,
            )
            for item in held_skills:
                if not _entry_matches_directory(
                    skills_descriptor,
                    item.inspection.name,
                    item.descriptor,
                ):
                    raise CleanupError(
                        "cleanup_state_changed",
                        "A legacy skill changed before it could be backed up.",
                    )
                try:
                    _exclusive_rename_at(
                        skills_descriptor,
                        item.inspection.name,
                        skill_backup_descriptor,
                        item.inspection.name,
                    )
                except BaseException as exc:
                    if isinstance(exc, Exception):
                        raise
                    backup_entry_exact = _entry_matches_directory(
                        skill_backup_descriptor,
                        item.inspection.name,
                        item.descriptor,
                    )
                    active_entry_exact = _entry_matches_directory(
                        skills_descriptor,
                        item.inspection.name,
                        item.descriptor,
                    )
                    if backup_entry_exact and not active_entry_exact:
                        item.moved = True
                        restoration_error: BaseException | None = None
                        try:
                            _exclusive_rename_at(
                                skill_backup_descriptor,
                                item.inspection.name,
                                skills_descriptor,
                                item.inspection.name,
                            )
                        except BaseException as recovery_exc:
                            restoration_error = recovery_exc
                        restored = bool(
                            _entry_matches_directory(
                                skills_descriptor,
                                item.inspection.name,
                                item.descriptor,
                            )
                            and not _entry_matches_directory(
                                skill_backup_descriptor,
                                item.inspection.name,
                                item.descriptor,
                            )
                        )
                        if restored:
                            item.moved = False
                            os.fsync(skills_descriptor)
                            os.fsync(skill_backup_descriptor)
                            raise
                        if skill_backup_path is None:
                            raise CleanupError(
                                "legacy_skill_restore_failed",
                                "The interrupted legacy skill move could not identify its recovery directory.",
                                details={
                                    "recovery_required": True,
                                    "legacy_skill_cleanup_complete": False,
                                    "legacy_skill_automatic_restore_attempted": True,
                                },
                            ) from exc
                        recovery = _held_skill_recovery(
                            [item],
                            skill_backup_descriptor,
                            skill_backup_path,
                        )
                        details: dict[str, Any] = {
                            "recovery_required": True,
                            "legacy_skill_cleanup_complete": False,
                            "legacy_skill_automatic_restore_attempted": True,
                            "legacy_skill_recovery": recovery,
                        }
                        if restoration_error is not None:
                            details["legacy_skill_restore_recovery"] = {
                                "error": (
                                    restoration_error.code
                                    if isinstance(restoration_error, CleanupError)
                                    else "legacy_skill_restore_interrupted"
                                ),
                                "message": str(restoration_error),
                            }
                        raise CleanupError(
                            "legacy_skill_restore_failed",
                            "The interrupted legacy skill move could not be restored automatically. The exact retained directory identity is recorded for recovery.",
                            details=details,
                        ) from exc
                    raise
                item.moved = True
                if not _entry_matches_directory(
                    skill_backup_descriptor,
                    item.inspection.name,
                    item.descriptor,
                ):
                    raise CleanupError(
                        "legacy_backup_failed",
                        "A moved legacy skill failed backup identity verification.",
                    )
                if (
                    skill_backup_path is None
                    or _skill_tree_digest(skill_backup_path / item.inspection.name)
                    != item.inspection.tree_digest
                ):
                    raise CleanupError(
                        "cleanup_state_changed",
                        "A legacy skill changed while its reviewed bytes were moved to recovery.",
                    )
            os.fsync(skill_backup_descriptor)
            os.fsync(skills_descriptor)

        if inspection.settings.legacy_server_detected:
            settings_backup = _remediate_settings_at(
                claude_descriptor,
                inspection,
                fingerprint,
            )

        if (
            not _directory_path_matches(
                inspection.claude_directory,
                claude_descriptor,
            )
            or (
                skills_descriptor is not None
                and not _directory_path_matches(
                    inspection.skills_directory,
                    skills_descriptor,
                )
            )
            or (
                skill_backup_descriptor is not None
                and skill_backup_path is not None
                and (
                    not _directory_path_matches(
                        skill_backup_path,
                        skill_backup_descriptor,
                    )
                    or stat.S_IMODE(os.fstat(skill_backup_descriptor).st_mode) != 0o700
                )
            )
            or any(
                skill_backup_descriptor is None
                or not _entry_matches_directory(
                    skill_backup_descriptor,
                    item.inspection.name,
                    item.descriptor,
                )
                for item in held_skills
            )
        ):
            raise CleanupError(
                "cleanup_state_changed",
                "A cleanup directory changed before final verification.",
            )
        final_state = inspect_state()
        if not final_state.clean:
            raise CleanupError(
                "cleanup_state_changed",
                "Legacy installation state changed before final verification.",
            )
        if any(
            skill_backup_path is None
            or _skill_tree_digest(skill_backup_path / item.inspection.name)
            != item.inspection.tree_digest
            for item in held_skills
        ):
            raise CleanupError(
                "cleanup_state_changed",
                "A recovered legacy skill no longer matches its reviewed bytes.",
            )
        completed = True
        skill_backups = {
            item.inspection.name: str(skill_backup_path / item.inspection.name)
            for item in held_skills
            if skill_backup_path is not None
        }
        return {
            "settings_backup": (str(settings_backup.path) if settings_backup else None),
            "skill_backup_root": (
                str(skill_backup_path) if skill_backup_path else None
            ),
            "skill_backups": skill_backups,
        }
    except OSError as exc:
        raise CleanupError(
            "legacy_cleanup_io_failed",
            "Legacy cleanup failed safely during a descriptor-bound operation.",
        ) from exc
    finally:
        active_error = sys.exc_info()[1]
        skill_recovery: list[dict[str, Any]] = []
        settings_status: dict[str, Any] | None = None
        try:
            if (
                not completed
                and skill_backup_descriptor is not None
                and skill_backup_path is not None
            ):
                skill_recovery = _held_skill_recovery(
                    held_skills,
                    skill_backup_descriptor,
                    skill_backup_path,
                )
            if not completed and settings_backup is not None:
                settings_status = _held_settings_status(
                    settings_backup,
                    claude_descriptor,
                )
        finally:
            if settings_backup is not None:
                settings_backup.close()
            for item in held_skills:
                os.close(item.descriptor)
            if skill_backup_descriptor is not None:
                os.close(skill_backup_descriptor)
            if skills_descriptor is not None:
                os.close(skills_descriptor)
            os.close(claude_descriptor)
        if isinstance(active_error, CleanupError):
            if skill_recovery:
                active_error.details.update(
                    {
                        "recovery_required": True,
                        "legacy_skill_cleanup_complete": False,
                        "legacy_skill_automatic_restore_attempted": (
                            active_error.details.get(
                                "legacy_skill_automatic_restore_attempted",
                                False,
                            )
                        ),
                        "legacy_skill_recovery": skill_recovery,
                    }
                )
            if settings_status is not None:
                active_error.details.update(settings_status)
                active_error.details["recovery_required"] = True


def remediate_confirmed(
    inspection: Inspection,
    confirmation: str,
) -> dict[str, Any]:
    _require_remediable(inspection)
    if inspection.clean:
        return {
            "schema_version": 1,
            "operation": "legacy_public_install_remediation",
            "changed": False,
            "clean": True,
            "idempotent_noop": True,
            "network_called": False,
            "credential_rotation_or_revocation_required": False,
            "local_cleanup_revokes_credential": False,
            "settings_backup": None,
            "skill_backup_root": None,
            "skill_backups": {},
        }
    fingerprint = _fingerprint(inspection)
    if not hmac.compare_digest(confirmation, fingerprint):
        raise CleanupError(
            "cleanup_confirmation_mismatch",
            "Confirmation does not match the current safe cleanup plan. Run remediate --dry-run again.",
        )
    current = inspect_state()
    _require_remediable(current)
    current_fingerprint = _fingerprint(current)
    if not hmac.compare_digest(confirmation, current_fingerprint):
        raise CleanupError(
            "cleanup_state_changed",
            "Legacy cleanup state changed after review. No cleanup was performed.",
        )
    if not _descriptor_operations_available():
        raise CleanupError(
            "secure_remediation_unavailable",
            "This platform cannot provide the descriptor-relative operations required for safe remediation.",
        )
    backups = _remediate_posix(current, current_fingerprint)
    result = {
        "schema_version": 1,
        "operation": "legacy_public_install_remediation",
        "changed": True,
        "clean": True,
        "idempotent_noop": False,
        "network_called": False,
        "fingerprint": current_fingerprint,
        "removed_legacy_mcp_server": bool(current.settings.legacy_server_detected),
        "moved_legacy_skills": [item.name for item in current.legacy_skills],
        "credential_rotation_or_revocation_required": (
            current.credential_rotation_required
        ),
        "local_cleanup_revokes_credential": False,
        **backups,
    }
    return result


def _print_text_scan(result: dict[str, Any]) -> None:
    status = "clean" if result["clean"] else "legacy state detected"
    print(f"Banana Claude legacy scan: {status}")
    settings = cast(dict[str, Any], result["settings"])
    print(f"Settings: {settings['status']}")
    for item in cast(list[dict[str, Any]], result["legacy_skill_locations"]):
        print(f"Skill {item['name']}: {item['status']} ({item['layout']})")
    rotation = result["credential_rotation_or_revocation_required"]
    if rotation is True:
        print("Credential rotation or revocation required: yes")
        print("Local configuration removal does not revoke the credential.")
    elif rotation is False:
        print("Credential rotation or revocation required: no detected credential")
    else:
        print("Credential rotation or revocation required: unknown")


def _print_text_dry_run(result: dict[str, Any]) -> None:
    print("Banana Claude legacy cleanup review")
    print(f"Fingerprint: {result['fingerprint']}")
    actions = cast(list[dict[str, Any]], result["proposed_actions"])
    if not actions:
        print("No cleanup actions are required.")
        return
    for action in actions:
        print(f"Proposed: {action['action']} at {action['target']}")
    if result["credential_rotation_or_revocation_required"]:
        print("After cleanup, rotate or revoke the detected credential separately.")


def _print_text_result(result: dict[str, Any]) -> None:
    if not result["changed"]:
        print("Banana Claude legacy cleanup: already clean, no changes made.")
        return
    print("Banana Claude legacy cleanup completed.")
    settings_backup = result.get("settings_backup")
    if settings_backup:
        print(f"Settings backup: {settings_backup}")
    skill_backup = result.get("skill_backup_root")
    if skill_backup:
        print(f"Skill backup root: {skill_backup}")
    if result["credential_rotation_or_revocation_required"]:
        print("Credential rotation or revocation is still required.")


def build_parser() -> argparse.ArgumentParser:
    parser = SecretSafeArgumentParser(
        description="Inspect and explicitly retire legacy public Banana Claude installs"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan = subparsers.add_parser("scan", help="Read-only legacy installation scan")
    scan.add_argument("--json", action="store_true")

    remediate = subparsers.add_parser(
        "remediate",
        help="Review or fingerprint-confirm a backup-first cleanup",
    )
    action = remediate.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--confirm", metavar="FINGERPRINT")
    remediate.add_argument("--json", action="store_true")
    return parser


def _fail(error: CleanupError) -> NoReturn:
    print(json.dumps(error.as_dict(), ensure_ascii=False), file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    args = build_parser().parse_args()
    try:
        inspection = inspect_state()
        if args.command == "scan":
            result = inspection.public()
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                _print_text_scan(result)
            return 0
        if args.dry_run:
            result = dry_run_result(inspection)
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                _print_text_dry_run(result)
            return 0
        result = remediate_confirmed(inspection, cast(str, args.confirm))
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            _print_text_result(result)
        return 0
    except CleanupError as exc:
        _fail(exc)


if __name__ == "__main__":
    raise SystemExit(main())
