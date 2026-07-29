# 知识收尾（洁癖式）— 交付后全仓知识一致性门

> 可选收尾门：`trellis-check` 只审**任务改动面**，此门补审「本次改动**连累**到的、改动面外的文档/规则/记忆是否还在说旧话」。**由收尾方自跑**——full lane 即 L2 Impler 收尾起草时自服务（见 [ADR-0004](./decisions/0004-closeout-split-l2-draft-l4-accept.md) 收尾职责分层），**不回弹给 rootorc**。

## §1 触发分级（先判跑不跑，省 token）

**自动分级**（据 lane / 收口点自判）：
- **full lane / milestone 收口** → 跑。
- **fast lane** → 跳过，记 Auto-Skip Log（见 [`execution-policy.md`](./execution-policy.md)）。
- **gardener** → 周期性对 workspace / 跨项目档跑（非单任务触发）。

### 手动触发词表（可移植）
自动分级之外，用户可在**任意 lane** 显式点名要求跑本收尾门。以下词一律等价，视作对 knowledge-closeout 门的**显式手动触发**：

| 触发词 | 说明 |
|---|---|
| `/neat` | 语义命令别名；宿主即使无原生 slash-command 实现，也照此语义当手动触发处理 |
| `neat skill` | 自然语点名 |
| `洁癖 skill` | 自然语点名（中文） |

- **显式手动触发覆盖 fast lane 的正常 auto-skip**——任意 lane 收到上述任一词都**跑**收尾门，fast lane 也不例外（此时不记 Auto-Skip，改按门正常两阶段汇报走）。
- 反向不变：未点名上述词时，自动分级行为**一律照旧**——fast lane 仍正常跳过并记 Auto-Skip Log。

## §2 事实面矩阵（扫哪、答什么）
逐面自问「这次改动后它还准吗」，一面一行，**并给每条结论标类别与出处**：

| 面 | 要答 | 类别 | 出处 | 未验证缺口 |
|---|---|---|---|---|
| 代码 | 被改符号的调用点 / 签名引用是否同步 | 实测/推断 | command / codegraph / `path:line` | 无 或具体缺口 |
| 运行态 | 注册表 / 配置 / 环境态是否反映新事实 | 实测/推断 | probe / artifact | 无 或具体缺口 |
| 文档 | README / guide / 设计稿是否还说旧话 | 实测/推断 | search / diff | 无 或具体缺口 |
| 规则 | spec / ADR / workflow 是否与新行为一致 | 实测/推断 | search / validator | 无 或具体缺口 |
| 记忆 | RepoMem / mem 是否留有被推翻的旧结论 | 实测/推断 | query result | 无 或具体缺口 |
| 工作区 | sendbox / Dashboard / task 台账是否已收敛 | 实测/推断 | inventory / status | 无 或具体缺口 |

- 每面状态 ∈ `verified-current` / `changed-and-verified` / `pending` / `out-of-scope` / `not-applicable`（**`not-applicable` 合法**）。
- 硬规则：**不许把未验证写成完成**；`git status` 干净 ≠ 全仓知识同步。
- **本矩阵不是验收证据表**：它负责**扫事实面**。真正用于验收的最终结论另落 [`sendbox` 的标准四列表](./sendbox.md#done-信与验收证据的-claim-provenance-门) 并跑 `validate_claim_provenance.py`；两张表不互相替代、也不互相复述。

## §3 两阶段汇报 + 清场纪律
1. **阶段一 完整汇报**（骨架四段）：影响面 / 已改 / **待确认** / 遗留。
2. → 收尾方 / 人**确认** → 才进阶段二清场。
3. **删除候选未确认前一个不删**；任务初始的「随手清理」不算最终确认。

## §5 Landing manifest（收尾无条件产出）
本门查「改动**连累**到的改动面外文档是否还准」；与之并列，收尾**必须无条件产出 landing manifest**——记「本次**主动落/改**了哪些盘、谁看过」，**为空时也要显式产出**（省略 manifest 才是违规）。逐条含「哪个文件哪一节 / 新增 vs 改写既有结论 / 类别（task 本地约定·跨模块 spec·跨切 guide·ADR）/ 谁评审（`nobody reviewed this` 是显式允许的值）」，并**无条件补答两项**：① **`History proof`**——canonical 路径写 `path@hgit-commit`，未获 human commit 授权则明确 pending、**不得声称 durable**；② **`临时/共享资源生命周期`**——未命中写 `N/A`，命中则只记不含 secret 的 owner/consumer/权限/硬到期（或 managed 提升）与清理前「消费者为零」证据。它是荣誉制 HITL 晋升门、machine-local 持久性断言与临时资源清理计划的机械化替代——权威定义与栏位见 [`verification-and-gates.md` «Landing manifest»](./verification-and-gates.md#landing-manifest收尾无条件产出--hitl-晋升门的机械化替代)。

## §4 知识放置
放哪层、晋升与否，一律遵 [`repomem-doc-boundary.md`](./repomem-doc-boundary.md)，此处不复述。

---
inspired-by: neat-freak skill（仅借机制思路、自有措辞重述，未拷原文）— https://github.com/KKKKhazix/khazix-skills/blob/main/neat-freak/SKILL.md
