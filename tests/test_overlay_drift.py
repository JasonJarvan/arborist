"""Tests for the overlay provenance writer and the drift validator.

Every fixture is built from scratch: a throwaway upstream git tree, a throwaway pin,
and throwaway adopting repos. The suite must never read the host's real registry,
real pin, or real adopted repos -- that would make results machine-dependent and
would let instance values into the repo.

What the assertions are protecting, in order of how quietly it fails:

1. **Fail closed.** Absent provenance and "never diverged" produce identical silence.
   A validator that resolves that silence in the reassuring direction is worse than
   none: it converts an unknown into a certificate. Same for an unverifiable pin.
2. **The three findings stay apart.** `behind`, `drifted` and `intentional` have
   different causes and different owners; merged into one verdict the report says
   nothing actionable, and a report that says nothing actionable gets ignored --
   which is the honour system again.
3. **Declared is not invisible.** A declaration with `reason` + `decided_by` is
   reported as `intentional` and still appears. Suppressing it would reinstate the
   honour system one level down; a declaration missing either field is reported as
   incomplete rather than accepted.
4. **Nothing is written into any repo by the validator, ever.**
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(script: str, name: str):
    module_path = ROOT / "overlay/scripts" / script
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec is not None and spec.loader is not None, module_path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PROVENANCE = load("arborist_provenance.py", "arborist_provenance")
DRIFT = load("validate_overlay_drift.py", "validate_overlay_drift")


def git(tree: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(tree), *args],
        capture_output=True,
        text=True,
        check=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "HOME": str(tree),
            "PATH": "/usr/bin:/bin",
        },
    )
    return result.stdout.strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Fixture:
    """A throwaway upstream tree, a pin, and adopting repos laid from it."""

    # The subset of the laid surface the fixtures exercise. Small on purpose: the
    # mapping table is the thing under test, not the size of the overlay.
    LAID = (
        ("overlay/scripts/agenttui.py", ".trellis/scripts/agenttui.py"),
        ("overlay/spec/guides/index.md", ".trellis/spec/guides/index.md"),
        (
            "overlay/spec/guides/tool-registry.md",
            ".trellis/spec/guides/tool-registry.md",
        ),
    )

    def __init__(self, base: Path) -> None:
        self.base = base
        self.upstream = base / "upstream"
        self.upstream.mkdir(parents=True)
        git(self.upstream, "init", "-q", "-b", "main")
        for upstream_path, _ in self.LAID:
            write(self.upstream / upstream_path, f"v1 of {upstream_path}\n")
        git(self.upstream, "add", "-A")
        git(self.upstream, "commit", "-q", "-m", "v1")
        self.first = git(self.upstream, "rev-parse", "HEAD")
        self.pin_path = base / "pin.json"
        self.write_pin(self.first)

    def write_pin(self, commit: str, tree: Path | None = None) -> None:
        self.pin_path.write_text(
            json.dumps(
                {"tree_path": str(tree or self.upstream), "commit": commit}, indent=2
            ),
            encoding="utf-8",
        )

    def advance(self) -> str:
        """One upstream commit that grows a laid file, as a real update would."""

        target = self.upstream / "overlay/scripts/agenttui.py"
        target.write_text("v2, considerably longer\n" * 20, encoding="utf-8")
        git(self.upstream, "add", "-A")
        git(self.upstream, "commit", "-q", "-m", "v2")
        return git(self.upstream, "rev-parse", "HEAD")

    def lay(self, name: str, *, at: str | None = None) -> Path:
        """Copy the surface into a fresh repo, as of one commit."""

        repo = self.base / name
        (repo / ".arborist").mkdir(parents=True)
        for upstream_path, repo_path in self.LAID:
            content = git(
                self.upstream, "show", f"{at or self.first}:{upstream_path}"
            )
            write(repo / repo_path, content + "\n")
        return repo

    def record(self, repo: Path, *, backfill: bool = False) -> int:
        argv = ["--repo", str(repo), "--upstream-tree", str(self.upstream), "--quiet"]
        if backfill:
            argv.append("--backfill")
        return PROVENANCE.main(argv)

    def read_record(self, repo: Path) -> dict:
        return json.loads(
            (repo / PROVENANCE.PROVENANCE_RELATIVE).read_text(encoding="utf-8")
        )

    # --- machine-level authority plumbing -------------------------------------
    #
    # A separate scratch ARBORIST_HOME per fixture, so the suite never reads or
    # writes the host's real global root.

    @property
    def home(self) -> Path:
        return self.base / "arborist-home"

    @property
    def bin_dir(self) -> Path:
        return self.home / "bin"

    def write_pin_into_home(self, commit: str) -> None:
        """The gardener's pin, in the place the writer reads it from."""

        target = self.home / PROVENANCE.PIN_RELATIVE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"tree_path": str(self.upstream), "commit": commit}, indent=2),
            encoding="utf-8",
        )

    def make_entry_point(self, name: str = "agenttui") -> Path:
        """A global entry point, which is what makes an absent record fail closed."""

        self.bin_dir.mkdir(parents=True, exist_ok=True)
        shim = self.bin_dir / name
        shim.write_text("#!/bin/sh\nexec true\n", encoding="utf-8")
        return shim

    def record_authority(self) -> int:
        return PROVENANCE.main(
            [
                "--record-authority",
                "--upstream-tree",
                str(self.upstream),
                "--arborist-home",
                str(self.home),
                "--quiet",
            ]
        )

    def record_execution(self, executed: Path) -> int:
        return PROVENANCE.main(
            [
                "--record-execution",
                str(executed),
                "--upstream-tree",
                str(self.upstream),
                "--arborist-home",
                str(self.home),
                "--quiet",
            ]
        )

    def read_authority(self) -> dict:
        return json.loads(
            (self.home / PROVENANCE.AUTHORITY_RELATIVE).read_text(encoding="utf-8")
        )

    def check(self, *argv: str) -> tuple[int, str]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = DRIFT.main(
                [
                    *argv,
                    "--pin",
                    str(self.pin_path),
                    "--authority",
                    str(self.home / PROVENANCE.AUTHORITY_RELATIVE),
                    "--executions",
                    str(self.home / PROVENANCE.EXECUTIONS_RELATIVE),
                    "--bin-dir",
                    str(self.bin_dir),
                ]
            )
        return code, stdout.getvalue()


class FixtureCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()


class ProvenanceWriterTest(FixtureCase):
    def test_records_the_upstream_head_as_the_baseline(self) -> None:
        repo = self.fixture.lay("repo-a")
        self.assertEqual(self.fixture.record(repo), 0)
        record = self.fixture.read_record(repo)
        self.assertEqual(record["upstream"]["commit"], self.fixture.first)
        self.assertEqual(
            record["upstream"]["commit_basis"], PROVENANCE.COMMIT_BASIS_UPSTREAM_HEAD
        )
        self.assertEqual(record["adopted_at_kind"], PROVENANCE.KIND_ADOPT)
        self.assertTrue(record["surface"], "no surface digests were recorded")

    def test_backfill_admits_an_unknown_baseline_instead_of_guessing(self) -> None:
        # A plausible-looking guess would be worse than an admitted gap: the entire
        # value of a baseline is that a later comparison can be trusted.
        repo = self.fixture.lay("repo-a")
        self.assertEqual(self.fixture.record(repo, backfill=True), 0)
        record = self.fixture.read_record(repo)
        self.assertIsNone(record["upstream"]["commit"])
        self.assertEqual(
            record["upstream"]["commit_basis"],
            PROVENANCE.COMMIT_BASIS_UNKNOWN_BACKFILL,
        )
        self.assertIn("not recoverable", record["upstream"]["commit_unknown_reason"])

    def test_nested_tree_files_are_recorded_not_silently_dropped(self) -> None:
        # Regression: the surface was collected with `Path.glob("dir/**")`, which
        # yields directories only, so every nested guide and ADR was omitted from the
        # baseline -- and the record still looked complete. A baseline missing the
        # largest part of the surface reports "in-sync" for files it never digested,
        # which is the exact failure mode fail-closed exists to prevent.
        repo = self.fixture.lay("repo-a")
        write(repo / ".trellis/spec/guides/decisions/0001-x.md", "adr\n")
        write(repo / ".trellis/spec/guides/methodology/m.md", "method\n")
        self.fixture.record(repo)
        recorded = {e["path"] for e in self.fixture.read_record(repo)["surface"]}
        self.assertIn(".trellis/spec/guides/decisions/0001-x.md", recorded)
        self.assertIn(".trellis/spec/guides/methodology/m.md", recorded)

    def test_backfill_still_records_todays_digests(self) -> None:
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo, backfill=True)
        record = self.fixture.read_record(repo)
        digests = {e["path"]: e["sha256"] for e in record["surface"]}
        self.assertIsNotNone(digests.get(".trellis/scripts/agenttui.py"))

    def test_a_rewrite_preserves_declared_deviations(self) -> None:
        # Dropping them would silently turn every declared deviation back into an
        # unexplained one: the honour system with extra steps.
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        path = repo / PROVENANCE.PROVENANCE_RELATIVE
        record = json.loads(path.read_text(encoding="utf-8"))
        record["local_modifications"] = [
            {
                "path": ".trellis/scripts/agenttui.py",
                "reason": "a local necessity",
                "decided_by": "this repo's gardener",
            }
        ]
        path.write_text(json.dumps(record), encoding="utf-8")

        self.fixture.record(repo)
        again = self.fixture.read_record(repo)
        self.assertEqual(len(again["local_modifications"]), 1)
        self.assertEqual(
            again["local_modifications"][0]["reason"], "a local necessity"
        )

    def test_a_moved_baseline_is_pushed_into_history_not_dropped(self) -> None:
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        second = self.fixture.advance()
        self.fixture.record(repo)
        record = self.fixture.read_record(repo)
        self.assertEqual(record["upstream"]["commit"], second)
        self.assertEqual(
            [h["upstream"]["commit"] for h in record["history"]], [self.fixture.first]
        )

    def test_history_is_bounded(self) -> None:
        # An unbounded list turns a baseline into a logfile, and the validator reads
        # this file on every checkup.
        repo = self.fixture.lay("repo-a")
        path = repo / PROVENANCE.PROVENANCE_RELATIVE
        write(
            path,
            json.dumps(
                {
                    "upstream": {"commit": "old" * 13},
                    "history": [{"upstream": {"commit": f"{i:040d}"}} for i in range(50)],
                }
            ),
        )
        self.fixture.record(repo)
        self.assertLessEqual(
            len(self.fixture.read_record(repo)["history"]), PROVENANCE.HISTORY_LIMIT
        )

    def test_an_unreadable_upstream_tree_is_recorded_as_unresolvable(self) -> None:
        # Not as in-sync: a baseline nobody can verify must not read as a verified one.
        repo = self.fixture.lay("repo-a")
        not_a_tree = self.fixture.base / "not-a-git-tree"
        not_a_tree.mkdir()
        PROVENANCE.main(
            ["--repo", str(repo), "--upstream-tree", str(not_a_tree), "--quiet"]
        )
        record = self.fixture.read_record(repo)
        self.assertIsNone(record["upstream"]["commit"])
        self.assertEqual(
            record["upstream"]["commit_basis"], PROVENANCE.COMMIT_BASIS_UNRESOLVABLE
        )

    def test_check_reports_absence_without_writing(self) -> None:
        repo = self.fixture.lay("repo-a")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = PROVENANCE.main(["--repo", str(repo), "--check"])
        self.assertEqual(code, 1)
        self.assertIn("Adopt is not complete", stdout.getvalue())
        self.assertFalse((repo / PROVENANCE.PROVENANCE_RELATIVE).exists())

    def test_check_passes_once_a_record_exists(self) -> None:
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = PROVENANCE.main(["--repo", str(repo), "--check"])
        self.assertEqual(code, 0)
        self.assertIn("provenance present", stdout.getvalue())

    def test_a_missing_repo_fails_closed(self) -> None:
        code = PROVENANCE.main(["--repo", str(self.fixture.base / "gone")])
        self.assertEqual(code, 2)

    def test_writing_touches_only_the_provenance_file(self) -> None:
        repo = self.fixture.lay("repo-a")
        before = {
            path.relative_to(repo).as_posix(): path.read_bytes()
            for path in repo.rglob("*")
            if path.is_file()
        }
        self.fixture.record(repo)
        after = {
            path.relative_to(repo).as_posix(): path.read_bytes()
            for path in repo.rglob("*")
            if path.is_file()
        }
        added = set(after) - set(before)
        self.assertEqual(added, {PROVENANCE.PROVENANCE_RELATIVE})
        for name in before:
            self.assertEqual(before[name], after[name], name)


