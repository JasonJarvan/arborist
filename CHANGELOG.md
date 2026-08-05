# Changelog

All notable changes to Arborist are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); versioning aims at [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **AgentTUI registry consistency gate** (`overlay/scripts/validate_agenttui_registry.py` + 37 tests,
  `agenttui-registry.md` §2.2.1/§2.3/§3/§4, `verification-and-gates.md` gate matrix, adopt-wired) —
  the guide already specified both `half-registered` directions and had **no enforcer at all**, which by
  this repo's own "a gate with no enforcer is decoration" rule made it decoration. Six checks now run
  over the global index plus every project leaf tree: `session_id` global uniqueness (one session belongs
  to one project, **not** state-restricted), `(multiplexer, session, pane_id)` uniqueness **checked
  independently** of it (two *different* sessions naming one pane means a `pane_ref` has already rotted)
  and **only among reachable leaves** — panes get **reused in sequence**, so a stopped leaf still holding
  the old triple is the normal aftermath, and reporting that as a collision would flood the report;
  it becomes a separate low-severity `stale-addressing-handle` **warning** that does not affect the exit
  code, kept readable apart from the high-severity `pane-ref-conflict` because the two want opposite
  handling (stop and fix vs. sweep up later) — half-registered
  direction A (summary, no leaf) and B (leaf, no summary), leaf `project` self-consistency with
  `project_id` **recomputed** from `realpath`, and index-summary vs leaf agreement on
  `role`/`brand`/`state`/`lineage` with the **leaf authoritative**. Every failure names the **full paths
  of both sides**. Exit `0/1/2`; a missing or unparsable global index is **exit 2 fail-closed** ("cannot
  read the index" is not "nothing to check"), while one dead project path is reported and the remaining
  projects are still checked. **Read-only on purpose — there is no `--fix`**: deciding which project a
  session belongs to, and deleting a leaf in someone else's repo, is another lane's call.
  The guide also gains the consequence ordering — **mis-delivery (a claimed/rotted `pane_ref`) outranks
  unreachability (half-registered)**, because unreachability fails loudly to the sender alone while
  mis-delivery is silent and charges the cost to an uninvolved third-party session.
- **Five "the registry looks fine but delivery still doesn't land — or lands wrong" shapes + a legitimate
  use for `dump-screen`** (`agenttui-registry.md` §3) — sandbox half-deafness (can be injected into,
  **cannot send**), expired auth (bytes arrive, submit key works, target CLI cannot process, transcript
  keeps **no trace**), long-text corruption without submit, **delivered-but-verified-too-early** (the
  nonce *is* in the target transcript; the verify window was `10 × 0.1s` = **one second** and ran before
  the target CLI flushed — a **false negative** that inflates every delivery-failure statistic), and
  **sender-side envelope corruption** (the envelope lost words *before leaving the sender*, because a
  quoting form triggered shell substitution; delivery succeeded, the nonce hit past the boundary, **every
  gate went green**, and the receiver read a sentence that was grammatical but hollowed out). Shapes 1–3
  look **identical** in the registry and rule 3's nonce yields the **same** `queued-unverified` for all of
  them — one reading, three different repairs — so `queued-unverified` is not a licence to resend. Shape 4
  adds the sharper epistemic point: **a wrong reading that comes with a plausible ready-made explanation
  never gets investigated** ("the target is mid-turn, it's queued" was unfalsifiable and wrong), so any
  "unverified" reading must be closed on a **falsifiable** criterion, never on a "probably…" narrative;
  and any classification data collected **before** the window is fixed carries that false negative — fix
  first, or mark those samples `suspect`. Shape 5 forces the closing conclusion: **the nonce proves the
  envelope arrived, not that what you meant to say arrived** — remedied structurally (ban substituting
  quote forms in envelope construction) and by detection (read back and compare verbatim), both recorded.
  Also recorded: the **codex delivery path is verified working** under short text plus a sufficient
  window (boundary → focus → short pointer → Tab → ~25s → nonce hit twice), which narrows the codex
  failure surface to shapes 3 and 4; hence a **recommended delivery shape** — *durable content goes in a
  letter, direct injection carries only a short pointer* — which sidesteps shape 3 and matches
  record ⊥ delivery orthogonality. The failure table's last column is deliberately scoped to the
  **reliability axis only** ("would a different multiplexer fix *this shape's delivery failure*" — all
  five: no), with a note that the **intrusiveness axis** (directed writes still require stealing focus,
  which interrupts a human working in the same multiplexer) is untouched by every delivery-side fix, so
  the table must **not** be read as evidence against changing multiplexer. **Coverage is stated in one
  deliberately unabbreviated sentence**: *5 known **shapes** covered, each with a signature-level fixture;
  one shape's trigger pattern constant rests on a **single observation**; and 4 shapes' signature→cause
  exclusivity rests on "the set of known causes is complete" — an assumption **already falsified twice this
  round** (three shapes became five).* Writing "5 causes covered" is banned as over-claiming: a fixture
  proves the **signature** is reproducible, not that the cause is covered, because what a classifier can
  see is only screen shape, command stdout, and whether a nonce appears past the boundary. Hence the table
  also carries a mandatory **`unclassified`** row — without it a classifier is forced to file a new cause
  under the nearest known one, which is exactly what happened both times this round — and the auth pattern
  constant is tagged `provenance: single-observation` with a **fail-closed** rule: no match ⇒ degrade to
  `unclassified`, never snap to the nearest shape. `dump-screen` is admitted as an
  **after-the-fact diagnostic** (separating "text never reached the composer" from "text reached it,
  never submitted") while staying **banned as an existence preflight** (silent empty + rc=0 on a
  nonexistent pane) and **not delivery evidence** (rule 3 still only accepts a nonce): reading *empty*
  is untrustworthy, reading *content* is not.
- **Epistemology general rule: some rules can only be produced by incidents** (`verification-and-gates.md`,
  beside "a gate with no enforcer is decoration") — asking "who would notice this wasn't done" supplies a
  missing *enforcer*, but never supplies a rule you don't yet know you need. Backed by this repo's own
  measured list (compact rewrite causing delivery false negatives; `--pane-id` not exempting focus;
  rc=0 with empty stdout when the pane is gone; a sandbox crippling only the outbound direction; expired
  auth accepting bytes it will never process; a registry leaf with every field correct written into the
  repo's parent directory; a verify window shorter than the target's flush; an envelope losing words to
  shell substitution while every gate stayed green; panes being reused in sequence, which makes naive
  "globally unique pane reference" report normal leftovers as collisions) — **not one of them is derivable
  from the spec**. Consequences: incident retrospectives must yield a spec increment; this class of rule's
  evidence tier is legitimately `实测` (a missing theoretical explanation is an acceptable gap, a missing
  measurement is not); **a wrong reading that comes with a plausible, unfalsifiable explanation never gets
  investigated**, so a gate's "failed / unverified" reading must be closed on a falsifiable criterion; and
  incident-born rules must themselves be checked for **false positives** — a gate people learn to ignore is
  worse than no gate, so the fix is usually splitting one rule by severity (fail vs. warning), not dropping
  the check. Attribution stays on the *shape*, never on a person or session.
- **Claim-provenance gate, as one contract** (`overlay/scripts/validate_claim_provenance.py` + tests,
  `overlay/work_context-templates/sendbox/_TEMPLATE-done.md`,
  `overlay/spec/guides/_TEMPLATE-acceptance-evidence.md`, `_TEMPLATE-handoff.md` delta, adopt-wired) —
  every conclusion a downstream reader acts on enters a canonical **schema v1** table
  (`结论 | 类别（实测/推断）| 出处 | 未验证缺口`); prose outside the table is not acceptance evidence.
  Column names are matched **exactly** (a parenthesised annotation is stripped); there are deliberately
  **no English aliases and no fuzzy header guessing** — an unrecognised header is reported as *missing*,
  and adding an alias is a versioned schema change. `推断` rows must name the still-unverified step, and
  from **four rows up** a gap column that is one copied non-`无` constant fails: satisfying a required
  column with a constant makes readers skip the column and drowns the rows that really have that gap.
  **Execution model, stated honestly:** the gate has exactly two consumption points — before a new done
  letter is sent, and before new/substantially rewritten acceptance evidence is accepted. It is **not** a
  generic task hook, and **no CI job can enforce it on an arbitrary adopter's sendbox** (that sendbox is
  typically excluded from the product git); CI can only check the validator's own behaviour.
- **PR-B's validators wired into real gates** (`verification-and-gates.md`, `repomem-doc-boundary.md`,
  `knowledge-closeout.md`, `roles-and-tiering.md`, `decisions/TEMPLATE.md`) — the two validators shipped
  earlier had no answer-moment, which by this repo's own "a gate with no enforcer is decoration" rule made
  them dead code. They now have gate-matrix rows (trigger / policy / where the trace lands), the ADR gate
  is called out at draft time *and* on both sides of the accept-time rename (`--visibility` has no
  default: a missing or ambiguous mode fails closed), the persistence gate lands in the landing manifest's
  new **`History proof`** mandatory item (`path@commit`, or an explicit
  `pending human commit authorization`), and a **`临时/共享资源生命周期`** mandatory item makes
  "the creator will remember to clean it up" visible. Remote strength stays split into the two honest
  flags (`--require-remote-configured` / `--require-remote-reachable`); ADR drafts are now
  `proposed-<slug>.md` and take no number until a single accept party assigns one.
