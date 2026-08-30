from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "banana" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZrXcAAAAASUVORK5CYII="
)
PNG_1X1_B64 = base64.b64encode(PNG_1X1).decode("ascii")
JPEG_1X1 = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q=="
)
JPEG_1X1_B64 = base64.b64encode(JPEG_1X1).decode("ascii")


class FakeResponse:
    def __init__(self, payload: dict[str, Any] | bytes) -> None:
        self.payload = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload).encode("utf-8")
        )

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.payload if size < 0 else self.payload[:size]


def completed_response(
    *, count: int = 1, mime_type: str = "image/jpeg"
) -> dict[str, Any]:
    image_data = JPEG_1X1_B64 if mime_type == "image/jpeg" else PNG_1X1_B64
    return {
        "id": "interaction-test",
        "model": "gemini-3.1-flash-image",
        "status": "completed",
        "steps": [
            {
                "type": "google_search_result",
                "search_suggestions": "<div>Google Search suggestion</div>",
            },
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "text",
                        "text": "Generated response text",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.test/source",
                            }
                        ],
                    },
                    *[
                        {"type": "image", "mime_type": mime_type, "data": image_data}
                        for _ in range(count)
                    ],
                ],
            },
        ],
        "usage": {"total_tokens": 42},
    }


def generate_content_response(
    *, count: int = 1, mime_type: str = "image/jpeg"
) -> dict[str, Any]:
    image_data = JPEG_1X1_B64 if mime_type == "image/jpeg" else PNG_1X1_B64
    return {
        "responseId": "response-test",
        "modelVersion": "gemini-3.1-flash-lite-image",
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "role": "model",
                    "parts": [
                        {"text": "Generated response text"},
                        *[
                            {"inlineData": {"mimeType": mime_type, "data": image_data}}
                            for _ in range(count)
                        ],
                    ],
                },
            }
        ],
        "usageMetadata": {"totalTokenCount": 42},
    }


@contextmanager
def temporary_banana_home() -> Iterator[Path]:
    previous_home = os.environ.get("BANANA_HOME")
    previous_output = os.environ.get("BANANA_OUTPUT_DIR")
    with tempfile.TemporaryDirectory() as directory:
        os.environ["BANANA_HOME"] = directory
        os.environ["BANANA_OUTPUT_DIR"] = str(Path(directory) / "output")
        try:
            yield Path(directory)
        finally:
            if previous_home is None:
                os.environ.pop("BANANA_HOME", None)
            else:
                os.environ["BANANA_HOME"] = previous_home
            if previous_output is None:
                os.environ.pop("BANANA_OUTPUT_DIR", None)
            else:
                os.environ["BANANA_OUTPUT_DIR"] = previous_output


def run_python(
    script: str, *arguments: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    process_env.pop("GEMINI_API_KEY", None)
    process_env.pop("GOOGLE_API_KEY", None)
    process_env.pop("GOOGLE_AI_API_KEY", None)
    if env:
        process_env.update(env)
    with tempfile.TemporaryDirectory() as directory:
        process_env.setdefault("BANANA_HOME", directory)
        if not env or "BANANA_OUTPUT_DIR" not in env:
            process_env["BANANA_OUTPUT_DIR"] = str(Path(directory) / "output")
        return subprocess.run(
            [sys.executable, str(SCRIPTS / script), *arguments],
            cwd=ROOT,
            env=process_env,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
