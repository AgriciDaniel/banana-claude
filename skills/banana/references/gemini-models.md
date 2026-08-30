# Current Gemini image models

Verified 2026-08-29 against Google's primary documentation. Machine-readable
capabilities and output prices live in `models.json` and are enforced by the
scripts. Recheck Google before publishing because model status, pricing, rate
limits, and Search terms are volatile.

Primary sources:

- <https://ai.google.dev/gemini-api/docs/image-generation>
- <https://ai.google.dev/gemini-api/docs/generate-content/image-generation>
- <https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite-image>
- <https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-image>
- <https://ai.google.dev/gemini-api/docs/models/gemini-3-pro-image>
- <https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-image>
- <https://ai.google.dev/gemini-api/docs/pricing>
- <https://ai.google.dev/gemini-api/docs/changelog>
- <https://ai.google.dev/gemini-api/docs/deprecations>
- <https://ai.google.dev/gemini-api/docs/interactions-overview>
- <https://ai.google.dev/gemini-api/docs/zdr>
- <https://ai.google.dev/api/interactions-api>
- <https://ai.google.dev/api/generate-content>
- <https://ai.google.dev/gemini-api/terms>

## Evidence classes and refresh

`models.json.claim_ledger` maps material volatile claims to their source URLs,
retrieval date, refresh due date, evidence class, and digest status. Treat the
classes differently:

- `official_documentation` means the claim was read from the named Google
  source on `retrieved_on`. The package does not contain a source snapshot, so
  the historical bytes are not independently auditable from the package.
- `reported_redacted_live_probe` means a local paid probe was reported during
  verification, but no response body or durable digest is packaged. It is
  supporting evidence, not independently reproducible proof.
- Banana policy is a conservative client decision derived from the documented
  evidence and conflicts. It must be labeled as policy, never as a provider
  guarantee.

Each runtime model's `evidence_claim_ids` maps identity and status, API and
output format, sizes and reference limits, features, and pricing to claim-ledger
IDs. API profiles and provider-retention fields carry their own mappings.
`catalog_field_provenance.local_policy_fields` separately identifies client
routing and fail-closed policy, so a local choice cannot masquerade as a Google
claim.

An absent digest is recorded explicitly as `not_captured`; it is not a hidden
pass. Recheck every claim by `refresh_due` and before release. If a source or
probe cannot be refreshed, preserve the last reported state, label it stale or
unverified, and keep the conservative route rather than silently promoting the
claim.

## Roster and routing

| Model ID | Status | Client API | Route | Sizes | Grounding | Video input |
|---|---|---|---|---|---|---|
| `gemini-3.1-flash-lite-image` | GA | generateContent | Lowest-cost, low-latency drafts and high-volume 1K work | 1K | No | Documentation conflict, client rejects |
| `gemini-3.1-flash-image` | GA | Interactions | Default general generation and editing | 512, 1K, 2K, 4K | Web and Image Search | HTTPS YouTube URL syntax, no access preflight |
| `gemini-3-pro-image` | GA | Interactions | Complex instructions, professional assets, text, localization, and brand precision | 1K, 2K, 4K | Web Search | No documented route |
| `gemini-2.5-flash-image` | Deprecated | generateContent | Compatibility only | About 1K | No | No |

Google schedules `gemini-2.5-flash-image` to shut down on 2026-10-02. Prefer
Lite for new low-cost 1K work.

The preview aliases `gemini-3.1-flash-image-preview` and
`gemini-3-pro-image-preview` shut down on 2026-06-25. The stable Pro replacement
is `gemini-3-pro-image`. Imagen 4 Gemini API endpoints shut down on 2026-08-17.

## Selection rules

- Start with Lite 1K for cheap concept exploration when long sequential edits,
  grounding, and character consistency are not needed.
- Use Flash for the normal create, edit, continuity, grounding, and
  video-derived workflow.
- Use Pro when precise instructions, complex layouts, localization, text, brand
  consistency, style references, or a final professional asset justify its
  price and latency.
- Use 2.5 only for an existing compatibility requirement. Do not build new
  workflows around a deprecated endpoint.
