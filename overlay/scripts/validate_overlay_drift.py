#!/usr/bin/env python3
"""Report how far one repo's overlay copy has fallen behind the upstream pin.

WHY
---
The overlay is laid into each adopting repo by copy, and copies of content whose
correct form is identical everywhere *will* diverge. On this codebase that is an
observed fact rather than a risk: one full round of catching up was completed, and
the gap reopened afterwards. Without a mechanical reading, "keep the copies in
step" is an honour system, and this is what an honour system produces.

This validator is that reading. It does not converge anything.

THREE FINDINGS, NEVER MERGED
----------------------------
Reporting them together would be the same as not reporting: they have different
causes, different owners, and opposite handling.

  behind      the recorded baseline commit is not the pinned commit, and commits
              between them touched the overlay. Cause: upstream moved. Repair:
              re-lay. Countable: how many commits, which files.
  drifted     a file's measured digest is not the digest recorded at laying time,
              and the deviation is **not** declared. Cause: somebody edited a
              copy. Repair: find out who and why *before* overwriting it.
  intentional the same measurement, but the repo has declared the deviation with a
              `reason` and a `decided_by`. Still listed, every time -- declared is
              not invisible. Suppressing it would put the honour system back, one
              level down; hiding it inside `drifted` would make the report so noisy
              that the undeclared ones stop being read.

All three can hold at once, and all three are printed when they do.

FAIL CLOSED
-----------
Absent provenance exits 2, never 0. "No baseline" and "never diverged" produce the
same silence, and a validator that resolves that silence in the reassuring direction
is worse than no validator: it converts an unknown into a certificate. The same
applies to the pin: if the pinned upstream tree is gone, or the pinned commit is not
reachable in the tree it names, that is exit 2 -- not "assume fine". A pin that
cannot be verified has stopped being a pin.

NOT A GATE ON STARTING WORK
---------------------------
It reports and prints the commands to reproduce the reading; it does not block. Two
reasons. A partly adopted or long-behind repo would otherwise be unable to start any
work at all, including the work of catching up. And per verification-and-gates,
prevention outranks detection: the surfaces that *can* be made structurally
incapable of drifting should be made so, and a blocking check on those is a
detection tax paid for a problem prevention already solved.

READ-ONLY, WITH ONE NAMED EXCEPTION TO "NO EXTERNAL COMMANDS"
-------------------------------------------------------------
No `--fix`. Nothing is written anywhere, and no file in any other repo is touched.
It does run `git`, which its sibling registry validator deliberately does not --
justified narrowly: only query subcommands (`rev-parse`, `cat-file`, `rev-list`,
`log`, `diff-tree`) against the pinned tree, all of which read the object store and
perturb nothing observable. "Is this commit reachable" has no substitute that does
not reimplement a git object walk, and reimplementing one to avoid calling git would
be the more dangerous choice.

Exit codes: 0 in-sync; 1 findings (behind and/or drifted and/or intentional);
2 provenance or pin unusable (fail closed).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

ARBORIST_HOME_ENV = "ARBORIST_HOME"


def arborist_home() -> Path:
    """The machine-level Arborist root: `$ARBORIST_HOME`, else `~/.arborist`.

    Unset **and** empty both resolve to `~/.arborist`. Mirrors the resolver in
    `agenttui.py`; a test pins them to the same answers.
    """

    override = os.environ.get(ARBORIST_HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".arborist"


DEFAULT_GLOBAL_INDEX = arborist_home() / "index.json"
DEFAULT_PIN = arborist_home() / "provenance" / "upstream.json"

# The two machine-level records this validator is the **named consumer** of. Both are
# written by `arborist_provenance.py`; consuming them here is what stops them from
# becoming records nobody reads, which is how this class of problem regenerates.
DEFAULT_AUTHORITY = arborist_home() / "provenance" / "authority-content.json"
DEFAULT_EXECUTIONS = arborist_home() / "provenance" / "executions.jsonl"

# Where the global entry points live. Their presence is what makes an absent
# authority record a fail-closed condition rather than an irrelevant one: if nothing
# is executed through the machine's single copy, there is nothing to record; if
# something is, an absent record means nobody knows what ran.
DEFAULT_BIN = arborist_home() / "bin"

PROVENANCE_RELATIVE = ".arborist/overlay-provenance.json"

# What the laying script lays, and where each thing lands. The two trees do not share
# a layout, and the mapping is not derivable from either side alone: `overlay/scripts/`
# is fanned out to three different destinations, and some of what lives there is not
# laid at all.
#
# The laying script is the **writer** of this contract and this is a **reader** of it.
# A reader that has fallen behind its writer shows up as an artifact present in the
# repo but mapped nowhere, which is reported rather than skipped -- so the duplication
# is at least self-announcing.
LAID: tuple[tuple[str, str, bool], ...] = (
    # (upstream path, repo-relative path, is a whole tree)
    ("overlay/spec/guides", ".trellis/spec/guides", True),
    ("overlay/arborist-templates", ".arborist/templates", True),
    ("overlay/scripts/agenttui.py", ".trellis/scripts/agenttui.py", False),
    (
        "overlay/scripts/agenttui_submit_ack.py",
        ".trellis/scripts/agenttui_submit_ack.py",
        False,
    ),
    (
        "overlay/scripts/arborist_brand_capacity.py",
        ".trellis/scripts/arborist_brand_capacity.py",
        False,
    ),
    (
        "overlay/scripts/validate_adr_numbers.py",
        ".trellis/scripts/validate_adr_numbers.py",
        False,
    ),
    (
        "overlay/scripts/validate_harness_persistence.py",
        ".trellis/scripts/validate_harness_persistence.py",
        False,
    ),
    (
        "overlay/scripts/validate_claim_provenance.py",
        ".trellis/scripts/validate_claim_provenance.py",
        False,
    ),
    (
        "overlay/scripts/validate_agenttui_registry.py",
        ".trellis/scripts/validate_agenttui_registry.py",
        False,
    ),
    (
        "overlay/scripts/validate_overlay_drift.py",
        ".trellis/scripts/validate_overlay_drift.py",
        False,
    ),
    ("overlay/scripts/classify_tier.py", ".trellis/scripts/classify_tier.py", False),
    (
        "overlay/scripts/arborist_provenance.py",
        ".trellis/scripts/arborist_provenance.py",
        False,
    ),
    ("overlay/scripts/hgit", "hgit", False),
    (
        "overlay/scripts/trellis_multica_sync.py",
        "scripts/trellis_multica_sync.py",
        False,
    ),
    ("scripts/install-brand-compat.py", "scripts/install-brand-compat.py", False),
    ("scripts/validate_brand_compat.py", "scripts/validate_brand_compat.py", False),
    (
        "overlay/work_context-templates/sendbox/_TEMPLATE-handoff.md",
        ".work_context/sendbox/_TEMPLATE-handoff.md",
        False,
    ),
    (
        "overlay/work_context-templates/sendbox/_TEMPLATE-done.md",
        ".work_context/sendbox/_TEMPLATE-done.md",
        False,
    ),
)

# Files whose writer is an upstream package's own installer. Their drift is reported
# -- the criterion is applied to them without exemption -- but no convergence is
# proposed: this side is not their writer, so a copy pushed here would be overwritten
# by the tool that owns it, and reporting a repair that cannot hold is worse than
# reporting nothing.
WRITER_NOT_OURS = "trellis"

EXIT_IN_SYNC = 0
EXIT_FINDINGS = 1
EXIT_FAIL_CLOSED = 2


class FailClosed(RuntimeError):
    """Provenance or pin unusable: exit 2, never "probably fine"."""


def git_query(tree: Path, *args: str) -> tuple[int, str]:
    """One read-only git query against the pinned tree. Never writes.

    Restricted by convention to query subcommands; the caller passes them. A failure
    to *run* git at all is reported as a non-zero code with empty output, so callers
    treat "git is missing" the same as "the query failed" -- both mean the reading
    was not obtained, which is the only thing that matters here.
    """

    try:
        result = subprocess.run(
            ["git", "-C", str(tree), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return result.returncode, result.stdout


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


def upstream_path_for(relative: str) -> str | None:
    """Map a repo-relative laid path back to its path in the upstream tree."""

    for upstream, repo_relative, is_tree in LAID:
        if relative == repo_relative:
            return upstream
        if is_tree and relative.startswith(repo_relative + "/"):
            return upstream + relative[len(repo_relative) :]
    return None


def repo_path_for(upstream: str) -> str | None:
    """Map an upstream path to where the laying script puts it in a repo."""

    for upstream_path, repo_relative, is_tree in LAID:
        if upstream == upstream_path:
            return repo_relative
        if is_tree and upstream.startswith(upstream_path + "/"):
            return repo_relative + upstream[len(upstream_path) :]
    return None


@dataclass
class Pin:
    """The machine-wide record of which upstream commit is current."""

    tree: Path
    commit: str
    source: Path

    @classmethod
    def load(cls, path: Path) -> "Pin":
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise FailClosed(
                f"no upstream pin at {path}. Without a pin there is nothing to be "
                "behind *of*, and treating that as in-sync would turn an unknown "
                "into a certificate."
            ) from exc
        except OSError as exc:
            raise FailClosed(f"cannot read the pin {path}: {exc}") from exc
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FailClosed(f"pin is not valid JSON: {path}: {exc}") from exc
        if not isinstance(document, dict):
            raise FailClosed(f"pin must be a JSON object: {path}")
        tree_value = document.get("tree_path")
        commit = document.get("commit")
        if not isinstance(tree_value, str) or not tree_value:
            raise FailClosed(f"pin has no usable 'tree_path': {path}")
        if not isinstance(commit, str) or not commit:
            raise FailClosed(f"pin has no usable 'commit': {path}")

        tree = Path(tree_value).expanduser()
        if not tree.is_dir():
            raise FailClosed(
                f"the pinned upstream tree does not exist: {tree} (named by {path}). "
                "The pin points at an existing working tree by design, so a moved or "
                "deleted tree is a broken pin -- not a reason to assume the copies "
                "are current."
            )
        code, _ = git_query(tree, "rev-parse", "--git-dir")
        if code != 0:
            raise FailClosed(
                f"the pinned upstream tree is not a readable git tree: {tree}"
            )
        # Reachability, not mere existence: a commit object can survive in the store
        # after the branch that held it was discarded, and "behind by N" computed
        # against an unreachable commit is a number with no meaning.
        code, _ = git_query(tree, "merge-base", "--is-ancestor", commit, "HEAD")
        if code == 127:
            raise FailClosed(f"cannot run git against the pinned tree: {tree}")
        if code != 0:
            code_exists, _ = git_query(tree, "cat-file", "-e", f"{commit}^{{commit}}")
            detail = (
                "the object exists but is not an ancestor of HEAD"
                if code_exists == 0
                else "the object is not in that tree at all"
            )
            raise FailClosed(
                f"the pinned commit {commit} is not reachable in {tree}: {detail}. "
                "A pin that cannot be verified has stopped being a pin."
            )
        return cls(tree=tree, commit=commit, source=path)

    def head(self) -> str | None:
        code, output = git_query(self.tree, "rev-parse", "HEAD")
        return output.strip() if code == 0 else None

    def blobs_at_commit(self) -> dict[str, str] | None:
        """Every path -> blob id at the pinned commit, or None if it cannot be listed.

        None is distinct from an empty mapping on purpose: "the pin lists nothing" and
        "the pin could not be listed" lead to opposite conclusions, and folding them
        would let an unreadable pin read as agreement.
        """

        code, output = git_query(self.tree, "ls-tree", "-r", self.commit)
        if code != 0:
            return None
        blobs: dict[str, str] = {}
        for line in output.splitlines():
            meta, _, path = line.partition("\t")
            parts = meta.split()
            if len(parts) >= 3 and parts[1] == "blob":
                blobs[path] = parts[2]
        return blobs

    def laid_blobs(self) -> dict[str, tuple[str, int | None]] | None:
        """Every laid artifact at the pinned commit: repo-relative path -> (blob, size).

        Read out of the commit rather than off the working tree: the tree is allowed
        to be ahead of, behind, or on another branch than the pin, and comparing a
        repo against whatever the tree happens to hold right now would make the
        reading depend on somebody else's checkout.

        The size comes along because it is the reading that makes a difference
        *legible*: "the digests differ" and "the local copy is a fifth of the size"
        are the same fact, but only the second one tells a reader at a glance that
        this is a long-abandoned copy rather than a one-line local edit.
        """

        code, output = git_query(self.tree, "ls-tree", "-r", "-l", self.commit)
        if code != 0:
            return None
        blobs: dict[str, tuple[str, int | None]] = {}
        for line in output.splitlines():
            if not line.strip():
                continue
            meta, _, path = line.partition("\t")
            parts = meta.split()
            if len(parts) < 4 or parts[1] != "blob":
                continue
            repo_relative = repo_path_for(path)
            if repo_relative is None:
                continue
            size = int(parts[3]) if parts[3].isdigit() else None
            blobs[repo_relative] = (parts[2], size)
        return blobs

    def blob_ids_of(self, paths: Sequence[Path]) -> dict[Path, str]:
        """Blob ids for local files, computed by git so they compare with `ls-tree`.

        Batched through one `hash-object --stdin-paths` process: a call per file over
        a machine's whole adopted surface turns a checkup into a minute of process
        spawning, and a check nobody waits for is a check nobody runs. `--no-filters`
        because a filter configured in one repo and not another would show up as
        content drift that does not exist.
        """

        if not paths:
            return {}
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.tree),
                    "hash-object",
                    "--no-filters",
                    "--stdin-paths",
                ],
                input="\n".join(str(path) for path in paths) + "\n",
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        if result.returncode != 0:
            return {}
        ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(ids) != len(paths):
            return {}
        return dict(zip(paths, ids))


@dataclass
class AuthorityReport:
    """What the machine's global entry points actually execute, vs the pinned commit.

    This is a **machine-level** reading, reported once, not per repo: there is one
    upstream working tree and the entry points exec files out of it.

    It exists because a pin cannot answer the question people assume it answers. The
    entry points `exec` working-tree files, and a working tree may hold bytes that
    exist in **no commit** -- at which point "which version ran" is not expressible as
    a commit at all. Comparing fingerprints is the only form of the question that
    always has an answer.
    """

    source: Path
    fail_closed: str | None = None
    tree_path: str | None = None
    tree_head: str | None = None
    tree_dirty: bool | None = None
    observed_at: str | None = None
    total: int = 0
    differs_from_pin: list[dict[str, Any]] = field(default_factory=list)
    not_in_pin: list[dict[str, Any]] = field(default_factory=list)
    not_comparable: list[dict[str, Any]] = field(default_factory=list)
    executions: list[dict[str, Any]] = field(default_factory=list)
    executed_not_recorded: list[dict[str, Any]] = field(default_factory=list)
    executed_stale: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_findings(self) -> bool:
        return bool(
            self.fail_closed
            or self.differs_from_pin
            or self.not_in_pin
            or self.not_comparable
            or self.executed_not_recorded
            or self.executed_stale
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "fail_closed": self.fail_closed,
            "tree_path": self.tree_path,
            "tree_head": self.tree_head,
            "tree_dirty": self.tree_dirty,
            "observed_at": self.observed_at,
            "executable_files": self.total,
            "differs_from_pin": self.differs_from_pin,
            "not_in_pin": self.not_in_pin,
            "not_comparable": self.not_comparable,
            "executions_read": len(self.executions),
            "executed_not_recorded": self.executed_not_recorded,
            "executed_stale": self.executed_stale,
        }


def read_executions(path: Path) -> list[dict[str, Any]]:
    """The newest execution record per executed path.

    Only the newest is consumed, which is also why the writer is allowed to compact:
    nothing this validator reads is lost by dropping older lines. Unparsable lines are
    skipped rather than fatal -- the file is appended to concurrently by whichever
    entry point ran, so a torn last line is an ordinary event, not a corruption.
    """

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    newest: dict[str, dict[str, Any]] = {}
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        key = record.get("executed_path")
        if isinstance(key, str) and key:
            newest[key] = record  # later line wins; the file is chronological
    return [newest[key] for key in sorted(newest)]


def check_authority(
    authority_path: Path,
    executions_path: Path,
    bin_dir: Path,
    pin: Pin,
) -> AuthorityReport:
    """Compare what is actually executed against the pinned commit.

    Fail-closed rule, stated precisely because a blanket one would be wrong in both
    directions: an absent authority record is a **fail-closed** condition **only when
    the machine has global entry points**. With no entry points nothing is executed
    through the single copy, and demanding a record would be a gate on a facility that
    is not in use -- a false alarm, and false alarms are how gates get ignored. With
    entry points present, an absent record means something is being executed and
    nobody recorded what: exactly the silence that must not read as agreement.
    """

    report = AuthorityReport(source=authority_path)
    has_entry_points = bin_dir.is_dir() and any(bin_dir.iterdir())

    try:
        raw = authority_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if has_entry_points:
            report.fail_closed = (
                f"no authority-content record at {authority_path}, but global entry "
                f"points exist in {bin_dir}. They exec files out of the upstream "
                "working tree, so without this record nobody can say which bytes the "
                "last call ran -- and the pinned commit cannot answer it either, "
                "because a working tree may hold bytes that are in no commit. Write "
                "it: python3 .../arborist_provenance.py --record-authority "
                "--upstream-tree <tree>"
            )
        else:
            report.fail_closed = None
        return report
    except OSError as exc:
        report.fail_closed = f"cannot read {authority_path}: {exc}"
        return report

    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        report.fail_closed = f"authority-content is not valid JSON: {authority_path}: {exc}"
        return report
    if not isinstance(document, dict):
        report.fail_closed = f"authority-content must be a JSON object: {authority_path}"
        return report

    report.tree_path = document.get("tree_path")
    report.tree_head = document.get("tree_head")
    report.tree_dirty = document.get("tree_dirty")
    report.observed_at = document.get("observed_at")

    files = document.get("files")
    files = [f for f in files if isinstance(f, dict)] if isinstance(files, list) else []
    report.total = len(files)

    # Recompute against the pin here rather than trusting the writer's own verdict:
    # the writer recorded its comparison at write time, and the pin may have been
    # advanced since. Trusting a stored verdict would make this validator a mirror.
    pinned_blobs = pin.blobs_at_commit()

    for entry in files:
        relative = entry.get("tree_relative_path")
        local_blob = entry.get("git_blob")
        if not isinstance(relative, str) or not isinstance(local_blob, str):
            continue
        pinned_blob = pinned_blobs.get(relative) if pinned_blobs is not None else None
        record = {
            "path": relative,
            "executed_path": entry.get("executed_path"),
            "sha256": entry.get("sha256"),
            "bytes": entry.get("bytes"),
            "local_blob": local_blob,
            "blob_at_pin": pinned_blob,
        }
        if pinned_blobs is None:
            record["note"] = (
                "not comparable: the pinned commit's tree could not be listed. An "
                "unobtained reading is not a passing one."
            )
            report.not_comparable.append(record)
        elif pinned_blob is None:
            record["note"] = (
                "the pinned commit does not carry this path at all, so what runs "
                "cannot be described by the pin"
            )
            report.not_in_pin.append(record)
        elif pinned_blob != local_blob:
            record["note"] = (
                "the executed bytes are NOT the bytes the pinned commit names. This "
                "is the normal state of a moving working tree -- which is precisely "
                "why the fingerprint, not the commit, is the version of record"
            )
            report.differs_from_pin.append(record)

    report.executions = read_executions(executions_path)
    fingerprints = {
        entry.get("sha256"): entry
        for entry in files
        if isinstance(entry.get("sha256"), str)
    }
    for execution in report.executions:
        digest = execution.get("sha256")
        executed = execution.get("executed_path")
        if not isinstance(digest, str):
            report.executed_not_recorded.append(
                {
                    "path": executed,
                    "note": (
                        "an execution was recorded with no content hash, so what ran "
                        "is unknown"
                    ),
                }
            )
            continue
        if digest not in fingerprints:
            report.executed_stale.append(
                {
                    "path": executed,
                    "sha256": digest,
                    "at": execution.get("at"),
                    "tree_head": execution.get("tree_head"),
                    "note": (
                        "the bytes that ran match no file in the current authority "
                        "record: the tree changed after that call, or the call ran a "
                        "file the record does not cover. Either way the pinned commit "
                        "does not describe it"
                    ),
                }
            )

    if has_entry_points and not report.executions:
        report.executed_not_recorded.append(
            {
                "path": str(bin_dir),
                "note": (
                    "global entry points exist but no execution has ever been "
                    "recorded. The record is only worth having if its writer is wired "
                    "in: each entry point must call arborist_provenance.py "
                    "--record-execution <authority path> (fail-open, so wiring it "
                    "cannot break the call)"
                ),
            }
        )

    return report


@dataclass
class Provenance:
    """One repo's recorded baseline."""

    path: Path
    schema_version: Any
    commit: str | None
    commit_basis: str | None
    commit_unknown_reason: str | None
    adopted_at: str | None
    adopted_at_kind: str | None
    surface: list[dict[str, Any]]
    declarations: dict[str, dict[str, Any]]

    @classmethod
    def load(cls, repo: Path) -> "Provenance":
        path = repo / PROVENANCE_RELATIVE
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise FailClosed(
                f"no provenance record at {path}. Absent provenance and 'never "
                "diverged' look identical, so this is reported as an environment "
                "failure rather than resolved in the reassuring direction. Write one: "
                "python3 <repo>/.trellis/scripts/arborist_provenance.py --repo <repo> "
                "--backfill"
            ) from exc
        except OSError as exc:
            raise FailClosed(f"cannot read provenance {path}: {exc}") from exc
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FailClosed(f"provenance is not valid JSON: {path}: {exc}") from exc
        if not isinstance(document, dict):
            raise FailClosed(f"provenance must be a JSON object: {path}")

        upstream = document.get("upstream")
        upstream = upstream if isinstance(upstream, dict) else {}
        surface = document.get("surface")
        surface = [e for e in surface if isinstance(e, dict)] if isinstance(surface, list) else []

        declarations: dict[str, dict[str, Any]] = {}
        raw_declarations = document.get("local_modifications")
        if isinstance(raw_declarations, list):
            for entry in raw_declarations:
                if not isinstance(entry, dict):
                    continue
                target = entry.get("path")
                if isinstance(target, str) and target:
                    declarations[target] = entry

        return cls(
            path=path,
            schema_version=document.get("schema_version"),
            commit=upstream.get("commit") if isinstance(upstream.get("commit"), str) else None,
            commit_basis=upstream.get("commit_basis"),
            commit_unknown_reason=upstream.get("commit_unknown_reason"),
            adopted_at=document.get("adopted_at"),
            adopted_at_kind=document.get("adopted_at_kind"),
            surface=surface,
            declarations=declarations,
        )


