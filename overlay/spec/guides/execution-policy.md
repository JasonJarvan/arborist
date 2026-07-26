# Execution Policy & Skip Discipline（<project>，吸纳自 HarnessStack）

> Trellis workflow.md 各步的执行门控与跳过纪律。吸纳自 HarnessStack § Execution Policy / Skip Mechanism / Lane Tiering。

## Brand gate（先于执行门控）

`effective_subagent_brand = impler.spec.brand`

这个 same-brand gate 适用于实现、TDD、重构、Explore、check、challenge 与 research，且先于下述 auto/ask-first/HITL 判断。执行角色 handoff 缺少 recipient brand、brand 不在宿主支持列表、实际 ATUI 与注册声明不一致，或计划中的 provider 产生 **brand mismatch**，都必须 fail closed：不创建 subagent、不猜默认值、不伪装成另一 brand。修正注册信息或 handoff 后才可继续。

Human 直接运行、无需 A2A 发现或路由的 harness 会话属于注册豁免；它们没有“缺注册 brand”的 gate 错误。该豁免不允许一个已参与路由的 Impler 绕过 same-brand 校验。

## 四级门控（每步一个 policy）

- **auto** — 直接执行，不问。用于只读/脚手架/幂等步（research-first、RepoMem.read、建 task 目录、get_context）。
- **auto-judge** — 代理**自主决定「跑还是跳」**；**跳了必须**在 task 记一行 Auto-Skip Log；**绝不问用户**。用于"原设计允许按需跳"的步（brainstorming 已收敛可跳、fast-lane 免 design、fast-lane 琐碎改动免 red-test-first、grill 可跳）。盲跑浪费 token，故给代理裁量权 + 审计留痕。
- **ask-first** — 真人决策点，宣布将做什么并**等用户批**。用于有外部副作用的步：**commit / push / MR / security-scan / task archive**。
- **HITL（强制人评）** — 契约强制的人类评审，不可配置。用于：**ADR/spec 的最终接受**（`proposed→accepted`，RepoMem.merge 等价）+ **跨任务一致性裁决**。注：full-lane 下 L2 收尾**起草** ADR 为 `proposed` 是 auto-judge（起草≠接受）；把 `proposed` 翻成 `accepted` 才是 HITL，归 L4/human（见 `roles-and-tiering.md` 收尾职责分层）。

## Skip Bias（程序轴，与 Lane 结构轴正交）

在 task `prd.md` 顶部可声明 `Skip Bias: conservative|aggressive`（只影响 auto-judge 步）：
- `conservative`（默认，可省）— 倾向跑，仅强信号才跳（单文件 typo、上轮已收敛）。
- `aggressive` — 倾向跳并记录，仅强信号才跑（真设计探索、多文件、动依赖）。

**两轴独立、四组合皆合法**：`Skip Bias`（多易跳一个**步骤**）⊥ `Lane`（哪些**文档**必须存在）。

## 跳过机制（禁止静默跳过）

| 情形 | 用哪种 |
|---|---|
| auto-judge 步、跳过符合该步"允许跳"条件 | **Auto-Skip Log**（轻量：task 记 `- #<step> — <一句理由>`，无需补偿）|
| auto-judge 步、跳过**超出**允许条件 | **Recipe Invariant Exception**（重量）|
| **auto / ask-first / HITL 步**被跳（尤其 security-scan / commit / 晋升门）| **Recipe Invariant Exception**（重量：`Reason` + `Compensating Action`，可被 HITL 评审 block）|

**Lane≠skip（重要）**：因 Lane 定义而不存在的文档（如 fast-lane 无 design.md）**不是跳过**，无需任何 log——那是"lane 裁文档"，不是"跳步骤"。只有跳*步骤*才记。

口头"就跳过"而无上述任一记录 = 禁止（无审计痕迹）。HITL 晋升评审是执行点，可因用错机制而 block。

## <project> 门控映射（workflow.md 各步）

| 步 | policy |
|---|---|
| 1.0b research-first + RepoMem.read | auto（只读）|
| 1.1 brainstorming | auto-judge（已收敛可跳）|
| 1.2 research / 4.x grill / red-team | auto-judge（可选）|
| 2.1 implement（含 TDD）| auto；fast-lane 琐碎改动免 red-test-first = auto-judge + skip-log |
| 2.2 check / 自验 | auto |
| security-scan（依赖变更）| **ask-first** + 是 MR-into-release 硬 gate（见 verification-and-gates）|
| commit / push / MR | **ask-first**（defer <project> `/commit` `/pr`）|
| ADR/spec 起草为 `proposed`（L2 full-lane 收尾） | **auto-judge** + 派独立 challenge subagent |
| ADR/spec 接受 `proposed→accepted` + 跨任务裁决 | **HITL**（L4/human）+ 前置 Challenge-before-ack |
| task archive | ask-first |

## Hooks 边界（add-only 铁律，X1）

`config.yaml` 的 `hooks.after_*`（含即将加的 Multica 同步）**只能加副作用，绝不得改步序 / 门 / 验证拓扑**——这些是 recipe 不变式。具体：
- hook 失败仅告警、**不阻塞**主流程（Trellis 原生行为，保持）。
- 任何 gate（security-scan 接 MR、HITL 晋升门、ask-first 提交）**不得**由 hook 承担或绕过。Multica WIMTB-at-archive 是**镜像**，不是门——它失败不该拦归档，也不该替代 HITL。
- 要停用某 hook 于特定 task：在 task 记 Recipe Invariant Exception，不静默停。
