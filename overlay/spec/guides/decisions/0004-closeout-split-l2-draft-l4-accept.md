# ADR-0004: 收尾职责分层 — L2 起草 / L4 轻量 accept（close-out split）

- **Status**: accepted
- **Origin**: rootorc harness-methodology 决策（arborist-rootorc session, 2026-07-22；user 批准方案 A）
- **Date**: 2026-07-22

## 三门自检（都 yes 才该是 ADR）
- [x] 难逆（改起来代价大）
- [x] 无上下文会让人惊讶（反直觉）
- [x] 真权衡（有被牺牲的合理替代）

## 背景
原模型把全部收尾（晋升裁决、ADR、WIMTB、状态流转、commit）压在 L4 RootOrche 的 HITL 门。单任务收尾也走 L4 → rootorc 成瓶颈，阻塞其并发编排。但收尾里的 challenge-before-ack、ADR 晋升、对外提交本就故意放 L4，是为防实现者自我认证。

## 决策
收尾按 Lane 切（详见 `roles-and-tiering.md` 收尾职责分层）：
- **fast lane**：L2 全权自收尾（check + WIMTB + flip status）；commit 仍 ask-first。
- **full lane**：L2 做**收尾起草**——check/自验、WIMTB 自任务草稿、ADR 写成 `proposed`、**派独立 challenge subagent** 唱反调、备好 commit/status —— 打包「待接受包」回 L4。
- **L4 轻量 accept**：跨任务一致性 + 翻 ADR `proposed→accepted` + commit/push/MR + flip status。
- **永不下放**：产品仓 commit/push、跨任务裁决、ADR 最终接受。
- 独立性靠 challenge subagent 的**对抗立场**补（接受共享先验；立场独立 > 上下文独立）。

## 被否方案
- **全下放 L2（含 status/ADR 接受）**：吞吐最大，但自我背书 / ADR 泛滥 / 跨任务盲区风险高。
- **维持全收尾归 L4**：无自证风险，但单任务也阻塞 rootorc，违背超长程并发初衷。
- **仅靠 L3 分担**：缓解 cohort 编排，但没解决单任务收尾的 L4 阻塞。

## 后果
- 正：rootorc 从重收尾解放，HITL 只留在真正要它的地方（对外提交 / 跨任务 / ADR 接受）；challenge 前移到 L2 起草，问题更早暴露。
- 负：challenge subagent 与起草方共享先验，独立性弱于跨 session 评审——**护栏**：subagent 必须对抗式 prompt（默认候选不成立）。待迭代：把可复用 challenge/red-team subagent 持久化进 agent pool（需新开 `overlay/agents/` 发行类别 + adopt 铺设）。

## Residual（后续 issue 落地后收紧）
- **fast-lane「全权自收尾」不无条件**：challenge 门的触发已从 Lane 改为**风险形状**——fast-lane 任务若命中 authn/authz/secrets/crypto/租户隔离/输入信任边界，或正确性依赖框架/服务器运行时默认，仍**强制派独立 challenge**（见 [`verification-and-gates.md`](../verification-and-gates.md) 风险形触发）。即「fast lane：L2 全权自收尾」受此 carve-out 约束，不等于「fast-lane 免 challenge」。
- **护栏必须与可见性无关**：本 split 的下放与「L4 轻量 accept」的「轻量」，**不得以「候选已登记进 ADR 索引 / 待接受包 durable 记录、human 事后可审计」为据**——在 `spec_visibility: machine-local`（overlay 隐身、无第二读者/无 MR）下该前提不成立（见 [`repomem-doc-boundary.md`](../repomem-doc-boundary.md) 可见性节）。存活的护栏只能是 visibility-independent 的：对抗式 challenge subagent + 永不下放的 L4 accept（产品仓 commit/push、跨任务裁决、ADR 最终接受）。

## 适用范围
本 split 治理**任务收尾**（fast/full lane）。**harness 自身开发**（写 guide / ADR / 改规则）**不受强制下放**——rootorc 或 gardener 可按体量自行直做：小而快直做，大或会阻塞才派 impler。下放是手段不是义务。
