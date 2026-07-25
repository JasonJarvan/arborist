# ADR-0001: AgentTUI 注册表以 session-id 为主键

- **Status**: accepted
- **Origin**: Arborist dogfood (self-hosting)
- **Date**: 2026-07-22

## 三门自检（都 yes 才该是 ADR，否则留 task notes/guides）
- [x] 难逆（改起来代价大）
- [x] 无上下文会让人惊讶（反直觉）
- [x] 真权衡（有被牺牲的合理替代）

## 背景
AgentTUI 注册表要给每个 coding-agent 会话一个身份锚，供并发 session 互相发现、并（未来）作触达句柄。CCB 把 session_id 当次要字段，主要靠 pane/window 标识；Arborist 剥离了 tmux/pane 层，需另选主键。

## 决策
以 **session_id 为 AgentTUI 的主键 / 触达句柄**（`runtime.json.session_id`）。目录键 `name` 是人读别名，稳态身份放 `spec.json`；同一 name 重启换新 session 时，`runtime.json` 换 session_id 并 `generation`+1，`spec.json` 不动。

## 被否方案
- **name 作主键**：稳定、人读，但不能直接触达/续接会话（`claude --resume <session-id>` 要的是 session_id）。
- **pane/window ref 作主键（CCB 路线）**：绑定终端复用器，违背 Arborist 剥离 tmux 的初衷、不可移植。

## 后果
- 正：可直接 `--resume` 触达；后端中立（session_id 各 brand 都有）；发现层零 tmux 依赖。
- 负：session_id 跨重启不稳定 → 必须靠 `generation` + `spec.json` 稳态层补偿身份连续性；死会话的 session_id 不复用，靠 gardener 保守 GC。
