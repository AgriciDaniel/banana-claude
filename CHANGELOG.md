# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.0.0] - 2026-08-30

[Read the version 3 release highlights](.github/releases/v3.0.0.md).

### Breaking

- Replaced the unpinned third-party MCP dependency with a bundled,
  zero-dependency Python MCP server and routed Gemini REST client.
- Moved plugin credential setup to sensitive `userConfig`; direct scripts read
  only `GEMINI_API_KEY` from the launching environment, ignore generic Google
  key aliases, and no longer accept key arguments.
- Replaced the legacy prompt-expansion workflow with a brief-led plan,
  approval, execution, pixel review, and recovery contract.
- Retired preview and Imagen routes from executable defaults. The deprecated
  `gemini-2.5-flash-image` route remains for compatibility only.
- The plugin now installs disabled and requires explicit enablement because its
  execution tools connect to a paid external service.
- Versioned cost-ledger and preset schemas replace the unversioned 1.4.1 state.
  Existing state requires the explicit dry-run and fingerprint-confirmed
  migration; it is never rewritten during install or normal loading.
- Public 1.4.1 and 2.1.0 installs can contain an unpinned third-party MCP entry,
  a raw Google key, and obsolete skill directories. Version 3 detects that
  residue and requires explicit backup-first cleanup plus key revocation or
  rotation before the installation can be considered ready.

### Added

- Added the closed `banana.visual-brief.v1` contract, canonical
  `brief_sha256`, compact approval summaries, and machine-detectable supplied
  brief gates for edits, uploaded references, Search, video, stored
  continuation, and portfolios.
- Added required non-sensitive reference disclosure aliases, separate
  brief-bound authority statements that block unresolved rights or permission,
  and explicit MCP `image_attribution` text immediately before every returned
  image, including variant, model, provider output index, artifact path, and
  artifact SHA-256.
- Added approval-bound provider `attempt_sha256` values and idempotent private
  cost-ledger reconciliation.
- Added explicit supplied `creative`, `preserve`, and `not_applicable` direction
  modes, plus runtime-only `prompt_only` for disclosed minimal plans, and a dated
  provider-claim ledger that labels official documentation, reported redacted
  probes, missing evidence digests, refresh deadlines, and executable field
  coverage.
- Current model and pricing registry for Nano Banana 2 Lite, Nano Banana 2,
  Nano Banana Pro, and the deprecated compatibility route.
- Current project-level spend-cap guidance, including Google's experimental
  status and documented billing-signal latency.
- No-Google `banana_models`, `banana_plan`, and `banana_portfolio_plan` MCP
  tools, with private local approval issuance for paid plans.
- Paid, exact-plan-gated generation, edit, and bounded portfolio MCP tools.
- Claude Code 2.1.199+ required-interaction metadata on every paid MCP tool, so
  allow rules, Auto, and Bypass modes cannot silently execute a paid request.
- Multi-image response extraction, atomic private artifact writes, hashed prompt
  and interaction-ID metadata, and transient delivery of raw interaction IDs,
  grounding citations, and Google Search Suggestions without sidecar
  persistence.
- Explicit Interactions routing for supported models and generateContent routing
  for Nano Banana 2 Lite and the deprecated 2.5 compatibility model.
- Thirty-minute single-use approval capabilities, stored only as hashes, bound
  to prompt, inputs, model, exact Google endpoint, catalog verification date,
  estimate, output, and privacy settings.
- Signature and hash validation for reference images before upload and again at
  execution time.
- Deterministic ordered SVG composition with multiple exact-copy text blocks,
  optional embedded local fonts, and supplied trusted raster logo/art layers.
- Explicit SVG review gating that requires a trusted delivery-size PNG or JPEG
  render before an automated critic can issue a pixel verdict.
- Added Banana-side object, character, and style reference roles and policies,
  with per-model limits, semantic purposes, subject IDs, and complete plan
  disclosure.
- Optional read-only visual architect and independent visual critic agents.
- Model-aware prompts, explicit locks and freedom, reference roles, text
  handling, visual QA, failure recovery, and provider-retention guidance.
- Deterministic offline tests for models, plans, provider errors, artifacts,
  API routing, approval replay, MCP transport, CLI boundaries, deterministic
  typesetting, concurrent cost tracking, presets, installer lifecycle, and
  repository contracts.
