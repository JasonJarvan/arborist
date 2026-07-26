# Sendbox：跨 session 定向交办（<project> host 配置 + 信规范）

> 角色间（L4 RootOrche / L3 SubOrche / L2 Impler / L1 subagent）的异步文件交办。操作用 **`sendbox-protocol` skill**（handoff/inherit verbs）；本篇是 <project> 宿主配置 + **信的命名/frontmatter 规范**。吸纳自 HarnessStack longterm § Cross-Session Sendbox Convention。

## Handoff brand contract

交给 Impler、SubOrche、Reviewer 等任务执行角色的 handoff 必须携带顶层 `recipient_brand`。生成器只用它与 `lane`、`task_kind` 从 `brand_routing.route_policies` 精确选择 leaf，不从作者 brand、模型名、目录名或旧信正文推断：

`effective_subagent_brand = impler.spec.brand`

- `recipient_brand: codex`：implement/TDD/refactor/Explore/check/challenge/research 全部路由到 Codex；不得生成要求 Claude 或 Claude Code 执行这些工作的指令。
- `recipient_brand: claude-code`：使用 Claude Code 路由，并保持宿主配置的 lane/agent/model 档位。
- brand 缺失、未知或生成结果出现 brand mismatch：handoff/inherit 都必须 fail closed，列出支持值并要求修正；不得补默认值或跨 brand fallback。

Human 收件人若不执行 task，可以不带 brand；一旦 handoff 让收件人承担执行角色，brand 即为必填。

宿主配置必须采用 cc-sendbox 0.6 的 `brand_routing` schema：`task_executing_roles`、`supported_brands`、`same_brand_policy: strict`，以及精确三层 `route_policies.<brand>.<lane>.<task-kind>`。每个 leaf 都必须有全局唯一 `policy_id`、非空 `route_fragment` 和显式 `agent` / `model`（由 runtime 决定时写 YAML `null`）。缺 tuple、重复 ID 或旧 schema 都是不兼容配置，必须在写信前失败。

## 目录结构（`toAgent/` + `toHuman/`）
```
.work_context/sendbox/
  toAgent/          # 收件人是 agent 角色
    toRootOrche/
    toSubOrche/
    toImpler/
  toHuman/          # 收件人是人
    toUser/
    toTestTeam/
```
- `<Role>`/`<Receiver>` 是**角色/职能**，非 session 名（session 短命、角色不）。
- 都在 `.work_context/`（git-ignored → 本地；副仓 `hgit` 记历史）。

## 信命名规范
`from-<task>-<type>.md` —— `<task>` = 来源 L2/L3 task 的 slug；`<type>` ∈
`handoff`（派活）· `done`（交付回报）· `ack`（确认）· `blocker`（阻塞）· `greenlight`（放行请求）· `plan-ready`（计划待评审）· `decisions`（决策记录）· `smoke`（人工 smoke 手册）。
例：`toAgent/toImpler/from-eve-42-handoff.md`、`toHuman/toUser/from-eve-42-greenlight.md`。

## Frontmatter 规范
**单收件人 + 瞬态**信可省 frontmatter（默认 burn，收件人 lifecycle 结束即 `rm`）。**多收件人 / durable** 信**必须**带：
```yaml
---
recipients:
  - role: <Impler|SubOrche|RootOrche|User|TestTeam>
    purpose: <为何读这封>
    lifecycle: <终止条件，如 "L2 started" / "signed off">
recipient_brand: <claude-code|codex>  # task-executing recipient 必填；human-only 可省
route_policy:                         # task-executing recipient 必填
  policy_id: <selected-policy-id>
  lane: <fast|full>
  task_kind: <implement|explore|check|challenge|research>
  agent: <selected-agent-or-null>
  model: <selected-model-or-null>
on_lifecycle_end: burn | archive | wimtb   # wimtb=蒸馏进对应 Multica issue 后 rm
task: <L2/L3 task 目录>
multica_issue: <task.json.meta.multica_issue，如有>
created: <YYYY-MM-DD>
created_in: <来源角色/session>
---
```
- 无 frontmatter 又无单一明确收件人的信 = 畸形。

