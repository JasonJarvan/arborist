#!/usr/bin/env python3
"""Record where one repo's overlay stopped, and what the machine actually executes.

TWO RECORDS, TWO QUESTIONS -- KEPT IN SEPARATE FIELDS ON PURPOSE
----------------------------------------------------------------
A pin answers **"which version was the decision made against"**. It cannot answer
**"which version did that call just run"**, and the difference is not theoretical:

* The global entry points `exec` a **file in the upstream working tree**, not a
  commit. A working tree is allowed to be dirty, so the bytes that run may
  correspond to **no commit at all** -- at which point "which version ran" is not
  expressible as a commit, and a field that only holds a commit cannot say it.
* Even with a clean tree, the tree moves forward. The pin was observed to disagree
  with the executed file **the same evening it was written**. A pin is a provenance
  document; treating it as an enforced version is how one field ends up carrying two
  meanings, only one of which is true.

So this script writes three things and never conflates them:

1. **`pinned_commit`** (in `provenance/upstream.json`, written by the gardener) --
   the decision baseline. Referenced here, never overwritten here.
2. **authority content fingerprints** (`provenance/authority-content.json`) -- the
   sha256 of each file the global entry points actually execute, plus whether those
   bytes exist as a blob in the pinned commit at all. A commit is recorded alongside
   as *incidental*; the fingerprint is the load-bearing value.
3. **an execution record** (`provenance/executions.jsonl`) -- one line per
   invocation: when, which file, its content hash, and the tree's HEAD if readable.

The reason record 3 exists at all is that records nobody reads are how this class of
problem regenerates. Its **named consumer is `validate_overlay_drift.py`**, which
compares the last executed fingerprint against the pinned commit. Written but
unconsumed would be the honour system with more files.

Record 3 is **self-bounding** (see `EXECUTION_RECORD_KEEP_PER_PATH`): it must not
become a third file nobody sweeps. Recording is also **fail-open by construction** --
the recorder never makes the capability call it observes fail, because an observer
that can break what it observes is worse than no observer.

WHY THIS FILE EXISTS
--------------------
The overlay is laid into each adopting repo by copy. Copies of content that is
identical in every repo *will* diverge -- not as a risk, as an observed fact, and
more than once: one round of catching up was completed and the gap reopened.
Without a mechanical reading of "how far behind am I", keeping the copies in step
is an honour system, and an honour system produces exactly that pattern.

This writer produces the reading's *baseline*; `validate_overlay_drift.py` consumes
it. Splitting the two is deliberate: the baseline must be written at the one moment
it is known for certain (immediately after laying), while the comparison happens
whenever somebody asks.

THE RECORD
----------
`<repo>/.arborist/overlay-provenance.json`:

    schema_version      integer; readers skip unknown versions, never guess
    upstream            { repo_id, commit, tree_path, dirty, commit_basis }
    adopted_at          ISO 8601, and `adopted_at_kind`: "adopt" or "backfill"
    adopt_sh_sha256     which laying script produced this state
    surface             [ { path, sha256, tier, writer } ] for the shared surface
    local_modifications [ { path, reason, decided_by, at } ] -- see below
    history             previous upstream records, oldest first

`local_modifications` is the answer to a failure mode that is worse than the one
this file fixes: if a repo that genuinely had to change one overlay file can only
ever show a red light, the report gets ignored wholesale, and an ignored report is
weaker than none. So a deviation may be **declared** -- but only with a `reason` and
a `decided_by`, and the validator then reports it as `intentional` rather than
passing over it. Declared is not invisible: it stays in the report, auditable. The
writer of that list is the repo's own gardener; this script preserves it and never
invents an entry.

WHAT IS NOT RECONSTRUCTED
-------------------------
`--backfill`, run against a repo adopted before this file existed, records
`commit: null` with `commit_basis: "unknown-backfill"`. The true upstream commit for
those copies is not recoverable, and a plausible-looking guess would be worse than
an admitted gap: the whole point of the baseline is that a later comparison can be
trusted. The first validator run after a backfill therefore reports **behind, with
an unknown baseline**. That is the correct output, not a defect; a real baseline
exists only after the first convergence.

Failing to write this file never fails the laying that called it. It is a new
capability, not a precondition of a flow that already worked -- and a repo left
unadopted because a bookkeeping file could not be written would be a strictly worse
outcome than a repo adopted without one. The *gate* that provenance must exist
belongs at the end of adopt (which reports it loudly), not in the middle.

Read-write by design, but each mode writes exactly one file: the per-repo record into
the repo it was pointed at, and the two global records under `$ARBORIST_HOME`. No
`--fix`, no convergence, nothing about other repos.

Exit codes: 0 written (or `--check` satisfied); 1 `--check` found no usable record;
2 usage / environment (fail closed). `--record-execution` is the exception: it exits
0 even when it could not write, by design -- see `record_execution`.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

SCHEMA_VERSION = 1

PROVENANCE_RELATIVE = ".arborist/overlay-provenance.json"

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


# The three global records. `upstream.json` is the gardener's to write; this script
# only reads it, so the decision baseline keeps a single writer.
PIN_RELATIVE = Path("provenance") / "upstream.json"
AUTHORITY_RELATIVE = Path("provenance") / "authority-content.json"
EXECUTIONS_RELATIVE = Path("provenance") / "executions.jsonl"

# Where the global entry points live, and therefore what "actually executed" means.
BIN_RELATIVE = Path("bin")

# The upstream files a global entry point may execute. Matched inside the upstream
# tree, so this is a shape, not a machine's list.
AUTHORITY_GLOBS = (
    "overlay/scripts/*.py",
    "overlay/scripts/hgit",
    "scripts/*.py",
)

# How many execution records to keep per executed path. The file is append-only in
# normal operation and compacts itself past this, for one reason: the previous
# paragraph of this design would otherwise have produced a third machine-level file
# with no sweeper, which is the failure mode it was written to avoid. The validator
# reads only the newest record per path, so compaction loses nothing it consumes --
# what it costs is deep history, and that cost is stated rather than hidden.
EXECUTION_RECORD_KEEP_PER_PATH = 20

KIND_ADOPT = "adopt"
KIND_BACKFILL = "backfill"

KIND_ADOPT = "adopt"
KIND_BACKFILL = "backfill"

COMMIT_BASIS_UPSTREAM_HEAD = "upstream-head"
COMMIT_BASIS_UNKNOWN_BACKFILL = "unknown-backfill"
COMMIT_BASIS_UNRESOLVABLE = "unresolvable"

# How many superseded upstream records to keep. Bounded because the file is read by
# a validator on every checkup: the useful signal is "it moved, and when", which the
# most recent few carry; an unbounded list turns a baseline into a logfile.
HISTORY_LIMIT = 20

# Recorded digests cover the shared surface only -- the tiers whose correct content
# is the same in every repo. Digesting per-repo artifacts would guarantee a
# permanent "modified" reading for files that are *supposed* to differ.
RECORDED_TIERS = ("G", "S")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_classifier() -> Any:
    """Load the tiering classifier as a module, for its surface manifest.

    The manifest is not restated here on purpose: two lists of "what the overlay
    lays" drift apart, and the one that drifts is always the one nobody runs.
    """

    module_path = Path(__file__).resolve().parent / "classify_tier.py"
    if not module_path.is_file():
        return None
    name = "_arborist_classifier_for_provenance"
    try:
        spec = importlib.util.spec_from_file_location(name, module_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None
    finally:
        sys.modules.pop(name, None)


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


def git_readonly(tree: Path, *args: str) -> str | None:
    """One read-only git query, or None. Never raises, never writes."""

    try:
        result = subprocess.run(
            ["git", "-C", str(tree), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def describe_upstream(tree: Path | None, *, kind: str) -> dict[str, Any]:
    """The upstream half of the record, with an explicit basis for the commit.

    Three outcomes, all of them named rather than collapsed into one nullable field:
    a real HEAD, an admitted backfill gap, and an upstream tree that could not be
    read at all. A reader must be able to tell those apart -- "no commit" that means
    "not knowable" and "no commit" that means "your upstream is not a git tree"
    lead to different repairs.
    """

    record: dict[str, Any] = {
        "repo_id": None,
        "commit": None,
        "tree_path": str(tree) if tree else None,
        "dirty": None,
        "commit_basis": COMMIT_BASIS_UNRESOLVABLE,
    }

    if kind == KIND_BACKFILL:
        record["commit_basis"] = COMMIT_BASIS_UNKNOWN_BACKFILL
        record["commit_unknown_reason"] = (
            "backfilled: this repo was laid before provenance was recorded, and the "
            "upstream commit its copies came from is not recoverable. A guess would "
            "defeat the purpose of having a baseline, so the gap is admitted. The "
            "first drift report will read 'behind, baseline unknown' -- correct "
            "output, not a defect."
        )

    if tree is None:
        return record

    if kind != KIND_BACKFILL:
        commit = git_readonly(tree, "rev-parse", "HEAD")
        if commit:
            record["commit"] = commit
            record["commit_basis"] = COMMIT_BASIS_UPSTREAM_HEAD
        else:
            record["commit_unknown_reason"] = (
                f"could not read HEAD of the upstream tree at {tree}: it is not a "
                "readable git tree. Recorded as unresolvable rather than as "
                "in-sync -- a baseline nobody can verify must not read as a "
                "verified one."
            )

    status = git_readonly(tree, "status", "--porcelain", "--", "overlay")
    if status is not None:
        record["dirty"] = bool(status)
    elif record["commit"]:
        # HEAD read but status did not: report the uncertainty rather than "clean".
        record["dirty"] = None

    origin = git_readonly(tree, "remote", "get-url", "origin")
    record["repo_id"] = origin or tree.name

    return record


def collect_surface(repo: Path, classifier: Any) -> list[dict[str, Any]]:
    """Digest every shared-tier file the overlay laid into this repo.

    Absent files are recorded with `sha256: null` rather than omitted. An artifact
    the upstream ships and this repo does not have is the strongest drift signal
    there is, and a record built only from what exists can never express it.
    """

    if classifier is None:
        return []

    entries: dict[str, dict[str, Any]] = {}
    for rule in classifier.SURFACE:
        if rule.tier not in RECORDED_TIERS or not rule.walk:
            continue
        if "*" in rule.pattern:
            for path in sorted(repo.glob(classifier.glob_pattern_for(rule.pattern))):
                if not path.is_file():
                    continue
                relative = path.relative_to(repo).as_posix()
                if classifier.is_noise(relative):
                    continue
                if classifier.match_rule(relative) is not rule:
                    continue  # a more specific rule owns it
                entries[relative] = {
                    "path": relative,
                    "sha256": sha256_file(path),
                    "tier": rule.tier,
                    "writer": rule.writer,
                }
        else:
            path = repo / rule.pattern
            if path.is_dir():
                continue
            entries[rule.pattern] = {
                "path": rule.pattern,
                "sha256": sha256_file(path),
                "tier": rule.tier,
                "writer": rule.writer,
            }
    return [entries[key] for key in sorted(entries)]


def read_existing(path: Path) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def carried_forward(existing: dict[str, Any] | None) -> tuple[list[Any], list[Any]]:
    """The two fields a rewrite must never destroy: declarations and history.

    A rewrite that dropped `local_modifications` would silently turn every declared
    deviation back into an unexplained one, which is the honour system with extra
    steps.
    """

    if not existing:
        return [], []
    declarations = existing.get("local_modifications")
    history = existing.get("history")
    return (
        list(declarations) if isinstance(declarations, list) else [],
        list(history) if isinstance(history, list) else [],
    )


def build_record(
    repo: Path,
    *,
    upstream_tree: Path | None,
    kind: str,
    adopt_script: Path | None,
    existing: dict[str, Any] | None,
    classifier: Any,
) -> dict[str, Any]:
    declarations, history = carried_forward(existing)

    previous_upstream = (existing or {}).get("upstream")
    upstream = describe_upstream(upstream_tree, kind=kind)
    if (
        isinstance(previous_upstream, dict)
        and previous_upstream.get("commit") != upstream.get("commit")
    ):
        history.append(
            {
                "upstream": previous_upstream,
                "superseded_at": now_iso(),
                "adopted_at": (existing or {}).get("adopted_at"),
            }
        )
    history = history[-HISTORY_LIMIT:]

    return {
        "schema_version": SCHEMA_VERSION,
        "upstream": upstream,
        "adopted_at": now_iso(),
        "adopted_at_kind": kind,
        "adopt_sh_sha256": sha256_file(adopt_script) if adopt_script else None,
        "surface": collect_surface(repo, classifier),
        "local_modifications": declarations,
        "history": history,
    }


def write_atomic(path: Path, document: dict[str, Any]) -> None:
    """Replace the record in one step, so a reader never sees a half-written file.

    Not a secret, so not 0600: it is machine-local bookkeeping that a human is
    expected to read. Written via a temporary sibling and `fsync` before rename,
    because the validator that reads it may run seconds later and a truncated
    baseline fails closed for the wrong reason.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    payload = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def read_pin(home: Path) -> dict[str, Any]:
    """The decision baseline, read-only. This script is not its writer."""

    try:
        document = json.loads((home / PIN_RELATIVE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return document if isinstance(document, dict) else {}


def record_authority_content(home: Path, tree: Path) -> dict[str, Any]:
    """Fingerprint every file a global entry point can execute, out of the work tree.

    Read from the **working tree**, not from a commit, because that is what gets
    executed. The commit is recorded next to each fingerprint as a cross-reference and
    is explicitly allowed to be absent: bytes that exist in no commit are a legitimate
    state of a working tree, and the whole point of fingerprinting is to be able to
    say so instead of naming a commit that does not describe them.
    """

    head = git_readonly(tree, "rev-parse", "HEAD")
    dirty_out = git_readonly(tree, "status", "--porcelain")
    pin = read_pin(home)
    pinned_commit = pin.get("commit") if isinstance(pin.get("commit"), str) else None

    # Blob ids at the pinned commit, so "do the executed bytes exist in the pin" is
    # answerable per file rather than as one global yes/no.
    pinned_blobs: dict[str, str] = {}
    if pinned_commit:
        for line in (git_readonly(tree, "ls-tree", "-r", pinned_commit) or "").splitlines():
            meta, _, path = line.partition("\t")
            parts = meta.split()
            if len(parts) >= 3 and parts[1] == "blob":
                pinned_blobs[path] = parts[2]

    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern in AUTHORITY_GLOBS:
        for path in sorted(tree.glob(pattern)):
            if not path.is_file():
                continue
            relative = path.relative_to(tree).as_posix()
            if relative in seen:
                continue
            seen.add(relative)
            local_blob = git_hash_object(tree, path)
            pinned_blob = pinned_blobs.get(relative)
            files.append(
                {
                    "tree_relative_path": relative,
                    "executed_path": str(path),
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                    "git_blob": local_blob,
                    "blob_at_pinned_commit": pinned_blob,
                    # Tri-state on purpose. `false` = the pin names different bytes;
                    # `null` = the pin could not be resolved at all. Collapsing the
                    # two would let an unreadable pin read as agreement.
                    "matches_pinned_commit": (
                        None
                        if (pinned_blob is None or local_blob is None)
                        else local_blob == pinned_blob
                    ),
                }
            )

    document = {
        "schema_version": SCHEMA_VERSION,
        "observed_at": now_iso(),
        "tree_path": str(tree),
        "tree_head": head,
        "tree_dirty": bool(dirty_out) if dirty_out is not None else None,
        # Copied for cross-reference only. The authority of this field stays in
        # upstream.json; duplicating it as a *value* here would create a second
        # writer of the decision baseline.
        "pinned_commit_seen": pinned_commit,
        "files": files,
        "note": (
            "Fingerprints are of the WORKING TREE files that the global entry points "
            "exec. The commit fields are cross-reference, not the reading: a working "
            "tree may hold bytes that exist in no commit, in which case 'which "
            "version ran' is not expressible as a commit and only the fingerprint "
            "can answer it. Consumer: validate_overlay_drift.py."
        ),
    }
    write_atomic(home / AUTHORITY_RELATIVE, document)
    return document


def git_hash_object(tree: Path, path: Path) -> str | None:
    """The git blob id of a local file, so it compares with `ls-tree` output."""

    try:
        result = subprocess.run(
            ["git", "-C", str(tree), "hash-object", "--no-filters", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def record_execution(home: Path, executed: Path, *, tree: Path | None) -> bool:
    """Append one line saying what was just executed. Never raises, never blocks.

    **Fail-open by construction.** This is called on the hot path of a capability
    invocation, so every failure mode -- unwritable directory, full disk, a race with
    another writer -- returns False and lets the call proceed. An observer that can
    break what it observes is worse than no observer, and the thing being observed
    here is the machine's only copy of several capabilities.

    It does not change the observed sequence either: it writes one line to a file
    nothing else reads at that moment, runs no command against the multiplexer, and
    touches neither the registry nor any session. What it costs is one small write
    per invocation.
    """

    try:
        record = {
            "at": now_iso(),
            "executed_path": str(executed),
            "sha256": sha256_file(executed),
            "bytes": executed.stat().st_size if executed.is_file() else None,
            "tree_path": str(tree) if tree else None,
            "tree_head": git_readonly(tree, "rev-parse", "HEAD") if tree else None,
        }
        path = home / EXECUTIONS_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        compact_executions(path)
        return True
    except Exception:
        return False


def compact_executions(path: Path) -> None:
    """Keep the newest N records per executed path, so the file cannot grow forever.

    Runs inline rather than as a separate sweeper, because a sweeper that has to be
    remembered is the same unswept-file problem one level up. Any failure here is
    swallowed: a compaction that broke the capability call would be a much worse
    outcome than an oversized log.
    """

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= EXECUTION_RECORD_KEEP_PER_PATH * 4:
            return
        kept: dict[str, list[str]] = {}
        for line in lines:
            try:
                key = str(json.loads(line).get("executed_path"))
            except json.JSONDecodeError:
                continue
            kept.setdefault(key, []).append(line)
        payload = "".join(
            line + "\n"
            for key in sorted(kept)
            for line in kept[key][-EXECUTION_RECORD_KEEP_PER_PATH:]
        )
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Record which upstream commit one repo's overlay stopped at, the digests "
            "of the shared surface, and -- separately -- the content fingerprints of "
            "the files the machine's global entry points actually execute. A pin "
            "answers 'which version was the decision made against'; it cannot answer "
            "'which version just ran', so the two are different fields."
        ),
        epilog=(
            "per-repo modes (need --repo):\n"
            "  (default)    record the upstream HEAD as the baseline (use at adopt time)\n"
            "  --backfill   record today's digests with an ADMITTED unknown baseline,\n"
            "               for a repo laid before provenance existed. The next drift\n"
            "               report will read 'behind, baseline unknown' -- correct.\n"
            "  --check      report whether a usable record exists; write nothing\n"
            "  --print-path print the record's path and exit\n"
            "\n"
            "machine-level modes (need --upstream-tree, not --repo):\n"
            "  --record-authority        fingerprint every file a global entry point can\n"
            "                            execute, READ FROM THE WORKING TREE (that is what\n"
            "                            runs). Records per file whether those bytes exist\n"
            "                            as a blob in the pinned commit -- tri-state, so an\n"
            "                            unreadable pin cannot read as agreement.\n"
            "  --record-execution PATH   append one line: when, which file, its hash, the\n"
            "                            tree HEAD if readable. For a global entry point to\n"
            "                            call. FAIL-OPEN: exits 0 even if it could not\n"
            "                            write, because an observer must never break the\n"
            "                            call it observes. Self-bounding file.\n"
            "\n"
            "the named consumer of both machine-level records is\n"
            "validate_overlay_drift.py -- a record with no reader is the honour\n"
            "system with more files.\n"
            "\n"
            "preserved across rewrites: local_modifications (declared deviations,\n"
            "each with reason + decided_by) and history. Neither is ever invented\n"
            "here; the repo's own gardener writes declarations.\n"
            "\n"
            "exit codes:\n"
            "  0  written, or --check satisfied, or --record-execution (always)\n"
            "  1  --check found no usable record\n"
            "  2  usage / environment (fail closed)\n"
        ),
    )
    parser.add_argument("--repo", type=Path, default=None, help="the adopting repo")
    parser.add_argument(
        "--upstream-tree",
        type=Path,
        default=None,
        help="the Arborist working tree the overlay was laid from",
    )
    parser.add_argument(
        "--adopt-script",
        type=Path,
        default=None,
        help="the laying script whose digest to record",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help=(
            "record an admitted unknown baseline for a repo laid before provenance "
            "existed (does NOT reconstruct history)"
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether a usable record exists, writing nothing",
    )
    parser.add_argument("--print-path", action="store_true", help="print the path only")
    parser.add_argument("--quiet", action="store_true", help="suppress the summary")
    parser.add_argument(
        "--record-authority",
        action="store_true",
        help=(
            "fingerprint the files the global entry points execute, read from the "
            "upstream WORKING TREE (needs --upstream-tree)"
        ),
    )
    parser.add_argument(
        "--record-execution",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "append one execution record for PATH and exit 0 whatever happens "
            "(fail-open: an observer must not break the call it observes)"
        ),
    )
    parser.add_argument(
        "--arborist-home",
        type=Path,
        default=None,
        help=(
            f"machine-level root for the two global records "
            f"(default: ${ARBORIST_HOME_ENV}, else ~/.arborist)"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = (
        args.arborist_home.expanduser() if args.arborist_home else arborist_home()
    )
    tree = args.upstream_tree.expanduser() if args.upstream_tree else None

    if args.record_execution is not None:
        # Deliberately unconditional exit 0, including when nothing was written.
        # This runs on the hot path of a capability invocation; a non-zero exit here
        # would turn bookkeeping into an outage.
        written = record_execution(home, args.record_execution.expanduser(), tree=tree)
        if not args.quiet and not written:
            print(
                "arborist: could not record this execution; proceeding anyway "
                "(bookkeeping must never break the call it observes)"
            )
        return 0

    if args.record_authority:
        if tree is None or not tree.is_dir():
            print(
                "--record-authority needs --upstream-tree pointing at an existing "
                "tree: the fingerprints are of that tree's working files, which is "
                "what the entry points execute. Fail closed rather than record an "
                "empty set that would read as 'nothing is executed here'."
            )
            return 2
        document = record_authority_content(home, tree)
        if not args.quiet:
            unmatched = [
                f for f in document["files"] if f["matches_pinned_commit"] is False
            ]
            unknown = [
                f for f in document["files"] if f["matches_pinned_commit"] is None
            ]
            print(f"authority content recorded: {home / AUTHORITY_RELATIVE}")
            print(
                f"  tree={document['tree_path']} head={document['tree_head']} "
                f"dirty={document['tree_dirty']} "
                f"pinned_commit_seen={document['pinned_commit_seen']}"
            )
            print(
                f"  {len(document['files'])} executable file(s); "
                f"{len(unmatched)} differ from the pinned commit, "
                f"{len(unknown)} not comparable"
            )
            if unmatched:
                print(
                    "  !! what runs is not what the pin names. That is expected of a "
                    "working tree and is exactly why the fingerprint, not the commit, "
                    "is the reading. Consumer: validate_overlay_drift.py"
                )
        return 0

    if args.repo is None:
        print("nothing to record: pass --repo PATH, --record-authority, or --record-execution")
        return 2

    repo = args.repo.expanduser()
    path = repo / PROVENANCE_RELATIVE

    if args.print_path:
        print(path)
        return 0

    if not repo.is_dir():
        print(f"not a directory: {repo}")
        return 2

    if args.check:
        existing = read_existing(path)
        if existing is None:
            print(
                f"no usable provenance record at {path}. Adopt is not complete "
                "without one: absent provenance is indistinguishable from "
                "'never diverged', which is the reading this record exists to make "
                "impossible. Write one with --backfill."
            )
            return 1
        upstream = existing.get("upstream") or {}
        print(
            f"provenance present: {path} (schema {existing.get('schema_version')}, "
            f"commit {upstream.get('commit')}, basis {upstream.get('commit_basis')}, "
            f"{len(existing.get('surface') or [])} surface entr(ies), "
            f"{len(existing.get('local_modifications') or [])} declared deviation(s))"
        )
        return 0

    classifier = load_classifier()
    kind = KIND_BACKFILL if args.backfill else KIND_ADOPT
    upstream_tree = tree

    existing = read_existing(path)
    record = build_record(
        repo,
        upstream_tree=upstream_tree,
        kind=kind,
        adopt_script=args.adopt_script.expanduser() if args.adopt_script else None,
        existing=existing,
        classifier=classifier,
    )
    write_atomic(path, record)

    if args.quiet:
        return 0

    upstream = record["upstream"]
    print(f"provenance written: {path}")
    print(
        f"  upstream: commit={upstream['commit']} basis={upstream['commit_basis']} "
        f"dirty={upstream['dirty']} tree={upstream['tree_path']}"
    )
    print(
        f"  surface: {len(record['surface'])} entr(ies); declared deviations: "
        f"{len(record['local_modifications'])}"
    )
    if classifier is None:
        print(
            "  !! the tiering manifest (classify_tier.py) was not found beside this "
            "script, so NO surface digests were recorded. The record is a stub: a "
            "drift report built on it can say 'behind' but not 'modified'."
        )
    if upstream["commit"] is None:
        print(f"  !! no upstream commit recorded: {upstream.get('commit_unknown_reason')}")
    if upstream["dirty"]:
        print(
            "  !! the upstream tree has uncommitted changes under overlay/, so this "
            "commit does not fully describe what was laid."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
