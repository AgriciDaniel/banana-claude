#!/usr/bin/env python3
"""Banana Claude -- Replicate API Fallback: Image Editing

Edit images via Replicate API using google/nano-banana-2.
Uses only Python stdlib (no pip dependencies).

Usage:
    replicate_edit.py --image path/to/image.png --prompt "remove the background"
                      [--aspect-ratio match_input_image] [--resolution 2K]
                      [--output-format png] [--api-key KEY]
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

MODEL = "google/nano-banana-2"
OUTPUT_DIR = Path.home() / "Documents" / "nanobanana_generated"
API_BASE = "https://api.replicate.com/v1/models"
POLL_TIMEOUT = 300  # seconds

VALID_RESOLUTIONS = {"512", "1K", "2K", "4K"}
VALID_OUTPUT_FORMATS = {"jpg", "png"}


def _load_config_key():
    """Try to load REPLICATE_API_TOKEN from ~/.banana/config.json."""
    config_path = Path.home() / ".banana" / "config.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                cfg = json.load(f)
            return cfg.get("REPLICATE_API_TOKEN") or cfg.get("replicate_api_token")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _api_request(url, api_key, data=None, method="GET"):
    """Make an authenticated request to the Replicate API."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def edit_image(image_path, prompt, aspect_ratio, resolution, output_format, api_key):
    """Call Replicate API to edit an image."""
    image_path = Path(image_path).resolve()
    if not image_path.exists():
        print(json.dumps({"error": True, "message": f"Image not found: {image_path}"}))
        sys.exit(1)

    # Read and encode image
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    # Determine MIME type
    suffix = image_path.suffix.lower()
    mime_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".webp": "image/webp"}
    mime_type = mime_types.get(suffix, "image/png")

    # Format as data URI
    data_uri = f"data:{mime_type};base64,{image_b64}"

    # POST to create prediction
    create_url = f"{API_BASE}/{MODEL}/predictions"
    body = {
        "input": {
            "prompt": prompt,
            "image_input": [data_uri],
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
        }
    }

    max_retries = 3
    prediction = None
    for attempt in range(max_retries):
        try:
            prediction = _api_request(create_url, api_key, data=body, method="POST")
            break
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            if e.code == 422:
                print(json.dumps({"error": True, "status": 422, "message": f"Invalid input: {error_body}"}))
                sys.exit(1)
            if e.code == 429 and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(json.dumps({"retry": True, "attempt": attempt + 1, "wait_seconds": wait, "reason": "rate_limited"}), file=sys.stderr)
                time.sleep(wait)
                continue
            print(json.dumps({"error": True, "status": e.code, "message": error_body}))
            sys.exit(1)
        except urllib.error.URLError as e:
            print(json.dumps({"error": True, "message": str(e.reason)}))
            sys.exit(1)

    if prediction is None:
        print(json.dumps({"error": True, "message": "Max retries exceeded creating prediction"}))
        sys.exit(1)

    # Poll until succeeded or failed
    poll_url = prediction.get("urls", {}).get("get")
    if not poll_url:
        # Fall back to constructing the URL from the prediction id
        pred_id = prediction.get("id")
        if not pred_id:
            print(json.dumps({"error": True, "message": "No prediction ID in response", "response": prediction}))
            sys.exit(1)
        poll_url = f"https://api.replicate.com/v1/predictions/{pred_id}"

    start_time = time.time()
    poll_interval = 1.0
    while True:
        elapsed = time.time() - start_time
        if elapsed > POLL_TIMEOUT:
            print(json.dumps({"error": True, "message": f"Prediction timed out after {POLL_TIMEOUT}s"}))
            sys.exit(1)

        try:
            status_resp = _api_request(poll_url, api_key, method="GET")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            print(json.dumps({"error": True, "status": e.code, "message": f"Poll failed: {error_body}"}))
            sys.exit(1)
        except urllib.error.URLError as e:
            print(json.dumps({"error": True, "message": f"Poll failed: {e.reason}"}))
            sys.exit(1)

        status = status_resp.get("status")

        if status == "succeeded":
            output = status_resp.get("output")
            break
        elif status == "failed":
            error_msg = status_resp.get("error", "Unknown error")
            print(json.dumps({"error": True, "message": f"Prediction failed: {error_msg}"}))
            sys.exit(1)
        elif status == "canceled":
            print(json.dumps({"error": True, "message": "Prediction was canceled"}))
            sys.exit(1)

        time.sleep(poll_interval)
        # Exponential backoff on polling, cap at 5s
        poll_interval = min(poll_interval * 1.5, 5.0)

    # Download the output image
    if not output:
        print(json.dumps({"error": True, "message": "No output in succeeded prediction"}))
        sys.exit(1)

    # Output can be a string URL or a list of URLs
    image_url = output[0] if isinstance(output, list) else output

    try:
        req = urllib.request.Request(image_url)
        with urllib.request.urlopen(req, timeout=60) as resp:
            image_bytes = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        print(json.dumps({"error": True, "message": f"Failed to download output image: {e}"}))
        sys.exit(1)

    # Save image
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    ext = output_format if output_format in {"png", "jpg", "webp"} else "png"
    filename = f"banana_edit_{timestamp}.{ext}"
    output_path = (OUTPUT_DIR / filename).resolve()

    with open(output_path, "wb") as f:
        f.write(image_bytes)

    return {
        "path": str(output_path),
        "model": MODEL,
        "source": str(image_path),
        "backend": "replicate",
    }


def main():
    parser = argparse.ArgumentParser(description="Edit images via Replicate API (google/nano-banana-2)")
    parser.add_argument("--image", required=True, help="Path to input image")
    parser.add_argument("--prompt", required=True, help="Edit instruction")
    parser.add_argument("--aspect-ratio", default="match_input_image", help="Aspect ratio (default: match_input_image)")
    parser.add_argument("--resolution", default="2K", help="Resolution: 1K, 2K, 4K (default: 2K)")
    parser.add_argument("--output-format", default="png", help="Output format: jpg, png, webp (default: png)")
    parser.add_argument("--api-key", default=None, help="Replicate API token (or set REPLICATE_API_TOKEN env)")

    args = parser.parse_args()

    if args.resolution not in VALID_RESOLUTIONS:
        print(json.dumps({"error": True, "message": f"Invalid resolution '{args.resolution}'. Valid: {sorted(VALID_RESOLUTIONS)}"}))
        sys.exit(1)

    if args.output_format not in VALID_OUTPUT_FORMATS:
        print(json.dumps({"error": True, "message": f"Invalid output format '{args.output_format}'. Valid: {sorted(VALID_OUTPUT_FORMATS)}"}))
        sys.exit(1)

    api_key = args.api_key or os.environ.get("REPLICATE_API_TOKEN") or _load_config_key()
    if not api_key:
        print(json.dumps({"error": True, "message": "No API key. Set REPLICATE_API_TOKEN env, pass --api-key, or add to ~/.banana/config.json"}))
        sys.exit(1)

    result = edit_image(
        image_path=args.image,
        prompt=args.prompt,
        aspect_ratio=args.aspect_ratio,
        resolution=args.resolution,
        output_format=args.output_format,
        api_key=api_key,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
