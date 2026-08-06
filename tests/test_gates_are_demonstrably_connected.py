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
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


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
            fires_in: list[str] = []
            for path, (source, functions) in cached.items():
                if name not in source:
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


if __name__ == "__main__":
    unittest.main()
