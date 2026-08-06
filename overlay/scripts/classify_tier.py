#!/usr/bin/env python3
"""Classify every artifact of the adopted overlay surface as global or project tier.

**The rule, and there is only one** -- the *repo-invariance test*:

> Move artifact A verbatim into another adopted repo on this machine. Does A's
> **correct content** change? No -> **global tier** (one authoritative copy).
> Yes -> **project tier** (one copy per repo). Partly -> it must be **split**; it
> may not be filed whole under either tier.

The object of the test is the **correct** content, never the *current* content.
Copies that have already diverged are the *consequence* of filing a global-tier
artifact per-repo, not evidence that it was project-tier all along -- so this
script reports divergence and tier as two separate readings and never lets the
first decide the second.

MECHANISING "the correct content changes"
-----------------------------------------
It changes exactly when the correct content has to carry a **project-dimension
value**. The closed set (each one detectable, each one a *value*, not a topic):

  P1  the repo root path, and the `project_id` derived from it
  P2  this repo's AgentTUI identity (session ids, session files, pane refs)
  P3  this repo's task / branch / issue identifiers
  P4  this repo's host reality (machine-absolute paths outside the repo, brand
      closed sets, service ids)
  P5  this repo's git objects (object names, side-history refs)

**Only value shapes count as evidence, never field names.** The registry guide
documents `session_id` and `pane_ref` at length; a detector that fired on the
*words* would classify the guides -- the largest provably repo-invariant surface
there is -- as project tier, and would do so with perfect confidence. Angle-bracket
placeholders are masked out before detection for the same reason: `<REPO_ROOT>` is
the generalized *absence* of a value.

TWO METHODS, REPORTED SEPARATELY
--------------------------------
1. **Detection** (per file): do any P1-P5 values appear?
2. **Cross-repo agreement** (`--crosscheck`): for one relative path, do all repos
   hold the same bytes?

They answer different questions and are both reported. Where method 1 says "no
project-dimension value" and method 2 says "the copies differ", that combination
is not a contradiction -- it is the signature of a global-tier artifact that was
copied per-repo and drifted, i.e. the exact finding this whole exercise exists to
make visible.

WHAT IS DELIBERATELY NOT DECIDED HERE
-------------------------------------
Three verdicts are referred to a human rather than guessed:

* `UNKNOWN/declared-global-carries-instance-value` -- a rule says global, the file
  carries a project-dimension value. Either a generalization-boundary violation
  (fix the file) or a mis-filed rule (fix the rule). Which one it is cannot be read
  off the bytes.
* `UNKNOWN/declared-project-carries-none` -- a rule says project tier on content
  grounds, but this repo's copy carries no instance value at all. Often means the
  copy is still the untouched template.
* `UNKNOWN/unclassified` -- the artifact matches no rule. Experiments that grew in
  one repo land here. Filing one *up* into a machine-wide contract by default would
  freeze one repo's experiment into everyone's contract, so the default is to leave
  it alone and name its owner.

A rule may declare its basis as `location` when repo-invariance fails for reasons
content cannot show -- a side-history git directory records *this* repo's object
graph; a repo's git exclude段 can only take effect in that repo's git dir. For
those, content detection is reported but never overrides the rule.

**Read-only.** No `--fix`, no writes, no external commands except `git` queries
that are themselves read-only, and nothing is written to any repo it inspects. The
`project_id` is computed by the registry validator's own implementation, loaded as
a module -- never reimplemented, because two implementations of a derived id is
precisely how one repo ends up with two ids (agenttui-registry.md §2.3).

Exit codes: 0 everything classified (and, with `--crosscheck`, no divergence);
1 findings to read (unknowns and/or divergence); 2 usage / environment, fail closed.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

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

TIER_GLOBAL = "G"
TIER_PROJECT = "P"
TIER_SPLIT = "S"
TIER_UNKNOWN = "UNKNOWN"

# Who writes the artifact. `trellis` matters on its own: those files are written by
# an upstream package's own installer, so converging them from here would be
# overwritten by their writer -- they are detected and reported, never converged.
WRITER_ARBORIST = "arborist"
WRITER_TRELLIS = "trellis"
WRITER_ADOPTER = "adopter"

BASIS_CONTENT = "content"
BASIS_LOCATION = "location"
BASIS_SPLIT = "split"

# Masked before detection: a placeholder is the generalized *absence* of a value,
# so a rule that counted it as one would classify every template as project tier.
PLACEHOLDER = re.compile(r"<[^<>\n]{1,120}>")
# The mask must be built from characters no detector's character class accepts,
# otherwise the mask itself becomes matchable: a word-shaped mask turns
# `.trellis/tasks/<mm-dd>-<slug>` into a "concrete" task path and every template
# reads as project tier. A control character satisfies that by construction.
PLACEHOLDER_MASK = "\x1f"

SESSION_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)
GIT_OBJECT_NAME = re.compile(r"\b[0-9a-f]{40}\b")
TASK_REF = re.compile(r"\.trellis/tasks/[0-9A-Za-z][0-9A-Za-z._-]*")
# Structural subdirectories of the task ledger, not task identifiers. Naming one is
# a statement about the *layout*, which is the same in every repo -- the reason the
# ledger's own directory is repo-invariant while its entries are not.
TASK_LEDGER_STRUCTURAL = frozenset({"archive"})
PROJECT_ID_SHAPE = re.compile(r"\b[0-9a-f]{12}\b")

# Files that are never artifacts of the surface, whatever directory they sit in.
NOISE_SUFFIXES = (".pyc", ".pyo", ".bak", ".orig", ".rej", ".swp", ".pre-st.bak")
NOISE_NAMES = ("__pycache__", ".DS_Store")

# Bytes read per file for detection. A generalization-boundary violation or an
# instance path appears in the head of a text file in practice, and an unbounded
# read over a machine's whole adopted surface turns a survey into a memory event.
READ_LIMIT = 512 * 1024


@dataclass(frozen=True)
class Rule:
    """One line of the surface manifest.

    `pattern` is a repo-relative fnmatch pattern (`**` crosses directories).
    `walk=False` treats a matching directory as **one** artifact and does not
    descend into it -- required for a side-history git directory (walking it is a
    survey of an object store, not of a surface) and appropriate for letter and
    task directories, whose per-repo nature is a property of the directory.
    """

    pattern: str
    tier: str
    writer: str
    basis: str
    why: str
    walk: bool = True


# The manifest. Ordered: the first matching rule wins, so specific entries precede
# the catch-alls they carve out of. Every path here is repo-relative and generic --
# no machine holds a value in this table.
SURFACE: tuple[Rule, ...] = (
    # ---- documents and templates. Generalization-boundary already forbids these
    # from carrying instance values, so they are repo-invariant *by construction*;
    # an instance value found in one is a boundary violation to fix, never a reason
    # to refile it as project tier.
    Rule(
        ".trellis/spec/guides/**",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "guides, ADRs and methodology: generalized by contract, so repo-invariant",
    ),
    Rule(
        ".arborist/templates/**",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "field documentation; example values only",
    ),
    Rule(
        ".work_context/sendbox/_TEMPLATE-*.md",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "letter templates: the shape is the contract, not this repo's letters",
    ),
    # ---- executable capability. A script's correct content does not depend on the
    # repo; the repo is a runtime argument. A script that hardcodes a repo path has
    # a bug, which is not the same thing as being project tier.
    Rule(
        ".trellis/scripts/agenttui*.py",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "AgentTUI reach/delivery: a machine-level capability",
    ),
    Rule(
        ".trellis/scripts/arborist_brand_capacity.py",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "brand capacity observer; its state is machine-level too",
    ),
    Rule(
        ".trellis/scripts/validate_*.py",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "validator code is repo-invariant; only what it validates is per-repo",
    ),
    Rule(
        ".trellis/scripts/classify_tier.py",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "this script; the criterion applies to itself",
    ),
    Rule(
        ".trellis/scripts/*.README.md",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "adapter documentation shipped beside its script",
    ),
    Rule(
        "scripts/trellis_multica_sync.py",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "ledger sync capability; ids arrive from the environment",
    ),
    Rule(
        "scripts/install-brand-compat.py",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "installer code; the installed block is the per-repo part",
    ),
    Rule(
        "scripts/validate_brand_compat.py",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "validator code",
    ),
    # ---- Trellis's own files. The criterion is applied to them without exemption
    # and answers "global" -- but their **writer** is an upstream package's own
    # installer, so the finding is recorded and no convergence is proposed here.
    Rule(
        ".trellis/scripts/hooks/**",
        TIER_GLOBAL,
        WRITER_TRELLIS,
        BASIS_CONTENT,
        "upstream-owned: detect drift, do not converge (its writer would overwrite)",
    ),
    Rule(
        ".trellis/scripts/common/**",
        TIER_GLOBAL,
        WRITER_TRELLIS,
        BASIS_CONTENT,
        "upstream-owned: detect drift, do not converge",
    ),
    Rule(
        ".trellis/scripts/__init__.py",
        TIER_GLOBAL,
        WRITER_TRELLIS,
        BASIS_CONTENT,
        "upstream-owned: detect drift, do not converge",
    ),
    Rule(
        ".trellis/scripts/*.py",
        TIER_GLOBAL,
        WRITER_TRELLIS,
        BASIS_CONTENT,
        "upstream-owned CLI helpers: detect drift, do not converge",
    ),
    # ---- must be split: a repo-invariant body plus a per-repo part in one file.
    Rule(
        "hgit",
        TIER_SPLIT,
        WRITER_ARBORIST,
        BASIS_SPLIT,
        "script body is global; snapshot allowlist entries a repo adds are project",
    ),
    Rule(
        ".trellis/workflow.md",
        TIER_SPLIT,
        WRITER_ADOPTER,
        BASIS_SPLIT,
        "customization block is global source; the substituted host values are not",
    ),
    Rule(
        "AGENTS.md",
        TIER_SPLIT,
        WRITER_ADOPTER,
        BASIS_SPLIT,
        "brand-compat block is global source; the surrounding instructions are not",
    ),
    # ---- global tier that is currently held per repo. Filing, not content: the
    # observed quantity is a machine-level account budget, so the state and its
    # lock belong to the machine. One lock per repo means there is no machine-level
    # mutual exclusion at all, which is a defect and not merely a placement.
    Rule(
        ".arborist/runtime/brand-capacity.json",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "observes machine-level brand budget: repo-invariant, currently per-repo",
    ),
    Rule(
        ".arborist/runtime/brand-capacity.lock",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_LOCATION,
        "a per-repo lock provides no machine-level mutual exclusion",
    ),
    Rule(
        ".arborist/runtime/brand-capacity-reports/**",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "self-reports about machine-level capacity",
    ),
    Rule(
        ".arborist/tools/agenttui-direct.json",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "describes a machine-level capability; project scope mirrors today's copies",
    ),
    Rule(
        ".arborist/tools/arborist-brand-capacity.json",
        TIER_GLOBAL,
        WRITER_ARBORIST,
        BASIS_CONTENT,
        "describes a machine-level capability",
    ),
    # ---- project tier.
    Rule(
        ".arborist/agents/**",
        TIER_PROJECT,
        WRITER_ADOPTER,
        BASIS_LOCATION,
        "the authoritative leaf: every record names this project",
    ),
    Rule(
        ".arborist/tools/*.json",
        TIER_PROJECT,
        WRITER_ADOPTER,
        BASIS_CONTENT,
        "project-specific capability entry; overrides the global one by name",
    ),
    Rule(
        ".arborist/overlay-provenance.json",
        TIER_PROJECT,
        WRITER_ARBORIST,
        BASIS_LOCATION,
        "records where *this* repo's overlay stopped; one per repo by definition",
    ),
    Rule(
        ".harness-vcs",
        TIER_PROJECT,
        WRITER_ADOPTER,
        BASIS_LOCATION,
        "this repo's harness object graph; merging it destroys path@commit checks",
        walk=False,
    ),
    Rule(
        ".work_context/sendbox/_handoff-config.yaml",
        TIER_PROJECT,
        WRITER_ADOPTER,
        BASIS_CONTENT,
        "the host's supported-brand closed set and routing policy",
    ),
    Rule(
        ".work_context/sendbox/toAgent",
        TIER_PROJECT,
        WRITER_ADOPTER,
        BASIS_LOCATION,
        "letters are this repo's durable records; they outlive sessions",
        walk=False,
    ),
    Rule(
        ".work_context/sendbox/toHuman",
        TIER_PROJECT,
        WRITER_ADOPTER,
        BASIS_LOCATION,
        "letters are this repo's durable records",
        walk=False,
    ),
    Rule(
        ".work_context/Dashboard",
        TIER_PROJECT,
        WRITER_ADOPTER,
        BASIS_LOCATION,
        "a projection of this repo's letters",
        walk=False,
    ),
    Rule(
        ".trellis/tasks",
        TIER_PROJECT,
        WRITER_ADOPTER,
        BASIS_LOCATION,
        "this repo's task ledger",
        walk=False,
    ),
    Rule(
        ".trellis/config.yaml",
        TIER_PROJECT,
        WRITER_ADOPTER,
        BASIS_CONTENT,
        "per-repo and per-machine configuration",
    ),
    Rule(
        ".developer",
        TIER_PROJECT,
        WRITER_ADOPTER,
        BASIS_CONTENT,
        "per-machine developer identity",
    ),
    Rule(
        ".mcp.json",
        TIER_PROJECT,
        WRITER_ADOPTER,
        BASIS_CONTENT,
        "indexes this repo's code",
    ),
    Rule(
        ".codegraph",
        TIER_PROJECT,
        WRITER_ADOPTER,
        BASIS_LOCATION,
        "symbol graph over this repo's code",
        walk=False,
    ),
)

# Where to look for artifacts that match no rule. Bounded to the surface the adopt
# script actually lays: a survey that walked the whole repo would report the
# product's own source as unclassified, and one that walked all of `.trellis/spec/`
# would report the adopter's own spec layers -- neither is this exercise's object,
# and a docket padded with them is a docket nobody reads.
SURVEY_ROOTS: tuple[str, ...] = (
    ".arborist",
    ".trellis/scripts",
    ".trellis/spec/guides",
    ".work_context",
)

# Directories never descended into during the survey, whatever a rule says. An
# object store and a bytecode cache are not surface.
SURVEY_SKIP_DIRS: tuple[str, ...] = (".harness-vcs", "__pycache__", ".codegraph")


class EnvironmentError_(RuntimeError):
    """Fail-closed environment problem (exit 2)."""


def project_id_for(path: Path) -> str | None:
    """The registry's `project_id`, computed by the registry's own implementation.

    Deliberately not reimplemented: two implementations of a derived id is how one
    repo ends up with two ids (agenttui-registry.md §2.3). If the registry validator
    is not beside this script, the value is reported as unknown -- never guessed,
    because a guessed id would then be *searched for* and would silently match
    nothing.
    """

    module_path = Path(__file__).resolve().parent / "validate_agenttui_registry.py"
    if not module_path.is_file():
        return None
    name = "_arborist_registry_validator_for_tiering"
    try:
        spec = importlib.util.spec_from_file_location(name, module_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return str(module.project_id_for(path))
    except Exception:
        return None
    finally:
        sys.modules.pop(name, None)


def is_noise(relative: str) -> bool:
    parts = Path(relative).parts
    if any(part in NOISE_NAMES for part in parts):
        return True
    return relative.endswith(NOISE_SUFFIXES)


def glob_pattern_for(pattern: str) -> str:
    """Turn a manifest pattern into one `Path.glob` will match *files* with.

    `Path.glob("dir/**")` yields **directories only** -- `**` stands for a run of
    directories, so a trailing one matches no file at all. The manifest is written
    in the shell's reading of `**` (everything below here), and a silent zero-match
    is the worst possible way for that mismatch to show up: the report simply omits
    the largest part of the surface and still looks complete.
    """

    return pattern + "/*" if pattern.endswith("/**") else pattern


def match_rule(relative: str) -> Rule | None:
    """First matching manifest rule, or None.

    A `**` pattern matches the directory itself as well as anything under it, so a
    rule written for a tree does not need a second entry for its root.
    """

    for rule in SURFACE:
        pattern = rule.pattern
        if fnmatch.fnmatchcase(relative, pattern):
            return rule
        if pattern.endswith("/**"):
            stem = pattern[: -len("/**")]
            if relative == stem or fnmatch.fnmatchcase(relative, stem):
                return rule
        # A non-walk rule names a directory; everything under it is that artifact.
        if not rule.walk and (
            relative == pattern or relative.startswith(pattern + "/")
        ):
            return rule
    return None


def read_head(path: Path) -> str | None:
    """Read the head of a text file, or None when it is not usefully text."""

    try:
        with path.open("rb") as handle:
            raw = handle.read(READ_LIMIT)
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    return raw.decode("utf-8", errors="replace")


@dataclass
class Detection:
    """Which project-dimension values a file's content carries."""

    hits: list[str] = field(default_factory=list)
    readable: bool = True

    @property
    def carries_instance_value(self) -> bool:
        return bool(self.hits)


