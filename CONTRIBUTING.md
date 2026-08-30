# Contributing to Banana Claude

Contributions are welcome! Here's how to help.

## How to Contribute

1. **Fork** the repository
2. **Create a branch** for your feature or fix
3. **Make your changes** and test them
4. **Submit a pull request** with a clear description

## What to Contribute

- Bug fixes
- New operation or capability routes backed by primary sources
- Improved brief, prompt, editing, and review patterns
- Documentation improvements
- Post-processing recipes

## Guidelines

- Keep `SKILL.md` under 500 lines and use progressive references.
- Update `models.json` first when model, capability, deprecation, or
  image-output pricing facts change. Add a primary source and verification date.
- Do not add guessed rate limits, free-tier claims, hidden prompt rules, API key
  arguments, key-bearing URLs, or live paid tests to CI.
- Treat the public 1.4.1 and 2.1.0 upgrade footprint as a security contract.
  Legacy scans must remain redacted and read-only; cleanup must remain explicit,
  fingerprint-bound, backup-first, and unable to overwrite concurrent settings.
- Add or update deterministic tests for every executable behavior change.
- Treat provider claims as test data, not timeless truths. A test that encodes a
  capability contradicted by a current primary source blocks release even when
  the suite passes.
- Separate documented provider limits from conservative Banana policies in the
  catalog, errors, tests, and prose.
- Install the pinned development-only verification tools with
  `python3 -m pip install --disable-pip-version-check -r requirements-dev.txt`.
- Run `python3 -m unittest discover -s tests -v`.
- Run `python3 -m compileall -q skills/banana/scripts tools tests`.
- Run `ruff check skills/banana/scripts tools tests` and
  `ruff format --check skills/banana/scripts tools tests`.
- Run `mypy --strict --no-incremental skills/banana/scripts tools tests`.
  Do not suppress a failure to make the gate green.
- Test as a plugin with `claude --plugin-dir .`.
- Validate with `claude plugin validate --strict .`.
- Run `bash -n install.sh` and `git diff --check`.
- Keep history in `CHANGELOG.md`; do not rewrite an older release entry to make
  it look current. Mark historical sections clearly enough that retrieval does
  not mistake them for current operating guidance.
- Follow the version locations in `CLAUDE.md` when preparing a release.

Before release, use a disposable Claude Code profile to load the plugin, inspect
the registered skill, agents, and MCP server, run an offline plan, and verify
that field drift is rejected. If a maintainer explicitly authorizes a paid
acceptance call, use a dedicated billing-enabled project, non-sensitive
fixtures, and a fixed small spend ceiling. Report secret substitution,
permission prompts, provider transport, and pixel review as separate results.
Never put a live provider call in public CI.

## Reporting Issues

Open an issue with:
- What you expected to happen
- What actually happened
- Steps to reproduce

Never include API keys, key-bearing URLs, credential files, full environment
dumps, or unredacted private reference media in an issue.