# A declaration is only a declaration if it says who decided and why. Without those
# two, "we meant to" is indistinguishable from "nobody knows", which is the honour
# system with a JSON file in front of it.
DECLARATION_REQUIRED_FIELDS = ("reason", "decided_by")


def declaration_is_complete(entry: dict[str, Any]) -> list[str]:
    """Missing required fields of one declaration, empty when complete."""

    return [
        name
        for name in DECLARATION_REQUIRED_FIELDS
        if not isinstance(entry.get(name), str) or not entry.get(name, "").strip()
    ]


@dataclass
class RepoReport:
    repo: Path
    provenance: Provenance | None = None
    behind_commits: int | None = None
    behind_files: list[str] = field(default_factory=list)
    baseline_unknown: bool = False
    drifted: list[dict[str, Any]] = field(default_factory=list)
    intentional: list[dict[str, Any]] = field(default_factory=list)
    incomplete_declarations: list[dict[str, Any]] = field(default_factory=list)
    absent: list[dict[str, Any]] = field(default_factory=list)
    stale_content: list[dict[str, Any]] = field(default_factory=list)
    missing_from_repo: list[str] = field(default_factory=list)
    not_ours: list[str] = field(default_factory=list)
    fail_closed: str | None = None

    @property
    def behind(self) -> bool:
        return self.baseline_unknown or bool(self.behind_files) or bool(
            self.behind_commits
        )

    @property
    def has_findings(self) -> bool:
        return bool(
            self.behind
            or self.drifted
            or self.intentional
            or self.incomplete_declarations
            or self.absent
            or self.stale_content
            or self.missing_from_repo
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "repo": str(self.repo),
            "fail_closed": self.fail_closed,
            "baseline": {
                "commit": self.provenance.commit if self.provenance else None,
                "basis": self.provenance.commit_basis if self.provenance else None,
                "kind": self.provenance.adopted_at_kind if self.provenance else None,
                "adopted_at": self.provenance.adopted_at if self.provenance else None,
                "unknown": self.baseline_unknown,
            },
            "behind": {
                "commits": self.behind_commits,
                "files": self.behind_files,
            },
            "drifted": self.drifted,
            "intentional": self.intentional,
            "incomplete_declarations": self.incomplete_declarations,
            "absent": self.absent,
            "stale_content": self.stale_content,
            "missing_from_repo": self.missing_from_repo,
            "upstream_written": self.not_ours,
            "verdict": self.verdict(),
        }

    def verdict(self) -> list[str]:
        """Every state that holds, not the worst one.

        Collapsing to a single worst-case word is what makes a mixed report
        unreadable: "behind" says nothing about whether somebody also edited a copy,
        and those two have different owners.
        """

        states: list[str] = []
        if self.fail_closed:
            states.append("fail-closed")
        if self.behind:
            states.append("behind")
        if self.stale_content:
            states.append("stale-content")
        if self.missing_from_repo:
            states.append("not-laid")
        if self.drifted:
            states.append("drifted")
        if self.intentional:
            states.append("intentional")
        if self.absent:
            states.append("absent-artifacts")
        if self.incomplete_declarations:
            states.append("incomplete-declaration")
        return states or ["in-sync"]


