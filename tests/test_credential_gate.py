"""侧史 pre-commit 凭据门的回归。

**测试形状受一条通则硬约束**（`verification-and-gates.md`
「门的回归必须端到端，且测试的结构必须与真实调用路径同构」实例 (i)）：
这个门的上一次回归直接 `import` 分类函数、跑过「数百个文件零误报」，据此认为门已验 ——
它**从未穿过「hook 被调用 → 拒绝提交」那条路径**，是一次真的绕过**提交成功了**才暴露。

⇒ 本文件的核心两条（`GateEndToEndTest`）在 `tempfile.mkdtemp` 造的**抛弃仓**里真的
`git init` → 装 hook → `add -f` → **真跑 `git commit`**，并断言两条读数：
**退出码非零** 且 **提交没产生**（`rev-list --count` 为 0）。只看退出码不足以区分
「拦住了」与「拦了但 git 仍然提交了」。

分类器的单元测试仍然保留 —— 它们测的是**判据**，不是门；两者是两个命题。

**假秘密样本一律由片段拼出，不写字面量**：否则本文件自己会成为一次泄漏，
并被其他扫描器（adopter 侧、公开上推前的 audit）当成真命中。
"""

from __future__ import annotations

import base64
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

# adopt 侧的 fixture 复用既有那一份（另写一套「最小可 adopt 仓」必然与它漂移）。
# 显式补 sys.path：`unittest discover -s tests` 会代劳，但 `-m unittest tests.<mod>` 不会。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_adopt_side_history as adopt_fixture  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
GATE_SRC = ROOT / "overlay" / "hook-templates" / "credential-gate" / "pre-commit"


