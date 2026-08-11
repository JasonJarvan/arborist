#!/usr/bin/env python3
"""shell 脚本里 `$var` 不得紧跟非 ASCII 字符 —— bash 3.2 会把首字节吞进变量名。

## 这条规则的来历(一次实测,以及它伪装成了什么)

macOS 自带 `/bin/bash` 是 **3.2.57**(许可证原因,Apple 不升级)。bash 3.2 在解析变量名时
**不认多字节字符**,于是:

    name=ok; set -u; echo "x $name：y"        # 全角冒号 ：= U+FF1A = EF BC 9A
    bash 3.2 → line 3: name<EF>: unbound variable        ← 0xEF 被并入了变量名
    bash 5   → x ok：y

`set -u` 之下这是硬失败。实测后果:`adopt.sh` 在 macOS 上 **rc=1**,于是
**adopter 装不上这套 harness**;仓内 12 个测试在 setUpClass 就炸。

**它当时伪装成了别的东西**:测试用 `subprocess(..., text=True)` 去解码 bash 吐的那个坏字节,
于是失败呈现为 `UnicodeDecodeError` —— 看起来像测试框架的编码问题,而真实缺陷是安装器炸了。
这是「取证命令的三种伪装」里的第三种(**数据在通往解析器的路上被改写**)的又一个实例。

## 判据是形态式的

不枚举变量名、不枚举字符:**凡 `$identifier` 后面紧跟一个非 ASCII 字节即拒**。修法是加花括号
(`${identifier}`),不是加 bash 版本门 —— 因为根因不是缺 bash4 特性(实测 `declare -A` /
`mapfile` / `${x,,}` 命中均为 0),而是解析多字节字符。

## 为什么这道门必须存在,而不是"改完就行"

写中文注释与中文输出的仓,**每写一行 `echo "…$var:…"` 都在重新引入它**,而 CI 若跑在
bash 5 上永远不会报。⇒ 这是典型的「正确做法与错误做法一样省事、但错误只在别人机器上炸」,
必须由门守,靠人记不住。
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# `$identifier` 紧跟一个非 ASCII 字节。按字节做,避免 Python 的 str 把多字节看成一个字符。
OFFENDER = re.compile(rb"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7F]")

SKIP_DIRS = {".git", ".harness-vcs", ".codegraph", "node_modules", "__pycache__"}


def shell_files() -> list[Path]:
    found: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix == ".sh" or path.name in {"hgit"}:
            found.append(path)
    return sorted(found)


class ShippedShellIsMultibyteSafeTest(unittest.TestCase):
    def test_no_shell_script_puts_a_bare_variable_before_a_non_ascii_byte(self) -> None:
        offenders: list[str] = []
        for path in shell_files():
            data = path.read_bytes()
            for match in OFFENDER.finditer(data):
                line = data[: match.start()].count(b"\n") + 1
                snippet = match.group(0).decode("utf-8", "replace")
                offenders.append(f"{path.relative_to(ROOT)}:{line}: {snippet!r} —— 改成 ${{…}}")
        self.assertEqual([], offenders, "\n".join(offenders))

    def test_the_scan_actually_covers_the_installer(self) -> None:
        """否则上一条会因为「一个文件都没扫到」而假绿。"""
        names = {path.name for path in shell_files()}
        self.assertIn("adopt.sh", names)
        self.assertIn("harness_worktree_link.sh", names)
        self.assertGreaterEqual(len(shell_files()), 3)


class TheCheckWouldFireTest(unittest.TestCase):
    """开火构造:门必须能抓到坏形式,否则它与没有门不可区分。"""

    def test_a_bare_variable_before_a_fullwidth_colon_is_caught(self) -> None:
        sample = 'echo "x $name：y"'.encode("utf-8")
        self.assertTrue(OFFENDER.search(sample))

    def test_the_braced_form_is_not_caught(self) -> None:
        sample = 'echo "x ${name}：y"'.encode("utf-8")
        self.assertIsNone(OFFENDER.search(sample))

    def test_a_variable_before_ascii_is_not_caught(self) -> None:
        self.assertIsNone(OFFENDER.search(b'echo "x $name: y"'))

    def test_a_variable_at_end_of_line_is_not_caught(self) -> None:
        self.assertIsNone(OFFENDER.search(b'echo "$name"\n'))


class TheCausalPremiseTest(unittest.TestCase):
    """证明这条规则的**前提**是真的,而不是照搬来的迷信。

    只在本机 bash 确实是 3.x 时才跑;bash>=4 上跳过并说明理由 —— 因为在 bash 5 上
    这个前提本来就不成立,强行断言只会得到一条假绿。
    """

    def test_bash_3_really_mis_parses_it(self) -> None:
        probe = subprocess.run(["bash", "--version"], capture_output=True, text=True)
        if probe.returncode != 0:
            self.skipTest("本机没有 bash")
        first = probe.stdout.splitlines()[0] if probe.stdout else ""
        if "version 3." not in first:
            self.skipTest(f"本机 bash 不是 3.x（{first.strip()}）—— 前提在此不成立,跳过而不是假绿")

        script = 'name=ok\nset -u\necho "x $name：y"\n'
        result = subprocess.run(["bash", "-c", script], capture_output=True)
        self.assertNotEqual(0, result.returncode, "bash 3.x 竟然接受了裸变量+全角字符?前提需重查")
        self.assertIn(b"unbound variable", result.stderr)

        braced = 'name=ok\nset -u\necho "x ${name}：y"\n'
        ok = subprocess.run(["bash", "-c", braced], capture_output=True)
        self.assertEqual(0, ok.returncode, ok.stderr)


if __name__ == "__main__":
    unittest.main()
