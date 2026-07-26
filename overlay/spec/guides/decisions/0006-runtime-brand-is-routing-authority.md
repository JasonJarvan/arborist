# ADR-0006: actual runtime brand 是 subagent 路由唯一权威

- **Status**: accepted
- **Origin**: human brand-compat ruling（2026-07-26）+ gardener systematic hardening
- **Date**: 2026-07-26

## 三门自检（都 yes 才该是 ADR，否则留 task notes/guides）

- [x] 难逆（改起来代价大）—— 注册表 schema、handoff 协议、平台注入面与 validator 共同依赖该身份维度
- [x] 无上下文会让人惊讶（反直觉）—— agent 名、模型名和作者 runtime 看似都能暗示 provider，但都不是接收执行者的真实 brand
- [x] 真权衡（有被牺牲的合理替代）—— 默认 brand、从 prose 推断、保留跨 provider fallback 都更宽容，但会把配置缺陷静默变成错误执行

## 背景

多平台项目里，同一份中立规范和 handoff 会被不同 AgentTUI 读取。若共享真相源写入某一
provider 的强制路由，另一 brand 的 Impler 会把本来合法的同品牌执行误判为冲突；若生成器
再从旧 prose、作者 runtime 或模型名猜 brand，错误会继续传播到每一级 subagent。

两个平台的自动可见面也不重叠：Codex 自动读取项目 `AGENTS.md`，Claude Code 的 session
注入读取 workflow Phase Index。只改一处不能形成跨平台契约。

## 决策

- AgentTUI 注册表的 `spec.brand` 必须记录会话的 **actual runtime brand**，不得伪装。
- Impler 到所有 L1 工作遵守
  `effective_subagent_brand = impler.spec.brand`；implement、TDD、refactor、Explore、
  check、challenge、research 都不得跨 provider。
- task-executing handoff 显式记录 `recipient_brand`，并只允许按
  `(recipient_brand, lane, task_kind)` 精确选择宿主配置的一个 route policy。缺值、未知值、
  tuple 缺失或实际/记录 brand 不匹配均 fail closed，不设默认和 fallback。
- 品牌中立规范保存在 guides；同一短契约机械安装到 Codex 可见的 `AGENTS.md` 和 Claude
  Code 可见的 workflow Phase Index，并由 validator 检查同步。
- provider-specific agent/model 只存在于对应 brand 的 route leaf。Claude Code 的固定模型
  agent 可由宿主安装；Codex 的模型由其项目配置或单次调用决定。
- human 直连、且不参与 A2A 发现或路由的 harness 会话不属于注册对象；validator 和 GC
  不得把它报告为未登记活动会话。

## 被否方案

- **默认 `claude-code` 或默认当前作者 brand**：配置缺失时会静默把执行者路由到错误 provider。
- **从 agent/model 名或旧 handoff prose 推断**：这些是可变宿主词汇和不可信历史文本，不是 runtime 身份。
- **把 brand 条款只写进中立 guides**：两个 TUI 都不保证自动读取，关键门控可能不可见。
- **只修一个平台的注入区**：另一平台仍可继续生成或服从冲突指令。
- **保留跨 provider fallback**：模糊了注册事实，并让 mismatch 看似成功。

## 后果

- 正：注册、生成、继承和 L1 派活使用同一个可机械验证的身份；两个平台都能在自动可见区
  看到同一契约；旧 prose 不能再覆盖 runtime 事实。
- 正：Claude Code full/Explore 的模型由固定 agent frontmatter 保证，不再依赖每次手传；
  Codex 路由不携带 Claude agent/model。
- 负：新增 brand 或 task kind 必须补齐 route matrix 和两个可见面校验，不能靠 wildcard
  快速接入；这是为 fail-closed 刻意支付的维护成本。
- 负：历史 handoff 不自动重写；仍处于生命周期内且冲突的信必须加明确覆盖标记，其他历史
  信保留审计语境。