- Start at 1K. Move to 2K or 4K only when the intended delivery and review
  justify the cost. A 4K tier is ratio-specific and does not mean every output
  edge is capped at 4096 pixels.
- `auto` uses each model's default 1K size. A mixed-model portfolio also locks
  all current routes to their common 1K tier so resolution does not confound
  the visual comparison.

## Ratios and resolution

Flash supports 14 ratios:

`1:1`, `1:4`, `1:8`, `2:3`, `3:2`, `3:4`, `4:1`, `4:3`, `4:5`, `5:4`,
`8:1`, `9:16`, `16:9`, `21:9`.

Pro and 2.5 use the ten conventional ratios. Banana also permits only these ten
ratios for Lite:

`1:1`, `2:3`, `3:2`, `3:4`, `4:3`, `4:5`, `5:4`, `9:16`, `16:9`, `21:9`.

For Lite, this is a conservative client allowlist rather than a provider hard
limit. Google's current Lite model page says the model supports 14 ratios, while
the current image-generation guide enumerates only the ten ratios above for
Lite. Banana uses their ten-ratio intersection until Google resolves that
documentation conflict.

Flash resolution values are `512`, `1K`, `2K`, and `4K`. Lite is 1K only.
Pro accepts `1K`, `2K`, and `4K`. The 2.5 route is 1K only. The client accepts
`0.5K` as a user alias and normalizes it to the documented `512` API value.

Examples of Flash 4K tier dimensions:

| Ratio | Dimensions |
|---|---:|
| 1:1 | 4096 x 4096 |
| 16:9 | 5504 x 3072 |
| 1:8 | 1536 x 12288 |
| 21:9 | 6336 x 2688 |

## Reference inputs

Google documents a provider maximum of 14 reference images for the Gemini 3
models. It separately documents model-specific high-fidelity role guidance:

| Model | Object references | Character references | Style references |
|---|---:|---:|---:|
| Lite | Up to 14 | Not documented | Not documented |
| Flash | Up to 10 | Up to 4 | Not separately documented |
| Pro | Up to 6 | Up to 5 | Up to 3 |
| 2.5 | Google says it works best with up to 3 total | Not separately documented | Not separately documented |

For 2.5, "works best with up to 3" is provider quality guidance, not a
documented provider hard limit. Banana turns that guidance into a conservative
three-image client policy. Banana also enforces the per-role counts in the
table as client policy. These validation policies are represented separately
from provider hard limits in `models.json`.

The bundled client requires every reference to have a Banana prompt annotation
role, `object`, `character`, or `style`. A required non-sensitive
`disclosure_alias` makes the upload recognizable in the approval view without
claiming consent. A
required `purpose` records the semantic job, such as identity, geometry,
composition, palette, or material. An optional `subject_id` labels several
views as the same intended subject. Role, purpose, and subject ID are text
inserted into the prompt beside each reference image. They are not Google API
request fields or provider-native reference categories. A separate authority
object, bound into the visual brief and approval, records only the user's
explicit rights, likeness, private/customer, endorsement, intended-use, and
provider-transmission decisions. Any unresolved decision blocks planning.

Google describes Lite as useful for quick local iterative edits but not
optimized for long sequential editing or complex multi-reference work. That is
a model capability, not server-managed conversation state. Lite is not listed
for the Interactions API, so this client routes it through generateContent and
requires each iteration to reattach the accepted output as a new reference.

The bundled client limits inline references to 20 MB total and conservatively
accepts PNG, JPEG, and WebP. Google's image-understanding documentation,
verified 2026-08-29, also lists HEIC and HEIF, but Banana fails those formats
closed until its local signature, dimension, and route validation supports
them. Google does not currently list GIF for image input, so Banana rejects GIF
before approval or key access. Use Google's Files API outside this client for
larger payloads or local video uploads.

## Interactions and generateContent

