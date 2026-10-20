from __future__ import annotations

import copy
import json
import tempfile
import unittest
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any
from unittest import mock

from tests._support import PNG_1X1

from banana_core import (
    MAX_JSON_NESTING_DEPTH,
    BananaError,
    build_generate_content_payload,
    build_interaction_payload,
    build_plan,
    enforce_json_nesting_limit,
    estimate_image_cost,
    load_catalog,
    models_supporting_image_size,
    public_plan,
)


def provider_reference(
    path: Path,
    *,
    role: str = "object",
    purpose: str = "preserve source geometry",
    subject_id: str | None = None,
) -> dict[str, str | Path | None]:
    return {
        "path": path,
        "disclosure_alias": "test reference",
        "role": role,
        "purpose": purpose,
        "subject_id": subject_id,
    }


def reference_authority(
    *,
    identity_or_likeness: str = "not_applicable",
    customer_or_private_asset: str = "not_applicable",
    endorsement_or_representation: str = "not_applicable",
    provider_transmission: str = "affirmed",
) -> dict[str, str]:
    return {
        "rights_or_license": "affirmed",
        "identity_or_likeness": identity_or_likeness,
        "customer_or_private_asset": customer_or_private_asset,
        "endorsement_or_representation": endorsement_or_representation,
        "provider_transmission": provider_transmission,
        "intended_use": "Exercise the local test workflow.",
    }


def supplied_visual_brief(
    *,
    references: list[dict[str, Any]] | None = None,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
) -> dict[str, Any]:
    return {
        "schema_version": "banana.visual-brief.v1",
        "goal": "A testable product hero.",
        "facts": ["The product has two controls."],
        "locks": ["Preserve the product geometry."],
        "freedoms": ["Background texture may vary."],
        "direction": {
            "mode": "creative",
            "thesis": "Quiet precision.",
            "signature": "One narrow light stripe.",
            "avoid": "Floating particles.",
        },
        "composition": ["Keep upper-left negative space."],
        "rendering": ["Soft side light."],
        "typography": {"exact_copy": [], "instructions": []},
        "references": references or [],
        "output": {
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
            "mime_type": "image/jpeg",
            "delivery_notes": ["Review at delivery size."],
        },
        "review_tests": ["The result follows the frozen composition."],
    }


def brief_for_references(
    references: list[dict[str, Any]],
    *,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
) -> dict[str, Any]:
    return supplied_visual_brief(
        references=[
            {
                "disclosure_alias": reference["disclosure_alias"],
                "role": reference["role"],
                "purpose": reference["purpose"],
                "subject_id": reference.get("subject_id"),
                "authority": reference.get("authority", reference_authority()),
            }
            for reference in references
        ],
        aspect_ratio=aspect_ratio,
        image_size=image_size,
    )


class JsonBoundaryTests(unittest.TestCase):
    def test_json_nesting_limit_is_explicit_and_interpreter_independent(self) -> None:
        allowed = b"[" * MAX_JSON_NESTING_DEPTH + b"0" + b"]" * MAX_JSON_NESTING_DEPTH
        rejected = b"[" + allowed + b"]"

        enforce_json_nesting_limit(allowed)
        with self.assertRaisesRegex(ValueError, "64-level nesting limit"):
            enforce_json_nesting_limit(rejected)

    def test_json_nesting_scan_ignores_escaped_string_content(self) -> None:
        value = b'{"value":"[{\\"nested\\":true}]"}'

        enforce_json_nesting_limit(value, max_depth=1)


