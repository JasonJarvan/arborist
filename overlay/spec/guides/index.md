# Arborist Guides

> Arborist 在 Trellis `.trellis/spec/guides/` 上叠加的**纪律与方法论**。规划/实现/评审时按需读对应 guide。总入口约定见 `.trellis/workflow.md` 的定制层。

> **可达性边界通告**：本 overlay 的可见性取决于宿主 `spec_visibility` 配置——`product-git`（spec/ADR 入产品仓 git，团队共享）或 `machine-local`（对产品仓隐身、副仓 `hgit` 记史，overlay 脚手架默认）。在 machine-local 或部分可见下，本 guide 集里的某些引用（`workflow.md` / `scripts/` / `host-config` / sendbox 等）在你的 checkout 里**可能打不开**。**打不开一个引用，不代表那条规则不存在**——照该规则执行，需要时另走渠道取到被隐身的文件。两个世界各得/各失什么、及部分可见的标注 pattern，见 [repomem-doc-boundary「spec/ADR 可见性」](./repomem-doc-boundary.md)。

## Guides

| Guide | 用途 | 何时读 |
|-------|------|--------|
| [角色层与任务分层 L1–L4](./roles-and-tiering.md) | L4 RootOrche / L3 SubOrche / L2 Impler / L1 subagent + 各级 steps + 生命周期场景 + ATUI 归属边界（通报⊥交办）+ worktree 步与纪律 | 多 session 协作、分解/派活、worktree 隔离 |
| [Execution Policy & Skip](./execution-policy.md) | 四级门控（auto/auto-judge/ask-first/HITL）+ Skip Bias + 跳过审计 + hooks add-only | 判断某步跑/跳、如何记录 |
| [RepoMem 层：文档边界与晋升](./repomem-doc-boundary.md) | 三层认知论 + Document Boundary 权威表 + Pairing Rules + persist 纪律 + read 装载 + spec/ADR 可见性（product-git vs machine-local）| 沉淀知识、晋升 ADR、避免复述 |
| [泛化边界（技术基石）](./generalization-boundary.md) | 泛化 gap 定义 + host-config/定制层/占位 三处分流 + 结构性排除 + 注入子集边界 + `spec_visibility` + 预防>检测>判断 | 撰写/同步 guide、公开上推去隐私、想让同步机械化 |
| [Verification & Gates](./verification-and-gates.md) | 门有执行者吗（通则）+ 多 lens 验证 + security-scan 接 MR 硬门 + 门控矩阵（含代码评审行）+ landing manifest + Challenge-before-ack + 已知上游 Trellis 缺口 | 验证、发 MR、晋升知识、给荣誉制门配机械产物 |
| [Sendbox 定向交办](./sendbox.md) | 跨 session 角色交办（read_first 绝对路径 + process-completeness + 生命周期/WIMTB）+ 持久化形态 A/B · fyi 信型 | durable handoff / 回报 |
| [Dashboard 待办投影](./dashboard.md) | 跨 session「此刻轮到人做什么」单一视图 | 多 session/待办堆积 |
| [AgentTUI 注册表](./agenttui-registry.md) | 并发 session 同伴发现：`.arborist/` 级联 + spec/runtime schema + 声明/派生状态模型 + 自登记 | 开新 session 自登记、找同伴、gardener 维护注册表 |
| [工具注册表 / 插件层](./tool-registry.md) | 可选能力发现：`.arborist/tools/` 级联 + `tool.json` schema + required/optional 置备与逐工具 fallback + 工具已知局限（`known_limits`：静默漏/静默空 → 交叉核验 + prefer 必配 fallback） | 需要某可选能力（历史检索/台账/…）、登记新工具、adopt 置备、写「prefer tool X」的 spec 行 |
| [知识收尾（洁癖式）](./knowledge-closeout.md) | 交付后全仓知识一致性门：事实面矩阵 + 两阶段汇报 + 触发分级 + landing manifest（无条件产出）；收尾方自跑 | full lane/milestone 收口、扫改动面外的过期文档/规则/记忆 |
| [HS 15-step 落点映射](./pipeline-mapping.md) | HarnessStack 15 步 → Trellis 3 阶段/guides 对照 | 想知道某方法论步进哪了 |
| [Engineering 方法论簇](./methodology/) | T1–T9（LLM 测试 / 验证纪律 / 契约防漂移 / MR / 依赖治理 / 数据契约 / 错误处理 / 本地文档 / handoff 归因）+ Tier3 | 对应场景取用 |
| [ADR 模板](./decisions/TEMPLATE.md) | 架构决策记录（三门自检 + `Origin` 溯源） | 产生 durable 架构决策时 |

## ADR Index（RepoMem.read 必读）

> 规划前必扫，避免重复决策 / 违背既有约束。ADR 只收过三门（难逆/反直觉/真权衡）的架构决策；可逆实现选择留 task notes 或相应 guide。

| ADR | 标题 | Status | Origin |
|---|---|---|---|
| [0001](./decisions/0001-agenttui-session-id-primary-key.md) | AgentTUI 注册表以 session-id 为主键 | accepted | dogfood |
| [0002](./decisions/0002-agenttui-declared-derived-state-model.md) | AgentTUI 状态用声明态+读时派生态模型（无守护进程） | accepted | dogfood |
| [0003](./decisions/0003-cross-session-reach-semantics.md) | `session_id` 触达语义 = `--resume` 追加，据活性选通道 | accepted | gardener |
| [0004](./decisions/0004-closeout-split-l2-draft-l4-accept.md) | 收尾职责分层 — L2 起草 / L4 轻量 accept | accepted | rootorc-methodology |
| [0005](./decisions/0005-agenttui-role-lineage-vs-generation.md) | AgentTUI 注册表补角色继承代数 lineage（与 generation 正交） | accepted | adopter-rootorc-v2 + gardener |
| [0006](./decisions/0006-runtime-brand-is-routing-authority.md) | actual runtime brand 是 subagent 路由唯一权威 | accepted | human brand-compat ruling + gardener |
