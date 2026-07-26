#!/usr/bin/env bash
# harness_worktree_link.sh —— 把 harness overlay 目录从【当前 worktree】symlink 回【主树】。
#
# 用途：
#   `git worktree` 只物化 tracked 文件；而 harness overlay（.trellis/ .work_context/
#   .arborist/ .claude/ docs/）对产品仓 git 隐身（写在 .git/info/exclude），所以新建的
#   worktree 里这些目录全缺。后果不是「读不到 spec」（绝对路径仍可读），而是【从 cwd 解析
#   仓根的工具静默返回空】：`task.py list` 在 worktree 里报 0（主树报 N）却不报错，任何跨任务
#   一致性自检都因此得到【假阴性】，且失效方向恰是护栏停止工作的方向。本脚本把这些目录 symlink
#   回主树，令 cwd 根工具、护栏、规则文件在 worktree 内恢复可用。
#
# 何时跑：**建完 worktree 立刻跑**（worktree 步的一部分）。之后每次进该 worktree 都可安全重跑。
#
#   git worktree add ../wt-xxx <branch>
#   cd ../wt-xxx && bash scripts/harness_worktree_link.sh   # ← 立刻
#
# 幂等：已是指向主树的正确 symlink → no-op；指向别处的旧 symlink → 重指；worktree 里已是真目录/
#   真文件 → 不覆盖、只告警跳过（避免吞掉 worktree 本地内容）；二次运行无副作用。
set -euo pipefail

# --- 定位主树（不写死路径）：worktree 的 --git-common-dir 指向主树的 .git；其父目录即主树根。 ---
common_git_dir="$(git rev-parse --git-common-dir 2>/dev/null)" || {
  echo "✗ 不在 git 仓内（git rev-parse 失败）" >&2; exit 1; }
common_git_dir="$(cd "$common_git_dir" && pwd)"          # 归一为绝对路径
main_tree="$(dirname "$common_git_dir")"                 # 主树根
this_git_dir="$(git rev-parse --absolute-git-dir 2>/dev/null)"
this_tree="$(git rev-parse --show-toplevel 2>/dev/null)"

# 主树自身（非 worktree）里 this_git_dir == common_git_dir：无需 symlink，直接 no-op。
if [ "$this_git_dir" = "$common_git_dir" ]; then
  echo "· 当前就在主树（非 worktree），无需 link。"
  exit 0
fi

echo "→ 主树: $main_tree"
echo "→ 当前 worktree: $this_tree"

# --- 被 symlink 的 harness 目录（git 隐身，worktree 里缺席）。 ---
# 注意：这些 symlink 要能被 `git check-ignore` 匹配、令 `git status` 归零，主树的
# .git/info/exclude 必须含【不带斜杠】形式（adopt.sh 负责写；带斜杠的 `/.trellis/` 只匹配
# 真目录、不匹配 symlink）。exclude 在 common git dir，主树写一次覆盖所有 worktree。
HARNESS_DIRS=(.trellis .work_context .arborist .claude docs)

# --- 故意【不】symlink 的两样，理由写明如下： ---
# ① codegraph 索引目录（如 .codegraph/）：索引基于【主树代码】构建。若在 worktree 里通过 symlink
#    复用主树索引，`impact`/依赖分析会对着【另一棵树】的代码状态给结论——那棵状态在本 worktree 并不
#    存在。静默给出错误结论，比「工具不可用」更糟。正确做法：要么在 worktree 内单独建一份索引，要么
#    把该能力当作不可用并上报（见 tool-registry fallback）。
# ② hgit 式 wrapper 及其 git-dir（hgit + .harness-vcs/）：wrapper 用 `dirname $0` 推根并把它作为
#    `--work-tree` 传给底层 git。若 symlink 到 worktree，`dirname $0` 解析出的根会指错树，令
#    --work-tree 落在错误的工作树上、快照错内容。它本就应只在主树里对主树运行。

relinked=0 noop=0 skipped=0 created=0

link_one() {
  local name="$1"
  local src="$main_tree/$name"
  local dst="$this_tree/$name"

  # 主树里源不存在 → 没什么可链，跳过（不同项目 harness 目录集可能有出入）。
  if [ ! -e "$src" ]; then
    echo "  · $name：主树无此目录，跳过"
    return 0
  fi

  if [ -L "$dst" ]; then
    # 已是 symlink：解析后与源同 → no-op；否则重指。
    if [ "$(readlink -f "$dst" 2>/dev/null || true)" = "$(readlink -f "$src")" ]; then
      echo "  · $name：已正确链接，no-op"
      noop=$((noop+1))
    else
      rm "$dst"
      ln -s "$src" "$dst"
      echo "  ↻ $name：旧链接重指 → $src"
      relinked=$((relinked+1))
    fi
  elif [ -e "$dst" ]; then
    # worktree 里是真目录/真文件：不覆盖，告警跳过（避免吞掉 worktree 本地内容）。
    echo "  ⚠ $name：worktree 内已存在真实目录/文件，未覆盖（如需 link 请人工确认后移除）" >&2
    skipped=$((skipped+1))
  else
    ln -s "$src" "$dst"
    echo "  ✓ $name：新建链接 → $src"
    created=$((created+1))
  fi
}

echo "→ 链接 harness 目录"
for d in "${HARNESS_DIRS[@]}"; do
  link_one "$d"
done

echo "✓ 完成：新建 $created · 重指 $relinked · 已在位 $noop · 跳过 $skipped"
echo "  提示：worktree 里搜索用 grep -R（跟随 symlink 目录），别用 -r（静默零命中）。"
echo "  提示：写 symlink 化的 harness 目录 = 写共享主树状态，会立刻影响所有并发 session。"
