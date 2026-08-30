from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any, NoReturn, cast
from unittest.mock import patch

from tests._support import (
    JPEG_1X1,
    PNG_1X1,
    PNG_1X1_B64,
    FakeResponse,
    completed_response,
    generate_content_response,
    temporary_banana_home,
)

import banana_core
import cost_tracker
from approval_store import issue_approval
from banana_core import (
    BananaError,
    api_key_from_env,
    build_interaction_payload,
    build_plan,
    call_generate_content,
    call_interactions,
    decode_image,
    execute_image,
    execute_validated_plan,
    extract_generate_content,
    extract_interaction,
    save_interaction,
)

AUTH_VALUE = "x"


def provider_reference(path: Path) -> dict[str, str | Path]:
    return {
        "path": path,
        "disclosure_alias": "source image",
        "role": "object",
        "purpose": "preserve source geometry",
    }


def reference_authority() -> dict[str, str]:
    return {
        "rights_or_license": "affirmed",
        "identity_or_likeness": "not_applicable",
        "customer_or_private_asset": "not_applicable",
        "endorsement_or_representation": "not_applicable",
        "provider_transmission": "affirmed",
        "intended_use": "Exercise the local test workflow.",
    }


def structured_brief(
    *,
    references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "banana.visual-brief.v1",
        "goal": "A controlled test image.",
        "facts": [],
        "locks": [],
        "freedoms": [],
        "direction": {
            "mode": "creative",
            "thesis": "Controlled test.",
            "signature": "One visible focal point.",
            "avoid": "Unexpected changes.",
        },
        "composition": [],
        "rendering": [],
        "typography": {"exact_copy": [], "instructions": []},
        "references": references or [],
        "output": {
            "aspect_ratio": "1:1",
            "image_size": "1K",
            "mime_type": "image/jpeg",
            "delivery_notes": [],
        },
        "review_tests": ["The image follows the approved prompt."],
    }


def brief_for_reference(reference: dict[str, Any]) -> dict[str, Any]:
    return structured_brief(
        references=[
            {
                "disclosure_alias": reference["disclosure_alias"],
                "role": reference["role"],
                "purpose": reference["purpose"],
                "subject_id": reference.get("subject_id"),
                "authority": reference_authority(),
            }
        ]
    )


def provider_error(code: int, payload: dict[str, Any]) -> urllib.error.HTTPError:
    body = json.dumps(payload).encode("utf-8")
    return urllib.error.HTTPError(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        code,
        "provider error",
        hdrs=Message(),
        fp=io.BytesIO(body),
    )


class RequestTests(unittest.TestCase):
    def test_provider_endpoint_requires_the_exact_closed_https_origin(self) -> None:
        calls = 0

        def should_not_open(*_args: Any, **_kwargs: Any) -> FakeResponse:
            nonlocal calls
            calls += 1
            return FakeResponse(b"{}")

        for endpoint in (
            "http://generativelanguage.googleapis.com/v1beta/interactions",
            "https://generativelanguage.googleapis.com.example.invalid/v1beta/interactions",
            "https://user@generativelanguage.googleapis.com/v1beta/interactions",
            "https://generativelanguage.googleapis.com:443/v1beta/interactions",
            "https://generativelanguage.googleapis.com/v1beta/interactions?redirect=1",
            "https://generativelanguage.googleapis.com/v1beta/interactions#fragment",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(BananaError) as caught:
                    call_interactions(
                        {},
                        endpoint=endpoint,
                        api_key=AUTH_VALUE,
                        opener=should_not_open,
                    )
                self.assertEqual(caught.exception.code, "api_surface_mismatch")
        self.assertEqual(calls, 0)

    def test_authenticated_provider_redirects_are_always_rejected(self) -> None:
        synthetic_key = "synthetic-key-never-forward"  # pragma: allowlist secret
        request = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            data=b"{}",
            headers={"x-goog-api-key": synthetic_key},
            method="POST",
        )
        handler = banana_core._RejectProviderRedirects()
        for target in (
            "https://generativelanguage.googleapis.com/v1beta/redirected",
            "https://example.invalid/credential-capture",
        ):
            with self.subTest(target=target):
                redirected = handler.redirect_request(
                    request,
                    None,
                    302,
                    "Found",
                    Message(),
                    target,
                )
                self.assertIsNone(redirected)

    def test_execution_uses_redirect_rejecting_default_opener(self) -> None:
        calls = 0

        def redirecting_open(
            request: urllib.request.Request, *, timeout: int
        ) -> FakeResponse:
            nonlocal calls
            calls += 1
            self.assertEqual(timeout, 180)
            self.assertEqual(request.get_header("X-goog-api-key"), AUTH_VALUE)
            handler = next(
                item
                for item in cast(Any, banana_core._PROVIDER_OPENER).handlers
                if isinstance(item, banana_core._RejectProviderRedirects)
            )
            self.assertIsNone(
                handler.redirect_request(
                    request,
                    None,
                    302,
                    "Found",
                    Message(),
                    "https://example.invalid/credential-capture",
                )
            )
            raise provider_error(
                302,
                {"error": {"status": "UNKNOWN", "message": "redirect rejected"}},
            )

        with tempfile.TemporaryDirectory() as directory:
            plan = build_plan(
                operation="generate",
                prompt="redirect defense",
                destination=directory,
            )
            with patch.object(
                banana_core._PROVIDER_OPENER,
                "open",
                side_effect=redirecting_open,
            ):
                with self.assertRaises(BananaError) as caught:
                    execute_validated_plan(
                        plan=plan,
                        prompt="redirect defense",
                        api_key=AUTH_VALUE,
                    )

        self.assertEqual(calls, 1)
        self.assertEqual(caught.exception.code, "provider_http_error")
        self.assertEqual(caught.exception.http_status, 302)

    def test_standalone_key_selection_accepts_only_gemini_api_key(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GOOGLE_API_KEY": "synthetic",  # pragma: allowlist secret
                "GOOGLE_AI_API_KEY": "synthetic",  # pragma: allowlist secret
            },
            clear=True,
        ):
            with self.assertRaises(BananaError) as caught:
                api_key_from_env()
            self.assertEqual(caught.exception.code, "missing_api_key")
            self.assertFalse(caught.exception.details["provider_called"])

        with patch.dict(os.environ, {"GEMINI_API_KEY": "  exact-key  "}, clear=True):
            self.assertEqual(api_key_from_env(), "exact-key")

    def test_reference_reopen_is_bounded_and_revalidated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            image.write_bytes(PNG_1X1)
            reference = provider_reference(image)
            plan = build_plan(
                operation="edit",
                prompt="change only the color",
                reference_paths=[reference],
                visual_brief=brief_for_reference(reference),
            )
            image.write_bytes(PNG_1X1 + b"changed")
            with self.assertRaises(BananaError) as caught:
                build_interaction_payload("change only the color", plan)
            self.assertEqual(caught.exception.code, "reference_changed")

    def test_key_is_in_header_and_never_in_url(self) -> None:
        captured: dict[str, Any] = {}

        def opener(request: Any, *, timeout: int) -> FakeResponse:
            captured["url"] = request.full_url
            captured["headers"] = {
                key.lower(): value for key, value in request.header_items()
            }
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse(completed_response())

        payload = {"model": "gemini-3.1-flash-image", "input": "test", "store": False}
        response = call_interactions(payload, api_key=AUTH_VALUE, opener=opener)
        self.assertEqual(response["status"], "completed")
        self.assertEqual(captured["headers"]["x-goog-api-key"], AUTH_VALUE)
        self.assertNotIn(AUTH_VALUE, captured["url"])
        self.assertNotIn("?key=", captured["url"])
        self.assertEqual(captured["body"], payload)
        self.assertEqual(captured["timeout"], 180)

    def test_transient_errors_retry_with_bounded_backoff(self) -> None:
        attempts: list[int] = []
        sleeps: list[float] = []

        def opener(_request: Any, *, timeout: int) -> FakeResponse:
            attempts.append(timeout)
            if len(attempts) < 3:
                raise provider_error(
                    429,
                    {"error": {"message": "try later", "status": "RESOURCE_EXHAUSTED"}},
                )
            return FakeResponse(completed_response())

        response = call_interactions(
            {"model": "gemini-3.1-flash-image", "input": "test"},
            api_key=AUTH_VALUE,
            opener=opener,
            sleeper=sleeps.append,
            max_attempts=3,
        )
        self.assertEqual(response["status"], "completed")
        self.assertEqual(attempts, [180, 180, 180])
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_paid_default_makes_one_provider_attempt(self) -> None:
        attempts: list[int] = []

        def opener(_request: Any, *, timeout: int) -> NoReturn:
            attempts.append(timeout)
            raise provider_error(503, {"error": {"message": "temporarily unavailable"}})

        with self.assertRaises(BananaError) as caught:
            call_interactions(
                {"model": "gemini-3.1-flash-image", "input": "test"},
                api_key=AUTH_VALUE,
                opener=opener,
            )
        self.assertEqual(caught.exception.code, "provider_unavailable")
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(attempts, [180])

    def test_generate_content_uses_model_scoped_v1_url(self) -> None:
        captured: dict[str, Any] = {}

        def opener(request: Any, *, timeout: int) -> FakeResponse:
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["headers"] = {
                key.lower(): value for key, value in request.header_items()
            }
            return FakeResponse(generate_content_response())

        payload = {"contents": [{"parts": [{"text": "test"}]}]}
        response = call_generate_content(
            payload,
            model="gemini-3.1-flash-lite-image",
            api_key=AUTH_VALUE,
            opener=opener,
        )
        self.assertEqual(response["responseId"], "response-test")
        self.assertEqual(
            captured["url"],
            "https://generativelanguage.googleapis.com/v1/models/gemini-3.1-flash-lite-image:generateContent",
        )
        self.assertEqual(captured["body"], payload)
        self.assertEqual(captured["headers"]["x-goog-api-key"], AUTH_VALUE)

    def test_final_rate_limit_is_typed(self) -> None:
        def opener(_request: Any, *, timeout: int) -> NoReturn:
            raise provider_error(429, {"error": {"message": "quota exhausted"}})

        with self.assertRaises(BananaError) as caught:
            call_interactions(
                {"model": "gemini-3.1-flash-image", "input": "test"},
                api_key=AUTH_VALUE,
                opener=opener,
                sleeper=lambda _seconds: None,
                max_attempts=1,
            )
        self.assertEqual(caught.exception.code, "rate_limited")
        self.assertTrue(caught.exception.retryable)

    def test_failed_precondition_is_classified_from_provider_status(self) -> None:
        def opener(_request: Any, *, timeout: int) -> NoReturn:
            raise provider_error(
                400,
                {
                    "error": {
                        "message": "Billing must be enabled",
                        "status": "FAILED_PRECONDITION",
                    }
                },
            )

        with self.assertRaises(BananaError) as caught:
            call_interactions(
                {"model": "gemini-3.1-flash-image", "input": "test"},
                api_key=AUTH_VALUE,
                opener=opener,
                max_attempts=1,
            )
        self.assertEqual(caught.exception.code, "billing_required")

    def test_billing_and_error_text_use_only_exact_allowlisted_status(self) -> None:
        sentinel = "PRIVATE_PROMPT_SENTINEL"

        def opener(_request: Any, *, timeout: int) -> NoReturn:
            raise provider_error(
                400,
                {
                    "error": {
                        "message": "FAILED_PRECONDITION " + sentinel,
                        "status": sentinel,
                        "code": sentinel,
                    }
                },
            )

        with self.assertRaises(BananaError) as caught:
            call_interactions(
                {"model": "gemini-3.1-flash-image", "input": "test"},
                api_key=AUTH_VALUE,
                opener=opener,
            )
        self.assertEqual(caught.exception.code, "provider_http_error")
        serialized = json.dumps(caught.exception.as_dict(), sort_keys=True)
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn("FAILED_PRECONDITION", serialized)

    def test_provider_error_payload_text_is_never_propagated(self) -> None:
        sentinel = "private prompt sentinel\u202e"
        cases: tuple[tuple[int, dict[str, Any]], ...] = (
            (429, {"error": {"message": sentinel, "status": "RESOURCE_EXHAUSTED"}}),
            (503, {"error": {"message": sentinel}}),
            (401, {"error": {"message": sentinel}}),
            (400, {"error": {"message": sentinel, "status": "FAILED_PRECONDITION"}}),
            (418, {"error": {"message": sentinel, "code": "TEAPOT"}}),
        )
        for code, payload in cases:
            with self.subTest(code=code):

                def opener(_request: Any, *, timeout: int) -> NoReturn:
                    raise provider_error(code, payload)

                with self.assertRaises(BananaError) as caught:
                    call_interactions(
                        {"model": "gemini-3.1-flash-image", "input": "test"},
                        api_key=AUTH_VALUE,
                        opener=opener,
                    )
                self.assertNotIn("private prompt", caught.exception.message)
                self.assertNotIn("\u202e", caught.exception.message)

        non_object = urllib.error.HTTPError(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            418,
            "provider error",
            hdrs=Message(),
            fp=io.BytesIO(json.dumps([sentinel]).encode("utf-8")),
        )

        def non_object_opener(_request: Any, *, timeout: int) -> NoReturn:
            raise non_object

        with self.assertRaises(BananaError) as caught:
            call_interactions(
                {"model": "gemini-3.1-flash-image", "input": "test"},
                api_key=AUTH_VALUE,
                opener=non_object_opener,
            )
        self.assertEqual(caught.exception.code, "provider_http_error")
        self.assertNotIn("private prompt", caught.exception.message)

    def test_invalid_retry_and_timeout_values_fail_before_network(self) -> None:
        with self.assertRaises(BananaError) as caught:
            call_interactions({}, api_key=AUTH_VALUE, max_attempts=0)
        self.assertEqual(caught.exception.code, "invalid_retry_budget")
        with self.assertRaises(BananaError) as caught:
            call_interactions({}, api_key=AUTH_VALUE, timeout=0)
        self.assertEqual(caught.exception.code, "invalid_timeout")

    def test_malformed_provider_json_fails_closed(self) -> None:
        with self.assertRaises(BananaError) as caught:
            call_interactions(
                {"model": "gemini-3.1-flash-image", "input": "test"},
                api_key=AUTH_VALUE,
                opener=lambda _request, **_kwargs: FakeResponse(b"not-json"),
            )
        self.assertEqual(caught.exception.code, "malformed_response")

        deeply_nested = b"[" * 100_000 + b"0" + b"]" * 100_000
        with self.assertRaises(BananaError) as caught:
            call_interactions(
                {"model": "gemini-3.1-flash-image", "input": "test"},
                api_key=AUTH_VALUE,
                opener=lambda _request, **_kwargs: FakeResponse(deeply_nested),
            )
        self.assertEqual(caught.exception.code, "malformed_response")

    def test_provider_response_size_is_bounded(self) -> None:
        with patch("banana_core.MAX_PROVIDER_RESPONSE_BYTES", 64):
            with self.assertRaises(BananaError) as caught:
                call_interactions(
                    {"model": "gemini-3.1-flash-image", "input": "test"},
                    api_key=AUTH_VALUE,
                    opener=lambda _request, **_kwargs: FakeResponse(b"x" * 65),
                )
        self.assertEqual(caught.exception.code, "provider_response_too_large")

    def test_provider_error_response_size_is_bounded(self) -> None:
        error = urllib.error.HTTPError(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            500,
            "provider error",
            hdrs=Message(),
            fp=io.BytesIO(b"x" * 65),
        )

        def opener(_request: Any, *, timeout: int) -> NoReturn:
            raise error

        with patch("banana_core.MAX_PROVIDER_ERROR_BYTES", 64):
            with self.assertRaises(BananaError) as caught:
                call_interactions(
                    {"model": "gemini-3.1-flash-image", "input": "test"},
                    api_key=AUTH_VALUE,
                    opener=opener,
                )
        self.assertEqual(caught.exception.code, "provider_response_too_large")


