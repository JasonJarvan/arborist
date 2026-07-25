<!-- 把本块粘进你项目的 .trellis/workflow.md（紧跟 "## Core Principles" 之后）。
     <占位> 处替换成你项目的实际值。workflow.md 不在 trellis update 的 hash 清单 → 本块 update-safe。 -->

## <project> 定制层（本地覆盖 · 读 workflow.md 时以本节为准）

> 由 Arborist overlay 引入。详规见 `.trellis/spec/guides/`。workflow.md update-safe。

### 术语消歧
- Trellis 的 "spec"（`.trellis/spec/`）= **编码规范/约定**（≈ RepoMem persist/memory），非行为契约。
- 单次变更的**行为契约** = 该 task `prd.md` 验收标准；关键能力的**累积契约摘要**落 `.trellis/spec/<pkg>/`。

### 角色/任务分层 L1–L4（多 session 共享本 harness）
**L4 RootOrche**（与 human 对话、编排整仓、分解、HITL 把关；无强制力）→ **L3 SubOrche**（管一批 L2、派活、集成）→ **L2 Impler**（实现一个 L2、TDD loop、回报）→ **L1 subagent**（auto-spawn 的 implement/check/research）。L3=parent task、L2=child task；与 Lane 正交。级间 sendbox 交办。详见 `guides/roles-and-tiering.md`。

### Trellis = 骨架，Superpowers = 工具箱
各步"怎么做"调 SP skill（brainstorming / writing-plans / TDD / subagent-driven-development / verification / code-review），产物落 `.work_context/superpowers/`。Trellis 原生 skill 与 SP 重叠时**择一**（见 guides/roles-and-tiering + workflow 里各步标注），别双跑。

### Git / 提交 / 分支 / MR —— defer 你项目的既有约定
走 `<你的 git/MR 规则，如 .claude/rules/* + /commit + /pr>`。硬线：**未经用户明说不提交、不 push**。（示例：功能分支从 main 切、MR 进当期 `release/YYYYMMDD`。）Trellis 不自造 git 流程（Phase 3.4 遵此）。

### Lane 与 TDD 逃生口
Lane 在 task `prd.md` 顶部声明 `Lane: fast|full`（full 若：动依赖 / 跨子树 / 公共契约 / 需 ADR）。TDD 默认开；**fast-lane 琐碎改动可免 red-test-first**，记 skip-log。

### research-first 前置
规划**从 research-first + RepoMem.read 起**（读 ADR/spec），**先于** brainstorm。符号/调用/影响面优先 **codegraph** MCP，grep 兜底。

### 知识收尾门（可选 · Phase 3.4 commit 后、`/finish-work` 前）
交付后按 `guides/knowledge-closeout.md` §1 分级判跑：full lane / milestone 收口跑「改动面外的全仓知识一致性」扫描；fast lane 跳过记 skip-log。**由收尾方自跑**（full lane 即 L2 Impler），不回弹 rootorc。

### 详规指针
角色/分层/交办：`guides/roles-and-tiering.md` · `guides/sendbox.md` · `guides/dashboard.md`；门控：`guides/execution-policy.md`；记忆/边界：`guides/repomem-doc-boundary.md`；验证/门：`guides/verification-and-gates.md`；HS 15-step 落点：`guides/pipeline-mapping.md`；方法论：`guides/methodology/`；注册表：`guides/agenttui-registry.md`（AgentTUI 同伴发现）· `guides/tool-registry.md`（可选能力发现）；知识收尾：`guides/knowledge-closeout.md`（交付后全仓一致性门）。

<!-- 另需在 Phase 1 加 1.0b research-first 步、把 [workflow-state:planning]/Active Task Routing 的 Load `trellis-brainstorm` 改指 SP brainstorming、Phase 2.2 加验证拓扑、Phase 3.3 加 ADR 分流+HITL 晋升门、Phase 3.4 defer git、Phase 3.5 加 WIMTB。逐条见 ADOPT.md。 -->
