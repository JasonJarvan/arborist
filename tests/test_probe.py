"""`probe.py` 的测试：它是「取证命令本身会出错」那条通则的机械载体。

**为什么它需要自己的测试而不是被信任**：这个程序的全部价值在于**它扣住否定读数**。
若那道门本身失效，后果比没有这个程序更糟 —— 使用者会以为读数已被佐证。所以这里逐一钉住
四种结局各自的**退出码**（它们必须互不相同：`negative` 与 `inconclusive` 共用一个码就是
本程序要消除的那次坍缩），以及「control 也读负时结论指向 probe 而不指向被测物」这一格。

fixture 全在 `tempfile` 抛弃目录里，命令一律用 `sys.executable` 跑内联脚本 —— 不依赖
`grep`/`git` 等外部工具的存在与版本，也不碰任何真实仓。
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "overlay" / "scripts" / "probe.py"

EXIT_OK = 0
EXIT_NEGATIVE = 1
EXIT_INCONCLUSIVE = 4
EXIT_PROBE_SUSPECT = 5


def emit(stdout: str = "", rc: int = 0, stderr: str = "") -> list[str]:
    """一条可控的被测命令：想输出什么、想以什么码退出，都由参数决定。"""

    script = (
        "import sys;"
        f"sys.stdout.write({stdout!r});"
        f"sys.stderr.write({stderr!r});"
        f"sys.exit({rc})"
    )
    return [sys.executable, "-c", script]


class ProbeOutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def run_probe(self, argv: list[str]) -> tuple[int, dict]:
        completed = subprocess.run(
            [sys.executable, str(PROBE), *argv], capture_output=True, text=True
        )
        # 直接解析子进程的 stdout。**不经过任何 shell 回显** —— 实测过一次
        # `echo "$out"` 在某些 shell 下会解释反斜杠转义，把 JSON 里的 \n 变成真换行，
        # 于是失败表现为「被测程序输出了非法 JSON」，会被读成被测物的缺陷。
        return completed.returncode, json.loads(completed.stdout)

    def argv_file(self, name: str, argv: list[str]) -> str:
        path = self.base / name
        path.write_text("\n".join(argv) + "\n", encoding="utf-8")
        return str(path)

    # -- 正读数 --------------------------------------------------------------

    def test_positive_reading_passes_through(self) -> None:
        code, result = self.run_probe(["--", *emit(stdout="7\n")])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(result["outcome"], "positive")
        self.assertEqual(result["negative_reasons"], [])

    # -- 否定读数被扣住 ------------------------------------------------------

    def test_nonzero_rc_alone_is_withheld(self) -> None:
        code, result = self.run_probe(["--", *emit(stdout="data\n", rc=3)])
        self.assertEqual(code, EXIT_INCONCLUSIVE)
        self.assertEqual(result["outcome"], "inconclusive")
        self.assertIn("rc=3", result["negative_reasons"])

    def test_empty_output_is_withheld(self) -> None:
        code, result = self.run_probe(["--", *emit(stdout="")])
        self.assertEqual(code, EXIT_INCONCLUSIVE)
        self.assertIn("empty stdout", result["negative_reasons"])

    def test_zero_count_is_withheld(self) -> None:
        """`grep -c` 式的「0」是最典型的自带解释的否定读数。"""
        code, result = self.run_probe(["--", *emit(stdout="0\n")])
        self.assertEqual(code, EXIT_INCONCLUSIVE)
        self.assertIn("stdout is a zero count", result["negative_reasons"])

    def test_nonexistent_command_is_withheld_not_reported_as_absence(self) -> None:
        """实测形态：一条根本不存在的子命令，其失败被丢弃的 stderr 掩盖了十二次。"""
        code, result = self.run_probe(["--", str(self.base / "definitely-not-here")])
        self.assertEqual(code, EXIT_INCONCLUSIVE)
        self.assertIsNone(result["rc"])
        self.assertIn("command could not be executed", result["negative_reasons"])

    def test_withheld_reading_says_how_to_proceed(self) -> None:
        """扣住而不给出路就会被绕过（批准必须便宜）。"""
        _, result = self.run_probe(["--", *emit(stdout="0\n")])
        self.assertIn("--control-file", result["detail"])
        self.assertIn("--accept-unverified-negative", result["detail"])

    # -- control ------------------------------------------------------------

    def test_positive_control_corroborates_the_negative(self) -> None:
        control = self.argv_file("ctl", emit(stdout="ok\n"))
        code, result = self.run_probe(
            ["--control-file", control, "--", *emit(stdout="0\n")]
        )
        self.assertEqual(code, EXIT_NEGATIVE)
        self.assertEqual(result["outcome"], "negative")
        self.assertEqual(result["control"]["verdict"], "positive")

    def test_negative_control_blames_the_probe_not_the_subject(self) -> None:
        """本文件最重要的一格：结论必须指向 probe，而不是变成一条关于被测物的发现。"""
        control = self.argv_file("ctl", emit(stdout="", rc=2))
        code, result = self.run_probe(
            ["--control-file", control, "--", *emit(stdout="0\n")]
        )
        self.assertEqual(code, EXIT_PROBE_SUSPECT)
        self.assertEqual(result["outcome"], "probe-suspect")
        self.assertIn("says nothing about the subject", result["detail"])

    def test_control_and_subject_get_distinct_exit_codes(self) -> None:
        """「东西不在」与「我判不出它在不在」不得共用一个读数。"""
        self.assertNotEqual(EXIT_NEGATIVE, EXIT_INCONCLUSIVE)
        self.assertNotEqual(EXIT_NEGATIVE, EXIT_PROBE_SUSPECT)
        self.assertNotEqual(EXIT_INCONCLUSIVE, EXIT_PROBE_SUSPECT)

    def test_unreadable_control_file_is_a_usage_error_not_a_finding(self) -> None:
        """一处 operator 笔误绝不能以「已佐证的否定」的形态返回。

        这一条抓到过一个真缺陷:原实现走 `SystemExit("message")`,退出码是 **1** ——
        正是本程序表示「否定,已佐证」的那个码。⇒ 打错一个路径会读成一条确证的发现。
        """
        completed = subprocess.run(
            [
                sys.executable, str(PROBE),
                "--control-file", str(self.base / "absent"),
                "--", *emit(stdout="0\n"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, EXIT_NEGATIVE)
        self.assertNotEqual(completed.returncode, EXIT_OK)
        self.assertIn("cannot read argv file", completed.stderr)

    def test_control_file_ignores_comments_and_blanks(self) -> None:
        path = self.base / "ctl-commented"
        tokens = emit(stdout="ok\n")
        path.write_text(
            "# a control that reads positive\n\n" + "\n".join(tokens) + "\n",
            encoding="utf-8",
        )
        code, result = self.run_probe(
            ["--control-file", str(path), "--", *emit(stdout="0\n")]
        )
        self.assertEqual(code, EXIT_NEGATIVE)
        self.assertEqual(result["control"]["verdict"], "positive")

    # -- 显式接受 ------------------------------------------------------------

    def test_explicit_acceptance_records_the_reason_and_marks_it_uncorroborated(
        self,
    ) -> None:
        code, result = self.run_probe(
            [
                "--accept-unverified-negative",
                "checked by hand against a known instance",
                "--",
                *emit(stdout="0\n"),
            ]
        )
        self.assertEqual(code, EXIT_NEGATIVE)
        self.assertEqual(result["outcome"], "negative-unverified")
        # 理由必须留在产物里，否则「未佐证」这件事在下一个读者那里消失。
        self.assertEqual(
            result["accepted_without_control"],
            "checked by hand against a known instance",
        )
        self.assertIn("Treat as a lead, not a finding", result["detail"])

    # -- 流分离 --------------------------------------------------------------

    def test_streams_are_kept_apart(self) -> None:
        """合并两条流正是「静默 stdout 顺带静默失败」的成因。"""
        _, result = self.run_probe(["--", *emit(stdout="7\n", stderr="a warning\n")])
        self.assertEqual(result["stdout"], "7\n")
        self.assertEqual(result["stderr"], "a warning\n")

    def test_no_command_is_a_usage_error(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(PROBE)], capture_output=True, text=True
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("no command given", completed.stderr)


if __name__ == "__main__":
    unittest.main()
