#!/usr/bin/env bash
# atui_launch.sh —— 启动一个 AgentTUI 的【唯一一段】启动逻辑，人类手启与 agent 派生共用。
#
# 为什么必须只有一段（不变量，见 agenttui-launch-and-brand-capacity.md §1.7）：
#   人类手启与 agent 派生若各写一份启动路径，`pane_ref` 值域、自识别方式、可达性判定会
#   分叉成两套，而分叉处的错误是【静默】的 —— 投递照样返回 rc=0，只是打在别处。故两侧
#   一律调本脚本；差异只允许出现在【可观测事实】上（有没有 tty），不允许出现在两份代码里。
#
# 本脚本【不装、不写、不改任何 shell 启动文件、不碰注册表】：
#   * 它不写 `.arborist/` 任何文件，也不代写 brand/role —— 实际 runtime brand 由被启动会话
#     自登记（ADR-0006）；本脚本收 `--brand/--role` 只为拼 session 名与打印计划。
#   * 要看它【将要】做什么用 `--dry-run`：逐条打印命令，一条都不执行。
#
# 逃生口（改的是人的交互环境，必须留）：`ARBORIST_ATUI_LAUNCH_WRAP=0` 即完全退回改造前的
#   启动形态（`env -u TRELLIS_CONTEXT_ID <cli> …`，不套任何复用器），有回归测试逐字钉住。
#
# 幂等：已在目标复用器内（`$TMUX` 非空）则直通，不再套一层 —— 反复嵌套会让 pane 句柄层级
#   不可预测，而【自识别门】（agenttui-registry.md §5.0）已实测过两次「认成外层/别人的 pane」。
set -euo pipefail

readonly WRAP_OFF_ENV="ARBORIST_ATUI_LAUNCH_WRAP"

usage() {
  cat <<'EOF'
用法：atui_launch.sh [选项] -- <cli> [cli 参数...]

选项：
  --project <path>        项目根（必填）。须含 .trellis/ 或 .git/，否则 fail-closed
                          （与 agenttui.py 的路径推导门同一形状：推不出就拒绝，绝不 mkdir）
  --multiplexer <名>      tmux | none（默认 tmux）。none = 不套复用器，原地起
  --socket <名或路径>     tmux server：含路径分隔符按 -S 路径，否则按 -L 名
                          （默认 arborist-<项目 slug>；显式给 "default" 用默认 server）
  --session <名>          session 名（默认 <项目 slug>-<pid>，即两段式命名第一段）
  --role <role>           仅进 session 名与计划输出；【不】写注册表
  --brand <brand>         同上。实际 runtime brand 由被启动会话自登记，本脚本不代写
  --bypass-flag <flag>    可重复。拼在 cli 参数之后（bypass 拼写属 adopter 本地实况）
  --dry-run               只打印将要执行的命令，什么都不执行
  -h, --help              本帮助

环境变量：
  ARBORIST_ATUI_LAUNCH_WRAP=0   逃生口：完全退回改造前形态（不套复用器）

为什么默认用私有 socket：本机默认 tmux server 上已住着别的工具的 session。共用默认 server
会让「同号 pane」在两个 server 间撞车（pane id 只在单个 server 内唯一），那正是 pane_ref
新增 socket 维度要消除的静默误投；顺带也避免本脚本的 session 级清理选项影响别人的 session。
EOF
}

die() { printf 'atui_launch: %s\n' "$1" >&2; exit "${2:-2}"; }

# --- 参数解析（"$@" 全程按数组传递；绝不用 "$*"，否则带空格的参数会被拆开） ------------
project=""
multiplexer="tmux"
socket=""
session=""
role=""
brand=""
dry_run=0
bypass_flags=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --project)      [ "$#" -ge 2 ] || die "--project 缺参数"; project="$2"; shift 2 ;;
    --multiplexer)  [ "$#" -ge 2 ] || die "--multiplexer 缺参数"; multiplexer="$2"; shift 2 ;;
    --socket)       [ "$#" -ge 2 ] || die "--socket 缺参数"; socket="$2"; shift 2 ;;
    --session)      [ "$#" -ge 2 ] || die "--session 缺参数"; session="$2"; shift 2 ;;
    --role)         [ "$#" -ge 2 ] || die "--role 缺参数"; role="$2"; shift 2 ;;
    --brand)        [ "$#" -ge 2 ] || die "--brand 缺参数"; brand="$2"; shift 2 ;;
    --bypass-flag)  [ "$#" -ge 2 ] || die "--bypass-flag 缺参数"; bypass_flags+=("$2"); shift 2 ;;
    --dry-run)      dry_run=1; shift ;;
    -h|--help)      usage; exit 0 ;;
    --)             shift; break ;;
    *)              die "未知选项：$1（cli 命令须写在 -- 之后）" ;;
  esac
