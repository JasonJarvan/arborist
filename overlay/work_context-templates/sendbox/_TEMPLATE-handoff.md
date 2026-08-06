---
recipients:
  - role: <Impler|SubOrche|RootOrche|User|TestTeam>
    purpose: <为何读这封>
    lifecycle: <终止条件，如 "L2 started" / "signed off">
# 下面两块仅能力驱动 handoff 用（任务依赖某 brand 独有能力时才带）；默认 brand-agnostic → 整块省略，谁接谁以自己 actual runtime brand 跑
recipient_brand: <claude-code|codex>
route_policy:
  policy_id: <selected-policy-id>
  lane: <fast|full>
  task_kind: <implement|explore|check|challenge|research>
  agent: <selected-agent-or-null>
  model: <selected-model-or-null>
on_lifecycle_end: burn | archive | wimtb
lifecycle_executor: <角色>   # 必填：谁真的执行上一行，含销毁前的判据抽取；缺它不得声明 burn
task: <L2/L3 task 目录>
multica_issue: <task.json.meta.multica_issue，如有>
created: <YYYY-MM-DD>
created_in: <来源角色/session>
---
# from-<task>-handoff

## Recipient brand（可选：仅能力驱动 handoff）
**默认省略本节**：handoff 默认 brand-agnostic，不钉执行者 brand，谁接就以自己的 actual runtime brand 跑。**只有当任务依赖某 brand 独有能力**（换 brand 无法等价完成）才钉 brand，填以下块。填时：顶层 `recipient_brand` 是接收者的 actual runtime brand，不是作者 brand 或期望模型；生成前以 `(recipient_brand, lane, task_kind)` 从 `_handoff-config.yaml` 精确选择一个 `route_policy`；缺失、未知或 brand mismatch 时停止，不猜默认值。

- `recipient_brand: codex`：implement/TDD/refactor/Explore/check/challenge/research 全部使用 Codex。
- `recipient_brand: claude-code`：fast implement=Sonnet、full implement=`trellis-implement-full`/Opus、Explore=`trellis-explore`/Sonnet、check/challenge=Opus、research=Sonnet。

## Selected route（仅能力驱动 handoff；brand-agnostic 时删除本节）

> policy_id: <selected-policy-id>
> recipient_brand: <claude-code|codex>
> lane: <fast|full>
> task_kind: <implement|explore|check|challenge|research>
> agent: <selected-agent-or-null>
> model: <selected-model-or-null>

<selected route_fragment；必须逐字来自 config leaf，且这是正文中唯一 routing 指令>

## Read first（绝对路径，N19）
- <REPO_ROOT>/.trellis/workflow.md
- <REPO_ROOT>/.trellis/spec/guides/roles-and-tiering.md
- <相关领域 spec / guides 绝对路径>
- <该任务 prd.md 绝对路径>

## 自登记（接手即做）
开新 session 接手后，按 `guides/agenttui-registry.md` §5 自登记进 `<REPO_ROOT>/.arborist/agents/<name>/`（`spec.json`+`runtime.json`）。session_id 派活方物理上写不了，必须你自建；信中 role / task / description 可直接作 `spec.json` 素材。

## Process（N20：不得静默省略 mandatory step）
遵 workflow.md 标准 Pipeline；本任务入口：<如 "Phase 2 TDD 实现 loop">。
短路声明（如有）：<逐条：跳过哪个 step + 理由/补偿；接收方抄进自己 task 记录>

## 任务
<要做什么；验收标准指向 prd.md；Lane=fast|full；L 级别>

## 回报
完成后**复制 `<REPO_ROOT>/.work_context/sendbox/_TEMPLATE-done.md`** 写
`from-<task>-done.md` 到来源角色目录：delivery + MR link + spec/ADR 晋升候选 + landing manifest。
**发送前必须让该模板里的标准 claim provenance 表通过**
`python3 <REPO_ROOT>/.trellis/scripts/validate_claim_provenance.py <这封 done 信的绝对路径>`
（门的语义见 `guides/sendbox.md`「Done 信与验收证据的 claim provenance 门」）。