def detect(text: str, *, repo: Path, project_id: str | None, home: Path) -> Detection:
    """Run the P1-P5 value detectors over one file's masked text.

    Value shapes only. Field names are never evidence: the registry guide documents
    `session_id` and `pane_ref` at length, and a detector that fired on the words
    would file the guides -- the largest provably repo-invariant surface there is --
    as project tier, confidently and wrongly.
    """

    masked = PLACEHOLDER.sub(PLACEHOLDER_MASK, text)
    detection = Detection()

    repo_literals = {str(repo), str(repo.resolve())}
    for literal in repo_literals:
        if literal in masked:
            detection.hits.append(f"P1 repo-root-path: {literal!r} appears verbatim")
            break

    if project_id:
        # Constrained to the 12-hex shape so a coincidental substring of a longer
        # digest is not read as the id.
        for candidate in set(PROJECT_ID_SHAPE.findall(masked)):
            if candidate == project_id:
                detection.hits.append("P1 project-id: this repo's derived id appears")
                break

    home_literal = str(home)
    outside = [
        found
        for found in set(
            re.findall(re.escape(home_literal) + r"/[^\s\"'`,;)\]]{1,200}", masked)
        )
        if not any(found.startswith(literal) for literal in repo_literals)
    ]
    if outside:
        detection.hits.append(
            f"P4 machine-absolute-path: {len(outside)} path(s) under the home "
            "directory but outside this repo"
        )

    sessions = set(SESSION_UUID.findall(masked))
    if sessions:
        detection.hits.append(f"P2 session-uuid: {len(sessions)} value(s)")

    objects = set(GIT_OBJECT_NAME.findall(masked))
    if objects:
        detection.hits.append(f"P5 git-object-name: {len(objects)} value(s)")

    # A task path only counts when it names a task that **exists in this repo**.
    # Illustrative task ids are everywhere -- in docstrings, in templates, in the
    # guides' own worked examples -- and counting those would file every document
    # that explains the layout as project tier. Existence is what separates "this
    # repo's ledger entry" from "an example of what one looks like".
    tasks = {
        ref
        for ref in TASK_REF.findall(masked)
        if ref.rsplit("/", 1)[-1] not in TASK_LEDGER_STRUCTURAL
        and (repo / ref).exists()
    }
    if tasks:
        detection.hits.append(
            f"P3 task-ref: {len(tasks)} task path(s) that exist in this repo"
        )

    return detection


