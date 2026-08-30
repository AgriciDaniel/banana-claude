from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests._support import run_python

import cost_tracker
from banana_core import BananaError, _atomic_write_at, _exclusive_rename_at
from cost_tracker import ledger_path, load_ledger

SECRET_PROMPTS = (
    "private launch concept alpha",
    "confidential portrait direction beta",
)


def legacy_ledger() -> dict[str, Any]:
    return {
        "total_cost": 0.078,
        "total_images": 2,
        "entries": [
            {
                "ts": "2026-08-20T10:11:12",
                "model": "gemini-3.1-flash-image-preview",
                "res": "1K",
                "cost": 0.039,
                "prompt": SECRET_PROMPTS[0],
            },
            {
                "ts": "2026-08-20T10:12:13",
                "model": "gemini-3.1-flash-image-preview",
                "res": "1K",
                "cost": 0.039,
                "prompt": SECRET_PROMPTS[1],
            },
        ],
        "daily": {"2026-08-20": {"count": 2, "cost": 0.078}},
    }


def write_legacy(home: Path, value: dict[str, Any] | None = None) -> bytes:
    raw = json.dumps(value if value is not None else legacy_ledger(), indent=2).encode(
        "utf-8"
    )
    home.mkdir(parents=True, exist_ok=True)
    (home / "costs.json").write_bytes(raw)
    return raw


def active_ledger() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "total_cost": 0.0336,
        "total_images": 1,
        "entries": [
            {
                "ts": "2026-08-20T10:11:12+00:00",
                "model": "gemini-3.1-flash-lite-image",
                "resolution": "1K",
                "count": 1,
                "estimated_image_output_usd": 0.0336,
                "image_output_rate_usd": 0.0336,
                "estimate_basis": "recorded_image_outputs",
                "estimate_is_invoice_cap": False,
                "batch": False,
                "label": "image generation",
            }
        ],
        "daily": {
            "2026-08-20": {
                "count": 1,
                "estimated_image_output_usd": 0.0336,
            }
        },
    }


def write_active(home: Path, value: dict[str, Any]) -> bytes:
    raw = json.dumps(value, indent=2).encode("utf-8")
    home.mkdir(parents=True, exist_ok=True)
    (home / "costs.json").write_bytes(raw)
    return raw


