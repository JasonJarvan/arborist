#!/usr/bin/env python3
"""Validate AgentTUI registry consistency across the global index and project leaves.

The registry (`agenttui-registry.md`) is a plain-file discovery table with **no
daemon**: every writer appends its own leaf and, optionally, a global summary.
That shape makes two classes of pollution structurally possible, and the guide
named both without ever giving them an executor — this script is the executor.

Six checks run over one global index plus the project leaf trees it points at:

1. **`session_id` global uniqueness** — one session belongs to one project. The
   same `session_id` claimed by leaves in two repos means one of them is a
   mis-registration, and a reader of the wrong one attributes an agent working
   in repo A to repo B.
2. **`pane_ref` uniqueness among reachable leaves** — one pane, one *live*
   agent, keyed on the `(multiplexer, session, pane_id)` triple. Formally a
   corollary of check 1, but checked independently because two *different*
   sessions naming the same pane means at least one `pane_ref` has already
   rotted (pane refs are start-time snapshots, guide §2.2), and the consequence
   is **mis-delivery into a third party's session, silently**.

   This check is **restricted to reachable state on purpose**, and splits into
   two findings of very different severity:

   * `pane-ref-conflict` (high, exit 1) — two reachable leaves claim one pane.
   * `stale-addressing-handle` (low, **warning only**) — a non-reachable leaf
     still carries a `pane_ref`.

   Panes are **reused in sequence**: a session ends and the next one starts in
   the same pane, so a stopped leaf still holding the old triple is the normal
   aftermath. Enforcing plain "globally unique triple" would report that as a
   collision, and a validator that cries wolf gets ignored — which is worse
   than not having one. The two also want opposite handling (drop everything
   and fix vs. sweep up later), so they must stay separately readable.
3. **half-registered, direction A** — index summary present, project leaf absent.
4. **half-registered, direction B** — project leaf present, index summary absent.
5. **`project` self-consistency** — a leaf's `spec.project.path` must equal the
   repo it actually sits in, and `project_id` must equal the sha256 prefix
   recomputed from that path. This is the mechanical detector for the failure
   shape "every field correct, the whole tree written one directory too high".
6. **index summary vs leaf agreement** — `role` / `brand` / `state` / `lineage`
   (absent reads as 1) must match, with the **leaf as authoritative** (guide §1).

Both half-registered directions are reported under the guide's own term
`half-registered` — neither "unregistered" nor "registered" — because the repair
differs per direction and neither licenses GC.

**Read-only, deliberately.** No `--fix`: the leaves live in other people's
repos, and deleting one is a judgement about which project a session belongs to,
not something a validator may make. It also never touches the network, reads no
credentials, and starts or stops nothing.

A missing or unparsable global index exits 2 (fail closed) rather than reading
as "nothing to check". A single project path that no longer exists is reported
and the remaining projects are still checked — one dead entry must not shadow
the whole registry's checkup.

Note check 1 is **not** state-restricted: a session_id registered twice is a
mis-registration whatever the states say. Only the pane_ref corollary needs the
reachability restriction.

Exit codes: 0 consistent (warnings may still be listed); 1 consistency failure;
2 usage / environment (fail closed).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Sequence

DEFAULT_GLOBAL_INDEX = Path.home() / ".arborist" / "index.json"

AGENTS_RELATIVE = Path(".arborist/agents")
SPEC_NAME = "spec.json"
RUNTIME_NAME = "runtime.json"

PROJECT_ID_LENGTH = 12

# Fields the global summary duplicates from the leaf (check 6). `lineage`
# carries the guide's documented default so a summary that omits it and a leaf
# that omits it still compare equal.
SUMMARY_FIELDS = ("role", "brand", "state", "lineage")
LINEAGE_DEFAULT = 1

# Declared states from which no pane addressing is expected to reach anybody.
# Everything else — `active`, the reserved `idle`, and any unknown or absent
# value — counts as reachable for the pane_ref uniqueness check (see
# `is_reachable_state`).
UNREACHABLE_STATES = ("stopped",)


class GlobalIndexError(RuntimeError):
    """The global index is missing, unreadable, or not the expected shape (exit 2)."""


class Finding(NamedTuple):
    """One consistency failure, printed verbatim on stdout."""

    code: str
    message: str

    def render(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass(frozen=True)
class Summary:
    """One agent summary read out of the global index."""

    project_root: Path
    name: str
    fields: dict[str, Any]

    @property
    def where(self) -> str:
        return f"index entry for project {self.project_root}, agent {self.name!r}"


@dataclass(frozen=True)
class Leaf:
    """One project-level leaf: `<repo>/.arborist/agents/<name>/{spec,runtime}.json`."""

    project_root: Path
    name: str
    directory: Path
    spec: dict[str, Any]
    runtime: dict[str, Any]

    @property
    def where(self) -> str:
        return f"{self.directory}"


def project_id_for(path: Path) -> str:
    """Recompute `project_id` exactly as the guide §2.1 defines it.

    Normalisation is `realpath` (resolve symlinks, drop the trailing slash) and
    the digest is the sha256 hex prefix. Recomputed, never trusted as written:
    a hand-copied `project_id` is how one repo splits into two index records.
    """

    normalized = str(Path(path).expanduser().resolve())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:PROJECT_ID_LENGTH]


def load_global_index(path: Path) -> list[dict[str, Any]]:
    """Return the index's `projects` list, or fail closed."""

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise GlobalIndexError(
            f"global index not found: {path}. A missing index is a fail-closed "
            "environment problem, not an empty registry: with no index there is "
            "no way to tell 'no agents registered' from 'the index was wiped'."
        ) from exc
    except OSError as exc:
        raise GlobalIndexError(f"cannot read global index {path}: {exc}") from exc

    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GlobalIndexError(f"global index is not valid JSON: {path}: {exc}") from exc

    if not isinstance(document, dict):
        raise GlobalIndexError(f"global index must be a JSON object: {path}")
    projects = document.get("projects")
    if projects is None:
        raise GlobalIndexError(f"global index has no 'projects' key: {path}")
    if not isinstance(projects, list):
        raise GlobalIndexError(f"global index 'projects' must be a list: {path}")
    return projects