- **Delivery preflight contract** (`agenttui-registry.md` §3) — one contract with two halves, both
  spec-only and **each marked "adapter not implemented"**: *path derivation* ("where should I write?" —
  a repo root inferred from the script's own location must be verified to actually be a project repo;
  never `mkdir` a fake registry) and *route derivation* ("can I even reach it?"). New **rule 6
  (send-side capability check)** validates only the capability the chosen route actually uses, reports
  **`no-operational-route` with a non-zero exit** when no operational route exists — kept semantically
  distinct from rule 3's `queued-unverified` ("didn't send" vs "sent but unverified") — and **forbids the
  silent fall-back to `claude -p --resume`**; that is symmetry, not a new principle, since the codex
  branch already refuses outright in the same situation. Rule 5 grows two field findings: "judge by
  stdout, never by exit code" applies to the **injection and submit commands themselves** (rc=0 with only
  `Session '<name>' not found` on stdout), with the worst case being **session present but pane absent —
  rc=0 and completely empty stdout**, so the existence preflight is the *only* pre-injection detector and
  the delivery nonce is the only post-hoc one; and `pane_ref` **rots on multiplexer session rename**
  (a launch-time snapshot), so every existing `pane_ref` must be rebuilt wholesale rather than having its
  `multiplexer` field edited.