done

[ "$#" -ge 1 ] || { usage >&2; die "缺少 -- <cli> …：本脚本不猜该起哪个 CLI"; }
[ -n "$project" ] || die "--project 必填：不从 cwd 猜项目根（猜错是静默的）"
[ -d "$project" ] || die "--project 不是目录：$project"

project_root="$(cd "$project" && pwd -P)"          # 归一化：解析 symlink、去尾斜杠
# 路径推导 fail-closed 门：目标须真是项目仓。与 agenttui.py 的 REPO_MARKERS 同一判据，
# 且同样按【存在】而非【是目录】判 —— git worktree 里 `.git` 是文件不是目录，按目录判会把
# 每个 worktree 都拒掉。推不出就拒绝，【绝不】造目录：`mkdir -p` 恰好会把错位置造得像本来就有。
[ -e "$project_root/.trellis" ] || [ -e "$project_root/.git" ] \
  || die "推导出的路径不是项目仓（须含 .trellis/ 或 .git/）：$project_root"

# --- 名字段（只用注册表允许的外部命名空间字符：tmux session 名不许 '.' 与 ':'） --------
slug="$(basename -- "$project_root" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9-' '-')"
slug="${slug//----/-}"; slug="${slug//---/-}"; slug="${slug//--/-}"
slug="${slug#-}"; slug="${slug%-}"
[ -n "$slug" ] || die "项目名归一化后为空，请显式 --session"

# 两段式命名第一段：`<项目>-<pid>`（可预测、不撞名）。第二段（改成
# `<项目>-<任务>-<role>`）由 ATUI 自登记时改名 —— 但**本脚本不改名**，理由见文末提示：
# 现行 tmux pane_ref 带 session 字段且投递前会核对它，改名会让既有句柄响亮失效。
[ -n "$session" ] || session="${slug}-$$"
[ -n "$socket" ] || socket="arborist-${slug}"

case "$multiplexer" in
  tmux|none) ;;
  *) die "--multiplexer 只支持 tmux | none（值域权威在 agenttui.py 的 transport 注册表）" ;;
esac

# --- 被启动命令：清掉继承的 session-context 身份，再拼 bypass flag ---------------------
# `env -u TRELLIS_CONTEXT_ID`：不清它，子会话会继承父 session 身份，进而投错 pane 或替
# 被启动方猜/写 brand（启动契约不变量 2）。
inner=(env -u TRELLIS_CONTEXT_ID "$@")
[ "${#bypass_flags[@]}" -eq 0 ] || inner+=("${bypass_flags[@]}")

# --- 是否套复用器（三条独立的「不套」理由，每条都要能被读出来） -----------------------
wrap="yes"
wrap_reason=""
if [ "${ARBORIST_ATUI_LAUNCH_WRAP-}" = "0" ]; then
  wrap="no"; wrap_reason="逃生口 $WRAP_OFF_ENV=0：退回改造前形态"
elif [ "$multiplexer" = "none" ]; then
  wrap="no"; wrap_reason="--multiplexer none"
elif [ -n "${TMUX-}" ]; then
  wrap="no"; wrap_reason="幂等：已在 tmux 内（\$TMUX 非空），不再套一层"
fi

if [ "$wrap" = "yes" ] && ! command -v tmux >/dev/null 2>&1; then
  # 刻意 fail-closed 而不是「悄悄不套」：不套的后果是被启动会话【没有】定向句柄，而这个
  # 差别在事后完全不可见（投递照样 rc=0，只是打不到）。要退回请显式用逃生口。
  die "tmux 未安装：不静默降级为不套复用器（差别不可见）。需要就用 $WRAP_OFF_ENV=0 显式退回"