class FailClosedTest(FixtureCase):
    def test_absent_provenance_exits_two_not_zero(self) -> None:
        repo = self.fixture.lay("repo-a")
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FAIL_CLOSED)
        self.assertIn("fail-closed", output)
        self.assertIn("look identical", output)

    def test_unparsable_provenance_exits_two(self) -> None:
        repo = self.fixture.lay("repo-a")
        write(repo / PROVENANCE.PROVENANCE_RELATIVE, "{ not json")
        code, _ = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FAIL_CLOSED)

    def test_a_missing_pin_exits_two(self) -> None:
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = DRIFT.main(
                ["--repo", str(repo), "--pin", str(self.fixture.base / "absent.json")]
            )
        self.assertEqual(code, DRIFT.EXIT_FAIL_CLOSED)
        self.assertIn("nothing to be behind", stdout.getvalue())

    def test_a_pinned_tree_that_is_gone_exits_two(self) -> None:
        # H3 puts the pin on an existing working tree, so a moved or deleted tree is
        # a broken pin -- not a reason to assume the copies are current.
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        self.fixture.write_pin(self.fixture.first, tree=self.fixture.base / "moved")
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FAIL_CLOSED)
        self.assertIn("does not exist", output)

    def test_a_pinned_commit_not_reachable_in_that_tree_exits_two(self) -> None:
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        self.fixture.write_pin("0" * 40)
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FAIL_CLOSED)
        self.assertIn("stopped being a pin", output)

    def test_a_missing_global_index_fails_closed_for_the_sweep(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = DRIFT.main(
                [
                    "--all",
                    "--global-index",
                    str(self.fixture.base / "absent.json"),
                    "--pin",
                    str(self.fixture.pin_path),
                ]
            )
        self.assertEqual(code, DRIFT.EXIT_FAIL_CLOSED)

    def test_no_target_fails_closed(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = DRIFT.main(["--pin", str(self.fixture.pin_path)])
        self.assertEqual(code, DRIFT.EXIT_FAIL_CLOSED)

    def test_one_dead_repo_does_not_shadow_the_others(self) -> None:
        good = self.fixture.lay("repo-a")
        self.fixture.record(good)
        code, output = self.fixture.check(
            "--repo", str(self.fixture.base / "gone"), "--repo", str(good)
        )
        self.assertEqual(code, DRIFT.EXIT_FAIL_CLOSED)
        self.assertIn("repo-a", output)
        self.assertIn("does not exist", output)


class ThreeFindingsTest(FixtureCase):
    def test_a_freshly_laid_and_recorded_repo_is_in_sync(self) -> None:
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_IN_SYNC, output)
        self.assertIn("in-sync", output)

    def test_an_upstream_that_moved_reads_as_behind_with_a_count(self) -> None:
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        second = self.fixture.advance()
        self.fixture.write_pin(second)
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FINDINGS)
        self.assertIn("behind", output)
        self.assertIn("1 upstream commit(s)", output)

    def test_a_long_abandoned_copy_is_reported_with_its_size_gap(self) -> None:
        # The reading the whole exercise started from: a copy that is a fraction of
        # what upstream ships. "The digests differ" and "a fifth of the size" are the
        # same fact, but only the second tells a reader which kind of drift it is.
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        second = self.fixture.advance()
        self.fixture.write_pin(second)
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FINDINGS)
        self.assertIn("stale-content", output)
        self.assertIn("% of upstream", output)

    def test_an_edited_copy_reads_as_drifted_not_behind(self) -> None:
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        (repo / ".trellis/spec/guides/index.md").write_text(
            "locally edited\n", encoding="utf-8"
        )
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FINDINGS)
        self.assertIn("drifted", output)
        self.assertNotIn("behind:", output)

    def test_a_declared_deviation_reads_as_intentional_and_is_still_listed(
        self,
    ) -> None:
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        (repo / ".trellis/spec/guides/index.md").write_text("edited\n", encoding="utf-8")
        path = repo / PROVENANCE.PROVENANCE_RELATIVE
        record = json.loads(path.read_text(encoding="utf-8"))
        record["local_modifications"] = [
            {
                "path": ".trellis/spec/guides/index.md",
                "reason": "this repo needs the extra section",
                "decided_by": "this repo's gardener",
                "at": "2026-01-01T00:00:00+00:00",
            }
        ]
        path.write_text(json.dumps(record), encoding="utf-8")

        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FINDINGS)
        self.assertIn("intentional", output)
        self.assertIn("index.md", output)
        self.assertNotIn("drifted:", output)

    def test_a_declaration_without_reason_or_decided_by_is_not_accepted(self) -> None:
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        (repo / ".trellis/spec/guides/index.md").write_text("edited\n", encoding="utf-8")
        path = repo / PROVENANCE.PROVENANCE_RELATIVE
        record = json.loads(path.read_text(encoding="utf-8"))
        record["local_modifications"] = [{"path": ".trellis/spec/guides/index.md"}]
        path.write_text(json.dumps(record), encoding="utf-8")

        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FINDINGS)
        self.assertIn("incomplete-declaration", output)

    def test_all_three_hold_at_once_and_all_three_are_reported(self) -> None:
        # Merged into one verdict the report says nothing actionable, and a report
        # that says nothing actionable gets ignored -- the honour system again.
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        second = self.fixture.advance()
        self.fixture.write_pin(second)
        (repo / ".trellis/spec/guides/index.md").write_text("edited\n", encoding="utf-8")
        path = repo / PROVENANCE.PROVENANCE_RELATIVE
        record = json.loads(path.read_text(encoding="utf-8"))
        record["local_modifications"] = [
            {
                "path": ".trellis/spec/guides/tool-registry.md",
                "reason": "r",
                "decided_by": "d",
            }
        ]
        path.write_text(json.dumps(record), encoding="utf-8")
        (repo / ".trellis/spec/guides/tool-registry.md").write_text(
            "also edited\n", encoding="utf-8"
        )

        code, output = self.fixture.check("--repo", str(repo), "--json")
        document = json.loads(output)
        verdict = document["repos"][0]["verdict"]
        self.assertEqual(code, DRIFT.EXIT_FINDINGS)
        for state in ("behind", "drifted", "intentional"):
            self.assertIn(state, verdict)

    def test_an_absent_recorded_artifact_is_reported(self) -> None:
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        (repo / ".trellis/spec/guides/index.md").unlink()
        code, output = self.fixture.check("--repo", str(repo), "--json")
        document = json.loads(output)
        self.assertEqual(code, DRIFT.EXIT_FINDINGS)
        self.assertTrue(document["repos"][0]["absent"])
        self.assertIn("not-laid", document["repos"][0]["verdict"])

    def test_the_pin_not_the_tree_head_is_what_repos_are_compared_against(
        self,
    ) -> None:
        # Otherwise the reading would depend on whichever branch somebody left
        # checked out in the upstream tree.
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        self.fixture.advance()  # tree HEAD moves; the pin stays put
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_IN_SYNC, output)
        self.assertIn("is not the pinned commit", output)