def collect_summaries(
    projects: Iterable[dict[str, Any]],
    *,
    index_path: Path,
) -> tuple[list[Summary], list[Path], list[Finding]]:
    """Flatten the index into per-agent summaries plus the project set to scan.

    The project set comes from `projects[].path`, **not** from the agents found
    there: a project whose summary list is empty still has to be scanned, or
    every one of its leaves would go unchecked (half-registered direction B is
    exactly the case where the index lists nothing).
    """

    summaries: list[Summary] = []
    project_roots: list[Path] = []
    seen_roots: set[str] = set()
    findings: list[Finding] = []
    for position, project in enumerate(projects):
        if not isinstance(project, dict):
            findings.append(
                Finding(
                    "index-malformed",
                    f"{index_path}: projects[{position}] is not an object",
                )
            )
            continue
        path_value = project.get("path")
        if not isinstance(path_value, str) or not path_value:
            findings.append(
                Finding(
                    "index-malformed",
                    f"{index_path}: projects[{position}] has no usable 'path'",
                )
            )
            continue
        project_root = Path(path_value).expanduser()
        if str(project_root) not in seen_roots:
            seen_roots.add(str(project_root))
            project_roots.append(project_root)
        agents = project.get("agents", [])
        if not isinstance(agents, list):
            findings.append(
                Finding(
                    "index-malformed",
                    f"{index_path}: projects[{position}] 'agents' is not a list "
                    f"(project {project_root})",
                )
            )
            continue
        for agent_position, agent in enumerate(agents):
            if not isinstance(agent, dict) or not isinstance(agent.get("name"), str):
                findings.append(
                    Finding(
                        "index-malformed",
                        f"{index_path}: projects[{position}].agents"
                        f"[{agent_position}] has no usable 'name' "
                        f"(project {project_root})",
                    )
                )
                continue
            summaries.append(
                Summary(
                    project_root=project_root,
                    name=agent["name"],
                    fields=dict(agent),
                )
            )
    return summaries, project_roots, findings


