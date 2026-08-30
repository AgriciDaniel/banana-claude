from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests._support import run_python

import banana_core
import legacy_cleanup


class LegacyPublicInstallCleanupTests(unittest.TestCase):
    SYNTHETIC_KEY = "AI" + "za" + "SySyntheticBananaCleanupKeyNeverValid000000"

    @classmethod
    def legacy_server(cls) -> dict[str, Any]:
        return {
            "command": "npx",
            "args": ["-y", "@ycse/nanobanana-mcp"],
            "env": {
                "GOOGLE_AI_API_KEY": cls.SYNTHETIC_KEY,
                "NANOBANANA_MODEL": "gemini-3.1-flash-image-preview",
            },
        }

    @classmethod
    def write_settings(
        cls,
        home: Path,
        *,
        mode: int = 0o640,
        include_legacy: bool = True,
    ) -> tuple[Path, bytes, dict[str, Any]]:
        path = home / ".claude" / "settings.json"
        path.parent.mkdir(parents=True, mode=0o700)
        value: dict[str, Any] = {
            "theme": "dark",
            "permissions": {"allow": ["Read", "Bash(git status:*)"]},
            "mcpServers": {
                "unrelated-server": {
                    "command": "safe-command",
                    "args": ["--mode", "local"],
                }
            },
            "nested": {"preserve": [1, True, None, {"value": "exact"}]},
        }
        if include_legacy:
            value["mcpServers"]["nanobanana-mcp"] = cls.legacy_server()
        raw = (json.dumps(value, indent=3, ensure_ascii=False) + "\n").encode()
        path.write_bytes(raw)
        path.chmod(mode)
        return path, raw, value

    @staticmethod
    def write_legacy_skill(home: Path, name: str) -> tuple[Path, dict[str, bytes]]:
        path = home / ".claude" / "skills" / name
        path.mkdir(parents=True)
        version = "1.4.1" if name == "banana" else "2.1.0"
        layout = "banana-claude-v1.4.1" if name == "banana" else "nano-banana-v2.1.0"
        files = {
            relative: f"legacy public file: {relative}\n".encode()
            for relative in legacy_cleanup.LEGACY_LAYOUT_FILES[layout]
        }
        files["SKILL.md"] = (
            "---\n"
            f"name: {name}\n"
            "metadata:\n"
            f"  version: {version}\n"
            '  mcp-package: "@ycse/nanobanana-mcp"\n'
            "---\n"
        ).encode()
        files["scripts/setup_mcp.py"] = b"MCP_PACKAGE = '@ycse/nanobanana-mcp'\n"
        for relative, raw in files.items():
            (path / relative).parent.mkdir(parents=True, exist_ok=True)
            (path / relative).write_bytes(raw)
        return path, files

    def assert_no_synthetic_key(self, *values: str) -> None:
        for value in values:
            self.assertNotIn(self.SYNTHETIC_KEY, value)

    def test_scan_and_dry_run_detect_both_public_layouts_without_writes_or_key_echo(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings, raw, _value = self.write_settings(home)
            banana, _banana_files = self.write_legacy_skill(home, "banana")
            nano, _nano_files = self.write_legacy_skill(home, "nano-banana")

            scan = run_python(
                "legacy_cleanup.py",
                "scan",
                "--json",
                env={"HOME": directory},
            )
            dry_first = run_python(
                "legacy_cleanup.py",
                "remediate",
                "--dry-run",
                "--json",
                env={"HOME": directory},
            )
            dry_second = run_python(
                "legacy_cleanup.py",
                "remediate",
                "--dry-run",
                "--json",
                env={"HOME": directory},
            )

            self.assertEqual(scan.returncode, 0, scan.stderr)
            self.assertEqual(dry_first.returncode, 0, dry_first.stderr)
            self.assertEqual(dry_second.returncode, 0, dry_second.stderr)
            self.assert_no_synthetic_key(
                scan.stdout,
                scan.stderr,
                dry_first.stdout,
                dry_first.stderr,
                dry_second.stdout,
                dry_second.stderr,
            )
            payload = json.loads(scan.stdout)
            self.assertFalse(payload["clean"])
            self.assertTrue(payload["read_only"])
            self.assertTrue(payload["settings"]["legacy_mcp_server_detected"])
            self.assertTrue(payload["settings"]["embedded_credential_detected"])
            self.assertTrue(payload["credential_rotation_or_revocation_required"])
            layouts = {
                item["name"]: item["layout"]
                for item in payload["legacy_skill_locations"]
                if item["legacy_detected"]
            }
            self.assertEqual(
                layouts,
                {
                    "banana": "banana-claude-v1.4.1",
                    "nano-banana": "nano-banana-v2.1.0",
                },
            )
            first_review = json.loads(dry_first.stdout)
            second_review = json.loads(dry_second.stdout)
            self.assertEqual(first_review["fingerprint"], second_review["fingerprint"])
            self.assertEqual(len(first_review["fingerprint"]), 64)
            self.assertTrue(first_review["dry_run"])
            self.assertFalse(first_review["will_write"])
            self.assertEqual(len(first_review["proposed_actions"]), 3)
            self.assertEqual(settings.read_bytes(), raw)
            self.assertTrue(banana.is_dir())
            self.assertTrue(nano.is_dir())
            self.assertEqual(
                list((home / ".claude").glob("banana-legacy-*-backup-*")), []
            )

    def test_unrelated_same_name_skill_is_ambiguous_and_never_auto_moved(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"HOME": directory}, clear=False),
        ):
            home = Path(directory)
            self.write_settings(home, include_legacy=False)
            skill = home / ".claude" / "skills" / "banana"
            skill.mkdir(parents=True)
            original = b"---\nname: banana\n---\n# Unrelated local workflow\n"
            (skill / "SKILL.md").write_bytes(original)

            inspection = legacy_cleanup.inspect_state()
            candidate = next(
                item for item in inspection.skills if item.name == "banana"
            )
            self.assertEqual(candidate.status, "ambiguous_same_name_unmanaged")
            self.assertTrue(candidate.legacy_detected)
            self.assertFalse(candidate.safe_to_remediate)
            with self.assertRaises(legacy_cleanup.CleanupError) as caught:
                legacy_cleanup.dry_run_result(inspection)

            self.assertEqual(caught.exception.code, "unsafe_legacy_skill")
            self.assertEqual((skill / "SKILL.md").read_bytes(), original)
            self.assertTrue(skill.is_dir())

    def test_deeply_nested_known_credential_requires_rotation_without_value_echo(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            nested: dict[str, Any] = {
                "GOOGLE_AI_API_KEY": self.SYNTHETIC_KEY,
            }
            for index in range(24):
                nested = {f"wrapper_{index}": [nested]}
            settings.write_text(
                json.dumps(
                    {"mcpServers": {"nanobanana-mcp": nested}},
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            scan = run_python(
                "legacy_cleanup.py",
                "scan",
                "--json",
                env={"HOME": directory},
            )
            reviewed = run_python(
                "legacy_cleanup.py",
                "remediate",
                "--dry-run",
                "--json",
                env={"HOME": directory},
            )

            self.assertEqual(scan.returncode, 0, scan.stderr)
            self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
            scan_payload = json.loads(scan.stdout)
            review_payload = json.loads(reviewed.stdout)
            self.assertTrue(scan_payload["credential_rotation_or_revocation_required"])
            self.assertTrue(
                review_payload["credential_rotation_or_revocation_required"]
            )
            self.assert_no_synthetic_key(
                scan.stdout,
                scan.stderr,
                reviewed.stdout,
                reviewed.stderr,
            )

    def test_confirm_preserves_unrelated_settings_mode_and_private_exact_backups(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings, raw, original = self.write_settings(home, mode=0o640)
            banana, banana_files = self.write_legacy_skill(home, "banana")
            nano, nano_files = self.write_legacy_skill(home, "nano-banana")
            reviewed = run_python(
                "legacy_cleanup.py",
                "remediate",
                "--dry-run",
                "--json",
                env={"HOME": directory},
            )
            fingerprint = json.loads(reviewed.stdout)["fingerprint"]

            confirmed = run_python(
                "legacy_cleanup.py",
                "remediate",
                "--confirm",
                fingerprint,
                "--json",
                env={"HOME": directory},
            )
            self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
            self.assert_no_synthetic_key(confirmed.stdout, confirmed.stderr)
            result = json.loads(confirmed.stdout)
            self.assertTrue(result["changed"])
            self.assertTrue(result["clean"])
            self.assertEqual(result["moved_legacy_skills"], ["banana", "nano-banana"])
            self.assertTrue(result["credential_rotation_or_revocation_required"])
            self.assertFalse(result["local_cleanup_revokes_credential"])

            active = json.loads(settings.read_text(encoding="utf-8"))
            expected = json.loads(json.dumps(original))
            del expected["mcpServers"]["nanobanana-mcp"]
            self.assertEqual(active, expected)
            self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o640)

            settings_backup = Path(result["settings_backup"])
            self.assertEqual(settings_backup.read_bytes(), raw)
            self.assertEqual(stat.S_IMODE(settings_backup.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(settings_backup.parent.stat().st_mode), 0o700)

            skill_root = Path(result["skill_backup_root"])
            self.assertEqual(skill_root.parent, home / ".claude" / "skills")
            self.assertEqual(stat.S_IMODE(skill_root.stat().st_mode), 0o700)
            self.assertFalse(banana.exists())
            self.assertFalse(nano.exists())
            for name, files in (("banana", banana_files), ("nano-banana", nano_files)):
                recovered = skill_root / name
                self.assertTrue(recovered.is_dir())
                for relative, expected_raw in files.items():
                    self.assertEqual((recovered / relative).read_bytes(), expected_raw)

            clean_scan = run_python(
                "legacy_cleanup.py",
                "scan",
                "--json",
                env={"HOME": directory},
            )
            self.assertEqual(clean_scan.returncode, 0, clean_scan.stderr)
            clean_payload = json.loads(clean_scan.stdout)
            self.assertTrue(clean_payload["clean"])
            self.assertFalse(
                clean_payload["credential_rotation_or_revocation_required"]
            )

            repeated = run_python(
                "legacy_cleanup.py",
                "remediate",
                "--confirm",
                fingerprint,
                "--json",
                env={"HOME": directory},
            )
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            repeated_payload = json.loads(repeated.stdout)
            self.assertFalse(repeated_payload["changed"])
            self.assertTrue(repeated_payload["idempotent_noop"])
            self.assertEqual(settings_backup.read_bytes(), raw)

    def test_current_marker_makes_banana_managed_and_clean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            banana, _files = self.write_legacy_skill(home, "banana")
            (banana / ".banana-claude-install.json").write_text(
                '{"name":"banana-claude","version":"3.0.0"}\n',
                encoding="utf-8",
            )
            scan = run_python(
                "legacy_cleanup.py",
                "scan",
                "--json",
                env={"HOME": directory},
            )
            self.assertEqual(scan.returncode, 0, scan.stderr)
            payload = json.loads(scan.stdout)
            self.assertTrue(payload["clean"])
            banana_result = next(
                item
                for item in payload["legacy_skill_locations"]
                if item["name"] == "banana"
            )
            self.assertTrue(banana_result["managed"])
            self.assertEqual(banana_result["status"], "managed_current")
            self.assertFalse(banana_result["legacy_detected"])

    @unittest.skipUnless(os.name != "nt", "requires POSIX symbolic links")
    def test_symlinked_settings_and_skill_targets_are_reported_and_refused(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            claude = home / ".claude"
            skills = claude / "skills"
            skills.mkdir(parents=True)
            outside_settings = home / "outside-settings.json"
            outside_raw = (
                json.dumps({"mcpServers": {"nanobanana-mcp": self.legacy_server()}})
                + "\n"
            ).encode()
            outside_settings.write_bytes(outside_raw)
            (claude / "settings.json").symlink_to(outside_settings)
            outside_skill = home / "outside-skill"
            outside_skill.mkdir()
            (outside_skill / "SKILL.md").write_text("outside\n", encoding="utf-8")
            (skills / "banana").symlink_to(outside_skill, target_is_directory=True)

            scan = run_python(
                "legacy_cleanup.py",
                "scan",
                "--json",
                env={"HOME": directory},
            )
            refused = run_python(
                "legacy_cleanup.py",
                "remediate",
                "--dry-run",
                "--json",
                env={"HOME": directory},
            )
            self.assertEqual(scan.returncode, 0, scan.stderr)
            self.assertEqual(refused.returncode, 1)
            self.assertIn("unsafe_legacy_settings", refused.stderr)
            self.assert_no_synthetic_key(
                scan.stdout,
                scan.stderr,
                refused.stdout,
                refused.stderr,
            )
            payload = json.loads(scan.stdout)
            self.assertTrue(payload["remediation_blocked"])
            self.assertEqual(payload["settings"]["status"], "unsafe_symlink")
            self.assertEqual(outside_settings.read_bytes(), outside_raw)
            self.assertTrue((skills / "banana").is_symlink())
            self.assertEqual(
                (outside_skill / "SKILL.md").read_text(encoding="utf-8"),
                "outside\n",
            )

    def test_nonregular_oversized_and_hardlinked_settings_are_refused(self) -> None:
        cases = ("nonregular", "oversized", "hardlinked")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                settings = home / ".claude" / "settings.json"
                settings.parent.mkdir(parents=True)
                if case == "nonregular":
                    settings.mkdir()
                elif case == "oversized":
                    settings.write_bytes(b" " * (legacy_cleanup.MAX_SETTINGS_BYTES + 1))
                else:
                    raw = (
                        json.dumps(
                            {"mcpServers": {"nanobanana-mcp": self.legacy_server()}}
                        )
                        + "\n"
                    ).encode()
                    settings.write_bytes(raw)
                    os.link(settings, settings.parent / "settings-alias.json")

                refused = run_python(
                    "legacy_cleanup.py",
                    "remediate",
                    "--dry-run",
                    "--json",
                    env={"HOME": directory},
                )
                self.assertEqual(refused.returncode, 1)
                self.assertIn("unsafe_legacy_settings", refused.stderr)
                self.assert_no_synthetic_key(refused.stdout, refused.stderr)
                self.assertEqual(
                    list((home / ".claude").glob("banana-legacy-*-backup-*")), []
                )

    def test_non_directory_skill_target_is_refused_without_settings_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings, raw, _value = self.write_settings(home)
            target = home / ".claude" / "skills" / "banana"
            target.parent.mkdir(parents=True)
            target.write_text("not a directory\n", encoding="utf-8")
            refused = run_python(
                "legacy_cleanup.py",
                "remediate",
                "--dry-run",
                "--json",
                env={"HOME": directory},
            )
            self.assertEqual(refused.returncode, 1)
            self.assertIn("unsafe_legacy_skill", refused.stderr)
            self.assertEqual(settings.read_bytes(), raw)
            self.assertEqual(target.read_text(encoding="utf-8"), "not a directory\n")
            self.assert_no_synthetic_key(refused.stdout, refused.stderr)

    def test_changed_settings_after_review_are_refused_without_backup_or_overwrite(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings, _raw, value = self.write_settings(home)
            reviewed = run_python(
                "legacy_cleanup.py",
                "remediate",
                "--dry-run",
                "--json",
                env={"HOME": directory},
            )
            fingerprint = json.loads(reviewed.stdout)["fingerprint"]
            value["concurrent"] = "writer"
            changed = (json.dumps(value, indent=2) + "\n").encode()
            settings.write_bytes(changed)

            refused = run_python(
                "legacy_cleanup.py",
                "remediate",
                "--confirm",
                fingerprint,
                "--json",
                env={"HOME": directory},
            )
            self.assertEqual(refused.returncode, 1)
            self.assertIn("cleanup_confirmation_mismatch", refused.stderr)
            self.assertEqual(settings.read_bytes(), changed)
            self.assertEqual(
                list((home / ".claude").glob("banana-legacy-settings-backup-*")),
                [],
            )
            self.assert_no_synthetic_key(refused.stdout, refused.stderr)

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative publication",
    )
    def test_concurrent_settings_recreation_retains_identity_bound_skill_backup(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"HOME": directory}, clear=False),
        ):
            home = Path(directory)
            settings, original, _value = self.write_settings(home)
            banana, banana_files = self.write_legacy_skill(home, "banana")
            inspection = legacy_cleanup.inspect_state()
            fingerprint = legacy_cleanup._fingerprint(inspection)
            competing = b'{"owner":"concurrent settings writer"}\n'
            publish = legacy_cleanup._publish_exclusive_at

            def recreate_then_publish(
                directory_descriptor: int,
                directory_path: Path,
                name: str,
                data: bytes,
                mode: int,
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
                publish(directory_descriptor, directory_path, name, data, mode)

            with patch(
                "legacy_cleanup._publish_exclusive_at",
                side_effect=recreate_then_publish,
            ):
                with self.assertRaises(legacy_cleanup.CleanupError) as caught:
                    legacy_cleanup.remediate_confirmed(inspection, fingerprint)

            self.assertEqual(caught.exception.code, "cleanup_state_changed")
            self.assertEqual(settings.read_bytes(), competing)
            settings_backups = list(
                (home / ".claude").glob("banana-legacy-settings-backup-*/settings.json")
            )
            self.assertEqual(len(settings_backups), 1)
            self.assertEqual(settings_backups[0].read_bytes(), original)
            self.assertEqual(stat.S_IMODE(settings_backups[0].stat().st_mode), 0o600)
            self.assertFalse(caught.exception.details["settings_restore_complete"])
            self.assertEqual(
                Path(caught.exception.details["settings_recovery_backup"]),
                settings_backups[0],
            )
            self.assertFalse(banana.exists())
            skill_recovery = caught.exception.details["legacy_skill_recovery"]
            self.assertEqual(len(skill_recovery), 1)
            self.assertTrue(skill_recovery[0]["path_binding_verified"])
            recovery_root = Path(skill_recovery[0]["path"]).parent
            for relative, expected in banana_files.items():
                self.assertEqual(
                    (recovery_root / "banana" / relative).read_bytes(),
                    expected,
                )
            self.assertFalse(caught.exception.details["legacy_skill_cleanup_complete"])
            self.assertFalse(
                caught.exception.details["legacy_skill_automatic_restore_attempted"]
            )
            self.assertNotIn(self.SYNTHETIC_KEY, str(caught.exception))

    @unittest.skipUnless(
        sys.platform.startswith("linux") or sys.platform == "darwin",
        "atomic exclusive dirfd rename is supported on Linux and macOS",
    )
    def test_post_rename_failure_reports_published_identity_without_hardlinks(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            original_rename = banana_core._exclusive_rename_at

            def rename_then_fail(*args: Any, **kwargs: Any) -> None:
                original_rename(*args, **kwargs)
                raise OSError("synthetic post-rename failure")

            try:
                with (
                    patch(
                        "legacy_cleanup._exclusive_rename_at",
                        side_effect=rename_then_fail,
                    ),
                    patch.object(
                        os,
                        "link",
                        side_effect=AssertionError(
                            "settings publication must not use hard links"
                        ),
                    ),
                ):
                    with self.assertRaises(legacy_cleanup.CleanupError) as caught:
                        legacy_cleanup._publish_exclusive_at(
                            descriptor,
                            root,
                            legacy_cleanup.SETTINGS_NAME,
                            b"{}\n",
                            0o600,
                        )
            finally:
                os.close(descriptor)

            self.assertEqual(caught.exception.code, "settings_publication_failed")
            self.assertTrue(caught.exception.details["recovery_required"])
            self.assertEqual(
                Path(caught.exception.details["published_settings_path"]),
                root / legacy_cleanup.SETTINGS_NAME,
            )
            self.assertIn("published_settings_identity", caught.exception.details)
            self.assertEqual((root / legacy_cleanup.SETTINGS_NAME).stat().st_nlink, 1)
            self.assertEqual(list(root.glob(".*.tmp")), [])

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative skill moves",
    )
    def test_nested_skill_byte_race_after_review_is_retained_without_success(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"HOME": directory}, clear=False),
        ):
            home = Path(directory)
            banana, _files = self.write_legacy_skill(home, "banana")
            nested_file = banana / "references" / "models.md"
            raced_bytes = b"concurrent nested skill bytes\n"
            inspection = legacy_cleanup.inspect_state()
            fingerprint = legacy_cleanup._fingerprint(inspection)
            real_rename = banana_core._exclusive_rename_at
            mutated = False

            def mutate_before_move(
                source_directory: int,
                source_name: str,
                destination_directory: int,
                destination_name: str,
            ) -> None:
                nonlocal mutated
                if not mutated and source_name == "banana":
                    nested_file.write_bytes(raced_bytes)
                    mutated = True
                real_rename(
                    source_directory,
                    source_name,
                    destination_directory,
                    destination_name,
                )

            with (
                patch(
                    "legacy_cleanup._descriptor_operations_available",
                    return_value=True,
                ),
                patch(
                    "legacy_cleanup._exclusive_rename_at",
                    side_effect=mutate_before_move,
                ),
            ):
                with self.assertRaises(legacy_cleanup.CleanupError) as caught:
                    legacy_cleanup.remediate_confirmed(inspection, fingerprint)

            self.assertTrue(mutated)
            self.assertEqual(caught.exception.code, "cleanup_state_changed")
            self.assertFalse(banana.exists())
            recovery = caught.exception.details["legacy_skill_recovery"][0]
            self.assertTrue(recovery["path_binding_verified"])
            self.assertEqual(
                (Path(recovery["path"]) / "references" / "models.md").read_bytes(),
                raced_bytes,
            )

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative publication",
    )
    def test_settings_restore_failure_reports_the_exact_recovery_backup(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"HOME": directory}, clear=False),
        ):
            home = Path(directory)
            settings, original, _value = self.write_settings(home)
            inspection = legacy_cleanup.inspect_state()
            fingerprint = legacy_cleanup._fingerprint(inspection)

            def fail_publication(*_args: Any, **_kwargs: Any) -> None:
                raise legacy_cleanup.CleanupError(
                    "synthetic_publication_failure", "Synthetic safe failure."
                )

            with (
                patch(
                    "legacy_cleanup._publish_exclusive_at",
                    side_effect=fail_publication,
                ),
                patch(
                    "legacy_cleanup._restore_settings_copy_exclusive_at",
                    side_effect=OSError("synthetic restore failure"),
                ),
            ):
                with self.assertRaises(legacy_cleanup.CleanupError) as caught:
                    legacy_cleanup.remediate_confirmed(inspection, fingerprint)

            self.assertEqual(caught.exception.code, "synthetic_publication_failure")
            self.assertFalse(caught.exception.details["settings_restore_complete"])
            recovery = Path(caught.exception.details["settings_recovery_backup"])
            self.assertEqual(recovery.read_bytes(), original)
            self.assertEqual(stat.S_IMODE(recovery.stat().st_mode), 0o600)
            self.assertFalse(settings.exists())
            self.assert_no_synthetic_key(str(caught.exception), repr(caught.exception))

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative publication",
    )
    def test_failed_publication_restores_a_copy_without_moving_the_backup(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"HOME": directory}, clear=False),
        ):
            home = Path(directory)
            settings, original, _value = self.write_settings(home)
            inspection = legacy_cleanup.inspect_state()
            fingerprint = legacy_cleanup._fingerprint(inspection)
            publish = legacy_cleanup._publish_exclusive_at
            calls = 0

            def fail_once_then_publish(*args: Any, **kwargs: Any) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise legacy_cleanup.CleanupError(
                        "synthetic_publication_failure", "Synthetic safe failure."
                    )
                publish(*args, **kwargs)

            with patch(
                "legacy_cleanup._publish_exclusive_at",
                side_effect=fail_once_then_publish,
            ):
                with self.assertRaises(legacy_cleanup.CleanupError) as caught:
                    legacy_cleanup.remediate_confirmed(inspection, fingerprint)

            self.assertEqual(calls, 2)
            self.assertEqual(caught.exception.code, "synthetic_publication_failure")
            self.assertTrue(caught.exception.details["settings_restore_complete"])
            self.assertEqual(settings.read_bytes(), original)
            recovery = Path(caught.exception.details["settings_recovery_backup"])
            self.assertEqual(recovery.read_bytes(), original)
            self.assertEqual(stat.S_IMODE(recovery.stat().st_mode), 0o600)

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative publication",
    )
    def test_restore_never_overwrites_a_writer_arriving_after_failure(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"HOME": directory}, clear=False),
        ):
            home = Path(directory)
            settings, original, _value = self.write_settings(home)
            inspection = legacy_cleanup.inspect_state()
            fingerprint = legacy_cleanup._fingerprint(inspection)
            restore = legacy_cleanup._restore_settings_copy_exclusive_at
            competing = b'{"owner":"late concurrent writer"}\n'

            def fail_publication(*_args: Any, **_kwargs: Any) -> None:
                raise legacy_cleanup.CleanupError(
                    "synthetic_publication_failure", "Synthetic safe failure."
                )

            def create_competing_then_restore(*args: Any, **kwargs: Any) -> None:
                settings.write_bytes(competing)
                restore(*args, **kwargs)

            with (
                patch(
                    "legacy_cleanup._publish_exclusive_at",
                    side_effect=fail_publication,
                ),
                patch(
                    "legacy_cleanup._restore_settings_copy_exclusive_at",
                    side_effect=create_competing_then_restore,
                ),
            ):
                with self.assertRaises(legacy_cleanup.CleanupError) as caught:
                    legacy_cleanup.remediate_confirmed(inspection, fingerprint)

            self.assertEqual(caught.exception.code, "synthetic_publication_failure")
            self.assertFalse(caught.exception.details["settings_restore_complete"])
            self.assertEqual(
                caught.exception.details["settings_restore_recovery"]["error"],
                "legacy_settings_restore_blocked",
            )
            self.assertEqual(settings.read_bytes(), competing)
            recovery = Path(caught.exception.details["settings_recovery_backup"])
            self.assertEqual(recovery.read_bytes(), original)
            self.assertNotIn(self.SYNTHETIC_KEY, str(caught.exception))

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative publication",
    )
    def test_skill_retention_is_attached_to_the_original_error(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"HOME": directory}, clear=False),
        ):
            home = Path(directory)
            settings, original, _value = self.write_settings(home)
            banana, banana_files = self.write_legacy_skill(home, "banana")
            inspection = legacy_cleanup.inspect_state()
            fingerprint = legacy_cleanup._fingerprint(inspection)

            with patch(
                "legacy_cleanup._remediate_settings_at",
                side_effect=legacy_cleanup.CleanupError(
                    "synthetic_settings_failure", "Synthetic safe failure."
                ),
            ):
                with self.assertRaises(legacy_cleanup.CleanupError) as caught:
                    legacy_cleanup.remediate_confirmed(inspection, fingerprint)

            self.assertEqual(caught.exception.code, "synthetic_settings_failure")
            self.assertFalse(caught.exception.details["legacy_skill_cleanup_complete"])
            self.assertFalse(
                caught.exception.details["legacy_skill_automatic_restore_attempted"]
            )
            recovery = caught.exception.details["legacy_skill_recovery"][0]
            self.assertTrue(recovery["path_binding_verified"])
            recovery_root = Path(recovery["path"]).parent
            self.assertFalse(banana.exists())
            for relative, expected in banana_files.items():
                self.assertEqual(
                    (recovery_root / "banana" / relative).read_bytes(), expected
                )
            self.assertEqual(settings.read_bytes(), original)
            self.assert_no_synthetic_key(str(caught.exception), repr(caught.exception))

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative publication",
    )
    def test_later_failure_reports_the_committed_settings_backup_identity(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"HOME": directory}, clear=False),
        ):
            home = Path(directory)
            settings, original, value = self.write_settings(home)
            inspection = legacy_cleanup.inspect_state()
            fingerprint = legacy_cleanup._fingerprint(inspection)

            with patch(
                "legacy_cleanup.inspect_state",
                side_effect=[inspection, inspection],
            ):
                with self.assertRaises(legacy_cleanup.CleanupError) as caught:
                    legacy_cleanup.remediate_confirmed(inspection, fingerprint)

            self.assertEqual(caught.exception.code, "cleanup_state_changed")
            self.assertTrue(caught.exception.details["settings_cleanup_committed"])
            self.assertTrue(
                caught.exception.details["settings_cleanup_currently_verified"]
            )
            receipt = caught.exception.details["settings_backup"]
            self.assertTrue(receipt["path_binding_verified"])
            backup = Path(receipt["path"])
            self.assertEqual(backup.read_bytes(), original)
            active = json.loads(settings.read_text(encoding="utf-8"))
            self.assertNotIn("nanobanana-mcp", active["mcpServers"])
            self.assertEqual(active["theme"], value["theme"])

    @unittest.skipUnless(
        sys.platform.startswith("linux") or sys.platform == "darwin",
        "atomic exclusive dirfd rename is supported on Linux and macOS",
    )
    def test_skill_backup_claim_never_overwrites_a_competing_entry(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"HOME": directory}, clear=False),
        ):
            home = Path(directory)
            self.write_settings(home)
            banana, banana_files = self.write_legacy_skill(home, "banana")
            inspection = legacy_cleanup.inspect_state()
            fingerprint = legacy_cleanup._fingerprint(inspection)
            original_rename = banana_core._exclusive_rename_at
            created_competitor = False

            def create_competitor_then_rename(
                source_directory: int,
                source_name: str,
                destination_directory: int,
                destination_name: str,
            ) -> None:
                nonlocal created_competitor
                if not created_competitor:
                    os.mkdir(destination_name, dir_fd=destination_directory)
                    created_competitor = True
                original_rename(
                    source_directory,
                    source_name,
                    destination_directory,
                    destination_name,
                )

            with (
                patch(
                    "legacy_cleanup._remediate_settings_at",
                    side_effect=legacy_cleanup.CleanupError(
                        "synthetic_settings_failure",
                        "Synthetic safe failure.",
                    ),
                ),
                patch(
                    "legacy_cleanup._exclusive_rename_at",
                    side_effect=create_competitor_then_rename,
                ),
            ):
                with self.assertRaises(legacy_cleanup.CleanupError) as caught:
                    legacy_cleanup.remediate_confirmed(inspection, fingerprint)

            self.assertTrue(created_competitor)
            self.assertEqual(caught.exception.code, "legacy_cleanup_io_failed")
            self.assertTrue(banana.is_dir())
            recovery_root = next(
                (home / ".claude" / "skills").glob("banana-legacy-skills-backup-*")
            )
            self.assertTrue((recovery_root / "banana").is_dir())
            self.assertEqual(list((recovery_root / "banana").iterdir()), [])
            for relative, expected in banana_files.items():
                self.assertEqual(
                    (banana / relative).read_bytes(),
                    expected,
                )

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative skill moves",
    )
    def test_skill_recovery_reports_a_replaced_backup_entry_as_unbound(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"HOME": directory}, clear=False),
        ):
            home = Path(directory)
            self.write_settings(home)
            banana, banana_files = self.write_legacy_skill(home, "banana")
            inspection = legacy_cleanup.inspect_state()
            fingerprint = legacy_cleanup._fingerprint(inspection)
            recovery_root: Path | None = None

            def replace_backup_then_fail(*_args: Any, **_kwargs: Any) -> None:
                nonlocal recovery_root
                recovery_root = next(
                    (home / ".claude" / "skills").glob("banana-legacy-skills-backup-*")
                )
                (recovery_root / "banana").rename(recovery_root / "held-original")
                (recovery_root / "banana").mkdir()
                (recovery_root / "banana" / "owner.txt").write_text(
                    "replacement entry\n",
                    encoding="utf-8",
                )
                raise legacy_cleanup.CleanupError(
                    "synthetic_settings_failure",
                    "Synthetic safe failure.",
                )

            with patch(
                "legacy_cleanup._remediate_settings_at",
                side_effect=replace_backup_then_fail,
            ):
                with self.assertRaises(legacy_cleanup.CleanupError) as caught:
                    legacy_cleanup.remediate_confirmed(inspection, fingerprint)

            assert recovery_root is not None
            self.assertEqual(caught.exception.code, "synthetic_settings_failure")
            recovery = caught.exception.details["legacy_skill_recovery"][0]
            self.assertFalse(recovery["path_binding_verified"])
            self.assertTrue(recovery["path_unknown"])
            self.assertIsNone(recovery["path"])
            observed = recovery["observed_nonmatching_recovery_entry"]
            self.assertTrue(observed["path_binding_verified"])
            self.assertEqual(observed["path"], str(recovery_root / "banana"))
            self.assertFalse(banana.exists())
            self.assertEqual(
                (recovery_root / "banana" / "owner.txt").read_text(encoding="utf-8"),
                "replacement entry\n",
            )
            for relative, expected in banana_files.items():
                self.assertEqual(
                    (recovery_root / "held-original" / relative).read_bytes(),
                    expected,
                )

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative skill moves",
    )
    def test_skill_source_substitution_reports_both_directory_identities(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"HOME": directory}, clear=False),
        ):
            home = Path(directory)
            self.write_settings(home, include_legacy=False)
            banana, banana_files = self.write_legacy_skill(home, "banana")
            skills = banana.parent
            held_original = skills / "held-original"
            inspection = legacy_cleanup.inspect_state()
            fingerprint = legacy_cleanup._fingerprint(inspection)
            original_rename = banana_core._exclusive_rename_at
            foreign_inode: int | None = None
            substituted = False

            def substitute_source_then_rename(
                source_directory: int,
                source_name: str,
                destination_directory: int,
                destination_name: str,
            ) -> None:
                nonlocal foreign_inode, substituted
                if source_name == "banana" and not substituted:
                    banana.rename(held_original)
                    banana.mkdir()
                    (banana / "owner.txt").write_text(
                        "foreign directory\n",
                        encoding="utf-8",
                    )
                    foreign_inode = banana.stat().st_ino
                    substituted = True
                original_rename(
                    source_directory,
                    source_name,
                    destination_directory,
                    destination_name,
                )

            with patch(
                "legacy_cleanup._exclusive_rename_at",
                side_effect=substitute_source_then_rename,
            ):
                with self.assertRaises(legacy_cleanup.CleanupError) as caught:
                    legacy_cleanup.remediate_confirmed(inspection, fingerprint)

            self.assertEqual(caught.exception.code, "legacy_backup_failed")
            recovery = caught.exception.details["legacy_skill_recovery"][0]
            self.assertFalse(recovery["path_binding_verified"])
            observed = recovery["observed_nonmatching_recovery_entry"]
            self.assertTrue(observed["path_binding_verified"])
            self.assertEqual(observed["inode"], foreign_inode)
            self.assertEqual(
                Path(observed["path"])
                .joinpath("owner.txt")
                .read_text(encoding="utf-8"),
                "foreign directory\n",
            )
            for relative, expected in banana_files.items():
                self.assertEqual((held_original / relative).read_bytes(), expected)

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative settings moves",
    )
    def test_settings_source_substitution_never_mislabels_foreign_backup(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"HOME": directory}, clear=False),
        ):
            home = Path(directory)
            settings, original, _value = self.write_settings(home)
            inspection = legacy_cleanup.inspect_state()
            fingerprint = legacy_cleanup._fingerprint(inspection)
            original_rename = banana_core._exclusive_rename_at
            foreign = b'{"foreign":"settings"}\n'
            substituted = False

            def substitute_settings_then_rename(
                source_directory: int,
                source_name: str,
                destination_directory: int,
                destination_name: str,
            ) -> None:
                nonlocal substituted
                if source_name == legacy_cleanup.SETTINGS_NAME and not substituted:
                    replacement = settings.with_name("foreign-settings.json")
                    replacement.write_bytes(foreign)
                    replacement.chmod(settings.stat().st_mode)
                    os.replace(replacement, settings)
                    substituted = True
                original_rename(
                    source_directory,
                    source_name,
                    destination_directory,
                    destination_name,
                )

            with patch(
                "legacy_cleanup._exclusive_rename_at",
                side_effect=substitute_settings_then_rename,
            ):
                with self.assertRaises(legacy_cleanup.CleanupError) as caught:
                    legacy_cleanup.remediate_confirmed(inspection, fingerprint)

            self.assertEqual(caught.exception.code, "cleanup_state_changed")
            self.assertTrue(caught.exception.details["settings_restore_complete"])
            self.assertNotIn("settings_recovery_backup", caught.exception.details)
            intended = caught.exception.details["intended_settings_source"]
            self.assertFalse(intended["path_binding_verified"])
            self.assertTrue(intended["reviewed_bytes_restored_to_active"])
            observed = caught.exception.details["observed_settings_backup_entry"]
            self.assertTrue(observed["path_binding_verified"])
            self.assertFalse(observed["matches_reviewed_source"])
            self.assertEqual(Path(observed["path"]).read_bytes(), foreign)
            reviewed = caught.exception.details["settings_reviewed_recovery_copy"]
            self.assertTrue(reviewed["path_binding_verified"])
            self.assertTrue(reviewed["contains_exact_reviewed_bytes"])
            self.assertEqual(Path(reviewed["path"]).read_bytes(), original)
            self.assertEqual(settings.read_bytes(), original)

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative settings moves",
    )
    def test_interrupt_after_settings_claim_restores_exact_active_settings(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"HOME": directory}, clear=False),
        ):
            home = Path(directory)
            settings, original, _value = self.write_settings(home)
            inspection = legacy_cleanup.inspect_state()
            fingerprint = legacy_cleanup._fingerprint(inspection)
            interrupted = False

            def rename_then_interrupt(
                source_directory: int,
                source_name: str,
                destination_directory: int,
                destination_name: str,
            ) -> None:
                nonlocal interrupted
                banana_core._exclusive_rename_at(
                    source_directory,
                    source_name,
                    destination_directory,
                    destination_name,
                )
                if not interrupted and source_name == legacy_cleanup.SETTINGS_NAME:
                    interrupted = True
                    raise KeyboardInterrupt("interrupt after successful settings claim")

            with patch(
                "legacy_cleanup._exclusive_rename_at",
                side_effect=rename_then_interrupt,
            ):
                with self.assertRaisesRegex(
                    KeyboardInterrupt,
                    "interrupt after successful settings claim",
                ):
                    legacy_cleanup.remediate_confirmed(inspection, fingerprint)

            self.assertTrue(interrupted)
            self.assertEqual(settings.read_bytes(), original)
            backups = list(
                (home / ".claude").glob("banana-legacy-settings-backup-*/settings.json")
            )
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_DIRECTORY"),
        "requires descriptor-relative skill moves",
    )
    def test_interrupt_after_skill_move_restores_exact_active_skill(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"HOME": directory}, clear=False),
        ):
            home = Path(directory)
            self.write_settings(home, include_legacy=False)
            banana, original_files = self.write_legacy_skill(home, "banana")
            inspection = legacy_cleanup.inspect_state()
            fingerprint = legacy_cleanup._fingerprint(inspection)
            interrupted = False

            def rename_then_interrupt(
                source_directory: int,
                source_name: str,
                destination_directory: int,
                destination_name: str,
            ) -> None:
                nonlocal interrupted
                banana_core._exclusive_rename_at(
                    source_directory,
                    source_name,
                    destination_directory,
                    destination_name,
                )
                if not interrupted and source_name == "banana":
                    interrupted = True
                    raise KeyboardInterrupt("interrupt after successful skill move")

            with patch(
                "legacy_cleanup._exclusive_rename_at",
                side_effect=rename_then_interrupt,
            ):
                with self.assertRaisesRegex(
                    KeyboardInterrupt,
                    "interrupt after successful skill move",
                ):
                    legacy_cleanup.remediate_confirmed(inspection, fingerprint)

            self.assertTrue(interrupted)
            self.assertTrue(banana.is_dir())
            for relative, expected in original_files.items():
                self.assertEqual((banana / relative).read_bytes(), expected)
            backup_roots = list(banana.parent.glob("banana-legacy-skills-backup-*"))
            self.assertEqual(len(backup_roots), 1)
            self.assertFalse((backup_roots[0] / "banana").exists())


if __name__ == "__main__":
    unittest.main()
