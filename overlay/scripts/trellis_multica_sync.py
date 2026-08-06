#!/usr/bin/env python3
"""Trellis <-> Multica sync hook (Arborist).

一个 Trellis task = 一个 Multica issue；parent/child ↔ L3/L2（父/子 issue）。
由 .trellis/config.yaml 的 hooks 调用，收 TASK_JSON_PATH：
  after_start   -> on-start   : 建/关联 L2 issue（有 parent 则挂 L3 父 issue）
  after_archive -> on-archive : WIMTB — 附 durable 文档 + 摘要 -> 验证 size_bytes -> status done

配置经环境变量（不硬编码）：
  MULTICA_WORKSPACE_ID      必填
  TRELLIS_MULTICA_PROJECT_ID 必填（目标项目）
不变式：失败不阻塞（记 pending 退 0）；WIMTB verify-before-rm（本脚本只 attach+验证，不 rm 本地）。
"""
import json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ID = os.environ.get("MULTICA_WORKSPACE_ID", "")
PROJECT_ID = os.environ.get("TRELLIS_MULTICA_PROJECT_ID", "")
PENDING_LOG = Path(".work_context/trellis-multica-pending.yaml")


def _require_cfg():
    if not WORKSPACE_ID or not PROJECT_ID:
        raise RuntimeError("set MULTICA_WORKSPACE_ID and TRELLIS_MULTICA_PROJECT_ID env")


def _mc(args, stdin=None):
    env = {**os.environ, "MULTICA_WORKSPACE_ID": WORKSPACE_ID}
    r = subprocess.run(["multica", *args], input=stdin, capture_output=True,
                       text=True, env=env, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"multica {' '.join(args)} -> {r.returncode}: {r.stderr.strip()}")
    return r.stdout


def _pending(entry):
    PENDING_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    with PENDING_LOG.open("a") as f:
        f.write(f"- {{ at: {ts}, entry: {json.dumps(entry, ensure_ascii=False)} }}\n")


def _load(p):
    p = Path(p); return p, json.loads(p.read_text())


def on_start(task_json_path):
    _require_cfg()
    p, t = _load(task_json_path)
    meta = t.setdefault("meta", {})
    if meta.get("multica_issue"):
        return
    args = ["issue", "create", "--project", PROJECT_ID,
            "--title", f"{t.get('id','?')}: {t.get('title','')}"[:120],
            "--status", "in_progress", "--output", "json"]
    parent = t.get("parent")
    if parent:
        pj = Path(parent) / "task.json"
        if pj.exists():
            pm = json.loads(pj.read_text()).get("meta", {})
            if pm.get("multica_issue"):
                args += ["--parent", pm["multica_issue"]]
    prd = p.parent / "prd.md"
    out = _mc(args, stdin=prd.read_text()) if prd.exists() else _mc(args)
    meta["multica_issue"] = json.loads(out).get("id")
    p.write_text(json.dumps(t, indent=2, ensure_ascii=False) + "\n")
    print(f"[multica] L2 issue {meta['multica_issue']} <- {t.get('id')}")


def on_archive(task_json_path):
    _require_cfg()
    p, t = _load(task_json_path)
    key = t.get("meta", {}).get("multica_issue")
    if not key:
        return
    _mc(["issue", "update", key, "--status", "done"])  # status-first
    attach = [str(p.parent / n) for n in ("prd.md", "design.md", "implement.md") if (p.parent / n).exists()]
    rdir = p.parent / "research"
    if rdir.is_dir():
        attach += [str(x) for x in sorted(rdir.glob("*.md"))]
    args = ["issue", "comment", "add", key, "--content-stdin"]
    for a in attach:
        args += ["--attachment", a]
    _mc(args, stdin=f"Task {t.get('id')} done. WIMTB: task docs attached.\n")
    got = json.loads(_mc(["issue", "get", key, "--output", "json"]))
    ok = any(x.get("size_bytes", 0) > 0 for x in got.get("attachments", []))
    print(f"[multica] WIMTB {key}: attachments verified={ok} (verify-before-rm 由清理步执行)")


# 错误出口用具名常量,而不是 `sys.exit("<字符串>")`。字符串形态会**静默退出 1**,
# 于是「调用方用错了」与这个脚本的其它不成功结局共用一个读数 —— 调用方无从区分。
# 判据(实测于另一个脚本的一次自伤:一处路径笔误以「一条已佐证的否定发现」的形态返回):
# **任何工具的错误出口都不得复用它的结论出口**,哪怕两者在数值上碰巧都表示不成功。
EXIT_USAGE = 2


def main():
    if len(sys.argv) < 2:
        print(
            "usage: trellis_multica_sync.py {on-start|on-archive} [TASK_JSON_PATH]",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)
    cmd = sys.argv[1]
    tj = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("TASK_JSON_PATH", "")
    try:
        {"on-start": on_start, "on-archive": on_archive}[cmd](tj)
    except KeyError:
        print(f"unknown cmd {cmd}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    except Exception as e:
        _pending({"cmd": cmd, "task_json": tj, "error": str(e)})
        print(f"[multica] {cmd} failed (queued, non-blocking): {e}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
