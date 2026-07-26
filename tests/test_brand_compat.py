from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def load_validator_namespace() -> dict[str, object]:
    validator_path = ROOT / "scripts/validate_brand_compat.py"
    namespace: dict[str, object] = {"__name__": "validate_brand_compat_test"}
    exec(
        compile(
            validator_path.read_text(encoding="utf-8"),
            str(validator_path),
            "exec",
        ),
        namespace,
    )
    return namespace


class NeutralContractTests(unittest.TestCase):
    def test_registry_requires_truthful_brand_and_exempts_human_direct_harness(self) -> None:
        registry = read("overlay/spec/guides/agenttui-registry.md")

        self.assertIn("actual runtime brand", registry)
        self.assertIn("human-direct harness", registry)
        self.assertIn("must not be reported as unregistered", registry)

    def test_roles_and_execution_policy_enforce_same_brand_chain(self) -> None:
        roles = read("overlay/spec/guides/roles-and-tiering.md")
        execution = read("overlay/spec/guides/execution-policy.md")

        for text in (roles, execution):
            self.assertIn("effective_subagent_brand = impler.spec.brand", text)
            self.assertIn("brand mismatch", text)

    def test_neutral_registry_example_does_not_default_to_claude(self) -> None:
        spec = json.loads(
            read("overlay/arborist-templates/agents/example/spec.json")
        )
        runtime = json.loads(
            read("overlay/arborist-templates/agents/example/runtime.json")
        )

        self.assertEqual("<actual-brand>", spec["brand"])
        self.assertEqual("<absolute-session-file-for-actual-brand>", runtime["session_file"])


class VisibilityContractTests(unittest.TestCase):
    def test_codex_and_claude_visible_blocks_share_contract_id(self) -> None:
        agents_block = read("overlay/project-instructions/brand-compat.md")
        workflow_block = read("overlay/workflow-phase-index-brand-compat.md")

        contract_id = "ARBORIST-BRAND-COMPAT:v1"
        self.assertIn(contract_id, agents_block)
        self.assertIn(contract_id, workflow_block)
        for text in (agents_block, workflow_block):
            self.assertIn("brand=codex", text)
            self.assertIn("brand=claude-code", text)
            self.assertIn("same-brand", text)
            self.assertIn(
                "<REPO_ROOT>/.work_context/sendbox/_handoff-config.yaml",
                text,
            )
            self.assertIn(
                "Handoff and inherit MUST receive this absolute path explicitly",
                text,
            )

    def test_adopt_installs_both_visible_blocks(self) -> None:
        adopt = read("adopt.sh")

        self.assertIn("install-brand-compat.py", adopt)
        self.assertIn("overlay/project-instructions/brand-compat.md", adopt)
        self.assertIn("overlay/workflow-phase-index-brand-compat.md", adopt)


class ClaudeModelRoutingTests(unittest.TestCase):
    def _frontmatter_model(self, relative_path: str) -> str:
        text = read(relative_path)
        match = re.search(r"^model:\s*(\S+)\s*$", text, flags=re.MULTILINE)
        self.assertIsNotNone(match, relative_path)
        return match.group(1)

    def _frontmatter_tools(self, relative_path: str) -> tuple[str, ...]:
        text = read(relative_path)
        match = re.search(r"^tools:\s*(.+?)\s*$", text, flags=re.MULTILINE)
        self.assertIsNotNone(match, relative_path)
        return tuple(part.strip() for part in match.group(1).split(","))

    def test_full_implementation_is_pinned_to_opus(self) -> None:
        path = (
            "overlay/platform-templates/claude/agents/"
            "trellis-implement-full.md"
        )
        self.assertEqual("opus", self._frontmatter_model(path))
        self.assertEqual(
            ("Read", "Write", "Edit", "Bash", "Glob", "Grep"),
            self._frontmatter_tools(path),
        )

    def test_explore_is_pinned_to_sonnet(self) -> None:
        path = "overlay/platform-templates/claude/agents/trellis-explore.md"
        self.assertEqual("sonnet", self._frontmatter_model(path))
        tools = self._frontmatter_tools(path)
        self.assertEqual(("Read", "Bash", "Glob", "Grep"), tools)
        self.assertNotIn("Write", tools)
        self.assertNotIn("Edit", tools)

    def test_handoff_template_uses_sendbox_0_6_frontmatter(self) -> None:
        template = read(
            "overlay/work_context-templates/sendbox/_TEMPLATE-handoff.md"
        )
        self.assertIn("recipient_brand: <claude-code|codex>", template)
        self.assertIn("\nroute_policy:\n", template)
        for key in ("policy_id:", "lane:", "task_kind:", "agent:", "model:"):
            self.assertIn(key, template)
        recipients = template.split("recipient_brand:", 1)[0]
        self.assertNotIn("\n    brand:", recipients)

    def test_handoff_config_uses_sendbox_0_6_route_matrix(self) -> None:
        config = read(
            "overlay/work_context-templates/sendbox/_handoff-config.yaml"
        )
        namespace = load_validator_namespace()
        errors: list[str] = []
        namespace["validate_route_config"](config, errors)
        self.assertEqual([], errors)
        policies = namespace["parse_route_policies"](config, [])
        self.assertEqual(20, len(policies))
        policy_ids = [leaf["policy_id"] for leaf in policies.values()]
        self.assertEqual(len(policy_ids), len(set(policy_ids)))
        for (brand, _lane, _kind), leaf in policies.items():
            if brand == "codex":
                self.assertIsNone(leaf["agent"])
                self.assertIsNone(leaf["model"])
                self.assertNotRegex(
                    leaf["route_fragment"],
                    r"(?i)claude|sonnet|opus|trellis-",
                )
        self.assertNotIn("recipient_brand_required:", config)
        self.assertNotIn("brand_routes:", config)
        self.assertNotIn("CLAUDE_CODE_SUBAGENT_MODEL:", config)


