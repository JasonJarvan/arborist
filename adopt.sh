#!/usr/bin/env bash
# Arborist adopt：把 overlay 叠进【当前目录=你的项目仓】。
# 前置：已 `trellis init`；在项目仓根运行 `bash /path/to/Arborist/adopt.sh`。
set -euo pipefail

ARBORIST_ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ARBORIST_ROOT/overlay"
BRAND_INSTALLER="$ARBORIST_ROOT/scripts/install-brand-compat.py"
BRAND_VALIDATOR="$ARBORIST_ROOT/scripts/validate_brand_compat.py"
BRAND_PROJECT_SOURCE="$ARBORIST_ROOT/overlay/project-instructions/brand-compat.md"
BRAND_WORKFLOW_SOURCE="$ARBORIST_ROOT/overlay/workflow-phase-index-brand-compat.md"
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
mkdir -p "$ROOT/scripts"
cp "$SRC/scripts/trellis_multica_sync.py" "$ROOT/scripts/"
cp "$BRAND_INSTALLER" "$BRAND_VALIDATOR" "$ROOT/scripts/"
chmod +x \
  "$ROOT/scripts/install-brand-compat.py" \
  "$ROOT/scripts/validate_brand_compat.py"
cp "$SRC/scripts/hgit" "$ROOT/hgit"; chmod +x "$ROOT/hgit"

echo "→ 铺 .work_context 模板（不覆盖已存在）"
mkdir -p "$ROOT/.work_context"
[ -e "$ROOT/.work_context/sendbox" ]   || cp -r "$SRC/work_context-templates/sendbox"   "$ROOT/.work_context/"
[ -e "$ROOT/.work_context/Dashboard" ] || cp -r "$SRC/work_context-templates/Dashboard" "$ROOT/.work_context/"
mkdir -p "$ROOT/.work_context/sendbox"
[ -e "$ROOT/.work_context/sendbox/_handoff-config.yaml" ] || \
  cp "$SRC/work_context-templates/sendbox/_handoff-config.yaml" "$ROOT/.work_context/sendbox/"
[ -e "$ROOT/.work_context/sendbox/_TEMPLATE-handoff.md" ] || \
  cp "$SRC/work_context-templates/sendbox/_TEMPLATE-handoff.md" "$ROOT/.work_context/sendbox/"
HANDOFF_CONFIG="$ROOT/.work_context/sendbox/_handoff-config.yaml"
if ! grep -Eq '^brand_routing:[[:space:]]*$' "$HANDOFF_CONFIG" \
   || ! grep -Eq '^[[:space:]]+same_brand_policy:[[:space:]]+strict[[:space:]]*$' "$HANDOFF_CONFIG"; then
  echo "✗ 已存在的 _handoff-config.yaml 不兼容 cc-sendbox brand_routing strict schema；"
  echo "  Arborist 未覆盖该用户配置。请按 overlay 模板合并后重跑 adopt.sh："
  echo "  $SRC/work_context-templates/sendbox/_handoff-config.yaml"
  exit 1
fi

echo "→ 安装 brand compatibility 双可见块 + Claude agents"
[ -f "$BRAND_PROJECT_SOURCE" ] && [ -f "$BRAND_WORKFLOW_SOURCE" ] || {
  echo "✗ brand compatibility source 缺失"
  exit 1
}
python3 "$BRAND_INSTALLER" \
  --source-tree "$ARBORIST_ROOT" \
  --target-repo "$ROOT"
echo "→ 验证 brand compatibility source + target"
python3 "$ROOT/scripts/validate_brand_compat.py" \
  --source-tree "$ARBORIST_ROOT" \
  --target-repo "$ROOT"

echo "→ 写 .git/info/exclude（harness overlay 隐身于产品仓）"
EXC="$ROOT/.git/info/exclude"
grep -q "Arborist overlay" "$EXC" 2>/dev/null || cat >> "$EXC" <<'EOF'

# Arborist overlay — machine-local, never in product repo / branches / push
/.trellis/
/.work_context/
/.mcp.json
/.codegraph/
/scripts/trellis_multica_sync.py
/scripts/install-brand-compat.py
/scripts/validate_brand_compat.py
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

# worktree symlink 兼容：harness 目录被 worktree symlink 回主树后（见
# scripts/harness_worktree_link.sh），需【不带斜杠】的 exclude 形式才能让 git check-ignore 匹配到
# symlink。两形式都要：带斜杠的 `/.trellis/` 只匹配【真目录】、不匹配 symlink（否则 symlink 以
# `?? .trellis` 现形、git status 不归零）；不带斜杠的 `/.trellis` 兼匹配主树真目录与 worktree 里的
# symlink。exclude 在 common git dir，主树写一次覆盖所有 worktree。
# 独立守卫（含早期 adopt 增量补写）：判 .trellis 无斜杠形式是否已在。
grep -q '^/\.trellis$' "$EXC" 2>/dev/null || cat >> "$EXC" <<'EOF'

# Arborist overlay — 无斜杠形式（匹配 worktree 里 symlink 化的 harness 目录；见 scripts/harness_worktree_link.sh）
/.trellis
/.work_context
/.arborist
# 注意：/.claude 与 /docs 是 blanket 隐身。exclude 只作用于【未跟踪】文件——
# 若产品仓已 git-tracked docs/（或 .claude/），已跟踪文件不受影响，仅令其中未跟踪的新文件隐身。
/.claude
/docs
EOF

echo "→ 建本地 harness 版本仓 .harness-vcs（无 remote）"
if [ ! -d "$ROOT/.harness-vcs" ]; then
  git --git-dir="$ROOT/.harness-vcs" --work-tree="$ROOT" init -q
  printf '/*\n' > "$ROOT/.harness-vcs/info/exclude"
  git --git-dir="$ROOT/.harness-vcs" --work-tree="$ROOT" add -f \
    .trellis \
    .claude/agents/trellis-implement-full.md \
    .claude/agents/trellis-explore.md \
    AGENTS.md \
    scripts/trellis_multica_sync.py \
    scripts/install-brand-compat.py \
    scripts/validate_brand_compat.py \
    hgit \
    .work_context 2>/dev/null || true
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
  2) brand compatibility 已机械写入 AGENTS.md 与 workflow Phase Index；可跑
     `python3 scripts/install-brand-compat.py --source-tree /path/to/Arborist --check` 验证。
  3) 用 Multica 则设 env：MULTICA_WORKSPACE_ID / TRELLIS_MULTICA_PROJECT_ID，并在 .trellis/config.yaml 挂 hooks + session_auto_commit: false。
  4) 用 codegraph 则 `codegraph init && codegraph install`。
  5) 重启 AI session。harness 改动走 ./hgit（log/diff/checkout 回退）。
NEXT
