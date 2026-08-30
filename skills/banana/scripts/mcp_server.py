#!/usr/bin/env python3
"""Bundled stdio MCP server for Banana Claude.

The server has no third-party runtime dependencies. It exposes separate plan
and execution tools so Claude can show a concrete costed plan before any paid
provider request.
"""

from __future__ import annotations

import json
import math
import sys
from typing import Any, BinaryIO

from banana_core import (
    BananaError,
    build_plan,
    enforce_json_nesting_limit,
    execute_image,
    issue_public_plan,
    load_catalog,
    validate_approval_text,
)
from portfolio import (
    build_portfolio_plan,
    execute_portfolio,
    issue_public_portfolio_plan,
)
from typeset import compose_image, typeset_image

SERVER_NAME = "banana-claude"
SERVER_VERSION = "3.0.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
LATEST_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = frozenset(
    {DEFAULT_PROTOCOL_VERSION, LATEST_PROTOCOL_VERSION}
)
MAX_CONTENT_LENGTH = 1_048_576
MAX_HEADER_LINE_LENGTH = 8_192
MAX_HEADER_LINES = 64
MAX_REQUEST_ID_LENGTH = 256
MAX_METHOD_NAME_LENGTH = 128
MAX_TOOL_NAME_LENGTH = 128
MAX_FINITE_FLOAT_INTEGER = int(sys.float_info.max)


REFERENCE_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "disclosure_alias": {
            "type": "string",
            "minLength": 1,
            "maxLength": 120,
        },
        "role": {"type": "string", "enum": ["object", "character", "style"]},
        "purpose": {"type": "string", "minLength": 1, "maxLength": 120},
        "subject_id": {"type": "string", "minLength": 1, "maxLength": 120},
    },
    "required": ["path", "disclosure_alias", "role", "purpose"],
    "additionalProperties": False,
}

REFERENCE_AUTHORITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rights_or_license": {
            "type": "string",
            "enum": ["affirmed", "not_applicable", "unresolved"],
        },
        "identity_or_likeness": {
            "type": "string",
            "enum": ["affirmed", "not_applicable", "unresolved"],
        },
        "customer_or_private_asset": {
            "type": "string",
            "enum": ["affirmed", "not_applicable", "unresolved"],
        },
        "endorsement_or_representation": {
            "type": "string",
            "enum": ["affirmed", "not_applicable", "unresolved"],
        },
        "provider_transmission": {
            "type": "string",
            "enum": ["affirmed", "unresolved"],
        },
        "intended_use": {"type": "string", "minLength": 1, "maxLength": 4096},
    },
    "required": [
        "rights_or_license",
        "identity_or_likeness",
        "customer_or_private_asset",
        "endorsement_or_representation",
        "provider_transmission",
        "intended_use",
    ],
    "additionalProperties": False,
}

VISUAL_BRIEF_REFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "disclosure_alias": {
            "type": "string",
            "minLength": 1,
            "maxLength": 120,
        },
        "role": {"type": "string", "enum": ["object", "character", "style"]},
        "purpose": {"type": "string", "minLength": 1, "maxLength": 120},
        "subject_id": {
            "oneOf": [
                {"type": "string", "minLength": 1, "maxLength": 120},
                {"const": None},
            ]
        },
        "authority": REFERENCE_AUTHORITY_SCHEMA,
    },
    "required": [
        "disclosure_alias",
        "role",
        "purpose",
        "subject_id",
        "authority",
    ],
    "additionalProperties": False,
}

