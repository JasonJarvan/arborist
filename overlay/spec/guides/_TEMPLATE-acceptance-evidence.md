# Acceptance evidence: <task>

> 复制到 `<task 目录>/acceptance-evidence.md` 后替换全部占位符。所有用于验收、
> 决策或下游实现的结论必须逐条进入下表；表外叙述只作解释，**不算验收证据**。
> `实测` 确无缺口写 `无`（不是留空）；`推断` 必须在「未验证缺口」点明尚未验证
> 的那一步。表达到 4 行后，不得给所有行复制同一个非 `无` 缺口——共同限制也要
> 逐行说明它如何约束**本行**结论。门的语义与错误矩阵见
> [`sendbox.md`](./sendbox.md#done-信与验收证据的-claim-provenance-门)。

| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| <AC / 契约的单一结论> | 实测 | <命令 + 结果 / artifact / path:line> | 无 |
| <基于已核事实的推断> | 推断 | <已核前提 + 推理依据> | <尚未验证的具体一步> |

**被接受前必跑**（新建或实质重写都算）：

```sh
python3 <REPO_ROOT>/.trellis/scripts/validate_claim_provenance.py \
  <REPO_ROOT>/.trellis/tasks/<task>/acceptance-evidence.md
```

## 补充解释

<可选。不得在这里新增未进入上表的验收结论。>
