#!/usr/bin/env python3
"""Plan or execute one Gemini image generation interaction.

Planning is the default and performs no Google request. It issues a short-lived
single-use approval ID. Execution requires both --execute and that exact ID.
Credentials are read only from the environment.
"""

from __future__ import annotations

import argparse
import json
import sys

from banana_core import (
    BananaError,
    SecretSafeArgumentParser,
    build_plan,
    build_reference_specs,
    execute_image,
    issue_public_plan,
    load_visual_brief_file,
)


def build_parser() -> argparse.ArgumentParser:
    parser = SecretSafeArgumentParser(
        description="Plan or execute a Gemini image generation"
    )
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--model", default="gemini-3.1-flash-image")
    parser.add_argument("--aspect-ratio", default="1:1")
    parser.add_argument("--resolution", default="auto")
    parser.add_argument(
        "--reference",
        action="append",
        default=[],
        help="Reference image path, repeatable",
    )
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
    parser.add_argument(
        "--reference-purpose",
        action="append",
        default=[],
        help="Purpose aligned by reference order",
    )
    parser.add_argument(
        "--reference-subject-id",
        action="append",
        default=[],
        help="Subject label aligned by reference order",
    )
    parser.add_argument(
        "--video-url",
        help=(
            "HTTPS YouTube watch or short URL syntax, Flash Image only; "
            "existence, public status, and Google accessibility are user-asserted, "
            "not preflighted; an inaccessible URL can consume the one paid attempt"
        ),
    )
    parser.add_argument("--previous-interaction-id")
    parser.add_argument("--thinking", choices=["minimal", "high"])
    parser.add_argument("--web-search", action="store_true")
    parser.add_argument("--image-search", action="store_true")
    parser.add_argument(
        "--store",
        action="store_true",
        help="Allow provider-side storage for continuation",
    )
    parser.add_argument("--mime-type", choices=["image/jpeg"], default="image/jpeg")
    parser.add_argument("--output-dir")
    parser.add_argument("--brief-file", help="UTF-8 JSON banana.visual-brief.v1 file")
    parser.add_argument("--label", default="generation")
    parser.add_argument(
        "--record-prompt",
        action="store_true",
        help="Store raw prompt in the local metadata sidecar",
    )
    parser.add_argument(
        "--execute", action="store_true", help="Make the paid provider request"
    )
    parser.add_argument("--confirm", help="Single-use approval ID approved by the user")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    operation = "continue" if args.previous_interaction_id else "generate"
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
        plan = build_plan(
            operation=operation,
            prompt=args.prompt,
            model=args.model,
            aspect_ratio=args.aspect_ratio,
            image_size=args.resolution,
            reference_paths=references,
            video_url=args.video_url,
            previous_interaction_id=args.previous_interaction_id,
            thinking_level=args.thinking,
            web_search=args.web_search,
            image_search=args.image_search,
            store=args.store,
            mime_type=args.mime_type,
            destination=args.output_dir,
            label=args.label,
            record_prompt=args.record_prompt,
            visual_brief=visual_brief,
        )
        if not args.execute:
            print(
                json.dumps(
                    {"network_called": False, "plan": issue_public_plan(plan)}, indent=2
                )
            )
            return 0
        if not args.confirm:
            raise BananaError(
                "confirmation_required",
                "Execution requires --confirm with the single-use approval ID.",
            )

        result = execute_image(
            operation=operation,
            prompt=args.prompt,
            approval_id=args.confirm,
            model=args.model,
            aspect_ratio=args.aspect_ratio,
            image_size=args.resolution,
            reference_paths=references,
            video_url=args.video_url,
            previous_interaction_id=args.previous_interaction_id,
            thinking_level=args.thinking,
            web_search=args.web_search,
            image_search=args.image_search,
            store=args.store,
            mime_type=args.mime_type,
            destination=args.output_dir,
            label=args.label,
            record_prompt=args.record_prompt,
            visual_brief=visual_brief,
        )
        result.pop("image_contents", None)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except BananaError as exc:
        print(json.dumps(exc.as_dict()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
