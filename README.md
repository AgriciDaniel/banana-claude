<p align="center">
  <img
    src="screenshots/banana-claude-character-loop.gif"
    alt="Banana Claude character cycling through thirty artistic urban looks while the Banana Claude title and pixel banana remain fixed"
    width="960"
  >
</p>

<h1 align="center">Banana Claude</h1>

<p align="center">
  <strong>Plan, generate, edit, compare, and review Gemini images from Claude Code.</strong>
</p>

<p align="center">
  <a href="https://github.com/AgriciDaniel/banana-claude/actions/workflows/validate.yml"><img alt="Validation" src="https://github.com/AgriciDaniel/banana-claude/actions/workflows/validate.yml/badge.svg"></a>
  <a href="https://github.com/AgriciDaniel/banana-claude/releases/latest"><img alt="Version 3.0.0" src="https://img.shields.io/badge/version-3.0.0-ff7b6b"></a>
  <a href="https://code.claude.com/docs/en/plugins"><img alt="Claude Code plugin" src="https://img.shields.io/badge/Claude%20Code-plugin-d97757"></a>
  <img alt="Python 3.11 or newer" src="https://img.shields.io/badge/Python-3.11%2B-3776ab">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/License-MIT-f4c542"></a>
</p>

Banana Claude is an open-source Claude Code plugin and standalone skill for AI
image generation, editing, visual QA, and bounded multi-model orchestration. It
turns one creative request into a frozen visual brief, an offline cost and
permission plan, an explicitly approved Gemini API call, and a review of the
actual returned pixels.

It routes across Nano Banana 2 Lite, Nano Banana 2, and Nano Banana Pro through
their current Google API surfaces. Every successful provider response is saved
as an image plus a privacy-conscious metadata sidecar. Paid calls never run from
public CI and never happen before the exact plan is shown for approval.

## Start in 60 seconds

Requirements: Claude Code 2.1.199 or newer, Python 3.11 or newer with `python3`
on `PATH`, and a Gemini API key for a billing-enabled Google AI project.

```text
/plugin marketplace add AgriciDaniel/banana-claude
/plugin install banana-claude@banana-claude-marketplace
/plugin enable banana-claude@banana-claude-marketplace
/reload-plugins
```

Then ask for the outcome you want:

```text
/banana-claude:banana generate an urban 16:9 GitHub hero with exact left-side copy space
```