- **Harness mechanical-gate validators** (`overlay/scripts/validate_adr_numbers.py`,
  `overlay/scripts/validate_harness_persistence.py` + tests, adopt-wired into `.trellis/scripts/`) —
  two independent, stdlib-only, read-only checks. The ADR one rejects duplicate **four-digit
  prefixes** (grouping the number alone, so `0007-a.md` and `0007-b.md` collide) while keeping
  unnumbered `proposed-<slug>.md` drafts outside the numeric namespace, and visibility-checks drafts
  *and* numbered ADRs so an accept-time rename is covered before and after numbering; which git
  records specs is declared explicitly (`--visibility machine-local|product-git`) and a missing mode,
  an ambiguous flag pair, or an absent side-history git dir **fails closed** instead of silently
  skipping the check. The persistence one proves named durable paths exist, are unignored, are clean,
  and carry a commit (`path@commit`), with remote strength split into two honestly-scoped flags:
  `--require-remote-configured` (configuration only, says so in its own output) and
  `--require-remote-reachable` (every evidence commit contained in a remote-tracking ref, bounded by
  the last fetch). There is deliberately no `--require-remote`.
- **Brand-capacity observer + safe AgentTUI launch contract** (`overlay/spec/guides/agenttui-launch-and-brand-capacity.md`,
  `overlay/spec/guides/decisions/0008-brand-capacity-and-safe-launch.md`) — a single-writer, stdlib-only,
  no-network, no-credentials observer (`overlay/scripts/arborist_brand_capacity.py` + tests) that reads
  Codex rate-limits passively from local rollout logs, polls Claude Code capacity mechanically via
  `claude -p /usage` (credence-gated: zero-side-effect proof required, else fail closed), keeps a
  self-report fallback, and gives a read-only brand recommendation **only** when creating a new Impler —
  with `source`/freshness always explicit and unknown/stale never disguised as fresh headroom. The guide's
  §1 documents the safe-launch invariants (one AgentTUI per tab, `new-tab` start that clears the inherited
  session-context identity, resolve-and-verify a stable non-plugin pane before any bootstrap write, launcher
  picks the binary while the launched session self-registers its real brand). Ships a `tool.json` template
  (`arborist-brand-capacity`, optional) plus adopt wiring into `.trellis/scripts/`. ADR-0008 records the
  three decisions; the collector supersedes the issue's "unknown unless a registered session self-reports" prose.
- **AgentTUI registry** guide (`overlay/spec/guides/agenttui-registry.md`) — `.arborist/`
  global–project cascade, spec/runtime schema, self-registration and lifecycle; scaffold templates
  plus adopt wiring; explainer pages under `docs/wiki/`.
