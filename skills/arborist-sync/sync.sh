#!/usr/bin/env bash
# arborist-sync 机械助手（copy + sed + audit）。判断（冲突调解 / 隐私裁定）由 arborist-sync Skill 的 Agent 做。
# 用法：
#   sync.sh generalize <rel-path...>   # 实例 → staging，去具体值（push 用）
#   sync.sh specialize <rel-path...>   # Arborist → staging，填占位（pull 用）
#   sync.sh audit <dir>                # 扫隐私/内部信息，报可疑项（push 前必跑）
# env：ARBORIST_ROOT INSTANCE_ROOT INSTANCE_ABS PROJECT  [STAGING=/tmp/arborist-sync]
#      INTERNAL_NAMES="name1 name2"（可选：额外内部项目/组织名，审计时标红）
set -euo pipefail
STAGING="${STAGING:-/tmp/arborist-sync}"
cmd="${1:-}"; shift || true

_need() { for v in "$@"; do [ -n "${!v:-}" ] || { echo "需要 env $v" >&2; exit 2; }; done; }

case "$cmd" in
  generalize)
    _need ARBORIST_ROOT INSTANCE_ROOT INSTANCE_ABS PROJECT
    rm -rf "$STAGING"; mkdir -p "$STAGING"
    for rel in "$@"; do
      mkdir -p "$STAGING/$(dirname "$rel")"; cp "$INSTANCE_ROOT/$rel" "$STAGING/$rel"
      sed -i -e "s#$INSTANCE_ABS#<REPO_ROOT>#g" -e "s/\\b$PROJECT\\b/<project>/g" -e "s#$HOME#<HOME>#g" "$STAGING/$rel"
    done
    echo "generalized -> $STAGING（下一步：Agent 跑 audit + diff vs $ARBORIST_ROOT/overlay）" ;;
  specialize)
    _need ARBORIST_ROOT INSTANCE_ROOT INSTANCE_ABS PROJECT
    rm -rf "$STAGING"; mkdir -p "$STAGING"
    for rel in "$@"; do
      mkdir -p "$STAGING/$(dirname "$rel")"; cp "$ARBORIST_ROOT/overlay/$rel" "$STAGING/$rel"
      sed -i -e "s#<REPO_ROOT>#$INSTANCE_ABS#g" -e "s/<project>/$PROJECT/g" -e "s#<HOME>#$HOME#g" "$STAGING/$rel"
    done
    echo "specialized -> $STAGING（下一步：Agent diff vs $INSTANCE_ROOT/.trellis/spec + 冲突调解）" ;;
  audit)
    dir="${1:?给目录}"; hits=0
    echo "== 绝对 home 路径 =="; grep -rnE "/home/|/Users/" "$dir" && hits=1 || echo "  clean"
    echo "== 邮箱 =="; grep -rnE "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}" "$dir" && hits=1 || echo "  clean"
    echo "== UUID/疑似密钥 =="; grep -rnE "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}|[A-Za-z0-9_-]{32,}" "$dir" && hits=1 || echo "  clean"
    for n in ${INTERNAL_NAMES:-}; do echo "== 内部名 $n =="; grep -rn "$n" "$dir" && hits=1 || echo "  clean"; done
    echo "== AGPL 来源疑似（拷来的 Trellis seed 原文）=="; grep -rnE "Thinking Guides|didn't think of that|30 minutes of thinking|Most bugs and tech debt" "$dir" && hits=1 || echo "  clean"
    [ "$hits" = 0 ] && echo "AUDIT: ✓ 无可疑" || echo "AUDIT: ⚠️ 有命中——Agent 逐条人判（隐私/许可证来源），泄漏则修后重扫，未过不 push"
    exit 0 ;;
  verify-placeholders)
    dir="${1:?给目录}"; mode="${2:?instance|arborist}"
    if [ "$mode" = instance ]; then
      grep -rnE "<REPO_ROOT>|<project>|<HOME>" "$dir" && { echo "✗ 实例侧残留占位——特化不完整，不可写入"; exit 1; } || echo "✓ 无残留占位"
    else
      _need INSTANCE_ABS PROJECT
      grep -rnE "$INSTANCE_ABS|\\b$PROJECT\\b|$HOME" "$dir" && { echo "✗ Arborist 侧残留具体值——泛化不完整，不可 push"; exit 1; } || echo "✓ 无残留具体值"
    fi ;;
  status)
    _need ARBORIST_ROOT INSTANCE_ROOT INSTANCE_ABS PROJECT
    echo "两侧差异（对实例 guide 泛化后 diff Arborist overlay；仅列不同/仅一侧有的文件）:"
    cd "$INSTANCE_ROOT/.trellis/spec/guides" 2>/dev/null || { echo "无实例 guides"; exit 1; }
    find . -name '*.md' | sed 's#^\./##' | while read rel; do
      a="$ARBORIST_ROOT/overlay/spec/guides/$rel"
      [ -f "$a" ] || { echo "  [仅实例] $rel"; continue; }
      gen=$(sed -e "s#$INSTANCE_ABS#<REPO_ROOT>#g" -e "s/\\b$PROJECT\\b/<project>/g" -e "s#$HOME#<HOME>#g" "$rel")
      diff -q <(printf '%s' "$gen") "$a" >/dev/null 2>&1 || echo "  [差异] $rel"
    done
    (cd "$ARBORIST_ROOT/overlay/spec/guides" && find . -name '*.md' | sed 's#^\./##' | while read rel; do [ -f "$INSTANCE_ROOT/.trellis/spec/guides/$rel" ] || echo "  [仅 Arborist] $rel"; done)
    ;;
  *) echo "usage: sync.sh {generalize|specialize|audit} ..." >&2; exit 2 ;;
esac
