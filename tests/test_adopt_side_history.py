from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

LEGACY_EXCLUDE = "/*\n"
BLOCK_BEGIN_MARKER = ">>> Arborist harness-vcs allowlist"

# 很多产品仓（含 Arborist 自己的仓）把 harness 目录写进【已跟踪】的根 .gitignore 以防误提交。
# gitignore 优先级是源级的：per-directory .gitignore 严格压过 $GIT_DIR/info/exclude，而侧史的
# work-tree 就是产品仓根 → 这种配置下侧史 allowlist 完全失效（`.trellis/` 带尾斜杠还会终止
# 目录遍历，底下的 negation 一律救不回来）。这是 git 语义，不是我们能绕过的 bug。
HARNESS_GITIGNORE = ".trellis/\nAGENTS.md\n.claude/\n.work_context/\n.arborist/\n"

# baseline / snapshot 都不得钉的运行时机器态（exclude 只管未跟踪文件 —— 钉上就再也隐不回去）。
RUNTIME_STATE = (
    ".trellis/tasks/07-01-sample/prd.md",
    ".trellis/workspace/active.json",
    ".arborist/agents/zz-session/runtime.json",
    ".work_context/Dashboard/index.md",
)
CREDENTIAL = ".work_context/multica.env"


def write(path: Path, text: str = "placeholder\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_target(
    temp_root: Path,
    gitignore: str | None = None,
) -> tuple[Path, dict[str, str]]:
    """造一个最小可 adopt 的产品仓（真 git 仓 + .trellis 骨架 + 隔离的 HOME）。

    gitignore 非空时写入根 `.gitignore` 并【提交】—— 模拟把 harness 目录列进 tracked
    .gitignore 的产品仓（侧史 allowlist 在这种仓里失效）。
    另外预置运行时机器态与凭证 env，好让 baseline force-add 面本身被断言覆盖。
    """
    target = temp_root / "repo"
    home = temp_root / "home"
    target.mkdir(parents=True)
    home.mkdir()
    subprocess.run(
        ["git", "init", "-q", "."],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
    )
    (target / ".trellis").mkdir()
    (target / ".trellis/workflow.md").write_text(
        "# Workflow\n\n## Phase Index\n\nExisting index text.\n\n## Phase 1: Plan\n",
        encoding="utf-8",
    )
    for relative_path in RUNTIME_STATE:
        write(target / relative_path, "{}\n")
    write(target / CREDENTIAL, "MULTICA_WORKSPACE_ID=<placeholder>\n")
    if gitignore is not None:
        (target / ".gitignore").write_text(gitignore, encoding="utf-8")
        subprocess.run(
            ["git", "add", ".gitignore"],
            cwd=target,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=product",
                "-c",
                "user.email=product@localhost",
                "commit",
                "-q",
                "-m",
                "product: ignore harness overlay",
            ],
            cwd=target,
            check=True,
            capture_output=True,
            text=True,
        )
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    return target, environment


def run_adopt(target: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ROOT / "adopt.sh")],
        cwd=target,
        env=environment,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )


