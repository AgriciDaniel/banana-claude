from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

from tests._support import (
    PNG_1X1,
    ROOT,
    SCRIPTS,
    completed_response,
    run_python,
    temporary_banana_home,
)

from banana_core import MAX_PROMPT_CHARS, BananaError
from batch import plan_csv
from doctor import PLUGIN_USER_CONFIG_ENV
from mcp_server import (
    MAX_CONTENT_LENGTH,
    McpSession,
    Transport,
    _execution_result,
    call_tool,
    handle_message,
    tool_definitions,
)
from portfolio import (
    build_portfolio_plan,
    execute_portfolio,
    issue_public_portfolio_plan,
    public_portfolio_plan,
)


def reference_authority() -> dict[str, str]:
    return {
        "rights_or_license": "affirmed",
        "identity_or_likeness": "not_applicable",
        "customer_or_private_asset": "not_applicable",
        "endorsement_or_representation": "not_applicable",
        "provider_transmission": "affirmed",
        "intended_use": "Exercise the local test workflow.",
    }


def visual_brief(
    *,
    references: list[dict[str, Any]] | None = None,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
) -> dict[str, Any]:
    return {
        "schema_version": "banana.visual-brief.v1",
        "goal": "A quiet product hero.",
        "facts": [],
        "locks": [],
        "freedoms": [],
        "direction": {
            "mode": "creative",
            "thesis": "Quiet precision.",
            "signature": "One light stripe.",
            "avoid": "Floating particles.",
        },
        "composition": [],
        "rendering": [],
        "typography": {"exact_copy": [], "instructions": []},
        "references": references or [],
        "output": {
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
            "mime_type": "image/jpeg",
            "delivery_notes": [],
        },
        "review_tests": ["The image follows the prompt."],
    }


