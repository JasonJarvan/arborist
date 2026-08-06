#!/usr/bin/env python3
"""`tool.json` 的入口形态一致性 validator：`invoke` 与 `availability` 不得混用两级入口。

**为什么这条要有机械执行者**：一条能力可以有两种入口形态 —— 全局单份权威入口
（`<ARBORIST_HOME>/bin/<shim>`）与项目内 adopted copy（`<repo>/.trellis/scripts/<x>.py`）。
两者的**仓根语义相反**：全局入口无从知道谁在调它，必须显式 `--repo`；项目副本的
`__file__` 确实在调用方仓内，推导正确。

实测发现的形状：两条已安装的全局条目里 `invoke.cli` 走全局 shim，而 `availability`
仍是 `python3 .trellis/scripts/<脚本>.py --help` —— 于是这条目**一边教人调全局入口、
一边拿项目副本证明它可用**。后果不是「探测失败」（项目副本通常也在），而是
**探测通过却证明了另一个东西**：读表方据此认为全局入口可用，而它可能根本没铺。
这正是 verification-and-gates「测试的结构必须与真实调用路径同构」在注册表这一层的实例。

**只读**：无 `--fix`、不执行任何外部命令、不联网、不写任何文件。修法要判「这条目应该是
哪一级」，那是 gardener 的裁定，不是脚本能替他做的。

用法::

    python3 validate_tool_entry_forms.py <path>...

`<path>` 可以是 `tool.json` 文件或含 `*.json` 的目录（递归）。退出码：
`0` 全部一致 / `1` 有条目混用入口形态 / `2` 路径不存在或 JSON 不可解析（fail closed
—— 「读不出这条目」不等于「这条目没问题」）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


EXIT_OK = 0
EXIT_INCONSISTENT = 1
EXIT_UNREADABLE = 2

# 入口形态的机械识别标记。刻意用**结构标记**而不是脚本名：一条目可以指任何脚本，
# 决定语义的是它位于全局那一份还是仓内那一份。
FORM_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("global", ("ARBORIST_HOME", "/.arborist/bin/", ".arborist/bin/")),
    ("project", (".trellis/scripts/",)),
)
# 参与判定的字段。`install` / `fallback` / `notes` 刻意**不**参与：fallback 的正当形态
# 就是「全局入口不可用时退回项目副本」，把它算进来会把一条正确的兜底判成不一致。
CHECKED_FIELDS = ("invoke", "availability")


def forms_in_text(text: str) -> set[str]:
    return {
        form for form, markers in FORM_MARKERS if any(m in text for m in markers)
    }


def strings_in(value: object) -> list[str]:
    """`invoke` 是对象（可多键并列）、`availability` 是字符串 —— 两种都要摊平。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings_in(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings_in(v)]
    return []


def check_entry(path: Path, entry: dict[str, object]) -> list[str]:
    """返回该条目的问题清单（空 = 一致）。"""
    problems: list[str] = []
    per_field: dict[str, set[str]] = {}
    for field in CHECKED_FIELDS:
        if field not in entry:
            continue
        found: set[str] = set()
        for text in strings_in(entry[field]):
            forms = forms_in_text(text)
            if len(forms) > 1:
                problems.append(
                    f"{path}: `{field}` 的单条命令同时含两级入口标记 "
                    f"({', '.join(sorted(forms))})：{text!r} —— 一条命令只能是一个入口形态"
                )
            found |= forms
        if found:
            per_field[field] = found

    forms = {form for found in per_field.values() for form in found}
    if len(forms) > 1:
        detail = "；".join(
            f"`{field}` → {', '.join(sorted(found))}"
            for field, found in sorted(per_field.items())
        )
        problems.append(
            f"{path}: 入口形态不一致（{detail}）。`availability` 必须探测 `invoke` "
            "所用的**同一个**入口：拿项目副本证明全局入口可用（或反之）时，探测通过"
            "却证明了另一个东西 —— 读表方会把一个可能根本没铺的入口当成可用"
        )

    scope = entry.get("scope")
    if forms == {"global"} and scope == "project":
        problems.append(
            f"{path}: `scope` 是 project，但 `invoke`/`availability` 指的是全局入口 "
            "—— scope 必须与所在级联层及入口形态一致（tool-registry §1）"
        )
    if forms == {"project"} and scope == "global":
        problems.append(
            f"{path}: `scope` 是 global，但 `invoke`/`availability` 指的是项目内副本 "
            "—— 全局条目不得教下游去调各仓自己的那一份"
        )
    return problems


def iter_entry_paths(paths: list[Path]) -> tuple[list[Path], list[str]]:
    found: list[Path] = []
    errors: list[str] = []
    for path in paths:
        if path.is_dir():
            found.extend(sorted(path.rglob("*.json")))
        elif path.is_file():
            found.append(path)
        else:
            errors.append(f"{path}: 路径不存在（fail closed：读不出的条目不算无问题）")
    return found, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "校验 tool.json 的 invoke 与 availability 指向同一个入口形态（只读，无 --fix）"
        )
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="tool.json 文件或含 *.json 的目录（递归）",
    )
    args = parser.parse_args(argv)

    entry_paths, unreadable = iter_entry_paths(args.paths)
    problems: list[str] = []
    for path in entry_paths:
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            unreadable.append(f"{path}: 不可读或非法 JSON（{exc}）")
            continue
        if not isinstance(entry, dict):
            unreadable.append(f"{path}: 顶层不是对象")
            continue
        problems.extend(check_entry(path, entry))

    for line in unreadable:
        print(f"unreadable: {line}", file=sys.stderr)
    for line in problems:
        print(f"inconsistent: {line}", file=sys.stderr)

    if unreadable:
        return EXIT_UNREADABLE
    if problems:
        return EXIT_INCONSISTENT
    print(f"ok: {len(entry_paths)} 条目的 invoke/availability 入口形态一致")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
