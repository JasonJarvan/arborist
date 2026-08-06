"""「调用方仓根必须显式给出」这条契约的端到端执行者。

**为什么必须走 subprocess 而不是 import 后调函数**：被测的判据是「**这一份**脚本是哪种入口
形态」，答案取自 `__file__` 的实际位置与进程环境变量。import 进本测试进程后 `__file__`
恒为上游那一份 —— 两种入口形态的差异**在进程内不可见**。按
`verification-and-gates.md`「门的回归必须端到端，且测试的结构必须与真实调用路径同构」，
测试必须穿过「脚本被铺在哪 / 进程环境变量说什么」这一层，于是逐条 fixture 都真的把脚本
拷到两个位置、真的以子进程调它。

**被钉住的活缺陷（下游 gardener 只读复验所得）**：
- 全局单份入口缺 `--repo` 时**不是被门拒绝**，而是按 `__file__` 的 `parents[2]` 推出
  **承载权威脚本的那个仓**并继续执行；`resolve_repo_root` 只证明「那里像个项目仓」，
  **不证明那是调用方仓**。上次只因权威仓恰好没有同名 agent 才在后续读取处失败 ——
  有同名 agent 时就是**误投**（`agenttui-registry.md` §2.2.1：误投比不可达严重）。
- 容量观测更严重：缺 `--repo` 时 **rc=0** 返回权威仓快照，没有任何兜底会失败
  ⇒ 「推导成功但仓错误」，调用方无从察觉。
- 契约第一跳成立、第二跳丢失：信封的 `reply_command` 只携带 authority script 路径，
  回复方照它执行就重新落回同一条错仓推导。

所有 fixture 都在 `tempfile` 抛弃目录里现造：不碰任何真实仓、任何真实注册表、任何真实
会话、任何真实复用器，`HOME` 亦被指向抛弃目录。
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
AGENTTUI_SOURCE = ROOT / "overlay" / "scripts" / "agenttui.py"
CAPACITY_SOURCE = ROOT / "overlay" / "scripts" / "arborist_brand_capacity.py"
ENTRY_FORM_VALIDATOR = ROOT / "overlay" / "scripts" / "validate_tool_entry_forms.py"
# `send` 计算（而非手抄）项目限定符，所以它需要注册表 validator 就在同一目录 ——
# 缺了就 fail-closed 而不是退回 leaf 里声明的 `project_id`。fixture 必须与 `adopt.sh`
# 实际铺设的形态一致（两个脚本一起进 `.trellis/scripts/`），否则这里测的是一个
# 现实中不存在的半装状态。
REGISTRY_VALIDATOR = ROOT / "overlay" / "scripts" / "validate_agenttui_registry.py"

# 占位名，绝非任何实测值。
SHARED_AGENT = "shared-name-agent"
PEER_AGENT = "peer-agent"
# 两仓各自的哨兵：出现在输出里就说明读的是那一仓。
AUTHORITY_SENTINEL = "authority-host-sentinel"
CALLER_SENTINEL = "caller-repo-sentinel"

# agenttui 的专用退出码：仓根不可知（既不是投递不确定，也不是注册表不一致）。
EXIT_REPO_ROOT_UNSPECIFIED = 5
REFUSAL_MARKER = "refusing to infer the caller's repository root"


def write_agent_leaf(repo: Path, name: str, *, sentinel: str, brand: str) -> None:
    """一条最小可读 leaf。`session_id` 带哨兵 ⇒ 读了哪一仓一看输出便知。"""
    leaf = repo / ".arborist" / "agents" / name
    leaf.mkdir(parents=True, exist_ok=True)
    session_file = repo / f"{name}-session.jsonl"
    session_file.write_text("transcript line\n", encoding="utf-8")
    (leaf / "spec.json").write_text(
        json.dumps(
            {
                "name": name,
                "brand": brand,
                "role": "impler",
                "project": {"path": str(repo), "project_id": "placeholder-project"},
            }
        ),
        encoding="utf-8",
    )
    (leaf / "runtime.json").write_text(
        json.dumps(
            {
                "session_id": f"{sentinel}-{name}",
                "session_file": str(session_file),
                "state": "active",
                "last_seen": datetime.now().astimezone().isoformat(timespec="seconds"),
                "pane_ref": None,
            }
        ),
        encoding="utf-8",
    )


def write_capacity_snapshot(repo: Path, *, sentinel: str) -> Path:
    """一份形态完好的快照。它**不是**观测值，`generated_at` 只是哨兵字符串的载体。"""
    state = repo / ".arborist" / "runtime" / "brand-capacity.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": f"1970-01-01T00:00:00+00:00 {sentinel}",
                "brands": {},
            }
        ),
        encoding="utf-8",
    )
    return state


class Fixture:
    """两个仓 + 两种入口形态的抛弃式 fixture。

    - `authority`：承载**全局单份权威脚本**的仓（脚本落在 `overlay/scripts/`）。
      它本身也是个项目仓 —— 这正是缺陷的成因：`resolve_repo_root` 检查它「像项目仓」
      时会通过。
    - `caller`：调用方仓，同时持有一份**项目内 adopted copy**（`.trellis/scripts/`）。
    - 两仓各有一个**同名** agent，用于钉住「上次只是恰好没同名」那个偶然。
    """

    def __init__(self, base: Path) -> None:
        self.base = base
        self.home = base / "fake-home"
        self.global_root = self.home / ".arborist"
        (self.global_root / "bin").mkdir(parents=True)
        (self.global_root / "index.json").write_text(
            json.dumps({"projects": []}), encoding="utf-8"
        )

        self.authority = base / "authority-host-repo"
        (self.authority / ".trellis").mkdir(parents=True)
        self.authority_scripts = self.authority / "overlay" / "scripts"
        self.authority_scripts.mkdir(parents=True)
        shutil.copy2(AGENTTUI_SOURCE, self.authority_scripts / AGENTTUI_SOURCE.name)
        shutil.copy2(CAPACITY_SOURCE, self.authority_scripts / CAPACITY_SOURCE.name)
        shutil.copy2(REGISTRY_VALIDATOR, self.authority_scripts / REGISTRY_VALIDATOR.name)
        write_agent_leaf(
            self.authority, SHARED_AGENT, sentinel=AUTHORITY_SENTINEL, brand="claude-code"
        )
        # 两条都用同一个 brand：本文件测的是仓根解析与信封回程，不是 brand 差异 ——
        # 让 resume 路在两个方向上都可用，回程才穿得过去。
        write_agent_leaf(
            self.authority, PEER_AGENT, sentinel=AUTHORITY_SENTINEL, brand="claude-code"
        )
        self.authority_state = write_capacity_snapshot(
            self.authority, sentinel=AUTHORITY_SENTINEL
        )

        self.caller = base / "caller-repo"
        self.caller_scripts = self.caller / ".trellis" / "scripts"
        self.caller_scripts.mkdir(parents=True)
        shutil.copy2(AGENTTUI_SOURCE, self.caller_scripts / AGENTTUI_SOURCE.name)
        shutil.copy2(CAPACITY_SOURCE, self.caller_scripts / CAPACITY_SOURCE.name)
        shutil.copy2(REGISTRY_VALIDATOR, self.caller_scripts / REGISTRY_VALIDATOR.name)
        write_agent_leaf(
            self.caller, SHARED_AGENT, sentinel=CALLER_SENTINEL, brand="claude-code"
        )
        write_agent_leaf(
            self.caller, PEER_AGENT, sentinel=CALLER_SENTINEL, brand="claude-code"
        )
        self.caller_state = write_capacity_snapshot(self.caller, sentinel=CALLER_SENTINEL)

        # 假 brand CLI：只为让 `shutil.which` 的能力检查通过。dry-run 不执行任何
        # 传输命令，所以这个 stub 永远不会被调用 —— 它存在，仅此而已。
        self.fake_bin = base / "fake-bin"
        self.fake_bin.mkdir()
        for name in ("claude", "codex"):
            stub = self.fake_bin / name
            stub.write_text(
                "#!/bin/sh\n"
                'echo "this stub must never be executed by a test" >&2\n'
                "exit 97\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)

    # -- entry points ---------------------------------------------------------

    @property
    def global_agenttui(self) -> Path:
        return self.authority_scripts / AGENTTUI_SOURCE.name

    @property
    def global_capacity(self) -> Path:
        return self.authority_scripts / CAPACITY_SOURCE.name

    @property
    def project_agenttui(self) -> Path:
        return self.caller_scripts / AGENTTUI_SOURCE.name

    @property
    def project_capacity(self) -> Path:
        return self.caller_scripts / CAPACITY_SOURCE.name

    def install_shim(self, name: str, authority: Path) -> Path:
        """铺一个可执行 shim，用来验证 `reply_command` 会优先选稳定全局入口形态。"""
        shim = self.global_root / "bin" / name
        shim.write_text(
            "#!/bin/sh\n"
            'exec python3 "' + str(authority) + '" "$@"\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)
        return shim

    def run(
        self,
        script: Path,
        argv: list[str],
        *,
        entry_form: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        # HOME 与 ARBORIST_HOME 双双指向抛弃目录：任何 Path.home() 派生的默认路径
        # （观测日志、全局 index、shim 探测）都不可能落到真实 $HOME。
        env["HOME"] = str(self.home)
        env["ARBORIST_HOME"] = str(self.global_root)
        env["PATH"] = os.pathsep.join([str(self.fake_bin), env.get("PATH", "")])
        env.pop("ARBORIST_ENTRY_FORM", None)
        if entry_form is not None:
            env["ARBORIST_ENTRY_FORM"] = entry_form
        return subprocess.run(
            [sys.executable, str(script), *argv],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )


class FixtureCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.fixture = Fixture(Path(self._temporary.name))


class GlobalEntryRequiresExplicitRepoTests(FixtureCase):
    """交付物 ①：全局入口边界要求显式 `--repo`。"""

    def assert_refused_before_reading_state(
        self, result: subprocess.CompletedProcess[str], *, expected_code: int
    ) -> None:
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, expected_code, combined)
        # 「在读取任何仓状态之前失败」的两条硬证据：① 没有任何 stdout（两个脚本的
        # 仓状态输出一律走 stdout）；② 权威仓的哨兵没有出现在任何一路输出里。
        self.assertEqual(result.stdout, "", "拒绝路径不得产出任何仓状态")
        self.assertNotIn(AUTHORITY_SENTINEL, combined)
        self.assertNotIn(CALLER_SENTINEL, combined)
        self.assertIn(REFUSAL_MARKER, result.stderr, combined)

    def test_messaging_state_command_without_repo_is_refused(self) -> None:
        result = self.fixture.run(
            self.fixture.global_agenttui, ["status", "--name", SHARED_AGENT]
        )
        self.assert_refused_before_reading_state(
            result, expected_code=EXIT_REPO_ROOT_UNSPECIFIED
        )

    def test_capacity_state_command_without_repo_is_refused(self) -> None:
        result = self.fixture.run(self.fixture.global_capacity, ["status"])
        self.assert_refused_before_reading_state(result, expected_code=1)

    def test_declared_global_form_beats_adopted_layout(self) -> None:
        """显式信号优先于结构：项目内位置 + 声明为全局 ⇒ 仍要求 `--repo`。

        这条钉住 fail-closed 的**方向**：判据冲突时按更严的那一侧走。
        """
        for script, expected in (
            (self.fixture.project_agenttui, EXIT_REPO_ROOT_UNSPECIFIED),
            (self.fixture.project_capacity, 1),
        ):
            with self.subTest(script=script.name):
                argv = (
                    ["status", "--name", SHARED_AGENT]
                    if script.name == AGENTTUI_SOURCE.name
                    else ["status"]
                )
                result = self.fixture.run(script, argv, entry_form="global-authority")
                self.assert_refused_before_reading_state(result, expected_code=expected)

    def test_unrecognised_entry_form_signal_is_not_a_fallback(self) -> None:
        """信号写错 ⇒ unknown ⇒ 仍要求 `--repo`，不得静默回退到结构判据。"""
        result = self.fixture.run(
            self.fixture.project_agenttui,
            ["status", "--name", SHARED_AGENT],
            entry_form="globalauthority",
        )
        self.assert_refused_before_reading_state(
            result, expected_code=EXIT_REPO_ROOT_UNSPECIFIED
        )

    def test_top_level_help_is_exempt(self) -> None:
        """`--help` 豁免：argparse 在门之前就处理掉它，且它不读任何仓状态。"""
        result = self.fixture.run(self.fixture.global_agenttui, ["--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--repo", result.stdout)
        self.assertNotIn(AUTHORITY_SENTINEL, result.stdout)

    def test_global_entry_with_explicit_repo_reads_the_caller_repo(self) -> None:
        result = self.fixture.run(
            self.fixture.global_agenttui,
            ["--repo", str(self.fixture.caller), "status", "--name", SHARED_AGENT],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn(CALLER_SENTINEL, payload["session_id"])
        self.assertNotIn(AUTHORITY_SENTINEL, result.stdout)


class SameNamedAgentTests(FixtureCase):
    """测试 3：钉住「上次只是恰好没同名」那个偶然。"""

    def test_same_name_in_both_repos_must_not_resolve_silently(self) -> None:
        # 前提自检：两仓真的各有一个同名 agent，且哨兵不同 —— 否则本测试证不到东西。
        for repo, sentinel in (
            (self.fixture.authority, AUTHORITY_SENTINEL),
            (self.fixture.caller, CALLER_SENTINEL),
        ):
            runtime = json.loads(
                (repo / ".arborist" / "agents" / SHARED_AGENT / "runtime.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn(sentinel, runtime["session_id"])

        result = self.fixture.run(
            self.fixture.global_agenttui, ["status", "--name", SHARED_AGENT]
        )
        self.assertNotEqual(result.returncode, 0, result.stdout)
        # 关键：不得**成功**，也不得吐出权威仓那条同名 agent 的任何字段。
        self.assertEqual(result.stdout, "")
        self.assertNotIn(AUTHORITY_SENTINEL, result.stdout + result.stderr)


class CapacityWrongRepoSuccessTests(FixtureCase):
    """测试 4：钉住已发生的「错仓成功」——rc=0 + 权威仓快照。"""

    def test_capacity_status_without_repo_never_returns_authority_snapshot(self) -> None:
        lock = self.fixture.authority / ".arborist" / "runtime" / "brand-capacity.lock"
        before = self.fixture.authority_state.read_text(encoding="utf-8")

        result = self.fixture.run(self.fixture.global_capacity, ["status"])

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn(AUTHORITY_SENTINEL, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        # 只读且零副作用：权威仓的快照未变、锁文件未被创建。
        self.assertEqual(self.fixture.authority_state.read_text(encoding="utf-8"), before)
        self.assertFalse(lock.exists())

    def test_capacity_status_with_explicit_repo_returns_that_repo(self) -> None:
        result = self.fixture.run(
            self.fixture.global_capacity, ["--repo", str(self.fixture.caller), "status"]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(CALLER_SENTINEL, result.stdout)
        self.assertNotIn(AUTHORITY_SENTINEL, result.stdout)


class ProjectCopyRegressionTests(FixtureCase):
    """测试 5：回归钉子 —— 别把**正确**的那条推导路一起堵掉。"""

    def test_adopted_copy_still_infers_its_own_repo(self) -> None:
        result = self.fixture.run(
            self.fixture.project_agenttui, ["status", "--name", SHARED_AGENT]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn(CALLER_SENTINEL, payload["session_id"])
        self.assertNotIn(AUTHORITY_SENTINEL, result.stdout)

    def test_adopted_capacity_copy_still_infers_its_own_repo(self) -> None:
        result = self.fixture.run(self.fixture.project_capacity, ["status"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(CALLER_SENTINEL, result.stdout)
        self.assertNotIn(AUTHORITY_SENTINEL, result.stdout)

    def test_declared_project_form_is_honoured(self) -> None:
        result = self.fixture.run(
            self.fixture.project_agenttui,
            ["status", "--name", SHARED_AGENT],
            entry_form="project-copy",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class ReplyCommandCarriesRepoTests(FixtureCase):
    """交付物 ② / 测试 2：契约第二跳不得重新推导仓根。"""

    def send_dry_run(self, script: Path, repo: Path) -> dict:
        result = self.fixture.run(
            script,
            [
                "--repo",
                str(repo),
                "send",
                "--from",
                PEER_AGENT,
                "--to",
                SHARED_AGENT,
                "--message",
                "short pointer: see the sendbox letter",
                "--dry-run",
                "--allow-resume",
                "--no-observation-log",
            ],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def reply_command_line(self, payload: dict) -> str:
        # 信封随投递 argv 一起走；`reply_command=` 是信封里的一行。
        blob = "\n".join(str(item) for item in payload["argv"])
        lines = [line for line in blob.splitlines() if line.startswith("reply_command=")]
        self.assertEqual(len(lines), 1, blob)
        return lines[0]

    def test_reply_command_names_the_resolved_repo(self) -> None:
        for label, script in (
            ("global-authority", self.fixture.global_agenttui),
            ("project-copy", self.fixture.project_agenttui),
        ):
            with self.subTest(entry_form=label):
                payload = self.send_dry_run(script, self.fixture.caller)
                line = self.reply_command_line(payload)
                self.assertIn(f"--repo {self.fixture.caller}", line)
                # 且不得指向承载权威脚本的那个仓。
                self.assertNotIn(f"--repo {self.fixture.authority}", line)

    def test_reply_command_prefers_the_global_shim_when_installed(self) -> None:
        shim = self.fixture.install_shim("agenttui", self.fixture.global_agenttui)
        payload = self.send_dry_run(self.fixture.global_agenttui, self.fixture.caller)
        line = self.reply_command_line(payload)
        self.assertIn(str(shim), line)
        self.assertIn(f"--repo {self.fixture.caller}", line)

    def test_reply_command_falls_back_to_the_script_path_without_a_shim(self) -> None:
        payload = self.send_dry_run(self.fixture.global_agenttui, self.fixture.caller)
        line = self.reply_command_line(payload)
        self.assertIn(str(self.fixture.global_agenttui), line)
        # 兜底形态照样带 --repo：入口形态是优化，`--repo` 是正确性要求。
        self.assertIn(f"--repo {self.fixture.caller}", line)

    def test_replaying_the_reply_command_targets_the_caller_repo(self) -> None:
        """穿到底：把 `reply_command` 当真执行一次，它必须打在调用方仓上。

        这是本文件最重要的一条 —— 前面几条只断言了**字符串**，这一条断言那串东西
        **作为命令**的效果。`<reply>` 换成真消息、加上 dry-run 以免产生任何副作用。
        """
        payload = self.send_dry_run(self.fixture.global_agenttui, self.fixture.caller)
        line = self.reply_command_line(payload)
        argv = shlex.split(line[len("reply_command=") :])
        argv = [
            "reply body: acknowledged" if part == "<reply>" else part for part in argv
        ]
        argv += ["--dry-run", "--allow-resume", "--no-observation-log"]
        self.assertEqual(argv[0], "python3")
        result = self.fixture.run(Path(argv[1]), argv[2:])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        replayed = json.loads(result.stdout)
        # 回复方读到的是**调用方仓**的 leaf，不是权威仓的同名 leaf。
        self.assertIn(CALLER_SENTINEL, replayed["target_session_id"])
        self.assertNotIn(AUTHORITY_SENTINEL, result.stdout)


class ToolEntryFormConsistencyTests(unittest.TestCase):
    """交付物 ③ / 测试 6：`invoke` 与 `availability` 入口形态必须一致。"""

    GLOBAL_INVOKE = '"${ARBORIST_HOME:-$HOME/.arborist}/bin/placeholder" --repo <REPO> --help'
    GLOBAL_AVAILABILITY = '"${ARBORIST_HOME:-$HOME/.arborist}/bin/placeholder" --help'
    PROJECT_INVOKE = "python3 .trellis/scripts/placeholder.py --help"

    def run_validator(self, *paths: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ENTRY_FORM_VALIDATOR), *(str(p) for p in paths)],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def write_entry(self, base: Path, name: str, entry: dict) -> Path:
        path = base / f"{name}.json"
        path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
        return path

    def test_mixed_entry_forms_fail(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            path = self.write_entry(
                base,
                "mixed",
                {
                    "name": "mixed",
                    "kind": "cli",
                    "scope": "global",
                    "invoke": {"cli": self.GLOBAL_INVOKE},
                    # 实测形状：教人调全局入口，却拿项目副本证明可用。
                    "availability": self.PROJECT_INVOKE,
                },
            )
            result = self.run_validator(path)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("入口形态不一致", result.stderr)

    def test_consistent_entry_forms_pass(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.write_entry(
                base,
                "global-form",
                {
                    "name": "global-form",
                    "kind": "cli",
                    "scope": "global",
                    "invoke": {"cli": self.GLOBAL_INVOKE},
                    "availability": self.GLOBAL_AVAILABILITY,
                    # fallback 里提项目副本是**正当**的兜底，不算不一致。
                    "fallback": "退回 python3 .trellis/scripts/placeholder.py",
                },
            )
            self.write_entry(
                base,
                "project-form",
                {
                    "name": "project-form",
                    "kind": "cli",
                    "scope": "project",
                    "invoke": {"cli": self.PROJECT_INVOKE},
                    "availability": self.PROJECT_INVOKE,
                },
            )
            result = self.run_validator(base)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_scope_must_match_the_entry_form(self) -> None:
        with TemporaryDirectory() as temporary:
            path = self.write_entry(
                Path(temporary),
                "scope-mismatch",
                {
                    "name": "scope-mismatch",
                    "kind": "cli",
                    "scope": "project",
                    "invoke": {"cli": self.GLOBAL_INVOKE},
                    "availability": self.GLOBAL_AVAILABILITY,
                },
            )
            result = self.run_validator(path)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("scope", result.stderr)

    def test_unreadable_entry_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "broken.json"
            path.write_text("{not json", encoding="utf-8")
            result = self.run_validator(path)
            # 2 ≠ 1：读不出这条目**不等于**这条目没问题。
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_shipped_templates_are_consistent(self) -> None:
        result = self.run_validator(ROOT / "overlay" / "arborist-templates" / "tools")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