VISUAL_BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "schema_version": {"const": "banana.visual-brief.v1"},
        "goal": {"type": "string", "minLength": 1, "maxLength": 4096},
        "facts": {
            "type": "array",
            "maxItems": 64,
            "items": {"type": "string", "minLength": 1, "maxLength": 4096},
        },
        "locks": {
            "type": "array",
            "maxItems": 64,
            "items": {"type": "string", "minLength": 1, "maxLength": 4096},
        },
        "freedoms": {
            "type": "array",
            "maxItems": 64,
            "items": {"type": "string", "minLength": 1, "maxLength": 4096},
        },
        "direction": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["creative", "preserve", "not_applicable"],
                },
                "thesis": {
                    "oneOf": [
                        {"type": "string", "minLength": 1, "maxLength": 4096},
                        {"const": None},
                    ]
                },
                "signature": {
                    "oneOf": [
                        {"type": "string", "minLength": 1, "maxLength": 4096},
                        {"const": None},
                    ]
                },
                "avoid": {
                    "oneOf": [
                        {"type": "string", "minLength": 1, "maxLength": 4096},
                        {"const": None},
                    ]
                },
            },
            "required": ["mode", "thesis", "signature", "avoid"],
            "additionalProperties": False,
        },
        "composition": {
            "type": "array",
            "maxItems": 64,
            "items": {"type": "string", "minLength": 1, "maxLength": 4096},
        },
        "rendering": {
            "type": "array",
            "maxItems": 64,
            "items": {"type": "string", "minLength": 1, "maxLength": 4096},
        },
        "typography": {
            "type": "object",
            "properties": {
                "exact_copy": {
                    "type": "array",
                    "maxItems": 64,
                    "items": {"type": "string", "minLength": 1, "maxLength": 4096},
                },
                "instructions": {
                    "type": "array",
                    "maxItems": 64,
                    "items": {"type": "string", "minLength": 1, "maxLength": 4096},
                },
            },
            "required": ["exact_copy", "instructions"],
            "additionalProperties": False,
        },
        "references": {
            "type": "array",
            "maxItems": 14,
            "items": VISUAL_BRIEF_REFERENCE_SCHEMA,
        },
        "output": {
            "type": "object",
            "properties": {
                "aspect_ratio": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 4096,
                },
                "image_size": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 4096,
                },
                "mime_type": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 4096,
                },
                "delivery_notes": {
                    "type": "array",
                    "maxItems": 64,
                    "items": {"type": "string", "minLength": 1, "maxLength": 4096},
                },
            },
            "required": [
                "aspect_ratio",
                "image_size",
                "mime_type",
                "delivery_notes",
            ],
            "additionalProperties": False,
        },
        "review_tests": {
            "type": "array",
            "minItems": 1,
            "maxItems": 64,
            "items": {"type": "string", "minLength": 1, "maxLength": 4096},
        },
    },
    "required": [
        "schema_version",
        "goal",
        "facts",
        "locks",
        "freedoms",
        "direction",
        "composition",
        "rendering",
        "typography",
        "references",
        "output",
        "review_tests",
    ],
    "additionalProperties": False,
}

TEXT_LAYER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {"const": "text"},
        "name": {"type": "string"},
        "text": {"type": "string", "minLength": 1, "maxLength": 20000},
        "x": {"type": "number"},
        "y": {"type": "number"},
        "font_size": {"type": "number", "exclusiveMinimum": 0},
        "font_family": {"type": "string", "default": "sans-serif"},
        "font_file": {"type": "string"},
        "font_weight": {"type": "string", "default": "normal"},
        "fill": {"type": "string", "default": "#ffffff"},
        "anchor": {
            "type": "string",
            "enum": ["start", "middle", "end"],
            "default": "start",
        },
        "line_height": {"type": "number", "exclusiveMinimum": 0, "default": 1.2},
        "letter_spacing": {"type": "number", "default": 0},
        "opacity": {"type": "number", "minimum": 0, "maximum": 1, "default": 1},
        "rotation": {"type": "number", "default": 0},
    },
    "required": ["type", "text", "x", "y", "font_size"],
    "additionalProperties": False,
}

