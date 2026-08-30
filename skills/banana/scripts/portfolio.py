#!/usr/bin/env python3
"""Plan and run a bounded multi-model image portfolio."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

from banana_core import (
    BananaError,
    OutputPublicationCapability,
    SecretSafeArgumentParser,
    build_plan,
    build_reference_specs,
    execute_validated_plan,
    get_model,
    load_catalog,
    load_visual_brief_file,
    output_directory,
    preflight_output_publication,
    provider_attempt_sha256,
    validate_output_mime_type,
)
from banana_core import (
    acquire_output_publication as acquire_output_publication,
)

MAX_MODELS = 3
MAX_PROMPTS = 3


def build_portfolio_plan(
    *,
    prompts: Iterable[str],
    models: Iterable[str],
    aspect_ratio: str = "1:1",
    image_size: str = "auto",
    reference_paths: Iterable[str | dict[str, Any]] = (),
    destination: str | Path | None = None,
    workers: int = 3,
    mime_type: str = "image/jpeg",
    record_prompt: bool = False,
    visual_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if visual_brief is None:
        raise BananaError(
            "structured_brief_required",
            "This request requires a supplied banana.visual-brief.v1 object before approval.",
            details={
                "provider_called": False,
                "structured_brief_required": True,
                "structured_brief_reasons": ["portfolio"],
            },
        )
    prompt_list = [value.strip() for value in prompts if value.strip()]
    model_list = list(dict.fromkeys(value.strip() for value in models if value.strip()))
    reference_list = list(reference_paths)
    if not isinstance(workers, int) or workers < 1 or workers > MAX_MODELS:
        raise BananaError(
            "invalid_worker_count",
            f"Portfolio workers must be between 1 and {MAX_MODELS}.",
        )
    checked_mime_type = validate_output_mime_type(mime_type)
    checked_destination = str(output_directory(destination))
    if not prompt_list or len(prompt_list) > MAX_PROMPTS:
        raise BananaError(
            "invalid_portfolio_prompts",
            f"Portfolio requires 1 to {MAX_PROMPTS} prompts.",
        )
    if not model_list or len(model_list) > MAX_MODELS:
        raise BananaError(
            "invalid_portfolio_models",
            f"Portfolio requires 1 to {MAX_MODELS} unique models.",
        )
    total = len(prompt_list) * len(model_list)
    limit = int(load_catalog()["portfolio_limit"])
    if total > limit:
        raise BananaError(
            "portfolio_too_large",
            f"Portfolio contains {total} requests, above the hard limit of {limit}.",
        )

    resolved_image_size = image_size
    if not image_size or image_size.lower() == "auto":
        common_sizes: set[str] | None = None
        for model in model_list:
            _, info = get_model(model)
            sizes = set(str(value) for value in info["image_sizes"])
            common_sizes = (
                sizes if common_sizes is None else common_sizes.intersection(sizes)
            )
        if not common_sizes:
            raise BananaError(
                "no_common_image_size",
                "Selected models do not share a comparable image size.",
            )
        resolved_image_size = "1K" if "1K" in common_sizes else sorted(common_sizes)[0]

    items: list[dict[str, Any]] = []
    shared_visual_brief = visual_brief
    shared_brief_source = "supplied"
    for prompt_index, prompt in enumerate(prompt_list, start=1):
        variant_id = f"variant-{prompt_index}"
        for model in model_list:
            plan = build_plan(
                operation="portfolio",
                prompt=prompt,
                model=model,
                aspect_ratio=aspect_ratio,
                image_size=resolved_image_size,
                reference_paths=reference_list,
                destination=checked_destination,
                label=f"portfolio-v{prompt_index}-{model}",
                mime_type=checked_mime_type,
                record_prompt=record_prompt,
                visual_brief=shared_visual_brief,
                _brief_source=shared_brief_source,
            )
            items.append(
                {
                    "variant": prompt_index,
                    "variant_id": variant_id,
                    "prompt": prompt,
                    "plan": plan,
                }
            )
    if items:
        shared_references = items[0]["plan"]["references"]
        if any(item["plan"]["references"] != shared_references for item in items[1:]):
            raise BananaError(
                "reference_changed_during_plan",
                "A shared reference changed while the portfolio was being planned. Create a new plan from stable files.",
            )
    fingerprints = [item["plan"]["request_fingerprint"] for item in items]
    brief_hashes = {item["plan"]["brief_sha256"] for item in items}
    if len(brief_hashes) != 1:
        raise BananaError(
            "visual_brief_mismatch",
            "Every portfolio item must share one frozen visual brief.",
        )
    portfolio_material = [*fingerprints, f"workers:{workers}"]
    request_fingerprint = hashlib.sha256(
        "|".join(portfolio_material).encode("ascii")
    ).hexdigest()[:24]
    return {
        "request_fingerprint": request_fingerprint,
        "network_called": False,
        "request_count": total,
        "model_count": len(model_list),
        "variant_count": len(prompt_list),
        "workers": workers,
        "max_concurrency": MAX_MODELS,
        "provider_attempt_count": total,
        "comparison_image_size": resolved_image_size,
        "output_directory": checked_destination,
        "output_mime_type": checked_mime_type,
        "record_prompt": bool(record_prompt),
        "brief_sha256": next(iter(brief_hashes)),
        "brief_source": shared_brief_source,
        "structured_brief_required": True,
        "structured_brief_reasons": ["portfolio"],
        "store": False,
        "estimated_image_output_usd": round(
            sum(item["plan"]["estimated_image_output_usd"] for item in items), 4
        ),
        "estimate_basis": "nominal_one_output",
        "estimate_is_invoice_cap": False,
        "output_count_uncertain": True,
        "estimate_excludes": [
            "input tokens",
            "text and thinking output",
            "Google Search queries",
        ],
        "items": items,
    }


def public_portfolio_plan(plan: dict[str, Any]) -> dict[str, Any]:
    public = {
        "request_fingerprint": plan["request_fingerprint"],
        "network_called": False,
        "request_count": plan["request_count"],
        "model_count": plan["model_count"],
        "variant_count": plan["variant_count"],
        "workers": plan["workers"],
        "max_concurrency": plan["max_concurrency"],
        "provider_attempt_count": plan["provider_attempt_count"],
        "comparison_image_size": plan["comparison_image_size"],
        "output_directory": plan["output_directory"],
        "output_mime_type": plan["output_mime_type"],
        "record_prompt": plan["record_prompt"],
        "brief_sha256": plan["brief_sha256"],
        "brief_source": plan["brief_source"],
        "structured_brief_required": plan["structured_brief_required"],
        "structured_brief_reasons": plan["structured_brief_reasons"],
        "store": plan["store"],
        "reference_count": plan["items"][0]["plan"]["reference_count"]
        if plan["items"]
        else 0,
        "reference_inputs": [
            {
                "disclosure_alias": reference["disclosure_alias"],
                "authority": reference["authority"],
                "mime_type": reference["mime_type"],
                "bytes": reference["bytes"],
                "sha256": reference["sha256"],
                "role": reference["role"],
                "purpose": reference["purpose"],
                "subject_id": reference["subject_id"],
            }
            for reference in (
                plan["items"][0]["plan"]["references"] if plan["items"] else []
            )
        ],
        "estimated_image_output_usd": plan["estimated_image_output_usd"],
        "estimate_basis": plan["estimate_basis"],
        "estimate_is_invoice_cap": plan["estimate_is_invoice_cap"],
        "output_count_uncertain": plan["output_count_uncertain"],
        "estimate_excludes": plan["estimate_excludes"],
        "variants": [
            {
                "variant": item["variant"],
                "variant_id": item["variant_id"],
                "prompt": item["prompt"],
                "prompt_sha256": item["plan"]["prompt_sha256"],
            }
            for item in plan["items"]
            if item["plan"]["model"] == plan["items"][0]["plan"]["model"]
        ]
        if plan["items"]
        else [],
        "items": [
            {
                "variant": item["variant"],
                "variant_id": item["variant_id"],
                "prompt": item["prompt"],
                "request_fingerprint": item["plan"]["request_fingerprint"],
                "model": item["plan"]["model"],
                "model_name": item["plan"]["model_name"],
                "api_surface": item["plan"]["api_surface"],
                "api_endpoint": item["plan"]["api_endpoint"],
                "catalog_verified_on": item["plan"]["catalog_verified_on"],
                "provider_response_format": item["plan"]["provider_response_format"],
                "aspect_ratio": item["plan"]["aspect_ratio"],
                "image_size": item["plan"]["image_size"],
                "store": item["plan"]["store"],
                "reference_count": item["plan"]["reference_count"],
                "image_output_rate_usd": item["plan"]["image_output_rate_usd"],
                "estimated_image_output_usd": item["plan"][
                    "estimated_image_output_usd"
                ],
                "estimate_basis": item["plan"]["estimate_basis"],
                "estimate_is_invoice_cap": item["plan"]["estimate_is_invoice_cap"],
                "output_count_uncertain": item["plan"]["output_count_uncertain"],
                "provider_attempt_count": item["plan"]["provider_attempt_count"],
                "thinking_behavior": item["plan"]["thinking_behavior"],
                "thinking_documentation_conflict": item["plan"][
                    "thinking_documentation_conflict"
                ],
                "thinking_documentation_note": item["plan"][
                    "thinking_documentation_note"
                ],
                "output_mime_documentation_conflict": item["plan"][
                    "output_mime_documentation_conflict"
                ],
                "output_mime_documentation_note": item["plan"][
                    "output_mime_documentation_note"
                ],
                "prompt_sha256": item["plan"]["prompt_sha256"],
                "brief_sha256": item["plan"]["brief_sha256"],
                "brief_source": item["plan"]["brief_source"],
            }
            for item in plan["items"]
        ],
    }
    public["approval_summary"] = {
        "prompts": [variant["prompt"] for variant in public["variants"]],
        "brief_sha256": plan["brief_sha256"],
        "brief_source": plan["brief_source"],
        "visual_brief": plan["items"][0]["plan"]["visual_brief"],
        "structured_brief_required": True,
        "structured_brief_reasons": ["portfolio"],
        "models": [item["model"] for item in public["items"]],
        "comparison_image_size": plan["comparison_image_size"],
        "output_mime_type": plan["output_mime_type"],
        "provider_attempt_count": plan["provider_attempt_count"],
        "estimated_image_output_usd": plan["estimated_image_output_usd"],
        "estimate_basis": plan["estimate_basis"],
        "estimate_is_invoice_cap": plan["estimate_is_invoice_cap"],
        "output_count_uncertain": plan["output_count_uncertain"],
        "store": plan["store"],
        "search_provider_retention_days": plan["items"][0]["plan"][
            "search_provider_retention_days"
        ],
        "search_provider_retention_mandatory": plan["items"][0]["plan"][
            "search_provider_retention_mandatory"
        ],
        "provider_storage_retention_default_days": plan["items"][0]["plan"][
            "provider_storage_retention_default_days"
        ],
        "provider_storage_retention_options_days": plan["items"][0]["plan"][
            "provider_storage_retention_options_days"
        ],
        "provider_storage_setting_inspectable": plan["items"][0]["plan"][
            "provider_storage_setting_inspectable"
        ],
        "provider_storage_warning": plan["items"][0]["plan"][
            "provider_storage_warning"
        ],
        "output_directory": plan["output_directory"],
        "references": [
            {
                "disclosure_alias": reference["disclosure_alias"],
                "authority": reference["authority"],
                "role": reference["role"],
                "purpose": reference["purpose"],
                "subject_id": reference["subject_id"],
            }
            for reference in public["reference_inputs"]
        ],
    }
    return public


def issue_public_portfolio_plan(plan: dict[str, Any]) -> dict[str, Any]:
    from approval_store import issue_approval

    preflight_output_publication(plan["output_directory"])
    public = public_portfolio_plan(plan)
    public.update(issue_approval(plan["request_fingerprint"], kind="portfolio"))
    return public


def execute_portfolio(
    *,
    portfolio: dict[str, Any],
    approval_id: str,
) -> dict[str, Any]:
    from approval_store import consume_approval

    capabilities: list[OutputPublicationCapability] = []
    try:
        for item in portfolio["items"]:
            capabilities.append(
                acquire_output_publication(item["plan"]["output_directory"])
            )
        attempt_digests = [
            provider_attempt_sha256(
                request_fingerprint=item["plan"]["request_fingerprint"],
                approval_id=approval_id,
                scope=(
                    f"portfolio:{portfolio['request_fingerprint']}:"
                    f"{index}:{item['variant_id']}:{item['plan']['model']}"
                ),
            )
            for index, item in enumerate(portfolio["items"])
        ]
        consume_approval(
            approval_id,
            portfolio["request_fingerprint"],
            kind="portfolio",
        )
        return _execute_portfolio_with_capabilities(
            portfolio,
            capabilities,
            attempt_digests,
        )
    finally:
        for capability in capabilities:
            capability.close()


def _execute_portfolio_with_capabilities(
    portfolio: dict[str, Any],
    capabilities: list[OutputPublicationCapability],
    attempt_digests: list[str],
) -> dict[str, Any]:
    worker_count = min(portfolio["workers"], portfolio["request_count"])
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    def run_item(
        item: dict[str, Any],
        publication_capability: OutputPublicationCapability,
        attempt_sha256: str,
    ) -> dict[str, Any]:
        plan = item["plan"]
        result = execute_validated_plan(
            plan=plan,
            prompt=item["prompt"],
            publication_capability=publication_capability,
            attempt_sha256=attempt_sha256,
        )
        result["variant"] = item["variant"]
        result["variant_id"] = item["variant_id"]
        return result

    with ThreadPoolExecutor(
        max_workers=worker_count, thread_name_prefix="banana-portfolio"
    ) as executor:
        future_map = {
            executor.submit(run_item, item, capability, attempt_sha256): item
            for item, capability, attempt_sha256 in zip(
                portfolio["items"],
                capabilities,
                attempt_digests,
                strict=True,
            )
        }
        for future in as_completed(future_map):
            item = future_map[future]
            try:
                results.append(future.result())
            except BananaError as exc:
                errors.append(
                    {
                        "variant": item["variant"],
                        "variant_id": item["variant_id"],
                        "model": item["plan"]["model"],
                        **exc.as_dict(),
                    }
                )
            except Exception:
                errors.append(
                    {
                        "variant": item["variant"],
                        "variant_id": item["variant_id"],
                        "model": item["plan"]["model"],
                        "error": True,
                        "code": "unexpected_error",
                        "message": "Unexpected portfolio worker failure.",
                        "retryable": False,
                    }
                )
    results.sort(key=lambda item: (item["variant"], item["plan"]["model"]))
    errors.sort(key=lambda item: (item["variant"], item["model"]))
    return {
        "ok": not errors,
        "transport_ok": not errors,
        "visual_review_status": "needs_review" if results else "not_available",
        "partial": bool(results and errors),
        "request_fingerprint": portfolio["request_fingerprint"],
        "results": results,
        "errors": errors,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = SecretSafeArgumentParser(
        description="Plan or execute a bounded multi-model portfolio"
    )
    parser.add_argument(
        "--prompt",
        action="append",
        required=True,
        help="Creative variant prompt, repeat up to three times",
    )
    parser.add_argument(
        "--model",
        action="append",
        required=True,
        help="Model route, repeat up to three times",
    )
    parser.add_argument("--aspect-ratio", default="1:1")
    parser.add_argument("--resolution", default="auto")
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument(
        "--reference-name",
        action="append",
        default=[],
        help="Non-sensitive disclosure alias aligned by reference order",
    )
    parser.add_argument(
        "--reference-role",
        action="append",
        choices=["object", "character", "style"],
        default=[],
    )
    parser.add_argument("--reference-purpose", action="append", default=[])
    parser.add_argument("--reference-subject-id", action="append", default=[])
    parser.add_argument("--output-dir")
    parser.add_argument("--brief-file", help="UTF-8 JSON banana.visual-brief.v1 file")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--mime-type", choices=["image/jpeg"], default="image/jpeg")
    parser.add_argument("--record-prompt", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--confirm", help="Single-use portfolio approval ID approved by the user"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        references = build_reference_specs(
            args.reference,
            names=args.reference_name,
            roles=args.reference_role,
            purposes=args.reference_purpose,
            subject_ids=args.reference_subject_id,
        )
        visual_brief = (
            load_visual_brief_file(args.brief_file) if args.brief_file else None
        )
        portfolio = build_portfolio_plan(
            prompts=args.prompt,
            models=args.model,
            aspect_ratio=args.aspect_ratio,
            image_size=args.resolution,
            reference_paths=references,
            destination=args.output_dir,
            workers=args.workers,
            mime_type=args.mime_type,
            record_prompt=args.record_prompt,
            visual_brief=visual_brief,
        )
        if not args.execute:
            print(json.dumps(issue_public_portfolio_plan(portfolio), indent=2))
            return 0
        if not args.confirm:
            raise BananaError(
                "confirmation_required",
                "Execution requires --confirm with the single-use portfolio approval ID.",
            )
        result = execute_portfolio(
            portfolio=portfolio,
            approval_id=args.confirm,
        )
        for item in result["results"]:
            item.pop("image_contents", None)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 2
    except BananaError as exc:
        print(json.dumps(exc.as_dict()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