- Pinned development-only Ruff and Mypy versions, with CI-enforced lint,
  formatting, and strict type-check gates. Runtime remains standard-library-only.
- Offline two-step migrations for exact 1.4.1 cost ledgers and presets, with
  source-bound fingerprints and private byte-for-byte backups before change.
- A redacted legacy-install scanner and fingerprint-confirmed cleanup for the
  public 1.4.1 `banana` and 2.1.0 `nano-banana` layouts. It removes only the
  obsolete `nanobanana-mcp` entry, preserves unrelated Claude settings and
  file modes, exhaustively checks bounded JSON for known credential fields, and
  moves old skills to recoverable private backups only when their rechecked
  file bytes still match the confirmed fingerprint.
- Bounded regular-file reads, closed active-state schemas, symlink-safe locks,
  and POSIX mode verification for migration, preset, cost, and approval state.
- Descriptor-bound POSIX state migrations that reject parent-identity swaps and
  multiply linked legacy sources before redirected writes or mode changes.

### Changed

- Raised the declared and CI-tested runtime floor from Python 3.10 to Python
  3.11 so the supported floor matches the interpreters verified for version 3.
- Execution now acquires the exact output-directory capability before approval
  consumption and holds its descriptor through provider I/O and artifact
  publication. Portfolio execution acquires every item capability before its
  shared approval is consumed.
- A canonical private receipt bound to a different prior directory inode is
  moved by descriptor-bound no-replace rename to a deterministic stale
  quarantine name before a fresh receipt is created. Unsafe or ambiguous
  receipts still fail closed.
- Artifact sidecars record only the visual-brief schema version, hash, and
  source, never the raw structured brief.
- Portfolio and edit MCP schemas now require the visual brief that the runtime
  already enforced, and reported provider probes are no longer labeled as
  independently verified package evidence.
- Updated the default route to stable `gemini-3.1-flash-image` and documented
  current ratios, resolutions, reference limits, Search, video, thinking, and
  Batch distinctions as verified on 2026-08-29.
- Generation, edit, and portfolio scripts now plan without network access by
  default and require `--execute` plus an exact single-use approval ID.
- Paid execution now makes one provider attempt per approval. Retryable
  failures require a new plan and explicit approval.
- CSV processing is explicitly an offline variation planner. It does not claim
  to submit Google's asynchronous Batch API, and it rejects presets that have
  not first been compiled into a visible brief.
- Presets now use a validated versioned visual-system schema.
- The standalone installer now refuses unowned directories, backs up managed
  installs, uses unique recovery locations, validates structured ownership
  markers, and retains a previous install for identity-based recovery after a
  failed replacement. Stage
  construction is descriptor-bound on the destination filesystem and produces
  an exact source manifest plus recursive inode and byte receipt, rejects extra
  entries, and binds private root modes. Publication atomically renames the held
  staged directory into an absent target. Both helper and shell acceptance
  recheck the target, parent, marker, and full receipt, including after an
  interrupted helper status. Competing operations resolve through no-replace
  renames. Post-publication failures never perform an inverse pathname rename;
  they retain uncertain lifecycle paths for receipt-based resolution instead.
  Recoverable uninstall preserves local data, and unknown arguments are rejected
  without being echoed.
- Pre-marker 1.4.1 standalone installs now have an explicit manual upgrade
  guide. The installer continues to refuse automatic adoption. The guide also
  covers the public 2.1.0 layout and its credential-remediation requirement.
- The standalone installer no longer creates or changes the private Banana
  state tree. Runtime components create only the state paths they actually use
  and apply their own fail-closed validation.
- Mixed-model `auto` portfolios use a common 1K comparison tier and expose the
  complete shared-reference and privacy plan before approval. Every item must
  resolve the identical shared reference snapshot or the plan fails closed.
- Successful execution distinguishes transport completion from pending visual
  acceptance with explicit result fields.
- Approval plans expose model-specific thinking behavior, the resolved provider
  response-format object, and Google's output-MIME documentation conflicts. A
  live 2026-08-28 Interactions request and the current generateContent enum
  establish JPEG as the only selectable output, so PNG output plans now fail
  before provider I/O.
