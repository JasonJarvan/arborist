# ADR-0002: AgentTUI 状态用「声明态 + 读时派生态」模型（无守护进程）

- **Status**: accepted
- **Origin**: Arborist dogfood (self-hosting)
- **Date**: 2026-07-22

## 三门自检（都 yes 才该是 ADR，否则留 task notes/guides）
- [x] 难逆（改起来代价大）
- [x] 无上下文会让人惊讶（反直觉）
- [x] 真权衡（有被牺牲的合理替代）

## 背景
注册表要反映每个 AgentTUI 的活/死，但 Arborist 明确不引守护进程（剥离 CCB 的 ccbd/socket/lease）。无常驻进程 → 没有权威的实时状态源。

## 决策
状态分两层：
- **声明态**（agent 自写，仅 `active`/`stopped`，只在 session start 与干净收尾两个可信触点写）；
- **有效态**（读者读表时现算）= f(声明态, `last_seen` 新鲜度, `session_file` mtime 探针)。

`idle` 是纯派生态：agent 空闲时不在运行，物理上不可自写，schema 保留该枚举但 MVP 不自写。stopped/stale 一律是**推定，非确知**；gardener 只保守 GC **条目**（非会话，误删可重建）。阈值 idle 15min / stale 24h 为建议默认。

## 被否方案
- **守护进程维护权威状态**：精确，但重、引依赖、违背剥离 CCB 的初衷。
- **单一 state 字段、每轮自写**：崩溃/关终端无回调 → state 永久停在过期值，读者被误导。

## 后果
- 正：零守护进程、零依赖；读者用 `session_file` mtime 探针零 brand 知识判活。
- 负：「idle 但终端还开着」与「已关终端」不可区分（探针局限）；有效态非确知，编排逻辑须容忍推定误差。遗留（归 gardener 实证回填）：codex 会话文件 mtime 行为**已实证**——随 turn 递增、`codex exec resume` 续同一 rollout，判活探针成立（见 [ADR-0003](./0003-cross-session-reach-semantics.md)）；**仍待实证**：无桥接环境自识别兜底。
