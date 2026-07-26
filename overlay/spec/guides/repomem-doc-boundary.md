# RepoMem 层：记忆分层 · 文档边界 · 晋升纪律（<project>）

> 吸纳自 HarnessStack § Repository Memory Layer / Task Identifier and Document Boundary。<project> 无 OpenSpec、无 codegraph 作真源时的重述见文末。

## 三层认知论

| 层 | 语义 | <project> 载体 | 持久性 |
|---|---|---|---|
| **规范性 normative**（承诺了什么）| 行为契约 | task `prd.md` 验收标准；关键能力的**累积契约摘要**在 `.trellis/spec/<pkg>/`（git）| prd 即弃 / 摘要持久 |
| **描述性 descriptive**（学到了什么）| 每任务捕获 | 本地 task 目录 notes/research（git-ignored）→ 完成 WIMTB 进 Multica issue | 本地临时 / Multica 持久 |
| **权威性 canonical**（现在相信什么）| 约定 + 决策 | `.trellis/spec/`（=persist/memory，约定/坑）+ `spec/guides/`（非包域 tacit/架构 know-how）+ `spec/guides/decisions/` ADR（=persist/architecture，三门决策）| 持久；可见性随宿主 `spec_visibility`（见下节，**非无条件 git-tracked/团队共享**）|

一句话：**task 目录 = 学到了什么（本地+Multica），`.trellis/spec/`+ADR = 现在相信什么，中间靠 finish 的 HITL 晋升门连接。**「在 git 里、团队共享」这半句**只在宿主 `spec_visibility: product-git` 时成立**——见下节「spec/ADR 可见性」。

## spec/ADR 可见性：product-git vs machine-local（host-config 显式选择）

「权威层在 git 里、团队共享、可经 MR 晋升」不是天然事实，而是宿主的一个**显式配置**——host-config `spec_visibility`。overlay 自身的脚手架默认把整个 overlay 用 `.git/info/exclude` 对产品仓隐身（machine-local），所以**不加限定地断言「spec/ADR 是 git-tracked 团队共享」为假**。两个世界，adopt 时选定并写进 host-config，正文只描述两者、不预设某一个：

| `spec_visibility` | 有 | 代价 / 失去 |
|---|---|---|
| **`product-git`**（spec/ADR 入产品仓 git）| 第二读者、可经 MR 评审、团队共享晋升；「现在相信什么，在 git 里」的晋升叙事成立 | 内部方法论/决策记录进产品仓历史 |
| **`machine-local`**（overlay 对产品仓隐身、副仓 `hgit` 记史；overlay 脚手架默认）| 私密——内部记录不进产品史 | **无第二读者、无 MR**；「在 git 里」的晋升叙事**不成立**（spec/ADR 只在本机 side history，甚或没有）；**跨机 / 跨人不可见** |

> 与 [sendbox.md 「持久化与可见性（形态 A / B）」](./sendbox.md) 同一枚硬币、不同维度：那节治**信件**的持久化/可见性，本节治 **spec/ADR** 的。术语对齐——`spec_visibility: product-git ≈ 形态 A（纳入产品 git）`、`machine-local ≈ 形态 B（排除）`；不复述，信件维度看 sendbox、spec/ADR 维度看本节。

**吃重的推论（授权下放护栏）**：machine-local 下，任何以「它登记在 ADR 索引里、human 事后可审计」为据的护栏**不存在**——索引不在任何共享历史里、无第二读者。据此下放的授权只能撤回。**授权下放不得以「经索引可事后审计」为唯一护栏**，除非 `spec_visibility: product-git` 且该记录确在共享历史里。

### 部分可见（只 `spec/` 入产品 git、其它路径仍隐身）的可行 pattern

若宿主只把 `spec/` 树入产品 git、而 workflow / scripts / host-config / sendbox 等仍隐身，spec 会引用一堆**在读者 checkout 里打不开的路径**：读者拿到一份**看着自洽、实则不全**的规则集，不报错、径直照残缺规则往下走（同「工具静默返回空结果」的失败形）。落地过的 pattern：

1. **一处可达性边界通告放在保证被加载的位置**——guides `index.md`（read 步已强制读它，见本篇末「RepoMem.read」）；**各其它 spec 树入口再各放一处**。放在没有保证读者的地方 = 重犯荣誉制错误。
2. **只就地标注高风险引用**——读者会据以行动的那些（step 定义 / 工具定义 / 外契约 SSOT）；**自描述与溯源引用不动**，免得通告淹没在噪声里（大多数引用属这类，别逐条加噪）。
3. **明写那句吃重的话**：**「打不开一个引用，不代表那条规则不存在。」**

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