- generateContent response-format values now use catalog-owned REST enums and
  are approval-bound. This replaces display strings that the live v1 endpoint
  rejected for aspect ratio and image size. A corrected live Lite request then
  returned a 1024 by 1024 JPEG.
- Lite thinking-default documentation conflicts are separated from Banana's
  conservative client policy. The catalog now follows Google's current guide,
  which documents video-to-image only for Gemini 3.1 Flash Image.
- Provider image blocks without an explicit returned MIME now fail closed
  before artifact decoding or writes.
- Provider usage metadata is reduced to allowlisted bounded token counts, and
  arbitrary provider error text is no longer propagated or persisted.
- Offline CSV prompts now use the same approval-visible text validation as
  direct and MCP plans, and local typesetting input files are bounded before
  full reads or parsing.

### Fixed

- Standalone lifecycle helpers now normalize catchable signal-like failures and
  distinguish prepublication interruption from post-publication uncertainty.
  Exact install and managed-move receipts can reverify a completed no-replace
  transaction without inverse rename, while shell cleanup preserves interrupt
  status and retains unresolved paths.
- Standalone staging now rejects unexpected skill-root entries as inventory
  drift, and the plugin and marketplace descriptions consistently declare the
  tested Python 3.11 runtime floor.
- Preset deletion now surfaces strict migration residue instead of masking an
  interrupted migration as an ordinary missing preset.
- Interactions PNG probe evidence now states that the reported rejection used
  only `gemini-3-pro-image`; shared Interactions route membership sits outside
  the probe object, and public Flash plans cannot machine-attribute Flash to
  that Pro-only probe. Flash's JPEG-only behavior is labeled a conservative
  shared-API policy rather than a Flash-specific probe result.
- Cost recovery now distinguishes `recorded`, conclusively `not_recorded`, and
  `unknown_requires_reconciliation`. Ambiguous ledger publication leaves both
  ledger booleans unknown instead of falsely reporting an unlogged attempt.
- Post-provider process-control interruptions now trigger read-only exact cost
  reconciliation and a typed abort before artifact publication, so a persisted
  billable attempt cannot disappear behind a raw interrupt.
- Replaced the malformed README cover lettering with a reviewed deterministic
  title treatment while preserving the generated character artwork.
- Final bundle acceptance now reopens and retains every artifact. Phase A checks
  identity, mode, link count, size, signature, stable stats, and SHA-256, then a
  bounded Phase B sweep rechecks each held descriptor and public name at its own
  point-in-time validation. This is not a bundle-wide atomic snapshot or write
  lease: a same-UID or root writer, including one with a preopened writable
  descriptor, can mutate an already checked member before later checks or before
  Python returns.
- Green-screen recovery examples now guard distinct computed destinations
  before every ImageMagick or FFmpeg write.
- Cost-ledger and preset migrations now reconcile catchable interruptions after
  claim without overwriting racers: before publication they can publish an
  independently verified, private single-link copy of the exact held legacy
  bytes, and after publication they prove the exact migrated active bytes.
  Missing active cost or per-name preset state plus strict migration residue now
  fails recovery-required instead of becoming empty history or a new preset.
- Added the plugin MCP server that prior releases documented but did not ship.
- Fixed concurrent cost-ledger updates with a stable lock and atomic replace.
- Approval, cost, and preset locks now rebind the public lock entry after
  acquiring the operating-system lock and revalidate it at transaction
  boundaries. Approval and cost commits also compare the destination inode with
  the identity read before publication.
- Removed fixed rate-limit guesses, hidden banned-word folklore, universal C2PA
  claims, free image-inference claims, and unsupported provider parameters.
- Corrected the historical v1.4.0 provider claims in current guidance: the Pro
  preview alias shut down on 2026-06-25, not 2026-03-09, and the listed quality
  words were never verified provider bans. The old entry remains unchanged as
  release history and is superseded by this correction.
- Preserved existing output-directory permissions instead of changing them,
  while binding output publication to stable non-following directory
  descriptors on POSIX systems.
- Migration confirmation now claims and revalidates the exact legacy source,
  then publishes exclusively so a concurrent legacy write is preserved instead
  of silently overwritten.
- Runtime state roots, approval and cost ledgers, and lock files now reject
  active or dangling symlinks without changing or escaping into their targets.