def commits_between(pin: Pin, baseline: str) -> tuple[int | None, list[str]]:
    """How far the overlay moved between the baseline and the pin.

    Counts only commits that touched the overlay: an upstream that advanced by fifty
    commits none of which touched a laid file has not left this repo behind, and
    reporting fifty would train the reader to ignore the number.
    """

    code, _ = git_query(pin.tree, "cat-file", "-e", f"{baseline}^{{commit}}")
    if code != 0:
        return None, []
    code, output = git_query(
        pin.tree,
        "rev-list",
        "--count",
        f"{baseline}..{pin.commit}",
        "--",
        "overlay",
        "scripts",
        "adopt.sh",
    )
    count = int(output.strip()) if code == 0 and output.strip().isdigit() else None
    code, output = git_query(
        pin.tree,
        "diff",
        "--name-only",
        baseline,
        pin.commit,
        "--",
        "overlay",
        "scripts",
        "adopt.sh",
    )
    files = sorted(line for line in output.splitlines() if line.strip()) if code == 0 else []
    return count, files


def check_stale_content(
    repo: Path,
    pin: Pin,
    report: RepoReport,
    laid: dict[str, tuple[str, int | None]] | None,
) -> None:
    """Compare each laid copy against the pinned commit's own content.

    This reading needs **no baseline** and is therefore the one that still works on
    a repo whose provenance is missing, unknown, or backfilled. It is also the
    reading that catches the case the whole exercise started from: a copy that is a
    fraction of the size of what upstream ships. Attribution -- was the difference
    there at laying time, or introduced afterwards -- is what provenance adds on
    top; without it the difference is still a fact.

    Two findings come out of it and they are kept apart:

      stale-content   the file exists in both and the bytes differ
      not-laid        the pin ships it and this repo does not have it at all
    """

    if laid is None:
        return

    present: list[Path] = []
    for relative in sorted(laid):
        path = repo / relative
        if path.is_file():
            present.append(path)
        else:
            report.missing_from_repo.append(relative)

    local = pin.blob_ids_of(present)
    if not local and present:
        # The batch hash failed; say so rather than reporting a clean surface.
        report.stale_content.append(
            {
                "path": "(all)",
                "note": (
                    "could not compute local blob ids, so no content comparison was "
                    "made. Reported as a finding rather than as agreement: an "
                    "unobtained reading is not a passing one."
                ),
            }
        )
        return

    for path in present:
        relative = path.relative_to(repo).as_posix()
        measured = local.get(path)
        pinned_blob, pinned_bytes = laid[relative]
        if measured is None or measured == pinned_blob:
            continue
        local_bytes = path.stat().st_size
        note = "content differs from the pinned upstream"
        if isinstance(pinned_bytes, int) and pinned_bytes > 0:
            note += (
                f"; local {local_bytes} bytes vs pinned {pinned_bytes} "
                f"({local_bytes * 100 // pinned_bytes}% of upstream)"
            )
        report.stale_content.append(
            {
                "path": relative,
                "pinned_blob": pinned_blob,
                "local_blob": measured,
                "local_bytes": local_bytes,
                "pinned_bytes": pinned_bytes,
                "note": note,
            }
        )


