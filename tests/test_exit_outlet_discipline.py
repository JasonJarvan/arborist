"""铺出去的脚本的退出码纪律：**错误出口不得复用结论出口。**

判据的来源是一次**门在自己身上生效**的实测：`probe.py` 的 control 文件不可读时，原实现走
`SystemExit("<字符串>")`，而字符串形态**静默退出 1** —— 正是该程序表示「否定，已佐证」的
那个码。⇒ **一处路径笔误会以「一条确证的发现」的形态返回。** 由此得到的判据比那次修法更宽：

> **任何工具的错误出口都不得复用它的结论出口**，哪怕两者在数值上「碰巧」都表示不成功。

本文件是它的机械执行者，两条检查各自对应那次失败的一半：

1. **同一脚本内的 `EXIT_*` 常量必须两两不同** —— 守将来（有人给新结局挑了一个已占用的值）。
2. **不得出现 `sys.exit("<字符串>")` / `raise SystemExit("<字符串>")`** —— 守当时那个成因：
   字符串形态不声明码，它**变成 1**，于是复用了 1 号出口无论那是什么。

第 2 条是两条里更吃劲的：第 1 条只在作者**已经想到要给这个结局一个码**时才起作用，而那次
失败恰恰是**根本没想到这里有个结局**。
"""

from __future__ import annotations

import ast
import unittest
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "overlay" / "scripts"


def shipped_python_scripts() -> list[Path]:
    return sorted(p for p in SCRIPTS.glob("*.py") if p.is_file())


def exit_constants(tree: ast.AST) -> dict[str, int]:
    """模块级 `EXIT_* = <int 字面量>` 赋值。"""

    found: dict[str, int] = {}
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(
            node.value.value, int
        ):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.startswith("EXIT_"):
                found[target.id] = node.value.value
    return found


def string_valued_exits(tree: ast.AST) -> list[tuple[int, str]]:
    """`sys.exit("...")` / `SystemExit("...")`，含 f-string。

    只认**字面量**字符串（含 f-string）。传变量的情况这里不判 —— 那需要类型推断，而一条
    误报多的检查会被学会忽略（本仓已有通则），宁可漏判也不虚报。
    """

    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        func = None
        if isinstance(node, ast.Call):
            func = node.func
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            func = node.exc.func
            node = node.exc  # noqa: PLW2901 -- 参数取自这个 Call
        if func is None:
            continue
        name = (
            func.attr
            if isinstance(func, ast.Attribute)
            else func.id
            if isinstance(func, ast.Name)
            else None
        )
        if name not in {"exit", "SystemExit"}:
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.JoinedStr) or (
            isinstance(first, ast.Constant) and isinstance(first.value, str)
        ):
            hits.append((getattr(node, "lineno", 0), name))
    return hits


class ExitOutletDisciplineTests(unittest.TestCase):
    def test_scan_surface_is_not_empty(self) -> None:
        """一条扫不到东西的检查跟没有检查一样。"""
        self.assertGreater(len(shipped_python_scripts()), 5)

    def test_exit_constants_are_pairwise_distinct_within_a_script(self) -> None:
        failures: list[str] = []
        for path in shipped_python_scripts():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            by_value: dict[int, list[str]] = defaultdict(list)
            for name, value in exit_constants(tree).items():
                by_value[value].append(name)
            for value, names in sorted(by_value.items()):
                if len(names) > 1:
                    failures.append(
                        f"{path.relative_to(ROOT)}: {sorted(names)} 共用退出码 {value} "
                        "—— 错误出口不得复用结论出口"
                    )
        self.assertEqual([], failures, "\n".join(failures))

    def test_no_string_valued_exits(self) -> None:
        """字符串形态不声明码,它**变成 1** —— 于是复用了 1 号出口无论那是什么。"""
        failures: list[str] = []
        for path in shipped_python_scripts():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for lineno, name in string_valued_exits(tree):
                failures.append(
                    f"{path.relative_to(ROOT)}:{lineno}: {name}('<字符串>') 静默退出 1；"
                    "改为打印到 stderr 并退出一个具名常量"
                )
        self.assertEqual([], failures, "\n".join(failures))

    def test_the_detector_actually_fires(self) -> None:
        """守卫自测:两条检查都必须能在构造样本上命中。"""
        colliding = ast.parse("EXIT_A = 1\nEXIT_B = 1\n")
        by_value: dict[int, list[str]] = defaultdict(list)
        for name, value in exit_constants(colliding).items():
            by_value[value].append(name)
        self.assertEqual([2], [len(v) for v in by_value.values()])

        for source in (
            'import sys\nsys.exit("bad usage")\n',
            'raise SystemExit("bad usage")\n',
            'cmd = "x"\nimport sys\nsys.exit(f"unknown {cmd}")\n',
        ):
            with self.subTest(source=source):
                self.assertTrue(string_valued_exits(ast.parse(source)))

    def test_named_constant_exits_are_not_flagged(self) -> None:
        """假阳性会让门被学会忽略 —— 正确形态必须通过。"""
        for source in (
            "import sys\nEXIT_USAGE = 2\nsys.exit(EXIT_USAGE)\n",
            "EXIT_USAGE = 2\nraise SystemExit(EXIT_USAGE)\n",
            "import sys\nsys.exit(0)\n",
            "import sys\nsys.exit(main())\n",
        ):
            with self.subTest(source=source):
                self.assertEqual([], string_valued_exits(ast.parse(source)))


if __name__ == "__main__":
    unittest.main()