class CliTests(unittest.TestCase):
    def test_direct_cli_parse_errors_do_not_echo_untrusted_arguments(self) -> None:
        entrypoints = {
            "generate.py": (),
            "edit.py": (),
            "portfolio.py": (),
            "batch.py": (),
            "cost_tracker.py": ("summary",),
            "presets.py": ("list",),
            "doctor.py": (),
            "typeset.py": (),
            "legacy_cleanup.py": ("scan",),
        }
        rejected_arguments = (
            ("--api-key", "synthetic-former-key-value-never-echo"),
            ("--not-a-banana-option", "arbitrary-private-value-never-echo"),
        )
        for script, prefix in entrypoints.items():
            for option, value in rejected_arguments:
                with self.subTest(script=script, option=option):
                    result = run_python(script, *prefix, option, value)
                    combined = result.stdout + result.stderr
                    self.assertEqual(result.returncode, 2, combined)
                    self.assertIn("invalid command-line arguments", result.stderr)
                    self.assertNotIn(option, combined)
                    self.assertNotIn(value, combined)

    def test_direct_cli_help_remains_available(self) -> None:
        for script in (
            "generate.py",
            "edit.py",
            "portfolio.py",
            "batch.py",
            "cost_tracker.py",
            "presets.py",
            "doctor.py",
            "typeset.py",
            "legacy_cleanup.py",
        ):
            with self.subTest(script=script):
                result = run_python(script, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires FIFO support")
    def test_csv_input_must_be_a_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.fifo"
            os.mkfifo(path)
            with self.assertRaises(BananaError) as caught:
                plan_csv(path, max_count=1, provider_batch=False)
            self.assertEqual(caught.exception.code, "csv_not_found")

    def test_generate_plans_without_key_or_network(self) -> None:
        result = run_python(
            "generate.py",
            "--prompt",
            "A quiet editorial still life",
            "--aspect-ratio",
            "16:9",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIs(payload["network_called"], False)
        self.assertEqual(payload["plan"]["model"], "gemini-3.1-flash-image")
        self.assertIn("request_fingerprint", payload["plan"])
        self.assertTrue(payload["plan"]["approval_id"].startswith("bap_"))
        self.assertEqual(payload["plan"]["approval_scope"], "single_use")

    def test_generate_accepts_closed_visual_brief_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            brief_path = Path(directory) / "brief.json"
            brief_path.write_text(json.dumps(visual_brief()), encoding="utf-8")
            result = run_python(
                "generate.py",
                "--prompt",
                "A quiet product hero",
                "--brief-file",
                str(brief_path),
                env={"BANANA_OUTPUT_DIR": str(Path(directory) / "output")},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)["plan"]
            self.assertEqual(payload["brief_source"], "supplied")
            self.assertEqual(len(payload["brief_sha256"]), 64)
            self.assertNotIn("visual_brief", payload)

    def test_invalid_model_is_not_reflected_by_cli_or_mcp(self) -> None:
        private_value = "synthetic-former-key-value-never-echo"
        result = run_python(
            "generate.py",
            "--prompt",
            "A quiet editorial still life",
            "--model",
            private_value,
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(private_value, result.stdout + result.stderr)
        self.assertIn("unsupported_model", result.stderr)

        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 75,
                "method": "tools/call",
                "params": {
                    "name": "banana_plan",
                    "arguments": {
                        "prompt": "A quiet editorial still life",
                        "model": private_value,
                        "references": [],
                    },
                },
            }
        )
        assert response is not None
        rendered = json.dumps(response)
        self.assertNotIn(private_value, rendered)
        error = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(error["code"], "unsupported_model")

    def test_execution_requires_confirmation_before_key_lookup(self) -> None:
        no_confirmation = run_python(
            "generate.py",
            "--prompt",
            "A quiet editorial still life",
            "--execute",
        )
        self.assertEqual(no_confirmation.returncode, 1)
        self.assertIn("confirmation_required", no_confirmation.stderr)
        self.assertNotIn("missing_api_key", no_confirmation.stderr)

        wrong_confirmation = run_python(
            "generate.py",
            "--prompt",
            "A quiet editorial still life",
            "--execute",
            "--confirm",
            "wrong-plan",
        )
        self.assertEqual(wrong_confirmation.returncode, 1)
        self.assertIn("invalid_approval", wrong_confirmation.stderr)
        self.assertNotIn("missing_api_key", wrong_confirmation.stderr)

    def test_edit_plan_hashes_reference_without_printing_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "private.png"
            image.write_bytes(PNG_1X1)
            brief_path = Path(directory) / "brief.json"
            brief_path.write_text(
                json.dumps(
                    visual_brief(
                        references=[
                            {
                                "disclosure_alias": "private product photo",
                                "role": "object",
                                "purpose": "preserve source geometry",
                                "subject_id": None,
                                "authority": reference_authority(),
                            }
                        ]
                    )
                ),
                encoding="utf-8",
            )
            result = run_python(
                "edit.py",
                "--image",
                str(image),
                "--reference-role",
                "object",
                "--reference-name",
                "private product photo",
                "--reference-purpose",
                "preserve source geometry",
                "--brief-file",
                str(brief_path),
                "--prompt",
                "Change only the jacket color",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(str(image), result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["plan"]["reference_count"], 1)
            self.assertEqual(len(payload["plan"]["reference_inputs"]), 1)

    def test_cli_reference_requires_explicit_role_and_purpose(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "private.png"
            image.write_bytes(PNG_1X1)
            result = run_python(
                "edit.py",
                "--image",
                str(image),
                "--prompt",
                "Change only the jacket color",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("reference_metadata_required", result.stderr)

    def test_csv_is_an_offline_plan_not_a_batch_submission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "plan.csv"
            csv_path.write_text(
                "prompt,model,ratio,resolution\n"
                "First,gemini-3.1-flash-lite-image,1:1,1K\n"
                "Second,gemini-3.1-flash-image,16:9,2K\n",
                encoding="utf-8",
            )
            plan = plan_csv(csv_path, max_count=2, provider_batch=True)
            self.assertFalse(plan["network_called"])
            self.assertEqual(plan["execution"], "not_submitted")
            self.assertEqual(plan["total_count"], 2)

    def test_csv_rejects_uncompiled_presets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "plan.csv"
            csv_path.write_text(
                "prompt,model,preset\nFirst,gemini-3.1-flash-image,brand-system\n",
                encoding="utf-8",
            )
            with self.assertRaises(BananaError) as caught:
                plan_csv(csv_path, max_count=2, provider_batch=False)
            self.assertEqual(caught.exception.code, "csv_validation_failed")
            self.assertIn("agent-side brief compilation", caught.exception.message)

    def test_csv_rejects_unsafe_or_oversized_approval_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "plan.csv"
            for label, prompt in (
                ("bidirectional control", "safe\u202eoverride"),
                ("oversized prompt", "x" * (MAX_PROMPT_CHARS + 1)),
            ):
                with self.subTest(label=label):
                    csv_path.write_text(f"prompt\n{prompt}\n", encoding="utf-8")
                    with self.assertRaises(BananaError) as caught:
                        plan_csv(csv_path, max_count=1, provider_batch=False)
                    self.assertEqual(caught.exception.code, "csv_validation_failed")

    def test_doctor_is_read_only_and_reports_missing_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_python("doctor.py", "--json", env={"HOME": directory})
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            checks = {item["name"]: item for item in payload["checks"]}
            self.assertFalse(checks["api_key_available"]["passed"])
            self.assertEqual(
                checks["api_key_available"]["detail"],
                "Claude plugin userConfig export is not present in this process",
            )
            self.assertTrue(checks["plugin_manifest"]["passed"])
            self.assertTrue(checks["legacy_install_state"]["passed"])

    def test_doctor_plugin_mode_uses_user_config_presence_without_echoing_it(
        self,
    ) -> None:
        plugin_sentinel = "synthetic-plugin-option-never-print"
        ambient_sentinel = "synthetic-ambient-key-never-print"
        with tempfile.TemporaryDirectory() as directory:
            result = run_python(
                "doctor.py",
                "--json",
                env={
                    "HOME": directory,
                    PLUGIN_USER_CONFIG_ENV: plugin_sentinel,
                    "GEMINI_API_KEY": ambient_sentinel,
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(plugin_sentinel, result.stdout + result.stderr)
            self.assertNotIn(ambient_sentinel, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            checks = {item["name"]: item for item in payload["checks"]}
            self.assertTrue(checks["api_key_available"]["passed"])
            self.assertEqual(
                checks["api_key_available"]["detail"],
                "Claude plugin userConfig export is present",
            )

    def test_doctor_plugin_mode_rejects_empty_or_whitespace_key(self) -> None:
        for configured in ("", "  \t\n"):
            with (
                self.subTest(configured=repr(configured)),
                tempfile.TemporaryDirectory() as directory,
            ):
                result = run_python(
                    "doctor.py",
                    "--json",
                    env={
                        "HOME": directory,
                        PLUGIN_USER_CONFIG_ENV: configured,
                    },
                )
                self.assertEqual(result.returncode, 1)
                payload = json.loads(result.stdout)
                checks = {item["name"]: item for item in payload["checks"]}
                self.assertFalse(checks["api_key_available"]["passed"])

    def test_mcp_enforces_declared_string_maximum_without_reflection(self) -> None:
        private_value = "synthetic-private-purpose-never-echo-" * 5
        self.assertGreater(len(private_value), 120)
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 76,
                "method": "tools/call",
                "params": {
                    "name": "banana_plan",
                    "arguments": {
                        "prompt": "Safe prompt",
                        "references": [
                            {
                                "path": "/approved/reference.png",
                                "disclosure_alias": "approved reference",
                                "role": "style",
                                "purpose": private_value,
                            }
                        ],
                    },
                },
            }
        )
        assert response is not None
        rendered = json.dumps(response)
        self.assertNotIn(private_value, rendered)
        error = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(error["code"], "invalid_arguments")

    def test_doctor_standalone_mode_requires_ambient_gemini_key(self) -> None:
        gemini_sentinel = "synthetic-standalone-key-never-print"
        plugin_sentinel = "synthetic-plugin-option-never-print"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed_skill = root / "skills" / "banana"
            installed_scripts = installed_skill / "scripts"
            installed_references = installed_skill / "references"
            installed_scripts.mkdir(parents=True)
            installed_references.mkdir()
            for name in ("doctor.py", "banana_core.py", "legacy_cleanup.py"):
                (installed_scripts / name).write_bytes((SCRIPTS / name).read_bytes())
            (installed_references / "models.json").write_bytes(
                (ROOT / "skills" / "banana" / "references" / "models.json").read_bytes()
            )
            (installed_skill / ".banana-claude-install.json").write_text(
                '{"name":"banana-claude","version":"3.0.0"}\n',
                encoding="utf-8",
            )
            home = root / "home"
            home.mkdir()
            base_env = os.environ.copy()
            for name in (
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
                "GOOGLE_AI_API_KEY",
                PLUGIN_USER_CONFIG_ENV,
            ):
                base_env.pop(name, None)
            base_env.update(
                {
                    "HOME": str(home),
                    "BANANA_HOME": str(root / "state"),
                    "BANANA_OUTPUT_DIR": str(root / "output"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )

            plugin_only_env = dict(base_env)
            plugin_only_env[PLUGIN_USER_CONFIG_ENV] = plugin_sentinel
            plugin_only = subprocess.run(
                [sys.executable, str(installed_scripts / "doctor.py"), "--json"],
                cwd=root,
                env=plugin_only_env,
                text=True,
                capture_output=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(plugin_only.returncode, 1, plugin_only.stderr)
            self.assertNotIn(plugin_sentinel, plugin_only.stdout + plugin_only.stderr)
            plugin_only_checks = {
                item["name"]: item for item in json.loads(plugin_only.stdout)["checks"]
            }
            self.assertFalse(plugin_only_checks["api_key_available"]["passed"])
            self.assertEqual(
                plugin_only_checks["api_key_available"]["detail"],
                "GEMINI_API_KEY is not present for standalone execution",
            )

            standalone_env = dict(base_env)
            standalone_env["GEMINI_API_KEY"] = gemini_sentinel
            standalone = subprocess.run(
                [sys.executable, str(installed_scripts / "doctor.py"), "--json"],
                cwd=root,
                env=standalone_env,
                text=True,
                capture_output=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(standalone.returncode, 0, standalone.stderr)
            self.assertNotIn(gemini_sentinel, standalone.stdout + standalone.stderr)
            standalone_checks = {
                item["name"]: item for item in json.loads(standalone.stdout)["checks"]
            }
            self.assertTrue(standalone_checks["api_key_available"]["passed"])
            self.assertEqual(
                standalone_checks["api_key_available"]["detail"],
                "GEMINI_API_KEY is configured for standalone execution",
            )

    def test_doctor_ignores_ambient_google_key_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_python(
                "doctor.py",
                "--json",
                env={
                    "HOME": directory,
                    "GOOGLE_API_KEY": "synthetic",  # pragma: allowlist secret
                    "GOOGLE_AI_API_KEY": "synthetic",  # pragma: allowlist secret
                },
            )
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            checks = {item["name"]: item for item in payload["checks"]}
            self.assertFalse(checks["api_key_available"]["passed"])

    def test_doctor_checks_nearest_existing_output_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "not-created" / "nested" / "output"
            result = run_python(
                "doctor.py",
                "--json",
                env={"BANANA_OUTPUT_DIR": str(destination), "HOME": directory},
            )
            payload = json.loads(result.stdout)
            checks = {item["name"]: item for item in payload["checks"]}
            self.assertTrue(checks["output_parent_writable"]["passed"])
            self.assertEqual(checks["output_parent_writable"]["detail"], directory)

    def test_doctor_blocks_legacy_mcp_without_echoing_the_key(self) -> None:
        sentinel = "synthetic-legacy-key-never-print"  # pragma: allowlist secret
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "unrelated": {"keep": True},
                        "mcpServers": {
                            "nanobanana-mcp": {
                                "command": "npx",
                                "args": ["-y", "@ycse/nanobanana-mcp"],
                                "env": {"GOOGLE_AI_API_KEY": sentinel},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            result = run_python("doctor.py", "--json", env={"HOME": directory})
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(sentinel, result.stdout)
            self.assertNotIn(sentinel, result.stderr)
            payload = json.loads(result.stdout)
            checks = {item["name"]: item for item in payload["checks"]}
            self.assertFalse(checks["legacy_install_state"]["passed"])
            self.assertIn("nanobanana-mcp", checks["legacy_install_state"]["detail"])

    def test_doctor_blocks_the_obsolete_nano_banana_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            skill = home / ".claude" / "skills" / "nano-banana"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: nano-banana\nversion: 2.1.0\n---\n",
                encoding="utf-8",
            )
            result = run_python("doctor.py", "--json", env={"HOME": directory})
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            checks = {item["name"]: item for item in payload["checks"]}
            self.assertFalse(checks["legacy_install_state"]["passed"])
            self.assertIn("nano-banana", checks["legacy_install_state"]["detail"])


class PortfolioTests(unittest.TestCase):
    def test_portfolio_requires_brief_before_model_iteration_or_planning(
        self,
    ) -> None:
        model_iterated = False

        def models() -> Iterator[str]:
            nonlocal model_iterated
            model_iterated = True
            yield "gemini-3.1-flash-image"

        with (
            mock.patch("portfolio.get_model") as get_model,
            mock.patch("portfolio.build_plan") as build_plan,
            mock.patch("portfolio.load_catalog") as load_catalog,
            self.assertRaises(BananaError) as caught,
        ):
            build_portfolio_plan(
                prompts=["Direct"],
                models=models(),
            )

        self.assertEqual(caught.exception.code, "structured_brief_required")
        self.assertEqual(
            caught.exception.details,
            {
                "provider_called": False,
                "structured_brief_required": True,
                "structured_brief_reasons": ["portfolio"],
            },
        )
        self.assertFalse(model_iterated)
        get_model.assert_not_called()
        build_plan.assert_not_called()
        load_catalog.assert_not_called()

    def test_portfolio_is_bounded_and_deterministic(self) -> None:
        first = build_portfolio_plan(
            prompts=["Direct", "One justified risk"],
            models=["gemini-3.1-flash-image", "gemini-3-pro-image"],
            aspect_ratio="16:9",
            visual_brief=visual_brief(aspect_ratio="16:9"),
        )
        second = build_portfolio_plan(
            prompts=["Direct", "One justified risk"],
            models=["gemini-3.1-flash-image", "gemini-3-pro-image"],
            aspect_ratio="16:9",
            visual_brief=visual_brief(aspect_ratio="16:9"),
        )
        self.assertEqual(first["request_fingerprint"], second["request_fingerprint"])
        self.assertEqual(first["request_count"], 4)
        public = public_portfolio_plan(first)
        self.assertFalse(public["network_called"])
        self.assertEqual(public["comparison_image_size"], "1K")
        self.assertTrue(all(item["image_size"] == "1K" for item in public["items"]))
        self.assertTrue(
            all(item["api_surface"] == "interactions" for item in public["items"])
        )
        self.assertTrue(
            all(
                item["api_endpoint"].endswith("/v1beta/interactions")
                for item in public["items"]
            )
        )
        self.assertTrue(
            all(item["catalog_verified_on"] == "2026-08-29" for item in public["items"])
        )
        self.assertTrue(all(item["store"] is False for item in public["items"]))
        self.assertEqual(public["output_mime_type"], "image/jpeg")
        approval_summary = public["approval_summary"]
        self.assertEqual(approval_summary["output_mime_type"], "image/jpeg")
        self.assertEqual(approval_summary["estimate_basis"], "nominal_one_output")
        self.assertTrue(approval_summary["output_count_uncertain"])
        self.assertFalse(approval_summary["search_provider_retention_mandatory"])
        self.assertIn("provider_storage_retention_default_days", approval_summary)
        self.assertIn("provider_storage_retention_options_days", approval_summary)
        self.assertIn("provider_storage_setting_inspectable", approval_summary)
        self.assertIn("provider_storage_warning", approval_summary)
        self.assertEqual(
            {item["thinking_behavior"] for item in public["items"]},
            {"minimal", "provider_default_process"},
        )
        self.assertTrue(
            all(
                item["thinking_documentation_conflict"] is False
                for item in public["items"]
            )
        )
        self.assertTrue(
            all(item["output_mime_documentation_conflict"] for item in public["items"])
        )
        self.assertTrue(
            all(
                "gemini-3-pro-image" in item["output_mime_documentation_note"]
                and "gemini-3.1-flash-image was not directly probed"
                in item["output_mime_documentation_note"]
                and "conservative API-surface policy"
                in item["output_mime_documentation_note"]
                for item in public["items"]
            )
        )
        self.assertEqual(
            [item["provider_response_format"] for item in public["items"]],
            [item["plan"]["provider_response_format"] for item in first["items"]],
        )
        with self.assertRaises(BananaError) as caught:
            build_portfolio_plan(
                prompts=["one", "two", "three", "four"],
                models=["gemini-3.1-flash-image"],
                visual_brief=visual_brief(),
            )
        self.assertEqual(caught.exception.code, "invalid_portfolio_prompts")

    def test_unexpected_portfolio_errors_do_not_expose_exception_text(self) -> None:
        with temporary_banana_home():
            portfolio = build_portfolio_plan(
                prompts=["Direct"],
                models=["gemini-3.1-flash-image"],
                visual_brief=visual_brief(),
            )
            approval = issue_public_portfolio_plan(portfolio)
            sentinel = "private sentinel at /tmp/private-source"
            with mock.patch(
                "portfolio.execute_validated_plan", side_effect=RuntimeError(sentinel)
            ):
                result = execute_portfolio(
                    portfolio=portfolio,
                    approval_id=approval["approval_id"],
                )
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["code"], "unexpected_error")
        self.assertEqual(
            result["errors"][0]["message"], "Unexpected portfolio worker failure."
        )
        self.assertNotIn(sentinel, json.dumps(result))

    def test_portfolio_cost_logging_never_persists_raw_interaction_id(self) -> None:
        raw_identifier = "synthetic-portfolio-interaction-id-never-persist"
        expected_digest = hashlib.sha256(raw_identifier.encode()).hexdigest()
        response = completed_response()
        response["id"] = raw_identifier

        with (
            tempfile.TemporaryDirectory() as directory,
            temporary_banana_home() as home,
        ):
            portfolio = build_portfolio_plan(
                prompts=["Direct"],
                models=["gemini-3.1-flash-image"],
                destination=directory,
                workers=1,
                visual_brief=visual_brief(),
            )
            approval = issue_public_portfolio_plan(portfolio)
            with mock.patch("banana_core.call_interactions", return_value=response):
                result = execute_portfolio(
                    portfolio=portfolio,
                    approval_id=approval["approval_id"],
                )

            self.assertTrue(result["ok"], result)
            self.assertNotIn(
                raw_identifier,
                json.dumps(result["results"][0]["cost_log"]),
            )
            ledger_bytes = (home / "costs.json").read_bytes()
            self.assertNotIn(raw_identifier.encode(), ledger_bytes)
            self.assertIn(expected_digest.encode(), ledger_bytes)

    def test_portfolio_provider_attempt_digests_are_unique(self) -> None:
        import portfolio as portfolio_module

        observed: list[str] = []

        def fake_execute(**kwargs: Any) -> dict[str, Any]:
            observed.append(kwargs["attempt_sha256"])
            return {
                "ok": True,
                "plan": {"model": kwargs["plan"]["model"]},
                "image_contents": [],
            }

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            portfolio = build_portfolio_plan(
                prompts=["Direct", "Risk"],
                models=["gemini-3.1-flash-image"],
                destination=directory,
                workers=1,
                visual_brief=visual_brief(),
            )
            approval = issue_public_portfolio_plan(portfolio)
            with mock.patch.object(
                portfolio_module,
                "execute_validated_plan",
                side_effect=fake_execute,
            ):
                result = execute_portfolio(
                    portfolio=portfolio,
                    approval_id=approval["approval_id"],
                )

        self.assertTrue(result["ok"])
        self.assertEqual(len(observed), 2)
        self.assertEqual(len(set(observed)), 2)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", value) for value in observed))

    def test_portfolio_directory_swap_writes_nothing_and_closes_capability(
        self,
    ) -> None:
        import banana_core
        import portfolio as portfolio_module

        provider_calls = 0
        held_capabilities: list[banana_core.OutputPublicationCapability] = []
        held_descriptors: list[int] = []
        original_acquire = portfolio_module.acquire_output_publication

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            root = Path(directory)
            destination = root / "approved"
            destination.mkdir()
            held_original = root / "held-original"
            portfolio = build_portfolio_plan(
                prompts=["Direct"],
                models=["gemini-3.1-flash-image"],
                destination=destination,
                workers=1,
                visual_brief=visual_brief(),
            )
            approval = issue_public_portfolio_plan(portfolio)

            def capture_capability(
                path: str | Path,
            ) -> banana_core.OutputPublicationCapability:
                capability = original_acquire(path)
                held_capabilities.append(capability)
                held_descriptors.append(capability.descriptor)
                return capability

            def swapping_provider(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
                nonlocal provider_calls
                provider_calls += 1
                destination.rename(held_original)
                destination.mkdir()
                return completed_response()

            with (
                mock.patch.object(
                    portfolio_module,
                    "acquire_output_publication",
                    side_effect=capture_capability,
                ),
                mock.patch(
                    "banana_core.call_interactions",
                    side_effect=swapping_provider,
                ),
            ):
                result = execute_portfolio(
                    portfolio=portfolio,
                    approval_id=approval["approval_id"],
                )

            self.assertEqual(provider_calls, 1)
            self.assertFalse(result["ok"])
            self.assertEqual(result["errors"][0]["code"], "output_directory_changed")
            details = result["errors"][0]["details"]
            self.assertTrue(details["provider_succeeded"])
            self.assertTrue(details["billable_attempt"])
            self.assertEqual(details["provider_attempt_count"], 1)
            self.assertEqual(list(destination.iterdir()), [])
            self.assertEqual(
                [path.name for path in held_original.iterdir()],
                [banana_core.PUBLICATION_CAPABILITY_NAME],
            )
            self.assertTrue(all(capability.closed for capability in held_capabilities))
            for descriptor in held_descriptors:
                with self.assertRaises(OSError):
                    os.fstat(descriptor)

    def test_portfolio_acquires_every_capability_before_approval_and_closes_all(
        self,
    ) -> None:
        import banana_core
        import portfolio as portfolio_module

        held: list[banana_core.OutputPublicationCapability] = []
        original_acquire = portfolio_module.acquire_output_publication

        def capture(
            path: str | Path,
        ) -> banana_core.OutputPublicationCapability:
            capability = original_acquire(path)
            held.append(capability)
            return capability

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            portfolio = build_portfolio_plan(
                prompts=["Direct", "Risk"],
                models=["gemini-3.1-flash-image"],
                destination=directory,
                workers=1,
                visual_brief=visual_brief(),
            )
            with mock.patch.object(
                portfolio_module,
                "acquire_output_publication",
                side_effect=capture,
            ):
                with self.assertRaises(BananaError) as caught:
                    execute_portfolio(
                        portfolio=portfolio,
                        approval_id="invalid",
                    )

        self.assertEqual(caught.exception.code, "invalid_approval")
        self.assertEqual(len(held), portfolio["request_count"])
        self.assertTrue(all(capability.closed for capability in held))

    def test_reference_iterable_is_reused_for_every_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "reference.png"
            image.write_bytes(PNG_1X1)
            plan = build_portfolio_plan(
                prompts=["Direct", "Risk"],
                models=["gemini-3.1-flash-image"],
                reference_paths=(
                    {
                        "path": path,
                        "disclosure_alias": "reference image",
                        "role": "character",
                        "purpose": "identity",
                        "subject_id": "hero",
                    }
                    for path in [str(image)]
                ),
                visual_brief=visual_brief(
                    references=[
                        {
                            "disclosure_alias": "reference image",
                            "role": "character",
                            "purpose": "identity",
                            "subject_id": "hero",
                            "authority": reference_authority(),
                        }
                    ]
                ),
            )
            self.assertEqual(
                [item["plan"]["reference_count"] for item in plan["items"]], [1, 1]
            )
            public = public_portfolio_plan(plan)
            self.assertEqual(public["reference_count"], 1)
            self.assertEqual(public["reference_inputs"][0]["role"], "character")
            self.assertEqual(public["reference_inputs"][0]["subject_id"], "hero")
            self.assertNotIn(str(image), str(public))


class McpTests(unittest.TestCase):
    def test_tool_contract_separates_offline_and_paid_tools(self) -> None:
        tools = {tool["name"]: tool for tool in tool_definitions()}
        self.assertEqual(
            set(tools),
            {
                "banana_models",
                "banana_plan",
                "banana_generate",
                "banana_edit",
                "banana_portfolio_plan",
                "banana_portfolio_generate",
                "banana_typeset",
            },
        )
        self.assertFalse(tools["banana_plan"]["annotations"]["readOnlyHint"])
        self.assertFalse(tools["banana_generate"]["annotations"]["readOnlyHint"])
        self.assertTrue(tools["banana_generate"]["annotations"]["openWorldHint"])
        interaction_required = {
            "banana_generate",
            "banana_edit",
            "banana_portfolio_generate",
        }
        for name in interaction_required:
            self.assertEqual(
                tools[name]["_meta"], {"anthropic/requiresUserInteraction": True}
            )
        for name in set(tools) - interaction_required:
            self.assertNotIn("_meta", tools[name])
        for tool in tools.values():
            self.assertNotIn("api_key", tool["inputSchema"]["properties"])
        reference_schema = tools["banana_plan"]["inputSchema"]["properties"][
            "references"
        ]["items"]
        self.assertEqual(
            reference_schema["required"],
            ["path", "disclosure_alias", "role", "purpose"],
        )
        for name in (
            "banana_plan",
            "banana_generate",
            "banana_edit",
            "banana_portfolio_plan",
            "banana_portfolio_generate",
        ):
            self.assertEqual(
                tools[name]["inputSchema"]["properties"]["mime_type"]["default"],
                "image/jpeg",
            )
            self.assertEqual(
                tools[name]["inputSchema"]["properties"]["mime_type"]["enum"],
                ["image/jpeg"],
            )
            self.assertIn("visual_brief", tools[name]["inputSchema"]["properties"])
            direction_modes = tools[name]["inputSchema"]["properties"]["visual_brief"][
                "properties"
            ]["direction"]["properties"]["mode"]["enum"]
            self.assertEqual(
                direction_modes,
                ["creative", "preserve", "not_applicable"],
            )
            self.assertNotIn("prompt_only", direction_modes)
        for name in ("banana_portfolio_plan", "banana_portfolio_generate"):
            self.assertIn("visual_brief", tools[name]["inputSchema"]["required"])
        self.assertIn("visual_brief", tools["banana_edit"]["inputSchema"]["required"])

    def test_mcp_interleaves_identity_before_every_portfolio_image(self) -> None:
        raw_markers = ["raw-image-one", "raw-image-two", "raw-image-three"]
        result = {
            "ok": True,
            "results": [
                {
                    "variant_id": "variant-1",
                    "plan": {"model": "model-a"},
                    "artifacts": [
                        {"path": "/safe/one.jpg", "sha256": "a" * 64},
                        {"path": "/safe/two.jpg", "sha256": "b" * 64},
                    ],
                    "image_contents": [
                        {"data": raw_markers[0], "mime_type": "image/jpeg"},
                        {"data": raw_markers[1], "mime_type": "image/jpeg"},
                    ],
                },
                {
                    "variant_id": "variant-2",
                    "plan": {"model": "model-b"},
                    "artifacts": [{"path": "/safe/three.jpg", "sha256": "c" * 64}],
                    "image_contents": [
                        {"data": raw_markers[2], "mime_type": "image/jpeg"}
                    ],
                },
            ],
            "errors": [],
        }

        rendered = _execution_result(result)

        self.assertEqual(
            [item["type"] for item in rendered["content"]],
            ["text", "text", "image", "text", "image", "text", "image"],
        )
        summary = rendered["content"][0]["text"]
        self.assertFalse(any(marker in summary for marker in raw_markers))
        identities = [
            json.loads(rendered["content"][index]["text"])["image_attribution"]
            for index in (1, 3, 5)
        ]
        self.assertEqual(
            [(item["variant_id"], item["model"]) for item in identities],
            [
                ("variant-1", "model-a"),
                ("variant-1", "model-a"),
                ("variant-2", "model-b"),
            ],
        )
        self.assertEqual(
            [item["provider_output_index"] for item in identities], [1, 2, 1]
        )
        self.assertEqual(
            [item["artifact_path"] for item in identities],
            ["/safe/one.jpg", "/safe/two.jpg", "/safe/three.jpg"],
        )

    def test_initialize_list_and_offline_plan(self) -> None:
        initialized = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        assert initialized is not None
        self.assertEqual(initialized["result"]["serverInfo"]["version"], "3.0.0")
        listed = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert listed is not None
        self.assertEqual(len(listed["result"]["tools"]), 7)

        with temporary_banana_home():
            result = call_tool("banana_plan", {"prompt": "A minimal still life"})
        self.assertFalse(result["isError"])
        plan = json.loads(result["content"][0]["text"])
        self.assertEqual(plan["estimated_image_output_usd"], 0.067)
        self.assertTrue(plan["approval_id"].startswith("bap_"))

    def test_mcp_cost_logging_never_persists_raw_interaction_id(self) -> None:
        raw_identifier = "synthetic-mcp-interaction-id-never-persist"
        expected_digest = hashlib.sha256(raw_identifier.encode()).hexdigest()
        response = completed_response()
        response["id"] = raw_identifier

        with (
            tempfile.TemporaryDirectory() as directory,
            temporary_banana_home() as home,
        ):
            prompt = "A minimal still life"
            planned = call_tool(
                "banana_plan",
                {"prompt": prompt, "output_dir": directory},
            )
            approval = json.loads(planned["content"][0]["text"])
            with mock.patch("banana_core.call_interactions", return_value=response):
                generated = call_tool(
                    "banana_generate",
                    {
                        "prompt": prompt,
                        "output_dir": directory,
                        "approval_id": approval["approval_id"],
                    },
                )

            self.assertFalse(generated["isError"])
            public = json.loads(generated["content"][0]["text"])
            self.assertNotIn(raw_identifier, json.dumps(public["cost_log"]))
            ledger_bytes = (home / "costs.json").read_bytes()
            self.assertNotIn(raw_identifier.encode(), ledger_bytes)
            self.assertIn(expected_digest.encode(), ledger_bytes)

    def test_session_requires_initialize_and_initialized_notification(self) -> None:
        session = McpSession()
        ping = session.handle({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert ping is not None
        self.assertEqual(ping["result"], {})

        blocked = session.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert blocked is not None
        self.assertEqual(blocked["error"]["code"], -32002)

        initialized = session.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            }
        )
        assert initialized is not None
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-11-25")
        incomplete = session.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
        assert incomplete is not None
        self.assertEqual(incomplete["error"]["code"], -32002)
        self.assertIsNone(
            session.handle(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }
            )
        )
        listed = session.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/list"})
        assert listed is not None
        self.assertEqual(len(listed["result"]["tools"]), 7)
        repeated = session.handle(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            }
        )
        assert repeated is not None
        self.assertEqual(repeated["error"]["code"], -32600)

    def test_initialize_negotiates_supported_legacy_protocol_versions(self) -> None:
        for request_id, version in enumerate(("2025-06-18", "2025-11-25"), start=4):
            with self.subTest(version=version):
                supported = handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "initialize",
                        "params": {"protocolVersion": version},
                    }
                )
                assert supported is not None
                self.assertEqual(supported["result"]["protocolVersion"], version)

        fallback = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "initialize",
                "params": {"protocolVersion": "2099-01-01"},
            }
        )
        assert fallback is not None
        self.assertEqual(fallback["id"], 5)
        self.assertEqual(fallback["result"]["protocolVersion"], "2025-11-25")

    def test_invalid_jsonrpc_request_shape_returns_invalid_request(self) -> None:
        for request in (
            {"id": 1, "method": "ping"},
            {"jsonrpc": "1.0", "id": 2, "method": "ping"},
            {"jsonrpc": "2.0", "id": 3, "method": []},
            {"jsonrpc": "2.0", "id": True, "method": "ping"},
            {"jsonrpc": "2.0", "id": {}, "method": "ping"},
        ):
            with self.subTest(request=request):
                response = handle_message(request)
                assert response is not None
                self.assertEqual(response["error"]["code"], -32600)
                if not isinstance(
                    request.get("id"), (str, int, float, type(None))
                ) or isinstance(request.get("id"), bool):
                    self.assertIsNone(response["id"])

    def test_jsonrpc_identifiers_reject_unsafe_unicode_without_terminating_stdio(
        self,
    ) -> None:
        unsafe_id = handle_message(
            {"jsonrpc": "2.0", "id": "safe\ud800", "method": "ping"}
        )
        assert unsafe_id is not None
        self.assertIsNone(unsafe_id["id"])
        self.assertEqual(unsafe_id["error"]["code"], -32600)

        unsafe_method = handle_message(
            {"jsonrpc": "2.0", "id": 47, "method": "ping\u202e"}
        )
        assert unsafe_method is not None
        self.assertEqual(unsafe_method["id"], 47)
        self.assertEqual(unsafe_method["error"]["code"], -32600)
        self.assertNotIn("\u202e", unsafe_method["error"]["message"])

        unsafe_tool = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 48,
                "method": "tools/call",
                "params": {
                    "name": "banana_plan\u202e",
                    "arguments": {"prompt": "safe"},
                },
            }
        )
        assert unsafe_tool is not None
        self.assertEqual(unsafe_tool["error"]["code"], -32602)

        raw_requests = (
            b'{"jsonrpc":"2.0","id":"\\ud800","method":"ping"}\n'
            + '{"jsonrpc":"2.0","id":49,"method":"ping\u202e"}\n'.encode()
            + b'{"jsonrpc":"2.0","id":50,"method":"ping"}\n'
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "mcp_server.py")],
            cwd=ROOT,
            input=raw_requests,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(
            result.returncode, 0, result.stderr.decode("utf-8", errors="replace")
        )
        self.assertNotIn("\u202e".encode(), result.stdout)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(responses[0]["error"]["code"], -32600)
        self.assertIsNone(responses[0]["id"])
        self.assertEqual(responses[1]["error"]["code"], -32600)
        self.assertEqual(responses[2], {"jsonrpc": "2.0", "id": 50, "result": {}})

        output = io.BytesIO()
        transport = Transport(io.BytesIO(), output)
        transport.write({"jsonrpc": "2.0", "id": 51, "result": {"text": "safe\ud800"}})
        self.assertIn(b"\\ud800", output.getvalue())
        json.loads(output.getvalue())

    def test_malformed_tool_argument_values_return_error_and_continue(self) -> None:
        requests = "\n".join(
            (
                '{"jsonrpc":"2.0","id":39,"method":"initialize","params":{"protocolVersion":"2025-11-25"}}',
                '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}',
                '{"jsonrpc":"2.0","id":40,"method":"tools/call","params":{"name":"banana_plan","arguments":{"prompt":[]}}}',
                '{"jsonrpc":"2.0","id":41,"method":"tools/call","params":{"name":"banana_plan","arguments":{"prompt":{}}}}',
                '{"jsonrpc":"2.0","id":42,"method":"tools/call","params":{"name":"banana_portfolio_plan","arguments":{"prompts":{},"models":[]}}}',
                '{"jsonrpc":"2.0","id":43,"method":"ping"}',
            )
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "mcp_server.py")],
            cwd=ROOT,
            input=requests + "\n",
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        for response in responses[1:4]:
            self.assertTrue(response["result"]["isError"])
            error = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(error["code"], "invalid_arguments")
        self.assertEqual(responses[4], {"jsonrpc": "2.0", "id": 43, "result": {}})

    def test_overlarge_json_number_returns_error_and_server_continues(self) -> None:
        overlarge_integer = "9" * 4000
        requests = "\n".join(
            (
                '{"jsonrpc":"2.0","id":44,"method":"initialize","params":{"protocolVersion":"2025-11-25"}}',
                '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}',
                '{"jsonrpc":"2.0","id":45,"method":"tools/call","params":{"name":"banana_typeset","arguments":{"image":"unused.png","text":"safe","x":'
                + overlarge_integer
                + ',"y":0,"font_size":12}}}',
                '{"jsonrpc":"2.0","id":46,"method":"ping"}',
            )
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "mcp_server.py")],
            cwd=ROOT,
            input=requests + "\n",
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses), 3)
        self.assertTrue(responses[1]["result"]["isError"])
        error = json.loads(responses[1]["result"]["content"][0]["text"])
        self.assertEqual(error["code"], "invalid_arguments")
        self.assertNotIn(overlarge_integer, result.stdout)
        self.assertEqual(responses[2], {"jsonrpc": "2.0", "id": 46, "result": {}})

    def test_tool_schema_validation_never_reflects_malformed_values(self) -> None:
        private_value = "synthetic-private-tool-value-never-echo"
        cases = (
            (
                "banana_portfolio_plan",
                {
                    "prompts": ["safe prompt"],
                    "models": ["gemini-3.1-flash-image"],
                    "workers": private_value,
                },
            ),
            (
                "banana_typeset",
                {
                    "image": "safe.jpg",
                    "text": "safe",
                    "x": private_value,
                    "y": 1,
                    "font_size": 12,
                },
            ),
            (
                "banana_plan",
                {
                    "prompt": "safe prompt",
                    private_value: True,
                },
            ),
        )
        for index, (name, arguments) in enumerate(cases, start=70):
            with self.subTest(name=name):
                response = handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": index,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                    }
                )
                assert response is not None
                rendered = json.dumps(response)
                self.assertNotIn(private_value, rendered)
                error = json.loads(response["result"]["content"][0]["text"])
                self.assertEqual(error["code"], "invalid_arguments")

    def test_unknown_tool_name_is_not_reflected(self) -> None:
        private_name = "synthetic-private-tool-name-never-echo"
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 73,
                "method": "tools/call",
                "params": {"name": private_name, "arguments": {}},
            }
        )
        assert response is not None
        rendered = json.dumps(response)
        self.assertNotIn(private_name, rendered)
        error = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(error["code"], "unknown_tool")

    def test_unknown_method_is_not_reflected(self) -> None:
        private_method = "synthetic-private-method-never-echo"
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 74,
                "method": private_method,
                "params": {},
            }
        )
        assert response is not None
        rendered = json.dumps(response)
        self.assertNotIn(private_method, rendered)
        self.assertEqual(response["error"]["code"], -32601)
        self.assertEqual(response["error"]["message"], "Method not found.")

    def test_transport_rejects_invalid_or_excessive_content_length(self) -> None:
        for raw in (
            b"Content-Length: -1\r\n\r\n{}",
            b"Content-Length: +2\r\n\r\n{}",
            b"Content-Length: 1048577\r\n\r\n{}",
            b"Content-Length: 4\r\n\r\n{}",
        ):
            with self.subTest(raw=raw):
                transport = Transport(io.BytesIO(raw), io.BytesIO())
                with self.assertRaises(BananaError) as caught:
                    transport.read()
                self.assertEqual(caught.exception.code, "invalid_transport")

    def test_transport_rejects_excessive_json_nesting(self) -> None:
        raw = b"[" * 100_000 + b"0" + b"]" * 100_000 + b"\n"
        transport = Transport(io.BytesIO(raw), io.BytesIO())
        with self.assertRaises(BananaError) as caught:
            transport.read()
        self.assertEqual(caught.exception.code, "parse_error")

    def test_stdio_rejects_oversized_newline_and_continues(self) -> None:
        oversized = b"x" * (MAX_CONTENT_LENGTH + 1) + b"\n"
        ping = b'{"jsonrpc":"2.0","id":44,"method":"ping"}\n'
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "mcp_server.py")],
            cwd=ROOT,
            input=oversized + ping,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(
            result.returncode, 0, result.stderr.decode("utf-8", errors="replace")
        )
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(responses[0]["error"]["code"], -32600)
        self.assertEqual(responses[1], {"jsonrpc": "2.0", "id": 44, "result": {}})

    def test_stdio_closes_after_unrecoverable_content_length_headers(self) -> None:
        malformed = (
            b"Content-Length: 2\r\n"
            + b"X-Test: value\r\n" * 65
            + b"\r\n{}"
            + b'{"jsonrpc":"2.0","id":45,"method":"ping"}\n'
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "mcp_server.py")],
            cwd=ROOT,
            input=malformed,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"Content-Length message has too many headers", result.stdout)
        self.assertNotIn(b'"id":45', result.stdout)

    def test_non_object_params_return_jsonrpc_error_without_crashing(self) -> None:
        for request_id, method in enumerate(
            ("initialize", "tools/list", "tools/call"), start=10
        ):
            with self.subTest(method=method):
                response = handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": method,
                        "params": [],
                    }
                )
                assert response is not None
                self.assertEqual(response["id"], request_id)
                self.assertEqual(response["error"]["code"], -32602)

        malformed_arguments = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 19,
                "method": "tools/call",
                "params": {"name": "banana_plan", "arguments": ["not", "an", "object"]},
            }
        )
        assert malformed_arguments is not None
        self.assertEqual(malformed_arguments["id"], 19)
        self.assertEqual(malformed_arguments["error"]["code"], -32602)

        requests = "\n".join(
            (
                '{"jsonrpc":"2.0","id":18,"method":"initialize","params":{"protocolVersion":"2025-11-25"}}',
                '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}',
                '{"jsonrpc":"2.0","id":20,"method":"tools/call","params":[]}',
                '{"jsonrpc":"2.0","id":21,"method":"ping"}',
            )
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "mcp_server.py")],
            cwd=ROOT,
            input=requests + "\n",
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(responses[1]["error"]["code"], -32602)
        self.assertEqual(responses[2]["id"], 21)
        self.assertEqual(responses[2]["result"], {})

    def test_stdio_rejects_non_object_json_and_continues(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "mcp_server.py")],
            cwd=ROOT,
            input='[]\nnull\n{"jsonrpc":"2.0","id":30,"method":"ping"}\n',
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(
            [response["error"]["code"] for response in responses[:2]], [-32600, -32600]
        )
        self.assertEqual(responses[2], {"jsonrpc": "2.0", "id": 30, "result": {}})

    def test_mcp_typeset_is_local_and_refuses_silent_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            output = Path(directory) / "exact.svg"
            image.write_bytes(PNG_1X1)
            arguments = {
                "image": str(image),
                "text": "Exact copy",
                "output": str(output),
                "x": 0.1,
                "y": 0.5,
                "font_size": 0.2,
            }
            result = call_tool("banana_typeset", arguments)
            self.assertFalse(result["isError"])
            payload = json.loads(result["content"][0]["text"])
            self.assertEqual(payload["path"], str(output))
            with self.assertRaises(BananaError) as caught:
                call_tool("banana_typeset", arguments)
            self.assertEqual(caught.exception.code, "output_exists")

    def test_mcp_typeset_supports_ordered_text_and_logo_layers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            logo = Path(directory) / "logo.png"
            output = Path(directory) / "branded.svg"
            image.write_bytes(PNG_1X1)
            logo.write_bytes(PNG_1X1)
            result = call_tool(
                "banana_typeset",
                {
                    "image": str(image),
                    "output": str(output),
                    "layers": [
                        {
                            "type": "image",
                            "name": "logo",
                            "path": str(logo),
                            "x": 0,
                            "y": 0,
                            "width": 1,
                            "height": 1,
                        },
                        {
                            "type": "text",
                            "name": "headline",
                            "text": "Exact",
                            "x": 0,
                            "y": 0.4,
                            "font_size": 0.2,
                        },
                        {
                            "type": "text",
                            "name": "legal",
                            "text": "Terms apply",
                            "x": 0,
                            "y": 0.8,
                            "font_size": 0.08,
                        },
                    ],
                },
            )
            payload = json.loads(result["content"][0]["text"])
            self.assertEqual(payload["layer_count"], 3)
            self.assertEqual(payload["image_layer_count"], 1)
            self.assertEqual(payload["text_layer_count"], 2)
            self.assertEqual(payload["visual_review_status"], "needs_review")

    def test_mcp_typeset_validation_accepts_exactly_one_input_form(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            logo = Path(directory) / "logo.png"
            image.write_bytes(PNG_1X1)
            logo.write_bytes(PNG_1X1)
            single = {
                "image": str(image),
                "text": "Exact",
                "output": str(Path(directory) / "single.svg"),
                "x": 0,
                "y": 0.5,
                "font_size": 0.2,
            }
            layered = {
                "image": str(image),
                "output": str(Path(directory) / "layers.svg"),
                "layers": [
                    {
                        "type": "image",
                        "name": "logo",
                        "path": str(logo),
                        "x": 0,
                        "y": 0,
                        "width": 1,
                        "height": 1,
                    }
                ],
            }
            both = {
                **single,
                "output": str(Path(directory) / "both.svg"),
                "layers": layered["layers"],
            }
            neither = {"image": str(image)}

            for request_id, arguments in enumerate((single, layered), start=80):
                response = handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {
                            "name": "banana_typeset",
                            "arguments": arguments,
                        },
                    }
                )
                assert response is not None
                self.assertFalse(response["result"]["isError"])

            for request_id, arguments in enumerate((both, neither), start=82):
                response = handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {
                            "name": "banana_typeset",
                            "arguments": arguments,
                        },
                    }
                )
                assert response is not None
                self.assertTrue(response["result"]["isError"])
                error = json.loads(response["result"]["content"][0]["text"])
                self.assertEqual(error["code"], "invalid_arguments")

    def test_invalid_tool_arguments_return_structured_error(self) -> None:
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "banana_edit", "arguments": {}},
            }
        )
        assert response is not None
        self.assertTrue(response["result"]["isError"])
        error = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(error["code"], "invalid_arguments")

    def test_edit_schema_rejects_missing_structured_brief(self) -> None:
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 47,
                "method": "tools/call",
                "params": {
                    "name": "banana_edit",
                    "arguments": {
                        "prompt": "Preserve the supplied subject.",
                        "approval_id": "bap_schema_only",
                        "references": [],
                    },
                },
            }
        )
        assert response is not None
        self.assertTrue(response["result"]["isError"])
        error = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(error["code"], "invalid_arguments")

    def test_mcp_rejects_bidirectional_prompt_controls(self) -> None:
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 46,
                "method": "tools/call",
                "params": {
                    "name": "banana_plan",
                    "arguments": {"prompt": "safe\u202eoverride"},
                },
            }
        )
        assert response is not None
        self.assertTrue(response["result"]["isError"])
        error = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(error["code"], "unsafe_approval_text")

    def test_transport_supports_newline_and_content_length(self) -> None:
        newline_in = io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
        newline_out = io.BytesIO()
        newline = Transport(newline_in, newline_out)
        newline_message = newline.read()
        assert newline_message is not None
        self.assertEqual(newline_message["method"], "ping")
        newline.write({"jsonrpc": "2.0", "id": 1, "result": {}})
        self.assertTrue(newline_out.getvalue().endswith(b"\n"))

        body = b'{"jsonrpc":"2.0","id":2,"method":"ping"}'
        framed_in = io.BytesIO(
            f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        )
        framed_out = io.BytesIO()
        framed = Transport(framed_in, framed_out)
        framed_message = framed.read()
        assert framed_message is not None
        self.assertEqual(framed_message["id"], 2)
        framed.write({"jsonrpc": "2.0", "id": 2, "result": {}})
        self.assertTrue(framed_out.getvalue().startswith(b"Content-Length:"))

    def test_stdio_server_handshake(self) -> None:
        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "mcp_server.py")],
            cwd=ROOT,
            input=request + "\n",
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["result"]["serverInfo"]["name"], "banana-claude")


if __name__ == "__main__":
    unittest.main()
