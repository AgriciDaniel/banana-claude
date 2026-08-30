# Banana Claude guide

Use this guide when you need more than the quick start in the
[README](../README.md). It covers installation, upgrades, everyday workflows,
and direct script use. The deeper provider and security contracts stay in the
focused references linked at the end.

## Requirements

- Claude Code 2.1.199 or newer
- Python 3.11 or newer, available as `python3`
- A Gemini API key for a billing-enabled Google AI project

Current Gemini image routes do not have a free API inference tier. Review the
plan and nominal estimate before every paid request. A nominal estimate is not
an invoice cap.

## Install the Claude Code plugin

Add the marketplace, install the plugin, then enable it when you are ready to
connect a paid Google service:

```text
/plugin marketplace add AgriciDaniel/banana-claude
/plugin install banana-claude@banana-claude-marketplace
/plugin enable banana-claude@banana-claude-marketplace
/reload-plugins
```

Claude Code asks for `google_ai_api_key`. The plugin marks this value as
sensitive and passes it only to the bundled MCP process. Do not paste the key
into chat, an issue, or a command.

Start with a plain-language request:

```text
/banana-claude:banana generate a restrained 16:9 hero image for a ceramics studio
```

Banana Claude first returns a plan with the exact prompt, model, reference
aliases, data settings, output destination, and nominal image estimate. Review
that plan before approving the paid request.

