# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.2] - 2026-03-27

### Added
- **Replicate backend** -- `google/nano-banana-2` as alternative to MCP and Direct Gemini API
  - `scripts/replicate_generate.py` -- stdlib-only generation script
  - `scripts/replicate_edit.py` -- stdlib-only editing script
  - `references/replicate.md` -- full reference doc with params, pricing, error handling
- **5-Input Creative Brief** system in SKILL.md (Purpose, Audience, Subject, Brand, References)
- **Edit-First principle** elevated to core principle with edit-vs-regenerate decision matrix
- **Three Prompt Variations** (Literal/Creative/Premium) for `/banana batch`
- **Quality Checklist** in response verification step
- **PEEL Strategy** for structured spec refinement (Position, Expression, Environment, Lens)
- **Progressive Enhancement** 4-phase workflow for `/banana chat` sessions
- **Multilingual & Localization** section in prompt-engineering.md
- **Expanded Character Consistency** (identity-locked patterns, group photos, storytelling)
- **5 new Common Pitfalls** (contradictory instructions, impossible physics, style mixing, etc.)
- **Expanded Search Grounding** with practical examples table
- **Resolution pixel dimension tables** for all aspect ratios at 512/1K/2K/4K
- **Input Limits section** in gemini-models.md (14 images, 7MB inline, 500MB total, HEIC/HEIF)
- **Watermark Behavior by Tier** table (SynthID, visible sparkle, C2PA)
- **Thinking Visibility** docs (`includeThoughts`, thought images)
- `setup_mcp.py` now supports `--replicate-key` and `--check-replicate`
- Replicate pricing in cost_tracker.py and cost-tracking.md

### Changed
- Prompt engineering approach: "Start with Intent, Refine with Specs" (PEEL strategy)
- Fallback chain: MCP → Direct Gemini API → Replicate
- Output tokens per image corrected to up to ~2,520 (was ~1,290)

### Fixed
- Free tier rate limits in cost-tracking.md corrected to ~5-15 RPM / ~20-500 RPD (was ~10 / ~500)

## [1.4.1] - 2026-03-27

### Changed
- Restructured as official Claude Code plugin (`.claude-plugin/plugin.json` manifest)
- Added marketplace catalog (`.claude-plugin/marketplace.json`) for distribution via `/plugin marketplace add`
- Moved `banana/` to `skills/banana/` (standard plugin layout)
- Moved `.claude/agents/` to `agents/` (standard plugin layout)
- Plugin install is now the primary installation method
- Updated CI workflow, README, CLAUDE.md, and install.sh for new structure

### Fixed
- Git remote URL corrected from `claude-banana` to `banana-claude`
- Removed `firebase-debug.log` from git tracking

## [1.4.0] - 2026-03-19

### Breaking Changes
- Removed `gemini-3-pro-image-preview` (Nano Banana Pro) -- shut down by Google March 9, 2026
- Replaced 6-component Reasoning Brief with Google's official 5-component formula (Subject → Action → Location/Context → Composition → Style)
- Default resolution changed from `1K` to `2K` in fallback scripts
- Banned prompt keywords: "8K", "masterpiece", "ultra-realistic", "high resolution" -- use prestigious context anchors instead

### Added
- Banned Keywords section in prompt-engineering.md (Stable Diffusion-era terms that degrade quality)
- Negative Prompts guidance (semantic reframing, ALL CAPS for constraints)
- Prompt Length Guide (20-60 words quick draft → 200-300 complex)
- Text Rendering section for Nano Banana 2
- Domain-to-model routing table in gemini-models.md
- Resolution defaults by domain mode
- Error response taxonomy in mcp-tools.md (429, 400 FAILED_PRECONDITION, IMAGE_SAFETY)
- Non-existent parameters warning in mcp-tools.md
- `.claude/agents/brief-constructor.md` subagent for prompt construction
- `CLAUDE.md` at repo root with development context and testing instructions
- Mandatory reference loading instruction at top of SKILL.md
- Full generation pipeline with retry logic and error handling in SKILL.md
- Exponential backoff retry logic (429 handling) in generate.py and edit.py
- FAILED_PRECONDITION billing error detection in fallback scripts
- Prestigious context anchors replacing banned quality keywords in all templates

