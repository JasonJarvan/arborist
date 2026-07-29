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
# AgentTUI 直投 operational adapter（满足 ADR-0007 投递契约；带 --pane-id 定向）。
# 放 .trellis/scripts/ 而非 scripts/：脚本靠 __file__.parents[2] 定位 repo root，须两级深。
mkdir -p "$ROOT/.trellis/scripts"
cp "$SRC/scripts/agenttui.py" "$ROOT/.trellis/scripts/"; chmod +x "$ROOT/.trellis/scripts/agenttui.py"
# brand-capacity observer（单写者容量观测 + 建 Impler 前只读推荐；不启停会话/不改注册/不碰凭证）。
# 同样靠 __file__.parents[2] 定位 repo root，须放 .trellis/scripts/（两级深）。
cp "$SRC/scripts/arborist_brand_capacity.py" "$ROOT/.trellis/scripts/"; chmod +x "$ROOT/.trellis/scripts/arborist_brand_capacity.py"

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
HVCS_MARK_BEGIN="# >>> Arborist harness-vcs allowlist（勿手改块内；块外自加条目会被保留）>>>"
HVCS_MARK_END="# <<< Arborist harness-vcs allowlist <<<"
# 侧史 exclude 曾是裸 `/*` —— 那等于「一切未跟踪文件不可见」：baseline 那批因已跟踪还看得见，
# 但此后新建的 canonical 文件（新 guide、新 ADR、新 durable 脚本）是未跟踪 → 被静默吞掉，
# `hgit status` 看不见，gardener 以为已落定、durable 知识其实没进侧史。改为 allowlist。
# 幂等：块以标记界定，每次 adopt 重写块内、原样保留块外 adopter 自加条目（照上面
# .git/info/exclude 的 `grep -q "Arborist overlay"` 幂等精神，但升级为「可更新」而非「只追加」）。
# 效力边界（诚实化）：本 allowlist 写在 `$GIT_DIR/info/exclude`，而 gitignore 优先级是源级的
# —— 产品仓工作树里的 `.gitignore` 严格压过它。产品仓若把 `.trellis/` 一类 harness 目录写进
# 自己的 `.gitignore`，本 allowlist 对那些面【完全失效】（下面 hvcs_check_visibility 会探测并
# 大声告警）。此时 durable 面靠 `./hgit snapshot` 显式捕获，不依赖 untracked 可见性。
hvcs_write_exclude() {
  local exc="$ROOT/.harness-vcs/info/exclude" tmp
  mkdir -p "$ROOT/.harness-vcs/info"
  tmp="$exc.arborist.tmp"
  {
    printf '%s\n' "$HVCS_MARK_BEGIN"
    cat <<'ALLOWLIST'
# harness 侧史可见面 —— allowlist（不是裸 /*）：只让【durable 面】里的未跟踪新文件对
# `hgit status` 现形，其余（产品源码 / 构建物 / 运行时机器态）照旧隐身。
# 逐级 negation：git 不下降进被排除的目录，故每层父目录都要先 un-exclude，子目录的 ! 才命中。
# 注意本文件只对【未跟踪】文件有话说，且被产品仓工作树的 `.gitignore` 整源压过（见 adopt.sh
# 里 hvcs_check_visibility 的告警）。被压过时用 `./hgit snapshot` 显式捕获 durable 面。
/*
!/.trellis
/.trellis/*
# canonical 规范面：spec 层 + guides + guides/decisions（ADR），递归可见。
# machine-local 布局下这里是 spec/ADR 的唯一记史处，未跟踪新文件必须看得见（见
# spec/guides/repomem-doc-boundary.md「权威性 canonical」与 spec_visibility: machine-local）。
!/.trellis/spec
# durable harness 脚本面（agenttui.py / arborist_brand_capacity.py 及后续新增的随附脚本）。
# 注意只放 .trellis/scripts/：产品仓根的 scripts/ 是产品自己的面，整面 un-exclude 会把产品源码卷进侧史。
!/.trellis/scripts
!/.arborist
/.arborist/*
# 项目级工具登记 tool.json（能力声明 + fallback 兜底契约，gardener 手写的 durable 知识，
# 见 spec/guides/tool-registry.md §2）。同级 agents/ 是 session 活体态（session-id 主键、
# 心跳刷 last_seen）、templates/ 可从 overlay 重铺 —— 二者都不是 durable 知识，继续隐身。
!/.arborist/tools
!/.work_context
/.work_context/*
# 信件是形态 B 下的原始 durable 记录：sendbox.md §持久化与可见性 规范地要求
# 「`hgit add <file>` 按文件、勿整目录」—— 未跟踪新信若被 exclude 吞掉，那条指令根本执行不了
# （得加 -f）。故 sendbox/ 递归可见。
# 同级 Dashboard/ 是【对信件的投影】（可由信件重建，14 天滚动归档），按「可导出 ≠ 知识」判据
# 继续隐身，且不在 `hgit snapshot` 白名单里 → 也不会被钉成 tracked —— 与 .arborist/templates/
# 同理。`.work_context/` 根下其它文件（尤其 `multica.env` 一类凭证 env）同样，见下面 `*.env`。
!/.work_context/sendbox
# 运行时 / 缓存 / 备份 / 凭证面：放最后 —— gitignore 是 last-match-wins，本段压过上面的 allowlist。
# `*.env`：hook 配置经 env 文件下发（如 `.work_context/multica.env` 存 workspace/project id 与 token）；
# 本机侧史同样是可读态，凭证绝不进史。同一组后缀也是 `hgit snapshot` 的逐文件噪声过滤清单
# （snapshot_is_noise）—— 双保险：exclude 管未跟踪可见性，snapshot 过滤管别被 -f 钉成 tracked。
*.env
__pycache__/
*.pyc
*.pyo
*.bak
*.orig
*.rej
*.swp
*~
.DS_Store
ALLOWLIST
    printf '%s\n' "$HVCS_MARK_END"
    # 块外内容原样接在后面（last-match-wins → adopter 自己的条目有最终发言权）。
    # 只剔两类行：① 本块旧内容（按标记）；② 旧式裸 `/*`（其语义已由块首行接管；留在块后会把
    # 整张 allowlist 重新盖掉）。除此之外一行不动 —— 绝不吹掉 adopter 自加的条目。
    if [ -f "$exc" ]; then
      awk -v b="$HVCS_MARK_BEGIN" -v e="$HVCS_MARK_END" '
        $0 == b { in_block = 1; next }
        $0 == e { in_block = 0; next }
        in_block { next }
        $0 == "/*" { next }
        { print }
      ' "$exc"
    fi
  } > "$tmp"
  mv "$tmp" "$exc"
}

# allowlist 只在【无人压制】时才有效：gitignore 优先级是源级的 —— per-directory `.gitignore`
# 严格压过 `$GIT_DIR/info/exclude`。侧史的 work-tree 就是产品仓根，故产品仓工作树里的
# `.gitignore`（无论是否已跟踪）先裁决且胜出；而 `.trellis/`（带尾斜杠）会终止目录遍历，
# 底下任何 negation 都救不回来。很多 adopter（含 Arborist 自身仓）正把 harness 目录写进
# `.gitignore` 以免误提交 —— 对这些仓，侧史的 untracked 可见性【拿不回来】，git 语义封死了。
# 故：探测 + 大声告警 + 指向不依赖可见性的显式捕获（`./hgit snapshot`）。不中断 adopt
# （照上面 required 依赖检查的先例）。canary 路径无需真实存在，check-ignore 照样裁决。
HVCS_CANARIES=(
  .trellis/spec/guides/arborist-visibility-canary.md
  .trellis/scripts/arborist_visibility_canary.py
  .arborist/tools/arborist-visibility-canary.json
  .work_context/sendbox/toAgent/arborist-visibility-canary.md
)
hvcs_check_visibility() {
  # 用字符串累加而非数组：`set -u` 下老 bash 展开空数组会误报 unbound。
  local canary verdict src suppressed=""
  for canary in "${HVCS_CANARIES[@]}"; do
    # rc=1 → 未被忽略 → 该面的未跟踪新文件对 `hgit status` 现形（健康）。
    verdict="$(git --git-dir="$ROOT/.harness-vcs" --work-tree="$ROOT" \
                 check-ignore -v --no-index -- "$canary" 2>/dev/null)" || continue
    src="${verdict%%:*}"
    case "$src" in
      *info/exclude) continue ;;  # 侧史 allowlist 自己的裁决（本不该发生）→ 不算外部压制
    esac
    suppressed="$suppressed       ${canary%/*}/ ← $src"$'\n'
  done
  [ -z "$suppressed" ] && return 0
  echo "  ✗✗ 侧史 untracked 可见性被产品仓 .gitignore 压制（gitignore 优先级：.gitignore > info/exclude）："
  printf '%s' "$suppressed"
  echo "     后果：这些 durable 面里【新建的未跟踪文件】不会出现在 \`./hgit status\`。"
  echo "     durable 面须用显式快照捕获（不依赖 untracked 可见性）："
  echo "       ./hgit snapshot --dry-run   # 先看将暂存什么"
  echo "       ./hgit snapshot && ./hgit commit -m \"...\""
}

# durable 面暂存统一走 `./hgit snapshot` —— 单一真相在 overlay/scripts/hgit 的
# SNAPSHOT_PATHS，adopt 与日常落定用同一张白名单、同一套噪声过滤，不再各写一份。
# 为何不用 `add -f .trellis .work_context` 这类整面 force-add（旧做法）：
#   ① 会把运行时机器态（.trellis/tasks/** workspace/** agents/**、.work_context/Dashboard/**）
#      钉成 tracked —— exclude 只管未跟踪文件，钉上就再也隐不回去，与本文件下面
#      「运行时机器态照旧隐身」「Dashboard 继续隐身」的设计直接冲突；
#   ② 噪声只能靠 pathspec `:(exclude)` 剔，而 `:(exclude)` 配【带目录前缀】的正向 pathspec 会
#      静默丢文件（git 拿正向 pathspec 的 common prefix 长度去偏移 exclude 匹配串，指针越过
#      串尾）→ rc=0、无 stderr，`.claude/agents/*.md` 与 `.arborist/tools/**` 根本没被 add。
# snapshot 改为自己枚举文件、按名过滤、具名 add，零 `:(exclude)`。
# 不再 `2>/dev/null || true` 吞错：旧写法正是让 BLOCKER 2 那种「rc=0 却一个文件没 add」以及
# 真实 fatal 一起隐形的原因。这里捕获 rc → 失败就大声说，并跳过 baseline commit（宁可没基线，
# 也不要一个内容不明的基线 + 一句「✓ 已叠加」）。
hvcs_snapshot_durable() {
  if ! "$ROOT/hgit" snapshot; then
    echo "  ✗✗ durable 面快照失败（见上方 git 报错）—— 跳过 baseline commit"
    echo "     修掉报错后重跑：./hgit snapshot && ./hgit commit -m \"baseline: Arborist overlay adopted\""
    return 1
  fi
}

HVCS_OK=1
HVCS_FRESH=0
if [ ! -d "$ROOT/.harness-vcs" ]; then
  git --git-dir="$ROOT/.harness-vcs" --work-tree="$ROOT" init -q
  HVCS_FRESH=1
elif ! git --git-dir="$ROOT/.harness-vcs" --work-tree="$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  # `.harness-vcs/` 在但不是 git 仓（拷贝/解压/中断残留）。不敢 init 覆盖，也不能装作成功。
  HVCS_OK=0
  echo "  ✗✗ $ROOT/.harness-vcs 存在但不是 git 仓 —— 侧史（exclude 校正 / durable 快照）全部跳过"
  echo "     处置：确认无用后 rm -rf .harness-vcs 再重跑 adopt.sh；有用则手工修复该 git-dir"
fi
if [ "$HVCS_OK" = 1 ]; then
  # 修复守卫【每次 adopt 都跑】，不只首次创建 —— 否则现存 adopter 永远拿不到本修复。
  hvcs_write_exclude
  hvcs_check_visibility
  if [ "$HVCS_FRESH" = 1 ]; then
    if hvcs_snapshot_durable; then
      git --git-dir="$ROOT/.harness-vcs" --work-tree="$ROOT" -c user.name=harness-local -c user.email=harness@localhost commit -q -m "baseline: Arborist overlay adopted" || true
    fi
  else
    # 现存 adopter：只修 exclude，【不 stage 任何东西】。gardener 可能已备好选择性暂存
    # （只 stage 某几个 guide 待 commit）—— adopt 替他 add 会把运行态 churn 混进去、毁掉那份准备。
    echo "  · 侧史 exclude 已按 allowlist 校正（未暂存任何文件）。落定 harness 改动："
    echo "      ./hgit snapshot --dry-run   →   ./hgit snapshot && ./hgit commit -m \"...\""
  fi
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
# arborist-brand-capacity 无 offer_tool 行：它随 harness 铺（脚本上面已 cp 到 .trellis/scripts/，
# tool.json 模板随 arborist-templates/tools 递归铺），无外部安装步骤 —— 与 agenttui 同先例。
# offer_tool 用 command -v 探 PATH 二进制，对随附脚本会误报「未安装」，故不用。

cat <<'NEXT'

✓ overlay 已叠加。手动收尾：
  1) 把 overlay/workflow-customization.md 的定制层块粘进 .trellis/workflow.md（Core Principles 后），替换 <占位>。
     并按其尾注调整 Phase 1/2/3（research-first 前置、breadcrumb→SP、验证拓扑、ADR/HITL、defer git、WIMTB）。
  2) brand compatibility 已机械写入 AGENTS.md 与 workflow Phase Index；可跑
     `python3 scripts/install-brand-compat.py --source-tree /path/to/Arborist --check` 验证。
  3) 用 Multica 则设 env：MULTICA_WORKSPACE_ID / TRELLIS_MULTICA_PROJECT_ID，并在 .trellis/config.yaml 挂 hooks + session_auto_commit: false。
  4) 用 codegraph 则 `codegraph init && codegraph install`。
  5) 重启 AI session。harness 改动走 ./hgit（log/diff/checkout 回退）；落定用
     `./hgit snapshot --dry-run` 复核后 `./hgit snapshot && ./hgit commit -m "..."`
     —— snapshot 按显式 durable 白名单暂存并剔掉凭证/缓存/备份，不依赖 untracked 可见性。
NEXT