def check_repo(
    repo: Path, pin: Pin, laid: dict[str, tuple[str, int | None]] | None
) -> RepoReport:
    report = RepoReport(repo=repo)

    # Content comparison first, and unconditionally: it is the reading that does not
    # depend on a baseline, so a repo with no provenance still gets a useful report
    # alongside its fail-closed verdict. A fail-closed exit that also prints nothing
    # teaches people to pass `--repo` to something else instead.
    check_stale_content(repo, pin, report, laid)

    try:
        provenance = Provenance.load(repo)
    except FailClosed as exc:
        report.fail_closed = str(exc)
        return report
    report.provenance = provenance

    # --- behind: baseline commit vs pinned commit.
    if provenance.commit is None:
        report.baseline_unknown = True
    elif provenance.commit != pin.commit:
        report.behind_commits, report.behind_files = commits_between(
            pin, provenance.commit
        )
        if report.behind_commits is None and not report.behind_files:
            # The baseline commit is not in the pinned tree: recorded against a
            # different upstream, or the commit was discarded. Not silently in-sync.
            report.baseline_unknown = True

    # --- drifted / intentional: measured digests vs recorded digests.
    for entry in provenance.surface:
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative:
            continue
        recorded = entry.get("sha256")
        writer = entry.get("writer")
        measured = sha256_file(repo / relative)

        if measured is None:
            if recorded is not None:
                report.absent.append(
                    {
                        "path": relative,
                        "note": (
                            "recorded at laying time, absent now. An artifact the "
                            "upstream ships and this repo does not have is drift, "
                            "and the loudest kind."
                        ),
                    }
                )
            continue
        if recorded is None or measured == recorded:
            continue

        declaration = provenance.declarations.get(relative)
        if declaration is None:
            finding = {
                "path": relative,
                "recorded_sha256": recorded,
                "measured_sha256": measured,
                "writer": writer,
                "note": (
                    "undeclared deviation: somebody edited this copy. Find out who "
                    "and why before overwriting it -- the edit may be the only place "
                    "a local necessity is recorded."
                ),
            }
            if writer == WRITER_NOT_OURS:
                finding["note"] += (
                    " Its writer is an upstream package's own installer, so no "
                    "convergence from this side is proposed: a copy pushed here "
                    "would be overwritten by the tool that owns it."
                )
                report.not_ours.append(relative)
            report.drifted.append(finding)
            continue

        missing = declaration_is_complete(declaration)
        record = {
            "path": relative,
            "recorded_sha256": recorded,
            "measured_sha256": measured,
            "reason": declaration.get("reason"),
            "decided_by": declaration.get("decided_by"),
            "at": declaration.get("at"),
        }
        if missing:
            record["missing_fields"] = missing
            record["note"] = (
                "declared, but incompletely: a declaration without "
                + " and ".join(missing)
                + " does not distinguish 'we meant to' from 'nobody knows'. It is "
                "listed here rather than accepted."
            )
            report.incomplete_declarations.append(record)
        else:
            record["note"] = (
                "declared deviation, listed every time on purpose: declared is not "
                "invisible. Suppressing it would reinstate the honour system one "
                "level down."
            )
            report.intentional.append(record)

    return report


