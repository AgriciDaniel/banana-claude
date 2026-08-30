from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests._support import ROOT

from tools import installer_lifecycle


def run_installer(
    home: Path,
    *arguments: str,
    extra_environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    if extra_environment:
        environment.update(extra_environment)
    return subprocess.run(
        ["bash", str(ROOT / "install.sh"), *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


def stage_digest(path: Path) -> str:
    descriptor = os.open(path, installer_lifecycle._directory_flags())
    try:
        return installer_lifecycle._snapshot_digest(
            installer_lifecycle._snapshot_tree(descriptor)
        )
    finally:
        os.close(descriptor)


class InstallerTests(unittest.TestCase):
    def test_postpublication_interruptions_are_receipted_without_rollback(
        self,
    ) -> None:
        for interruption in (KeyboardInterrupt, lambda: SystemExit(17)):
            with self.subTest(interruption=interruption):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    install_root = root / "skills"
                    install_root.mkdir()
                    staged = install_root / ".banana-stage-test"
                    staged_identity, snapshot = installer_lifecycle.build_stage(
                        ROOT / "skills" / "banana",
                        staged,
                        ".banana-claude-install.json",
                        "3.0.0",
                        installer_lifecycle.directory_identity(install_root),
                    )
                    target = install_root / "banana"

                    with (
                        mock.patch(
                            "tools.installer_lifecycle.os.fsync",
                            side_effect=interruption(),
                        ),
                        self.assertRaises(
                            installer_lifecycle.PostPublicationInterrupted
                        ),
                    ):
                        installer_lifecycle.install_staged(
                            staged,
                            target,
                            ".banana-claude-install.json",
                            staged_identity,
                            installer_lifecycle.directory_identity(install_root),
                            installer_lifecycle.directory_identity(install_root),
                            snapshot,
                        )

                    self.assertFalse(staged.exists())
                    self.assertEqual(
                        installer_lifecycle.verify_installed(
                            target,
                            ".banana-claude-install.json",
                            staged_identity,
                            installer_lifecycle.directory_identity(install_root),
                            snapshot,
                        ),
                        staged_identity,
                    )

    def test_postpublication_move_interruptions_are_receipted_without_rollback(
        self,
    ) -> None:
        for interruption in (KeyboardInterrupt, lambda: SystemExit(17)):
            with self.subTest(interruption=interruption):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    source = root / "banana"
                    source.mkdir(mode=0o700)
                    (source / "SKILL.md").write_text(
                        "reviewed bytes\n", encoding="utf-8"
                    )
                    (source / ".banana-claude-install.json").write_text(
                        '{"name":"banana-claude","version":"3.0.0"}\n',
                        encoding="utf-8",
                    )
                    recovery = root / "recovery"
                    recovery.mkdir()
                    destination = recovery / "banana"
                    expected_identity = installer_lifecycle.managed_identity(
                        source, ".banana-claude-install.json"
                    )
                    source_parent_identity = installer_lifecycle.directory_identity(
                        root
                    )
                    destination_parent_identity = (
                        installer_lifecycle.directory_identity(recovery)
                    )

                    with (
                        mock.patch(
                            "tools.installer_lifecycle.os.fsync",
                            side_effect=interruption(),
                        ),
                        self.assertRaises(
                            installer_lifecycle.PostPublicationInterrupted
                        ),
                    ):
                        installer_lifecycle.move_verified_managed(
                            source,
                            destination,
                            ".banana-claude-install.json",
                            expected_identity,
                            source_parent_identity,
                            destination_parent_identity,
                        )

                    self.assertFalse(source.exists())
                    self.assertEqual(
                        installer_lifecycle.verify_managed_move(
                            source,
                            destination,
                            ".banana-claude-install.json",
                            expected_identity,
                            source_parent_identity,
                            destination_parent_identity,
                        ),
                        expected_identity,
                    )

    def test_managed_move_receipt_preserves_legacy_public_directory_mode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "banana"
            source.mkdir(mode=0o755)
            source.chmod(0o755)
            (source / "SKILL.md").write_text("reviewed bytes\n", encoding="utf-8")
            (source / ".banana-claude-install.json").write_text(
                '{"name":"banana-claude","version":"3.0.0"}\n',
                encoding="utf-8",
            )
            recovery = root / "recovery"
            recovery.mkdir()
            destination = recovery / "banana"
            expected_identity = installer_lifecycle.managed_identity(
                source, ".banana-claude-install.json"
            )
            parent_identity = installer_lifecycle.directory_identity(root)
            recovery_identity = installer_lifecycle.directory_identity(recovery)

            installer_lifecycle.move_verified_managed(
                source,
                destination,
                ".banana-claude-install.json",
                expected_identity,
                parent_identity,
                recovery_identity,
            )

            self.assertEqual(
                installer_lifecycle.verify_managed_move(
                    source,
                    destination,
                    ".banana-claude-install.json",
                    expected_identity,
                    parent_identity,
                    recovery_identity,
                ),
                expected_identity,
            )
            self.assertEqual(destination.stat().st_mode & 0o777, 0o755)

    def test_main_normalizes_signal_like_failures_without_tracebacks(self) -> None:
        for interruption, expected_status, expected_marker in (
            (KeyboardInterrupt(), 130, "installer_prepublication_interrupted"),
            (SystemExit(17), 1, "installer_prepublication_interrupted"),
            (
                installer_lifecycle.PostPublicationInterrupted(),
                1,
                "installer_postpublication_interrupted",
            ),
        ):
            with self.subTest(interruption=type(interruption).__name__):
                stderr = io.StringIO()
                with (
                    mock.patch.object(
                        installer_lifecycle,
                        "managed_identity",
                        side_effect=interruption,
                    ),
                    contextlib.redirect_stderr(stderr),
                ):
                    status = installer_lifecycle.main(
                        ["identity", "unused", ".banana-claude-install.json"]
                    )

                self.assertEqual(status, expected_status)
                self.assertEqual(stderr.getvalue(), f"{expected_marker}\n")

    def test_install_reinstall_and_recoverable_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            first = run_installer(home)
            self.assertEqual(first.returncode, 0, first.stderr)
            skill = home / ".claude" / "skills" / "banana"
            marker = skill / ".banana-claude-install.json"
            self.assertTrue((skill / "SKILL.md").is_file())
            self.assertFalse((home / ".banana").exists())
            self.assertEqual(
                json.loads(marker.read_text(encoding="utf-8"))["version"], "3.0.0"
            )
            self.assertTrue(os.access(skill / "scripts" / "generate.py", os.X_OK))
            expected_files = {
                Path(".banana-claude-install.json"),
                Path("SKILL.md"),
                *{
                    Path("references") / path.name
                    for path in (ROOT / "skills" / "banana" / "references").iterdir()
                    if path.is_file() and path.suffix in {".md", ".json"}
                },
                *{
                    Path("scripts") / path.name
                    for path in (ROOT / "skills" / "banana" / "scripts").glob("*.py")
                },
            }
            installed_files = {
                path.relative_to(skill) for path in skill.rglob("*") if path.is_file()
            }
            self.assertEqual(installed_files, expected_files)
            self.assertFalse(
                any("__pycache__" in path.parts for path in installed_files)
            )

            local_change = skill / "local-change.txt"
            local_change.write_text("recover me", encoding="utf-8")
            second = run_installer(home)
            self.assertEqual(second.returncode, 0, second.stderr)
            backups = list((home / ".claude" / "skills").glob("banana.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(
                (backups[0] / "local-change.txt").read_text(encoding="utf-8"),
                "recover me",
            )

            private_data = home / ".banana" / "presets" / "keep.json"
            private_data.parent.mkdir(parents=True)
            private_data.write_text("{}", encoding="utf-8")
            removed = run_installer(home, "--uninstall")
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertFalse(skill.exists())
            recoveries = list((home / ".claude" / "skills").glob("banana.removed-*"))
            self.assertEqual(len(recoveries), 1)
            self.assertTrue((recoveries[0] / "SKILL.md").is_file())
            self.assertTrue(private_data.is_file())

    def test_installer_never_touches_private_state_tree(self) -> None:
        scenarios = ("banana_symlink", "presets_symlink", "banana_file", "presets_file")
        for scenario in scenarios:
            with (
                self.subTest(scenario=scenario),
                tempfile.TemporaryDirectory() as directory,
            ):
                home = Path(directory)
                state = home / ".banana"
                victim = home / "external-state"
                victim.mkdir(mode=0o755)
                sentinel = victim / "sentinel.txt"
                sentinel.write_text("preserve", encoding="utf-8")

                if scenario == "banana_symlink":
                    state.symlink_to(victim, target_is_directory=True)
                elif scenario == "presets_symlink":
                    state.mkdir(mode=0o711)
                    (state / "presets").symlink_to(victim, target_is_directory=True)
                elif scenario == "banana_file":
                    state.write_text("not a directory", encoding="utf-8")
                    state.chmod(0o640)
                else:
                    state.mkdir(mode=0o711)
                    (state / "presets").write_text("not a directory", encoding="utf-8")
                    (state / "presets").chmod(0o640)

                state_mode = state.lstat().st_mode
                presets = state / "presets"
                presets_mode = presets.lstat().st_mode if presets.exists() else None
                victim_mode = victim.stat().st_mode

                installed = run_installer(home)
                self.assertEqual(installed.returncode, 0, installed.stderr)
                removed = run_installer(home, "--uninstall")
                self.assertEqual(removed.returncode, 0, removed.stderr)

                self.assertEqual(state.lstat().st_mode, state_mode)
                if presets_mode is not None:
                    self.assertEqual(presets.lstat().st_mode, presets_mode)
                self.assertEqual(victim.stat().st_mode, victim_mode)
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
                self.assertFalse((victim / "presets").exists())

    def test_concurrent_fresh_installs_leave_one_valid_active_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / ".claude" / "skills"
            root.mkdir(parents=True)
            environment = os.environ.copy()
            environment["HOME"] = str(home)
            processes = [
                subprocess.Popen(
                    ["bash", str(ROOT / "install.sh")],
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for _ in range(2)
            ]
            results = [process.communicate(timeout=20) for process in processes]
            return_codes = [process.returncode for process in processes]

            self.assertIn(0, return_codes, results)
            self.assertTrue(all(code in {0, 1} for code in return_codes), results)
            skill = root / "banana"
            self.assertTrue((skill / "SKILL.md").is_file())
            self.assertEqual(
                json.loads(
                    (skill / ".banana-claude-install.json").read_text(encoding="utf-8")
                )["name"],
                "banana-claude",
            )
            for retained in root.glob(".banana-stage-*"):
                self.assertTrue((retained / "SKILL.md").is_file())
            self.assertFalse((root / ".banana-install.lock").exists())

    def test_no_replace_install_race_preserves_both_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = root / "stage" / "banana"
            staged.mkdir(parents=True)
            staged.chmod(0o700)
            (staged / "SKILL.md").write_text("reviewed bytes\n", encoding="utf-8")
            (staged / ".banana-claude-install.json").write_text(
                '{"name":"banana-claude","version":"3.0.0"}\n',
                encoding="utf-8",
            )
            install_root = root / "skills"
            install_root.mkdir()
            target = install_root / "banana"
            real_move = installer_lifecycle._rename_no_replace
            injected = False

            def add_concurrent_target(*args: Any, **kwargs: Any) -> None:
                nonlocal injected
                if not injected:
                    injected = True
                    target.mkdir()
                    (target / "owner.txt").write_text(
                        "concurrent owner\n", encoding="utf-8"
                    )
                real_move(*args, **kwargs)

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_rename_no_replace",
                    side_effect=add_concurrent_target,
                ),
                self.assertRaises(OSError),
            ):
                installer_lifecycle.install_staged(
                    staged,
                    target,
                    ".banana-claude-install.json",
                    installer_lifecycle.directory_identity(staged),
                    installer_lifecycle.directory_identity(staged.parent),
                    installer_lifecycle.directory_identity(install_root),
                    stage_digest(staged),
                )

            self.assertTrue(injected)
            self.assertEqual(
                (target / "owner.txt").read_text(encoding="utf-8"),
                "concurrent owner\n",
            )
            self.assertEqual(
                (staged / "SKILL.md").read_text(encoding="utf-8"),
                "reviewed bytes\n",
            )

    def test_stage_builder_never_populates_a_swapped_public_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            install_root = Path(directory) / "skills"
            install_root.mkdir()
            staged = install_root / ".banana-stage-test"
            held = install_root / ".banana-stage-test.builder-held"
            real_copy = installer_lifecycle._copy_regular_at
            swapped = False

            def swap_stage_before_copy(*args: Any, **kwargs: Any) -> None:
                nonlocal swapped
                if not swapped:
                    swapped = True
                    staged.rename(held)
                    staged.mkdir()
                    (staged / "owner.txt").write_text(
                        "concurrent owner\n", encoding="utf-8"
                    )
                real_copy(*args, **kwargs)

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_copy_regular_at",
                    side_effect=swap_stage_before_copy,
                ),
                self.assertRaises(installer_lifecycle.LifecycleError),
            ):
                installer_lifecycle.build_stage(
                    ROOT / "skills" / "banana",
                    staged,
                    ".banana-claude-install.json",
                    "3.0.0",
                    installer_lifecycle.directory_identity(install_root),
                )

            self.assertTrue(swapped)
            self.assertEqual(list(staged.iterdir()), [staged / "owner.txt"])
            self.assertTrue((held / "SKILL.md").is_file())

    def test_stage_builder_rejects_pre_receipt_byte_and_inventory_tampering(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            install_root = Path(directory) / "skills"
            install_root.mkdir()
            staged = install_root / ".banana-stage-test"
            real_snapshot = installer_lifecycle._snapshot_tree
            injected = False

            def tamper_before_receipt(descriptor: int) -> Any:
                nonlocal injected
                if not injected:
                    injected = True
                    (staged / "scripts" / "generate.py").write_text(
                        "print('foreign')\n", encoding="utf-8"
                    )
                    (staged / "scripts" / "foreign.py").write_text(
                        "print('extra')\n", encoding="utf-8"
                    )
                return real_snapshot(descriptor)

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_snapshot_tree",
                    side_effect=tamper_before_receipt,
                ),
                self.assertRaises(installer_lifecycle.LifecycleError),
            ):
                installer_lifecycle.build_stage(
                    ROOT / "skills" / "banana",
                    staged,
                    ".banana-claude-install.json",
                    "3.0.0",
                    installer_lifecycle.directory_identity(install_root),
                )

            self.assertTrue(injected)
            self.assertEqual(
                (staged / "scripts" / "generate.py").read_text(encoding="utf-8"),
                "print('foreign')\n",
            )
            self.assertTrue((staged / "scripts" / "foreign.py").is_file())

    def test_stage_builder_requires_every_declared_runtime_file(self) -> None:
        for scenario in ("missing", "symlink"):
            with (
                self.subTest(scenario=scenario),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                source = root / "source"
                shutil.copytree(ROOT / "skills" / "banana", source)
                required = source / "scripts" / "banana_core.py"
                if scenario == "missing":
                    required.unlink()
                else:
                    required.unlink()
                    required.symlink_to(root / "outside-runtime.py")
                    (root / "outside-runtime.py").write_text(
                        "outside bytes\n",
                        encoding="utf-8",
                    )
                install_root = root / "install"
                install_root.mkdir()
                staged = install_root / ".banana-stage-test"

                with self.assertRaises(installer_lifecycle.LifecycleError):
                    installer_lifecycle.build_stage(
                        source,
                        staged,
                        ".banana-claude-install.json",
                        "3.0.0",
                        installer_lifecycle.directory_identity(install_root),
                    )

                self.assertFalse((staged / "scripts" / "banana_core.py").exists())

    def test_stage_builder_rejects_unmanaged_allowlisted_suffix_files(self) -> None:
        for selected_directory, extra_name in (
            ("scripts", "unmanaged_runtime.py"),
            ("references", "unmanaged_reference.md"),
            ("references", "unmanaged_catalog.json"),
        ):
            with (
                self.subTest(
                    selected_directory=selected_directory,
                    extra_name=extra_name,
                ),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                source = root / "source"
                shutil.copytree(ROOT / "skills" / "banana", source)
                extra = source / selected_directory / extra_name
                extra.write_text("unmanaged source entry\n", encoding="utf-8")
                install_root = root / "install"
                install_root.mkdir()
                staged = install_root / ".banana-stage-test"

                with self.assertRaises(installer_lifecycle.LifecycleError):
                    installer_lifecycle.build_stage(
                        source,
                        staged,
                        ".banana-claude-install.json",
                        "3.0.0",
                        installer_lifecycle.directory_identity(install_root),
                    )

                self.assertEqual(
                    extra.read_text(encoding="utf-8"),
                    "unmanaged source entry\n",
                )
                self.assertFalse((staged / selected_directory / extra_name).exists())

    def test_stage_builder_rejects_unmanaged_root_entries(self) -> None:
        for extra_name, is_directory in (
            ("unmanaged-root.txt", False),
            ("unmanaged-root", True),
        ):
            with (
                self.subTest(extra_name=extra_name),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                source = root / "source"
                shutil.copytree(ROOT / "skills" / "banana", source)
                extra = source / extra_name
                if is_directory:
                    extra.mkdir()
                else:
                    extra.write_text("unmanaged source entry\n", encoding="utf-8")
                install_root = root / "install"
                install_root.mkdir()
                staged = install_root / ".banana-stage-test"

                with self.assertRaises(installer_lifecycle.LifecycleError):
                    installer_lifecycle.build_stage(
                        source,
                        staged,
                        ".banana-claude-install.json",
                        "3.0.0",
                        installer_lifecycle.directory_identity(install_root),
                    )

                self.assertTrue(extra.exists())
                self.assertFalse(staged.exists())

    def test_stage_builder_rejects_a_required_source_type_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            shutil.copytree(ROOT / "skills" / "banana", source)
            install_root = root / "install"
            install_root.mkdir()
            staged = install_root / ".banana-stage-test"
            required = source / "scripts" / "banana_core.py"
            held = source / "scripts" / "banana_core.py.held"
            outside = root / "outside-runtime.py"
            outside.write_text("outside bytes\n", encoding="utf-8")
            real_copy = installer_lifecycle._copy_regular_at
            swapped = False

            def swap_before_copy(*args: Any, **kwargs: Any) -> Any:
                nonlocal swapped
                if not swapped and args[2] == "banana_core.py":
                    required.rename(held)
                    required.symlink_to(outside)
                    swapped = True
                return real_copy(*args, **kwargs)

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_copy_regular_at",
                    side_effect=swap_before_copy,
                ),
                self.assertRaises(installer_lifecycle.LifecycleError),
            ):
                installer_lifecycle.build_stage(
                    source,
                    staged,
                    ".banana-claude-install.json",
                    "3.0.0",
                    installer_lifecycle.directory_identity(install_root),
                )

            self.assertTrue(swapped)
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside bytes\n")

    def test_stage_builder_rejects_source_leaf_replacement_after_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            shutil.copytree(ROOT / "skills" / "banana", source)
            install_root = root / "install"
            install_root.mkdir()
            staged = install_root / ".banana-stage-test"
            selected = source / "scripts" / "generate.py"
            held = source / "scripts" / "generate.py.reviewed"
            original = selected.read_bytes()
            foreign = b"print('after-copy replacement')\n"
            real_revalidate = installer_lifecycle._revalidate_source_manifest
            replaced = False

            def replace_before_final_source_receipt(*args: Any, **kwargs: Any) -> None:
                nonlocal replaced
                if not replaced:
                    selected.rename(held)
                    selected.write_bytes(foreign)
                    replaced = True
                real_revalidate(*args, **kwargs)

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_revalidate_source_manifest",
                    side_effect=replace_before_final_source_receipt,
                ),
                self.assertRaises(installer_lifecycle.LifecycleError),
            ):
                installer_lifecycle.build_stage(
                    source,
                    staged,
                    ".banana-claude-install.json",
                    "3.0.0",
                    installer_lifecycle.directory_identity(install_root),
                )

            self.assertTrue(replaced)
            self.assertEqual(selected.read_bytes(), foreign)
            self.assertEqual(held.read_bytes(), original)
            self.assertEqual(
                (staged / "scripts" / "generate.py").read_bytes(),
                original,
            )

    def test_stage_builder_rejects_private_root_mode_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            install_root = Path(directory) / "skills"
            install_root.mkdir()
            staged = install_root / ".banana-stage-test"
            real_snapshot = installer_lifecycle._snapshot_tree
            changed = False

            def change_mode_before_receipt(descriptor: int) -> Any:
                nonlocal changed
                if not changed:
                    changed = True
                    staged.chmod(0o777)
                return real_snapshot(descriptor)

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_snapshot_tree",
                    side_effect=change_mode_before_receipt,
                ),
                self.assertRaises(installer_lifecycle.LifecycleError),
            ):
                installer_lifecycle.build_stage(
                    ROOT / "skills" / "banana",
                    staged,
                    ".banana-claude-install.json",
                    "3.0.0",
                    installer_lifecycle.directory_identity(install_root),
                )

            self.assertTrue(changed)
            self.assertEqual(staged.stat().st_mode & 0o777, 0o777)

    def test_install_rejects_a_stage_changed_after_its_build_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            install_root = Path(directory) / "skills"
            install_root.mkdir()
            staged = install_root / ".banana-stage-test"
            target = install_root / "banana"
            identity, digest = installer_lifecycle.build_stage(
                ROOT / "skills" / "banana",
                staged,
                ".banana-claude-install.json",
                "3.0.0",
                installer_lifecycle.directory_identity(install_root),
            )
            (staged / "SKILL.md").write_text("changed bytes\n", encoding="utf-8")

            with self.assertRaises(installer_lifecycle.LifecycleError):
                installer_lifecycle.install_staged(
                    staged,
                    target,
                    ".banana-claude-install.json",
                    identity,
                    installer_lifecycle.directory_identity(install_root),
                    installer_lifecycle.directory_identity(install_root),
                    digest,
                )

            self.assertFalse(target.exists())
            self.assertEqual(
                (staged / "SKILL.md").read_text(encoding="utf-8"),
                "changed bytes\n",
            )

    def test_unowned_skill_is_never_overwritten_or_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            skill = home / ".claude" / "skills" / "banana"
            skill.mkdir(parents=True)
            sentinel = skill / "owner.txt"
            sentinel.write_text("user-owned", encoding="utf-8")

            install = run_installer(home)
            self.assertEqual(install.returncode, 1)
            self.assertIn("Refusing to overwrite", install.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "user-owned")

            uninstall = run_installer(home, "--uninstall")
            self.assertEqual(uninstall.returncode, 1)
            self.assertIn("Refusing to remove", uninstall.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "user-owned")

    def test_invalid_ownership_marker_is_never_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            skill = home / ".claude" / "skills" / "banana"
            skill.mkdir(parents=True)
            sentinel = skill / "owner.txt"
            sentinel.write_text("user-owned", encoding="utf-8")
            (skill / ".banana-claude-install.json").write_text(
                '{"name":"not-banana","version":"3.0.0"}\n',
                encoding="utf-8",
            )

            install = run_installer(home)
            self.assertEqual(install.returncode, 1)
            self.assertIn("valid Banana ownership marker", install.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "user-owned")

            uninstall = run_installer(home, "--uninstall")
            self.assertEqual(uninstall.returncode, 1)
            self.assertIn("valid Banana ownership marker", uninstall.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "user-owned")

    def test_failed_reinstall_retains_previous_managed_skill_for_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            first = run_installer(home)
            self.assertEqual(first.returncode, 0, first.stderr)
            root = home / ".claude" / "skills"
            skill = root / "banana"
            sentinel = skill / "local-change.txt"
            sentinel.write_text("restore me", encoding="utf-8")

            real_python = shutil.which("python3")
            self.assertIsNotNone(real_python)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                'if [[ "${2:-}" == "install" '
                '&& "${3:-}" == *"/.banana-stage-"* '
                '&& "${4:-}" == */.claude/skills/banana ]]; then\n'
                "  exit 71\n"
                "fi\n"
                f'exec "{real_python}" "$@"\n',
                encoding="utf-8",
            )
            fake_python.chmod(0o700)

            failed = run_installer(
                home,
                extra_environment={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
            )
            self.assertEqual(failed.returncode, 1, failed.stderr)
            self.assertIn("previous managed skill recovery candidate", failed.stderr)
            self.assertFalse(skill.exists())
            self.assertFalse((root / ".banana-install.lock").exists())
            retained_stages = list(root.glob(".banana-stage-*"))
            self.assertEqual(len(retained_stages), 1)
            self.assertTrue((retained_stages[0] / "SKILL.md").is_file())
            backups = list(root.glob("banana.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(
                (backups[0] / "local-change.txt").read_text(encoding="utf-8"),
                "restore me",
            )
            self.assertTrue((backups[0] / ".banana-claude-install.json").is_file())

    def test_lost_helper_success_is_recovered_only_by_the_complete_receipt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            real_python = shutil.which("python3")
            self.assertIsNotNone(real_python)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                'if [[ "${2:-}" == "install" ]]; then\n'
                f'  "{real_python}" "$@"\n'
                "  status=$?\n"
                '  if [[ "${status}" -eq 0 ]]; then exit 71; fi\n'
                '  exit "${status}"\n'
                "fi\n"
                f'exec "{real_python}" "$@"\n',
                encoding="utf-8",
            )
            fake_python.chmod(0o700)

            result = run_installer(
                home,
                extra_environment={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
            )

            skill = home / ".claude" / "skills" / "banana"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("complete install receipt was reverified", result.stderr)
            self.assertIn("Installed the standalone", result.stdout)
            self.assertTrue((skill / "scripts" / "generate.py").is_file())
            self.assertEqual(
                list((home / ".claude" / "skills").glob(".banana-stage-*")), []
            )

    def test_lost_move_helper_status_is_reverified_before_uninstall_success(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            installed = run_installer(home)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            real_python = shutil.which("python3")
            self.assertIsNotNone(real_python)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                'if [[ "${2:-}" == "move" ]]; then\n'
                f'  "{real_python}" "$@"\n'
                "  status=$?\n"
                '  if [[ "${status}" -eq 0 ]]; then exit 71; fi\n'
                '  exit "${status}"\n'
                "fi\n"
                f'exec "{real_python}" "$@"\n',
                encoding="utf-8",
            )
            fake_python.chmod(0o700)

            result = run_installer(
                home,
                "--uninstall",
                extra_environment={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
            )

            root = home / ".claude" / "skills"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("complete move receipt was reverified", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((root / "banana").exists())
            recoveries = list(root.glob("banana.removed-*"))
            self.assertEqual(len(recoveries), 1)
            self.assertTrue((recoveries[0] / "SKILL.md").is_file())

    def test_shell_final_acceptance_rejects_nested_byte_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            real_python = shutil.which("python3")
            self.assertIsNotNone(real_python)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                'if [[ "${2:-}" == "verify-install" ]]; then\n'
                '  printf "print(\\\'foreign\\\')\\n" > "$3/scripts/generate.py"\n'
                "fi\n"
                f'exec "{real_python}" "$@"\n',
                encoding="utf-8",
            )
            fake_python.chmod(0o700)

            result = run_installer(
                home,
                extra_environment={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
            )

            skill = home / ".claude" / "skills" / "banana"
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn("Installed the standalone", result.stdout)
            self.assertIn("complete receipt changed", result.stderr)
            self.assertEqual(
                (skill / "scripts" / "generate.py").read_text(encoding="utf-8"),
                "print('foreign')\n",
            )

    def test_target_appearing_during_install_is_preserved_without_false_success(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / ".claude" / "skills"
            real_python = shutil.which("python3")
            self.assertIsNotNone(real_python)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                'if [[ "${2:-}" == "install" '
                '&& "${4:-}" == */.claude/skills/banana ]]; then\n'
                '  mkdir -- "$4"\n'
                '  printf "concurrent owner\\n" > "$4/owner.txt"\n'
                "fi\n"
                f'exec "{real_python}" "$@"\n',
                encoding="utf-8",
            )
            fake_python.chmod(0o700)

            result = run_installer(
                home,
                extra_environment={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
            )

            target = root / "banana"
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn("Installed the standalone", result.stdout)
            self.assertEqual(
                (target / "owner.txt").read_text(encoding="utf-8"),
                "concurrent owner\n",
            )
            self.assertFalse((target / "banana").exists())
            self.assertFalse((target / "SKILL.md").exists())
            retained_stages = list(root.glob(".banana-stage-*"))
            self.assertEqual(len(retained_stages), 1)
            self.assertTrue((retained_stages[0] / "SKILL.md").is_file())

    def test_dangling_symlink_target_is_retained_and_disclosed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / ".claude" / "skills"
            real_python = shutil.which("python3")
            self.assertIsNotNone(real_python)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                'if [[ "${2:-}" == "install" ]]; then\n'
                '  ln -s "missing-target" "$4"\n'
                "fi\n"
                f'exec "{real_python}" "$@"\n',
                encoding="utf-8",
            )
            fake_python.chmod(0o700)

            result = run_installer(
                home,
                extra_environment={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
            )

            target = root / "banana"
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertTrue(target.is_symlink())
            self.assertEqual(os.readlink(target), "missing-target")
            self.assertIn("Unresolved install target retained at", result.stderr)
            retained_stages = list(root.glob(".banana-stage-*"))
            self.assertEqual(len(retained_stages), 1)
            self.assertTrue((retained_stages[0] / "SKILL.md").is_file())

    def test_uninstall_refuses_a_valid_marker_replacement_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            installed = run_installer(home)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            root = home / ".claude" / "skills"
            skill = root / "banana"
            held = root / "banana.concurrent-held"
            real_python = shutil.which("python3")
            self.assertIsNotNone(real_python)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                'if [[ "${2:-}" == "move" '
                '&& "${3:-}" == */.claude/skills/banana '
                '&& "${4:-}" == *"banana.removed-"* ]]; then\n'
                '  mv -- "$3" "${3}.concurrent-held"\n'
                '  mkdir -- "$3"\n'
                '  printf "concurrent owner\\n" > "$3/owner.txt"\n'
                '  printf \'{"name":"banana-claude","version":"3.0.0"}\\n\' '
                '> "$3/.banana-claude-install.json"\n'
                "fi\n"
                f'exec "{real_python}" "$@"\n',
                encoding="utf-8",
            )
            fake_python.chmod(0o700)

            result = run_installer(
                home,
                "--uninstall",
                extra_environment={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
            )

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("changed during uninstall", result.stderr)
            self.assertEqual(
                (skill / "owner.txt").read_text(encoding="utf-8"),
                "concurrent owner\n",
            )
            self.assertTrue((held / "SKILL.md").is_file())
            self.assertNotIn("Moved the standalone skill", result.stdout)
            self.assertEqual(list(root.glob("banana.removed-*")), [])

    def test_uninstall_discloses_a_racing_dangling_recovery_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            installed = run_installer(home)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            root = home / ".claude" / "skills"
            skill = root / "banana"
            real_python = shutil.which("python3")
            self.assertIsNotNone(real_python)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                'if [[ "${2:-}" == "move" '
                '&& "${3:-}" == */.claude/skills/banana '
                '&& "${4:-}" == */banana.removed-* ]]; then\n'
                '  ln -s "missing-recovery" "$4"\n'
                "fi\n"
                f'exec "{real_python}" "$@"\n',
                encoding="utf-8",
            )
            fake_python.chmod(0o700)

            result = run_installer(
                home,
                "--uninstall",
                extra_environment={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
            )

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertTrue((skill / "SKILL.md").is_file())
            self.assertIn("inspect the recovery candidate at", result.stderr)
            retained = list(root.glob("banana.removed-*"))
            self.assertEqual(len(retained), 1)
            self.assertTrue(retained[0].is_symlink())
            self.assertEqual(os.readlink(retained[0]), "missing-recovery")

    def test_managed_move_never_rolls_a_foreign_source_replacement_back(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "banana"
            source.mkdir()
            (source / "SKILL.md").write_text("reviewed bytes\n", encoding="utf-8")
            (source / ".banana-claude-install.json").write_text(
                '{"name":"banana-claude","version":"3.0.0"}\n',
                encoding="utf-8",
            )
            recovery = root / "recovery"
            recovery.mkdir()
            destination = recovery / "banana"
            held = root / "banana.concurrent-held"
            expected_identity = installer_lifecycle.managed_identity(
                source,
                ".banana-claude-install.json",
            )
            source_parent_identity = installer_lifecycle.directory_identity(root)
            destination_parent_identity = installer_lifecycle.directory_identity(
                recovery
            )
            real_rename = os.rename
            real_move = installer_lifecycle._rename_no_replace
            raced = False

            def race_before_move(*args: Any, **kwargs: Any) -> None:
                nonlocal raced
                if not raced:
                    raced = True
                    real_rename(source, held)
                    source.mkdir()
                    (source / "owner.txt").write_text(
                        "concurrent owner\n",
                        encoding="utf-8",
                    )
                    (source / ".banana-claude-install.json").write_text(
                        '{"name":"banana-claude","version":"3.0.0"}\n',
                        encoding="utf-8",
                    )
                real_move(*args, **kwargs)

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_rename_no_replace",
                    side_effect=race_before_move,
                ),
                self.assertRaises(installer_lifecycle.LifecycleError),
            ):
                installer_lifecycle.move_verified_managed(
                    source,
                    destination,
                    ".banana-claude-install.json",
                    expected_identity,
                    source_parent_identity,
                    destination_parent_identity,
                )

            self.assertEqual(
                (destination / "owner.txt").read_text(encoding="utf-8"),
                "concurrent owner\n",
            )
            self.assertEqual(
                (held / "SKILL.md").read_text(encoding="utf-8"),
                "reviewed bytes\n",
            )
            self.assertFalse(source.exists())

    def test_managed_move_never_rolls_a_foreign_destination_into_source(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "banana"
            source.mkdir()
            (source / "SKILL.md").write_text("reviewed bytes\n", encoding="utf-8")
            (source / ".banana-claude-install.json").write_text(
                '{"name":"banana-claude","version":"3.0.0"}\n',
                encoding="utf-8",
            )
            recovery = root / "recovery"
            recovery.mkdir()
            destination = recovery / "banana"
            held_destination = recovery / "banana.installer-held"
            real_move = installer_lifecycle._rename_no_replace

            def replace_destination_after_move(*args: Any, **kwargs: Any) -> None:
                real_move(*args, **kwargs)
                destination.rename(held_destination)
                destination.mkdir()
                (destination / "owner.txt").write_text(
                    "concurrent owner\n", encoding="utf-8"
                )
                (destination / ".banana-claude-install.json").write_text(
                    '{"name":"banana-claude","version":"3.0.0"}\n',
                    encoding="utf-8",
                )

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_rename_no_replace",
                    side_effect=replace_destination_after_move,
                ),
                self.assertRaises(installer_lifecycle.LifecycleError),
            ):
                installer_lifecycle.move_verified_managed(
                    source,
                    destination,
                    ".banana-claude-install.json",
                    installer_lifecycle.managed_identity(
                        source, ".banana-claude-install.json"
                    ),
                    installer_lifecycle.directory_identity(root),
                    installer_lifecycle.directory_identity(recovery),
                )

            self.assertFalse(source.exists())
            self.assertEqual(
                (destination / "owner.txt").read_text(encoding="utf-8"),
                "concurrent owner\n",
            )
            self.assertEqual(
                (held_destination / "SKILL.md").read_text(encoding="utf-8"),
                "reviewed bytes\n",
            )

    def test_managed_move_retains_destination_after_post_move_stat_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "banana"
            source.mkdir()
            (source / "SKILL.md").write_text("reviewed bytes\n", encoding="utf-8")
            (source / ".banana-claude-install.json").write_text(
                '{"name":"banana-claude","version":"3.0.0"}\n',
                encoding="utf-8",
            )
            recovery = root / "recovery"
            recovery.mkdir()
            destination = recovery / "banana"
            expected_identity = installer_lifecycle.managed_identity(
                source,
                ".banana-claude-install.json",
            )
            source_parent_identity = installer_lifecycle.directory_identity(root)
            destination_parent_identity = installer_lifecycle.directory_identity(
                recovery
            )
            recovery_identity = (recovery.stat().st_dev, recovery.stat().st_ino)
            real_stat = os.stat
            real_move = installer_lifecycle._rename_no_replace
            failed = False
            move_calls = 0

            def count_move(*args: Any, **kwargs: Any) -> None:
                nonlocal move_calls
                move_calls += 1
                real_move(*args, **kwargs)

            def fail_first_destination_stat(
                path: Any, *args: Any, **kwargs: Any
            ) -> os.stat_result:
                nonlocal failed
                result = real_stat(path, *args, **kwargs)
                directory_descriptor = kwargs.get("dir_fd")
                if (
                    not failed
                    and path == "banana"
                    and isinstance(directory_descriptor, int)
                    and (
                        os.fstat(directory_descriptor).st_dev,
                        os.fstat(directory_descriptor).st_ino,
                    )
                    == recovery_identity
                ):
                    failed = True
                    raise OSError("synthetic post-move stat failure")
                return result

            with (
                mock.patch.object(
                    os,
                    "stat",
                    side_effect=fail_first_destination_stat,
                ),
                mock.patch.object(
                    installer_lifecycle,
                    "_rename_no_replace",
                    side_effect=count_move,
                ),
                self.assertRaises(OSError),
            ):
                installer_lifecycle.move_verified_managed(
                    source,
                    destination,
                    ".banana-claude-install.json",
                    expected_identity,
                    source_parent_identity,
                    destination_parent_identity,
                )

            self.assertTrue(failed)
            self.assertEqual(move_calls, 1)
            self.assertFalse(source.exists())
            self.assertEqual(
                (destination / "SKILL.md").read_text(encoding="utf-8"),
                "reviewed bytes\n",
            )

    def test_install_transaction_preserves_a_concurrent_target_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = root / "stage" / "banana"
            staged.mkdir(parents=True)
            staged.chmod(0o700)
            (staged / "SKILL.md").write_text("reviewed bytes\n", encoding="utf-8")
            (staged / ".banana-claude-install.json").write_text(
                '{"name":"banana-claude","version":"3.0.0"}\n',
                encoding="utf-8",
            )
            install_root = root / "skills"
            install_root.mkdir()
            target = install_root / "banana"
            real_move = installer_lifecycle._rename_no_replace
            injected = False

            def add_concurrent_entry(*args: Any, **kwargs: Any) -> None:
                nonlocal injected
                if not injected:
                    injected = True
                    target.mkdir()
                    (target / "owner.txt").write_text(
                        "concurrent owner\n", encoding="utf-8"
                    )
                real_move(*args, **kwargs)

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_rename_no_replace",
                    side_effect=add_concurrent_entry,
                ),
                self.assertRaises(OSError),
            ):
                installer_lifecycle.install_staged(
                    staged,
                    target,
                    ".banana-claude-install.json",
                    installer_lifecycle.directory_identity(staged),
                    installer_lifecycle.directory_identity(staged.parent),
                    installer_lifecycle.directory_identity(install_root),
                    stage_digest(staged),
                )

            self.assertTrue(injected)
            self.assertEqual(
                (target / "owner.txt").read_text(encoding="utf-8"),
                "concurrent owner\n",
            )
            self.assertFalse((target / "SKILL.md").exists())
            self.assertTrue((staged / "SKILL.md").is_file())
            self.assertEqual(list(target.iterdir()), [target / "owner.txt"])

    def test_install_transaction_rejects_replaced_entry_before_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = root / "stage" / "banana"
            staged.mkdir(parents=True)
            staged.chmod(0o700)
            (staged / "SKILL.md").write_text("reviewed bytes\n", encoding="utf-8")
            (staged / ".banana-claude-install.json").write_text(
                '{"name":"banana-claude","version":"3.0.0"}\n',
                encoding="utf-8",
            )
            install_root = root / "skills"
            install_root.mkdir()
            target = install_root / "banana"
            real_move = installer_lifecycle._rename_no_replace
            swapped = False

            def replace_entry_after_publication(*args: Any, **kwargs: Any) -> None:
                nonlocal swapped
                real_move(*args, **kwargs)
                if not swapped:
                    swapped = True
                    (target / "SKILL.md").rename(target / "SKILL.installer-held")
                    (target / "SKILL.md").write_text(
                        "foreign accepted\n", encoding="utf-8"
                    )

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_rename_no_replace",
                    side_effect=replace_entry_after_publication,
                ),
                self.assertRaises(installer_lifecycle.LifecycleError),
            ):
                installer_lifecycle.install_staged(
                    staged,
                    target,
                    ".banana-claude-install.json",
                    installer_lifecycle.directory_identity(staged),
                    installer_lifecycle.directory_identity(staged.parent),
                    installer_lifecycle.directory_identity(install_root),
                    stage_digest(staged),
                )

            self.assertTrue(swapped)
            self.assertEqual(
                (target / "SKILL.md").read_text(encoding="utf-8"),
                "foreign accepted\n",
            )
            self.assertEqual(
                (target / "SKILL.installer-held").read_text(encoding="utf-8"),
                "reviewed bytes\n",
            )
            self.assertFalse(staged.exists())

    def test_install_transaction_rejects_replaced_nested_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = root / "stage" / "banana"
            scripts = staged / "scripts"
            scripts.mkdir(parents=True)
            staged.chmod(0o700)
            (staged / "SKILL.md").write_text("reviewed bytes\n", encoding="utf-8")
            (scripts / "generate.py").write_text(
                "print('reviewed')\n", encoding="utf-8"
            )
            (staged / ".banana-claude-install.json").write_text(
                '{"name":"banana-claude","version":"3.0.0"}\n',
                encoding="utf-8",
            )
            install_root = root / "skills"
            install_root.mkdir()
            target = install_root / "banana"
            real_move = installer_lifecycle._rename_no_replace

            def replace_nested_entry(*args: Any, **kwargs: Any) -> None:
                real_move(*args, **kwargs)
                (target / "scripts" / "generate.py").rename(
                    target / "scripts" / "generate.installer-held"
                )
                (target / "scripts" / "generate.py").write_text(
                    "print('foreign')\n", encoding="utf-8"
                )

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_rename_no_replace",
                    side_effect=replace_nested_entry,
                ),
                self.assertRaises(installer_lifecycle.LifecycleError),
            ):
                installer_lifecycle.install_staged(
                    staged,
                    target,
                    ".banana-claude-install.json",
                    installer_lifecycle.directory_identity(staged),
                    installer_lifecycle.directory_identity(staged.parent),
                    installer_lifecycle.directory_identity(install_root),
                    stage_digest(staged),
                )

            self.assertFalse(staged.exists())
            self.assertEqual(
                (target / "scripts" / "generate.py").read_text(encoding="utf-8"),
                "print('foreign')\n",
            )
            self.assertEqual(
                (target / "scripts" / "generate.installer-held").read_text(
                    encoding="utf-8"
                ),
                "print('reviewed')\n",
            )

    def test_install_post_publication_failure_never_inverse_renames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = root / "stage" / "banana"
            staged.mkdir(parents=True)
            staged.chmod(0o700)
            (staged / "SKILL.md").write_text("reviewed bytes\n", encoding="utf-8")
            (staged / ".banana-claude-install.json").write_text(
                '{"name":"banana-claude","version":"3.0.0"}\n',
                encoding="utf-8",
            )
            install_root = root / "skills"
            install_root.mkdir()
            target = install_root / "banana"
            digest = stage_digest(staged)
            real_move = installer_lifecycle._rename_no_replace
            move_calls = 0

            def count_move(*args: Any, **kwargs: Any) -> None:
                nonlocal move_calls
                move_calls += 1
                real_move(*args, **kwargs)

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_rename_no_replace",
                    side_effect=count_move,
                ),
                mock.patch.object(
                    os,
                    "fsync",
                    side_effect=OSError("synthetic durability failure"),
                ),
                self.assertRaises(OSError),
            ):
                installer_lifecycle.install_staged(
                    staged,
                    target,
                    ".banana-claude-install.json",
                    installer_lifecycle.directory_identity(staged),
                    installer_lifecycle.directory_identity(staged.parent),
                    installer_lifecycle.directory_identity(install_root),
                    digest,
                )

            self.assertEqual(move_calls, 1)
            self.assertFalse(staged.exists())
            self.assertEqual(
                (target / "SKILL.md").read_text(encoding="utf-8"),
                "reviewed bytes\n",
            )

    def test_verify_installed_rejects_swap_during_final_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            install_root = Path(directory) / "skills"
            install_root.mkdir()
            staged = install_root / ".banana-stage-test"
            target = install_root / "banana"
            held_target = install_root / "banana.verifier-held"
            identity, digest = installer_lifecycle.build_stage(
                ROOT / "skills" / "banana",
                staged,
                ".banana-claude-install.json",
                "3.0.0",
                installer_lifecycle.directory_identity(install_root),
            )
            parent_identity = installer_lifecycle.directory_identity(install_root)
            installer_lifecycle.install_staged(
                staged,
                target,
                ".banana-claude-install.json",
                identity,
                parent_identity,
                parent_identity,
                digest,
            )
            real_snapshot = installer_lifecycle._snapshot_tree
            snapshots = 0

            def swap_during_second_snapshot(descriptor: int) -> Any:
                nonlocal snapshots
                snapshots += 1
                if snapshots == 2:
                    target.rename(held_target)
                    target.mkdir(mode=0o700)
                    (target / "owner.txt").write_text(
                        "concurrent owner\n", encoding="utf-8"
                    )
                return real_snapshot(descriptor)

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_snapshot_tree",
                    side_effect=swap_during_second_snapshot,
                ),
                self.assertRaises(installer_lifecycle.LifecycleError),
            ):
                installer_lifecycle.verify_installed(
                    target,
                    ".banana-claude-install.json",
                    identity,
                    parent_identity,
                    digest,
                )

            self.assertEqual(snapshots, 2)
            self.assertEqual(
                (target / "owner.txt").read_text(encoding="utf-8"),
                "concurrent owner\n",
            )
            self.assertTrue((held_target / "SKILL.md").is_file())

    def test_verify_installed_requires_target_and_parent_sync(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            install_root = Path(directory) / "skills"
            install_root.mkdir()
            staged = install_root / ".banana-stage-test"
            target = install_root / "banana"
            identity, digest = installer_lifecycle.build_stage(
                ROOT / "skills" / "banana",
                staged,
                ".banana-claude-install.json",
                "3.0.0",
                installer_lifecycle.directory_identity(install_root),
            )
            parent_identity = installer_lifecycle.directory_identity(install_root)
            installer_lifecycle.install_staged(
                staged,
                target,
                ".banana-claude-install.json",
                identity,
                parent_identity,
                parent_identity,
                digest,
            )

            with (
                mock.patch.object(
                    os,
                    "fsync",
                    side_effect=OSError("synthetic verifier sync failure"),
                ),
                self.assertRaises(OSError),
            ):
                installer_lifecycle.verify_installed(
                    target,
                    ".banana-claude-install.json",
                    identity,
                    parent_identity,
                    digest,
                )

    def test_managed_move_rejects_destination_parent_swap_and_retains_move(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_parent = root / "source"
            source_parent.mkdir()
            source = source_parent / "banana"
            source.mkdir()
            (source / "SKILL.md").write_text("reviewed bytes\n", encoding="utf-8")
            (source / ".banana-claude-install.json").write_text(
                '{"name":"banana-claude","version":"3.0.0"}\n',
                encoding="utf-8",
            )
            destination_parent = root / "recovery"
            destination_parent.mkdir()
            destination = destination_parent / "banana"
            held_parent = root / "recovery.installer-held"
            real_move = installer_lifecycle._rename_no_replace
            swapped = False

            def swap_destination_parent(*args: Any, **kwargs: Any) -> None:
                nonlocal swapped
                if not swapped:
                    swapped = True
                    destination_parent.rename(held_parent)
                    destination_parent.mkdir()
                    (destination_parent / "owner.txt").write_text(
                        "concurrent owner\n", encoding="utf-8"
                    )
                real_move(*args, **kwargs)

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_rename_no_replace",
                    side_effect=swap_destination_parent,
                ),
                self.assertRaises(installer_lifecycle.LifecycleError),
            ):
                installer_lifecycle.move_verified_managed(
                    source,
                    destination,
                    ".banana-claude-install.json",
                    installer_lifecycle.managed_identity(
                        source, ".banana-claude-install.json"
                    ),
                    installer_lifecycle.directory_identity(source_parent),
                    installer_lifecycle.directory_identity(destination_parent),
                )

            self.assertTrue(swapped)
            self.assertFalse(source.exists())
            self.assertFalse(destination.exists())
            self.assertEqual(
                (destination_parent / "owner.txt").read_text(encoding="utf-8"),
                "concurrent owner\n",
            )
            self.assertTrue((held_parent / "banana" / "SKILL.md").is_file())

    def test_managed_move_rejects_source_parent_swap_and_retains_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_parent = root / "source"
            source_parent.mkdir()
            source = source_parent / "banana"
            source.mkdir()
            (source / "SKILL.md").write_text("reviewed bytes\n", encoding="utf-8")
            (source / ".banana-claude-install.json").write_text(
                '{"name":"banana-claude","version":"3.0.0"}\n',
                encoding="utf-8",
            )
            destination_parent = root / "recovery"
            destination_parent.mkdir()
            destination = destination_parent / "banana"
            held_parent = root / "source.installer-held"
            real_move = installer_lifecycle._rename_no_replace
            swapped = False

            def swap_source_parent(*args: Any, **kwargs: Any) -> None:
                nonlocal swapped
                if not swapped:
                    swapped = True
                    source_parent.rename(held_parent)
                    source_parent.mkdir()
                    (source_parent / "owner.txt").write_text(
                        "concurrent owner\n", encoding="utf-8"
                    )
                real_move(*args, **kwargs)

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_rename_no_replace",
                    side_effect=swap_source_parent,
                ),
                self.assertRaises(installer_lifecycle.LifecycleError),
            ):
                installer_lifecycle.move_verified_managed(
                    source,
                    destination,
                    ".banana-claude-install.json",
                    installer_lifecycle.managed_identity(
                        source, ".banana-claude-install.json"
                    ),
                    installer_lifecycle.directory_identity(source_parent),
                    installer_lifecycle.directory_identity(destination_parent),
                )

            self.assertTrue(swapped)
            self.assertEqual(
                (source_parent / "owner.txt").read_text(encoding="utf-8"),
                "concurrent owner\n",
            )
            self.assertTrue((destination / "SKILL.md").is_file())
            self.assertFalse((held_parent / "banana").exists())

    def test_managed_move_never_replaces_a_racing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "banana"
            source.mkdir()
            (source / "SKILL.md").write_text("reviewed bytes\n", encoding="utf-8")
            (source / ".banana-claude-install.json").write_text(
                '{"name":"banana-claude","version":"3.0.0"}\n',
                encoding="utf-8",
            )
            destination_parent = root / "recovery"
            destination_parent.mkdir()
            destination = destination_parent / "banana"
            real_move = installer_lifecycle._rename_no_replace
            raced = False

            def create_destination_before_rename(*args: Any, **kwargs: Any) -> None:
                nonlocal raced
                if not raced:
                    raced = True
                    destination.mkdir()
                    (destination / "owner.txt").write_text(
                        "concurrent owner\n", encoding="utf-8"
                    )
                real_move(*args, **kwargs)

            with (
                mock.patch.object(
                    installer_lifecycle,
                    "_rename_no_replace",
                    side_effect=create_destination_before_rename,
                ),
                self.assertRaises(OSError),
            ):
                installer_lifecycle.move_verified_managed(
                    source,
                    destination,
                    ".banana-claude-install.json",
                    installer_lifecycle.managed_identity(
                        source, ".banana-claude-install.json"
                    ),
                    installer_lifecycle.directory_identity(root),
                    installer_lifecycle.directory_identity(destination_parent),
                )

            self.assertTrue(raced)
            self.assertTrue((source / "SKILL.md").is_file())
            self.assertEqual(
                (destination / "owner.txt").read_text(encoding="utf-8"),
                "concurrent owner\n",
            )

    def test_unknown_option_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secret_shaped = "--api-key=never-accepted"
            result = run_installer(Path(directory), secret_shaped)
            self.assertEqual(result.returncode, 2)
            self.assertIn("Unknown option", result.stderr)
            self.assertNotIn(secret_shaped, result.stdout)
            self.assertNotIn(secret_shaped, result.stderr)

    def test_internal_lifecycle_helper_has_safe_help(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "installer_lifecycle.py"),
                "--help",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Internal descriptor-bound transaction helper", result.stdout)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
