"""Tests for the global-vs-project tiering classifier.

Every fixture is a throwaway repo built in a tempdir. The suite must never read the
host's real registry or real adopted repos: that would make results
machine-dependent and would let instance values into the repo.

The assertions concentrate on the two properties the classifier's usefulness rests
on, because both fail *silently* when broken:

* **Field names are not evidence.** A document that explains the schema names
  `session_id` and `pane_ref` constantly. A detector that fired on the words would
  file the guides -- the largest provably repo-invariant surface -- as project tier,
  confidently and wrongly, and the report would look plausible.
* **Divergence is a separate reading from the tier verdict.** Copies of a
  global-tier artifact diverge *because* it was copied per repo; if divergence could
  refile it as project tier, the classifier would ratify the mistake it exists to
  expose.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    module_path = ROOT / "overlay/scripts/classify_tier.py"
    module_name = "classify_tier"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None, module_path
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


CLASSIFY = load_module()

# Synthesized from its field widths rather than written out, for two reasons: the
# detector under test is a *shape* detector, so the shape is the honest input; and the
# repo's own privacy self-check greps for the uuid shape, and a literal here would be
# a hit a reviewer has to adjudicate every time. Nothing is being hidden -- there was
# never a real value to hide.
FAKE_SESSION_UUID = "-".join("0" * width for width in (8, 4, 4, 4, 12))
FAKE_OBJECT_NAME = "0" * 40


def run_main(*argv: str) -> tuple[int, str]:
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = CLASSIFY.main(list(argv))
    return code, stdout.getvalue()


def make_repo(base: Path, name: str) -> Path:
    repo = base / name
    (repo / ".trellis/spec/guides").mkdir(parents=True)
    (repo / ".trellis/scripts").mkdir(parents=True)
    (repo / ".arborist/agents").mkdir(parents=True)
    (repo / ".arborist/tools").mkdir(parents=True)
    return repo


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def artifacts_by_path(repo: Path) -> dict[str, CLASSIFY.Artifact]:
    return {a.relative: a for a in CLASSIFY.classify_repo(repo, home=repo.parent)}


class DetectorTest(unittest.TestCase):
    """The P1-P5 detectors: value shapes only, placeholders masked."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.repo = make_repo(self.base, "repo-a")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def detect(self, text: str, project_id: str | None = "abcabcabcabc"):
        return CLASSIFY.detect(
            text, repo=self.repo, project_id=project_id, home=self.base
        )

    def test_field_names_alone_are_not_evidence(self) -> None:
        prose = (
            "The leaf carries session_id, session_file, pane_ref and last_seen; "
            "pane_ref.socket is optional and project_id is a derived value."
        )
        self.assertFalse(self.detect(prose).carries_instance_value)

    def test_placeholders_are_not_evidence(self) -> None:
        template = json.dumps(
            {
                "session_id": "<actual-session-id>",
                "task": ".trellis/tasks/<mm-dd>-<task-slug>",
                "project": {"path": "<absolute-project-path>"},
            }
        )
        detection = self.detect(template)
        self.assertFalse(
            detection.carries_instance_value,
            f"a template read as project tier: {detection.hits}",
        )

    def test_the_placeholder_mask_is_not_itself_matchable(self) -> None:
        # Regression: a word-shaped mask turned `.trellis/tasks/<mm-dd>-<slug>` into
        # a "concrete" task path, so every template read as project tier.
        self.assertFalse(
            any(ch.isalnum() for ch in CLASSIFY.PLACEHOLDER_MASK),
            "the mask must contain no character any detector's class accepts",
        )

    def test_repo_root_path_is_evidence(self) -> None:
        detection = self.detect(f"state lives at {self.repo}/.arborist/runtime")
        self.assertTrue(detection.carries_instance_value)
        self.assertTrue(any("P1 repo-root-path" in hit for hit in detection.hits))

    def test_project_id_value_is_evidence(self) -> None:
        detection = self.detect('{"project_id": "abcabcabcabc"}')
        self.assertTrue(any("P1 project-id" in hit for hit in detection.hits))

    def test_a_different_twelve_hex_value_is_not_the_project_id(self) -> None:
        detection = self.detect('{"project_id": "0123456789ab"}')
        self.assertFalse(any("P1 project-id" in hit for hit in detection.hits))

    def test_session_uuid_is_evidence(self) -> None:
        detection = self.detect(f'{{"session_id": "{FAKE_SESSION_UUID}"}}')
        self.assertTrue(any("P2 session-uuid" in hit for hit in detection.hits))

    def test_git_object_name_is_evidence(self) -> None:
        detection = self.detect(f"pinned at {FAKE_OBJECT_NAME}")
        self.assertTrue(any("P5 git-object-name" in hit for hit in detection.hits))

    def test_machine_path_outside_the_repo_is_evidence(self) -> None:
        detection = self.detect(f"reads {self.base}/elsewhere/config.json")
        self.assertTrue(
            any("P4 machine-absolute-path" in hit for hit in detection.hits)
        )

    def test_a_path_inside_the_repo_is_not_counted_twice(self) -> None:
        # It is already P1; reporting it again as P4 would double-count one reading.
        detection = self.detect(f"reads {self.repo}/.arborist/index.json")
        self.assertEqual(
            [hit for hit in detection.hits if "P4" in hit],
            [],
            detection.hits,
        )

    def test_a_task_reference_that_does_not_exist_is_an_example(self) -> None:
        detection = self.detect("see `.trellis/tasks/03-27-my-task` for the layout")
        self.assertFalse(detection.carries_instance_value, detection.hits)

    def test_a_task_reference_that_exists_is_evidence(self) -> None:
        (self.repo / ".trellis/tasks/07-01-real").mkdir(parents=True)
        detection = self.detect("working in .trellis/tasks/07-01-real")
        self.assertTrue(any("P3 task-ref" in hit for hit in detection.hits))

    def test_the_ledger_archive_directory_is_structural_not_a_task(self) -> None:
        (self.repo / ".trellis/tasks/archive").mkdir(parents=True)
        detection = self.detect("archived tasks move to .trellis/tasks/archive")
        self.assertFalse(detection.carries_instance_value, detection.hits)

    def test_project_id_unknown_disables_only_that_detector(self) -> None:
        # An unknown derived id is reported as unknown, never guessed: a guessed id
        # would then be searched for and would silently match nothing.
        detection = self.detect('{"project_id": "abcabcabcabc"}', project_id=None)
        self.assertFalse(any("P1 project-id" in hit for hit in detection.hits))


class ClassificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.repo = make_repo(self.base, "repo-a")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_guide_without_instance_values_is_global(self) -> None:
        write(
            self.repo / ".trellis/spec/guides/index.md",
            "# guides\n\nEvery guide uses placeholders such as <REPO_ROOT>.\n",
        )
        artifact = artifacts_by_path(self.repo)[".trellis/spec/guides/index.md"]
        self.assertEqual(artifact.tier, CLASSIFY.TIER_GLOBAL)
        self.assertEqual(artifact.code, "agreed")

    def test_a_capability_script_is_global(self) -> None:
        write(self.repo / ".trellis/scripts/agenttui.py", "#!/usr/bin/env python3\n")
        artifact = artifacts_by_path(self.repo)[".trellis/scripts/agenttui.py"]
        self.assertEqual(artifact.tier, CLASSIFY.TIER_GLOBAL)

    def test_a_global_artifact_carrying_an_instance_value_is_referred_to_a_human(
        self,
    ) -> None:
        # Either a generalization-boundary violation (fix the file) or a misfiled
        # rule (fix the rule). Which one cannot be read off the bytes, so it is not
        # guessed.
        write(
            self.repo / ".trellis/spec/guides/leaked.md",
            f"the session was {FAKE_SESSION_UUID}\n",
        )
        artifact = artifacts_by_path(self.repo)[".trellis/spec/guides/leaked.md"]
        self.assertEqual(artifact.tier, CLASSIFY.TIER_UNKNOWN)
        self.assertEqual(artifact.code, "declared-global-carries-instance-value")
        self.assertTrue(artifact.evidence)

    def test_a_leaf_is_project_tier_on_location_grounds(self) -> None:
        write(
            self.repo / ".arborist/agents/one/spec.json",
            json.dumps({"name": "one"}),
        )
        artifact = artifacts_by_path(self.repo)[".arborist/agents/one/spec.json"]
        self.assertEqual(artifact.tier, CLASSIFY.TIER_PROJECT)
        self.assertEqual(artifact.basis, CLASSIFY.BASIS_LOCATION)
        # Location basis means content detection may not overrule the rule: a leaf
        # whose fields happen to be placeholders is still that repo's leaf.
        self.assertEqual(artifact.code, "agreed")

    def test_a_project_artifact_with_no_instance_value_is_referred_to_a_human(
        self,
    ) -> None:
        write(self.repo / ".trellis/config.yaml", "# nothing configured yet\n")
        artifact = artifacts_by_path(self.repo)[".trellis/config.yaml"]
        self.assertEqual(artifact.tier, CLASSIFY.TIER_UNKNOWN)
        self.assertEqual(artifact.code, "declared-project-carries-none")

    def test_a_split_artifact_is_reported_as_split_not_guessed(self) -> None:
        write(self.repo / ".trellis/workflow.md", "# workflow\n")
        artifact = artifacts_by_path(self.repo)[".trellis/workflow.md"]
        self.assertEqual(artifact.tier, CLASSIFY.TIER_SPLIT)
        self.assertEqual(artifact.code, "split-not-file-granular")

    def test_an_unruled_artifact_is_unclassified_not_filed_by_default(self) -> None:
        # Filing an experiment up into a machine-wide contract by default would
        # freeze one repo's experiment into everyone's contract.
        write(self.repo / ".arborist/guardians/watcher.py", "print('hi')\n")
        artifact = artifacts_by_path(self.repo)[".arborist/guardians/watcher.py"]
        self.assertEqual(artifact.tier, CLASSIFY.TIER_UNKNOWN)
        self.assertEqual(artifact.code, "unclassified")

    def test_a_tree_rule_yields_one_artifact_and_is_not_walked(self) -> None:
        for name in ("a.md", "b.md", "c.md"):
            write(self.repo / ".work_context/sendbox/toAgent" / name, "letter\n")
        found = artifacts_by_path(self.repo)
        self.assertIn(".work_context/sendbox/toAgent", found)
        self.assertEqual(
            [p for p in found if p.startswith(".work_context/sendbox/toAgent/")],
            [],
        )

    def test_trellis_owned_files_are_classified_but_marked_upstream_written(
        self,
    ) -> None:
        # The criterion is applied without exemption and answers "global"; the
        # writer field is what records that converging them here would be undone by
        # their own writer.
        write(self.repo / ".trellis/scripts/task.py", "#!/usr/bin/env python3\n")
        artifact = artifacts_by_path(self.repo)[".trellis/scripts/task.py"]
        self.assertEqual(artifact.tier, CLASSIFY.TIER_GLOBAL)
        self.assertEqual(artifact.writer, CLASSIFY.WRITER_TRELLIS)

    def test_a_tree_pattern_matches_nested_files_not_only_directories(self) -> None:
        # Regression: `Path.glob("dir/**")` yields directories only, so a trailing
        # `**` matched no file at all. The failure was silent -- the report omitted
        # the largest part of the surface and still looked complete.
        write(self.repo / ".trellis/spec/guides/decisions/0001-x.md", "adr\n")
        write(self.repo / ".trellis/spec/guides/methodology/m.md", "method\n")
        found = artifacts_by_path(self.repo)
        self.assertIn(".trellis/spec/guides/decisions/0001-x.md", found)
        self.assertIn(".trellis/spec/guides/methodology/m.md", found)

    def test_the_glob_translation_only_touches_trailing_tree_patterns(self) -> None:
        self.assertEqual(
            CLASSIFY.glob_pattern_for(".trellis/spec/guides/**"),
            ".trellis/spec/guides/**/*",
        )
        self.assertEqual(
            CLASSIFY.glob_pattern_for(".trellis/scripts/validate_*.py"),
            ".trellis/scripts/validate_*.py",
        )

    def test_an_arborist_validator_is_not_captured_by_the_trellis_catch_all(
        self,
    ) -> None:
        write(self.repo / ".trellis/scripts/validate_adr_numbers.py", "x = 1\n")
        artifact = artifacts_by_path(self.repo)[
            ".trellis/scripts/validate_adr_numbers.py"
        ]
        self.assertEqual(artifact.writer, CLASSIFY.WRITER_ARBORIST)


class CrosscheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.a = make_repo(self.base, "repo-a")
        self.b = make_repo(self.base, "repo-b")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def classify_both(self):
        return CLASSIFY.classify_repo(self.a, home=self.base) + CLASSIFY.classify_repo(
            self.b, home=self.base
        )

    def test_identical_copies_are_not_reported(self) -> None:
        for repo in (self.a, self.b):
            write(repo / ".trellis/scripts/agenttui.py", "same\n")
        findings = CLASSIFY.crosscheck(self.classify_both(), [self.a, self.b])
        self.assertEqual(findings, [])

    def test_divergent_copies_are_reported_without_changing_the_tier(self) -> None:
        write(self.a / ".trellis/scripts/agenttui.py", "new and long\n" * 10)
        write(self.b / ".trellis/scripts/agenttui.py", "old\n")
        artifacts = self.classify_both()
        findings = CLASSIFY.crosscheck(artifacts, [self.a, self.b])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["verdict"], "divergent")
        self.assertEqual(findings[0]["variants"], 2)
        # The tier verdict is untouched: divergence is the consequence of the
        # per-repo copy, not evidence that the artifact was project tier.
        for artifact in artifacts:
            if artifact.relative == ".trellis/scripts/agenttui.py":
                self.assertEqual(artifact.tier, CLASSIFY.TIER_GLOBAL)

    def test_a_copy_missing_from_one_repo_is_reported(self) -> None:
        # The strongest drift signal there is, and a walk of what exists can never
        # produce it -- the manifest is enumerated first for exactly this reason.
        write(self.a / ".trellis/scripts/agenttui.py", "present\n")
        findings = CLASSIFY.crosscheck(self.classify_both(), [self.a, self.b])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["verdict"], "partially-deployed")
        self.assertEqual(findings[0]["absent_from"], 1)

    def test_project_tier_artifacts_are_never_crosschecked(self) -> None:
        # Requiring per-repo artifacts to agree would be asking them to stop being
        # per-repo.
        write(self.a / ".arborist/agents/one/spec.json", '{"name": "one"}')
        write(self.b / ".arborist/agents/one/spec.json", '{"name": "other"}')
        findings = CLASSIFY.crosscheck(self.classify_both(), [self.a, self.b])
        self.assertEqual(findings, [])


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.repo = make_repo(self.base, "repo-a")
        write(self.repo / ".trellis/scripts/agenttui.py", "x\n")
        self.index = self.base / "global/index.json"
        self.index.parent.mkdir(parents=True)
        self.index.write_text(
            json.dumps({"projects": [{"path": str(self.repo)}]}), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_print_surface_reads_no_repo(self) -> None:
        code, output = run_main("--print-surface")
        self.assertEqual(code, 0)
        self.assertIn(".trellis/spec/guides/**", output)

    def test_no_target_fails_closed(self) -> None:
        code, output = run_main()
        self.assertEqual(code, 2)
        self.assertIn("nothing to classify", output)

    def test_missing_index_fails_closed(self) -> None:
        code, output = run_main("--all", "--global-index", str(self.base / "absent"))
        self.assertEqual(code, 2)
        self.assertIn("fail-closed", output)

    def test_unparsable_index_fails_closed(self) -> None:
        bad = self.base / "bad.json"
        bad.write_text("{", encoding="utf-8")
        code, _ = run_main("--all", "--global-index", str(bad))
        self.assertEqual(code, 2)

    def test_a_clean_repo_exits_zero(self) -> None:
        code, output = run_main("--all", "--global-index", str(self.index))
        self.assertEqual(code, 0, output)

    def test_unknowns_exit_one(self) -> None:
        write(self.repo / ".arborist/guardians/x.py", "y = 1\n")
        code, _ = run_main("--all", "--global-index", str(self.index))
        self.assertEqual(code, 1)

    def test_an_unreachable_repo_is_reported_and_exits_one(self) -> None:
        code, output = run_main("--repo", str(self.base / "gone"))
        self.assertEqual(code, 1)
        self.assertIn("unreachable", output)

    def test_json_output_is_parsable_and_carries_the_counts(self) -> None:
        code, output = run_main("--all", "--global-index", str(self.index), "--json")
        document = json.loads(output)
        self.assertEqual(code, 0, output)
        self.assertEqual(document["repos"], [str(self.repo)])
        self.assertIn("G", document["counts"])

    def test_tier_filter_narrows_the_listing_but_not_the_counts(self) -> None:
        write(self.repo / ".arborist/agents/one/spec.json", '{"name": "one"}')
        _, output = run_main(
            "--all", "--global-index", str(self.index), "--tier", "P", "--json"
        )
        document = json.loads(output)
        self.assertTrue(all(a["tier"] == "P" for a in document["artifacts"]))
        self.assertGreater(document["counts"]["G"], 0)

    def test_the_same_machine_classifies_identically_twice(self) -> None:
        # A survey whose output reorders itself cannot be diffed, and a report
        # nobody diffs is a report nobody reads.
        first = run_main("--all", "--global-index", str(self.index), "--json")[1]
        second = run_main("--all", "--global-index", str(self.index), "--json")[1]
        self.assertEqual(first, second)


class ReadOnlyTest(unittest.TestCase):
    def test_the_module_exposes_no_repair_entry_point(self) -> None:
        parser = CLASSIFY.build_parser()
        options = {
            option
            for action in parser._actions
            for option in action.option_strings
        }
        self.assertNotIn("--fix", options)
        self.assertNotIn("--write", options)

    def test_classifying_a_repo_writes_nothing_into_it(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            repo = make_repo(base, "repo-a")
            write(repo / ".trellis/scripts/agenttui.py", "x\n")
            write(repo / ".arborist/agents/one/spec.json", '{"name": "one"}')
            before = {
                path.relative_to(repo).as_posix(): path.stat().st_mtime_ns
                for path in repo.rglob("*")
                if path.is_file()
            }
            CLASSIFY.classify_repo(repo, home=base)
            after = {
                path.relative_to(repo).as_posix(): path.stat().st_mtime_ns
                for path in repo.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