Google recommends the GA Interactions API for new interactive projects. Its
current model enum includes Flash, Pro, and the deprecated 2.5 image model, but
not Gemini 3.1 Flash Lite Image. Banana uses Interactions for the two current
full routes. It deliberately keeps the deprecated 2.5 compatibility model on
the explicit generateContent legacy path documented by Google, where its
aspect-ratio request omits unsupported `imageSize`. This is a client routing
choice, not a claim that Google omits 2.5 from the Interactions model enum.

For Flash and Pro:

```text
POST https://generativelanguage.googleapis.com/v1beta/interactions
x-goog-api-key: $GEMINI_API_KEY
Content-Type: application/json
```

Example image request:

```json
{
  "model": "gemini-3.1-flash-image",
  "input": [{"type": "text", "text": "A precise visual prompt"}],
  "response_format": {
    "type": "image",
    "mime_type": "image/jpeg",
    "aspect_ratio": "16:9",
    "image_size": "2K"
  },
  "store": false
}
```

Google's current sources conflict on explicit PNG selection for Interactions.
The Interactions API reference lists only `image/jpeg`, while the current
model-specific image guide shows both `image/png` and `image/jpeg` in REST
requests. A redacted local Interactions probe using `gemini-3-pro-image` was
reported on 2026-08-28 as rejecting `image/png` and naming `image/jpeg` as the
supported value. It did not directly test `gemini-3.1-flash-image`, and no
durable response digest is packaged. Banana therefore restricts Flash and Pro
Interactions output to JPEG as a conservative API-surface policy and rejects
PNG before network I/O. Every affected approval plan still exposes the source
conflict, exact probe scope, and policy note.

The current generateContent `ImageResponseFormat` schema likewise exposes only
`IMAGE_JPEG` as a selectable output MIME. Its legacy image-generation guide
uses PNG filenames in examples without defining an explicit PNG response enum.
Banana therefore restricts every route to JPEG output. PNG remains accepted for
validated input references and local post-processing.

Interactions provides a universal endpoint, execution steps, server-managed
continuation, and provider-side storage. Storage is enabled by provider default,
so Banana sends `store: false` for one-shot work. A stored multi-turn workflow
must explicitly set `store: true` and disclose retention before using
`previous_interaction_id`. Tools, system instructions, and generation config
must be supplied again on each continuation.

For the paid tier, Google documents 55 days as the default Interactions
retention period and allows project-level automatic deletion after 7, 14, 28,
or 55 days. Banana cannot inspect the project's configured retention period.
Every `store: true` plan therefore exposes the documented default, the allowed
options, and the client-inspection warning before approval. This provider
storage disclosure is separate from Search grounding's mandatory 30-day
retention rule.

A public single-request plan also exposes the exact normalized prompt for human
review and retains its SHA-256 hash in the approval fingerprint. The prompt is
transient by default: Banana does not write it to an artifact sidecar or cost
ledger unless the user explicitly enables prompt recording.

For Lite and the deprecated 2.5 compatibility model:

```text
POST https://generativelanguage.googleapis.com/v1/models/gemini-3.1-flash-lite-image:generateContent
x-goog-api-key: $GEMINI_API_KEY
Content-Type: application/json
```

The generateContent payload uses `contents`,
`generationConfig.responseModalities`, and
`generationConfig.responseFormat.image`. It does not use Interactions storage
or `previous_interaction_id`. Friendly plan values are converted at the raw
REST boundary to the current typed enums, for example `1:1` to
`ASPECT_RATIO_ONE_BY_ONE`, `1K` to `IMAGE_SIZE_ONE_K`, and `image/jpeg` to
`IMAGE_JPEG`. The resolved provider object is included in the approval
fingerprint. A redacted local Lite probe was reported on 2026-08-28 as
accepting the typed 1:1, 1K, and JPEG tuple and returning a 1024 by 1024
`image/jpeg`; no durable response digest is packaged. The deprecated 2.5 request omits
`imageSize`, which that model does not support. Google's legacy generateContent
image guide says video-to-image is available on Flash and Lite. In conflict,
the modern image-generation guide, current Lite model page and limitations, and
May 28, 2026 changelog entry describe it as Flash Image only. Banana follows
the corroborating current sources and rejects video input on Lite before key
access or provider I/O, until Google resolves the documentation conflict.

