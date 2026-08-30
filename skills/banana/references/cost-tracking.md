# Cost planning and private ledger

Verified 2026-08-29 against Google's primary documentation:

- pricing: https://ai.google.dev/gemini-api/docs/pricing
- billing and spend caps: https://ai.google.dev/gemini-api/docs/billing#spend-caps
- Interactions storage: https://ai.google.dev/gemini-api/docs/interactions-overview
- retention controls: https://ai.google.dev/gemini-api/docs/zdr
- Gemini API terms: https://ai.google.dev/gemini-api/terms

Pricing and provider retention are volatile. The checked models.json catalog is
Banana's executable source for the current plan. Recheck the primary sources
before a release, procurement decision, or durable budget commitment.

## Nominal image-output estimates

| Model | Size | Standard | Google Batch |
|---|---:|---:|---:|
| gemini-3.1-flash-lite-image | 1K | $0.0336 | $0.0168 |
| gemini-3.1-flash-image | 512 | $0.045 | $0.022 |
| gemini-3.1-flash-image | 1K | $0.067 | $0.034 |
| gemini-3.1-flash-image | 2K | $0.101 | $0.050 |
| gemini-3.1-flash-image | 4K | $0.151 | $0.076 |
| gemini-3-pro-image | 1K or 2K | $0.134 | $0.067 |
| gemini-3-pro-image | 4K | $0.24 | $0.12 |
| gemini-2.5-flash-image | About 1K | $0.039 | $0.0195 |

Each Banana plan uses estimate_basis: nominal_one_output. The displayed
image_output_rate_usd is the current nominal rate for one output at the chosen
model and size. estimated_image_output_usd is that nominal rate multiplied by
the planned provider requests.

This is not a spend cap or final invoice. estimate_is_invoice_cap is false and
output_count_uncertain is true. A provider response can contain a different
number of image outputs, and billing applies to actual output. Input text,
reference images, text output, thinking output, and Google Search queries can
add charges. Grounding can run more than one provider search query for one user
request.

Configure a project-level monthly spend cap in AI Studio before paid use.
Google currently labels project caps experimental and documents about ten
minutes of billing-signal latency, during which overages can occur. Treat the
provider cap, Banana's exact-plan approval, and the private ledger as three
different controls; none makes the others redundant.

provider_attempt_count reports paid provider requests, not guaranteed output
images. A portfolio reports the sum across items, its selected workers, and the
hard max_concurrency of 3. It contains no more than nine total provider
attempts and no more than three concurrent attempts.

## Provider-success accounting order

Before provider I/O, Banana derives one non-secret, approval-bound
`attempt_sha256` for the exact provider attempt. Once a provider response has
been parsed successfully, Banana records that digest and the actual number of
returned image outputs in the private estimate ledger before publishing image
or sidecar files. This keeps a later artifact-publication failure from silently
omitting a known billable success. The record remains a nominal image-output
estimate and can exclude input, thinking, text, reference, and Search charges.

The digest makes an exact replay idempotent, so replaying the same recorder
operation does not increase totals. If ledger publication completes but final
verification raises, Banana rereads under the held ledger lock and reports
`recorded` only when exactly one entry matches the expected digest and complete
normalized payload.

Ledger failure does not authorize a retry and does not erase the provider
result. Banana's top-level generate and edit results, including
post-provider artifact-error details, expose
`cost_recording_status`, `attempt_sha256`, `cost_log_recorded`, and
`unlogged_billable_attempt`:

These are generation-result fields assembled by the orchestration runtime.
They are not the return-field names of the lower-level `record_generation`
ledger primitive, whose internal `status` and `logged` values are normalized
before the public result is returned.

- `recorded`: the exact record is present, including an idempotent replay or a
  verified reread after a save error; the booleans are `true` and `false`;
- `not_recorded`: valid held-lock reconciliation proved the digest absent; the
  booleans are `false` and `true`;
