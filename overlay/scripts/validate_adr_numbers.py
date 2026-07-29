#!/usr/bin/env python3
"""Validate the ADR filename namespace: unique numbers + recorded visibility.

Two independent checks run over one decisions directory:

1. **numeric namespace** — every `NNNN-<slug>.md` filename must hold a unique
   four-digit prefix. Grouping is on the *prefix alone*, never the whole
   filename, so `0007-a.md` and `0007-b.md` collide. Unnumbered
   `proposed-<slug>.md` drafts live outside the numeric namespace and can never
   collide with each other or with a numbered ADR.
2. **visibility** — every ADR markdown file must be visible to the git that
   records specs. Both classes are checked (drafts *and* numbered/accepted
   files), which is what makes an accept-time rename covered on both sides of
   the number assignment: `proposed-x.md` is checked before the rename and
   `NNNN-x.md` after it.

Which git records specs is host layout, not something this script may guess, so
`--visibility` is mandatory:

* `machine-local` — specs are recorded only in a side-history harness repo
  (separate git dir, product work tree). Needs `--git-dir`.
* `product-git` — specs are recorded in the product repo's own history.

A missing mode, or a flag combination that names two different gits, exits 2
(fail closed). A missing side-history git dir is likewise a **failure, never a
silent skip** — silently skipping visibility whenever the harness git dir is
absent is exactly the hole that lets brand-new ADR files stay invisible.

Exit codes: 0 valid; 1 validation failure; 2 usage / environment (fail closed).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple, Sequence


# Only an exact four-digit group followed by `-` enters the numeric namespace:
# `12-x.md`, `0012.md`, `00120-x.md` and `proposed-0012-x.md` all stay out.
ADR_FILENAME = re.compile(r"^(?P<prefix>\d{4})-.+\.md$")
PROPOSED_FILENAME = re.compile(r"^proposed-.+\.md$")

VISIBILITY_MODES = ("machine-local", "product-git")

# Default layout is the adopted one: `<repo-root>/.trellis/scripts/<this>.py`.
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
DECISIONS_RELATIVE = Path(".trellis/spec/guides/decisions")
HARNESS_GIT_DIR_NAME = ".harness-vcs"


class VisibilityConfigError(RuntimeError):
    """The visibility mode is missing, ambiguous, or unusable (exit 2)."""


class VisibilityTarget(NamedTuple):
    """Where "is this file visible?" gets asked, once the mode is resolved."""

    mode: str
    git_argv: list[str]
    work_tree: Path
    advice: str


def find_duplicate_prefixes(decisions_dir: Path) -> dict[str, list[Path]]:
    """Return numeric prefixes held by more than one ADR file."""

    grouped: defaultdict[str, list[Path]] = defaultdict(list)
    for path in sorted(decisions_dir.iterdir()):
        if not path.is_file():
            continue
        match = ADR_FILENAME.fullmatch(path.name)
        if match is not None:
            grouped[match.group("prefix")].append(path)

    return {
        prefix: paths
        for prefix, paths in sorted(grouped.items())
        if len(paths) > 1
    }


def count_adr_files(decisions_dir: Path) -> tuple[int, int]:
    """Return (numbered ADR count, unnumbered proposed-draft count)."""

    numbered = 0
    drafts = 0
    for path in sorted(decisions_dir.glob("*.md")):
        if not path.is_file():
            continue
        if ADR_FILENAME.fullmatch(path.name) is not None:
            numbered += 1
        elif PROPOSED_FILENAME.fullmatch(path.name) is not None:
            drafts += 1
    return numbered, drafts


def product_work_tree(repo_root: Path) -> Path:
    """Return the product git work tree containing repo_root, or fail closed."""

    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise VisibilityConfigError(
            f"product-git visibility needs a git work tree at {repo_root}: {detail}"
        )
    return Path(result.stdout.strip())


def resolve_visibility(
    *,
    mode: str | None,
    repo_root: Path,
    git_dir: Path | None,
) -> VisibilityTarget:
    """Turn the declared visibility mode into a concrete git to interrogate.

    Fail closed on a missing mode and on any combination that would leave two
    candidate gits in play; never degrade into "skip the check".
    """

    if mode is None:
        raise VisibilityConfigError(
            "--visibility is required and has no default: pass machine-local "
            "(specs recorded only in the side-history harness repo) or "
            "product-git (specs recorded in the product repo's own history). "
            "Refusing to guess which git records specs."
        )
    if mode not in VISIBILITY_MODES:
        raise VisibilityConfigError(
            f"unknown visibility mode {mode!r}; expected one of "
            f"{', '.join(VISIBILITY_MODES)}"
        )

    if mode == "machine-local":
        harness_git_dir = (
            git_dir if git_dir is not None else repo_root / HARNESS_GIT_DIR_NAME
        )
        if not harness_git_dir.is_dir():
            raise VisibilityConfigError(
                "machine-local visibility needs the side-history git dir, but "
                f"{harness_git_dir} is not a directory. Its absence is a "
                "failure, not a reason to skip the check: skipping is how new "
                "ADR files stay invisible."
            )
        return VisibilityTarget(
            mode="machine-local",
            git_argv=[
                "git",
                f"--git-dir={harness_git_dir}",
                f"--work-tree={repo_root}",
            ],
            work_tree=repo_root,
            advice=(
                f"update {harness_git_dir / 'info' / 'exclude'} with the "
                "documented parent-directory allowlist"
            ),
        )

    if git_dir is not None:
        raise VisibilityConfigError(
            "--git-dir is ambiguous with --visibility product-git: --git-dir "
            "names the side-history git dir used by machine-local mode, so the "
            "pair leaves two candidate gits in play. Pass one or the other."
        )
    return VisibilityTarget(
        mode="product-git",
        git_argv=["git", "-C", str(repo_root)],
        work_tree=product_work_tree(repo_root),
        advice="remove the .gitignore rule that hides the decisions directory",
    )


def find_ignored_adr_files(
    decisions_dir: Path,
    *,
    target: VisibilityTarget,
) -> list[tuple[Path, str]]:
    """Return (ADR file, deciding ignore rule) for every hidden ADR file.

    Covers `proposed-<slug>.md` drafts and numbered/accepted ADRs alike. No
    `--no-index`: a file already tracked by the interrogated git *is* visible,
    which is precisely the question being asked.
    """

    ignored: list[tuple[Path, str]] = []
    work_tree = target.work_tree.resolve()
    for path in sorted(decisions_dir.glob("*.md")):
        if not path.is_file():
            continue
        try:
            relative_path = path.resolve().relative_to(work_tree)
        except ValueError as exc:
            raise VisibilityConfigError(
                f"ADR file is outside the {target.mode} work tree "
                f"{work_tree}: {path}"
            ) from exc

        result = subprocess.run(
            [
                *target.git_argv,
                "check-ignore",
                "-v",
                "--",
                relative_path.as_posix(),
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=work_tree,
        )
        if result.returncode == 0:
            rule = result.stdout.strip().splitlines()[0] if result.stdout.strip() else "?"
            ignored.append((path, rule))
        elif result.returncode != 1:
            detail = result.stderr.strip() or f"exit {result.returncode}"
            raise VisibilityConfigError(
                f"cannot check {target.mode} visibility for "
                f"{relative_path.as_posix()}: {detail}"
            )
    return ignored


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Validate that every four-digit ADR filename prefix is unique and "
            "that every ADR file is visible to the git that records specs. "
            "Unnumbered proposed-<slug>.md drafts are outside the numeric "
            "namespace, but drafts and numbered ADRs are both visibility-checked, "
            "so an accept-time rename is covered before and after numbering."
        ),
        epilog=(
            "visibility modes (no default; a missing or ambiguous mode exits 2):\n"
            "  machine-local  specs recorded only in the side-history harness\n"
            "                 repo; --git-dir must point at an existing git dir\n"
            "  product-git    specs recorded in the product repo's own history;\n"
            "                 --git-dir is rejected as ambiguous here\n"
            "\n"
            "exit codes:\n"
            "  0  numeric prefixes unique and every ADR file visible\n"
            "  1  duplicate prefix, or an ADR file hidden from the recording git\n"
            "  2  usage / environment problem (fail closed, nothing validated)\n"
        ),
    )
    parser.add_argument(
        "--visibility",
        choices=VISIBILITY_MODES,
        default=None,
        help="which git records specs (required; no default)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help=(
            "repository root holding the decisions directory "
            "(default: two levels above this script)"
        ),
    )
    parser.add_argument(
        "--decisions-dir",
        type=Path,
        default=None,
        help=f"ADR directory (default: <repo-root>/{DECISIONS_RELATIVE.as_posix()})",
    )
    parser.add_argument(
        "--git-dir",
        type=Path,
        default=None,
        help=(
            "side-history git dir for machine-local visibility "
            f"(default: <repo-root>/{HARNESS_GIT_DIR_NAME})"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    repo_root = args.repo_root.resolve()
    if not repo_root.is_dir():
        print(f"repository root not found: {repo_root}", file=sys.stderr)
        return 2

    # Resolve the mode before looking at any content: an unresolvable mode must
    # fail closed on its own, not hide behind a content verdict.
    try:
        target = resolve_visibility(
            mode=args.visibility,
            repo_root=repo_root,
            git_dir=args.git_dir,
        )
    except VisibilityConfigError as exc:
        print(f"visibility mode unusable: {exc}", file=sys.stderr)
        return 2

    decisions_dir = (
        args.decisions_dir
        if args.decisions_dir is not None
        else repo_root / DECISIONS_RELATIVE
    )
    if not decisions_dir.is_dir():
        print(f"ADR decisions directory not found: {decisions_dir}", file=sys.stderr)
        return 2

    duplicates = find_duplicate_prefixes(decisions_dir)
    if duplicates:
        for prefix, paths in duplicates.items():
            names = ", ".join(path.name for path in paths)
            print(
                f"duplicate ADR numeric prefix {prefix}: {names}",
                file=sys.stderr,
            )
        return 1

    try:
        hidden = find_ignored_adr_files(decisions_dir, target=target)
    except (OSError, VisibilityConfigError) as exc:
        print(f"cannot validate ADR visibility: {exc}", file=sys.stderr)
        return 2
    if hidden:
        for path, rule in hidden:
            print(
                f"ADR file invisible to {target.mode} git: {path.name} "
                f"(ignored by {rule})",
                file=sys.stderr,
            )
        print(target.advice, file=sys.stderr)
        return 1

    numbered, drafts = count_adr_files(decisions_dir)
    print(
        "ADR numeric prefixes unique and every ADR file visible to "
        f"{target.mode} git: {decisions_dir}"
    )
    print(f"checked {numbered} numbered ADR(s) + {drafts} proposed draft(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
