---
name: arborist-relocate-project
description: Rename or move an Arborist-managed project without breaking Claude Code/Codex history, Arborist agent leaves, the global project index, host configuration, managed routing paths, or hgit. Use when a repository containing `.arborist/`, `.trellis/host-config.yaml`, or `.harness-vcs/` changes its absolute path or project name, including an Arborist adoption instance or the Arborist repository itself.
---

# Relocate an Arborist-managed project

Relocate the working tree, delegate chat-store migration to
`cc-relocate-project`, then update Arborist's path-derived state with the bundled
script. Keep project-specific prose and delivered letters under agent review.

## Hard rules

- Default to dry-run. Require explicit user authorization before `--apply`.
- Never merge two existing Claude project stores or two Arborist index entries.
- Compute `project_id` from the new realpath; never copy a supplied ID without
  recomputing it.
- Create a compatibility symlink before touching live sessions. Prefer closing
  affected Claude Code/Codex sessions; a live relocation is an explicit exception.
- Do not rename `pane_ref.session`: it is a multiplexer session name.
- Do not broadly replace paths in chat transcripts, sendbox letters, task
  archives, tool output, or pasted content.
- Every substitution is anchored to a whole path component or whole word. Never
  reintroduce bare substring replacement: an old name that is a prefix of the
  new one (`<name>` -> `<name>-main`) corrupts silently on a second run.
- Run the helper in the tree that owns `.arborist/`. If `.arborist/` is a
  symlink into another tree, relocate there instead.
- Do not commit or push unless the user separately authorizes it. If the adopted
  project requires harness history, stage only explicit files with `hgit add -f`.

## Workflow

### 1. Preflight

Normalize the old/new absolute paths and verify:

- the old working tree exists and the new working tree does not;
- `.arborist/agents/*/spec.json`, `~/.arborist/index.json`, and
  `.trellis/host-config.yaml` agree on the old path;
- the computed old `project_id` agrees with current leaves/index;
- no unrelated entry already uses the new path or computed new ID;
- affected chat stores and live processes are identified;
- Git/hgit worktrees are inspected so unrelated changes remain untouched.

Before moving, inspect the state helper's arguments:

```bash
python3 <this-skill>/scripts/relocate_arborist_state.py --help
```

The helper operates on the new project root, so run its dry-run after step 2.

### 2. Move and preserve compatibility

Move the working tree and immediately create an old-path compatibility symlink.
Use platform-native commands and explicit paths. Confirm both old and new
spellings resolve to the new realpath.

### 3. Relocate Claude Code and Codex history

**Pinned dependency.** This step delegates to the `cc-relocate-project` Skill.
Required build:

- it must ship a bundled `relocate_sessions.py` next to its `SKILL.md`;
- it must be at **commit `daafbf0` or later** — that is where Codex support
  (rollout `session_meta`, SQLite `threads`, path-keyed trust/hook config)
  landed. Earlier or trimmed copies handle Claude only.

Before starting, prove the build you loaded is usable:

```bash
ls <cc-relocate-project-skill>/relocate_sessions.py
python3 <cc-relocate-project-skill>/relocate_sessions.py --help
```

Distributions that ship `SKILL.md` alone (no bundled script) do not satisfy this
step. Stop and obtain the pinned build; chat migration is part of this
operation, not an optional cleanup.

**Precedence when the two Skills disagree.** `cc-relocate-project` also
documents moving the directory itself and preflighting that the new path does
not exist. In this combined procedure those steps are already done by step 2
(move, then compatibility symlink), so:

- ignore its move/`test ! -e` preflight prose — the new path exists by design
  here, and the old path resolves through the symlink;
- run only its chat-store migration (`relocate_sessions.py`);
- on live sessions, `cc-relocate-project` lists them under "do not use". That
  is the safer default and stays authoritative unless the user explicitly
  authorizes a live relocation under this Skill's hard rules — the compatibility
  symlink from step 2 is what makes that exception survivable, and it must stay
  until every affected session is reopened.

Require these postconditions:

- Claude's new encoded project directory exists and its structured cwd values
  equal the new path.
- Codex's selected rollout `session_meta.payload.cwd` and SQLite `threads.cwd`
  equal the new path; SQLite integrity is `ok`.
- Codex path-keyed trust/hook configuration uses the new path.

### 4. Update Arborist state

Run:

```bash
python3 <this-skill>/scripts/relocate_arborist_state.py \
  --old-path "$OLD_PATH" --new-path "$NEW_PATH"

python3 <this-skill>/scripts/relocate_arborist_state.py \
  --old-path "$OLD_PATH" --new-path "$NEW_PATH" --apply
```

The helper rewrites a value only when that value is currently the old one, and
only on whole-component / whole-word matches:

- all Arborist leaf `project.path` / `project_id` values and project-name words
  in leaf descriptions;
- Claude `runtime.session_file`, by renaming the encoded project **directory
  component**, after confirming the relocated file exists;
- the one exact global index entry;
- `AGENTS.md`, `.trellis/workflow.md`;
- `.trellis/host-config.yaml`: `project:` and `repo_root:` only if they still
  hold the old name/path, other lines by anchored path match;
- `.harness-vcs/config` `core.worktree`.

It deliberately preserves identity fields, Codex date-based runtime paths, and
`pane_ref`.

Refusals and safety properties, all evaluated before the first byte is written:

- identical `--old-path`/`--new-path`;
- overlapping spellings, where one path is a prefix of the other or one project
  name contains the other. Substitution stays anchored, so pass
  `--allow-nested-rename` once the overlap is confirmed intentional — for
  example `<name>` -> `<name>-main`;
- `.arborist/` or `.arborist/agents/` being a symlink;
- no trace of `--old-path` in leaf specs, the global index, or host-config while
  no layer holds the new path either — that means the old path is mistyped;
- `.harness-vcs/` present but not a usable, writable git directory;
- a `runtime.session_file` whose relocated target does not exist yet.

`--apply` backs up every file it is about to rewrite under
`~/.arborist/backups/arborist-relocate-project-<timestamp>/` (override with
`--backup-dir`) and rolls the rewrites back if a later step fails. Re-running
`--apply` after a completed relocation is a reported no-op.

Regression tests live in `tests/` next to `scripts/`:

```bash
python3 -m unittest discover -s <this-skill>/tests -v
```

### 5. Agent-reviewed sweep

Search exact old absolute paths outside VCS internals and chat transcripts.
Classify each hit:

- current routing/configuration: update;
- project-facing name such as a README heading: update;
- delivered sendbox letter: preserve conclusions and filename, update actionable
  absolute paths, and append a dated rename note;
- historical transcript/task/workspace content: preserve.

Keep linked sibling repository paths unchanged. Verify brand-compat managed
blocks after path edits.

### 6. Verify and hand off

Verify:

- new `project_id` recomputes from the new realpath everywhere;
- global index retains every unrelated project unchanged;
- all leaf `session_file` paths exist;
- product Git sees only intended project-facing changes and no harness files;
- hgit sees only intended harness changes;
- linked-repo symlinks remain ignored and valid;
- compatibility symlink remains until the user reopens affected sessions.

Report the new path/ID, migrated Claude/Codex thread counts, backups, residual
historical old-name mentions, uncommitted files, and whether live-session
notifications were safe. Never trust stale `pane_ref` without checking the
current multiplexer pane.