## Handoff 信必备正文（交办给执行角色，见 `_TEMPLATE-handoff.md`）
1. **`read_first`（绝对路径，硬性 N19）**：`<REPO_ROOT>/.trellis/workflow.md` + 相关 guides + 该任务 `prd.md`（worktree/独立 session 看不到被 exclude 的 harness overlay，相对路径悬空）。
2. **process-completeness（N20）**：遵标准 Pipeline，或逐条声明短路的 step（接收方抄进自己 task 记录）；不得静默省略 TDD/security-scan/HITL。
3. **任务引用** + Multica issue。
4. **recipient brand + route block**：顶层 `recipient_brand` 与 `route_policy` 必须来自 `_handoff-config.yaml` 的精确 `(brand, lane, task_kind)` leaf；`policy_id` / `agent` / `model` 必须一致，正文只渲染该 leaf 的 `route_fragment`。

## 自动路由 vs 人确认（durable 边界，A2A 自动化判据）
交办可自动化（若接入了某个瞬态通信后端）到什么程度，按下列切分：
- **瞬态 = 全自动、免确认**：ack / 状态 / done 通知 / blocker 上报 / 提问 —— 纯协调 chatter，直接自动路由。
- **durable = 自动送达 + 落定前人确认**：满足任一——① 映射到某 task/EVE；② 产生/改变决策、计划、晋升候选；③ 需 outlive 会话成为记录（plan-ready / decisions / 改 scope 的 delivery / 晋升候选）。**自动送达**，但接收侧/门在"认作已承诺/落定"前**停下等 user 确认**（对齐 HITL/ask-first）。
- 一句话：**协调 chatter 全自动；承诺级记录 自动送达 + 落定前人确认。**

## 生命周期
- 瞬态（ack/greenlight/blocker/done）→ **burn**。
- durable 且映射 L2/L3 → **wimtb**（蒸馏进 Multica issue + 附原信 → 验证 → `rm`；同 verification-and-gates WIMTB 不变式）。
- 无 EVE 的 durable 信 → 留 `.work_context/` 或升级 guide，不硬塞无关 issue。

## Inherit（接收方"继承"handoff——handoff 的读取侧）
handoff 是**写**（派活方投信）；inherit 是**读/接管**（接收会话"继承"这封信开工）。接收角色开一个新 session 后：
1. **校验 recipient brand + route policy**：执行角色必须有受支持的顶层 `recipient_brand`，且与当前 actual runtime brand 一致；再按 frontmatter 的 lane/task_kind 重解 config leaf，并核对 `policy_id` / `agent` / `model` 与正文 Selected route。任一不一致即停止继承。
2. **读 `read_first`**（信里列的绝对路径：workflow.md + 相关 guides + 该任务 prd）——绝对路径保证 worktree/独立 session 也能加载被 exclude 的 harness overlay（N19）。
3. **按 process-completeness 声明续流程**：遵 workflow.md 标准 Pipeline，或采纳信里逐条声明的短路 step（抄进自己 task 记录，不静默绕门）。
4. **认领任务**：从信的 `task` 字段定位 L2/L3 task 目录 + Multica issue，进入对应 Phase（如"从 Phase 2 TDD 入"）。
5. 完成后按信尾写 `from-<task>-done.md` 回投来源角色。
> handoff/inherit 是一对动作，操作可由 `sendbox-protocol` skill 的 handoff/inherit verbs 执行；本节定义 Arborist 语义。

## 与 Trellis 的关系
Trellis 无原生定向交办；`trellis mem`+journal+task 目录覆盖"回忆/连续性"，sendbox 补"定向指令"层。live 多代理才考虑 `trellis channel`。
