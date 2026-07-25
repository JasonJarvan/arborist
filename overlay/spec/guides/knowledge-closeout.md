# 知识收尾（洁癖式）— 交付后全仓知识一致性门

> 可选收尾门：`trellis-check` 只审**任务改动面**，此门补审「本次改动**连累**到的、改动面外的文档/规则/记忆是否还在说旧话」。**由收尾方自跑**——full lane 即 L2 Impler 收尾起草时自服务（见 [ADR-0004](./decisions/0004-closeout-split-l2-draft-l4-accept.md) 收尾职责分层），**不回弹给 rootorc**。

## §1 触发分级（先判跑不跑，省 token）
- **full lane / milestone 收口** → 跑。
- **fast lane** → 跳过，记 Auto-Skip Log（见 [`execution-policy.md`](./execution-policy.md)）。
- **gardener** → 周期性对 workspace / 跨项目档跑（非单任务触发）。

## §2 事实面矩阵（扫哪、答什么）
逐面自问「这次改动后它还准吗」，一面一行：

| 面 | 要答 |
|---|---|
| 代码 | 被改符号的调用点 / 签名引用是否同步 |
| 运行态 | 注册表 / 配置 / 环境态是否反映新事实 |
| 文档 | README / guide / 设计稿是否还说旧话 |
| 规则 | spec / ADR / workflow 是否与新行为一致 |
| 记忆 | RepoMem / mem 是否留有被推翻的旧结论 |
| 工作区 | sendbox / Dashboard / task 台账是否已收敛 |

- 每面状态 ∈ `verified-current` / `changed-and-verified` / `pending` / `out-of-scope` / `not-applicable`（**`not-applicable` 合法**）。
- 硬规则：**不许把未验证写成完成**；`git status` 干净 ≠ 全仓知识同步。

## §3 两阶段汇报 + 清场纪律
1. **阶段一 完整汇报**（骨架四段）：影响面 / 已改 / **待确认** / 遗留。
2. → 收尾方 / 人**确认** → 才进阶段二清场。
3. **删除候选未确认前一个不删**；任务初始的「随手清理」不算最终确认。

## §4 知识放置
放哪层、晋升与否，一律遵 [`repomem-doc-boundary.md`](./repomem-doc-boundary.md)，此处不复述。

---
inspired-by: neat-freak skill（仅借机制思路、自有措辞重述，未拷原文）— https://github.com/KKKKhazix/khazix-skills/blob/main/neat-freak/SKILL.md
