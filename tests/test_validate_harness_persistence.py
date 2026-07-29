from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Placeholder remote URL — not an instance value, never contacted.
UNREACHABLE_REMOTE_URL = "https://example.invalid/harness.git"

DURABLE_RELATIVE = ".trellis/spec/guides/example.md"


def load_validator_module():
    """Load the overlay validator by path, without a package import."""
    module_path = ROOT / "overlay/scripts/validate_harness_persistence.py"
    module_name = "validate_harness_persistence"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None, module_path
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_validator_module()


class HarnessFixture(unittest.TestCase):
    """Scratch work tree + side-history git dir; no real repository involved."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.work_tree = self.root / "repo"
        self.work_tree.mkdir()
        self.git_dir = self.work_tree / ".harness-vcs"
        self.git("init", "--quiet")
        self.git("config", "user.name", "harness-local")
        self.git("config", "user.email", "harness@localhost")
        self.path = self.work_tree / DURABLE_RELATIVE
        self.path.parent.mkdir(parents=True)

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "git",
                f"--git-dir={self.git_dir}",
                f"--work-tree={self.work_tree}",
                *args,
            ],
            cwd=self.work_tree,
            check=True,
            capture_output=True,
            text=True,
        )

    def commit_durable(self, body: str = "# durable\n") -> str:
        self.path.write_text(body, encoding="utf-8")
        self.git("add", DURABLE_RELATIVE)
        self.git("commit", "--quiet", "-m", "test: persist durable file")
        return self.git("log", "-1", "--format=%H").stdout.strip()

    def add_bare_remote(self, name: str = "origin") -> Path:
        bare = self.root / f"{name}.git"
        subprocess.run(
            ["git", "init", "--quiet", "--bare", str(bare)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.git("remote", "add", name, str(bare))
        return bare

    def run_validator(self, *extra: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = VALIDATOR.main(
                [
                    "--repo-root",
                    str(self.work_tree),
                    "--git-dir",
                    str(self.git_dir),
                    *extra,
                    str(self.path),
                ]
            )
        return result, stdout.getvalue(), stderr.getvalue()


class PathEvidenceTests(HarnessFixture):
    """exact-path / clean-status / path@commit — the mode-independent core."""

    def test_missing_durable_file_fails(self) -> None:
        result, _, stderr = self.run_validator()

        self.assertEqual(result, 1)
        self.assertIn("durable harness file does not exist", stderr)

    def test_ignored_untracked_durable_file_fails(self) -> None:
        self.path.write_text("# ignored\n", encoding="utf-8")
        (self.git_dir / "info").mkdir(parents=True, exist_ok=True)
        (self.git_dir / "info/exclude").write_text("/*\n", encoding="utf-8")

        result, _, stderr = self.run_validator()

        self.assertEqual(result, 1)
        self.assertIn("ignored by hgit", stderr)

    def test_visible_but_uncommitted_file_fails(self) -> None:
        self.path.write_text("# pending\n", encoding="utf-8")

        result, _, stderr = self.run_validator()

        self.assertEqual(result, 1)
        self.assertIn("uncommitted hgit state", stderr)

    def test_committed_then_modified_file_fails(self) -> None:
        self.commit_durable("# v1\n")
        self.path.write_text("# v2\n", encoding="utf-8")

        result, _, stderr = self.run_validator()

        self.assertEqual(result, 1)
        self.assertIn("uncommitted hgit state", stderr)

    def test_clean_committed_file_passes_with_commit_evidence(self) -> None:
        commit = self.commit_durable()

        result, stdout, stderr = self.run_validator()

        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertIn("harness persistence valid: 1 path(s)", stdout)
        self.assertIn(f"{DURABLE_RELATIVE}@{commit}", stdout)

    def test_path_outside_the_work_tree_fails(self) -> None:
        outside = self.root / "outside.md"
        outside.write_text("# outside\n", encoding="utf-8")
        self.commit_durable()

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = VALIDATOR.main(
                [
                    "--repo-root",
                    str(self.work_tree),
                    "--git-dir",
                    str(self.git_dir),
                    str(outside),
                ]
            )

        self.assertEqual(result, 1)
        self.assertIn("outside harness work tree", stderr.getvalue())

    def test_missing_git_dir_fails_closed(self) -> None:
        self.commit_durable()

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = VALIDATOR.main(
                [
                    "--repo-root",
                    str(self.work_tree),
                    "--git-dir",
                    str(self.work_tree / ".harness-vcs-absent"),
                    str(self.path),
                ]
            )

        self.assertEqual(result, 2)
        self.assertIn("harness git dir not found", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")


class RemoteStrengthTests(HarnessFixture):
    """The two remote flags must prove different things, and say so."""

    def test_both_remote_modes_fail_without_any_configured_remote(self) -> None:
        self.commit_durable()

        weak, _, weak_stderr = self.run_validator("--require-remote-configured")
        strong, _, strong_stderr = self.run_validator("--require-remote-reachable")

        self.assertEqual((weak, strong), (1, 1))
        self.assertIn("no configured remote", weak_stderr)
        self.assertIn("no configured remote", strong_stderr)

    def test_weak_and_strong_modes_disagree_when_the_commit_was_never_pushed(self) -> None:
        # The regression witness for the old `--require-remote`: a configured
        # remote is all it ever proved, so it passed here while nothing had left
        # the machine. The strong flag is what actually refuses.
        commit = self.commit_durable()
        self.git("remote", "add", "origin", UNREACHABLE_REMOTE_URL)

        weak, weak_stdout, weak_stderr = self.run_validator(
            "--require-remote-configured"
        )
        strong, strong_stdout, strong_stderr = self.run_validator(
            "--require-remote-reachable"
        )

        self.assertEqual(weak, 0, weak_stderr)
        self.assertIn("remote configured: origin", weak_stdout)
        self.assertIn("not that any commit reached a remote", weak_stdout)

        self.assertEqual(strong, 1)
        self.assertEqual(strong_stdout, "")
        self.assertIn("no remote-tracking ref under refs/remotes/", strong_stderr)
        self.assertNotIn(commit, strong_stdout)

    def test_strong_mode_passes_only_for_a_commit_in_a_remote_tracking_ref(self) -> None:
        commit = self.commit_durable("# v1\n")
        self.add_bare_remote()
        self.git("push", "--quiet", "origin", "HEAD:refs/heads/main")

        pushed, pushed_stdout, pushed_stderr = self.run_validator(
            "--require-remote-reachable"
        )

        self.assertEqual(pushed, 0, pushed_stderr)
        self.assertIn(f"{DURABLE_RELATIVE}@{commit}", pushed_stdout)
        self.assertIn("remote reachable:", pushed_stdout)
        self.assertIn("refs/remotes/origin/main", pushed_stdout)
        self.assertIn("as of the last fetch", pushed_stdout)

    def test_strong_mode_refuses_a_local_commit_made_after_the_push(self) -> None:
        # Remote-tracking refs exist (so this is not the never-fetched shape),
        # but the newest evidence commit is not contained in any of them.
        self.commit_durable("# v1\n")
        self.add_bare_remote()
        self.git("push", "--quiet", "origin", "HEAD:refs/heads/main")
        local_only = self.commit_durable("# v2 local only\n")

        weak, _, weak_stderr = self.run_validator("--require-remote-configured")
        strong, strong_stdout, strong_stderr = self.run_validator(
            "--require-remote-reachable"
        )

        self.assertEqual(weak, 0, weak_stderr)
        self.assertEqual(strong, 1)
        self.assertEqual(strong_stdout, "")
        self.assertIn("not contained in any remote-tracking ref", strong_stderr)
        self.assertIn(local_only, strong_stderr)

    def test_remote_scope_selects_which_tracking_refs_count(self) -> None:
        commit = self.commit_durable()
        self.add_bare_remote("origin")
        self.add_bare_remote("elsewhere")
        self.git("push", "--quiet", "origin", "HEAD:refs/heads/main")

        matched, matched_stdout, matched_stderr = self.run_validator(
            "--require-remote-reachable", "--remote", "origin"
        )
        unmatched, _, unmatched_stderr = self.run_validator(
            "--require-remote-reachable", "--remote", "elsewhere"
        )

        self.assertEqual(matched, 0, matched_stderr)
        self.assertIn(f"{DURABLE_RELATIVE}@{commit}", matched_stdout)
        self.assertEqual(unmatched, 1)
        self.assertIn("refs/remotes/elsewhere/", unmatched_stderr)

    def test_unknown_remote_name_fails_closed(self) -> None:
        self.commit_durable()
        self.add_bare_remote("origin")

        result, stdout, stderr = self.run_validator(
            "--require-remote-reachable", "--remote", "no-such-remote"
        )

        self.assertEqual(result, 2)
        self.assertIn("is not a configured hgit remote", stderr)
        self.assertEqual(stdout, "")

    def test_remote_scope_without_the_strong_flag_fails_closed(self) -> None:
        self.commit_durable()
        self.add_bare_remote("origin")

        result, stdout, stderr = self.run_validator("--remote", "origin")

        self.assertEqual(result, 2)
        self.assertIn("only scopes --require-remote-reachable", stderr)
        self.assertEqual(stdout, "")

    def test_the_unqualified_require_remote_spelling_is_gone(self) -> None:
        # The over-claiming name must not survive as an accepted spelling: it
        # reads as "persisted off this machine" while proving only config.
        with self.assertRaises(SystemExit) as raised, redirect_stderr(io.StringIO()):
            VALIDATOR.main(
                [
                    "--repo-root",
                    str(self.work_tree),
                    "--git-dir",
                    str(self.git_dir),
                    "--require-remote",
                    str(self.path),
                ]
            )

        self.assertEqual(raised.exception.code, 2)

    def test_help_does_not_promise_more_than_the_weak_flag_proves(self) -> None:
        help_text = VALIDATOR.build_parser().format_help()

        self.assertIn("--require-remote-configured", help_text)
        self.assertIn("--require-remote-reachable", help_text)
        self.assertIn("configuration only", help_text)


if __name__ == "__main__":
    unittest.main()