- Paid execution now proves atomic no-replace publication in the selected
  output directory before approval consumption or provider I/O. Provider
  successes are cost-accounted before artifact publication, with a typed
  attempt digest and explicit recorded, not-recorded, or unknown reconciliation
  state if the private ledger cannot immediately prove its outcome.
- Pre-spend publication proof now retains one fixed private capability receipt
  and revalidates its bytes, inode, mode, link count, and directory binding on
  reuse, eliminating cleanup-by-path from that transaction.
- Artifact publication keeps the temporary inode descriptor open through
  exclusive rename and returns identity-bound recovery records after uncertain
  source, destination, or verification failures. Legacy settings publication
  uses the same exclusive rename primitive instead of temporary hard links.
- Deterministic SVG output no longer follows a destination symlink, including
  force replacement. Direct CLI parse errors no longer echo unknown argument
  values, including obsolete key-bearing invocations.
- Provider interaction IDs are one-way hashed before ledger or sidecar
  persistence. Valid older schema-1 ledger entries are normalized under the
  ledger lock without printing the raw identifier.
- Lite video input now discloses the conflict between Google's legacy and
  current documentation while retaining the conservative reject policy. Flash
  video plans state that only YouTube URL syntax is checked and that
  accessibility is user-asserted, not preflighted.
- Prompt-recording sidecars now normalize and verify the prompt against the
  approval-bound hash before publication. Pull-request static-check examples
  now include the maintained `tools` package.
- Image responses are now published as one call-level image and sidecar bundle.
  Every new path uses atomic exclusive rename where supported, pre-existing
  files are preserved, and every published inode is rechecked at its individual
  validation point before acceptance. Failures retain rather than path-delete
  published outputs or private temporary paths, and typed recovery details carry
  the root safe error plus path, device, and inode records. Unsupported
  exclusive-rename hosts or filesystems fail closed, and a concurrent
  replacement present at a member's validation point is not accepted as this
  call's output. These checks do not freeze an entry after its validation point.
- Preserved generateContent prompt-level and candidate-level filtering reasons,
  including recitation, sensitive-information, escalation, and image-specific
  reasons, as typed, sanitized client errors.
- Fixed stale command naming, model IDs, pricing, setup guidance, ownership
  paths, version metadata, and issue templates.
- Hardened MCP protocol negotiation, enforced the initialize/initialized
  lifecycle, bounded both stdio framing styles, preserved recovery after a
  rejected newline frame, closed unrecoverable Content-Length sessions without
  parsing residual bytes, rejected unsafe Unicode in JSON-RPC identifiers
  without echoing it, and clarified command, approval, and private-reporting
  guidance.
- Limited standalone installation to the maintained skill, reference, and
  Python source allowlist so bytecode caches and ignored artifacts cannot leak
  into an install.
- Installer staging now requires every declared runtime file, snapshots the
  complete source allowlist, and rejects missing, symlinked, or type-swapped
  source entries before final receipt acceptance.
- Cost ledgers now reject wrong schema versions, invalid container types,
  boolean counts, and non-finite values before any update.
- Legacy ledger migration redacts old prompt snippets from active state while
  retaining exact original bytes only in the disclosed private backup.
- Cost migration and legacy skill cleanup no longer inverse-rename uncertain
  backups after a partial transaction. Errors retain and distinguish intended,
  active, and backup identities for manual recovery. Preset deletion is an
  atomic recoverable move and explicitly reports that no byte erasure occurred.
- Unexpected portfolio worker failures now return a constant safe error instead
  of exposing exception text that could contain private local data.
- Local raster composition now rejects bytes that change after validation, and
  non-force SVG writes claim the destination exclusively instead of racing an
  unconditional replacement. Windows uses native non-replacing path rename for
  this local-only SVG publication path.

### Security

- Keys are injected only into the bundled MCP process through sensitive Claude
  Code configuration and are sent to Google in `x-goog-api-key`, never a URL.
- Raw prompts are excluded from the ledger and metadata by default. Output,
  sidecar, approval, preset, and ledger files use private permissions where
  supported.
- Paid calls are separated from offline planning and fail closed on plan drift,
  replayed approval, changed reference bytes, unsupported capabilities, corrupt
  provider output, and corrupt local state.
