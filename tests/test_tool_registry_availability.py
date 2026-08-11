#!/usr/bin/env python3
"""`validate_tool_registry_availability.py` 的开火构造 + 铺出去的条目必须已过关。

按「门上线时必须同时存在一次能让它开火的构造(不得事后补)」——本文件与那道门同一个
commit 落地,且两条判据各自的坏样例是**先写的那半**。

两个坏样例都不是想象出来的:
- 缺期望正文 ⇒ 原 multica 条目就是「`multica auth status` 通过」,而该命令 token
  失效时仍 rc=0;
- 参数序相左 ⇒ 原 brand-capacity 全局条目 availability 写 `status --repo <R>`,
  实测 rc=2。
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "overlay" / "scripts" / "validate_tool_registry_availability.py"
TEMPLATES = ROOT / "overlay" / "arborist-templates" / "tools"

sys.path.insert(0, str(GATE.parent))
import validate_tool_registry_availability as gate  # noqa: E402


CLEAN = {
    "name": "demo",
    "kind": "cli",
    "invoke": {"cli": "demo --repo <CALLER_REPO_ROOT> {status|refresh} --help"},
    "availability": "`demo --repo <CALLER_REPO_ROOT> status` 只读探测",
    "availability_expect": "正文含 `ready`;正文说 not ready 即判不可用,不以退出码为准",
}


class GateRefusesTest(unittest.TestCase):
    def test_a_missing_expect_field_is_rejected(self) -> None:
        entry = {k: v for k, v in CLEAN.items() if k != "availability_expect"}
        problems = gate.check_entry("demo", entry)
        self.assertTrue(problems)
        self.assertIn("availability_expect", " ".join(problems))

    def test_an_empty_expect_field_is_rejected(self) -> None:
        entry = {**CLEAN, "availability_expect": "   "}
        self.assertTrue(gate.check_entry("demo", entry))

    def test_an_option_written_after_the_subcommand_is_rejected(self) -> None:
        """真实缺陷形态:invoke 把 --repo 写在 {…} 前,availability 写在子命令后。"""
        entry = {**CLEAN, "availability": "`demo status --repo <CALLER_REPO_ROOT>` 只读探测"}
        problems = gate.check_entry("demo", entry)
        self.assertTrue(problems)
        joined = " ".join(problems)
        self.assertIn("--repo", joined)
        self.assertIn("status", joined)

    def test_the_inverted_order_is_caught_in_the_expect_field_too(self) -> None:
        entry = {**CLEAN, "availability_expect": "先跑 `demo refresh --repo <R>` 再看正文"}
        self.assertTrue(gate.check_entry("demo", entry))

    def test_a_missing_availability_is_rejected(self) -> None:
        entry = {k: v for k, v in CLEAN.items() if k != "availability"}
        self.assertTrue(gate.check_entry("demo", entry))

    def test_subcommand_names_come_from_invoke_not_from_a_hardcoded_list(self) -> None:
        """形态式的证据:换一组子命令名,门照样开火 —— 说明它没有内置名单。"""
        entry = {
            **CLEAN,
            "invoke": {"cli": "demo --flag <X> {frobnicate|wibble} --help"},
            "availability": "`demo wibble --flag <X>`",
        }
        self.assertTrue(gate.check_entry("demo", entry))


class GateStaysQuietWhenItShouldTest(unittest.TestCase):
    """开火样例证明门有效;本组证明它不是「一律拒绝」—— 那种门会被学会忽略。"""

    def test_a_correct_entry_passes(self) -> None:
        self.assertEqual([], gate.check_entry("demo", CLEAN))

    def test_an_entry_with_no_subcommand_group_passes(self) -> None:
        entry = {**CLEAN, "invoke": {"cli": "demo --help"},
                 "availability": "`demo --help`"}
        self.assertEqual([], gate.check_entry("demo", entry))

    def test_an_option_that_invoke_puts_after_the_subcommand_is_not_flagged(self) -> None:
        entry = {
            "name": "demo",
            "invoke": {"cli": "demo {status|refresh} --json"},
            "availability": "`demo status --json`",
            "availability_expect": "正文是 JSON",
        }
        self.assertEqual([], gate.check_entry("demo", entry))


class ExitOutletTest(unittest.TestCase):
    """错误出口不得复用结论出口 —— 一次打错路径不能返回成「有条目被拒」。"""

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(GATE), *args],
                              capture_output=True, text=True)

    def test_an_unreadable_path_exits_usage_not_violation(self) -> None:
        with TemporaryDirectory() as tmp:
            result = self._run(str(Path(tmp) / "nope.json"))
        self.assertEqual(gate.EXIT_USAGE, result.returncode)
        self.assertNotEqual(gate.EXIT_VIOLATION, result.returncode)

    def test_the_three_exit_codes_are_pairwise_distinct(self) -> None:
        codes = [gate.EXIT_OK, gate.EXIT_VIOLATION, gate.EXIT_USAGE]
        self.assertEqual(len(codes), len(set(codes)))

    def test_a_bad_entry_exits_violation_end_to_end(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            entry = {k: v for k, v in CLEAN.items() if k != "availability_expect"}
            path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
            result = self._run(str(path))
        self.assertEqual(gate.EXIT_VIOLATION, result.returncode)


class ShippedTemplatesPassTest(unittest.TestCase):
    """连通性:铺出去的模板必须真的过这道门,否则门与产物脱节。"""

    def test_every_shipped_tool_template_passes_the_gate(self) -> None:
        result = subprocess.run(
            [sys.executable, str(GATE), str(TEMPLATES)],
            capture_output=True, text=True,
        )
        self.assertEqual(gate.EXIT_OK, result.returncode, result.stderr)

    def test_the_templates_directory_actually_holds_entries(self) -> None:
        """否则上一条会因为「一个条目都没扫到」而假绿。"""
        self.assertGreaterEqual(len(list(TEMPLATES.rglob("*.json"))), 5)


if __name__ == "__main__":
    unittest.main()
