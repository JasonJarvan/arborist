#!/usr/bin/env python3
"""Regression tests for scripts/relocate_arborist_state.py.

Everything runs against a throwaway fixture tree under a temporary directory:
the helper is invoked as a subprocess with an explicit ``--global-index``, so no
real project, index, or chat store is ever reachable from these tests.

Run:

    python3 -m unittest discover -s skills/arborist-relocate-project/tests -v
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "relocate_arborist_state.py"
SESSION_ID = "session-fixture-0001"
AGENT_NAMES = ("gardener", "rootorc")


def claude_encode(path: str) -> str:
    return re.sub(r"[:\\/_]", "-", path.rstrip("/"))


def short_id(path: str) -> str:
    return hashlib.sha256(path.encode()).hexdigest()[:12]


@dataclass
class Fixture:
    root: Path
    project: Path
    old: str
    index: Path
    claude_projects: Path
    main_tree: Path

    @property
    def new(self) -> str:
        return str(self.project)

    @property
    def host_config(self) -> Path:
        return self.project / ".trellis" / "host-config.yaml"

    @property
    def harness(self) -> Path:
        return self.project / ".harness-vcs"

    def leaf(self, agent: str, name: str) -> Path:
        return self.project / ".arborist" / "agents" / agent / name

    def backups(self) -> Path:
        return self.index.parent / "backups"


def build_fixture(
    root: Path,
    old_name: str = "Arborist",
    new_dir: str = "Arborist-main",
    *,
    valid_harness: bool = True,
    agents_md_symlink: bool = False,
    relocated_session: bool = True,
) -> Fixture:
    """Create an isolated post-move project root plus an isolated global index."""
    project = root / new_dir
    old = str(root / old_name)
    home = root / "home"
    claude_projects = home / ".claude" / "projects"
    main_tree = root / "main-tree"
    old_id = short_id(old)

    for agent in AGENT_NAMES:
        (project / ".arborist" / "agents" / agent).mkdir(parents=True)
    (project / ".trellis").mkdir(parents=True)
    main_tree.mkdir(parents=True)
    (home / ".arborist").mkdir(parents=True)

    old_session_dir = claude_projects / claude_encode(old)
    old_session_dir.mkdir(parents=True)
    (old_session_dir / f"{SESSION_ID}.jsonl").write_text("{}\n", encoding="utf-8")
    if relocated_session:
        # Pretend the chat-store relocation already ran.
        new_session_dir = claude_projects / claude_encode(str(project))
        new_session_dir.mkdir(parents=True)
        (new_session_dir / f"{SESSION_ID}.jsonl").write_text("{}\n", encoding="utf-8")

    for agent in AGENT_NAMES:
        spec = {
            "name": agent,
            "role": agent,
            "brand": "claude-code",
            "description": f"L4 orchestrator for {old_name} work; {old_name}ary prose stays",
            "task": f"completed {old}/.trellis/tasks/archive/x",
            "project": {"path": old, "project_id": old_id},
        }
        (project / ".arborist" / "agents" / agent / "spec.json").write_text(
            json.dumps(spec, indent=2) + "\n", encoding="utf-8"
        )
        runtime = {
            "session_id": SESSION_ID,
            "session_file": str(old_session_dir / f"{SESSION_ID}.jsonl"),
            "state": "active",
            "generation": 1,
            "pane_ref": {"session": "work", "window": "2", "pane": "%17"},
        }
        (project / ".arborist" / "agents" / agent / "runtime.json").write_text(
            json.dumps(runtime, indent=2) + "\n", encoding="utf-8"
        )

    (project / ".trellis" / "host-config.yaml").write_text(
        f"project: {old_name}\nrepo_root: {old}\nbrand: claude-code\nnote: see {old}/AGENTS.md\n",
        encoding="utf-8",
    )
    (project / ".trellis" / "workflow.md").write_text(
        f"# workflow\n\nAbsolute: {old}/.trellis/workflow.md\n", encoding="utf-8"
    )
    agents_md_text = f"# AGENTS\n\nRepo root: {old}\n\nRun {old}/hgit status\n"
    if agents_md_symlink:
        # Mirrors the worktree discipline: the worktree copy is a symlink back
        # into the tree that owns the file.
        target = main_tree / "AGENTS.md"
        target.write_text(agents_md_text, encoding="utf-8")
        (project / "AGENTS.md").symlink_to(target)
    else:
        (project / "AGENTS.md").write_text(agents_md_text, encoding="utf-8")

    harness = project / ".harness-vcs"
    if valid_harness:
        subprocess.run(["git", "init", "--quiet", "--bare", str(harness)], check=True)
        subprocess.run(
            ["git", f"--git-dir={harness}", "config", "core.bare", "false"], check=True
        )
        subprocess.run(
            ["git", f"--git-dir={harness}", "config", "core.worktree", old], check=True
        )
    else:
        harness.mkdir()
        (harness / "config").write_text(
            f"[core]\n\trepositoryformatversion = 0\n\tbare = false\n\tworktree = {old}\n",
            encoding="utf-8",
        )

    index = home / ".arborist" / "index.json"
    index.write_text(
        json.dumps(
            {
                "projects": [
                    {"project_id": old_id, "path": old, "name": old_name, "agents": []},
                    {
                        "project_id": "deadbeef0001",
                        "path": str(root / "unrelated"),
                        "name": "unrelated",
                        "agents": [],
                    },
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return Fixture(root, project, old, index, claude_projects, main_tree)


def snapshot(*paths: Path) -> dict[str, str]:
    """md5/symlink-target snapshot used to prove "not one byte changed"."""
    state: dict[str, str] = {}

    def record(path: Path, key: str) -> None:
        if path.is_symlink():
            state[key] = f"symlink:{os.readlink(path)}"
        else:
            state[key] = "md5:" + hashlib.md5(path.read_bytes()).hexdigest()

    for base in paths:
        if base.is_file():
            record(base, str(base))
            continue
        for current, dirs, files in os.walk(base, followlinks=False):
            for name in sorted(dirs):
                candidate = Path(current) / name
                if candidate.is_symlink():
                    state[str(candidate)] = f"symlink:{os.readlink(candidate)}"
            dirs[:] = sorted(name for name in dirs if not (Path(current) / name).is_symlink())
            for name in sorted(files):
                candidate = Path(current) / name
                record(candidate, str(candidate))
    return state


@unittest.skipUnless(shutil.which("git"), "git is required to build the harness fixture")
class RelocateStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="arborist-relocate-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_helper(self, fixture: Fixture, *extra: str, old: str | None = None) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(SCRIPT),
            "--old-path",
            old if old is not None else fixture.old,
            "--new-path",
            fixture.new,
            "--global-index",
            str(fixture.index),
            *extra,
        ]
        return subprocess.run(command, capture_output=True, text=True)

    def full_snapshot(self, fixture: Fixture) -> dict[str, str]:
        return snapshot(fixture.project, fixture.index, fixture.main_tree)

    def read(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def worktree(self, fixture: Fixture) -> str:
        result = subprocess.run(
            ["git", f"--git-dir={fixture.harness}", "config", "--get", "core.worktree"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    # B1 --------------------------------------------------------------
    def test_apply_twice_is_idempotent(self) -> None:
        """<name> -> <name>-main applied twice must not yield <name>-main-main."""
        fixture = build_fixture(self.tmp)
        first = self.run_helper(fixture, "--allow-nested-rename", "--apply")
        self.assertEqual(first.returncode, 0, first.stderr)
        after_first = self.full_snapshot(fixture)

        second = self.run_helper(fixture, "--allow-nested-rename", "--apply")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("no changes", second.stdout)
        self.assertEqual(after_first, self.full_snapshot(fixture))

        for path in (
            fixture.project / "AGENTS.md",
            fixture.project / ".trellis" / "workflow.md",
            fixture.host_config,
            fixture.leaf("rootorc", "spec.json"),
            fixture.leaf("rootorc", "runtime.json"),
            fixture.index,
        ):
            self.assertNotIn("-main-main", self.read(path), f"nested corruption in {path}")

    def test_nested_rename_refused_without_flag(self) -> None:
        fixture = build_fixture(self.tmp)
        before = self.full_snapshot(fixture)
        result = self.run_helper(fixture, "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--allow-nested-rename", result.stderr)
        self.assertEqual(before, self.full_snapshot(fixture))
        self.assertFalse(fixture.backups().exists())

    def test_name_substitution_is_word_anchored(self) -> None:
        """A project name that is a prefix of ordinary prose must not be rewritten."""
        fixture = build_fixture(self.tmp, old_name="api", new_dir="svc")
        result = self.run_helper(fixture, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        description = json.loads(self.read(fixture.leaf("rootorc", "spec.json")))["description"]
        self.assertEqual(description, "L4 orchestrator for svc work; apiary prose stays")

    # B2 --------------------------------------------------------------
    def test_symlinked_file_is_written_through_to_its_target(self) -> None:
        fixture = build_fixture(self.tmp, agents_md_symlink=True)
        target = fixture.main_tree / "AGENTS.md"
        result = self.run_helper(fixture, "--allow-nested-rename", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)

        agents_md = fixture.project / "AGENTS.md"
        self.assertTrue(agents_md.is_symlink(), "symlink was replaced by a regular file")
        self.assertEqual(Path(os.path.realpath(agents_md)), target)
        self.assertIn(fixture.new, self.read(target))
        self.assertNotIn(f"{fixture.old}\n", self.read(target))

    def test_symlinked_arborist_dir_is_refused(self) -> None:
        fixture = build_fixture(self.tmp)
        real = fixture.root / "real-arborist"
        shutil.move(str(fixture.project / ".arborist"), str(real))
        (fixture.project / ".arborist").symlink_to(real)

        result = self.run_helper(fixture, "--allow-nested-rename", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr)
        spec = json.loads(self.read(real / "agents" / "rootorc" / "spec.json"))
        self.assertEqual(spec["project"]["path"], fixture.old)
        self.assertFalse(fixture.backups().exists())

    # B3 --------------------------------------------------------------
    def test_unusable_harness_dir_fails_preflight_without_writing(self) -> None:
        fixture = build_fixture(self.tmp, valid_harness=False)
        before = self.full_snapshot(fixture)
        result = self.run_helper(fixture, "--allow-nested-rename", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("preflight", result.stderr)
        self.assertEqual(before, self.full_snapshot(fixture))
        self.assertFalse(fixture.backups().exists())

    def test_missing_relocated_session_fails_preflight_without_writing(self) -> None:
        fixture = build_fixture(self.tmp, relocated_session=False)
        before = self.full_snapshot(fixture)
        result = self.run_helper(fixture, "--allow-nested-rename", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cc-relocate-project", result.stderr)
        self.assertEqual(before, self.full_snapshot(fixture))
        self.assertFalse(fixture.backups().exists())

    def test_failed_write_rolls_back_earlier_writes(self) -> None:
        """A mid-apply failure must leave the tree exactly as it was found."""
        fixture = build_fixture(self.tmp, old_name="api", new_dir="svc")
        before = self.full_snapshot(fixture)
        trellis = fixture.project / ".trellis"
        mode = trellis.stat().st_mode
        os.chmod(trellis, 0o500)  # readable/traversable, not writable
        self.addCleanup(os.chmod, trellis, mode)

        result = self.run_helper(fixture, "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rolled back", result.stderr)
        self.assertEqual(before, self.full_snapshot(fixture))
        self.assertEqual(self.worktree(fixture), fixture.old)

    # B4 --------------------------------------------------------------
    def test_wrong_old_path_is_refused_and_host_config_untouched(self) -> None:
        fixture = build_fixture(self.tmp)
        before = self.full_snapshot(fixture)
        result = self.run_helper(fixture, "--apply", old=str(fixture.root / "some-other-project"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no evidence", result.stderr)
        self.assertIn(f"repo_root: {fixture.old}", self.read(fixture.host_config))
        self.assertEqual(before, self.full_snapshot(fixture))
        self.assertFalse(fixture.backups().exists())

    # m2 --------------------------------------------------------------
    def test_identical_old_and_new_is_refused(self) -> None:
        fixture = build_fixture(self.tmp)
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--old-path",
                fixture.new,
                "--new-path",
                fixture.new,
                "--global-index",
                str(fixture.index),
                "--apply",
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("identical", result.stderr)

    # dry-run ---------------------------------------------------------
    def test_dry_run_has_no_side_effects(self) -> None:
        fixture = build_fixture(self.tmp)
        before = self.full_snapshot(fixture)
        for _ in range(3):
            result = self.run_helper(fixture, "--allow-nested-rename")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("DRY-RUN", result.stdout)
            self.assertEqual(before, self.full_snapshot(fixture))
        self.assertFalse(fixture.backups().exists())
        self.assertEqual(self.worktree(fixture), fixture.old)

    def test_dry_run_and_apply_report_the_same_changes(self) -> None:
        fixture = build_fixture(self.tmp)
        dry = self.run_helper(fixture, "--allow-nested-rename")
        wet = self.run_helper(fixture, "--allow-nested-rename", "--apply")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertEqual(wet.returncode, 0, wet.stderr)
        planned = [line for line in dry.stdout.splitlines() if line.startswith("  update ")]
        applied = [line for line in wet.stdout.splitlines() if line.startswith("  update ")]
        self.assertEqual(planned, applied)

    # happy path ------------------------------------------------------
    def test_apply_updates_every_layer(self) -> None:
        fixture = build_fixture(self.tmp, old_name="api", new_dir="svc")
        result = self.run_helper(fixture, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        new_id = json.loads(self.read(fixture.leaf("rootorc", "spec.json")))["project"][
            "project_id"
        ]

        for agent in AGENT_NAMES:
            spec = json.loads(self.read(fixture.leaf(agent, "spec.json")))
            self.assertEqual(spec["project"]["path"], fixture.new)
            self.assertEqual(spec["project"]["project_id"], new_id)
            runtime = json.loads(self.read(fixture.leaf(agent, "runtime.json")))
            self.assertEqual(
                runtime["session_file"],
                str(fixture.claude_projects / claude_encode(fixture.new) / f"{SESSION_ID}.jsonl"),
            )
            self.assertTrue(Path(runtime["session_file"]).is_file())
            self.assertEqual(runtime["pane_ref"]["session"], "work")

        host = self.read(fixture.host_config)
        self.assertIn("project: svc", host)
        self.assertIn(f"repo_root: {fixture.new}", host)
        self.assertNotIn(fixture.old, host)
        self.assertNotIn(fixture.old, self.read(fixture.project / "AGENTS.md"))
        self.assertNotIn(fixture.old, self.read(fixture.project / ".trellis" / "workflow.md"))

        index = json.loads(self.read(fixture.index))
        relocated = [entry for entry in index["projects"] if entry["name"] == "svc"]
        self.assertEqual(len(relocated), 1)
        self.assertEqual(relocated[0]["path"], fixture.new)
        self.assertEqual(relocated[0]["project_id"], new_id)
        unrelated = [entry for entry in index["projects"] if entry["name"] == "unrelated"]
        self.assertEqual(len(unrelated), 1)
        self.assertEqual(unrelated[0]["project_id"], "deadbeef0001")

        self.assertEqual(self.worktree(fixture), fixture.new)

    def test_apply_backs_up_every_file_it_rewrites(self) -> None:
        fixture = build_fixture(self.tmp, old_name="api", new_dir="svc")
        result = self.run_helper(fixture, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        backup_dirs = sorted(fixture.backups().iterdir())
        self.assertEqual(len(backup_dirs), 1)
        backup = backup_dirs[0]
        saved = {
            str(path.relative_to(backup)) for path in backup.rglob("*") if path.is_file()
        }
        self.assertIn("index.json", saved)
        for relative in (
            "AGENTS.md",
            ".trellis/workflow.md",
            ".trellis/host-config.yaml",
            ".arborist/agents/rootorc/spec.json",
            ".arborist/agents/rootorc/runtime.json",
        ):
            self.assertIn(f"project/{relative}", saved)
        self.assertIn(fixture.old, self.read(backup / "project" / "AGENTS.md"))


if __name__ == "__main__":
    unittest.main()
