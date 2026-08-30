from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests._support import temporary_banana_home

import approval_store
from approval_store import (
    MAX_REGISTRY_BYTES,
    consume_approval,
    issue_approval,
    registry_path,
)
from banana_core import BananaError, _atomic_write_at


class ApprovalStoreTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "locked-file replacement is POSIX-specific")
    def test_lock_entry_replacement_aborts_before_registry_publication(self) -> None:
        with temporary_banana_home() as directory:
            real_save = approval_store._save_registry

            def replace_lock_then_save(
                registry: dict[str, Any],
                directory_descriptor: int | None,
                *,
                lock_descriptor: int,
                expected_registry_identity: tuple[int, int] | None,
            ) -> None:
                replacement = directory / "replacement.lock"
                replacement.write_bytes(b"foreign-lock")
                replacement.chmod(0o600)
                os.replace(replacement, directory / "approvals.lock")
                real_save(
                    registry,
                    directory_descriptor,
                    lock_descriptor=lock_descriptor,
                    expected_registry_identity=expected_registry_identity,
                )

            with (
                patch.object(
                    approval_store,
                    "_save_registry",
                    side_effect=replace_lock_then_save,
                ),
                self.assertRaises(BananaError) as caught,
            ):
                issue_approval("request-a", kind="single")

            self.assertEqual(caught.exception.code, "unsafe_approval_lock")
            self.assertFalse(registry_path().exists())
            self.assertEqual(
                (directory / "approvals.lock").read_bytes(), b"foreign-lock"
            )

    def test_registry_replacement_after_read_is_preserved_without_false_success(
        self,
    ) -> None:
        with temporary_banana_home():
            issue_approval("request-a", kind="single")
            foreign = b'{"foreign":"registry"}\n'
            real_atomic_write_at = _atomic_write_at

            def replace_registry_then_publish(
                directory_descriptor: int,
                name: str,
                data: bytes,
                *,
                replace: bool,
                expected_directory: Path | None,
                expected_destination_identity: tuple[int, int] | None | object,
            ) -> tuple[int, int]:
                replacement = registry_path().with_name("foreign-registry.json")
                replacement.write_bytes(foreign)
                replacement.chmod(0o600)
                os.replace(replacement, registry_path())
                return real_atomic_write_at(
                    directory_descriptor,
                    name,
                    data,
                    replace=replace,
                    expected_directory=expected_directory,
                    expected_destination_identity=expected_destination_identity,
                )

            with (
                patch.object(
                    approval_store,
                    "_atomic_write_at",
                    side_effect=replace_registry_then_publish,
                ),
                self.assertRaises(BananaError) as caught,
            ):
                issue_approval("request-b", kind="single")

            self.assertEqual(caught.exception.code, "output_destination_changed")
            self.assertEqual(registry_path().read_bytes(), foreign)

    @unittest.skipIf(os.name == "nt", "directory symlink setup requires POSIX")
    def test_state_root_symlink_fails_without_chmod_or_escape_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.mkdir(mode=0o755)
            outside.chmod(0o755)
            sentinel = outside / "sentinel"
            sentinel.write_bytes(b"preserve")
            state = root / "state"
            state.symlink_to(outside, target_is_directory=True)

            with patch.dict(os.environ, {"BANANA_HOME": str(state)}, clear=False):
                with self.assertRaises(BananaError) as caught:
                    issue_approval("request-a", kind="single")

            self.assertEqual(caught.exception.code, "unsafe_approval_state_directory")
            self.assertTrue(state.is_symlink())
            self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o755)
            self.assertEqual(list(outside.iterdir()), [sentinel])
            self.assertEqual(sentinel.read_bytes(), b"preserve")

    @unittest.skipIf(os.name == "nt", "file symlink setup requires POSIX")
    def test_active_and_dangling_registry_symlinks_are_never_replaced(self) -> None:
        for target_exists in (True, False):
            with self.subTest(target_exists=target_exists):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    state = root / "state"
                    state.mkdir()
                    target = root / "outside-registry"
                    if target_exists:
                        target.write_bytes(b"outside-registry-sentinel")
                    registry = state / "approvals.json"
                    registry.symlink_to(target)

                    with patch.dict(
                        os.environ, {"BANANA_HOME": str(state)}, clear=False
                    ):
                        with self.assertRaises(BananaError) as caught:
                            issue_approval("request-a", kind="single")

                    self.assertEqual(caught.exception.code, "corrupt_approval_registry")
                    self.assertTrue(registry.is_symlink())
                    if target_exists:
                        self.assertEqual(
                            target.read_bytes(), b"outside-registry-sentinel"
                        )
                    else:
                        self.assertFalse(target.exists())

    def test_approval_is_private_bound_and_single_use(self) -> None:
        with temporary_banana_home() as directory:
            issued = issue_approval("request-a", kind="single")
            self.assertTrue(issued["approval_id"].startswith("bap_"))
            self.assertNotIn(
                issued["approval_id"], registry_path().read_text(encoding="utf-8")
            )
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(registry_path().stat().st_mode), 0o600)

            with self.assertRaises(BananaError) as caught:
                consume_approval(issued["approval_id"], "request-b", kind="single")
            self.assertEqual(caught.exception.code, "plan_mismatch")

            consume_approval(issued["approval_id"], "request-a", kind="single")
            with self.assertRaises(BananaError) as caught:
                consume_approval(issued["approval_id"], "request-a", kind="single")
            self.assertEqual(caught.exception.code, "approval_already_used")

    def test_scope_is_enforced_without_consuming(self) -> None:
        with temporary_banana_home():
            issued = issue_approval("portfolio-a", kind="portfolio")
            with self.assertRaises(BananaError) as caught:
                consume_approval(issued["approval_id"], "portfolio-a", kind="single")
            self.assertEqual(caught.exception.code, "approval_scope_mismatch")
            consume_approval(issued["approval_id"], "portfolio-a", kind="portfolio")

    def test_concurrent_consumers_cannot_replay(self) -> None:
        with temporary_banana_home():
            issued = issue_approval("request-a", kind="single")

            def consume() -> str:
                try:
                    consume_approval(issued["approval_id"], "request-a", kind="single")
                    return "ok"
                except BananaError as exc:
                    return exc.code

            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = sorted(executor.map(lambda _value: consume(), range(2)))
            self.assertEqual(outcomes, ["approval_already_used", "ok"])

    def test_capacity_never_revokes_an_unexpired_approval(self) -> None:
        with (
            temporary_banana_home(),
            patch.object(approval_store, "MAX_RECORDS", 2),
        ):
            first = issue_approval("request-a", kind="single")
            issue_approval("request-b", kind="single")
            with self.assertRaises(BananaError) as caught:
                issue_approval("request-c", kind="single")

            self.assertEqual(caught.exception.code, "approval_capacity_reached")
            consume_approval(first["approval_id"], "request-a", kind="single")

    def test_corrupt_registry_fails_closed(self) -> None:
        with temporary_banana_home():
            registry_path().parent.mkdir(parents=True, exist_ok=True)
            registry_path().write_text("not json", encoding="utf-8")
            with self.assertRaises(BananaError) as caught:
                issue_approval("request-a", kind="single")
            self.assertEqual(caught.exception.code, "corrupt_approval_registry")

    def test_excessive_json_nesting_fails_closed(self) -> None:
        with temporary_banana_home():
            registry_path().parent.mkdir(parents=True, exist_ok=True)
            registry_path().write_bytes(b"[" * 100_000 + b"0" + b"]" * 100_000)
            with self.assertRaises(BananaError) as caught:
                issue_approval("request-a", kind="single")
            self.assertEqual(caught.exception.code, "corrupt_approval_registry")

    def test_oversized_registry_is_rejected_before_parsing(self) -> None:
        with temporary_banana_home():
            registry_path().parent.mkdir(parents=True, exist_ok=True)
            with registry_path().open("wb") as handle:
                handle.seek(MAX_REGISTRY_BYTES)
                handle.write(b"x")
            with self.assertRaises(BananaError) as caught:
                issue_approval("request-a", kind="single")
            self.assertEqual(caught.exception.code, "corrupt_approval_registry")

    def test_registry_schema_and_records_are_closed(self) -> None:
        cases = (
            {"schema_version": True, "records": {}},
            {"schema_version": 1, "records": {}, "unknown": True},
            {
                "schema_version": 1,
                "records": {
                    "not-a-digest": {
                        "request_fingerprint": "request-a",
                        "kind": "single",
                        "issued_at": "2026-08-28T00:00:00+00:00",
                        "expires_at": "2026-08-28T00:30:00+00:00",
                        "consumed_at": None,
                    }
                },
            },
        )
        for payload in cases:
            with self.subTest(payload=payload), temporary_banana_home():
                registry_path().parent.mkdir(parents=True, exist_ok=True)
                registry_path().write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(BananaError) as caught:
                    issue_approval("request-a", kind="single")
                self.assertEqual(caught.exception.code, "corrupt_approval_registry")

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires non-following file opens")
    def test_registry_and_lock_symlinks_fail_closed(self) -> None:
        for target in ("registry", "lock"):
            for target_exists in (True, False):
                with (
                    self.subTest(target=target, target_exists=target_exists),
                    temporary_banana_home() as directory,
                ):
                    source = directory / "source"
                    if target_exists:
                        source.write_text("{}", encoding="utf-8")
                    path = (
                        registry_path()
                        if target == "registry"
                        else directory / "approvals.lock"
                    )
                    path.symlink_to(source)
                    with self.assertRaises(BananaError) as caught:
                        issue_approval("request-a", kind="single")
                    self.assertIn(
                        caught.exception.code,
                        {"corrupt_approval_registry", "unsafe_approval_lock"},
                    )
                    self.assertTrue(path.is_symlink())
                    if target_exists:
                        self.assertEqual(source.read_text(encoding="utf-8"), "{}")
                    else:
                        self.assertFalse(source.exists())


if __name__ == "__main__":
    unittest.main()