def digest(path: Path) -> str | None:
    """sha256 of one file, or None for a directory or an unreadable path."""

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


@dataclass
class Artifact:
    """One classified path in one repo."""

    repo: str
    relative: str
    tier: str
    code: str
    writer: str
    basis: str
    why: str
    evidence: list[str]
    sha256: str | None
    is_dir: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "path": self.relative,
            "tier": self.tier,
            "code": self.code,
            "writer": self.writer,
            "basis": self.basis,
            "why": self.why,
            "evidence": self.evidence,
            "sha256": self.sha256,
            "kind": "directory" if self.is_dir else "file",
        }

    def render(self) -> str:
        head = f"{self.tier:<7} {self.relative}"
        if self.code != "agreed":
            head += f"  [{self.code}]"
        if self.evidence:
            head += "\n" + "\n".join(f"          - {item}" for item in self.evidence)
        return head


def enumerate_surface(repo: Path) -> list[tuple[str, Rule | None, bool]]:
    """Every surface path in one repo, with its rule (or None when unclassified).

    Returns `(relative_path, rule, is_dir)`. Order is stable so two runs over an
    unchanged machine produce identical reports -- a survey whose output reorders
    itself cannot be diffed, and a report nobody diffs is a report nobody reads.
    """

    found: dict[str, tuple[Rule | None, bool]] = {}

    def consider(path: Path) -> None:
        relative = path.relative_to(repo).as_posix()
        if is_noise(relative):
            return
        rule = match_rule(relative)
        if rule is not None and not rule.walk:
            # One artifact for the whole tree; record it under the rule's own name
            # so N repos produce N entries rather than N x (its file count).
            found.setdefault(rule.pattern, (rule, (repo / rule.pattern).is_dir()))
            return
        found[relative] = (rule, path.is_dir())

    # Rules first: this is what makes an *absent* artifact reportable rather than
    # invisible (a repo missing a global-tier script is the strongest drift signal
    # there is, and a walk of what exists can never produce it).
    for rule in SURFACE:
        if "*" in rule.pattern:
            for path in sorted(repo.glob(glob_pattern_for(rule.pattern))):
                if any(part in SURVEY_SKIP_DIRS for part in path.parts):
                    continue
                consider(path)
        else:
            path = repo / rule.pattern
            if path.exists():
                consider(path)

    # Then a bounded walk, to surface artifacts no rule mentions.
    for root_name in SURVEY_ROOTS:
        root = repo / root_name
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SURVEY_SKIP_DIRS)
            here = Path(dirpath)
            relative_dir = here.relative_to(repo).as_posix()
            dir_rule = match_rule(relative_dir)
            if dir_rule is not None and not dir_rule.walk:
                # A tree the manifest treats as one artifact: it was already
                # recorded above, and descending would replace one honest entry
                # with a file-by-file transcript of somebody's letters.
                dirnames[:] = []
                continue
            for name in sorted(filenames):
                consider(here / name)

    return [
        (relative, rule, is_dir)
        for relative, (rule, is_dir) in sorted(found.items())
    ]


