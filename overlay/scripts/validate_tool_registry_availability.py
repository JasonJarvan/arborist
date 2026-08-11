#!/usr/bin/env python3
"""工具注册表的可用性探测判据门:探测不得只读退出码,也不得与 invoke 形态相左。

## 两条判据,各自来自一次实测

### ① 每条 `availability` 必须配一条 `availability_expect`(期望正文特征)

**成功的信号和失败的信号常走同一个出口。** 三个实测:

| 工具 | 命令 | 退出码 | 正文 |
|---|---|---|---|
| multica | `multica auth status` | **rc=0** | `Token is invalid or expired: … 401` |
| codegraph | `codegraph status` | **rc=0** | `⚠ Not initialized` |
| agentsview | `agentsview serve status` | rc=0 | `running at …`(此例正文与退出码一致) |

前两条里,注册表原本写的判据是「`multica auth status` 通过」——**只读退出码就会把一个
空台账报成可用**。这不是命令写错,是判据本身缺了一半。

所以本门要求 `availability_expect` **存在且非空**:它必须说清「跑通了」与「能力真的
可用」怎么区分。缺字段 ⇒ 拒(读作 unknown,不读作 ok,与全篇 fail-safe 同向)。

这是 [`verification-and-gates.md`](../spec/guides/verification-and-gates.md) 里
「错误出口不得复用结论出口」的**镜像版**:那条管**被测工具**的出口,本条管**探测方**
的读法。工具把两种结局塞进同一个出口时,读表方唯一的补救就是读正文。

### ② `availability` 的参数序不得与 `invoke` 相左

实测:`arborist-brand-capacity` 的全局条目里 `invoke` 写
`… --repo <CALLER_REPO_ROOT> {refresh|status|…}`(选项在子命令**之前**),而
`availability` 写 `status --repo <CALLER_REPO_ROOT>`(选项在子命令**之后**)。
后者被 argparse 判为 `unrecognized arguments` 而 **rc=2** ——
**照着 availability 跑,会把一个好用的入口报成坏的。**

而这条条目的 `notes` 里恰恰写着「探测的必须是本条 `invoke` 用的**同一个入口形态**」。
它自己的 availability 违反了它自己写的规矩 —— 这正是「规则有了但没有执行者」的形状。

**判据是形态式的,子命令名从 `invoke` 自己的 `{a|b|c}` 里取,不在本文件里手列**:
凡某个顶层选项在 `invoke` 中出现在 `{…}` 之前,它就不得在 availability 文本里
出现在任一子命令名之后。

## 出口

    0 = 通过    1 = 有条目被拒    2 = usage(路径读不到 / 参数错)

错误出口不复用结论出口:一次打错路径不得返回成「有条目被拒」。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_USAGE = 2

SUBCOMMAND_GROUP = re.compile(r"\{([a-z][a-z0-9_|,-]*)\}")
TOP_LEVEL_OPTION = re.compile(r"--[a-z][a-z0-9-]*")


def subcommands_from(invoke_text: str) -> list[str]:
    """子命令名取自 invoke 自己的 `{a|b|c}`,不在本文件里手列。"""
    names: list[str] = []
    for group in SUBCOMMAND_GROUP.findall(invoke_text):
        names.extend(part for part in re.split(r"[|,]", group) if part)
    return names


def options_before_subcommand(invoke_text: str) -> list[str]:
    """在 `{…}` 之前出现的顶层选项。它们必须在子命令之前给。"""
    match = SUBCOMMAND_GROUP.search(invoke_text)
    if not match:
        return []
    return TOP_LEVEL_OPTION.findall(invoke_text[: match.start()])


def flatten(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(flatten(item) for item in value)
    return ""


def check_entry(name: str, entry: dict) -> list[str]:
    problems: list[str] = []

    availability = entry.get("availability")
    if not isinstance(availability, str) or not availability.strip():
        problems.append(f"{name}: 缺 `availability`(或为空)")

    expect = entry.get("availability_expect")
    if expect is None:
        problems.append(
            f"{name}: 缺 `availability_expect`。缺字段读作 unknown、不读作 ok —— "
            f"多个工具在能力不可用时仍以 rc=0 退出(multica token 失效、"
            f"codegraph 索引未初始化),只读退出码会把不可用报成可用"
        )
    elif not isinstance(expect, str) or not expect.strip():
        problems.append(f"{name}: `availability_expect` 为空。它必须说清「跑通了」与「真可用」怎么区分")

    invoke_text = flatten(entry.get("invoke", ""))
    probe_text = " ".join(
        text for text in (availability if isinstance(availability, str) else "",
                          expect if isinstance(expect, str) else "")
    )
    names = subcommands_from(invoke_text)
    for option in set(options_before_subcommand(invoke_text)):
        for sub in names:
            # 子命令名后面紧跟(允许中间有非命令字符之外的空白)该选项 ⇒ 参数序与 invoke 相左
            if re.search(rf"(?<![\w-]){re.escape(sub)}\s+{re.escape(option)}(?![\w-])", probe_text):
                problems.append(
                    f"{name}: 探测文本把 `{option}` 写在子命令 `{sub}` 之后,而 `invoke` 把它写在"
                    f" `{{…}}` 之前。顶层选项写在子命令之后会被 argparse 判为 unrecognized "
                    f"arguments(rc=2)⇒ 照 availability 跑会把一个好用的入口报成坏的"
                )
                break

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "paths", nargs="+", metavar="PATH",
        help="工具条目 json,或含条目的目录(递归)",
    )
    args = parser.parse_args(argv)

    files: list[Path] = []
    for name in args.paths:
        path = Path(name)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.json")))
        elif path.is_file():
            files.append(path)
        else:
            print(f"usage: 读不到 {path}", file=sys.stderr)
            return EXIT_USAGE

    if not files:
        print("usage: 没有找到任何 json 条目", file=sys.stderr)
        return EXIT_USAGE

    problems: list[str] = []
    for path in files:
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            print(f"usage: 读不到 {path}: {exc}", file=sys.stderr)
            return EXIT_USAGE
        except json.JSONDecodeError as exc:
            problems.append(f"{path}: 不是合法 json: {exc}")
            continue
        if not isinstance(entry, dict):
            problems.append(f"{path}: 顶层不是对象")
            continue
        problems.extend(check_entry(str(path), entry))

    if problems:
        print(f"refused: {len(problems)} 处", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_VIOLATION

    print(f"ok: {len(files)} 条目,每条都有非空 availability_expect,且探测参数序与 invoke 一致")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
