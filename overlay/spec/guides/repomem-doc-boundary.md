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

### machine-local 的「已晋升」必须有 hgit commit 证据

写入 `.trellis/spec/`、ADR、durable validator 或 `.arborist/tools/` 只证明知识在**当前工作树已物化**，**不**证明它已进入 side history。machine-local 下必须区分三态：

| 状态 | 可声称什么 | **不**可声称什么 |
|---|---|---|
| 文件存在，但 `hgit status` 非空、或 `hgit log -- <path>` 为空 | 已物化、待提交 | 已持久 / 可从历史恢复 / 已 outlive 工作树 |
| 文件对 `hgit` 可见、状态 clean、且该 path 有 commit SHA | 已进入**本机** side history | 跨机 / 跨人共享（machine-local 永不提供） |
| 上一行成立，且每个证据 commit 已在某 remote-tracking ref 里 | 「截至上次 fetch 已进入 remote」 | 「此刻一定在远端」（remote-tracking ref 只新鲜到上次 fetch）|

收尾 landing manifest 里每个 canonical spec/ADR/validator/tool 路径，在 human **明确授权**本次 `hgit` commit 之后，必须运行：

```sh
python3 .trellis/scripts/validate_harness_persistence.py <exact-path>...
```

validator 逐路径要求：文件存在、未被侧史 ignore、索引/工作树 clean、至少一个 commit，并输出 `path@commit`。**未获 commit 授权时必须写 `pending human commit authorization`**，不得用「已晋升」替代「已持久」——「未经用户明说不提交」同样约束 `hgit`，同行或编排者的建议不能代替 human 授权。