def classify_repo(repo: Path, *, home: Path) -> list[Artifact]:
    """Classify one repo's whole surface."""

    project_id = project_id_for(repo)
    artifacts: list[Artifact] = []
    for relative, rule, is_dir in enumerate_surface(repo):
        path = repo / relative
        sha = None if is_dir else digest(path)

        if rule is None:
            artifacts.append(
                Artifact(
                    repo=str(repo),
                    relative=relative,
                    tier=TIER_UNKNOWN,
                    code="unclassified",
                    writer="unknown",
                    basis="none",
                    why=(
                        "matches no manifest rule. Filing it up into a machine-wide "
                        "contract by default would freeze one repo's experiment into "
                        "everyone's contract; leave it in place and name its owner."
                    ),
                    evidence=[],
                    sha256=sha,
                    is_dir=is_dir,
                )
            )
            continue

        evidence: list[str] = []
        code = "agreed"
        tier = rule.tier

        if is_dir or rule.basis in (BASIS_LOCATION, BASIS_SPLIT):
            if rule.basis == BASIS_SPLIT:
                code = "split-not-file-granular"
                evidence.append(
                    "the split boundary is inside this file; a per-file digest "
                    "cannot draw it, so the parts are named in the rule instead"
                )
        else:
            text = read_head(path)
            if text is None:
                code = "content-unreadable"
                evidence.append(
                    "not decodable as text (or unreadable), so content detection "
                    "was not run; the rule stands on its own reasoning"
                )
            else:
                detection = detect(
                    text, repo=repo, project_id=project_id, home=home
                )
                evidence.extend(detection.hits)
                if rule.tier == TIER_GLOBAL and detection.carries_instance_value:
                    tier = TIER_UNKNOWN
                    code = "declared-global-carries-instance-value"
                elif (
                    rule.tier == TIER_PROJECT and not detection.carries_instance_value
                ):
                    tier = TIER_UNKNOWN
                    code = "declared-project-carries-none"

        artifacts.append(
            Artifact(
                repo=str(repo),
                relative=relative,
                tier=tier,
                code=code,
                writer=rule.writer,
                basis=rule.basis,
                why=rule.why,
                evidence=evidence,
                sha256=sha,
                is_dir=is_dir,
            )
        )
    return artifacts


