# Changelog

All notable changes to Arborist are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); versioning aims at [SemVer](https://semver.org/).

## [Unreleased]

### Fixed
- **Cross-project delivery no longer addresses a target from a stale mirror copy — the authority is the
  home leaf, and an unverifiable home fails closed** (`agenttui.py` `load_agent`, new check 7
  `mirror-stale` in `validate_agenttui_registry.py`, new `agenttui-registry.md` §2.2.2 plus the
  `foreign_repo_registration` schema row). Cross-project delivery has no repo-crossing parameter — delivery
  planning takes **one** repo root and loads sender and target from it — so the existing, human-authorised
  mechanism is a **self-declared mirror**: the sending repo also holds a leaf for the foreign target, whose
  `project` fields point at the target's real home project. The defect was that the mirror **copied the whole
  runtime half** (`session_id` / `session_file` / `pane_ref` / `last_seen` / `generation`) while the target's
  heartbeat only ever writes its **home** leaf ⇒ the copy rots by construction, and nothing ever followed
  `home_registry`. **Consequence grading is why this is a fix and not a nicety**: pane ids are reused in
  sequence (measured), so a stale `pane_ref` addresses **whoever holds that pane now** — the guide's
  most severe class, *silent mis-delivery* into a third party's composer, versus *unreachable*, which is
  loud, bounded to the sender, and gets chased down. Hence **fail closed rather than fall back**: if
  `home_registry` is absent, relative, unreadable, names another agent, names another project, or is itself
  a mirror, the delivery **raises** — falling back to the copy would trade a loud error for a quiet
  mis-delivery, and *a failure that can be seen always beats a success that cannot*. The mirror's runtime
  copy is **kept but demoted to diagnostics**: when its addressing fields disagree with home, the delivery
  path says so loudly (`warnings`, `target_mirror_stale_fields`, `target_runtime_authority`) rather than
  silently re-syncing, because a silent sync would hide the very fact that mirrors rot. Validator severity
  follows **what the field does**, not how far it drifted: addressing fields
  (`session_id`/`session_file`/`pane_ref`) are failures, snapshot fields (`last_seen`, `state`,
  `generation`, …) are warnings — failing on the latter would red-light every mirror permanently, and a gate
  people learn to ignore is worse than none. Read-only, no `--fix`, no external command, same discipline as
  the other six checks. **Still not implemented, recorded per item** (guide §2.2.1 status table and §3 gap
  list): direct cross-repo addressing without a mirror leaf; downgrading
  `duplicate-session-id`/`pane-ref-conflict`/`project-mismatch` to info for a well-declared mirror (mirrors
  still raise those known false positives); automatic creation, recycling, or syncing of mirrors — the last
  deliberately, since syncing would hide the rot.

### Added
- **An interface that silently falls back to some default target when a locating argument is missing must be
  wrapped fail-closed at our layer** (`verification-and-gates.md` general rule + `agenttui-registry.md`
  §1.1 instance + `tool-registry.md` §1.1 entry-form consistency) — **the third time this repository has hit
  the same shape**, which is why it is a general rule rather than a third fix. The first two were on the
  multiplexer side (`display-message -p -t <nonexistent>` answers **rc=0 and silently falls back to the
  *current* pane's attributes** — well-formed output belonging to somebody else's pane; `dump-screen -p
  --pane-id <nonexistent>` answers **rc=0 and empty**, read as "the pane is there, the screen is just
  blank"). The third appeared **in our own scripts**: a single machine-wide capability entry point invoked
  without `--repo` inferred the caller's repository root from its own `__file__` and got **the repository
  that hosts the authority script**. Criterion, reusable and not a description of this fix: *if an interface
  still answers rc=0 when a "which one / where / to whom" argument is missing, if what it returns is
  **well-formed** (and therefore reads like success), and if the caller **cannot tell from the return value
  itself** whether it got its own target or the default the interface chose for it — then it may not be used
  directly as a criterion or an enforcement surface.* The wrapping direction is fixed: **when you cannot
  tell who you should be addressing, demand it explicitly instead of silently picking one.** Discipline
  ("remember to pass the argument") cannot be the executor here — it has no product, and all three
  instances were documented as requiring the argument while being omitted anyway, precisely because nothing
  failed when it was. The executor is refusal on the *callee* side plus an end-to-end regression that
  traverses the real entry form.

- **A gate's regression must be end-to-end, and the test's structure must be isomorphic to the real call
  path** (`verification-and-gates.md`, cross-referenced from `sendbox.md`'s claim-provenance contract and
  from `agenttui-registry.md` §5.0-b) — **"the segment under test is correct" and "the gate will actually refuse"
  are two different propositions**, and passing the first does not entail the second, *because the
  difference between them is invisible from inside the test*. A green suite is how that invisibility
  presents itself, not evidence against it. Criterion: **if any layer sits outside the segment under test — hook
  call chain, shell type, process structure, multiplexer nesting, a real socket or a real server — then
  that layer's differences cannot be seen from inside the test**; either make the test traverse it, or
  write down explicitly that this test does not cover it. Silence is not an option. Two measured
  instances, deliberately kept because they sit on **different dimensions** (one dimension alone reads as
  "be careful in that one place"): **(i) call-chain layer** — a credential gate's regression `import`ed the
  classifier directly and passed on hundreds of files with zero false positives, so it tested the
  classification logic and never the path from *hook invocation* to *refused commit*; a real bypass
  committing successfully is what exposed it. **(ii) process / shell type** — a signal `trap` meant to clean
  up an inner multiplexer session when the outer pane closes passed an end-to-end test in which the pane's
  only foreground process *was the script itself*, whereas real use is a human pasting the command into an
  interactive shell, where the trap lands on a shell with job control and **never ran** — leaving a session
  still working and still burning quota while the human believed it closed. Deliberately **parallel to**,
  not folded into, "a new observation must first prove it does not perturb what it observes": that rule is
  about a test *doing one thing too many*, this one about a test *traversing one layer too few* — and
  "my test is read-only, zero perturbation" is precisely this rule's most typical victim. Adds no new gate
  row (a row without a product is the decoration this guide already rejects); its executor is the existing
  claim-provenance **"unverified gap"** column, which must now name **the layer the test did not traverse**
  and may not accept "there is a regression test" as provenance. Corollary recorded: **an artifact landing
  is not a path taking effect** — an accepted spec, a merged adapter, a green regression are none of them
  proof that the gate refuses on the real path.
- **A transient carrier must have its criteria extracted before it is destroyed — what burns is the
  carrier, not the criteria** (`verification-and-gates.md` general rule + `sendbox.md` instance +
  `lifecycle_executor` in both sendbox templates) — carriers have lifecycles, criteria do not. Letters,
  task directories, `research/` output, close-out packets all expire, and a lifecycle field disposes of the
  **whole carrier** while the common case is "a letter whose lifecycle is `burn` containing three criteria
  worth keeping". Three precise gaps, which is why this was never a discipline problem: **granularity**
  (no per-item disposal exists at all), **landing site** ("promoted into durable docs" is uncheckable, and
  a criterion in the wrong place is a criterion not kept — same shape as a rule outside the injected
  subset, which no session can read), and **executor** (nobody checks, so the loss is silent *and the
  un-extracted ones cannot be counted*). Mechanical product: before `burn`/`archive`/distillation, every
  criterion must be given **one openable reference** (durable file path + section heading) or the carrier
  must declare **"no criteria here"** — "it was promoted" is not a reference. Landing sites are routed rather than
  left vague (mechanically enforceable → validator plus a failing test; contract-affecting → ADR; reusable
  across tasks → `methodology/` or the matching guide; **task-local → stays in the task directory**, since
  over-promotion dilutes). Executor is the carrier's lifecycle executor, named per carrier — for letters the
  new required `lifecycle_executor` frontmatter field, and **a letter without one may not declare `burn`**.
  Fail-safe direction is one-sided on purpose: **what you cannot judge is not burned, it is archived** —
  burning is irreversible and its loss uncountable, keeping only costs space.
- **Allowlist over denylist — a gate asks "who approved this", not "what is wrong with this"**
  (`verification-and-gates.md`, third general rule on gate *design*, parallel to "a gate without an executor
  is decoration" and "do not wire a gate's trigger to a proxy") — the two questions **fail in opposite
  directions**: a denylist must enumerate *dangerous shapes*, so its completeness depends on what the author
  happened to think of and the missing cell **passes silently**; an allowlist enumerates *what is approved*,
  so the missing cell **fails loudly** and someone comes to ask for approval. Only the loud side can ever be
  fixed. Evidence strength is recorded **with** the rule because it decides how far the rule can be trusted:
  it is not extrapolated from one case but **two unrelated problem domains independently converging** — a
  credential-identification denylist measured failing across three repos, and an external-API publication
  gate's path-prefix denylist measured failing on its own. **Two different domains beat two instances of one
  domain**: same-domain pairs may be a property of that domain, cross-domain convergence can only be the
  rule. The other half ships as a **necessary condition, not a suggestion**: **an allowlist must make
  approval cheap.** Expensive approval means people route around the gate (`--no-verify`, disable it for a
  moment, force-add a whole surface), so the gate is missing exactly when it was most needed — the same
  mechanism as "a gate with many false positives gets learned-around", one entrance making the gate *noisy*
  and the other making it *expensive*. Hence: a denylist→allowlist conversion is only done when that half is
  done too; inverting the list while keeping a manual approval round merely trades silent leakage for
  systematic bypass, whose readings look *better*. The `scope` half is now landed with its executor — see the
  credential gate entry below.
- **Harness side-history credential gate (`overlay/hook-templates/credential-gate/`), wired by `adopt.sh` into
  `.harness-vcs/hooks/pre-commit`, with `scope` enforced as a real check** — this is the executor the
  `scope` rule above was registered against; both halves land together, because a rule without an executor is
  decoration while an implementation without `scope` turns unscoped authorisations into accomplished facts
  that later cannot be reconstructed.
  **Why nothing of the ignore family can do this job**: two defences were measured failing. A *file-name shape
  list* missed the shapes actually hit (`.local.md`, an `.env` in a subdirectory) — its completeness depends on
  what the author happened to think of, and the missing cell passes silently. A *directory-level exclusion* is
  overruled by `add -f`, measured: `add <excluded path>` → 0 staged, `add -f <same path>` → **1** staged — and
  force-adding whole harness subtrees (including `hgit snapshot`) is this toolchain's *established* usage, not
  anyone's slip. Hence only a **pre-commit check of already-staged content** cannot be routed around.
  **The real hazard is not leakage but bypassing a fail-closed contract**: the side history has no remote, so
  nothing escapes. What breaks is this — a credential manager's correct design is *delete the file when it
  expires*, so consumers may rely on "file present ⇒ value valid"; but **old values in version history are not
  deleted with it**, and a reader of history gets a credential that *looks valid and is already void*, with the
  contract telling it not to doubt. That converts a fail-closed design into a fail-open one.
  **Judged by class, not by shape**: sha256 digests, keys that are publishable by design (publishable / anon /
  public-client — the *value* is checked too, since those often sit in a field named `api_key`), account
  identifiers and placeholders are **not** secrets; a suspicious *path* with no real secret in it is let
  through, and no path-shape list takes part in the verdict at all — that is precisely the defence measured
  failing above. Over-reporting inflates the remediation surface and **dilutes the one item that actually
  needed it**. **Fail-closed throughout**: an unavailable gate refuses. The class exists because of a measured
  fail-open — the gate once derived the repo root from its own file's relative depth, the file moved, the
  derivation pointed elsewhere, the git subcommand failed, stdout was empty, the staged list came out empty and
  the gate **silently returned 0**. *A fail-open security gate is worse than no gate: it makes people believe
  they are protected.* Git-dir now comes only from `GIT_DIR` (which git guarantees when invoking a hook), with
  an upward search for `.harness-vcs` as fallback and a refusal if neither works.
  **Exemption must stay cheap** or the gate gets routed around: one `echo` appends a line to
  `$GIT_DIR/allowed-credentials`, i.e. right next to what it guards. **All four fields
  (`approver`/`date`/`scope`/`why`) are required and placeholder values do not count**; a defective entry
  **does not take effect** *and* the commit is refused with the line number and the missing field named — not
  silently ignored, since silent ignoring lets the author believe the exemption is live and discover otherwise
  only at the next real commit, or worse, conclude the gate is broken and bypass it. `scope` is required
  because **authorisation does not extrapolate**: a "this one file" authorisation, unscoped, gets read by the
  next person as "files of this kind are fine", and by then the original intent is unrecoverable.
  **Self-match protection is a property of the source, not a path exception**: a detector inherently contains
  the patterns it detects, and this gate was once refused by itself. Bare literals are written so they
  *cannot* match themselves (`sb[_]secret[_]` rather than the plain form); granting itself a path exception
  would be special-casing that also breaks on rename or copy. `tests/test_credential_gate.py` feeds the gate's
  own source to its own classifier and asserts zero hits.
  **Its regression is end-to-end**, per the rule above whose instance (i) *is this gate's previous
  regression*: the tests build a throwaway repo under `tempfile.mkdtemp`, install the hook, `add -f` a
  fragment-assembled fake secret and **really run `git commit`**, asserting **both** readings — non-zero exit
  **and** no commit produced — plus an attribution control (the same commit succeeds when the gate is not
  installed) and the passing side likewise really committing. Also gated in `adopt.sh`: the hook is installed
  **before the first commit** (the incident was a blanket snapshot, and the baseline is one), installation is
  idempotent via an `ARBORIST-CREDENTIAL-GATE:v1` marker, a **user's own** `pre-commit` is never overwritten
  (loud warning plus manual-merge instructions), and the baseline commit no longer swallows failure with
  `|| true` — a refusal by this gate is the one refusal that most needs to be seen.
- **Exemplary vs exhaustive lists** (`generalization-boundary.md`) — sync and privacy both run on lists (the
  sync allowlist, structural exclusions, placeholder tables, the detection layer's pattern set), and
  **whether a list is exemplary or exhaustive must be written on the list**, because the two demand
  *opposite* reader actions: absent from an exhaustive list means "it is not in this class, completeness is
  the author's"; absent from an exemplary list means "**nobody has judged this for you**". The failure mode
  is one-directional — an exemplary list read as exhaustive turns "was never thought of" into "was
  adjudicated safe" and the judgement that should have happened silently disappears, whereas the reverse
  only wastes one judgement. So the default is conservative: **an unlabelled list reads as exemplary**, and
  claiming exhaustiveness is an explicit act that takes on completeness. The guide's own two lists are now
  labelled accordingly (the sync allowlist is exhaustive because it is the mechanism's actual input; the
  excluded-item list is exemplary), and the tie-in is named: layer 2 (regex) can only ever enumerate
  enumerable patterns, which is why layer 3 (model/human) is not optional at the public boundary.
- **`delivery ≠ migration`** (`agenttui-registry.md` §3) — a successful delivery, a merged adapter and an
  accepted contract are none of them "the callers are on this contract". The contract's executor is **every
  caller**, so "migrated" is a **per-caller** fact and may only be claimed by enumerating and classifying
  all callers (on the adapter / still hand-injecting raw / no operational route). Auditing incomplete ⇒ no
  claim of completed sync or migration; using a merge or one successful send to support "migrated" is
  substituting a weaker reading for the conclusion actually wanted.
- **A structural generalisation-boundary guard over the whole `overlay/` tree**
  (`tests/test_overlay_generalization_guard.py`, +6 tests) — the boundary's layer-2 (regex) defence had no
  executor inside this repo: nothing failed when an absolute home path, an email address, a UUID or a long
  hex session id landed in a file that gets synced to adopters. It now scans every text file under
  `overlay/` for those *structural* patterns only. Deliberately **not** codename matching: a list of private
  codenames inside a public repo would itself be the leak it means to prevent, and codenames are layer-3
  (model/human) work by this guide's own defence-in-depth split — which is exactly the exemplary/exhaustive
  labelling above applied to the guard itself.
- **Three criteria on the shape of a record, grouped under "the shape of a record decides whether the
  judgement can be remade"** (`verification-and-gates.md`) — none of them says "write things down"; each names
  a *dimension* whose absence makes a later re-judgement impossible. **(i) Loudness is not rhetoric**: turning
  a loud error into a quiet half-success can be a regression even when the new reading is more accurate,
  because the loud one gets chased and the quiet one does not — so any "make the report more precise" change
  must ask whether it converted something chased into something ignored, and if so add a mechanism *with an
  executor*. **(ii) A withdrawal must record which kind it was** — "the evidence refuted it" or "the cost was
  accepted" — because the second is premise-dependent and re-opens by itself when the premise changes, while
  writing only "withdrawn" destroys that reversibility. **(iii) A drift statement about a layered artifact
  must name the layer**: when something has both a versioned product layer and a git-excluded runtime face,
  "it is behind" collapses the two and readers hear the more severe one. Each carries the measured instance it
  came from. The test for all three: **could someone reading only this record, a year later, remake the
  judgement that was made at the time?** If not, a dimension is missing.
- **Sender-side consumption of the submit ack — the one thing that stops an accepted message being sent
  twice** (`agenttui.py` `read_submit_ack` + `ACK_STATUS_*`, `agenttui-registry.md` §3, +5 tests) — the
  receiver-side ack shipped earlier had no consumer, so the guarantee existed only for a human reading the
  table by hand. Now every pane delivery reports `ack_status` (on success too, because the value of the pair
  is in the *combination*), and exactly one behaviour changes: when the ack says the receiver's hook fired
  but the transcript nonce has not surfaced, the retry is **suppressed**. That combination is unreadable
  from the transcript alone — it looks identical to "never submitted" — and the old code pressed submit
  again in both cases, i.e. it duplicated accepted messages. Three fail-safe properties are pinned by
  tests: `table-unreadable` stays a **separate value** from `unconfirmed` ("I could not look" and "I looked
  and found nothing" license different actions, and a missing ack module is the former — the facility may
  simply not be adopted here); a missing ack never *blocks* the single retry the contract already allows
  (the one-sided direction is that absence can only downgrade to unconfirmed, never assert not-submitted
  and never forbid); and a failed lookup can never fail the delivery — the observation must not change the
  delivery it observes.
- **A sixth delivery failure shape, found by walking into it: the target is not ready yet**
  (`agenttui-registry.md` §3) — a delivery to a freshly spawned ATUI read back unverified; the screen dump
  showed the pane still running a package-manager self-update (the installer's own progress output on screen), i.e. **the CLI had not taken over the
  terminal** and the bytes went to the shell in front of it. Its reading is identical to the other five,
  but its handling is the opposite of all of them: **waiting works** — it is the only shape where it does
  (waiting never fixes a sandbox, an expired credential, a truncated composer write, or a corrupted
  envelope). Conflating it therefore produces two opposite errors: treated as one of the others, a target
  that only needed a moment is abandoned; treated as this one, a permanently broken target is waited on
  forever. The readiness criterion is required to be **causal**, not observational: "the screen looks like a
  composer" is guesswork, whereas **"the target has completed self-registration"** is an action the target
  itself performed, which proves the CLI is up, can read the harness, and can write files — the same
  reasoning as the ack. Hence a launch-side invariant: **do not deliver to a spawned ATUI before its
  self-registration completes.** This also names a previously unattributed failure class — a newly spawned
  ATUI has a readiness window during which any delivery lands in the void, indistinguishable from a broken
  target. (The launcher's own wait-for-binary retry protects the launcher, not the sender.)
  Recorded as the third falsification of "the known-cause set is complete" (three shapes → five → six),
  which is the concrete payoff of having insisted on keeping the `unclassified` bucket.
- **`pane_ref.socket`: pane addressing gains the *server* dimension it was missing**
  (`agenttui-registry.md` §2.2 / §2.2.1 / §3 / §4, `overlay/scripts/agenttui.py`,
  `overlay/scripts/validate_agenttui_registry.py`, one tool template, +16 tests) — a pane id in the
  second pane transport is documented as unique only *within one multiplexer server*, while a
  `pane_ref` carried `(multiplexer, session, pane_id)` and no socket. That made a pane_ref the name of a
  pane *number* rather than of a pane: on a machine running several servers, a same-numbered pane on the
  default server whose session name also matched passed the existence probe, passed the session
  cross-check, and took the envelope into an uninvolved session's composer — the silent mis-delivery the
  guide rates as its worst outcome, and the one residual hazard left by the transport when it shipped.
  The field is **optional and absent means the default server**, so every pane_ref written before it
  existed produces a byte-identical command line (pinned by a test). The transport addresses **all
  three** of its commands — existence probe, write, submit — at that server, so preflight is a question
  about the pane the delivery will actually use; whether the value is a socket *name* or *path* is
  decided by the value's own shape, which is the same distinction the multiplexer's own two options
  draw, so no second field is invented and no value means both. Stuffing a socket into `session`
  instead is **explicitly forbidden**: it costs nothing today and misleads every later reader, including
  the session cross-check whose whole job is spotting a rotted handle. The uniqueness key in §2.2.1 and
  in the validator is now the quadruple, because leaving the socket out is wrong in *both* directions —
  two different real panes on two servers report a conflict that does not exist, and two leaves really
  contending for one pane can hide behind a spelling. Absent and an explicit `default` normalise to the
  same server (the default socket *is* named `default`), so uniqueness is enforced on the pane and not
  on the spelling; the two implementations of that normalisation are pinned to the same answers by a
  test. Two residual gaps are listed rather than glossed: the normalisation is **lexical only** (a name
  is never resolved against a path, since that needs the socket directory and uid of whoever wrote the
  leaf), so one server spelled two ways under-reports a real conflict; and a transport that does not
  honour the field **ignores it silently**, with no mechanical check yet.
- **One launch path for humans and agents: `overlay/scripts/atui_launch.sh` (shipped, deliberately not wired)**
  (`agenttui-launch-and-brand-capacity.md` invariants 7 and 8, +34 tests) — a human-started and an
  agent-derived ATUI going through two different launch paths forks the `pane_ref` value domain, the
  self-identification method and the reachability verdict into two, and errors at the fork are
  **silent**: delivery still reports success, it just lands elsewhere. So there is now exactly one
  script, called from both sides, with the only permitted difference decided by an *observable fact*
  (a tty ⇒ attach in the foreground; no tty ⇒ create detached), everything else — server, naming,
  cleanup hook, identity-variable clearing — byte-identical. Properties, each with a mechanical test:
  idempotent (already inside the multiplexer ⇒ pass through, because repeated nesting makes the pane
  handle level unpredictable and the self-identification gate has already measured two real cases of a
  session mistaking someone else's pane for its own); reversible by one environment variable, whose
  plan is compared **byte for byte** against the pre-existing launch form; argument-faithful (`"$@"`,
  never `"$*"`); `--dry-run` prints what it *would* run and runs nothing; and a missing multiplexer is
  a **non-zero exit rather than quietly not wrapping**, since an unwrapped session simply has no
  directed handle and that difference is invisible afterwards. Two-stage session naming does the first
  stage only (`<project>-<pid>`) and **never renames**: renaming is safe only where the addressing
  handle carries no session name, and this transport's pane_ref carries one *and* cross-checks it, so a
  rename must be paired with rebuilding the whole pane_ref. It writes no registry entry and never
  writes the brand — the launched session self-registers its actual runtime brand. **Not wired on
  purpose**: it is not in the adoption scaffold, no shell startup file is touched, and no existing
  command name is replaced; a biconditional test makes the guide's "not wired yet" statement and the
  scaffold agree, so whoever enables it has to update both. What remains is exactly the part that
  affects a real person: point the human's launch command at it (new name first, replace later) and run
  one human-present smoke test.
- **Receiver-side submit-ack handshake: a causal delivery reading next to the existing bystander one**
  (`overlay/scripts/agenttui_submit_ack.py`, `overlay/hook-templates/submit-ack/`,
  `agenttui-registry.md` §3 rule 8, one `[local]` injection entry, +28 tests) — the only delivery
  evidence so far was the sender walking the target's transcript for the per-send nonce. That reading is
  *bystander*: it lags the target CLI's own flush (a 1-second verification window read an already
  delivered envelope as unverified and provoked a duplicate submit), and it cannot separate "the text is
  piled up in the composer and was never submitted" from "submitted but not yet flushed" — the first of
  which is the pain actually reported. The receiving CLI's submit hook fires *only* on a real submit, so
  an ack is causal proof of submission. Acks are appended one JSON object per line to a global
  `~/.arborist/submit-acks.jsonl` (append-only because several ATUIs write concurrently and a
  read-modify-write loses records; same naming and permission handling as the focus-intrusion event log —
  0600 on creation, an existing mode left exactly as found). A record carries only what the hook can
  itself prove — nonce, timestamp, receiver brand/agent/project/session, the matched envelope header
  fields — and structurally never the message body. Two hard properties, both mechanically pinned: the
  recorder **always exits 0** (a non-zero submit hook blocks a real person's prompt) and **always writes
  an empty stdout** (some brands inject hook stdout as context), so every failure degrades to a stderr
  warning. Wiring is manual and comes in two forms, with a sibling hook command preferred over pasting
  into the shipped hook script precisely because it makes "does not change the existing hook's behaviour"
  structural rather than test-dependent; the paste-in form is nevertheless covered by a differential test
  that runs a hook fixture with and without the snippet and requires byte-identical stdout and exit code.
  The fail-safe direction is the load-bearing part: **a missing ack means unconfirmed, never "not
  submitted"** — the hook may be uninstalled, silently skipped at init time when the host settings file is
  tracked by the product repo, or its write may have failed, and asserting non-submission from an absent
  record would trigger a capability-ladder downgrade and re-deliver a message the target already has. An
  ack may therefore only *prevent* a downgrade, never cause one. Not implemented, and stated as a gap in
  the guide: `agenttui.py` does not consult the table yet, so no delivery result carries an ack field and
  the seven-value upgrades are, for now, a human reading rather than a mechanical one.

### Fixed
- **Global capability entry points now refuse to guess the caller's repository root** (`agenttui.py`,
  `arborist_brand_capacity.py`, new `validate_tool_entry_forms.py`, new global-form tool templates under
  `arborist-templates/tools/global/`) — a live defect found by read-only re-verification downstream, with an
  observable **wrong-repo success**. Two entry forms exist and their repo-root semantics are **opposite**: an
  adopted copy at `<repo>/.trellis/scripts/` may correctly infer the root from its own location, whereas a
  machine-wide authority copy invoked through a shim cannot — `parents[2]` there names the repository that
  *hosts the script*. The pre-existing root gate could not separate the two: it only proves the derived path
  *looks like* a project repository, and the authority's host does. Readings: on the messaging side a missing
  `--repo` was **not refused by the gate** but kept executing against the authority repository, failing later
  only because that repository *happened* to have no agent by the requested name — with a same-named agent it
  is a **mis-delivery** (`agenttui-registry.md` §2.2.1: a failure that can be seen always beats a success that
  cannot). On the capacity-observation side it was strictly worse: **rc=0**, returning the authority
  repository's snapshot — well-formed, with someone else's observation values, and nothing downstream to fail.
  Now: every subcommand that reads or writes project state refuses **before reading any repository state**
  when the entry form is not an adopted project copy, with a dedicated exit code for the messaging adapter so
  "which repo?" and "the registry says no" no longer share one. The form is decided by an **explicit signal**
  (`ARBORIST_ENTRY_FORM`, which a shim must export), falling back to a **structural check of the inference's
  own stated precondition** (is this script really at `.trellis/scripts/`?) — an unrecognised signal value is
  `unknown` rather than a fallback to structure, so a typo cannot silently re-enable inference, and anything
  undecidable demands explicit `--repo`. The only exemption is top-level `--help`, exempt by *call order*
  (argparse handles it before the gate) rather than by a list that could rot. Second hop closed too: the
  envelope's `reply_command` now carries the **already-resolved** `--repo`, preferring the stable global shim
  form — previously it carried only the authority script path, so a replier following the envelope fell back
  into the same wrong-repo inference. Tool entries gain a mechanical consistency check: `invoke` and
  `availability` must name the **same** entry form (the observed shape was `invoke` pointing at the global shim
  while `availability` probed a project copy — which *passes* and thereby proves something else entirely,
  leaving readers to treat a possibly-uninstalled entry point as available), and `scope` must match. The
  regression is subprocess-based on purpose: the criterion is read from `__file__`'s real location and the
  process environment, so the difference between the two entry forms is **structurally invisible** to an
  in-process import — including a fixture where **both** repositories hold a same-named agent, pinning down
  the accident that the earlier reading merely got lucky on.

### Changed
- **Session cleanup is recommended through the multiplexer's own option again, and its arming moment is now a measured hard rule**
  (`agenttui-registry.md` §5.0-b) — the section still recommended "capture the close event" (a signal
  `trap`) in its body while the warning below it recorded that the same mechanism had already been
  disproved in real use: the trap lands on the *interactive* shell a human pastes into, does not run, and
  leaves an **invisible live agent** still working and still spending quota. The recommendation is now the
  multiplexer's built-in "destroy the session when the last client detaches", chosen for one hard reason —
  it depends on neither a signal nor the kind of shell carrying it, so the test shape and the real usage
  are isomorphic, which is exactly where the previous version died. Its cost is stated in the same breath
  rather than in a footnote: the criterion is an *inference* (no client attached) and cannot separate
  "the human closed the window" from "the human stepped away", so an **inner** detach is collateral
  damage while anyone using an **outer** detach is unaffected. New, and measured on a private detached
  server plus a faked pty client: switching the option on while **nothing is attached destroys the session
  immediately** (the server went with it), which would kill an ATUI started detached before anyone could
  look at it — and delivery into an unattached server is itself a measured, legitimate shape. So the
  option **must be armed by the client-attached event, never at session creation**, with the honest
  consequence spelled out: a session that is never attached will not disappear on its own and needs
  explicit destruction. The re-test conditions for the still-open "long envelope, busy target" gap are now
  written down as a table (long envelope, target mid-turn, byte-for-byte comparison, sender-side self-check
  first, both multiplexers), because "unverified" without the conditions for verifying it is a dead end.
- **Two tmux-transport gaps closed by one human-present smoke test, and the migration itself withdrawn**
  (`agenttui-registry.md` §3 gap list) — the entries "the no-focus-theft claim is only proven at the server
  state layer, not with a client attached" and "the submit-key semantics were never verified against a real
  ATUI" are both now measured. With target ATUIs living in tabs the human was **not** looking at, delivery
  left the outer active tab **byte-identical** and both targets' pane-active flags unchanged, with a client
  attached; and sending the contract byte for Enter put each brand's envelope nonce into its own session
  record. Recorded alongside, because it is the easier reading to reach for and it is wrong: **this does not
  show that tmux fixes the composer-not-submitting problem.** The variables were not controlled on the
  painful case — the message was short and the targets idle, and each of those has already been shown
  independently sufficient for success on the other multiplexer too. Proving anything about long envelopes
  or busy targets requires re-measuring under exactly those conditions. Also recorded as a method: both gaps
  had sat unverified not because measuring was hard but because **measuring required interrupting a person**,
  so the right moment to clear that class of gap is while the person is already present — scheduling it
  separately means the interruption cost defers it indefinitely.
  With focus theft judged an **acceptable cost** by the owner (a human present can absorb the interruption),
  the last standing reason to migrate is gone and the migration is **withdrawn**: the transport stays in the
  tree, dormant (nothing declares that multiplexer, so routing never reaches it) and zero-behaviour-change,
  and no launcher change is made. The withdrawal is deliberately recorded as "the cost was accepted", **not**
  "the evidence refuted it" — if unattended operation later becomes common, focus theft regains its cost and
  the case re-opens without needing to be re-argued.
- **Pane reachability and current Codex turn activity are now two separate readings**
  (`agenttui.py` `derive_codex_submit_activity` / `build_pane_route`, `agenttui-registry.md` §3 rule 1,
  ADR-0007 Amendment 3, +12 tests) — the submit key used to be chosen from the *reachability* state, which
  is derived from transcript freshness. Freshness answers "is this pane worth addressing"; it does not
  answer "is a turn running right now", and a target whose turn has just finished is still inside the
  freshness window. A downstream adopter measured both directions: Tab handed to an idle composer enqueues
  nothing and leaves the envelope sitting unsubmitted, and conversely a genuinely busy target's Tab queue
  does not surface in the transcript until the turn ends, so an early grep miss read as failure and
  provoked a duplicate decision. The key is now derived from the target's own latest complete turn-boundary
  event (`task_started` → Tab, `task_complete` → Enter), refreshed once more immediately before the key
  because the turn can end during the settle delay, and an unterminated JSONL tail is treated as unknown
  rather than skipped — skipping it would confidently report the state from *before* the record currently
  being written. No trustworthy boundary means the send is refused before the first pane command rather
  than guessed. Claude Code is untouched: still Enter unconditionally, still no boundary read, because its
  Tab is autocomplete and its own receiver-side queue handles a busy turn.
- **Delivery outcomes are classified by the action that was executed, replacing the single
  `queued-unverified` bucket** (`agenttui.py` `OUTCOME_GUIDANCE` / `RETRY_SAFE_OUTCOMES` /
  `send_via_pane`, `agenttui-registry.md` §3 rule 4, +14 tests) — the problem was not the name but the
  merge: "wait out a turn boundary", "recover text already sitting in the composer" and "go inspect a
  command that never reported back" are opposite caller actions that shared one reading, so a caller could
  not tell which one it had. Pane results are now `pre-injection-rejected` / `delivered` /
  `queued-for-next-turn` / `submit-unverified` / `composer-unsubmitted` / `write-unverified` /
  `submit-command-unverified`, each carrying `submit_action`, `recommended_action`,
  `verification_guidance` and `retry_safe`. `retry_safe=true` is confined to the two paths where zero pane
  commands are mechanically provable (`pre-injection-rejected`, `no-operational-route`) and a test pins
  that set — a command that failed or timed out does **not** prove the absence of side effects.
  `no-operational-route` keeps its exit status 3 and stays strictly "nothing was sent". Honest boundary,
  stated in the guide: this splits **actions**, not **causes** — an authentication failure and a truncated
  composer still share `submit-unverified`, and no screen-dump classifier exists yet.
- **A Codex envelope is written as one bracketed-paste burst instead of a keystroke stream**
  (`PaneTransport.frame_paste` / `PASTE_FRAMED_BRANDS`, `agenttui-registry.md` §3 rule 1, +7 tests) —
  measured downstream on one Codex version: an unframed fast character stream is classified as a paste
  burst, and Enter is then consumed as a newline *inside* that burst, so a mechanically idle target with
  two submit commands both returning 0 still had the envelope sitting in its composer. This is the causal
  fix for the *write method* half of shape 3 and nothing more: routing, transport selection and the command
  sequence are unchanged (one write command, same verb, same addressing — only the payload is wrapped).
  The intent ("deliver as a single paste") is a capability question asked by the routing layer; the escape
  bytes appear only inside the transport, pinned by a mechanical test. Enabled per brand from measurement
  only, so Claude Code stays unframed — same name is not the same capability.
- **The resume runner is detached and is never killed by the sender's timeout**
  (`agenttui.py` `send_via_resume` / `observe_detached_resume`, `agenttui-registry.md` §3 rule 7,
  ADR-0007 Amendment 3, +11 tests) — `claude -p --resume` and `codex exec resume` carry the target's whole
  turn, so running them under this process's timeout made the sender's patience the target's deadline: an
  observation timeout SIGKILLed a runner that was working correctly, aborting a turn that may already have
  written files or called external systems. This is orthogonal to resume having become explicit opt-in —
  opt-in changed *who chooses* the route, not who owns its lifetime. The runner now starts in its own
  process session with stdin detached, `--timeout` bounds only the nonce observation window, and no code
  path in that function can signal the runner (a test greps for it). Outcomes are `delivered` (still only
  transport entry, so `task_completion=unverified`), `resume-started-unverified` and
  `resume-exited-unverified`; a runner exit, even with status 0, is not proof of zero side effects. Its
  output goes to a private file rather than a pipe — an abandoned runner whose pipe buffer filled would
  block *inside the target's turn* — and is neither discarded (for the `-p` shape it is the only place the
  target's reply appears) nor cleaned up while the runner is still writing; the path is reported instead.

### Added
- **Optional project `alias`, with its domain enforced at the source** (`agenttui-registry.md` §2.3 + §5.0-b,
  index template, validator check, +5 tests) — projects need a short name for places a full repository name
  does not fit, the first of which is a terminal multiplexer session name. Three constraints are normative:
  an alias is **never an identity** (addressing and de-duplication go by the derived project id, and a
  mechanical test forbids any lookup, grouping or comparison keyed on the alias); its value domain is
  restricted to `[a-z][a-z0-9-]{0,31}` **because it is interpolated into external namespaces** that commonly
  forbid dots, colons and spaces — constraining it once at the source beats escaping it at every consumer,
  which is the kind of thing that gets missed in exactly one place; and its absence must never fail anything
  (readers fall back to the project name).
- **Session naming *suggestion* for multiplexer-hosted ATUIs (explicitly not a requirement), plus the
  lifecycle setting that must accompany it** (`agenttui-registry.md` §5.0-b) — the useful name is
  `<project alias or name>-<task>-<role>`, taken **from the registry rather than the directory name** (a
  directory can be renamed and several worktrees can point at one project, while the registry's project
  identity is unique). But a launcher cannot know the task or the role at start time — those are settled
  during self-registration, sometimes after a conversation. So the launcher starts with a predictable
  `<project>-<pid>` and the ATUI **renames the session** once it registers. The section opens by stating
  that it is advice whose only purpose is human findability: **an existing recognisable name is kept**, and
  renaming for the sake of a uniform format is forbidden — the gain is tidiness, the cost is possibly rotting
  an addressing handle, and that trade does not hold. It also records a measured default that sits on the
  dangerous side: when the human closes the outer window, the default multiplexer behaviour **keeps the
  session and its ATUI running** — worse than a stale handle, because it is an agent still working and still
  spending quota while the human believes it was closed, and the registry cannot show that state either. The
  destroy-on-last-client-detach option must be set explicitly, with two implementation notes: setting it on a
  session created detached makes that session destroy itself immediately, and whether the detach key becomes
  a hazard depends entirely on how the human actually closes things — ask first, then pick the mechanism. The section states the condition
  under which that is safe at all: it works only where the pane handle is a globally unique, lifetime-stable
  id, and is **unsafe** where the handle embeds the session name — there a rename silently rots every
  existing handle, a failure class already measured in this repo. Which is also why evaluating a different
  multiplexer means inspecting its handle shape, not just its injection command.
- **Pane self-identification gate, restored from a downstream adopter's history where it had been lost**
  (`agenttui-registry.md` §5.0, gate-matrix row) — self-registration has to fill a pane handle, and the most
  natural way for a session to answer "which pane am I in" is to read the multiplexer's injected environment
  variables. That method is **unreliable and fails silently**: two real misidentifications were measured —
  once claiming *someone else's* pane, once **inheriting the sender's** pane during a headless turn. A wrong
  pane handle raises no error; it just makes later deliveries land in an unrelated session. The gate makes
  the environment variable a **lead requiring corroboration**, never proof of identity: a second independent
  reading (the pane's running command and working directory, compared against the identity and cwd the
  session claims) must agree, and contradiction / a candidate pane already held by another live leaf / only
  the outer handle being visible under nesting all **fail closed**. The section states explicitly why this
  cannot be replaced by the post-write uniqueness checks and why both must coexist: uniqueness can only
  notice a conflict **after both leaves are written**, and it never notices a one-sided misidentification at
  all — so uniqueness alone means alerting only after the pollution exists, with a whole failure class
  invisible. Directly relevant to the nested launcher shape now under evaluation: under nesting the **inner**
  handle must be recorded, and only after a nonce-verified directed injection proves that handle reaches this
  TUI — filling in the outer handle because it is the one exposed is the exact case the gate forbids, and is
  how both measured misidentifications happened. One past violation is kept on record de-personalised: a
  handle in this repo was written by reading it back out of process environment — the very method this gate
  rejects. That value happened to be correct, which is precisely why it must not become precedent; "the
  value was right" and "the method is sound" are different claims.
- **A second pane transport (`tmux`) that coexists with the existing one, so panes migrate one at a
  time** (`agenttui.py` `TmuxTransport` + `TRANSPORTS`, `agenttui-registry.md` §2.2 / §3 rule 5 and
  the new tmux readings table, +27 tests) — this is **not** a migration to tmux: both transports stay
  registered and `pane_ref.multiplexer` (value domain now `zellij` / `tmux`) picks one, so no flag day
  is needed. The delivery contract and the routing layer are untouched, which is what ADR-0007's
  transport neutrality was for: adding a multiplexer is a subclass plus one registry entry, and a
  mechanical test still pins that no multiplexer name or command appears in routing code. Measured on
  a private detached server so that no real terminal was touched: `send-keys -t` is genuinely
  directed — it reaches a pane in another window with the active window and every pane's active flag
  unchanged and no cross-delivery — so **this transport's existence probe does not have to be a focus
  command**, which is its substantive advantage over a focus-addressed one. The probe is therefore
  `list-panes -t` (rc=1 plus `can't find pane:` for a missing target), and one trap is recorded
  alongside the other transport's screen-dump trap: **`display-message -p -t <missing>` answers rc=0
  and silently falls back to the *current* pane's attributes**, i.e. a false positive that is harder
  to doubt than an empty one. Hence the general lesson now written down: every multiplexer has a
  "most natural property read" command and that is exactly the one that falls back silently with
  rc=0, so a change of multiplexer requires re-measuring cell by cell rather than assuming a
  same-named command means the same thing. Verdicts still come from **stdout and stderr joined**, not
  from the exit code, even though this transport's codes are more trustworthy. Addressing anchors on
  the pane id (`%N`, documented as unchanged for the pane's life and measured to survive a session
  rename), which shrinks the rot surface of `pane_ref` — the session name is still cross-checked, so
  a rename becomes a loud refusal to rebuild the whole handle instead of a silent write into nowhere.
  Rule 5's pre-flight is contractually **downgraded from necessary to an optimisation on this
  transport only** (the worst cell — pane gone, rc=0, both streams empty — does not occur here), and
  deliberately **not** acted on in code: the contract is transport neutral and the downgrade rests on
  one measurement of one version. Three gaps are listed rather than implied: `pane_ref` has no socket
  dimension, so only the default tmux server is addressable and a same-name same-id pane on another
  server would still be a silent mis-delivery; "does not steal focus" is proven at the server's state
  layer, not against an attached human; and the submit-key bytes have not been verified against a real
  agent TUI over this transport.
- **A mechanical tiebreak for cross-repo registry conflicts, because that class has no owner by
  construction** (`agenttui-registry.md` §2.2.1, `validate_agenttui_registry.py`
  `tiebreak_readings`, gate matrix row, +9 tests) — every high-severity conflict found on real data
  was **between two repos**: repo A's leaf and repo B's leaf claiming the same pane, or the same
  `session_id` claimed in both. "Each lane fixes its own" does not apply here: **each lane's leaf
  reads as self-consistent, the conflict is only visible globally**, so the predictable outcome is
  both sides believing the other is wrong, or both waiting for the other, and every conflict stalls.
  The rule now fixes the input priority (**the pane's real cwd > each leaf's `session_file`
  ownership > `last_seen`**), states that the ruling is made **once, globally**, and that its
  product is a **named ruling** — which claim is legitimate, which leaf is deleted, and the readings
  it rests on — handed to the lane owning the leaf judged wrong, since deleting a leaf in another
  repo is that lane's call. The validator now prints those readings inline (each claimant's path,
  `session_id`, `session_file`, `state`, `last_seen`, `pane_ref`) so a ruling can be made from the
  report alone, and it still **does not rule**: reporting is not adjudicating.
  The highest-priority input, the pane's real cwd, is deliberately **not acquired**: it needs a
  pane-addressed multiplexer command, the only one that reliably reports pane existence *is the
  focus command* (it can pull a human's view onto the pane), and the layout dump carries no
  pane→pid mapping, so there is no read-only substitute. Per the methodology entry above, an
  observation that perturbs what it observes must not hide in a validator that is run in bulk
  (before and after every GC), so the reading prints as `unknown` **with its reason** and a human
  supplies it. The mechanical proof that this changed nothing about what the script does to the
  world: it executes **no external command at all**, and a test pins that.
- **`validate_agenttui_registry.py --print-project-id <repo>`** — prints the `project_id` recomputed
  from `realpath`, so the self-registration write path can *compute* the derived value instead of
  copying a literal. Exits 2 when the path is not an existing directory: `realpath` would digest a
  typo into a perfectly plausible id, which is the exact failure the mode exists to prevent. It
  reads no global index, because registration happens before there is a registry to read.
- **Methodology: a new observation must first prove it does not perturb what it observes**
  (`verification-and-gates.md`, beside the "some rules can only be born from an incident" entry) — the same
  shape hit this repo three times at three different levels in one session: collecting failure-classification
  samples before the verification window was fixed (the *data* was perturbed — false negatives would have
  been frozen into a fictitious cause), using the focus command as the existence probe (the *observed
  object* was perturbed — the probe pulls the target into focus, so every following reading says "already
  focused" and a ratio looks cleanest exactly where the disturbance is worst), and adding a read-only
  context command around that probe (the *tests* were perturbed — the command sequence changed and nine
  existing tests failed). None was carelessness; all three share the blind spot that **observation is
  assumed neutral**, which is most dangerous precisely when the action is read-only — read-only is not
  perturbation-free. The entry's mechanical criterion: ask whether the new observation changes the
  sequence or state the observed party is in, and **if it does, default it off and produce a mechanical
  proof that behaviour with it off is identical to before the feature existed** — the last clause is what
  turns "I'll try not to interfere" into something verifiable. Three corollaries are recorded: observation
  data is only valid from the moment the instrument was fixed, events beat aggregates when the observation
  changes later readings (the bias is one-directional toward *under*-counting), and unknown must stay
  distinguishable from "did not happen".
- **A criterion for when direct injection is warranted at all** (`agenttui-registry.md` §3) — the
  delivery-shape convention (durable content in a letter, direct injection carries only a short pointer)
  had no criterion for the *decision*, and was measurably used backwards: two collaborating sessions each
  direct-injected a dozen long envelopes in one evening, nearly all of them **conversation**. The rule now
  states it plainly: direct injection is a *delivery notification*, the letter is the record, so **only a
  message that requires the recipient to change behaviour immediately** (a blocker, a correction, revoking
  a decision already being executed) is injected; everything else goes to the inbox and is picked up
  naturally. Getting this backwards is systematic rather than careless — the highest-frequency, least
  durable content is exactly what least needs injecting, and also exactly what is most tempting to inject,
  because it is happening now. Its cost is now measurable: one injection was observed switching a human's
  entire view to another tab, away from the conversation they were having.
- **Focus-intrusion observations are recorded as events with stratification, never as a rate**
  (`agenttui.py` `append_observation` / `addressing_observation` / `--observation-log`,
  `agenttui-registry.md` §3, +9 tests) — the counter added in the previous entry would have
  **systematically understated** what it measures, in two ways that had to be fixed *before* collecting
  data rather than after. First, the measurement changes the measured quantity: the probe *is* the focus
  command, so once one delivery pulls a pane into focus, every following delivery to that same pane reads
  "already focused" even though the first one really did interrupt someone — a ratio therefore looks
  *cleanest* exactly in the burst traffic that disturbs a human most. Second, aggregation hides the
  stratification that carries the question: a delivery into the session and tab a human is watching is a
  different event from one to a pane nobody is looking at, and averaging them answers neither "how common"
  nor "how bad". So each pane delivery now appends one event (timestamp, target pane, intrusion,
  `same_multiplexer_session`, `active_tab_before`/`active_tab_after`, and `tab_switched` — the strongest
  disturbance signal), folding is left to analysis, and a test pins that this script computes no rate at
  all. Unknowns are recorded as `null`, never as "did not happen": an unreadable layout gives
  `tab_switched: null` rather than `false`, an unreachable pane records no intrusion value rather than
  "already-focused" (nothing was delivered; counting it would pad the denominator), and an unfamiliar
  answer is `unknown`. The extra reading runs **only** when an observation will be recorded, because an
  unconditional extra command would change the command sequence every caller sees — the same perturbation
  problem one level up; a regression test pins the non-observing sequence. Known and recorded gap: the
  layout dump exposes no pane-to-tab mapping, so "which tab holds the target" is unavailable and the
  before/after active tab is used as a proxy.
- **Focus-theft counter, derived from a probe answer the adapter already had** (`agenttui.py`
  `addressing_intrusion` + `INTRUSION_*`, `agenttui-registry.md` §3, +6 tests) — the intrusiveness of
  pane-addressed delivery (the probe *is* the focus command) was recorded as an architectural cost with no
  measurement behind it, and the plan was to settle it with an experiment needing a human present. But
  rc=0 from the probe means the focus *actually moved* and rc=2 "already focused" means nobody was
  disturbed, so the existing preflight already answers, per delivery, whether that delivery stole
  someone's view. Delivery results now carry `addressing_intrusion`, giving the **rate** with no new
  experiment, no human present, and nothing interrupted. An unreachable pane records **no value** rather
  than "none" (nothing was delivered; counting it would pad the denominator and understate the real rate),
  and an unfamiliar non-zero answer records `unknown` rather than being assumed harmless. This answers the
  half that should be known first — how often focus theft happens, i.e. whether the cost justifies
  changing transports — and explicitly not the other half (whether another transport avoids it), which
  still needs the in-person experiment.
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

### Changed
- **`project_id` is computed at write time, not accepted as a literal** (`agenttui-registry.md`
  §2.3 / §5 step 4, both `arborist-templates/` examples, +8 tests) — the real-data sweep found a
  hand-copied `project_id` that does not recompute, alongside leaves declaring a project they do not
  sit in. The cure for that family is **not** "correct the value": the registration path should
  *compute* it from `realpath`, and an existing value that disagrees must **fail closed** rather
  than be overwritten (overwriting also erases the only trace that there was ever a disagreement).
  The send side already had this rule (ADR-0007 amendment); validating only on the send side amounts
  to letting the wrong value be written first. The templates no longer offer a `<project-id>` blank
  — **a blank is an invitation to hand-copy** — and instead name the value as derived and give the
  command that prints it. Recorded in the guide as an instance of **prevention > detection >
  judgement**: the validator can detect this, but as long as the write path accepts a literal, it
  has permanent work, and every finding it reports was avoidable.

### Fixed
- **A session that had just self-registered could never complete its first heartbeat** (`agenttui.py`
  `update_global_summary` / `write_runtime_state`, `agenttui-registry.md` §5.6/§5.7, +8 tests) — the roll-up
  refused when the agent summary or the project entry was absent, which is *exactly* the state a correct
  self-registration leaves behind, so the documented "self-register, then heartbeat" sequence could not
  complete. Worse, it refused **after** the leaf was already on disk, reporting `error` for a half-success
  with no way for the caller to tell "nothing happened" from "half happened". The roll-up now **creates what
  is missing**, on the grounds that a summary is *derived* from the leaf and the leaf is authoritative — so
  generating one needs no information the leaf lacks and there is nothing to guess; it is also the only
  mechanism that can restore the leaf/summary pair, i.e. it *is* the repair for half-registered direction B.
  Created entries carry `created_by` so an auditor can distinguish a rolled-up entry from a hand-written one;
  silent creation would let a mis-derived project id look like it had always been there. The guide's step 6
  said appending to the global index was **optional** — that was wrong and directly contradicted the entry
  injected into every session (which says to sync the summary); "optional" bought no freedom, only drift,
  since it made an already-named inconsistent state into a legal choice.
  On atomicity: two files cannot be written atomically together, so the fix does **not** pretend to be
  atomic — it makes the outcome *readable*, which is where the harm actually was. Both halves are reported
  separately, including on success. The leaf is written first deliberately: leaf-without-summary is a named,
  detectable state with a defined repair, while summary-without-leaf points at an agent that may not exist —
  given one must land first, land the one whose failure mode is diagnosable.
  **And the first draft of that reporting was a regression, caught in review**: it advised a retry. Once the
  create paths exist, the "entry absent" failure class cannot occur, so every *remaining* failure is
  structural or I/O damage — which no retry improves. Advising one would loop a caller through something
  that can never succeed, and it would trade a **loud error for a quiet half-success** — and a loud wrong
  reading gets chased down while a quiet half-success does not. Remaining failures are therefore marked
  not-self-repairing and pointed at the mechanism that actually finds them (the registry consistency
  validator reports direction B and has answer-moments), with it stated explicitly that "someone will read
  stderr" is **not** an executor, because a heartbeat runs automatically and nobody watches its stderr.
  Also corrected while here: the guide's repair for direction A referenced a `register-self` subcommand that
  **does not exist** in the shipped adapter — a repair pointing at a non-existent executor, which is itself
  the "decoration" failure this repo names elsewhere.
- **Shape 3 splits into 3a/3b — measurement overturned half of its attribution** (`agenttui-registry.md` §3)
  — two long-envelope deliveries to different targets produced an identical signature: text in the composer,
  composer not cleared, no credential error, nothing in the transcript. Under the old single row that reads as
  "long text corrupted". **But re-sending the submit key once succeeded both times, and the text was intact
  character for character.** The controlled variables say what actually differed: the first attempt used the
  *wrong* submit key and was corrected about a minute later (success); the second used the *right* key but
  only about a second after the write (failure), then succeeded on a second identical key. So the shared
  variable behind both failures is **neither the key nor text integrity — it is the interval between writing
  and submitting**: the composer had not finished consuming a long paste when the key arrived, so the key was
  swallowed into the paste stream or ignored. The two now split as **3a** (text on screen *with missing
  characters*) and **3b** (text on screen *byte-identical* yet unsubmitted) — telling them apart is just
  "are characters missing" — because their fixes differ: atomic delivery versus waiting for composer
  readiness. And 3b's fix is explicitly **not** "raise the submit-delay constant": that is the class of fix a
  later reader optimises away. The required shape is to **wait on an observable signal** — poll the screen
  until the envelope's trailing characters appear, then submit — turning "have I waited enough" from a timer
  into a criterion, the same move as the ack: replace the sender's estimate with evidence the observed side
  produced. Recorded as a *pending* inference rather than a conclusion: atomic delivery probably eases both,
  but atomicity guarantees one write call, not that the terminal finished processing it, so it may only
  narrow the window — the readiness criterion stays as the backstop.
- **The shipped adapter cannot deliver across projects, which silently voids the entire contract for that
  whole class of delivery** (`agenttui-registry.md` §3 gap list) — leaf lookup is scoped to a single
  repository and the repository root is a single-valued parameter, so sender and target must share a repo. The
  global index *does* carry each project's path, so cross-project addressing is available in the data; the
  adapter simply does not use it. The consequence is not a missing convenience but a systematic bypass: a
  cross-project delivery can only be done by hand, and a hand-made injection skips **every** contract rule —
  existence preflight, capability check, the outcome model, ack consumption, framed writes, the widened
  verification window, focus-theft recording. Every hardening added today is inert there. The attribution is
  spelled out because it decides the fix: in one measured cross-project attempt the sender used the enqueue
  key on an idle target, violating the routing rule — and filing that as *someone's routing mistake* is the
  wrong reading, because a hand injector **must re-implement routing itself** (liveness, per-brand keys,
  interval, verification), and the odds of getting six contract rules right by hand at the keyboard are low.
  **Errors of this kind are products of the gap, not of carelessness** — filed as carelessness, the next
  person repeats it; filed as a gap, the gap gets closed. The general form is one step past "a gate with no
  enforcer is decoration": **a contract that is implemented but unusable for an entire class of case
  degenerates into decoration for that class — silently, because the caller cannot see what they bypassed.**
- **Shape 6 splits in two with opposite handling, and the launch invariant written one commit earlier had a
  logical hole** (`agenttui-registry.md` §3) — continuing the same measurement: the pane later showed the
  self-update had finished but the CLI **required a manual restart and would not start itself**. At that
  moment the pane was just a shell, the envelope sent into it was consumed as a command, and the target ATUI
  **had never existed**. So **6a "starting up"** (waiting works) and **6b "start not completed and will not
  complete on its own"** (waiting is useless; the launch action must be re-issued) need separating — and the
  split is itself the argument for a causal readiness criterion: the two are distinguishable *on screen*,
  but only by recognising each CLI's restart wording, which is exactly the kind of fragile single-observation
  constant this guide flags elsewhere, whereas **"it never self-registers, however long you wait" decides 6b
  with no such knowledge**. Screen shape guesses; self-registration decides.
  The invariant "do not deliver to a spawned ATUI before its self-registration completes" was then found to
  be unsatisfiable as written: **self-registration requires the session to be activated first**, and
  activation is what the first message does — so that phrasing forbids ever sending the first message. It now
  separates by sender: the **spawner's first delivery** only requires that the CLI has taken over the
  terminal, and it **carries its own criterion** (send a short nonce-bearing pointer; the nonce reaching the
  target transcript proves readiness *and* receipt — and its absence is 6a, the one and only case where
  re-sending the same envelope is permitted, precisely because it is the one shape where waiting works),
  while a **third party's later delivery** does require self-registration, because a third party can only
  learn the address from the registry and guessing a pane handle is the very error the self-identification
  gate forbids. The difference is not strictness but **information available**: the spawner knows what it
  just started and where; a third party does not. Collapsing them into one rule either forbids the first
  delivery or licenses a third party to guess.
- **The "trap SIGHUP" cleanup mechanism recorded one commit earlier is refuted by measurement under real use**
  (`agenttui-registry.md` §5.0-b) — closing the outer pane does deliver a catchable `SIGHUP`, and trapping it
  passed end-to-end **in a test where the pane's only foreground process was a script**. Under real use it
  failed: after the human closed the pane, the inner client was gone, the inner **session survived**, and the
  ATUI **kept running** — the "invisible live agent" this section exists to prevent. The cause is that the two
  process structures are not isomorphic: in the test the trap sat on the script that *was* the foreground
  process, whereas a human pastes the command into an **interactive shell**, so the trap sits on a shell with
  job control whose SIGHUP handling differs — the trap never ran. The reliable mechanism therefore goes back
  to the multiplexer's built-in destroy-on-last-client-detach, which depends on neither a signal nor a shell
  type and so behaves the same either way; its known cost is that an *inner* detach is also caught, which
  matters only for someone who detaches at that layer. The general rule is recorded as the more valuable part:
  **when validating a mechanism triggered by a human action, the test's process structure must be isomorphic
  to real use** — "the signal arrives" and "the trap runs" are two different claims, and passing the first does
  not establish the second, while the difference between them (script shell versus interactive shell) is
  invisible from inside the test.
- **Two corrections to the ack module found while reviewing it, both silent-failure shaped** — (a) the
  envelope header parser only handled the **multi-line** form, so an envelope flattened onto one line
  produced **no ack at all**; since neither the composer's newline handling nor a brand's hook-payload
  normalisation is under this repo's control, that failure was both reachable and silent — and silent means
  *indistinguishable from "the target never submitted"*, the exact confusion this facility exists to remove.
  Both forms now parse, the body is cut at its marker so prose containing `key=value` can never contribute a
  header field, and all four shapes (flat, multi-line, flattened-without-nonce, bare mention in prose) are
  pinned by tests. (b) The multiplexer session lifecycle prescription shipped one commit earlier named the
  wrong mechanism: "destroy the session when no client is attached" is an **inference, not a cause** — it
  only sees whether a client is attached *right now*, so it cannot tell "the human closed the window" from
  "the human stepped away", and those two want opposite handling. Measured replacement, per case, in an
  isolated test session: closing the outer tab delivers a **catchable `SIGHUP`** to the pane's foreground
  process (verified end to end — inner session present before, gone after), detaching the *outer* session
  sends no signal at all and both sessions survive, and detaching the *inner* session returns normally.
  Trapping the close event is therefore both more precise and kinder: an inner detach becomes a legitimate
  operation again instead of "press one key by mistake and kill a working agent". The section also records
  *why* the wrong prescription was written: the two layers each have a "detach" and they were conflated, so
  the guide now forbids the bare word — it must always say **outer** detach or **inner** detach. Recorded as
  unverified: whether other multiplexer implementations also signal on pane close (it is observed behaviour,
  not a standard requirement).
- **The tiebreak shipped one commit earlier rested on a false premise: "cross-repo duplicate = stray
  registration, delete the wrong one"** (`agenttui-registry.md` §2.2.1, `validate_agenttui_registry.py`
  wording, +2 tests) — reading the leaves' actual contents (rather than judging from the finding alone)
  showed most cross-repo duplicate claims are **self-declared, authorised cross-repo mirror
  registrations**: the leaf names its authoritative entry, why it exists, and who authorised it, and its
  declared project path deliberately points at the repo where that agent really works. Deleting such a
  leaf removes the *only* way another repo can reach that agent. So the guide now makes callers **judge
  the kind of duplication before judging which side is wrong**, and states the real conclusion: the
  root cause is a **schema gap**, not dirty data — the global-uniqueness rule has no first-class exception
  for cross-repo reachability, so a legitimate need can only be expressed by *looking* like a duplicate,
  which the validator must then report as high severity. Until that field exists, the high-severity report
  on a self-declared mirror is a **known false positive** whose handling is "issue a named ruling, delete
  nothing". One risk is recorded as surviving the reclassification: mirrors share a pane handle, so
  delivery lands on the same real target *today*, but becomes a genuine silent misdelivery once that pane
  is reused — a mirror's pane handle must therefore expire together with the authoritative entry's.
- **Tiebreak input #2 was written as a universal rule but is brand-dependent** (same files) — "decide
  ownership from the session_file path" holds only for a brand that stores sessions in per-project
  directories. Another brand keeps rollout logs in a single global directory, so its session-file path
  carries **no** ownership information and using it would produce confident wrong rulings; the substitute
  reading is the cwd the session records about itself in its first rollout entry. Both the guide and the
  validator's inline text now scope this input by brand, pinned by a test.
- **A safety claim shipped one commit earlier was wrong** (`agenttui-registry.md` §3) — the previous entry
  justified measuring the already-focused case with "probing the pane you occupy steals nobody's focus".
  That reasoning conflates *the process runs in this pane* with *this pane is the client's focus*; *process
  location is not client focus*. The measurement happened to disturb nobody only because it happened to
  return rc=2; had it returned rc=0, the command would have pulled the client's view to that pane. The
  correct statement is: **it cannot be guaranteed in advance, and the return code says afterwards whether
  it happened** — which is exactly what made the focus-theft counter above possible.
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
