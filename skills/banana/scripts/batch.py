#!/usr/bin/env python3
"""Validate a CSV and produce a costed variation plan.

This utility does not submit a Gemini Batch API job and never calls a network.
Google's true Batch API is asynchronous and uses generateContent jobs.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any

from banana_core import (
    MAX_PROMPT_CHARS,
    BananaError,
    SecretSafeArgumentParser,
    _read_regular_file_bounded,
    estimate_image_cost,
    get_model,
    normalize_image_size,
    validate_approval_text,
    validate_aspect_ratio,
)

HARD_MAX_ROWS = 100
MAX_CSV_BYTES = 5 * 1024 * 1024


def build_parser() -> argparse.ArgumentParser:
    parser = SecretSafeArgumentParser(description="Validate a CSV image variation plan")
    parser.add_argument("--csv", required=True)
    parser.add_argument(
        "--max-count", type=int, default=20, help="Accepted row ceiling, maximum 100"
    )
    parser.add_argument(
        "--provider-batch",
        action="store_true",
        help="Estimate Google's asynchronous Batch pricing",
    )
    return parser


def plan_csv(path: Path, *, max_count: int, provider_batch: bool) -> dict[str, Any]:
    if max_count < 1 or max_count > HARD_MAX_ROWS:
        raise BananaError(
            "invalid_max_count", f"--max-count must be between 1 and {HARD_MAX_ROWS}."
        )
    if not path.is_file():
        raise BananaError("csv_not_found", f"CSV file not found: {path}")
    raw = _read_regular_file_bounded(
        path,
        max_bytes=MAX_CSV_BYTES,
        unreadable_code="csv_not_found",
        oversized_code="csv_too_large",
        label="CSV",
    )

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        text = raw.decode("utf-8-sig")
        with io.StringIO(text, newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or "prompt" not in reader.fieldnames:
                raise BananaError(
                    "missing_prompt_column", "CSV must contain a 'prompt' column."
                )
            for line_number, row in enumerate(reader, start=2):
                if len(rows) >= max_count:
                    errors.append(
                        f"Line {line_number}: row ceiling of {max_count} exceeded"
                    )
                    continue
                prompt = (row.get("prompt") or "").strip()
                model = (row.get("model") or "gemini-3.1-flash-image").strip()
                ratio = (row.get("ratio") or "1:1").strip()
                requested_size = (row.get("resolution") or "auto").strip()
                preset = (row.get("preset") or "").strip()
                if not prompt:
                    errors.append(f"Line {line_number}: missing prompt")
                    continue
                if preset:
                    errors.append(
                        f"Line {line_number}: presets require agent-side brief compilation before CSV planning"
                    )
                    continue
                try:
                    prompt = validate_approval_text(
                        prompt,
                        field=f"Line {line_number} prompt",
                        max_length=MAX_PROMPT_CHARS,
                        multiline=True,
                    )
                    selected, info = get_model(model)
                    size = normalize_image_size(requested_size, info)
                    ratio = validate_aspect_ratio(ratio, info)
                    cost = estimate_image_cost(selected, size, batch=provider_batch)
                except BananaError as exc:
                    errors.append(f"Line {line_number}: {exc.message}")
                    continue
                rows.append(
                    {
                        "line": line_number,
                        "prompt": prompt,
                        "model": selected,
                        "aspect_ratio": ratio,
                        "image_size": size,
                        "estimated_image_output_usd": cost,
                        "image_output_rate_usd": cost,
                        "estimate_basis": "nominal_one_output",
                    }
                )
    except (csv.Error, UnicodeDecodeError) as exc:
        raise BananaError("csv_parse_error", f"Could not parse CSV: {exc}") from exc

    if errors:
        raise BananaError("csv_validation_failed", "; ".join(errors[:20]))
    return {
        "network_called": False,
        "kind": "variation_plan",
        "provider_batch": provider_batch,
        "execution": "not_submitted",
        "rows": rows,
        "total_count": len(rows),
        "estimated_image_output_usd": round(
            sum(row["estimated_image_output_usd"] for row in rows), 4
        ),
        "estimate_basis": "nominal_one_output_per_planned_request",
        "estimate_is_invoice_cap": False,
        "output_count_uncertain": True,
        "estimate_excludes": [
            "input tokens",
            "text and thinking output",
            "Google Search queries",
        ],
    }


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = plan_csv(
            Path(args.csv).expanduser().resolve(),
            max_count=args.max_count,
            provider_batch=args.provider_batch,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except BananaError as exc:
        print(json.dumps(exc.as_dict()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