class SweepTest(FixtureCase):
    def test_the_sweep_covers_every_repo_the_index_names(self) -> None:
        a = self.fixture.lay("repo-a")
        b = self.fixture.lay("repo-b")
        self.fixture.record(a)
        self.fixture.record(b)
        index = self.fixture.base / "index.json"
        index.write_text(
            json.dumps({"projects": [{"path": str(a)}, {"path": str(b)}]}),
            encoding="utf-8",
        )
        code, output = self.fixture.check("--all", "--global-index", str(index))
        self.assertEqual(code, DRIFT.EXIT_IN_SYNC, output)
        self.assertIn("checked 2 repo(s)", output)

    def test_the_report_prints_the_commands_that_reproduce_it(self) -> None:
        # A report whose numbers cannot be re-derived by its reader is an assertion,
        # and an assertion about somebody else's repo is what this replaces.
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        _, output = self.fixture.check("--repo", str(repo))
        self.assertIn("reproduce this reading", output)
        self.assertIn("--all", output)

    def test_the_report_says_it_does_not_block(self) -> None:
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        _, output = self.fixture.check("--repo", str(repo))
        self.assertIn("does not block", output)


class ReadOnlyTest(FixtureCase):
    def test_the_validator_exposes_no_repair_entry_point(self) -> None:
        parser = DRIFT.build_parser()
        options = {
            option for action in parser._actions for option in action.option_strings
        }
        self.assertNotIn("--fix", options)
        self.assertNotIn("--sync", options)

    def test_checking_writes_nothing_into_the_repo(self) -> None:
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        before = {
            path.relative_to(repo).as_posix(): path.stat().st_mtime_ns
            for path in repo.rglob("*")
            if path.is_file()
        }
        self.fixture.check("--repo", str(repo))
        after = {
            path.relative_to(repo).as_posix(): path.stat().st_mtime_ns
            for path in repo.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)

    def test_checking_writes_nothing_into_the_upstream_tree(self) -> None:
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        status_before = git(self.fixture.upstream, "status", "--porcelain")
        self.fixture.check("--repo", str(repo))
        self.assertEqual(git(self.fixture.upstream, "status", "--porcelain"), status_before)