Banana plans offline first. You see the compiled prompt, model, endpoint,
references, data settings, output destination, and nominal estimate before any
paid request. Read the full [installation](#installation),
[upgrade](#upgrade-from-public-141-or-210-installs), and
[security and privacy](#security-and-privacy) sections before production use.

## What you can make

| Workflow | What Banana Claude adds |
|---|---|
| Generate | Brief-led generation with explicit composition, copy, locks, freedom, output, and review tests |
| Edit | A precise delta plus preservation rules, with recovery from the original when an edit drifts |
| Portfolio | Up to three prompts across three model routes, capped at nine paid calls and three concurrent requests |
| Continue | Stored Flash or Pro sessions with retention disclosure, or reference-based iteration without stored state |
| Review | Pixel-level checks for content, crop, identity, geometry, typography, brand locks, artifacts, rights, and provenance |
| Typeset | Deterministic exact-copy text and trusted raster asset composition when generated lettering is not reliable enough |

## Why version 3

- Bundles its own zero-dependency Python MCP server instead of invoking an
  unpinned third-party package.
- Uses Google's current Interactions and generateContent schemas, stable image
  model IDs, and one clearly marked deprecated compatibility route.
- Separates creative direction, immutable locks, approval, execution, visual
  review, and recovery.
- Supports declared reference roles, Flash and Pro continuation, Google Search
  grounding, and Flash video-to-image from strictly validated YouTube URL
  shapes.
- Binds a canonical `banana.visual-brief.v1` digest into 30-minute, single-use
  approvals, makes one provider attempt per approval, and records private,
  concurrency-safe estimates without raw prompts by default.
- Includes deterministic offline coverage for validation, API parsing, secret
  boundaries, atomic output writes, concurrency, migrations, presets,
  installation, and repository contracts.

Gemini output is probabilistic. Banana Claude does not guarantee consistency,
spelling, geometry, policy acceptance, or rights clearance. Those remain review
conditions, not marketing claims.

## Current model routes

Verified 2026-08-29 against [Google's image generation guide](https://ai.google.dev/gemini-api/docs/image-generation),
[pricing](https://ai.google.dev/gemini-api/docs/pricing), and
[deprecations](https://ai.google.dev/gemini-api/docs/deprecations).

| Route | Model ID | API surface | Best use |
|---|---|---|---|
| Draft | `gemini-3.1-flash-lite-image` | generateContent | Lowest-cost and low-latency 1K work |
| Standard | `gemini-3.1-flash-image` | Interactions | General generation, editing, Search, and video-derived work |
| Professional | `gemini-3-pro-image` | Interactions | Complex instructions, text, localization, brand precision, and final assets |
| Compatibility | `gemini-2.5-flash-image` | generateContent | Deprecated legacy work only, shutdown scheduled 2026-10-02 |

The old preview aliases shut down on 2026-06-25. Imagen 4 Gemini API endpoints
shut down on 2026-08-17. Current image model pricing tables show no free API
inference tier, so a billing-enabled Google AI project is required.

JPEG is the only selectable output MIME on every route. A redacted local
Interactions probe using `gemini-3-pro-image` was reported on 2026-08-28 as
rejecting PNG; it did not directly test `gemini-3.1-flash-image`. The current
Interactions reference lists only JPEG, and the generateContent
`ImageResponseFormat` enum exposes only `IMAGE_JPEG`. Banana therefore rejects
PNG output plans before reading the key or calling Google as a conservative
API-surface policy. PNG remains supported as an input/reference format and as a
local render target. Each approval plan exposes the relevant Google
documentation conflict and its exact resolved provider response-format object.

Another redacted local probe was reported on 2026-08-28 as having Gemini 3.1
Flash Lite Image accept
`ASPECT_RATIO_ONE_BY_ONE`, `IMAGE_SIZE_ONE_K`, and `IMAGE_JPEG`, then returned a
1024 by 1024 `image/jpeg`. No durable response digest for either probe is
packaged. Google's legacy
[generateContent image guide](https://ai.google.dev/gemini-api/docs/generate-content/image-generation)
says video-to-image is available on Flash and Lite. In conflict, the modern
[image-generation guide](https://ai.google.dev/gemini-api/docs/image-generation),
current [Lite model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite-image),
and [May 28, 2026 changelog entry](https://ai.google.dev/gemini-api/docs/changelog)
describe video-to-image as Flash Image only. Banana follows the corroborating
current sources and rejects video input on Lite before reading the key or
calling Google, until Google resolves the documentation conflict.

## Installation

### Claude Code plugin, recommended

The bundled MCP requires Python 3.11 or newer and a `python3` command on
`PATH`. Check this before enabling the plugin:

```bash
python3 --version
```

The current MCP command is intentionally dependency-free, but it does not fall
back to a platform-specific `python` launcher. Installations without a
`python3` command must provide an equivalent launcher or use the direct scripts
with an explicitly supported Python 3.11+ interpreter.

Add the marketplace and install the plugin:

```text
/plugin marketplace add AgriciDaniel/banana-claude
/plugin install banana-claude@banana-claude-marketplace
/plugin enable banana-claude@banana-claude-marketplace
/reload-plugins
```

The plugin installs disabled because enabling it connects to a paid external
service. Explicitly enable it only when you are ready to configure Google and
review paid plans. Use Claude Code 2.1.199 or newer so the three paid MCP tools'
required-interaction metadata is enforced. When the plugin is enabled, Claude
Code prompts for `google_ai_api_key`. The
manifest marks it sensitive, so Claude Code masks the value and uses secure
credential storage where supported. Do not paste the key into chat or pass it
on a command line.

Create a key for a billing-enabled project in [Google AI Studio](https://aistudio.google.com/apikey).
Before paid use, configure the project's experimental monthly spend cap in
[AI Studio billing](https://ai.google.dev/gemini-api/docs/billing#spend-caps).
Google documents about ten minutes of enforcement latency and possible
overages, so the cap complements rather than replaces Banana's per-request
approval. Then run:

```text
/banana-claude:banana generate a restrained 16:9 hero image for a ceramics studio
```

The plugin first returns a compact `approval_summary` with the exact compiled
prompt, normalized visual brief, `brief_sha256`, model, ratio, size, storage and
retention disclosure, uploaded reference aliases, output and privacy settings,
a nominal image-output estimate, and a short-lived single-use approval ID. The
complete trace remains available after that decision surface. Review those
values and give a clear approval after seeing the plan. The capability prevents
drift and replay. On Claude Code 2.1.199 or newer,
the three paid MCP tools are marked as requiring user interaction, so
[Claude Code prompts even under allow rules, Auto, or Bypass
modes](https://code.claude.com/docs/en/permission-modes) and denies them where a
session cannot collect an answer. The approval ID alone is still not proof that
the exact plan was reviewed, so the skill requires a separate clear approval
after the plan is shown. Direct standalone scripts cannot inherit this Claude
Code host boundary and remain conversation-policy gated.

### Local plugin development

```bash
git clone https://github.com/AgriciDaniel/banana-claude.git
cd banana-claude
claude --plugin-dir .
```

Use `/reload-plugins` after editing plugin files.

### Standalone compatibility skill

The standalone installer provides `/banana` and the direct planning scripts,
but not the plugin-managed MCP, specialist agents, or sensitive key
configuration. The skill performs the same brief and review work inline:

```bash
git clone https://github.com/AgriciDaniel/banana-claude.git
cd banana-claude
./install.sh
```

Inspect the script before running it. It refuses to overwrite an unowned skill,
backs up a previous managed install, and moves an uninstall to a recoverable
directory. Ownership means a parseable `.banana-claude-install.json` marker
whose `name` is `banana-claude` and whose `version` is a non-empty string. The
marker is a lifecycle guard, not proof that the directory is trustworthy.
Managed backup and uninstall moves retain and recheck the reviewed directory
identity, both parent identities, and an atomic no-replace rename. A new install
builds its stage on the install filesystem and writes it only through held,
non-following directory descriptors. The helper binds a recursive receipt of
the selected source names and bytes, every copied inode, private modes, and the
exact closed inventory. It then atomically publishes that held staged directory
with a no-replace rename. Final shell acceptance reopens the target and rechecks
its identity, parent, marker, private mode, and complete receipt. A lost helper
status or catchable signal-like interruption is accepted only when that same
receipt proves the committed target. Managed backup and uninstall moves use a
separate descriptor-bound move receipt. A target race or receipt drift fails
without false success. Concurrent operations resolve through the same exclusive
rename primitive. Failure handling never
path-deletes the target, stage, backup, or removal path; uncertain state is
retained for manual inspection. Post-publication failure never triggers an
inverse pathname rename; the helper or user resolves the retained state from
its identity and receipt.
The standalone source root must contain exactly `SKILL.md`, `references`, and
`scripts`; an unexpected root entry fails closed as inventory drift. Within the
selected directories, the installer copies only the closed Markdown/JSON
reference allowlist and closed top-level Python-script allowlist. It does not
copy bytecode caches or ignored development artifacts.
Installation does not create, inspect, chmod, or otherwise change
`$BANANA_HOME` or `~/.banana`; runtime components create only the private state
paths they actually use.
The receipt is a transaction validation point, not ongoing same-account tamper
protection. A process running as the same operating-system user can modify that
user's files after acceptance. Treat that as post-install modification and
rerun from a trusted checkout when local account integrity is in doubt.
Configure `GEMINI_API_KEY` through your normal shell secret manager or
environment before executing a paid direct request. Standalone execution reads
only that variable. It deliberately ignores the generic `GOOGLE_API_KEY` and
`GOOGLE_AI_API_KEY` aliases so an ambient credential cannot silently select a
different Google project or billing account.

### Upgrade from public 1.4.1 or 2.1.0 installs

Public 1.4.1 and 2.1.0 installers could add an unpinned
`npx -y @ycse/nanobanana-mcp` entry to `~/.claude/settings.json`, store a raw
`GOOGLE_AI_API_KEY` in that entry, and install either `banana` or `nano-banana`
under `~/.claude/skills`. Installing version 3 alone does not neutralize those
older files. A key passed to the old `--with-mcp` option may also remain in
shell history.

Do not paste that key into a cleanup command or issue. Use the version 3
checkout to perform a redacted review before enabling the new plugin:

1. Run the read-only legacy scan. It reports names and states, never a stored
   key value:

   ```bash
   python3 skills/banana/scripts/legacy_cleanup.py scan --json
   ```

2. If cleanup is needed, preview the exact proposal, review its fingerprint,
   then confirm that fingerprint unchanged:

   ```bash
   python3 skills/banana/scripts/legacy_cleanup.py remediate --dry-run --json
   python3 skills/banana/scripts/legacy_cleanup.py remediate \
     --confirm FINGERPRINT_FROM_DRY_RUN --json
   ```

   Remediation removes only the obsolete `nanobanana-mcp` settings member,
   preserves unrelated settings and the active settings-file mode, and moves
   recognized old skill directories to unique recoverable backups. It refuses
   symlinks, non-regular or multiply linked settings, changed fingerprints, and
   a competing settings writer. Known credential fields are inspected through
   the complete bounded JSON value, and old skill fingerprints include regular
   file bytes that are rechecked after movement and before success. Inspect and
   retain every reported backup until the upgrade is verified. Skill moves are
   never automatically reversed after a partial failure. Their exact observed
   identities remain in the typed recovery report. A settings copy is restored
   only through an exclusive no-replace publication from the held exact backup,
   so a concurrent settings writer is never overwritten. Confirmed
   automated remediation requires secure descriptor-relative filesystem
   operations. On a platform without them,
   scan and dry-run remain available, but confirmation fails closed so the
   reviewed cleanup must be completed manually.

3. If the scan reports that a credential was stored, revoke or rotate it in
   [Google AI Studio](https://aistudio.google.com/apikey). Deleting the JSON
   entry cannot retract a key that was previously stored on disk, copied into a
   backup, logged, or passed on a command line. The private settings backup is
   byte-exact and therefore still contains that old value. Never upload it;
   remove it according to your local retention policy after rotation and the
   upgrade review are complete.

4. Install version 3. The standalone installer still refuses to adopt an
   unmarked `banana` directory, so complete the reviewed legacy cleanup first.
   Then run the read-only doctor and require the legacy check to pass:

   ```bash
   python3 "$CLAUDE_SKILL_DIR/scripts/doctor.py" --json
   ```

5. If `~/.banana/costs.json` came from 1.4.1, preview its exact offline
   migration, review the redacted proposal and fingerprint, then confirm that
   fingerprint unchanged:

   ```bash
   python3 "$CLAUDE_SKILL_DIR/scripts/cost_tracker.py" migrate-v1 --dry-run
   python3 "$CLAUDE_SKILL_DIR/scripts/cost_tracker.py" migrate-v1 \
     --confirm FINGERPRINT_FROM_DRY_RUN
   ```

6. Repeat the same review and confirmation for each legacy preset name:

   ```bash
   python3 "$CLAUDE_SKILL_DIR/scripts/presets.py" migrate-v1 quiet-precision --dry-run
   python3 "$CLAUDE_SKILL_DIR/scripts/presets.py" migrate-v1 quiet-precision \
     --confirm FINGERPRINT_FROM_DRY_RUN
   ```

All scans, cleanup, and state migrations are local and make no provider
request. Confirmation rereads the source and fails if it no longer matches the
reviewed fingerprint. Legacy-install remediation reports its recoverable
settings and skill backups. Before a state replacement, Banana stores a
timestamped byte-for-byte backup under the private `$BANANA_HOME/backups` tree.
Legacy cost backups can contain old prompt snippets. The active migrated ledger
deliberately replaces those snippets with a redaction marker. Migration state
reads are bounded to regular files, and symlinked state, lock, or backup paths
fail closed. Retain the backups privately until `doctor`, preset `show`, cost
`summary`, and one normal local planning workflow have been reviewed. A typed
migration failure never replaces a competing active path. For a catchable
process-control interruption before publication, Banana may atomically publish
an independently verified `0600`, single-link copy of the exact held legacy
bytes to a still-free active name while retaining the exact private backup;
after publication, it accepts only an exact migrated active file plus the exact
legacy backup. Otherwise it returns a typed recovery error with the observed
identities. If an uncatchable termination leaves `costs.json` absent beside a
strictly named migration backup, later loads fail with
`cost_migration_recovery_required`; they never report empty history or choose a
backup automatically. An absent preset name beside a strictly matching preset
migration backup similarly blocks load, list, and creation for that name with
`preset_migration_recovery_required`; Banana neither selects nor restores a
backup automatically.

## Typical workflows

### Generate

```text
/banana-claude:banana generate a product launch visual with exact left-side copy space
```

Banana freezes the goal, content facts, locks, freedom, direction, references,
composition, rendering, typography, output, and review tests. It compiles only
the fields that matter. A simple request stays simple.

### Edit with preservation

```text
/banana-claude:banana edit /path/to/source.png change only the jacket to rust orange
```

The edit contract names the exact delta and what must remain unchanged. If an
edit degrades identity or geometry, the workflow restarts from the original.

### Continue a stored session

Use provider-managed continuation on Flash or Pro only after accepting storage
and retention. Banana's one-shot Interactions requests explicitly send
`store: false`; Google's provider default is `store: true`.
For paid-tier Interactions, [Google currently documents 55-day retention by
default](https://ai.google.dev/gemini-api/docs/interactions-overview) and
project-level choices of 7, 14, 28, or 55 days. Banana cannot read the project's
configured value, so a stored plan discloses the documented default, available
choices, and that uncertainty. Stored turns use the returned
`previous_interaction_id`; consistency is supported but not guaranteed. Lite
and the deprecated 2.5 route use generateContent in this client, so an iteration
reattaches the accepted output as a new reference instead of continuing
provider-managed state.

### Compare multiple model routes

```text
/banana-claude:banana portfolio compare a direct direction and one justified risk on Flash and Pro
```

Banana shows every exact variant prompt, the aggregate nominal estimate, common
comparison resolution, every route, and the hashes, MIME types, sizes, roles,
safe disclosure aliases, authority statements, and purposes of all shared
references before calling
Google. `auto` uses a common 1K tier for a fair current-model comparison. The
portfolio tool is bounded to nine total requests, runs no more than three
concurrently, and reports partial failure because external paid calls cannot be
rolled back. Every returned MCP image is preceded by text that names its
variant, model, provider output index, artifact path, and SHA-256 digest.

### Review

The workflow requires every output to be checked for required content, exact
copy, composition, crop, direction, identity, product geometry, brand locks,
lighting, materials, typography, local artifacts, rights, attribution, and
provenance. The result is Pass, Targeted fix, Regenerate, or Blocked.

### Exact-copy typesetting

For a logo, legal copy, brand font, or dense layout, generate the visual field
without relying on the model for final copy. The zero-dependency compositor
embeds the background, ordered exact text blocks, and supplied trusted raster
logo or art assets in a deterministic SVG. An optional local TTF, OTF, WOFF,
or WOFF2 file can be embedded for portable font selection:

```bash
python3 skills/banana/scripts/typeset.py \
  --image /path/to/generated.png \
  --text "EXACT APPROVED COPY" \
  --x 120 --y 180 --font-size 64 --font-weight 700 \
  --font-file /path/to/approved-font.woff2 \
  --output /path/to/final.svg
```

This guarantees the characters in the vector layer, not a particular raster
renderer. Pin and embed the approved font, then render a PNG or JPEG preview
with a trusted viewer at the exact delivery dimensions and inspect it together
with the SVG. If no trusted renderer is available, automated visual review stays
blocked and the user must inspect the delivery artifact. Never treat SVG markup
as pixel evidence.

For multiple text and asset layers, pass an ordered JSON array:

```json
[
  {"type":"text","name":"headline","text":"EXACT HEADLINE","x":120,"y":180,"font_size":64,"font_weight":"700","fill":"#FFFFFF"},
  {"type":"image","name":"logo","path":"/path/to/approved-logo.png","x":120,"y":760,"width":240,"height":80,"fit":"contain"}
]
```

```bash
python3 skills/banana/scripts/typeset.py \
  --image /path/to/generated.png \
  --layers-file /path/to/layers.json \
  --output /path/to/final.svg
```

Image layers accept trusted raster assets. Export an approved SVG logo to a
reviewed PNG before composition. The compositor deliberately does not embed
arbitrary source SVG because it can carry active or external content.

## Direct script workflow

All paid direct scripts are plan-first:

Simple one-shot generation without references, Search, video, or stored state
can use the disclosed `planner_minimal` brief. Its runtime-only `prompt_only`
direction keeps creative intent in the exact approved prompt without claiming a
separate thesis or misclassifying the request as intentionally plain. Edit,
reference, Search, video,
stored-continuation, and portfolio commands require `--brief-file` pointing to
an accepted `banana.visual-brief.v1` JSON object. See
[prompt-engineering.md](skills/banana/references/prompt-engineering.md) for the
closed schema.

```bash
python3 skills/banana/scripts/generate.py \
  --prompt "A quiet editorial still life" \
  --model gemini-3.1-flash-image \
  --reference /path/to/product.png \
  --reference-name "front product photo" \
  --reference-role object \
  --reference-purpose "preserve product geometry" \
  --aspect-ratio 16:9 \
  --resolution 1K \
  --brief-file /path/to/banana-visual-brief.json
```

The command prints the compact approval summary, complete public plan, request
fingerprint, retention and cost disclosures, and a 30-minute single-use
approval ID without calling Google. The reference name must be a non-sensitive,
user-recognizable alias. Banana does not infer it from a local path. After
reviewing and approving the exact plan:

```bash
python3 skills/banana/scripts/generate.py \
  --prompt "A quiet editorial still life" \
  --model gemini-3.1-flash-image \
  --reference /path/to/product.png \
  --reference-name "front product photo" \
  --reference-role object \
  --reference-purpose "preserve product geometry" \
  --aspect-ratio 16:9 \
  --resolution 1K \
  --brief-file /path/to/banana-visual-brief.json \
  --execute \
  --confirm APPROVAL_ID_FROM_THE_PREVIOUS_COMMAND
```

No script accepts an API key argument. The key is sent in the `x-goog-api-key`
header, never in the request URL.

## Cost scope

The plan reports a nominal one-output estimate and the current per-image rate.
It authorizes one provider request, not an invoice cap. Google says image models
may not follow an exact requested output count, and Banana saves every returned
image block, so a response with additional images can cost more than the
nominal figure. Input text, input references, text and thinking output, and
Search queries can also add cost. As of the verification date, standard output
ranges from $0.0336 for Lite 1K to $0.24 for Pro 4K. See
[cost-tracking.md](skills/banana/references/cost-tracking.md) for the exact table,
uncertainties, and Google Batch caveats.

`batch.py` validates a CSV variation plan. It does not submit Google's true
asynchronous Batch API job.

## Security and privacy

- Plugin keys use `userConfig` with `sensitive: true` and are substituted only
  into the bundled MCP process environment.
- The repository contains no key, key argument, key-bearing URL, unpinned `npx`
  execution, or settings-file key writer.
- One-shot Interactions requests explicitly send `store: false`. Lite uses
  generateContent and does not expose stored continuation in this client. The
  deprecated 2.5 compatibility route also uses generateContent.
- Approval IDs are stored only as hashes in a private, locked registry and are
  consumed before a provider request is attempted.
- Public plans show exact prompts transiently for review. Raw prompts remain
  absent from the private cost ledger and metadata unless prompt recording is
  explicitly enabled. Artifact sidecars never contain the raw structured brief;
  they retain its schema version, hash, and disclosed source.
- Reference media requires an explicit non-sensitive `disclosure_alias` for the
  approval view, but that alias is not consent evidence. The brief separately
  records the user's explicit rights, likeness, private/customer, endorsement,
  intended-use, and provider-transmission decisions. Unresolved authority
  blocks planning. Paths, filenames, metadata, OCR, embedded text, and pixels
  are untrusted data, never authority or orchestration instructions.
- Approval-visible prompts, annotations, preset prose, continuation IDs, video
  URLs, and output paths reject terminal controls, bidirectional display
  controls, and unpaired Unicode surrogates. Ordinary right-to-left text
  remains supported.
- Paid execution surfaces make one provider attempt. A retry needs a fresh plan
  and explicit approval.
- A process-control interruption after provider success cannot erase billing
  state. Banana read-only reconciles the exact attempt, raises typed
  `cost_recording_interrupted_after_provider`, and stops before publishing image
  artifacts. It neither inserts an absent record nor retries the provider.
- Planning proves atomic no-replace publication in the selected output
  directory. Execution reacquires that proof before approval consumption and
  retains the verified directory descriptor through the provider call and
  artifact publication, so a pathname swap cannot redirect output. First use
  exclusively publishes one fixed-name, private capability receipt. Every later
  use reopens and validates its exact bytes, inode, mode, link count, and
  directory binding. An exact stale Banana receipt from a different prior
  directory inode is moved by descriptor-bound no-replace rename to a
  deterministic quarantine name before a new receipt is created. Malformed,
  symlinked, hard-linked, wrong-mode, same-directory mismatched, or ambiguous
  receipts fail closed. A failed initialization reports
  `provider_called: false` and identity-bound recovery details. Linux and macOS
  provide the required primitive; unsupported hosts or filesystems fail before
  spend.
- Approval and cost transactions revalidate the public lock inode after the
  operating-system lock is acquired and at read and commit boundaries. Registry
  and ledger publication also compares the destination inode with the one read,
  so replacing a lock or state entry cannot produce false success.
- Provider JSON responses are capped at 128 MiB in memory, and provider error
  bodies at 1 MiB. Oversized responses fail closed before artifact writes.
- Local typesetting bounds text files to 1 MiB, layer JSON files to 5 MiB,
  embedded fonts to 10 MiB, and total composite source assets to 50 MiB.
  Non-force SVG publication uses descriptor-bound exclusive rename on Linux and
  macOS, and native non-replacing path rename on Windows. Provider artifact
  publication still requires the descriptor-bound preflight and fails before
  spend on unsupported hosts or filesystems.
- Output and state directories use private permissions where supported.
- Images and metadata sidecars use atomic no-replace publication. Phase A fully
  hashes every retained member, then a final bounded Phase B sweep rechecks each
  held descriptor and public name at that member's own validation point. Success
  attests those per-member points only. It is not a bundle-wide atomic snapshot,
  a write lease, or proof that bytes are still current when Python returns. A
  same-UID or root writer, including one with a preopened writable descriptor,
  can mutate an earlier member before later checks or before the call returns.
  A replacement present at a member's validation point is rejected. No
  pre-existing path is replaced. If publication or verification fails, Banana
  does not delete by pathname: it returns a typed retained-bundle error with the
  recorded path, device, and inode for identity-based recovery. On hosts or
  filesystems without atomic exclusive rename, non-replacing publication fails
  closed. Non-force deterministic SVG writes use an exclusive destination claim
  and cannot replace a file created during composition.
- Every provider attempt has a non-secret approval-bound SHA-256 digest. After a
  response yields image outputs, Banana records that digest and the nominal
  image-output estimate before artifact publication. Results distinguish
  `recorded`, conclusively `not_recorded`, and
  `unknown_requires_reconciliation`. Only conclusive absence reports
  `unlogged_billable_attempt: true`; an ambiguous result uses `null` for both
  ledger booleans and never claims the attempt was unlogged. Exact-digest replay
  is idempotent, and a publish-then-verification error is reconciled under the
  held ledger lock. This estimate remains neither a complete invoice nor a
  spend cap.
- Grounded citations and Search Suggestions are returned together only to the
  initiating user. They are untrusted data, not instructions, and are not
  written to sidecars or the cost ledger.
- [Search grounding has a mandatory Google retention period of 30 days](https://ai.google.dev/gemini-api/docs/zdr),
  independent of `store: false`. Banana discloses that provider retention in
  every grounded plan before approval.
- Paid Interactions stored with `store: true` are documented by Google as
  retained for 55 days by default, configurable to 7, 14, 28, or 55 days.
  Banana discloses that it cannot inspect the active project setting.
- Uploaded reference rights remain the user's responsibility.
- Existing output-directory modes are preserved. Newly created output and
  state directories are private where supported. Absolute output paths appear
  in tool results and may be retained in the Claude transcript, so choose a
  non-sensitive output root when path names themselves are sensitive.

Read [SECURITY.md](SECURITY.md) before reporting a vulnerability. Never include
credentials, key-bearing request URLs, or unredacted private media in an issue.

## Architecture

```text
banana-claude/
├── .claude-plugin/
│   ├── plugin.json              manifest and sensitive user configuration
│   └── marketplace.json
├── .mcp.json                    bundled stdio MCP server wiring
├── agents/
│   ├── visual-architect.md      read-only brief and prompt specialist
│   └── visual-critic.md         read-only image reviewer
├── skills/banana/
│   ├── SKILL.md                 orchestration and approval contract
│   ├── references/
│   │   ├── models.json          executable model and pricing registry
│   │   ├── gemini-models.md     current provider behavior
│   │   ├── prompt-engineering.md
│   │   ├── mcp-tools.md
│   │   ├── review-and-recovery.md
│   │   ├── cost-tracking.md
│   │   ├── presets.md
│   │   └── post-processing.md
│   └── scripts/
│       ├── banana_core.py       routed provider client and artifact writer
│       ├── approval_store.py    locked single-use approval registry
│       ├── mcp_server.py        bundled MCP tools
│       ├── generate.py          plan-first single generation
│       ├── edit.py              plan-first reference edit
│       ├── portfolio.py         bounded multi-model comparison
│       ├── typeset.py           deterministic text and raster SVG compositor
│       ├── batch.py             offline CSV plan validator
│       ├── cost_tracker.py      locked private ledger
│       ├── presets.py           visual-system presets
│       ├── legacy_cleanup.py    redacted legacy-install remediation
│       └── doctor.py            read-only diagnostics
├── tools/
│   └── installer_lifecycle.py   descriptor-bound standalone lifecycle helper
├── tests/                       offline deterministic verification
├── pyproject.toml               explicit Ruff and Mypy policy
└── requirements-dev.txt         pinned development-only verification tools
```

## Verification

For development:

```bash
python3 -m pip install --disable-pip-version-check -r requirements-dev.txt
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
ruff check skills/banana/scripts tools tests
ruff format --check skills/banana/scripts tools tests
mypy --strict --no-incremental skills/banana/scripts tools tests
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q skills/banana/scripts tools tests
claude plugin validate --strict .
bash -n install.sh
git diff --check
```

Live Gemini acceptance is intentionally manual and paid. Use a dedicated test
project, a fixed small spend ceiling, and non-sensitive fixture media. Verify
the saved image and metadata, then inspect the pixels. Never run live provider
tests in public CI.

Before release, also run a real Claude Code session from a disposable profile:
load the plugin with `claude --plugin-dir .`, inspect its skill, agents, and MCP
server, exercise an offline plan, and confirm that an altered execution is
rejected. Secret substitution, permission prompts, one capped provider call,
and pixel acceptance remain separate manual gates and must be reported as such.

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md). Current
model, pricing, deprecation, Search, and retention claims need primary-source
evidence and a verification date.

## License and author

MIT License, see [LICENSE](LICENSE).

Built by [Agrici Daniel](https://agricidaniel.com/about), AI Workflow Architect.

Brand assets: [animated cover](screenshots/banana-claude-character-loop.gif),
[static cover](screenshots/cover-image-v3.webp), and
[GitHub social preview](screenshots/social-preview-v3.jpg).

- [Blog](https://agricidaniel.com/blog)
- [AI Marketing Hub](https://www.skool.com/ai-marketing-hub)
- [YouTube](https://www.youtube.com/@AgriciDaniel)
- [Open-source projects](https://github.com/AgriciDaniel)
