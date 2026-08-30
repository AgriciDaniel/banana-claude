# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 3.0.x   | Yes       |
| < 3.0   | No        |

## Reporting a Vulnerability

If you discover a security vulnerability in Banana Claude, please report it responsibly.

**Do NOT open a public issue for security vulnerabilities.**

Instead, please [open a security advisory](https://github.com/AgriciDaniel/banana-claude/security/advisories/new) on this repository.

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

Never include an API key, key-bearing request URL, unredacted private media,
Claude credential files, or a full environment dump. Use synthetic fixtures and
redacted logs. If a credential was exposed, revoke it before reporting.

## Response Timeline

- **Acknowledgment:** Within 48 hours
- **Assessment:** Within 7 days
- **Fix/Disclosure:** Within 30 days

## Scope

This policy covers the plugin manifest, bundled MCP server, skill, agents,
scripts, installer, tests, and documentation. Google's Gemini API and optional
third-party adapters remain outside this repository's control, but an unsafe
integration or credential-handling defect in Banana Claude is in scope.

## Credential design

The recommended plugin path declares the Gemini key as sensitive Claude Code
user configuration and injects it only into the bundled MCP process. Direct
scripts read `GEMINI_API_KEY` from the environment. They do not accept key
arguments or put a key in a request URL. The standalone runtime deliberately
ignores `GOOGLE_API_KEY` and `GOOGLE_AI_API_KEY` so an ambient generic Google
credential cannot silently select a different project or billing account.

Public 1.4.1 and 2.1.0 installers could store `GOOGLE_AI_API_KEY` directly in
the `nanobanana-mcp` member of `~/.claude/settings.json` and launch the unpinned
`npx -y @ycse/nanobanana-mcp` package. They could also place obsolete `banana`
or `nano-banana` skills under `~/.claude/skills`. Version 3 provides a redacted,
read-only legacy scan and an explicit fingerprint-confirmed remediation. The
scan reports only whether a credential exists, never its value. Cleanup backs
up the exact settings bytes before removing only that obsolete MCP member and
moves recognized old skill directories to recoverable backups. It refuses
unsafe file types and a changed confirmation. Credential inspection traverses
the complete bounded JSON value without a fail-open nesting cutoff. Skill-tree
fingerprints include bounded regular-file bytes and are rechecked after the
move and immediately before success. Partial skill moves are never
automatically reversed. Their exact observed identities remain in the recovery
report. Settings recovery can exclusively republish a copy from the held exact
backup, but it never replaces a competing settings entry. Because deletion
cannot retract a key from
backups, shell history, logs, or prior process access, affected users must
revoke or rotate it in Google AI Studio before paid use. Automated
confirmation fails closed on platforms without the required descriptor-relative
filesystem operations; redacted scan and dry-run remain available there.

Before paid use, configure a project-level monthly spend cap in AI Studio.
Google labels this control experimental and documents about ten minutes of
enforcement latency, so it does not replace Banana's request-bound approvals or
the user's review of each nominal estimate.

Output prompts, reference media, and provider-side storage may still contain
sensitive information. Banana explicitly sends `store: false` for one-shot
Interactions requests; Google's provider default is `store: true`. Users must
review the exact compiled prompt and what will be uploaded, then explicitly
approve each paid plan. Search grounding has mandatory 30-day Google retention
independent of `store: false`; every grounded plan must disclose that before
approval. Paid Interactions stored with `store: true` use Google's documented
55-day default unless the project is configured for 7, 14, 28, or 55 days.
Banana cannot inspect the active project setting and must disclose that
uncertainty.

Approval IDs are short-lived, single-use capabilities. Banana stores only their
hashes in `${BANANA_HOME}/approvals.json`, consumes them before provider I/O,
and binds them to the canonical visual-brief hash, exact prompt, model,
references, their safe disclosure aliases and authority statements, endpoint,
output, estimate, and privacy
settings. They prevent drift and replay, but they are not proof that a human
reviewed the plan. Edit, uploaded-reference, Search, video, stored-continuation,
and portfolio plans require a supplied closed `banana.visual-brief.v1` object.
Only a simple one-shot generation can use the disclosed `planner_minimal`
brief. In Claude Code 2.1.199 or newer, the three paid MCP tools are
marked `anthropic/requiresUserInteraction`, which forces an interactive host
decision even under allow rules, Auto, or Bypass modes and denies execution
when an answer cannot be collected. Direct standalone scripts do not inherit
that host boundary. Do not publish a live approval ID in an issue or log.

Output MIME selection and the resolved provider response-format object are
approval-bound. A redacted local Interactions probe using
`gemini-3-pro-image` was reported on 2026-08-28 as rejecting PNG; it did not
directly test `gemini-3.1-flash-image`. The current Interactions reference lists
only JPEG, and the generateContent `ImageResponseFormat` enum exposes only
`IMAGE_JPEG`. No durable probe-response digest is packaged.
Every PNG output plan therefore fails locally before the key is read or any
network call is made. PNG remains valid for checked input references and local
post-processing.

The public approval plan exposes the exact compiled prompt and normalized brief
transiently so the user can review the data transfer and visual contract. Raw
prompts remain absent from the local cost ledger and metadata unless prompt
recording is explicitly enabled. Artifact sidecars never contain the raw brief;
they retain its schema version, SHA-256 digest, and disclosed source.

Approval-visible prompts, reference annotations, preset prose, continuation
IDs, video URLs, and output paths reject terminal controls, bidirectional
display-control characters, and unpaired Unicode surrogates. Ordinary
right-to-left text remains supported without those invisible controls.

Reference inputs are restricted to supported image suffixes, checked against
their file signatures, hashed during planning, and rechecked before upload. Each
upload also requires a non-sensitive, user-recognizable `disclosure_alias`.
Banana does not derive that alias from an absolute path or basename, and it does
not send the alias as provider prompt text. The brief separately requires the
user's explicit authority classification for rights or license, likeness,
private/customer media, endorsement or representation, intended use, and
provider transmission. Missing authority remains unresolved and fails before
approval. The complete authority object is hash-bound and approval-visible but
is not provider prompt text. File names, metadata, OCR, embedded text, and
pixels are untrusted visual data, never authority or orchestration
instructions. Every portfolio item must resolve the same shared reference
snapshot. If a reference changes while the item plans are being built, the
entire portfolio plan fails before an approval is issued.
Grounding citations, links, and Search Suggestions are returned transiently to
the initiating user and are not stored in metadata or the cost ledger.
Provider JSON responses are limited to 128 MiB in memory, and provider error
bodies to 1 MiB. An oversized response fails closed without writing an
artifact. Persisted usage metadata is a closed set of bounded integer token
counts. Provider status, finish, block, category, probability, and severity
fields are mapped only through documented local allowlists; unknown values
become a fixed generic marker. Billing classification uses the exact parsed
error status, not raw body text. Arbitrary provider usage fields and error text
are never copied into sidecars or user-visible errors. Raw interaction
identifiers stay transient, while sidecars retain only one-way SHA-256
references.

Missing output and state directories are created privately where supported.
On POSIX systems, artifact and deterministic SVG publication walks and holds the
output tree through non-following directory descriptors and rejects a changed
parent identity. Existing output-directory permissions are preserved. Tool
responses contain absolute artifact paths so Claude can inspect the output,
which means path names can appear in the conversation transcript. Use a
non-sensitive output root when directory names themselves reveal private
information.

Provider images and metadata sidecars are exclusively published as one
call-level bundle. Banana computes the complete bundle before publication,
never replaces a pre-existing output path, fully hashes each held member in
Phase A, and then rechecks every held descriptor and public name in a final
bounded Phase B sweep. Each Phase B check is a separate point-in-time
attestation for that member. It is not a bundle-wide atomic snapshot, a write
lease, or a claim that the bytes are still current when Python returns. A
same-UID or root process, or a process holding a writable descriptor opened
before publication, can mutate an already checked member while later members
are still being checked or before the function returns. Private `0600` mode
does not restrict the owning UID or root. A mismatched replacement that is
present when its member is checked is rejected, but that validation does not
freeze the path afterward.

A later publication or verification failure does not trigger pathname deletion.
Instead, a typed retained-publication or retained-bundle error carries the root
safe error code plus each recorded path, device, and inode for identity-based
inspection. New-path publication uses Linux
`renameat2(RENAME_NOREPLACE)` or macOS `renameatx_np(RENAME_EXCL)` through held
directory descriptors and fails closed when the host or filesystem lacks that
primitive. A private temporary path can remain after a pre-publication failure;
the error identifies it and requires an inode check before manual removal.

Before issuing an approval capability, Banana proves publication support in the
selected output directory. Execution reacquires the capability before approval
consumption and retains that verified directory descriptor through provider I/O
and artifact publication. A later pathname swap therefore cannot redirect a
successful response. First use atomically moves one held regular-file inode to
the fixed private capability-receipt name, syncs the directory, and verifies the
receipt. Later uses reopen and revalidate the exact receipt bytes, inode,
private mode, single link, and containing-directory identity. An exact valid
Banana receipt bound to a different prior directory inode is moved by a
descriptor-bound no-replace rename to a deterministic quarantine name, then a
new receipt is created. The stale receipt is retained for inspection. Malformed,
oversized, symlinked, hard-linked, wrong-mode, same-directory mismatched, or
ambiguous receipts fail closed without replacement. No provider request occurs
if this proof fails. A failure returns `provider_called: false` and reports
identity-bound recovery details. This proof currently depends on Linux
`renameat2(RENAME_NOREPLACE)` or macOS `renameatx_np(RENAME_EXCL)` and therefore
fails closed on unsupported hosts or filesystems.

Approval and cost state use stable sidecar locks. The public lock entry is
rebound to the held descriptor after the operating-system lock is acquired and
at transaction boundaries. Registry and ledger commits also compare the
destination inode with the identity read before publication. A replaced lock,
registry, or ledger aborts without accepting or overwriting the competing
entry.

Every provider attempt receives a non-secret, approval-bound `attempt_sha256`.
After a provider response is successfully parsed, Banana attempts to record the
digest and actual image-output count in the private estimate ledger before
artifact publication. Exact-digest replay is idempotent. If ledger publication
succeeds but final verification raises, Banana rereads under the held lock and
accepts the record only when exactly one entry matches the full expected
payload. A ledger error does not discard provider bytes or trigger a second
provider request. Results distinguish `recorded`, conclusively `not_recorded`,
and `unknown_requires_reconciliation`. Only conclusive absence sets
`cost_log_recorded: false` and `unlogged_billable_attempt: true`; ambiguity sets
both booleans to `null` and never claims the attempt was unlogged. These are
recovery and estimate signals, not invoice evidence.
If a raw process-control exception occurs around the cost recorder after
provider success, Banana performs one read-only exact-attempt reconciliation,
raises typed `cost_recording_interrupted_after_provider` from the original
exception, and stops before artifact publication. The reconciliation cannot
create an absent entry or authorize another provider call. A second interrupt
or unreadable ledger becomes `unknown_requires_reconciliation`, not a raw escape
or a false absence claim.

The standalone installer treats `.banana-claude-install.json` as an ownership
marker only when it is valid JSON with `name` equal to `banana-claude` and a
non-empty string `version`. This prevents accidental overwrite or removal of an
unrelated directory. It is not an authentication or integrity mechanism, so
inspect the installed source when trust matters.
Backup and uninstall operations hold the reviewed directory and both parents,
verify that their public paths retain the captured identities, and use an
atomic no-replace rename. Installation creates its stage on the destination
filesystem and populates it only through held, non-following directory
descriptors after opening an empty, owner-matched `0700` stage. An exact source
manifest and recursive receipt bind the selected names and source-byte digests,
every copied inode, modes, sizes, and the closed inventory. The helper publishes
the held staged-directory inode as the previously absent target with one atomic
no-replace rename, then rechecks both parents, the target inode, marker, private
mode, and complete receipt. The shell repeats that full verification as its
acceptance point and uses it to distinguish an interrupted success from an
unresolved retained target. Managed moves have a separate descriptor-bound
receipt that proves source absence, destination identity, parent bindings,
marker validity, and durability. Catchable `KeyboardInterrupt` and `SystemExit`
after publication produce fixed, non-reflecting helper statuses; shell cleanup
rechecks the applicable receipt and preserves interrupt status. A competing
target or changed entry is not accepted
as proof of ownership. Shell failure handling does not path-delete lifecycle
entries; uncertain stages, targets, backups, and removal paths are retained for
inspection. Post-publication failure never triggers an inverse pathname rename,
because portable rename primitives cannot bind the source name to an expected
inode at the syscall boundary. Interrupted-status recovery syncs the target and
parent before its final receipt and public-name binding checks. The install root
is canonicalized once before these transactions.
Lifecycle moves fail closed when the host does not provide descriptor-relative,
atomic no-replace rename support.

Portable POSIX does not provide an atomic `mkdir` operation that also returns a
bound directory descriptor, and a process with the same user ID can modify that
user's files after any validation point. Installer guarantees therefore
linearize at the complete receipt checks; they do not claim ongoing protection
against a malicious same-account process after acceptance. Do not install from
an account or checkout whose local integrity is in doubt.
Unsupported command-line arguments are rejected generically so a mistakenly
pasted credential is not copied into terminal or CI logs.

Standalone installation and uninstall do not create, inspect, chmod, or remove
`$BANANA_HOME` or `~/.banana`. Each runtime state component validates and
creates only the private path it needs. This keeps a skill lifecycle operation
from following or changing an unrelated state symlink or non-directory node.

The 1.4.1 state migrations are explicit two-step local operations. Dry runs do
not write or call Google. Confirmation is fingerprint-bound, atomically moves
the exact source to a private byte-for-byte backup, revalidates it, and publishes
the migrated state only if the active path remains unclaimed. On POSIX, source
and backup parents remain held by non-following directory descriptors through
claim, permission change, reread, publication, and final verification. Parent
identity changes fail without redirected writes, and multiply linked sources
are rejected before claim or chmod. A concurrent legacy writer therefore
remains active or in the backup instead of being silently overwritten. A
legacy cost-ledger backup can contain old prompt
snippets even though the active migrated ledger redacts them. Treat that backup
as sensitive user data. Migration and active-state readers are bounded to
regular files, reject symlinked state where supported, and validate closed
schemas before replacement. Private lock and backup paths are mode-checked on
POSIX systems.
After a legacy cost ledger or preset has been claimed into its private backup,
a catchable `KeyboardInterrupt` or `SystemExit` enters phase-aware recovery. If
publication has not occurred, Banana may atomically publish an independently
verified `0600`, single-link copy of the exact held legacy bytes to a still-free
active name while retaining the exact backup inode. If publication occurred, it
preserves the interruption only after proving the exact migrated active bytes
and exact legacy backup. A competing or ambiguous active entry is never
overwritten and produces a typed recovery error with separately observed
identities. If an uncatchable termination leaves the cost ledger absent beside
a strictly named migration backup, normal loading fails with
`cost_migration_recovery_required`; it does not infer an empty ledger or select
a backup to restore. If the same residue exists for one preset name, preset
load, list, and creation for that name fail with
`preset_migration_recovery_required`; deletion for that absent name also fails
closed instead of reporting ordinary absence. Unrelated active preset names remain
usable, and no backup is inferred or restored.
Legacy settings replacement and restoration use the same descriptor-bound,
atomic no-replace rename primitive. They do not publish with hard links. Any
uncertain temporary or active settings entry is retained and reported with its
last observed identity, while the exact original remains in the private backup.