- Approval-visible text rejects terminal controls, bidirectional display
  controls, and unpaired Unicode surrogates while preserving ordinary
  right-to-left writing.
- Deterministic typesetting applies the same fail-closed validation to explicit
  and derived output paths.
- Provider response bodies are bounded to 128 MiB and error bodies to 1 MiB
  before JSON parsing or artifact writes.
- Deterministic typesetting bounds text files to 1 MiB, layer JSON files to
  5 MiB, embedded fonts to 10 MiB, and total composite source assets to 50 MiB.
- Paid MCP calls require a direct Claude Code host decision where interaction is
  available and are denied where the session cannot collect one. Direct scripts
  remain separately plan-gated and do not claim that host enforcement.
- The doctor fails readiness when it detects the legacy unpinned MCP entry or
  obsolete skill layouts. Scans never print the stored key. Removing the entry
  cannot retract a credential previously stored on disk or passed on a command
  line, so affected users must revoke or rotate that key in Google AI Studio.

## [2.1.0] - 2026-03-13

### Added

- 4K output, expanded aspect ratios, thinking controls, Search grounding,
  multi-image inputs, image-only output, safety guidance, and updated diagrams.
- The `nano-banana` skill layout and an optional third-party MCP setup path.

### Changed

- Defaulted the historical adapter to the then-preview
  `gemini-3.1-flash-image-preview` model.
- Added an installer option that accepted an API key on the command line and
  stored it directly in Claude settings. Version 3 removes this unsafe path and
  documents mandatory credential revocation or rotation for affected users.

### Fixed

- Corrected historical skill formatting and prompt-guidance contradictions.

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

> Historical note added in 3.0.0: the bullets below are preserved as the
> 1.4.0 release record. The March 9 image-model shutdown date, official
> five-field formula, banned-word rules, prompt-length limits, universal rate
> limits, and retry guidance were later found incorrect, unsupported, or local
> heuristics. Current operating guidance is in the 3.0.0 section and current
> references.

### Breaking Changes
- Removed `gemini-3-pro-image-preview` (Nano Banana Pro) -- shut down by Google March 9, 2026
- Replaced 6-component Reasoning Brief with Google's official 5-component formula (Subject → Action → Location/Context → Composition → Style)
- Default resolution changed from `1K` to `2K` in fallback scripts
- Banned prompt keywords: "8K", "masterpiece", "ultra-realistic", "high resolution" -- use prestigious context anchors instead

### Added
- Banned Keywords section in prompt-engineering.md (Stable Diffusion-era terms that degrade quality)
- Negative Prompts guidance (semantic reframing, ALL CAPS for constraints)
  Version 3 correction: ALL CAPS was historical advice, not a verified provider
  adherence mechanism, and current guidance removes it.
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
  Version 3 correction: prestige anchors were a historical heuristic, not a
  Gemini requirement, and current guidance removes the rule.

### Changed
- SKILL.md version bumped to 1.4.0 with improved frontmatter
- gemini-models.md fully restructured with NB2/NB naming, updated pricing ($0.067/1K)
- Model routing table uses 5-component references instead of 6-component
- All prompt templates updated to use prestigious anchors instead of banned keywords
  Version 3 correction: this was a historical local heuristic, not provider
  guidance, and current templates do not require it.
- Prompt adaptation rules updated to remove banned keywords
  Version 3 correction: generic quality words are not provider-banned, and the
  current workflow does not enforce that historical rule.

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

> Historical note added in 3.0.0: the bullets below are preserved as the
> 1.2.0 release record. The universal C2PA and fixed rate-limit claims were not
> supported as durable provider facts and are removed from current guidance.

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

[1.4.0]: https://github.com/AgriciDaniel/banana-claude/releases/tag/v1.4.0
[1.4.1]: https://github.com/AgriciDaniel/banana-claude/releases/tag/v1.4.1
[2.1.0]: https://github.com/AgriciDaniel/banana-claude/releases/tag/v2.1.0
[3.0.0]: https://github.com/AgriciDaniel/banana-claude/compare/v1.4.1...v3.0.0
[Unreleased]: https://github.com/AgriciDaniel/banana-claude/compare/v3.0.0...HEAD