class CatalogTests(unittest.TestCase):
    def test_catalog_has_current_routes_and_verification_date(self) -> None:
        catalog = load_catalog()
        self.assertEqual(catalog["verified_on"], "2026-10-20")
        self.assertEqual(catalog["default_model"], "gemini-nano-banana-2.1")
        self.assertEqual(
            set(catalog["models"]),
            {
                "gemini-3.1-flash-lite-image",
                "gemini-nano-banana-2.1",
                "gemini-3-pro-image",
                "gemini-3.1-flash-image",
            },
        )
        self.assertEqual(
            catalog["models"]["gemini-3.1-flash-image"]["status"], "deprecated"
        )
        self.assertFalse(
            catalog["models"]["gemini-3.1-flash-image"]["shutdown_date_announced"]
        )
        self.assertIn("gemini-2.5-flash-image", catalog["retired_model_ids"])
        self.assertEqual(
            catalog["models"]["gemini-3.1-flash-lite-image"]["api_surface"],
            "generate_content",
        )
        self.assertEqual(
            catalog["models"]["gemini-nano-banana-2.1"]["api_surface"], "interactions"
        )
        self.assertEqual(
            catalog["models"]["gemini-nano-banana-2.1"]["image_sizes"],
            ["1K", "2K", "4K"],
        )
        self.assertEqual(
            catalog["models"]["gemini-3.1-flash-image"]["api_surface"], "interactions"
        )
        self.assertEqual(
            catalog["models"]["gemini-3-pro-image"]["default_image_size"], "1K"
        )
        self.assertTrue(
            catalog["models"]["gemini-3.1-flash-lite-image"]["features"][
                "iterative_editing"
            ]
        )
        self.assertFalse(
            catalog["models"]["gemini-3.1-flash-lite-image"]["features"][
                "server_managed_continuation"
            ]
        )
        self.assertFalse(
            catalog["models"]["gemini-3.1-flash-lite-image"]["features"]["video_input"]
        )
        self.assertTrue(
            catalog["models"]["gemini-3.1-flash-lite-image"]["features"][
                "provider_video_input_documented"
            ]
        )
        self.assertEqual(
            catalog["models"]["gemini-3.1-flash-lite-image"]["features"][
                "video_input_policy"
            ],
            "client_path_not_validated",
        )
        lite_video_docs = catalog["models"]["gemini-3.1-flash-lite-image"]["features"][
            "video_input_documentation"
        ]
        self.assertFalse(lite_video_docs["provider_documentation_conflict"])
        self.assertIn("rejects Lite video", lite_video_docs["note"])
        self.assertIn("Nano Banana 2.1", lite_video_docs["note"])
        default_features = catalog["models"]["gemini-nano-banana-2.1"]["features"]
        self.assertTrue(default_features["video_input"])
        self.assertTrue(default_features["provider_video_input_documented"])
        self.assertEqual(default_features["video_input_policy"], "enabled")
        self.assertNotIn("video_input_documentation", default_features)
        self.assertNotIn(
            "pricing_documentation", catalog["models"]["gemini-nano-banana-2.1"]
        )
        self.assertIn(
            "nano-banana-2-1-video-input",
            catalog["models"]["gemini-nano-banana-2.1"]["evidence_claim_ids"][
                "features"
            ],
        )
        flash = catalog["models"]["gemini-3.1-flash-image"]
        self.assertTrue(flash["features"]["video_input"])
        self.assertEqual(flash["features"]["video_input_policy"], "enabled")
        self.assertIn("only for 512 output", flash["route"])
        self.assertNotIn("video", flash["route"])
        self.assertFalse(
            catalog["models"]["gemini-3-pro-image"]["features"]["video_input"]
        )
        self.assertEqual(
            [
                model_id
                for model_id, model_info in catalog["models"].items()
                if model_info["features"]["video_input"]
            ],
            ["gemini-nano-banana-2.1", "gemini-3.1-flash-image"],
        )
        self.assertTrue(
            {
                "https://ai.google.dev/gemini-api/docs/image-generation",
                "https://ai.google.dev/gemini-api/docs/generate-content/image-generation",
                "https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite-image",
                "https://ai.google.dev/gemini-api/docs/changelog",
            }.issubset(catalog["sources"])
        )
        self.assertEqual(
            catalog["models"]["gemini-3.1-flash-lite-image"]["features"][
                "thinking_default"
            ],
            "minimal",
        )
        self.assertTrue(
            catalog["models"]["gemini-3.1-flash-lite-image"]["features"][
                "thinking_default_documentation_conflict"
            ]
        )
        self.assertEqual(
            catalog["models"]["gemini-3.1-flash-image"]["features"]["thinking_default"],
            "minimal",
        )
        self.assertEqual(
            catalog["models"]["gemini-3.1-flash-image"]["output_mime_types"],
            ["image/jpeg"],
        )
        self.assertEqual(
            catalog["models"]["gemini-3-pro-image"]["output_mime_types"],
            ["image/jpeg"],
        )
        self.assertEqual(
            catalog["models"]["gemini-3.1-flash-lite-image"]["output_mime_types"],
            ["image/jpeg"],
        )
        mime_docs = catalog["api_profiles"]["interactions"]["output_mime_documentation"]
        self.assertTrue(mime_docs["png_conflict"])
        self.assertEqual(mime_docs["reported_probe_on"], "2026-08-28")

    def test_catalog_separates_provider_limits_from_banana_policy(self) -> None:
        catalog = load_catalog()
        lite = catalog["models"]["gemini-3.1-flash-lite-image"]
        self.assertEqual(
            lite["aspect_ratio_policy"]["kind"], "conservative_client_allowlist"
        )
        self.assertTrue(lite["aspect_ratio_policy"]["provider_documentation_conflict"])
        self.assertEqual(len(lite["aspect_ratios"]), 10)

        default = catalog["models"]["gemini-nano-banana-2.1"]["reference_limits"]
        self.assertEqual(default["provider_hard_total"], 14)
        self.assertEqual(default["banana_policy_by_role"]["styles"], 0)

    def test_runtime_provider_fields_have_claim_ledger_coverage(self) -> None:
        catalog = load_catalog()
        claim_ids = {claim["id"] for claim in catalog["claim_ledger"]["claims"]}
        provenance = catalog["catalog_field_provenance"]
        required_groups = set(provenance["model_evidence_groups"])
        self.assertEqual(
            required_groups,
            {
                "identity_and_status",
                "api_surface_and_output_format",
                "formats_and_reference_limits",
                "features",
                "pricing",
            },
        )
        self.assertIn("models.*.route", provenance["local_policy_fields"])
        self.assertIn(
            "models.*.reference_limits.banana_policy_total",
            provenance["local_policy_fields"],
        )

        for model_id, model_info in catalog["models"].items():
            with self.subTest(model=model_id):
                evidence = model_info["evidence_claim_ids"]
                self.assertEqual(set(evidence), required_groups)
                for group, group_claim_ids in evidence.items():
                    self.assertTrue(group_claim_ids, msg=f"{model_id}: {group}")
                    self.assertTrue(set(group_claim_ids).issubset(claim_ids))

        probe_claim = "interactions-png-rejection-probe"
        interactions = catalog["api_profiles"]["interactions"]
        interactions_probe = interactions["reported_live_probe"]
        self.assertEqual(interactions_probe["model"], "gemini-3-pro-image")
        self.assertNotIn("accepted_models", interactions_probe)
        flash_claims = catalog["models"]["gemini-3.1-flash-image"][
            "evidence_claim_ids"
        ]["api_surface_and_output_format"]
        pro_claims = catalog["models"]["gemini-3-pro-image"]["evidence_claim_ids"][
            "api_surface_and_output_format"
        ]
        self.assertNotIn(probe_claim, flash_claims)
        self.assertIn(probe_claim, pro_claims)

        flash_public = public_plan(
            build_plan(
                operation="generate",
                prompt="Flash probe-attribution boundary",
                model="gemini-3.1-flash-image",
            )
        )
        public_probe = flash_public["api_profile_reported_live_probe"]
        self.assertEqual(public_probe["model"], "gemini-3-pro-image")
        self.assertNotIn(
            "gemini-3.1-flash-image",
            json.dumps(public_probe, sort_keys=True),
        )

        for profile_name, profile in catalog["api_profiles"].items():
            with self.subTest(api_profile=profile_name):
                routed_models = [
                    model_id
                    for model_id, model_info in catalog["models"].items()
                    if model_info["api_surface"] == profile_name
                ]
                self.assertEqual(profile["supported_models"], routed_models)
                for group_claim_ids in profile["evidence_claim_ids"].values():
                    self.assertTrue(group_claim_ids)
                    self.assertTrue(set(group_claim_ids).issubset(claim_ids))
                reported_probe = profile["reported_live_probe"]
                self.assertEqual(reported_probe["reported_on"], "2026-08-28")
                self.assertNotIn("verified_on", reported_probe)
                self.assertIn(reported_probe["evidence_claim_id"], claim_ids)

        policies = catalog["provider_policies"]
        policy_evidence = policies["evidence_claim_ids"]
        self.assertEqual(
            set(policy_evidence),
            set(policies) - {"evidence_claim_ids"},
        )
        self.assertTrue(set(policy_evidence.values()).issubset(claim_ids))

    def test_current_output_prices_are_exact(self) -> None:
        self.assertEqual(
            estimate_image_cost("gemini-3.1-flash-lite-image", "1K"), 0.0336
        )
        self.assertEqual(estimate_image_cost("gemini-3.1-flash-image", "4K"), 0.151)
        self.assertEqual(estimate_image_cost("gemini-3-pro-image", "2K"), 0.134)
        self.assertEqual(
            estimate_image_cost("gemini-3-pro-image", "4K", batch=True), 0.12
        )