IMAGE_LAYER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {"const": "image"},
        "name": {"type": "string"},
        "path": {"type": "string", "minLength": 1},
        "x": {"type": "number"},
        "y": {"type": "number"},
        "width": {"type": "number", "exclusiveMinimum": 0},
        "height": {"type": "number", "exclusiveMinimum": 0},
        "fit": {
            "type": "string",
            "enum": ["contain", "cover", "stretch"],
            "default": "contain",
        },
        "opacity": {"type": "number", "minimum": 0, "maximum": 1, "default": 1},
        "rotation": {"type": "number", "default": 0},
    },
    "required": ["type", "path", "x", "y", "width", "height"],
    "additionalProperties": False,
}


COMMON_PLAN_PROPERTIES: dict[str, Any] = {
    "prompt": {
        "type": "string",
        "minLength": 1,
        "description": "The frozen visual prompt. The user accepts the brief separately and later approves spend and data transfer.",
    },
    "model": {"type": "string", "description": "A model ID from banana_models."},
    "aspect_ratio": {"type": "string", "default": "1:1"},
    "image_size": {"type": "string", "default": "auto"},
    "references": {"type": "array", "items": REFERENCE_ITEM_SCHEMA, "default": []},
    "visual_brief": VISUAL_BRIEF_SCHEMA,
    "thinking_level": {"type": "string", "enum": ["minimal", "high"]},
    "web_search": {"type": "boolean", "default": False},
    "image_search": {"type": "boolean", "default": False},
    "store": {"type": "boolean", "default": False},
    "mime_type": {"type": "string", "enum": ["image/jpeg"], "default": "image/jpeg"},
    "output_dir": {"type": "string"},
    "label": {"type": "string", "default": "image"},
    "record_prompt": {
        "type": "boolean",
        "default": False,
        "description": "Store the raw prompt in the local metadata sidecar. This is off by default.",
    },
}


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def tool_definitions() -> list[dict[str, Any]]:
    execute_properties = {
        **COMMON_PLAN_PROPERTIES,
        "approval_id": {
            "type": "string",
            "description": "Single-use approval ID from the exact plan shown to and approved by the user.",
        },
        "video_url": {"type": "string"},
        "previous_interaction_id": {"type": "string"},
    }
    return [
        {
            "name": "banana_models",
            "description": "Return the checked-in Gemini image model catalog, capabilities, routes, pricing, and verification date. No network call.",
            "inputSchema": _schema({}, []),
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
            },
        },
        {
            "name": "banana_plan",
            "description": "Validate and cost one generation, edit, or continuation, then issue a 30-minute single-use local approval ID. This never calls Google. Show the returned plan to the user before execution.",
            "inputSchema": _schema(
                {
                    **COMMON_PLAN_PROPERTIES,
                    "operation": {
                        "type": "string",
                        "enum": ["generate", "edit", "continue"],
                        "default": "generate",
                    },
                    "video_url": {"type": "string"},
                    "previous_interaction_id": {"type": "string"},
                },
                ["prompt"],
            ),
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
            },
        },
        {
            "name": "banana_generate",
            "description": "Make one paid Gemini image generation or continuation attempt through the model's supported API surface. Use only after explicit approval of the exact banana_plan.",
            "inputSchema": _schema(execute_properties, ["prompt", "approval_id"]),
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": True,
            },
            "_meta": {"anthropic/requiresUserInteraction": True},
        },
        {
            "name": "banana_edit",
            "description": "Make one paid reference-image edit attempt. Use only after explicit approval of the exact banana_plan. References are required.",
            "inputSchema": _schema(
                execute_properties,
                ["prompt", "approval_id", "references", "visual_brief"],
            ),
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": True,
            },
            "_meta": {"anthropic/requiresUserInteraction": True},
        },
        {
            "name": "banana_portfolio_plan",
            "description": "Plan a bounded parallel comparison across up to three prompts and three Gemini image models, then issue one 30-minute single-use local approval ID. No Google network call.",
            "inputSchema": _schema(
                {
                    "prompts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 3,
                    },
                    "models": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 3,
                    },
                    "aspect_ratio": {"type": "string", "default": "1:1"},
                    "image_size": {"type": "string", "default": "auto"},
                    "references": {
                        "type": "array",
                        "items": REFERENCE_ITEM_SCHEMA,
                        "default": [],
                    },
                    "visual_brief": VISUAL_BRIEF_SCHEMA,
                    "output_dir": {"type": "string"},
                    "workers": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 3,
                        "default": 3,
                    },
                    "mime_type": {
                        "type": "string",
                        "enum": ["image/jpeg"],
                        "default": "image/jpeg",
                    },
                    "record_prompt": {"type": "boolean", "default": False},
                },
                ["prompts", "models", "visual_brief"],
            ),
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
            },
        },
        {
            "name": "banana_portfolio_generate",
            "description": "Execute a previously approved bounded portfolio in parallel. This can make up to nine paid Gemini requests.",
            "inputSchema": _schema(
                {
                    "prompts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 3,
                    },
                    "models": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 3,
                    },
                    "aspect_ratio": {"type": "string", "default": "1:1"},
                    "image_size": {"type": "string", "default": "auto"},
                    "references": {
                        "type": "array",
                        "items": REFERENCE_ITEM_SCHEMA,
                        "default": [],
                    },
                    "visual_brief": VISUAL_BRIEF_SCHEMA,
                    "approval_id": {"type": "string"},
                    "output_dir": {"type": "string"},
                    "workers": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 3,
                        "default": 3,
                    },
                    "mime_type": {
                        "type": "string",
                        "enum": ["image/jpeg"],
                        "default": "image/jpeg",
                    },
                    "record_prompt": {"type": "boolean", "default": False},
                },
                ["prompts", "models", "visual_brief", "approval_id"],
            ),
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": True,
            },
            "_meta": {"anthropic/requiresUserInteraction": True},
        },
        {
            "name": "banana_typeset",
            "description": "Create a local, self-contained deterministic SVG with one exact text block or ordered text and trusted raster logo/art layers. No Google call and no silent overwrite. A trusted PNG or JPEG render is required before automated visual review.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "image": {"type": "string"},
                    "text": {"type": "string", "minLength": 1},
                    "layers": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 64,
                        "items": {"oneOf": [TEXT_LAYER_SCHEMA, IMAGE_LAYER_SCHEMA]},
                    },
                    "output": {"type": "string"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "font_size": {"type": "number", "exclusiveMinimum": 0},
                    "font_family": {"type": "string", "default": "sans-serif"},
                    "font_file": {"type": "string"},
                    "font_weight": {"type": "string", "default": "normal"},
                    "fill": {"type": "string", "default": "#ffffff"},
                    "anchor": {
                        "type": "string",
                        "enum": ["start", "middle", "end"],
                        "default": "start",
                    },
                    "line_height": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "default": 1.2,
                    },
                },
                "required": ["image"],
                "oneOf": [
                    {"required": ["layers"]},
                    {"required": ["text", "x", "y", "font_size"]},
                ],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
            },
        },
    ]