class CostMigrationTests(unittest.TestCase):
    def test_active_schema_normalizes_and_rewrites_raw_interaction_identifier(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            raw_identifier = "synthetic-legacy-interaction-id-never-echo"
            expected_digest = hashlib.sha256(raw_identifier.encode()).hexdigest()
            value = active_ledger()
            value["entries"][0]["interaction_id"] = raw_identifier
            original = write_active(Path(directory), value)

            normalized = load_ledger()
            normalized_entry = normalized["entries"][0]
            self.assertNotIn("interaction_id", normalized_entry)
            self.assertEqual(normalized_entry["interaction_id_sha256"], expected_digest)
            self.assertEqual((Path(directory) / "costs.json").read_bytes(), original)

            with self.assertRaises(BananaError) as saved:
                cost_tracker.save_ledger(value)
            self.assertEqual(saved.exception.code, "invalid_cost_ledger")
            self.assertEqual((Path(directory) / "costs.json").read_bytes(), original)

            result = run_python(
                "cost_tracker.py",
                "summary",
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(raw_identifier, result.stdout + result.stderr)
            rewritten = (Path(directory) / "costs.json").read_bytes()
            self.assertNotIn(raw_identifier.encode(), rewritten)
            self.assertIn(expected_digest.encode(), rewritten)

    def test_writer_rejects_unsafe_retained_text_before_creating_ledger(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            with self.assertRaises(BananaError) as unsafe_label:
                cost_tracker.record_generation(
                    model="gemini-3.1-flash-lite-image",
                    resolution="1K",
                    label="visible\nterminal",
                )
            self.assertEqual(unsafe_label.exception.code, "invalid_cost_label")

            with self.assertRaises(BananaError) as unsafe_id:
                cost_tracker.record_generation(
                    model="gemini-3.1-flash-lite-image",
                    resolution="1K",
                    interaction_id="response\u202eretained",
                )
            self.assertEqual(unsafe_id.exception.code, "invalid_interaction_id")
            self.assertFalse((Path(directory) / "costs.json").exists())

    def test_active_schema_is_closed_deep_and_reconciled(self) -> None:
        cases: dict[str, dict[str, Any]] = {}

        boolean_schema = active_ledger()
        boolean_schema["schema_version"] = True
        cases["boolean schema version"] = boolean_schema

        unknown_top_level = active_ledger()
        unknown_top_level["unknown"] = "field"
        cases["unknown top-level field"] = unknown_top_level

        unknown_entry = active_ledger()
        unknown_entry["entries"][0]["unknown"] = "field"
        cases["unknown entry field"] = unknown_entry

        missing_entry_field = active_ledger()
        del missing_entry_field["entries"][0]["batch"]
        cases["missing generated entry field"] = missing_entry_field

        boolean_entry_count = active_ledger()
        boolean_entry_count["entries"][0]["count"] = True
        cases["boolean entry count"] = boolean_entry_count

        invoice_cap_true = active_ledger()
        invoice_cap_true["entries"][0]["estimate_is_invoice_cap"] = True
        cases["invoice cap marker true"] = invoice_cap_true

        inconsistent_entry_rate = active_ledger()
        inconsistent_entry_rate["entries"][0]["image_output_rate_usd"] = 0.5
        cases["entry cost and rate mismatch"] = inconsistent_entry_rate

        inconsistent_total = active_ledger()
        inconsistent_total["total_cost"] = 99.0
        cases["inconsistent active total"] = inconsistent_total

        inconsistent_daily_count = active_ledger()
        inconsistent_daily_count["daily"]["2026-08-20"]["count"] = 2
        cases["inconsistent daily count"] = inconsistent_daily_count

        inconsistent_daily_day = active_ledger()
        inconsistent_daily_day["daily"] = {
            "2026-08-21": {"count": 1, "estimated_image_output_usd": 0.0336}
        }
        cases["inconsistent active day"] = inconsistent_daily_day

        legacy_daily_fallback = active_ledger()
        legacy_daily_fallback["daily"]["2026-08-20"] = {"count": 1, "cost": 0.0336}
        cases["obsolete daily cost field"] = legacy_daily_fallback

        unsafe_model = active_ledger()
        unsafe_model["entries"][0]["model"] = "model\u202eretained"
        cases["bidirectional model"] = unsafe_model

        unsafe_resolution = active_ledger()
        unsafe_resolution["entries"][0]["resolution"] = "1K\x1b"
        cases["terminal control resolution"] = unsafe_resolution

        unsafe_label = active_ledger()
        unsafe_label["entries"][0]["label"] = "line one\nline two"
        cases["multiline label"] = unsafe_label

        unsafe_basis = active_ledger()
        unsafe_basis["entries"][0]["estimate_basis"] = "recorded_image_outputs\u202e"
        cases["controlled estimate basis"] = unsafe_basis

        unsafe_identifier = active_ledger()
        unsafe_identifier["entries"][0]["interaction_id"] = "response-\ud800"
        cases["surrogate interaction identifier"] = unsafe_identifier

        oversized_identifier = active_ledger()
        oversized_identifier["entries"][0]["interaction_id"] = "x" * 513
        cases["oversized interaction identifier"] = oversized_identifier

        malformed_digest = active_ledger()
        malformed_digest["entries"][0]["interaction_id_sha256"] = "not-a-digest"
        cases["malformed interaction identifier digest"] = malformed_digest

        malformed_attempt_digest = active_ledger()
        malformed_attempt_digest["entries"][0]["attempt_sha256"] = "A" * 64
        cases["malformed cost attempt digest"] = malformed_attempt_digest

        ambiguous_identifier = active_ledger()
        ambiguous_identifier["entries"][0]["interaction_id"] = "response-safe-123"
        ambiguous_identifier["entries"][0]["interaction_id_sha256"] = "0" * 64
        cases["raw and digested interaction identifier"] = ambiguous_identifier

        for label, value in cases.items():
            with (
                self.subTest(label=label),
                tempfile.TemporaryDirectory() as directory,
                patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
            ):
                home = Path(directory)
                original = write_active(home, value)
                with self.assertRaises(BananaError) as loaded:
                    load_ledger()
                self.assertEqual(loaded.exception.code, "corrupt_cost_ledger")
                self.assertNotIn("retained", loaded.exception.message)
                self.assertNotIn("line one", loaded.exception.message)
                self.assertNotIn("response-", loaded.exception.message)

                with self.assertRaises(BananaError) as saved:
                    cost_tracker.save_ledger(value)
                self.assertEqual(saved.exception.code, "invalid_cost_ledger")
                self.assertEqual((home / "costs.json").read_bytes(), original)

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "O_NOFOLLOW is unavailable")
    def test_cost_lock_refuses_symlink_without_touching_target(self) -> None:
        for target_exists in (True, False):
            with (
                self.subTest(target_exists=target_exists),
                tempfile.TemporaryDirectory() as directory,
                patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
            ):
                home = Path(directory)
                target = home / "outside-lock-target"
                if target_exists:
                    target.write_bytes(b"sentinel")
                lock = home / "costs.lock"
                lock.symlink_to(target)

                with self.assertRaises(BananaError) as caught:
                    with cost_tracker.ledger_lock():
                        self.fail("symlink lock unexpectedly opened")

                self.assertEqual(caught.exception.code, "unsafe_cost_lock")
                self.assertTrue(lock.is_symlink())
                if target_exists:
                    self.assertEqual(target.read_bytes(), b"sentinel")
                else:
                    self.assertFalse(target.exists())

    @unittest.skipIf(os.name == "nt", "directory symlink setup requires POSIX")
    def test_dry_run_rejects_symlinked_state_root_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            original = write_legacy(outside)
            outside.chmod(0o755)
            state = root / "state"
            state.symlink_to(outside, target_is_directory=True)

            result = run_python(
                "cost_tracker.py",
                "migrate-v1",
                "--dry-run",
                env={"BANANA_HOME": str(state)},
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("unsafe_cost_state_directory", result.stderr)
            self.assertTrue(state.is_symlink())
            self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o755)
            self.assertEqual((outside / "costs.json").read_bytes(), original)
            self.assertEqual(
                sorted(path.name for path in outside.iterdir()), ["costs.json"]
            )

    def test_dry_run_is_read_only_deterministic_and_redacts_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            original = write_legacy(home)

            first = run_python(
                "cost_tracker.py",
                "migrate-v1",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )
            second = run_python(
                "cost_tracker.py",
                "migrate-v1",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            proposal = json.loads(first.stdout)
            repeated = json.loads(second.stdout)
            self.assertTrue(proposal["dry_run"])
            self.assertFalse(proposal["will_write"])
            self.assertFalse(proposal["network_called"])
            self.assertEqual(
                proposal["migration_fingerprint"], repeated["migration_fingerprint"]
            )
            self.assertEqual(len(proposal["migration_fingerprint"]), 64)
            self.assertEqual(proposal["summary"]["legacy_prompt_fields_redacted"], 2)
            self.assertEqual(proposal["proposed_ledger"]["schema_version"], 1)
            self.assertEqual(proposal["proposed_ledger"]["total_cost"], 0.078)
            for entry in proposal["proposed_ledger"]["entries"]:
                self.assertNotIn("prompt", entry)
                self.assertTrue(entry["legacy_prompt_redacted"])
            for secret in SECRET_PROMPTS:
                self.assertNotIn(secret, first.stdout)
                self.assertNotIn(secret, first.stderr)
            self.assertEqual((home / "costs.json").read_bytes(), original)
            self.assertFalse((home / "costs.lock").exists())
            self.assertFalse((home / "backups").exists())

            summary = run_python(
                "cost_tracker.py",
                "summary",
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(summary.returncode, 1)
            self.assertIn("corrupt_cost_ledger", summary.stderr)
            self.assertEqual((home / "costs.json").read_bytes(), original)

    def test_confirmation_is_bound_to_current_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            original = write_legacy(home)
            reviewed = run_python(
                "cost_tracker.py",
                "migrate-v1",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
            fingerprint = json.loads(reviewed.stdout)["migration_fingerprint"]
            changed = original + b"\n"
            (home / "costs.json").write_bytes(changed)

            rejected = run_python(
                "cost_tracker.py",
                "migrate-v1",
                "--confirm",
                fingerprint,
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("migration_confirmation_mismatch", rejected.stderr)
            self.assertEqual((home / "costs.json").read_bytes(), changed)
            self.assertFalse((home / "backups").exists())

    def test_confirmed_migration_preserves_meaning_and_writes_private_exact_backup(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {"BANANA_HOME": directory},
                clear=False,
            ),
        ):
            home = Path(directory)
            original = write_legacy(home)
            reviewed = run_python(
                "cost_tracker.py",
                "migrate-v1",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
            fingerprint = json.loads(reviewed.stdout)["migration_fingerprint"]

            migrated = run_python(
                "cost_tracker.py",
                "migrate-v1",
                "--confirm",
                fingerprint,
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            result = json.loads(migrated.stdout)
            self.assertTrue(result["migrated"])
            self.assertFalse(result["network_called"])
            self.assertEqual(result["migration_fingerprint"], fingerprint)

            backup = Path(result["backup"]["path"])
            self.assertEqual(backup.parent, home / "backups")
            self.assertEqual(backup.read_bytes(), original)
            self.assertEqual(stat.S_IMODE(backup.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((home / "costs.lock").stat().st_mode), 0o600)

            ledger = load_ledger()
            self.assertEqual(ledger["schema_version"], 1)
            self.assertEqual(ledger["total_images"], 2)
            self.assertEqual(ledger["total_cost"], 0.078)
            self.assertEqual(
                ledger["daily"],
                {"2026-08-20": {"count": 2, "estimated_image_output_usd": 0.078}},
            )
            self.assertEqual(len(ledger["entries"]), 2)
            for entry in ledger["entries"]:
                self.assertNotIn("prompt", entry)
                self.assertTrue(entry["legacy_prompt_redacted"])
            active = (home / "costs.json").read_text(encoding="utf-8")
            for secret in SECRET_PROMPTS:
                self.assertNotIn(secret, active)

            summary = run_python(
                "cost_tracker.py",
                "summary",
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)
            self.assertIn("Total images: 2", summary.stdout)
            logged = run_python(
                "cost_tracker.py",
                "log",
                "--model",
                "gemini-3.1-flash-lite-image",
                "--resolution",
                "1K",
                "--label",
                "post-migration check",
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(logged.returncode, 0, logged.stderr)
            self.assertEqual(json.loads(logged.stdout)["total_images"], 3)
            self.assertEqual(load_ledger()["total_images"], 3)

    def test_malformed_or_inconsistent_legacy_ledgers_fail_closed(self) -> None:
        cases: dict[str, dict[str, Any]] = {}
        extra_field = legacy_ledger()
        extra_field["unexpected"] = True
        cases["extra top-level field"] = extra_field

        boolean_count = legacy_ledger()
        boolean_count["total_images"] = True
        cases["boolean total_images"] = boolean_count

        missing_entry_field = legacy_ledger()
        del missing_entry_field["entries"][0]["prompt"]
        cases["missing entry field"] = missing_entry_field

        nonfinite_cost = legacy_ledger()
        nonfinite_cost["entries"][0]["cost"] = float("inf")
        cases["nonfinite cost"] = nonfinite_cost

        inconsistent_total = legacy_ledger()
        inconsistent_total["total_cost"] = 99.0
        cases["inconsistent total"] = inconsistent_total

        inconsistent_daily_bucket = legacy_ledger()
        inconsistent_daily_bucket["daily"] = {"2026-08-21": {"count": 2, "cost": 0.078}}
        cases["daily bucket does not match entries"] = inconsistent_daily_bucket

        unsafe_retained_model = legacy_ledger()
        unsafe_retained_model["entries"][0]["model"] = "legacy\u202eretained"
        cases["unsafe retained model"] = unsafe_retained_model

        invalid_daily_key = legacy_ledger()
        invalid_daily_key["daily"] = {
            "do-not-print-this-private-value": {"count": 2, "cost": 0.078}
        }
        cases["invalid daily key"] = invalid_daily_key

        for label, value in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                original = write_legacy(home, value)
                result = run_python(
                    "cost_tracker.py",
                    "migrate-v1",
                    "--dry-run",
                    env={"BANANA_HOME": directory},
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("invalid_legacy_cost_ledger", result.stderr)
                self.assertNotIn("do-not-print-this-private-value", result.stderr)
                for secret in SECRET_PROMPTS:
                    self.assertNotIn(secret, result.stderr)
                self.assertEqual((home / "costs.json").read_bytes(), original)
                self.assertFalse((home / "costs.lock").exists())
                self.assertFalse((home / "backups").exists())

    def test_normal_load_enforces_bounded_reads(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {"BANANA_HOME": directory},
                clear=False,
            ),
            patch.object(cost_tracker, "MAX_LEDGER_BYTES", 32),
        ):
            path = ledger_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"{" + b" " * 32)
            with self.assertRaises(BananaError) as caught:
                load_ledger()
            self.assertEqual(caught.exception.code, "corrupt_cost_ledger")

    def test_concurrent_confirmations_do_not_overwrite_migrated_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            original = write_legacy(home)
            reviewed = run_python(
                "cost_tracker.py",
                "migrate-v1",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
            fingerprint = json.loads(reviewed.stdout)["migration_fingerprint"]

            def confirm(_index: int) -> tuple[int, str, str]:
                result = run_python(
                    "cost_tracker.py",
                    "migrate-v1",
                    "--confirm",
                    fingerprint,
                    env={"BANANA_HOME": directory},
                )
                return result.returncode, result.stdout, result.stderr

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(confirm, range(2)))

            self.assertEqual(sorted(code for code, _stdout, _stderr in results), [0, 1])
            self.assertEqual(len(list((home / "backups").glob("costs.v1-*.json"))), 1)
            self.assertEqual(
                next((home / "backups").glob("costs.v1-*.json")).read_bytes(), original
            )
            with patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False):
                ledger = load_ledger()
            self.assertEqual(ledger["schema_version"], 1)
            self.assertEqual(ledger["total_images"], 2)
            self.assertEqual(len(ledger["entries"]), 2)

    def test_write_after_confirmation_reread_is_preserved(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            path = home / "costs.json"
            original = write_legacy(home)
            proposal = cost_tracker._migration_proposal(original, path)
            fingerprint = proposal["migration_fingerprint"]
            competing = b'{"legacy_writer":"new bytes"}\n'
            original_publish = _atomic_write_at

            def recreate_then_publish(
                directory_descriptor: int,
                name: str,
                data: bytes,
                *,
                replace: bool = True,
                expected_directory: Path | None = None,
            ) -> None:
                competing_descriptor = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_descriptor,
                )
                with os.fdopen(competing_descriptor, "wb") as handle:
                    handle.write(competing)
                    handle.flush()
                    os.fsync(handle.fileno())
                original_publish(
                    directory_descriptor,
                    name,
                    data,
                    replace=replace,
                    expected_directory=expected_directory,
                )

            args = cost_tracker.build_parser().parse_args(
                ["migrate-v1", "--confirm", fingerprint]
            )
            with patch(
                "cost_tracker._atomic_write_at",
                side_effect=recreate_then_publish,
            ):
                with self.assertRaises(BananaError) as caught:
                    cost_tracker.cmd_migrate_v1(args)

            self.assertEqual(caught.exception.code, "migration_source_changed")
            self.assertEqual(path.read_bytes(), competing)
            backups = list((home / "backups").glob("costs.v1-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertFalse(caught.exception.details["migration_cleanup_complete"])
            self.assertFalse(
                caught.exception.details["migration_automatic_restore_attempted"]
            )
            intended = caught.exception.details["intended_legacy_ledger"]
            self.assertTrue(intended["path_binding_verified"])
            self.assertEqual(Path(intended["path"]), backups[0])
            observed_active = caught.exception.details["observed_active_entry"]
            self.assertEqual(Path(observed_active["path"]), path)

    @unittest.skipUnless(
        sys.platform.startswith("linux") or sys.platform == "darwin",
        "atomic exclusive dirfd rename is supported on Linux and macOS",
    )
    def test_backup_claim_source_substitution_is_retained_and_reported(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            path = home / "costs.json"
            original = write_legacy(home)
            proposal = cost_tracker._migration_proposal(original, path)
            fingerprint = proposal["migration_fingerprint"]
            held_original = home / "held-original.json"
            foreign = b'{"foreign":"replacement"}\n'
            real_rename = _exclusive_rename_at
            substituted = False

            def substitute_then_claim(
                source_directory: int,
                source_name: str,
                destination_directory: int,
                destination_name: str,
            ) -> None:
                nonlocal substituted
                if not substituted and source_name == "costs.json":
                    os.rename(
                        source_name,
                        held_original.name,
                        src_dir_fd=source_directory,
                        dst_dir_fd=source_directory,
                    )
                    descriptor = os.open(
                        source_name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=source_directory,
                    )
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(foreign)
                    substituted = True
                real_rename(
                    source_directory,
                    source_name,
                    destination_directory,
                    destination_name,
                )

            args = cost_tracker.build_parser().parse_args(
                ["migrate-v1", "--confirm", fingerprint]
            )
            with patch(
                "cost_tracker._exclusive_rename_at",
                side_effect=substitute_then_claim,
            ):
                with self.assertRaises(BananaError) as caught:
                    cost_tracker.cmd_migrate_v1(args)

            self.assertTrue(substituted)
            self.assertEqual(caught.exception.code, "migration_source_changed")
            self.assertEqual(held_original.read_bytes(), original)
            self.assertFalse(path.exists())
            intended = caught.exception.details["intended_legacy_ledger"]
            self.assertFalse(intended["path_binding_verified"])
            self.assertTrue(intended["path_unknown"])
            observed_backup = caught.exception.details["observed_backup_entry"]
            self.assertTrue(observed_backup["path_binding_verified"])
            self.assertEqual(Path(observed_backup["path"]).read_bytes(), foreign)
            retained = caught.exception.details["intended_recovery"]
            self.assertTrue(retained["retained"])
            self.assertTrue(
                any(
                    entry["exact_reviewed_bytes"]
                    and Path(entry["path"]).read_bytes() == original
                    for entry in retained["recovery_entries"]
                    if entry.get("path")
                )
            )

    @unittest.skipUnless(
        sys.platform.startswith("linux") or sys.platform == "darwin",
        "atomic exclusive dirfd rename is supported on Linux and macOS",
    )
    def test_unlinked_substituted_cost_source_is_copied_to_recovery(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            path = home / "costs.json"
            original = write_legacy(home)
            proposal = cost_tracker._migration_proposal(original, path)
            fingerprint = proposal["migration_fingerprint"]
            foreign = b'{"foreign":"replacement"}\n'
            real_rename = _exclusive_rename_at
            substituted = False

            def replace_then_claim(
                source_directory: int,
                source_name: str,
                destination_directory: int,
                destination_name: str,
            ) -> None:
                nonlocal substituted
                if not substituted and source_name == "costs.json":
                    replacement = home / "foreign-costs.json"
                    replacement.write_bytes(foreign)
                    replacement.chmod(0o600)
                    os.replace(replacement, path)
                    substituted = True
                real_rename(
                    source_directory,
                    source_name,
                    destination_directory,
                    destination_name,
                )

            args = cost_tracker.build_parser().parse_args(
                ["migrate-v1", "--confirm", fingerprint]
            )
            with patch(
                "cost_tracker._exclusive_rename_at",
                side_effect=replace_then_claim,
            ):
                with self.assertRaises(BananaError) as caught:
                    cost_tracker.cmd_migrate_v1(args)

            self.assertEqual(caught.exception.code, "migration_source_changed")
            self.assertFalse(path.exists())
            observed = caught.exception.details["observed_backup_entry"]
            self.assertEqual(Path(observed["path"]).read_bytes(), foreign)
            retained = caught.exception.details["intended_recovery"]
            self.assertTrue(retained["retained"])
            exact_paths = [
                Path(entry["path"])
                for entry in retained["recovery_entries"]
                if entry.get("path") and entry.get("exact_reviewed_bytes") is True
            ]
            self.assertTrue(exact_paths)
            self.assertTrue(
                any(candidate.read_bytes() == original for candidate in exact_paths)
            )

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative directory operations",
    )
    def test_source_parent_swap_never_writes_redirect_and_preserves_source(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ, {"BANANA_HOME": str(Path(directory) / "home")}, clear=False
            ),
        ):
            root = Path(directory)
            home = root / "home"
            original = write_legacy(home)
            proposal = cost_tracker._migration_proposal(original, home / "costs.json")
            fingerprint = proposal["migration_fingerprint"]
            moved_home = root / "held-home"
            original_rename = _exclusive_rename_at
            swapped = False

            def swap_source_parent(
                source_directory: int,
                source_name: str,
                destination_directory: int,
                destination_name: str,
            ) -> None:
                nonlocal swapped
                if not swapped and source_name == "costs.json":
                    os.rename(home, moved_home)
                    home.mkdir(mode=0o700)
                    swapped = True
                original_rename(
                    source_directory,
                    source_name,
                    destination_directory,
                    destination_name,
                )

            args = cost_tracker.build_parser().parse_args(
                ["migrate-v1", "--confirm", fingerprint]
            )
            with patch(
                "cost_tracker._exclusive_rename_at",
                side_effect=swap_source_parent,
            ):
                with self.assertRaises(BananaError) as caught:
                    cost_tracker.cmd_migrate_v1(args)

            self.assertTrue(swapped)
            self.assertEqual(
                caught.exception.code, "migration_source_directory_changed"
            )
            self.assertEqual(list(home.iterdir()), [])
            recovery = caught.exception.details["intended_legacy_ledger"]
            self.assertTrue(recovery["path_unknown"])
            self.assertEqual(
                next((moved_home / "backups").glob("costs.v1-*.json")).read_bytes(),
                original,
            )

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative directory operations",
    )
    def test_backup_parent_swap_never_writes_redirect_and_retains_source(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            original = write_legacy(home)
            proposal = cost_tracker._migration_proposal(original, home / "costs.json")
            fingerprint = proposal["migration_fingerprint"]
            backup_directory = home / "backups"
            moved_backup = home / "held-backups"
            original_rename = _exclusive_rename_at
            swapped = False

            def swap_backup_parent(
                source_directory: int,
                source_name: str,
                destination_directory: int,
                destination_name: str,
            ) -> None:
                nonlocal swapped
                if not swapped and source_name == "costs.json":
                    os.rename(backup_directory, moved_backup)
                    backup_directory.mkdir(mode=0o700)
                    swapped = True
                original_rename(
                    source_directory,
                    source_name,
                    destination_directory,
                    destination_name,
                )

            args = cost_tracker.build_parser().parse_args(
                ["migrate-v1", "--confirm", fingerprint]
            )
            with patch(
                "cost_tracker._exclusive_rename_at",
                side_effect=swap_backup_parent,
            ):
                with self.assertRaises(BananaError) as caught:
                    cost_tracker.cmd_migrate_v1(args)

            self.assertTrue(swapped)
            self.assertEqual(
                caught.exception.code, "migration_backup_directory_changed"
            )
            self.assertFalse((home / "costs.json").exists())
            self.assertEqual(list(backup_directory.iterdir()), [])
            retained = next(moved_backup.glob("costs.v1-*.json"))
            self.assertEqual(retained.read_bytes(), original)
            recovery = caught.exception.details["intended_legacy_ledger"]
            self.assertTrue(recovery["path_unknown"])

    @unittest.skipUnless(os.name != "nt", "requires POSIX hard links")
    def test_hard_linked_source_is_rejected_before_claim_or_chmod(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            original = write_legacy(home)
            source = home / "costs.json"
            alias = home / "costs-alias.json"
            os.link(source, alias)
            original_mode = stat.S_IMODE(source.stat().st_mode)
            reviewed = run_python(
                "cost_tracker.py",
                "migrate-v1",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )
            fingerprint = json.loads(reviewed.stdout)["migration_fingerprint"]

            confirmed = run_python(
                "cost_tracker.py",
                "migrate-v1",
                "--confirm",
                fingerprint,
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(confirmed.returncode, 1)
            self.assertIn("unsafe_legacy_cost_ledger", confirmed.stderr)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(alias.read_bytes(), original)
            self.assertEqual(source.stat().st_nlink, 2)
            self.assertEqual(stat.S_IMODE(source.stat().st_mode), original_mode)
            self.assertFalse((home / "backups").exists())

    def test_migrate_v1_requires_exactly_one_review_or_confirmation_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            write_legacy(Path(directory))
            missing = run_python(
                "cost_tracker.py",
                "migrate-v1",
                env={"BANANA_HOME": directory},
            )
            both = run_python(
                "cost_tracker.py",
                "migrate-v1",
                "--dry-run",
                "--confirm",
                "not-a-fingerprint",
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(missing.returncode, 2)
            self.assertEqual(both.returncode, 2)

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative directory operations",
    )
    def test_interrupt_after_successful_claim_restores_exact_active_ledger(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            original = write_legacy(home)
            path = home / "costs.json"
            proposal = cost_tracker._migration_proposal(original, path)
            fingerprint = proposal["migration_fingerprint"]
            interrupted = False

            def rename_then_interrupt(
                source_directory: int,
                source_name: str,
                destination_directory: int,
                destination_name: str,
            ) -> None:
                nonlocal interrupted
                _exclusive_rename_at(
                    source_directory,
                    source_name,
                    destination_directory,
                    destination_name,
                )
                if not interrupted:
                    interrupted = True
                    raise KeyboardInterrupt("interrupt after successful ledger claim")

            args = cost_tracker.build_parser().parse_args(
                ["migrate-v1", "--confirm", fingerprint]
            )
            with patch(
                "cost_tracker._exclusive_rename_at",
                side_effect=rename_then_interrupt,
            ):
                with self.assertRaisesRegex(
                    KeyboardInterrupt,
                    "interrupt after successful ledger claim",
                ):
                    cost_tracker.cmd_migrate_v1(args)

            self.assertTrue(interrupted)
            self.assertEqual(path.read_bytes(), original)
            backups = list((home / "backups").glob("costs.v1-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            active_metadata = path.stat()
            backup_metadata = backups[0].stat()
            self.assertNotEqual(
                (active_metadata.st_dev, active_metadata.st_ino),
                (backup_metadata.st_dev, backup_metadata.st_ino),
            )
            self.assertEqual(active_metadata.st_nlink, 1)
            self.assertEqual(backup_metadata.st_nlink, 1)
            self.assertEqual(stat.S_IMODE(active_metadata.st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(backup_metadata.st_mode), 0o600)

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "requires descriptor-bound no-overwrite recovery",
    )
    def test_baseexception_after_claim_reread_restores_exact_active_ledger(
        self,
    ) -> None:
        for exception_type in (KeyboardInterrupt, SystemExit):
            with (
                self.subTest(exception_type=exception_type.__name__),
                tempfile.TemporaryDirectory() as directory,
                patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
            ):
                home = Path(directory)
                original = write_legacy(home)
                path = home / "costs.json"
                proposal = cost_tracker._migration_proposal(original, path)
                fingerprint = proposal["migration_fingerprint"]
                original_read = cost_tracker._bounded_descriptor_read
                reads = 0

                def interrupt_post_claim(
                    descriptor: int,
                    *,
                    limit: int,
                    error_code: str,
                    message: str,
                ) -> bytes:
                    nonlocal reads
                    reads += 1
                    if reads == 3:
                        raise exception_type("interrupt after claim reread")
                    return original_read(
                        descriptor,
                        limit=limit,
                        error_code=error_code,
                        message=message,
                    )

                args = cost_tracker.build_parser().parse_args(
                    ["migrate-v1", "--confirm", fingerprint]
                )
                with patch(
                    "cost_tracker._bounded_descriptor_read",
                    side_effect=interrupt_post_claim,
                ):
                    with self.assertRaises(exception_type) as caught:
                        cost_tracker.cmd_migrate_v1(args)

                self.assertEqual(
                    caught.exception.args, ("interrupt after claim reread",)
                )
                self.assertEqual(reads, 3)
                self.assertEqual(path.read_bytes(), original)
                backups = list((home / "backups").glob("costs.v1-*.json"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_bytes(), original)
                active_metadata = path.stat()
                backup_metadata = backups[0].stat()
                self.assertNotEqual(
                    (active_metadata.st_dev, active_metadata.st_ino),
                    (backup_metadata.st_dev, backup_metadata.st_ino),
                )
                self.assertEqual(active_metadata.st_nlink, 1)
                self.assertEqual(backup_metadata.st_nlink, 1)
                self.assertEqual(stat.S_IMODE(active_metadata.st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(backup_metadata.st_mode), 0o600)

                with patch("builtins.print"):
                    cost_tracker.cmd_migrate_v1(args)
                self.assertEqual(load_ledger(), proposal["proposed_ledger"])
                self.assertEqual(backups[0].read_bytes(), original)

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "requires descriptor-bound no-overwrite recovery",
    )
    def test_interrupt_after_active_publication_keeps_exact_migrated_ledger(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            original = write_legacy(home)
            path = home / "costs.json"
            proposal = cost_tracker._migration_proposal(original, path)
            fingerprint = proposal["migration_fingerprint"]
            expected_active = cost_tracker._active_ledger_bytes(
                proposal["proposed_ledger"]
            )
            original_read = cost_tracker._bounded_descriptor_read
            reads = 0

            def interrupt_active_verification(
                descriptor: int,
                *,
                limit: int,
                error_code: str,
                message: str,
            ) -> bytes:
                nonlocal reads
                reads += 1
                if reads == 4:
                    raise KeyboardInterrupt("interrupt after active publication")
                return original_read(
                    descriptor,
                    limit=limit,
                    error_code=error_code,
                    message=message,
                )

            args = cost_tracker.build_parser().parse_args(
                ["migrate-v1", "--confirm", fingerprint]
            )
            with patch(
                "cost_tracker._bounded_descriptor_read",
                side_effect=interrupt_active_verification,
            ):
                with self.assertRaisesRegex(
                    KeyboardInterrupt,
                    "interrupt after active publication",
                ):
                    cost_tracker.cmd_migrate_v1(args)

            self.assertEqual(reads, 4)
            self.assertEqual(path.read_bytes(), expected_active)
            self.assertEqual(load_ledger(), proposal["proposed_ledger"])
            backups = list((home / "backups").glob("costs.v1-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertNotEqual(path.stat().st_ino, backups[0].stat().st_ino)

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "requires descriptor-bound no-overwrite recovery",
    )
    def test_interrupt_recovery_never_overwrites_competing_active_ledger(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            original = write_legacy(home)
            path = home / "costs.json"
            proposal = cost_tracker._migration_proposal(original, path)
            fingerprint = proposal["migration_fingerprint"]
            competing = b'{"competing":"active ledger"}\n'
            original_read = cost_tracker._bounded_descriptor_read
            original_publish = _atomic_write_at
            reads = 0

            def race_then_interrupt(
                descriptor: int,
                *,
                limit: int,
                error_code: str,
                message: str,
            ) -> bytes:
                nonlocal reads
                reads += 1
                if reads == 3:
                    raise KeyboardInterrupt("interrupt with active racer")
                return original_read(
                    descriptor,
                    limit=limit,
                    error_code=error_code,
                    message=message,
                )

            def race_recovery_publication(
                directory_descriptor: int,
                name: str,
                data: bytes,
                *,
                replace: bool = True,
                expected_directory: Path | None = None,
            ) -> None:
                descriptor = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_descriptor,
                )
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(competing)
                    handle.flush()
                    os.fsync(handle.fileno())
                original_publish(
                    directory_descriptor,
                    name,
                    data,
                    replace=replace,
                    expected_directory=expected_directory,
                )

            args = cost_tracker.build_parser().parse_args(
                ["migrate-v1", "--confirm", fingerprint]
            )
            with (
                patch(
                    "cost_tracker._bounded_descriptor_read",
                    side_effect=race_then_interrupt,
                ),
                patch(
                    "cost_tracker._atomic_write_at",
                    side_effect=race_recovery_publication,
                ),
            ):
                with self.assertRaises(BananaError) as caught:
                    cost_tracker.cmd_migrate_v1(args)

            self.assertEqual(caught.exception.code, "migration_recovery_failed")
            self.assertEqual(
                caught.exception.details["interrupted_exception_type"],
                "KeyboardInterrupt",
            )
            recovery = caught.exception.details["migration_recovery"]
            self.assertFalse(recovery["migration_state_safe"])
            self.assertEqual(
                recovery["cleanup_status"],
                "active_entry_present_no_overwrite",
            )
            self.assertEqual(path.read_bytes(), competing)
            backups = list((home / "backups").glob("costs.v1-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)

    def test_absent_active_ledger_with_migration_backup_fails_closed(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            original = write_legacy(home)
            backup_directory = home / "backups"
            backup_directory.mkdir(mode=0o700)
            backup = backup_directory / (
                "costs.v1-20260829T123456123456Z-0123456789ab-0123456789abcdef.json"
            )
            (home / "costs.json").rename(backup)
            backup.chmod(0o600)

            with self.assertRaises(BananaError) as caught:
                load_ledger()

            self.assertEqual(
                caught.exception.code,
                "cost_migration_recovery_required",
            )
            details = caught.exception.details
            self.assertTrue(details["recovery_required"])
            self.assertFalse(details["active_ledger_present"])
            self.assertFalse(details["automatic_restore_attempted"])
            self.assertTrue(details["backup_directory_path_binding_verified"])
            observed = details["observed_backup"]
            self.assertTrue(observed["regular_file"])
            self.assertEqual(
                (observed["device"], observed["inode"]),
                (backup.stat().st_dev, backup.stat().st_ino),
            )
            self.assertEqual(backup.read_bytes(), original)
            self.assertFalse((home / "costs.json").exists())

    def test_unrelated_backup_name_does_not_infer_migration_residue(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            backup_directory = home / "backups"
            backup_directory.mkdir(mode=0o700)
            unrelated = backup_directory / "costs-manual-note.json"
            unrelated.write_text('{"note":"not migration residue"}\n')

            self.assertEqual(load_ledger(), cost_tracker.empty_ledger())
            self.assertTrue(unrelated.exists())

    def test_explicit_empty_active_ledger_takes_precedence_over_old_backup(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            original = write_legacy(home)
            backup_directory = home / "backups"
            backup_directory.mkdir(mode=0o700)
            backup = backup_directory / (
                "costs.v1-20260829T123456123456Z-0123456789ab-0123456789abcdef.json"
            )
            (home / "costs.json").rename(backup)
            (home / "costs.json").write_bytes(
                cost_tracker._active_ledger_bytes(cost_tracker.empty_ledger())
            )
            (home / "costs.json").chmod(0o600)

            self.assertEqual(load_ledger(), cost_tracker.empty_ledger())
            self.assertEqual(backup.read_bytes(), original)

    def test_reconcile_generation_attempt_returns_one_exact_recorded_entry(
        self,
    ) -> None:
        attempt = hashlib.sha256(b"read-only-exact-reconciliation").hexdigest()
        interaction_id = "provider-interaction-for-exact-reconciliation"
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            cost_tracker.record_generation(
                model="gemini-3.1-flash-lite-image",
                resolution="1K",
                count=2,
                label="reconciled generation",
                batch=True,
                interaction_id=interaction_id,
                attempt_sha256=attempt,
            )
            path = ledger_path()
            before = path.read_bytes()

            result = cost_tracker.reconcile_generation_attempt(
                model="gemini-3.1-flash-lite-image",
                resolution="1K",
                count=2,
                label="reconciled generation",
                batch=True,
                interaction_id=interaction_id,
                attempt_sha256=attempt,
            )

            self.assertEqual(result["status"], "recorded")
            self.assertTrue(result["logged"])
            self.assertTrue(result["idempotent_replay"])
            self.assertFalse(result["reconciled_after_save_error"])
            self.assertEqual(result["attempt_sha256"], attempt)
            self.assertNotIn("interaction_id_sha256", result["entry"])
            self.assertEqual(path.read_bytes(), before)

    def test_reconcile_generation_attempt_absent_is_read_only(self) -> None:
        attempt = hashlib.sha256(b"conclusively-absent-reconciliation").hexdigest()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            with self.assertRaises(BananaError) as caught:
                cost_tracker.reconcile_generation_attempt(
                    model="gemini-3.1-flash-lite-image",
                    resolution="1K",
                    attempt_sha256=attempt,
                )

            self.assertEqual(caught.exception.code, "cost_recording_not_recorded")
            self.assertEqual(caught.exception.details["status"], "not_recorded")
            self.assertEqual(caught.exception.details["attempt_sha256"], attempt)
            self.assertEqual(
                caught.exception.details["reason"],
                "attempt_digest_conclusively_absent",
            )
            self.assertFalse(ledger_path().exists())

    def test_reconcile_generation_attempt_duplicate_is_unknown_and_read_only(
        self,
    ) -> None:
        attempt = hashlib.sha256(b"duplicate-reconciliation").hexdigest()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            cost_tracker.record_generation(
                model="gemini-3.1-flash-lite-image",
                resolution="1K",
                label="duplicate reconciliation",
                attempt_sha256=attempt,
            )
            ledger = load_ledger()
            duplicate = dict(ledger["entries"][0])
            ledger["entries"].append(duplicate)
            ledger["total_images"] = 2
            ledger["total_cost"] = round(float(ledger["total_cost"]) * 2, 4)
            day = duplicate["ts"][:10]
            ledger["daily"][day]["count"] = 2
            ledger["daily"][day]["estimated_image_output_usd"] = ledger["total_cost"]
            cost_tracker.save_ledger(ledger)
            before = ledger_path().read_bytes()

            with self.assertRaises(BananaError) as caught:
                cost_tracker.reconcile_generation_attempt(
                    model="gemini-3.1-flash-lite-image",
                    resolution="1K",
                    label="duplicate reconciliation",
                    attempt_sha256=attempt,
                )

            self.assertEqual(
                caught.exception.code,
                "cost_recording_unknown_requires_reconciliation",
            )
            self.assertEqual(
                caught.exception.details["status"],
                "unknown_requires_reconciliation",
            )
            self.assertEqual(
                caught.exception.details["reason"],
                "attempt_digest_not_unique_or_payload_mismatch",
            )
            self.assertEqual(ledger_path().read_bytes(), before)

    def test_reconcile_generation_attempt_requires_every_expected_field(
        self,
    ) -> None:
        cases = (
            "model",
            "resolution",
            "count",
            "estimated_cost",
            "unit_rate",
            "batch",
            "label",
            "interaction_presence",
            "interaction_value",
        )
        for case in cases:
            with (
                self.subTest(case=case),
                tempfile.TemporaryDirectory() as directory,
                patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
            ):
                attempt = hashlib.sha256(
                    f"payload-mismatch-{case}".encode()
                ).hexdigest()
                expected_interaction = "expected-provider-interaction"
                cost_tracker.record_generation(
                    model="gemini-3.1-flash-lite-image",
                    resolution="1K",
                    label="expected reconciliation payload",
                    interaction_id=expected_interaction,
                    attempt_sha256=attempt,
                )
                ledger = load_ledger()
                entry = ledger["entries"][0]
                day = entry["ts"][:10]
                reconciliation_interaction: str | None = expected_interaction
                if case == "model":
                    entry["model"] = "gemini-3-pro-image"
                elif case == "resolution":
                    entry["resolution"] = "2K"
                elif case == "count":
                    entry["count"] = 2
                    changed_cost = round(float(entry["image_output_rate_usd"]) * 2, 4)
                    entry["estimated_image_output_usd"] = changed_cost
                    ledger["total_images"] = 2
                    ledger["total_cost"] = changed_cost
                    ledger["daily"][day]["count"] = 2
                    ledger["daily"][day]["estimated_image_output_usd"] = changed_cost
                elif case == "estimated_cost":
                    changed_cost = round(
                        float(entry["estimated_image_output_usd"]) + 0.00004,
                        5,
                    )
                    entry["estimated_image_output_usd"] = changed_cost
                    ledger["total_cost"] = changed_cost
                    ledger["daily"][day]["estimated_image_output_usd"] = changed_cost
                elif case == "unit_rate":
                    entry["image_output_rate_usd"] = round(
                        float(entry["image_output_rate_usd"]) + 0.00004,
                        5,
                    )
                elif case == "batch":
                    entry["batch"] = True
                elif case == "label":
                    entry["label"] = "different reconciliation payload"
                elif case == "interaction_presence":
                    reconciliation_interaction = None
                elif case == "interaction_value":
                    reconciliation_interaction = "different-provider-interaction"

                if case not in {"interaction_presence", "interaction_value"}:
                    cost_tracker.save_ledger(ledger)
                before = ledger_path().read_bytes()
                with self.assertRaises(BananaError) as caught:
                    cost_tracker.reconcile_generation_attempt(
                        model="gemini-3.1-flash-lite-image",
                        resolution="1K",
                        label="expected reconciliation payload",
                        interaction_id=reconciliation_interaction,
                        attempt_sha256=attempt,
                    )

                self.assertEqual(
                    caught.exception.code,
                    "cost_recording_unknown_requires_reconciliation",
                )
                self.assertEqual(
                    caught.exception.details["status"],
                    "unknown_requires_reconciliation",
                )
                self.assertEqual(ledger_path().read_bytes(), before)

    def test_reconcile_generation_attempt_rejects_invalid_digest(self) -> None:
        with self.assertRaises(BananaError) as caught:
            cost_tracker.reconcile_generation_attempt(
                model="gemini-3.1-flash-lite-image",
                resolution="1K",
                attempt_sha256="A" * 64,
            )
        self.assertEqual(caught.exception.code, "invalid_cost_attempt_digest")

    def test_reconcile_generation_attempt_types_baseexception_as_unknown(self) -> None:
        attempt = hashlib.sha256(b"interrupted-read-only-reconciliation").hexdigest()
        for exception_type in (KeyboardInterrupt, SystemExit):
            with (
                self.subTest(exception_type=exception_type.__name__),
                tempfile.TemporaryDirectory() as directory,
                patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
                patch.object(
                    cost_tracker,
                    "load_ledger",
                    side_effect=exception_type("interrupted reconciliation read"),
                ),
            ):
                with self.assertRaises(BananaError) as caught:
                    cost_tracker.reconcile_generation_attempt(
                        model="gemini-3.1-flash-lite-image",
                        resolution="1K",
                        attempt_sha256=attempt,
                    )

                self.assertEqual(
                    caught.exception.code,
                    "cost_recording_unknown_requires_reconciliation",
                )
                self.assertEqual(
                    caught.exception.details["status"],
                    "unknown_requires_reconciliation",
                )
                self.assertEqual(
                    caught.exception.details["reconciliation_error"]["exception_type"],
                    exception_type.__name__,
                )
                self.assertFalse(ledger_path().exists())


if __name__ == "__main__":
    unittest.main()
