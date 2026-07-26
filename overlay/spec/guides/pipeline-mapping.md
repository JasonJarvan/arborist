# HarnessStack 15-step Pipeline → <project> Trellis 落点

> 回答"HS 的 15 步进哪儿了"。the origin harness 是 15 步单一 Pipeline；<project> 是 Trellis 3 阶段（Plan/Execute/Finish）+ 定制层 + guides。逐步对照：

| HS 步 | 落点（Trellis 阶段 / guide） | 备注 |
|---|---|---|
| 1 ECC.research-first | workflow.md **Phase 1.0b**（research-first，codegraph 优先） | 从 Trellis 原 1.2〔optional·后〕提前为 required·先于 brainstorm |
| 2 RepoMem.read | **Phase 1.0b**（读 ADR+spec）+ `repomem-doc-boundary.md` | 与步1 合为 1.0b |
| 3 brainstorming | **Phase 1.1** = SP `brainstorming`（定制层） | 替代 trellis-brainstorm 对话部分 |
| 4 OpenSpec.explore/propose | **不吸纳**（D2）→ task `prd.md` 承担行为契约 | 有意损失，见 repomem-doc-boundary「累积契约摘要」补偿 |
| 4.1 grill-with-docs | workflow.md **1.2** 可选设计门（full·auto-judge） | 术语 sink 到 `.trellis/spec/` |
| 4.2 feasibility red-team | workflow.md **1.2** 可选（子代理 + codegraph file:line 证据） | |
| 5 RepoMem.capture（开 temp） | 本地 **task 目录** notes/research（git-ignored） | 描述性层 |
| 6 writing-plans | **Phase 1**（复杂）= SP `writing-plans` → `implement.md`（唯一权威） | plans/ 仅草稿 |
| 7a worktrees | **Phase 2** SP `using-git-worktrees`（对齐 `.worktrees/`） | |
| 7b executing-plans + TDD | **Phase 2.1** tdd loop + SP `subagent-driven-development`（in-session 派 L1）| executing-plans 仅"另会话跑 plan"才用 |
| 8 RepoMem.capture（持续） | task notes（→ 完成 WIMTB 进 Multica） | |
| 9 ECC.security-scan | `verification-and-gates.md`：**MR-into-release 硬 gate**（go→govulncheck / npm→npm audit） | 非 task archive |
| 10a OpenSpec.verify | **Phase 2.2** 逐条核对 `prd.md` 验收标准 | 无正式 spec，弱化版 |
| 10b verification-before-completion | **Phase 2.2** SP（与 trellis-check 并列双 lens） | |
| 11 requesting-code-review | **Phase 2.2/3** `/code-review`(+`/security-review`)+SP `requesting`/`receiving` | |
| 11.1 toTestTeam smoke | `verification-and-gates.md` 人工 smoke（web 前端用 playwright/webapp-testing） | 风险触发：(a) 用户可见/外部接口 或 (b) 依赖框架/服务器运行时默认（任一命中）；(b) 命中的纯后端不豁免 |
| 12 finishing-a-development-branch | workflow.md **Phase 3.4** = defer <project> `/commit` `/pr` + 发布列车 | MR→当期 release |
| 13 OpenSpec.archive | `task.py archive` + **Multica WIMTB**（after_archive hook） | change 冻结→任务文档冻结 |
| 14 RepoMem.merge（HITL） | workflow.md **3.3** HITL 晋升门 + Challenge-before-ack + `repomem-doc-boundary.md` | |
| 15 RepoMem.prune/split | `methodology/local-docs-and-ignore.md`（周期性，非每任务） | journal/archive 清理 |

## 结构差异小结
- HS 单一线性 15 步 → Trellis 3 阶段 + **角色分层**（L1–L4 各挑子集，见 `roles-and-tiering.md`）：不是每 session 都跑全 15 步，按角色/Lane 裁剪。
- **门控**（HS Execution Policy）横切在各步：见 `execution-policy.md`（auto/auto-judge/ask-first/HITL）。
- **不吸纳**：OpenSpec 正式 specs（步4，D2）、Task-ID 三-id 不变式（Trellis 单 id）、version-plan（发布列车替代）。
- HS 无、Trellis/本仓有：`trellis mem` 跨工具对话检索、per-turn breadcrumb、codegraph MCP。
