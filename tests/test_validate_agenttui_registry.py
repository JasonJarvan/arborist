"""Tests for the AgentTUI registry consistency validator.

Every fixture is built from scratch in a tempdir: the suite must never read the
host's real `~/.arborist/` registry, both because that would make results
machine-dependent and because instance values (real paths, real session ids)
must not enter the repo.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_validator_module():
    """Load the overlay validator by path, without a package import."""
    module_path = ROOT / "overlay/scripts/validate_agenttui_registry.py"
    module_name = "validate_agenttui_registry"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None, module_path
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_validator_module()


def run_main(*argv: str) -> tuple[int, str]:
    """Run the validator's main and capture stdout (all output goes there)."""
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        result = VALIDATOR.main(list(argv))
    return result, stdout.getvalue()


def project_id_for(path: Path) -> str:
    normalized = str(Path(path).resolve())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


class RegistryFixture:
    """A throwaway global index plus a set of throwaway project repos."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.index_path = base / "global" / "index.json"
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._projects: dict[str, dict[str, Any]] = {}

    def add_project(self, name: str, *, create_dir: bool = True) -> Path:
        root = self.base / name
        if create_dir:
            (root / ".arborist" / "agents").mkdir(parents=True, exist_ok=True)
        self._projects[name] = {
            "project_id": project_id_for(root),
            "path": str(root),
            "name": name,
            "agents": [],
        }
        return root

    def project_root(self, name: str) -> Path:
        return self.base / name

    def write_leaf(
        self,
        project: str,
        agent: str,
        *,
        session_id: str,
        role: str = "impler",
        brand: str = "claude-code",
        state: str = "active",
        lineage: int | None = None,
        pane_ref: dict[str, str] | None = None,
        last_seen: str | None = "2000-01-01T00:00:00+00:00",
        declared_project_path: Path | None = None,
        declared_project_id: str | None = None,
        omit_runtime: bool = False,
        broken_spec_json: bool = False,
    ) -> Path:
        root = self.project_root(project)
        directory = root / ".arborist" / "agents" / agent
        directory.mkdir(parents=True, exist_ok=True)

        declared_path = declared_project_path or root
        spec: dict[str, Any] = {
            "name": agent,
            "role": role,
            "brand": brand,
            "description": "fixture agent",
            "task": "fixture task",
            "project": {
                "path": str(declared_path),
                "project_id": declared_project_id or project_id_for(declared_path),
            },
            "created": "2000-01-01T00:00:00+00:00",
        }
        if lineage is not None:
            spec["lineage"] = lineage
        if broken_spec_json:
            (directory / "spec.json").write_text("{not json", encoding="utf-8")
        else:
            (directory / "spec.json").write_text(
                json.dumps(spec), encoding="utf-8"
            )

        if not omit_runtime:
            runtime: dict[str, Any] = {
                "session_id": session_id,
                "session_file": str(self.base / "transcripts" / f"{session_id}.jsonl"),
                "state": state,
                "generation": 1,
                "pane_ref": pane_ref,
            }
            if last_seen is not None:
                runtime["last_seen"] = last_seen
            (directory / "runtime.json").write_text(
                json.dumps(runtime), encoding="utf-8"
            )
        return directory

    def add_summary(
        self,
        project: str,
        agent: str,
        *,
        session_id: str,
        role: str = "impler",
        brand: str = "claude-code",
        state: str = "active",
        lineage: int | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "name": agent,
            "role": role,
            "brand": brand,
            "state": state,
            "session_id": session_id,
        }
        if lineage is not None:
            entry["lineage"] = lineage
        self._projects[project]["agents"].append(entry)

    def register(self, project: str, agent: str, **kwargs: Any) -> Path:
        """Write a leaf *and* its index summary — the fully-registered shape."""
        summary_keys = ("session_id", "role", "brand", "state", "lineage")
        summary_kwargs = {k: v for k, v in kwargs.items() if k in summary_keys}
        directory = self.write_leaf(project, agent, **kwargs)
        self.add_summary(project, agent, **summary_kwargs)
        return directory

    def flush(self, *, raw: str | None = None) -> Path:
        if raw is not None:
            self.index_path.write_text(raw, encoding="utf-8")
        else:
            document = {"projects": list(self._projects.values())}
            self.index_path.write_text(json.dumps(document), encoding="utf-8")
        return self.index_path


class FixtureTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.fixture = RegistryFixture(self.base)


class CleanRegistryTests(FixtureTestCase):
    def test_clean_registry_exits_zero_and_prints_counts(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.add_project("repo-b")
        self.fixture.register(
            "repo-a",
            "gardener",
            session_id="sid-a",
            role="gardener",
            pane_ref={"multiplexer": "mux", "session": "s-a", "pane_id": "terminal_0"},
        )
        self.fixture.register(
            "repo-b",
            "impler-one",
            session_id="sid-b",
            pane_ref={"multiplexer": "mux", "session": "s-b", "pane_id": "terminal_0"},
        )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 0, out)
        self.assertIn("AgentTUI registry consistent", out)
        self.assertIn("checked 2 project(s), 2 leaf/leaves, 2 index summar", out)

    def test_null_pane_ref_and_absent_lineage_are_clean(self) -> None:
        # `pane_ref: null` is the documented value when pane delivery is off,
        # and an absent `lineage` reads as 1 on both sides.
        self.fixture.add_project("repo-a")
        self.fixture.register("repo-a", "rootorc", session_id="sid-a", pane_ref=None)
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 0, out)

    def test_lineage_default_matches_explicit_one(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.write_leaf("repo-a", "rootorc", session_id="sid-a")
        self.fixture.add_summary("repo-a", "rootorc", session_id="sid-a", lineage=1)
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 0, out)

    def test_validator_never_writes(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.register("repo-a", "gardener", session_id="sid-a", role="gardener")
        # Deliberately dirty, so the run has something it might be tempted to fix.
        self.fixture.write_leaf("repo-a", "orphan", session_id="sid-orphan")
        index = self.fixture.flush()

        before = self._snapshot(self.base)
        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertEqual(self._snapshot(self.base), before)

    @staticmethod
    def _snapshot(base: Path) -> dict[str, bytes]:
        return {
            str(path.relative_to(base)): path.read_bytes()
            for path in sorted(base.rglob("*"))
            if path.is_file()
        }


class SessionIdUniquenessTests(FixtureTestCase):
    def test_same_session_registered_in_two_projects_fails(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.add_project("repo-b")
        leaf_a = self.fixture.register("repo-a", "impler-one", session_id="sid-shared")
        leaf_b = self.fixture.register("repo-b", "impler-one", session_id="sid-shared")
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("duplicate-session-id", out)
        self.assertIn("in more than one project", out)
        # Both conflicting paths must be named, not just the count.
        self.assertIn(str(leaf_a), out)
        self.assertIn(str(leaf_b), out)
        self.assertIn("session_file", out)

    def test_same_session_twice_in_one_project_fails(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.register("repo-a", "impler-one", session_id="sid-shared")
        self.fixture.register("repo-a", "impler-two", session_id="sid-shared")
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("duplicate-session-id", out)
        self.assertIn("more than once in the same project", out)

    def test_distinct_sessions_pass(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.add_project("repo-b")
        self.fixture.register("repo-a", "impler-one", session_id="sid-a")
        self.fixture.register("repo-b", "impler-one", session_id="sid-b")
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 0, out)


class PaneRefUniquenessTests(FixtureTestCase):
    PANE = {"multiplexer": "mux", "session": "shared", "pane_id": "terminal_3"}

    def test_two_reachable_leaves_claiming_one_pane_fails_with_rot_note(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.add_project("repo-b")
        leaf_a = self.fixture.register(
            "repo-a", "impler-one", session_id="sid-a", pane_ref=dict(self.PANE)
        )
        leaf_b = self.fixture.register(
            "repo-b", "impler-one", session_id="sid-b", pane_ref=dict(self.PANE)
        )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("pane-ref-conflict", out)
        self.assertIn("terminal_3", out)
        self.assertIn("rotted", out)
        self.assertIn("third party", out)
        self.assertIn(str(leaf_a), out)
        self.assertIn(str(leaf_b), out)
        # No duplicate session id here: the pane check must stand on its own.
        self.assertNotIn("duplicate-session-id", out)

    def test_sequential_pane_reuse_is_not_a_conflict(self) -> None:
        # The false positive the split exists to avoid: one session ended, the
        # next started in the same pane. The stopped leaf still holds the old
        # triple, and that is normal.
        self.fixture.add_project("repo-a")
        stopped = self.fixture.register(
            "repo-a",
            "impler-old",
            session_id="sid-old",
            state="stopped",
            pane_ref=dict(self.PANE),
        )
        self.fixture.register(
            "repo-a",
            "impler-new",
            session_id="sid-new",
            state="active",
            pane_ref=dict(self.PANE),
        )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        # Only a cleanup warning, so the run still passes.
        self.assertEqual(code, 0, out)
        self.assertNotIn("pane-ref-conflict", out)
        self.assertIn("stale-addressing-handle", out)
        self.assertIn(str(stopped), out)
        self.assertIn("1 warning(s)", out)

    def test_stale_handle_is_a_warning_in_its_own_block(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.register(
            "repo-a",
            "impler-old",
            session_id="sid-old",
            state="stopped",
            pane_ref=dict(self.PANE),
        )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 0, out)
        self.assertIn("--- warnings", out)
        self.assertIn("warning: stale-addressing-handle", out)
        self.assertIn("reused by a later session", out)

    def test_two_stopped_leaves_on_one_pane_are_warnings_not_a_conflict(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.register(
            "repo-a",
            "impler-old",
            session_id="sid-old",
            state="stopped",
            pane_ref=dict(self.PANE),
        )
        self.fixture.register(
            "repo-a",
            "impler-older",
            session_id="sid-older",
            state="stopped",
            pane_ref=dict(self.PANE),
        )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 0, out)
        self.assertNotIn("pane-ref-conflict", out)
        self.assertEqual(out.count("stale-addressing-handle"), 2)

    def test_stopped_leaf_without_pane_ref_is_not_warned_about(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.register(
            "repo-a", "impler-old", session_id="sid-old", state="stopped", pane_ref=None
        )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 0, out)
        self.assertNotIn("stale-addressing-handle", out)
        self.assertIn("0 warning(s)", out)

    def test_idle_counts_as_reachable(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.register(
            "repo-a",
            "impler-one",
            session_id="sid-a",
            state="idle",
            pane_ref=dict(self.PANE),
        )
        self.fixture.register(
            "repo-a",
            "impler-two",
            session_id="sid-b",
            state="active",
            pane_ref=dict(self.PANE),
        )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("pane-ref-conflict", out)

    def test_unknown_state_counts_as_reachable(self) -> None:
        # Fail towards reporting: guessing "probably dead" would suppress a
        # real mis-delivery risk.
        self.assertTrue(VALIDATOR.is_reachable_state({}))
        self.assertTrue(VALIDATOR.is_reachable_state({"state": "contradiction"}))
        self.assertFalse(VALIDATOR.is_reachable_state({"state": "stopped"}))

    def test_duplicate_session_id_is_not_state_restricted(self) -> None:
        # The root constraint stands regardless of state; only its pane_ref
        # corollary is restricted to reachable leaves.
        self.fixture.add_project("repo-a")
        self.fixture.add_project("repo-b")
        self.fixture.register(
            "repo-a", "impler-one", session_id="sid-shared", state="stopped"
        )
        self.fixture.register(
            "repo-b", "impler-one", session_id="sid-shared", state="stopped"
        )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("duplicate-session-id", out)

    def test_same_pane_id_under_different_session_names_passes(self) -> None:
        # The key is the whole triple, so `terminal_0` in two multiplexer
        # sessions is not a collision.
        self.fixture.add_project("repo-a")
        self.fixture.register(
            "repo-a",
            "impler-one",
            session_id="sid-a",
            pane_ref={"multiplexer": "mux", "session": "one", "pane_id": "terminal_0"},
        )
        self.fixture.register(
            "repo-a",
            "impler-two",
            session_id="sid-b",
            pane_ref={"multiplexer": "mux", "session": "two", "pane_id": "terminal_0"},
        )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 0, out)


class HalfRegisteredTests(FixtureTestCase):
    def test_direction_a_summary_without_leaf(self) -> None:
        root = self.fixture.add_project("repo-a")
        self.fixture.add_summary("repo-a", "ghost", session_id="sid-ghost")
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("half-registered", out)
        self.assertIn("direction A", out)
        self.assertIn(str(root / ".arborist/agents/ghost"), out)
        self.assertIn(str(index), out)
        self.assertIn("register-self", out)

    def test_direction_a_when_agents_dir_was_wiped(self) -> None:
        # The observed shape: `<repo>/.arborist/agents/` emptied by a sync while
        # every index summary stayed.
        self.fixture.add_project("repo-a")
        for suffix in ("one", "two", "three"):
            self.fixture.add_summary(
                "repo-a", f"impler-{suffix}", session_id=f"sid-{suffix}"
            )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count("direction A"), 3)

    def test_direction_b_leaf_without_summary(self) -> None:
        self.fixture.add_project("repo-a")
        leaf = self.fixture.write_leaf("repo-a", "unlisted", session_id="sid-a")
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("half-registered", out)
        self.assertIn("direction B", out)
        self.assertIn(str(leaf), out)
        self.assertIn(str(index), out)

    def test_direction_b_does_not_also_report_field_disagreement(self) -> None:
        # Without a summary there is nothing to disagree with; reporting both
        # would double-count one fault.
        self.fixture.add_project("repo-a")
        self.fixture.write_leaf("repo-a", "unlisted", session_id="sid-a")
        index = self.fixture.flush()

        _, out = run_main("--global-index", str(index))
        self.assertNotIn("index-leaf-disagreement", out)

    def test_incomplete_leaf_pair_is_reported(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.add_summary("repo-a", "partial", session_id="sid-a")
        leaf = self.fixture.write_leaf(
            "repo-a", "partial", session_id="sid-a", omit_runtime=True
        )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("leaf-incomplete", out)
        self.assertIn("runtime.json", out)
        self.assertIn(str(leaf), out)

    def test_unreadable_leaf_is_reported_and_others_still_checked(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.write_leaf(
            "repo-a", "broken", session_id="sid-broken", broken_spec_json=True
        )
        self.fixture.write_leaf("repo-a", "unlisted", session_id="sid-a")
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("leaf-unreadable", out)
        self.assertIn("direction B", out)


class ProjectSelfConsistencyTests(FixtureTestCase):
    def test_declared_path_pointing_at_another_repo_fails(self) -> None:
        root_a = self.fixture.add_project("repo-a")
        root_b = self.fixture.add_project("repo-b")
        # Leaf physically in repo-b, but claiming repo-a — the "fields all
        # correct, written in the wrong place" shape.
        self.fixture.register(
            "repo-b",
            "impler-one",
            session_id="sid-a",
            declared_project_path=root_a,
        )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("project-mismatch", out)
        self.assertIn(str(root_a), out)
        self.assertIn(str(root_b), out)

    def test_declared_path_pointing_at_parent_directory_fails(self) -> None:
        root = self.fixture.add_project("repo-a")
        self.fixture.register(
            "repo-a",
            "impler-one",
            session_id="sid-a",
            declared_project_path=root.parent,
        )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("project-mismatch", out)

    def test_hand_copied_project_id_fails(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.register(
            "repo-a",
            "impler-one",
            session_id="sid-a",
            declared_project_id="deadbeefcafe",
        )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("project-id-mismatch", out)
        self.assertIn("deadbeefcafe", out)

    def test_project_id_is_recomputed_from_realpath(self) -> None:
        root = self.fixture.add_project("repo-a")
        self.assertEqual(
            VALIDATOR.project_id_for(root), project_id_for(root)
        )
        self.assertEqual(len(VALIDATOR.project_id_for(root)), 12)
        # A trailing slash must normalise to the same id.
        self.assertEqual(
            VALIDATOR.project_id_for(Path(str(root) + "/")),
            VALIDATOR.project_id_for(root),
        )

    def test_missing_project_object_is_reported(self) -> None:
        root = self.fixture.add_project("repo-a")
        directory = root / ".arborist/agents/no-project"
        directory.mkdir(parents=True)
        (directory / "spec.json").write_text(
            json.dumps({"name": "no-project", "role": "impler"}), encoding="utf-8"
        )
        (directory / "runtime.json").write_text(
            json.dumps({"session_id": "sid-a", "state": "active"}), encoding="utf-8"
        )
        self.fixture.add_summary("repo-a", "no-project", session_id="sid-a")
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("project-mismatch", out)
        self.assertIn("no 'project' object", out)


class SummaryAgreementTests(FixtureTestCase):
    def _one_disagreement(self, **overrides: Any) -> tuple[int, str]:
        self.fixture.add_project("repo-a")
        self.fixture.write_leaf(
            "repo-a",
            "impler-one",
            session_id="sid-a",
            role="impler",
            brand="claude-code",
            state="active",
            lineage=1,
        )
        summary: dict[str, Any] = {
            "session_id": "sid-a",
            "role": "impler",
            "brand": "claude-code",
            "state": "active",
            "lineage": 1,
        }
        summary.update(overrides)
        self.fixture.add_summary("repo-a", "impler-one", **summary)
        index = self.fixture.flush()
        return run_main("--global-index", str(index))

    def test_role_disagreement(self) -> None:
        code, out = self._one_disagreement(role="suborc")
        self.assertEqual(code, 1, out)
        self.assertIn("index-leaf-disagreement: role", out)
        self.assertIn("leaf is", out)

    def test_brand_disagreement(self) -> None:
        code, out = self._one_disagreement(brand="codex")
        self.assertEqual(code, 1, out)
        self.assertIn("index-leaf-disagreement: brand", out)

    def test_state_disagreement(self) -> None:
        code, out = self._one_disagreement(state="stopped")
        self.assertEqual(code, 1, out)
        self.assertIn("index-leaf-disagreement: state", out)

    def test_lineage_disagreement(self) -> None:
        code, out = self._one_disagreement(lineage=4)
        self.assertEqual(code, 1, out)
        self.assertIn("index-leaf-disagreement: lineage", out)

    def test_lineage_absent_in_summary_but_two_in_leaf_disagrees(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.write_leaf("repo-a", "impler-one", session_id="sid-a", lineage=2)
        self.fixture.add_summary("repo-a", "impler-one", session_id="sid-a")
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("index-leaf-disagreement: lineage", out)

    def test_all_fields_agreeing_passes(self) -> None:
        code, out = self._one_disagreement()
        self.assertEqual(code, 0, out)


class GlobalIndexFailClosedTests(FixtureTestCase):
    def test_missing_index_exits_two(self) -> None:
        missing = self.base / "global" / "index.json"
        code, out = run_main("--global-index", str(missing))
        self.assertEqual(code, 2, out)
        self.assertIn("global index unusable", out)
        self.assertIn("not an empty registry", out)

    def test_invalid_json_index_exits_two(self) -> None:
        index = self.fixture.flush(raw="{ this is not json")
        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 2, out)
        self.assertIn("not valid JSON", out)

    def test_index_without_projects_key_exits_two(self) -> None:
        index = self.fixture.flush(raw=json.dumps({"agents": []}))
        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 2, out)
        self.assertIn("no 'projects' key", out)

    def test_index_projects_not_a_list_exits_two(self) -> None:
        index = self.fixture.flush(raw=json.dumps({"projects": {}}))
        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 2, out)
        self.assertIn("must be a list", out)

    def test_index_top_level_not_an_object_exits_two(self) -> None:
        index = self.fixture.flush(raw=json.dumps([]))
        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 2, out)

    def test_malformed_project_entry_is_a_finding_not_exit_two(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.register("repo-a", "impler-one", session_id="sid-a")
        document = json.loads(self.fixture.flush().read_text(encoding="utf-8"))
        document["projects"].append({"name": "pathless"})
        index = self.fixture.flush(raw=json.dumps(document))

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("index-malformed", out)


class DeadProjectPathTests(FixtureTestCase):
    def test_dead_project_path_is_reported_and_others_still_checked(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.register("repo-a", "impler-one", session_id="sid-a")
        dead = self.fixture.add_project("repo-gone", create_dir=False)
        self.fixture.add_summary("repo-gone", "ghost", session_id="sid-ghost")
        self.fixture.write_leaf("repo-a", "unlisted", session_id="sid-b")
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("project-unreachable", out)
        self.assertIn(str(dead), out)
        # The rest of the table was still checked, not aborted at the first fault.
        self.assertIn("direction B", out)
        self.assertIn("checked 2 project(s)", out)

    def test_dead_project_does_not_emit_per_agent_half_registered(self) -> None:
        self.fixture.add_project("repo-gone", create_dir=False)
        for suffix in ("one", "two"):
            self.fixture.add_summary(
                "repo-gone", f"impler-{suffix}", session_id=f"sid-{suffix}"
            )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertNotIn("half-registered", out)
        self.assertEqual(out.count("project-unreachable"), 1)


class ProjectSelectionTests(FixtureTestCase):
    def test_explicit_project_narrows_the_scan(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.add_project("repo-b")
        self.fixture.register("repo-a", "impler-one", session_id="sid-a")
        self.fixture.write_leaf("repo-b", "unlisted", session_id="sid-b")
        index = self.fixture.flush()

        code, out = run_main(
            "--global-index", str(index), "--project", str(self.fixture.project_root("repo-a"))
        )
        self.assertEqual(code, 0, out)
        self.assertIn("checked 1 project(s)", out)

        code, out = run_main(
            "--global-index", str(index), "--project", str(self.fixture.project_root("repo-b"))
        )
        self.assertEqual(code, 1, out)
        self.assertIn("direction B", out)

    def test_repeated_project_flags_accumulate(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.add_project("repo-b")
        self.fixture.register("repo-a", "impler-one", session_id="sid-a")
        self.fixture.register("repo-b", "impler-one", session_id="sid-b")
        index = self.fixture.flush()

        code, out = run_main(
            "--global-index",
            str(index),
            "--project",
            str(self.fixture.project_root("repo-a")),
            "--project",
            str(self.fixture.project_root("repo-b")),
        )
        self.assertEqual(code, 0, out)
        self.assertIn("checked 2 project(s)", out)

    def test_no_abbreviated_flags(self) -> None:
        # allow_abbrev=False: `--glob` must not silently mean `--global-index`.
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                run_main("--glob", str(self.fixture.index_path))


class CrossRepoTiebreakReadingsTests(FixtureTestCase):
    """The two findings that span repos must carry the readings a ruling needs.

    A cross-repo conflict has no owner by construction — each lane's own leaf is
    self-consistent — so the report has to be sufficient on its own, and it has
    to say that the ruling is global and is not made by the validator.
    """

    PANE = {"multiplexer": "mux", "session": "shared", "pane_id": "terminal_7"}

    def _cross_repo_pane_conflict(self, **overrides: Any) -> tuple[str, Path, Path]:
        self.fixture.add_project("repo-a")
        self.fixture.add_project("repo-b")
        leaf_a = self.fixture.register(
            "repo-a",
            "impler-one",
            session_id="sid-a",
            state="active",
            pane_ref=dict(self.PANE),
            **overrides,
        )
        leaf_b = self.fixture.register(
            "repo-b",
            "impler-two",
            session_id="sid-b",
            state="active",
            pane_ref=dict(self.PANE),
            **overrides,
        )
        index = self.fixture.flush()
        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        return out, leaf_a, leaf_b

    def test_pane_conflict_prints_every_reading_a_ruling_needs(self) -> None:
        out, leaf_a, leaf_b = self._cross_repo_pane_conflict()
        self.assertIn("pane-ref-conflict", out)
        for leaf in (leaf_a, leaf_b):
            self.assertIn(f"claimant {leaf}", out)
        # session_id / session_file / state / last_seen / pane_ref, per claimant.
        self.assertIn("session_id=sid-a", out)
        self.assertIn("session_id=sid-b", out)
        self.assertIn(str(self.base / "transcripts" / "sid-a.jsonl"), out)
        self.assertIn(str(self.base / "transcripts" / "sid-b.jsonl"), out)
        self.assertEqual(out.count("state=active"), 2)
        self.assertEqual(out.count("last_seen=2000-01-01T00:00:00+00:00"), 2)
        self.assertEqual(out.count("pane_id=terminal_7"), 3)  # 1 header + 2 claimants

    def test_pane_conflict_states_the_priority_order(self) -> None:
        out, _, _ = self._cross_repo_pane_conflict()
        self.assertIn(VALIDATOR.TIEBREAK_PRIORITY, out)
        # The order itself, not just that some inputs are listed.
        cwd_at = out.index("the pane's real cwd")
        session_file_at = out.index("session_file ownership")
        last_seen_at = out.index("3) last_seen")
        self.assertLess(cwd_at, session_file_at)
        self.assertLess(session_file_at, last_seen_at)

    def test_pane_conflict_says_the_ruling_is_global_and_not_made_here(self) -> None:
        out, _, _ = self._cross_repo_pane_conflict()
        self.assertIn("ONCE, GLOBALLY", out)
        self.assertIn("does NOT", out)
        self.assertIn("named one", out)
        self.assertIn("another repo is that lane's call", out)

    def test_pane_real_cwd_is_reported_unknown_with_its_reason(self) -> None:
        out, _, _ = self._cross_repo_pane_conflict()
        self.assertIn("pane real cwd (priority 1): unknown", out)
        # The reason must be present, or "unknown" reads as a missing feature.
        self.assertIn("focus command", out)
        self.assertIn("read-only substitute", out)
        self.assertIn("Supply this reading manually", out)

    def test_duplicate_session_id_carries_the_same_readings(self) -> None:
        self.fixture.add_project("repo-a")
        self.fixture.add_project("repo-b")
        leaf_a = self.fixture.register("repo-a", "impler-one", session_id="sid-shared")
        leaf_b = self.fixture.register("repo-b", "impler-one", session_id="sid-shared")
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 1, out)
        self.assertIn("duplicate-session-id", out)
        self.assertIn(VALIDATOR.TIEBREAK_PRIORITY, out)
        self.assertIn(f"claimant {leaf_a}", out)
        self.assertIn(f"claimant {leaf_b}", out)
        self.assertIn("pane real cwd (priority 1): unknown", out)
        # No pane_ref on either claimant: that must read as absent, not blank.
        self.assertEqual(out.count("pane_ref=absent-or-unusable"), 2)

    def test_absent_last_seen_reads_as_absent_not_blank(self) -> None:
        # A blank in a ruling's evidence column would read as "checked, nothing
        # there" when it actually means "never written".
        out, _, _ = self._cross_repo_pane_conflict(last_seen=None)
        self.assertEqual(out.count("last_seen=absent"), 2)
        self.assertNotIn("last_seen=,", out)

    def test_readings_do_not_make_the_validator_write(self) -> None:
        # Reporting the readings must stay read-only: byte-for-byte unchanged
        # even on a fixture that gives the run something to be tempted to fix.
        out, _, _ = self._cross_repo_pane_conflict()
        self.assertIn("pane-ref-conflict", out)
        before = self._snapshot()
        code, out = run_main("--global-index", str(self.fixture.index_path))
        self.assertEqual(code, 1, out)
        self.assertEqual(self._snapshot(), before)

    def test_validator_runs_no_external_command(self) -> None:
        """The mechanical proof that these readings added no observation.

        Per verification-and-gates, a new observation must be shown not to
        perturb what it observes. The strongest available form of that proof is
        that this script executes nothing at all: the pane's real cwd is left
        `unknown` precisely because acquiring it would need a command that can
        move a human's view.
        """

        source = (ROOT / "overlay/scripts/validate_agenttui_registry.py").read_text(
            encoding="utf-8"
        )
        for forbidden in ("import subprocess", "os.system", "os.popen", "shutil.which"):
            self.assertNotIn(forbidden, source)
        self.assertFalse(hasattr(VALIDATOR, "subprocess"))

    def test_stale_handle_warning_carries_no_readings(self) -> None:
        # The low-severity cleanup item has an owner (the leaf's own lane), so
        # it needs no tiebreak block — and padding it would bury the real ones.
        self.fixture.add_project("repo-a")
        self.fixture.register(
            "repo-a",
            "impler-old",
            session_id="sid-old",
            state="stopped",
            pane_ref=dict(self.PANE),
        )
        index = self.fixture.flush()

        code, out = run_main("--global-index", str(index))
        self.assertEqual(code, 0, out)
        self.assertIn("stale-addressing-handle", out)
        self.assertNotIn(VALIDATOR.TIEBREAK_PRIORITY, out)

    def _snapshot(self) -> dict[str, bytes]:
        return {
            str(path.relative_to(self.base)): path.read_bytes()
            for path in sorted(self.base.rglob("*"))
            if path.is_file()
        }


class ComputeProjectIdModeTests(FixtureTestCase):
    """`--print-project-id`: the write path computes the value instead of copying it."""

    def test_print_project_id_matches_the_recomputed_value(self) -> None:
        root = self.fixture.add_project("repo-a")
        code, out = run_main("--print-project-id", str(root))
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), project_id_for(root))

    def test_print_project_id_needs_no_global_index(self) -> None:
        # Self-registration happens before there is any registry to read.
        root = self.fixture.add_project("repo-a")
        missing_index = self.base / "nowhere" / "index.json"
        code, out = run_main(
            "--global-index", str(missing_index), "--print-project-id", str(root)
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), project_id_for(root))

    def test_print_project_id_fails_closed_on_non_directory(self) -> None:
        # realpath would digest a typo into a perfectly plausible id.
        code, out = run_main("--print-project-id", str(self.base / "typo-repo"))
        self.assertEqual(code, 2, out)
        self.assertIn("not an existing directory", out)
        self.assertNotIn(project_id_for(self.base / "typo-repo"), out)

    def test_print_project_id_writes_nothing(self) -> None:
        root = self.fixture.add_project("repo-a")
        self.fixture.register("repo-a", "impler-one", session_id="sid-a")
        self.fixture.flush()
        before = {
            str(path.relative_to(self.base)): path.read_bytes()
            for path in sorted(self.base.rglob("*"))
            if path.is_file()
        }
        code, _ = run_main("--print-project-id", str(root))
        self.assertEqual(code, 0)
        after = {
            str(path.relative_to(self.base)): path.read_bytes()
            for path in sorted(self.base.rglob("*"))
            if path.is_file()
        }
        self.assertEqual(after, before)


class WriteTimeProjectIdRuleTests(unittest.TestCase):
    """The rule moved to write time: templates must offer no slot to hand-copy into."""

    @staticmethod
    def _read(relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_templates_offer_no_fillable_project_id_slot(self) -> None:
        for relative in (
            "overlay/arborist-templates/agents/example/spec.json",
            "overlay/arborist-templates/index.json",
        ):
            raw = self._read(relative)
            self.assertNotIn('"<project-id>"', raw, relative)
            document = json.loads(raw)
            value = (
                document["project"]["project_id"]
                if "project" in document
                else document["projects"][0]["project_id"]
            )
            self.assertIn("computed-from-realpath", value, relative)
            self.assertIn("not-a-fill-in-slot", value, relative)
            self.assertIn("--print-project-id", value, relative)

    def test_guide_moves_the_rule_to_write_time(self) -> None:
        guide = self._read("overlay/spec/guides/agenttui-registry.md")
        self.assertIn("规则前移到写入时", guide)
        self.assertIn("预防 > 检测 > 判断", guide)
        self.assertIn("--print-project-id", guide)
        # Self-registration step 4 is the landing point, and an existing
        # mismatching value must fail closed rather than be overwritten.
        self.assertIn("已有值与重算不符 ⇒ fail closed", guide)

    def test_guide_states_the_cross_repo_tiebreak(self) -> None:
        guide = self._read("overlay/spec/guides/agenttui-registry.md")
        self.assertIn("跨仓冲突的机械 tiebreak", guide)
        self.assertIn("判定必须在全局做", guide)
        self.assertIn("具名裁定", guide)
        self.assertIn("真实 cwd", guide)
        self.assertIn("不裁定、不删、无 `--fix`", guide)

    def test_gate_matrix_row_mentions_the_readings_and_the_computed_id(self) -> None:
        gates = self._read("overlay/spec/guides/verification-and-gates.md")
        row = next(
            line
            for line in gates.splitlines()
            if line.startswith("|") and "AgentTUI 注册表一致性" in line
        )
        self.assertIn("裁定所需读数", row)
        self.assertIn("--print-project-id", row)
        self.assertIn("不执行任何外部命令", row)


if __name__ == "__main__":
    unittest.main()
