# RepoMem 层：记忆分层 · 文档边界 · 晋升纪律（<project>）

> 吸纳自 HarnessStack § Repository Memory Layer / Task Identifier and Document Boundary。<project> 无 OpenSpec、无 codegraph 作真源时的重述见文末。

## 三层认知论

| 层 | 语义 | <project> 载体 | 持久性 |
|---|---|---|---|
| **规范性 normative**（承诺了什么）| 行为契约 | task `prd.md` 验收标准；关键能力的**累积契约摘要**在 `.trellis/spec/<pkg>/`（git）| prd 即弃 / 摘要持久 |
| **描述性 descriptive**（学到了什么）| 每任务捕获 | 本地 task 目录 notes/research（git-ignored）→ 完成 WIMTB 进 Multica issue | 本地临时 / Multica 持久 |
| **权威性 canonical**（现在相信什么）| 约定 + 决策 | `.trellis/spec/`（=persist/memory，约定/坑）+ `spec/guides/`（非包域 tacit/架构 know-how）+ `spec/guides/decisions/` ADR（=persist/architecture，三门决策）| git-tracked 团队共享 |

一句话：**task 目录 = 学到了什么（本地+Multica），`.trellis/spec/`+ADR = 现在相信什么（git），中间靠 finish 的 HITL 晋升门连接。**

## Per-Task Document Boundary（权威归属表）

<project> doc set 比 the origin harness 多，更需要边界表。**各 doc set 回答不同问题，不得互相复述**：

| Doc set | 回答 | 权威于 |
|---|---|---|
| task `prd.md` | 变更契约是什么？ | 需求、验收标准、行为 delta |
| task `design.md` / `implement.md` | 怎么设计/怎么执行？ | 技术设计（Dn 决策）、执行清单 |
| task 本地 notes/research（→Multica）| 学到什么会 outlive 本变更？ | tacit 知识、实现期决策/权衡、跨任务启示 |
| `.trellis/spec/<pkg>/` | 该 package 编码怎么做？ | 约定/规范/坑（persist/memory）|
| `.trellis/spec/guides/` | 跨包思维/非包域 know-how？ | 架构推理、运维 know-how（persist/memory 非包域部分）|
| `.trellis/spec/guides/decisions/` ADR | 为什么这么定（难逆/反直觉/真权衡）？ | 架构决策 + 为什么（persist/architecture）|

**唯一查重点 = HITL 晋升门**：晋升候选与已在 spec/ADR/prd 的内容查重；重复则删不晋升。

## Pairing Rules（软重叠协调）

1. **Open questions**：`design.md` 的 open-question **必须链接**到答案落点——task notes/research 文件；答案随 WIMTB 进同一 Multica issue。规划期提问、实现期作答。
2. **Rejected alternatives**：规划期否掉的（凭推理）→ `design.md` 一行理由；实现期否掉的（现实打脸）→ task notes 全上下文。不同决策时点，非重复。
3. **Architecture decisions**：per-change 决策进 `design.md` 的 D1..Dn；HITL 晋升时把 durable 架构洞见提到 ADR。**ADR 必须带 `Origin: <task/issue-key>`**（见 decisions/TEMPLATE.md），保晋升后可溯源到变更史。

## persist 晋升纪律（Hard Rules，无 OpenSpec/codegraph 下重述）

- **不复述契约**：ADR/spec 不得复述 task `prd.md` 验收标准或已在 spec 的约定（原 the origin harness「不复述 OpenSpec」的 <project> 版）。
- **不存代码可推的结构事实**：ADR/spec 只写决策/约束/被否方案/**为什么**；符号位置/调用关系/文件结构 = 读代码即得（**用 codegraph `query`/`callers`/`impact` 客观核**）→ 禁写。checklist：见到"某函数在哪/谁调用谁/目录长啥样" → 不进 ADR。
- 可逆的实现选择、操作性 know-how → 留 task notes 或 `guides/`，**不进 ADR**（ADR 只收三门决策）。

## RepoMem.read（Phase 1.0b 的 read 半边）

规划前加载**权威层**作上下文：读 `.trellis/spec/`（相关 package + guides）+ **`guides/decisions/` ADR 索引**（见 `guides/index.md` 的 ADR 索引段——read 步**必读**该索引）。需要历史（描述性）时用 `trellis mem`（对话回溯，**≠ 文档库**）+ `multica issue`（WIMTB 文档）检索——补充、非必读。
