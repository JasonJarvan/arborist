#!/usr/bin/env python3
"""Prove that named durable harness files sit in clean, committed side history.

For each **exact path** from a landing manifest the validator proves three
things against the side-history git (separate git dir, product work tree):

* the path exists on disk and is not ignored by that git;
* its worktree state is clean (nothing uncommitted, nothing untracked);
* it has at least one commit, reported as `path@commit` evidence.

Remote claims are deliberately split into two flags of *different* strength,
because "a remote is configured" and "this commit reached a remote" are
different facts and only the second one is cross-machine persistence:

* ``--require-remote-configured`` — the side history has at least one
  configured remote. Proves configuration only. It does **not** prove any
  commit was pushed, and the output says so.
* ``--require-remote-reachable`` — every reported evidence commit is contained
  in a remote-tracking ref (optionally scoped with ``--remote``). Strictly
  stronger, and still honest about its own bound: remote-tracking refs are only
  as fresh as the last fetch, so this proves "contained in a remote-tracking ref
  as of the last fetch", not "present on the remote right now".

There is no ``--require-remote``: the unqualified spelling reads as the strong
claim while the cheap check only supports the weak one.

Exit codes: 0 valid; 1 evidence failure; 2 usage / environment (fail closed).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, Sequence


# Default layout is the adopted one: `<repo-root>/.trellis/scripts/<this>.py`.
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_GIT_DIR_NAME = ".harness-vcs"
REMOTE_REF_NAMESPACE = "refs/remotes"


class Evidence(NamedTuple):
    path: str
    commit: str

    def render(self) -> str:
        return f"{self.path}@{self.commit}"


def run_git(
    *,
    git_dir: Path,
    repo_root: Path,
    args: Sequence[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            f"--git-dir={git_dir}",
            f"--work-tree={repo_root}",
            *args,
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )


def relative_durable_path(raw_path: Path, repo_root: Path) -> tuple[Path, Path]:
    absolute_path = raw_path if raw_path.is_absolute() else repo_root / raw_path
    resolved_root = repo_root.resolve()
    resolved_path = absolute_path.resolve()
    try:
        relative_path = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"path is outside harness work tree: {raw_path}") from exc
    return resolved_path, relative_path


def configured_remotes(
    *,
    git_dir: Path,
    repo_root: Path,
) -> tuple[list[str], str | None]:
    """Return (configured remote names, error)."""

    result = run_git(git_dir=git_dir, repo_root=repo_root, args=["remote"])
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        return [], f"cannot read hgit remotes: {detail}"
    return [line.strip() for line in result.stdout.splitlines() if line.strip()], None


def remote_configured_evidence(
    *,
    git_dir: Path,
    repo_root: Path,
) -> tuple[bool, str]:
    """Weak check: is any remote configured at all?

    Proves configuration and nothing more — not that a commit was pushed, not
    that anything is reachable from the remote. The caller must not describe
    this as cross-machine persistence.
    """

    remotes, error = configured_remotes(git_dir=git_dir, repo_root=repo_root)
    if error is not None:
        return False, error
    if not remotes:
        return False, "hgit has no configured remote; persistence terminates on this machine"
    return True, (
        f"remote configured: {', '.join(remotes)} "
        "(proves configuration only, not that any commit reached a remote)"
    )


def remote_tracking_refs_containing(
    commit: str,
    *,
    git_dir: Path,
    repo_root: Path,
    remote: str | None,
) -> tuple[list[str], str | None]:
    """Return (remote-tracking refs containing commit, error).

    `--contains=` (not a space-separated value) is required: for-each-ref takes
    an optional value there, so `--contains <sha>` risks being read as a ref
    pattern instead. `*/HEAD` symrefs are dropped as they only mirror a branch.
    """

    scope = f"{REMOTE_REF_NAMESPACE}/{remote}/" if remote else f"{REMOTE_REF_NAMESPACE}/"
    result = run_git(
        git_dir=git_dir,
        repo_root=repo_root,
        args=[
            "for-each-ref",
            f"--contains={commit}",
            "--format=%(refname)",
            scope,
        ],
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        return [], f"cannot read remote-tracking refs: {detail}"
    refs = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.strip().endswith("/HEAD")
    ]
    return refs, None


def remote_tracking_scope_exists(
    *,
    git_dir: Path,
    repo_root: Path,
    remote: str | None,
) -> bool:
    """Is there any remote-tracking ref in scope (i.e. has anything been fetched)?

    Separated from the per-commit containment check so that "nothing was ever
    fetched" reports as its own actionable failure instead of looking like
    "this particular commit is local-only".
    """

    scope = f"{REMOTE_REF_NAMESPACE}/{remote}/" if remote else f"{REMOTE_REF_NAMESPACE}/"
    result = run_git(
        git_dir=git_dir,
        repo_root=repo_root,
        args=["for-each-ref", "--format=%(refname)", scope],
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def persistence_evidence(
    raw_path: Path,
    *,
    git_dir: Path,
    repo_root: Path,
) -> tuple[Evidence | None, str | None]:
    """Return (path@commit evidence, error) for one durable harness file."""

    try:
        resolved_path, relative_path = relative_durable_path(raw_path, repo_root)
    except ValueError as exc:
        return None, str(exc)

    display_path = relative_path.as_posix()
    if not resolved_path.is_file():
        return None, f"{display_path}: durable harness file does not exist"

    ignored = run_git(
        git_dir=git_dir,
        repo_root=repo_root,
        args=["check-ignore", "--quiet", "--", display_path],
    )
    if ignored.returncode == 0:
        return None, f"{display_path}: ignored by hgit"
    if ignored.returncode != 1:
        detail = ignored.stderr.strip() or f"exit {ignored.returncode}"
        return None, f"{display_path}: cannot check hgit ignore state: {detail}"

    status = run_git(
        git_dir=git_dir,
        repo_root=repo_root,
        args=[
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            display_path,
        ],
    )
    if status.returncode != 0:
        detail = status.stderr.strip() or f"exit {status.returncode}"
        return None, f"{display_path}: cannot read hgit status: {detail}"
    if status.stdout.strip():
        return (
            None,
            f"{display_path}: uncommitted hgit state {status.stdout.strip()!r}",
        )

    history = run_git(
        git_dir=git_dir,
        repo_root=repo_root,
        args=["log", "-1", "--format=%H", "--", display_path],
    )
    if history.returncode != 0:
        detail = history.stderr.strip() or f"exit {history.returncode}"
        return None, f"{display_path}: cannot read hgit history: {detail}"
    commit = history.stdout.strip()
    if not commit:
        return None, f"{display_path}: no committed hgit history"

    return Evidence(path=display_path, commit=commit), None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Validate that explicitly selected durable harness files are "
            "visible, clean, and backed by hgit commits."
        ),
        epilog=(
            "remote strength (pick by what you actually need to prove):\n"
            "  --require-remote-configured  a remote exists in hgit config.\n"
            "                               Proves configuration only; it does\n"
            "                               NOT prove any commit was pushed.\n"
            "  --require-remote-reachable   every evidence commit is contained in\n"
            "                               a remote-tracking ref (as of the last\n"
            "                               fetch). Strictly stronger.\n"
            "  There is no --require-remote: the unqualified name reads as the\n"
            "  strong claim while the cheap check only supports the weak one.\n"
            "\n"
            "exit codes:\n"
            "  0  every path is visible, clean, committed (plus remote checks)\n"
            "  1  an evidence check failed\n"
            "  2  usage / environment problem (fail closed, nothing validated)\n"
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="harness work tree (default: two levels above this script)",
    )
    parser.add_argument(
        "--git-dir",
        type=Path,
        default=None,
        help=f"harness git dir (default: <repo-root>/{HARNESS_GIT_DIR_NAME})",
    )
    parser.add_argument(
        "--require-remote-configured",
        action="store_true",
        help="fail unless hgit has a configured remote (configuration only)",
    )
    parser.add_argument(
        "--require-remote-reachable",
        action="store_true",
        help=(
            "fail unless every evidence commit is contained in a "
            "remote-tracking ref (as of the last fetch)"
        ),
    )
    parser.add_argument(
        "--remote",
        default=None,
        help=(
            "scope --require-remote-reachable to one remote's tracking refs "
            "(default: any remote)"
        ),
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="exact durable harness paths from the landing manifest",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    git_dir = (
        args.git_dir.resolve()
        if args.git_dir is not None
        else repo_root / HARNESS_GIT_DIR_NAME
    )
    if not repo_root.is_dir():
        print(f"harness work tree not found: {repo_root}", file=sys.stderr)
        return 2
    if not git_dir.is_dir():
        print(f"harness git dir not found: {git_dir}", file=sys.stderr)
        return 2
    if args.remote is not None and not args.require_remote_reachable:
        print(
            "--remote only scopes --require-remote-reachable; on its own it "
            "proves nothing. Pass --require-remote-reachable or drop --remote.",
            file=sys.stderr,
        )
        return 2

    notes: list[str] = []
    # Both remote flags presuppose a configured remote; the strong one adds
    # reachability on top, so the weak check runs for either.
    if args.require_remote_configured or args.require_remote_reachable:
        has_remote, detail = remote_configured_evidence(
            git_dir=git_dir,
            repo_root=repo_root,
        )
        if not has_remote:
            print(detail, file=sys.stderr)
            return 1
        notes.append(detail)
        if args.remote is not None:
            remotes, error = configured_remotes(git_dir=git_dir, repo_root=repo_root)
            if error is not None:
                print(error, file=sys.stderr)
                return 2
            if args.remote not in remotes:
                print(
                    f"--remote {args.remote} is not a configured hgit remote "
                    f"({', '.join(remotes)})",
                    file=sys.stderr,
                )
                return 2

    evidence: list[Evidence] = []
    errors: list[str] = []
    for path in args.paths:
        item, error = persistence_evidence(
            path,
            git_dir=git_dir,
            repo_root=repo_root,
        )
        if error is not None:
            errors.append(error)
        elif item is not None:
            evidence.append(item)

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    if args.require_remote_reachable:
        scope = (
            f"{REMOTE_REF_NAMESPACE}/{args.remote}/"
            if args.remote
            else f"{REMOTE_REF_NAMESPACE}/"
        )
        if not remote_tracking_scope_exists(
            git_dir=git_dir,
            repo_root=repo_root,
            remote=args.remote,
        ):
            print(
                f"no remote-tracking ref under {scope}: nothing has been "
                "fetched or pushed, so reachability cannot be proven "
                "(git fetch first)",
                file=sys.stderr,
            )
            return 1
        unreachable: list[str] = []
        for item in evidence:
            refs, error = remote_tracking_refs_containing(
                item.commit,
                git_dir=git_dir,
                repo_root=repo_root,
                remote=args.remote,
            )
            if error is not None:
                print(f"{item.path}: {error}", file=sys.stderr)
                return 2
            if not refs:
                unreachable.append(
                    f"{item.render()}: not contained in any remote-tracking ref "
                    f"under {scope}; the commit is local-only or the "
                    "remote-tracking refs are stale (git fetch first)"
                )
            else:
                notes.append(
                    f"remote reachable: {item.render()} contained in "
                    f"{', '.join(refs)} (as of the last fetch)"
                )
        if unreachable:
            for line in unreachable:
                print(line, file=sys.stderr)
            return 1

    print(f"harness persistence valid: {len(evidence)} path(s)")
    for item in evidence:
        print(item.render())
    for note in notes:
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
