---
recipients:
  - role: <Impler|SubOrche|RootOrche|User|TestTeam>
    purpose: <为何读这封>
    lifecycle: <终止条件，如 "L2 started" / "signed off">
on_lifecycle_end: burn | archive | wimtb
task: <L2/L3 task 目录>
multica_issue: <task.json.meta.multica_issue，如有>
created: <YYYY-MM-DD>
created_in: <来源角色/session>
---
# from-<task>-handoff

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
完成后写 `from-<task>-done.md` 到来源角色目录：delivery + MR link + spec/ADR 晋升候选。