def hgit(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            f"--git-dir={target / '.harness-vcs'}",
            f"--work-tree={target}",
            *args,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def hgit_cli(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """走真实入口 ./hgit（覆盖 snapshot 子命令的派发与 root 解析）。"""
    return subprocess.run(
        ["bash", str(target / "hgit"), *args],
        cwd=target,
        text=True,
        capture_output=True,
        check=False,
    )


def side_history_untracked(target: Path) -> set[str]:
    """侧史里【未跟踪但可见】的路径集合（-uall：不折叠成目录，逐文件列）。"""
    result = hgit(target, "status", "--porcelain", "-uall")
    assert result.returncode == 0, result.stderr
    return {
        line[3:]
        for line in result.stdout.splitlines()
        if line.startswith("?? ")
    }


def side_history_tracked(target: Path) -> list[str]:
    listing = hgit(target, "ls-files")
    assert listing.returncode == 0, listing.stderr
    return listing.stdout.splitlines()


class SideHistoryVisibilityTests(unittest.TestCase):
    """新 adopter：durable 面的未跟踪新文件必须对 hgit 现形，运行时/缓存面必须继续隐身。"""

    temp_dir: tempfile.TemporaryDirectory[str]
    target: Path
    adopt_stdout: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        target, environment = make_target(Path(cls.temp_dir.name))
        result = run_adopt(target, environment)
        assert result.returncode == 0, result.stderr
        cls.adopt_stdout = result.stdout
        cls.target = target

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    def assertVisible(self, relative_path: str) -> None:
        self.assertIn(
            relative_path,
            side_history_untracked(self.target),
            f"{relative_path} 应对 hgit status 可见（durable 面不得被 exclude 吞掉）",
        )

    def assertHidden(self, relative_path: str) -> None:
        self.assertNotIn(
            relative_path,
            side_history_untracked(self.target),
            f"{relative_path} 应继续隐身（运行时/缓存/产品面不进侧史）",
        )

    def test_baseline_commit_exists(self) -> None:
        log = hgit(self.target, "log", "--oneline")
        self.assertEqual(0, log.returncode, log.stderr)
        self.assertEqual(1, len(log.stdout.splitlines()))
        self.assertIn("baseline", log.stdout)

    def test_no_suppression_warning_without_product_gitignore(self) -> None:
        # 产品仓没把 harness 目录写进 .gitignore → allowlist 生效 → 不该报压制。
        self.assertNotIn("untracked 可见性被产品仓 .gitignore 压制", self.adopt_stdout)

    def test_untracked_new_guide_is_visible(self) -> None:
        write(self.target / ".trellis/spec/guides/zz-fresh-guide.md", "# fresh guide\n")
        self.assertVisible(".trellis/spec/guides/zz-fresh-guide.md")

    def test_untracked_new_adr_under_decisions_is_visible(self) -> None:
        write(
            self.target / ".trellis/spec/guides/decisions/0099-fresh-decision.md",
            "# ADR-0099\n",
        )
        self.assertVisible(".trellis/spec/guides/decisions/0099-fresh-decision.md")

    def test_untracked_durable_script_is_visible(self) -> None:
        write(self.target / ".trellis/scripts/zz_fresh_tool.py", "value = 1\n")
        self.assertVisible(".trellis/scripts/zz_fresh_tool.py")

    def test_untracked_package_spec_layer_is_visible(self) -> None:
        write(self.target / ".trellis/spec/sample-pkg/api/contracts.md", "# contract\n")
        self.assertVisible(".trellis/spec/sample-pkg/api/contracts.md")

    def test_untracked_project_tool_entry_is_visible(self) -> None:
        write(self.target / ".arborist/tools/zz-local-tool.json", "{}\n")
        self.assertVisible(".arborist/tools/zz-local-tool.json")

    def test_untracked_sendbox_letter_is_visible(self) -> None:
        # sendbox.md §持久化与可见性 规范要求「hgit add <file> 按文件」——新信被 exclude
        # 吞掉就执行不了那条指令（得 -f）。信是原始 durable 记录，必须现形。
        write(
            self.target / ".work_context/sendbox/toAgent/toGardener/from-zz-fresh-fyi.md",
            "# fresh letter\n",
        )
        self.assertVisible(
            ".work_context/sendbox/toAgent/toGardener/from-zz-fresh-fyi.md"
        )

    def test_credential_env_files_never_enter_side_history(self) -> None:
        # hook 配置经 env 文件下发（workspace/project id、token）。侧史是本机可读态 →
        # 凭证既不得对 status 现形，也不得被 baseline force-add 钉成 tracked（钉上就隐不回去）。
        # 该 env 在 adopt【之前】就已存在（make_target 预置），故这里真的在考 baseline 那一步。
        self.assertHidden(CREDENTIAL)
        self.assertEqual(
            [],
            [path for path in side_history_tracked(self.target) if path.endswith(".env")],
            "baseline force-add 不得把凭证 env 钉进侧史",
        )

    def test_runtime_and_cache_surfaces_stay_hidden(self) -> None:
        write(self.target / ".trellis/scripts/__pycache__/zz_cached.pyc", "junk\n")
        write(self.target / ".trellis/spec/guides/index.md.bak", "old\n")
        write(self.target / "zz_product_source.py", "print(1)\n")
        write(self.target / ".work_context/Dashboard/zz-scratch.md", "# scratch\n")
        for hidden in (
            ".trellis/scripts/__pycache__/zz_cached.pyc",
            ".trellis/spec/guides/index.md.bak",
            "zz_product_source.py",
            ".work_context/Dashboard/zz-scratch.md",
            *RUNTIME_STATE,
        ):
            with self.subTest(path=hidden):
                self.assertHidden(hidden)

    def test_baseline_tracks_whole_durable_surface(self) -> None:
        tracked = side_history_tracked(self.target)
        for required in (
            ".trellis/workflow.md",
            ".trellis/spec/guides/index.md",
            ".trellis/scripts/agenttui.py",
            ".trellis/scripts/arborist_brand_capacity.py",
            ".trellis/scripts/validate_adr_numbers.py",
            ".trellis/scripts/validate_harness_persistence.py",
            ".trellis/scripts/validate_claim_provenance.py",
            "AGENTS.md",
            "hgit",
            "scripts/trellis_multica_sync.py",
            "scripts/install-brand-compat.py",
            "scripts/validate_brand_compat.py",
            # BLOCKER 2 回归见证：`:(exclude)` 配带目录前缀的正向 pathspec 会静默丢文件，
            # 旧 force-add 让这两个 agent 定义根本没进侧史 → ./hgit checkout 回滚拿不回它们。
            ".claude/agents/trellis-explore.md",
            ".claude/agents/trellis-implement-full.md",
        ):
            with self.subTest(path=required):
                self.assertIn(required, tracked)

    def test_baseline_does_not_pin_runtime_state_or_noise(self) -> None:
        # MAJOR 2：整面 force-add `.trellis` / `.work_context` 会把运行时机器态钉成 tracked，
        # 和 exclude 里「运行时态照旧隐身 / Dashboard 继续隐身」的承诺直接冲突。durable 白名单
        # 收窄后二者一致 —— 这条就是那份一致性的见证。
        tracked = side_history_tracked(self.target)
        for forbidden in RUNTIME_STATE:
            with self.subTest(path=forbidden):
                self.assertNotIn(forbidden, tracked)
        noisy = [
            path
            for path in tracked
            if path.endswith((".pyc", ".pyo", ".bak", ".env")) or "__pycache__/" in path
        ]
        self.assertEqual([], noisy, "force-add 不得把缓存/备份/凭证钉成 tracked（钉上就再也隐不回去）")


class SnapshotTests(unittest.TestCase):
    """`./hgit snapshot`：不依赖 untracked 可见性的显式 durable 捕获面。"""

    temp_dir: tempfile.TemporaryDirectory[str]
    target: Path
    dry_run: subprocess.CompletedProcess[str]
    snapshot: subprocess.CompletedProcess[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        target, environment = make_target(Path(cls.temp_dir.name))
        result = run_adopt(target, environment)
        assert result.returncode == 0, result.stderr
        # 新建一批 durable 文件 + 一批必须被剔掉的噪声，然后显式快照。
        write(target / ".trellis/spec/guides/zz-fresh-guide.md", "# fresh guide\n")
        write(target / ".trellis/spec/guides/decisions/0099-fresh.md", "# ADR-0099\n")
        write(target / ".arborist/tools/zz-local-tool.json", "{}\n")
        write(target / ".work_context/sendbox/toAgent/toGardener/from-zz-fyi.md", "# hi\n")
        write(target / ".trellis/scripts/zz_fresh_tool.py", "value = 1\n")
        write(target / ".trellis/scripts/__pycache__/zz_cached.pyc", "junk\n")
        write(target / ".trellis/spec/guides/index.md.bak", "old\n")
        write(target / ".arborist/tools/secrets.env", "TOKEN=<placeholder>\n")
        cls.dry_run = hgit_cli(target, "snapshot", "--dry-run")
        cls.dry_run_staged = hgit(target, "diff", "--cached", "--name-only").stdout
        cls.snapshot = hgit_cli(target, "snapshot")
        cls.target = target

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    def test_snapshot_succeeds(self) -> None:
        self.assertEqual(0, self.snapshot.returncode, self.snapshot.stderr)
        self.assertEqual(0, self.dry_run.returncode, self.dry_run.stderr)
        self.assertIn("已暂存", self.snapshot.stdout)

    def test_dry_run_lists_without_touching_index(self) -> None:
        self.assertIn("将暂存", self.dry_run.stdout)
        self.assertIn(".trellis/spec/guides/zz-fresh-guide.md", self.dry_run.stdout)
        self.assertNotIn("已暂存", self.dry_run.stdout)
        self.assertEqual("", self.dry_run_staged, "--dry-run 不得改动 index")

    def test_snapshot_captures_new_durable_files(self) -> None:
        tracked = side_history_tracked(self.target)
        for required in (
            ".trellis/spec/guides/zz-fresh-guide.md",
            ".trellis/spec/guides/decisions/0099-fresh.md",
            ".arborist/tools/zz-local-tool.json",
            ".work_context/sendbox/toAgent/toGardener/from-zz-fyi.md",
            ".trellis/scripts/zz_fresh_tool.py",
        ):
            with self.subTest(path=required):
                self.assertIn(required, tracked)

    def test_snapshot_never_pins_credentials_runtime_state_or_noise(self) -> None:
        tracked = side_history_tracked(self.target)
        for forbidden in (
            CREDENTIAL,
            ".arborist/tools/secrets.env",
            ".trellis/scripts/__pycache__/zz_cached.pyc",
            ".trellis/spec/guides/index.md.bak",
            *RUNTIME_STATE,
        ):
            with self.subTest(path=forbidden):
                self.assertNotIn(forbidden, tracked)

    def test_snapshot_reports_what_it_dropped(self) -> None:
        self.assertIn("剔除", self.snapshot.stdout)
        self.assertIn(".arborist/tools/secrets.env", self.snapshot.stdout)

    def test_snapshot_rejects_unknown_arguments(self) -> None:
        result = hgit_cli(self.target, "snapshot", "--force-everything")
        self.assertEqual(2, result.returncode)
        self.assertIn("未知参数", result.stderr)

    def test_plain_subcommands_still_pass_through(self) -> None:
        result = hgit_cli(self.target, "log", "--oneline")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("baseline", result.stdout)


class TrackedGitignoreSuppressionTests(unittest.TestCase):
    """产品仓 tracked .gitignore 列了 harness 目录：allowlist 失效 → 必须告警 + 显式快照兜底。"""

    temp_dir: tempfile.TemporaryDirectory[str]
    target: Path
    adopt: subprocess.CompletedProcess[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        target, environment = make_target(
            Path(cls.temp_dir.name), gitignore=HARNESS_GITIGNORE
        )
        result = run_adopt(target, environment)
        assert result.returncode == 0, result.stderr
        cls.adopt = result
        cls.target = target

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    def test_adopt_still_completes(self) -> None:
        # 照 required 依赖检查的先例：醒目告警，但不中断铺设。
        self.assertEqual(0, self.adopt.returncode, self.adopt.stderr)
        self.assertIn("overlay 已叠加", self.adopt.stdout)

    def test_adopt_warns_loudly_about_suppression(self) -> None:
        self.assertIn("✗✗", self.adopt.stdout)
        self.assertIn("untracked 可见性被产品仓 .gitignore 压制", self.adopt.stdout)
        self.assertIn("./hgit snapshot", self.adopt.stdout)

    def test_warning_names_every_suppressed_durable_surface(self) -> None:
        for surface in (
            ".trellis/spec/guides/ ← .gitignore",
            ".trellis/scripts/ ← .gitignore",
            ".arborist/tools/ ← .gitignore",
            ".work_context/sendbox/toAgent/ ← .gitignore",
        ):
            with self.subTest(surface=surface):
                self.assertIn(surface, self.adopt.stdout)

    def test_untracked_visibility_is_genuinely_lost(self) -> None:
        # 不是我们的 bug 而是 git 语义（.gitignore > info/exclude，且 `.trellis/` 终止遍历）。
        # 把这个事实钉成断言：文档不得再无条件承诺「现形」。
        write(self.target / ".trellis/spec/guides/zz-fresh-guide.md", "# fresh\n")
        self.assertNotIn(
            ".trellis/spec/guides/zz-fresh-guide.md",
            side_history_untracked(self.target),
        )

    def test_snapshot_still_captures_durable_files(self) -> None:
        write(self.target / ".trellis/spec/guides/zz-snap-guide.md", "# guide\n")
        write(self.target / ".trellis/spec/guides/decisions/0098-snap.md", "# ADR-0098\n")
        write(self.target / ".arborist/tools/zz-snap-tool.json", "{}\n")
        write(
            self.target / ".work_context/sendbox/toAgent/toGardener/from-zz-snap.md",
            "# letter\n",
        )
        result = hgit_cli(self.target, "snapshot")
        self.assertEqual(0, result.returncode, result.stderr)
        tracked = side_history_tracked(self.target)
        for required in (
            ".trellis/spec/guides/zz-snap-guide.md",
            ".trellis/spec/guides/decisions/0098-snap.md",
            ".arborist/tools/zz-snap-tool.json",
            ".work_context/sendbox/toAgent/toGardener/from-zz-snap.md",
            ".claude/agents/trellis-explore.md",
            ".claude/agents/trellis-implement-full.md",
        ):
            with self.subTest(path=required):
                self.assertIn(required, tracked)

    def test_snapshot_path_still_never_pins_credentials(self) -> None:
        result = hgit_cli(self.target, "snapshot")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [],
            [path for path in side_history_tracked(self.target) if path.endswith(".env")],
            "被压制配置下的显式快照同样不得把凭证钉进侧史",
        )


class SideHistoryExcludeRepairTests(unittest.TestCase):
    """现存 adopter（旧式裸 /* exclude）也要拿到修复；重复 adopt 幂等、不吹掉自加条目。"""

    def test_legacy_bare_exclude_is_repaired_for_existing_adopter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target, environment = make_target(Path(temp_dir))
            # 用旧式做法预置一个「已存在」的侧史仓：裸 /* exclude + 一次 baseline。
            init = hgit(target, "init", "-q")
            self.assertEqual(0, init.returncode, init.stderr)
            legacy_exclude = target / ".harness-vcs/info/exclude"
            legacy_exclude.write_text(LEGACY_EXCLUDE, encoding="utf-8")
            write(target / ".trellis/spec/guides/index.md", "# idx\n")
            hgit(target, "add", "-f", ".trellis/spec")
            commit = hgit(
                target,
                "-c",
                "user.name=harness-local",
                "-c",
                "user.email=harness@localhost",
                "commit",
                "-q",
                "-m",
                "legacy baseline",
            )
            self.assertEqual(0, commit.returncode, commit.stderr)

            # 旧式行为回归确认：新建 canonical 文件在修复前【看不见】。
            write(target / ".trellis/spec/guides/zz-fresh-guide.md", "# fresh\n")
            self.assertNotIn(
                ".trellis/spec/guides/zz-fresh-guide.md",
                side_history_untracked(target),
            )

            result = run_adopt(target, environment)
            self.assertEqual(0, result.returncode, result.stderr)

            repaired = legacy_exclude.read_text(encoding="utf-8")
            self.assertIn(BLOCK_BEGIN_MARKER, repaired)
            self.assertEqual(
                1,
                repaired.count("\n/*\n"),
                "旧式裸 /* 应被 allowlist 首行接管，不得另有一处把 allowlist 重新盖掉",
            )
            self.assertIn("!/.trellis/spec", repaired)
            # 修复后：guides / decisions / durable 脚本面的未跟踪新文件都现形。
            write(
                target / ".trellis/spec/guides/decisions/0099-fresh-decision.md",
                "# ADR\n",
            )
            write(target / ".trellis/scripts/zz_fresh_tool.py", "value = 1\n")
            visible = side_history_untracked(target)
            self.assertIn(".trellis/spec/guides/decisions/0099-fresh-decision.md", visible)
            self.assertIn(".trellis/scripts/zz_fresh_tool.py", visible)

    def test_existing_side_history_is_never_staged_or_committed_for_adopter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target, environment = make_target(Path(temp_dir))
            first = run_adopt(target, environment)
            self.assertEqual(0, first.returncode, first.stderr)
            write(target / ".trellis/spec/guides/zz-fresh-guide.md", "# fresh\n")

            second = run_adopt(target, environment)
            self.assertEqual(0, second.returncode, second.stderr)

            log = hgit(target, "log", "--oneline")
            self.assertEqual(
                1,
                len(log.stdout.splitlines()),
                "现存侧史仓不得被 adopt 代为造 commit（落定归 adopter/gardener）",
            )
            # MAJOR 4：gardener 可能已备好选择性暂存（只 stage 某几个 guide 待 commit）。
            # adopt 替他 add 会把运行态 churn 混进去、毁掉那份准备 → 一个字节都不许 stage。
            staged = hgit(target, "diff", "--cached", "--name-only").stdout.splitlines()
            self.assertEqual([], staged, "现存 adopter 路径不得暂存任何文件")
            self.assertIn("未暂存任何文件", second.stdout)
            self.assertIn("./hgit snapshot", second.stdout)

    def test_repeat_adopt_is_idempotent_and_keeps_adopter_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target, environment = make_target(Path(temp_dir))
            first = run_adopt(target, environment)
            self.assertEqual(0, first.returncode, first.stderr)

            exclude_path = target / ".harness-vcs/info/exclude"
            adopter_entry = "\n# adopter 自加\n!/zz-my-own-durable-surface\n"
            exclude_path.write_text(
                exclude_path.read_text(encoding="utf-8") + adopter_entry,
                encoding="utf-8",
            )
            after_first = exclude_path.read_text(encoding="utf-8")

            second = run_adopt(target, environment)
            self.assertEqual(0, second.returncode, second.stderr)
            after_second = exclude_path.read_text(encoding="utf-8")
            third = run_adopt(target, environment)
            self.assertEqual(0, third.returncode, third.stderr)
            after_third = exclude_path.read_text(encoding="utf-8")

            self.assertEqual(after_first, after_second, "重跑 adopt 不得改动 exclude 内容")
            self.assertEqual(after_second, after_third)
            self.assertEqual(1, after_third.count(BLOCK_BEGIN_MARKER), "allowlist 块不得重复堆叠")
            self.assertIn("!/zz-my-own-durable-surface", after_third)
            self.assertEqual(1, after_third.count("!/zz-my-own-durable-surface"))
            self.assertEqual(1, after_third.count("\n/*\n"), "allowlist 首行 /* 只应有一处")

    def test_non_git_harness_vcs_directory_warns_instead_of_claiming_success(self) -> None:
        # MINOR 2：`.harness-vcs/` 在但不是 git 仓（拷贝/解压/中断残留）时不许静静地打成功横幅。
        with tempfile.TemporaryDirectory() as temp_dir:
            target, environment = make_target(Path(temp_dir))
            write(target / ".harness-vcs/leftover.txt", "not a git dir\n")

            result = run_adopt(target, environment)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("✗✗", result.stdout)
            self.assertIn("不是 git 仓", result.stdout)
            self.assertIn("rm -rf .harness-vcs", result.stdout)
            self.assertFalse(
                (target / ".harness-vcs/info/exclude").exists(),
                "非 git 仓不得被当作侧史来写 exclude",
            )


if __name__ == "__main__":
    unittest.main()
