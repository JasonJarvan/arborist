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


def load_validator_module():
    """Load the overlay validator by path, without a package import."""
    module_path = ROOT / "overlay/scripts/validate_adr_numbers.py"
    module_name = "validate_adr_numbers"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None, module_path
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_validator_module()

# Side-history exclude that hides everything (the pre-allowlist failure shape).
HIDE_EVERYTHING = "/*\n"

# Parent-directory allowlist: git never descends into an excluded directory, so
# every level must be un-excluded before the leaf negation can match.
DECISIONS_ALLOWLIST = "\n".join(
    [
        "/*",
        "!/.trellis/",
        "/.trellis/*",
        "!/.trellis/spec/",
        "/.trellis/spec/*",
        "!/.trellis/spec/guides/",
        "/.trellis/spec/guides/*",
        "!/.trellis/spec/guides/decisions/",
        "",
    ]
)

DECISIONS_RELATIVE = ".trellis/spec/guides/decisions"


def run_main(*argv: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = VALIDATOR.main(list(argv))
    return result, stdout.getvalue(), stderr.getvalue()


class NumericNamespaceTests(unittest.TestCase):
    """Prefix grouping is on the four-digit number alone, not the whole name."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.decisions = Path(self.tempdir.name)

    def touch(self, name: str) -> None:
        (self.decisions / name).write_text("# test\n", encoding="utf-8")

    def test_unique_numbers_pass_and_unassigned_drafts_are_outside_namespace(self) -> None:
        self.touch("0011-first.md")
        self.touch("0012-second.md")
        self.touch("proposed-third.md")
        self.touch("proposed-fourth.md")
        self.touch("TEMPLATE.md")

        self.assertEqual(VALIDATOR.find_duplicate_prefixes(self.decisions), {})
        self.assertEqual(VALIDATOR.count_adr_files(self.decisions), (2, 2))

    def test_different_slugs_with_same_numeric_prefix_collide(self) -> None:
        # Grouping the whole filename would let these two coexist; grouping the
        # prefix is what makes them a conflict.
        self.touch("0007-a.md")
        self.touch("0007-b.md")
        self.touch("0008-other.md")

        duplicates = VALIDATOR.find_duplicate_prefixes(self.decisions)

        self.assertEqual(list(duplicates), ["0007"])
        self.assertEqual(
            [path.name for path in duplicates["0007"]],
            ["0007-a.md", "0007-b.md"],
        )

    def test_only_exact_four_digit_dash_prefixes_enter_the_namespace(self) -> None:
        self.touch("12-short.md")
        self.touch("0012.md")
        self.touch("00120-five-digits.md")
        self.touch("proposed-0012-draft.md")
        self.touch("0012-valid.md")

        self.assertEqual(VALIDATOR.find_duplicate_prefixes(self.decisions), {})

    def test_many_proposed_drafts_never_collide_with_each_other(self) -> None:
        self.touch("proposed-first.md")
        self.touch("proposed-second.md")
        self.touch("proposed-third.md")

        self.assertEqual(VALIDATOR.find_duplicate_prefixes(self.decisions), {})
        self.assertEqual(VALIDATOR.count_adr_files(self.decisions), (0, 3))


class HarnessFixture(unittest.TestCase):
    """Scratch product work tree + side-history git dir; no real repo touched."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.work_tree = Path(self.tempdir.name) / "repo"
        self.work_tree.mkdir()
        self.git_dir = self.work_tree / ".harness-vcs"
        # Same two-git layout adopt.sh produces: a normal product repo, plus a
        # side-history git dir sharing the product work tree. The two modes must
        # be able to disagree, which a `--separate-git-dir` fixture cannot show.
        subprocess.run(
            ["git", "init", "--quiet", str(self.work_tree)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                f"--git-dir={self.git_dir}",
                f"--work-tree={self.work_tree}",
                "init",
                "--quiet",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.decisions = self.work_tree / DECISIONS_RELATIVE
        self.decisions.mkdir(parents=True)

    def write_side_exclude(self, body: str) -> None:
        (self.git_dir / "info").mkdir(parents=True, exist_ok=True)
        (self.git_dir / "info/exclude").write_text(body, encoding="utf-8")

    def write_product_gitignore(self, body: str) -> None:
        (self.work_tree / ".gitignore").write_text(body, encoding="utf-8")

    def touch(self, name: str) -> Path:
        path = self.decisions / name
        path.write_text("# adr\n", encoding="utf-8")
        return path

    def run_machine_local(self, *extra: str) -> tuple[int, str, str]:
        return run_main(
            "--visibility",
            "machine-local",
            "--repo-root",
            str(self.work_tree),
            "--git-dir",
            str(self.git_dir),
            *extra,
        )

    def run_product_git(self, *extra: str) -> tuple[int, str, str]:
        return run_main(
            "--visibility",
            "product-git",
            "--repo-root",
            str(self.work_tree),
            *extra,
        )


class VisibilityModeTests(HarnessFixture):
    def test_ignored_proposed_draft_fails_visibility(self) -> None:
        draft = self.touch("proposed-socket-ownership-attestation.md")
        self.write_side_exclude(HIDE_EVERYTHING)

        target = VALIDATOR.resolve_visibility(
            mode="machine-local",
            repo_root=self.work_tree,
            git_dir=self.git_dir,
        )
        hidden = VALIDATOR.find_ignored_adr_files(self.decisions, target=target)

        self.assertEqual([path.name for path, _ in hidden], [draft.name])

        result, _, stderr = self.run_machine_local()

        self.assertEqual(result, 1)
        self.assertIn("invisible to machine-local git", stderr)
        self.assertIn(draft.name, stderr)
        self.assertIn("info/exclude", stderr)

    def test_ignored_accepted_adr_also_fails_visibility(self) -> None:
        # Accept-time rename, after side: the numbered file must be checked too,
        # otherwise numbering an ADR would launder it out of the check.
        accepted = self.touch("0012-socket-ownership-attestation.md")
        self.write_side_exclude(HIDE_EVERYTHING)

        result, _, stderr = self.run_machine_local()

        self.assertEqual(result, 1)
        self.assertIn("invisible to machine-local git", stderr)
        self.assertIn(accepted.name, stderr)

    def test_accept_time_rename_is_checked_on_both_sides(self) -> None:
        # Before: the draft. After: the numbered file. Same hidden verdict, so
        # the rename cannot slip through in either state.
        draft = self.touch("proposed-socket-ownership-attestation.md")
        self.write_side_exclude(HIDE_EVERYTHING)
        before, _, before_stderr = self.run_machine_local()

        accepted = draft.with_name("0012-socket-ownership-attestation.md")
        draft.rename(accepted)
        after, _, after_stderr = self.run_machine_local()

        self.assertEqual((before, after), (1, 1))
        self.assertIn(draft.name, before_stderr)
        self.assertIn(accepted.name, after_stderr)

    def test_allowlisted_decisions_directory_passes(self) -> None:
        self.touch("proposed-socket-ownership-attestation.md")
        self.touch("0012-accepted.md")
        self.write_side_exclude(DECISIONS_ALLOWLIST)

        result, stdout, stderr = self.run_machine_local()

        self.assertEqual(result, 0, stderr)
        self.assertIn("every ADR file visible to machine-local git", stdout)
        self.assertIn("1 numbered ADR(s) + 1 proposed draft(s)", stdout)

    def test_duplicate_prefix_fails_even_when_visible(self) -> None:
        self.touch("0007-a.md")
        self.touch("0007-b.md")
        self.write_side_exclude(DECISIONS_ALLOWLIST)

        result, _, stderr = self.run_machine_local()

        self.assertEqual(result, 1)
        self.assertIn("duplicate ADR numeric prefix 0007", stderr)
        self.assertIn("0007-a.md", stderr)
        self.assertIn("0007-b.md", stderr)

    def test_product_git_mode_reads_the_product_gitignore(self) -> None:
        self.touch("0012-accepted.md")
        self.write_product_gitignore(f"/{DECISIONS_RELATIVE}/\n")

        hidden_result, _, hidden_stderr = self.run_product_git()

        self.assertEqual(hidden_result, 1)
        self.assertIn("invisible to product-git git", hidden_stderr)
        self.assertIn(".gitignore", hidden_stderr)

        self.write_product_gitignore("build/\n")
        visible_result, stdout, stderr = self.run_product_git()

        self.assertEqual(visible_result, 0, stderr)
        self.assertIn("every ADR file visible to product-git git", stdout)

    def test_side_history_exclude_does_not_decide_product_git_mode(self) -> None:
        # The two modes must interrogate different gits; a side-history exclude
        # that hides everything must not fail product-git mode.
        self.touch("0012-accepted.md")
        self.write_side_exclude(HIDE_EVERYTHING)

        product_result, _, _ = self.run_product_git()
        machine_result, _, _ = self.run_machine_local()

        self.assertEqual(product_result, 0)
        self.assertEqual(machine_result, 1)


class FailClosedTests(HarnessFixture):
    """Missing or ambiguous visibility mode must fail closed, never skip."""

    def test_missing_visibility_mode_fails_closed(self) -> None:
        self.touch("0012-accepted.md")
        self.write_side_exclude(DECISIONS_ALLOWLIST)

        result, stdout, stderr = run_main("--repo-root", str(self.work_tree))

        self.assertEqual(result, 2)
        self.assertIn("--visibility is required", stderr)
        self.assertIn("Refusing to guess", stderr)
        self.assertEqual(stdout, "")

    def test_missing_side_history_git_dir_fails_closed_instead_of_skipping(self) -> None:
        # The regression this guards: treating an absent `.harness-vcs` as
        # "nothing to check" is what let brand-new ADR files stay invisible.
        self.touch("0012-accepted.md")
        absent = self.work_tree / ".harness-vcs-absent"
        self.assertFalse(absent.exists())

        result, stdout, stderr = run_main(
            "--visibility",
            "machine-local",
            "--repo-root",
            str(self.work_tree),
            "--git-dir",
            str(absent),
        )

        self.assertEqual(result, 2)
        self.assertIn("not a directory", stderr)
        self.assertIn("not a reason to skip", stderr)
        self.assertNotIn("valid", stdout)
        self.assertEqual(stdout, "")

    def test_git_dir_with_product_git_mode_is_ambiguous_and_fails_closed(self) -> None:
        self.touch("0012-accepted.md")

        result, stdout, stderr = run_main(
            "--visibility",
            "product-git",
            "--repo-root",
            str(self.work_tree),
            "--git-dir",
            str(self.git_dir),
        )

        self.assertEqual(result, 2)
        self.assertIn("ambiguous", stderr)
        self.assertEqual(stdout, "")

    def test_product_git_mode_without_a_git_work_tree_fails_closed(self) -> None:
        outside = Path(self.tempdir.name) / "not-a-repo"
        (outside / DECISIONS_RELATIVE).mkdir(parents=True)
        (outside / DECISIONS_RELATIVE / "0012-accepted.md").write_text(
            "# adr\n", encoding="utf-8"
        )

        result, stdout, stderr = run_main(
            "--visibility",
            "product-git",
            "--repo-root",
            str(outside),
        )

        self.assertEqual(result, 2)
        self.assertIn("product-git visibility needs a git work tree", stderr)
        self.assertEqual(stdout, "")

    def test_unknown_visibility_mode_is_rejected_by_the_parser(self) -> None:
        with self.assertRaises(SystemExit) as raised, redirect_stderr(io.StringIO()):
            VALIDATOR.main(["--visibility", "guess"])

        self.assertEqual(raised.exception.code, 2)

    def test_missing_decisions_directory_fails_closed(self) -> None:
        result, _, stderr = run_main(
            "--visibility",
            "machine-local",
            "--repo-root",
            str(self.work_tree),
            "--git-dir",
            str(self.git_dir),
            "--decisions-dir",
            str(self.work_tree / "no-such-dir"),
        )

        self.assertEqual(result, 2)
        self.assertIn("ADR decisions directory not found", stderr)

    def test_decisions_directory_outside_the_work_tree_fails_closed(self) -> None:
        outside = Path(self.tempdir.name) / "elsewhere"
        outside.mkdir()
        (outside / "0012-accepted.md").write_text("# adr\n", encoding="utf-8")

        result, _, stderr = self.run_machine_local("--decisions-dir", str(outside))

        self.assertEqual(result, 2)
        self.assertIn("outside the machine-local work tree", stderr)


if __name__ == "__main__":
    unittest.main()
