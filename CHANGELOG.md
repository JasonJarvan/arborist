# Changelog

All notable changes to Arborist are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); versioning aims at [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **AgentTUI registry** guide (`overlay/spec/guides/agenttui-registry.md`) — `.arborist/`
  global–project cascade, spec/runtime schema, self-registration and lifecycle; scaffold templates
  plus adopt wiring; explainer pages under `docs/wiki/`.
- **Tool registry / plugin layer** guide (`overlay/spec/guides/tool-registry.md`) — `tool.json`
  schema with requirement tiering (`required` / `optional` + `fallback`), init provisioning in
  `adopt.sh` / `ADOPT.md` (required = warn + instructions; optional = prompt → register or
  fallback), with agentsview and Multica as the first registered optional tools.

### Origin — forked from Arbor
Arborist is a fork of [Arbor](https://github.com/JasonJarvan/arbor) (Apache-2.0), reduced to the
**pure Trellis + HarnessStack harness with the CCB multi-agent runtime removed**. It is the
backend-agnostic core: workflow discipline, role tiering, sendbox handoff, and methodology — with
the transient live-coordination layer treated as a **pluggable extension point**. The layer that Arbor
bound to CCB is now backend-agnostic rather than tied to a specific runtime.

### Removed (relative to Arbor)
- **CCB integration** — deleted the `ccb-integration.md` guide, the `overlay/ccb-templates/` config
  seed, the CCB agentsview design spec, and every CCB command / config / dependency reference.
- **CCB as a pillar** — the README lineage, comparison tables, install steps, `NOTICE`, and
  `.gitignore` no longer reference `@seemseam/ccb` or `.ccb/`.

### Changed (relative to Arbor)
- **Transient coordination abstracted** — `roles-and-tiering.md` and `sendbox.md` now describe the
  transient backend as a pluggable extension point (no built-in), keeping durable orchestration on the
  sendbox file protocol.
- **Rebranded** Arbor → Arborist throughout, and `arbor-sync` → `arborist-sync`; lineage attribution to
  Arbor retained in README / NOTICE.

### Inherited from Arbor (unchanged)
- **Open-source under Apache-2.0** — `LICENSE` + `NOTICE`; the AGPL dependency (Trellis) is installed
  separately and not bundled.
- **Adoptable overlay** — guides, scripts, and `.work_context` templates laid via `adopt.sh`, kept
  invisible to the product repo through `.git/info/exclude` and versioned in a separate local
  `hgit` (`.harness-vcs`) history.
- **Discipline guides** — roles & tiering (L1–L4), four-level Execution Policy, layered RepoMem with
  document-boundary and promotion gate, multi-lens verification with a security-scan MR gate, the
  sendbox directed-handoff protocol, and the pending-actions Dashboard.
- **Nine methodology clusters** distilled from real projects (LLM testing, verification discipline,
  contract drift, MR/git discipline, dependency & migration, error handling, local docs, handoff
  attribution, and misc patterns).
- **`arborist-sync` skill** — bidirectional overlay sync between the template repo and an adopting
  instance, with de-privatization, AGPL-source and placeholder-integrity gates, and conflict mediation.
- **Install & adoption docs** — agent-driven `INSTALL.md`, one-shot `adopt.sh`, step-by-step
  `ADOPT.md`, and English + Chinese READMEs.

[Unreleased]: https://github.com/<owner>/arborist
