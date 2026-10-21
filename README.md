<p align="center">
  <img
    src="screenshots/banana-claude-character-loop.gif"
    alt="Banana Claude character cycling through thirty artistic urban looks while the Banana Claude title and pixel banana remain fixed"
    width="960"
  >
</p>

<h1 align="center">Banana Claude</h1>

<p align="center">
  <strong>Create, edit, compare, and review Gemini images from Claude Code.</strong>
</p>

<p align="center">
  <a href="https://github.com/AgriciDaniel/banana-claude/actions/workflows/validate.yml"><img alt="Validation" src="https://github.com/AgriciDaniel/banana-claude/actions/workflows/validate.yml/badge.svg"></a>
  <a href="https://github.com/AgriciDaniel/banana-claude/releases/latest"><img alt="Version 3.1.0" src="https://img.shields.io/badge/version-3.1.0-ff7b6b"></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/License-MIT-f4c542"></a>
</p>

Banana Claude turns a plain-language creative request into a planned and
reviewable Gemini image workflow. It shows the prompt, model, data settings,
output destination, and nominal estimate before any paid request.

## Start here

Requirements: Claude Code 2.1.199 or newer, Python 3.11 or newer with `python3`
on `PATH`, and a Gemini API key for a billing-enabled Google AI project.
Image generation and editing run on Linux and macOS. Native Windows is not yet
supported because output publication needs an atomic no-replace rename that the
client does not implement there; planning fails with
`output_exclusive_rename_unavailable` before any provider call. Use WSL on
Windows.

```text
/plugin marketplace add AgriciDaniel/banana-claude
/plugin install banana-claude@banana-claude-marketplace
/plugin enable banana-claude@banana-claude-marketplace
/reload-plugins
```

Then ask for the image you want:

```text
/banana-claude:banana generate an urban 16:9 GitHub hero with clean left-side copy space
```

Banana Claude plans offline first. Review the exact plan, then approve the paid
request when it matches your intent.

## The workflow is simple

1. **Ask:** describe the outcome in normal language.
2. **Plan:** Banana Claude builds the visual brief and chooses a route.
3. **Review:** inspect the prompt, references, privacy settings, and estimate.
4. **Approve:** one short-lived approval authorizes one provider attempt.
5. **Create:** the image and a privacy-conscious metadata sidecar are saved.
6. **Check:** review the actual pixels, then fix, regenerate, or ship.

## What you can make

- **Generate:** campaign visuals, covers, product scenes, diagrams, concepts,
  social assets, and more.
- **Edit:** make one clear change while protecting identity, geometry, and brand
  details.
- **Continue:** iterate with stored Nano Banana 2.1 or Pro sessions, or attach
  the last result as a fresh reference.
- **Compare:** test up to three prompts across three model routes in one bounded
  portfolio.
- **Review:** check copy, crop, composition, consistency, artifacts, rights, and
  provenance.
- **Typeset:** add approved copy, fonts, logos, and trusted raster art locally
  when exact text matters.

Banana Claude routes across Google's current Nano Banana 2.1 (the default),
Nano Banana 2 Lite, and Nano Banana Pro models, and keeps the deprecated Nano
Banana 2 route only for 512 drafts. See the dated
[Gemini model reference](skills/banana/references/gemini-models.md) for current
capabilities and pricing.

## Built for control

- The plugin installs disabled because image generation is a paid service.
- API keys stay out of commands, request URLs, metadata, and public CI.
- Every paid tool shows its plan and requires a user decision before execution.
- One approval permits one provider attempt. A changed plan needs a new
  approval.
- Cost records stay private and omit raw prompts by default.
- Generated output is never treated as automatically correct or production
  ready.

Gemini output is probabilistic. Banana Claude cannot guarantee consistency,
spelling, geometry, policy acceptance, rights clearance, or a final invoice.
Those remain review conditions, not marketing claims.

Read [Security and privacy](SECURITY.md) before production use.

## Documentation

- [User guide](docs/guide.md): installation, upgrades, workflows, and direct
  scripts
- [Prompt craft](skills/banana/references/prompt-engineering.md): visual briefs,
  consistency, composition, and recovery
- [MCP tools](skills/banana/references/mcp-tools.md): planning and execution
  contracts
- [Security](SECURITY.md): credentials, approvals, outputs, state, and reporting
- [Changelog](CHANGELOG.md), [version 3.1 release notes](.github/releases/v3.1.0.md),
  and [version 3 release notes](.github/releases/v3.0.0.md)

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening
a pull request. For help or a reproducible bug, open an issue without keys,
private media, or full environment dumps.

## License

MIT License, see [LICENSE](LICENSE).

Built by [Agrici Daniel](https://agricidaniel.com/about), AI Workflow Architect.

[Blog](https://agricidaniel.com/blog) ·
[AI Marketing Hub](https://www.skool.com/ai-marketing-hub) ·
[YouTube](https://www.youtube.com/@AgriciDaniel) ·
[More open-source projects](https://github.com/AgriciDaniel)
