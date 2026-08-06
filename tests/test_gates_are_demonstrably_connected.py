"""每一道门上线时，必须同时存在一次**能让它开火**的构造。

判据（`verification-and-gates.md`「一道从未拒绝过任何东西的门…」）：

> 一道从未拒绝过任何东西的门，与不存在的门，**在读数上不可区分**。
> ⇒ 门上线时必须同时存在一次能让它开火的构造，**不得事后补**。
> ⇒ 记账口径：**零命中不得记为「干净」，只能记为「未回答」**。

**这里刻意不检查「它在生产里真的拒过东西」**：那会诱使人为了给门攒战绩而把违规样本塞进
生产。要检查的是**存在一次构造能让它开火** —— 那既证明门连着，又不需要真实世界配合。

**为什么这条检查是「形态式」而不是「枚举式」**（这两类的强弱见同一份 guide）：它不列举
「哪些门需要这样一个构造」（那会等于本文件作者的想象力），而是**对铺出去的每一个门一律
要求**，新增一个门若忘了配构造，它**当场**失败。⇒ 覆盖面不依赖本文件被更新。

## 两层，以及为什么必须是两层

第一版只按**测试函数名的词形**判（`fires` / `reject` / `detect` …）。那**本身是枚举式的**，
而且它的两半方向不同：名字不匹配 ⇒ 误判「未回答」（**假阳性，方向安全**）；名字带 `reject`
但其实只测放行 ⇒ 误判「已回答」（**假阴性，方向不安全**）。

修法不是去读断言写法——那只会把枚举**从函数名搬到断言写法上**（`assertRaises` / 非零码 /
`assertIn` 某标记……又是一张会被下一格推翻的表）。改判**因果**：

> **把门拿掉，测试必须变红。**

这不是新发明，**它就是那条通则的字面可执行形式**：通则说「一道从未拒绝过任何东西的门，与
不存在的门，在读数上不可区分」——那么证明二者**可**区分的唯一办法，就是**真的把门拿掉，看
读数变不变**。它不依赖任何命名、任何断言写法、任何作者的表达习惯。

⇒ 分层：**词形匹配只作必要条件**（用来挑出候选测试），**变异提供充分证据**。

**成本**：只对门做（当前 7 个），每格只跑**一条**候选测试，在抛弃目录里变异 ——
实测单次约半秒，不做全量变异。
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "overlay" / "scripts"
TESTS = ROOT / "tests"

# 铺出去的「门」= 会拒绝东西的脚本。判定按命名与职责，而不是逐个手列白名单
# （手列白名单本身就是枚举式的，会随新增的门腐烂）。
GATE_PATTERNS = ("validate_*.py", "probe.py")

# 一个测试函数名若含这些词，它测的是「门会拒绝」而不是「门在放行时不吵」。
FIRES = re.compile(
    r"(fires|catches|detect|reject|refus|fail|flag|blame|withheld|invalid|"
    r"conflict|mismatch|stale|violat|not_laid|drift)",
    re.IGNORECASE,
)


def shipped_gates() -> list[Path]:
    found: list[Path] = []
    for pattern in GATE_PATTERNS:
        found.extend(sorted(SCRIPTS.glob(pattern)))
    return found


def test_functions(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]


class GatesAreDemonstrablyConnectedTests(unittest.TestCase):
    def test_scan_surface_is_not_empty(self) -> None:
        """一条扫不到门的检查跟没有检查一样。"""
        self.assertGreaterEqual(len(shipped_gates()), 5)
        self.assertGreater(len(list(TESTS.glob("test_*.py"))), 10)

    def test_every_gate_has_a_construction_that_makes_it_fire(self) -> None:
        test_files = sorted(TESTS.glob("test_*.py"))
        cached = {path: (path.read_text(encoding="utf-8"), test_functions(path))
                  for path in test_files}

        missing: list[str] = []
        for gate in shipped_gates():
            name = gate.name
            stem = name[:-3] if name.endswith(".py") else name
            fires_in: list[str] = []
            for path, (source, functions) in cached.items():
                if name not in source and stem not in source:
                    continue
                if any(FIRES.search(function) for function in functions):
                    fires_in.append(path.name)
            if not fires_in:
                missing.append(
                    f"{gate.relative_to(ROOT)}: 没有任何测试文件既提到它、又含一个"
                    "「会开火」的测试函数。零命中不得记为「干净」，只能记为「未回答」"
                )
        self.assertEqual([], missing, "\n".join(missing))

    def test_the_check_would_notice_a_gate_with_only_happy_path_tests(self) -> None:
        """守卫自测：只有放行侧测试的门必须被判为「未回答」。

        用构造样本而不是真实文件 —— 真实文件全都合格（那正是本次的读数），所以只测真实
        文件的话，这条检查**永远不会开火**，于是它自己就成了它要防的那种门。
        """
        happy_only = ["test_clean_input_passes", "test_output_shape_is_stable"]
        self.assertFalse(any(FIRES.search(name) for name in happy_only))

        with_a_firing_test = happy_only + ["test_conflicting_entries_are_rejected"]
        self.assertTrue(any(FIRES.search(name) for name in with_a_firing_test))




class MutationProvesTheGateIsConnectedTests(unittest.TestCase):
    """把门拿掉,它的测试必须变红 —— 「门连着」的**因果**证据。

    变异一律在 `tempfile` 抛弃目录里做:**绝不改真实工作树**。一次崩溃若留下被变异的门,
    那本身就是一次静默失效,而它的形状正是本文件要防的东西。
    """

    #: 「拿掉门」= 用一个一律成功、且什么符号都不提供的桩替换它。作为 CLI 它永远放行,
    #: 作为被 import 的模块它没有任何符号 ⇒ 两种用法都会让「它会拒绝」的测试变红。
    #:
    #: ⚠️ `sys.exit(0)` **不得**放在模块层:那会在 import 时抛 `SystemExit(0)`,穿过
    #: unittest 的加载机制、让**整个测试进程以 0 退出** ⇒ 变异变得不可见,而变异那条
    #: 测试会「因为错误的原因通过」。这是本文件在自己身上撞到的第二次同族失误。
    STUB = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if __name__ == \"__main__\":\n"
        "    sys.exit(0)\n"
    )

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = TemporaryDirectory()
        cls.sandbox = Path(cls._tmp.name) / "tree"
        cls.sandbox.mkdir(parents=True)
        # 整棵产品树都要带(除隐藏项:`.git` 与被 git 排除的运行时面)。
        #
        # 为什么不是「只带 overlay/ 与 tests/」:有些门的测试跑的是 `adopt.sh`,而它又
        # 去取 `scripts/` 下的东西。少任何一件,候选测试会因**缺文件**而红或**根本选不中**
        # —— 那是来自另一层的读数,会让变异那条测试「因为错误的原因通过」。这一格是被
        # 下面那条 runner-fault 护栏抓出来的,不是想到的。
        for entry in sorted(ROOT.iterdir()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                shutil.copytree(entry, cls.sandbox / entry.name)
            else:
                shutil.copy2(entry, cls.sandbox / entry.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def candidates(self, gate_name: str) -> list[tuple[str, str]]:
        """(测试模块, 测试函数) —— 由词形匹配挑出,**只作必要条件**。"""
        # 文件名**或**模块名 —— 测试可能 `import validate_overlay_drift`(不带 `.py`)。
        # 只匹配带扩展名的那一种时,那道门的候选为空、被误判为「未回答」:一次由变异层
        # 自己抓到的匹配缺口。
        stem = gate_name[:-3] if gate_name.endswith(".py") else gate_name
        found: list[tuple[str, str]] = []
        for path in sorted(TESTS.glob("test_*.py")):
            source = path.read_text(encoding="utf-8")
            if gate_name not in source and stem not in source:
                continue
            for function in test_functions(path):
                if FIRES.search(function):
                    found.append((path.stem, function))
        return found

    RAN = re.compile(r"^Ran (\d+) test", re.MULTILINE)

    def run_in_sandbox(self, module: str, function: str) -> tuple[int, str]:
        """返回 (rc, 输出)。**选中 0 个测试视为跑器故障,不视为读数。**

        `-k` 选不中任何测试时 unittest 仍以 **0** 退出 ⇒ 「没变红」会被读成「门没连着」,
        而真相是**什么都没跑**。这一格与 `probe.py` 的 `probe-suspect` 同源:关于跑器的
        读数不得记进关于被测物的账。
        """
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "-k", function, f"tests.{module}"],
            cwd=self.sandbox,
            capture_output=True,
            text=True,
        )
        output = completed.stdout + completed.stderr
        match = self.RAN.search(output)
        if match is not None and int(match.group(1)) == 0:
            raise AssertionError(
                f"runner fault: `-k {function}` selected 0 tests in tests.{module}; "
                "that is a reading about the runner, not about the gate"
            )
        return completed.returncode, output

    def test_removing_each_gate_turns_one_of_its_tests_red(self) -> None:
        gates = shipped_gates()
        self.assertGreaterEqual(len(gates), 5, "扫不到门 —— 守卫本身失效了")

        unproven: list[str] = []
        for gate in gates:
            target = self.sandbox / "overlay" / "scripts" / gate.name
            original = gate.read_text(encoding="utf-8")
            proven_by: str | None = None
            try:
                target.write_text(self.STUB, encoding="utf-8")
                for module, function in self.candidates(gate.name):
                    rc, _ = self.run_in_sandbox(module, function)
                    if rc != 0:
                        proven_by = f"{module}.{function}"
                        break
            finally:
                # 复原,以免上一格的变异污染下一格的读数。
                target.write_text(original, encoding="utf-8")
            if proven_by is None:
                unproven.append(
                    f"{gate.relative_to(ROOT)}: 拿掉它之后,没有一条候选测试变红 "
                    "⇒ 「它连着」尚未被证明(零命中记为「未回答」,不是「干净」)"
                )
        self.assertEqual([], unproven, "\n".join(unproven))

    def test_the_unmutated_tree_is_green_for_the_same_tests(self) -> None:
        """对照组:同一批测试在**未变异**的沙箱里必须是绿的。

        少了这一组,上面那条会因为「测试本来就红」而虚假通过 —— 那正是
        `probe.py` 存在的理由(一个否定读数也可能是坏 probe 的产物)。

        **它当场抓到过一次**:第一版在沙箱里用了不带包前缀的模块名,于是**每一条**候选
        测试都因 `ModuleNotFoundError` 而红 ⇒ 变异那条测试**因为错误的原因通过了**。
        这就是「断言命中 ≠ 命中来自你以为的那一层」在本文件自己身上的一次。
        """
        checked = 0
        for gate in shipped_gates():
            for module, function in self.candidates(gate.name)[:1]:
                rc, output = self.run_in_sandbox(module, function)
                self.assertEqual(
                    0,
                    rc,
                    f"{module}.{function} 在未变异的沙箱里就是红的:\n" + output[-900:],
                )
                checked += 1
        self.assertGreaterEqual(checked, 5)


if __name__ == "__main__":
    unittest.main()