class ValidatorTests(unittest.TestCase):
    def test_validator_source_exists_and_names_both_generation_paths(self) -> None:
        validator = read("scripts/validate_brand_compat.py")

        self.assertIn("codex", validator)
        self.assertIn("claude-code", validator)
        self.assertIn("ARBORIST-BRAND-COMPAT:v1", validator)

    def test_validator_rejects_unscoped_claude_routing(self) -> None:
        namespace = load_validator_namespace()
        errors: list[str] = []
        namespace["validate_unscoped_routes"](
            {"roles": "Implementation must always use Claude Code."},
            errors,
        )
        self.assertTrue(errors)
        errors = []
        namespace["validate_unscoped_routes"](
            {
                "roles": (
                    "For brand=claude-code, use the configured route; "
                    "all implementation must use Claude Code."
                )
            },
            errors,
        )
        self.assertTrue(errors)
        errors = []
        namespace["validate_unscoped_routes"](
            {
                "roles": (
                    "For brand=claude-code, implementation must always "
                    "use Claude Code."
                )
            },
            errors,
        )
        self.assertFalse(errors)

    def test_route_parser_allows_host_sections_before_and_after_brand_routing(
        self,
    ) -> None:
        config = read(
            "overlay/work_context-templates/sendbox/_handoff-config.yaml"
        )
        config_with_trailing_host_sections = (
            config
            + "\nsuggested_skills:\n"
            + "  - repo-memory\n"
            + "must_read_extra:\n"
            + "  - <REPO_ROOT>/docs/context.md\n"
            + "day1_template_mode_b: |\n"
            + "  - [ ] Read the inherited task context\n"
        )
        namespace = load_validator_namespace()
        errors: list[str] = []
        namespace["validate_route_config"](
            config_with_trailing_host_sections,
            errors,
        )
        self.assertEqual([], errors)


class SendboxCompatibilityFixtureTests(unittest.TestCase):
    def test_arborist_tokens_match_connected_sendbox_schema(self) -> None:
        cc_root_value = os.environ.get("CC_SENDBOX_ROOT")
        if not cc_root_value:
            self.skipTest("CC_SENDBOX_ROOT is not set")
        verbs_path = (
            Path(cc_root_value).resolve()
            / "skills/sendbox-protocol/verbs.md"
        )
        self.assertTrue(verbs_path.is_file(), verbs_path)
        verbs = verbs_path.read_text(encoding="utf-8")
        config = read(
            "overlay/work_context-templates/sendbox/_handoff-config.yaml"
        )
        template = read(
            "overlay/work_context-templates/sendbox/_TEMPLATE-handoff.md"
        )
        for token in (
            "brand_routing:",
            "task_executing_roles:",
            "supported_brands:",
            "same_brand_policy: strict",
            "route_policies:",
            "policy_id:",
            "route_fragment:",
            "agent:",
            "model:",
        ):
            self.assertIn(token, verbs)
            self.assertIn(token, config)
        for token in (
            "recipient_brand:",
            "route_policy:",
            "policy_id:",
            "lane:",
            "task_kind:",
            "agent:",
            "model:",
        ):
            self.assertIn(token, verbs)
            self.assertIn(token, template)