`generateContent` also remains the basis for Google's true asynchronous Batch
API and exposes fields not currently offered by Interactions. Banana's CSV
utility only validates a variation plan; it does not submit a Batch job.

## Grounding

Flash supports Web Search, Image Search, or both. Image Search does not require
Web Search to be selected in the same request:

```json
{"type": "google_search", "search_types": ["image_search"]}
```

Pro supports Web Search. Lite and 2.5 do not support Search grounding for image
generation. Use grounding only when the image needs current factual context.
Search can create additional charges per provider search query.

Grounded Interactions responses can contain URL citations, a
`google_search_result`, and `search_suggestions`. Display the associated Google
Search Suggestions together with the Grounded Result and links, only to the
same user who initiated the request. The bundled client returns that attribution
data transiently and does not persist it in sidecars, ledgers, or presets.
Google's terms restrict caching, copying, storage, analysis, and reuse outside
narrow exceptions. Image Search does not support retrieving real-world images
of people for generated-image use.

Google retains Search-grounded request and response data for 30 days. This is a
mandatory Search-grounding retention rule and is independent of an
Interactions request's `store: false` setting. Banana exposes that fact in each
grounded plan before approval. Do not describe a grounded request as zero
retention.

## Thinking controls

The current legacy image guide says Flash and Lite default to `minimal` and
allow `minimal` or `high`. The current Lite model page documents the same levels
but does not state a default. Banana therefore uses `minimal` while exposing
that source conflict in Lite approval plans. Pro uses its documented default
reasoning process, but the current image guide does not document a
client-selectable Pro level. Gemini 2.5 does not use the Gemini 3
`thinking_level` control.

## Output, state, and limitations

- Banana's displayed output price is the current per-image rate and its cost
  estimate is explicitly a nominal one-output estimate. It is not an invoice
  cap. A response can contain multiple image blocks even though there is no
  Imagen-style `sampleCount` parameter, so the billed output count remains
  uncertain until the response and provider bill are available. The client
  makes one provider attempt per approval.
- Multi-turn editing and reference-based consistency are supported, not
  guaranteed. Drift remains possible.
- Server-managed continuation is available only on the Flash and Pro
  Interactions routes in this client. Lite and 2.5 can still be iterated by
  reattaching the accepted output in a new request.
- Google's legacy generateContent image guide documents video-to-image on Flash
  and Lite, while the modern image guide, current Lite model page and
  limitations, and May 28, 2026 changelog entry say Flash Image only. Banana
  resolves this conflict conservatively: the bundled client accepts only the
  supported HTTPS YouTube watch or short URL syntax for Flash, with a
  syntactically valid 11-character video ID. It does not preflight whether the
  video exists, is public, or is accessible to Google. Passing a URL asserts
  those conditions, and an inaccessible URL can consume the one paid provider
  attempt. Local video needs a Files API upload workflow outside this client.
  Every non-Flash route rejects video before provider I/O.
- The bundled paid surfaces make one provider attempt per approval. A 429, 5xx,
  network error, or timeout requires a fresh plan and user approval before a
  second attempt.
- Audio input is not supported for image generation.
- Exact counts, spelling, identity, geometry, and small text can still fail.
  Inspect the actual output.
- Rate limits depend on the project, account, model, and billing tier. Check the
  live AI Studio limits page. Do not rely on guessed RPM or RPD numbers.
- Current image model pricing tables show no free API inference tier. A key can
  be created without charge, but image calls need a billing-enabled project.

## Rights and provenance

Google documents SynthID on all generated images covered by the image guide.
Do not generalize the Google Cloud Enterprise Agent Platform C2PA contract to
every Gemini Developer API response without byte-level verification. Image
conversion, cropping, recompression, or metadata stripping can alter provenance
metadata.

The user must have rights to uploaded references and remains responsible for
lawful use, attribution, and distribution. Do not present generated output as a
guaranteed unique asset or as an endorsement by a referenced person or brand.
