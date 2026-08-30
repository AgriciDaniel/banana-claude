## Summary

<!-- Lead with the outcome and why it matters. -->

## Changes

-

## Verification

<!-- List exact commands and results. Separate offline, plugin, and paid live checks. -->

- [ ] `python3 -m pip install --disable-pip-version-check -r requirements-dev.txt`
- [ ] `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`
- [ ] `ruff check skills/banana/scripts tools tests`
- [ ] `ruff format --check skills/banana/scripts tools tests`
- [ ] `mypy --strict --no-incremental skills/banana/scripts tools tests`
- [ ] `PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q skills/banana/scripts tools tests`
- [ ] `claude plugin validate --strict .`
- [ ] `bash -n install.sh`
- [ ] `git diff --check`
- [ ] No secret, key-bearing URL, raw private media, or full environment dump is included
- [ ] Current provider claims have a primary source and verification date
- [ ] No passing test asserts behavior contradicted by the current primary source
- [ ] Any paid live call was explicitly approved, bounded, and reported separately

## Risk and rollback

<!-- State blast radius, irreversible effects, and how to undo the change. -->

## Open items

<!-- State known gaps and deliberately skipped checks. Use "None" when empty. -->