class ResponseTests(unittest.TestCase):
    def test_extracts_every_image_text_citation_and_search_suggestion(self) -> None:
        response = completed_response(count=2)
        response["steps"][0].pop("search_suggestions")
        response["steps"][0]["result"] = [
            {"search_suggestions": "<div>Google Search suggestion</div>"}
        ]
        extracted = extract_interaction(response)
        self.assertEqual(len(extracted["images"]), 2)
        self.assertEqual(extracted["text"], "Generated response text")
        self.assertEqual(extracted["citations"][0]["type"], "url_citation")
        self.assertEqual(
            extracted["search_suggestions"], ["<div>Google Search suggestion</div>"]
        )

    def test_extracts_generate_content_and_skips_thought_images(self) -> None:
        response = generate_content_response(count=2)
        response["usageMetadata"].update(
            {
                "prompt": "private prompt sentinel",
                "nested": {"prompt": "private prompt sentinel"},
                "cachedContentTokenCount": 7,
                "invalidCount": True,
            }
        )
        response["candidates"][0]["content"]["parts"].insert(
            0,
            {
                "thought": True,
                "inlineData": {"mimeType": "image/png", "data": PNG_1X1_B64},
            },
        )
        extracted = extract_generate_content(
            response, model="gemini-3.1-flash-lite-image"
        )
        self.assertEqual(len(extracted["images"]), 2)
        self.assertEqual(extracted["interaction_id"], "response-test")
        self.assertEqual(
            extracted["usage"],
            {"totalTokenCount": 42, "cachedContentTokenCount": 7},
        )

    def test_generate_content_surfaces_prompt_and_candidate_safety_reasons(
        self,
    ) -> None:
        with self.assertRaises(BananaError) as caught:
            extract_generate_content(
                {
                    "promptFeedback": {
                        "blockReason": "IMAGE_SAFETY",
                        "safetyRatings": [
                            {
                                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                                "probability": "HIGH",
                                "blocked": True,
                            }
                        ],
                    }
                },
                model="gemini-3.1-flash-lite-image",
            )
        self.assertEqual(caught.exception.code, "prompt_blocked")
        self.assertEqual(
            caught.exception.as_dict()["details"]["block_reason"], "IMAGE_SAFETY"
        )
        self.assertEqual(
            set(caught.exception.as_dict()["details"]),
            {"block_reason", "safety_ratings"},
        )

        with self.assertRaises(BananaError) as caught:
            extract_generate_content(
                {
                    "candidates": [
                        {
                            "finishReason": "IMAGE_PROHIBITED_CONTENT",
                            "safetyRatings": [
                                {
                                    "category": "HARM_CATEGORY_HARASSMENT",
                                    "blocked": True,
                                }
                            ],
                            "content": {"parts": []},
                        }
                    ]
                },
                model="gemini-2.5-flash-image",
            )
        self.assertEqual(caught.exception.code, "generation_blocked")
        self.assertEqual(
            caught.exception.as_dict()["details"]["finish_reasons"],
            ["IMAGE_PROHIBITED_CONTENT"],
        )

        for finish_reason in ("RECITATION", "SPII", "ESCALATION"):
            with (
                self.subTest(finish_reason=finish_reason),
                self.assertRaises(BananaError) as caught,
            ):
                extract_generate_content(
                    {
                        "candidates": [
                            {
                                "finishReason": finish_reason,
                                "content": {"parts": []},
                            }
                        ]
                    },
                    model="gemini-3.1-flash-lite-image",
                )
            self.assertEqual(caught.exception.code, "generation_blocked")
            self.assertEqual(
                caught.exception.as_dict()["details"]["finish_reasons"], [finish_reason]
            )

    def test_provider_reason_fields_are_closed_allowlists(self) -> None:
        sentinel = "PRIVATE_PROMPT_SENTINEL"
        cases: tuple[dict[str, Any], ...] = (
            {
                "status": sentinel,
                "error": {"status": sentinel, "code": sentinel},
            },
            {"status": sentinel},
        )
        for response in cases:
            with (
                self.subTest(response=response),
                self.assertRaises(BananaError) as caught,
            ):
                extract_interaction(response)
            serialized = json.dumps(caught.exception.as_dict(), sort_keys=True)
            self.assertNotIn(sentinel, serialized)
            self.assertIn("UNKNOWN", serialized)

        generate_content_cases: tuple[dict[str, Any], ...] = (
            {
                "promptFeedback": {
                    "blockReason": sentinel,
                    "safetyRatings": [
                        {
                            "category": sentinel,
                            "probability": sentinel,
                            "severity": sentinel,
                            "blocked": True,
                        }
                    ],
                }
            },
            {
                "candidates": [
                    {
                        "finishReason": sentinel,
                        "safetyRatings": [
                            {
                                "category": sentinel,
                                "probability": sentinel,
                                "severity": sentinel,
                            }
                        ],
                        "content": {"parts": []},
                    }
                ]
            },
        )
        for response in generate_content_cases:
            with (
                self.subTest(response=response),
                self.assertRaises(BananaError) as caught,
            ):
                extract_generate_content(response, model="gemini-3.1-flash-lite-image")
            serialized = json.dumps(caught.exception.as_dict(), sort_keys=True)
            self.assertNotIn(sentinel, serialized)
            self.assertIn("UNKNOWN", serialized)

    def test_noncompleted_or_imageless_response_fails_closed(self) -> None:
        with self.assertRaises(BananaError) as caught:
            extract_interaction({"status": "failed", "error": {"message": "safety"}})
        self.assertEqual(caught.exception.code, "interaction_not_completed")
        with self.assertRaises(BananaError) as caught:
            extract_interaction({"status": "completed", "steps": []})
        self.assertEqual(caught.exception.code, "no_image")

    def test_image_data_and_signature_are_validated(self) -> None:
        raw, mime = decode_image({"data": PNG_1X1_B64, "mime_type": "image/png"})
        self.assertEqual(raw, PNG_1X1)
        self.assertEqual(mime, "image/png")
        with self.assertRaises(BananaError) as caught:
            decode_image({"data": "%%%", "mime_type": "image/png"})
        self.assertEqual(caught.exception.code, "invalid_image_data")
        bad = base64.b64encode(b"not a png").decode("ascii")
        with self.assertRaises(BananaError) as caught:
            decode_image({"data": bad, "mime_type": "image/png"})
        self.assertEqual(caught.exception.code, "invalid_image_signature")
        with self.assertRaises(BananaError) as caught:
            decode_image({"data": PNG_1X1_B64})
        self.assertEqual(caught.exception.code, "missing_output_mime")

    def test_missing_provider_image_mime_fails_closed(self) -> None:
        interaction = completed_response()
        del interaction["steps"][1]["content"][1]["mime_type"]
        with self.assertRaises(BananaError) as caught:
            extract_interaction(interaction)
        self.assertEqual(caught.exception.code, "missing_output_mime")

        generated = generate_content_response()
        del generated["candidates"][0]["content"]["parts"][1]["inlineData"]["mimeType"]
        with self.assertRaises(BananaError) as caught:
            extract_generate_content(generated, model="gemini-3.1-flash-lite-image")
        self.assertEqual(caught.exception.code, "missing_output_mime")

    def test_atomic_artifact_and_sidecar_are_private(self) -> None:
        plan = build_plan(
            operation="generate",
            prompt="private prompt",
            web_search=True,
            visual_brief=structured_brief(),
        )
        response = completed_response()
        response["usage"].update(
            {
                "prompt": "private prompt",
                "nested": {"prompt": "private prompt"},
                "invalid_count": True,
            }
        )
        response["id"] = "private_prompt_sentinel"
        extracted = extract_interaction(response)
        with tempfile.TemporaryDirectory() as directory:
            artifacts = save_interaction(
                extracted,
                plan=plan,
                prompt="private prompt",
                destination=directory,
                label="test asset",
            )
            self.assertEqual(len(artifacts), 1)
            image = Path(artifacts[0]["path"])
            sidecar = Path(artifacts[0]["metadata_path"])
            self.assertEqual(image.read_bytes(), JPEG_1X1)
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertNotIn("prompt", metadata)
            self.assertNotIn("citations", metadata)
            self.assertNotIn("search_suggestions", metadata)
            self.assertEqual(metadata["usage"], {"total_tokens": 42})
            self.assertNotIn("interaction_id", metadata)
            self.assertEqual(
                metadata["interaction_id_sha256"],
                hashlib.sha256(b"private_prompt_sentinel").hexdigest(),
            )
            self.assertNotIn("private_prompt_sentinel", sidecar.read_text("utf-8"))
            self.assertTrue(metadata["grounding_used"])
            self.assertEqual(metadata["prompt_sha256"], plan["prompt_sha256"])
            self.assertEqual(metadata["brief_sha256"], plan["brief_sha256"])
            self.assertEqual(metadata["brief_source"], "supplied")
            self.assertEqual(
                metadata["visual_brief_schema_version"], "banana.visual-brief.v1"
            )
            self.assertNotIn("visual_brief", metadata)
            self.assertEqual(metadata["artifact"]["width"], 1)
            self.assertEqual(metadata["artifact"]["height"], 1)
            self.assertEqual(stat.S_IMODE(image.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(sidecar.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(Path(directory).stat().st_mode), 0o700)

    def test_recorded_prompt_matches_the_approved_normalized_prompt_hash(self) -> None:
        plan = build_plan(operation="generate", prompt="  normalized prompt  ")
        extracted = extract_interaction(completed_response())

        with tempfile.TemporaryDirectory() as directory:
            artifacts = save_interaction(
                extracted,
                plan=plan,
                prompt="  normalized prompt  ",
                destination=directory,
                record_prompt=True,
            )

            sidecar = Path(artifacts[0]["metadata_path"])
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(metadata["prompt"], "normalized prompt")
            self.assertEqual(
                hashlib.sha256(metadata["prompt"].encode("utf-8")).hexdigest(),
                metadata["prompt_sha256"],
            )

    def test_prompt_change_after_approval_is_rejected_before_publication(self) -> None:
        plan = build_plan(operation="generate", prompt="approved prompt")
        extracted = extract_interaction(completed_response())

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(BananaError) as caught:
                save_interaction(
                    extracted,
                    plan=plan,
                    prompt="different prompt",
                    destination=directory,
                    record_prompt=True,
                )

            self.assertEqual(caught.exception.code, "prompt_mismatch")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_bundle_failure_retains_published_sidecar_without_unlinking(self) -> None:
        plan = build_plan(operation="generate", prompt="transactional output")
        extracted = extract_interaction(completed_response())
        original_publish = banana_core._atomic_write_at
        calls = 0

        def fail_second_publication(*args: Any, **kwargs: Any) -> tuple[int, int]:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise BananaError(
                    "synthetic_publication_failure", "Synthetic publication failure."
                )
            return original_publish(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(
                    banana_core,
                    "_atomic_write_at",
                    side_effect=fail_second_publication,
                ),
                patch.object(
                    os,
                    "unlink",
                    side_effect=AssertionError("publication recovery must not unlink"),
                ),
            ):
                with self.assertRaises(BananaError) as caught:
                    save_interaction(
                        extracted,
                        plan=plan,
                        prompt="transactional output",
                        destination=directory,
                    )
            self.assertEqual(caught.exception.code, "output_bundle_retained")
            self.assertEqual(
                caught.exception.details["publication_error_code"],
                "synthetic_publication_failure",
            )
            self.assertTrue(caught.exception.details["recovery_required"])
            leftovers = list(root.iterdir())
            self.assertEqual(len(leftovers), 1)
            self.assertTrue(leftovers[0].name.endswith(".json"))
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_multi_image_failure_retains_only_this_calls_published_outputs(
        self,
    ) -> None:
        plan = build_plan(operation="generate", prompt="transactional portfolio")
        extracted = extract_interaction(completed_response(count=2))
        original_publish = banana_core._atomic_write_at
        calls = 0

        def fail_last_image(*args: Any, **kwargs: Any) -> tuple[int, int]:
            nonlocal calls
            calls += 1
            if calls == 4:
                raise BananaError(
                    "synthetic_publication_failure", "Synthetic publication failure."
                )
            return original_publish(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sentinel = root / "pre-existing.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            with patch.object(
                banana_core,
                "_atomic_write_at",
                side_effect=fail_last_image,
            ):
                with self.assertRaises(BananaError) as caught:
                    save_interaction(
                        extracted,
                        plan=plan,
                        prompt="transactional portfolio",
                        destination=root,
                    )
            self.assertEqual(caught.exception.code, "output_bundle_retained")
            self.assertEqual(
                caught.exception.details["publication_error_code"],
                "synthetic_publication_failure",
            )
            retained = caught.exception.details["retained_artifacts"]
            self.assertEqual(len(retained), 3)
            self.assertEqual(len(list(root.iterdir())), 4)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_post_publication_failure_retains_current_output(self) -> None:
        plan = build_plan(operation="generate", prompt="current artifact recovery")
        extracted = extract_interaction(completed_response())
        original_match = banana_core._directory_path_matches_fd
        checks = 0

        def fail_after_first_publication(path: Path, descriptor: int) -> bool:
            nonlocal checks
            checks += 1
            if checks == 3:
                return False
            return original_match(path, descriptor)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(
                banana_core,
                "_directory_path_matches_fd",
                side_effect=fail_after_first_publication,
            ):
                with self.assertRaises(BananaError) as caught:
                    save_interaction(
                        extracted,
                        plan=plan,
                        prompt="current artifact recovery",
                        destination=root,
                    )

            self.assertEqual(caught.exception.code, "output_bundle_retained")
            self.assertEqual(
                caught.exception.details["publication_error_code"],
                "output_directory_changed",
            )
            leftovers = list(root.iterdir())
            self.assertEqual(len(leftovers), 1)
            self.assertTrue(leftovers[0].name.endswith(".json"))
            self.assertEqual(list(root.glob(".*.tmp")), [])

    @unittest.skipUnless(
        sys.platform.startswith("linux") or sys.platform == "darwin",
        "atomic exclusive dirfd rename is supported on Linux and macOS",
    )
    def test_exclusive_publication_never_uses_hard_links(self) -> None:
        plan = build_plan(operation="generate", prompt="exclusive rename")
        extracted = extract_interaction(completed_response())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(
                os,
                "link",
                side_effect=AssertionError("hard links must not publish outputs"),
            ):
                artifacts = save_interaction(
                    extracted,
                    plan=plan,
                    prompt="exclusive rename",
                    destination=root,
                )
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(len(list(root.iterdir())), 2)

    def test_foreign_temporary_inode_is_never_deleted_after_rename_failure(
        self,
    ) -> None:
        foreign = b"foreign-temporary-content"

        def replace_temporary_then_fail(
            source_directory: int,
            source_name: str,
            _destination_directory: int,
            _destination_name: str,
        ) -> None:
            os.unlink(source_name, dir_fd=source_directory)
            foreign_descriptor = os.open(
                source_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=source_directory,
            )
            with os.fdopen(foreign_descriptor, "wb") as handle:
                handle.write(foreign)
            raise OSError("synthetic exclusive rename failure")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with patch.object(
                    banana_core,
                    "_exclusive_rename_at",
                    side_effect=replace_temporary_then_fail,
                ):
                    with self.assertRaises(BananaError) as caught:
                        banana_core._atomic_write_at(
                            descriptor,
                            "artifact.bin",
                            b"approved-content",
                            replace=False,
                            expected_directory=root,
                        )
            finally:
                os.close(descriptor)

            self.assertEqual(caught.exception.code, "output_claim_failed")
            self.assertTrue(caught.exception.details["temporary_not_deleted"])
            leftovers = list(root.iterdir())
            self.assertEqual(len(leftovers), 1)
            self.assertTrue(leftovers[0].name.startswith("."))
            self.assertTrue(leftovers[0].name.endswith(".tmp"))
            self.assertEqual(leftovers[0].read_bytes(), foreign)

    @unittest.skipUnless(
        sys.platform.startswith("linux") or sys.platform == "darwin",
        "atomic exclusive dirfd rename is supported on Linux and macOS",
    )
    def test_source_swap_reports_observed_final_and_unlocated_intended_inode(
        self,
    ) -> None:
        foreign = b"foreign-source-swap"
        original_rename = banana_core._exclusive_rename_at
        held_name = ".held-approved-output"

        def swap_source_then_publish(
            source_directory: int,
            source_name: str,
            destination_directory: int,
            destination_name: str,
        ) -> None:
            os.rename(
                source_name,
                held_name,
                src_dir_fd=source_directory,
                dst_dir_fd=source_directory,
            )
            foreign_descriptor = os.open(
                source_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=source_directory,
            )
            with os.fdopen(foreign_descriptor, "wb") as handle:
                handle.write(foreign)
            original_rename(
                source_directory,
                source_name,
                destination_directory,
                destination_name,
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with patch.object(
                    banana_core,
                    "_exclusive_rename_at",
                    side_effect=swap_source_then_publish,
                ):
                    with self.assertRaises(BananaError) as caught:
                        banana_core._atomic_write_at(
                            descriptor,
                            "artifact.bin",
                            b"approved-content",
                            replace=False,
                            expected_directory=root,
                        )
            finally:
                os.close(descriptor)

            self.assertEqual(caught.exception.code, "output_publication_retained")
            final = root / "artifact.bin"
            held = root / held_name
            self.assertEqual(final.read_bytes(), foreign)
            self.assertEqual(held.read_bytes(), b"approved-content")
            final_metadata = final.lstat()
            held_metadata = held.lstat()
            retained = caught.exception.details["retained_artifacts"]
            self.assertEqual(len(retained), 1)
            self.assertEqual(retained[0]["path"], str(final))
            self.assertEqual(
                (retained[0]["device"], retained[0]["inode"]),
                (final_metadata.st_dev, final_metadata.st_ino),
            )
            intended = caught.exception.details["intended_artifact"]
            self.assertEqual(
                (intended["device"], intended["inode"]),
                (held_metadata.st_dev, held_metadata.st_ino),
            )
            self.assertTrue(intended["path_unknown"])
            self.assertTrue(caught.exception.details["intended_artifact_path_unknown"])

    def test_post_rename_foreign_final_is_preserved_and_never_accepted(self) -> None:
        foreign = b"foreign-concurrent-content"
        original_rename = banana_core._exclusive_rename_at

        def replace_published_output(
            source_directory: int,
            source_name: str,
            destination_directory: int,
            destination_name: str,
        ) -> None:
            original_rename(
                source_directory,
                source_name,
                destination_directory,
                destination_name,
            )
            os.unlink(destination_name, dir_fd=destination_directory)
            foreign_descriptor = os.open(
                destination_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=destination_directory,
            )
            with os.fdopen(foreign_descriptor, "wb") as handle:
                handle.write(foreign)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with patch.object(
                    banana_core,
                    "_exclusive_rename_at",
                    side_effect=replace_published_output,
                ):
                    with self.assertRaises(BananaError) as caught:
                        banana_core._atomic_write_at(
                            descriptor,
                            "artifact.bin",
                            b"approved-content",
                            replace=False,
                            expected_directory=root,
                        )
            finally:
                os.close(descriptor)

            self.assertEqual(caught.exception.code, "output_publication_retained")
            self.assertEqual(
                caught.exception.details["publication_error_code"],
                "output_claim_changed",
            )
            self.assertEqual((root / "artifact.bin").read_bytes(), foreign)
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_bundle_commit_recheck_preserves_a_replaced_prior_artifact(self) -> None:
        plan = build_plan(operation="generate", prompt="bundle ownership")
        extracted = extract_interaction(completed_response())
        original_publish = banana_core._atomic_write_at
        first_name = ""
        first_directory = -1
        calls = 0

        def replace_before_bundle_commit(*args: Any, **kwargs: Any) -> tuple[int, int]:
            nonlocal calls, first_directory, first_name
            identity = original_publish(*args, **kwargs)
            calls += 1
            if calls == 1:
                first_directory = args[0]
                first_name = args[1]
            elif calls == 2:
                os.unlink(first_name, dir_fd=first_directory)
                foreign_descriptor = os.open(
                    first_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=first_directory,
                )
                with os.fdopen(foreign_descriptor, "wb") as handle:
                    handle.write(b"foreign-bundle-content")
            return identity

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(
                banana_core,
                "_atomic_write_at",
                side_effect=replace_before_bundle_commit,
            ):
                with self.assertRaises(BananaError) as caught:
                    save_interaction(
                        extracted,
                        plan=plan,
                        prompt="bundle ownership",
                        destination=root,
                    )

            self.assertEqual(calls, 2)
            self.assertEqual(caught.exception.code, "output_bundle_retained")
            self.assertEqual(
                caught.exception.details["publication_error_code"],
                "output_claim_changed",
            )
            leftovers = list(root.iterdir())
            self.assertEqual(len(leftovers), 2)
            self.assertEqual(
                (root / first_name).read_bytes(), b"foreign-bundle-content"
            )
            other = next(path for path in leftovers if path.name != first_name)
            self.assertEqual(other.read_bytes(), JPEG_1X1)
            retained = caught.exception.details["retained_artifacts"]
            self.assertEqual(len(retained), 3)
            intended = next(
                item
                for item in retained
                if item.get("artifact_relationship") == "intended_call_artifact"
                and item.get("last_known_path") == str(root / first_name)
            )
            observed = next(
                item
                for item in retained
                if item.get("artifact_relationship")
                == "observed_nonmatching_public_entry"
            )
            self.assertFalse(intended["path_binding_verified"])
            self.assertTrue(intended["path_unknown"])
            self.assertIsNone(intended["path"])
            self.assertTrue(observed["path_binding_verified"])
            self.assertTrue(observed["not_this_call_artifact"])

    def test_bundle_receipt_rejects_same_inode_mutation_of_prior_sidecar(
        self,
    ) -> None:
        plan = build_plan(operation="generate", prompt="bundle byte ownership")
        extracted = extract_interaction(completed_response())
        original_publish = banana_core._atomic_write_at
        first_name = ""
        first_directory = -1
        first_identity: tuple[int, int] | None = None
        mutated_identity: tuple[int, int] | None = None
        calls = 0

        def mutate_prior_sidecar(*args: Any, **kwargs: Any) -> tuple[int, int]:
            nonlocal calls, first_directory, first_identity, first_name
            nonlocal mutated_identity
            identity = original_publish(*args, **kwargs)
            calls += 1
            if calls == 1:
                first_directory = args[0]
                first_name = args[1]
                first_identity = identity
            elif calls == 2:
                descriptor = os.open(first_name, os.O_RDWR, dir_fd=first_directory)
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    os.write(descriptor, b"X")
                    os.fsync(descriptor)
                    metadata = os.fstat(descriptor)
                    mutated_identity = (metadata.st_dev, metadata.st_ino)
                finally:
                    os.close(descriptor)
            return identity

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(
                banana_core,
                "_atomic_write_at",
                side_effect=mutate_prior_sidecar,
            ):
                with self.assertRaises(BananaError) as caught:
                    save_interaction(
                        extracted,
                        plan=plan,
                        prompt="bundle byte ownership",
                        destination=root,
                    )

            self.assertEqual(calls, 2)
            self.assertEqual(first_identity, mutated_identity)
            self.assertEqual(caught.exception.code, "output_bundle_retained")
            self.assertEqual(
                caught.exception.details["publication_error_code"],
                "output_claim_changed",
            )
            self.assertEqual(len(list(root.iterdir())), 2)
            self.assertEqual((root / first_name).read_bytes()[:1], b"X")

    def test_bundle_receipt_rejects_same_inode_mutation_of_last_image(self) -> None:
        plan = build_plan(operation="generate", prompt="last image byte ownership")
        extracted = extract_interaction(completed_response())
        original_publish = banana_core._atomic_write_at
        published_identity: tuple[int, int] | None = None
        mutated_identity: tuple[int, int] | None = None
        mutated_name = ""
        calls = 0

        def mutate_last_image(*args: Any, **kwargs: Any) -> tuple[int, int]:
            nonlocal calls, mutated_identity, mutated_name, published_identity
            identity = original_publish(*args, **kwargs)
            calls += 1
            if calls == 2:
                directory_descriptor = args[0]
                mutated_name = args[1]
                published_identity = identity
                descriptor = os.open(
                    mutated_name,
                    os.O_RDWR,
                    dir_fd=directory_descriptor,
                )
                try:
                    os.lseek(descriptor, -1, os.SEEK_END)
                    os.write(descriptor, b"\x00")
                    os.fsync(descriptor)
                    metadata = os.fstat(descriptor)
                    mutated_identity = (metadata.st_dev, metadata.st_ino)
                finally:
                    os.close(descriptor)
            return identity

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(
                banana_core,
                "_atomic_write_at",
                side_effect=mutate_last_image,
            ):
                with self.assertRaises(BananaError) as caught:
                    save_interaction(
                        extracted,
                        plan=plan,
                        prompt="last image byte ownership",
                        destination=root,
                    )

            self.assertEqual(calls, 2)
            self.assertEqual(published_identity, mutated_identity)
            self.assertEqual(caught.exception.code, "output_bundle_retained")
            self.assertEqual(
                caught.exception.details["publication_error_code"],
                "output_claim_changed",
            )
            mutated = root / mutated_name
            self.assertTrue(mutated.read_bytes().startswith(b"\xff\xd8\xff"))
            self.assertEqual(mutated.read_bytes()[-1:], b"\x00")

    def test_phase_b_rejects_earlier_sidecar_mutated_after_phase_a(self) -> None:
        plan = build_plan(operation="generate", prompt="phase boundary mutation")
        extracted = extract_interaction(completed_response())
        original_phase_b = banana_core._bundle_phase_b_receipt_matches
        mutated_identity: tuple[int, int] | None = None
        calls = 0

        def mutate_before_phase_b(
            directory_descriptor: int,
            member: Any,
            phase_a: Any,
        ) -> bool:
            nonlocal calls, mutated_identity
            calls += 1
            if calls == 1:
                self.assertTrue(member.path.name.endswith(".json"))
                descriptor = os.open(
                    member.path.name,
                    os.O_RDWR,
                    dir_fd=directory_descriptor,
                )
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    os.write(descriptor, b"X")
                    os.fsync(descriptor)
                    metadata = os.fstat(descriptor)
                    mutated_identity = (metadata.st_dev, metadata.st_ino)
                finally:
                    os.close(descriptor)
            return original_phase_b(directory_descriptor, member, phase_a)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(
                banana_core,
                "_bundle_phase_b_receipt_matches",
                side_effect=mutate_before_phase_b,
            ):
                with self.assertRaises(BananaError) as caught:
                    save_interaction(
                        extracted,
                        plan=plan,
                        prompt="phase boundary mutation",
                        destination=root,
                    )

            self.assertEqual(calls, 1)
            self.assertIsNotNone(mutated_identity)
            self.assertEqual(caught.exception.code, "output_bundle_retained")
            self.assertEqual(
                caught.exception.details["publication_error_code"],
                "output_claim_changed",
            )
            sidecar = next(root.glob("*.json"))
            metadata = sidecar.stat()
            self.assertEqual(mutated_identity, (metadata.st_dev, metadata.st_ino))
            self.assertEqual(sidecar.read_bytes()[:1], b"X")

    def test_phase_b_ctime_rejects_same_size_write_and_byte_restore(self) -> None:
        plan = build_plan(operation="generate", prompt="ctime receipt")
        extracted = extract_interaction(completed_response())
        original_phase_b = banana_core._bundle_phase_b_receipt_matches
        restored_bytes: bytes | None = None
        observed_ctime_ns: int | None = None
        calls = 0

        def write_and_restore_before_phase_b(
            directory_descriptor: int,
            member: Any,
            phase_a: Any,
        ) -> bool:
            nonlocal calls, observed_ctime_ns, restored_bytes
            calls += 1
            if calls == 1:
                descriptor = os.open(
                    member.path.name,
                    os.O_RDWR,
                    dir_fd=directory_descriptor,
                )
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    original = os.read(descriptor, 1)
                    self.assertEqual(len(original), 1)
                    for _ in range(100):
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        os.write(descriptor, b"X" if original != b"X" else b"Y")
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        os.write(descriptor, original)
                        os.fsync(descriptor)
                        current = os.fstat(descriptor)
                        os.utime(
                            member.path.name,
                            ns=(current.st_atime_ns, member.baseline.mtime_ns),
                            dir_fd=directory_descriptor,
                            follow_symlinks=False,
                        )
                        current = os.fstat(descriptor)
                        if current.st_ctime_ns != member.baseline.ctime_ns:
                            observed_ctime_ns = current.st_ctime_ns
                            break
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    restored_bytes = os.read(descriptor, len(member.payload))
                finally:
                    os.close(descriptor)
                self.assertIsNotNone(observed_ctime_ns)
                self.assertEqual(restored_bytes, member.payload)
                restored = os.fstat(member.descriptor)
                self.assertEqual(restored.st_size, member.baseline.size)
                self.assertEqual(restored.st_mtime_ns, member.baseline.mtime_ns)
                self.assertEqual(restored.st_ctime_ns, observed_ctime_ns)
            return original_phase_b(directory_descriptor, member, phase_a)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(
                banana_core,
                "_bundle_phase_b_receipt_matches",
                side_effect=write_and_restore_before_phase_b,
            ):
                with self.assertRaises(BananaError) as caught:
                    save_interaction(
                        extracted,
                        plan=plan,
                        prompt="ctime receipt",
                        destination=root,
                    )

            self.assertEqual(calls, 1)
            self.assertEqual(caught.exception.code, "output_bundle_retained")
            self.assertEqual(
                caught.exception.details["publication_error_code"],
                "output_claim_changed",
            )
            self.assertIsNotNone(observed_ctime_ns)
            sidecar = next(root.glob("*.json"))
            self.assertEqual(sidecar.read_bytes(), restored_bytes)

    def test_phase_b_rejects_public_name_replacement_after_phase_a(self) -> None:
        plan = build_plan(operation="generate", prompt="phase name binding")
        extracted = extract_interaction(completed_response())
        original_phase_b = banana_core._bundle_phase_b_receipt_matches
        intended_identity: tuple[int, int] | None = None
        replacement_identity: tuple[int, int] | None = None
        calls = 0

        def replace_public_name_before_phase_b(
            directory_descriptor: int,
            member: Any,
            phase_a: Any,
        ) -> bool:
            nonlocal calls, intended_identity, replacement_identity
            calls += 1
            if calls == 1:
                intended_identity = member.identity
                os.unlink(member.path.name, dir_fd=directory_descriptor)
                descriptor = os.open(
                    member.path.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_descriptor,
                )
                try:
                    os.write(descriptor, member.payload)
                    os.fsync(descriptor)
                    metadata = os.fstat(descriptor)
                    replacement_identity = (metadata.st_dev, metadata.st_ino)
                finally:
                    os.close(descriptor)
            return original_phase_b(directory_descriptor, member, phase_a)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(
                banana_core,
                "_bundle_phase_b_receipt_matches",
                side_effect=replace_public_name_before_phase_b,
            ):
                with self.assertRaises(BananaError) as caught:
                    save_interaction(
                        extracted,
                        plan=plan,
                        prompt="phase name binding",
                        destination=root,
                    )

            self.assertEqual(calls, 1)
            self.assertNotEqual(intended_identity, replacement_identity)
            self.assertEqual(caught.exception.code, "output_bundle_retained")
            self.assertEqual(
                caught.exception.details["publication_error_code"],
                "output_claim_changed",
            )
            retained = caught.exception.details["retained_artifacts"]
            self.assertTrue(
                any(item.get("not_this_call_artifact") for item in retained)
            )

    def test_phase_b_rejects_output_directory_swap_after_phase_a(self) -> None:
        plan = build_plan(operation="generate", prompt="phase directory binding")
        extracted = extract_interaction(completed_response())
        original_phase_b = banana_core._bundle_phase_b_receipt_matches
        calls = 0

        with tempfile.TemporaryDirectory() as directory:
            container = Path(directory)
            destination = container / "approved"
            held = container / "held-approved"

            def swap_directory_before_phase_b(
                directory_descriptor: int,
                member: Any,
                phase_a: Any,
            ) -> bool:
                nonlocal calls
                calls += 1
                if calls == 1:
                    destination.rename(held)
                    destination.mkdir()
                return original_phase_b(directory_descriptor, member, phase_a)

            with patch.object(
                banana_core,
                "_bundle_phase_b_receipt_matches",
                side_effect=swap_directory_before_phase_b,
            ):
                with self.assertRaises(BananaError) as caught:
                    save_interaction(
                        extracted,
                        plan=plan,
                        prompt="phase directory binding",
                        destination=destination,
                    )

            self.assertEqual(calls, 1)
            self.assertEqual(caught.exception.code, "output_bundle_retained")
            self.assertEqual(
                caught.exception.details["publication_error_code"],
                "output_claim_changed",
            )
            self.assertEqual(list(destination.iterdir()), [])
            self.assertEqual(len(list(held.iterdir())), 2)
            destination.rmdir()
            held.rename(destination)

    def test_fallback_no_replace_fails_closed_without_temp_or_hardlink(self) -> None:
        plan = build_plan(operation="generate", prompt="fallback fail closed")
        extracted = extract_interaction(completed_response())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(banana_core, "_open_secure_directory", return_value=None),
                patch.object(tempfile, "mkstemp") as make_temporary,
                patch.object(os, "link") as make_hardlink,
            ):
                with self.assertRaises(BananaError) as caught:
                    save_interaction(
                        extracted,
                        plan=plan,
                        prompt="fallback fail closed",
                        destination=root,
                    )

            self.assertEqual(
                caught.exception.code, "output_exclusive_rename_unavailable"
            )
            make_temporary.assert_not_called()
            make_hardlink.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_final_bundle_stat_oserror_is_typed_and_outputs_are_retained(
        self,
    ) -> None:
        plan = build_plan(operation="generate", prompt="bundle stat")
        extracted = extract_interaction(completed_response())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(
                banana_core,
                "_bundle_artifact_identity",
                side_effect=OSError("synthetic final stat failure"),
            ):
                with self.assertRaises(BananaError) as caught:
                    save_interaction(
                        extracted,
                        plan=plan,
                        prompt="bundle stat",
                        destination=root,
                    )

            self.assertEqual(caught.exception.code, "output_bundle_retained")
            self.assertEqual(
                caught.exception.details["publication_error_code"],
                "output_claim_changed",
            )
            self.assertEqual(len(list(root.iterdir())), 2)

    def test_final_bundle_lstat_oserror_is_typed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "artifact.bin"
            artifact.write_bytes(b"content")
            with patch.object(
                os,
                "lstat",
                side_effect=OSError("synthetic final lstat failure"),
            ):
                with self.assertRaises(BananaError) as caught:
                    banana_core._bundle_artifact_identity(artifact, None)
            self.assertEqual(caught.exception.code, "output_bundle_stat_failed")

    def test_provider_output_rejects_parent_identity_changes(self) -> None:
        plan = build_plan(operation="generate", prompt="stable destination")
        extracted = extract_interaction(completed_response())
        original_match = banana_core._directory_path_matches_fd

        for parent_exists in (True, False):
            with (
                self.subTest(parent_exists=parent_exists),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                destination = root / "approved"
                if parent_exists:
                    destination.mkdir()
                moved = root / "approved-before-swap"
                redirect = root / "redirect"
                redirect.mkdir()
                swapped = False

                def swap_before_publication(path: Path, descriptor: int) -> bool:
                    nonlocal swapped
                    if not swapped and Path(path) == destination:
                        destination.rename(moved)
                        destination.symlink_to(redirect, target_is_directory=True)
                        swapped = True
                    return original_match(path, descriptor)

                with patch.object(
                    banana_core,
                    "_directory_path_matches_fd",
                    side_effect=swap_before_publication,
                ):
                    with self.assertRaises(BananaError) as caught:
                        save_interaction(
                            extracted,
                            plan=plan,
                            prompt="stable destination",
                            destination=destination,
                        )
                self.assertEqual(caught.exception.code, "output_directory_changed")
                self.assertEqual(list(redirect.iterdir()), [])
                self.assertEqual(list(moved.iterdir()), [])

    def test_existing_output_directory_mode_is_preserved(self) -> None:
        plan = build_plan(operation="generate", prompt="shared destination")
        extracted = extract_interaction(completed_response())
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "shared"
            destination.mkdir(mode=0o755)
            destination.chmod(0o755)
            save_interaction(
                extracted,
                plan=plan,
                prompt="shared destination",
                destination=destination,
            )
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o755)

    def test_output_type_mismatch_writes_nothing(self) -> None:
        plan = build_plan(operation="generate", prompt="jpeg", mime_type="image/jpeg")
        extracted = extract_interaction(completed_response(mime_type="image/png"))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(BananaError) as caught:
                save_interaction(
                    extracted, plan=plan, prompt="jpeg", destination=directory
                )
            self.assertEqual(caught.exception.code, "output_type_mismatch")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_exact_plan_confirmation_precedes_network(self) -> None:
        calls: list[bool] = []

        def opener(_request: Any, **_kwargs: Any) -> FakeResponse:
            calls.append(True)
            return FakeResponse(completed_response())

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            with self.assertRaises(BananaError) as caught:
                execute_image(
                    operation="generate",
                    prompt="approved prompt",
                    approval_id="wrong-plan",
                    destination=directory,
                    api_key=AUTH_VALUE,
                    opener=opener,
                )
            self.assertEqual(caught.exception.code, "invalid_approval")
            self.assertEqual(calls, [])

            plan = build_plan(
                operation="generate", prompt="approved prompt", destination=directory
            )
            approval = issue_approval(plan["request_fingerprint"], kind="single")
            result = execute_image(
                operation="generate",
                prompt="approved prompt",
                approval_id=approval["approval_id"],
                destination=directory,
                api_key=AUTH_VALUE,
                opener=opener,
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["transport_ok"])
            self.assertEqual(result["visual_review_status"], "needs_review")
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(result["artifacts"]), 1)
            with self.assertRaises(BananaError) as caught:
                execute_image(
                    operation="generate",
                    prompt="approved prompt",
                    approval_id=approval["approval_id"],
                    destination=directory,
                    api_key=AUTH_VALUE,
                    opener=opener,
                )
            self.assertEqual(caught.exception.code, "approval_already_used")
            self.assertEqual(len(calls), 1)

    def test_publication_capability_is_proven_before_provider_io(self) -> None:
        calls: list[bool] = []

        def opener(_request: Any, **_kwargs: Any) -> FakeResponse:
            calls.append(True)
            return FakeResponse(completed_response())

        with tempfile.TemporaryDirectory() as directory:
            plan = build_plan(
                operation="generate",
                prompt="preflight before spend",
                destination=directory,
            )
            with patch.object(
                banana_core,
                "_exclusive_rename_at",
                side_effect=BananaError(
                    "output_exclusive_rename_unavailable",
                    "Synthetic unsupported publication filesystem.",
                ),
            ):
                with self.assertRaises(BananaError) as caught:
                    execute_validated_plan(
                        plan=plan,
                        prompt="preflight before spend",
                        api_key=AUTH_VALUE,
                        opener=opener,
                    )

            self.assertEqual(
                caught.exception.code,
                "output_exclusive_rename_unavailable",
            )
            self.assertFalse(caught.exception.details["provider_called"])
            self.assertEqual(calls, [])
            source = caught.exception.details["preflight_source"]
            self.assertFalse(source["path_binding_verified"])
            recovery = Path(source["last_known_path"])
            self.assertTrue(recovery.is_file())
            receipt = json.loads(recovery.read_text(encoding="utf-8"))
            self.assertEqual(receipt["schema_version"], 1)
            self.assertEqual(
                receipt["purpose"],
                "atomic-no-replace-publication",
            )
            self.assertEqual(receipt["directory_inode"], Path(directory).stat().st_ino)

    def test_invalid_approval_closes_preacquired_publication_capability(self) -> None:
        held: list[banana_core.OutputPublicationCapability] = []
        original_acquire = banana_core.acquire_output_publication

        def capture(
            path: str | Path,
        ) -> banana_core.OutputPublicationCapability:
            capability = original_acquire(path)
            held.append(capability)
            return capability

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            with patch.object(
                banana_core,
                "acquire_output_publication",
                side_effect=capture,
            ):
                with self.assertRaises(BananaError) as caught:
                    execute_image(
                        operation="generate",
                        prompt="invalid approval cleanup",
                        approval_id="invalid",
                        destination=directory,
                        api_key=AUTH_VALUE,
                    )

        self.assertEqual(caught.exception.code, "invalid_approval")
        self.assertEqual(len(held), 1)
        self.assertTrue(held[0].closed)

    def test_publication_capability_is_retained_and_reused_without_deletion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_rename = banana_core._exclusive_rename_at
            with (
                patch.object(
                    banana_core,
                    "_exclusive_rename_at",
                    wraps=original_rename,
                ) as rename,
                patch.object(
                    os,
                    "unlink",
                    side_effect=AssertionError("preflight must not unlink"),
                ),
                patch.object(
                    os,
                    "rmdir",
                    side_effect=AssertionError("preflight must not rmdir"),
                ),
            ):
                banana_core.preflight_output_publication(root)
                banana_core.preflight_output_publication(root)

            self.assertEqual(rename.call_count, 1)
            receipt = root / banana_core.PUBLICATION_CAPABILITY_NAME
            self.assertTrue(receipt.is_file())
            self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
            self.assertEqual(list(root.iterdir()), [receipt])

    def test_stale_publication_receipt_is_quarantined_and_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / banana_core.PUBLICATION_CAPABILITY_NAME
            stale_bytes = (
                json.dumps(
                    {
                        "directory_device": 0,
                        "directory_inode": 0,
                        "purpose": "atomic-no-replace-publication",
                        "schema_version": 1,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode()
            receipt.write_bytes(stale_bytes)
            receipt.chmod(0o600)

            capability = banana_core.acquire_output_publication(root)
            capability.close()

            digest = hashlib.sha256(stale_bytes).hexdigest()[:16]
            quarantine = root / (
                f"{banana_core.PUBLICATION_CAPABILITY_NAME}.stale-{digest}"
            )
            self.assertEqual(quarantine.read_bytes(), stale_bytes)
            refreshed = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(refreshed["directory_device"], root.stat().st_dev)
            self.assertEqual(refreshed["directory_inode"], root.stat().st_ino)
            self.assertEqual(stat.S_IMODE(quarantine.stat().st_mode), 0o600)

    def test_stale_receipt_quarantine_collision_fails_without_movement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / banana_core.PUBLICATION_CAPABILITY_NAME
            stale_bytes = (
                json.dumps(
                    {
                        "directory_device": root.stat().st_dev + 1,
                        "directory_inode": root.stat().st_ino + 1,
                        "purpose": "atomic-no-replace-publication",
                        "schema_version": 1,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode()
            receipt.write_bytes(stale_bytes)
            receipt.chmod(0o600)
            digest = hashlib.sha256(stale_bytes).hexdigest()[:16]
            quarantine = root / (
                f"{banana_core.PUBLICATION_CAPABILITY_NAME}.stale-{digest}"
            )
            quarantine.write_bytes(b"existing quarantine")
            quarantine.chmod(0o600)

            with self.assertRaises(BananaError) as caught:
                banana_core.acquire_output_publication(root)

            self.assertEqual(
                caught.exception.code, "output_preflight_quarantine_conflict"
            )
            self.assertTrue(caught.exception.details["quarantine_collision"])
            self.assertEqual(receipt.read_bytes(), stale_bytes)
            self.assertEqual(quarantine.read_bytes(), b"existing quarantine")

    def test_malformed_receipt_remains_fail_closed_and_unmoved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / banana_core.PUBLICATION_CAPABILITY_NAME
            malformed = b'{"schema_version":1,"purpose":"wrong"}\n'
            receipt.write_bytes(malformed)
            receipt.chmod(0o600)

            with self.assertRaises(BananaError) as caught:
                banana_core.acquire_output_publication(root)

            self.assertEqual(caught.exception.code, "output_preflight_receipt_invalid")
            self.assertTrue(caught.exception.details["recovery_required"])
            self.assertEqual(
                caught.exception.details["receipt_recovery_status"],
                "manual_review_required",
            )
            self.assertEqual(receipt.read_bytes(), malformed)
            self.assertEqual(list(root.glob("*.stale-*")), [])

    def test_save_interaction_does_not_close_caller_owned_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = build_plan(
                operation="generate",
                prompt="caller owned capability",
                destination=directory,
            )
            capability = banana_core.acquire_output_publication(directory)
            try:
                artifacts = save_interaction(
                    extract_interaction(completed_response()),
                    plan=plan,
                    prompt="caller owned capability",
                    destination=directory,
                    publication_capability=capability,
                )
                self.assertEqual(len(artifacts), 1)
                self.assertFalse(capability.closed)
                self.assertTrue(stat.S_ISDIR(os.fstat(capability.descriptor).st_mode))
            finally:
                capability.close()

    def test_execute_validated_plan_closes_its_acquired_capability(self) -> None:
        held: list[banana_core.OutputPublicationCapability] = []
        original_acquire = banana_core.acquire_output_publication

        def capture(
            path: str | Path,
        ) -> banana_core.OutputPublicationCapability:
            capability = original_acquire(path)
            held.append(capability)
            return capability

        def opener(_request: Any, **_kwargs: Any) -> FakeResponse:
            return FakeResponse(completed_response())

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            plan = build_plan(
                operation="generate",
                prompt="owned execution cleanup",
                destination=directory,
            )
            with patch.object(
                banana_core,
                "acquire_output_publication",
                side_effect=capture,
            ):
                result = execute_validated_plan(
                    plan=plan,
                    prompt="owned execution cleanup",
                    api_key=AUTH_VALUE,
                    opener=opener,
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["cost_recording_status"], "recorded")
        self.assertTrue(result["cost_log_recorded"])
        self.assertFalse(result["unlogged_billable_attempt"])
        self.assertRegex(result["attempt_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(result["attempt_sha256"], result["cost_log"]["attempt_sha256"])
        self.assertEqual(len(held), 1)
        self.assertTrue(held[0].closed)

    def test_cost_interrupt_after_ledger_publish_is_reconciled_and_stops(
        self,
    ) -> None:
        original_recorded_result = cost_tracker._recorded_result

        for interruption in (
            KeyboardInterrupt("synthetic post-save interrupt"),
            SystemExit("synthetic post-save exit"),
        ):
            with (
                self.subTest(interruption=type(interruption).__name__),
                tempfile.TemporaryDirectory() as directory,
                temporary_banana_home() as banana_home,
            ):
                batch = isinstance(interruption, SystemExit)
                plan = build_plan(
                    operation="generate",
                    prompt="interrupt after ledger publish",
                    destination=directory,
                    batch=batch,
                )
                result_calls = 0

                def interrupt_first_result(*args: Any, **kwargs: Any) -> dict[str, Any]:
                    nonlocal result_calls
                    result_calls += 1
                    if result_calls == 1:
                        raise interruption
                    return original_recorded_result(*args, **kwargs)

                with (
                    patch.object(
                        cost_tracker,
                        "_recorded_result",
                        side_effect=interrupt_first_result,
                    ),
                    patch.object(banana_core, "save_interaction") as save_artifacts,
                ):
                    with self.assertRaises(BananaError) as caught:
                        execute_validated_plan(
                            plan=plan,
                            prompt="interrupt after ledger publish",
                            api_key=AUTH_VALUE,
                            opener=lambda _request, **_kwargs: FakeResponse(
                                completed_response()
                            ),
                        )

                self.assertEqual(result_calls, 2)
                self.assertEqual(
                    caught.exception.code,
                    "cost_recording_interrupted_after_provider",
                )
                self.assertIs(caught.exception.__cause__, interruption)
                details = caught.exception.details
                self.assertTrue(details["provider_succeeded"])
                self.assertTrue(details["billable_attempt"])
                self.assertEqual(details["provider_attempt_count"], 1)
                self.assertEqual(details["provider_output_count"], 1)
                self.assertEqual(
                    details["estimated_image_output_usd"],
                    plan["image_output_rate_usd"],
                )
                self.assertEqual(details["cost_recording_status"], "recorded")
                self.assertTrue(details["cost_log_recorded"])
                self.assertFalse(details["unlogged_billable_attempt"])
                self.assertEqual(
                    details["interrupted_exception_type"],
                    type(interruption).__name__,
                )
                self.assertEqual(
                    details["cost_log"]["attempt_sha256"],
                    details["attempt_sha256"],
                )
                ledger = json.loads((banana_home / "costs.json").read_text("utf-8"))
                self.assertEqual(ledger["total_images"], 1)
                self.assertEqual(len(ledger["entries"]), 1)
                self.assertIs(ledger["entries"][0]["batch"], batch)
                save_artifacts.assert_not_called()
                self.assertEqual(list(Path(directory).glob("banana_*")), [])

    def test_cost_wrapper_interrupt_after_recorder_return_is_reconciled_and_stops(
        self,
    ) -> None:
        real_record_generation = cost_tracker.record_generation

        for interruption in (
            KeyboardInterrupt("synthetic wrapper interrupt"),
            SystemExit("synthetic wrapper exit"),
        ):
            with (
                self.subTest(interruption=type(interruption).__name__),
                tempfile.TemporaryDirectory() as directory,
                temporary_banana_home() as banana_home,
            ):
                plan = build_plan(
                    operation="generate",
                    prompt="interrupt after recorder return",
                    destination=directory,
                )
                wrapper_calls = 0

                def interrupt_after_return(**kwargs: Any) -> dict[str, Any]:
                    nonlocal wrapper_calls
                    wrapper_calls += 1
                    recorded = real_record_generation(**kwargs)
                    self.assertEqual(recorded["status"], "recorded")
                    raise interruption

                with (
                    patch.object(
                        cost_tracker,
                        "record_generation",
                        side_effect=interrupt_after_return,
                    ),
                    patch.object(banana_core, "save_interaction") as save_artifacts,
                ):
                    with self.assertRaises(BananaError) as caught:
                        execute_validated_plan(
                            plan=plan,
                            prompt="interrupt after recorder return",
                            api_key=AUTH_VALUE,
                            opener=lambda _request, **_kwargs: FakeResponse(
                                completed_response()
                            ),
                        )

                self.assertEqual(wrapper_calls, 1)
                self.assertEqual(
                    caught.exception.code,
                    "cost_recording_interrupted_after_provider",
                )
                self.assertIs(caught.exception.__cause__, interruption)
                details = caught.exception.details
                self.assertEqual(details["cost_recording_status"], "recorded")
                self.assertTrue(details["cost_log_recorded"])
                self.assertFalse(details["unlogged_billable_attempt"])
                self.assertEqual(
                    details["interrupted_exception_type"],
                    type(interruption).__name__,
                )
                self.assertEqual(
                    details["cost_log"]["attempt_sha256"],
                    details["attempt_sha256"],
                )
                ledger = json.loads((banana_home / "costs.json").read_text("utf-8"))
                self.assertEqual(ledger["total_images"], 1)
                self.assertEqual(len(ledger["entries"]), 1)
                save_artifacts.assert_not_called()
                self.assertEqual(list(Path(directory).glob("banana_*")), [])

    def test_cost_interrupt_with_conclusive_absence_stops_without_artifacts(
        self,
    ) -> None:
        interruption = KeyboardInterrupt("synthetic absent attempt interrupt")
        with (
            tempfile.TemporaryDirectory() as directory,
            temporary_banana_home() as banana_home,
            patch.object(
                cost_tracker,
                "record_generation",
                side_effect=interruption,
            ),
            patch.object(banana_core, "save_interaction") as save_artifacts,
        ):
            plan = build_plan(
                operation="generate",
                prompt="conclusively absent interrupted attempt",
                destination=directory,
            )
            with self.assertRaises(BananaError) as caught:
                execute_validated_plan(
                    plan=plan,
                    prompt="conclusively absent interrupted attempt",
                    api_key=AUTH_VALUE,
                    opener=lambda _request, **_kwargs: FakeResponse(
                        completed_response()
                    ),
                )

            self.assertEqual(
                caught.exception.code,
                "cost_recording_interrupted_after_provider",
            )
            self.assertIs(caught.exception.__cause__, interruption)
            details = caught.exception.details
            self.assertEqual(details["cost_recording_status"], "not_recorded")
            self.assertFalse(details["cost_log_recorded"])
            self.assertTrue(details["unlogged_billable_attempt"])
            self.assertEqual(
                details["cost_log_error"]["code"],
                "cost_recording_not_recorded",
            )
            self.assertEqual(
                details["cost_log_error"]["details"]["attempt_sha256"],
                details["attempt_sha256"],
            )
            self.assertFalse((banana_home / "costs.json").exists())
            save_artifacts.assert_not_called()
            self.assertEqual(list(Path(directory).glob("banana_*")), [])

    def test_cost_interrupt_with_failed_reconciliation_reports_unknown_safely(
        self,
    ) -> None:
        for reconciliation_failure in (
            KeyboardInterrupt("nested interrupt sentinel"),
            RuntimeError("unexpected failure sentinel"),
        ):
            interruption = SystemExit("synthetic recorder exit")
            with (
                self.subTest(failure=type(reconciliation_failure).__name__),
                tempfile.TemporaryDirectory() as directory,
                temporary_banana_home(),
            ):
                plan = build_plan(
                    operation="generate",
                    prompt="failed interrupted reconciliation",
                    destination=directory,
                )
                with (
                    patch.object(
                        cost_tracker,
                        "record_generation",
                        side_effect=interruption,
                    ),
                    patch.object(
                        cost_tracker,
                        "reconcile_generation_attempt",
                        side_effect=reconciliation_failure,
                    ),
                    patch.object(banana_core, "save_interaction") as save_artifacts,
                ):
                    with self.assertRaises(BananaError) as caught:
                        execute_validated_plan(
                            plan=plan,
                            prompt="failed interrupted reconciliation",
                            api_key=AUTH_VALUE,
                            opener=lambda _request, **_kwargs: FakeResponse(
                                completed_response()
                            ),
                        )

                self.assertEqual(
                    caught.exception.code,
                    "cost_recording_interrupted_after_provider",
                )
                self.assertIs(caught.exception.__cause__, interruption)
                details = caught.exception.details
                self.assertEqual(
                    details["cost_recording_status"],
                    "unknown_requires_reconciliation",
                )
                self.assertIsNone(details["cost_log_recorded"])
                self.assertIsNone(details["unlogged_billable_attempt"])
                self.assertEqual(
                    details["cost_log_error"]["code"],
                    "cost_recording_unknown_requires_reconciliation",
                )
                self.assertEqual(
                    details["cost_log_error"]["details"]["exception_type"],
                    type(reconciliation_failure).__name__,
                )
                serialized = json.dumps(details, sort_keys=True)
                self.assertNotIn("sentinel", serialized)
                save_artifacts.assert_not_called()
                self.assertEqual(list(Path(directory).glob("banana_*")), [])

    def test_execute_rejects_prompt_mismatch_before_preflight_or_provider(self) -> None:
        calls: list[bool] = []

        def opener(_request: Any, **_kwargs: Any) -> FakeResponse:
            calls.append(True)
            return FakeResponse(completed_response())

        with tempfile.TemporaryDirectory() as directory:
            plan = build_plan(
                operation="generate",
                prompt="approved prompt",
                destination=directory,
            )
            with patch.object(banana_core, "preflight_output_publication") as preflight:
                with self.assertRaises(BananaError) as caught:
                    execute_validated_plan(
                        plan=plan,
                        prompt="different prompt",
                        api_key=AUTH_VALUE,
                        opener=opener,
                    )

            self.assertEqual(caught.exception.code, "prompt_mismatch")
            preflight.assert_not_called()
            self.assertEqual(calls, [])

    def test_unusable_provider_response_discloses_unlogged_billable_attempt(
        self,
    ) -> None:
        response = completed_response(count=0)

        def opener(_request: Any, **_kwargs: Any) -> FakeResponse:
            return FakeResponse(response)

        with tempfile.TemporaryDirectory() as directory:
            plan = build_plan(
                operation="generate",
                prompt="provider response accounting",
                destination=directory,
            )
            with self.assertRaises(BananaError) as caught:
                execute_validated_plan(
                    plan=plan,
                    prompt="provider response accounting",
                    api_key=AUTH_VALUE,
                    opener=opener,
                )

            self.assertEqual(caught.exception.code, "no_image")
            self.assertTrue(caught.exception.details["provider_response_received"])
            self.assertTrue(caught.exception.details["billable_attempt"])
            self.assertTrue(caught.exception.details["unlogged_billable_attempt"])
            self.assertFalse(caught.exception.details["cost_log_recorded"])
            self.assertEqual(
                caught.exception.details["cost_recording_status"], "not_recorded"
            )
            self.assertRegex(
                caught.exception.details["attempt_sha256"], r"^[0-9a-f]{64}$"
            )
            self.assertIsNone(caught.exception.details["provider_output_count"])

    def test_provider_success_is_logged_before_artifact_publication_failure(
        self,
    ) -> None:
        interaction_id = "synthetic-provider-success-id"
        response = completed_response()
        response["id"] = interaction_id

        def opener(_request: Any, **_kwargs: Any) -> FakeResponse:
            return FakeResponse(response)

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            plan = build_plan(
                operation="generate",
                prompt="billable publication failure",
                destination=directory,
            )
            with patch.object(
                banana_core,
                "save_interaction",
                side_effect=BananaError(
                    "synthetic_publication_failure",
                    "Synthetic publication failure.",
                ),
            ):
                with self.assertRaises(BananaError) as caught:
                    execute_validated_plan(
                        plan=plan,
                        prompt="billable publication failure",
                        api_key=AUTH_VALUE,
                        opener=opener,
                    )

            self.assertEqual(caught.exception.code, "synthetic_publication_failure")
            self.assertTrue(caught.exception.details["provider_succeeded"])
            self.assertTrue(caught.exception.details["billable_attempt"])
            self.assertTrue(caught.exception.details["cost_log_recorded"])
            self.assertFalse(caught.exception.details["unlogged_billable_attempt"])
            ledger_path = Path(os.environ["BANANA_HOME"]) / "costs.json"
            ledger_bytes = ledger_path.read_bytes()
            self.assertNotIn(interaction_id.encode(), ledger_bytes)
            ledger = json.loads(ledger_bytes)
            self.assertEqual(ledger["total_images"], 1)
            entry = ledger["entries"][0]
            self.assertNotIn("interaction_id", entry)
            self.assertEqual(
                entry["interaction_id_sha256"],
                hashlib.sha256(interaction_id.encode()).hexdigest(),
            )
            self.assertNotIn(
                interaction_id,
                json.dumps(caught.exception.details["cost_log"]),
            )

    def test_publication_failure_preserves_typed_not_recorded_signal(
        self,
    ) -> None:
        def opener(_request: Any, **_kwargs: Any) -> FakeResponse:
            return FakeResponse(completed_response())

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            plan = build_plan(
                operation="generate",
                prompt="unlogged billable attempt",
                destination=directory,
            )
            with (
                patch(
                    "cost_tracker.record_generation",
                    side_effect=BananaError(
                        "cost_recording_not_recorded",
                        "Synthetic conclusive absence.",
                        details={"status": "not_recorded"},
                    ),
                ),
                patch.object(
                    banana_core,
                    "save_interaction",
                    side_effect=BananaError(
                        "synthetic_publication_failure",
                        "Synthetic publication failure.",
                    ),
                ),
            ):
                with self.assertRaises(BananaError) as caught:
                    execute_validated_plan(
                        plan=plan,
                        prompt="unlogged billable attempt",
                        api_key=AUTH_VALUE,
                        opener=opener,
                    )

            self.assertEqual(caught.exception.code, "synthetic_publication_failure")
            self.assertFalse(caught.exception.details["cost_log_recorded"])
            self.assertTrue(caught.exception.details["unlogged_billable_attempt"])
            self.assertEqual(
                caught.exception.details["cost_recording_status"], "not_recorded"
            )
            self.assertEqual(
                caught.exception.details["cost_log_error"]["code"],
                "cost_recording_not_recorded",
            )

    def test_publication_failure_preserves_ambiguous_cost_state(self) -> None:
        def opener(_request: Any, **_kwargs: Any) -> FakeResponse:
            return FakeResponse(completed_response())

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            plan = build_plan(
                operation="generate",
                prompt="ambiguous cost attempt",
                destination=directory,
            )
            with (
                patch(
                    "cost_tracker.record_generation",
                    side_effect=BananaError(
                        "cost_recording_unknown_requires_reconciliation",
                        "Synthetic ambiguity.",
                        details={"status": "unknown_requires_reconciliation"},
                    ),
                ),
                patch.object(
                    banana_core,
                    "save_interaction",
                    side_effect=BananaError(
                        "synthetic_publication_failure",
                        "Synthetic publication failure.",
                    ),
                ),
            ):
                with self.assertRaises(BananaError) as caught:
                    execute_validated_plan(
                        plan=plan,
                        prompt="ambiguous cost attempt",
                        api_key=AUTH_VALUE,
                        opener=opener,
                    )

        details = caught.exception.details
        self.assertEqual(
            details["cost_recording_status"], "unknown_requires_reconciliation"
        )
        self.assertIsNone(details["cost_log_recorded"])
        self.assertIsNone(details["unlogged_billable_attempt"])

    def test_reconciled_cost_record_is_reported_as_recorded(self) -> None:
        def opener(_request: Any, **_kwargs: Any) -> FakeResponse:
            return FakeResponse(completed_response())

        def reconciled_record(**kwargs: Any) -> dict[str, Any]:
            return {
                "status": "recorded",
                "logged": True,
                "idempotent_replay": False,
                "reconciled_after_save_error": True,
                "attempt_sha256": kwargs["attempt_sha256"],
            }

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            plan = build_plan(
                operation="generate",
                prompt="reconciled cost attempt",
                destination=directory,
            )
            with patch("cost_tracker.record_generation", side_effect=reconciled_record):
                result = execute_validated_plan(
                    plan=plan,
                    prompt="reconciled cost attempt",
                    api_key=AUTH_VALUE,
                    opener=opener,
                )

        self.assertEqual(result["cost_recording_status"], "recorded")
        self.assertTrue(result["cost_log_recorded"])
        self.assertFalse(result["unlogged_billable_attempt"])
        self.assertTrue(result["cost_log"]["reconciled_after_save_error"])

    def test_unverifiable_cost_recorder_result_requires_reconciliation(self) -> None:
        def opener(_request: Any, **_kwargs: Any) -> FakeResponse:
            return FakeResponse(completed_response())

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            plan = build_plan(
                operation="generate",
                prompt="malformed cost result",
                destination=directory,
            )
            with patch(
                "cost_tracker.record_generation",
                return_value={"status": "recorded", "logged": True},
            ):
                result = execute_validated_plan(
                    plan=plan,
                    prompt="malformed cost result",
                    api_key=AUTH_VALUE,
                    opener=opener,
                )

        self.assertEqual(
            result["cost_recording_status"], "unknown_requires_reconciliation"
        )
        self.assertIsNone(result["cost_log_recorded"])
        self.assertIsNone(result["unlogged_billable_attempt"])
        self.assertNotIn("cost_log", result)
        self.assertEqual(
            result["cost_log_error"]["code"],
            "cost_recording_unknown_requires_reconciliation",
        )

    def test_provider_directory_swap_writes_no_artifacts_and_closes_capability(
        self,
    ) -> None:
        calls = 0
        held_capabilities: list[banana_core.OutputPublicationCapability] = []
        held_descriptors: list[int] = []
        original_acquire = banana_core.acquire_output_publication

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            root = Path(directory)
            destination = root / "approved"
            destination.mkdir()
            held_original = root / "held-original"

            def capture_capability(
                path: str | Path,
            ) -> banana_core.OutputPublicationCapability:
                capability = original_acquire(path)
                held_capabilities.append(capability)
                held_descriptors.append(capability.descriptor)
                return capability

            def swapping_opener(_request: Any, **_kwargs: Any) -> FakeResponse:
                nonlocal calls
                calls += 1
                destination.rename(held_original)
                destination.mkdir()
                return FakeResponse(completed_response())

            plan = build_plan(
                operation="generate",
                prompt="directory swap",
                destination=destination,
            )
            approval = issue_approval(plan["request_fingerprint"], kind="single")
            with patch.object(
                banana_core,
                "acquire_output_publication",
                side_effect=capture_capability,
            ):
                with self.assertRaises(BananaError) as caught:
                    execute_image(
                        operation="generate",
                        prompt="directory swap",
                        approval_id=approval["approval_id"],
                        destination=destination,
                        api_key=AUTH_VALUE,
                        opener=swapping_opener,
                    )

            self.assertEqual(calls, 1)
            self.assertEqual(caught.exception.code, "output_directory_changed")
            self.assertTrue(caught.exception.details["provider_succeeded"])
            self.assertTrue(caught.exception.details["billable_attempt"])
            self.assertEqual(caught.exception.details["provider_attempt_count"], 1)
            self.assertEqual(list(destination.iterdir()), [])
            self.assertEqual(
                [path.name for path in held_original.iterdir()],
                [banana_core.PUBLICATION_CAPABILITY_NAME],
            )
            self.assertTrue(all(capability.closed for capability in held_capabilities))
            for descriptor in held_descriptors:
                with self.assertRaises(OSError):
                    os.fstat(descriptor)

    def test_lite_execution_routes_to_generate_content(self) -> None:
        captured: dict[str, Any] = {}

        def opener(request: Any, **_kwargs: Any) -> FakeResponse:
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(generate_content_response())

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            plan = build_plan(
                operation="generate",
                prompt="fast draft",
                model="gemini-3.1-flash-lite-image",
                destination=directory,
            )
            approval = issue_approval(plan["request_fingerprint"], kind="single")
            result = execute_image(
                operation="generate",
                prompt="fast draft",
                model="gemini-3.1-flash-lite-image",
                approval_id=approval["approval_id"],
                destination=directory,
                api_key=AUTH_VALUE,
                opener=opener,
            )
        self.assertTrue(result["ok"])
        self.assertIn(":generateContent", captured["url"])
        self.assertIn("generationConfig", captured["body"])
        self.assertEqual(result["plan"]["api_surface"], "generate_content")

    def test_deprecated_2_5_execution_routes_to_generate_content(self) -> None:
        captured: dict[str, Any] = {}

        def opener(request: Any, **_kwargs: Any) -> FakeResponse:
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            response = generate_content_response()
            response["modelVersion"] = "gemini-2.5-flash-image"
            return FakeResponse(response)

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            plan = build_plan(
                operation="generate",
                prompt="compatibility draft",
                model="gemini-2.5-flash-image",
                destination=directory,
            )
            approval = issue_approval(plan["request_fingerprint"], kind="single")
            result = execute_image(
                operation="generate",
                prompt="compatibility draft",
                model="gemini-2.5-flash-image",
                approval_id=approval["approval_id"],
                destination=directory,
                api_key=AUTH_VALUE,
                opener=opener,
            )
        self.assertIn("gemini-2.5-flash-image:generateContent", captured["url"])
        self.assertNotIn(
            "imageSize", captured["body"]["generationConfig"]["responseFormat"]["image"]
        )
        self.assertEqual(result["plan"]["api_surface"], "generate_content")

    def test_changed_reference_invalidates_approval_before_network(self) -> None:
        calls: list[bool] = []

        def opener(_request: Any, **_kwargs: Any) -> FakeResponse:
            calls.append(True)
            return FakeResponse(completed_response())

        with tempfile.TemporaryDirectory() as directory, temporary_banana_home():
            image = Path(directory) / "source.png"
            output = Path(directory) / "output"
            image.write_bytes(PNG_1X1)
            reference = provider_reference(image)
            plan = build_plan(
                operation="edit",
                prompt="change only the color",
                reference_paths=[reference],
                destination=output,
                visual_brief=brief_for_reference(reference),
            )
            approval = issue_approval(plan["request_fingerprint"], kind="single")
            image.write_bytes(PNG_1X1 + b"changed")
            with self.assertRaises(BananaError) as caught:
                execute_image(
                    operation="edit",
                    prompt="change only the color",
                    reference_paths=[provider_reference(image)],
                    visual_brief=brief_for_reference(provider_reference(image)),
                    approval_id=approval["approval_id"],
                    destination=output,
                    api_key=AUTH_VALUE,
                    opener=opener,
                )
            self.assertEqual(caught.exception.code, "plan_mismatch")
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