class AuthorityContentTest(FixtureCase):
    """The reading a pin cannot give: which bytes the entry points actually execute.

    Every test here goes **through a real git tree and real files on disk**, never
    through the comparison function alone. That is deliberate: the defect these tests
    exist for was invisible at the logic layer -- the entry point's source was correct
    about which path it would exec, and the divergence only existed one layer down, in
    the bytes that path held. A suite that only exercised the comparison would have
    passed while the machine ran something nobody had recorded.
    """

    def authority_path(self) -> Path:
        return self.fixture.upstream / "overlay/scripts/agenttui.py"

    def test_a_clean_tree_at_the_pin_reports_no_authority_findings(self) -> None:
        self.fixture.write_pin_into_home(self.fixture.first)
        self.fixture.make_entry_point()
        self.assertEqual(self.fixture.record_authority(), 0)
        self.fixture.record_execution(self.authority_path())
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_IN_SYNC, output)
        self.assertIn("machine authority", output)

    def test_a_dirty_tree_is_reported_because_no_commit_describes_it(self) -> None:
        # The core of the ruling: the entry points exec a WORKING TREE file. Edit it
        # without committing and the bytes that run exist in no commit at all, so
        # "which version ran" is not expressible as a commit -- only a fingerprint can
        # answer, and this must be visible rather than silently pass.
        self.fixture.write_pin_into_home(self.fixture.first)
        self.fixture.make_entry_point()
        self.authority_path().write_text("uncommitted local edit\n", encoding="utf-8")
        self.fixture.record_authority()
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FINDINGS)
        self.assertIn("authority-differs-from-pin", output)
        self.assertIn("version of record", output)

    def test_a_tree_that_moved_past_the_pin_is_reported(self) -> None:
        # The observed case: the pin disagreed with the executed file the same evening
        # it was written, because the tree is supposed to move.
        self.fixture.write_pin_into_home(self.fixture.first)
        self.fixture.make_entry_point()
        self.fixture.advance()  # tree HEAD moves; the pin stays at the first commit
        self.fixture.record_authority()
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FINDINGS)
        self.assertIn("authority-differs-from-pin", output)

    def test_the_recorded_fingerprint_is_of_the_working_file_not_of_a_commit(
        self,
    ) -> None:
        self.fixture.write_pin_into_home(self.fixture.first)
        path = self.authority_path()
        path.write_text("uncommitted\n", encoding="utf-8")
        self.fixture.record_authority()
        entry = next(
            f
            for f in self.fixture.read_authority()["files"]
            if f["tree_relative_path"] == "overlay/scripts/agenttui.py"
        )
        expected = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
        self.assertEqual(entry["sha256"], expected)
        self.assertIs(entry["matches_pinned_commit"], False)

    def test_matches_pinned_commit_is_tri_state(self) -> None:
        # `false` (the pin names other bytes) and `null` (the pin could not be
        # resolved) must stay distinguishable, or an unreadable pin reads as agreement.
        self.fixture.write_pin_into_home(self.fixture.first)
        self.fixture.record_authority()
        matched = {
            f["tree_relative_path"]: f["matches_pinned_commit"]
            for f in self.fixture.read_authority()["files"]
        }
        self.assertIs(matched["overlay/scripts/agenttui.py"], True)

        # Now with a pin that cannot be resolved at all.
        self.fixture.write_pin_into_home("0" * 40)
        self.fixture.record_authority()
        matched = {
            f["tree_relative_path"]: f["matches_pinned_commit"]
            for f in self.fixture.read_authority()["files"]
        }
        self.assertIsNone(matched["overlay/scripts/agenttui.py"])

    def test_the_pin_file_is_never_rewritten_by_this_writer(self) -> None:
        # The decision baseline keeps a single writer: the gardener.
        self.fixture.write_pin_into_home(self.fixture.first)
        pin_file = self.fixture.home / PROVENANCE.PIN_RELATIVE
        before = pin_file.read_bytes()
        self.fixture.record_authority()
        self.fixture.record_execution(self.authority_path())
        self.assertEqual(pin_file.read_bytes(), before)

    def test_entry_points_with_no_authority_record_fail_closed(self) -> None:
        self.fixture.write_pin_into_home(self.fixture.first)
        self.fixture.make_entry_point()
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FAIL_CLOSED)
        self.assertIn("no authority-content record", output)

    def test_no_entry_points_and_no_record_is_not_a_finding(self) -> None:
        # With nothing executed from a single copy there is nothing to record, and
        # demanding a record would be a gate on a facility not in use. False alarms
        # are how gates get ignored.
        self.fixture.write_pin_into_home(self.fixture.first)
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_IN_SYNC, output)
        self.assertIn("not in use", output)

    def test_an_unparsable_authority_record_fails_closed(self) -> None:
        self.fixture.write_pin_into_home(self.fixture.first)
        target = self.fixture.home / PROVENANCE.AUTHORITY_RELATIVE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{ not json", encoding="utf-8")
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        code, _ = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FAIL_CLOSED)

    def test_entry_points_with_no_execution_ever_recorded_is_a_finding(self) -> None:
        # A record whose writer is not wired in is the honour system with more files.
        self.fixture.write_pin_into_home(self.fixture.first)
        self.fixture.make_entry_point()
        self.fixture.record_authority()
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FINDINGS)
        self.assertIn("execution-unrecorded", output)

    def test_bytes_that_ran_but_match_no_current_authority_file_are_reported(
        self,
    ) -> None:
        # End to end through the real sequence: record what a call ran, then let the
        # tree move underneath. The recorded hash then matches nothing current, which
        # is the only evidence that the call ran something else.
        self.fixture.write_pin_into_home(self.fixture.first)
        self.fixture.make_entry_point()
        self.fixture.record_authority()
        self.fixture.record_execution(self.authority_path())
        self.authority_path().write_text("changed afterwards\n", encoding="utf-8")
        self.fixture.record_authority()
        repo = self.fixture.lay("repo-a")
        self.fixture.record(repo)
        code, output = self.fixture.check("--repo", str(repo))
        self.assertEqual(code, DRIFT.EXIT_FINDINGS)
        self.assertIn("executed-not-in-authority", output)

    def test_the_validator_recomputes_rather_than_trusting_the_stored_verdict(
        self,
    ) -> None:
        # The writer's verdict was true when written; the pin may have advanced since.
        # Trusting it would make this validator a mirror of the writer.
        self.fixture.write_pin_into_home(self.fixture.first)
        self.fixture.make_entry_point()
        self.fixture.record_authority()
        self.fixture.record_execution(self.authority_path())
        target = self.fixture.home / PROVENANCE.AUTHORITY_RELATIVE
        document = json.loads(target.read_text(encoding="utf-8"))
        for entry in document["files"]:
            entry["matches_pinned_commit"] = True  # a lie the validator must not use
        target.write_text(json.dumps(document), encoding="utf-8")
        second = self.fixture.advance()
        self.fixture.write_pin(second)

        code, output = self.fixture.check("--repo", str(self.fixture.lay("repo-a")))
        self.assertEqual(code, DRIFT.EXIT_FAIL_CLOSED)  # that repo has no provenance
        self.assertIn("authority-differs-from-pin", output)

    def test_recording_an_execution_never_fails_the_call_it_observes(self) -> None:
        # Fail-open by construction: this runs on the hot path of a capability
        # invocation, so a non-zero exit would turn bookkeeping into an outage.
        unwritable = Path("/proc/nonexistent-arborist-home")
        code = PROVENANCE.main(
            [
                "--record-execution",
                str(self.authority_path()),
                "--arborist-home",
                str(unwritable),
                "--quiet",
            ]
        )
        self.assertEqual(code, 0)

    def test_the_execution_record_is_self_bounding(self) -> None:
        # It must not become a third machine-level file with no sweeper -- which is the
        # exact failure mode it was introduced to avoid one level up.
        self.fixture.write_pin_into_home(self.fixture.first)
        path = self.authority_path()
        for _ in range(PROVENANCE.EXECUTION_RECORD_KEEP_PER_PATH * 6):
            self.fixture.record_execution(path)
        lines = (
            (self.fixture.home / PROVENANCE.EXECUTIONS_RELATIVE)
            .read_text(encoding="utf-8")
            .splitlines()
        )
        self.assertLessEqual(len(lines), PROVENANCE.EXECUTION_RECORD_KEEP_PER_PATH * 4)
        self.assertGreater(len(lines), 0)

    def test_only_the_newest_execution_per_path_is_consumed(self) -> None:
        self.fixture.write_pin_into_home(self.fixture.first)
        path = self.authority_path()
        self.fixture.record_execution(path)
        path.write_text("second version\n", encoding="utf-8")
        self.fixture.record_execution(path)
        newest = DRIFT.read_executions(
            self.fixture.home / PROVENANCE.EXECUTIONS_RELATIVE
        )
        self.assertEqual(len(newest), 1)
        expected = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
        self.assertEqual(newest[0]["sha256"], expected)

    def test_a_torn_line_in_the_execution_record_is_skipped_not_fatal(self) -> None:
        # The file is appended to by whichever entry point ran, so a torn last line is
        # an ordinary event.
        self.fixture.write_pin_into_home(self.fixture.first)
        self.fixture.record_execution(self.authority_path())
        target = self.fixture.home / PROVENANCE.EXECUTIONS_RELATIVE
        with target.open("a", encoding="utf-8") as handle:
            handle.write('{"at": "trunc')
        self.assertEqual(len(DRIFT.read_executions(target)), 1)


