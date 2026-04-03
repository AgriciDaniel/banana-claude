# Replicate Backend Reference -- google/nano-banana-2

> Alternative backend for image generation when MCP is unavailable or
> for users who prefer Replicate's simpler authentication.
>
> Model: `google/nano-banana-2` (Gemini 3.1 Flash Image on Replicate)

## Model Overview

Nano Banana 2 on Replicate provides **Pro-level visual quality with Flash-level speed and pricing**.

Key capabilities:
- **Text rendering** in multiple languages with high accuracy
- **Conversational editing** -- iterative refinement through natural dialogue
- **Multi-image fusion** -- blend up to 14 reference images in a single composition
- **Character consistency** -- maintain appearance of up to 5 people across images
- **Search grounding** -- Google Web Search + Image Search for real-time data
- **Resolutions** from 512px drafts to 4K production assets
- **Extreme aspect ratios** -- 1:4, 4:1, 1:8, 8:1 in addition to standard ratios

## When to Use Replicate

| Scenario | Recommended Backend |
|----------|-------------------|
| MCP server configured and working | MCP (primary) |
| MCP unavailable, have Replicate token | Replicate |
| MCP unavailable, have Google AI key | Direct Gemini API |
| Simpler auth needed (no Google Cloud) | Replicate |
| Need webhook/async processing | Replicate |

## Authentication

Set the `REPLICATE_API_TOKEN` environment variable:
```bash
export REPLICATE_API_TOKEN="r8_your_token_here"
```

Or store in `~/.banana/config.json`:
```json
{"replicate_api_token": "r8_your_token_here"}
```

Get a token at: https://replicate.com/account/api-tokens

## Input Parameters

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | Yes | — | Text description of the image |
| `image_input` | array | No | `[]` | Reference images (up to 14), as URLs or base64 data URIs |
| `aspect_ratio` | string | No | `match_input_image` | Aspect ratio (see below) |
| `resolution` | string | No | `2K` | `512`, `1K`, `2K`, or `4K` |
| `output_format` | string | No | `jpg` | `jpg` or `png` |
| `google_search` | boolean | No | `false` | Enable Google Web Search grounding |
| `image_search` | boolean | No | `false` | Enable Google Image Search grounding (auto-enables web search) |

## Supported Aspect Ratios

`1:1`, `2:3`, `3:2`, `3:4`, `4:3`, `4:5`, `5:4`, `9:16`, `16:9`, `21:9`, `1:4`, `4:1`, `1:8`, `8:1`, `match_input_image`

## Output

- **Type:** URL string pointing to the generated image
- **Expiration:** URLs expire after ~24 hours — download immediately
- **Watermark:** SynthID invisible watermark included on all outputs

## CLI Usage

**Generate:**
```bash
python3 scripts/replicate_generate.py --prompt "a sunset over mountains" --aspect-ratio "16:9" --resolution "2K"
```

**Edit:**
```bash
python3 scripts/replicate_edit.py --image path/to/photo.png --prompt "remove the background"
```

**With search grounding:**
```bash
python3 scripts/replicate_generate.py --prompt "current weather in Tokyo as an infographic" --google-search
```

## Pricing

Replicate uses per-second compute pricing. Check https://replicate.com/pricing for current rates.
Estimated ~$0.05 per image (varies by resolution and processing time).

## Error Handling

| Error | Cause | Resolution |
|-------|-------|-----------|
| HTTP 422 | Invalid input parameters | Check prompt, aspect ratio, resolution values |
| HTTP 401 | Invalid API token | Verify REPLICATE_API_TOKEN |
| HTTP 429 | Rate limited | Wait and retry with exponential backoff |
| Prediction `failed` | Model error or content filtered | Check error message, rephrase prompt |
| Prediction timeout | Model at capacity | Retry later or use direct Gemini API fallback |

## Differences from Direct Gemini API

| Feature | Replicate | Direct Gemini API |
|---------|-----------|-------------------|
| Auth | Bearer token (simple) | Google AI API key |
| Image output | URL (download needed) | Base64 inline |
| Search grounding | `google_search` boolean | `googleSearch` tool config |
| Aspect ratio default | `match_input_image` | `1:1` |
| Output format | `jpg` (default), `png`, `webp` | PNG only |
| `imageSize` param | `resolution` | `imageSize` (UPPERCASE required) |