def _text_result(value: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": json.dumps(value, indent=2, ensure_ascii=False)}
        ],
        "isError": is_error,
    }


def _execution_result(result: dict[str, Any]) -> dict[str, Any]:
    public_result = dict(result)
    attributed_images: list[tuple[dict[str, Any], dict[str, Any]]] = []
    if isinstance(public_result.get("results"), list):
        public_items: list[dict[str, Any]] = []
        for raw_item in public_result["results"]:
            item = dict(raw_item)
            image_contents = item.pop("image_contents", [])
            artifacts = item.get("artifacts", [])
            if len(image_contents) != len(artifacts):
                raise BananaError(
                    "mcp_image_attribution_mismatch",
                    "Returned images could not be matched to their saved artifacts.",
                )
            for output_index, (image, artifact) in enumerate(
                zip(image_contents, artifacts, strict=True), start=1
            ):
                attributed_images.append(
                    (
                        image,
                        {
                            "variant_id": item["variant_id"],
                            "model": item["plan"]["model"],
                            "provider_output_index": output_index,
                            "artifact_path": artifact["path"],
                            "artifact_sha256": artifact["sha256"],
                        },
                    )
                )
            public_items.append(item)
        public_result["results"] = public_items
    else:
        image_contents = public_result.pop("image_contents", [])
        artifacts = public_result.get("artifacts", [])
        if len(image_contents) != len(artifacts):
            raise BananaError(
                "mcp_image_attribution_mismatch",
                "Returned images could not be matched to their saved artifacts.",
            )
        for output_index, (image, artifact) in enumerate(
            zip(image_contents, artifacts, strict=True), start=1
        ):
            attributed_images.append(
                (
                    image,
                    {
                        "variant_id": "single",
                        "model": public_result["plan"]["model"],
                        "provider_output_index": output_index,
                        "artifact_path": artifact["path"],
                        "artifact_sha256": artifact["sha256"],
                    },
                )
            )
    content = [
        {
            "type": "text",
            "text": json.dumps(public_result, indent=2, ensure_ascii=False),
        }
    ]
    for image, attribution in attributed_images:
        content.append(
            {
                "type": "text",
                "text": json.dumps(
                    {"image_attribution": attribution},
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
            }
        )
        content.append(
            {"type": "image", "data": image["data"], "mimeType": image["mime_type"]}
        )
    return {"content": content, "isError": False}


def _schema_value_matches(value: Any, schema: dict[str, Any]) -> bool:
    if "const" in schema and value != schema["const"]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    required = schema.get("required")
    if required is not None:
        if (
            not isinstance(required, list)
            or not isinstance(value, dict)
            or any(field not in value for field in required)
        ):
            return False
    if "oneOf" in schema:
        alternatives = schema["oneOf"]
        if not isinstance(alternatives, list):
            return False
        if (
            sum(
                bool(isinstance(item, dict) and _schema_value_matches(value, item))
                for item in alternatives
            )
            != 1
        ):
            return False

    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            return False
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return False
        if schema.get("additionalProperties") is False and any(
            field not in properties for field in value
        ):
            return False
        return all(
            field not in properties
            or (
                isinstance(properties[field], dict)
                and _schema_value_matches(item, properties[field])
            )
            for field, item in value.items()
        )
    if expected_type == "array":
        if not isinstance(value, list):
            return False
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            return False
        if isinstance(maximum, int) and len(value) > maximum:
            return False
        item_schema = schema.get("items")
        return bool(
            item_schema is None
            or (
                isinstance(item_schema, dict)
                and all(_schema_value_matches(item, item_schema) for item in value)
            )
        )
    if expected_type == "string":
        return bool(
            isinstance(value, str)
            and (
                not isinstance(schema.get("minLength"), int)
                or len(value) >= schema["minLength"]
            )
            and (
                not isinstance(schema.get("maxLength"), int)
                or len(value) <= schema["maxLength"]
            )
        )
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return False
    elif expected_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        if isinstance(value, float) and not math.isfinite(value):
            return False
        if isinstance(value, int) and abs(value) > MAX_FINITE_FLOAT_INTEGER:
            return False
    elif expected_type is not None:
        return False

    if expected_type in {"integer", "number"}:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        exclusive_minimum = schema.get("exclusiveMinimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            return False
        if isinstance(maximum, (int, float)) and value > maximum:
            return False
        if isinstance(exclusive_minimum, (int, float)) and value <= exclusive_minimum:
            return False
    return True


def _validate_tool_arguments(name: str, arguments: dict[str, Any]) -> None:
    schema = next(
        (
            tool["inputSchema"]
            for tool in tool_definitions()
            if tool.get("name") == name
        ),
        None,
    )
    if not isinstance(schema, dict):
        raise BananaError("unknown_tool", "Unknown MCP tool name.")
    if not _schema_value_matches(arguments, schema):
        raise BananaError(
            "invalid_arguments",
            "Tool arguments do not match the declared input schema.",
        )


def _execute_single(arguments: dict[str, Any], operation: str) -> dict[str, Any]:
    references = arguments.get("references", [])
    previous_id = arguments.get("previous_interaction_id")
    actual_operation = (
        "continue" if previous_id and operation == "generate" else operation
    )
    result = execute_image(
        operation=actual_operation,
        prompt=arguments["prompt"],
        approval_id=arguments["approval_id"],
        model=arguments.get("model"),
        aspect_ratio=arguments.get("aspect_ratio", "1:1"),
        image_size=arguments.get("image_size", "auto"),
        reference_paths=references,
        video_url=arguments.get("video_url"),
        previous_interaction_id=previous_id,
        thinking_level=arguments.get("thinking_level"),
        web_search=bool(arguments.get("web_search", False)),
        image_search=bool(arguments.get("image_search", False)),
        store=bool(arguments.get("store", False)),
        mime_type=arguments.get("mime_type", "image/jpeg"),
        destination=arguments.get("output_dir"),
        label=arguments.get("label", "image"),
        record_prompt=bool(arguments.get("record_prompt", False)),
        visual_brief=arguments.get("visual_brief"),
    )
    return _execution_result(result)


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "banana_models":
        return _text_result(load_catalog())
    if name == "banana_plan":
        plan = build_plan(
            operation=arguments.get("operation", "generate"),
            prompt=arguments["prompt"],
            model=arguments.get("model"),
            aspect_ratio=arguments.get("aspect_ratio", "1:1"),
            image_size=arguments.get("image_size", "auto"),
            reference_paths=arguments.get("references", []),
            video_url=arguments.get("video_url"),
            previous_interaction_id=arguments.get("previous_interaction_id"),
            thinking_level=arguments.get("thinking_level"),
            web_search=bool(arguments.get("web_search", False)),
            image_search=bool(arguments.get("image_search", False)),
            store=bool(arguments.get("store", False)),
            mime_type=arguments.get("mime_type", "image/jpeg"),
            destination=arguments.get("output_dir"),
            label=arguments.get("label", "image"),
            record_prompt=bool(arguments.get("record_prompt", False)),
            visual_brief=arguments.get("visual_brief"),
        )
        return _text_result(issue_public_plan(plan))
    if name == "banana_generate":
        return _execute_single(arguments, "generate")
    if name == "banana_edit":
        return _execute_single(arguments, "edit")
    if name == "banana_portfolio_plan":
        portfolio = build_portfolio_plan(
            prompts=arguments["prompts"],
            models=arguments["models"],
            aspect_ratio=arguments.get("aspect_ratio", "1:1"),
            image_size=arguments.get("image_size", "auto"),
            reference_paths=arguments.get("references", []),
            destination=arguments.get("output_dir"),
            workers=int(arguments.get("workers", 3)),
            mime_type=arguments.get("mime_type", "image/jpeg"),
            record_prompt=bool(arguments.get("record_prompt", False)),
            visual_brief=arguments.get("visual_brief"),
        )
        return _text_result(issue_public_portfolio_plan(portfolio))
    if name == "banana_portfolio_generate":
        portfolio = build_portfolio_plan(
            prompts=arguments["prompts"],
            models=arguments["models"],
            aspect_ratio=arguments.get("aspect_ratio", "1:1"),
            image_size=arguments.get("image_size", "auto"),
            reference_paths=arguments.get("references", []),
            destination=arguments.get("output_dir"),
            workers=int(arguments.get("workers", 3)),
            mime_type=arguments.get("mime_type", "image/jpeg"),
            record_prompt=bool(arguments.get("record_prompt", False)),
            visual_brief=arguments.get("visual_brief"),
        )
        result = execute_portfolio(
            portfolio=portfolio,
            approval_id=arguments["approval_id"],
        )
        return _execution_result(result)
    if name == "banana_typeset":
        if "layers" in arguments:
            result = compose_image(
                image_path=arguments["image"],
                layers=arguments["layers"],
                output_path=arguments.get("output"),
            )
        else:
            result = typeset_image(
                image_path=arguments["image"],
                text=arguments["text"],
                output_path=arguments.get("output"),
                x=float(arguments["x"]),
                y=float(arguments["y"]),
                font_size=float(arguments["font_size"]),
                font_family=arguments.get("font_family", "sans-serif"),
                font_path=arguments.get("font_file"),
                font_weight=arguments.get("font_weight", "normal"),
                fill=arguments.get("fill", "#ffffff"),
                anchor=arguments.get("anchor", "start"),
                line_height=float(arguments.get("line_height", 1.2)),
            )
        return _text_result(result)
    raise BananaError("unknown_tool", "Unknown MCP tool name.")


class Transport:
    def __init__(self, input_stream: BinaryIO, output_stream: BinaryIO) -> None:
        self.input = input_stream
        self.output = output_stream
        self.framing = "newline"

    def read(self) -> dict[str, Any] | None:
        while True:
            first = self.input.readline(MAX_CONTENT_LENGTH + 2)
            if first == b"":
                return None
            if first in {b"\n", b"\r\n"}:
                continue
            break
        if first.lower().startswith(b"content-length:"):
            if len(first) > MAX_HEADER_LINE_LENGTH:
                if not first.endswith(b"\n"):
                    self._discard_line_remainder()
                raise self._fatal_transport("Content-Length header is too long.")
            value = first.split(b":", 1)[1].strip()
            if not value.isdigit():
                raise self._fatal_transport("Invalid Content-Length header.")
            length = int(value)
            if not 0 < length <= MAX_CONTENT_LENGTH:
                raise self._fatal_transport(
                    "Content-Length is outside the allowed range."
                )
            self.framing = "content-length"
            for _header_index in range(MAX_HEADER_LINES):
                header = self.input.readline(MAX_HEADER_LINE_LENGTH + 1)
                if header == b"":
                    raise self._fatal_transport(
                        "Content-Length message is missing its header terminator."
                    )
                if len(header) > MAX_HEADER_LINE_LENGTH:
                    if not header.endswith(b"\n"):
                        self._discard_line_remainder()
                    raise self._fatal_transport("Content-Length header is too long.")
                if header in {b"\n", b"\r\n"}:
                    break
            else:
                raise self._fatal_transport(
                    "Content-Length message has too many headers."
                )
            raw = self.input.read(length)
            if len(raw) != length:
                raise self._fatal_transport("Content-Length message is truncated.")
        else:
            if first.endswith(b"\r\n"):
                raw = first[:-2]
            elif first.endswith(b"\n"):
                raw = first[:-1]
            else:
                raw = first
            if len(raw) > MAX_CONTENT_LENGTH:
                if not first.endswith(b"\n"):
                    self._discard_line_remainder()
                raise BananaError(
                    "invalid_transport", "Newline message is outside the allowed range."
                )
            raw = raw.strip()
        try:
            enforce_json_nesting_limit(raw)
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise BananaError(
                "parse_error", "Received invalid JSON-RPC input."
            ) from exc
        if not isinstance(message, dict):
            raise BananaError("invalid_request", "JSON-RPC message must be an object.")
        return message

    def _discard_line_remainder(self) -> None:
        """Drain one rejected overlong line without retaining it in memory."""
        while True:
            chunk = self.input.readline(MAX_CONTENT_LENGTH + 2)
            if chunk == b"" or chunk.endswith(b"\n"):
                return

    @staticmethod
    def _fatal_transport(message: str) -> BananaError:
        return BananaError("invalid_transport", message, details={"fatal": True})

    def write(self, message: dict[str, Any]) -> None:
        raw = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
        if self.framing == "content-length":
            self.output.write(
                f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw
            )
        else:
            self.output.write(raw + b"\n")
        self.output.flush()


def _jsonrpc_error(
    request_id: Any, code: int, message: str, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _safe_protocol_string(value: Any, *, field: str, max_length: int) -> bool:
    if not isinstance(value, str):
        return False
    try:
        checked = validate_approval_text(value, field=field, max_length=max_length)
    except BananaError:
        return False
    return checked == value


def _valid_request_id(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, str):
        return _safe_protocol_string(
            value, field="JSON-RPC request ID", max_length=MAX_REQUEST_ID_LENGTH
        )
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _valid_method(value: Any) -> bool:
    return _safe_protocol_string(
        value, field="JSON-RPC method", max_length=MAX_METHOD_NAME_LENGTH
    )


class McpSession:
    """Enforce the MCP initialize/initialized lifecycle for one stdio peer."""

    def __init__(self) -> None:
        self.state = "new"

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        request_id = message.get("id")
        if (
            message.get("jsonrpc") != "2.0"
            or not _valid_method(message.get("method"))
            or ("id" in message and not _valid_request_id(request_id))
        ):
            return handle_message(message)

        method = message["method"]
        if method == "ping":
            return handle_message(message)

        if self.state == "new":
            if method == "initialize" and "id" in message:
                response = handle_message(message)
                if response is not None and "result" in response:
                    self.state = "awaiting_initialized"
                return response
            if "id" not in message:
                return None
            return _jsonrpc_error(request_id, -32002, "Server not initialized.")

        if self.state == "awaiting_initialized":
            if method == "notifications/initialized" and "id" not in message:
                params = message.get("params", {})
                if isinstance(params, dict):
                    self.state = "ready"
                return None
            if "id" not in message:
                return None
            return _jsonrpc_error(
                request_id, -32002, "Server initialization is incomplete."
            )

        if method == "initialize":
            if "id" not in message:
                return None
            return _jsonrpc_error(request_id, -32600, "Server is already initialized.")
        if method == "notifications/initialized":
            return None
        return handle_message(message)


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    if (
        message.get("jsonrpc") != "2.0"
        or not _valid_method(message.get("method"))
        or ("id" in message and not _valid_request_id(request_id))
    ):
        return _jsonrpc_error(
            request_id if _valid_request_id(request_id) else None,
            -32600,
            "Invalid Request.",
        )
    if "id" not in message:
        return None
    method = message["method"]
    params = message.get("params", {})
    if not isinstance(params, dict):
        return _jsonrpc_error(request_id, -32602, "Invalid params: expected an object.")
    if method == "initialize":
        requested = params.get("protocolVersion")
        if not isinstance(requested, str):
            return _jsonrpc_error(
                request_id,
                -32602,
                "Invalid initialize params: protocolVersion must be a string.",
            )
        negotiated = (
            requested
            if requested in SUPPORTED_PROTOCOL_VERSIONS
            else LATEST_PROTOCOL_VERSION
        )
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": tool_definitions()},
        }
    if method == "tools/call":
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return _jsonrpc_error(
                request_id, -32602, "Invalid tools/call arguments: expected an object."
            )
        tool_name = params.get("name")
        if not isinstance(tool_name, str) or not _safe_protocol_string(
            tool_name, field="MCP tool name", max_length=MAX_TOOL_NAME_LENGTH
        ):
            return _jsonrpc_error(
                request_id, -32602, "Invalid tools/call name: expected a safe string."
            )
        try:
            _validate_tool_arguments(tool_name, arguments)
            result = call_tool(tool_name, arguments)
        except BananaError as exc:
            result = _text_result(exc.as_dict(), is_error=True)
        except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
            result = _text_result(
                BananaError(
                    "invalid_arguments",
                    "Tool arguments could not be processed safely.",
                ).as_dict(),
                is_error=True,
            )
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    return _jsonrpc_error(request_id, -32601, "Method not found.")


def main() -> int:
    transport = Transport(sys.stdin.buffer, sys.stdout.buffer)
    session = McpSession()
    while True:
        try:
            message = transport.read()
            if message is None:
                return 0
            response = session.handle(message)
            if response is not None:
                transport.write(response)
        except BananaError as exc:
            code = -32700 if exc.code == "parse_error" else -32600
            transport.write(_jsonrpc_error(None, code, exc.message))
            if exc.code == "invalid_transport" and exc.details.get("fatal") is True:
                return 1
        except BrokenPipeError:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