class MappingTest(unittest.TestCase):
    def test_the_two_directions_of_the_laid_mapping_agree(self) -> None:
        # A one-way mapping that disagrees with its inverse would report artifacts as
        # both absent upstream and absent locally, for the same file.
        for upstream, repo_relative, is_tree in DRIFT.LAID:
            with self.subTest(upstream=upstream):
                self.assertEqual(DRIFT.repo_path_for(upstream), repo_relative)
                self.assertEqual(DRIFT.upstream_path_for(repo_relative), upstream)
                if is_tree:
                    self.assertEqual(
                        DRIFT.repo_path_for(upstream + "/nested/x.md"),
                        repo_relative + "/nested/x.md",
                    )
                    self.assertEqual(
                        DRIFT.upstream_path_for(repo_relative + "/nested/x.md"),
                        upstream + "/nested/x.md",
                    )

    def test_an_unmapped_path_maps_to_nothing_rather_than_guessing(self) -> None:
        self.assertIsNone(DRIFT.repo_path_for("README.md"))
        self.assertIsNone(DRIFT.upstream_path_for("src/main.py"))

    def test_every_laid_upstream_path_exists_in_this_tree(self) -> None:
        # The laying script is the writer of this contract and the validator is a
        # reader of it. A reader that has fallen behind its writer would silently
        # report artifacts as missing everywhere, so the mapping is pinned to the
        # tree it ships in.
        for upstream, _, _ in DRIFT.LAID:
            with self.subTest(upstream=upstream):
                self.assertTrue((ROOT / upstream).exists(), upstream)


if __name__ == "__main__":
    unittest.main()
