#!/usr/bin/env python3
"""Install Arborist's brand contract into platform-visible project files."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path


CONTRACT_ID = "ARBORIST-BRAND-COMPAT:v1"
BLOCK_START = "<!-- ARBORIST-BRAND-COMPAT:START -->"
BLOCK_END = "<!-- ARBORIST-BRAND-COMPAT:END -->"
TRELLIS_START = "<!-- TRELLIS:START -->"
TRELLIS_END = "<!-- TRELLIS:END -->"
MANAGED_AGENT_MARKER = f"<!-- {CONTRACT_ID} managed Claude agent -->"

PROJECT_BLOCK = Path("overlay/project-instructions/brand-compat.md")
WORKFLOW_BLOCK = Path("overlay/workflow-phase-index-brand-compat.md")
CLAUDE_AGENT_DIR = Path("overlay/platform-templates/claude/agents")
CLAUDE_AGENT_NAMES = ("trellis-implement-full.md", "trellis-explore.md")


class InstallError(RuntimeError):
    """Raised when installation cannot preserve the target contract safely."""


def read_required(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise InstallError(f"required file is missing: {path}") from exc


def managed_block(source: str) -> str:
    return f"{BLOCK_START}\n{source.strip()}\n{BLOCK_END}"


def render_source(source: str, target_repo: Path) -> str:
    return source.replace("<REPO_ROOT>", str(target_repo.resolve()))


def remove_managed_block(text: str, path: Path) -> str:
    start_count = text.count(BLOCK_START)
    end_count = text.count(BLOCK_END)
    if start_count != end_count:
        raise InstallError(f"unbalanced brand-compat markers in {path}")
    if start_count > 1:
        raise InstallError(f"multiple brand-compat blocks in {path}")
    if not start_count:
        return text
    pattern = re.compile(
        rf"[ \t]*{re.escape(BLOCK_START)}.*?{re.escape(BLOCK_END)}[ \t]*\n?",
        flags=re.DOTALL,
    )
    return pattern.sub("", text, count=1)


def install_agents_text(current: str, block_source: str, path: Path) -> str:
    clean = remove_managed_block(current, path).rstrip()
    block = managed_block(block_source)

    start = clean.find(TRELLIS_START)
    end = clean.find(TRELLIS_END)
    if (start == -1) != (end == -1) or (start != -1 and end < start):
        raise InstallError(f"unbalanced Trellis markers in {path}")

    if end != -1:
        insertion = end + len(TRELLIS_END)
        before = clean[:insertion].rstrip()
        after = clean[insertion:].strip()
        pieces = [before, block]
        if after:
            pieces.append(after)
        result = "\n\n".join(pieces)
    else:
        result = "\n\n".join(part for part in (clean, block) if part)

    trellis_start = result.find(TRELLIS_START)
    trellis_end = result.find(TRELLIS_END)
    block_pos = result.find(BLOCK_START)
    if trellis_start != -1 and trellis_start < block_pos < trellis_end:
        raise InstallError(f"brand block would be inside the Trellis block in {path}")
    return result + "\n"


def install_workflow_text(current: str, block_source: str, path: Path) -> str:
    clean = remove_managed_block(current, path)
    phase_index = re.search(r"(?m)^## Phase Index(?:[^\n]*)\n", clean)
    phase_one = re.search(r"(?m)^## Phase 1(?::|\s|$)", clean)
    if phase_index is None or phase_one is None or phase_one.start() <= phase_index.end():
        raise InstallError(
            f"{path} must contain Phase Index before '## Phase 1' "
            "so the Claude-visible block has a safe insertion point"
        )

    block = managed_block(block_source)
    insertion = phase_index.end()
    before = clean[:insertion].rstrip()
    after = clean[insertion:].lstrip("\n")
    result = f"{before}\n\n{block}\n\n{after}"

    block_start = result.find(BLOCK_START)
    phase_one_start = re.search(r"(?m)^## Phase 1(?::|\s|$)", result)
    if phase_one_start is None or block_start >= phase_one_start.start():
        raise InstallError(f"brand block would be outside Phase Index in {path}")
    return result.rstrip() + "\n"


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if path.exists() else None
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        if mode is not None:
            os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def desired_files(source_tree: Path, target_repo: Path) -> dict[Path, str]:
    project_source = read_required(source_tree / PROJECT_BLOCK)
    workflow_source = read_required(source_tree / WORKFLOW_BLOCK)
    for source_path, content in (
        (source_tree / PROJECT_BLOCK, project_source),
        (source_tree / WORKFLOW_BLOCK, workflow_source),
    ):
        if CONTRACT_ID not in content:
            raise InstallError(f"{source_path} does not declare {CONTRACT_ID}")
    project_source = render_source(project_source, target_repo)
    workflow_source = render_source(workflow_source, target_repo)

    agents_path = target_repo / "AGENTS.md"
    workflow_path = target_repo / ".trellis/workflow.md"
    current_agents = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    current_workflow = read_required(workflow_path)

    desired = {
        agents_path: install_agents_text(current_agents, project_source, agents_path),
        workflow_path: install_workflow_text(
            current_workflow, workflow_source, workflow_path
        ),
    }

    target_agent_dir = target_repo / ".claude/agents"
    for name in CLAUDE_AGENT_NAMES:
        source_path = source_tree / CLAUDE_AGENT_DIR / name
        source_content = read_required(source_path)
        if MANAGED_AGENT_MARKER not in source_content:
            raise InstallError(f"managed marker is missing from {source_path}")
        target_path = target_agent_dir / name
        if target_path.exists():
            current = target_path.read_text(encoding="utf-8")
            if current != source_content and MANAGED_AGENT_MARKER not in current:
                raise InstallError(
                    f"refusing to overwrite user-owned Claude agent: {target_path}"
                )
        desired[target_path] = source_content
    return desired


def run(source_tree: Path, target_repo: Path, check: bool) -> int:
    source_tree = source_tree.resolve()
    target_repo = target_repo.resolve()
    if not target_repo.is_dir():
        raise InstallError(f"target repository is not a directory: {target_repo}")

    desired = desired_files(source_tree, target_repo)
    changed = [
        path
        for path, content in desired.items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]
    if check:
        if changed:
            for path in changed:
                print(f"OUTDATED: {path}", file=sys.stderr)
            return 1
        print(f"OK: {CONTRACT_ID} is installed in {target_repo}")
        return 0

    for path in changed:
        write_atomic(path, desired[path])
        print(f"installed: {path}")
    if not changed:
        print(f"unchanged: {CONTRACT_ID} is already installed in {target_repo}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target_path",
        nargs="?",
        type=Path,
        help="target repository (defaults to the current directory)",
    )
    parser.add_argument(
        "--source-tree",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Arborist source tree containing overlay/",
    )
    parser.add_argument(
        "--target-repo",
        "--target",
        dest="target_repo",
        type=Path,
        help="target repository (alias: --target)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift without writing files",
    )
    args = parser.parse_args(argv)
    if args.target_path is not None and args.target_repo is not None:
        parser.error("choose either positional target_path or --target-repo")
    args.target_repo = args.target_repo or args.target_path or Path.cwd()
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args.source_tree, args.target_repo, args.check)
    except InstallError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
