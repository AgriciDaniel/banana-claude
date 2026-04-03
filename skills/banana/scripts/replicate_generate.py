#!/usr/bin/env python3
"""Banana Claude -- Replicate API Backend: Image Generation

Generate images via the Replicate API using google/nano-banana-2.
Uses only Python stdlib (no pip dependencies).

Usage:
    replicate_generate.py --prompt "a cat in space" [--aspect-ratio 16:9] [--resolution 2K]
                          [--output-format png] [--image-input img.png] [--api-key KEY]
                          [--google-search] [--image-search]
"""

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

MODEL = "google/nano-banana-2"
DEFAULT_RESOLUTION = "2K"
DEFAULT_RATIO = "1:1"
DEFAULT_FORMAT = "png"
OUTPUT_DIR = Path.home() / "Documents" / "nanobanana_generated"
API_BASE = "https://api.replicate.com/v1/models"
POLL_TIMEOUT = 300  # seconds

VALID_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2",
                "4:5", "5:4", "21:9", "1:4", "4:1", "1:8", "8:1",
                "match_input_image"}
VALID_RESOLUTIONS = {"512", "1K", "2K", "4K"}
VALID_FORMATS = {"jpg", "png"}
MAX_IMAGE_INPUTS = 14


def _load_config_token():
    """Try to read replicate_api_token from ~/.banana/config.json."""
    config_path = Path.home() / ".banana" / "config.json"
    if config_path.is_file():
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
            return data.get("replicate_api_token")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _resolve_api_key(cli_key):
    """Resolve API key: CLI arg > env var > config file."""
    if cli_key:
        return cli_key
    env_key = os.environ.get("REPLICATE_API_TOKEN")
    if env_key:
        return env_key
    return _load_config_token()


