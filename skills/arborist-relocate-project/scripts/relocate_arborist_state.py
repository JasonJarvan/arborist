#!/usr/bin/env python3
"""Update Arborist-managed state after a project directory rename.

Run the chat-store relocation first. This script does not move the working tree
and does not commit; dry-run is the default.

Safety model:

- every path/name substitution is anchored (whole path component, whole word),
  so re-running the same relocation is a no-op instead of producing nested
  spellings such as ``<name>-main-main``;
- overlapping old/new spellings are refused unless ``--allow-nested-rename``;
- symlinked targets are written through to their realpath, so a worktree
  symlink keeps pointing at the main tree and the main tree receives the edit;
- everything that can fail is probed in preflight; ``--apply`` backs up every
  file it is about to touch and rolls back if a later step fails.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Characters that may continue a path component or a project name. A match is
# only accepted when it is not glued to one of these on either side, so
# ``/x/proj`` never matches inside ``/x/proj-main`` and ``proj`` never matches
# inside ``proj-main`` or ``project``.
TOKEN_CHARS = r"A-Za-z0-9._~\-"


def lexical(value: str) -> str:
    return os.path.abspath(os.path.expanduser(value)).rstrip("/\\")


def project_id(path: str) -> str:
    normalized = os.path.realpath(path).rstrip("/\\")
    return hashlib.sha256(normalized.encode()).hexdigest()[:12]


def claude_encode(path: str) -> str:
    return re.sub(r"[:\\/_]", "-", path.rstrip("/\\"))


def anchored_sub(text: str, old: str, new: str) -> tuple[str, int]:
    """Replace `old` with `new` only where `old` is a whole token.

    Used for both absolute paths and bare project names. The replacement is
    applied through a callable so backslashes in `new` are literal.
    """
    pattern = re.compile(rf"(?<![{TOKEN_CHARS}]){re.escape(old)}(?![{TOKEN_CHARS}])")
    return pattern.subn(lambda _match: new, text)


def resolve_for_write(path: Path) -> Path:
    """Return the real file a write should land on.

    Writing through a symlink matters under the worktree discipline: harness
    files are often symlinks back into the main tree. Replacing the symlink
    itself would silently detach the worktree and leave the main tree stale.
    """
    if path.is_symlink():
        return Path(os.path.realpath(path))
    return path


def atomic_write(path: Path, text: str) -> None:
    target = resolve_for_write(path)
    stat = target.stat()
    fd, tmp_name = tempfile.mkstemp(prefix=f"{target.name}.relocate-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, stat.st_mode)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


@dataclass
class Plan:
    """One pending file rewrite, with the bytes needed to roll it back."""

    path: Path
    label: str
    backup_name: str
    original: str
    updated: str


@dataclass
class Evidence:
    old: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)


def dump_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def relocate_component(value: str, old_component: str, new_component: str) -> str | None:
    """Rename whole path components of `value`; None when nothing matches.

    Claude's encoded project directories use ``-`` both as a separator and
    inside names, so substring replacement cannot be anchored. Comparing whole
    components can.
    """
    parts = list(Path(value).parts)
    hits = [index for index, part in enumerate(parts) if part == old_component]
    if not hits:
        return None
    for index in hits:
        parts[index] = new_component
    return str(Path(*parts))


def unquote(value: str) -> tuple[str, str]:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1], value[0]
    return value, ""


def split_line(line: str) -> tuple[str, str]:
    ending = line[len(line.rstrip("\r\n")) :]
    return line[: len(line) - len(ending)], ending


def scalar(body: str, key: str) -> re.Match[str] | None:
    return re.fullmatch(rf"({re.escape(key)}:\s*)(\S.*?)(\s*)", body)


def nested_reason(old: str, new: str, old_name: str, new_name: str) -> str | None:
    if new.startswith(old) or old.startswith(new):
        return "one absolute path is a prefix of the other"
    if old_name != new_name and (old_name in new_name or new_name in old_name):
        return "one project name contains the other"
    return None


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Single probe/execute helper so dry-run and --apply share `check=` semantics."""
    return subprocess.run(args, capture_output=True, text=True, check=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-path", required=True)
    parser.add_argument("--new-path", required=True)
    parser.add_argument("--project-root")
    parser.add_argument("--new-name")
    parser.add_argument("--global-index", default="~/.arborist/index.json")
    parser.add_argument("--backup-dir")
    parser.add_argument(
        "--allow-nested-rename",
        action="store_true",
        help="permit an old/new pair where one spelling contains the other "
        "(for example <name> -> <name>-main); substitution stays anchored, "
        "this flag only records that the overlap is intended",
    )
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def plan_leaf_specs(
    spec_files: list[Path],
    root: Path,
    old: str,
    new: str,
    old_name: str,
    new_name: str,
    new_id: str,
) -> list[Plan]:
    plans: list[Plan] = []
    for path in spec_files:
        original = path.read_text(encoding="utf-8")
        value = json.loads(original)
        changed = False
        project = value.get("project", {})
        if project.get("path") == old:
            project["path"] = new
            changed = True
        if project.get("path") == new and project.get("project_id") != new_id:
            project["project_id"] = new_id
            changed = True
        description = value.get("description")
        if isinstance(description, str) and old_name != new_name:
            updated, count = anchored_sub(description, old_name, new_name)
            if count:
                value["description"] = updated
                changed = True
        if changed:
            relative = str(path.relative_to(root))
            plans.append(Plan(path, relative, f"project/{relative}", original, dump_json(value)))
    return plans


def plan_leaf_runtimes(
    runtime_files: list[Path],
    root: Path,
    old_encoded: str,
    new_encoded: str,
) -> list[Plan]:
    plans: list[Plan] = []
    for path in runtime_files:
        original = path.read_text(encoding="utf-8")
        value = json.loads(original)
        session_file = value.get("session_file")
        if not isinstance(session_file, str):
            continue
        replacement = relocate_component(session_file, old_encoded, new_encoded)
        if replacement is None:
            continue
        if not Path(replacement).is_file():
            raise SystemExit(
                "preflight: relocated Claude session file is missing; run "
                f"cc-relocate-project first: {replacement}"
            )
        value["session_file"] = replacement
        relative = str(path.relative_to(root))
        plans.append(Plan(path, relative, f"project/{relative}", original, dump_json(value)))
    return plans


def plan_prose(path: Path, relative: str, old: str, new: str) -> Plan | None:
    if not path.is_file():
        return None
    original = path.read_text(encoding="utf-8")
    updated, count = anchored_sub(original, old, new)
    if not count:
        return None
    return Plan(path, relative, f"project/{relative}", original, updated)


def plan_host_config(
    path: Path,
    relative: str,
    old: str,
    new: str,
    old_name: str,
    new_name: str,
) -> tuple[Plan | None, list[str]]:
    """Rewrite host-config only where the current value is the old one.

    host-config is the single source of truth for instance-specific values, so
    an unconditional rewrite would make it disagree with every other layer when
    the operator mistypes --old-path.
    """
    warnings: list[str] = []
    if not path.is_file():
        return None, warnings
    original = path.read_text(encoding="utf-8")
    changed = 0
    output: list[str] = []
    for line in original.splitlines(keepends=True):
        body, ending = split_line(line)
        match = scalar(body, "project")
        if match:
            value, quote = unquote(match.group(2))
            if value == old_name:
                body = f"{match.group(1)}{quote}{new_name}{quote}{match.group(3)}"
                changed += 1
            elif value != new_name:
                warnings.append(f"host-config project is neither old nor new name: {value}")
            output.append(body + ending)
            continue
        match = scalar(body, "repo_root")
        if match:
            value, quote = unquote(match.group(2))
            if lexical(value) == old:
                body = f"{match.group(1)}{quote}{new}{quote}{match.group(3)}"
                changed += 1
            elif lexical(value) != new:
                warnings.append(f"host-config repo_root is neither old nor new path: {value}")
            output.append(body + ending)
            continue
        body, count = anchored_sub(body, old, new)
        changed += count
        output.append(body + ending)
    if not changed:
        return None, warnings
    return Plan(path, relative, f"project/{relative}", original, "".join(output)), warnings


def host_config_evidence(path: Path, old: str, new: str, old_name: str, new_name: str) -> Evidence:
    evidence = Evidence()
    if not path.is_file():
        return evidence
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        match = scalar(line, "project")
        if match:
            value = unquote(match.group(2))[0]
            if value == old_name:
                evidence.old.append("host-config project")
            elif value == new_name:
                evidence.new.append("host-config project")
            continue
        match = scalar(line, "repo_root")
        if match:
            value = lexical(unquote(match.group(2))[0])
            if value == old:
                evidence.old.append("host-config repo_root")
            elif value == new:
                evidence.new.append("host-config repo_root")
    if anchored_sub(text, old, new)[1]:
        evidence.old.append("host-config path reference")
    return evidence


def plan_index(
    index_path: Path,
    old: str,
    new: str,
    old_id: str,
    new_id: str,
    new_name: str,
) -> tuple[Plan | None, Evidence]:
    evidence = Evidence()
    if not index_path.is_file():
        return None, evidence
    original = index_path.read_text(encoding="utf-8")
    index_data = json.loads(original)
    projects = index_data.get("projects", [])
    matches = [entry for entry in projects if entry.get("path") == old]
    if len(matches) > 1:
        raise SystemExit(f"preflight: multiple global index entries match old path: {old}")
    new_matches = [
        entry
        for entry in projects
        if entry.get("path") != old
        and (entry.get("path") == new or entry.get("project_id") == new_id)
    ]
    if matches:
        evidence.old.append("global index")
    if new_matches:
        evidence.new.append("global index")
    if matches and new_matches:
        raise SystemExit("preflight: new path/project_id already belongs to another index entry")
    if not matches and len(new_matches) > 1:
        raise SystemExit("preflight: multiple global index entries match new path/project_id")
    if not matches and new_matches:
        current = new_matches[0]
        if current.get("path") != new or current.get("project_id") != new_id:
            raise SystemExit("preflight: new path/project_id is split across conflicting entries")
    if not matches:
        return None, evidence
    entry = matches[0]
    if entry.get("project_id") != old_id:
        raise SystemExit(
            f"preflight: global index old project_id mismatch: expected {old_id}, "
            f"found {entry.get('project_id')}"
        )
    entry["path"] = new
    entry["project_id"] = new_id
    entry["name"] = new_name
    plan = Plan(index_path, str(index_path), index_path.name, original, dump_json(index_data))
    return plan, evidence


def probe_harness(hgit_dir: Path) -> str:
    """Fail preflight unless the harness git dir is usable and writable."""
    revision = run_git(["git", f"--git-dir={hgit_dir}", "rev-parse", "--git-dir"])
    if revision.returncode != 0:
        raise SystemExit(
            f"preflight: {hgit_dir} is not a usable git directory, so core.worktree "
            f"cannot be updated: {revision.stderr.strip()}"
        )
    config = run_git(["git", f"--git-dir={hgit_dir}", "config", "--get", "core.worktree"])
    if config.returncode not in (0, 1):
        raise SystemExit(
            f"preflight: cannot read core.worktree from {hgit_dir}: {config.stderr.strip()}"
        )
    config_file = hgit_dir / "config"
    if config_file.is_file() and not os.access(resolve_for_write(config_file), os.W_OK):
        raise SystemExit(f"preflight: {config_file} is not writable")
    return config.stdout.strip()


def apply_plans(plans: list[Plan], backup_dir: Path, worktree_cmd: list[str] | None) -> Path | None:
    """Back up every target, write everything, then run git; roll back on failure."""
    created_backup: Path | None = None
    if plans:
        backup_dir.mkdir(parents=True, exist_ok=False)
        created_backup = backup_dir
        for plan in plans:
            destination = backup_dir / plan.backup_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolve_for_write(plan.path), destination)
    written: list[Plan] = []
    try:
        for plan in plans:
            atomic_write(plan.path, plan.updated)
            written.append(plan)
        if worktree_cmd:
            result = run_git(worktree_cmd)
            if result.returncode != 0:
                raise RuntimeError(
                    f"git config core.worktree failed: {result.stderr.strip() or result.returncode}"
                )
    except Exception as exc:
        restore_failures: list[str] = []
        for plan in reversed(written):
            try:
                atomic_write(plan.path, plan.original)
            except Exception:  # pragma: no cover - restore is best effort
                restore_failures.append(plan.label)
        detail = f"rolled back {len(written)} file(s)"
        if restore_failures:
            detail = f"rollback incomplete; restore by hand: {', '.join(restore_failures)}"
        hint = f" backups: {created_backup}" if created_backup else ""
        raise SystemExit(f"apply failed: {exc}; {detail}.{hint}") from exc
    return created_backup