def load_repos_from_index(index_path: Path) -> list[Path]:
    try:
        raw = index_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FailClosed(
            f"global index not found: {index_path}. With no index there is no way to "
            "tell 'nothing adopted' from 'the index was wiped', so the sweep fails "
            "closed rather than reporting a clean machine."
        ) from exc
    except OSError as exc:
        raise FailClosed(f"cannot read global index {index_path}: {exc}") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FailClosed(f"global index is not valid JSON: {index_path}: {exc}")
    projects = document.get("projects") if isinstance(document, dict) else None
    if not isinstance(projects, list):
        raise FailClosed(f"global index has no 'projects' list: {index_path}")
    return [
        Path(entry["path"]).expanduser()
        for entry in projects
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    ]


def reproduce_commands(repo: Path, pin: Pin) -> list[str]:
    """The commands that reproduce this reading, printed with the report.

    A report whose numbers cannot be re-derived by its reader is an assertion, and
    an assertion about somebody else's repo is exactly the thing this exercise set
    out to replace.
    """

    return [
        f"python3 {Path(__file__).name} --repo {repo}",
        f"python3 {Path(__file__).name} --all   # the whole machine's matrix",
        f"git -C {pin.tree} log --oneline <recorded-commit>..{pin.commit} -- overlay",
        f"cat {repo / PROVENANCE_RELATIVE}",
    ]