def crosscheck(artifacts: Sequence[Artifact], repos: Sequence[Path]) -> list[dict[str, Any]]:
    """Cross-repo agreement for artifacts whose correct content is repo-invariant.

    Divergence here is a **separate reading** from the tier verdict, never an input
    to it: a global-tier artifact copied per repo diverges *because* it was copied,
    so letting divergence refile it as project tier would ratify the very mistake.
    """

    groups: dict[str, dict[str, str | None]] = {}
    for artifact in artifacts:
        if artifact.is_dir or artifact.tier != TIER_GLOBAL:
            continue
        groups.setdefault(artifact.relative, {})[artifact.repo] = artifact.sha256

    findings: list[dict[str, Any]] = []
    repo_names = [str(repo) for repo in repos]
    for relative, by_repo in sorted(groups.items()):
        digests = {sha for sha in by_repo.values() if sha}
        absent = [name for name in repo_names if name not in by_repo]
        if len(digests) <= 1 and not absent:
            continue
        findings.append(
            {
                "path": relative,
                "variants": len(digests),
                "present_in": len(by_repo),
                "absent_from": len(absent),
                "verdict": (
                    "divergent"
                    if len(digests) > 1
                    else "partially-deployed"
                ),
                "note": (
                    "one authoritative content, more than one copy on this machine: "
                    "the copies have already diverged. Divergence is the consequence "
                    "of the per-repo copy, not evidence of project tier."
                    if len(digests) > 1
                    else "absent from at least one adopted repo"
                ),
                "by_repo": by_repo,
                "absent_repos": absent,
            }
        )
    return findings


