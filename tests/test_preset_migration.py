from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests._support import run_python

import presets
from banana_core import BananaError, _atomic_write_at, _exclusive_rename_at
from presets import MAX_PRESET_BYTES, _bounded_preset_descriptor_read, load_preset


class LegacyPresetMigrationTests(unittest.TestCase):
    @staticmethod
    def legacy_preset(**overrides: Any) -> dict[str, Any]:
        value: dict[str, Any] = {
            "name": "studio",
            "description": "Legacy approved direction",
            "colors": ["#112233", "#AABBCC"],
            "style": "Quiet precision with a warm focal point",
            "typography": "Humanist sans, sentence case",
            "lighting": "Soft directional studio light",
            "mood": "Confident and calm",
            "default_ratio": "16:9",
            "default_resolution": "2K",
        }
        value.update(overrides)
        return value

    @staticmethod
    def write_legacy(
        home: Path, value: dict[str, Any] | None = None
    ) -> tuple[Path, bytes]:
        path = home / "presets" / "studio.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (
            json.dumps(value or LegacyPresetMigrationTests.legacy_preset(), indent=2)
            + "\n"
        ).encode()
        path.write_bytes(raw)
        return path, raw

    @unittest.skipIf(os.name == "nt", "directory symlink setup requires POSIX")
    def test_migration_rejects_symlinked_home_or_ancestor_without_escape(
        self,
    ) -> None:
        for layout in ("home", "ancestor"):
            with (
                self.subTest(layout=layout),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                if layout == "home":
                    actual_home = root / "outside-state"
                    configured_home = root / "state"
                    link = configured_home
                else:
                    outside_parent = root / "outside-parent"
                    actual_home = outside_parent / "state"
                    configured_parent = root / "redirect"
                    configured_home = configured_parent / "state"
                    link = configured_parent
                source, original = self.write_legacy(actual_home)
                reviewed = run_python(
                    "presets.py",
                    "migrate-v1",
                    "studio",
                    "--dry-run",
                    env={"BANANA_HOME": str(actual_home)},
                )
                self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
                fingerprint = json.loads(reviewed.stdout)["fingerprint"]
                source.chmod(0o640)
                source.parent.chmod(0o750)
                actual_home.chmod(0o755)
                if layout == "home":
                    configured_home.symlink_to(actual_home, target_is_directory=True)
                else:
                    configured_parent.symlink_to(
                        outside_parent,
                        target_is_directory=True,
                    )

                commands = (
                    ("migrate-v1", "studio", "--dry-run"),
                    ("migrate-v1", "studio", "--confirm", fingerprint),
                )
                for command in commands:
                    with self.subTest(layout=layout, action=command[2]):
                        result = run_python(
                            "presets.py",
                            *command,
                            env={"BANANA_HOME": str(configured_home)},
                        )
                        self.assertEqual(result.returncode, 1)
                        self.assertIn("unsafe_preset_state_directory", result.stderr)
                        self.assertTrue(link.is_symlink())
                        self.assertEqual(
                            stat.S_IMODE(actual_home.stat().st_mode), 0o755
                        )
                        self.assertEqual(
                            stat.S_IMODE(source.parent.stat().st_mode), 0o750
                        )
                        self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o640)
                        self.assertEqual(source.read_bytes(), original)
                        self.assertEqual(
                            sorted(path.name for path in actual_home.iterdir()),
                            ["presets"],
                        )
                        self.assertEqual(
                            sorted(path.name for path in source.parent.iterdir()),
                            ["studio.json"],
                        )

    def test_confirmed_migration_fails_closed_without_bound_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source, original = self.write_legacy(home)
            with patch.dict(
                os.environ,
                {"BANANA_HOME": directory},
                clear=False,
            ):
                path, _raw, _proposal, fingerprint = presets._migration_material(
                    "studio"
                )
                with (
                    patch.object(presets, "_open_secure_directory", return_value=None),
                    self.assertRaises(BananaError) as caught,
                ):
                    presets._migrate_confirmed_preset_with_descriptors(
                        "studio",
                        path,
                        fingerprint,
                    )

            self.assertEqual(caught.exception.code, "preset_migration_unavailable")
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(
                sorted(path.name for path in home.rglob("*")),
                ["presets", "studio.json"],
            )

    def test_dry_run_is_deterministic_read_only_and_normal_load_fails_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path, raw = self.write_legacy(home)
            with patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False):
                with self.assertRaises(BananaError) as caught:
                    load_preset("studio")
            self.assertEqual(caught.exception.code, "invalid_preset")

            first = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )
            second = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            first_payload = json.loads(first.stdout)
            second_payload = json.loads(second.stdout)

            self.assertEqual(
                first_payload["fingerprint"], second_payload["fingerprint"]
            )
            self.assertEqual(len(first_payload["fingerprint"]), 64)
            self.assertTrue(first_payload["dry_run"])
            self.assertFalse(first_payload["will_write"])
            self.assertFalse(first_payload["network_called"])
            self.assertTrue(first_payload["requires_review"])
            self.assertEqual(first_payload["proposal"]["schema_version"], 2)
            self.assertEqual(
                first_payload["proposal"]["palette"], ["#112233", "#AABBCC"]
            )
            self.assertEqual(
                first_payload["proposal"]["visual_thesis"],
                "Quiet precision with a warm focal point",
            )
            self.assertEqual(
                first_payload["proposal"]["photography"],
                "Lighting: Soft directional studio light; Mood: Confident and calm",
            )
            self.assertEqual(first_payload["proposal"]["default_aspect_ratio"], "16:9")
            self.assertEqual(first_payload["proposal"]["default_image_size"], "2K")
            self.assertEqual(
                first_payload["proposal"]["default_model"], "gemini-3.1-flash-image"
            )
            self.assertEqual(first_payload["mapping"]["direct"]["colors"], "palette")
            self.assertEqual(path.read_bytes(), raw)
            self.assertFalse((home / "backups").exists())
            self.assertFalse((home / ".locks").exists())

    def test_bad_confirmation_does_not_mutate_or_create_migration_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path, raw = self.write_legacy(home)
            result = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                "--confirm",
                "0" * 64,
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("migration_fingerprint_mismatch", result.stderr)
            self.assertEqual(path.read_bytes(), raw)
            self.assertFalse((home / "backups").exists())
            self.assertFalse((home / ".locks").exists())

    def test_cli_requires_exactly_one_migration_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path, raw = self.write_legacy(home)
            missing = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                env={"BANANA_HOME": directory},
            )
            conflicting = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                "--dry-run",
                "--confirm",
                "0" * 64,
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(missing.returncode, 2)
            self.assertEqual(conflicting.returncode, 2)
            self.assertEqual(path.read_bytes(), raw)
            self.assertFalse((home / "backups").exists())
            self.assertFalse((home / ".locks").exists())

    def test_confirm_creates_private_exact_backup_and_usable_schema_two_preset(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path, raw = self.write_legacy(home)
            preview = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            fingerprint = json.loads(preview.stdout)["fingerprint"]

            confirmed = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                "--confirm",
                fingerprint,
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
            payload = json.loads(confirmed.stdout)
            self.assertTrue(payload["migrated"])
            self.assertFalse(payload["network_called"])
            self.assertFalse(payload["requires_review"])

            backup = Path(payload["backup_path"])
            self.assertEqual(backup.parent, home / "backups" / "presets")
            self.assertEqual(backup.read_bytes(), raw)
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(backup.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(backup.parent.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            if os.name != "nt":
                lock = home / ".locks" / "presets" / "studio.lock"
                self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(lock.parent.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(lock.parent.parent.stat().st_mode), 0o700)

            with patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False):
                migrated = load_preset("studio")
            self.assertEqual(migrated, payload["preset"])

            listed = run_python("presets.py", "list", env={"BANANA_HOME": directory})
            shown = run_python(
                "presets.py", "show", "studio", env={"BANANA_HOME": directory}
            )
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertEqual(
                json.loads(listed.stdout)["presets"],
                [{"name": "studio", "description": "Legacy approved direction"}],
            )
            self.assertEqual(json.loads(shown.stdout), migrated)

    def test_only_exact_valid_legacy_shape_is_accepted(self) -> None:
        cases = {
            "extra field": {**self.legacy_preset(), "instructions": "hidden"},
            "missing field": {
                key: value
                for key, value in self.legacy_preset().items()
                if key != "mood"
            },
            "wrong name": self.legacy_preset(name="different"),
            "wrong scalar type": self.legacy_preset(style=["not", "text"]),
            "invalid palette": self.legacy_preset(colors=["red"]),
        }
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for label, value in cases.items():
                with self.subTest(label=label):
                    path, raw = self.write_legacy(home, value)
                    result = run_python(
                        "presets.py",
                        "migrate-v1",
                        "studio",
                        "--dry-run",
                        env={"BANANA_HOME": directory},
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("invalid_legacy_preset", result.stderr)
                    self.assertEqual(path.read_bytes(), raw)

    def test_all_preset_reads_are_bounded(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {"BANANA_HOME": directory},
                clear=False,
            ),
        ):
            home = Path(directory)
            path = home / "presets" / "studio.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(b" " * (MAX_PRESET_BYTES + 1))
            with self.assertRaises(BananaError) as caught:
                load_preset("studio")
            self.assertEqual(caught.exception.code, "preset_too_large")

            migrated = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(migrated.returncode, 1)
            self.assertIn("preset_too_large", migrated.stderr)

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_NOFOLLOW"),
        "requires POSIX no-follow file opens",
    )
    def test_preset_source_symlinks_are_rejected_without_migration_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            preset_directory = home / "presets"
            preset_directory.mkdir()
            target = home / "legacy-target.json"
            raw = (json.dumps(self.legacy_preset(), indent=2) + "\n").encode()
            target.write_bytes(raw)
            (preset_directory / "studio.json").symlink_to(target)

            with patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False):
                with self.assertRaises(BananaError) as caught:
                    load_preset("studio")
            self.assertEqual(caught.exception.code, "invalid_preset")

            migrated = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(migrated.returncode, 1)
            self.assertIn("invalid_preset", migrated.stderr)
            self.assertEqual(target.read_bytes(), raw)
            self.assertFalse((home / "backups").exists())
            self.assertFalse((home / ".locks").exists())

    @unittest.skipUnless(os.name != "nt", "requires POSIX non-regular files")
    def test_non_regular_preset_sources_are_rejected_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / "presets" / "studio.json"
            source.mkdir(parents=True)
            with patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False):
                with self.assertRaises(BananaError) as caught:
                    load_preset("studio")
            self.assertEqual(caught.exception.code, "invalid_preset")

            migrated = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(migrated.returncode, 1)
            self.assertIn("invalid_preset", migrated.stderr)

        if hasattr(os, "mkfifo"):
            with tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                source = home / "presets" / "studio.json"
                source.parent.mkdir()
                os.mkfifo(source)
                migrated = run_python(
                    "presets.py",
                    "migrate-v1",
                    "studio",
                    "--dry-run",
                    env={"BANANA_HOME": directory},
                )
                self.assertEqual(migrated.returncode, 1)
                self.assertIn("invalid_preset", migrated.stderr)

    @unittest.skipUnless(os.name != "nt", "requires POSIX symbolic links")
    def test_migration_rejects_symlinked_private_state_directories(self) -> None:
        cases = ("locks", "backups", "backup presets", "preset directory")
        for label in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                path, raw = self.write_legacy(home)
                preview = run_python(
                    "presets.py",
                    "migrate-v1",
                    "studio",
                    "--dry-run",
                    env={"BANANA_HOME": directory},
                )
                self.assertEqual(preview.returncode, 0, preview.stderr)
                fingerprint = json.loads(preview.stdout)["fingerprint"]
                outside = home / "outside"
                outside.mkdir()

                if label == "locks":
                    (home / ".locks").symlink_to(outside, target_is_directory=True)
                elif label == "backups":
                    (home / "backups").symlink_to(outside, target_is_directory=True)
                elif label == "backup presets":
                    (home / "backups").mkdir()
                    (home / "backups" / "presets").symlink_to(
                        outside, target_is_directory=True
                    )
                else:
                    path.unlink()
                    (home / "presets").rmdir()
                    (home / "presets").symlink_to(outside, target_is_directory=True)
                    (outside / "studio.json").write_bytes(raw)

                confirmed = run_python(
                    "presets.py",
                    "migrate-v1",
                    "studio",
                    "--confirm",
                    fingerprint,
                    env={"BANANA_HOME": directory},
                )
                self.assertEqual(confirmed.returncode, 1)
                self.assertIn("unsafe_preset_state_directory", confirmed.stderr)
                self.assertEqual(
                    (outside / "studio.json").exists(), label == "preset directory"
                )
                if label != "preset directory":
                    self.assertEqual(path.read_bytes(), raw)

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_NOFOLLOW"),
        "requires POSIX no-follow file opens",
    )
    def test_migration_rejects_symlinked_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path, raw = self.write_legacy(home)
            preview = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )
            fingerprint = json.loads(preview.stdout)["fingerprint"]
            lock_directory = home / ".locks" / "presets"
            lock_directory.mkdir(parents=True)
            outside = home / "outside.lock"
            outside.write_bytes(b"unchanged")
            (lock_directory / "studio.lock").symlink_to(outside)

            confirmed = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                "--confirm",
                fingerprint,
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(confirmed.returncode, 1)
            self.assertIn("preset_migration_failed", confirmed.stderr)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(outside.read_bytes(), b"unchanged")
            self.assertFalse((home / "backups").exists())

    @unittest.skipUnless(os.name != "nt", "requires POSIX hard links")
    def test_create_rejects_hardlinked_lock_before_chmod_or_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            lock_directory = home / ".locks" / "presets"
            lock_directory.mkdir(parents=True)
            foreign = home / "foreign.lock"
            foreign.write_bytes(b"foreign lock bytes")
            foreign.chmod(0o640)
            os.link(foreign, lock_directory / "studio.lock")

            created = run_python(
                "presets.py",
                "create",
                "studio",
                "--description",
                "must not be written",
                env={"BANANA_HOME": directory},
            )

            self.assertEqual(created.returncode, 1)
            self.assertIn("preset_migration_failed", created.stderr)
            self.assertEqual(foreign.read_bytes(), b"foreign lock bytes")
            self.assertEqual(stat.S_IMODE(foreign.stat().st_mode), 0o640)
            self.assertEqual(foreign.stat().st_nlink, 2)
            self.assertFalse((home / "presets" / "studio.json").exists())

    @unittest.skipIf(os.name == "nt", "requires POSIX flock and rename")
    def test_lock_entry_replacement_is_rejected_before_critical_section(self) -> None:
        import fcntl

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            lock = home / ".locks" / "presets" / "studio.lock"
            replacement = home / "replacement.lock"
            replacement.write_bytes(b"foreign replacement lock")
            original_flock = fcntl.flock
            replaced = False
            entered = False

            def replace_after_flock(descriptor: int, operation: int) -> None:
                nonlocal replaced
                original_flock(descriptor, operation)
                if operation == fcntl.LOCK_EX and not replaced:
                    lock.unlink()
                    replacement.rename(lock)
                    replaced = True

            with patch("fcntl.flock", side_effect=replace_after_flock):
                with self.assertRaises(BananaError) as caught:
                    with presets._preset_lock("studio"):
                        entered = True

            self.assertTrue(replaced)
            self.assertFalse(entered)
            self.assertEqual(caught.exception.code, "preset_migration_failed")
            self.assertEqual(lock.read_bytes(), b"foreign replacement lock")
            self.assertEqual(lock.stat().st_nlink, 1)

    def test_json_value_and_recursion_errors_are_typed_without_payload_echo(
        self,
    ) -> None:
        deeply_nested = "[" * 100_000 + "]" * 100_000
        oversized_integer = "9" * 5_000
        oversized_reference = "x" * (presets.MAX_REFERENCE_JSON_CHARS + 1)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / "presets" / "studio.json"
            path.parent.mkdir()
            path.write_text(deeply_nested, encoding="utf-8")
            migrated = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(migrated.returncode, 1)
            self.assertIn("invalid_preset", migrated.stderr)
            self.assertNotIn(deeply_nested[:100], migrated.stderr)

            reference = run_python(
                "presets.py",
                "create",
                "reference-test",
                "--reference",
                oversized_integer,
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(reference.returncode, 1)
            self.assertIn("invalid_preset", reference.stderr)
            self.assertNotIn(oversized_integer[:100], reference.stderr)

            bounded_reference = run_python(
                "presets.py",
                "create",
                "bounded-reference-test",
                "--reference",
                oversized_reference,
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(bounded_reference.returncode, 1)
            self.assertIn("invalid_preset", bounded_reference.stderr)
            self.assertNotIn(oversized_reference[:100], bounded_reference.stderr)

    def test_non_force_create_refuses_destination_that_appears_during_publication(
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
            args = presets.build_parser().parse_args(
                ["create", "studio", "--description", "candidate"]
            )
            destination = Path(directory) / "presets" / "studio.json"
            competing_bytes = b'{"owner":"competing writer"}\n'
            atomic_json = presets._atomic_json

            def publish_after_racer(
                path: Path,
                value: dict[str, Any],
                *,
                replace: bool = True,
            ) -> None:
                self.assertFalse(replace)
                path.write_bytes(competing_bytes)
                atomic_json(path, value, replace=replace)

            with patch("presets._atomic_json", side_effect=publish_after_racer):
                with self.assertRaises(BananaError) as caught:
                    presets.cmd_create(args)

            self.assertEqual(caught.exception.code, "preset_exists")
            self.assertEqual(destination.read_bytes(), competing_bytes)
            self.assertEqual(list(destination.parent.glob(".studio.*.json")), [])

    def test_concurrent_non_force_creates_have_exactly_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            descriptions = ("first candidate", "second candidate")

            def create(description: str) -> Any:
                return run_python(
                    "presets.py",
                    "create",
                    "studio",
                    "--description",
                    description,
                    env={"BANANA_HOME": directory},
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(create, descriptions))

            successes = [result for result in results if result.returncode == 0]
            failures = [result for result in results if result.returncode != 0]
            self.assertEqual(len(successes), 1)
            self.assertEqual(len(failures), 1)
            self.assertIn("preset_exists", failures[0].stderr)

            with patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False):
                created = load_preset("studio")
            self.assertIn(created["description"], descriptions)

    def test_write_after_confirmation_reread_is_preserved(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            path, original = self.write_legacy(home)
            _path, _raw, _proposal, fingerprint = presets._migration_material("studio")
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

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with patch(
                "presets._atomic_write_at",
                side_effect=recreate_then_publish,
            ):
                with self.assertRaises(BananaError) as caught:
                    presets.cmd_migrate_v1(args)

            self.assertEqual(caught.exception.code, "migration_fingerprint_mismatch")
            self.assertEqual(path.read_bytes(), competing)
            backups = list((home / "backups" / "presets").glob("studio.v1-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            recovery = caught.exception.details["migration_recovery"]
            self.assertTrue(recovery["publication_attempted"])
            self.assertFalse(recovery["publication_succeeded"])
            self.assertFalse(recovery["restored"])
            self.assertTrue(recovery["active_entry_present"])
            self.assertTrue(recovery["backup_retained"])
            self.assertEqual(
                recovery["cleanup_status"],
                "backup_retained_active_entry_present",
            )
            self.assertEqual(
                (
                    recovery["exact_legacy_identity"]["device"],
                    recovery["exact_legacy_identity"]["inode"],
                ),
                (backups[0].stat().st_dev, backups[0].stat().st_ino),
            )

    def test_recovery_race_preserves_competing_active_and_exact_backup(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, _proposal, fingerprint = presets._migration_material("studio")
            competing = b'{"legacy_writer":"won recovery race"}\n'
            original_publish = _atomic_write_at
            publication_calls = 0

            def fail_then_race_recovery_publication(
                directory_descriptor: int,
                name: str,
                data: bytes,
                *,
                replace: bool = True,
                expected_directory: Path | None = None,
            ) -> None:
                nonlocal publication_calls
                publication_calls += 1
                if publication_calls == 1:
                    raise BananaError(
                        "forced_before_publication",
                        "Forced failure before active publication.",
                    )
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

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with patch(
                "presets._atomic_write_at",
                side_effect=fail_then_race_recovery_publication,
            ):
                with self.assertRaises(BananaError) as caught:
                    presets.cmd_migrate_v1(args)

            self.assertEqual(caught.exception.code, "forced_before_publication")
            self.assertEqual(publication_calls, 2)
            self.assertEqual(source.read_bytes(), competing)
            backups = list((home / "backups" / "presets").glob("studio.v1-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            recovery = caught.exception.details["migration_recovery"]
            self.assertFalse(recovery["restored"])
            self.assertTrue(recovery["active_entry_present"])
            self.assertTrue(recovery["backup_retained"])
            self.assertEqual(
                recovery["cleanup_status"],
                "backup_retained_active_entry_race",
            )

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "requires descriptor-bound no-overwrite recovery",
    )
    def test_prepublication_failure_restores_exact_inode_and_retains_backup(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, _proposal, fingerprint = presets._migration_material("studio")
            original_publish = _atomic_write_at
            publication_calls = 0

            def fail_then_recover(
                directory_descriptor: int,
                name: str,
                data: bytes,
                *,
                replace: bool = True,
                expected_directory: Path | None = None,
            ) -> None:
                nonlocal publication_calls
                publication_calls += 1
                if publication_calls == 1:
                    raise BananaError(
                        "forced_before_publication",
                        "Forced failure before active publication.",
                    )
                original_publish(
                    directory_descriptor,
                    name,
                    data,
                    replace=replace,
                    expected_directory=expected_directory,
                )

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with patch("presets._atomic_write_at", side_effect=fail_then_recover):
                with self.assertRaises(BananaError) as caught:
                    presets.cmd_migrate_v1(args)

            self.assertEqual(caught.exception.code, "forced_before_publication")
            self.assertEqual(publication_calls, 2)
            self.assertEqual(source.read_bytes(), original)
            backups = list((home / "backups" / "presets").glob("studio.v1-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            active_metadata = source.stat()
            backup_metadata = backups[0].stat()
            self.assertNotEqual(
                (active_metadata.st_dev, active_metadata.st_ino),
                (backup_metadata.st_dev, backup_metadata.st_ino),
            )
            self.assertEqual(active_metadata.st_nlink, 1)
            self.assertEqual(backup_metadata.st_nlink, 1)
            self.assertEqual(stat.S_IMODE(active_metadata.st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(backup_metadata.st_mode), 0o600)
            recovery = caught.exception.details["migration_recovery"]
            self.assertTrue(recovery["restored"])
            self.assertTrue(recovery["backup_retained"])
            self.assertEqual(
                recovery["cleanup_status"],
                "exact_independent_active_copy_and_backup_inode_retained",
            )

    def test_replaced_backup_entry_is_never_used_for_restore(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, _proposal, fingerprint = presets._migration_material("studio")
            foreign = b'{"foreign":"backup path replacement"}\n'
            relocated = home / "backups" / "presets" / "held-original.json"

            def replace_backup_then_fail(*_args: Any, **_kwargs: Any) -> None:
                backups = list((home / "backups" / "presets").glob("studio.v1-*.json"))
                self.assertEqual(len(backups), 1)
                backups[0].rename(relocated)
                backups[0].write_bytes(foreign)
                raise BananaError("forced_root_error", "Forced root failure.")

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with patch(
                "presets._atomic_write_at",
                side_effect=replace_backup_then_fail,
            ):
                with self.assertRaises(BananaError) as caught:
                    presets.cmd_migrate_v1(args)

            self.assertEqual(caught.exception.code, "forced_root_error")
            self.assertFalse(source.exists())
            self.assertEqual(relocated.read_bytes(), original)
            generated = list((home / "backups" / "presets").glob("studio.v1-*.json"))
            self.assertEqual(len(generated), 1)
            self.assertEqual(generated[0].read_bytes(), foreign)
            recovery = caught.exception.details["migration_recovery"]
            self.assertFalse(recovery["restored"])
            self.assertFalse(recovery["active_entry_present"])
            self.assertFalse(recovery["backup_entry_identity_verified"])
            self.assertFalse(recovery["backup_public_path_binding_verified"])
            self.assertEqual(
                recovery["cleanup_status"],
                "backup_retained_unbound_no_restore",
            )
            self.assertEqual(
                (
                    recovery["exact_legacy_identity"]["device"],
                    recovery["exact_legacy_identity"]["inode"],
                ),
                (relocated.stat().st_dev, relocated.stat().st_ino),
            )

    def test_post_publication_failure_retains_root_error_and_exact_backup(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, _proposal, fingerprint = presets._migration_material("studio")
            original_publish = _atomic_write_at
            original_read = _bounded_preset_descriptor_read
            published = False

            def publish(
                directory_descriptor: int,
                name: str,
                data: bytes,
                *,
                replace: bool = True,
                expected_directory: Path | None = None,
            ) -> None:
                nonlocal published
                original_publish(
                    directory_descriptor,
                    name,
                    data,
                    replace=replace,
                    expected_directory=expected_directory,
                )
                published = True

            def fail_post_publication_read(descriptor: int, *, name: str) -> bytes:
                if published:
                    raise BananaError(
                        "forced_post_publication",
                        "Forced post-publication verification failure.",
                    )
                return original_read(descriptor, name=name)

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with (
                patch("presets._atomic_write_at", side_effect=publish),
                patch(
                    "presets._bounded_preset_descriptor_read",
                    side_effect=fail_post_publication_read,
                ),
            ):
                with self.assertRaises(BananaError) as caught:
                    presets.cmd_migrate_v1(args)

            self.assertEqual(caught.exception.code, "forced_post_publication")
            self.assertEqual(load_preset("studio")["schema_version"], 2)
            backups = list((home / "backups" / "presets").glob("studio.v1-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            recovery = caught.exception.details["migration_recovery"]
            self.assertTrue(recovery["publication_attempted"])
            self.assertTrue(recovery["publication_succeeded"])
            self.assertFalse(recovery["restored"])
            self.assertTrue(recovery["active_entry_present"])
            self.assertFalse(recovery["active_entry_exact_legacy_identity"])
            self.assertTrue(recovery["backup_retained"])
            self.assertEqual(
                recovery["cleanup_status"],
                "exact_migrated_active_and_legacy_backup_retained",
            )
            self.assertEqual(
                (
                    recovery["exact_legacy_identity"]["device"],
                    recovery["exact_legacy_identity"]["inode"],
                ),
                (backups[0].stat().st_dev, backups[0].stat().st_ino),
            )

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative no-replace rename",
    )
    def test_backup_claim_collision_preserves_source_and_destination(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, _proposal, fingerprint = presets._migration_material("studio")
            fixed_now = datetime(2026, 8, 29, 9, 30, tzinfo=timezone.utc)
            suffix = b"\x15" * 8
            backup_directory = home / "backups" / "presets"
            backup_directory.mkdir(parents=True)
            collision = backup_directory / (
                "studio.v1-"
                f"{fixed_now.strftime('%Y%m%dT%H%M%S%fZ')}-"
                f"{fingerprint[:12]}-{suffix.hex()}.json"
            )
            collision_bytes = b'{"existing":"private backup"}\n'
            collision.write_bytes(collision_bytes)

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with (
                patch("presets.datetime") as datetime_mock,
                patch("presets.os.urandom", return_value=suffix),
            ):
                datetime_mock.now.return_value = fixed_now
                with self.assertRaises(BananaError) as caught:
                    presets.cmd_migrate_v1(args)

            self.assertEqual(caught.exception.code, "preset_backup_failed")
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(collision.read_bytes(), collision_bytes)
            self.assertFalse(caught.exception.details["claim_completed"])
            intended = caught.exception.details["intended_legacy_identity"]
            self.assertEqual(
                (intended["device"], intended["inode"]),
                (source.stat().st_dev, source.stat().st_ino),
            )

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative no-replace rename",
    )
    def test_source_substitution_retains_and_reports_intended_identity(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, _proposal, fingerprint = presets._migration_material("studio")
            relocated = source.with_name("held-intended.json")
            foreign = b'{"foreign":"substituted source"}\n'
            original_exclusive_rename = _exclusive_rename_at
            substituted = False

            def substitute_then_claim(
                source_directory_descriptor: int,
                source_name: str,
                destination_directory_descriptor: int,
                destination_name: str,
            ) -> None:
                nonlocal substituted
                if not substituted and source_name == source.name:
                    source.rename(relocated)
                    source.write_bytes(foreign)
                    source.chmod(0o640)
                    substituted = True
                original_exclusive_rename(
                    source_directory_descriptor,
                    source_name,
                    destination_directory_descriptor,
                    destination_name,
                )

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with patch(
                "presets._exclusive_rename_at",
                side_effect=substitute_then_claim,
            ):
                with self.assertRaises(BananaError) as caught:
                    presets.cmd_migrate_v1(args)

            self.assertTrue(substituted)
            self.assertEqual(caught.exception.code, "migration_fingerprint_mismatch")
            self.assertFalse(source.exists())
            self.assertEqual(relocated.read_bytes(), original)
            backups = list((home / "backups" / "presets").glob("studio.v1-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), foreign)
            self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o640)
            intended = caught.exception.details["intended_legacy_identity"]
            claimed = caught.exception.details["claimed_backup_identity"]
            self.assertEqual(
                (intended["device"], intended["inode"]),
                (relocated.stat().st_dev, relocated.stat().st_ino),
            )
            self.assertEqual(
                (claimed["device"], claimed["inode"]),
                (backups[0].stat().st_dev, backups[0].stat().st_ino),
            )
            intended_recovery = caught.exception.details["intended_recovery"]
            self.assertTrue(intended_recovery["retained"])
            self.assertEqual(intended_recovery["method"], "held_inode_link")
            recovery_path = Path(intended_recovery["path"])
            self.assertEqual(recovery_path.read_bytes(), original)
            self.assertEqual(
                (intended_recovery["device"], intended_recovery["inode"]),
                (relocated.stat().st_dev, relocated.stat().st_ino),
            )
            recovery = caught.exception.details["migration_recovery"]
            self.assertFalse(recovery["backup_entry_identity_verified"])
            self.assertEqual(
                (
                    recovery["exact_legacy_identity"]["device"],
                    recovery["exact_legacy_identity"]["inode"],
                ),
                (relocated.stat().st_dev, relocated.stat().st_ino),
            )

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative no-replace rename",
    )
    def test_post_link_failure_reports_link_and_fallback_copy(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, _proposal, fingerprint = presets._migration_material("studio")
            relocated = source.with_name("held-intended.json")
            foreign = b'{"foreign":"substituted source"}\n'
            original_exclusive_rename = _exclusive_rename_at
            real_fsync = os.fsync
            substituted = False
            injected = False

            def substitute_then_claim(
                source_directory_descriptor: int,
                source_name: str,
                destination_directory_descriptor: int,
                destination_name: str,
            ) -> None:
                nonlocal substituted
                if not substituted and source_name == source.name:
                    source.rename(relocated)
                    source.write_bytes(foreign)
                    source.chmod(0o640)
                    substituted = True
                original_exclusive_rename(
                    source_directory_descriptor,
                    source_name,
                    destination_directory_descriptor,
                    destination_name,
                )

            def fail_once_after_recovery_link(descriptor: int) -> None:
                nonlocal injected
                recovery_links = list(
                    (home / "backups" / "presets").glob(
                        "studio.intended-recovery-*.json"
                    )
                )
                if recovery_links and not injected:
                    injected = True
                    raise OSError("synthetic post-link fsync failure")
                real_fsync(descriptor)

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with (
                patch(
                    "presets._exclusive_rename_at",
                    side_effect=substitute_then_claim,
                ),
                patch("presets.os.fsync", side_effect=fail_once_after_recovery_link),
            ):
                with self.assertRaises(BananaError) as caught:
                    presets.cmd_migrate_v1(args)

            self.assertTrue(substituted)
            self.assertTrue(injected)
            self.assertEqual(caught.exception.code, "migration_fingerprint_mismatch")
            intended_recovery = caught.exception.details["intended_recovery"]
            self.assertTrue(intended_recovery["retained"])
            self.assertEqual(
                intended_recovery["method"],
                "exact_reviewed_bytes_copy",
            )
            entries = intended_recovery["recovery_entries"]
            self.assertEqual(
                [entry["method"] for entry in entries],
                ["held_inode_link", "exact_reviewed_bytes_copy"],
            )
            link_receipt, copy_receipt = entries
            self.assertTrue(link_receipt["publication_succeeded"])
            self.assertFalse(link_receipt["verification_complete"])
            self.assertTrue(link_receipt["identity_binding_verified"])
            self.assertTrue(link_receipt["path_binding_verified"])
            self.assertTrue(copy_receipt["publication_succeeded"])
            self.assertTrue(copy_receipt["verification_complete"])
            self.assertTrue(copy_receipt["identity_binding_verified"])
            self.assertTrue(copy_receipt["path_binding_verified"])

            link_path = Path(link_receipt["path"])
            copy_path = Path(copy_receipt["path"])
            self.assertEqual(link_path.read_bytes(), original)
            self.assertEqual(copy_path.read_bytes(), original)
            self.assertEqual(
                (link_receipt["device"], link_receipt["inode"]),
                (relocated.stat().st_dev, relocated.stat().st_ino),
            )
            self.assertEqual(
                (copy_receipt["device"], copy_receipt["inode"]),
                (copy_path.stat().st_dev, copy_path.stat().st_ino),
            )
            self.assertNotEqual(link_receipt["inode"], copy_receipt["inode"])

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative no-replace rename",
    )
    def test_unlinked_intended_source_is_retained_as_exact_private_copy(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, _proposal, fingerprint = presets._migration_material("studio")
            foreign = b'{"foreign":"destructive source substitution"}\n'
            original_exclusive_rename = _exclusive_rename_at
            substituted = False

            def unlink_then_substitute(
                source_directory_descriptor: int,
                source_name: str,
                destination_directory_descriptor: int,
                destination_name: str,
            ) -> None:
                nonlocal substituted
                if not substituted and source_name == source.name:
                    source.unlink()
                    source.write_bytes(foreign)
                    source.chmod(0o640)
                    substituted = True
                original_exclusive_rename(
                    source_directory_descriptor,
                    source_name,
                    destination_directory_descriptor,
                    destination_name,
                )

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with patch(
                "presets._exclusive_rename_at",
                side_effect=unlink_then_substitute,
            ):
                with self.assertRaises(BananaError) as caught:
                    presets.cmd_migrate_v1(args)

            self.assertTrue(substituted)
            self.assertEqual(caught.exception.code, "migration_fingerprint_mismatch")
            self.assertFalse(source.exists())
            foreign_backups = list(
                (home / "backups" / "presets").glob("studio.v1-*.json")
            )
            self.assertEqual(len(foreign_backups), 1)
            self.assertEqual(foreign_backups[0].read_bytes(), foreign)
            intended = caught.exception.details["intended_legacy_identity"]
            self.assertEqual(intended["link_count"], 0)
            intended_recovery = caught.exception.details["intended_recovery"]
            self.assertTrue(intended_recovery["retained"])
            self.assertEqual(
                intended_recovery["method"],
                "exact_reviewed_bytes_copy",
            )
            recovery_copy = Path(intended_recovery["path"])
            self.assertEqual(recovery_copy.read_bytes(), original)
            self.assertEqual(stat.S_IMODE(recovery_copy.stat().st_mode), 0o600)
            self.assertEqual(
                (intended_recovery["device"], intended_recovery["inode"]),
                (recovery_copy.stat().st_dev, recovery_copy.stat().st_ino),
            )

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires directory fsync support",
    )
    def test_new_backup_ancestry_is_fsynced_leaf_to_root(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            _source, _original = self.write_legacy(home)
            _path, _raw, _proposal, fingerprint = presets._migration_material("studio")
            backup_root = home / "backups"
            backup_directory = backup_root / "presets"
            real_fsync = os.fsync
            calls: list[str] = []

            def record_fsync(descriptor: int) -> None:
                metadata = os.fstat(descriptor)
                for label, path in (
                    ("backup_directory", backup_directory),
                    ("backup_root", backup_root),
                    ("home", home),
                ):
                    try:
                        path_metadata = path.stat()
                    except FileNotFoundError:
                        continue
                    if stat.S_ISDIR(metadata.st_mode) and (
                        metadata.st_dev,
                        metadata.st_ino,
                    ) == (path_metadata.st_dev, path_metadata.st_ino):
                        calls.append(label)
                        break
                real_fsync(descriptor)

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with (
                patch("presets.os.fsync", side_effect=record_fsync),
                patch("builtins.print"),
            ):
                presets.cmd_migrate_v1(args)

            expected = ["backup_directory", "backup_root", "home"]
            self.assertTrue(
                any(
                    calls[index : index + 3] == expected for index in range(len(calls))
                ),
                calls,
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
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, _proposal, fingerprint = presets._migration_material("studio")
            source_directory = home / "presets"
            moved_source = home / "held-presets"
            original_rename = os.rename
            original_exclusive_rename = _exclusive_rename_at
            swapped = False

            def swap_source_parent(
                source_directory_descriptor: int,
                source_name: str,
                destination_directory_descriptor: int,
                destination_name: str,
            ) -> None:
                nonlocal swapped
                if not swapped and source_name == "studio.json":
                    original_rename(source_directory, moved_source)
                    source_directory.mkdir(mode=0o700)
                    swapped = True
                original_exclusive_rename(
                    source_directory_descriptor,
                    source_name,
                    destination_directory_descriptor,
                    destination_name,
                )

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with patch(
                "presets._exclusive_rename_at",
                side_effect=swap_source_parent,
            ):
                with self.assertRaises(BananaError) as caught:
                    presets.cmd_migrate_v1(args)

            self.assertTrue(swapped)
            self.assertEqual(caught.exception.code, "preset_source_directory_changed")
            self.assertEqual(list(source_directory.iterdir()), [])
            self.assertEqual(list(moved_source.iterdir()), [])
            backups = list((home / "backups" / "presets").glob("studio.v1-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            recovery = caught.exception.details["migration_recovery"]
            self.assertFalse(recovery["source_directory_binding_verified"])
            self.assertTrue(recovery["backup_directory_binding_verified"])
            self.assertTrue(recovery["backup_retained"])
            self.assertEqual(
                recovery["cleanup_status"],
                "backup_retained_unbound_no_restore",
            )

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative directory operations",
    )
    def test_backup_parent_swap_never_writes_redirect_and_retains_backup(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, _proposal, fingerprint = presets._migration_material("studio")
            backup_directory = home / "backups" / "presets"
            moved_backup = home / "backups" / "held-presets"
            original_rename = os.rename
            original_exclusive_rename = _exclusive_rename_at
            swapped = False

            def swap_backup_parent(
                source_directory_descriptor: int,
                source_name: str,
                destination_directory_descriptor: int,
                destination_name: str,
            ) -> None:
                nonlocal swapped
                if not swapped and source_name == "studio.json":
                    original_rename(backup_directory, moved_backup)
                    backup_directory.mkdir(mode=0o700)
                    swapped = True
                original_exclusive_rename(
                    source_directory_descriptor,
                    source_name,
                    destination_directory_descriptor,
                    destination_name,
                )

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with patch(
                "presets._exclusive_rename_at",
                side_effect=swap_backup_parent,
            ):
                with self.assertRaises(BananaError) as caught:
                    presets.cmd_migrate_v1(args)

            self.assertTrue(swapped)
            self.assertEqual(caught.exception.code, "preset_backup_directory_changed")
            self.assertFalse(source.exists())
            self.assertEqual(list(backup_directory.iterdir()), [])
            backups = list(moved_backup.glob("studio.v1-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            recovery = caught.exception.details["migration_recovery"]
            self.assertTrue(recovery["source_directory_binding_verified"])
            self.assertFalse(recovery["backup_directory_binding_verified"])
            self.assertTrue(recovery["backup_entry_identity_verified"])
            self.assertFalse(recovery["backup_public_path_binding_verified"])
            self.assertTrue(recovery["backup_retained"])
            self.assertEqual(
                recovery["cleanup_status"],
                "backup_retained_unbound_no_restore",
            )
            self.assertEqual(
                (
                    recovery["exact_legacy_identity"]["device"],
                    recovery["exact_legacy_identity"]["inode"],
                ),
                (backups[0].stat().st_dev, backups[0].stat().st_ino),
            )

    @unittest.skipUnless(os.name != "nt", "requires POSIX hard links")
    def test_hard_linked_source_is_rejected_before_claim_or_chmod(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source, original = self.write_legacy(home)
            alias = source.parent / "studio-alias.json"
            os.link(source, alias)
            original_mode = stat.S_IMODE(source.stat().st_mode)
            reviewed = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                "--dry-run",
                env={"BANANA_HOME": directory},
            )
            fingerprint = json.loads(reviewed.stdout)["fingerprint"]

            confirmed = run_python(
                "presets.py",
                "migrate-v1",
                "studio",
                "--confirm",
                fingerprint,
                env={"BANANA_HOME": directory},
            )
            self.assertEqual(confirmed.returncode, 1)
            self.assertIn("unsafe_legacy_preset", confirmed.stderr)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(alias.read_bytes(), original)
            self.assertEqual(source.stat().st_nlink, 2)
            self.assertEqual(stat.S_IMODE(source.stat().st_mode), original_mode)
            self.assertFalse((home / "backups").exists())

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative directory operations",
    )
    def test_interrupt_after_successful_claim_restores_exact_active_preset(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, _proposal, fingerprint = presets._migration_material("studio")
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
                    raise KeyboardInterrupt("interrupt after successful preset claim")

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with patch(
                "presets._exclusive_rename_at",
                side_effect=rename_then_interrupt,
            ):
                with self.assertRaisesRegex(
                    KeyboardInterrupt,
                    "interrupt after successful preset claim",
                ):
                    presets.cmd_migrate_v1(args)

            self.assertTrue(interrupted)
            self.assertEqual(source.read_bytes(), original)
            backups = list((home / "backups" / "presets").glob("studio.v1-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            active_metadata = source.stat()
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
    def test_baseexception_after_claim_reread_restores_exact_active_preset(
        self,
    ) -> None:
        for exception_type in (KeyboardInterrupt, SystemExit):
            with (
                self.subTest(exception_type=exception_type.__name__),
                tempfile.TemporaryDirectory() as directory,
                patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
            ):
                home = Path(directory)
                source, original = self.write_legacy(home)
                _path, _raw, proposal, fingerprint = presets._migration_material(
                    "studio"
                )
                original_read = _bounded_preset_descriptor_read
                reads = 0

                def interrupt_post_claim(descriptor: int, *, name: str) -> bytes:
                    nonlocal reads
                    reads += 1
                    if reads == 4:
                        raise exception_type("interrupt after preset claim reread")
                    return original_read(descriptor, name=name)

                args = presets.build_parser().parse_args(
                    ["migrate-v1", "studio", "--confirm", fingerprint]
                )
                with patch(
                    "presets._bounded_preset_descriptor_read",
                    side_effect=interrupt_post_claim,
                ):
                    with self.assertRaises(exception_type) as caught:
                        presets.cmd_migrate_v1(args)

                self.assertEqual(
                    caught.exception.args,
                    ("interrupt after preset claim reread",),
                )
                self.assertEqual(reads, 4)
                self.assertEqual(source.read_bytes(), original)
                backups = list((home / "backups" / "presets").glob("studio.v1-*.json"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_bytes(), original)
                active_metadata = source.stat()
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
                    presets.cmd_migrate_v1(args)
                self.assertEqual(load_preset("studio"), proposal)
                self.assertEqual(backups[0].read_bytes(), original)

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "requires descriptor-bound no-overwrite recovery",
    )
    def test_interrupt_after_active_publication_keeps_exact_migrated_preset(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, proposal, fingerprint = presets._migration_material("studio")
            expected_active = presets._serialized_preset(proposal)
            original_read = _bounded_preset_descriptor_read
            reads = 0

            def interrupt_active_verification(descriptor: int, *, name: str) -> bytes:
                nonlocal reads
                reads += 1
                if reads == 5:
                    raise KeyboardInterrupt("interrupt after active preset publication")
                return original_read(descriptor, name=name)

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with patch(
                "presets._bounded_preset_descriptor_read",
                side_effect=interrupt_active_verification,
            ):
                with self.assertRaisesRegex(
                    KeyboardInterrupt,
                    "interrupt after active preset publication",
                ):
                    presets.cmd_migrate_v1(args)

            self.assertEqual(reads, 5)
            self.assertEqual(source.read_bytes(), expected_active)
            self.assertEqual(load_preset("studio"), proposal)
            backups = list((home / "backups" / "presets").glob("studio.v1-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertNotEqual(source.stat().st_ino, backups[0].stat().st_ino)

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "requires descriptor-bound no-overwrite recovery",
    )
    def test_interrupt_recovery_never_overwrites_competing_active_preset(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, _proposal, fingerprint = presets._migration_material("studio")
            competing = b'{"competing":"active preset"}\n'
            original_read = _bounded_preset_descriptor_read
            reads = 0

            def race_then_interrupt(descriptor: int, *, name: str) -> bytes:
                nonlocal reads
                reads += 1
                if reads == 4:
                    source.write_bytes(competing)
                    source.chmod(0o600)
                    raise KeyboardInterrupt("interrupt with active preset racer")
                return original_read(descriptor, name=name)

            args = presets.build_parser().parse_args(
                ["migrate-v1", "studio", "--confirm", fingerprint]
            )
            with patch(
                "presets._bounded_preset_descriptor_read",
                side_effect=race_then_interrupt,
            ):
                with self.assertRaises(BananaError) as caught:
                    presets.cmd_migrate_v1(args)

            self.assertEqual(
                caught.exception.code,
                "preset_migration_recovery_failed",
            )
            self.assertEqual(
                caught.exception.details["interrupted_exception_type"],
                "KeyboardInterrupt",
            )
            recovery = caught.exception.details["migration_recovery"]
            self.assertFalse(recovery["migration_state_safe"])
            self.assertEqual(
                recovery["cleanup_status"],
                "backup_retained_active_entry_present",
            )
            self.assertEqual(source.read_bytes(), competing)
            backups = list((home / "backups" / "presets").glob("studio.v1-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)

    @staticmethod
    def crash_residue_path(home: Path, name: str = "studio") -> Path:
        backup_directory = home / "backups" / "presets"
        backup_directory.mkdir(parents=True, mode=0o700)
        return backup_directory / (
            f"{name}.v1-20260829T123456123456Z-0123456789ab-0123456789abcdef.json"
        )

    def test_missing_preset_with_migration_backup_fails_closed(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            backup = self.crash_residue_path(home)
            source.rename(backup)
            backup.chmod(0o600)

            with self.assertRaises(BananaError) as caught:
                load_preset("studio")

            self.assertEqual(
                caught.exception.code,
                "preset_migration_recovery_required",
            )
            details = caught.exception.details
            self.assertTrue(details["recovery_required"])
            self.assertEqual(details["preset_name"], "studio")
            self.assertFalse(details["active_preset_present"])
            self.assertFalse(details["automatic_restore_attempted"])
            self.assertTrue(details["inspection_complete"])
            self.assertTrue(details["backup_directory_path_binding_verified"])
            observed = details["observed_backup"]
            self.assertTrue(observed["regular_file"])
            self.assertEqual(
                (observed["device"], observed["inode"]),
                (backup.stat().st_dev, backup.stat().st_ino),
            )
            self.assertEqual(backup.read_bytes(), original)
            self.assertFalse(source.exists())

    def test_create_refuses_to_mask_missing_preset_migration_residue(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            backup = self.crash_residue_path(home)
            source.rename(backup)
            for extra_argument in ([], ["--force"]):
                with self.subTest(extra_argument=extra_argument):
                    args = presets.build_parser().parse_args(
                        [
                            "create",
                            "studio",
                            "--description",
                            "replacement",
                            *extra_argument,
                        ]
                    )
                    with self.assertRaises(BananaError) as caught:
                        presets.cmd_create(args)
                    self.assertEqual(
                        caught.exception.code,
                        "preset_migration_recovery_required",
                    )
            self.assertFalse(source.exists())
            self.assertEqual(backup.read_bytes(), original)

    def test_delete_refuses_to_mask_missing_preset_migration_residue(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            backup = self.crash_residue_path(home)
            source.rename(backup)
            backup.chmod(0o600)
            args = presets.build_parser().parse_args(["delete", "studio", "--confirm"])

            with self.assertRaises(BananaError) as caught:
                presets.cmd_delete(args)

            self.assertEqual(
                caught.exception.code,
                "preset_migration_recovery_required",
            )
            self.assertFalse(source.exists())
            self.assertEqual(backup.read_bytes(), original)

    def test_delete_missing_preset_without_residue_reports_not_found(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            source, _original = self.write_legacy(Path(directory))
            source.unlink()
            args = presets.build_parser().parse_args(["delete", "studio", "--confirm"])

            with self.assertRaises(BananaError) as caught:
                presets.cmd_delete(args)

            self.assertEqual(caught.exception.code, "preset_not_found")

    def test_delete_valid_active_preset_preserves_old_migration_backup(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
            patch("builtins.print"),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, proposal, _fingerprint = presets._migration_material("studio")
            backup = self.crash_residue_path(home)
            source.rename(backup)
            active = presets._serialized_preset(proposal)
            source.write_bytes(active)
            source.chmod(0o600)
            args = presets.build_parser().parse_args(["delete", "studio", "--confirm"])

            presets.cmd_delete(args)

            self.assertFalse(source.exists())
            self.assertEqual(backup.read_bytes(), original)
            deleted = list(
                (home / "backups" / "deleted-presets").glob("studio.deleted-*.json")
            )
            self.assertEqual(len(deleted), 1)
            self.assertEqual(deleted[0].read_bytes(), active)

    def test_residue_is_scoped_to_its_exact_preset_name(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            studio, original = self.write_legacy(home)
            backup = self.crash_residue_path(home)
            studio.rename(backup)
            args = presets.build_parser().parse_args(
                ["create", "portrait", "--description", "independent preset"]
            )

            with patch("builtins.print"):
                presets.cmd_create(args)

            self.assertEqual(
                load_preset("portrait")["description"],
                "independent preset",
            )
            with self.assertRaises(BananaError) as caught:
                load_preset("another-missing-preset")
            self.assertEqual(caught.exception.code, "preset_not_found")
            self.assertEqual(backup.read_bytes(), original)

    def test_valid_active_preset_is_unaffected_by_old_migration_backup(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            _path, _raw, proposal, _fingerprint = presets._migration_material("studio")
            backup = self.crash_residue_path(home)
            source.rename(backup)
            source.write_bytes(presets._serialized_preset(proposal))
            source.chmod(0o600)

            self.assertEqual(load_preset("studio"), proposal)
            self.assertEqual(backup.read_bytes(), original)

    def test_list_surfaces_missing_preset_migration_residue(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            backup = self.crash_residue_path(home)
            source.rename(backup)
            args = presets.build_parser().parse_args(["list"])

            with self.assertRaises(BananaError) as caught:
                presets.cmd_list(args)

            self.assertEqual(
                caught.exception.code,
                "preset_migration_recovery_required",
            )
            self.assertEqual(backup.read_bytes(), original)

    @unittest.skipIf(os.name == "nt", "directory symlink setup requires POSIX")
    def test_residue_guard_rejects_symlinked_backup_directory(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            root = Path(directory)
            source, original = self.write_legacy(root)
            outside = root / "outside-backups"
            outside.mkdir()
            outside_backup = (
                outside
                / self.crash_residue_path(
                    root,
                ).name
            )
            source.rename(outside_backup)
            backup_directory = root / "backups" / "presets"
            backup_directory.rmdir()
            backup_directory.symlink_to(outside, target_is_directory=True)

            with self.assertRaises(BananaError) as caught:
                load_preset("studio")

            self.assertEqual(
                caught.exception.code,
                "unsafe_preset_state_directory",
            )
            self.assertEqual(outside_backup.read_bytes(), original)

    @unittest.skipIf(os.name == "nt", "directory rename setup requires POSIX")
    def test_residue_guard_detects_backup_directory_swap(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
        ):
            home = Path(directory)
            source, original = self.write_legacy(home)
            backup = self.crash_residue_path(home)
            source.rename(backup)
            backup_directory = backup.parent
            held_directory = backup_directory.parent / "held-presets"
            original_binding_check = presets._preset_directory_binding_verified
            swapped = False

            def swap_before_backup_recheck(
                path: Path,
                descriptor: int | None,
                expected_identity: tuple[int, int],
            ) -> bool:
                nonlocal swapped
                if path == backup_directory and not swapped:
                    backup_directory.rename(held_directory)
                    backup_directory.mkdir(mode=0o700)
                    swapped = True
                return original_binding_check(path, descriptor, expected_identity)

            with patch(
                "presets._preset_directory_binding_verified",
                side_effect=swap_before_backup_recheck,
            ):
                with self.assertRaises(BananaError) as caught:
                    load_preset("studio")

            self.assertTrue(swapped)
            self.assertEqual(
                caught.exception.code,
                "unsafe_preset_state_directory",
            )
            self.assertEqual((held_directory / backup.name).read_bytes(), original)
            self.assertEqual(list(backup_directory.iterdir()), [])

    def test_residue_scan_limit_fails_closed_without_guessing(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"BANANA_HOME": directory}, clear=False),
            patch.object(presets, "MAX_PRESET_BACKUP_SCAN_ENTRIES", 2),
        ):
            home = Path(directory)
            (home / "presets").mkdir(parents=True)
            backup_directory = home / "backups" / "presets"
            backup_directory.mkdir(parents=True)
            for index in range(3):
                (backup_directory / f"unrelated-{index}.json").write_text("{}\n")

            with self.assertRaises(BananaError) as caught:
                load_preset("studio")

            self.assertEqual(
                caught.exception.code,
                "preset_migration_recovery_required",
            )
            self.assertFalse(caught.exception.details["inspection_complete"])
            self.assertEqual(
                caught.exception.details["inspection_status"],
                "backup_entry_limit_exceeded",
            )
            self.assertIsNone(caught.exception.details["observed_backup"])


if __name__ == "__main__":
    unittest.main()
