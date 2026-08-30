#!/usr/bin/env python3
"""Create a deterministic SVG exact-copy layer over a local raster image."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

from banana_core import (
    BananaError,
    SecretSafeArgumentParser,
    _atomic_write,
    _read_regular_file_bounded,
    image_dimensions,
    validate_approval_text,
    validate_reference_paths,
)

MAX_FONT_BYTES = 10 * 1024 * 1024
MAX_TEXT_FILE_BYTES = 1 * 1024 * 1024
MAX_LAYERS_FILE_BYTES = 5 * 1024 * 1024
MAX_LAYER_COUNT = 64
MAX_COMPOSITE_SOURCE_BYTES = 50 * 1024 * 1024
MAX_OUTPUT_PATH_LENGTH = 4_096
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?(?:[0-9a-fA-F]{2})?$")
FONT_MIME = {
    ".ttf": ("font/ttf", (b"\x00\x01\x00\x00", b"true")),
    ".otf": ("font/otf", (b"OTTO",)),
    ".woff": ("font/woff", (b"wOFF",)),
    ".woff2": ("font/woff2", (b"wOF2",)),
}


def _number(value: float) -> str:
    if not math.isfinite(value):
        raise BananaError("invalid_layer", "Derived layer geometry must remain finite.")
    rendered = f"{value:.6f}".rstrip("0").rstrip(".")
    return rendered or "0"


def _xml_text_is_valid(value: str) -> bool:
    return all(
        character in "\t\n\r"
        or 0x20 <= ord(character) <= 0xD7FF
        or 0xE000 <= ord(character) <= 0xFFFD
        or 0x10000 <= ord(character) <= 0x10FFFF
        for character in value
    )


def _output_path(image: Path, value: str | Path | None, *, suffix: str) -> Path:
    candidate = (
        str(value) if value is not None else str(image.with_name(image.stem + suffix))
    )
    checked = validate_approval_text(
        candidate,
        field="Typeset output path",
        max_length=MAX_OUTPUT_PATH_LENGTH,
    )
    return Path(os.path.abspath(Path(checked).expanduser()))


def _read_bounded_bytes(
    path: Path,
    *,
    max_bytes: int,
    error_code: str,
    label: str,
) -> bytes:
    return _read_regular_file_bounded(
        path,
        max_bytes=max_bytes,
        unreadable_code="typeset_io_error",
        oversized_code=error_code,
        label=label,
    )


def _font_face(font_path: str | Path | None) -> tuple[str, str, str | None, int]:
    if not font_path:
        return "", "", None, 0
    path = Path(font_path).expanduser().resolve()
    if not path.is_file():
        raise BananaError("font_not_found", f"Font file not found: {path}")
    details = FONT_MIME.get(path.suffix.lower())
    if not details:
        raise BananaError(
            "unsupported_font_type", "Font must be TTF, OTF, WOFF, or WOFF2."
        )
    raw = _read_bounded_bytes(
        path,
        max_bytes=MAX_FONT_BYTES,
        error_code="invalid_font_size",
        label="Embedded font",
    )
    if not raw or len(raw) > MAX_FONT_BYTES:
        raise BananaError(
            "invalid_font_size",
            f"Embedded font must be between 1 byte and {MAX_FONT_BYTES} bytes.",
        )
    mime_type, signatures = details
    if not raw.startswith(signatures):
        raise BananaError(
            "invalid_font_signature", "Font bytes do not match the declared file type."
        )
    encoded = base64.b64encode(raw).decode("ascii")
    digest = hashlib.sha256(raw).hexdigest()
    family = f"BananaEmbedded-{digest[:12]}"
    css = (
        f"@font-face{{font-family:'{family}';"
        f"src:url(data:{mime_type};base64,{encoded})"
        "}"
    )
    return css, family, digest, len(raw)


def render_svg(
    *,
    image_path: str | Path,
    text: str,
    x: float,
    y: float,
    font_size: float,
    font_family: str,
    font_weight: str,
    fill: str,
    anchor: str,
    line_height: float,
    font_path: str | Path | None = None,
) -> tuple[bytes, dict[str, Any]]:
    return render_composite_svg(
        image_path=image_path,
        layers=[
            {
                "type": "text",
                "text": text,
                "x": x,
                "y": y,
                "font_size": font_size,
                "font_family": font_family,
                "font_file": str(font_path) if font_path else None,
                "font_weight": font_weight,
                "fill": fill,
                "anchor": anchor,
                "line_height": line_height,
            }
        ],
    )


def _layer_number(
    layer: dict[str, Any],
    field: str,
    *,
    default: float | None = None,
    positive: bool = False,
) -> float:
    raw = layer.get(field, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise BananaError(
            "invalid_layer", f"Layer field '{field}' must be a finite number."
        )
    try:
        value = float(raw)
    except OverflowError as exc:
        raise BananaError(
            "invalid_layer", f"Layer field '{field}' must be a finite number."
        ) from exc
    if not math.isfinite(value):
        raise BananaError(
            "invalid_layer", f"Layer field '{field}' must be a finite number."
        )
    if positive and value <= 0:
        raise BananaError("invalid_layer", f"Layer field '{field}' must be positive.")
    return value


def _raster(path_value: str | Path) -> tuple[dict[str, Any], bytes, int, int]:
    reference = validate_reference_paths([path_value], 1)[0]
    path = Path(reference["path"])
    raw = _read_regular_file_bounded(
        path,
        max_bytes=int(reference["bytes"]),
        unreadable_code="reference_unreadable",
        oversized_code="reference_changed",
        label="Raster",
    )
    if (
        len(raw) != reference["bytes"]
        or hashlib.sha256(raw).hexdigest() != reference["sha256"]
    ):
        raise BananaError(
            "reference_changed",
            "A raster changed after validation. Retry from stable local files.",
        )
    width, height = image_dimensions(raw, reference["mime_type"])
    if width is None or height is None:
        raise BananaError(
            "dimensions_unavailable",
            "Raster dimensions could not be read. Use PNG, JPEG, GIF, or WebP.",
        )
    return reference, raw, width, height


def render_composite_svg(
    *,
    image_path: str | Path,
    layers: list[dict[str, Any]],
) -> tuple[bytes, dict[str, Any]]:
    """Render ordered exact-copy text and trusted raster asset layers."""
    if not isinstance(layers, list) or not layers or len(layers) > MAX_LAYER_COUNT:
        raise BananaError(
            "invalid_layers",
            f"Composite requires 1 to {MAX_LAYER_COUNT} ordered layers.",
        )

    background, background_raw, width, height = _raster(image_path)
    source_bytes = len(background_raw)
    background_data = base64.b64encode(background_raw).decode("ascii")
    elements: list[str] = []
    font_rules: dict[str, str] = {}
    font_hashes: list[str] = []
    asset_records: list[dict[str, Any]] = []
    text_layers = 0
    image_layers = 0
    line_count = 0

    for index, layer in enumerate(layers, start=1):
        if not isinstance(layer, dict):
            raise BananaError("invalid_layer", f"Layer {index} must be an object.")
        layer_type = layer.get("type")
        if layer_type == "text":
            allowed = {
                "type",
                "name",
                "text",
                "x",
                "y",
                "font_size",
                "font_family",
                "font_file",
                "font_weight",
                "fill",
                "anchor",
                "line_height",
                "letter_spacing",
                "opacity",
                "rotation",
            }
            unknown = sorted(set(layer) - allowed)
            if unknown:
                raise BananaError(
                    "invalid_layer",
                    f"Text layer {index} has unknown fields: {', '.join(unknown)}.",
                )
            text = layer.get("text")
            if not isinstance(text, str) or not text or len(text) > 20_000:
                raise BananaError(
                    "empty_text",
                    f"Text layer {index} requires 1 to 20000 exact characters.",
                )
            if not _xml_text_is_valid(text):
                raise BananaError(
                    "invalid_text",
                    f"Text layer {index} contains characters invalid in XML 1.0.",
                )
            x = _layer_number(layer, "x")
            y = _layer_number(layer, "y")
            font_size = _layer_number(layer, "font_size", positive=True)
            line_height = _layer_number(
                layer, "line_height", default=1.2, positive=True
            )
            letter_spacing = _layer_number(layer, "letter_spacing", default=0.0)
            opacity = _layer_number(layer, "opacity", default=1.0)
            rotation = _layer_number(layer, "rotation", default=0.0)
            if not 0 <= opacity <= 1:
                raise BananaError(
                    "invalid_layer",
                    f"Text layer {index} opacity must be between 0 and 1.",
                )
            anchor = layer.get("anchor", "start")
            if anchor not in {"start", "middle", "end"}:
                raise BananaError(
                    "invalid_anchor",
                    f"Text layer {index} anchor must be start, middle, or end.",
                )
            font_weight = str(layer.get("font_weight", "normal"))
            if font_weight not in {
                "normal",
                "bold",
                "100",
                "200",
                "300",
                "400",
                "500",
                "600",
                "700",
                "800",
                "900",
            }:
                raise BananaError(
                    "invalid_font_weight",
                    f"Text layer {index} has an unsupported font weight.",
                )
            fill = layer.get("fill", "#ffffff")
            if not isinstance(fill, str) or not HEX_COLOR.fullmatch(fill):
                raise BananaError(
                    "invalid_fill",
                    f"Text layer {index} fill must be a 3, 6, or 8 digit hex color.",
                )
            font_family = layer.get("font_family", "sans-serif")
            if (
                not isinstance(font_family, str)
                or len(font_family) > 200
                or not _xml_text_is_valid(font_family)
            ):
                raise BananaError(
                    "invalid_layer", f"Text layer {index} font_family is invalid."
                )
            font_rule, embedded_family, font_sha256, font_bytes = _font_face(
                layer.get("font_file")
            )
            source_bytes += font_bytes
            active_family = embedded_family or font_family.strip() or "sans-serif"
            if font_sha256 and font_rule:
                font_rules[font_sha256] = font_rule
                if font_sha256 not in font_hashes:
                    font_hashes.append(font_sha256)

            lines = text.split("\n")
            line_count += len(lines)
            tspans = []
            for line_index, line in enumerate(lines):
                dy = "0" if line_index == 0 else _number(font_size * line_height)
                tspans.append(
                    f'<tspan x="{_number(x)}" dy="{dy}">{html.escape(line)}</tspan>'
                )
            transform = (
                f' transform="rotate({_number(rotation)} {_number(x)} {_number(y)})"'
                if rotation
                else ""
            )
            elements.append(
                f'  <text x="{_number(x)}" y="{_number(y)}" fill="{fill}" '
                f'font-family="{html.escape(active_family, quote=True)}" font-size="{_number(font_size)}" '
                f'font-weight="{font_weight}" text-anchor="{anchor}" letter-spacing="{_number(letter_spacing)}" '
                f'opacity="{_number(opacity)}" xml:space="preserve"{transform}>{"".join(tspans)}</text>'
            )
            text_layers += 1
        elif layer_type == "image":
            allowed = {
                "type",
                "name",
                "path",
                "x",
                "y",
                "width",
                "height",
                "fit",
                "opacity",
                "rotation",
            }
            unknown = sorted(set(layer) - allowed)
            if unknown:
                raise BananaError(
                    "invalid_layer",
                    f"Image layer {index} has unknown fields: {', '.join(unknown)}.",
                )
            path_value = layer.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                raise BananaError(
                    "invalid_layer", f"Image layer {index} requires a raster path."
                )
            asset, asset_raw, asset_width, asset_height = _raster(path_value)
            source_bytes += len(asset_raw)
            x = _layer_number(layer, "x", default=0.0)
            y = _layer_number(layer, "y", default=0.0)
            layer_width = _layer_number(
                layer, "width", default=float(asset_width), positive=True
            )
            layer_height = _layer_number(
                layer, "height", default=float(asset_height), positive=True
            )
            opacity = _layer_number(layer, "opacity", default=1.0)
            rotation = _layer_number(layer, "rotation", default=0.0)
            if not 0 <= opacity <= 1:
                raise BananaError(
                    "invalid_layer",
                    f"Image layer {index} opacity must be between 0 and 1.",
                )
            fit = layer.get("fit", "contain")
            preserve = {
                "contain": "xMidYMid meet",
                "cover": "xMidYMid slice",
                "stretch": "none",
            }.get(str(fit))
            if preserve is None:
                raise BananaError(
                    "invalid_layer",
                    f"Image layer {index} fit must be contain, cover, or stretch.",
                )
            data = base64.b64encode(asset_raw).decode("ascii")
            center_x = x + layer_width / 2
            center_y = y + layer_height / 2
            transform = (
                f' transform="rotate({_number(rotation)} {_number(center_x)} {_number(center_y)})"'
                if rotation
                else ""
            )
            elements.append(
                f'  <image x="{_number(x)}" y="{_number(y)}" width="{_number(layer_width)}" '
                f'height="{_number(layer_height)}" opacity="{_number(opacity)}" '
                f'preserveAspectRatio="{preserve}" href="data:{asset["mime_type"]};base64,{data}"{transform}/>'
            )
            asset_records.append(
                {
                    "sha256": asset["sha256"],
                    "mime_type": asset["mime_type"],
                    "bytes": asset["bytes"],
                    "width": asset_width,
                    "height": asset_height,
                }
            )
            image_layers += 1
        else:
            raise BananaError(
                "invalid_layer_type", f"Layer {index} type must be text or image."
            )

        if source_bytes > MAX_COMPOSITE_SOURCE_BYTES:
            raise BananaError(
                "composite_too_large",
                f"Composite source assets exceed the {MAX_COMPOSITE_SOURCE_BYTES}-byte safety limit.",
            )

    defs = ""
    if font_rules:
        defs = (
            "  <defs><style>"
            + "".join(font_rules[key] for key in sorted(font_rules))
            + "</style></defs>\n"
        )
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        f"{defs}"
        f'  <image width="{width}" height="{height}" href="data:{background["mime_type"]};base64,{background_data}"/>\n'
        + "\n".join(elements)
        + "\n</svg>\n"
    )
    metadata = {
        "input_sha256": background["sha256"],
        "font_sha256": font_hashes[0] if len(font_hashes) == 1 else None,
        "font_sha256s": font_hashes,
        "width": width,
        "height": height,
        "layer_count": len(layers),
        "text_layer_count": text_layers,
        "image_layer_count": image_layers,
        "line_count": line_count,
        "assets": asset_records,
    }
    return svg.encode("utf-8"), metadata


def typeset_image(
    *,
    image_path: str | Path,
    text: str,
    x: float,
    y: float,
    font_size: float,
    output_path: str | Path | None = None,
    font_family: str = "sans-serif",
    font_path: str | Path | None = None,
    font_weight: str = "normal",
    fill: str = "#ffffff",
    anchor: str = "start",
    line_height: float = 1.2,
    force: bool = False,
) -> dict[str, Any]:
    image = Path(image_path).expanduser().resolve()
    output = _output_path(image, output_path, suffix="-typeset.svg")
    if output.suffix.lower() != ".svg":
        raise BananaError(
            "invalid_output_type",
            "Deterministic typesetting output must use the .svg suffix.",
        )
    if output.exists() and not force:
        raise BananaError(
            "output_exists",
            f"Output already exists: {output}. Choose a new path or explicitly replace it.",
        )
    svg, metadata = render_svg(
        image_path=image,
        text=text,
        x=x,
        y=y,
        font_size=font_size,
        font_family=font_family,
        font_path=font_path,
        font_weight=font_weight,
        fill=fill,
        anchor=anchor,
        line_height=line_height,
    )
    _atomic_write(output, svg, replace=force)
    return {
        "ok": True,
        "visual_review_status": "needs_review",
        "automated_visual_review_status": "blocked_pending_raster_preview",
        "raster_preview_required": True,
        "review_instruction": (
            "Render this SVG with a trusted viewer at its delivery dimensions, then inspect the PNG or JPEG "
            "preview together with the SVG. SVG source text is not pixel evidence."
        ),
        "path": str(output),
        "sha256": hashlib.sha256(svg).hexdigest(),
        **metadata,
    }


def compose_image(
    *,
    image_path: str | Path,
    layers: list[dict[str, Any]],
    output_path: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    image = Path(image_path).expanduser().resolve()
    output = _output_path(image, output_path, suffix="-composite.svg")
    if output.suffix.lower() != ".svg":
        raise BananaError(
            "invalid_output_type",
            "Deterministic composition output must use the .svg suffix.",
        )
    if output.exists() and not force:
        raise BananaError(
            "output_exists",
            f"Output already exists: {output}. Choose a new path or explicitly replace it.",
        )
    svg, metadata = render_composite_svg(image_path=image, layers=layers)
    _atomic_write(output, svg, replace=force)
    return {
        "ok": True,
        "visual_review_status": "needs_review",
        "automated_visual_review_status": "blocked_pending_raster_preview",
        "raster_preview_required": True,
        "review_instruction": (
            "Render this SVG with a trusted viewer at its delivery dimensions, then inspect the PNG or JPEG "
            "preview together with the SVG. SVG source text is not pixel evidence."
        ),
        "path": str(output),
        "sha256": hashlib.sha256(svg).hexdigest(),
        **metadata,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = SecretSafeArgumentParser(
        description="Compose exact text and trusted raster assets into a deterministic SVG"
    )
    parser.add_argument("--image", required=True)
    text_group = parser.add_mutually_exclusive_group(required=True)
    text_group.add_argument("--text")
    text_group.add_argument("--text-file")
    text_group.add_argument(
        "--layers-file", help="JSON file containing an ordered text/image layer array"
    )
    parser.add_argument("--output")
    parser.add_argument("--x", type=float)
    parser.add_argument("--y", type=float)
    parser.add_argument("--font-size", type=float)
    parser.add_argument("--font-family", default="sans-serif")
    parser.add_argument("--font-file")
    parser.add_argument("--font-weight", default="normal")
    parser.add_argument("--fill", default="#ffffff")
    parser.add_argument("--anchor", choices=["start", "middle", "end"], default="start")
    parser.add_argument("--line-height", type=float, default=1.2)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.layers_file:
            try:
                layers_path = Path(args.layers_file).expanduser().resolve()
                layers_raw = _read_bounded_bytes(
                    layers_path,
                    max_bytes=MAX_LAYERS_FILE_BYTES,
                    error_code="layers_file_too_large",
                    label="--layers-file",
                )
                layers_value = json.loads(layers_raw.decode("utf-8"))
            except (ValueError, RecursionError) as exc:
                raise BananaError(
                    "invalid_layers", f"--layers-file is not valid JSON: {exc}"
                ) from exc
            if not isinstance(layers_value, list):
                raise BananaError(
                    "invalid_layers", "--layers-file must contain a JSON array."
                )
            result = compose_image(
                image_path=args.image,
                layers=layers_value,
                output_path=args.output,
                force=args.force,
            )
        elif args.text_file:
            if args.x is None or args.y is None or args.font_size is None:
                raise BananaError(
                    "missing_typography",
                    "Text mode requires --x, --y, and --font-size.",
                )
            text_path = Path(args.text_file).expanduser().resolve()
            text = _read_bounded_bytes(
                text_path,
                max_bytes=MAX_TEXT_FILE_BYTES,
                error_code="text_file_too_large",
                label="--text-file",
            ).decode("utf-8")
            result = typeset_image(
                image_path=args.image,
                text=text,
                x=args.x,
                y=args.y,
                font_size=args.font_size,
                output_path=args.output,
                font_family=args.font_family,
                font_path=args.font_file,
                font_weight=args.font_weight,
                fill=args.fill,
                anchor=args.anchor,
                line_height=args.line_height,
                force=args.force,
            )
        else:
            if args.x is None or args.y is None or args.font_size is None:
                raise BananaError(
                    "missing_typography",
                    "Text mode requires --x, --y, and --font-size.",
                )
            text = args.text
            result = typeset_image(
                image_path=args.image,
                text=text,
                x=args.x,
                y=args.y,
                font_size=args.font_size,
                output_path=args.output,
                font_family=args.font_family,
                font_path=args.font_file,
                font_weight=args.font_weight,
                fill=args.fill,
                anchor=args.anchor,
                line_height=args.line_height,
                force=args.force,
            )
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, UnicodeError) as exc:
        error = BananaError(
            "typeset_io_error", f"Could not read or write typesetting input: {exc}"
        )
        print(json.dumps(error.as_dict()), file=sys.stderr)
        return 1
    except BananaError as exc:
        print(json.dumps(exc.as_dict()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