- **Tool registry / plugin layer** guide (`overlay/spec/guides/tool-registry.md`) — `tool.json`
  schema with requirement tiering (`required` / `optional` + `fallback`), init provisioning in
  `adopt.sh` / `ADOPT.md` (required = warn + instructions; optional = prompt → register or
  fallback), with agentsview and Multica as the first registered optional tools.
- **Gate mechanization** (`verification-and-gates.md`) — a **gate matrix** giving every gate one
  mandatory answer-moment (run-or-skip + mechanical record), including a **code-review row**, and an
  **unconditionally-produced landing manifest** (emitted even when empty) as the auditable
  replacement for the honor-system HITL promotion gate.
- **Hazard-pinned gate triggers** — the manual-smoke and challenge/red-team gates now fire on
  **risk shape**, not task shape: smoke clause (b) and challenge clause (c) share the one
  "correctness depends on framework/runtime defaults" criterion (pure-backend not exempt) and
  **cross-reference each other** so neither silently drifts back to a task-shape proxy; a general
  principle "pin a gate's trigger to its hazard" added to `verification-and-gates.md` and the T2
  verification-discipline cluster.
- **Tool known-limitations** — `tool.json` gains `known_limits` and `architecture` fields plus a
  guide subsection (`tool-registry.md`): silent-miss / silent-empty limits demand cross-verification
  and a mandatory fallback for any `prefer tool X` spec line.
- **Worktree isolation** — a manual, idempotent harness link script
  (`overlay/scripts/harness_worktree_link.sh`) that symlinks harness dirs back to the main tree, plus
  **no-slash `.git/info/exclude` forms** in `adopt.sh` so `git check-ignore` matches the symlinked
  dirs and `git status` zeroes out; the `roles-and-tiering.md` worktree step and discipline document it.
- **ATUI ownership boundary** (`roles-and-tiering.md`) — notify ⊥ handoff (never take another lane's
  work), backed by a new **`fyi` letter type** (`sendbox.md`) that reports without transferring
  ownership or requesting action.
- **Sendbox persistence forms A/B** (`sendbox.md`) — explicit in-git (A) vs excluded/`hgit` (B)
  persistence-and-visibility modes, with de-privatization required in both.
- **Visibility config** — host-config `spec_visibility` (`product-git` vs `machine-local`) as the
  single source for spec/ADR visibility (`repomem-doc-boundary.md`, `generalization-boundary.md`),
  with a **reachability-boundary notice** on the guide index: an unopenable reference does not mean
  the rule is absent.
- **Injection-subset boundary** — a warning that the `workflow.md` customization body is not
  auto-injected by SessionStart / per-turn breadcrumb, with a verification snippet
  (`generalization-boundary.md`).
- **Close-out discipline** — decision-requests must carry structure; the impler converges by asking
  rather than re-delegating; ADR-0004 Residual tightened.