def render_authority(report: AuthorityReport, pin: Pin, *, verbose: bool) -> str:
    """The machine-level block: what actually runs, versus what the pin names.

    Printed first, and printed even when clean, because the whole point of this
    section is that the reader stops assuming the pin answers it. A section that
    appears only on failure teaches nobody what the two fields mean.
    """

    lines = ["== machine authority (what the global entry points actually execute)"]
    if report.fail_closed:
        lines.append(f"   fail-closed: {report.fail_closed}")
        return "\n".join(lines)
    if report.total == 0 and not report.executions:
        lines.append(
            "   not in use: no authority record and no global entry points, so "
            "nothing is executed from a single copy. Nothing to compare -- and "
            "demanding a record here would be a gate on a facility not in use."
        )
        return "\n".join(lines)

    lines.append(
        f"   record: {report.source} observed_at={report.observed_at}"
    )
    lines.append(
        f"   tree={report.tree_path} head={report.tree_head} "
        f"dirty={report.tree_dirty}; pinned_commit={pin.commit}"
    )
    lines.append(
        f"   {report.total} executable file(s); "
        f"{len(report.differs_from_pin)} differ from the pin, "
        f"{len(report.not_in_pin)} absent from the pin, "
        f"{len(report.not_comparable)} not comparable; "
        f"{len(report.executions)} recorded execution(s)"
    )

    def listing(label: str, findings: list[dict[str, Any]]) -> None:
        if not findings:
            return
        lines.append(f"   {label}: {len(findings)}")
        shown = findings if verbose else findings[:10]
        for finding in shown:
            lines.append(f"     - {finding.get('path')}: {finding['note']}")
        if len(shown) < len(findings):
            lines.append(f"     ... {len(findings) - len(shown)} more (--verbose)")

    listing("authority-differs-from-pin", report.differs_from_pin)
    listing("authority-not-in-pin", report.not_in_pin)
    listing("authority-not-comparable", report.not_comparable)
    listing("executed-not-in-authority", report.executed_stale)
    listing("execution-unrecorded", report.executed_not_recorded)

    if report.differs_from_pin or report.not_in_pin:
        lines.append(
            "   reading: the pin is a PROVENANCE document (which version the decision "
            "was made against), not an enforced version. It cannot say which bytes the "
            "last call ran, and where the tree is dirty no commit can. The "
            "fingerprints above are the version of record."
        )
    return "\n".join(lines)