def _encode_image(path):
    """Read an image file and return a data URI string."""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        print(json.dumps({"error": True, "message": f"Image file not found: {path}"}))
        sys.exit(1)
    mime, _ = mimetypes.guess_type(str(p))
    if not mime or not mime.startswith("image/"):
        mime = "image/png"
    with open(p, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _api_request(url, api_key, method="GET", body=None):
    """Make an authenticated request to the Replicate API."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def create_prediction(prompt, aspect_ratio, resolution, output_format,
                      image_input_uris, google_search, image_search, api_key):
    """Create a prediction on Replicate and poll until complete."""
    url = f"{API_BASE}/{MODEL}/predictions"

    body = {
        "input": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
            "image_input": image_input_uris,
            "google_search": google_search,
            "image_search": image_search,
        }
    }

    # --- Submit prediction with retry logic ---
    max_retries = 3
    prediction = None
    for attempt in range(max_retries):
        try:
            prediction = _api_request(url, api_key, method="POST", body=body)
            break
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            if e.code == 429 and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(json.dumps({"retry": True, "attempt": attempt + 1, "wait_seconds": wait, "reason": "rate_limited"}), file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code == 422:
                print(json.dumps({"error": True, "status": 422, "message": f"Invalid input: {error_body}"}))
                sys.exit(1)
            print(json.dumps({"error": True, "status": e.code, "message": error_body}))
            sys.exit(1)
        except urllib.error.URLError as e:
            print(json.dumps({"error": True, "message": str(e.reason)}))
            sys.exit(1)

    if prediction is None:
        print(json.dumps({"error": True, "message": "Max retries exceeded"}))
        sys.exit(1)

    # --- Poll for completion ---
    poll_url = prediction.get("urls", {}).get("get")
    if not poll_url:
        print(json.dumps({"error": True, "message": "No polling URL in prediction response"}))
        sys.exit(1)

    start_time = time.time()
    while True:
        elapsed = time.time() - start_time
        if elapsed > POLL_TIMEOUT:
            print(json.dumps({"error": True, "message": f"Prediction timed out after {POLL_TIMEOUT} seconds"}))
            sys.exit(1)

        try:
            status_resp = _api_request(poll_url, api_key, method="GET")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            print(json.dumps({"error": True, "status": e.code, "message": f"Poll error: {error_body}"}))
            sys.exit(1)
        except urllib.error.URLError as e:
            print(json.dumps({"error": True, "message": f"Poll error: {e.reason}"}))
            sys.exit(1)

        status = status_resp.get("status")
        if status == "succeeded":
            return status_resp
        elif status == "failed":
            error_msg = status_resp.get("error", "Unknown error")
            print(json.dumps({"error": True, "message": f"Prediction failed: {error_msg}"}))
            sys.exit(1)
        elif status == "canceled":
            print(json.dumps({"error": True, "message": "Prediction was canceled"}))
            sys.exit(1)

        # Backoff: poll every 2 seconds
        time.sleep(2)


def download_image(image_url, output_format):
    """Download the generated image and save it locally."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    ext = output_format if output_format in VALID_FORMATS else "png"
    filename = f"banana_{timestamp}.{ext}"
    output_path = (OUTPUT_DIR / filename).resolve()

    req = urllib.request.Request(image_url)
    with urllib.request.urlopen(req, timeout=120) as resp:
        image_data = resp.read()

    with open(output_path, "wb") as f:
        f.write(image_data)

    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description="Generate images via Replicate API (google/nano-banana-2)")
    parser.add_argument("--prompt", required=True, help="Image generation prompt")
    parser.add_argument("--image-input", action="append", default=None,
                        help="Path to a reference image (can be repeated, max 14)")
    parser.add_argument("--aspect-ratio", default=DEFAULT_RATIO,
                        help=f"Aspect ratio (default: {DEFAULT_RATIO})")
    parser.add_argument("--resolution", default=DEFAULT_RESOLUTION,
                        help=f"Resolution: 1K, 2K, 4K (default: {DEFAULT_RESOLUTION})")
    parser.add_argument("--output-format", default=DEFAULT_FORMAT,
                        help=f"Output format: jpg, png, webp (default: {DEFAULT_FORMAT})")
    parser.add_argument("--google-search", action="store_true",
                        help="Enable Google Web Search grounding")
    parser.add_argument("--image-search", action="store_true",
                        help="Enable Google Image Search grounding")
    parser.add_argument("--api-key", default=None,
                        help="Replicate API token (or set REPLICATE_API_TOKEN env)")

    args = parser.parse_args()

    # Validate arguments
    if args.aspect_ratio not in VALID_RATIOS:
        print(json.dumps({"error": True, "message": f"Invalid aspect ratio '{args.aspect_ratio}'. Valid: {sorted(VALID_RATIOS)}"}))
        sys.exit(1)

    if args.resolution not in VALID_RESOLUTIONS:
        print(json.dumps({"error": True, "message": f"Invalid resolution '{args.resolution}'. Valid: {sorted(VALID_RESOLUTIONS)}"}))
        sys.exit(1)

    if args.output_format not in VALID_FORMATS:
        print(json.dumps({"error": True, "message": f"Invalid output format '{args.output_format}'. Valid: {sorted(VALID_FORMATS)}"}))
        sys.exit(1)

    image_inputs = args.image_input or []
    if len(image_inputs) > MAX_IMAGE_INPUTS:
        print(json.dumps({"error": True, "message": f"Too many image inputs ({len(image_inputs)}). Maximum is {MAX_IMAGE_INPUTS}."}))
        sys.exit(1)

    api_key = _resolve_api_key(args.api_key)
    if not api_key:
        print(json.dumps({"error": True, "message": "No API key. Set REPLICATE_API_TOKEN env or pass --api-key"}))
        sys.exit(1)

    # Encode reference images as data URIs
    image_input_uris = [_encode_image(p) for p in image_inputs]

    # Create prediction and wait for result
    result = create_prediction(
        prompt=args.prompt,
        aspect_ratio=args.aspect_ratio,
        resolution=args.resolution,
        output_format=args.output_format,
        image_input_uris=image_input_uris,
        google_search=args.google_search,
        image_search=args.image_search,
        api_key=api_key,
    )

    # Download generated image
    output_url = result.get("output")
    if not output_url or not isinstance(output_url, str):
        print(json.dumps({"error": True, "message": f"Unexpected output format: {output_url}"}))
        sys.exit(1)

    saved_path = download_image(output_url, args.output_format)

    # Print result JSON to stdout
    print(json.dumps({
        "path": saved_path,
        "model": MODEL,
        "aspect_ratio": args.aspect_ratio,
        "resolution": args.resolution,
        "backend": "replicate",
    }, indent=2))


if __name__ == "__main__":
    main()