### Fixed
- **The probe's non-zero return code was recorded as an unresolved contradiction; it is now measured**
  (`agenttui-registry.md` §3, `agenttui.py` comments, +5 tests) — two independent reports disagreed about
  what the existence probe answers for an *already-focused* pane (rc=0 + empty vs rc=2 + "already
  focused"). The case was wrongly judged untestable ("measuring it steals a human's focus"); probing the
  pane one already occupies steals nobody's focus. Measured directly, twice: **rc=2** with
  `… is already focused` on **stderr**. The two reports are therefore not a contradiction but two branches
  of one rule: **rc=2 means "the requested focus change did not happen"**, and it has two opposite causes —
  the pane is already there (benign, and *positive existence evidence*) or the pane does not exist (fatal).
  Since both answer rc=2, **a return code cannot separate them**, which upgrades "never reject on a
  non-zero code" from a cautious choice to a measured requirement: rejecting on rc would refuse delivery to
  the most common healthy case — the very state a verified-successful delivery was in. Only not-found
  *text* may reject; `already focused` passes. That pass-through was previously implicit (it simply matched
  no pattern) and is now explicit in the spec, in a comment on the pattern list, and pinned by tests.
  Still open, and needing a human present because measuring it switches the active tab: the pane-focused-
  but-tab-inactive case, and a session with no client attached.
- **Measurement discipline: merging the two streams makes stream attribution unobservable**
  (`agenttui-registry.md` §3) — the "diagnostic is on stderr, not stdout" error survived because the
  readings were collected with `2>&1`, which structurally erases *which* stream said what. The raw data was
  in hand and the distinction was invisible in it. Any measurement whose conclusion will be used to judge
  one stream must record the streams **separately**; merged output is for reading what a command said, not
  for sourcing a decision criterion.
- **Delivery verification window was one second** (`overlay/scripts/agenttui.py`, `agenttui-registry.md` §3
  shape 4, +6 tests) — the window was expressed as `attempts × interval` (10 × 0.1), which hid the total
  behind a multiplication; that is why nobody noticed. Measured three independent times: a target's
  transcript record lands later than that (one case timed at **< 5s**), so *delivered* envelopes read back
  as `queued-unverified` — and that false negative then drove the retry branch to press submit **a second
  time**, i.e. it was actively producing duplicate deliveries. Now a seconds-named window
  (`PANE_VERIFY_WINDOW_SECONDS`, 20s) with backoff polling and early exit, plus a short separate tier for
  an active Codex pane whose Tab-queued envelope cannot surface before the turn boundary anyway. The
  guide records the *direction* as well as the number: early exit means widening costs the success path
  nothing while narrowing is what manufactures false negatives — widening is fail-safe, narrowing is
  fail-dangerous, so do not shrink it to make `send` return sooner.
- **A shipped spec claim carrying this repo's strongest evidence label was wrong in two places**
  (`agenttui-registry.md` §3, plus the matching code comments) — the guide said the existence probe
  returns rc=0 for a missing pane and must therefore be judged by *stdout*. Re-measured on one
  multiplexer version: the probe returns **rc=2**, and the diagnostic is on **stderr**, not stdout.
  Injection and submit commands *are* rc=0 on failure (that half stands), but their diagnostic is on
  stderr too while stdout may carry ordinary content (a session list), so "parse stdout" was imprecise
  everywhere it appeared. The adapter always joined both streams, so this was **documentation wrong,
  implementation right**; the wording is now "stdout and stderr joined" throughout. The section carries a
  six-row raw-reading table (command / rc / stdout / stderr per case) and two new rules: an unresolved
  contradiction between two independent reports about the *already-focused* probe case is recorded
  explicitly, and until it is settled a non-zero return code must **not** be used as a rejection signal
  (if the other report is right, that would misjudge the most common case); and granting the
  "independently reproduced" label now **requires attaching the raw readings** (command + rc + verbatim
  stdout + verbatim stderr) — conclusions without readings may only claim "reproduction asserted",
  because the same version and command produced two different reported return codes, so recording the
  version alone cannot support cross-checking.
- **Delivery-contract corrections from dogfood** (`overlay/spec/guides/agenttui-registry.md` §3–§5,
  ADR-0007 Amendment 2026-07-29) — five spec-level defects, each tagged with its evidence grade
  (independently reproduced upstream vs. measured downstream and not yet reproduced):
  (1) the delivery-evidence rule assumed transcripts are **append-only**, so a compact / rollout
  rewrite turned a genuinely delivered envelope into `queued-unverified` — a **false negative** that
  invites the duplicate re-send rule 2 forbids; evidence is now an **inode+size fingerprint** with a
  documented **full-file nonce fallback** and explicit evidence grades
  (`…-after-boundary` vs `…-fullfile`), plus the argument for why a per-send unique nonce makes the
  fallback false-positive-free; (2) "`--pane-id` injects without focus" was **wrong** — cross-tab
  injection requires focusing first, so delivery **steals focus** and structurally conflicts with a
  human driving the same multiplexer session; recorded as a **known architectural limitation** with
  multiplexer choice under evaluation (no replacement promised); (3) a new contract rule for
  **pane-existence preflight**: probes must parse stdout (exit code is 0 even for a missing pane) and
  must not use the read-screen command that returns **silently empty** for a nonexistent pane;
  (4) backfilled cross-directory `--resume` lookup (Codex resume works across directories, Claude
  Code `--resume` must run inside the target project directory); (5) two upstream-found spec holes —
  transcript mtime advances for **external headless resume** too, so `contradiction` is a **weak
  signal** and must be reviewed by inspecting what grew, and **half-registered has two directions**
  (index-without-leaf and leaf-without-index) that both must be detected and reported; plus a
  self-registration **fail-closed path gate** (missing `<repo>/.arborist/` must report
  half-registered instead of silently walking up to the parent directory).
  The shipped adapter's **unimplemented contract clauses are now listed explicitly** in the guide
  rather than being papered over as "contract satisfied".

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
