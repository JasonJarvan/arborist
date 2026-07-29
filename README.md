# Arborist

> **A stronger agent harness for ultra-long-horizon coding — the Trellis + HarnessStack workflow & orchestration core.**
>
> Lineage: **[Trellis](https://www.npmjs.com/package/@mindfoldhq/trellis)** (workflow engine) × **CodeTeam methodology** (a distilled HarnessStack discipline layer).
>
> **Fork of [Arbor](https://github.com/JasonJarvan/arbor)** (Apache-2.0) with the CCB multi-agent runtime removed — see [Relationship to Arbor](#relationship-to-arbor).
>
> 中文说明见 [README.zh.md](./README.zh.md)。

`Apache-2.0` · `overlay for Trellis` · `deps: Trellis — AGPL, installed separately, not bundled` · [中文 README](./README.zh.md)

**What it is.** Arborist is an *adoptable overlay* that turns Trellis into a harness built to survive **ultra-long-horizon coding** — one goal spanning dozens of sessions, many concurrent sub-tasks, needing audit and rollback.
**Who it's for.** Teams (or a solo dev) running multi-session AI coding who have hit the wall where a single agent loses the plot across sessions, gates get silently skipped, and there is no clean way to roll a harness change back.
**What it solves.** It layers role tiering, explicit gates, layered memory, and semantic cross-session handoff on top of Trellis — **without ever polluting your product repo**, keeping the transient coordination backend pluggable (see below).

Two pillars:

- **Trellis** — the workflow engine (3 phases Plan/Execute/Finish, task system, per-turn breadcrumb).
- **CodeTeam methodology** — the discipline layer: L1–L4 role tiering, explicit gates (incl. auto-judge/HITL), layered memory (RepoMem + ADR + promotion gate + challenge-before-ack), multi-lens verification, sendbox semantic handoff, a pending-actions Dashboard, and a task ledger.

Two-layer orchestration division: **ledger = your issue tracker · durable semantic handoff = sendbox (the built-in, file-based channel)**. A **transient live-coordination** backend (a visible multi-window TUI, an A2A auto-reply runtime, …) is a **pluggable extension point** — the default build does not bundle one; out of the box, transient coordination is human-in-the-loop across concurrent sessions, or Trellis-native subagents for single-session fan-out.

Arborist is not a fork of Trellis. It is an **adoptable overlay** that never pollutes the product repo (`.git/info/exclude` + a separate local `hgit` history repo). It *is* a fork of Arbor — see below.

## What Arborist adds on top of Trellis

| Capability | Trellis native | Arborist adds |
|---|---|---|
| Role / task tiering L1–L4 | parent/child + subagents | explicit **RootOrche / SubOrche / Impler / subagent**, each running a tailored slice of the pipeline; lifecycle walkthroughs |
| Gates & audit | task/commit confirm | four-level **Execution Policy** (auto / **auto-judge** / ask-first / HITL) + Skip Bias + no-silent-skip audit |
| Layered memory | spec update + journal + mem | **three-tier epistemics** + ADR (with `Origin` traceability) + Document-Boundary table + Pairing Rules + **HITL promotion gate + challenge-before-ack** |
| Verification | single check | multi-lens: check + behavior self-verify + **dependency security-scan as a hard MR gate** + human smoke |
| Cross-session handoff | mem/journal (recall) | **sendbox** directed letters (absolute read_first + process-completeness + lifecycle/WIMTB) |
| Cognitive load | breadcrumb/statusline | **Dashboard** — one projection of "what does the human owe now" across sessions |
| Persistence | local files | task-ledger mirror (one task = one issue, parent/child ↔ L3/L2, WIMTB on finish) |
| Code intelligence | grep/glob | **codegraph** MCP (symbols/callers/impact) feeding red-team evidence + promotion discipline |
| Multi-agent orchestration | one-shot subagent | **role tiering + sendbox** durable handoff; transient live coordination is a **pluggable backend** (no built-in), tasks → ledger |
| No product-repo pollution | `.trellis/` committed | **`.git/info/exclude` overlay + separate `hgit` history** — versioned/rollbackable, never in feature branches/push |
| Methodology corpus | — | 9 `methodology/` clusters distilled from real projects |

## Who is this for

**Adopt Arborist if** you run AI coding across many sessions on one long goal, coordinate more than one agent at a time, and need the work to be auditable and reversible — and you want that discipline *without* committing harness files into your product repo.

**You probably don't need it (yet) if** your work is single-session, one-agent, short-horizon tasks — plain Trellis (or no harness at all) is lighter. Arborist's value shows up exactly when a session boundary, a concurrent sub-task, or a "how did we get here?" audit would otherwise cost you.

Everything beyond the base overlay is **opt-in**: the task ledger and codegraph are all optional. The minimum that delivers value is `adopt.sh` + pasting the workflow customization block.

## Install

**Option A — hand a prompt to an agent (recommended).** Paste the bootstrap prompt in [INSTALL.md](./INSTALL.md) into a fresh coding-agent session opened in your repo; it installs the dependencies (Trellis, and optionally codegraph), runs `trellis init`, clones Arborist, and runs `adopt.sh`.

**Option B — manual.**
```bash
npm i -g @mindfoldhq/trellis            # required; optional: codegraph
trellis init --claude --codex -u <your-name>
git clone https://github.com/<owner>/arborist.git /tmp/arborist
bash /tmp/arborist/adopt.sh                 # lays overlay, writes .git/info/exclude, builds local history repo
# restart your AI session
```
Step-by-step adoption + adaptation checklist: **[ADOPT.md](./ADOPT.md)**.

### What you get after adopting (minimal first run)

Into an otherwise untouched repo, `adopt.sh` lays down — all hidden from your product git via `.git/info/exclude`:

- `.trellis/spec/guides/` — the discipline + methodology guides ([index](./overlay/spec/guides/index.md)), read on demand by your agent during Plan/Execute/Finish.
- `.trellis/workflow.md` — after you paste the [customization block](./overlay/workflow-customization.md), the pipeline (gates, verification topology, promotion gate) is live.
- `AGENTS.md` + the workflow Phase Index — matching `ARBORIST-BRAND-COMPAT:v1` managed blocks keep Codex and Claude Code on truthful same-brand subagent chains.
- `.claude/agents/trellis-implement-full.md` + `trellis-explore.md` — fixed Opus/Sonnet routing for Claude Code without a global subagent-model environment variable.
- `.work_context/` — sendbox (directed handoff letters) + Dashboard (pending-actions projection) scaffolds.
- `.harness-vcs/` + `hgit` — a separate local history for the harness, so `hgit log` / `hgit checkout <sha>` roll changes back independent of your product `git`.

Restart your AI session and the guides + workflow customization take effect. `git status` on your product repo stays clean — none of the above is visible to it.

## Architecture: overlay + local history repo

- **Overlay** — `overlay/` lays into your project's `.trellis/spec/guides/`, `scripts/`, `.work_context/` templates + a workflow.md customization block.
- **Invisible to the product repo** — those paths go into `.git/info/exclude` (per-clone, uncommitted) → product repo / feature branches / push never see them.
- **Rollbackable** — a separate git repo (`.harness-vcs`, no remote) + an `hgit` wrapper versions the harness; `hgit log` / `hgit checkout <sha> -- <path>` to roll back, decoupled from product `git`.
- **Team / multi-machine** — `hgit remote add` + push to share; or Trellis's native `--workflow-source`.

Three repos, kept deliberately separate:

```
        ┌──────────────────────────────────────┐
        │  Arborist template repo (this repo)      │   Apache-2.0
        │  overlay/ guides · scripts · templates│   generic; placeholders <REPO_ROOT>/<project>
        └───────────────────┬──────────────────┘
                            │  adopt.sh  (lay overlay + specialize placeholders)
                            ▼
  ┌──────────────────────────────────────────────────────────┐
  │  Your product repo  (git)                                 │
  │                                                           │
  │    src/  ...................  your code — committed/pushed │
  │    .trellis/spec/guides/  ...  overlay (the harness)       │
  │    .git/info/exclude  ........  makes the overlay          │
  │                                 INVISIBLE to product git   │
  └───────────────────────────┬──────────────────────────────┘
                              │  harness changes versioned by
                              ▼
  ┌──────────────────────────────────────────────────────────┐
  │  .harness-vcs   (hgit — local git repo, no remote)        │
  │    hgit log   ·   hgit checkout <sha> -- <path>  (rollback)│
  └──────────────────────────────────────────────────────────┘
```

Your product remote never sees the harness; the harness has its own history you can roll back; Arborist upstream stays generic so improvements flow both ways (see [`arborist-sync`](./skills/arborist-sync/SKILL.md)).

## Guides

The core of Arborist is its discipline + methodology guides, laid into `.trellis/spec/guides/`. Full index with "when to read" cues: [`overlay/spec/guides/index.md`](./overlay/spec/guides/index.md).

| Guide | What it covers |
|---|---|
| [Roles & tiering L1–L4](./overlay/spec/guides/roles-and-tiering.md) | RootOrche / SubOrche / Impler / subagent + per-tier pipeline slices + lifecycle scenarios |
| [Execution Policy & Skip](./overlay/spec/guides/execution-policy.md) | four-level gates (auto / auto-judge / ask-first / HITL) + Skip Bias + no-silent-skip audit |
| [RepoMem: doc boundary & promotion](./overlay/spec/guides/repomem-doc-boundary.md) | three-tier epistemics + Document-Boundary authority table + Pairing Rules + persist discipline |
| [Verification & Gates](./overlay/spec/guides/verification-and-gates.md) | multi-lens verification + security-scan hard MR gate + review + challenge-before-ack |
| [Sendbox handoff](./overlay/spec/guides/sendbox.md) | cross-session directed letters (absolute read_first + process-completeness + lifecycle/WIMTB) |
| [Dashboard](./overlay/spec/guides/dashboard.md) | single projection of "what does the human owe now" across sessions |
| [AgentTUI registry](./overlay/spec/guides/agenttui-registry.md) | peer discovery for concurrent sessions: `.arborist/` cascade + spec/runtime schema + declared/derived state model + self-registration |
| [Safe AgentTUI launch + brand-capacity observer](./overlay/spec/guides/agenttui-launch-and-brand-capacity.md) | safe-launch invariants (one AgentTUI per tab, clear inherited identity, resolve a stable non-plugin pane, launcher picks the binary while the session self-registers its brand) + a single-writer, no-credentials capacity observer with explicit source/freshness and Impler-creation-only recommendation |
| [Tool registry](./overlay/spec/guides/tool-registry.md) | optional-capability plugin layer: `.arborist/tools/` cascade + `tool.json` schema + required/optional provisioning with per-tool fallbacks |
| [Knowledge close-out](./overlay/spec/guides/knowledge-closeout.md) | post-delivery repo-wide knowledge-consistency gate: fact-surface matrix + two-phase report + trigger tiering (run by the close-out owner; covers what trellis-check's change-scope misses); manually triggerable from any lane via `/neat`, `neat skill`, or `洁癖 skill` |
| [HS 15-step mapping](./overlay/spec/guides/pipeline-mapping.md) | HarnessStack 15-step → Trellis phases / guides crosswalk |
| [Methodology clusters](./overlay/spec/guides/methodology/index.md) | 9 clusters (LLM testing / verification / contract drift / MR / dependencies / errors / local docs / handoff attribution …) |
| [ADR template](./overlay/spec/guides/decisions/TEMPLATE.md) | architecture decision record (three-gate self-check + `Origin` traceability) |

Deep-dive explainers (timelines, state machines, walkthroughs) live in [`docs/wiki/`](./docs/wiki/index.md); the guides above stay canonical.

## Adaptation surface

Replace placeholders when adopting: `<REPO_ROOT>` (your repo's absolute path), task-ledger env (Multica, or your own tracker), subtree/language + security scanners, git/MR conventions, local-docs convention. See ADOPT.md.

## Layout

```
overlay/spec/guides/            # discipline + methodology guides (the core)
overlay/scripts/                # trellis_multica_sync.py (env-configured) + hgit
overlay/project-instructions/   # Codex-visible managed instruction sources
overlay/platform-templates/     # platform-specific managed agent templates
overlay/work_context-templates/ # sendbox (toAgent/toHuman) + Dashboard scaffolds
overlay/workflow-customization.md  # the workflow.md customization block
scripts/                        # brand-compat installer + validator
skills/arborist-sync/              # bidirectional overlay sync (de-privatize + conflict mediation)
skills/arborist-relocate-project/  # safe project rename: registries + chat-history coordination
INSTALL.md · adopt.sh · ADOPT.md   # install prompt + one-shot adopt + guide
```

## Relationship to Arbor

Arborist is a **fork of [Arbor](https://github.com/JasonJarvan/arbor)** (Apache-2.0). Arbor's lineage is
**Trellis (workflow engine) + HarnessStack (multi-agent orchestration discipline) + CCB (a visible,
multi-window TUI / A2A communication runtime)**. Arborist keeps the first two and **removes CCB entirely** —
it is the backend-agnostic harness core.

**What changed vs Arbor: the CCB runtime was removed, and transient live-coordination became a pluggable extension point.**

| | Arbor | Arborist |
|---|---|---|
| Trellis workflow kernel | ✅ | ✅ |
| HarnessStack discipline (roles, gates, RepoMem, verification, methodology) | ✅ | ✅ |
| Sendbox durable file handoff | ✅ | ✅ |
| Transient live-coordination runtime | **CCB** (built-in, tmux-pane agents + `ask`) | **pluggable extension point, no built-in** |
| Dependency footprint | Trellis + optional CCB | Trellis only |

**Why fork.** Some adopters want the workflow + orchestration discipline without committing to any
specific terminal multiplexer or A2A backend. Arborist is that layer: durable orchestration rides the
sendbox file protocol, and a transient backend can be attached out-of-band if desired. Improvements flow
between the two via generic, backend-neutral guides.

## Contributing

Arborist is a corpus of generalized engineering discipline — contributions of new methodology clusters, guide improvements, and adopt/sync tooling are welcome. Ground rules: keep guides generic (placeholders, no absolute paths / internal names / secrets), never paste text sourced from the AGPL dependencies, and use English commits. See **[CONTRIBUTING.md](./CONTRIBUTING.md)**.

## License

Arborist itself (guides / scripts / config templates / docs) is open-source under Apache-2.0 — see [`LICENSE`](./LICENSE).

**Dependencies are separate and not bundled**: Trellis (AGPL-3.0-only) and optional codegraph / Multica are installed by you and remain under their own licenses. Arborist interoperates with them **via the CLI as separate processes** — it is an interoperability overlay, not a derivative work, and redistributes none of their code.