要声称「保证已离开本机」，按**强度**选 flag，别用一个名字混两档（详见 [`verification-and-gates`](./verification-and-gates.md#持久化机制也必须有执行者)）：`--require-remote-configured` 只证明**配了** remote（**不**证明任何 commit 被推送过）；`--require-remote-reachable`（可用 `--remote` 收窄）才证明每个证据 commit 已进入 remote-tracking ref。**刻意没有 `--require-remote`** —— 不带限定的名字读起来像强声称，而廉价检查只支撑弱的那档。

这也暴露出一个自指边界：如果 guide 已写明「`hgit` 无强制步骤会失效」，却仍由工作树承载整段演进史，那么**「写进 guide」本身不是执行者**。要闭合该类风险，必须由 hook、收尾必答时刻或定时审计触发本 validator/提交；在这些执行者落地前，manifest 必须保留 pending，**不能用更醒目的文字冒充持久化**。

#### 1. 触发范围

任何 landing manifest 在 `spec_visibility: machine-local` 下声称 canonical spec、ADR、durable validator/script 或 tool registration **已持久化**时触发。task、runtime、cache 与普通 sendbox 不进入本契约。

#### 2. 命令

```sh
python3 .trellis/scripts/validate_harness_persistence.py \
  [--repo-root <work-tree>] [--git-dir <side-git-dir>] \
  [--require-remote-configured] [--require-remote-reachable [--remote <name>]] \
  <exact-path>...
```

#### 3. 契约

- 输入必须是 landing manifest 里的**精确路径**；不接受目录隐式扩面，**不自动 stage / commit**。
- 每个路径必须位于 repo root 内、是现存文件、对侧史可见、status clean 且有历史。
- 成功时 stdout 首行 `harness persistence valid: N path(s)`，随后逐行 `relative/path@<commit>`；失败写 stderr，且**不输出任何伪 commit 证据**。

#### 4. 错误矩阵

| 条件 | exit | 诊断 |
|---|---:|---|
| repo root / git-dir 不存在 | 2 | `not found`（fail closed，什么都没验）|
| path 越出 work tree 或文件不存在 | 1 | `outside` / `does not exist` |
| untracked durable 文件被 ignore | 1 | `ignored` |
| staged / unstaged / untracked | 1 | 未提交状态 |
| status clean 但该 path 无历史 | 1 | 无 commit 历史 |
| clean 且有 commit | 0 | `path@commit` |

#### 5. Good / Base / Bad

- **Good**：human 授权精确 pathspec commit 之后，所有 manifest 路径逐条输出 SHA。
- **Base**：未获授权、路径 dirty ⇒ manifest 保留 pending，validator exit 1。**这不是失败流程，这是诚实流程。**
- **Bad**：文件存在但被侧史根级 `/*` 静默 ignore ⇒ validator exit 1，禁止声称 durable。

#### 6. 测试要求

`tests/test_validate_harness_persistence.py` 覆盖 ignored / visible-uncommitted / committed-then-modified / clean-committed 四态与两档 remote flag。**真实收尾仍须另对 manifest 精确路径跑一次 CLI —— 单元测试不能替代真实 commit 证据。**

#### 7. Wrong vs Correct

```text
Wrong:   文件存在 + 已更新 ADR index  ⇒ 知识已 outlive 信件
Correct: 文件存在                     ⇒ 已物化
         status clean + path 有 SHA + validator PASS ⇒ 已进入本机 side history
         + --require-remote-reachable PASS           ⇒ 截至上次 fetch 已进入 remote
```

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

## Accepted ADR 的事实性更正边界

`accepted` 不等于禁止纠正事实，但必须区分「**决策变了**」与「**对世界的描述写错了**」：

- 修改后**我们该怎么做**发生变化 → **决策变更**。走新的 `proposed → accepted` HITL 门，或以 superseding ADR 明确替代旧决策；**不得借「修正文案」绕过接受流程**。
- 修改后做法不变，只是**世界是什么样**的事实范围被反例收窄或纠正 → **事实性更正**。可在 accepted ADR 原地加限定词与**带日期的 `⚠️ 修订` 块**，写清原陈述、反例、正确边界与可复核出处，并通知 human；不重开 HITL 晋升门。

事实性更正**不得静默覆盖历史**，也不得只换一句话而省略反例。已发生过的先例（通用化叙述）：某 adopting repo 的一份 accepted ADR 记「按进程组发信号并保留 SIGKILL 兜底」——决策本身没变，被更正的是「**所有**孙进程都会被回收」这个全称事实：一个真 `setsid()` 的孙进程证明逃逸后代不在原进程组内，于是 ADR 原地收窄为「继承进程组的孙进程」，并用日期修订块保留更正链。**该类范围过宽的全称结论，本可在接受前被 claim provenance 的「出处」栏挡住**（见 [`sendbox`](./sendbox.md#done-信与验收证据的-claim-provenance-门)）。

## ADR 文件名与编号分配（共享命名空间硬规则）

`guides/decisions/` 是所有 worktree 与并发 session **共同写入的一个物理命名空间**。「扫一眼当前最大号再加一」是带检查窗口的读-改-写，两个起草者仍可同时拿到同一编号；这**不是加强纪律能消除**的竞争。因此：

| 阶段 | 文件名 | 分配者 |
|---|---|---|
| 起草（`Status: proposed`）| `proposed-<slug>.md`，**不占数字编号** | L2 起草者 |
| 接受（`proposed → accepted`）| `NNNN-<slug>.md` | **本次 HITL accept 的单一 accept 方** |

- proposed 阶段的交叉引用**用 slug**，不用尚未稳定的数字。
- accept 方在接受**前**运行 `python3 .trellis/scripts/validate_adr_numbers.py --visibility <machine-local|product-git>`，从当时已编号文件里准备候选号；分配、改名与写 `Status: accepted` 属**同一次** accept 操作。写入**后**必须再跑同一 validator；任何四位数字前缀重复即 fail，接受不得完成。
- **`--visibility` 无默认值**：「哪个 git 记规范」是宿主布局，不是 validator 能猜的。缺失、或与 `--git-dir` 组合成「两个候选 git 都在场」，一律 exit 2 fail closed；侧史 git dir 不存在同样是**失败、不是静默跳过**——静默跳过正是让新 ADR 文件一直隐身的那个洞。
- **侧史必须让未跟踪的 durable harness 文件进入状态面**。只靠 `add -f` 会把「记得纳管」变成荣誉制：侧史根级 `/*` exclude 下，新 ADR、guide、validator 或 tool registration 都可**静默消失**。机械做法是在侧史 git dir 的 `info/exclude` 里用 **parent-directory allowlist**（git 不会下降进被排除的目录，故每一级都要先放行）放行 `.trellis/spec/`、`.trellis/scripts/`（继续排除 `__pycache__`）与 `.arborist/tools/`；task、runtime 与普通 sendbox 仍保持 local/transient。
- `validate_adr_numbers.py` 在真实 `decisions/` 上**同时**检查数字前缀与可见性：任一 proposed 草稿仍被记规范那个 git ignore 即 fail；**numbered 与 proposed 两类都查**，所以 accept 时的改名在编号前后都被覆盖。注意侧史 `info/exclude` 是**本机 git-dir 元数据、不进 harness 历史**，因此 `validate_adr_numbers.py` 与 `validate_harness_persistence.py` 才是可回溯的防漂移执行者，**不能把本机 allowlist 当作唯一修复**。
- 现存已经带号的 proposed ADR **不追溯改名**；它们在 accept 时仍须通过前后两次唯一性校验。

编号只在决策被接受、需要稳定公开引用时才有价值。让**单一 accept 方**分配是在源头序列化写入；validator 是兜底，按**四位数字前缀**分组（而不是按完整文件名去重——否则 `0007-a.md` 与 `0007-b.md` 会双双过关）。

## persist 晋升纪律（Hard Rules，无 OpenSpec/codegraph 下重述）

- **不复述契约**：ADR/spec 不得复述 task `prd.md` 验收标准或已在 spec 的约定（原 the origin harness「不复述 OpenSpec」的 <project> 版）。
- **不存代码可推的结构事实**：ADR/spec 只写决策/约束/被否方案/**为什么**；符号位置/调用关系/文件结构 = 读代码即得（**用 codegraph `query`/`callers`/`impact` 客观核**）→ 禁写。checklist：见到"某函数在哪/谁调用谁/目录长啥样" → 不进 ADR。
- 可逆的实现选择、操作性 know-how → 留 task notes 或 `guides/`，**不进 ADR**（ADR 只收三门决策）。

## RepoMem.read（Phase 1.0b 的 read 半边）

规划前加载**权威层**作上下文：读 `.trellis/spec/`（相关 package + guides）+ **`guides/decisions/` ADR 索引**（见 `guides/index.md` 的 ADR 索引段——read 步**必读**该索引）。需要历史（描述性）时用 `trellis mem`（对话回溯，**≠ 文档库**）+ `multica issue`（WIMTB 文档）检索——补充、非必读。
