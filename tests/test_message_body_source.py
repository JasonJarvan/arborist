"""`--message-file` 的执行者测试：形态 5（发送侧信封损坏）的机械修法。

**为什么这一格值得一个独立文件**：这不是一个参数的便利性测试。形态 5 已由**两个独立
发送方**各实测一次，第二次的成因是「**反引号在双引号内仍会被替换**」，而它的签名
**不是文本变短** —— 投出去的正文只多了两个空格，接收方**完全没察觉**。⇒ 修法必须是
「不提供出错形态」（正文不经 shell）而不是「提醒别出错」，因此这里测的是**接口是否
真的不提供那条出错路径**。
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
AGENTTUI = ROOT / "overlay" / "scripts" / "agenttui.py"


def run(argv: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AGENTTUI), *argv],
        capture_output=True,
        text=True,
        input=stdin,
    )


class MessageBodySourceTests(unittest.TestCase):
    """**层序是实测的,不是假设的。**

    第一版这个文件假设「正文解析先于仓根解析」,于是不传 `--repo`。结果两条测试
    **因为错误的原因通过了** —— 它们断言的字符串确实出现,但来自**仓根拒绝**那一层,
    正文根本没被解析过。实测层序相反：**仓根解析在前**。⇒ 这里给一个抛弃式假仓,让
    执行真的走到正文解析那一层；正文通过后会停在更晚的注册表读取,那正是「正文被接受」
    的可观察证据。

    （这次自伤本身是 `verification-and-gates.md`「取证命令本身会出错」的一个实例：
    一条断言在**它以为的那一层之外**被满足,而测试全绿。）
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        # 一个「像项目仓」的抛弃目录：足以过仓根解析,且没有注册表 ⇒ 正文解析之后
        # 必然停在注册表读取,给出一个与正文无关、可断言的更晚层错误。
        self.repo = self.base / "fake-repo"
        (self.repo / ".trellis").mkdir(parents=True)
        self.repo_args = ["--repo", str(self.repo)]

    LATER_LAYER = "missing registry file"

    def test_message_and_message_file_are_mutually_exclusive(self) -> None:
        """两个都给必须当场拒 —— 否则「哪个赢」会变成一个无人知道的默认。"""
        result = run(
            [
                *self.repo_args, "send", "--from", "a", "--to", "b",
                "--message", "x", "--message-file", str(self.base / "nope.txt"),
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not allowed with argument", result.stderr)

    def test_one_of_them_is_required(self) -> None:
        result = run([*self.repo_args, "send", "--from", "a", "--to", "b"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--message", result.stderr)

    def test_blank_body_from_a_file_is_refused_and_says_why(self) -> None:
        """空正文是「整段被替换吞掉」最可能的可观察痕迹。"""
        blank = self.base / "blank.txt"
        blank.write_text("   \n\t\n", encoding="utf-8")
        result = run(
            [*self.repo_args, "send", "--from", "a", "--to", "b",
             "--message-file", str(blank)]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("empty message body", result.stderr)
        # 错误信息必须指出成因与出路，否则读者会以为是自己文件写错了。
        self.assertIn("backticks are substituted even inside double quotes", result.stderr)

    def test_blank_body_from_the_literal_argument_is_refused_too(self) -> None:
        """同一道门必须两条来源都管 —— 只管文件那条等于没管被替换的那条。"""
        result = run(
            [*self.repo_args, "send", "--from", "a", "--to", "b", "--message", "   "]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("empty message body", result.stderr)

    def test_unreadable_message_file_fails_closed(self) -> None:
        result = run(
            [*self.repo_args, "send", "--from", "a", "--to", "b",
             "--message-file", str(self.base / "absent.txt")]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot read --message-file", result.stderr)

    def test_shell_metacharacters_survive_the_file_path(self) -> None:
        """本文件的要点：正文经文件时,反引号与 $() 必须**逐字**保留。

        断言方式是「正文被接受、失败发生在**更晚**的一层」：正文通过后停在注册表
        读取。若正文被吞成空,它会停在**更早**的一层（空正文拒绝),两者可区分。
        """
        body = self.base / "body.txt"
        payload = "keep `git status` and $(echo x) and 'quotes' verbatim"
        body.write_text(payload, encoding="utf-8")
        result = run(
            [*self.repo_args, "send", "--from", "a", "--to", "b",
             "--message-file", str(body)]
        )
        self.assertNotIn("empty message body", result.stderr)
        self.assertIn(self.LATER_LAYER, result.stderr)

    def test_stdin_is_accepted_as_a_body_source(self) -> None:
        result = run(
            [*self.repo_args, "send", "--from", "a", "--to", "b",
             "--message-file", "-"],
            stdin="body via stdin with `backticks`",
        )
        self.assertNotIn("empty message body", result.stderr)
        self.assertIn(self.LATER_LAYER, result.stderr)


if __name__ == "__main__":
    unittest.main()
