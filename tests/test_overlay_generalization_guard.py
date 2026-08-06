"""`overlay/` 泛化边界的第 2 层（正则检测）执行者。

`generalization-boundary.md` 的防御纵深有三层：预防（结构性排除）、检测（正则）、判断（模型/人）。
第 2 层此前在本仓**没有执行者** —— 一个绝对 home 路径 / 邮箱 / UUID / 长十六进制 session id
落进 `overlay/`（会被同步给 adopter 的那一面）时，没有任何东西会失败。本文件就是那个执行者。

**只查结构性模式，刻意不查私有代号**：把一份私有代号清单写进公开仓，本身就是它要防的那次泄漏；
且代号判定按同一份 guide 的分层属**第 3 层（模型/人）**。这也是「范例清单 vs 穷举清单」这条判据
施加在守卫自己身上的结果 —— 本守卫是**穷举的**（对它所列的那几类结构模式），但它覆盖的类别本身
是**范例的**（不声称抓全语义泄漏）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "overlay"

# 只扫文本文件；二进制/缓存不进扫描面。
TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".sh",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".txt",
    ".cfg",
    ".ini",
    "",
}
SKIP_DIR_NAMES = {"__pycache__", ".git"}

# 结构性泄漏模式。每一条都必须能给出「为什么它在被同步的文件里一定是实例值」。
LEAK_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        "absolute-home-path",
        r"/(?:home|Users)/[A-Za-z0-9._-]+",
        "绝对 home 路径是实例值；被同步文件里应写 <REPO_ROOT> / <HOME> 占位或引 host-config",
    ),
    (
        "email",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "邮箱是个人身份，属结构性排除项",
    ),
    (
        "uuid",
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        "UUID 通常是真实 session id / 实例标识；示例值请写 <session-id> 占位",
    ),
    (
        "long-hex-token",
        r"\b[0-9a-f]{32,}\b",
        "长十六进制串可能是真实 token / 摘要；示例请写 <sha256> 占位",
    ),
)

COMPILED = tuple((name, re.compile(pat), why) for name, pat, why in LEAK_PATTERNS)


def iter_overlay_text_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(OVERLAY.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        files.append(path)
    return files


def scan_text(text: str) -> list[tuple[str, int, str, str]]:
    """返回 (pattern_name, lineno, 命中片段, 理由)。"""
    hits: list[tuple[str, int, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, regex, why in COMPILED:
            match = regex.search(line)
            if match:
                hits.append((name, lineno, match.group(0), why))
    return hits


class OverlayLeakScanTest(unittest.TestCase):
    def test_overlay_tree_has_no_structural_instance_values(self) -> None:
        files = iter_overlay_text_files()
        self.assertGreater(len(files), 20, "扫描面为空或过小 —— 守卫本身失效了")

        failures: list[str] = []
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for name, lineno, snippet, why in scan_text(text):
                rel = path.relative_to(ROOT)
                failures.append(f"{rel}:{lineno} [{name}] {snippet!r} — {why}")

        self.assertEqual(
            [],
            failures,
            "overlay/ 出现结构性实例值（泛化边界第 2 层）：\n" + "\n".join(failures),
        )

    def test_scanner_catches_each_pattern(self) -> None:
        """守卫自己也要被测 —— 一条抓不到东西的检测跟没有检测一样。

        样本一律**由片段拼出**，不写字面量：否则这份测试自己就会成为它要防的那次泄漏，
        且会被本文件之外的同类扫描（adopter 侧、公开上推前的 audit）当成真命中。
        """
        home_path = "/" + "home" + "/" + "someone" + "/repo"
        address = "someone" + "@" + "example" + ".com"
        fake_uuid = "-".join(("0" * 8, "0" * 4, "0" * 4, "0" * 4, "0" * 12))
        samples = {
            "absolute-home-path": f"cd {home_path}",
            "email": f"联系 {address}",
            "uuid": f"session {fake_uuid} 已登记",
            "long-hex-token": "sha256 " + "a" * 40,
        }
        for expected, line in samples.items():
            with self.subTest(pattern=expected):
                names = [hit[0] for hit in scan_text(line)]
                self.assertIn(expected, names)

    def test_placeholder_forms_are_not_flagged(self) -> None:
        """假阳性会让门被学会忽略 —— 占位形式必须通过。"""
        for line in (
            "read_first: <REPO_ROOT>/.trellis/workflow.md",
            "全局根 = ${ARBORIST_HOME:-$HOME/.arborist}",
            "session_id: <session-id>",
            "记 `path@commit`，摘要写 <sha256>",
        ):
            with self.subTest(line=line):
                self.assertEqual([], scan_text(line))


class ThreeGeneralRulesLandedTest(unittest.TestCase):
    """三条通则的落点执行者：删掉标题或交叉引用会当场失败，而不是静默消失。

    这本身是「没有执行者的规则是装饰」施加在这三条规则自己身上。
    """

    def read(self, rel: str) -> str:
        return (OVERLAY / rel).read_text(encoding="utf-8")

    def test_gate_regression_rule_is_a_parallel_section_with_both_instances(self) -> None:
        text = self.read("spec/guides/verification-and-gates.md")
        self.assertIn(
            "### 门的回归必须端到端，且测试的结构必须与真实调用路径同构",
            text,
        )
        # 两个实例分属不同维度；少一个就会被读成「只有那一处要小心」。
        self.assertIn("**调用链层级**", text)
        self.assertIn("**进程 / shell 类型**", text)
        # 与观测扰动那条是并列关系，不是推论。
        self.assertIn("**与上一条并列，不是它的推论。**", text)
        # 案卷侧不得再自带一份通则正文（重复即漂移源）。
        registry = self.read("spec/guides/agenttui-registry.md")
        self.assertIn(
            "#门的回归必须端到端且测试的结构必须与真实调用路径同构",
            registry,
        )

    def test_landed_needs_an_independent_reading(self) -> None:
        text = self.read("spec/guides/verification-and-gates.md")
        self.assertIn("### 状态表里的「已落」必须附一条独立读数", text)
        # 证据是「同一天两个方向」；删掉它就退化成一个案例，而单向案例读起来
        # 像是某一方不可靠，而非信道不可靠。
        self.assertIn("同一天里两个方向都发生了", text)
        # fail-safe 方向单侧，且理由（假 ✅ 让该项从视野消失）必须留着。
        self.assertIn("判不准时不标「已落」", text)
        # 机械产物：不接受 owner 自报。
        self.assertIn("必须同格附一条读表方自己能复核的读数", text)
        # 语言侧那一半：只修读表侧修不掉。
        self.assertIn("已排入,未落", text)

    def test_capability_tri_state_landed_with_its_executor(self) -> None:
        registry = self.read("spec/guides/agenttui-registry.md")
        self.assertIn("#### 2.1.1 `capabilities`：记原因，不记布尔", registry)
        # 三值闭集缺一即不可路由。
        for value in ("`available`", "`policy-denied`", "`unavailable`"):
            self.assertIn(value, registry)
        # 存在的全部理由是这一句；删掉它就会有人把它简化回布尔。
        self.assertIn("策略禁用 ≠ 能力缺失", registry)
        # 缺字段读作 unknown，不是 available。
        self.assertIn("不读作 `available`", registry)
        # 执行者:validator 的闭集校验必须真在。
        validator = (OVERLAY / "scripts" / "validate_agenttui_registry.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("CAPABILITY_VALUES", validator)
        self.assertIn("capability-value-invalid", validator)

    def test_transient_carrier_rule_has_executor_and_failsafe_direction(self) -> None:
        text = self.read("spec/guides/verification-and-gates.md")
        self.assertIn("### transient 载体销毁前必须抽取判据", text)
        self.assertIn("**缺执行者的载体不得声明 `burn`。**", text)
        self.assertIn("判不准的不 burn，转 `archive`", text)

        sendbox = self.read("spec/guides/sendbox.md")
        self.assertIn("#transient-载体销毁前必须抽取判据", sendbox)
        self.assertIn("lifecycle_executor", sendbox)
        # 执行者字段必须同时在两份模板里，否则规范有字段、信里没有。
        for template in ("_TEMPLATE-handoff.md", "_TEMPLATE-done.md"):
            body = (OVERLAY / "work_context-templates" / "sendbox" / template).read_text(
                encoding="utf-8"
            )
            self.assertIn("lifecycle_executor:", body, template)

    def test_allowlist_rule_keeps_its_evidence_and_its_other_half(self) -> None:
        text = self.read("spec/guides/verification-and-gates.md")
        self.assertIn("## Allowlist over denylist", text)
        # 证据强度决定可信度，删它等于把跨域收敛降成一个案例。
        self.assertIn("两个互不相关的问题域各自独立到达同一结论", text)
        # 配套那半是必要条件；只留前半会造出一个被绕过的门。
        self.assertIn("**allowlist 必须让「批准」便宜。**", text)
        # `scope` 已落，且**必须**与它的执行者同在：规则先落是装饰，实现先落则
        # 无 scope 的授权已成既成事实。删掉任一半都会在这里当场失败。
        self.assertIn("allowlist 条目必须写 `scope`", text)
        self.assertIn("hook-templates/credential-gate/pre-commit", text)
        self.assertTrue(
            (OVERLAY / "hook-templates/credential-gate/pre-commit").exists(),
            "guide 指名了执行者，但那个执行者不在 —— 规则退化成装饰",
        )


if __name__ == "__main__":
    unittest.main()
