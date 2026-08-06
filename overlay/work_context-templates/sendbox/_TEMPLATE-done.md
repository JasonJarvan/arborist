---
recipients:
  - role: <Impler|SubOrche|RootOrche|User|TestTeam>
    purpose: <为何读这封交付回报>
    lifecycle: <终止条件，如 "验收完成并蒸馏">
on_lifecycle_end: burn | archive | wimtb
lifecycle_executor: <角色>   # 必填：谁真的执行上一行，含销毁前的判据抽取；缺它不得声明 burn
task: <L2/L3 task 目录>
multica_issue: <task.json.meta.multica_issue，如有>
created: <YYYY-MM-DD>
created_in: <来源角色/session>
---

# from-<task>-done

## 交付摘要

<本次交付、分支/commit、仍冻结的 ask-first 动作。逐条证据以下表为准。>

## Claim provenance（验收事实真相源）

> 所有会被下游用于验收、决策或继续实现的结论必须逐条进入本表；表外叙述可解释
> 上下文，**不算验收证据**。`实测` 的出处写命令输出、artifact 或 `path:line`，
> 要让第二读者能复核；`推断` 的出处写已核前提，并在「未验证缺口」点明尚未验证
> 的那一步（`推断 + 未验证缺口=无` 不合格）。禁止把实测与推断揉成一行。
> `实测` 确无缺口写 `无`，不是留空。表达到 4 行后，不得给所有行复制同一个
> 非 `无` 缺口——共同限制也要逐行说明它如何约束**本行**结论。

| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| <可被验收的单一结论> | 实测 | <命令 + 结果 / artifact / path:line> | 无 |
| <基于已核事实作出的推断> | 推断 | <已核前提 + 推理依据> | <尚未验证的具体一步> |

**发送前必跑**（本封信自身的路径，非目录）：

```sh
python3 <REPO_ROOT>/.trellis/scripts/validate_claim_provenance.py \
  <REPO_ROOT>/.work_context/sendbox/toAgent/to<Receiver>/from-<task>-done.md
```

未通过就发出去 = 把占位符或复制常量当验收证据；门的语义、错误矩阵与存量边界见
`.trellis/spec/guides/sendbox.md`「Done 信与验收证据的 claim provenance 门」。

## 交付状态

- Branch / HEAD: <value>
- Tests: <一句话摘要；逐条证据仍以上表为准>
- Commit / push / MR: <done | frozen | pending explicit authorization>
- Landing manifest: <指向本次收尾的 landing manifest；含「谁评审」与必答项>

## Impler 提的问题（如有）

<请收件方**判断**的事项：冲突仲裁 / 跨任务契约验收 / scope 缺陷 / blocker。
「请你判断 X」可以，「请你替我做 X」不行——见 guides/roles-and-tiering.md 收尾职责分层。无则写「无」。>

## 下一步请求

<请收件方执行的事项；无则写「无」。>