- `unknown_requires_reconciliation`: presence or absence cannot be proved; both
  booleans are `null`, and no output may describe the attempt as unlogged.

If `KeyboardInterrupt`, `SystemExit`, or another raw process-control exception
lands after provider success while the recorder is returning, Banana performs
one read-only exact-attempt reconciliation under the ledger lock. It then raises
`cost_recording_interrupted_after_provider` from the original interruption with
the tri-state and safe attempt details. It does not insert an absent ledger
entry, publish image artifacts, retry the provider, or allow a second
reconciliation interruption to escape raw.

Reconcile `not_recorded` or `unknown_requires_reconciliation` against the
private ledger and provider billing record without making another generation
request. A provider response that cannot be parsed is a known billable attempt
with `not_recorded`, because the output count required for the ledger is not
available.

Current image-model pricing tables show no free API inference tier. A user can
create an API key, but image calls require a billing-enabled project.

## Storage and retention disclosure

The 2026-08-29 catalog records these provider rules:

- Banana explicitly sends store: false for one-shot Interactions requests;
- a stored paid Interactions request defaults to 55 days, with project
  retention options of 7, 14, 28, or 55 days;
- Banana cannot inspect the project's configured Interactions retention period;
- Search-grounded request and response data has mandatory 30-day provider
  retention, independent of store: false.

When store is true, show provider_storage_retention_default_days,
provider_storage_retention_options_days,
provider_storage_setting_inspectable, and provider_storage_warning. Do not
claim the user's project is set to a shorter option unless they verify it
outside Banana. When Search is enabled, show
search_provider_retention_days and search_provider_retention_mandatory.

## Approval disclosure

Before each paid attempt, show:

- the exact compiled prompt, plus stable variant IDs and exact prompts for a
  portfolio;
- the normalized visual brief in the compact approval summary, its
  `brief_sha256`, disclosed source, and whether a supplied brief was required;
- request fingerprint, approval ID and expiry, catalog date, model, API surface,
  and endpoint;
- provider attempt count and output-count uncertainty;
- image-output rate, nominal estimate basis, nominal total,
  estimate_is_invoice_cap: false, and excluded charges;
- ratio, size, destination, MIME type, label, and prompt-recording choice;
- every reference's non-sensitive disclosure alias, brief-bound authority
  statement, MIME type, byte count, hash, Banana prompt role, semantic purpose,
  and subject ID, or the video URL;
- Search state and retention;
- storage, continuation, configured-retention visibility, default, options, and
  warning.

Obtain explicit approval for that exact plan. The approval ID is single-use and
expires after 30 minutes. A change to a prompt, model, size, grounding, storage,
references, destination, format, label, or prompt-recording choice needs a new
plan. Catalog verification date and exact nominal estimate are fingerprint
inputs, so a catalog or price update invalidates an older plan.

## True Google Batch API

Google Batch is an asynchronous generateContent workflow, normally targeted for
completion within 24 hours. It offers discounted inference and separate
batch-oriented limits. Inline jobs suit smaller payloads, while larger jobs use
JSONL through the Files API.

Banana's batch.py validates a CSV variation plan only. It does not submit a
Google Batch job. --provider-batch selects discounted estimation but performs
no provider call. Do not claim the discount was used unless a real Batch job
was submitted and verified.

## Working-directory-independent ledger commands

    python3 "$CLAUDE_SKILL_DIR/scripts/cost_tracker.py" estimate \
      --model gemini-3.1-flash-image --resolution 2K --count 3

    python3 "$CLAUDE_SKILL_DIR/scripts/cost_tracker.py" log \
      --model gemini-3.1-flash-image --resolution 2K \
      --count 1 --label "approved homepage concept"

    python3 "$CLAUDE_SKILL_DIR/scripts/cost_tracker.py" today
    python3 "$CLAUDE_SKILL_DIR/scripts/cost_tracker.py" summary
    python3 "$CLAUDE_SKILL_DIR/scripts/cost_tracker.py" reset --confirm

