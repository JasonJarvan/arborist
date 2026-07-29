<!--
ADR 起草模板。**复制为 `proposed-<slug>.md`；起草者不占数字编号。**
只在 HITL accept 时，由本次单一 accept 方分配 NNNN 并改名为 `NNNN-<slug>.md`。
起草完成、以及 accept 的改名/状态写入前后，各运行一次：
  python3 .trellis/scripts/validate_adr_numbers.py --visibility <machine-local|product-git>
该门同时校验四位数字前缀唯一性、与「记规范那个 git」对 proposed 草稿及已编号 ADR
的可见性（`--visibility` 无默认值，缺失/歧义 exit 2 fail closed）。规则见
guides/repomem-doc-boundary.md「ADR 文件名与编号分配」。

machine-local 下，只有在 human 明确授权 hgit commit、提交完成、且运行
  python3 .trellis/scripts/validate_harness_persistence.py <本 ADR 路径>
成功之后，才可声称「已持久」；否则 landing manifest 写 pending。
只收过三门的架构决策。
-->
# ADR (proposed): <决策标题>
<!-- accept 时随改名一并改成 `# ADR-NNNN: <决策标题>` -->

- **Status**: proposed | accepted | superseded-by ADR-XXXX
- **Origin**: <task 目录名 / issue-key>  <!-- 必填：晋升溯源到变更史（Pairing Rule 3）-->
- **Date**: <YYYY-MM-DD>

## 三门自检（都 yes 才该是 ADR，否则留 task notes/guides）
- [ ] 难逆（改起来代价大）
- [ ] 无上下文会让人惊讶（反直觉）
- [ ] 真权衡（有被牺牲的合理替代）

## 背景
<为什么要做这个决策；约束。**不写代码结构事实**——符号/调用/目录用 codegraph 查即得，禁入。>

## 决策
<我们决定做什么。>

## 被否方案
<考虑过但否掉的，各一行理由（规划期）。>

## 后果
<正/负面影响；后续要注意的。>
