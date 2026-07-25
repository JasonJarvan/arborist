#!/usr/bin/env bash
# Arborist adopt：把 overlay 叠进【当前目录=你的项目仓】。
# 前置：已 `trellis init`；在项目仓根运行 `bash /path/to/Arborist/adopt.sh`。
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)/overlay"
ROOT="$(pwd)"
[ -d "$ROOT/.trellis" ] || { echo "✗ 未见 .trellis/ —— 先 trellis init"; exit 1; }
[ -d "$ROOT/.git" ] || { echo "✗ 不是 git 仓根"; exit 1; }

# required 依赖检查（Trellis / Superpowers）：缺失 = harness 不完整 → 醒目告警 + 给装法，不中断铺设。
# 见 overlay/spec/guides/tool-registry.md §2.5。
echo "→ required 依赖检查"
if ! command -v trellis >/dev/null 2>&1; then
  echo "  ✗✗ Trellis CLI 未见于 PATH —— 不装没法用（init/update/task 流程全依赖它）"
  echo "     装法：npm i -g @mindfoldhq/trellis"
fi
if ! ls "$HOME"/.claude/plugins/cache/*/superpowers >/dev/null 2>&1 \
   && ! grep -qs '"superpowers@' "$HOME/.claude/plugins/installed_plugins.json"; then
  echo "  ✗✗ Superpowers 未安装 —— workflow 定制层各步骤依赖其 skills，不装没法用"
  echo "     装法：Claude Code 内 /plugin install superpowers@claude-plugins-official"
fi

echo "→ 铺 guides"
mkdir -p "$ROOT/.trellis/spec/guides"
[ -f "$ROOT/.trellis/spec/guides/index.md" ] && cp "$ROOT/.trellis/spec/guides/index.md" "$ROOT/.trellis/spec/guides/index.md.pre-st.bak" || true
cp -r "$SRC/spec/guides/." "$ROOT/.trellis/spec/guides/"

echo "→ 铺 scripts + hgit"
mkdir -p "$ROOT/scripts"; cp "$SRC/scripts/trellis_multica_sync.py" "$ROOT/scripts/"
cp "$SRC/scripts/hgit" "$ROOT/hgit"; chmod +x "$ROOT/hgit"

echo "→ 铺 .work_context 模板（不覆盖已存在）"
mkdir -p "$ROOT/.work_context"
[ -e "$ROOT/.work_context/sendbox" ]   || cp -r "$SRC/work_context-templates/sendbox"   "$ROOT/.work_context/"
[ -e "$ROOT/.work_context/Dashboard" ] || cp -r "$SRC/work_context-templates/Dashboard" "$ROOT/.work_context/"

echo "→ 写 .git/info/exclude（harness overlay 隐身于产品仓）"
EXC="$ROOT/.git/info/exclude"
grep -q "Arborist overlay" "$EXC" 2>/dev/null || cat >> "$EXC" <<'EOF'

# Arborist overlay — machine-local, never in product repo / branches / push
/.trellis/
/.work_context/
/.mcp.json
/.codegraph/
/scripts/trellis_multica_sync.py
/AGENTS.md
/hgit
/.harness-vcs/
/.arborist/
EOF

echo "→ 铺注册表骨架 .arborist/（AgentTUI + 工具；不覆盖已存在）"
mkdir -p "$ROOT/.arborist/agents" "$ROOT/.arborist/tools"
[ -e "$ROOT/.arborist/templates" ] || cp -r "$SRC/arborist-templates" "$ROOT/.arborist/templates"
# 独立守卫：早期 adopt 的仓（templates 已在、但无 tools/）增量补上工具模板
[ -e "$ROOT/.arborist/templates/tools" ] || { [ -d "$SRC/arborist-templates/tools" ] && cp -r "$SRC/arborist-templates/tools" "$ROOT/.arborist/templates/tools" || true; }
mkdir -p "$HOME/.arborist/tools"
[ -e "$HOME/.arborist/index.json" ] || printf '{\n  "projects": []\n}\n' > "$HOME/.arborist/index.json"

# 独立守卫：早期 adopt 的仓（已有 "Arborist overlay" 块）也能增量补上这一条
grep -q '^/\.arborist/$' "$EXC" 2>/dev/null || cat >> "$EXC" <<'EOF'

# Arborist registries (AgentTUI / tools) — machine-local runtime state, never committed
/.arborist/
EOF

echo "→ 建本地 harness 版本仓 .harness-vcs（无 remote）"
if [ ! -d "$ROOT/.harness-vcs" ]; then
  git --git-dir="$ROOT/.harness-vcs" --work-tree="$ROOT" init -q
  printf '/*\n' > "$ROOT/.harness-vcs/info/exclude"
  git --git-dir="$ROOT/.harness-vcs" --work-tree="$ROOT" add -f .trellis scripts/trellis_multica_sync.py hgit .work_context 2>/dev/null || true
  git --git-dir="$ROOT/.harness-vcs" --work-tree="$ROOT" -c user.name=harness-local -c user.email=harness@localhost commit -q -m "baseline: Arborist overlay adopted" || true
fi

# optional 工具置备（agentsview / multica / codegraph）：探测 → 交互时逐个问；绝不自动安装、
# 绝不改 agent 配置（MCP 接线）。登记 = 从模板拷 tool.json 到 ~/.arborist/tools/（幂等，不覆盖）。
# 拒装 → 打印 fallback，一切照常。见 overlay/spec/guides/tool-registry.md §2.5。
echo "→ optional 工具置备（不自动安装）"
offer_tool() { # $1=命令名 $2=装法 $3=fallback
  local name="$1" how="$2" fb="$3" ans=""
  local tpl="$SRC/arborist-templates/tools/$name.json" dst="$HOME/.arborist/tools/$name.json"
  if command -v "$name" >/dev/null 2>&1; then
    if [ -e "$dst" ]; then
      echo "  · $name：已安装、已登记（$dst）"
    elif [ -t 0 ] && [ -f "$tpl" ]; then
      read -r -p "  · $name 已安装，登记进 ~/.arborist/tools/？[y/N] " ans || true
      case "$ans" in
        y|Y) cp "$tpl" "$dst"; echo "    ✓ 已登记 $dst —— 把其中 <占位> 换成本机实况（invoke/availability/notes）";;
        *)   echo "    跳过登记；缺席时兜底：$fb";;
      esac
    elif [ -f "$tpl" ]; then
      echo "  · $name：已安装、未登记（非交互）。手动登记：cp $tpl $dst 并填实况"
    else
      echo "  · $name：已安装（无模板；要登记按 guide §2 手写 tool.json）"
    fi
  else
    if [ -t 0 ]; then
      read -r -p "  · $name 未安装，需要吗？（只给装法，不代装）[y/N] " ans || true
      case "$ans" in
        y|Y) echo "    装法：$how；装好后重跑 adopt.sh 或按 guide §2 登记";;
        *)   echo "    好——兜底：$fb";;
      esac
    else
      echo "  · $name：未安装（非交互）。装法：$how；兜底：$fb"
    fi
  fi
}
offer_tool agentsview '从其发布渠道装二进制，`agentsview serve` 启动' '手翻本地 journal / 各 brand 会话目录'
offer_tool multica    '`multica setup` / `multica login`' '台账退化为本地 .trellis/tasks/ + sendbox 交办；WIMTB 本地留档'
offer_tool codegraph  '`codegraph init && codegraph install`' '无符号图谱 MCP → 退回 grep/glob 检索代码'

cat <<'NEXT'

✓ overlay 已叠加。手动收尾：
  1) 把 overlay/workflow-customization.md 的定制层块粘进 .trellis/workflow.md（Core Principles 后），替换 <占位>。
     并按其尾注调整 Phase 1/2/3（research-first 前置、breadcrumb→SP、验证拓扑、ADR/HITL、defer git、WIMTB）。
  2) 用 Multica 则设 env：MULTICA_WORKSPACE_ID / TRELLIS_MULTICA_PROJECT_ID，并在 .trellis/config.yaml 挂 hooks + session_auto_commit: false。
  3) 用 codegraph 则 `codegraph init && codegraph install`。
  4) 重启 AI session。harness 改动走 ./hgit（log/diff/checkout 回退）。
NEXT
