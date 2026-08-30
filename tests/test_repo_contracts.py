from __future__ import annotations

import json
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tests._support import ROOT

VERSION = "3.0.0"
LOCAL_STATE_PARTS = {
    ".banana",
    ".claude",
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "node_modules",
    "venv",
}
LOCAL_STATE_ROOTS = {"cover-options", "scripts"}


def is_maintained_path(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return (
        bool(relative.parts)
        and relative.parts[0] not in LOCAL_STATE_ROOTS
        and not any(part in LOCAL_STATE_PARTS for part in relative.parts)
    )


class RepositoryContractTests(unittest.TestCase):
    def test_required_plugin_runtime_and_review_files_exist(self) -> None:
        required = [
            ".claude-plugin/plugin.json",
            ".claude-plugin/marketplace.json",
            ".mcp.json",
            "skills/banana/SKILL.md",
            "skills/banana/references/models.json",
            "skills/banana/references/gemini-models.md",
            "skills/banana/references/prompt-engineering.md",
            "skills/banana/references/mcp-tools.md",
            "skills/banana/references/review-and-recovery.md",
            "skills/banana/references/cost-tracking.md",
            "skills/banana/references/presets.md",
            "skills/banana/references/post-processing.md",
            "skills/banana/scripts/banana_core.py",
            "skills/banana/scripts/approval_store.py",
            "skills/banana/scripts/mcp_server.py",
            "skills/banana/scripts/generate.py",
            "skills/banana/scripts/edit.py",
            "skills/banana/scripts/portfolio.py",
            "skills/banana/scripts/typeset.py",
            "skills/banana/scripts/batch.py",
            "skills/banana/scripts/cost_tracker.py",
            "skills/banana/scripts/presets.py",
            "skills/banana/scripts/legacy_cleanup.py",
            "skills/banana/scripts/doctor.py",
            "agents/visual-architect.md",
            "agents/visual-critic.md",
            "tools/installer_lifecycle.py",
            "install.sh",
            "pyproject.toml",
            "requirements-dev.txt",
            "screenshots/banana-claude-character-loop.gif",
            "screenshots/cover-image-v3.webp",
            "screenshots/social-preview-v3.jpg",
            ".github/releases/v3.0.0.md",
        ]
        missing = [path for path in required if not (ROOT / path).is_file()]
        self.assertEqual(missing, [])
        self.assertFalse((ROOT / "skills/banana/scripts/setup_mcp.py").exists())
        self.assertFalse((ROOT / "skills/banana/scripts/validate_setup.py").exists())
        self.assertFalse((ROOT / "agents/brief-constructor.md").exists())
        for obsolete_screenshot in (
            "banana-claude-skillcommand.gif",
            "domain-modes.webp",
            "pipeline-flow.webp",
            "reasoning-brief.webp",
        ):
            self.assertFalse((ROOT / "screenshots" / obsolete_screenshot).exists())

    def test_skill_component_inventory_is_closed_and_routed(self) -> None:
        reference_names = {
            "cost-tracking.md",
            "gemini-models.md",
            "mcp-tools.md",
            "models.json",
            "post-processing.md",
            "presets.md",
            "prompt-engineering.md",
            "review-and-recovery.md",
        }
        script_names = {
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
        agent_names = {"visual-architect.md", "visual-critic.md"}
        tool_names = {"__init__.py", "installer_lifecycle.py"}

        references = ROOT / "skills/banana/references"
        scripts = ROOT / "skills/banana/scripts"
        agents = ROOT / "agents"
        tools = ROOT / "tools"
        self.assertEqual(
            {path.name for path in references.iterdir() if path.is_file()},
            reference_names,
        )
        self.assertEqual({path.name for path in scripts.glob("*.py")}, script_names)
        self.assertEqual({path.name for path in agents.glob("*.md")}, agent_names)
        self.assertEqual({path.name for path in tools.glob("*.py")}, tool_names)

        skill = (ROOT / "skills/banana/SKILL.md").read_text(encoding="utf-8")
        for name in reference_names - {"models.json"}:
            with self.subTest(reference=name):
                self.assertIn(f"references/{name}", skill)

    def test_json_files_parse_and_model_sources_are_primary(self) -> None:
        def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON key: {key}")
                result[key] = value
            return result

        for path in ROOT.rglob("*.json"):
            if is_maintained_path(path):
                with self.subTest(path=path):
                    json.loads(
                        path.read_text(encoding="utf-8"),
                        object_pairs_hook=reject_duplicate_keys,
                    )
        catalog = json.loads(
            (ROOT / "skills/banana/references/models.json").read_text(encoding="utf-8")
        )
        self.assertEqual(catalog["verified_on"], "2026-08-29")
        self.assertTrue(catalog["sources"])
        self.assertTrue(
            all(
                source.startswith("https://ai.google.dev/")
                for source in catalog["sources"]
            )
        )
        self.assertEqual(
            catalog["models"]["gemini-3.1-flash-image"]["output_mime_types"],
            ["image/jpeg"],
        )
        self.assertEqual(
            catalog["models"]["gemini-3-pro-image"]["output_mime_types"], ["image/jpeg"]
        )
        self.assertTrue(
            all(
                model["output_mime_types"] == ["image/jpeg"]
                for model in catalog["models"].values()
            )
        )
        self.assertEqual(
            catalog["api_profiles"]["interactions"]["output_mime_documentation"][
                "reported_probe_on"
            ],
            "2026-08-28",
        )
        interactions_live = catalog["api_profiles"]["interactions"][
            "reported_live_probe"
        ]
        self.assertEqual(
            catalog["api_profiles"]["interactions"]["supported_models"],
            ["gemini-3.1-flash-image", "gemini-3-pro-image"],
        )
        self.assertEqual(
            catalog["api_profiles"]["generate_content"]["supported_models"],
            ["gemini-3.1-flash-lite-image", "gemini-2.5-flash-image"],
        )
        self.assertEqual(interactions_live["reported_on"], "2026-08-28")
        self.assertNotIn("verified_on", interactions_live)
        self.assertNotIn("accepted_models", interactions_live)
        self.assertNotIn("rejected_model", interactions_live)
        self.assertNotIn("rejected_response_format_test_model", interactions_live)
        self.assertEqual(interactions_live["model"], "gemini-3-pro-image")
        self.assertEqual(
            interactions_live["rejected_response_format"],
            {"mime_type": "image/png"},
        )
        wire_values = catalog["api_profiles"]["generate_content"]["wire_values"]
        self.assertEqual(wire_values["aspect_ratio"]["1:1"], "ASPECT_RATIO_ONE_BY_ONE")
        self.assertEqual(wire_values["image_size"]["1K"], "IMAGE_SIZE_ONE_K")
        self.assertEqual(wire_values["output_mime_type"], {"image/jpeg": "IMAGE_JPEG"})
        live = catalog["api_profiles"]["generate_content"]["reported_live_probe"]
        self.assertEqual(live["reported_on"], "2026-08-28")
        self.assertNotIn("verified_on", live)
        self.assertEqual(live["model"], "gemini-3.1-flash-lite-image")
        self.assertEqual(
            live["request"],
            {
                "mimeType": "IMAGE_JPEG",
                "aspectRatio": "ASPECT_RATIO_ONE_BY_ONE",
                "imageSize": "IMAGE_SIZE_ONE_K",
            },
        )
        self.assertEqual(
            live["response"], {"mime_type": "image/jpeg", "width": 1024, "height": 1024}
        )
        ledger = catalog["claim_ledger"]
        self.assertEqual(ledger["schema_version"], 1)
        self.assertEqual(ledger["retrieval_precision"], "date")
        claims = ledger["claims"]
        claim_ids = [claim["id"] for claim in claims]
        self.assertEqual(len(claim_ids), len(set(claim_ids)))
        self.assertGreaterEqual(len(claims), 10)
        for claim in claims:
            with self.subTest(claim=claim["id"]):
                self.assertEqual(
                    set(claim),
                    {
                        "id",
                        "claim",
                        "evidence_type",
                        "source_urls",
                        "retrieved_on",
                        "refresh_due",
                        "evidence_digest",
                        "independently_auditable_from_package",
                        "current_source_recheck_possible",
                    },
                )
                self.assertIn(
                    claim["evidence_type"],
                    {"official_documentation", "reported_redacted_live_probe"},
                )
                self.assertTrue(claim["source_urls"])
                self.assertTrue(
                    all(
                        source.startswith("https://ai.google.dev/")
                        for source in claim["source_urls"]
                    )
                )
                self.assertTrue(
                    set(claim["source_urls"]).issubset(set(catalog["sources"]))
                )
                self.assertLess(
                    date.fromisoformat(claim["retrieved_on"]),
                    date.fromisoformat(claim["refresh_due"]),
                )
                self.assertEqual(
                    claim["evidence_digest"],
                    {"sha256": None, "status": "not_captured"},
                )
                self.assertFalse(claim["independently_auditable_from_package"])
        self.assertEqual(
            interactions_live["evidence_claim_id"],
            "interactions-png-rejection-probe",
        )
        self.assertEqual(live["evidence_claim_id"], "flash-lite-jpeg-probe")

    def test_sensitive_plugin_configuration_and_bundled_mcp(self) -> None:
        manifest = json.loads(
            (ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8")
        )
        marketplace = json.loads(
            (ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
        )
        self.assertIs(manifest["defaultEnabled"], False)
        self.assertIs(marketplace["plugins"][0]["defaultEnabled"], False)
        secret = manifest["userConfig"]["google_ai_api_key"]
        self.assertTrue(secret["sensitive"])
        self.assertTrue(secret["required"])

        mcp = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))[
            "mcpServers"
        ]["banana"]
        self.assertEqual(mcp["command"], "python3")
        self.assertEqual(
            mcp["args"],
            ["${CLAUDE_PLUGIN_ROOT}/skills/banana/scripts/mcp_server.py"],
        )
        self.assertEqual(
            mcp["env"]["GEMINI_API_KEY"], "${user_config.google_ai_api_key}"
        )
        self.assertNotIn("npx", json.dumps(mcp).lower())

    def test_release_version_is_consistent(self) -> None:
        manifest = json.loads(
            (ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8")
        )
        citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        skill = (ROOT / "skills/banana/SKILL.md").read_text(encoding="utf-8")
        server = (ROOT / "skills/banana/scripts/mcp_server.py").read_text(
            encoding="utf-8"
        )
        core = (ROOT / "skills/banana/scripts/banana_core.py").read_text(
            encoding="utf-8"
        )
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(manifest["version"], VERSION)
        self.assertIn(f'version: "{VERSION}"', skill)
        self.assertIn(f'SERVER_VERSION = "{VERSION}"', server)
        self.assertIn(f"banana-claude/{VERSION}", core)
        self.assertIn(f'INSTALL_VERSION="{VERSION}"', installer)
        self.assertIn(f"version-{VERSION}-", readme)
        self.assertIn(f'version: "{VERSION}"', citation)
        repository_url = "https://github.com/AgriciDaniel/banana-claude"
        self.assertIn(f'repository-code: "{repository_url}"', citation)
        self.assertIn(f'url: "{repository_url}"', citation)
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        release_heading = f"## [{VERSION}] - 2026-08-30"
        self.assertIn(release_heading, changelog)
        unreleased = changelog.split("## [Unreleased]", 1)[1].split("\n## ", 1)[0]
        self.assertEqual(unreleased.strip(), "")
        release_section = changelog.split(release_heading, 1)[1].split("\n## ", 1)[0]
        self.assertIn("Portfolio and edit MCP schemas", release_section)
        self.assertIn("reported provider probes", release_section)
        self.assertIn("Pinned development-only Ruff and Mypy", release_section)

    def test_release_media_and_highlights_are_linked_and_bounded(self) -> None:
        def jpeg_dimensions(data: bytes) -> tuple[int, int]:
            self.assertTrue(data.startswith(b"\xff\xd8"))
            offset = 2
            start_of_frame = {
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
            }
            while offset + 4 <= len(data):
                self.assertEqual(data[offset], 0xFF)
                while offset < len(data) and data[offset] == 0xFF:
                    offset += 1
                self.assertLess(offset, len(data))
                marker = data[offset]
                offset += 1
                if marker in {0x01, 0xD8, 0xD9}:
                    continue
                self.assertLessEqual(offset + 2, len(data))
                segment_length = int.from_bytes(data[offset : offset + 2], "big")
                self.assertGreaterEqual(segment_length, 2)
                self.assertLessEqual(offset + segment_length, len(data))
                if marker in start_of_frame:
                    self.assertGreaterEqual(segment_length, 7)
                    height = int.from_bytes(data[offset + 3 : offset + 5], "big")
                    width = int.from_bytes(data[offset + 5 : offset + 7], "big")
                    return width, height
                offset += segment_length
            self.fail("JPEG start-of-frame marker was not found")

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        highlights = ROOT / ".github/releases/v3.0.0.md"
        gif = ROOT / "screenshots/banana-claude-character-loop.gif"
        social = ROOT / "screenshots/social-preview-v3.jpg"

        self.assertIn("screenshots/banana-claude-character-loop.gif", readme)
        self.assertIn(".github/releases/v3.0.0.md", changelog)
        self.assertIn('date-released: "2026-08-30"', citation)
        self.assertIn("*.gif binary", attributes)
        self.assertIn("*.webp binary", attributes)
        highlights_text = highlights.read_text(encoding="utf-8")
        self.assertIn("# Banana Claude 3.0.0", highlights_text)
        self.assertIn(
            "387 deterministic offline tests on Python 3.11 and Python 3.14.",
            highlights_text,
        )

        gif_data = gif.read_bytes()
        self.assertIn(gif_data[:6], {b"GIF87a", b"GIF89a"})
        self.assertEqual(
            (
                int.from_bytes(gif_data[6:8], "little"),
                int.from_bytes(gif_data[8:10], "little"),
            ),
            (960, 536),
        )
        self.assertLess(gif.stat().st_size, 10_000_000)

        social_data = social.read_bytes()
        self.assertEqual(jpeg_dimensions(social_data), (1280, 640))
        self.assertLess(social.stat().st_size, 1_000_000)

    def test_no_credential_cli_or_key_bearing_request_surface(self) -> None:
        product_paths = [
            ROOT / ".claude-plugin",
            ROOT / ".mcp.json",
            ROOT / "agents",
            ROOT / "skills",
            ROOT / "tools",
            ROOT / "README.md",
            ROOT / "SECURITY.md",
            ROOT / "install.sh",
        ]
        texts = []
        text_suffixes = {".md", ".py", ".json", ".yml", ".yaml", ".sh", ".cff", ".txt"}
        for path in product_paths:
            candidates = (
                [path]
                if path.is_file()
                else [item for item in path.rglob("*") if item.is_file()]
            )
            for candidate in candidates:
                if (
                    candidate.suffix.lower() not in text_suffixes
                    and candidate.name not in {"CODEOWNERS", "LICENSE"}
                ):
                    continue
                texts.append((candidate, candidate.read_text(encoding="utf-8")))
        forbidden = ["?key=", "&key=", "--api" + "-key", "--" + "key"]
        failures = []
        for path, content in texts:
            for token in forbidden:
                if token in content:
                    failures.append(f"{path.relative_to(ROOT)} contains {token}")
        self.assertEqual(failures, [])

    def test_retired_models_appear_only_in_explicit_history(self) -> None:
        retired = {
            "gemini-3.1-flash-image-preview",
            "gemini-3-pro-image-preview",
            "gemini-2.5-flash-image-preview",
        }
        allowed = {
            Path("CHANGELOG.md"),
            Path("skills/banana/references/models.json"),
            Path("skills/banana/references/gemini-models.md"),
        }
        failures = []
        text_suffixes = {".md", ".py", ".json", ".yml", ".yaml", ".sh", ".cff", ".txt"}
        for path in ROOT.rglob("*"):
            if (
                not path.is_file()
                or not is_maintained_path(path)
                or "tests" in path.parts
            ):
                continue
            if path.suffix.lower() not in text_suffixes and path.name not in {
                "CODEOWNERS",
                "LICENSE",
            }:
                continue
            content = path.read_text(encoding="utf-8")
            if (
                any(model in content for model in retired)
                and path.relative_to(ROOT) not in allowed
            ):
                failures.append(str(path.relative_to(ROOT)))
        self.assertEqual(failures, [])

    def test_provider_probe_and_portfolio_language_matches_runtime_evidence(
        self,
    ) -> None:
        mcp_reference = (ROOT / "skills/banana/references/mcp-tools.md").read_text(
            encoding="utf-8"
        )
        prompting = (ROOT / "skills/banana/references/prompt-engineering.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("dated reported-probe metadata", mcp_reference)
        self.assertIn("not independently verified by this release", mcp_reference)
        self.assertNotIn("dated live-verification record", mcp_reference)
        self.assertNotIn("rejected PNG live", mcp_reference)
        self.assertIn("one shared brief", prompting)
        self.assertIn("separate briefs and separate", prompting)
        self.assertNotIn("differ in thesis or composition", prompting)

    def test_text_contract_has_no_unicode_em_dash(self) -> None:
        failures = []
        text_suffixes = {".md", ".py", ".json", ".yml", ".yaml", ".sh", ".cff", ".txt"}
        for path in ROOT.rglob("*"):
            if not path.is_file() or not is_maintained_path(path):
                continue
            if path.suffix.lower() not in text_suffixes and path.name not in {
                "CODEOWNERS",
                "LICENSE",
            }:
                continue
            if "\N{EM DASH}" in path.read_text(encoding="utf-8"):
                failures.append(str(path.relative_to(ROOT)))
        self.assertEqual(failures, [])

    def test_post_processing_recipes_use_atomic_no_replace_renderer(self) -> None:
        reference = (ROOT / "skills/banana/references/post-processing.md").read_text(
            encoding="utf-8"
        )
        normalized_reference = " ".join(reference.split())
        self.assertIn(
            "The helper call is mandatory for every fixed output and every "
            "computed destination inside a loop.",
            normalized_reference,
        )
        self.assertIn(
            "That link operation is atomic and no-replace", normalized_reference
        )
        self.assertIn("single-link final file", normalized_reference)
        self.assertIn(
            "owned by the current user and not group-writable or world-writable",
            normalized_reference,
        )
        self.assertIn(
            "no ancestor may be renameable by an untrusted party",
            normalized_reference,
        )
        self.assertIn("`SIGKILL`, a power loss, or a host crash", normalized_reference)
        self.assertIn("both names can remain with link count two", normalized_reference)
        self.assertIn(
            "guaranteed only after a successful helper return", normalized_reference
        )
        self.assertNotIn("banana_require_new_destination", reference)

        bash_blocks = re.findall(r"```bash\n(.*?)\n```", reference, flags=re.DOTALL)
        helper = next(
            block for block in bash_blocks if "banana_render_new_destination()" in block
        )
        for required in (
            "tempfile.mkdtemp(",
            "subprocess.run(",
            "os.link(rendered, destination, follow_symlinks=False)",
            "except FileExistsError:",
            "rendered_info.st_nlink != 1",
            "final_info.st_nlink != 1",
            "parent_info.st_mode & 0o022",
            "shutil.rmtree(",
        ):
            with self.subTest(helper_contract=required):
                self.assertIn(required, helper)
        self.assertNotIn("os.replace(", helper)
        self.assertNotIn("os.rename(", helper)

        output_tool = re.compile(
            r"(?m)^\s*(?:(?:magick(?!\s+identify\b)|convert|ffmpeg|potrace)\b|"
            r'python3 "\$CLAUDE_SKILL_DIR/scripts/typeset\.py"(?=\s))'
        )
        tool_count = 0
        literal_destinations: list[str] = []
        for block in bash_blocks:
            block_tool_count = len(output_tool.findall(block))
            if block_tool_count == 0:
                continue
            with self.subTest(block=block):
                wrapper_count = len(
                    re.findall(r"(?m)^\s*banana_render_new_destination\s+", block)
                )
                placeholder_count = block.count('"__BANANA_RENDER_OUTPUT__"')
                self.assertEqual(wrapper_count, block_tool_count)
                self.assertEqual(placeholder_count, block_tool_count)
                without_wrapper_destinations = re.sub(
                    r'(?m)^\s*banana_render_new_destination\s+"[^"]+"\s*\\?$',
                    "",
                    block,
                )
                destinations = re.findall(
                    r'(?m)^\s*banana_render_new_destination\s+"([^"]+)"', block
                )
                for destination in destinations:
                    self.assertNotIn(destination, without_wrapper_destinations)
                literal_destinations.extend(
                    destination
                    for destination in destinations
                    if not destination.startswith("$")
                )
                tool_count += block_tool_count

        self.assertEqual(tool_count, 29)
        self.assertEqual(len(literal_destinations), len(set(literal_destinations)))

    def test_documented_renderer_rejects_a_racing_destination_and_cleans(self) -> None:
        reference = (ROOT / "skills/banana/references/post-processing.md").read_text(
            encoding="utf-8"
        )
        helper = next(
            block
            for block in re.findall(r"```bash\n(.*?)\n```", reference, flags=re.DOTALL)
            if "banana_render_new_destination()" in block
        )

        def run_helper(
            destination: Path, producer: str
        ) -> subprocess.CompletedProcess[str]:
            invocation = (
                '\nbanana_render_new_destination "$1" "$2" -c "$3" '
                '"__BANANA_RENDER_OUTPUT__" "$1"\n'
            )
            return subprocess.run(
                ["bash", "-s", "--", str(destination), sys.executable, producer],
                input=helper + invocation,
                text=True,
                capture_output=True,
                check=False,
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "final.png"
            success = run_helper(
                destination,
                "from pathlib import Path; import sys; "
                "Path(sys.argv[1]).write_bytes(b'complete')",
            )
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(destination.read_bytes(), b"complete")
            self.assertEqual(destination.stat().st_nlink, 1)
            self.assertEqual(list(root.iterdir()), [destination])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "final.png"
            raced = run_helper(
                destination,
                "from pathlib import Path; import sys; "
                "Path(sys.argv[1]).write_bytes(b'candidate'); "
                "Path(sys.argv[2]).write_bytes(b'racer')",
            )
            self.assertNotEqual(raced.returncode, 0)
            self.assertEqual(destination.read_bytes(), b"racer")
            self.assertEqual(destination.stat().st_nlink, 1)
            self.assertEqual(list(root.iterdir()), [destination])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "final.png"
            failed = run_helper(
                destination,
                "from pathlib import Path; import sys; "
                "Path(sys.argv[1]).write_bytes(b'partial'); raise SystemExit(7)",
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse(destination.exists())
            self.assertEqual(list(root.iterdir()), [])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "final.png"
            invalid = run_helper(
                destination,
                "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertFalse(destination.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_current_operating_docs_do_not_restore_retired_claims(self) -> None:
        current_paths = [
            ROOT / "README.md",
            ROOT / "CLAUDE.md",
            ROOT / "SECURITY.md",
            ROOT / "agents",
            ROOT / "skills/banana",
        ]
        forbidden = {
            "Flash or Lite": "video input is Flash Image only",
            "Google also documents Lite video-to-image": (
                "video input is Flash Image only"
            ),
            "video-to-image for both Gemini 3.1 Flash and Lite": (
                "video input is Flash Image only"
            ),
            "Google documents Flash and Lite video context": (
                "video input is Flash Image only"
            ),
            "provider role": "reference roles are Banana prompt annotations",
            "provider category": "reference categories are Banana policy",
            "nine parallel": "portfolio execution is capped at three concurrent attempts",
            "current GA model IDs": "the compatibility route is deprecated",
            "python3 scripts/": "skill commands must resolve from the skill directory",
        }
        failures = []
        for root in current_paths:
            candidates = (
                [root]
                if root.is_file()
                else [path for path in root.rglob("*") if path.is_file()]
            )
            for path in candidates:
                if path.suffix.lower() not in {".md", ".py", ".json"}:
                    continue
                content = path.read_text(encoding="utf-8")
                for phrase, reason in forbidden.items():
                    if phrase in content:
                        failures.append(
                            f"{path.relative_to(ROOT)} contains {phrase!r}: {reason}"
                        )
        self.assertEqual(failures, [])

    def test_local_secret_and_state_patterns_are_ignored(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".env", ignore)
        self.assertIn(".env.*", ignore)
        self.assertIn("*.key", ignore)
        self.assertIn(".banana/", ignore)
        self.assertIn(".claude/settings.local.json", ignore)

    def test_standalone_installer_uses_a_source_allowlist(self) -> None:
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        lifecycle = (ROOT / "tools/installer_lifecycle.py").read_text(encoding="utf-8")
        self.assertNotIn("cp -a", installer)
        self.assertNotIn("find ", installer)
        self.assertIn('"${SOURCE_DIR}" "${STAGE_SKILL}"', installer)
        self.assertIn('"SKILL.md"', lifecycle)
        self.assertIn('{".md", ".json"}', lifecycle)
        self.assertIn('{".py"}', lifecycle)
        self.assertIn("if snapshot != expected_entries", lifecycle)

    def test_agents_are_read_only_and_not_skill_preloaded(self) -> None:
        for path in (ROOT / "agents").glob("*.md"):
            content = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertRegex(content, r"(?m)^tools: Read$")
                self.assertNotRegex(content, r"(?m)^skills:")
        critic = (ROOT / "agents/visual-critic.md").read_text(encoding="utf-8")
        self.assertIn("SVG source is not pixel evidence", critic)
        self.assertIn("return `BLOCKED`", critic)

    def test_visual_architect_status_blocks_uncompiled_prompts(self) -> None:
        architect = (ROOT / "agents/visual-architect.md").read_text(encoding="utf-8")
        self.assertIn("STATUS\n[READY | BLOCKED]", architect)
        self.assertIn("keeps the unresolved brief visible for correction", architect)
        self.assertIn(
            "For `BLOCKED`, the entire `COMPILED PROMPT`\n"
            "   section must be exactly `[Not compiled]`.",
            architect,
        )
        self.assertIn(
            "For `READY`, provide a real,\n"
            "   model-ready prompt and never use that placeholder.",
            architect,
        )

    def test_prompt_only_review_never_invents_direction_fields(self) -> None:
        review = (ROOT / "skills/banana/references/review-and-recovery.md").read_text(
            encoding="utf-8"
        )
        normalized = " ".join(review.split())
        self.assertIn(
            "runtime-only `prompt_only` mode with `brief_source: planner_minimal`",
            normalized,
        )
        self.assertIn(
            "judge adherence to the exact approved prompt and aesthetic coherence "
            "with that prompt",
            normalized,
        )
        self.assertIn(
            "Do not require, reconstruct, or invent a separate thesis, signature, "
            "or avoid field",
            normalized,
        )
        self.assertIn("Do not relabel `prompt_only` as `not_applicable`", normalized)

    def test_ci_actions_are_sha_pinned_and_provider_offline(self) -> None:
        workflow = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")
        uses = re.findall(r"(?m)^\s*uses:\s*(\S+)", workflow)
        self.assertTrue(uses)
        self.assertTrue(all(re.search(r"@[0-9a-f]{40}$", value) for value in uses))
        self.assertNotIn("npm install", workflow)
        self.assertNotIn("GEMINI_API_KEY", workflow)
        self.assertIn('python-version: ["3.11", "3.14"]', workflow)
        self.assertNotIn('python-version: ["3.10", "3.14"]', workflow)
        self.assertIn(
            "pip install --disable-pip-version-check -r requirements-dev.txt",
            workflow,
        )
        self.assertIn(
            "ruff check --no-cache skills/banana/scripts tools tests", workflow
        )
        self.assertIn(
            "ruff format --check --no-cache skills/banana/scripts tools tests",
            workflow,
        )
        self.assertIn(
            "mypy --strict --no-incremental skills/banana/scripts tools tests",
            workflow,
        )
        self.assertIn("\n  validate:\n    name: validate\n", workflow)
        self.assertIn("needs: [offline-tests, repository-contract]", workflow)
        self.assertIn(
            'test "${OFFLINE_TESTS_RESULT}" = "success"',
            workflow,
        )
        self.assertIn(
            'test "${REPOSITORY_CONTRACT_RESULT}" = "success"',
            workflow,
        )
        requirements = [
            line
            for line in (ROOT / "requirements-dev.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(requirements, ["mypy==2.3.1", "ruff==0.16.5"])
        tool_config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('target-version = "py311"', tool_config)
        self.assertIn('select = ["E4", "E7", "E9", "F", "I"]', tool_config)
        self.assertIn('test-bootstrap = ["tests._support"]', tool_config)
        self.assertIn('python_version = "3.11"', tool_config)
        self.assertIn("strict = true", tool_config)

    def test_historical_provider_claims_have_adjacent_supersession_notes(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        version_140 = changelog.split("## [1.4.0]", 1)[1].split("\n## ", 1)[0]
        version_120 = changelog.split("## [1.2.0]", 1)[1].split("\n## ", 1)[0]
        self.assertIn("Historical note added in 3.0.0", version_140)
        self.assertIn("March 9 image-model shutdown date", version_140)
        self.assertIn("banned-word rules", version_140)
        self.assertIn("universal rate", version_140)
        self.assertIn(
            "ALL CAPS was historical advice, not a verified provider",
            version_140,
        )
        self.assertIn("prestige anchors were a historical heuristic", version_140)
        self.assertIn("generic quality words are not provider-banned", version_140)
        self.assertIn("Historical note added in 3.0.0", version_120)
        self.assertIn("universal C2PA", version_120)
        self.assertIn("fixed rate-limit claims", version_120)

    def test_python_floor_is_consistent(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        doctor = (ROOT / "skills/banana/scripts/doctor.py").read_text(encoding="utf-8")
        plugin = (ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8")
        marketplace = (ROOT / ".claude-plugin/marketplace.json").read_text(
            encoding="utf-8"
        )
        self.assertIn("Python 3.11 or newer", readme)
        self.assertIn("Python 3.11 or newer", claude)
        self.assertIn("sys.version_info >= (3, 11)", installer)
        self.assertIn("Python 3.11 or newer is required", installer)
        self.assertIn("sys.version_info >= (3, 11)", doctor)
        self.assertIn("Python 3.11+", plugin)
        self.assertIn("Python 3.11+", marketplace)
        self.assertNotIn("Python 3.10+", plugin)
        self.assertNotIn("Python 3.10+", marketplace)

    def test_skill_size_and_executable_entry_points(self) -> None:
        skill_lines = (ROOT / "skills/banana/SKILL.md").read_text(
            encoding="utf-8"
        ).count("\n") + 1
        self.assertLessEqual(skill_lines, 500)
        paths = [
            ROOT / "install.sh",
            ROOT / "tools/installer_lifecycle.py",
            *(ROOT / "skills/banana/scripts").glob("*.py"),
        ]
        failures = [
            str(path.relative_to(ROOT))
            for path in paths
            if not stat.S_IMODE(path.stat().st_mode) & 0o100
        ]
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
