# T8 · 本地文档 / gitignore 分层治理

> 源：`personal-local-gitignore-pattern` · `version-plan`（治理 nugget）。**是 <project> 本地文档约定 + `.work_context/` 的方法论背书。**

## 核心

- **三层 gitignore 分工**：
  - 项目共享、该被跟踪的忽略规则 → `.gitignore`（committed）；
  - 单人**本仓**本地产物（个人 prompt / 本地 doc / IDE 配置）→ `.git/info/exclude`（per-clone，不进 git）；
  - 跨仓个人垃圾 → `core.excludesFile`（全局）。
  - worktree 经 git-common-dir 一处写处处生效；`git check-ignore -v <path>` 诊断某文件被哪条规则忽略。
- **docs 分层治理**：长期共享产物进 trunk；**编排 / spec-change / 跨 session 信件 / 记忆等 per-process 状态 local-only**（避免编排噪音淹没真实代码 diff、拖慢 review）。
- roadmap 文档按"当前详细 / 未来方向 / 最远只列待验证"维护，版本完成时归档。

## <project> 现状（已对齐）
`.work_context/`（§12）承接过程文档；G0 把 `.trellis/tasks/`+`workspace/` 设 local-only；`.codegraph/` 本地。durable 团队知识（spec/guides/ADR/workflow.md）进 git。

## 本地文件治理（X2 · Q1 累积隐忧的落地）

`session_auto_commit: false` 后，本地 Trellis 产物无人自动 commit，会累积 → 需明确治理：
- `.trellis/workspace/<dev>/journal-*.md`（2000 行滚动、无限生成）：定期人工清理/归档；只保留近期 + index.md 摘要。**prune 上界建议**：单 dev 保留最近 3–5 个 journal 文件，更早的删（内容已在 git 历史/Multica）。
- `.trellis/tasks/archive/{年-月}/`（`task.py archive` 是**移动非删除**、无上界）：完成任务 **WIMTB 进 Multica 后**，本地 archive 目录可定期 `\rm -rf`（Multica 是持久副本）。
- **WIMTB 后本地 task 处置**：验证附件落地（`multica issue get` 看 `size_bytes` 非零）**之后**才 `rm` 本地 task 目录；未验证不删（Multica 是唯一副本时删了就丢）。
- 周期：跟随发布列车节奏（每个 release 周期过一遍），非每任务。

## 落点
workflow.md docs 治理规则；与 <project> 的本地工程文档约定呼应；Multica WIMTB 见 verification-and-gates。