## Upgrade a 1.4.1 ledger

Version 1.4.1 wrote an unversioned ledger at the same path and stored a short
raw prompt snippet in each entry. Version 3 fails closed on that format during
normal logging and reporting. Migrate it explicitly, never by editing in place:

    python3 "$CLAUDE_SKILL_DIR/scripts/cost_tracker.py" migrate-v1 --dry-run
    python3 "$CLAUDE_SKILL_DIR/scripts/cost_tracker.py" migrate-v1 \
      --confirm FINGERPRINT_FROM_DRY_RUN

The dry run is read-only. It recognizes only the exact 1.4.1 structure,
validates its counts and finite non-negative costs, prints no raw prompt, and
returns a fingerprint bound to both the source bytes and the complete proposed
schema-1 ledger. Confirmation locks and rereads the ledger, rejects a changed
fingerprint, creates an exclusive timestamped byte-for-byte backup under
`$BANANA_HOME/backups`, revalidates the claimed source, and only then installs
the active ledger if the source path is still free. A concurrent legacy write
remains active or in that backup instead of being overwritten. Ordinary typed
failures after claim retain the intended legacy inode, its last known path, and
the separately observed active and backup entries for identity-based recovery.
For a catchable `KeyboardInterrupt` or `SystemExit` before publication, Banana
may atomically publish an independently verified `0600`, single-link copy of the
exact held legacy bytes to a still-free active name while keeping the exact
private backup, then preserves the original interruption. After publication,
it preserves the interruption only when the exact migrated active bytes and
exact legacy backup are both proven. A racer or ambiguous state is never
overwritten and becomes `migration_recovery_failed`.
If an uncatchable termination leaves the active ledger absent beside a strictly
named migration backup, a later load raises
`cost_migration_recovery_required`; it never reports an empty ledger or selects
a backup automatically.
On POSIX, confirmation holds the source and backup parents through
descriptor-relative claim, backup permission change, bounded reread, exclusive
publication, and final verification. It rejects a changed parent identity or a
multiply linked source before redirected writes or chmod. The backup and
directory are private where supported. Ledger and lock reads are bounded to
regular files. Symlinked lock or ledger paths fail closed, and the lock must be
a private, single-link regular file on POSIX systems.

The active migrated ledger preserves validated totals, dates, models,
resolutions, and recorded costs. It does not retain the legacy raw prompt
snippets. Each migrated entry carries an explicit redaction marker instead.
The private backup still contains the original snippets, so retain or remove it
according to the user's data policy only after the migrated ledger is verified.
Migration performs no provider request.

The ledger is stored at $BANANA_HOME/costs.json, defaulting to
~/.banana/costs.json. It uses a stable cross-process lock and atomic replacement
so concurrent completions do not lose entries. Directories are private where
Unix permissions are supported.

Provider interaction IDs remain transient. Cost logging validates an ID only
long enough to compute an optional `interaction_id_sha256` value and never
serializes the raw identifier. Earlier schema-1 ledgers containing a valid raw
`interaction_id` are normalized to the digest in memory. The next locked
summary, today, or successful logging operation atomically rewrites that
canonical form without printing the identifier. An unsafe or ambiguous legacy
identifier fails closed with a generic ledger error.

The ledger fails closed on corrupt or deeply nested JSON, unknown or extra
schema fields, malformed entries, invalid container or count types,
inconsistent entry, daily, or top-level totals, unsafe retained text, and
non-finite or negative costs. It does not overwrite the damaged record. Use the
explicit 1.4.1 migration only when its dry run validates the exact source. Move
any other damaged record aside or repair it deliberately.

Raw prompts are not logged. Use a short non-sensitive label. Image sidecars
store a prompt hash by default and store the raw prompt only after the user
chooses record_prompt. Grounding citations, links, Grounded Result text, and
Search Suggestions are never written to the ledger or sidecars.