def load_gate():
    """按路径加载无 `.py` 后缀的钩子脚本。

    能这样加载本身是个设计约束：门在 import 时**不得**有副作用（早先版本在模块层
    解析 git-dir，import 即可能抛异常）。git-dir 现在只在 `main()` 里解析。
    """
    spec = importlib.util.spec_from_file_location(
        "arborist_credential_gate",
        GATE_SRC,
        loader=importlib.machinery.SourceFileLoader("arborist_credential_gate", str(GATE_SRC)),
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = load_gate()


# ── 假秘密 / 假豁免样本：一律拼片段 ─────────────────────────────────────
def fake_jwt(exp_offset: int = -86400) -> str:
    def seg(payload: dict) -> str:
        raw = json.dumps(payload).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    header = seg({"alg": "HS" + "256", "typ": "JWT"})
    body = seg({"exp": int(time.time()) + exp_offset, "role": "test"})
    signature = "s" * 24
    return f"{header}.{body}.{signature}"


def fake_pem() -> str:
    begin = "-----" + "BEGIN" + " RSA PRIVATE KEY" + "-----"
    end = "-----" + "END" + " RSA PRIVATE KEY" + "-----"
    return begin + "\n" + "A" * 60 + "\n" + end + "\n"


FAKE_SECRETS = {
    "jwt": lambda: "token = " + fake_jwt(),
    "pem": fake_pem,
    "prefix-vendor-secret": lambda: "key=" + "sb" + "_secret" + "_" + "A" * 24,
    "prefix-sk": lambda: "key=" + "sk" + "-" + "A" * 24,
    "prefix-ghp": lambda: "key=" + "ghp" + "_" + "B" * 24,
    "prefix-xox": lambda: "key=" + "xox" + "b" + "-" + "1" * 12,
    "cred-field": lambda: '{"' + "refresh" + "_token" + '": "' + "R" * 32 + '"}',
}

FAKE_EXEMPT = {
    "digest-value": lambda: '{"api' + "_key" + '": "sha256:' + "a" * 64 + '"}',
    "digest-bare": lambda: '{"' + "secret" + '": "' + "b" * 64 + '"}',
    "publishable-key": lambda: "key=" + "sb" + "_publishable" + "_" + "C" * 24,
    "publishable-in-cred-field": lambda: '{"api' + "_key" + '": "' + "sb" + "_publishable" + "_" + "D" * 24 + '"}',
    "anon-field": lambda: '{"' + "secret" + '": "' + "${ANON" + "_KEY}" + '"}',
    "placeholder-angle": lambda: '{"' + "password" + '": "<your-password-here>"}',
    "placeholder-changeme": lambda: '{"client' + "_secret" + '": "CHANGEME"}',
    "short-value": lambda: '{"' + "password" + '": "abc"}',
}


class ClassifierTest(unittest.TestCase):
    """判据侧（**不是**门侧 —— 门侧见 GateEndToEndTest）。"""

    def test_each_real_secret_class_is_caught(self) -> None:
        for name, build in FAKE_SECRETS.items():
            with self.subTest(secret=name):
                self.assertNotEqual([], GATE.classify(build()), f"{name} 未被识别为真秘密")

    def test_each_exempt_class_passes(self) -> None:
        for name, build in FAKE_EXEMPT.items():
            with self.subTest(exempt=name):
                self.assertEqual([], GATE.classify(build()), f"{name} 被误报")

    def test_suspicious_path_with_clean_content_is_not_judged_by_form(self) -> None:
        """按【分类】判，不按【形态】判 —— 路径形态根本不进 classify 的签名。"""
        self.assertEqual([], GATE.classify("PORT=5432\nDEBUG=true\n"))
        # 门里也不该存在任何「可疑路径清单」参与判决（那正是失效过的那条防线）。
        self.assertNotIn("SUSPECT_PATH", dir(GATE))

    def test_jwt_liveness_is_reported_not_used_as_verdict(self) -> None:
        expired = GATE.classify("t=" + fake_jwt(-86400 * 3))
        live = GATE.classify("t=" + fake_jwt(+3600))
        self.assertNotEqual([], expired, "已过期的 JWT 仍不该进历史")
        self.assertNotEqual([], live)
        self.assertIn("已过期", expired[0])
        self.assertIn("未过期", live[0])

    def test_gate_source_does_not_match_itself(self) -> None:
        """自匹配防护：检测器天然含有被检测的模式（grep 自己那个经典问题）。

        源码里的裸字面量【故意】写成不能匹配自身的形式（`sb[_]secret[_]` 而非 `sb_secret_`）。
        给自己开一条路径例外是特例化，且会随文件改名或被复制而失效 —— 让字面量不自匹配才是治本。
        本断言就是那个性质的执行者。
        """
        self.assertEqual(
            [],
            GATE.classify(GATE_SRC.read_text(encoding="utf-8")),
            "门的源码被自己的分类器命中 —— 裸字面量的不自匹配性质被破坏了",
        )


class AllowlistTest(unittest.TestCase):
    """四段字段是真校验，不只是错误提示里的文字。"""

    def test_complete_entry_takes_effect(self) -> None:
        line = "path/to/creds.env  # approver=role-name date=2026-01-02 scope=只这一个文件、只侧史 why=见某条裁定"
        allowed, defects = GATE.parse_allowlist(line + "\n")
        self.assertEqual([], defects)
        self.assertEqual({"path/to/creds.env"}, allowed)

    def test_missing_any_field_is_reported_and_entry_does_not_take_effect(self) -> None:
        base = {
            "approver": "approver=role-name",
            "date": "date=2026-01-02",
            "scope": "scope=只这一个文件",
            "why": "why=理由",
        }
        for missing in base:
            with self.subTest(missing=missing):
                comment = " ".join(v for k, v in base.items() if k != missing)
                allowed, defects = GATE.parse_allowlist(f"p/x.env  # {comment}\n")
                self.assertEqual(set(), allowed, "缺字段的条目不得生效")
                self.assertEqual(1, len(defects))
                self.assertIn("第 1 行", defects[0])
                self.assertIn(f"{missing}=", defects[0])

    def test_placeholder_value_counts_as_missing(self) -> None:
        """错误提示里印的就是 `scope=<授权范围>` —— 整行抄下来不算一次授权。"""
        line = "p/x.env  # approver=<谁> date=2026-01-02 scope=<授权范围> why=<理由>\n"
        allowed, defects = GATE.parse_allowlist(line)
        self.assertEqual(set(), allowed)
        self.assertIn("scope=", defects[0])

    def test_bad_date_shape_is_a_defect(self) -> None:
        line = "p/x.env  # approver=role date=昨天 scope=只这一个文件 why=理由\n"
        allowed, defects = GATE.parse_allowlist(line)
        self.assertEqual(set(), allowed)
        self.assertIn("YYYY-MM-DD", defects[0])

    def test_comments_and_blanks_are_not_entries(self) -> None:
        allowed, defects = GATE.parse_allowlist("\n# 说明行\n   \n")
        self.assertEqual((set(), []), (allowed, defects))

    def test_values_may_contain_spaces(self) -> None:
        line = "p/x.env  # approver=some role date=2026-01-02 scope=这一个文件，仅侧史 why=一句带空格的理由\n"
        allowed, defects = GATE.parse_allowlist(line)
        self.assertEqual([], defects)
        self.assertEqual({"p/x.env"}, allowed)


class HarnessRepo:
    """一个**临时抛弃仓**：真 git 仓 + 真 harness git-dir + 真装上的 hook。

    绝不碰任何真实仓：仓根来自 `tempfile.mkdtemp`，用完删除。
    """

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="arborist-credgate-"))
        self.git_dir = self.root / ".harness-vcs"
        self._git("init", "-q")
        self._git("config", "user.name", "harness-local")
        self._git("config", "user.email", "harness@localhost")

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", f"--git-dir={self.git_dir}", f"--work-tree={self.root}", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(self.root)},
        )

    def install_gate(self) -> None:
        hooks = self.git_dir / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        shutil.copy2(GATE_SRC, hooks / "pre-commit")
        (hooks / "pre-commit").chmod(0o755)

    def write_allowlist(self, text: str) -> None:
        (self.git_dir / "allowed-credentials").write_text(text, encoding="utf-8")

    def stage(self, relpath: str, content: str) -> None:
        target = self.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        # `add -f`：正是这条让所有 ignore 类机制失效的用法，所以测试必须用它。
        result = self._git("add", "-f", relpath)
        assert result.returncode == 0, result.stderr

    def commit(self) -> subprocess.CompletedProcess[str]:
        return self._git("commit", "-m", "probe")

    def commit_count(self) -> int:
        result = self._git("rev-list", "--count", "--all")
        return int(result.stdout.strip() or 0)

    def destroy(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class GateEndToEndTest(unittest.TestCase):
    """穿过「hook 被调用 → 拒绝提交」整条路径。两条读数都断言。"""

    def setUp(self) -> None:
        self.repo = HarnessRepo()
        self.addCleanup(self.repo.destroy)

    def test_ignore_does_not_stop_force_add(self) -> None:
        """先立事实：exclude 挡不住 `add -f` —— 这是本门存在的全部理由。"""
        (self.repo.git_dir / "info").mkdir(parents=True, exist_ok=True)
        (self.repo.git_dir / "info" / "exclude").write_text("secrets/\n", encoding="utf-8")
        (self.repo.root / "secrets").mkdir()
        (self.repo.root / "secrets" / "x.env").write_text("k=v\n", encoding="utf-8")

        plain = self.repo._git("add", "secrets/x.env")
        staged_after_plain = self.repo._git("diff", "--cached", "--name-only").stdout.split()
        forced = self.repo._git("add", "-f", "secrets/x.env")
        staged_after_forced = self.repo._git("diff", "--cached", "--name-only").stdout.split()

        self.assertNotEqual(0, plain.returncode, "被 exclude 的路径裸 add 应当失败")
        self.assertEqual([], staged_after_plain)
        self.assertEqual(0, forced.returncode)
        self.assertEqual(["secrets/x.env"], staged_after_forced)

    def test_real_secret_is_refused_and_no_commit_is_produced(self) -> None:
        self.repo.install_gate()
        self.repo.stage("harness/creds.local.md", "auth: " + fake_jwt() + "\n")

        result = self.repo.commit()

        self.assertNotEqual(0, result.returncode, f"门未开火：\n{result.stdout}\n{result.stderr}")
        self.assertEqual(0, self.repo.commit_count(), "退出码非零但提交仍然产生了 —— 门形同虚设")
        self.assertIn("凭据门", result.stderr)

    def test_same_commit_succeeds_without_the_gate(self) -> None:
        """归因对照：**不装**门时同一次提交会成功。

        少了这一条，上面那次「rc≠0 且无提交」可能来自任何别的原因（配置、权限、空提交），
        而测试内部看不出区别 —— 那正是本文件开头那条通则要防的东西。
        """
        self.repo.stage("harness/creds.local.md", "auth: " + fake_jwt() + "\n")

        result = self.repo.commit()

        self.assertEqual(0, result.returncode, f"{result.stdout}\n{result.stderr}")
        self.assertEqual(1, self.repo.commit_count())

    def test_clean_content_really_commits(self) -> None:
        """放行侧同样端到端：真提交、真成功。否则「门不误伤」也只是个声称。"""
        self.repo.install_gate()
        self.repo.stage(".trellis/spec/guides/x.md", "# guide\n\nPORT=5432\n")

        result = self.repo.commit()

        self.assertEqual(0, result.returncode, f"{result.stdout}\n{result.stderr}")
        self.assertEqual(1, self.repo.commit_count())

    def test_suspicious_path_without_real_secret_commits(self) -> None:
        """路径可疑、内容无真秘密 ⇒ 放行（按分类判，不按形态判）。"""
        self.repo.install_gate()
        self.repo.stage(".work_context/shared-auth/notes.local.md", "凭据放在系统凭据管理器里，本文件只记流程。\n")

        result = self.repo.commit()

        self.assertEqual(0, result.returncode, f"{result.stdout}\n{result.stderr}")
        self.assertEqual(1, self.repo.commit_count())

    def test_complete_allowlist_entry_lets_the_commit_through(self) -> None:
        self.repo.install_gate()
        self.repo.write_allowlist(
            "harness/creds.local.md  # approver=role-name date=2026-01-02 "
            "scope=只这一个文件、只侧史 why=见裁定记录\n"
        )
        self.repo.stage("harness/creds.local.md", "auth: " + fake_jwt() + "\n")

        result = self.repo.commit()

        self.assertEqual(0, result.returncode, f"{result.stdout}\n{result.stderr}")
        self.assertEqual(1, self.repo.commit_count())

    def test_allowlist_missing_scope_refuses_and_names_the_line(self) -> None:
        """缺 scope 不是「该条目失效」而已 —— 提交必须被拒，且报出第几行缺什么。"""
        self.repo.install_gate()
        self.repo.write_allowlist(
            "harness/creds.local.md  # approver=role-name date=2026-01-02 why=见裁定记录\n"
        )
        self.repo.stage("harness/creds.local.md", "auth: " + fake_jwt() + "\n")

        result = self.repo.commit()

        self.assertNotEqual(0, result.returncode)
        self.assertEqual(0, self.repo.commit_count())
        self.assertIn("第 1 行", result.stderr)
        self.assertIn("scope=", result.stderr)
        self.assertIn("授权不外推", result.stderr)

    def test_allowlist_defect_refuses_even_a_clean_commit(self) -> None:
        """条目残缺时任何提交都不该通过，否则「不生效」会被「这次刚好没命中」掩盖。"""
        self.repo.install_gate()
        self.repo.write_allowlist("harness/creds.local.md  # approver=role-name date=2026-01-02\n")
        self.repo.stage("docs/clean.md", "# 完全干净\n")

        result = self.repo.commit()

        self.assertNotEqual(0, result.returncode)
        self.assertEqual(0, self.repo.commit_count())

    def test_gate_unavailable_does_not_let_the_commit_through(self) -> None:
        """git 子命令失败 ⇒ fail-closed。

        复现的是那次真实 fail-open 的形状：子命令失败 ⇒ stdout 为空 ⇒ staged 列表为空
        ⇒ 静默 `return 0` 放行。这里把 `git` 换成一个恒定失败的假 git，断言门**拒绝**。
        """
        self.repo.install_gate()
        self.repo.stage("docs/clean.md", "# 完全干净\n")

        fake_bin = self.repo.root / "fake-bin"
        fake_bin.mkdir()
        stub = fake_bin / "git"
        stub.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
        stub.chmod(0o755)

        result = subprocess.run(
            ["python3", str(self.repo.git_dir / "hooks" / "pre-commit")],
            cwd=self.repo.root,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
                "GIT_DIR": str(self.repo.git_dir),
                "HOME": str(self.repo.root),
            },
        )

        self.assertNotEqual(0, result.returncode, "git 子命令失败时门放行了 —— 这正是那次 fail-open")
        self.assertIn("fail-closed", result.stderr)

    def test_missing_git_dir_is_refused_not_guessed(self) -> None:
        """定位不到 git-dir 时拒绝，而不是靠 `__file__` 的相对深度去猜。"""
        outside = Path(tempfile.mkdtemp(prefix="arborist-credgate-nogit-"))
        self.addCleanup(shutil.rmtree, outside, True)
        env = {k: v for k, v in os.environ.items() if k != "GIT_DIR"}
        env["HOME"] = str(outside)

        result = subprocess.run(
            ["python3", str(GATE_SRC)],
            cwd=outside,
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("无法定位", result.stderr)


class AdoptWiringTest(unittest.TestCase):
    """接线侧：真跑 `adopt.sh`，再断言钩子真的在位并真的会开火。

    **只 grep `adopt.sh` 的正文不算验过接线**（「制品到位 ≠ 路径生效」）——
    所以下面既有静态断言，也有真跑 adopt 的那两条。
    """

    def adopt(self) -> tuple[Path, dict[str, str]]:
        """在临时目录里跑真实 `adopt.sh`（HOME 也隔离，绝不碰真实仓与真实 `~/.arborist`）。"""
        temp_root = Path(tempfile.mkdtemp(prefix="arborist-credgate-adopt-"))
        self.addCleanup(shutil.rmtree, temp_root, True)
        target, environment = adopt_fixture.make_target(temp_root)
        result = adopt_fixture.run_adopt(target, environment)
        self.assertEqual(0, result.returncode, f"{result.stdout}\n{result.stderr}")
        return target, environment

    def test_adopt_installs_the_hook_and_it_actually_fires(self) -> None:
        target, _ = self.adopt()
        hook = target / ".harness-vcs" / "hooks" / "pre-commit"
        self.assertTrue(hook.exists(), "adopt 后钩子不在位 —— 接线没生效")
        self.assertTrue(os.access(hook, os.X_OK))
        # baseline 提交本身穿过了这道门（门装在 baseline 之前）。
        baseline = adopt_fixture.hgit(target, "rev-list", "--count", "--all")
        self.assertEqual("1", baseline.stdout.strip())

        # 真跑一次带假秘密的提交：必须被拒且不产生提交。
        (target / ".trellis" / "spec" / "guides").mkdir(parents=True, exist_ok=True)
        (target / ".trellis" / "spec" / "guides" / "leak.md").write_text(
            "auth: " + fake_jwt() + "\n", encoding="utf-8"
        )
        adopt_fixture.hgit(target, "add", "-f", ".trellis/spec/guides/leak.md")
        refused = adopt_fixture.hgit(
            target, "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-m", "probe"
        )
        self.assertNotEqual(0, refused.returncode, f"{refused.stdout}\n{refused.stderr}")
        self.assertIn("凭据门", refused.stderr)
        self.assertEqual(
            "1",
            adopt_fixture.hgit(target, "rev-list", "--count", "--all").stdout.strip(),
            "门开火了但提交仍然产生 —— 门形同虚设",
        )

    def test_adopt_is_idempotent_and_spares_a_user_hook(self) -> None:
        target, environment = self.adopt()
        hook = target / ".harness-vcs" / "hooks" / "pre-commit"
        first = hook.read_bytes()

        # ① 重跑：不重复堆、内容不变。
        again = adopt_fixture.run_adopt(target, environment)
        self.assertEqual(0, again.returncode, again.stderr)
        self.assertEqual(first, hook.read_bytes())

        # ② 用户自有钩子（无 marker）：绝不覆盖，且必须大声告警。
        hook.write_text("#!/bin/sh\n# 用户自己的钩子\nexit 0\n", encoding="utf-8")
        mine = hook.read_bytes()
        third = adopt_fixture.run_adopt(target, environment)
        self.assertEqual(mine, hook.read_bytes(), "用户自有钩子被覆盖了")
        self.assertIn("✗✗", third.stdout)
        self.assertIn("credential-gate", third.stdout)

    def test_template_is_executable_and_marked(self) -> None:
        self.assertTrue(GATE_SRC.exists())
        self.assertTrue(os.access(GATE_SRC, os.X_OK), "模板必须可执行，否则 hook 装上也不跑")
        self.assertIn("ARBORIST-CREDENTIAL-GATE:v1", GATE_SRC.read_text(encoding="utf-8"))

    def test_adopt_installs_gate_before_first_commit_and_never_overwrites_user_hook(self) -> None:
        adopt = (ROOT / "adopt.sh").read_text(encoding="utf-8")
        self.assertIn("hvcs_install_credential_gate", adopt)
        # marker 判据 = 幂等的依据（「文件存在」不能区分我们装的和用户自己的）
        self.assertIn("ARBORIST-CREDENTIAL-GATE:v1", adopt)
        self.assertIn("cmp -s", adopt)
        # 门必须先于 baseline commit 装上：事故正是发生在一次 blanket snapshot 上。
        install_at = adopt.index("hvcs_install_credential_gate || true")
        baseline_at = adopt.index('baseline: Arborist overlay adopted"')
        self.assertLess(install_at, baseline_at)

    def test_readme_and_guide_carry_the_scope_rule_together(self) -> None:
        readme = (GATE_SRC.parent / "README.md").read_text(encoding="utf-8")
        guide = (ROOT / "overlay/spec/guides/verification-and-gates.md").read_text(encoding="utf-8")
        for text, label in ((readme, "README"), (guide, "guide")):
            self.assertIn("授权不外推", text, label)
        # 规则与实现必须同时在位：规则先落是装饰，实现先落则无 scope 的授权成既成事实。
        self.assertIn("hook-templates/credential-gate/pre-commit", guide)
        self.assertIn("allowlist 条目必须写 `scope`", guide)


if __name__ == "__main__":
    unittest.main()