def main() -> int:
    args = parse_args()
    old = lexical(args.old_path)
    new = lexical(args.new_path)
    if old == new:
        raise SystemExit("preflight: --old-path and --new-path are identical; nothing to relocate")
    root = Path(args.project_root or new).expanduser().resolve()
    if str(root) != os.path.realpath(new):
        raise SystemExit(f"project root must resolve to new path: root={root}, new={new}")
    if not root.is_dir():
        raise SystemExit(f"new project root does not exist: {root}")
    new_name = args.new_name or Path(new).name
    old_name = Path(old).name
    new_id = project_id(new)
    old_id = hashlib.sha256(old.encode()).hexdigest()[:12]
    apply = args.apply

    if not args.allow_nested_rename:
        reason = nested_reason(old, new, old_name, new_name)
        if reason:
            raise SystemExit(
                f"preflight: refusing an overlapping rename ({reason}). Substitution is "
                "anchored and safe, but confirm the intent and re-run with "
                "--allow-nested-rename."
            )

    arborist_dir = root / ".arborist"
    leaf_dir = arborist_dir / "agents"
    for candidate in (arborist_dir, leaf_dir):
        if candidate.is_symlink():
            raise SystemExit(
                f"preflight: {candidate} is a symlink; run the helper in the tree that owns "
                "the leaves so leaf writes cannot land in another project"
            )

    spec_files = sorted(leaf_dir.glob("*/spec.json")) if leaf_dir.is_dir() else []
    runtime_files = sorted(leaf_dir.glob("*/runtime.json")) if leaf_dir.is_dir() else []
    evidence = Evidence()
    leaf_old_ids: set[str] = set()
    for path in spec_files:
        value = json.loads(path.read_text(encoding="utf-8"))
        project = value.get("project", {})
        if project.get("path") == old:
            leaf_old_ids.add(project.get("project_id"))
            evidence.old.append(f"leaf {path.parent.name}")
        elif project.get("path") == new:
            evidence.new.append(f"leaf {path.parent.name}")
            if project.get("project_id") not in (new_id, None):
                raise SystemExit(f"preflight: new-path leaf has wrong project_id: {path}")
    if leaf_old_ids and leaf_old_ids != {old_id}:
        raise SystemExit(
            f"preflight: old-path leaf project_id mismatch: expected {old_id}, "
            f"found {sorted(leaf_old_ids)}"
        )

    host_config = root / ".trellis" / "host-config.yaml"
    host_evidence = host_config_evidence(host_config, old, new, old_name, new_name)
    evidence.old.extend(host_evidence.old)
    evidence.new.extend(host_evidence.new)

    index_path = Path(args.global_index).expanduser()
    index_plan, index_evidence = plan_index(index_path, old, new, old_id, new_id, new_name)
    evidence.old.extend(index_evidence.old)
    evidence.new.extend(index_evidence.new)

    notes: list[str] = []
    if not evidence.old:
        if not evidence.new:
            raise SystemExit(
                f"preflight: no evidence of {old} in leaf specs, the global index, or "
                "host-config, and no layer already holds the new path. Check --old-path."
            )
        notes.append(f"no {old} references remain; state already reflects {new}")

    hgit_dir = root / ".harness-vcs"
    worktree_cmd: list[str] | None = None
    if hgit_dir.is_dir():
        current_worktree = probe_harness(hgit_dir)
        if current_worktree != new:
            worktree_cmd = ["git", f"--git-dir={hgit_dir}", "config", "core.worktree", new]

    old_encoded = claude_encode(old)
    new_encoded = claude_encode(new)
    plans: list[Plan] = []
    plans.extend(plan_leaf_specs(spec_files, root, old, new, old_name, new_name, new_id))
    plans.extend(plan_leaf_runtimes(runtime_files, root, old_encoded, new_encoded))
    for relative in ("AGENTS.md", ".trellis/workflow.md"):
        plan = plan_prose(root / relative, relative, old, new)
        if plan:
            plans.append(plan)
    host_plan, host_warnings = plan_host_config(
        host_config, str(host_config.relative_to(root)), old, new, old_name, new_name
    )
    if host_plan:
        plans.append(host_plan)
    if index_plan:
        plans.append(index_plan)

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"{mode}: Arborist state {old} -> {new}")
    print(f"new_name={new_name} project_id={new_id}")
    for note in notes:
        print(f"  note {note}")
    for warning in host_warnings:
        print(f"  warning {warning}")
    for plan in plans:
        print(f"  update {plan.label}")
    if worktree_cmd:
        print("  update .harness-vcs/config (core.worktree)")
    if not plans and not worktree_cmd:
        print("  no changes")
    if not apply:
        return 0

    if args.backup_dir:
        backup_dir = Path(args.backup_dir).expanduser()
        if backup_dir.exists():
            raise SystemExit(f"--backup-dir already exists: {backup_dir}")
    else:
        timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        parent = index_path.parent / "backups"
        backup_dir = parent / f"arborist-relocate-project-{timestamp}"
        attempt = 1
        while backup_dir.exists():
            backup_dir = parent / f"arborist-relocate-project-{timestamp}-{attempt}"
            attempt += 1
    created_backup = apply_plans(plans, backup_dir, worktree_cmd)
    if created_backup:
        print(f"backup: {created_backup}")

    for path in spec_files + runtime_files:
        if path.is_file():
            json.loads(path.read_text(encoding="utf-8"))
    if index_path.is_file():
        json.loads(index_path.read_text(encoding="utf-8"))
    total = len(plans) + (1 if worktree_cmd else 0)
    print(f"Applied {total} Arborist state updates; no commit was created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
