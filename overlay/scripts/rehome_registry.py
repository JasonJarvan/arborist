#!/usr/bin/env python3
"""把注册表从一台机器搬到另一台:重算派生值,置空不能跨机继承的值。

## 为什么需要一个工具,而不是一次 sed

迁移流程做了一半:路径被重写了,**派生值没有跟着重算**。表面完全正常,而
`project_id` 是给 envelope 签名、用来回答「哪一个 project 实例」的依据 ——
**id 错等于跨仓寻址的依据错,且外观无异常。** `agenttui.py` 与
`validate_agenttui_registry.py` 都写明:

> The id is a derived value: the registration path must **compute** it, not accept it.

sed 改不出派生值。这就是本工具存在的理由。

## 三类字段,三种处置(形态式:按「这个值从哪来」分类,不枚举具体字段名)

| 类 | 例 | 处置 | 为什么 |
|---|---|---|---|
| **派生值** | `project.project_id` | **重算** | 从 realpath 派生;复制过来的就是错的 |
| **位置值** | `project.path` | **按叶子实际所在地改写** | 叶子躺在哪个仓里,那个仓就是权威 —— 与「跨仓镜像的权威是 home registry,不是镜像自己的快照」同一条原则 |
| **不可跨机继承的值** | `pane_ref` | **置空 + 记原因** | 见下 |

## `pane_ref` 为什么必须置空,而不是留着或猜

旧机的 `pane_ref` 形如 `{zellij, session=arborist, pane_id=terminal_6}`。新机上
**同名会话可能真的存在且活着** —— 于是那个 ref 不是「失效」,是**指向了别人**。
留着它,下一次投递就会往人**现在**在用的 pane 里打字。

`agenttui-registry.md` §5.0 的根规则已经答了这一格:**凡自识别证据不足以唯一确定
该 pane ⇒ 拒绝写入。** 一个跨机器搬过来的 pane_ref **不是证据**。置空是 fail-safe
方向:空 ⇒ 投递退到 resume 通道;陈旧 ⇒ 投递打进错的活 pane。

**置空不是修复,是解除危险。** 真正的修复只能由 owner 自登记时重新自识别完成——
校验器对半注册叶子写的也是同一句:*the owner repairs it by self-registering*。

## `session_file` 悬空路径:改写,不了就置空,绝不留悬空

按规则重映射家目录前缀;不中就按**文件名**去 `~/.codex/sessions` 与
`~/.claude/projects` 全库搜(transcript 属「改路径」不属「取回」)。两步都不中 ⇒
置 `null` 并记 `session_file_unresolved`。**绝不留一条指向不存在文件的路径** ——
悬空路径读起来像「有 transcript」,而 `null` 读起来像「没有」,后者是真的。

## 幂等 · 写前备份 · dry-run 默认

默认只报不改。`--apply` 才写,且写前把整棵 `.arborist` 与全局 index 复制进
带时间戳的备份目录。跑第二遍应当报 0 处改动 —— 这是幂等性的验收读数。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

EXIT_OK = 0
EXIT_CHANGES_PENDING = 1
EXIT_USAGE = 2
EXIT_REFUSED = 4

GLOBAL_INDEX = Path.home() / ".arborist" / "index.json"
BACKUP_ROOT = Path.home() / ".arborist" / "rehome-backups"
TRANSCRIPT_ROOTS = (Path.home() / ".codex" / "sessions", Path.home() / ".claude" / "projects")


def project_id_for(path: Path) -> str:
    """规范定义:realpath 归一化后的绝对路径的 sha256 前 12 位。**算,不接受。**"""
    return hashlib.sha256(os.path.realpath(path).encode()).hexdigest()[:12]


def remap_home(value: str) -> str:
    """把旧家目录前缀换成本机的。两种形态:真实路径,以及 claude 的路径编码目录名。"""
    home = str(Path.home())
    swapped = re.sub(r"^/(?:home|Users)/[^/]+", home, value)
    encoded = home.replace("/", "-")
    return re.sub(r"-(?:home|Users)-[^-]+-", f"{encoded}-", swapped)


def resolve_transcript(value: str | None) -> tuple[str | None, str | None]:
    """→ (可用路径 或 None, 无法解析时的原因)。绝不返回悬空路径。"""
    if not value:
        return None, None
    if Path(value).exists():
        return value, None
    remapped = remap_home(value)
    if Path(remapped).exists():
        return remapped, None
    basename = Path(value).name
    for root in TRANSCRIPT_ROOTS:
        if not root.is_dir():
            continue
        for hit in root.rglob(basename):
            return str(hit), None
    return None, f"not found on this machine (was {value})"


class Change:
    def __init__(self, where: str, field: str, before: object, after: object, why: str) -> None:
        self.where, self.field, self.before, self.after, self.why = where, field, before, after, why

    def __str__(self) -> str:
        return f"{self.where}: {self.field}\n    {self.before!r}\n  → {self.after!r}   ({self.why})"


def plan_leaf(repo: Path, leaf: Path) -> tuple[list[Change], dict, dict]:
    """返回 (改动清单, 新 spec, 新 runtime)。repo 由叶子实际所在地决定,不读声明值。"""
    changes: list[Change] = []
    spec = json.loads((leaf / "spec.json").read_text(encoding="utf-8"))
    runtime_path = leaf / "runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8")) if runtime_path.exists() else {}
    where = f"{repo.name}/{leaf.name}"

    real = os.path.realpath(repo)
    project = spec.setdefault("project", {})
    if project.get("path") != real:
        changes.append(Change(where, "project.path", project.get("path"), real,
                              "叶子实际所在地才是权威"))
        project["path"] = real
    computed = project_id_for(repo)
    if project.get("project_id") != computed:
        changes.append(Change(where, "project.project_id", project.get("project_id"), computed,
                              "派生值必须重算,不得沿用"))
        project["project_id"] = computed

    if runtime.get("pane_ref") is not None:
        changes.append(Change(where, "runtime.pane_ref", runtime.get("pane_ref"), None,
                              "pane 身份不能跨机继承;陈旧 ref 会投进别人的活 pane"))
        runtime["pane_ref"] = None
        runtime["pane_ref_cleared_reason"] = "rehomed across machines; owner must re-self-identify"

    resolved, reason = resolve_transcript(runtime.get("session_file"))
    if resolved != runtime.get("session_file"):
        changes.append(Change(where, "runtime.session_file", runtime.get("session_file"), resolved,
                              reason or "重映射到本机路径"))
        runtime["session_file"] = resolved
    if reason:
        runtime["session_file_unresolved"] = reason
    elif "session_file_unresolved" in runtime:
        del runtime["session_file_unresolved"]

    return changes, spec, runtime


def plan_index(repos: list[Path]) -> tuple[list[Change], dict, list[str]]:
    """全局索引:重写 path、**重算** project_id;并报半注册,但不 GC。"""
    changes: list[Change] = []
    notes: list[str] = []
    if not GLOBAL_INDEX.exists():
        return changes, {}, [f"全局索引不存在:{GLOBAL_INDEX}"]
    index = json.loads(GLOBAL_INDEX.read_text(encoding="utf-8"))
    for entry in index.get("projects", []):
        declared = entry.get("path", "")
        remapped = remap_home(declared)
        if remapped != declared:
            changes.append(Change("index", f"{entry.get('name')}.path", declared, remapped,
                                  "旧家目录前缀"))
            entry["path"] = remapped
        target = Path(entry["path"])
        if not target.is_dir():
            notes.append(f"index: {entry.get('name')} 的 path 不是目录,跳过 id 重算:{target}")
            continue
        computed = project_id_for(target)
        if entry.get("project_id") != computed:
            changes.append(Change("index", f"{entry.get('name')}.project_id",
                                  entry.get("project_id"), computed,
                                  "派生值必须重算"))
            entry["project_id"] = computed
        leaves = target / ".arborist" / "agents"
        for agent in entry.get("agents", []):
            if not (leaves / agent["name"] / "spec.json").exists():
                notes.append(
                    f"half-registered: index 记着 {entry.get('name')}/{agent['name']},"
                    f"但叶子不存在。**不得据此 GC** —— owner 自登记才是修复路径"
                )
    return changes, index, notes


def backup(paths: list[Path], stamp: str) -> Path:
    destination = BACKUP_ROOT / stamp
    destination.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if not path.exists():
            continue
        target = destination / path.name if path.is_file() else destination / f"{path.parent.name}-{path.name}"
        if path.is_dir():
            shutil.copytree(path, target, dirs_exist_ok=True)
        else:
            shutil.copy2(path, target)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", action="append", default=[], metavar="PATH",
                        help="要 rehome 的仓根(可重复)。只处理已有 .arborist 的仓")
    parser.add_argument("--index-only", action="store_true", help="只 rehome 全局索引")
    parser.add_argument("--apply", action="store_true", help="真写。默认只报不改")
    args = parser.parse_args(argv)

    if not args.repo and not args.index_only:
        print("usage: 至少给一个 --repo,或用 --index-only", file=sys.stderr)
        return EXIT_USAGE

    repos: list[Path] = []
    for name in args.repo:
        repo = Path(name)
        if not repo.is_dir():
            print(f"usage: 不是目录:{repo}", file=sys.stderr)
            return EXIT_USAGE
        repos.append(repo)

    all_changes: list[Change] = []
    writes: list[tuple[Path, dict]] = []

    for repo in repos:
        leaves = repo / ".arborist" / "agents"
        if not leaves.is_dir():
            print(f"skip: {repo} 没有 .arborist/agents —— 不是本工具能修的缺口"
                  f"(缺整棵注册表 ⇒ 先恢复或由 owner 自登记)")
            continue
        for leaf in sorted(leaves.iterdir()):
            if not (leaf / "spec.json").exists():
                print(f"skip: {leaf} 没有 spec.json")
                continue
            changes, spec, runtime = plan_leaf(repo, leaf)
            all_changes.extend(changes)
            if changes:
                writes.append((leaf / "spec.json", spec))
                writes.append((leaf / "runtime.json", runtime))

    index_changes, index, notes = plan_index(repos)
    all_changes.extend(index_changes)
    if index_changes:
        writes.append((GLOBAL_INDEX, index))

    for change in all_changes:
        print(change)
    for note in notes:
        print(f"note: {note}")

    if not all_changes:
        print("ok: 0 处改动 —— 已是 rehomed 状态(这条同时是幂等性的验收读数)")
        return EXIT_OK

    if not args.apply:
        print(f"\ndry-run: {len(all_changes)} 处待改。加 --apply 才写。")
        return EXIT_CHANGES_PENDING

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    saved = backup([repo / ".arborist" for repo in repos] + [GLOBAL_INDEX], stamp)
    print(f"\nbackup: {saved}")
    for path, payload in writes:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"applied: {len(all_changes)} 处。复跑一次应报 0 处改动。")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