Before production use, configure the experimental monthly spend cap for the
Google project in [AI Studio](https://ai.google.dev/gemini-api/docs/billing#spend-caps).
Google documents enforcement latency and possible overages, so this complements
the per-request approval instead of replacing it.

## Local plugin development

```bash
git clone https://github.com/AgriciDaniel/banana-claude.git
cd banana-claude
claude --plugin-dir .
```

Use `/reload-plugins` after changing plugin files.

## Standalone compatibility skill

The standalone install provides `/banana` and the direct planning scripts. It
does not provide the plugin-managed MCP server, specialist agents, or sensitive
key configuration.

```bash
git clone https://github.com/AgriciDaniel/banana-claude.git
cd banana-claude
./install.sh
```

Inspect the installer before running it. It refuses to overwrite an unowned
skill, backs up a previous managed install, and moves an uninstall to a
recoverable directory.

Standalone paid execution reads only `GEMINI_API_KEY`. Configure it through your
normal secret manager. Banana Claude deliberately ignores generic Google key
aliases so an ambient credential cannot silently select another project or
billing account.

## Upgrade from 1.4.1 or 2.1.0

Public 1.4.1 and 2.1.0 installs may have left an unpinned third-party MCP entry,
a raw Google key in Claude settings, an obsolete skill directory, or a
key-bearing shell command. Installing version 3 does not remove that residue.

Use a version 3 checkout to review the old footprint before enabling the new
plugin.

1. Run the redacted, read-only scan:

   ```bash
   python3 skills/banana/scripts/legacy_cleanup.py scan --json
   ```

2. If cleanup is needed, preview the exact proposal and review its fingerprint.
   Confirm only that unchanged fingerprint:

   ```bash
   python3 skills/banana/scripts/legacy_cleanup.py remediate --dry-run --json
   python3 skills/banana/scripts/legacy_cleanup.py remediate \
     --confirm FINGERPRINT_FROM_DRY_RUN --json
   ```

3. If the scan reports a stored credential, revoke or rotate it in
   [Google AI Studio](https://aistudio.google.com/apikey). Deleting a settings
   entry cannot retract a key that was previously stored, logged, or copied to
   a backup. Keep private backups private.

4. Install version 3, then run the read-only doctor from the checkout or the
   installed skill directory:

   ```bash
   python3 skills/banana/scripts/doctor.py --json
   ```

5. If an old cost ledger is present, preview and confirm its exact migration:

   ```bash
   python3 skills/banana/scripts/cost_tracker.py migrate-v1 --dry-run
   python3 skills/banana/scripts/cost_tracker.py migrate-v1 \
     --confirm FINGERPRINT_FROM_DRY_RUN
   ```

6. Repeat the same dry-run and confirmation for each old preset:

   ```bash
   python3 skills/banana/scripts/presets.py migrate-v1 quiet-precision --dry-run
   python3 skills/banana/scripts/presets.py migrate-v1 quiet-precision \
     --confirm FINGERPRINT_FROM_DRY_RUN
   ```

These scans, cleanup steps, and migrations are local. They do not call Google.
Retain the reported backups until the doctor, migrated state, and one normal
offline planning flow have been reviewed.

## Everyday workflows

### Generate

```text
/banana-claude:banana generate a product launch visual with exact left-side copy space
```

Banana Claude turns the request into a compact visual brief, then compiles only
the fields needed for the approved provider prompt.

### Edit while preserving the source

```text
/banana-claude:banana edit /path/to/source.png change only the jacket to rust orange
```

The edit plan names the exact change and what must stay untouched. If identity
or geometry drifts, restart from the original instead of editing the failed
output again.

### Compare model routes

```text
/banana-claude:banana portfolio compare a direct direction and one justified risk on Flash and Pro
```

A portfolio can compare up to three prompts across three routes. It is capped at
nine provider requests and three concurrent attempts. The complete plan and
aggregate nominal estimate appear before execution.

### Continue an image

Flash and Pro can continue a stored provider interaction after the storage and
retention choice is accepted. One-shot Interactions requests send `store: false`.
Lite and the deprecated compatibility route iterate by attaching the accepted
output as a new reference.

Read the current retention details in
[cost planning](../skills/banana/references/cost-tracking.md#storage-and-retention-disclosure).

### Review the pixels

Every result should be checked for required content, copy, composition, crop,
identity, product geometry, brand locks, artifacts, rights, and provenance. The
workflow returns one of four honest outcomes: Pass, Targeted fix, Regenerate, or
Blocked.

Use the full [visual review and recovery checklist](../skills/banana/references/review-and-recovery.md)
for production work.

### Add exact copy locally

For legal copy, logos, approved fonts, or dense layouts, generate the visual
field first and add exact text or trusted raster assets with the deterministic
SVG compositor. This guarantees the characters in the vector layer, not the
pixels produced by an unknown renderer.

See [post-processing](../skills/banana/references/post-processing.md#exact-copy-composition)
for the complete typesetting and delivery workflow.

## Direct script workflow

Direct paid scripts are plan-first. A simple one-shot request can be planned
without a separate brief file:

```bash
python3 skills/banana/scripts/generate.py \
  --prompt "A quiet editorial still life" \
  --model gemini-3.1-flash-image \
  --aspect-ratio 16:9 \
  --resolution 1K
```

The command prints the approval summary, full plan, request fingerprint, and a
30-minute single-use approval ID without calling Google. After reviewing that
exact plan, repeat the same command with:

```text
--execute --confirm APPROVAL_ID_FROM_THE_PREVIOUS_COMMAND
```

Editing, references, Search, video, stored continuation, and portfolios require
an accepted `banana.visual-brief.v1` JSON file. Read the
[visual brief contract](../skills/banana/references/prompt-engineering.md#versioned-contract)
and [MCP tool reference](../skills/banana/references/mcp-tools.md) before using
those surfaces directly.

No script accepts an API key argument. The key is sent in a request header,
never in the request URL.

## Pick a route

| Route | Use it for |
|---|---|
| Nano Banana 2 Lite | Fast, lower-cost 1K drafts and high-volume work |
| Nano Banana 2 | General generation, editing, continuation, grounding, and video-derived work |
| Nano Banana Pro | Complex instructions, text, localization, brand precision, and final assets |

There is also one deprecated compatibility route for existing work. Model
status, features, pricing, and provider behavior can change. Check the dated
[Gemini model reference](../skills/banana/references/gemini-models.md) before a
release, procurement decision, or durable budget commitment.

## Know the limits

- Gemini output is probabilistic. Consistency, spelling, geometry, policy
  acceptance, rights, and production fitness still need human review.
- A Banana Claude estimate covers the named image-output assumption. It is not
  a complete invoice or a hard provider spending cap.
- Stored continuation and Search grounding have provider retention conditions.
  Read the disclosed plan before approval.
- Paid provider calls and pixel acceptance never run in public CI.

## Go deeper

- [Security and privacy](../SECURITY.md)
- [Current Gemini models](../skills/banana/references/gemini-models.md)
- [Visual brief and prompt craft](../skills/banana/references/prompt-engineering.md)
- [MCP tools](../skills/banana/references/mcp-tools.md)
- [Cost planning](../skills/banana/references/cost-tracking.md)
- [Visual review and recovery](../skills/banana/references/review-and-recovery.md)
- [Contributing](../CONTRIBUTING.md)