fi

# --- 组装最终要执行的命令 -------------------------------------------------------------
plan=()
if [ "$wrap" = "no" ]; then
  plan=("${inner[@]}")
else
  socket_argv=()
  case "$socket" in
    */*) socket_argv=(-S "$socket") ;;   # 含路径分隔符 = socket 路径
    *)   socket_argv=(-L "$socket") ;;   # 否则 = socket 名
  esac
  # 有 tty ⇒ 前台起并附着（人类手启）；无 tty ⇒ detached 起（agent 派生路径没有终端可附着）。
  # 分支判据是一个【可观测事实】，两侧其余每一项（socket / 命名 / 清理钩子 / env 清除）逐字相同。
  attach_now="yes"
  [ -t 1 ] || attach_now="no"
  plan=(tmux "${socket_argv[@]}" new-session)
  [ "$attach_now" = "yes" ] || plan+=(-d)
  plan+=(-s "$session" -c "$project_root" -- "${inner[@]}")
  # session 生命周期与人类的关闭动作对齐，且【不依赖信号】（`trap SIGHUP` 已被实测推翻：
  # 真实用法是人在交互 shell 里粘命令，trap 落在交互 shell 上、不执行 ⇒ 留下看不见的活体）。
  #
  # 为什么是 client-attached 钩子而不是直接 `set-option destroy-unattached on`：
  # 实测（私有 socket 的 detached server）——对一个【当下无客户端】的 session 直接开该选项，
  # session 当场被销毁（server 随之消失）。那会杀掉「detached 起、还没人来看」的 ATUI。
  # 改成「第一个客户端附着时才打开」后实测：未附着期间 session 存活、选项为空；附着后选项
  # 变 on；客户端被杀（≈人类关掉外层窗口）⇒ session 与其中进程一并结束。
  # 已知代价：首次附着之后，【内层 detach】也会被销毁误伤（内层 detach 同样让 session 变成
  # 无客户端）。用【外层 detach】的人不受影响。两层的 detach 是两个不同动作，勿混。
  plan+=(\; set-hook -t "$session" client-attached "set-option -t $session destroy-unattached on")
fi

show() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
}

if [ "$dry_run" = "1" ]; then
  printf 'atui_launch --dry-run（什么都不会执行）\n'
  printf '  project      = %s\n' "$project_root"
  printf '  multiplexer  = %s\n' "$multiplexer"
  printf '  wrap         = %s%s\n' "$wrap" \
    "$([ -n "$wrap_reason" ] && printf '（%s）' "$wrap_reason")"
  if [ "$wrap" = "yes" ]; then
    printf '  socket       = %s\n' "$socket"
    printf '  session      = %s（两段式第一段；本脚本不改名，理由见下）\n' "$session"
  fi
  printf '  role/brand   = %s / %s（仅供人读；brand 由被启动会话自登记，本脚本不代写）\n' \
    "${role:-未给}" "${brand:-未给}"
  show "${plan[@]}"
  if [ "$wrap" = "yes" ]; then
    printf '提示：起完由【被启动会话自己】按 agenttui-registry.md §5.0 自识别门登记 pane_ref\n'
    printf '      （tmux 下权威句柄是 $TMUX_PANE 与 $TMUX 第一段的 socket 路径，不必猜）。\n'
    printf '提示：改成两段式第二段（<项目>-<任务>-<role>）会让既有 pane_ref 响亮失效——现行\n'
    printf '      tmux pane_ref 带 session 字段且投递前核对它。要改名必须【同时整条重建】\n'
    printf '      pane_ref，不能只改一个字段；故本脚本不代改名。\n'
    if [ "${attach_now-}" = "no" ]; then
      printf '提示：无 tty ⇒ detached 起。清理钩子在【首次附着】时才生效，故一个起了就没人\n'
      printf '      附着过的 session 不会自动消失，需显式 kill-session。\n'
    fi
  fi
  exit 0
fi

exec "${plan[@]}"
