#!/usr/bin/env python3
"""Shared, zero-dependency core for Banana Claude.

The core routes each model through a documented Google API surface, keeps
credentials in request headers, validates requested capabilities against a
closed catalog, and writes outputs atomically.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import ctypes
import errno
import hashlib
import json
import os
import re
import stat
import struct
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, NamedTuple, NoReturn, cast

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CATALOG_PATH = SKILL_DIR / "references" / "models.json"
DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "banana-claude"
MAX_INLINE_BYTES = 20 * 1024 * 1024
MAX_PROMPT_CHARS = 65_536
MAX_PROVIDER_RESPONSE_BYTES = 128 * 1024 * 1024
MAX_PROVIDER_ERROR_BYTES = 1 * 1024 * 1024
PROVIDER_API_HOST = "generativelanguage.googleapis.com"
BIDI_CONTROL_CODEPOINTS = frozenset(
    {0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)}
)
TRANSIENT_HTTP_CODES = {408, 429, 500, 502, 503, 504}
SUPPORTED_THINKING_LEVELS = {"minimal", "high"}
USAGE_TOKEN_KEYS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "thoughts_tokens",
        "tool_use_prompt_tokens",
        "promptTokenCount",
        "candidatesTokenCount",
        "totalTokenCount",
        "cachedContentTokenCount",
        "thoughtsTokenCount",
        "toolUsePromptTokenCount",
    }
)
MAX_PROVIDER_TOKEN_COUNT = 2**63 - 1
PROVIDER_ERROR_STATUSES = frozenset(
    {
        "ABORTED",
        "ALREADY_EXISTS",
        "CANCELLED",
        "DATA_LOSS",
        "DEADLINE_EXCEEDED",
        "FAILED_PRECONDITION",
        "INTERNAL",
        "INVALID_ARGUMENT",
        "NOT_FOUND",
        "NOT_IMPLEMENTED",
        "OUT_OF_RANGE",
        "PERMISSION_DENIED",
        "RESOURCE_EXHAUSTED",
        "UNAUTHENTICATED",
        "UNAVAILABLE",
        "UNKNOWN",
    }
)
INTERACTION_FAILURE_STATUSES = frozenset(
    {"CANCELLED", "EXPIRED", "FAILED", "INCOMPLETE", "REQUIRES_ACTION"}
)
FINISH_REASONS = frozenset(
    {
        "BLOCKLIST",
        "ESCALATION",
        "FINISH_REASON_UNSPECIFIED",
        "IMAGE_OTHER",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_RECITATION",
        "IMAGE_SAFETY",
        "LANGUAGE",
        "MALFORMED_FUNCTION_CALL",
        "MAX_TOKENS",
        "NO_IMAGE",
        "OTHER",
        "PROHIBITED_CONTENT",
        "RECITATION",
        "SAFETY",
        "SPII",
        "STOP",
        "TOO_MANY_TOOL_CALLS",
        "UNEXPECTED_TOOL_CALL",
    }
)
PROMPT_BLOCK_REASONS = frozenset(
    {
        "BLOCKLIST",
        "BLOCK_REASON_UNSPECIFIED",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_SAFETY",
        "OTHER",
        "PROHIBITED_CONTENT",
        "SAFETY",
    }
)
SAFETY_CATEGORIES = frozenset(
    {
        "HARM_CATEGORY_CIVIC_INTEGRITY",
        "HARM_CATEGORY_DANGEROUS",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
        "HARM_CATEGORY_DEROGATORY",
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_IMAGE_DANGEROUS_CONTENT",
        "HARM_CATEGORY_IMAGE_HARASSMENT",
        "HARM_CATEGORY_IMAGE_HATE",
        "HARM_CATEGORY_IMAGE_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_MEDICAL",
        "HARM_CATEGORY_SEXUAL",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_TOXICITY",
        "HARM_CATEGORY_UNSPECIFIED",
        "HARM_CATEGORY_VIOLENCE",
    }
)
SAFETY_PROBABILITIES = frozenset(
    {
        "HARM_PROBABILITY_UNSPECIFIED",
        "HIGH",
        "LOW",
        "MEDIUM",
        "NEGLIGIBLE",
    }
)
SAFETY_SEVERITIES = frozenset(
    {
        "HARM_SEVERITY_HIGH",
        "HARM_SEVERITY_LOW",
        "HARM_SEVERITY_MEDIUM",
        "HARM_SEVERITY_NEGLIGIBLE",
        "HARM_SEVERITY_UNSPECIFIED",
        "HIGH",
        "LOW",
        "MEDIUM",
        "NEGLIGIBLE",
    }
)
REFERENCE_ROLE_KEYS = {
    "object": "objects",
    "character": "characters",
    "style": "styles",
}
REFERENCE_AUTHORITY_CATEGORY_FIELDS = (
    "rights_or_license",
    "identity_or_likeness",
    "customer_or_private_asset",
    "endorsement_or_representation",
)
REFERENCE_AUTHORITY_CATEGORY_VALUES = frozenset(
    {"affirmed", "not_applicable", "unresolved"}
)
MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
EXTENSION_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
VISUAL_BRIEF_SCHEMA_VERSION = "banana.visual-brief.v1"
MAX_VISUAL_BRIEF_BYTES = 1_048_576
MAX_VISUAL_BRIEF_LIST_ITEMS = 64
MAX_VISUAL_BRIEF_TEXT_CHARS = 65_536
MAX_PUBLICATION_RECEIPT_BYTES = 1_024
PUBLICATION_CAPABILITY_NAME = ".banana-publication-capability-v1"
_DESTINATION_IDENTITY_UNCHECKED = object()
VIDEO_URL_SYNTAX_ERROR = (
    "Only HTTPS YouTube watch or short URLs with a syntactically valid "
    "11-character video ID are accepted. This check does not verify that the "
    "video exists, is public, or is accessible to Google."
)
VIDEO_URL_PAID_ATTEMPT_WARNING = (
    "Banana validates only the allowed HTTPS YouTube URL syntax and 11-character "
    "ID shape. It does not preflight whether the video exists, is public, or is "
    "accessible to Google. Passing the URL asserts those conditions. An "
    "inaccessible URL can consume the one paid provider attempt."
)


class SecretSafeArgumentParser(argparse.ArgumentParser):
    """Reject invalid command lines without repeating untrusted argv text."""

    def error(self, message: str) -> NoReturn:
        del message
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid command-line arguments\n")


class BananaError(RuntimeError):
    """A user-facing error with a stable machine-readable code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        http_status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.http_status = http_status
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "error": True,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.http_status is not None:
            data["http_status"] = self.http_status
        if self.details:
            data["details"] = self.details
        return data


class OutputPublicationCapability:
    """Caller-owned handle binding an approved path to one directory inode."""

    def __init__(self, directory: Path, descriptor: int) -> None:
        self.directory = directory
        self._descriptor: int | None = descriptor

    @property
    def descriptor(self) -> int:
        if self._descriptor is None:
            raise BananaError(
                "output_capability_closed",
                "The held output publication capability is already closed.",
            )
        return self._descriptor

    @property
    def closed(self) -> bool:
        return self._descriptor is None

    def close(self) -> None:
        descriptor = self._descriptor
        if descriptor is not None:
            self._descriptor = None
            os.close(descriptor)


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    """Load and minimally validate the checked-in model catalog."""
    try:
        with CATALOG_PATH.open("r", encoding="utf-8") as handle:
            catalog = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise BananaError(
            "catalog_unavailable", f"Cannot load model catalog: {exc}"
        ) from exc

    if (
        not isinstance(catalog, dict)
        or not isinstance(catalog.get("models"), dict)
        or not catalog.get("default_model")
    ):
        raise BananaError(
            "catalog_invalid", "Model catalog is missing required fields."
        )
    return cast(dict[str, Any], catalog)


def get_model(model: str | None = None) -> tuple[str, dict[str, Any]]:
    catalog = load_catalog()
    selected = model or catalog["default_model"]
    info = catalog["models"].get(selected)
    if not info:
        available = ", ".join(sorted(catalog["models"]))
        raise BananaError(
            "unsupported_model",
            f"Unsupported model. Available: {available}",
        )
    return selected, info


def normalize_image_size(value: str | None, model_info: dict[str, Any]) -> str:
    if not value or value.lower() == "auto":
        return str(model_info["default_image_size"])
    aliases = {"0.5k": "512", "512px": "512", "1k": "1K", "2k": "2K", "4k": "4K"}
    normalized = aliases.get(value.strip().lower(), value.strip())
    if normalized not in model_info["image_sizes"]:
        supported = ", ".join(model_info["image_sizes"])
        raise BananaError(
            "unsupported_image_size",
            f"Image size is not supported by this model. Use: {supported}",
        )
    return normalized


def validate_aspect_ratio(value: str, model_info: dict[str, Any]) -> str:
    ratio = value.strip()
    if ratio not in model_info["aspect_ratios"]:
        supported = ", ".join(model_info["aspect_ratios"])
        raise BananaError(
            "unsupported_aspect_ratio",
            f"Aspect ratio is not in Banana's allowlist for this model. Use: {supported}",
        )
    return ratio


def estimate_image_cost(model: str, image_size: str, *, batch: bool = False) -> float:
    _, info = get_model(model)
    normalized_size = normalize_image_size(image_size, info)
    price_tier = "batch" if batch else "standard"
    try:
        return float(info["pricing_usd"][price_tier][normalized_size])
    except (KeyError, TypeError, ValueError) as exc:
        raise BananaError(
            "price_unavailable",
            f"No {price_tier} output price for {model} at {normalized_size}.",
        ) from exc


def output_directory(override: str | Path | None = None) -> Path:
    if override:
        checked = validate_approval_text(
            str(override),
            field="Output directory",
            max_length=4_096,
        )
        return Path(checked).expanduser().resolve()
    configured = os.environ.get("BANANA_OUTPUT_DIR")
    if configured:
        checked = validate_approval_text(
            configured,
            field="BANANA_OUTPUT_DIR",
            max_length=4_096,
        )
        return Path(checked).expanduser().resolve()
    return DEFAULT_OUTPUT_DIR.resolve()


def validate_approval_text(
    value: Any,
    *,
    field: str,
    max_length: int,
    multiline: bool = False,
    error_code: str = "unsafe_approval_text",
) -> str:
    """Validate text whose visible rendering is part of a human approval."""
    if not isinstance(value, str):
        raise BananaError(error_code, f"{field} must be a string.")
    checked = value.strip()
    if not checked:
        raise BananaError(error_code, f"{field} cannot be empty.")
    if len(checked) > max_length:
        raise BananaError(
            error_code, f"{field} exceeds the {max_length}-character client limit."
        )
    allowed_controls = {"\n"} if multiline else set()
    for character in checked:
        codepoint = ord(character)
        category = unicodedata.category(character)
        if codepoint in BIDI_CONTROL_CODEPOINTS:
            raise BananaError(
                error_code,
                f"{field} contains a bidirectional display-control character.",
            )
        if category == "Cs":
            raise BananaError(
                error_code, f"{field} contains an unpaired Unicode surrogate."
            )
        if category == "Cc" and character not in allowed_controls:
            raise BananaError(error_code, f"{field} contains a control character.")
    return checked


def validate_output_mime_type(
    value: str, model_info: dict[str, Any] | None = None
) -> str:
    if value not in {"image/png", "image/jpeg"}:
        raise BananaError(
            "unsupported_output_type",
            "Output MIME type must be image/png or image/jpeg.",
        )
    if model_info is not None and value not in model_info.get("output_mime_types", []):
        supported = ", ".join(model_info.get("output_mime_types", [])) or "none"
        raise BananaError(
            "unsupported_output_type",
            f"The selected model supports these output types: {supported}.",
        )
    return value


def resolve_provider_response_format(
    *,
    api_surface: str,
    api_profile: dict[str, Any],
    model_info: dict[str, Any],
    aspect_ratio: str,
    image_size: str,
    output_mime_type: str,
) -> dict[str, Any]:
    """Resolve the exact provider wire object before approval fingerprinting."""
    if api_surface == "interactions":
        return {
            "type": "image",
            "mime_type": output_mime_type,
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
        }

    wire_values = api_profile.get("wire_values")
    if not isinstance(wire_values, dict):
        raise BananaError(
            "catalog_invalid", "The generateContent API profile has no wire-value map."
        )

    def mapped(group: str, value: str) -> str:
        mapping = wire_values.get(group)
        resolved = mapping.get(value) if isinstance(mapping, dict) else None
        if not isinstance(resolved, str) or not resolved:
            raise BananaError(
                "catalog_invalid",
                f"The generateContent API profile cannot encode {group} value '{value}'.",
            )
        return resolved

    image_format = {
        "mimeType": mapped("output_mime_type", output_mime_type),
        "aspectRatio": mapped("aspect_ratio", aspect_ratio),
    }
    if model_info["features"].get("configurable_image_size"):
        image_format["imageSize"] = mapped("image_size", image_size)
    return {"image": image_format}