### Changed
- SKILL.md version bumped to 1.4.0 with improved frontmatter
- gemini-models.md fully restructured with NB2/NB naming, updated pricing ($0.067/1K)
- Model routing table uses 5-component references instead of 6-component
- All prompt templates updated to use prestigious anchors instead of banned keywords
- Prompt adaptation rules updated to remove banned keywords

### Fixed
- gemini-3-pro-image-preview listed as "Active" when it was dead since March 9
- Pricing was stale ($0.039 for 3.1 Flash when actual is $0.067)
- Rate limits updated to reflect 92% cut (Free: ~5-15 RPM / ~20-500 RPD)

## [1.3.0] - 2026-03-14

### Added
- **Multi-model routing** -- task-based model selection table (draft/standard/quality/text-heavy/batch)
- **Cost tracking** -- `cost_tracker.py` with log, summary, today, estimate, and reset commands
- **Direct API fallback** -- `generate.py` and `edit.py` scripts for when MCP is unavailable (stdlib only)
- **Brand/style presets** -- `presets.py` for reusable brand identities (colors, style, typography, lighting, mood)
- **CSV batch workflow** -- `batch.py` parses CSV files into generation plans with cost estimates
- **Green screen transparency pipeline** -- workaround for Gemini's lack of transparent backgrounds
- **Safety filter rephrase strategies** -- 5 rephrase patterns, common trigger categories, example rephrases
- Cost tracking reference (`references/cost-tracking.md`) with pricing table and free tier limits
- Brand presets reference (`references/presets.md`) with schema, 3 example presets, merge behavior
- Abstract domain mode added to README
- Step 1.5 (Check for Presets) in Creative Director pipeline
- `/banana preset` and `/banana cost` commands in Quick Reference
- Expanded error handling for MCP unavailable and safety filter false positives

### Changed
- Quality Presets section replaced with Model Routing table
- Pro model status updated: may still be accessible for image generation
- Pricing note: research suggests NB2 pricing may be ~$0.067/img
- Architecture diagram updated to show all 7 scripts and 6 references
- install.sh creates `~/.banana/` directory for cost tracking and presets

### Removed
- Legacy `nano-banana/scripts/__pycache__/` (orphaned .pyc files)

## [1.2.0] - 2026-03-13

### Added
- 4K resolution output via `imageSize` parameter (512, 1K, 2K, 4K)
- 5 new aspect ratios: 2:3, 3:2, 4:5, 5:4, 21:9 (14 total)
- Thinking level control (minimal/low/medium/high)
- Search grounding with Google Search (web + image)
- Multi-image input support (up to 14 references)
- Image-only output mode
- Safety filter documentation with `finishReason` values
- Pricing table, content credentials section (SynthID + C2PA)
- Resolution selection step (Step 4.5) in pipeline
- Character consistency multi-image reference technique
- Cover image, pipeline diagram, reasoning brief diagram, domain modes diagram

### Changed
- Rate limits corrected: ~10 RPM / ~500 RPD (reduced Dec 2025)
- `NANOBANANA_MODEL` default: `gemini-3.1-flash-image-preview`
- Search grounding key: `googleSearch` (REST format)
- Quality presets now include resolution column

### Fixed
- SKILL.md markdown formatting bug on text-heavy template line
- Contradictory prompt engineering mistake #9 wording

## [1.0.0] - 2026-03-13

### Added
- Initial release of Banana Claude
- Creative Director pipeline with 6-component Reasoning Brief
- 8 domain modes, MCP integration, post-processing pipeline
- Batch variations, multi-turn chat, prompt inspiration
- Install script with validation

[1.4.2]: https://github.com/AgriciDaniel/banana-claude/releases/tag/v1.4.2
[1.4.1]: https://github.com/AgriciDaniel/banana-claude/releases/tag/v1.4.1
[1.4.0]: https://github.com/AgriciDaniel/banana-claude/releases/tag/v1.4.0
[1.3.0]: https://github.com/AgriciDaniel/banana-claude/releases/tag/v1.3.0
[1.2.0]: https://github.com/AgriciDaniel/banana-claude/releases/tag/v1.2.0
[1.0.0]: https://github.com/AgriciDaniel/banana-claude/releases/tag/v1.0.0