def load_repos_from_index(index_path: Path) -> list[Path]:
    try:
        raw = index_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise EnvironmentError_(
            f"global index not found: {index_path}. A missing index is a fail-closed "
            "environment problem, not an empty machine: with no index there is no "
            "way to tell 'nothing adopted' from 'the index was wiped'."
        ) from exc
    except OSError as exc:
        raise EnvironmentError_(f"cannot read global index {index_path}: {exc}") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EnvironmentError_(f"global index is not valid JSON: {index_path}: {exc}")
    projects = document.get("projects") if isinstance(document, dict) else None
    if not isinstance(projects, list):
        raise EnvironmentError_(f"global index has no 'projects' list: {index_path}")
    repos: list[Path] = []
    for entry in projects:
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            repos.append(Path(entry["path"]).expanduser())
    return repos


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Classify the adopted overlay surface as global tier (one authoritative "
            "copy per machine) or project tier (one per repo), by the "
            "repo-invariance test. Read-only: it reports, it never moves anything."
        ),
        epilog=(
            "tiers:\n"
            "  G        global: correct content does not change between repos\n"
            "  P        project: correct content carries a project-dimension value\n"
            "  S        must be split: one file holds both parts\n"
            "  UNKNOWN  referred to a human; never guessed\n"
            "\n"
            "UNKNOWN codes:\n"
            "  declared-global-carries-instance-value  boundary violation or misfiled rule\n"
            "  declared-project-carries-none           possibly still the untouched template\n"
            "  unclassified                            matches no rule; name its owner\n"
            "\n"
            "exit codes:\n"
            "  0  everything classified; with --crosscheck, no divergence either\n"
            "  1  findings to read (unknowns and/or divergence)\n"
            "  2  usage / environment (fail closed)\n"
        ),
    )
    parser.add_argument(
        "--repo",
        type=Path,
        action="append",
        dest="repos",
        metavar="PATH",
        help="repo to classify; repeatable",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="classify every repo named by the global index",
    )
    parser.add_argument(
        "--global-index",
        type=Path,
        default=DEFAULT_GLOBAL_INDEX,
        help=(
            f"global index used by --all (default: {DEFAULT_GLOBAL_INDEX}; the root "
            f"is ${ARBORIST_HOME_ENV} when set to a non-empty value)"
        ),
    )
    parser.add_argument(
        "--tier",
        action="append",
        choices=[TIER_GLOBAL, TIER_PROJECT, TIER_SPLIT, TIER_UNKNOWN],
        dest="tiers",
        help="only report these tiers; repeatable",
    )
    parser.add_argument(
        "--crosscheck",
        action="store_true",
        help=(
            "additionally compare global-tier artifacts across repos and report "
            "divergence (a separate reading from the tier verdict)"
        ),
    )
    parser.add_argument("--json", action="store_true", help="emit one JSON document")
    parser.add_argument(
        "--print-surface",
        action="store_true",
        help="print the manifest and exit 0, reading no repo",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.print_surface:
        for rule in SURFACE:
            print(
                f"{rule.tier:<7} {rule.writer:<8} {rule.basis:<8} "
                f"{'tree' if not rule.walk else 'file'}  {rule.pattern}"
            )
            print(f"          {rule.why}")
        return 0

    repos: list[Path] = []
    if args.all:
        try:
            repos.extend(load_repos_from_index(args.global_index.expanduser()))
        except EnvironmentError_ as exc:
            print(f"environment: {exc}")
            return 2
    for repo in args.repos or []:
        repos.append(repo.expanduser())
    if not repos:
        print("nothing to classify: pass --repo PATH or --all")
        return 2

    seen: set[str] = set()
    ordered: list[Path] = []
    for repo in repos:
        key = str(repo)
        if key not in seen:
            seen.add(key)
            ordered.append(repo)

    home = Path.home()
    artifacts: list[Artifact] = []
    unreachable: list[Path] = []
    for repo in ordered:
        if not repo.is_dir():
            unreachable.append(repo)
            continue
        artifacts.extend(classify_repo(repo, home=home))

    reachable = [repo for repo in ordered if repo not in unreachable]
    divergence = crosscheck(artifacts, reachable) if args.crosscheck else []

    wanted = set(args.tiers) if args.tiers else None
    shown = [a for a in artifacts if wanted is None or a.tier in wanted]

    unknowns = [a for a in artifacts if a.tier == TIER_UNKNOWN]
    counts = {
        tier: sum(1 for a in artifacts if a.tier == tier)
        for tier in (TIER_GLOBAL, TIER_PROJECT, TIER_SPLIT, TIER_UNKNOWN)
    }

    if args.json:
        print(
            json.dumps(
                {
                    "repos": [str(repo) for repo in reachable],
                    "unreachable_repos": [str(repo) for repo in unreachable],
                    "counts": counts,
                    "divergence": divergence,
                    "artifacts": [a.to_json() for a in shown],
                },
                indent=2,
                sort_keys=False,
            )
        )
    else:
        for repo in ordered:
            in_repo = [a for a in shown if a.repo == str(repo)]
            if repo in unreachable:
                print(f"== {repo}\n   unreachable: not a directory")
                continue
            print(f"== {repo}  ({len(in_repo)} shown)")
            for artifact in in_repo:
                print("   " + artifact.render().replace("\n", "\n   "))
        if divergence:
            print("\n--- cross-repo divergence (global-tier artifacts) ---")
            for finding in divergence:
                print(
                    f"{finding['verdict']}: {finding['path']} -- "
                    f"{finding['variants']} distinct content(s) across "
                    f"{finding['present_in']} repo(s), absent from "
                    f"{finding['absent_from']}"
                )
        print(
            "\n"
            + ", ".join(f"{tier}={counts[tier]}" for tier in counts)
            + f"; repos={len(reachable)}"
            + (f", divergent paths={len(divergence)}" if args.crosscheck else "")
        )
        if unknowns:
            print(
                f"{len(unknowns)} artifact(s) referred to a human: rerun with "
                "--tier UNKNOWN to read them alone."
            )

    if unreachable:
        print(f"{len(unreachable)} repo(s) named by the index are unreachable")
    if unknowns or divergence or unreachable:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