def render(report: RepoReport, pin: Pin, *, verbose: bool) -> str:
    lines = [f"== {report.repo}", f"   verdict: {', '.join(report.verdict())}"]

    def listing(label: str, findings: Sequence[dict[str, Any]]) -> None:
        if not findings:
            return
        lines.append(f"   {label}: {len(findings)}")
        shown = list(findings) if verbose else list(findings)[:10]
        for finding in shown:
            lines.append(f"     - {finding['path']}: {finding['note']}")
        if len(shown) < len(findings):
            lines.append(f"     ... {len(findings) - len(shown)} more (--verbose)")

    # Printed before the fail-closed verdict on purpose: this reading needs no
    # baseline, so it is exactly what a repo missing provenance still needs told.
    if report.stale_content:
        lines.append(
            f"   stale-content: {len(report.stale_content)} laid file(s) differ from "
            f"the pinned upstream {pin.commit[:12]}"
        )
        # Ordered by how much content is missing locally, largest first: the copies
        # that are a fraction of what upstream ships are the ones worth reading
        # about, and alphabetical order buries them among one-line differences.
        ordered = sorted(
            report.stale_content,
            key=lambda f: -((f.get("pinned_bytes") or 0) - (f.get("local_bytes") or 0)),
        )
        shown = ordered if verbose else ordered[:10]
        for finding in shown:
            lines.append(f"     - {finding['path']}: {finding['note']}")
        if len(shown) < len(report.stale_content):
            lines.append(
                f"     ... {len(report.stale_content) - len(shown)} more (--verbose)"
            )
    if report.missing_from_repo:
        lines.append(
            f"   not-laid: {len(report.missing_from_repo)} artifact(s) the pin ships "
            "are absent from this repo"
        )
        shown = (
            report.missing_from_repo if verbose else report.missing_from_repo[:10]
        )
        for name in shown:
            lines.append(f"     - {name}")
        if len(shown) < len(report.missing_from_repo):
            lines.append(
                f"     ... {len(report.missing_from_repo) - len(shown)} more (--verbose)"
            )

    if report.fail_closed:
        lines.append(f"   fail-closed: {report.fail_closed}")
        return "\n".join(lines)

    provenance = report.provenance
    assert provenance is not None
    lines.append(
        f"   baseline: commit={provenance.commit} basis={provenance.commit_basis} "
        f"kind={provenance.adopted_at_kind} at={provenance.adopted_at}"
    )
    lines.append(f"   pin: commit={pin.commit} tree={pin.tree}")

    if report.baseline_unknown:
        lines.append(
            "   behind: baseline unknown -- the recorded commit is absent or not in "
            "the pinned tree, so the distance cannot be counted. Reported as behind, "
            "never as in-sync."
        )
        if provenance.commit_unknown_reason:
            lines.append(f"     recorded reason: {provenance.commit_unknown_reason}")
    elif report.behind_files or report.behind_commits:
        lines.append(
            f"   behind: {report.behind_commits} upstream commit(s) touching the "
            f"overlay, {len(report.behind_files)} file(s) changed since the baseline"
        )
        shown = report.behind_files if verbose else report.behind_files[:10]
        for name in shown:
            lines.append(f"     + {name}")
        if len(shown) < len(report.behind_files):
            lines.append(
                f"     ... {len(report.behind_files) - len(shown)} more (--verbose)"
            )

    listing("drifted", report.drifted)
    listing("intentional", report.intentional)
    listing("incomplete-declaration", report.incomplete_declarations)
    listing("absent", report.absent)

    if report.not_ours:
        lines.append(
            f"   note: {len(report.not_ours)} of the drifted file(s) are written by "
            "an upstream package's own installer; their drift is reported, no "
            "convergence from this side is proposed."
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Report how far a repo's overlay copy has fallen behind the upstream "
            "pin, and whether its copies were edited. Read-only: it reports, it "
            "never converges, and it does not block anybody from starting work."
        ),
        epilog=(
            "findings (never merged -- different causes, different owners):\n"
            "  behind                  upstream moved; the recorded baseline is older\n"
            "  drifted                 a copy's digest changed and nobody declared it\n"
            "  intentional             declared with reason + decided_by; listed every\n"
            "                          time, because declared is not invisible\n"
            "  absent-artifacts        recorded at laying time, missing now\n"
            "  incomplete-declaration  declared without reason and/or decided_by\n"
            "\n"
            "machine-level findings (reported once, not per repo):\n"
            "  authority-differs-from-pin  the bytes the global entry points execute are\n"
            "                              not the bytes the pinned commit names. Normal\n"
            "                              for a moving working tree -- which is exactly\n"
            "                              why the FINGERPRINT, not the commit, is the\n"
            "                              version of record. A pin answers 'what was the\n"
            "                              decision made against', never 'what just ran'.\n"
            "  authority-not-in-pin        the pin does not carry that path at all, so\n"
            "                              what runs cannot be described by a commit\n"
            "  executed-not-in-authority   the bytes a recorded call ran match no file in\n"
            "                              the current authority record\n"
            "  execution-unrecorded        entry points exist but no call was ever\n"
            "                              recorded -- the record's writer is not wired in\n"
            "\n"
            "exit codes:\n"
            "  0  in-sync\n"
            "  1  findings to read\n"
            "  2  provenance missing/unparsable, or the pin cannot be verified, or\n"
            "     entry points exist with no authority record\n"
            "     (fail closed: 'no baseline' must never read as 'never diverged')\n"
        ),
    )
    parser.add_argument(
        "--repo", type=Path, action="append", dest="repos", metavar="PATH"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="sweep every repo named by the global index and print the machine matrix",
    )
    parser.add_argument("--global-index", type=Path, default=DEFAULT_GLOBAL_INDEX)
    parser.add_argument(
        "--pin",
        type=Path,
        default=DEFAULT_PIN,
        help=f"the machine-wide upstream pin (default: {DEFAULT_PIN})",
    )
    parser.add_argument(
        "--authority",
        type=Path,
        default=DEFAULT_AUTHORITY,
        help=(
            "content fingerprints of the files the global entry points execute "
            f"(default: {DEFAULT_AUTHORITY})"
        ),
    )
    parser.add_argument(
        "--executions",
        type=Path,
        default=DEFAULT_EXECUTIONS,
        help=f"append-only execution record (default: {DEFAULT_EXECUTIONS})",
    )
    parser.add_argument(
        "--bin-dir",
        type=Path,
        default=DEFAULT_BIN,
        help=(
            "where the global entry points live; their presence is what makes an "
            f"absent authority record fail closed (default: {DEFAULT_BIN})"
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--verbose", action="store_true", help="list every finding, not the first ten"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    repos: list[Path] = []
    if args.all:
        try:
            repos.extend(load_repos_from_index(args.global_index.expanduser()))
        except FailClosed as exc:
            print(f"fail-closed: {exc}")
            return EXIT_FAIL_CLOSED
    repos.extend((path.expanduser() for path in (args.repos or [])))
    if not repos:
        print("nothing to check: pass --repo PATH or --all")
        return EXIT_FAIL_CLOSED

    try:
        pin = Pin.load(args.pin.expanduser())
    except FailClosed as exc:
        print(f"fail-closed: {exc}")
        return EXIT_FAIL_CLOSED

    head = pin.head()
    laid = pin.laid_blobs()
    authority = check_authority(
        args.authority.expanduser(),
        args.executions.expanduser(),
        args.bin_dir.expanduser(),
        pin,
    )
    seen: set[str] = set()
    reports: list[RepoReport] = []
    for repo in repos:
        if str(repo) in seen:
            continue
        seen.add(str(repo))
        if not repo.is_dir():
            report = RepoReport(repo=repo)
            report.fail_closed = (
                f"repo path does not exist: {repo}. Reported per repo and the sweep "
                "continues: one dead entry must not shadow the whole machine."
            )
            reports.append(report)
            continue
        reports.append(check_repo(repo, pin, laid))

    fail_closed = [r for r in reports if r.fail_closed]
    with_findings = [r for r in reports if not r.fail_closed and r.has_findings]

    if args.json:
        print(
            json.dumps(
                {
                    "pin": {
                        "commit": pin.commit,
                        "tree": str(pin.tree),
                        "source": str(pin.source),
                        "tree_head": head,
                        "pin_is_tree_head": head == pin.commit,
                    },
                    "authority": authority.to_json(),
                    "repos": [r.to_json() for r in reports],
                    "summary": {
                        "checked": len(reports),
                        "in_sync": len(reports) - len(fail_closed) - len(with_findings),
                        "with_findings": len(with_findings),
                        "fail_closed": len(fail_closed),
                        "authority_findings": authority.has_findings,
                    },
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        if head and head != pin.commit:
            print(
                f"note: the pinned tree's HEAD ({head[:12]}) is not the pinned commit "
                f"({pin.commit[:12]}). The pin, not HEAD, is what repos are compared "
                "against -- advancing the pin is a separate, deliberate act.\n"
            )
        print(render_authority(authority, pin, verbose=args.verbose))
        for report in reports:
            print(render(report, pin, verbose=args.verbose))
        print(
            f"\nchecked {len(reports)} repo(s): "
            f"{len(reports) - len(fail_closed) - len(with_findings)} in-sync, "
            f"{len(with_findings)} with findings, {len(fail_closed)} fail-closed"
        )
        print("reproduce this reading:")
        for command in reproduce_commands(reports[0].repo if reports else Path("."), pin):
            print(f"  {command}")
        print(
            "this check does not block starting work (a repo that is behind must "
            "still be able to do the work of catching up)."
        )

    if fail_closed or authority.fail_closed:
        return EXIT_FAIL_CLOSED
    if with_findings or authority.has_findings:
        return EXIT_FINDINGS
    return EXIT_IN_SYNC


if __name__ == "__main__":
    raise SystemExit(main())