def read_json_object(path: Path) -> dict[str, Any]:
    """Read one leaf file, raising ValueError for anything not a JSON object."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document


def collect_leaves(project_root: Path) -> tuple[list[Leaf], list[Finding]]:
    """Read every leaf under one project, reporting unreadable ones and moving on."""

    leaves: list[Leaf] = []
    findings: list[Finding] = []
    agents_dir = project_root / AGENTS_RELATIVE
    if not agents_dir.is_dir():
        # Not a failure on its own: a project may legitimately have no agents.
        # Missing leaves for agents the index *does* list surface as check 3.
        return leaves, findings

    for directory in sorted(agents_dir.iterdir()):
        if not directory.is_dir():
            continue
        spec_path = directory / SPEC_NAME
        runtime_path = directory / RUNTIME_NAME
        missing = [p for p in (spec_path, runtime_path) if not p.is_file()]
        if missing:
            findings.append(
                Finding(
                    "leaf-incomplete",
                    f"{directory} is missing "
                    + ", ".join(p.name for p in missing)
                    + " (a leaf is the spec.json + runtime.json pair)",
                )
            )
            continue
        try:
            spec = read_json_object(spec_path)
            runtime = read_json_object(runtime_path)
        except ValueError as exc:
            findings.append(Finding("leaf-unreadable", str(exc)))
            continue
        leaves.append(
            Leaf(
                project_root=project_root,
                name=directory.name,
                directory=directory,
                spec=spec,
                runtime=runtime,
            )
        )
    return leaves, findings


def check_session_id_uniqueness(leaves: Sequence[Leaf]) -> list[Finding]:
    """Check 1: one session belongs to exactly one project (and one leaf)."""

    grouped: defaultdict[str, list[Leaf]] = defaultdict(list)
    for leaf in leaves:
        session_id = leaf.runtime.get("session_id")
        if isinstance(session_id, str) and session_id:
            grouped[session_id].append(leaf)

    findings: list[Finding] = []
    for session_id, claimants in sorted(grouped.items()):
        if len(claimants) < 2:
            continue
        roots = {str(leaf.project_root.resolve()) for leaf in claimants}
        scope = (
            "in more than one project"
            if len(roots) > 1
            else "more than once in the same project"
        )
        listed = " and ".join(leaf.where for leaf in claimants)
        findings.append(
            Finding(
                "duplicate-session-id",
                f"session_id {session_id} is claimed {scope}: {listed}. "
                "One session belongs to one project. Which claim is real can be "
                "decided from the session_file path in each runtime.json or from "
                "the actual cwd of that pane; delete the leaf that does not "
                "belong to its project.",
            )
        )
    return findings


def pane_ref_key(pane_ref: Any) -> tuple[str, str, str] | None:
    """Return the `(multiplexer, session, pane_id)` triple, or None if unusable."""

    if not isinstance(pane_ref, dict):
        return None
    values = [pane_ref.get(field) for field in ("multiplexer", "session", "pane_id")]
    if any(not isinstance(value, str) or not value for value in values):
        return None
    return (values[0], values[1], values[2])  # type: ignore[return-value]


def is_reachable_state(runtime: dict[str, Any]) -> bool:
    """Is this leaf's declared state one that pane addressing could still target?

    Panes are **reused in sequence**: one session ends, the next starts in the
    same pane. A stopped leaf that still carries the old pane_ref is therefore
    the *normal* aftermath, not a collision — so uniqueness is enforced only
    among reachable leaves.

    An unknown or absent state counts as reachable: guessing "probably dead"
    would suppress the high-severity finding, and a suppressed mis-delivery
    warning is the one outcome worth avoiding.
    """

    state = runtime.get("state")
    return state not in UNREACHABLE_STATES


def check_pane_ref_uniqueness(
    leaves: Sequence[Leaf],
) -> tuple[list[Finding], list[Finding]]:
    """Check 2, in two halves that must not be folded into one.

    Returns `(conflicts, stale_handles)`:

    * **`pane-ref-conflict`** (high severity, exit 1) — two *reachable* leaves
      claim one pane. That is a live mis-delivery risk: the envelope lands in
      someone else's composer, silently.
    * **`stale-addressing-handle`** (low severity, warning) — a leaf in a
      non-reachable state still carries a non-empty `pane_ref`. That is a
      cleanup item, and it is deliberately **not** counted as a conflict:
      counting sequential pane reuse as a collision would flood the report with
      false positives, and a validator people learn to ignore is worse than none.
    """

    grouped: defaultdict[tuple[str, str, str], list[Leaf]] = defaultdict(list)
    stale: list[Finding] = []
    for leaf in leaves:
        key = pane_ref_key(leaf.runtime.get("pane_ref"))
        if key is None:
            continue
        if is_reachable_state(leaf.runtime):
            grouped[key].append(leaf)
            continue
        multiplexer, session, pane_id = key
        stale.append(
            Finding(
                "stale-addressing-handle",
                f"{leaf.where} declares state "
                f"{leaf.runtime.get('state')!r} but still carries pane_ref "
                f"(multiplexer={multiplexer}, session={session}, "
                f"pane_id={pane_id}). Leftover addressing handle: clear it in "
                "bulk. It is excluded from pane_ref uniqueness on purpose — the "
                "pane has most likely been reused by a later session, which is "
                "normal, not a collision.",
            )
        )

    conflicts: list[Finding] = []
    for key, claimants in sorted(grouped.items()):
        if len(claimants) < 2:
            continue
        multiplexer, session, pane_id = key
        listed = " and ".join(leaf.where for leaf in claimants)
        session_ids = {
            leaf.runtime.get("session_id")
            for leaf in claimants
            if isinstance(leaf.runtime.get("session_id"), str)
        }
        rot = (
            " These are different sessions, so at least one pane_ref has already "
            "rotted (pane refs are start-time snapshots)."
            if len(session_ids) > 1
            else ""
        )
        conflicts.append(
            Finding(
                "pane-ref-conflict",
                f"pane_ref (multiplexer={multiplexer}, session={session}, "
                f"pane_id={pane_id}) is claimed by more than one reachable leaf: "
                f"{listed}.{rot} Two live agents contending for one pane means "
                "delivery lands in a third party's session, silently; rebuild "
                "the whole pane_ref, do not edit single fields.",
            )
        )
    return conflicts, stale


def check_half_registered_a(
    summaries: Sequence[Summary],
    leaves_by_key: dict[tuple[str, str], Leaf],
    *,
    index_path: Path,
    readable_roots: set[str],
) -> list[Finding]:
    """Check 3: index summary present, project leaf absent."""

    findings: list[Finding] = []
    for summary in summaries:
        root = str(summary.project_root.resolve())
        if root not in readable_roots:
            # The project directory itself is unreachable; that is already
            # reported once per project, and re-reporting it per agent would
            # bury every other finding.
            continue
        if (root, summary.name) in leaves_by_key:
            continue
        expected = summary.project_root / AGENTS_RELATIVE / summary.name
        findings.append(
            Finding(
                "half-registered",
                f"direction A (index summary present, leaf absent): "
                f"{summary.where} in {index_path} has no leaf at {expected}/ "
                f"({SPEC_NAME} + {RUNTIME_NAME}). Neither unregistered nor "
                "registered: the owner repairs it by self-registering / "
                "register-self (a heartbeat cannot fix a file that does not "
                "exist), and it must not be GC'd on this evidence.",
            )
        )
    return findings


def check_half_registered_b(
    leaves: Sequence[Leaf],
    summaries_by_key: dict[tuple[str, str], Summary],
    *,
    index_path: Path,
) -> list[Finding]:
    """Check 4: project leaf present, index summary absent."""

    findings: list[Finding] = []
    for leaf in leaves:
        key = (str(leaf.project_root.resolve()), leaf.name)
        if key in summaries_by_key:
            continue
        findings.append(
            Finding(
                "half-registered",
                f"direction B (leaf present, index summary absent): {leaf.where} "
                f"has no matching entry in {index_path} for project "
                f"{leaf.project_root} agent {leaf.name!r}. Neither unregistered "
                "nor registered: the owner's heartbeat or the gardener's roll-up "
                "adds the summary, and it must not be GC'd on this evidence.",
            )
        )
    return findings


def check_project_self_consistency(leaves: Sequence[Leaf]) -> list[Finding]:
    """Check 5: declared project path == hosting repo, and project_id recomputes."""

    findings: list[Finding] = []
    for leaf in leaves:
        project = leaf.spec.get("project")
        if not isinstance(project, dict):
            findings.append(
                Finding(
                    "project-mismatch",
                    f"{leaf.where}/{SPEC_NAME} has no 'project' object "
                    "({path, project_id} is required to attribute the leaf)",
                )
            )
            continue

        declared_path = project.get("path")
        actual_root = leaf.project_root.resolve()
        if not isinstance(declared_path, str) or not declared_path:
            findings.append(
                Finding(
                    "project-mismatch",
                    f"{leaf.where}/{SPEC_NAME} has no 'project.path' "
                    f"(it sits in {actual_root})",
                )
            )
        else:
            declared_root = Path(declared_path).expanduser().resolve()
            if declared_root != actual_root:
                findings.append(
                    Finding(
                        "project-mismatch",
                        f"{leaf.where}/{SPEC_NAME} declares project.path "
                        f"{declared_path} but the leaf actually sits in "
                        f"{actual_root}. A leaf may only live at "
                        f"<repo>/{AGENTS_RELATIVE.as_posix()}/<name>/ of the very "
                        "repo it declares.",
                    )
                )

        declared_id = project.get("project_id")
        if isinstance(declared_path, str) and declared_path:
            expected_id = project_id_for(Path(declared_path))
            if declared_id != expected_id:
                findings.append(
                    Finding(
                        "project-id-mismatch",
                        f"{leaf.where}/{SPEC_NAME} declares project_id "
                        f"{declared_id!r} but the sha256 prefix recomputed from "
                        f"realpath({declared_path}) is {expected_id!r}. The id is "
                        "recomputed, never trusted as written.",
                    )
                )
    return findings


def summary_value(fields: dict[str, Any], field: str) -> Any:
    if field == "lineage":
        return fields.get("lineage", LINEAGE_DEFAULT)
    return fields.get(field)


def leaf_value(leaf: Leaf, field: str) -> Any:
    if field == "state":
        return leaf.runtime.get("state")
    if field == "lineage":
        return leaf.spec.get("lineage", LINEAGE_DEFAULT)
    return leaf.spec.get(field)


def check_summary_agreement(
    leaves: Sequence[Leaf],
    summaries_by_key: dict[tuple[str, str], Summary],
    *,
    index_path: Path,
) -> list[Finding]:
    """Check 6: the duplicated summary fields must agree, leaf authoritative."""

    findings: list[Finding] = []
    for leaf in leaves:
        key = (str(leaf.project_root.resolve()), leaf.name)
        summary = summaries_by_key.get(key)
        if summary is None:
            continue  # direction B, already reported by check 4.
        for field in SUMMARY_FIELDS:
            expected = leaf_value(leaf, field)
            actual = summary_value(summary.fields, field)
            if expected != actual:
                findings.append(
                    Finding(
                        "index-leaf-disagreement",
                        f"{field}: {index_path} says {actual!r} for project "
                        f"{leaf.project_root} agent {leaf.name!r}, while "
                        f"{leaf.where} says {expected!r}. The leaf is "
                        "authoritative; fix the index summary.",
                    )
                )
    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Validate AgentTUI registry consistency: session_id and pane_ref "
            "global uniqueness, both half-registered directions, project-field "
            "self-consistency, and index-summary vs leaf agreement. Read-only "
            "by design — it reports, it never repairs."
        ),
        epilog=(
            "failures (exit 1; each reported with its own code):\n"
            "  duplicate-session-id     one session claimed by leaves in 2+ projects\n"
            "  pane-ref-conflict        one (multiplexer, session, pane_id) claimed by\n"
            "                           two *reachable* leaves = live mis-delivery risk\n"
            "  half-registered          direction A (summary, no leaf) / B (leaf, no summary)\n"
            "  project-mismatch         spec.project.path != the repo hosting the leaf\n"
            "  project-id-mismatch      project_id != sha256 prefix of realpath(path)\n"
            "  index-leaf-disagreement  role/brand/state/lineage differ (leaf wins)\n"
            "\n"
            "warnings (listed separately, do NOT affect the exit code):\n"
            "  stale-addressing-handle  a non-reachable leaf still carries a pane_ref.\n"
            "                           A cleanup item, never a conflict: panes get\n"
            "                           reused in sequence, so this is the normal\n"
            "                           aftermath of a session ending. Folding it into\n"
            "                           pane-ref-conflict would bury the real ones.\n"
            "\n"
            "exit codes:\n"
            "  0  registry consistent (a check count is printed; warnings may be listed)\n"
            "  1  at least one consistency failure, or an unreachable project path\n"
            "  2  global index missing / unparsable (fail closed, nothing checked)\n"
        ),
    )
    parser.add_argument(
        "--global-index",
        type=Path,
        default=DEFAULT_GLOBAL_INDEX,
        help=f"global registry index (default: {DEFAULT_GLOBAL_INDEX})",
    )
    parser.add_argument(
        "--project",
        type=Path,
        action="append",
        default=None,
        dest="projects",
        metavar="PATH",
        help=(
            "project root to check; repeatable. Default: every projects[].path "
            "in the global index"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    index_path = args.global_index.expanduser()

    try:
        raw_projects = load_global_index(index_path)
    except GlobalIndexError as exc:
        print(f"global index unusable: {exc}")
        return 2

    summaries, indexed_roots, findings = collect_summaries(
        raw_projects, index_path=index_path
    )

    if args.projects:
        project_roots = [path.expanduser() for path in args.projects]
    else:
        project_roots = indexed_roots

    leaves: list[Leaf] = []
    readable_roots: set[str] = set()
    for project_root in project_roots:
        if not project_root.is_dir():
            # Report and keep going: one dead index entry must not shadow the
            # rest of the registry's checkup.
            findings.append(
                Finding(
                    "project-unreachable",
                    f"project path does not exist: {project_root} (named by "
                    f"{index_path}); its leaf-side checks were skipped, the "
                    "other projects were still checked",
                )
            )
            continue
        readable_roots.add(str(project_root.resolve()))
        project_leaves, project_findings = collect_leaves(project_root)
        leaves.extend(project_leaves)
        findings.extend(project_findings)

    leaves_by_key = {
        (str(leaf.project_root.resolve()), leaf.name): leaf for leaf in leaves
    }
    summaries_by_key = {
        (str(summary.project_root.resolve()), summary.name): summary
        for summary in summaries
    }

    findings.extend(check_session_id_uniqueness(leaves))
    pane_conflicts, warnings = check_pane_ref_uniqueness(leaves)
    findings.extend(pane_conflicts)
    findings.extend(
        check_half_registered_a(
            summaries,
            leaves_by_key,
            index_path=index_path,
            readable_roots=readable_roots,
        )
    )
    findings.extend(
        check_half_registered_b(leaves, summaries_by_key, index_path=index_path)
    )
    findings.extend(check_project_self_consistency(leaves))
    findings.extend(
        check_summary_agreement(leaves, summaries_by_key, index_path=index_path)
    )

    counts = (
        f"checked {len(project_roots)} project(s), {len(leaves)} leaf/leaves, "
        f"{len(summaries)} index summar(y/ies)"
    )

    for finding in findings:
        print(finding.render())
    if warnings:
        # A separate, labelled block: the low-severity cleanup items must never
        # be mistaken for — or hide — the mis-delivery findings above.
        print("--- warnings (cleanup items; do not affect the exit code) ---")
        for warning in warnings:
            print(f"warning: {warning.render()}")

    if findings:
        print(
            f"{len(findings)} registry consistency failure(s), "
            f"{len(warnings)} warning(s); {counts}"
        )
        return 1

    print(f"AgentTUI registry consistent: {index_path}")
    print(f"{len(warnings)} warning(s); {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