class PlanTests(unittest.TestCase):
    def assert_code(self, code: str, callback: Callable[[], Any]) -> None:
        with self.assertRaises(BananaError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_visual_brief_is_closed_canonical_and_fingerprint_bound(self) -> None:
        brief = supplied_visual_brief()
        reordered = {key: brief[key] for key in reversed(brief)}
        first = build_plan(
            operation="generate",
            prompt="Frozen prompt",
            visual_brief=brief,
        )
        second = build_plan(
            operation="generate",
            prompt="Frozen prompt",
            visual_brief=reordered,
        )
        self.assertEqual(first["brief_sha256"], second["brief_sha256"])
        self.assertEqual(first["request_fingerprint"], second["request_fingerprint"])
        self.assertEqual(first["brief_source"], "supplied")

        drifted = copy.deepcopy(brief)
        drifted["direction"]["signature"] = "A different light stripe."
        changed = build_plan(
            operation="generate",
            prompt="Frozen prompt",
            visual_brief=drifted,
        )
        self.assertNotEqual(first["brief_sha256"], changed["brief_sha256"])
        self.assertNotEqual(
            first["request_fingerprint"], changed["request_fingerprint"]
        )

        unknown = copy.deepcopy(brief)
        unknown["unexpected"] = True
        self.assert_code(
            "invalid_visual_brief",
            partial(
                build_plan,
                operation="generate",
                prompt="Frozen prompt",
                visual_brief=unknown,
            ),
        )
        nested_unknown = copy.deepcopy(brief)
        nested_unknown["direction"]["camera"] = "hidden field"
        self.assert_code(
            "invalid_visual_brief",
            partial(
                build_plan,
                operation="generate",
                prompt="Frozen prompt",
                visual_brief=nested_unknown,
            ),
        )

    def test_visual_brief_must_match_references_and_resolved_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "reference.png"
            image.write_bytes(PNG_1X1)
            reference = provider_reference(image)
            brief_reference = {
                "disclosure_alias": "test reference",
                "role": "object",
                "purpose": "preserve source geometry",
                "subject_id": None,
                "authority": reference_authority(),
            }
            matching = supplied_visual_brief(references=[brief_reference])
            plan = build_plan(
                operation="edit",
                prompt="Preserve geometry",
                reference_paths=[reference],
                visual_brief=matching,
            )
            self.assertEqual(plan["brief_source"], "supplied")

            wrong_alias = copy.deepcopy(matching)
            wrong_alias["references"][0]["disclosure_alias"] = "different alias"
            self.assert_code(
                "visual_brief_mismatch",
                partial(
                    build_plan,
                    operation="edit",
                    prompt="Preserve geometry",
                    reference_paths=[reference],
                    visual_brief=wrong_alias,
                ),
            )
            wrong_output = copy.deepcopy(matching)
            wrong_output["output"]["aspect_ratio"] = "16:9"
            self.assert_code(
                "visual_brief_mismatch",
                partial(
                    build_plan,
                    operation="edit",
                    prompt="Preserve geometry",
                    reference_paths=[reference],
                    visual_brief=wrong_output,
                ),
            )

    def test_direction_mode_supports_supplied_modes_and_runtime_prompt_only(
        self,
    ) -> None:
        creative = build_plan(
            operation="generate",
            prompt="Creative still life",
            visual_brief=supplied_visual_brief(),
        )
        self.assertEqual(creative["visual_brief"]["direction"]["mode"], "creative")

        for mode in ("preserve", "not_applicable"):
            with self.subTest(mode=mode):
                brief = supplied_visual_brief()
                brief["direction"] = {
                    "mode": mode,
                    "thesis": None,
                    "signature": None,
                    "avoid": None,
                }
                plan = build_plan(
                    operation="generate",
                    prompt="No invented direction",
                    visual_brief=brief,
                )
                self.assertEqual(plan["visual_brief"]["direction"], brief["direction"])

        invalid_preserve = supplied_visual_brief()
        invalid_preserve["direction"] = {
            "mode": "preserve",
            "thesis": "Invented direction",
            "signature": None,
            "avoid": None,
        }
        self.assert_code(
            "invalid_visual_brief",
            partial(
                build_plan,
                operation="generate",
                prompt="Preserve",
                visual_brief=invalid_preserve,
            ),
        )
        invalid_creative = supplied_visual_brief()
        invalid_creative["direction"]["signature"] = None
        self.assert_code(
            "invalid_visual_brief",
            partial(
                build_plan,
                operation="generate",
                prompt="Creative",
                visual_brief=invalid_creative,
            ),
        )

        minimal = build_plan(
            operation="generate",
            prompt="A surreal editorial still life with sculptural shadows",
        )
        self.assertEqual(
            minimal["visual_brief"]["direction"],
            {
                "mode": "prompt_only",
                "thesis": None,
                "signature": None,
                "avoid": None,
            },
        )
        self.assertIn(
            "aesthetic choices are coherent",
            minimal["visual_brief"]["review_tests"][0],
        )

        supplied_prompt_only = supplied_visual_brief()
        supplied_prompt_only["direction"] = {
            "mode": "prompt_only",
            "thesis": None,
            "signature": None,
            "avoid": None,
        }
        self.assert_code(
            "invalid_visual_brief",
            partial(
                build_plan,
                operation="generate",
                prompt="Externally supplied prompt-only brief",
                visual_brief=supplied_prompt_only,
            ),
        )

    def test_planner_minimal_and_approval_summary_are_disclosed_without_raw_brief(
        self,
    ) -> None:
        plan = build_plan(operation="generate", prompt="Simple still life")
        disclosed = public_plan(plan)
        self.assertEqual(disclosed["brief_source"], "planner_minimal")
        self.assertEqual(
            disclosed["approval_summary"]["brief_source"], "planner_minimal"
        )
        self.assertEqual(
            disclosed["approval_summary"]["brief_sha256"], plan["brief_sha256"]
        )
        self.assertEqual(disclosed["approval_summary"]["prompt"], "Simple still life")
        summary = disclosed["approval_summary"]
        self.assertEqual(summary["output_mime_type"], plan["output_mime_type"])
        self.assertEqual(summary["estimate_basis"], plan["estimate_basis"])
        self.assertEqual(
            summary["output_count_uncertain"], plan["output_count_uncertain"]
        )
        self.assertIn("provider_storage_retention_default_days", summary)
        self.assertIn("provider_storage_retention_options_days", summary)
        self.assertIn("provider_storage_setting_inspectable", summary)
        self.assertIn("provider_storage_warning", summary)
        self.assertEqual(summary["model"], "gemini-nano-banana-2.1")
        self.assertEqual(summary["model_status"], "ga")
        self.assertIsNone(summary["thinking_level"])
        self.assertEqual(summary["thinking_behavior"], plan["thinking_behavior"])
        self.assertEqual(summary["thinking_behavior"], "medium")
        self.assertEqual(
            summary["image_output_rate_usd"], plan["image_output_rate_usd"]
        )
        self.assertIsNone(summary["video_url"])
        self.assertIsNone(summary["video_url_paid_attempt_warning"])
        self.assertNotIn("visual_brief", disclosed)

        deprecated = public_plan(
            build_plan(
                operation="generate",
                prompt="Simple still life",
                model="gemini-3.1-flash-image",
                image_size="512",
                thinking_level="high",
            )
        )["approval_summary"]
        self.assertEqual(deprecated["model_status"], "deprecated")
        self.assertEqual(deprecated["thinking_level"], "high")
        self.assertEqual(deprecated["thinking_behavior"], "client_override_high")
        self.assertEqual(
            deprecated["image_output_rate_usd"],
            estimate_image_cost("gemini-3.1-flash-image", "512"),
        )

    def test_machine_detectable_high_risk_routes_require_structured_brief(self) -> None:
        cases: list[tuple[dict[str, Any], list[str]]] = [
            (
                {"operation": "portfolio", "prompt": "compare"},
                ["portfolio"],
            ),
            (
                {
                    "operation": "generate",
                    "prompt": "grounded",
                    "web_search": True,
                },
                ["search_grounding"],
            ),
            (
                {
                    "operation": "generate",
                    "prompt": "video poster",
                    "model": "gemini-3.1-flash-image",
                    "video_url": "https://youtu.be/dQw4w9WgXcQ",
                },
                ["video_input"],
            ),
            (
                {
                    "operation": "continue",
                    "prompt": "continue",
                    "previous_interaction_id": "previous-1",
                    "store": True,
                },
                ["stored_continuation"],
            ),
        ]
        for kwargs, expected_reasons in cases:
            with self.subTest(expected_reasons=expected_reasons):
                with self.assertRaises(BananaError) as caught:
                    build_plan(**kwargs)
                self.assertEqual(caught.exception.code, "structured_brief_required")
                self.assertFalse(caught.exception.details["provider_called"])
                self.assertEqual(
                    caught.exception.details["structured_brief_reasons"],
                    expected_reasons,
                )

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "reference.png"
            image.write_bytes(PNG_1X1)
            with self.assertRaises(BananaError) as caught:
                build_plan(
                    operation="edit",
                    prompt="edit",
                    reference_paths=[provider_reference(image)],
                )
            self.assertEqual(caught.exception.code, "structured_brief_required")
            self.assertEqual(
                caught.exception.details["structured_brief_reasons"],
                ["edit", "uploaded_references"],
            )

        simple = build_plan(operation="generate", prompt="simple")
        self.assertFalse(simple["structured_brief_required"])
        self.assertEqual(simple["structured_brief_reasons"], [])

    def test_reference_disclosure_alias_is_required_bound_and_authority_visible(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "private-basename.png"
            image.write_bytes(PNG_1X1)
            missing_name = {
                "path": image,
                "role": "object",
                "purpose": "geometry",
            }
            self.assert_code(
                "reference_metadata_required",
                partial(
                    build_plan,
                    operation="edit",
                    prompt="Preserve geometry",
                    reference_paths=[missing_name],
                ),
            )
            unknown_reference_field: dict[str, Any] = provider_reference(image)
            unknown_reference_field["authority"] = reference_authority()
            self.assert_code(
                "invalid_reference",
                partial(
                    build_plan,
                    operation="edit",
                    prompt="Preserve geometry",
                    reference_paths=[unknown_reference_field],
                ),
            )
            first_reference = provider_reference(image)
            first = build_plan(
                operation="edit",
                prompt="Preserve geometry",
                reference_paths=[first_reference],
                visual_brief=brief_for_references([first_reference]),
            )
            renamed_reference = provider_reference(image)
            renamed_reference["disclosure_alias"] = "front product photo"
            changed = build_plan(
                operation="edit",
                prompt="Preserve geometry",
                reference_paths=[renamed_reference],
                visual_brief=brief_for_references([renamed_reference]),
            )
            self.assertNotEqual(
                first["request_fingerprint"], changed["request_fingerprint"]
            )
            payload = build_interaction_payload("Preserve geometry", changed)
            alias_sentinel = "front product photo"
            annotation = payload["input"][1]["text"]
            generate_content = build_generate_content_payload(
                "Preserve geometry", changed
            )
            self.assertNotIn(alias_sentinel, str(payload))
            self.assertNotIn(alias_sentinel, str(generate_content))
            self.assertNotIn(image.name, annotation)
            self.assertEqual(
                public_plan(changed)["reference_inputs"][0]["disclosure_alias"],
                alias_sentinel,
            )
            self.assertEqual(
                public_plan(changed)["approval_summary"]["references"][0]["authority"],
                reference_authority(),
            )

    def test_reference_authority_is_brief_bound_and_unresolved_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "portrait.png"
            image.write_bytes(PNG_1X1)
            reference = provider_reference(image, role="character")
            authority = reference_authority(
                identity_or_likeness="affirmed",
                customer_or_private_asset="affirmed",
            )
            brief_reference = {**reference, "authority": authority}
            approved_brief = brief_for_references([brief_reference])
            approved = build_plan(
                operation="edit",
                prompt="Preserve this explicitly authorized portrait",
                reference_paths=[reference],
                visual_brief=approved_brief,
            )
            self.assertEqual(
                approved["visual_brief"]["references"][0]["authority"],
                authority,
            )
            self.assertEqual(
                public_plan(approved)["reference_inputs"][0]["authority"],
                authority,
            )

            unresolved = copy.deepcopy(approved_brief)
            unresolved["references"][0]["authority"]["identity_or_likeness"] = (
                "unresolved"
            )
            with self.assertRaises(BananaError) as caught:
                build_plan(
                    operation="edit",
                    prompt="Preserve this explicitly authorized portrait",
                    reference_paths=[reference],
                    visual_brief=unresolved,
                )
            self.assertEqual(caught.exception.code, "reference_authority_unresolved")
            self.assertFalse(caught.exception.details["provider_called"])

    def test_provider_reference_gif_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "reference.gif"
            image.write_bytes(b"GIF89a" + b"\x01\x00\x01\x00")
            self.assert_code(
                "unsupported_reference_type",
                partial(
                    build_plan,
                    operation="edit",
                    prompt="Preserve geometry",
                    reference_paths=[provider_reference(image)],
                ),
            )

    def test_plan_is_deterministic_and_prompt_sensitive(self) -> None:
        first = build_plan(
            operation="generate", prompt="A restrained ceramic still life"
        )
        second = build_plan(
            operation="generate", prompt="A restrained ceramic still life"
        )
        changed = build_plan(operation="generate", prompt="A bright ceramic still life")
        self.assertEqual(first["request_fingerprint"], second["request_fingerprint"])
        self.assertNotEqual(
            first["request_fingerprint"], changed["request_fingerprint"]
        )
        self.assertEqual(first["estimated_image_output_usd"], 0.0336)
        self.assertEqual(first["image_output_rate_usd"], 0.0336)
        self.assertEqual(first["estimate_basis"], "nominal_one_output")
        self.assertFalse(first["estimate_is_invoice_cap"])
        self.assertTrue(first["output_count_uncertain"])
        self.assertEqual(first["provider_attempt_count"], 1)
        self.assertEqual(
            first["api_endpoint"],
            "https://generativelanguage.googleapis.com/v1beta/interactions",
        )

    def test_catalog_date_and_estimate_are_approval_bound(self) -> None:
        with mock.patch("banana_core.estimate_image_cost", side_effect=[0.067, 0.999]):
            first = build_plan(
                operation="generate", prompt="A restrained ceramic still life"
            )
            repriced = build_plan(
                operation="generate", prompt="A restrained ceramic still life"
            )
        self.assertEqual(first["catalog_verified_on"], "2026-10-20")
        self.assertNotEqual(
            first["request_fingerprint"], repriced["request_fingerprint"]
        )

    def test_output_and_privacy_controls_are_approval_bound(self) -> None:
        base = build_plan(
            operation="generate", prompt="A restrained ceramic still life"
        )
        changed = [
            build_plan(
                operation="generate",
                prompt="A restrained ceramic still life",
                destination="/tmp/other",
            ),
            build_plan(
                operation="generate",
                prompt="A restrained ceramic still life",
                label="other",
            ),
            build_plan(
                operation="generate",
                prompt="A restrained ceramic still life",
                record_prompt=True,
            ),
        ]
        for plan in changed:
            self.assertNotEqual(
                base["request_fingerprint"], plan["request_fingerprint"]
            )

    def test_approval_visible_text_rejects_display_controls_and_surrogates(
        self,
    ) -> None:
        for label, value in (
            ("right-to-left override", "safe\u202eoverride"),
            ("left-to-right isolate", "safe\u2066override"),
            ("arabic letter mark", "safe\u061coverride"),
            ("unpaired surrogate", "safe\ud800override"),
        ):
            with self.subTest(label=label):
                self.assert_code(
                    "unsafe_approval_text",
                    partial(build_plan, operation="generate", prompt=value),
                )
        ordinary_rtl = build_plan(operation="generate", prompt="ملصق خزفي هادئ")
        self.assertEqual(ordinary_rtl["prompt"], "ملصق خزفي هادئ")

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "reference.png"
            image.write_bytes(PNG_1X1)
            self.assert_code(
                "invalid_reference_metadata",
                partial(
                    build_plan,
                    operation="edit",
                    prompt="preserve geometry",
                    reference_paths=[
                        {
                            "path": image,
                            "disclosure_alias": "safe reference",
                            "role": "object",
                            "purpose": "safe\u202eoverride",
                        }
                    ],
                ),
            )
        self.assert_code(
            "unsafe_approval_text",
            partial(
                build_plan,
                operation="generate",
                prompt="safe prompt",
                destination="/tmp/safe\u2066override",
            ),
        )

    def test_model_specific_size_ratio_and_grounding(self) -> None:
        self.assert_code(
            "unsupported_image_size",
            lambda: build_plan(
                operation="generate",
                prompt="draft",
                model="gemini-3.1-flash-lite-image",
                image_size="4K",
            ),
        )
        flash = build_plan(
            operation="generate",
            prompt="wide strip",
            model="gemini-3.1-flash-image",
            aspect_ratio="1:8",
            image_size="512",
            web_search=True,
            image_search=True,
            visual_brief=supplied_visual_brief(aspect_ratio="1:8", image_size="512"),
        )
        self.assertEqual(flash["aspect_ratio"], "1:8")
        self.assertEqual(flash["image_size"], "512")
        self.assertEqual(flash["search_provider_retention_days"], 30)
        self.assertTrue(flash["search_provider_retention_mandatory"])
        ungrounded = build_plan(operation="generate", prompt="offline still life")
        self.assertIsNone(ungrounded["search_provider_retention_days"])
        self.assertFalse(ungrounded["search_provider_retention_mandatory"])
        self.assert_code(
            "web_search_not_supported",
            lambda: build_plan(
                operation="generate",
                prompt="draft",
                model="gemini-3.1-flash-lite-image",
                web_search=True,
            ),
        )
        self.assert_code(
            "storage_not_supported",
            lambda: build_plan(
                operation="generate",
                prompt="draft",
                model="gemini-3.1-flash-lite-image",
                store=True,
            ),
        )

    def test_image_search_can_be_used_without_web_search(self) -> None:
        plan = build_plan(
            operation="generate",
            prompt="butterfly",
            image_search=True,
            visual_brief=supplied_visual_brief(),
        )
        self.assertFalse(plan["web_search"])
        self.assertTrue(plan["image_search"])
        self.assertEqual(plan["search_provider_retention_days"], 30)
        self.assertTrue(plan["search_provider_retention_mandatory"])
        payload = build_interaction_payload("butterfly", plan)
        self.assertEqual(
            payload["tools"],
            [{"type": "google_search", "search_types": ["image_search"]}],
        )

    def test_interactions_storage_retention_is_disclosed_and_approval_bound(
        self,
    ) -> None:
        plan = build_plan(operation="generate", prompt="stored draft", store=True)
        self.assertEqual(plan["provider_storage_retention_default_days"], 55)
        self.assertEqual(
            plan["provider_storage_retention_options_days"], [7, 14, 28, 55]
        )
        self.assertFalse(plan["provider_storage_setting_inspectable"])
        self.assertIn("cannot inspect", plan["provider_storage_warning"])
        unstored = build_plan(operation="generate", prompt="stored draft", store=False)
        self.assertIsNone(unstored["provider_storage_retention_default_days"])
        self.assertEqual(unstored["provider_storage_retention_options_days"], [])
        self.assertIsNone(unstored["provider_storage_setting_inspectable"])
        self.assertNotEqual(
            plan["request_fingerprint"],
            build_plan(operation="generate", prompt="stored draft", store=False)[
                "request_fingerprint"
            ],
        )
        policies = load_catalog()["provider_policies"]
        with mock.patch.dict(
            policies, {"interactions_paid_default_retention_days": 28}
        ):
            changed = build_plan(
                operation="generate", prompt="stored draft", store=True
            )
        self.assertEqual(changed["provider_storage_retention_default_days"], 28)
        self.assertNotEqual(plan["request_fingerprint"], changed["request_fingerprint"])

    def test_thinking_levels_are_model_specific(self) -> None:
        self.assertEqual(
            (
                lite := build_plan(
                    operation="generate",
                    prompt="reason",
                    model="gemini-3.1-flash-lite-image",
                )
            )["thinking_behavior"],
            "minimal",
        )
        self.assertTrue(lite["thinking_documentation_conflict"])
        self.assertIn("model page", lite["thinking_documentation_note"])
        self.assertEqual(
            build_plan(operation="generate", prompt="reason")["thinking_behavior"],
            "medium",
        )
        self.assertEqual(
            build_plan(operation="generate", prompt="reason", thinking_level="medium")[
                "thinking_behavior"
            ],
            "client_override_medium",
        )
        self.assert_code(
            "thinking_not_supported",
            partial(
                build_plan,
                operation="generate",
                prompt="reason",
                model="gemini-3.1-flash-image",
                thinking_level="medium",
            ),
        )
        for model in (
            "gemini-3.1-flash-lite-image",
            "gemini-3.1-flash-image",
            "gemini-nano-banana-2.1",
        ):
            plan = build_plan(
                operation="generate",
                prompt="reason",
                model=model,
                thinking_level="high",
            )
            self.assertEqual(plan["thinking_level"], "high")
            self.assertEqual(plan["thinking_behavior"], "client_override_high")
            self.assert_code(
                "invalid_thinking_level",
                partial(
                    build_plan,
                    operation="generate",
                    prompt="reason",
                    model=model,
                    thinking_level="low",
                ),
            )
        self.assert_code(
            "thinking_not_supported",
            lambda: build_plan(
                operation="generate",
                prompt="reason",
                model="gemini-3-pro-image",
                thinking_level="high",
            ),
        )

    def test_jpeg_constraint_and_documentation_conflict_are_disclosed(self) -> None:
        catalog = load_catalog()
        for model in catalog["models"]:
            with self.subTest(model=model):
                jpeg = build_plan(operation="generate", prompt="jpeg", model=model)
                self.assertEqual(jpeg["output_mime_type"], "image/jpeg")
                self.assertTrue(jpeg["output_mime_documentation_conflict"])
                self.assertIsInstance(jpeg["output_mime_documentation_note"], str)
                self.assert_code(
                    "unsupported_output_type",
                    partial(
                        build_plan,
                        operation="generate",
                        prompt="png",
                        model=model,
                        mime_type="image/png",
                    ),
                )

    def test_provider_response_format_is_approval_bound(self) -> None:
        first_wire = {"image": {"mimeType": "IMAGE_JPEG", "aspectRatio": "FIRST"}}
        second_wire = {"image": {"mimeType": "IMAGE_JPEG", "aspectRatio": "SECOND"}}
        with mock.patch(
            "banana_core.resolve_provider_response_format",
            side_effect=[first_wire, second_wire],
        ):
            first = build_plan(
                operation="generate",
                prompt="wire",
                model="gemini-3.1-flash-lite-image",
            )
            changed = build_plan(
                operation="generate",
                prompt="wire",
                model="gemini-3.1-flash-lite-image",
            )
        self.assertEqual(first["provider_response_format"], first_wire)
        self.assertEqual(changed["provider_response_format"], second_wire)
        self.assertNotEqual(
            first["request_fingerprint"], changed["request_fingerprint"]
        )

    def test_continuation_requires_id_and_storage(self) -> None:
        self.assert_code(
            "missing_interaction_id",
            lambda: build_plan(
                operation="continue", prompt="change the sky", store=True
            ),
        )
        self.assert_code(
            "continuation_requires_storage",
            lambda: build_plan(
                operation="continue",
                prompt="change the sky",
                previous_interaction_id="previous-1",
            ),
        )
        self.assert_code(
            "continuation_not_supported",
            lambda: build_plan(
                operation="continue",
                prompt="change the sky",
                model="gemini-3.1-flash-lite-image",
                previous_interaction_id="previous-1",
                store=True,
            ),
        )
        plan = build_plan(
            operation="continue",
            prompt="change the sky",
            previous_interaction_id="previous-1",
            store=True,
            visual_brief=supplied_visual_brief(),
        )
        self.assertTrue(plan["store"])

    def test_previous_id_cannot_change_operation_semantics(self) -> None:
        self.assert_code(
            "operation_mismatch",
            lambda: build_plan(
                operation="generate",
                prompt="change the sky",
                previous_interaction_id="previous-1",
                store=True,
            ),
        )

    def test_edit_and_reference_limits(self) -> None:
        self.assert_code(
            "missing_reference",
            lambda: build_plan(operation="edit", prompt="change only color"),
        )
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            image.write_bytes(PNG_1X1)
            reference = provider_reference(image)
            plan = build_plan(
                operation="edit",
                prompt="change only color",
                reference_paths=[reference],
                visual_brief=brief_for_references([reference]),
            )
            self.assertEqual(plan["reference_count"], 1)
            fake = Path(directory) / "renamed.png"
            fake.write_bytes(b"not an image")
            self.assert_code(
                "invalid_reference_signature",
                lambda: build_plan(
                    operation="edit",
                    prompt="change only color",
                    reference_paths=[provider_reference(fake)],
                ),
            )
            self.assert_code(
                "reference_metadata_required",
                lambda: build_plan(
                    operation="edit",
                    prompt="change only color",
                    reference_paths=[image],
                ),
            )
            self.assert_code(
                "reference_metadata_required",
                lambda: build_plan(
                    operation="edit",
                    prompt="change only color",
                    reference_paths=[{"path": image, "role": "object"}],
                ),
            )
            self.assert_code(
                "too_many_references",
                lambda: build_plan(
                    operation="edit",
                    prompt="change only color",
                    reference_paths=[provider_reference(image)] * 15,
                ),
            )
            with self.assertRaises(BananaError) as caught:
                build_plan(
                    operation="edit",
                    prompt="change only color",
                    reference_paths=[provider_reference(image)] * 15,
                )
            self.assertIn("Banana policy", caught.exception.message)
            self.assert_code(
                "too_many_character_references",
                lambda: build_plan(
                    operation="edit",
                    prompt="preserve every identity",
                    model="gemini-3.1-flash-image",
                    reference_paths=[
                        {
                            "path": image,
                            "disclosure_alias": f"person view {index}",
                            "role": "character",
                            "purpose": "preserve identity",
                            "subject_id": f"person-{index}",
                        }
                        for index in range(5)
                    ],
                ),
            )
            self.assert_code(
                "too_many_style_references",
                lambda: build_plan(
                    operation="edit",
                    prompt="use the visual language",
                    model="gemini-3-pro-image",
                    reference_paths=[
                        {
                            "path": image,
                            "disclosure_alias": "style reference",
                            "role": "style",
                            "purpose": "preserve visual language",
                        }
                        for _index in range(4)
                    ],
                ),
            )

    def test_reference_roles_are_fingerprinted_labeled_and_disclosed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "identity.png"
            image.write_bytes(PNG_1X1)
            character = [
                {
                    "path": image,
                    "disclosure_alias": "hero portrait",
                    "role": "character",
                    "purpose": "identity",
                    "subject_id": "hero",
                }
            ]
            object_reference = [
                {
                    "path": image,
                    "disclosure_alias": "hero object",
                    "role": "object",
                    "purpose": "geometry",
                }
            ]
            plan = build_plan(
                operation="edit",
                prompt="preserve the hero",
                reference_paths=character,
                visual_brief=brief_for_references(character),
            )
            changed = build_plan(
                operation="edit",
                prompt="preserve the hero",
                reference_paths=object_reference,
                visual_brief=brief_for_references(object_reference),
            )
            self.assertNotEqual(
                plan["request_fingerprint"], changed["request_fingerprint"]
            )
            disclosed = public_plan(plan)["reference_inputs"][0]
            self.assertEqual(disclosed["role"], "character")
            self.assertEqual(disclosed["purpose"], "identity")
            self.assertEqual(disclosed["subject_id"], "hero")
            payload = build_interaction_payload("preserve the hero", plan)
            self.assertIn("Banana reference annotation", payload["input"][1]["text"])
            self.assertIn("role: character", payload["input"][1]["text"])
            self.assertIn("subject_id: hero", payload["input"][1]["text"])
            self.assertNotIn("category:", payload["input"][1]["text"])

    def test_video_routes_to_2_1_and_flash_with_syntax_only_validation(
        self,
    ) -> None:
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        for video_model in ("gemini-nano-banana-2.1", "gemini-3.1-flash-image"):
            with (
                self.subTest(video_model=video_model),
                mock.patch("banana_core.urllib.request.urlopen") as urlopen,
            ):
                self.assert_code(
                    "structured_brief_required",
                    partial(
                        build_plan,
                        operation="generate",
                        prompt="poster",
                        model=video_model,
                        video_url=url,
                    ),
                )
                plan = build_plan(
                    operation="generate",
                    prompt="poster",
                    model=video_model,
                    video_url=url,
                    visual_brief=supplied_visual_brief(),
                )
                urlopen.assert_not_called()
                self.assertEqual(plan["model"], video_model)
                self.assertEqual(plan["api_surface"], "interactions")
                self.assertEqual(plan["video_url"], url)
                self.assertTrue(plan["video_input"])
                self.assertEqual(plan["structured_brief_reasons"], ["video_input"])
                payload = build_interaction_payload("poster", plan)
                self.assertEqual(payload["model"], video_model)
                self.assertEqual(
                    payload["input"][0],
                    {"type": "video", "uri": url, "mime_type": "video/mp4"},
                )
                self.assertEqual(
                    payload["input"][1], {"type": "text", "text": "poster"}
                )
                summary = public_plan(plan)["approval_summary"]
                self.assertEqual(summary["video_url"], url)
                self.assertEqual(
                    summary["video_url_paid_attempt_warning"],
                    plan["video_url_paid_attempt_warning"],
                )
        with mock.patch("banana_core.urllib.request.urlopen") as urlopen:
            plan = build_plan(
                operation="generate",
                prompt="poster",
                model="gemini-3.1-flash-image",
                video_url=url,
                visual_brief=supplied_visual_brief(),
            )
        urlopen.assert_not_called()
        self.assertEqual(plan["video_url"], url)
        self.assertTrue(plan["video_url_syntax_validated"])
        self.assertEqual(
            plan["video_url_status_disclosure"],
            {
                "existence": "user_asserted",
                "public_status": "user_asserted",
                "google_accessibility": "user_asserted",
                "preflighted": False,
            },
        )
        self.assertIn("does not preflight", plan["video_url_paid_attempt_warning"])
        self.assertIn(
            "one paid provider attempt", plan["video_url_paid_attempt_warning"]
        )
        disclosed = public_plan(plan)
        self.assertTrue(disclosed["video_url_syntax_validated"])
        self.assertEqual(
            disclosed["video_url_status_disclosure"],
            plan["video_url_status_disclosure"],
        )
        self.assertEqual(
            disclosed["video_url_paid_attempt_warning"],
            plan["video_url_paid_attempt_warning"],
        )
        short_url = "https://youtu.be/dQw4w9WgXcQ"
        self.assertEqual(
            build_plan(
                operation="generate",
                prompt="poster",
                model="gemini-3.1-flash-image",
                video_url=short_url,
                visual_brief=supplied_visual_brief(),
            )["video_url"],
            short_url,
        )
        for unsupported_model in (
            "gemini-3.1-flash-lite-image",
            "gemini-3-pro-image",
        ):
            with self.subTest(unsupported_model=unsupported_model):
                self.assert_code(
                    "video_not_supported",
                    partial(
                        build_plan,
                        operation="generate",
                        prompt="poster",
                        model=unsupported_model,
                        video_url=url,
                        visual_brief=supplied_visual_brief(),
                    ),
                )
        with self.assertRaises(BananaError) as unsupported:
            build_plan(
                operation="generate",
                prompt="poster",
                model="gemini-3.1-flash-image",
                video_url="https://example.com/video.mp4",
            )
        self.assertEqual(unsupported.exception.code, "unsupported_video_url")
        self.assertIn("syntactically valid", unsupported.exception.message)
        self.assertIn("does not verify", unsupported.exception.message)
        self.assertNotIn("Only public", unsupported.exception.message)
        self.assert_code(
            "unsafe_approval_text",
            lambda: build_plan(
                operation="generate",
                prompt="poster",
                model="gemini-3.1-flash-image",
                video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ&note=\u202ehidden",
            ),
        )
        for invalid_url in (
            "https://www.youtube.com/watch?v=example",
            "https://www.youtube.com/watch?v=",
            "https://www.youtube.com/watch?feature=share",
            "https://youtu.be/not-an-id",
            "https://youtu.be/dQw4w9WgXcQ/extra",
        ):
            with self.subTest(invalid_url=invalid_url):
                self.assert_code(
                    "unsupported_video_url",
                    partial(
                        build_plan,
                        operation="generate",
                        prompt="poster",
                        model="gemini-3.1-flash-image",
                        video_url=invalid_url,
                    ),
                )

    def test_public_plan_discloses_data_without_local_reference_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "private-reference.png"
            image.write_bytes(PNG_1X1)
            reference = provider_reference(image)
            plan = build_plan(
                operation="edit",
                prompt="  change only color  ",
                reference_paths=[reference],
                visual_brief=brief_for_references([reference]),
            )
            disclosed = public_plan(plan)
            self.assertEqual(disclosed["prompt"], "change only color")
            self.assertEqual(disclosed["prompt_sha256"], plan["prompt_sha256"])
            self.assertNotIn("references", disclosed)
            self.assertEqual(disclosed["reference_inputs"][0]["bytes"], len(PNG_1X1))
            self.assertNotIn(str(image), str(disclosed))

    def test_interactions_payload_contains_explicit_state_and_tools(self) -> None:
        plan = build_plan(
            operation="generate",
            prompt="grounded butterfly",
            aspect_ratio="16:9",
            image_size="2K",
            thinking_level="high",
            web_search=True,
            image_search=True,
            visual_brief=supplied_visual_brief(aspect_ratio="16:9", image_size="2K"),
        )
        payload = build_interaction_payload("grounded butterfly", plan)
        self.assertIs(payload["store"], False)
        self.assertEqual(payload["response_format"]["image_size"], "2K")
        self.assertEqual(payload["generation_config"], {"thinking_level": "high"})
        self.assertEqual(
            payload["tools"][0]["search_types"], ["web_search", "image_search"]
        )

        web_only = build_plan(
            operation="generate",
            prompt="grounded butterfly",
            web_search=True,
            visual_brief=supplied_visual_brief(),
        )
        self.assertEqual(
            build_interaction_payload("grounded butterfly", web_only)["tools"],
            [{"type": "google_search", "search_types": ["web_search"]}],
        )

    def test_generate_content_payload_uses_lite_route(self) -> None:
        plan = build_plan(
            operation="generate",
            prompt="poster",
            model="gemini-3.1-flash-lite-image",
            aspect_ratio="16:9",
            thinking_level="high",
            mime_type="image/jpeg",
        )
        payload = build_generate_content_payload("poster", plan)
        self.assertEqual(payload["contents"][0]["parts"][0], {"text": "poster"})
        config = payload["generationConfig"]
        self.assertEqual(config["thinkingConfig"], {"thinkingLevel": "HIGH"})
        self.assertEqual(
            config["responseFormat"]["image"]["aspectRatio"],
            "ASPECT_RATIO_SIXTEEN_BY_NINE",
        )
        self.assertEqual(
            config["responseFormat"]["image"]["imageSize"], "IMAGE_SIZE_ONE_K"
        )
        self.assertEqual(config["responseFormat"]["image"]["mimeType"], "IMAGE_JPEG")
        self.assertEqual(config["responseFormat"], plan["provider_response_format"])
        self.assertEqual(
            plan["api_profile_reported_live_probe"]["response"],
            {"mime_type": "image/jpeg", "width": 1024, "height": 1024},
        )

    def test_generate_content_wire_map_covers_every_catalog_ratio(self) -> None:
        catalog = load_catalog()
        wire_values = catalog["api_profiles"]["generate_content"]["wire_values"]
        for model, model_info in catalog["models"].items():
            if model_info["api_surface"] != "generate_content":
                continue
            for ratio in model_info["aspect_ratios"]:
                with self.subTest(model=model, ratio=ratio):
                    plan = build_plan(
                        operation="generate",
                        prompt="wire coverage",
                        model=model,
                        aspect_ratio=ratio,
                    )
                    image_format = plan["provider_response_format"]["image"]
                    self.assertEqual(
                        image_format["aspectRatio"], wire_values["aspect_ratio"][ratio]
                    )
                    self.assertEqual(image_format["mimeType"], "IMAGE_JPEG")

    def test_retired_2_5_and_default_512_are_rejected_before_network(self) -> None:
        with self.assertRaises(BananaError) as retired:
            build_plan(
                operation="generate",
                prompt="compatibility image",
                model="gemini-2.5-flash-image",
            )
        self.assertEqual(retired.exception.code, "retired_model")
        self.assertIn("gemini-2.5-flash-image", retired.exception.message)
        self.assertIn("was retired", retired.exception.message)
        self.assertIn(
            "current default, gemini-nano-banana-2.1", retired.exception.message
        )
        with self.assertRaises(BananaError) as unknown:
            build_plan(
                operation="generate",
                prompt="compatibility image",
                model="gemini-unknown-image",
            )
        self.assertEqual(unknown.exception.code, "unsupported_model")
        with self.assertRaises(BananaError) as size:
            build_plan(operation="generate", prompt="draft", image_size="512")
        self.assertEqual(size.exception.code, "unsupported_image_size")
        self.assertIn("Use: 1K, 2K, 4K", size.exception.message)
        self.assertIn(
            "Catalog models that support 512: gemini-3.1-flash-image",
            size.exception.message,
        )
        with self.assertRaises(BananaError) as alias_size:
            build_plan(operation="generate", prompt="draft", image_size="512px")
        self.assertIn(
            "Catalog models that support 512: gemini-3.1-flash-image",
            alias_size.exception.message,
        )
        with self.assertRaises(BananaError) as unknown_size:
            build_plan(operation="generate", prompt="draft", image_size="8K")
        self.assertEqual(unknown_size.exception.code, "unsupported_image_size")
        self.assertNotIn("Catalog models that support", unknown_size.exception.message)
        self.assertEqual(
            models_supporting_image_size("2k"),
            ["gemini-nano-banana-2.1", "gemini-3-pro-image", "gemini-3.1-flash-image"],
        )
        self.assertEqual(
            build_plan(
                operation="generate",
                prompt="draft",
                model="gemini-3.1-flash-image",
                image_size="512",
            )["image_size"],
            "512",
        )

    def test_single_interaction_does_not_fake_a_sample_count(self) -> None:
        self.assert_code(
            "unsupported_image_count",
            lambda: build_plan(
                operation="generate", prompt="three cats", image_count=3
            ),
        )


if __name__ == "__main__":
    unittest.main()
