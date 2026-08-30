#!/usr/bin/env python3
"""Read-only installation and configuration checks for Banana Claude."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from banana_core import (
    CATALOG_PATH,
    BananaError,
    SecretSafeArgumentParser,
    load_catalog,
    output_directory,
)
from legacy_cleanup import CleanupError, inspect_state

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
MCP_CONFIG = PLUGIN_ROOT / ".mcp.json"
STANDALONE_MARKER = SKILL_DIR / ".banana-claude-install.json"
PLUGIN_USER_CONFIG_ENV = "CLAUDE_PLUGIN_OPTION_GOOGLE_AI_API_KEY"


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _nearest_existing_path(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def run_checks() -> list[dict[str, Any]]:
    plugin_mode = PLUGIN_MANIFEST.is_file() and MCP_CONFIG.is_file()
    standalone_mode = STANDALONE_MARKER.is_file()
    checks = [
        _check(
            "python_version",
            sys.version_info >= (3, 11),
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ),
        _check(
            "installation_layout",
            plugin_mode or standalone_mode,
            "plugin"
            if plugin_mode
            else "standalone"
            if standalone_mode
            else "unrecognized",
        ),
        _check(
            "plugin_manifest",
            PLUGIN_MANIFEST.is_file() or standalone_mode,
            str(PLUGIN_MANIFEST)
            if PLUGIN_MANIFEST.is_file()
            else "not applicable to standalone install",
        ),
        _check(
            "bundled_mcp_config",
            MCP_CONFIG.is_file() or standalone_mode,
            str(MCP_CONFIG)
            if MCP_CONFIG.is_file()
            else "not included in standalone install by design",
        ),
        _check("model_catalog", CATALOG_PATH.is_file(), str(CATALOG_PATH)),
    ]
    try:
        catalog = load_catalog()
        schema_ok = bool(catalog.get("models")) and set(
            catalog.get("api_profiles", {})
        ) == {
            "interactions",
            "generate_content",
        }
        checks.append(
            _check(
                "catalog_schema",
                schema_ok,
                f"{len(catalog.get('models', {}))} models, 2 API surfaces",
            )
        )
    except BananaError as exc:
        checks.append(_check("catalog_schema", False, exc.message))

    try:
        legacy = inspect_state()
        if legacy.clean:
            legacy_detail = "no recognized legacy MCP or skill residue"
        else:
            detected = []
            if legacy.settings.legacy_server_detected:
                detected.append("nanobanana-mcp")
            detected.extend(item.name for item in legacy.legacy_skills)
            legacy_detail = (
                "recognized legacy state: " + ", ".join(detected)
                if detected
                else f"legacy scan blocked: {legacy.settings.status}"
            )
        checks.append(_check("legacy_install_state", legacy.clean, legacy_detail))
    except CleanupError as exc:
        checks.append(
            _check(
                "legacy_install_state",
                False,
                f"legacy scan failed safely: {exc.code}",
            )
        )

    if plugin_mode:
        has_key = bool(os.environ.get(PLUGIN_USER_CONFIG_ENV, "").strip())
        key_detail = (
            "Claude plugin userConfig export is present"
            if has_key
            else "Claude plugin userConfig export is not present in this process"
        )
    else:
        has_key = bool(os.environ.get("GEMINI_API_KEY", "").strip())
        execution_mode = "standalone" if standalone_mode else "direct script"
        key_detail = (
            f"GEMINI_API_KEY is configured for {execution_mode} execution"
            if has_key
            else f"GEMINI_API_KEY is not present for {execution_mode} execution"
        )
    checks.append(
        _check(
            "api_key_available",
            has_key,
            key_detail,
        )
    )

    destination = output_directory()
    parent = _nearest_existing_path(destination)
    writable = parent.is_dir() and os.access(parent, os.W_OK | os.X_OK)
    checks.append(_check("output_parent_writable", writable, str(parent)))
    return checks


def build_parser() -> argparse.ArgumentParser:
    parser = SecretSafeArgumentParser(description="Read-only Banana Claude diagnostics")
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    checks = run_checks()
    passed = sum(1 for item in checks if item["passed"])
    result = {
        "passed": passed,
        "total": len(checks),
        "ready": passed == len(checks),
        "checks": checks,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("Banana Claude doctor")
        for item in checks:
            status = "PASS" if item["passed"] else "FAIL"
            print(f"[{status}] {item['name']}: {item['detail']}")
        print(f"Result: {passed}/{len(checks)} checks passed")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