class InstallerSmokeTests(unittest.TestCase):
    def test_temp_repo_install_is_idempotent_and_preserves_user_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            workflow = target / ".trellis/workflow.md"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "# Workflow\n\n"
                "## Phase Index\n\n"
                "User-owned phase index note.\n\n"
                "## Phase 1: Plan\n\n"
                "User-owned phase one text.\n",
                encoding="utf-8",
            )
            agents = target / "AGENTS.md"
            agents.write_text(
                "User-owned preface.\n\n"
                "<!-- TRELLIS:START -->\n"
                "Trellis-owned instructions.\n"
                "<!-- TRELLIS:END -->\n\n"
                "User-owned suffix.\n",
                encoding="utf-8",
            )

            command = [
                sys.executable,
                str(ROOT / "scripts/install-brand-compat.py"),
                "--source-tree",
                str(ROOT),
                "--target-repo",
                str(target),
            ]
            first = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(0, first.returncode, first.stderr)
            second = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(0, second.returncode, second.stderr)

            agents_text = agents.read_text(encoding="utf-8")
            workflow_text = workflow.read_text(encoding="utf-8")
            self.assertEqual(
                1, agents_text.count("<!-- ARBORIST-BRAND-COMPAT:START -->")
            )
            self.assertEqual(
                1, workflow_text.count("<!-- ARBORIST-BRAND-COMPAT:START -->")
            )
            self.assertIn("User-owned preface.", agents_text)
            self.assertIn("User-owned suffix.", agents_text)
            self.assertIn("User-owned phase index note.", workflow_text)
            self.assertIn("User-owned phase one text.", workflow_text)
            expected_config_path = str(
                (target / ".work_context/sendbox/_handoff-config.yaml").resolve()
            )
            self.assertIn(expected_config_path, agents_text)
            self.assertIn(expected_config_path, workflow_text)
            self.assertNotIn("<REPO_ROOT>", agents_text)
            self.assertNotIn("<REPO_ROOT>", workflow_text)
            self.assertGreater(
                agents_text.index("<!-- ARBORIST-BRAND-COMPAT:START -->"),
                agents_text.index("<!-- TRELLIS:END -->"),
            )
            self.assertLess(
                workflow_text.index("<!-- ARBORIST-BRAND-COMPAT:START -->"),
                workflow_text.index("## Phase 1: Plan"),
            )
            self.assertTrue(
                (target / ".claude/agents/trellis-implement-full.md").is_file()
            )
            self.assertTrue((target / ".claude/agents/trellis-explore.md").is_file())

            check_result = subprocess.run(
                [*command, "--check"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, check_result.returncode, check_result.stderr)

            custom_agent = target / ".claude/agents/trellis-explore.md"
            custom_agent.write_text("User-owned custom agent.\n", encoding="utf-8")
            collision = subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(2, collision.returncode)
            self.assertIn("refusing to overwrite", collision.stderr)
            self.assertEqual(
                "User-owned custom agent.\n",
                custom_agent.read_text(encoding="utf-8"),
            )


class AdoptSmokeTests(unittest.TestCase):
    def test_adopt_copies_sources_and_installs_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            target = temp_root / "repo"
            home = temp_root / "home"
            (target / ".git/info").mkdir(parents=True)
            (target / ".git/info/exclude").write_text("", encoding="utf-8")
            (target / ".trellis").mkdir()
            (target / ".trellis/workflow.md").write_text(
                "# Workflow\n\n"
                "## Phase Index\n\n"
                "Existing index text.\n\n"
                "## Phase 1: Plan\n",
                encoding="utf-8",
            )
            home.mkdir()
            environment = os.environ.copy()
            environment["HOME"] = str(home)

            result = subprocess.run(
                ["bash", str(ROOT / "adopt.sh")],
                cwd=target,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((target / "scripts/install-brand-compat.py").is_file())
            self.assertTrue((target / "scripts/validate_brand_compat.py").is_file())
            self.assertTrue(
                (target / ".work_context/sendbox/_handoff-config.yaml").is_file()
            )
            self.assertIn(
                "ARBORIST-BRAND-COMPAT:v1",
                (target / "AGENTS.md").read_text(encoding="utf-8"),
            )

            target_config = (
                target / ".work_context/sendbox/_handoff-config.yaml"
            )
            target_config.write_text(
                target_config.read_text(encoding="utf-8")
                + "\nsuggested_skills:\n"
                + "  - repo-memory\n"
                + "must_read_extra:\n"
                + "  - <REPO_ROOT>/docs/context.md\n"
                + "day1_template_mode_b: |\n"
                + "  - [ ] Read the inherited task context\n",
                encoding="utf-8",
            )
            target_validation = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/validate_brand_compat.py"),
                    "--source-tree",
                    str(ROOT),
                    "--target-repo",
                    str(target),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                0,
                target_validation.returncode,
                target_validation.stderr,
            )

    def test_adopt_rejects_existing_legacy_handoff_config_without_overwrite(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            target = temp_root / "repo"
            home = temp_root / "home"
            (target / ".git/info").mkdir(parents=True)
            (target / ".git/info/exclude").write_text("", encoding="utf-8")
            (target / ".trellis").mkdir()
            (target / ".trellis/workflow.md").write_text(
                "# Workflow\n\n## Phase Index\n\n## Phase 1: Plan\n",
                encoding="utf-8",
            )
            sendbox = target / ".work_context/sendbox"
            sendbox.mkdir(parents=True)
            legacy_config = (
                "handoff:\n"
                "  recipient_brand_required: true\n"
                "brand_routes:\n"
                "  codex:\n"
                "    provider: codex\n"
            )
            config_path = sendbox / "_handoff-config.yaml"
            config_path.write_text(legacy_config, encoding="utf-8")
            home.mkdir()
            environment = os.environ.copy()
            environment["HOME"] = str(home)

            result = subprocess.run(
                ["bash", str(ROOT / "adopt.sh")],
                cwd=target,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("不兼容 cc-sendbox", result.stdout)
            self.assertEqual(
                legacy_config,
                config_path.read_text(encoding="utf-8"),
            )

    def test_adopt_rejects_partial_or_cross_brand_route_matrix(self) -> None:
        source_config = read(
            "overlay/work_context-templates/sendbox/_handoff-config.yaml"
        )
        cases = {
            "partial": (
                "brand_routing:\n"
                "  task_executing_roles:\n"
                "    - Impler\n"
                "    - SubOrche\n"
                "    - Reviewer\n"
                "  supported_brands:\n"
                "    - codex\n"
                "    - claude-code\n"
                "  same_brand_policy: strict\n"
                "  route_policies:\n"
                "    codex:\n",
                "route tuple matrix mismatch",
            ),
            "polluted": (
                source_config.replace("          agent: null", "          agent: codex", 1),
                "must use null agent/model",
            ),
        }
        for case_name, (invalid_config, expected_error) in cases.items():
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as temp_dir:
                temp_root = Path(temp_dir)
                target = temp_root / "repo"
                home = temp_root / "home"
                (target / ".git/info").mkdir(parents=True)
                (target / ".git/info/exclude").write_text("", encoding="utf-8")
                (target / ".trellis").mkdir()
                (target / ".trellis/workflow.md").write_text(
                    "# Workflow\n\n## Phase Index\n\n## Phase 1: Plan\n",
                    encoding="utf-8",
                )
                sendbox = target / ".work_context/sendbox"
                sendbox.mkdir(parents=True)
                config_path = sendbox / "_handoff-config.yaml"
                config_path.write_text(invalid_config, encoding="utf-8")
                home.mkdir()
                environment = os.environ.copy()
                environment["HOME"] = str(home)

                result = subprocess.run(
                    ["bash", str(ROOT / "adopt.sh")],
                    cwd=target,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn(expected_error, result.stderr)
                self.assertEqual(
                    invalid_config,
                    config_path.read_text(encoding="utf-8"),
                )


class TargetInstructionSurfaceTests(unittest.TestCase):
    def _adopt_target(self, temp_root: Path) -> Path:
        target = temp_root / "repo"
        home = temp_root / "home"
        (target / ".git/info").mkdir(parents=True)
        (target / ".git/info/exclude").write_text("", encoding="utf-8")
        (target / ".trellis").mkdir()
        (target / ".trellis/workflow.md").write_text(
            "# Workflow\n\n## Phase Index\n\n## Phase 1: Plan\n",
            encoding="utf-8",
        )
        home.mkdir()
        environment = os.environ.copy()
        environment["HOME"] = str(home)
        result = subprocess.run(
            ["bash", str(ROOT / "adopt.sh")],
            cwd=target,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return target

    def _validate_target(self, target: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/validate_brand_compat.py"),
                "--source-tree",
                str(ROOT),
                "--target-repo",
                str(target),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_target_validator_rejects_unscoped_claude_route_in_agents(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = self._adopt_target(Path(temp_dir))
            agents = target / "AGENTS.md"
            agents.write_text(
                agents.read_text(encoding="utf-8")
                + "\nAll implementation must use Claude Code.\n",
                encoding="utf-8",
            )
            result = self._validate_target(target)
            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "adopted target AGENTS.md",
                result.stderr,
            )
            self.assertIn("unscoped Claude routing clause", result.stderr)

    def test_target_validator_rejects_unscoped_claude_route_in_workflow(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = self._adopt_target(Path(temp_dir))
            workflow = target / ".trellis/workflow.md"
            workflow.write_text(
                workflow.read_text(encoding="utf-8") + "\n实现一律 Claude Code。\n",
                encoding="utf-8",
            )
            result = self._validate_target(target)
            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "adopted target .trellis/workflow.md",
                result.stderr,
            )
            self.assertIn("unscoped Claude routing clause", result.stderr)


if __name__ == "__main__":
    unittest.main()
