# 角色/任务分层 L1–L4 + 生命周期（<project>，吸纳自 HarnessStack）

> 同一个人同时开多 session，共享这一套 harness，各按级别从 Pipeline 挑 steps；级间靠 sendbox 交办。**四级**（顶→底）：

| 级 | 角色 | = Trellis | Multica | 强制力 |
|---|---|---|---|---|
| **L4** | **RootOrche** 根编排 | 与 human 对话、编排整仓；非被派任务 | 对应 <project> 项目/repo 级 | **无强制力**（顶，人直接接口，无上级派它）|
| **L3** | **SubOrche** 子编排 | parent task（管一批 L2 的开放任务）| L3 父 issue（架构决策+进度矩阵）| 受 L4 派 |
| **L2** | **Impler** 实现者 | child task（一个可独立验证交付）| L2 子 issue（`multica_parent`→L3）| 受 L3/L4 派 |
| **L1** | **subagent**（**auto-spawn**）| 无 task/issue，短生命 | — | 由 L2 自动派（trellis-implement/check/research）|

（与 **Lane(fast/full) 正交**：L1–L4 是角色/任务结构；fast/full 是文档集大小。）

## 各级跑哪些 Pipeline steps

- **L4 RootOrche**：Phase 1 research-first + brainstorm（与 human）→ 分解 L3/L2 任务、定 Lane → 派活（sendbox）→ Phase 3 **轻量 accept**（跨任务一致性 + 翻 ADR `proposed→accepted` + commit/push/MR 对 human；见下「收尾职责分层」）。**不**跑 L2 的 TDD loop、**不**替 L2 做本任务收尾起草。
- **L3 SubOrche**：把 parent(L3) 分解/排序成 child(L2)、维护 L3 dashboard、逐个派 L2 给 Impler、cohort 集成验收 → 回报 L4。**不**直接实现、**不**替 L4 做对-human 的 HITL。
- **L2 Impler**：本 L2 的 1.0b research-first + RepoMem.read → Phase 2 TDD loop（红-绿-重构，**派 L1 subagent** 做切片）→ 3.3 **收尾起草**（见下「收尾职责分层」：full-lane 起草 ADR `proposed` + 派独立 challenge subagent + 打包「待接受包」；fast-lane 全权自收尾）→ sendbox 回报 done。
- **L1 subagent**：`trellis-implement`/`trellis-check`/`trellis-research` 自动派生，做单一切片/检查/检索；不再往下派、不越权。dispatch prompt 带 `Active task:`（见 workflow.md 2.1）。

## 收尾职责分层（close-out split · 防 rootorc 阻塞）
收尾不再整块压在 L4；按 Lane 切：
- **fast lane**：L2 Impler **全权收尾**（自 trellis-check + 行为自验 + WIMTB 自任务 + flip status）；无 L4 门。commit 仍 ask-first 对 human。
- **full lane**：L2 Impler 做**收尾起草**——check/自验 → WIMTB 自任务草稿 → ADR 候选**写成 `Status: proposed` 的真文件**（不再只 surface 文本）→ **派独立 challenge subagent** 唱反调（见 `verification-and-gates.md` «Challenge-before-ack»）→ 备好 commit/status 但不执行 → done 信打包**「待接受包」**（proposed ADR 列表 + WIMTB 草稿 + challenge 裁定 + 拟提交范围）回 L4。
- **L4 轻量 accept**：只做 L2 做不了的——**跨任务/集成一致性扫描**（唯 L4 见姊妹任务）+ **翻 ADR `proposed→accepted`**（晋升最终权）+ **commit/push/MR**（对 human）+ flip issue status done。
- **永不下放（rootorc/human 安全边界）**：产品仓 commit/push · 跨任务裁决 · ADR 最终接受。

## 建议的生命周期（按场景，从开始到结束跑哪些 step，非强制）

### 场景 A：单体小改（fast lane，L2 Impler 直做，或 L4 直做）
`no_task → 建 task(Lane=fast) → 1.0b research-first(轻) → [brainstorm 常跳，记 skip-log] → prd-only → start → 2.1 实现(fast-lane 琐碎可免 red-test-first，记 skip-log；否则 TDD) → 2.2 trellis-check → 3.3 判 spec/ADR(多为无) → /commit(ask-first) → /pr 进当期 release(security-scan 若动依赖) → finish-work`。无 L3/L4 编排、无 sendbox。

### 场景 B：中等特性（full lane，L4→L2 单派）
`L4: research-first + RepoMem.read + brainstorm(与 human) → 建 task(Lane=full, prd+design+implement) → [4.1 grill / 4.2 red-team 可选] → sendbox handoff 给 Impler(read_first 绝对路径 + process 声明) → L2 Impler: start → 2.1 TDD(派 L1 subagent) → 2.2 check + security-scan(动依赖)+人工 smoke(可见改动) → 3.3 晋升候选 → done 信回 L4 → L4: /code-review → HITL 晋升门(challenge-before-ack) → /commit + /pr(进 release) → archive(WIMTB 进 Multica) → RepoMem.merge`。

### 场景 C：大特性/超长程（full，L4→L3→多 L2 并发）
`L4: 分解成 parent(L3 cohort) + 多个 child(L2) → 派 L3 给 SubOrche → L3 SubOrche: 维护 L3 dashboard、排序、逐个 sendbox 派 L2 给多个 Impler(并发 session) → 各 L2 Impler 跑场景 B 的 L2 段、done 信回 L3 → L3: cohort 集成验收 → 回报 L4 → L4: 整体 HITL 门 + 上线 → 各 L2 archive→WIMTB, L3 收敛→WIMTB 进 L3 父 issue`。human 同时盯这些 session → 用 Dashboard 看待办。

> step 细节见 workflow.md Phase 1/2/3 + `pipeline-mapping.md`（HS 15-step 落点）；门控 policy 见 `execution-policy.md`；交办见 `sendbox.md`。

## 级间交办：durable 走 sendbox，transient 是可插拔扩展点
- **durable**（handoff/decision/plan-ready/晋升/改 scope）→ **sendbox 文件协议**：写信物落 `.work_context/sendbox/` + 认作已定前 HITL 确认（见 `sendbox.md`）。这是本 repo **内置**的编排通道。
- **transient**（催活/问答/要即时结论的瞬态 chatter）→ 属于**可插拔的通信后端扩展点**：本 repo 缺省不内置具体实现（一个可见多 window TUI / A2A 自动回投的运行时可作为外接后端接入）。开箱即用时瞬态协调退化为人工在并发 session 间带话，或由 Trellis 原生 subagent 承担单会话 fan-out。
- L4/L3/L2 各自开独立 session（人驱动并发）；L1 subagent 由 L2 在会话内 auto-spawn。

## 与 Trellis 原生的关系
Parent/Child Task Trees + 子代理 dispatch + `task.py --mine`/assignee 是载体。channel-driven 面向程序化 peer；本模型是**人驱动并发 session + sendbox 异步 durable 信**，用 native/tdd + sendbox。