def normalize_label(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")[:80] or "image"


def api_key_from_env() -> str:
    value = os.environ.get("GEMINI_API_KEY")
    if value and value.strip():
        return value.strip()
    raise BananaError(
        "missing_api_key",
        "No Gemini API key is configured. Configure the plugin secret or set GEMINI_API_KEY.",
        details={"provider_called": False},
    )


def _read_regular_file_bounded(
    path: Path,
    *,
    max_bytes: int,
    unreadable_code: str,
    oversized_code: str,
    label: str,
) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise BananaError(
                unreadable_code, f"{label} must be a regular file: {path}"
            )
        handle = os.fdopen(descriptor, "rb")
        descriptor = None
        with handle:
            raw = handle.read(max_bytes + 1)
    except OSError as exc:
        raise BananaError(
            unreadable_code, f"Cannot read {label.lower()}: {path}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) > max_bytes:
        raise BananaError(
            oversized_code, f"{label} exceeds the {max_bytes}-byte safety limit: {path}"
        )
    return raw


def _matches_image_signature(data: bytes, mime_type: str) -> bool:
    if mime_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime_type == "image/webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False


def _reference_input(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, (str, Path)):
        raise BananaError(
            "reference_metadata_required",
            "Each image reference requires a path, a safe disclosure alias, a role, and a purpose.",
        )
    if not isinstance(value, dict):
        raise BananaError(
            "invalid_reference",
            "Each reference must be a path or a structured reference object.",
        )
    if set(value) - {"path", "disclosure_alias", "role", "purpose", "subject_id"}:
        raise BananaError(
            "invalid_reference",
            "A structured reference contains unsupported fields.",
        )
    raw_path = value.get("path")
    if not isinstance(raw_path, (str, Path)) or not str(raw_path).strip():
        raise BananaError(
            "invalid_reference", "A structured reference requires a non-empty path."
        )
    role = value.get("role")
    if role not in REFERENCE_ROLE_KEYS:
        allowed = ", ".join(REFERENCE_ROLE_KEYS)
        raise BananaError(
            "invalid_reference_role", f"Reference role must be one of: {allowed}."
        )
    if value.get("disclosure_alias") is None or value.get("purpose") is None:
        raise BananaError(
            "reference_metadata_required",
            "Each image reference requires a non-sensitive disclosure alias and a non-empty Banana prompt annotation for purpose.",
        )

    normalized: dict[str, Any] = {
        "path": raw_path,
        "role": role,
        "disclosure_alias": None,
        "purpose": None,
        "subject_id": None,
    }
    for field in ("disclosure_alias", "purpose", "subject_id"):
        raw = value.get(field)
        if raw is None:
            continue
        normalized[field] = validate_approval_text(
            raw,
            field=f"Reference {field}",
            max_length=120,
            error_code="invalid_reference_metadata",
        )
    return normalized


def validate_references(
    values: Iterable[str | Path | dict[str, Any]],
    limits: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_values = list(values)
    total_limit = int(limits.get("banana_policy_total", 0))
    if len(raw_values) > total_limit:
        raise BananaError(
            "too_many_references",
            f"Banana policy allows at most {total_limit} reference images for this route, "
            f"received {len(raw_values)}.",
        )
    references: list[dict[str, Any]] = []
    role_counts = {role: 0 for role in REFERENCE_ROLE_KEYS}
    role_limits = limits.get("banana_policy_by_role", {})
    total_bytes = 0
    for raw_value in raw_values:
        reference_input = _reference_input(raw_value)
        role = str(reference_input["role"])
        role_counts[role] += 1
        role_limit = int(role_limits.get(REFERENCE_ROLE_KEYS[role], 0))
        if role_counts[role] > role_limit:
            raise BananaError(
                f"too_many_{role}_references",
                f"Banana policy allows at most {role_limit} {role} reference images for this route, "
                f"received {role_counts[role]}.",
            )
        path = Path(reference_input["path"]).expanduser().resolve()
        if not path.is_file():
            raise BananaError(
                "reference_not_found", f"Reference image not found: {path}"
            )
        mime_type = MIME_BY_SUFFIX.get(path.suffix.lower())
        if not mime_type:
            raise BananaError(
                "unsupported_reference_type",
                f"Unsupported reference image type: {path.suffix or '(none)'}",
            )
        remaining_bytes = MAX_INLINE_BYTES - total_bytes
        raw = _read_regular_file_bounded(
            path,
            max_bytes=remaining_bytes,
            unreadable_code="reference_unreadable",
            oversized_code="references_too_large",
            label="Reference image",
        )
        size = len(raw)
        if size < 1:
            raise BananaError("empty_reference", f"Reference image is empty: {path}")
        total_bytes += size
        if not _matches_image_signature(raw[:12], mime_type):
            raise BananaError(
                "invalid_reference_signature",
                f"Reference bytes do not match the declared {mime_type} type: {path}",
            )
        references.append(
            {
                "path": str(path),
                "mime_type": mime_type,
                "bytes": size,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "role": role,
                "disclosure_alias": reference_input["disclosure_alias"],
                "purpose": reference_input["purpose"],
                "subject_id": reference_input["subject_id"],
            }
        )
    return references


def validate_reference_paths(
    paths: Iterable[str | Path], limit: int
) -> list[dict[str, Any]]:
    """Validate local raster paths for non-provider utilities."""
    return validate_references(
        (
            {
                "path": path,
                "role": "object",
                "disclosure_alias": "local raster input",
                "purpose": "local raster composition",
            }
            for path in paths
        ),
        {
            "banana_policy_total": limit,
            "banana_policy_by_role": {
                "objects": limit,
                "characters": limit,
                "styles": limit,
            },
        },
    )


def build_reference_specs(
    paths: Iterable[str | Path],
    *,
    names: Iterable[str] = (),
    roles: Iterable[str] = (),
    purposes: Iterable[str] = (),
    subject_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Pair repeatable CLI reference fields without exposing path parsing to callers."""
    path_list = list(paths)
    metadata_lists = {
        "name": list(names),
        "role": list(roles),
        "purpose": list(purposes),
        "subject_id": list(subject_ids),
    }
    for field, values in metadata_lists.items():
        if len(values) > len(path_list):
            raise BananaError(
                "reference_metadata_mismatch",
                f"Received more --reference-{field.replace('_', '-')} values than reference paths.",
            )
    for field in ("name", "role", "purpose"):
        if path_list and len(metadata_lists[field]) != len(path_list):
            raise BananaError(
                "reference_metadata_required",
                f"Every reference requires one aligned --reference-{field.replace('_', '-')} value.",
            )
    specs: list[dict[str, Any]] = []
    for index, path in enumerate(path_list):
        role = metadata_lists["role"][index]
        purpose = metadata_lists["purpose"][index]
        subject_id = (
            metadata_lists["subject_id"][index]
            if index < len(metadata_lists["subject_id"])
            else None
        )
        specs.append(
            {
                "path": path,
                "disclosure_alias": metadata_lists["name"][index],
                "role": role,
                "purpose": purpose,
                "subject_id": subject_id or None,
            }
        )
    return specs


def validate_video_url(video_url: str | None, model_info: dict[str, Any]) -> str | None:
    if not video_url:
        return None
    if not model_info["features"].get("video_input"):
        raise BananaError(
            "video_not_supported",
            "Banana does not route video-to-image input to the selected model.",
        )
    checked_video_url = validate_approval_text(
        video_url,
        field="Video URL",
        max_length=2_048,
    )
    try:
        parsed = urllib.parse.urlsplit(checked_video_url)
        port = parsed.port
    except ValueError as exc:
        raise BananaError(
            "unsupported_video_url",
            VIDEO_URL_SYNTAX_ERROR,
        ) from exc
    hostname = (parsed.hostname or "").lower().rstrip(".")
    video_id: str | None = None
    if (
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and port in {None, 443}
        and hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}
        and parsed.path == "/watch"
    ):
        candidates = urllib.parse.parse_qs(parsed.query).get("v", [])
        if len(candidates) == 1:
            video_id = candidates[0]
    elif (
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and port in {None, 443}
        and hostname in {"youtu.be", "www.youtu.be"}
    ):
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) == 1:
            video_id = path_parts[0]
    if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise BananaError(
            "unsupported_video_url",
            VIDEO_URL_SYNTAX_ERROR,
        )
    return checked_video_url


def load_visual_brief_file(path: str | Path) -> dict[str, Any]:
    """Read one bounded, regular JSON visual-brief file."""
    raw = _read_regular_file_bounded(
        Path(path).expanduser(),
        max_bytes=MAX_VISUAL_BRIEF_BYTES,
        unreadable_code="visual_brief_unreadable",
        oversized_code="visual_brief_too_large",
        label="Visual brief",
    )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise BananaError(
            "invalid_visual_brief",
            "The visual brief file must contain one valid UTF-8 JSON object.",
        ) from exc
    if not isinstance(value, dict):
        raise BananaError(
            "invalid_visual_brief",
            "The visual brief must be one JSON object.",
        )
    return cast(dict[str, Any], value)


def _closed_object(
    value: Any,
    *,
    fields: frozenset[str],
    required: frozenset[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BananaError("invalid_visual_brief", f"{label} must be an object.")
    unknown = set(value) - fields
    missing = required - set(value)
    if unknown or missing:
        raise BananaError(
            "invalid_visual_brief",
            f"{label} does not match the closed {VISUAL_BRIEF_SCHEMA_VERSION} contract.",
        )
    return cast(dict[str, Any], value)


def _brief_text(value: Any, *, label: str, max_length: int = 4_096) -> str:
    return validate_approval_text(
        value,
        field=label,
        max_length=max_length,
        multiline=True,
        error_code="invalid_visual_brief",
    )


def _brief_text_list(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list):
        raise BananaError("invalid_visual_brief", f"{label} must be an array.")
    if len(value) > MAX_VISUAL_BRIEF_LIST_ITEMS:
        raise BananaError(
            "invalid_visual_brief",
            f"{label} exceeds the {MAX_VISUAL_BRIEF_LIST_ITEMS}-item client limit.",
        )
    return [_brief_text(item, label=f"{label} item") for item in value]


def _reference_brief_view(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "disclosure_alias": reference["disclosure_alias"],
            "role": reference["role"],
            "purpose": reference["purpose"],
            "subject_id": reference["subject_id"],
        }
        for reference in references
    ]


def _minimal_visual_brief(
    *,
    prompt: str,
    references: list[dict[str, Any]],
    aspect_ratio: str,
    image_size: str,
    mime_type: str,
) -> dict[str, Any]:
    return {
        "schema_version": VISUAL_BRIEF_SCHEMA_VERSION,
        "goal": prompt,
        "facts": [],
        "locks": [],
        "freedoms": [],
        "direction": {
            "mode": "prompt_only",
            "thesis": None,
            "signature": None,
            "avoid": None,
        },
        "composition": [],
        "rendering": [],
        "typography": {"exact_copy": [], "instructions": []},
        "references": _reference_brief_view(references),
        "output": {
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
            "mime_type": mime_type,
            "delivery_notes": [],
        },
        "review_tests": [
            "The generated image visibly follows the approved prompt and its aesthetic choices are coherent with that prompt."
        ],
    }


def validate_visual_brief(
    value: dict[str, Any],
    *,
    references: list[dict[str, Any]],
    aspect_ratio: str,
    image_size: str,
    mime_type: str,
    allow_prompt_only: bool = False,
) -> dict[str, Any]:
    """Validate and normalize the closed visual-brief contract."""
    brief = _closed_object(
        value,
        fields=frozenset(
            {
                "schema_version",
                "goal",
                "facts",
                "locks",
                "freedoms",
                "direction",
                "composition",
                "rendering",
                "typography",
                "references",
                "output",
                "review_tests",
            }
        ),
        required=frozenset(
            {
                "schema_version",
                "goal",
                "facts",
                "locks",
                "freedoms",
                "direction",
                "composition",
                "rendering",
                "typography",
                "references",
                "output",
                "review_tests",
            }
        ),
        label="Visual brief",
    )
    if brief["schema_version"] != VISUAL_BRIEF_SCHEMA_VERSION:
        raise BananaError(
            "invalid_visual_brief",
            f"Visual brief schema_version must be {VISUAL_BRIEF_SCHEMA_VERSION}.",
        )
    direction = _closed_object(
        brief["direction"],
        fields=frozenset({"mode", "thesis", "signature", "avoid"}),
        required=frozenset({"mode", "thesis", "signature", "avoid"}),
        label="Visual brief direction",
    )
    direction_mode = direction["mode"]
    allowed_direction_modes = {"creative", "preserve", "not_applicable"}
    if allow_prompt_only:
        allowed_direction_modes.add("prompt_only")
    if direction_mode not in allowed_direction_modes:
        raise BananaError(
            "invalid_visual_brief",
            "Visual brief direction mode is not allowed for this brief source.",
        )
    direction_values: dict[str, str | None] = {}
    for field in ("thesis", "signature", "avoid"):
        raw_direction_value = direction[field]
        if direction_mode == "creative":
            direction_values[field] = _brief_text(
                raw_direction_value,
                label=f"Visual brief direction {field}",
            )
        elif raw_direction_value is not None:
            raise BananaError(
                "invalid_visual_brief",
                "Preserve, not_applicable, and prompt_only direction modes require null thesis, signature, and avoid fields.",
            )
        else:
            direction_values[field] = None
    typography = _closed_object(
        brief["typography"],
        fields=frozenset({"exact_copy", "instructions"}),
        required=frozenset({"exact_copy", "instructions"}),
        label="Visual brief typography",
    )
    output = _closed_object(
        brief["output"],
        fields=frozenset({"aspect_ratio", "image_size", "mime_type", "delivery_notes"}),
        required=frozenset(
            {"aspect_ratio", "image_size", "mime_type", "delivery_notes"}
        ),
        label="Visual brief output",
    )
    raw_references = brief["references"]
    if not isinstance(raw_references, list):
        raise BananaError(
            "invalid_visual_brief", "Visual brief references must be an array."
        )
    if len(raw_references) > 14:
        raise BananaError(
            "invalid_visual_brief",
            "Visual brief references exceed the 14-item contract limit.",
        )
    normalized_references: list[dict[str, Any]] = []
    for index, item in enumerate(raw_references, start=1):
        reference = _closed_object(
            item,
            fields=frozenset(
                {"disclosure_alias", "role", "purpose", "subject_id", "authority"}
            ),
            required=frozenset(
                {"disclosure_alias", "role", "purpose", "subject_id", "authority"}
            ),
            label=f"Visual brief reference {index}",
        )
        role = reference["role"]
        if role not in REFERENCE_ROLE_KEYS:
            raise BananaError(
                "invalid_visual_brief",
                "Visual brief reference role is unsupported.",
            )
        subject_id = reference["subject_id"]
        authority = _closed_object(
            reference["authority"],
            fields=frozenset(
                {
                    *REFERENCE_AUTHORITY_CATEGORY_FIELDS,
                    "provider_transmission",
                    "intended_use",
                }
            ),
            required=frozenset(
                {
                    *REFERENCE_AUTHORITY_CATEGORY_FIELDS,
                    "provider_transmission",
                    "intended_use",
                }
            ),
            label=f"Visual brief reference {index} authority",
        )
        normalized_authority: dict[str, str] = {}
        for field in REFERENCE_AUTHORITY_CATEGORY_FIELDS:
            status = authority[field]
            if status not in REFERENCE_AUTHORITY_CATEGORY_VALUES:
                raise BananaError(
                    "invalid_visual_brief",
                    f"Visual brief reference {index} authority {field} is invalid.",
                )
            normalized_authority[field] = str(status)
        provider_transmission = authority["provider_transmission"]
        if provider_transmission not in {"affirmed", "unresolved"}:
            raise BananaError(
                "invalid_visual_brief",
                f"Visual brief reference {index} provider_transmission is invalid.",
            )
        normalized_authority["provider_transmission"] = str(provider_transmission)
        normalized_authority["intended_use"] = _brief_text(
            authority["intended_use"],
            label=f"Visual brief reference {index} authority intended_use",
        )
        if (
            any(
                normalized_authority[field] == "unresolved"
                for field in REFERENCE_AUTHORITY_CATEGORY_FIELDS
            )
            or provider_transmission != "affirmed"
        ):
            raise BananaError(
                "reference_authority_unresolved",
                "Reference authority or provider-transmission permission is unresolved. Obtain an explicit user decision before approval.",
                details={"provider_called": False, "reference_index": index},
            )
        normalized_references.append(
            {
                "disclosure_alias": _brief_text(
                    reference["disclosure_alias"],
                    label=f"Visual brief reference {index} disclosure_alias",
                    max_length=120,
                ),
                "role": role,
                "purpose": _brief_text(
                    reference["purpose"],
                    label=f"Visual brief reference {index} purpose",
                    max_length=120,
                ),
                "subject_id": (
                    _brief_text(
                        subject_id,
                        label=f"Visual brief reference {index} subject_id",
                        max_length=120,
                    )
                    if subject_id is not None
                    else None
                ),
                "authority": normalized_authority,
            }
        )
    normalized: dict[str, Any] = {
        "schema_version": VISUAL_BRIEF_SCHEMA_VERSION,
        "goal": _brief_text(brief["goal"], label="Visual brief goal"),
        "facts": _brief_text_list(brief["facts"], label="Visual brief facts"),
        "locks": _brief_text_list(brief["locks"], label="Visual brief locks"),
        "freedoms": _brief_text_list(brief["freedoms"], label="Visual brief freedoms"),
        "direction": {
            "mode": direction_mode,
            "thesis": direction_values["thesis"],
            "signature": direction_values["signature"],
            "avoid": direction_values["avoid"],
        },
        "composition": _brief_text_list(
            brief["composition"], label="Visual brief composition"
        ),
        "rendering": _brief_text_list(
            brief["rendering"], label="Visual brief rendering"
        ),
        "typography": {
            "exact_copy": _brief_text_list(
                typography["exact_copy"], label="Visual brief exact_copy"
            ),
            "instructions": _brief_text_list(
                typography["instructions"], label="Visual brief typography instructions"
            ),
        },
        "references": normalized_references,
        "output": {
            "aspect_ratio": _brief_text(
                output["aspect_ratio"], label="Visual brief output aspect_ratio"
            ),
            "image_size": _brief_text(
                output["image_size"], label="Visual brief output image_size"
            ),
            "mime_type": _brief_text(
                output["mime_type"], label="Visual brief output mime_type"
            ),
            "delivery_notes": _brief_text_list(
                output["delivery_notes"], label="Visual brief delivery_notes"
            ),
        },
        "review_tests": _brief_text_list(
            brief["review_tests"], label="Visual brief review_tests"
        ),
    }
    comparable_references = [
        {
            "disclosure_alias": reference["disclosure_alias"],
            "role": reference["role"],
            "purpose": reference["purpose"],
            "subject_id": reference["subject_id"],
        }
        for reference in normalized_references
    ]
    if comparable_references != _reference_brief_view(references) or normalized[
        "output"
    ] != {
        "aspect_ratio": aspect_ratio,
        "image_size": image_size,
        "mime_type": mime_type,
        "delivery_notes": normalized["output"]["delivery_notes"],
    }:
        raise BananaError(
            "visual_brief_mismatch",
            "The supplied visual brief does not match the planned references and resolved output settings.",
        )
    if not normalized["review_tests"]:
        raise BananaError(
            "invalid_visual_brief",
            "Visual brief review_tests must contain at least one visible test.",
        )
    text_total = sum(len(item) for item in _walk_visual_brief_text(normalized))
    if text_total > MAX_VISUAL_BRIEF_TEXT_CHARS:
        raise BananaError(
            "invalid_visual_brief",
            "Visual brief text exceeds the aggregate client limit.",
        )
    return normalized


def _walk_visual_brief_text(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_visual_brief_text(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_visual_brief_text(item)


def _visual_brief_digest(brief: dict[str, Any]) -> str:
    canonical = json.dumps(
        brief,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_plan(
    *,
    operation: str,
    prompt: str,
    model: str | None = None,
    aspect_ratio: str = "1:1",
    image_size: str | None = None,
    reference_paths: Iterable[str | Path | dict[str, Any]] = (),
    video_url: str | None = None,
    previous_interaction_id: str | None = None,
    thinking_level: str | None = None,
    web_search: bool = False,
    image_search: bool = False,
    store: bool = False,
    image_count: int = 1,
    batch: bool = False,
    mime_type: str = "image/jpeg",
    destination: str | Path | None = None,
    label: str = "image",
    record_prompt: bool = False,
    visual_brief: dict[str, Any] | None = None,
    _brief_source: str | None = None,
) -> dict[str, Any]:
    """Validate a request and return a stable, non-secret execution plan."""
    clean_prompt = validate_approval_text(
        prompt,
        field="Prompt",
        max_length=MAX_PROMPT_CHARS,
        multiline=True,
    )
    if operation not in {"generate", "edit", "continue", "portfolio"}:
        raise BananaError("unsupported_operation", "Unsupported operation.")
    if image_count != 1:
        raise BananaError(
            "unsupported_image_count",
            "One provider request produces one planned image. Use a bounded portfolio or a Batch workflow for multiple requests.",
        )

    selected, info = get_model(model)
    size = normalize_image_size(image_size, info)
    ratio = validate_aspect_ratio(aspect_ratio, info)
    references = validate_references(reference_paths, info["reference_limits"])
    checked_video_url = validate_video_url(video_url, info)
    video_url_status_disclosure = (
        {
            "existence": "user_asserted",
            "public_status": "user_asserted",
            "google_accessibility": "user_asserted",
            "preflighted": False,
        }
        if checked_video_url is not None
        else None
    )
    video_url_paid_attempt_warning = (
        VIDEO_URL_PAID_ATTEMPT_WARNING if checked_video_url is not None else None
    )
    checked_mime_type = validate_output_mime_type(mime_type, info)
    checked_destination = str(output_directory(destination))
    checked_label = normalize_label(label)
    api_surface = str(info.get("api_surface", ""))
    catalog = load_catalog()
    if api_surface not in catalog.get("api_profiles", {}):
        raise BananaError(
            "catalog_invalid", f"Model '{selected}' has an invalid API surface."
        )
    api_profile = catalog["api_profiles"][api_surface]
    if api_surface == "interactions":
        api_endpoint = str(api_profile.get("url", ""))
    else:
        api_endpoint = str(api_profile.get("url_template", "")).format(
            model=urllib.parse.quote(selected, safe="")
        )
    api_endpoint = _validated_provider_api_url(
        api_endpoint,
        code="catalog_invalid",
        message=f"Model '{selected}' has an invalid Google API endpoint.",
    )

    provider_response_format = resolve_provider_response_format(
        api_surface=api_surface,
        api_profile=api_profile,
        model_info=info,
        aspect_ratio=ratio,
        image_size=size,
        output_mime_type=checked_mime_type,
    )
    api_profile_reported_live_probe = api_profile.get("reported_live_probe")
    if not isinstance(api_profile_reported_live_probe, dict):
        api_profile_reported_live_probe = None

    thinking_behavior = (
        f"client_override_{thinking_level}"
        if thinking_level
        else str(
            info["features"].get("thinking_default", "provider_default_not_documented")
        )
    )
    thinking_documentation_conflict = bool(
        info["features"].get("thinking_default_documentation_conflict", False)
    )
    thinking_documentation_note = (
        str(info["features"].get("thinking_default_documentation_note"))
        if thinking_documentation_conflict
        else None
    )
    mime_documentation = api_profile.get("output_mime_documentation", {})
    output_mime_documentation_conflict = bool(
        isinstance(mime_documentation, dict) and mime_documentation.get("png_conflict")
    )
    output_mime_documentation_note = (
        str(mime_documentation.get("note"))
        if output_mime_documentation_conflict
        else None
    )

    if operation == "edit" and not references:
        raise BananaError(
            "missing_reference", "Editing requires at least one reference image."
        )
    checked_previous_interaction_id = (
        validate_approval_text(
            previous_interaction_id,
            field="Previous interaction ID",
            max_length=512,
        )
        if previous_interaction_id is not None
        else None
    )
    if operation == "continue" and not checked_previous_interaction_id:
        raise BananaError(
            "missing_interaction_id", "Continuation requires previous_interaction_id."
        )
    if checked_previous_interaction_id and operation != "continue":
        raise BananaError(
            "operation_mismatch",
            "previous_interaction_id is valid only for a continue operation.",
        )
    if checked_previous_interaction_id and not info["features"].get(
        "server_managed_continuation"
    ):
        raise BananaError(
            "continuation_not_supported",
            "The selected model is not routed for stored multi-turn continuation.",
        )
    if thinking_level:
        if thinking_level not in SUPPORTED_THINKING_LEVELS:
            raise BananaError(
                "invalid_thinking_level",
                "Unsupported thinking level.",
            )
        allowed_levels = info["features"].get("thinking_levels", [])
        if thinking_level not in allowed_levels:
            supported = ", ".join(allowed_levels) if allowed_levels else "none"
            raise BananaError(
                "thinking_not_supported",
                f"The selected model does not support the requested thinking level. Supported configurable levels: {supported}.",
            )
    if web_search and not info["features"].get("web_search"):
        raise BananaError(
            "web_search_not_supported",
            "The selected model does not support Google Search grounding.",
        )
    if image_search and not info["features"].get("image_search"):
        raise BananaError(
            "image_search_not_supported",
            "The selected model does not support Image Search grounding.",
        )
    if checked_previous_interaction_id and not store:
        raise BananaError(
            "continuation_requires_storage",
            "Stored continuation requires store=true on the interaction.",
        )
    if store and api_surface != "interactions":
        raise BananaError(
            "storage_not_supported",
            "The selected model is routed through generateContent and does not support stored interaction continuation here.",
        )

    grounding_requested = bool(web_search or image_search)
    policies = catalog.get("provider_policies", {})
    search_retention_days = (
        int(policies.get("search_grounding_retention_days", 30))
        if grounding_requested
        else None
    )
    provider_storage_retention_default_days = (
        int(policies.get("interactions_paid_default_retention_days", 55))
        if store and api_surface == "interactions"
        else None
    )
    provider_storage_retention_options_days = (
        [
            int(value)
            for value in policies.get(
                "interactions_paid_retention_options_days", [7, 14, 28, 55]
            )
        ]
        if store and api_surface == "interactions"
        else []
    )
    provider_storage_setting_inspectable = (
        bool(policies.get("interactions_retention_setting_client_inspectable", False))
        if store and api_surface == "interactions"
        else None
    )
    provider_storage_warning = (
        "Banana cannot inspect the project's configured Interactions retention period; "
        "confirm it outside this client before storing."
        if store and api_surface == "interactions"
        else None
    )

    price_each = estimate_image_cost(selected, size, batch=batch)
    estimated_image_output_usd = round(price_each * image_count, 4)
    estimate_basis = "nominal_one_output"
    estimate_is_invoice_cap = False
    output_count_uncertain = True
    provider_attempt_count = 1
    structured_brief_reasons = [
        reason
        for required, reason in (
            (operation == "portfolio", "portfolio"),
            (operation == "edit", "edit"),
            (bool(references), "uploaded_references"),
            (bool(web_search or image_search), "search_grounding"),
            (checked_video_url is not None, "video_input"),
            (checked_previous_interaction_id is not None, "stored_continuation"),
        )
        if required
    ]
    structured_brief_required = bool(structured_brief_reasons)
    if visual_brief is None and structured_brief_required:
        raise BananaError(
            "structured_brief_required",
            "This request requires a supplied banana.visual-brief.v1 object before approval.",
            details={
                "provider_called": False,
                "structured_brief_required": True,
                "structured_brief_reasons": structured_brief_reasons,
            },
        )
    brief_source = _brief_source or (
        "supplied" if visual_brief is not None else "planner_minimal"
    )
    if brief_source not in {"supplied", "planner_minimal"}:
        raise BananaError("invalid_visual_brief", "Visual brief source is invalid.")
    resolved_brief = validate_visual_brief(
        (
            visual_brief
            if visual_brief is not None
            else _minimal_visual_brief(
                prompt=clean_prompt,
                references=references,
                aspect_ratio=ratio,
                image_size=size,
                mime_type=checked_mime_type,
            )
        ),
        references=references,
        aspect_ratio=ratio,
        image_size=size,
        mime_type=checked_mime_type,
        allow_prompt_only=brief_source == "planner_minimal",
    )
    for reference, brief_reference in zip(
        references, resolved_brief["references"], strict=True
    ):
        reference["authority"] = brief_reference["authority"]
    brief_sha256 = _visual_brief_digest(resolved_brief)
    canonical = {
        "operation": operation,
        "prompt_sha256": hashlib.sha256(clean_prompt.encode("utf-8")).hexdigest(),
        "model": selected,
        "api_surface": api_surface,
        "api_endpoint": api_endpoint,
        "catalog_verified_on": catalog.get("verified_on"),
        "api_profile_reported_live_probe": api_profile_reported_live_probe,
        "aspect_ratio": ratio,
        "image_size": size,
        "references": [
            {
                "sha256": ref["sha256"],
                "bytes": ref["bytes"],
                "disclosure_alias": ref["disclosure_alias"],
                "authority": ref["authority"],
                "role": ref["role"],
                "purpose": ref["purpose"],
                "subject_id": ref["subject_id"],
            }
            for ref in references
        ],
        "video_url": checked_video_url,
        "video_url_syntax_validated": checked_video_url is not None,
        "video_url_status_disclosure": video_url_status_disclosure,
        "video_url_paid_attempt_warning": video_url_paid_attempt_warning,
        "previous_interaction_id": checked_previous_interaction_id,
        "thinking_level": thinking_level,
        "thinking_behavior": thinking_behavior,
        "thinking_documentation_conflict": thinking_documentation_conflict,
        "thinking_documentation_note": thinking_documentation_note,
        "web_search": bool(web_search),
        "image_search": bool(image_search),
        "search_provider_retention_days": search_retention_days,
        "provider_storage_retention_default_days": provider_storage_retention_default_days,
        "provider_storage_retention_options_days": provider_storage_retention_options_days,
        "provider_storage_setting_inspectable": provider_storage_setting_inspectable,
        "provider_storage_warning": provider_storage_warning,
        "store": bool(store),
        "image_count": image_count,
        "batch": bool(batch),
        "output_mime_type": checked_mime_type,
        "provider_response_format": provider_response_format,
        "output_mime_documentation_conflict": output_mime_documentation_conflict,
        "output_mime_documentation_note": output_mime_documentation_note,
        "output_directory": checked_destination,
        "label": checked_label,
        "record_prompt": bool(record_prompt),
        "image_output_rate_usd": price_each,
        "estimated_image_output_usd": estimated_image_output_usd,
        "estimate_basis": estimate_basis,
        "estimate_is_invoice_cap": estimate_is_invoice_cap,
        "output_count_uncertain": output_count_uncertain,
        "provider_attempt_count": provider_attempt_count,
        "brief_sha256": brief_sha256,
        "brief_source": brief_source,
        "structured_brief_required": structured_brief_required,
        "structured_brief_reasons": structured_brief_reasons,
    }
    canonical_bytes = json.dumps(
        canonical, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    request_fingerprint = hashlib.sha256(canonical_bytes).hexdigest()[:24]
    return {
        "request_fingerprint": request_fingerprint,
        "operation": operation,
        "model": selected,
        "model_name": info["display_name"],
        "model_status": info["status"],
        "api_surface": api_surface,
        "api_endpoint": api_endpoint,
        "catalog_verified_on": catalog.get("verified_on"),
        "api_profile_reported_live_probe": api_profile_reported_live_probe,
        "aspect_ratio": ratio,
        "image_size": size,
        "image_count": image_count,
        "reference_count": len(references),
        "video_input": bool(checked_video_url),
        "video_url_syntax_validated": checked_video_url is not None,
        "video_url_status_disclosure": video_url_status_disclosure,
        "video_url_paid_attempt_warning": video_url_paid_attempt_warning,
        "previous_interaction_id": checked_previous_interaction_id,
        "thinking_level": thinking_level,
        "thinking_behavior": thinking_behavior,
        "thinking_documentation_conflict": thinking_documentation_conflict,
        "thinking_documentation_note": thinking_documentation_note,
        "web_search": bool(web_search),
        "image_search": bool(image_search),
        "search_provider_retention_days": search_retention_days,
        "search_provider_retention_mandatory": grounding_requested,
        "provider_storage_retention_default_days": provider_storage_retention_default_days,
        "provider_storage_retention_options_days": provider_storage_retention_options_days,
        "provider_storage_setting_inspectable": provider_storage_setting_inspectable,
        "provider_storage_warning": provider_storage_warning,
        "store": bool(store),
        "batch": bool(batch),
        "output_mime_type": checked_mime_type,
        "provider_response_format": provider_response_format,
        "output_mime_documentation_conflict": output_mime_documentation_conflict,
        "output_mime_documentation_note": output_mime_documentation_note,
        "output_directory": checked_destination,
        "label": checked_label,
        "record_prompt": bool(record_prompt),
        "image_output_rate_usd": price_each,
        "estimated_image_output_usd": estimated_image_output_usd,
        "estimate_basis": estimate_basis,
        "estimate_is_invoice_cap": estimate_is_invoice_cap,
        "output_count_uncertain": output_count_uncertain,
        "provider_attempt_count": provider_attempt_count,
        "brief_sha256": brief_sha256,
        "brief_source": brief_source,
        "visual_brief": resolved_brief,
        "structured_brief_required": structured_brief_required,
        "structured_brief_reasons": structured_brief_reasons,
        "estimate_excludes": [
            "input tokens",
            "text and thinking output",
            "Google Search queries",
        ],
        "prompt": clean_prompt,
        "prompt_sha256": canonical["prompt_sha256"],
        "references": references,
        "video_url": checked_video_url,
    }


def public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Return an approval-safe plan without local reference paths."""
    public = {
        key: value
        for key, value in plan.items()
        if key not in {"references", "visual_brief"}
    }
    public["reference_inputs"] = [
        {
            "disclosure_alias": reference["disclosure_alias"],
            "authority": reference["authority"],
            "mime_type": reference["mime_type"],
            "bytes": reference["bytes"],
            "sha256": reference["sha256"],
            "role": reference["role"],
            "purpose": reference["purpose"],
            "subject_id": reference["subject_id"],
        }
        for reference in plan["references"]
    ]
    public["approval_summary"] = _approval_summary(plan)
    return public


def _approval_summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt": plan["prompt"],
        "brief_sha256": plan["brief_sha256"],
        "brief_source": plan["brief_source"],
        "visual_brief": plan["visual_brief"],
        "model": plan["model"],
        "image_size": plan["image_size"],
        "aspect_ratio": plan["aspect_ratio"],
        "output_mime_type": plan["output_mime_type"],
        "provider_attempt_count": plan["provider_attempt_count"],
        "estimated_image_output_usd": plan["estimated_image_output_usd"],
        "estimate_basis": plan["estimate_basis"],
        "estimate_is_invoice_cap": plan["estimate_is_invoice_cap"],
        "output_count_uncertain": plan["output_count_uncertain"],
        "store": plan["store"],
        "grounding": {
            "web_search": plan["web_search"],
            "image_search": plan["image_search"],
        },
        "search_provider_retention_days": plan["search_provider_retention_days"],
        "search_provider_retention_mandatory": plan[
            "search_provider_retention_mandatory"
        ],
        "provider_storage_retention_default_days": plan[
            "provider_storage_retention_default_days"
        ],
        "provider_storage_retention_options_days": plan[
            "provider_storage_retention_options_days"
        ],
        "provider_storage_setting_inspectable": plan[
            "provider_storage_setting_inspectable"
        ],
        "provider_storage_warning": plan["provider_storage_warning"],
        "output_directory": plan["output_directory"],
        "references": [
            {
                "disclosure_alias": reference["disclosure_alias"],
                "authority": reference["authority"],
                "role": reference["role"],
                "purpose": reference["purpose"],
                "subject_id": reference["subject_id"],
            }
            for reference in plan["references"]
        ],
        "structured_brief_required": plan["structured_brief_required"],
        "structured_brief_reasons": plan["structured_brief_reasons"],
    }


def issue_public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Issue one short-lived approval capability and return the public plan."""
    from approval_store import issue_approval

    preflight_output_publication(plan["output_directory"])
    public = public_plan(plan)
    public.update(issue_approval(plan["request_fingerprint"], kind="single"))
    public["network_called"] = False
    return public


def _encode_reference(reference: dict[str, Any]) -> dict[str, Any]:
    path = Path(reference["path"])
    raw = _read_regular_file_bounded(
        path,
        max_bytes=int(reference["bytes"]),
        unreadable_code="reference_unreadable",
        oversized_code="reference_changed",
        label="Reference image",
    )
    if (
        len(raw) != reference["bytes"]
        or hashlib.sha256(raw).hexdigest() != reference["sha256"]
        or not _matches_image_signature(raw[:12], reference["mime_type"])
    ):
        raise BananaError(
            "reference_changed",
            "A reference image changed after the plan was created. Create and approve a new plan.",
        )
    data = base64.b64encode(raw).decode("ascii")
    return {"type": "image", "mime_type": reference["mime_type"], "data": data}


def _reference_label(index: int, reference: dict[str, Any]) -> str:
    parts = [
        f"Banana reference annotation {index}",
        f"role: {reference['role']}",
    ]
    if reference.get("purpose"):
        parts.append(f"purpose: {reference['purpose']}")
    if reference.get("subject_id"):
        parts.append(f"subject_id: {reference['subject_id']}")
    return "; ".join(parts) + "."


def build_interaction_payload(prompt: str, plan: dict[str, Any]) -> dict[str, Any]:
    inputs: list[dict[str, Any]] = [{"type": "text", "text": prompt.strip()}]
    for index, reference in enumerate(plan["references"], start=1):
        inputs.append({"type": "text", "text": _reference_label(index, reference)})
        inputs.append(_encode_reference(reference))
    if plan.get("video_url"):
        inputs.insert(
            0,
            {
                "type": "video",
                "uri": plan["video_url"],
                "mime_type": "video/mp4",
            },
        )

    payload: dict[str, Any] = {
        "model": plan["model"],
        "input": inputs,
        "response_format": plan["provider_response_format"],
        "store": bool(plan["store"]),
    }
    if plan.get("previous_interaction_id"):
        payload["previous_interaction_id"] = plan["previous_interaction_id"]
    if plan.get("thinking_level"):
        payload["generation_config"] = {"thinking_level": plan["thinking_level"]}
    search_types: list[str] = []
    if plan.get("web_search"):
        search_types.append("web_search")
    if plan.get("image_search"):
        search_types.append("image_search")
    if search_types:
        payload["tools"] = [{"type": "google_search", "search_types": search_types}]
    return payload


def build_generate_content_payload(prompt: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Build a REST generateContent payload for models absent from Interactions."""
    parts: list[dict[str, Any]] = []
    if plan.get("video_url"):
        parts.append(
            {
                "fileData": {"fileUri": plan["video_url"]},
                "videoMetadata": {"fps": 0.5},
            }
        )
    parts.append({"text": prompt.strip()})
    for index, reference in enumerate(plan["references"], start=1):
        encoded = _encode_reference(reference)
        parts.append({"text": _reference_label(index, reference)})
        parts.append(
            {
                "inlineData": {
                    "mimeType": encoded["mime_type"],
                    "data": encoded["data"],
                }
            }
        )

    generation_config: dict[str, Any] = {
        "responseModalities": ["TEXT", "IMAGE"],
        "responseFormat": plan["provider_response_format"],
    }
    if plan.get("thinking_level"):
        generation_config["thinkingConfig"] = {
            "thinkingLevel": plan["thinking_level"].upper()
        }
    return {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": generation_config,
    }


def _safe_provider_enum(value: Any, allowed: frozenset[str]) -> str | None:
    """Return only a locally documented provider enum, never provider prose."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    if not normalized:
        return None
    return normalized if normalized in allowed else "UNKNOWN"


def _safe_provider_identifier(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,512}", candidate):
        return None
    return candidate


def _provider_identifier_digest(value: Any) -> str | None:
    """Create a stable sidecar reference without persisting a provider identifier."""
    candidate = _safe_provider_identifier(value)
    if candidate is None:
        return None
    return hashlib.sha256(candidate.encode("utf-8")).hexdigest()


def _safe_usage(value: Any) -> dict[str, int]:
    """Keep only documented scalar token counts from provider metadata."""
    if not isinstance(value, dict):
        return {}
    usage: dict[str, int] = {}
    for key in USAGE_TOKEN_KEYS:
        count = value.get(key)
        if type(count) is int and 0 <= count <= MAX_PROVIDER_TOKEN_COUNT:
            usage[key] = count
    return usage


def _validated_provider_image_mime(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise BananaError(
            "missing_output_mime",
            "Provider image output omitted its MIME type.",
        )
    if value not in EXTENSION_BY_MIME:
        raise BananaError(
            "unsupported_output_type",
            "Provider returned an unsupported image MIME type.",
        )
    return value


def _provider_error_status_from_body(body: bytes) -> str | None:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    error = parsed.get("error", parsed) if isinstance(parsed, dict) else None
    if not isinstance(error, dict):
        return None
    status = error.get("status")
    if not isinstance(status, str):
        return None
    normalized = status.strip().upper()
    return normalized if normalized in PROVIDER_ERROR_STATUSES else None


def _error_message_from_body(body: bytes) -> str:
    provider_status = _provider_error_status_from_body(body)
    if provider_status:
        return f"The provider returned error status {provider_status}."
    return "The provider returned an error response."


def _read_bounded(stream: Any, *, limit: int, label: str) -> bytes:
    """Read at most one bounded provider payload into memory."""
    body = stream.read(limit + 1)
    if len(body) > limit:
        raise BananaError(
            "provider_response_too_large",
            f"The provider {label} exceeded Banana's {limit}-byte safety limit.",
        )
    return cast(bytes, body)


def _validated_provider_api_url(
    url: str,
    *,
    code: str,
    message: str,
) -> str:
    """Accept only the closed Gemini HTTPS origin with no URL indirection."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except (TypeError, ValueError) as exc:
        raise BananaError(code, message) from exc
    if (
        parsed.scheme != "https"
        or parsed.netloc != PROVIDER_API_HOST
        or parsed.hostname != PROVIDER_API_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or not parsed.path.startswith("/")
        or parsed.query
        or parsed.fragment
    ):
        raise BananaError(code, message)
    return url


class _RejectProviderRedirects(urllib.request.HTTPRedirectHandler):
    """Never forward an authenticated provider request through a redirect."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


_PROVIDER_OPENER = urllib.request.build_opener(_RejectProviderRedirects())


def _open_provider_request(
    request: urllib.request.Request,
    *,
    timeout: int,
) -> Any:
    return _PROVIDER_OPENER.open(request, timeout=timeout)


def _call_json_api(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str | None = None,
    timeout: int = 180,
    max_attempts: int = 1,
    opener: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Make a JSON API request, with retries only when explicitly requested."""
    if max_attempts < 1:
        raise BananaError("invalid_retry_budget", "max_attempts must be at least 1.")
    if timeout < 1:
        raise BananaError("invalid_timeout", "timeout must be at least 1 second.")
    checked_url = _validated_provider_api_url(
        url,
        code="api_surface_mismatch",
        message="The provider endpoint is not the approved Google API origin.",
    )
    key = api_key or api_key_from_env()
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request_opener = opener or _open_provider_request

    for attempt in range(1, max_attempts + 1):
        # checked_url has an exact HTTPS origin, no user info, port, query, or
        # fragment. The default opener also rejects every redirect.
        request = urllib.request.Request(
            checked_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": key,
                "User-Agent": "banana-claude/3.0.0",
            },
            method="POST",
        )
        try:
            with request_opener(request, timeout=timeout) as response:
                raw = _read_bounded(
                    response,
                    limit=MAX_PROVIDER_RESPONSE_BYTES,
                    label="response",
                )
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise BananaError(
                    "malformed_response", "Provider response was not a JSON object."
                )
            return parsed
        except urllib.error.HTTPError as exc:
            try:
                body = (
                    _read_bounded(
                        exc,
                        limit=MAX_PROVIDER_ERROR_BYTES,
                        label="error response",
                    )
                    if exc.fp
                    else b""
                )
            finally:
                exc.close()
            provider_message = _error_message_from_body(body)
            provider_status = _provider_error_status_from_body(body)
            if exc.code in TRANSIENT_HTTP_CODES and attempt < max_attempts:
                sleeper(float(2 ** (attempt - 1)))
                continue
            if exc.code == 429:
                raise BananaError(
                    "rate_limited", provider_message, retryable=True, http_status=429
                ) from exc
            if exc.code in TRANSIENT_HTTP_CODES:
                raise BananaError(
                    "provider_unavailable",
                    provider_message,
                    retryable=True,
                    http_status=exc.code,
                ) from exc
            if exc.code in {401, 403}:
                raise BananaError(
                    "authentication_failed", provider_message, http_status=exc.code
                ) from exc
            if exc.code == 400 and provider_status == "FAILED_PRECONDITION":
                raise BananaError(
                    "billing_required", provider_message, http_status=400
                ) from exc
            raise BananaError(
                "provider_http_error", provider_message, http_status=exc.code
            ) from exc
        except urllib.error.URLError as exc:
            if attempt < max_attempts:
                sleeper(float(2 ** (attempt - 1)))
                continue
            raise BananaError(
                "network_error",
                "Gemini request failed before a response was received.",
                retryable=True,
            ) from exc
        except TimeoutError as exc:
            if attempt < max_attempts:
                sleeper(float(2 ** (attempt - 1)))
                continue
            raise BananaError(
                "timeout", "Gemini request timed out.", retryable=True
            ) from exc
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise BananaError(
                "malformed_response", "Provider response was not valid UTF-8 JSON."
            ) from exc

    raise BananaError(
        "retry_exhausted", "Gemini request exhausted its retry budget.", retryable=True
    )


def call_interactions(
    payload: dict[str, Any],
    *,
    endpoint: str | None = None,
    api_key: str | None = None,
    timeout: int = 180,
    max_attempts: int = 1,
    opener: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Call the Interactions API once unless a caller explicitly opts into retries."""
    url = endpoint or str(load_catalog()["api_profiles"]["interactions"]["url"])
    url = _validated_provider_api_url(
        url,
        code="api_surface_mismatch",
        message="Interactions endpoint is not an approved Google API URL.",
    )
    return _call_json_api(
        url,
        payload,
        api_key=api_key,
        timeout=timeout,
        max_attempts=max_attempts,
        opener=opener,
        sleeper=sleeper,
    )


def call_generate_content(
    payload: dict[str, Any],
    *,
    model: str,
    endpoint: str | None = None,
    api_key: str | None = None,
    timeout: int = 180,
    max_attempts: int = 1,
    opener: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Call the model-scoped generateContent endpoint."""
    selected, info = get_model(model)
    if info.get("api_surface") != "generate_content":
        raise BananaError(
            "api_surface_mismatch",
            f"Model '{selected}' is not routed through generateContent.",
        )
    template = str(load_catalog()["api_profiles"]["generate_content"]["url_template"])
    url = endpoint or template.format(model=urllib.parse.quote(selected, safe=""))
    url = _validated_provider_api_url(
        url,
        code="api_surface_mismatch",
        message="generateContent endpoint is not an approved Google API URL.",
    )
    return _call_json_api(
        url,
        payload,
        api_key=api_key,
        timeout=timeout,
        max_attempts=max_attempts,
        opener=opener,
        sleeper=sleeper,
    )


def extract_interaction(response: dict[str, Any]) -> dict[str, Any]:
    """Extract every image, text block, citation, and search suggestion."""
    status = response.get("status")
    if status != "completed":
        error = response.get("error")
        if isinstance(error, dict):
            reason = _safe_provider_enum(error.get("status"), PROVIDER_ERROR_STATUSES)
        else:
            reason = None
        reason = reason or _safe_provider_enum(status, INTERACTION_FAILURE_STATUSES)
        reason = reason or "UNKNOWN"
        raise BananaError(
            "interaction_not_completed", f"Interaction did not complete: {reason}"
        )

    images: list[dict[str, str]] = []
    texts: list[str] = []
    citations: list[dict[str, Any]] = []
    search_suggestions: list[str] = []

    for step in response.get("steps", []):
        if not isinstance(step, dict):
            continue
        if step.get("type") == "google_search_result":
            suggestion = step.get("search_suggestions")
            if isinstance(suggestion, str) and suggestion:
                search_suggestions.append(suggestion)
            results = step.get("result", [])
            if isinstance(results, dict):
                results = [results]
            if isinstance(results, list):
                for result in results:
                    if not isinstance(result, dict):
                        continue
                    nested_suggestion = result.get("search_suggestions")
                    if isinstance(nested_suggestion, str) and nested_suggestion:
                        search_suggestions.append(nested_suggestion)
        if step.get("type") != "model_output":
            continue
        for block in step.get("content", []):
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "image" and block.get("data"):
                mime_type = _validated_provider_image_mime(block.get("mime_type"))
                images.append({"data": str(block["data"]), "mime_type": mime_type})
            elif block_type == "text" and block.get("text"):
                texts.append(str(block["text"]))
                if isinstance(block.get("annotations"), list):
                    citations.extend(
                        item for item in block["annotations"] if isinstance(item, dict)
                    )

    convenience = response.get("output_image")
    if not images and isinstance(convenience, dict) and convenience.get("data"):
        mime_type = _validated_provider_image_mime(convenience.get("mime_type"))
        images.append({"data": str(convenience["data"]), "mime_type": mime_type})
    if not images:
        raise BananaError(
            "no_image", "The completed interaction did not contain an image output."
        )

    return {
        "interaction_id": _safe_provider_identifier(response.get("id")),
        "model": _safe_provider_identifier(response.get("model")),
        "status": status,
        "images": images,
        "text": "\n".join(texts).strip(),
        "citations": citations,
        "search_suggestions": list(dict.fromkeys(search_suggestions)),
        "usage": _safe_usage(response.get("usage")),
    }


def _safe_safety_ratings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    ratings: list[dict[str, Any]] = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        rating: dict[str, Any] = {}
        field_allowlists = {
            "category": SAFETY_CATEGORIES,
            "probability": SAFETY_PROBABILITIES,
            "severity": SAFETY_SEVERITIES,
        }
        for field, allowed in field_allowlists.items():
            normalized = _safe_provider_enum(item.get(field), allowed)
            if normalized:
                rating[field] = normalized
        if isinstance(item.get("blocked"), bool):
            rating["blocked"] = item["blocked"]
        if rating:
            ratings.append(rating)
    return ratings


def extract_generate_content(response: dict[str, Any], *, model: str) -> dict[str, Any]:
    """Normalize a generateContent response into the shared image result shape."""
    images: list[dict[str, str]] = []
    texts: list[str] = []
    finish_reasons: list[str] = []
    candidate_safety_ratings: list[dict[str, Any]] = []
    candidates = response.get("candidates", [])
    if not isinstance(candidates, list):
        raise BananaError(
            "malformed_response", "generateContent candidates must be an array."
        )
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        finish_reason = candidate.get("finishReason") or candidate.get("finish_reason")
        normalized_finish_reason = _safe_provider_enum(finish_reason, FINISH_REASONS)
        if normalized_finish_reason:
            finish_reasons.append(normalized_finish_reason)
        candidate_safety_ratings.extend(
            _safe_safety_ratings(
                candidate.get("safetyRatings") or candidate.get("safety_ratings")
            )
        )
        content = candidate.get("content", {})
        if not isinstance(content, dict):
            continue
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict) or part.get("thought") is True:
                continue
            text = part.get("text")
            if isinstance(text, str) and text:
                texts.append(text)
            inline = part.get("inlineData") or part.get("inline_data")
            if not isinstance(inline, dict) or not inline.get("data"):
                continue
            mime_type = inline.get("mimeType") or inline.get("mime_type")
            if not isinstance(mime_type, str) or not mime_type:
                raise BananaError(
                    "missing_output_mime",
                    "Provider image output omitted its MIME type.",
                )
            if mime_type.startswith("image/"):
                checked_mime = _validated_provider_image_mime(mime_type)
                images.append({"data": str(inline["data"]), "mime_type": checked_mime})
    if not images:
        prompt_feedback = (
            response.get("promptFeedback") or response.get("prompt_feedback") or {}
        )
        if not isinstance(prompt_feedback, dict):
            prompt_feedback = {}
        block_reason = _safe_provider_enum(
            prompt_feedback.get("blockReason") or prompt_feedback.get("block_reason"),
            PROMPT_BLOCK_REASONS,
        )
        prompt_safety_ratings = _safe_safety_ratings(
            prompt_feedback.get("safetyRatings")
            or prompt_feedback.get("safety_ratings")
        )
        if block_reason:
            details: dict[str, Any] = {"block_reason": block_reason}
            if prompt_safety_ratings:
                details["safety_ratings"] = prompt_safety_ratings
            raise BananaError(
                "prompt_blocked",
                f"generateContent blocked the prompt: {block_reason}.",
                details=details,
            )

        unique_finish_reasons = list(dict.fromkeys(finish_reasons))
        details = (
            {"finish_reasons": unique_finish_reasons} if unique_finish_reasons else {}
        )
        if candidate_safety_ratings:
            details["safety_ratings"] = candidate_safety_ratings
        blocked_reasons = {
            "SAFETY",
            "BLOCKLIST",
            "PROHIBITED_CONTENT",
            "RECITATION",
            "SPII",
            "ESCALATION",
            "IMAGE_SAFETY",
            "IMAGE_PROHIBITED_CONTENT",
            "IMAGE_RECITATION",
        }
        code = (
            "generation_blocked"
            if blocked_reasons.intersection(unique_finish_reasons)
            else "no_image"
        )
        reason = ", ".join(unique_finish_reasons) or "NO_IMAGE_PART"
        raise BananaError(
            code, f"generateContent did not return an image: {reason}.", details=details
        )
    return {
        "interaction_id": _safe_provider_identifier(
            response.get("responseId") or response.get("response_id")
        ),
        "model": _safe_provider_identifier(
            response.get("modelVersion") or response.get("model_version")
        )
        or model,
        "status": "completed",
        "images": images,
        "text": "\n".join(texts).strip(),
        "citations": [],
        "search_suggestions": [],
        "usage": _safe_usage(
            response.get("usageMetadata") or response.get("usage_metadata")
        ),
    }


def decode_image(image: dict[str, str]) -> tuple[bytes, str]:
    mime_type = image.get("mime_type")
    if not mime_type:
        raise BananaError(
            "missing_output_mime", "Provider image output omitted its MIME type."
        )
    if mime_type not in EXTENSION_BY_MIME:
        raise BananaError(
            "unsupported_output_type",
            "Provider returned an unsupported image MIME type.",
        )
    try:
        raw = base64.b64decode(image["data"], validate=True)
    except (binascii.Error, ValueError, KeyError) as exc:
        raise BananaError(
            "invalid_image_data", "Provider returned corrupt base64 image data."
        ) from exc
    if not _matches_image_signature(raw[:12], mime_type):
        raise BananaError(
            "invalid_image_signature",
            "Provider image bytes do not match the declared MIME type.",
        )
    return raw, mime_type


def image_dimensions(raw: bytes, mime_type: str) -> tuple[int | None, int | None]:
    if mime_type == "image/png" and len(raw) >= 24:
        return struct.unpack(">II", raw[16:24])
    if mime_type == "image/jpeg":
        index = 2
        while index + 9 < len(raw):
            if raw[index] != 0xFF:
                index += 1
                continue
            marker = raw[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(raw):
                break
            segment_length = int.from_bytes(raw[index : index + 2], "big")
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                if index + 7 <= len(raw):
                    height = int.from_bytes(raw[index + 3 : index + 5], "big")
                    width = int.from_bytes(raw[index + 5 : index + 7], "big")
                    return width, height
                break
            if segment_length < 2:
                break
            index += segment_length
    if (
        mime_type == "image/webp"
        and len(raw) >= 25
        and raw[:4] == b"RIFF"
        and raw[8:12] == b"WEBP"
    ):
        chunk_type = raw[12:16]
        if chunk_type == b"VP8X" and len(raw) >= 30:
            width = int.from_bytes(raw[24:27], "little") + 1
            height = int.from_bytes(raw[27:30], "little") + 1
            return width, height
        if chunk_type == b"VP8L" and raw[20] == 0x2F:
            packed = int.from_bytes(raw[21:25], "little")
            width = (packed & 0x3FFF) + 1
            height = ((packed >> 14) & 0x3FFF) + 1
            return width, height
        if chunk_type == b"VP8 " and len(raw) >= 30 and raw[23:26] == b"\x9d\x01\x2a":
            width = int.from_bytes(raw[26:28], "little") & 0x3FFF
            height = int.from_bytes(raw[28:30], "little") & 0x3FFF
            if width and height:
                return width, height
    return None, None


def _legacy_secure_directory(path: Path) -> None:
    """Windows fallback for platforms without directory-descriptor traversal."""
    if path.exists():
        if not path.is_dir():
            raise BananaError(
                "invalid_output_directory", f"Output parent is not a directory: {path}"
            )
        return
    try:
        path.mkdir(parents=True, mode=0o700)
    except OSError as exc:
        raise BananaError(
            "invalid_output_directory", f"Cannot create output directory: {path}"
        ) from exc


def _open_secure_directory(path: Path) -> int | None:
    """Open or create an absolute directory without following path components."""
    absolute = Path(os.path.abspath(path))
    if os.name == "nt" or not hasattr(os, "O_DIRECTORY"):
        _legacy_secure_directory(absolute)
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
                raise OSError("unsafe directory component")
            created = False
            try:
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                    created = True
                except FileExistsError:
                    pass
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
            metadata = os.fstat(next_descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(next_descriptor)
                raise OSError("path component is not a directory")
            if created:
                os.fchmod(next_descriptor, 0o700)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise BananaError(
            "invalid_output_directory",
            f"Output directory changed, contains a symbolic link, or cannot be opened safely: {absolute}",
        ) from exc


def _directory_path_matches_fd(path: Path, descriptor: int) -> bool:
    """Check that the approved path still names the held directory inode."""
    try:
        path_metadata = os.stat(path, follow_symlinks=False)
        descriptor_metadata = os.fstat(descriptor)
    except OSError:
        return False
    return (
        stat.S_ISDIR(path_metadata.st_mode)
        and path_metadata.st_dev == descriptor_metadata.st_dev
        and path_metadata.st_ino == descriptor_metadata.st_ino
    )


def _exclusive_rename_at(
    source_directory: int,
    source_name: str,
    destination_directory: int,
    destination_name: str,
) -> None:
    """Rename one dirfd-relative entry only if the destination is absent."""
    library = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(source_name)
    destination = os.fsencode(destination_name)
    operation: Any
    flags: int
    if sys.platform.startswith("linux"):
        try:
            operation = library.renameat2
        except AttributeError as exc:
            raise BananaError(
                "output_exclusive_rename_unavailable",
                "This platform cannot publish a new output with an atomic exclusive rename.",
            ) from exc
        flags = 1  # RENAME_NOREPLACE
    elif sys.platform == "darwin":
        try:
            operation = library.renameatx_np
        except AttributeError as exc:
            raise BananaError(
                "output_exclusive_rename_unavailable",
                "This platform cannot publish a new output with an atomic exclusive rename.",
            ) from exc
        flags = 4  # RENAME_EXCL
    else:
        raise BananaError(
            "output_exclusive_rename_unavailable",
            "This platform cannot publish a new output with an atomic exclusive rename.",
        )

    operation.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    operation.restype = ctypes.c_int
    if (
        operation(
            source_directory,
            source,
            destination_directory,
            destination,
            flags,
        )
        == 0
    ):
        return

    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(error_number, os.strerror(error_number), destination_name)
    unsupported_errors = {errno.ENOSYS, errno.EINVAL}
    for attribute in ("ENOTSUP", "EOPNOTSUPP"):
        value = getattr(errno, attribute, None)
        if isinstance(value, int):
            unsupported_errors.add(value)
    if error_number in unsupported_errors:
        raise BananaError(
            "output_exclusive_rename_unavailable",
            "The output filesystem does not support atomic exclusive rename publication.",
        )
    raise OSError(error_number, os.strerror(error_number), destination_name)


def _approved_output_path(destination: str | Path) -> Path:
    """Return the approved pathname without following it again."""
    return Path(os.path.abspath(Path(destination).expanduser()))


def _validate_output_publication_capability(
    capability: OutputPublicationCapability,
    destination: str | Path,
) -> Path:
    """Validate that an approved pathname still names a held directory."""
    directory = _approved_output_path(destination)
    if capability.directory != directory:
        raise BananaError(
            "output_capability_mismatch",
            "The held publication capability does not match the approved output directory.",
        )
    descriptor = capability.descriptor
    try:
        metadata = os.fstat(descriptor)
    except OSError as exc:
        raise BananaError(
            "output_capability_closed",
            "The held output publication capability is unavailable.",
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise BananaError(
            "output_capability_invalid",
            "The held output publication capability is not a directory.",
        )
    if not _directory_path_matches_fd(directory, descriptor):
        raise BananaError(
            "output_directory_changed",
            "The approved output directory changed after validation. No output artifact was written.",
        )
    return directory


def _create_publication_receipt(
    directory: Path,
    directory_descriptor: int,
    receipt_name: str,
    receipt_bytes: bytes,
) -> tuple[int, str, tuple[int, int], int]:
    source_name = f".{receipt_name}.{os.urandom(16).hex()}.tmp"
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(source_name, flags, 0o600, dir_fd=directory_descriptor)
    identity: tuple[int, int] | None = None
    link_count: int | None = None
    try:
        written = 0
        while written < len(receipt_bytes):
            count = os.write(descriptor, receipt_bytes[written:])
            if count <= 0:
                raise BananaError(
                    "output_preflight_failed",
                    "The publication capability receipt could not be written completely.",
                )
            written += count
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        identity = (metadata.st_dev, metadata.st_ino)
        link_count = metadata.st_nlink
        public = os.stat(
            source_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or (public.st_dev, public.st_ino) != identity
        ):
            raise BananaError(
                "output_preflight_failed",
                "The publication capability source was not one bound private regular file.",
            )
        try:
            _exclusive_rename_at(
                directory_descriptor,
                source_name,
                directory_descriptor,
                receipt_name,
            )
        except FileExistsError as exc:
            raise BananaError(
                "output_preflight_conflict",
                "Another publication capability receipt appeared during initialization.",
            ) from exc
        return descriptor, source_name, identity, metadata.st_nlink
    except BaseException as exc:
        try:
            metadata = os.fstat(descriptor)
            identity = (metadata.st_dev, metadata.st_ino)
            link_count = metadata.st_nlink
        except OSError:
            pass
        os.close(descriptor)
        if isinstance(exc, BananaError):
            code = exc.code
            message = exc.message
            details = dict(exc.details)
        else:
            code = "output_preflight_failed"
            message = "The publication capability receipt could not be created safely."
            details = {}
        if identity is not None:
            details["preflight_source"] = _unlocated_recovery_artifact(
                identity,
                last_known_path=directory / source_name,
                link_count=link_count,
            )
            details["recovery_required"] = True
        raise BananaError(code, message, details=details) from exc


def _stale_receipt_directory_identity(raw: bytes) -> tuple[int, int] | None:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None
    if (
        not isinstance(parsed, dict)
        or set(parsed)
        != {"directory_device", "directory_inode", "purpose", "schema_version"}
        or parsed.get("purpose") != "atomic-no-replace-publication"
        or parsed.get("schema_version") != 1
        or not isinstance(parsed.get("directory_device"), int)
        or isinstance(parsed.get("directory_device"), bool)
        or not isinstance(parsed.get("directory_inode"), int)
        or isinstance(parsed.get("directory_inode"), bool)
        or parsed["directory_device"] < 0
        or parsed["directory_inode"] < 0
    ):
        return None
    canonical = (
        json.dumps(parsed, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if canonical != raw:
        return None
    return parsed["directory_device"], parsed["directory_inode"]


def _publication_receipt_invalid(receipt_path: Path, *, reason: str) -> BananaError:
    return BananaError(
        "output_preflight_receipt_invalid",
        "The retained publication capability receipt is invalid and requires manual recovery.",
        details={
            "recovery_required": True,
            "receipt_path": str(receipt_path),
            "receipt_recovery_status": "manual_review_required",
            "reason": reason,
        },
    )


def _quarantine_stale_publication_receipt(
    *,
    directory: Path,
    directory_descriptor: int,
    receipt_name: str,
    receipt_descriptor: int,
    receipt_identity: tuple[int, int],
    receipt_bytes: bytes,
) -> Path:
    digest = hashlib.sha256(receipt_bytes).hexdigest()[:16]
    quarantine_name = f"{receipt_name}.stale-{digest}"
    quarantine_path = directory / quarantine_name
    try:
        _exclusive_rename_at(
            directory_descriptor,
            receipt_name,
            directory_descriptor,
            quarantine_name,
        )
    except FileExistsError as exc:
        raise BananaError(
            "output_preflight_quarantine_conflict",
            "The stale publication receipt quarantine name already exists. No receipt was moved or replaced.",
            details={
                "recovery_required": True,
                "quarantine_path": str(quarantine_path),
                "quarantine_collision": True,
            },
        ) from exc
    try:
        moved = os.stat(
            quarantine_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise BananaError(
            "output_preflight_quarantine_unverified",
            "The stale publication receipt movement could not be verified.",
            details={
                "recovery_required": True,
                "quarantine_path": str(quarantine_path),
            },
        ) from exc
    try:
        os.stat(receipt_name, dir_fd=directory_descriptor, follow_symlinks=False)
        original_absent = False
    except FileNotFoundError:
        original_absent = True
    except OSError as exc:
        raise BananaError(
            "output_preflight_quarantine_unverified",
            "The stale publication receipt movement could not be verified.",
            details={
                "recovery_required": True,
                "quarantine_path": str(quarantine_path),
            },
        ) from exc
    held = os.fstat(receipt_descriptor)
    if (
        not original_absent
        or (moved.st_dev, moved.st_ino) != receipt_identity
        or (held.st_dev, held.st_ino) != receipt_identity
        or held.st_nlink != 1
        or not _descriptor_has_exact_bytes(receipt_descriptor, receipt_bytes)
    ):
        raise BananaError(
            "output_preflight_quarantine_unverified",
            "The stale publication receipt movement could not be verified.",
            details={
                "recovery_required": True,
                "quarantine_path": str(quarantine_path),
            },
        )
    os.fsync(directory_descriptor)
    return quarantine_path


def acquire_output_publication(
    destination: str | Path,
) -> OutputPublicationCapability:
    """Prove publication support and retain the validated directory handle.

    The proof is retained as one private, directory-bound capability receipt.
    Retaining the receipt avoids every pathname cleanup race in this pre-spend
    transaction. Later plans revalidate its bytes, inode, mode, link count, and
    containing directory before relying on the prior proof.
    """
    directory = _approved_output_path(destination)
    directory_descriptor = _open_secure_directory(directory)
    if directory_descriptor is None:
        raise BananaError(
            "output_exclusive_rename_unavailable",
            "This platform cannot prove atomic no-replace output publication before provider execution.",
        )

    receipt_name = PUBLICATION_CAPABILITY_NAME
    receipt_path = directory / receipt_name
    source_name = f".{receipt_name}.{os.urandom(16).hex()}.tmp"
    source_path = directory / source_name
    source_descriptor: int | None = None
    source_identity: tuple[int, int] | None = None
    source_link_count: int | None = None
    receipt_identity: tuple[int, int] | None = None
    quarantine_path: Path | None = None
    completed = False
    active_error: BaseException | None = None
    try:
        if not _directory_path_matches_fd(directory, directory_descriptor):
            raise BananaError(
                "output_directory_changed",
                "The approved output directory changed before publication preflight.",
            )
        directory_metadata = os.fstat(directory_descriptor)
        receipt_bytes = (
            json.dumps(
                {
                    "directory_device": directory_metadata.st_dev,
                    "directory_inode": directory_metadata.st_ino,
                    "purpose": "atomic-no-replace-publication",
                    "schema_version": 1,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

        try:
            existing = os.stat(
                receipt_name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            existing = None

        if existing is None:
            (
                source_descriptor,
                source_name,
                source_identity,
                source_link_count,
            ) = _create_publication_receipt(
                directory,
                directory_descriptor,
                receipt_name,
                receipt_bytes,
            )
            source_path = directory / source_name
            receipt_identity = source_identity
        else:
            receipt_identity = (existing.st_dev, existing.st_ino)
            if (
                not stat.S_ISREG(existing.st_mode)
                or existing.st_nlink != 1
                or stat.S_IMODE(existing.st_mode) != 0o600
            ):
                raise _publication_receipt_invalid(
                    receipt_path,
                    reason="not_one_private_single_link_regular_file",
                )
            read_flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                read_flags |= os.O_NOFOLLOW
            if hasattr(os, "O_CLOEXEC"):
                read_flags |= os.O_CLOEXEC
            source_descriptor = os.open(
                receipt_name,
                read_flags,
                dir_fd=directory_descriptor,
            )

        held_metadata = os.fstat(source_descriptor)
        receipt_public = os.stat(
            receipt_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        receipt_identity = receipt_identity or (
            held_metadata.st_dev,
            held_metadata.st_ino,
        )
        os.lseek(source_descriptor, 0, os.SEEK_SET)
        observed_bytes = os.read(source_descriptor, MAX_PUBLICATION_RECEIPT_BYTES + 1)
        held_after = os.fstat(source_descriptor)
        receipt_after = os.stat(
            receipt_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        receipt_binding_valid = (
            stat.S_ISREG(held_metadata.st_mode)
            and held_metadata.st_nlink == 1
            and stat.S_IMODE(held_metadata.st_mode) == 0o600
            and (held_metadata.st_dev, held_metadata.st_ino) == receipt_identity
            and (receipt_public.st_dev, receipt_public.st_ino) == receipt_identity
            and (held_after.st_dev, held_after.st_ino) == receipt_identity
            and held_after.st_nlink == 1
            and held_metadata.st_size == len(observed_bytes)
            and len(observed_bytes) <= MAX_PUBLICATION_RECEIPT_BYTES
            and (receipt_after.st_dev, receipt_after.st_ino) == receipt_identity
        )
        if not receipt_binding_valid:
            raise _publication_receipt_invalid(
                receipt_path,
                reason="receipt_identity_or_bytes_changed_during_validation",
            )
        if observed_bytes != receipt_bytes:
            stale_identity = _stale_receipt_directory_identity(observed_bytes)
            current_identity = (
                directory_metadata.st_dev,
                directory_metadata.st_ino,
            )
            if stale_identity is None or stale_identity == current_identity:
                raise _publication_receipt_invalid(
                    receipt_path,
                    reason="receipt_content_not_exactly_recoverable",
                )
            quarantine_path = _quarantine_stale_publication_receipt(
                directory=directory,
                directory_descriptor=directory_descriptor,
                receipt_name=receipt_name,
                receipt_descriptor=source_descriptor,
                receipt_identity=receipt_identity,
                receipt_bytes=observed_bytes,
            )
            os.close(source_descriptor)
            source_descriptor = None
            (
                source_descriptor,
                source_name,
                source_identity,
                source_link_count,
            ) = _create_publication_receipt(
                directory,
                directory_descriptor,
                receipt_name,
                receipt_bytes,
            )
            source_path = directory / source_name
            receipt_identity = source_identity
            held_metadata = os.fstat(source_descriptor)
            receipt_public = os.stat(
                receipt_name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            os.lseek(source_descriptor, 0, os.SEEK_SET)
            observed_bytes = os.read(
                source_descriptor, MAX_PUBLICATION_RECEIPT_BYTES + 1
            )
            held_after = os.fstat(source_descriptor)
            receipt_after = os.stat(
                receipt_name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(held_metadata.st_mode)
                or held_metadata.st_nlink != 1
                or stat.S_IMODE(held_metadata.st_mode) != 0o600
                or (held_metadata.st_dev, held_metadata.st_ino) != receipt_identity
                or (receipt_public.st_dev, receipt_public.st_ino) != receipt_identity
                or (held_after.st_dev, held_after.st_ino) != receipt_identity
                or held_after.st_nlink != 1
                or held_metadata.st_size != len(observed_bytes)
                or len(observed_bytes) > MAX_PUBLICATION_RECEIPT_BYTES
                or (receipt_after.st_dev, receipt_after.st_ino) != receipt_identity
                or observed_bytes != receipt_bytes
            ):
                invalid = _publication_receipt_invalid(
                    receipt_path,
                    reason="refreshed_receipt_verification_failed",
                )
                invalid.details["quarantine_path"] = str(quarantine_path)
                raise invalid
        os.fsync(directory_descriptor)
        if not _directory_path_matches_fd(directory, directory_descriptor):
            raise BananaError(
                "output_directory_changed",
                "The approved output directory changed during publication preflight.",
            )
        completed = True
    except BaseException as exc:
        active_error = exc
    finally:
        if source_descriptor is not None:
            try:
                source_link_count = os.fstat(source_descriptor).st_nlink
            except OSError:
                pass
            os.close(source_descriptor)
        if not completed:
            os.close(directory_descriptor)

    if completed:
        return OutputPublicationCapability(directory, directory_descriptor)
    if isinstance(active_error, BananaError):
        code = active_error.code
        message = active_error.message
    else:
        code = "output_preflight_failed"
        message = "The output filesystem could not prove atomic no-replace publication before provider execution."
    details: dict[str, Any] = {
        "provider_called": False,
        "recovery_required": source_identity is not None
        or receipt_identity is not None,
        "preflight_receipt_path": str(receipt_path),
        "preflight_path_requires_identity_check": True,
    }
    if isinstance(active_error, BananaError):
        details.update(active_error.details)
    if quarantine_path is not None:
        details["quarantine_path"] = str(quarantine_path)
        details["stale_receipt_quarantined"] = True
    if source_identity is not None:
        details["preflight_source"] = _unlocated_recovery_artifact(
            source_identity,
            last_known_path=source_path,
            link_count=source_link_count,
        )
    if receipt_identity is not None:
        details["preflight_receipt_identity"] = {
            "device": receipt_identity[0],
            "inode": receipt_identity[1],
            "path_binding_verified": False,
            "verify_device_and_inode": True,
        }
    raise BananaError(code, message, details=details) from active_error


def preflight_output_publication(destination: str | Path) -> None:
    """Plan-time wrapper proving publication support without retaining a handle."""
    capability = acquire_output_publication(destination)
    capability.close()


def _hold_output_directory(destination: str | Path) -> OutputPublicationCapability:
    """Hold a directory for publication when provider preflight is not needed."""
    directory = _approved_output_path(destination)
    descriptor = _open_secure_directory(directory)
    if descriptor is None:
        raise BananaError(
            "output_exclusive_rename_unavailable",
            "This platform cannot hold the output directory for safe publication.",
        )
    return OutputPublicationCapability(directory, descriptor)


def _safe_error_code(error: BaseException) -> str:
    if isinstance(error, BananaError) and re.fullmatch(r"[a-z0-9_]{1,64}", error.code):
        return error.code
    return "unexpected_publication_error"


def _root_publication_error_code(error: BaseException) -> str:
    if isinstance(error, BananaError):
        nested = error.details.get("publication_error_code")
        if isinstance(nested, str) and re.fullmatch(r"[a-z0-9_]{1,64}", nested):
            return nested
    return _safe_error_code(error)


def _recovery_artifact(path: Path, identity: tuple[int, int]) -> dict[str, Any]:
    return {
        "path": str(path),
        "device": identity[0],
        "inode": identity[1],
        "path_binding_verified": True,
        "verify_device_and_inode": True,
    }


def _unlocated_recovery_artifact(
    identity: tuple[int, int],
    *,
    last_known_path: Path,
    link_count: int | None = None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "path": None,
        "last_known_path": str(last_known_path),
        "device": identity[0],
        "inode": identity[1],
        "path_binding_verified": False,
        "path_unknown": True,
        "verify_device_and_inode": True,
    }
    if link_count is not None:
        receipt["last_observed_link_count"] = link_count
    return receipt


def _observed_entry_identity_at(
    directory_descriptor: int,
    name: str,
) -> tuple[int, int] | None:
    try:
        metadata = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except OSError:
        return None
    return metadata.st_dev, metadata.st_ino


def _descriptor_has_exact_bytes(descriptor: int, expected: bytes) -> bool:
    try:
        original_offset = os.lseek(descriptor, 0, os.SEEK_CUR)
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        total = 0
        while total <= len(expected):
            chunk = os.read(descriptor, min(1024 * 1024, len(expected) + 1 - total))
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
        os.lseek(descriptor, original_offset, os.SEEK_SET)
    except OSError:
        return False
    return bool(
        total == len(expected) and digest.digest() == hashlib.sha256(expected).digest()
    )


def _complete_file_receipt_matches(
    directory_descriptor: int,
    name: str,
    descriptor: int,
    expected_identity: tuple[int, int],
    expected: bytes,
) -> bool:
    try:
        held_before = os.fstat(descriptor)
        public_before = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        exact_bytes = _descriptor_has_exact_bytes(descriptor, expected)
        held_after = os.fstat(descriptor)
        public_after = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except OSError:
        return False

    def receipt(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            stat.S_IFMT(metadata.st_mode),
            stat.S_IMODE(metadata.st_mode),
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    expected_mode = 0o600 if os.name != "nt" else stat.S_IMODE(held_before.st_mode)
    return bool(
        exact_bytes
        and receipt(held_before) == receipt(held_after)
        and receipt(public_before) == receipt(public_after)
        and receipt(held_after) == receipt(public_after)
        and stat.S_ISREG(held_after.st_mode)
        and held_after.st_nlink == 1
        and stat.S_IMODE(held_after.st_mode) == expected_mode
        and held_after.st_size == len(expected)
        and (held_after.st_dev, held_after.st_ino) == expected_identity
    )


def _complete_path_file_receipt_matches(
    path: Path,
    descriptor: int,
    expected_identity: tuple[int, int],
    expected: bytes,
) -> bool:
    try:
        held_before = os.fstat(descriptor)
        public_before = os.lstat(path)
        exact_bytes = _descriptor_has_exact_bytes(descriptor, expected)
        held_after = os.fstat(descriptor)
        public_after = os.lstat(path)
    except OSError:
        return False

    def receipt(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            stat.S_IFMT(metadata.st_mode),
            stat.S_IMODE(metadata.st_mode),
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    expected_mode = 0o600 if os.name != "nt" else stat.S_IMODE(held_before.st_mode)
    return bool(
        exact_bytes
        and receipt(held_before) == receipt(held_after)
        and receipt(public_before) == receipt(public_after)
        and receipt(held_after) == receipt(public_after)
        and stat.S_ISREG(held_after.st_mode)
        and held_after.st_nlink == 1
        and stat.S_IMODE(held_after.st_mode) == expected_mode
        and held_after.st_size == len(expected)
        and (held_after.st_dev, held_after.st_ino) == expected_identity
    )


def _error_with_temporary_recovery(
    error: BananaError,
    temporary_path: Path,
    intended_identity: tuple[int, int] | None,
    *,
    observed_identity: tuple[int, int] | None,
    path_is_bound: bool,
    intended_link_count: int | None,
) -> BananaError:
    details = dict(error.details)
    details.update(
        {
            "recovery_required": True,
            "temporary_path": str(temporary_path),
            "temporary_path_identity_unknown": observed_identity is None,
            "temporary_path_requires_identity_check": True,
        }
    )
    if observed_identity is not None:
        details["temporary_not_deleted"] = True
        details["temporary_identity"] = {
            "device": observed_identity[0],
            "inode": observed_identity[1],
        }
        details["retained_artifacts"] = [
            _recovery_artifact(temporary_path, observed_identity)
            if path_is_bound
            else _unlocated_recovery_artifact(
                observed_identity,
                last_known_path=temporary_path,
            )
        ]
    if intended_identity is not None:
        details["intended_artifact"] = {
            "device": intended_identity[0],
            "inode": intended_identity[1],
            "last_known_path": str(temporary_path),
            "path_binding_verified": observed_identity == intended_identity
            and path_is_bound,
            "path_unknown": observed_identity != intended_identity or not path_is_bound,
            "last_observed_link_count": intended_link_count,
        }
        if observed_identity != intended_identity or not path_is_bound:
            details["intended_artifact_path_unknown"] = True
    return BananaError(
        error.code,
        error.message,
        retryable=error.retryable,
        http_status=error.http_status,
        details=details,
    )


def _atomic_write_at(
    directory_descriptor: int,
    name: str,
    data: bytes,
    *,
    replace: bool = True,
    expected_directory: Path | None = None,
    expected_destination_identity: tuple[int, int] | None | object = (
        _DESTINATION_IDENTITY_UNCHECKED
    ),
) -> tuple[int, int]:
    """Atomically publish one basename relative to a held directory descriptor."""
    if not name or name in {".", ".."} or Path(name).name != name:
        raise BananaError("output_claim_failed", "Output name is not one basename.")
    label = expected_directory / name if expected_directory is not None else Path(name)
    if expected_directory is not None and not _directory_path_matches_fd(
        expected_directory, directory_descriptor
    ):
        raise BananaError(
            "output_directory_changed",
            "The output directory changed before publication. No redirected output was written.",
        )
    temporary_name = f".{name}.{os.urandom(16).hex()}.tmp"
    temporary_label = (
        expected_directory / temporary_name
        if expected_directory is not None
        else Path(temporary_name)
    )
    temporary_identity: tuple[int, int] | None = None
    temporary_descriptor: int | None = None
    temporary_link_count: int | None = None
    published_identity: tuple[int, int] | None = None
    publication_may_exist = False
    active_error: BaseException | None = None
    active_cause: BaseException | None = None
    try:
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=directory_descriptor)
        temporary_descriptor = descriptor
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise BananaError(
                "output_claim_failed", "Temporary output is not one regular file."
            )
        temporary_identity = (metadata.st_dev, metadata.st_ino)
        temporary_link_count = metadata.st_nlink
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            if os.name != "nt":
                os.fchmod(handle.fileno(), 0o600)

        if expected_directory is not None and not _directory_path_matches_fd(
            expected_directory, directory_descriptor
        ):
            raise BananaError(
                "output_directory_changed",
                "The output directory changed during publication. No redirected output was accepted.",
            )
        if expected_destination_identity is not _DESTINATION_IDENTITY_UNCHECKED:
            observed_destination_identity = _observed_entry_identity_at(
                directory_descriptor,
                name,
            )
            if observed_destination_identity != expected_destination_identity:
                raise BananaError(
                    "output_destination_changed",
                    "The destination changed after it was read. No replacement was attempted.",
                    details={
                        "expected_destination_identity": (
                            {
                                "device": expected_destination_identity[0],
                                "inode": expected_destination_identity[1],
                            }
                            if isinstance(expected_destination_identity, tuple)
                            else None
                        ),
                        "observed_destination_identity": (
                            {
                                "device": observed_destination_identity[0],
                                "inode": observed_destination_identity[1],
                            }
                            if observed_destination_identity is not None
                            else None
                        ),
                    },
                )
        source_metadata = os.stat(
            temporary_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        held_metadata = os.fstat(descriptor)
        temporary_link_count = held_metadata.st_nlink
        if (
            not stat.S_ISREG(source_metadata.st_mode)
            or source_metadata.st_nlink != 1
            or not stat.S_ISREG(held_metadata.st_mode)
            or held_metadata.st_nlink != 1
            or (source_metadata.st_dev, source_metadata.st_ino) != temporary_identity
            or (held_metadata.st_dev, held_metadata.st_ino) != temporary_identity
            or stat.S_IMODE(source_metadata.st_mode) != 0o600
            or source_metadata.st_size != len(data)
            or not _descriptor_has_exact_bytes(descriptor, data)
        ):
            raise BananaError(
                "output_claim_changed",
                "The temporary output changed before publication. No path was accepted as the intended artifact.",
            )
        if replace:
            os.replace(
                temporary_name,
                name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
            )
            publication_may_exist = True
        else:
            try:
                _exclusive_rename_at(
                    directory_descriptor,
                    temporary_name,
                    directory_descriptor,
                    name,
                )
            except FileExistsError as exc:
                raise BananaError(
                    "output_exists",
                    f"Output already exists: {label}. Choose a new path or explicitly replace it.",
                ) from exc
            publication_may_exist = True
        try:
            published_metadata = os.stat(
                name, dir_fd=directory_descriptor, follow_symlinks=False
            )
        except OSError as exc:
            raise BananaError(
                "output_publication_stat_failed",
                f"Could not verify the published output: {label}.",
            ) from exc
        published_identity = (published_metadata.st_dev, published_metadata.st_ino)
        if (
            published_identity != temporary_identity
            or not _complete_file_receipt_matches(
                directory_descriptor,
                name,
                descriptor,
                temporary_identity,
                data,
            )
        ):
            raise BananaError(
                "output_claim_changed",
                f"The published output changed before it could be accepted: {label}.",
            )
        os.fsync(directory_descriptor)
        if expected_directory is not None and not _directory_path_matches_fd(
            expected_directory, directory_descriptor
        ):
            raise BananaError(
                "output_directory_changed",
                "The output directory changed during publication. The result was not accepted.",
            )
        try:
            committed_metadata = os.stat(
                name, dir_fd=directory_descriptor, follow_symlinks=False
            )
        except OSError as exc:
            raise BananaError(
                "output_publication_stat_failed",
                f"Could not verify the committed output: {label}.",
            ) from exc
        published_identity = (committed_metadata.st_dev, committed_metadata.st_ino)
        if (
            published_identity != temporary_identity
            or not _complete_file_receipt_matches(
                directory_descriptor,
                name,
                descriptor,
                temporary_identity,
                data,
            )
        ):
            raise BananaError(
                "output_claim_changed",
                f"The published output changed before it could be accepted: {label}.",
            )
        if temporary_descriptor is not None:
            os.close(temporary_descriptor)
            temporary_descriptor = None
        return temporary_identity
    except BananaError as exc:
        active_error = exc
    except OSError as exc:
        active_error = BananaError(
            "output_claim_failed", f"Could not safely publish output: {label}."
        )
        active_cause = exc
    except BaseException as exc:
        active_error = exc

    if active_error is not None:
        expected_path_is_bound = (
            expected_directory is None
            or _directory_path_matches_fd(expected_directory, directory_descriptor)
        )
        held_identity = temporary_identity
        if temporary_descriptor is not None:
            try:
                held_metadata = os.fstat(temporary_descriptor)
                temporary_link_count = held_metadata.st_nlink
                held_identity = (held_metadata.st_dev, held_metadata.st_ino)
            except OSError:
                temporary_link_count = None
            os.close(temporary_descriptor)
            temporary_descriptor = None
        observed_temporary_identity = _observed_entry_identity_at(
            directory_descriptor,
            temporary_name,
        )
        observed_destination_identity = _observed_entry_identity_at(
            directory_descriptor,
            name,
        )
        temporary_is_intended = bool(
            held_identity is not None and observed_temporary_identity == held_identity
        )
        destination_is_intended = bool(
            held_identity is not None and observed_destination_identity == held_identity
        )
        publication_uncertain = publication_may_exist or destination_is_intended
        retained_artifacts: list[dict[str, Any]] = []
        if observed_destination_identity is not None:
            observed_destination = (
                _recovery_artifact(label, observed_destination_identity)
                if expected_path_is_bound
                else _unlocated_recovery_artifact(
                    observed_destination_identity,
                    last_known_path=label,
                )
            )
            observed_destination["artifact_relationship"] = (
                "intended_artifact"
                if destination_is_intended
                else "observed_nonmatching_destination"
            )
            retained_artifacts.append(observed_destination)
        if observed_temporary_identity is not None:
            observed_temporary = (
                _recovery_artifact(
                    temporary_label,
                    observed_temporary_identity,
                )
                if expected_path_is_bound
                else _unlocated_recovery_artifact(
                    observed_temporary_identity,
                    last_known_path=temporary_label,
                )
            )
            observed_temporary["artifact_relationship"] = (
                "intended_temporary_artifact"
                if temporary_is_intended
                else "observed_nonmatching_temporary_entry"
            )
            retained_artifacts.append(observed_temporary)
        normalized = (
            active_error
            if isinstance(active_error, BananaError)
            else BananaError(
                "output_claim_failed", f"Could not safely publish output: {label}."
            )
        )
        details = dict(normalized.details)
        details.update(
            {
                "publication_error_code": _safe_error_code(active_error),
                "recovery_required": bool(retained_artifacts or held_identity),
                "publication_path": str(label),
                "publication_path_identity_unknown": (
                    observed_destination_identity is None
                ),
                "retained_artifacts": retained_artifacts,
            }
        )
        if observed_temporary_identity is not None:
            details.update(
                {
                    "temporary_not_deleted": True,
                    "temporary_path": str(temporary_label),
                    "temporary_identity": {
                        "device": observed_temporary_identity[0],
                        "inode": observed_temporary_identity[1],
                    },
                    "temporary_path_requires_identity_check": True,
                }
            )
        if observed_destination_identity is not None:
            details["observed_destination_entry"] = {
                "device": observed_destination_identity[0],
                "inode": observed_destination_identity[1],
                "path": str(label) if expected_path_is_bound else None,
                "last_known_path": str(label),
                "path_binding_verified": expected_path_is_bound,
                "matches_intended_identity": destination_is_intended,
            }
        if held_identity is not None:
            if temporary_is_intended:
                intended_path = temporary_label
                intended_bound = expected_path_is_bound
            elif destination_is_intended:
                intended_path = label
                intended_bound = expected_path_is_bound
            else:
                intended_path = temporary_label
                intended_bound = False
            details["intended_artifact"] = {
                "device": held_identity[0],
                "inode": held_identity[1],
                "path": str(intended_path) if intended_bound else None,
                "last_known_path": str(intended_path),
                "path_binding_verified": intended_bound,
                "path_unknown": not intended_bound,
                "last_observed_link_count": temporary_link_count,
            }
            if not intended_bound:
                details["intended_artifact_path_unknown"] = True
        if publication_uncertain:
            raise BananaError(
                "output_publication_retained",
                "Output publication did not complete verification. Recovery retained every observed entry for identity-based review.",
                details=details,
            ) from active_error
        recovered = BananaError(
            normalized.code,
            normalized.message,
            retryable=normalized.retryable,
            http_status=normalized.http_status,
            details=details,
        )
        if active_cause is not None:
            raise recovered from active_cause
        raise recovered from active_error
    if temporary_descriptor is not None:
        os.close(temporary_descriptor)
    raise BananaError(
        "output_claim_failed", f"Could not verify the published output: {label}."
    )


def _atomic_write(path: Path, data: bytes, *, replace: bool = True) -> tuple[int, int]:
    absolute = Path(os.path.abspath(path))
    directory_descriptor = _open_secure_directory(absolute.parent)
    if directory_descriptor is None:
        if not replace and not _path_rename_without_replace_supported():
            raise BananaError(
                "output_exclusive_rename_unavailable",
                "This platform cannot safely publish a new output without replacing an existing path.",
            )
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{absolute.name}.", dir=str(absolute.parent)
            )
        except OSError as exc:
            raise BananaError(
                "output_claim_failed", f"Could not create a private output: {absolute}."
            ) from exc
        temporary_path = Path(temporary_name)
        temporary_identity: tuple[int, int] | None = None
        temporary_descriptor: int | None = descriptor
        published_identity: tuple[int, int] | None = None
        publication_may_exist = False
        active_error: BaseException | None = None
        active_cause: BaseException | None = None
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                metadata = os.fstat(handle.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise BananaError(
                        "output_claim_failed",
                        "Temporary output is not one regular file.",
                    )
                temporary_identity = (metadata.st_dev, metadata.st_ino)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
                if os.name != "nt":
                    os.fchmod(handle.fileno(), 0o600)
            if not _complete_path_file_receipt_matches(
                temporary_path,
                descriptor,
                temporary_identity,
                data,
            ):
                raise BananaError(
                    "output_claim_changed",
                    "The temporary output changed before path publication.",
                )
            if replace:
                os.replace(temporary_path, absolute)
                publication_may_exist = True
            else:
                try:
                    os.rename(temporary_path, absolute)
                except FileExistsError as exc:
                    raise BananaError(
                        "output_exists",
                        f"Output already exists: {absolute}. Choose a new path or explicitly replace it.",
                    ) from exc
                publication_may_exist = True
            try:
                published = os.lstat(absolute)
            except OSError as exc:
                raise BananaError(
                    "output_publication_stat_failed",
                    f"Could not verify the published output: {absolute}.",
                ) from exc
            published_identity = (published.st_dev, published.st_ino)
            if (
                published_identity != temporary_identity
                or not _complete_path_file_receipt_matches(
                    absolute,
                    descriptor,
                    temporary_identity,
                    data,
                )
            ):
                raise BananaError(
                    "output_claim_changed",
                    f"The published output changed before it could be accepted: {absolute}.",
                )
            os.close(descriptor)
            temporary_descriptor = None
            return temporary_identity
        except BananaError as exc:
            active_error = exc
        except OSError as exc:
            active_error = BananaError(
                "output_claim_failed", f"Could not safely publish output: {absolute}."
            )
            active_cause = exc
        except BaseException as exc:
            active_error = exc

        if active_error is not None:
            held_identity = temporary_identity
            held_link_count: int | None = None
            if temporary_descriptor is not None:
                try:
                    held_metadata = os.fstat(temporary_descriptor)
                    held_identity = (held_metadata.st_dev, held_metadata.st_ino)
                    held_link_count = held_metadata.st_nlink
                except OSError:
                    pass
                os.close(temporary_descriptor)
                temporary_descriptor = None

            def observed_identity(candidate: Path) -> tuple[int, int] | None:
                try:
                    metadata = os.lstat(candidate)
                except OSError:
                    return None
                return metadata.st_dev, metadata.st_ino

            observed_temporary_identity = observed_identity(temporary_path)
            observed_destination_identity = observed_identity(absolute)
            temporary_is_intended = bool(
                held_identity is not None
                and observed_temporary_identity == held_identity
            )
            destination_is_intended = bool(
                held_identity is not None
                and observed_destination_identity == held_identity
            )
            publication_uncertain = publication_may_exist or destination_is_intended
            retained_artifacts: list[dict[str, Any]] = []
            if observed_destination_identity is not None:
                destination_receipt = _recovery_artifact(
                    absolute,
                    observed_destination_identity,
                )
                destination_receipt["artifact_relationship"] = (
                    "intended_artifact"
                    if destination_is_intended
                    else "observed_nonmatching_destination"
                )
                retained_artifacts.append(destination_receipt)
            if observed_temporary_identity is not None:
                temporary_receipt = _recovery_artifact(
                    temporary_path,
                    observed_temporary_identity,
                )
                temporary_receipt["artifact_relationship"] = (
                    "intended_temporary_artifact"
                    if temporary_is_intended
                    else "observed_nonmatching_temporary_entry"
                )
                retained_artifacts.append(temporary_receipt)
            normalized = (
                active_error
                if isinstance(active_error, BananaError)
                else BananaError(
                    "output_claim_failed",
                    f"Could not safely publish output: {absolute}.",
                )
            )
            details = dict(normalized.details)
            details.update(
                {
                    "publication_error_code": _safe_error_code(active_error),
                    "recovery_required": bool(retained_artifacts or held_identity),
                    "retained_artifacts": retained_artifacts,
                }
            )
            if observed_temporary_identity is not None:
                details.update(
                    {
                        "temporary_not_deleted": True,
                        "temporary_path": str(temporary_path),
                        "temporary_identity": {
                            "device": observed_temporary_identity[0],
                            "inode": observed_temporary_identity[1],
                        },
                        "temporary_path_requires_identity_check": True,
                    }
                )
            if observed_destination_identity is not None:
                details["observed_destination_entry"] = {
                    "path": str(absolute),
                    "device": observed_destination_identity[0],
                    "inode": observed_destination_identity[1],
                    "path_binding_verified": True,
                    "matches_intended_identity": destination_is_intended,
                }
            if held_identity is not None:
                if temporary_is_intended:
                    intended_path = temporary_path
                    intended_bound = True
                elif destination_is_intended:
                    intended_path = absolute
                    intended_bound = True
                else:
                    intended_path = temporary_path
                    intended_bound = False
                details["intended_artifact"] = {
                    "device": held_identity[0],
                    "inode": held_identity[1],
                    "path": str(intended_path) if intended_bound else None,
                    "last_known_path": str(intended_path),
                    "path_binding_verified": intended_bound,
                    "path_unknown": not intended_bound,
                    "last_observed_link_count": held_link_count,
                }
                if not intended_bound:
                    details["intended_artifact_path_unknown"] = True
            if publication_uncertain:
                raise BananaError(
                    "output_publication_retained",
                    "Output publication did not complete verification. Recovery retained every observed entry for identity-based review.",
                    details=details,
                ) from active_error
            recovered = BananaError(
                normalized.code,
                normalized.message,
                retryable=normalized.retryable,
                http_status=normalized.http_status,
                details=details,
            )
            if active_cause is not None:
                raise recovered from active_cause
            raise recovered from active_error
        if temporary_descriptor is not None:
            os.close(temporary_descriptor)
        raise BananaError(
            "output_claim_failed", f"Could not verify the published output: {absolute}."
        )

    try:
        return _atomic_write_at(
            directory_descriptor,
            absolute.name,
            data,
            replace=replace,
            expected_directory=absolute.parent,
        )
    finally:
        os.close(directory_descriptor)


def _path_rename_without_replace_supported() -> bool:
    """Python's path rename is no-replace on Windows, unlike POSIX rename."""
    return os.name == "nt"


def _bundle_artifact_identity(
    path: Path, directory_descriptor: int | None
) -> tuple[int, int]:
    try:
        if directory_descriptor is None:
            metadata = os.lstat(path)
        else:
            metadata = os.stat(
                path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
    except OSError as exc:
        raise BananaError(
            "output_bundle_stat_failed",
            "A published artifact could not be inspected during final bundle verification.",
        ) from exc
    return metadata.st_dev, metadata.st_ino


class _BundleMetadataReceipt(NamedTuple):
    device: int
    inode: int
    file_type: int
    mode: int
    link_count: int
    size: int
    mtime_ns: int
    ctime_ns: int


class _BundlePhaseAReceipt(NamedTuple):
    device: int
    inode: int
    file_type: int
    mode: int
    link_count: int
    size: int
    mtime_ns: int
    ctime_ns: int
    sha256: bytes
    signature_mime_type: str | None


class _RetainedBundleMember(NamedTuple):
    path: Path
    identity: tuple[int, int]
    payload: bytes
    descriptor: int
    baseline: _BundleMetadataReceipt
    expected_sha256: bytes
    expected_signature_mime_type: str | None


def _bundle_metadata_receipt(metadata: os.stat_result) -> _BundleMetadataReceipt:
    return _BundleMetadataReceipt(
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
        stat.S_IMODE(metadata.st_mode),
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _bundle_drift_error() -> BananaError:
    return BananaError(
        "output_claim_changed",
        "A published artifact changed before the bundle could be accepted.",
    )


def _descriptor_digest_and_prefix(
    descriptor: int,
    *,
    expected_size: int,
) -> tuple[int, bytes, bytes]:
    """Hash one held file without allowing an unbounded concurrent growth read."""
    original_offset = os.lseek(descriptor, 0, os.SEEK_CUR)
    digest = hashlib.sha256()
    prefix = bytearray()
    total = 0
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while total <= expected_size:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, expected_size + 1 - total),
            )
            if not chunk:
                break
            if len(prefix) < 12:
                prefix.extend(chunk[: 12 - len(prefix)])
            digest.update(chunk)
            total += len(chunk)
    finally:
        os.lseek(descriptor, original_offset, os.SEEK_SET)
    return total, digest.digest(), bytes(prefix)


def _bundle_phase_a_receipt(
    directory_descriptor: int,
    member: _RetainedBundleMember,
) -> _BundlePhaseAReceipt | None:
    """Fully verify one held member and return its stable post-hash receipt."""
    held_before = os.fstat(member.descriptor)
    public_before = os.stat(
        member.path.name,
        dir_fd=directory_descriptor,
        follow_symlinks=False,
    )
    expected_mode = 0o600 if os.name != "nt" else stat.S_IMODE(held_before.st_mode)
    held_before_receipt = _bundle_metadata_receipt(held_before)
    public_before_receipt = _bundle_metadata_receipt(public_before)
    if (
        not stat.S_ISREG(held_before.st_mode)
        or not stat.S_ISREG(public_before.st_mode)
        or held_before.st_nlink != 1
        or public_before.st_nlink != 1
        or stat.S_IMODE(held_before.st_mode) != expected_mode
        or stat.S_IMODE(public_before.st_mode) != expected_mode
        or held_before.st_size != len(member.payload)
        or public_before.st_size != len(member.payload)
        or (held_before.st_dev, held_before.st_ino) != member.identity
        or (public_before.st_dev, public_before.st_ino) != member.identity
        or held_before_receipt != member.baseline
        or public_before_receipt != member.baseline
    ):
        return None

    total, observed_digest, prefix = _descriptor_digest_and_prefix(
        member.descriptor,
        expected_size=len(member.payload),
    )
    held_after = os.fstat(member.descriptor)
    public_after = os.stat(
        member.path.name,
        dir_fd=directory_descriptor,
        follow_symlinks=False,
    )
    held_after_receipt = _bundle_metadata_receipt(held_after)
    public_after_receipt = _bundle_metadata_receipt(public_after)
    signature_matches = (
        member.expected_signature_mime_type is None
        or _matches_image_signature(
            prefix,
            member.expected_signature_mime_type,
        )
    )
    if (
        total != len(member.payload)
        or observed_digest != member.expected_sha256
        or not signature_matches
        or held_before_receipt != held_after_receipt
        or public_before_receipt != public_after_receipt
        or held_after_receipt != public_after_receipt
        or held_after_receipt != member.baseline
    ):
        return None
    return _BundlePhaseAReceipt(
        *held_after_receipt,
        observed_digest,
        member.expected_signature_mime_type,
    )


def _bundle_phase_b_receipt_matches(
    directory_descriptor: int,
    member: _RetainedBundleMember,
    phase_a: _BundlePhaseAReceipt,
) -> bool:
    """Recheck one member at its point in the final bounded acceptance sweep."""
    held = _bundle_metadata_receipt(os.fstat(member.descriptor))
    public = _bundle_metadata_receipt(
        os.stat(
            member.path.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    )
    phase_a_metadata = _BundleMetadataReceipt(*phase_a[:8])
    return bool(
        held == phase_a_metadata
        and public == phase_a_metadata
        and (held.device, held.inode) == member.identity
        and phase_a.sha256 == member.expected_sha256
        and phase_a.signature_mime_type == member.expected_signature_mime_type
    )


def _open_retained_bundle_member(
    directory_descriptor: int,
    path: Path,
    expected_identity: tuple[int, int],
    expected: bytes,
) -> _RetainedBundleMember:
    """Reopen one published member and retain its stable baseline receipt."""
    flags = os.O_RDONLY
    for optional_flag in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
        flags |= int(getattr(os, optional_flag, 0))
    try:
        descriptor = os.open(path.name, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        raise _bundle_drift_error() from exc
    try:
        held_before = os.fstat(descriptor)
        public_before = os.stat(
            path.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        held_after = os.fstat(descriptor)
        public_after = os.stat(
            path.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        baseline = _bundle_metadata_receipt(held_after)
        expected_mode = 0o600 if os.name != "nt" else baseline.mode
        if (
            _bundle_metadata_receipt(held_before) != baseline
            or _bundle_metadata_receipt(public_before) != baseline
            or _bundle_metadata_receipt(public_after) != baseline
            or baseline.file_type != stat.S_IFREG
            or baseline.mode != expected_mode
            or baseline.link_count != 1
            or baseline.size != len(expected)
            or (baseline.device, baseline.inode) != expected_identity
        ):
            raise _bundle_drift_error()
    except OSError as exc:
        os.close(descriptor)
        raise _bundle_drift_error() from exc
    except BaseException:
        os.close(descriptor)
        raise
    return _RetainedBundleMember(
        path,
        expected_identity,
        expected,
        descriptor,
        baseline,
        hashlib.sha256(expected).digest(),
        MIME_BY_SUFFIX.get(path.suffix.lower()),
    )


def _retained_artifacts_from_error(error: BaseException) -> list[dict[str, Any]]:
    if not isinstance(error, BananaError):
        return []
    retained = error.details.get("retained_artifacts")
    if not isinstance(retained, list):
        return []
    return [dict(item) for item in retained if isinstance(item, dict)]


def _bundle_recovery_artifacts(
    published: list[tuple[Path, tuple[int, int]]],
    *,
    directory: Path,
    directory_descriptor: int | None,
) -> list[dict[str, Any]]:
    """Describe intended and observed bundle entries without overstating binding."""
    directory_is_bound = (
        directory_descriptor is not None
        and _directory_path_matches_fd(directory, directory_descriptor)
    )
    retained: list[dict[str, Any]] = []
    for path, intended_identity in published:
        try:
            observed_identity = _bundle_artifact_identity(path, directory_descriptor)
        except (BananaError, OSError):
            observed_identity = None
        if directory_is_bound and observed_identity == intended_identity:
            artifact = _recovery_artifact(path, intended_identity)
            artifact["artifact_relationship"] = "intended_call_artifact"
            retained.append(artifact)
            continue

        intended = _unlocated_recovery_artifact(
            intended_identity,
            last_known_path=path,
        )
        intended["artifact_relationship"] = "intended_call_artifact"
        retained.append(intended)
        if observed_identity is not None:
            if directory_is_bound:
                observed = _recovery_artifact(path, observed_identity)
            else:
                observed = _unlocated_recovery_artifact(
                    observed_identity,
                    last_known_path=path,
                )
            observed["artifact_relationship"] = "observed_nonmatching_public_entry"
            observed["not_this_call_artifact"] = True
            retained.append(observed)
    return retained


def _validated_plan_prompt(plan: dict[str, Any], prompt: str) -> str:
    """Return the normalized prompt only when it matches the approved plan."""
    clean_prompt = validate_approval_text(
        prompt,
        field="Prompt",
        max_length=MAX_PROMPT_CHARS,
        multiline=True,
    )
    expected_prompt_digest = plan.get("prompt_sha256")
    if (
        not isinstance(expected_prompt_digest, str)
        or hashlib.sha256(clean_prompt.encode("utf-8")).hexdigest()
        != expected_prompt_digest
    ):
        raise BananaError(
            "prompt_mismatch",
            "The prompt no longer matches the approved execution plan.",
        )
    return clean_prompt


def provider_attempt_sha256(
    *,
    request_fingerprint: str,
    approval_id: str | None = None,
    scope: str | None = None,
) -> str:
    """Return a non-secret idempotency digest for one provider attempt."""
    material: dict[str, str] = {
        "request_fingerprint": request_fingerprint,
    }
    if approval_id is None:
        material["nonce"] = os.urandom(32).hex()
    else:
        material["approval_id"] = approval_id
    if scope is not None:
        material["scope"] = scope
    canonical = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(b"banana.provider-attempt.v1\0" + canonical).hexdigest()


def _provider_response_processing_error(
    error: BaseException,
    *,
    attempt_sha256: str,
) -> BananaError:
    """Preserve the root error and disclose the completed provider attempt."""
    if isinstance(error, BananaError):
        code = error.code
        message = error.message
        retryable = error.retryable
        http_status = error.http_status
        details = dict(error.details)
    else:
        code = "provider_response_processing_failed"
        message = "The provider responded, but its response could not be processed."
        retryable = False
        http_status = None
        details = {}
    details.update(
        {
            "provider_response_received": True,
            "billable_attempt": True,
            "provider_attempt_count": 1,
            "provider_output_count": None,
            "provider_output_count_known": False,
            "attempt_sha256": attempt_sha256,
            "cost_recording_status": "not_recorded",
            "cost_log_recorded": False,
            "unlogged_billable_attempt": True,
        }
    )
    return BananaError(
        code,
        message,
        retryable=retryable,
        http_status=http_status,
        details=details,
    )


def _safe_exception_type_name(error: BaseException) -> str:
    candidate = type(error).__name__
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", candidate):
        return candidate
    return "BaseException"


def _cost_reconciliation_error_payload(
    *,
    status: str,
    attempt_sha256: str,
    reason: str,
    error: BaseException | None = None,
) -> dict[str, Any]:
    if status == "not_recorded":
        code = "cost_recording_not_recorded"
        message = (
            "The billable provider attempt is conclusively absent from the cost ledger."
        )
    else:
        code = "cost_recording_unknown_requires_reconciliation"
        message = "The billable provider attempt requires cost-ledger reconciliation."
    details: dict[str, Any] = {
        "status": status,
        "attempt_sha256": attempt_sha256,
        "reason": reason,
    }
    if error is not None:
        details["exception_type"] = _safe_exception_type_name(error)
    return BananaError(code, message, details=details).as_dict()


def _raise_post_provider_cost_interrupt(
    interruption: BaseException,
    *,
    reconcile_generation_attempt: Callable[..., dict[str, Any]],
    model: str,
    resolution: str,
    count: int,
    label: str,
    batch: bool,
    interaction_id: str | None,
    attempt_sha256: str,
    estimated_image_output_usd: float,
) -> NoReturn:
    """Reconcile an interrupted cost write, then stop before artifact publication."""
    status = "unknown_requires_reconciliation"
    cost_log_recorded: bool | None = None
    unlogged_billable_attempt: bool | None = None
    cost_log: dict[str, Any] | None = None
    reconciliation_error: dict[str, Any] | None = None
    try:
        observed = reconcile_generation_attempt(
            model=model,
            resolution=resolution,
            count=count,
            label=label,
            batch=batch,
            interaction_id=interaction_id,
            attempt_sha256=attempt_sha256,
        )
        if (
            observed.get("status") == "recorded"
            and observed.get("logged") is True
            and observed.get("attempt_sha256") == attempt_sha256
        ):
            status = "recorded"
            cost_log_recorded = True
            unlogged_billable_attempt = False
            cost_log = observed
        else:
            reconciliation_error = _cost_reconciliation_error_payload(
                status="unknown_requires_reconciliation",
                attempt_sha256=attempt_sha256,
                reason="unexpected_cost_reconciliation_result",
            )
    except BananaError as error:
        observed_status = error.details.get("status")
        observed_attempt = error.details.get("attempt_sha256")
        if (
            error.code == "cost_recording_not_recorded"
            and observed_status == "not_recorded"
            and observed_attempt == attempt_sha256
        ):
            status = "not_recorded"
            cost_log_recorded = False
            unlogged_billable_attempt = True
            reconciliation_error = _cost_reconciliation_error_payload(
                status=status,
                attempt_sha256=attempt_sha256,
                reason="attempt_digest_conclusively_absent",
            )
        else:
            reconciliation_error = _cost_reconciliation_error_payload(
                status="unknown_requires_reconciliation",
                attempt_sha256=attempt_sha256,
                reason="cost_reconciliation_failed",
                error=error,
            )
    except BaseException as error:
        reconciliation_error = _cost_reconciliation_error_payload(
            status="unknown_requires_reconciliation",
            attempt_sha256=attempt_sha256,
            reason="cost_reconciliation_failed",
            error=error,
        )

    details: dict[str, Any] = {
        "provider_succeeded": True,
        "billable_attempt": True,
        "provider_attempt_count": 1,
        "provider_output_count": count,
        "estimated_image_output_usd": estimated_image_output_usd,
        "estimate_is_invoice_cap": False,
        "attempt_sha256": attempt_sha256,
        "cost_recording_status": status,
        "cost_log_recorded": cost_log_recorded,
        "unlogged_billable_attempt": unlogged_billable_attempt,
        "interrupted_exception_type": _safe_exception_type_name(interruption),
    }
    if cost_log is not None:
        details["cost_log"] = cost_log
    if reconciliation_error is not None:
        details["cost_log_error"] = reconciliation_error
    raise BananaError(
        "cost_recording_interrupted_after_provider",
        "The provider succeeded, but cost recording was interrupted. No output artifacts were published.",
        details=details,
    ) from interruption


def save_interaction(
    extracted: dict[str, Any],
    *,
    plan: dict[str, Any],
    prompt: str,
    destination: str | Path | None = None,
    label: str = "image",
    record_prompt: bool = False,
    publication_capability: OutputPublicationCapability | None = None,
) -> list[dict[str, Any]]:
    """Publish an interaction through a held or locally acquired capability."""
    _validated_plan_prompt(plan, prompt)
    for image in extracted["images"]:
        _, mime_type = decode_image(image)
        if mime_type != plan["output_mime_type"]:
            raise BananaError(
                "output_type_mismatch",
                "Provider image MIME type did not match the approved plan.",
            )
    owned_capability: OutputPublicationCapability | None = None
    capability = publication_capability
    if capability is None:
        directory = output_directory(destination or plan["output_directory"])
        owned_capability = _hold_output_directory(directory)
        capability = owned_capability
    try:
        return _save_interaction_with_capability(
            extracted,
            plan=plan,
            prompt=prompt,
            destination=destination,
            label=label,
            record_prompt=record_prompt,
            publication_capability=capability,
            validate_capability=publication_capability is not None,
        )
    finally:
        if owned_capability is not None:
            owned_capability.close()


def _save_interaction_with_capability(
    extracted: dict[str, Any],
    *,
    plan: dict[str, Any],
    prompt: str,
    destination: str | Path | None = None,
    label: str = "image",
    record_prompt: bool = False,
    publication_capability: OutputPublicationCapability,
    validate_capability: bool,
) -> list[dict[str, Any]]:
    clean_prompt = _validated_plan_prompt(plan, prompt)
    directory = (
        _validate_output_publication_capability(
            publication_capability,
            destination if destination is not None else plan["output_directory"],
        )
        if validate_capability
        else publication_capability.directory
    )
    safe_label = normalize_label(label)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    artifacts: list[dict[str, Any]] = []
    decoded_images: list[tuple[bytes, str]] = []
    publications: list[tuple[Path, bytes]] = []

    for image in extracted["images"]:
        raw, mime_type = decode_image(image)
        if mime_type != plan["output_mime_type"]:
            raise BananaError(
                "output_type_mismatch",
                "Provider image MIME type did not match the approved plan.",
            )
        decoded_images.append((raw, mime_type))

    catalog = load_catalog()
    for index, (raw, mime_type) in enumerate(decoded_images, start=1):
        extension = EXTENSION_BY_MIME[mime_type]
        suffix = f"_{index}" if len(decoded_images) > 1 else ""
        image_path = directory / f"banana_{timestamp}_{safe_label}{suffix}{extension}"
        width, height = image_dimensions(raw, mime_type)
        artifact = {
            "path": str(Path(os.path.abspath(image_path))),
            "mime_type": mime_type,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "width": width,
            "height": height,
        }
        metadata: dict[str, Any] = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "provider": catalog["provider"],
            "model": plan["model"],
            "operation": plan["operation"],
            "aspect_ratio": plan["aspect_ratio"],
            "image_size": plan["image_size"],
            "store": plan["store"],
            "prompt_sha256": plan["prompt_sha256"],
            "visual_brief_schema_version": VISUAL_BRIEF_SCHEMA_VERSION,
            "brief_sha256": plan["brief_sha256"],
            "brief_source": plan["brief_source"],
            "references": [
                {
                    "sha256": ref["sha256"],
                    "bytes": ref["bytes"],
                    "mime_type": ref["mime_type"],
                    "disclosure_alias": ref["disclosure_alias"],
                    "role": ref["role"],
                    "purpose": ref["purpose"],
                    "subject_id": ref["subject_id"],
                }
                for ref in plan["references"]
            ],
            "artifact": artifact,
            "usage": extracted.get("usage", {}),
            "grounding_used": bool(plan.get("web_search") or plan.get("image_search")),
            "provenance_notice": "Google documents SynthID on Gemini-generated images. Post-processing may alter provenance metadata.",
        }
        interaction_digest = _provider_identifier_digest(
            extracted.get("interaction_id")
        )
        if interaction_digest:
            metadata["interaction_id_sha256"] = interaction_digest
        previous_interaction_digest = _provider_identifier_digest(
            plan.get("previous_interaction_id")
        )
        if previous_interaction_digest:
            metadata["previous_interaction_id_sha256"] = previous_interaction_digest
        if record_prompt:
            metadata["prompt"] = clean_prompt
        sidecar_path = image_path.with_suffix(image_path.suffix + ".json")
        publications.append(
            (
                sidecar_path,
                (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode(
                    "utf-8"
                ),
            )
        )
        artifact["metadata_path"] = str(Path(os.path.abspath(sidecar_path)))
        artifacts.append(artifact)

    publications.extend(
        (
            Path(artifact["path"]),
            decoded_images[index][0],
        )
        for index, artifact in enumerate(artifacts)
    )

    directory_descriptor = publication_capability.descriptor
    published: list[tuple[Path, tuple[int, int]]] = []
    retained_members: list[_RetainedBundleMember] = []
    try:
        for path, payload in publications:
            identity = _atomic_write_at(
                directory_descriptor,
                path.name,
                payload,
                replace=False,
                expected_directory=directory,
            )
            published.append((path, identity))
            retained_members.append(
                _open_retained_bundle_member(
                    directory_descriptor,
                    path,
                    identity,
                    payload,
                )
            )

        if not _directory_path_matches_fd(directory, directory_descriptor):
            raise _bundle_drift_error()
        phase_a_receipts: list[_BundlePhaseAReceipt] = []
        for member in retained_members:
            try:
                receipt = _bundle_phase_a_receipt(
                    directory_descriptor,
                    member,
                )
            except OSError as exc:
                raise _bundle_drift_error() from exc
            if receipt is None:
                raise _bundle_drift_error()
            phase_a_receipts.append(receipt)
        if not _directory_path_matches_fd(directory, directory_descriptor):
            raise _bundle_drift_error()

        # Phase B is a bounded sequence of per-member validation points, not a
        # bundle-wide atomic snapshot or write lease. Success attests each
        # retained descriptor and public name only when that member is checked.
        # A same-UID or root writer, including one with a preopened writable fd,
        # can mutate an earlier member before later checks or before this call
        # returns.
        for member, phase_a in zip(retained_members, phase_a_receipts, strict=True):
            if not _directory_path_matches_fd(directory, directory_descriptor):
                raise _bundle_drift_error()
            try:
                current_identity = _bundle_artifact_identity(
                    member.path,
                    directory_descriptor,
                )
                receipt_matches = _bundle_phase_b_receipt_matches(
                    directory_descriptor,
                    member,
                    phase_a,
                )
            except (BananaError, OSError) as exc:
                raise _bundle_drift_error() from exc
            if current_identity != member.identity or not receipt_matches:
                raise _bundle_drift_error()
        if not _directory_path_matches_fd(directory, directory_descriptor):
            raise _bundle_drift_error()
    except BaseException as caught:
        failure: BaseException
        if isinstance(caught, OSError):
            failure = BananaError(
                "output_bundle_io_failed",
                "Artifact publication encountered an operating-system error.",
            )
        else:
            failure = caught

        retained = _bundle_recovery_artifacts(
            published,
            directory=directory,
            directory_descriptor=directory_descriptor,
        )
        retained.extend(_retained_artifacts_from_error(failure))
        unique_retained: list[dict[str, Any]] = []
        seen: set[tuple[object, object, object]] = set()
        for artifact in retained:
            key = (
                artifact.get("path"),
                artifact.get("device"),
                artifact.get("inode"),
            )
            if key not in seen:
                seen.add(key)
                unique_retained.append(artifact)

        if unique_retained:
            recovery_details: dict[str, Any] = {
                "publication_error_code": _root_publication_error_code(failure),
                "recovery_required": True,
                "retained_artifacts": unique_retained,
            }
            if isinstance(failure, BananaError) and failure.details:
                recovery_details["publication_recovery"] = dict(failure.details)
            raise BananaError(
                "output_bundle_retained",
                "The artifact bundle did not complete. Recovery did not delete publication paths, which require identity-based review.",
                details=recovery_details,
            ) from failure
        if failure is not caught:
            raise failure from caught
        raise
    finally:
        for member in retained_members:
            try:
                os.close(member.descriptor)
            except OSError:
                pass
    return artifacts


def execute_validated_plan(
    *,
    plan: dict[str, Any],
    prompt: str,
    api_key: str | None = None,
    opener: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    publication_capability: OutputPublicationCapability | None = None,
    attempt_sha256: str | None = None,
) -> dict[str, Any]:
    """Execute an already validated plan after its outer approval was consumed."""
    clean_prompt = _validated_plan_prompt(plan, prompt)
    surface = plan.get("api_surface")
    if surface not in {"interactions", "generate_content"}:
        raise BananaError(
            "api_surface_mismatch", "The approved plan has an unsupported API surface."
        )
    provider_attempt = attempt_sha256 or provider_attempt_sha256(
        request_fingerprint=plan["request_fingerprint"]
    )
    if not re.fullmatch(r"[0-9a-f]{64}", provider_attempt):
        raise BananaError(
            "invalid_provider_attempt_digest",
            "The provider attempt digest must be one full lowercase SHA-256 digest.",
        )
    owned_capability: OutputPublicationCapability | None = None
    capability = publication_capability
    if capability is None:
        owned_capability = acquire_output_publication(plan["output_directory"])
        capability = owned_capability
    else:
        _validate_output_publication_capability(
            capability,
            plan["output_directory"],
        )
    try:
        return _execute_validated_plan_with_capability(
            plan=plan,
            clean_prompt=clean_prompt,
            api_key=api_key,
            opener=opener,
            sleeper=sleeper,
            publication_capability=capability,
            attempt_sha256=provider_attempt,
        )
    finally:
        if owned_capability is not None:
            owned_capability.close()


def _execute_validated_plan_with_capability(
    *,
    plan: dict[str, Any],
    clean_prompt: str,
    api_key: str | None,
    opener: Callable[..., Any] | None,
    sleeper: Callable[[float], None],
    publication_capability: OutputPublicationCapability,
    attempt_sha256: str,
) -> dict[str, Any]:
    """Execute and publish while the caller retains the directory capability."""
    surface = plan["api_surface"]
    if surface == "interactions":
        payload = build_interaction_payload(clean_prompt, plan)
        response = call_interactions(
            payload,
            endpoint=plan["api_endpoint"],
            api_key=api_key,
            max_attempts=1,
            opener=opener,
            sleeper=sleeper,
        )
        try:
            extracted = extract_interaction(response)
        except BaseException as exc:
            raise _provider_response_processing_error(
                exc,
                attempt_sha256=attempt_sha256,
            ) from exc
    elif surface == "generate_content":
        payload = build_generate_content_payload(clean_prompt, plan)
        response = call_generate_content(
            payload,
            model=plan["model"],
            endpoint=plan["api_endpoint"],
            api_key=api_key,
            max_attempts=1,
            opener=opener,
            sleeper=sleeper,
        )
        try:
            extracted = extract_generate_content(response, model=plan["model"])
        except BaseException as exc:
            raise _provider_response_processing_error(
                exc,
                attempt_sha256=attempt_sha256,
            ) from exc
    publication_capability_error: BaseException | None = None
    try:
        _validate_output_publication_capability(
            publication_capability,
            plan["output_directory"],
        )
    except BaseException as exc:
        publication_capability_error = exc
    from cost_tracker import reconcile_generation_attempt, record_generation

    provider_output_count = len(extracted["images"])
    estimated_image_output_usd = round(
        float(plan["image_output_rate_usd"]) * provider_output_count,
        4,
    )
    batch = bool(plan.get("batch", False))
    provider_interaction_id = extracted.get("interaction_id")
    if not isinstance(provider_interaction_id, str):
        provider_interaction_id = None
    cost_log: dict[str, Any] | None = None
    cost_log_error: dict[str, Any] | None = None
    cost_recording_status = "unknown_requires_reconciliation"
    cost_log_recorded: bool | None = None
    unlogged_billable_attempt: bool | None = None
    try:
        cost_log = record_generation(
            model=plan["model"],
            resolution=plan["image_size"],
            count=provider_output_count,
            label=plan["label"],
            batch=batch,
            interaction_id=provider_interaction_id,
            attempt_sha256=attempt_sha256,
        )
        if (
            cost_log.get("status") != "recorded"
            or cost_log.get("logged") is not True
            or cost_log.get("attempt_sha256") != attempt_sha256
        ):
            raise BananaError(
                "cost_recording_unknown_requires_reconciliation",
                "The cost recorder returned an unverifiable outcome.",
                details={
                    "status": "unknown_requires_reconciliation",
                    "attempt_sha256": attempt_sha256,
                    "reason": "unexpected_cost_recorder_result",
                },
            )
        cost_recording_status = "recorded"
        cost_log_recorded = True
        unlogged_billable_attempt = False
    except BananaError as exc:
        if cost_log is not None:
            cost_log = None
        cost_log_error = exc.as_dict()
        observed_status = exc.details.get("status")
        if (
            exc.code == "cost_recording_not_recorded"
            and observed_status == "not_recorded"
        ):
            cost_recording_status = "not_recorded"
            cost_log_recorded = False
            unlogged_billable_attempt = True
        elif (
            exc.code == "cost_recording_unknown_requires_reconciliation"
            and observed_status == "unknown_requires_reconciliation"
        ):
            cost_recording_status = "unknown_requires_reconciliation"
    except Exception:
        cost_log_error = BananaError(
            "cost_recording_unknown_requires_reconciliation",
            "The provider succeeded, but cost recording requires reconciliation.",
            details={
                "status": "unknown_requires_reconciliation",
                "attempt_sha256": attempt_sha256,
            },
        ).as_dict()
    except BaseException as interruption:
        _raise_post_provider_cost_interrupt(
            interruption,
            reconcile_generation_attempt=reconcile_generation_attempt,
            model=plan["model"],
            resolution=plan["image_size"],
            count=provider_output_count,
            label=plan["label"],
            batch=batch,
            interaction_id=provider_interaction_id,
            attempt_sha256=attempt_sha256,
            estimated_image_output_usd=estimated_image_output_usd,
        )

    try:
        if publication_capability_error is not None:
            raise publication_capability_error
        artifacts = save_interaction(
            extracted,
            plan=plan,
            prompt=clean_prompt,
            destination=plan["output_directory"],
            label=plan["label"],
            record_prompt=plan["record_prompt"],
            publication_capability=publication_capability,
        )
    except BaseException as exc:
        if isinstance(exc, BananaError):
            code = exc.code
            message = exc.message
            retryable = exc.retryable
            http_status = exc.http_status
            details = dict(exc.details)
        else:
            code = "artifact_publication_failed_after_provider"
            message = (
                "The provider succeeded, but artifact publication failed unexpectedly."
            )
            retryable = False
            http_status = None
            details = {}
        details.update(
            {
                "provider_succeeded": True,
                "billable_attempt": True,
                "provider_attempt_count": 1,
                "provider_output_count": provider_output_count,
                "estimated_image_output_usd": estimated_image_output_usd,
                "estimate_is_invoice_cap": False,
                "attempt_sha256": attempt_sha256,
                "cost_recording_status": cost_recording_status,
                "cost_log_recorded": cost_log_recorded,
                "unlogged_billable_attempt": unlogged_billable_attempt,
            }
        )
        if cost_log is not None:
            details["cost_log"] = cost_log
        if cost_log_error is not None:
            details["cost_log_error"] = cost_log_error
        raise BananaError(
            code,
            message,
            retryable=retryable,
            http_status=http_status,
            details=details,
        ) from exc

    result = {
        "ok": True,
        "transport_ok": True,
        "visual_review_status": "needs_review",
        "plan": public_plan(plan),
        "artifacts": artifacts,
        "text": extracted.get("text", ""),
        "citations": extracted.get("citations", []),
        "search_suggestions": extracted.get("search_suggestions", []),
        "grounding_display_required": bool(
            plan.get("web_search") or plan.get("image_search")
        ),
        "usage": extracted.get("usage", {}),
        "image_contents": extracted["images"],
        "attempt_sha256": attempt_sha256,
        "cost_recording_status": cost_recording_status,
        "cost_log_recorded": cost_log_recorded,
        "unlogged_billable_attempt": unlogged_billable_attempt,
    }
    if plan.get("store") is True and extracted.get("interaction_id") is not None:
        result["interaction_id"] = extracted["interaction_id"]
    if cost_log is not None:
        result["cost_log"] = cost_log
    if cost_log_error is not None:
        result["cost_log_error"] = cost_log_error
    return result


def execute_image(
    *,
    operation: str,
    prompt: str,
    approval_id: str,
    model: str | None = None,
    aspect_ratio: str = "1:1",
    image_size: str | None = None,
    reference_paths: Iterable[str | Path | dict[str, Any]] = (),
    video_url: str | None = None,
    previous_interaction_id: str | None = None,
    thinking_level: str | None = None,
    web_search: bool = False,
    image_search: bool = False,
    store: bool = False,
    mime_type: str = "image/jpeg",
    destination: str | Path | None = None,
    label: str = "image",
    record_prompt: bool = False,
    visual_brief: dict[str, Any] | None = None,
    api_key: str | None = None,
    opener: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Consume one approval, make one provider attempt, and save the output."""
    plan = build_plan(
        operation=operation,
        prompt=prompt,
        model=model,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        reference_paths=reference_paths,
        video_url=video_url,
        previous_interaction_id=previous_interaction_id,
        thinking_level=thinking_level,
        web_search=web_search,
        image_search=image_search,
        store=store,
        mime_type=mime_type,
        destination=destination,
        label=label,
        record_prompt=record_prompt,
        visual_brief=visual_brief,
    )
    from approval_store import consume_approval

    publication_capability = acquire_output_publication(plan["output_directory"])
    try:
        attempt_sha256 = provider_attempt_sha256(
            request_fingerprint=plan["request_fingerprint"],
            approval_id=approval_id,
        )
        consume_approval(approval_id, plan["request_fingerprint"], kind="single")
        return execute_validated_plan(
            plan=plan,
            prompt=prompt,
            api_key=api_key,
            opener=opener,
            sleeper=sleeper,
            publication_capability=publication_capability,
            attempt_sha256=attempt_sha256,
        )
    finally:
        publication_capability.close()
