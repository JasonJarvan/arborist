# ADR-0005: AgentTUI 注册表补「角色继承代数 lineage」，与 generation 正交

- **Status**: accepted
- **Origin**: adopter-rootorc-v2 需求（某 adopter 仓）+ Arborist gardener 裁定（dogfood 跨仓）
- **Date**: 2026-07-25

## 三门自检（都 yes 才该是 ADR，否则留 task notes/guides）
- [x] 难逆（改起来代价大）—— schema 新增身份维，落地后跨仓模板/实例都依赖其语义
- [x] 无上下文会让人惊讶（反直觉）—— `generation` 与「第几代承担者」是两回事、结构上不可互推，却极易被混为一谈
- [x] 真权衡（有被牺牲的合理替代）—— 编进 name / 复用 generation / 全量审计指针，各有代价

## 背景
sendbox Mode B（inheritance-handoff）是长程 L4/L3 角色的常规路径：上下文将尽 → 写交接信 → **角色不死、承担者换人**。任何仓跑久了 rootorc 必出 v2/v3。但注册表 schema 无字段表达「当前是该角色第几代承担者」：`generation`（ADR-0001/0002 锚定）是「**同一承担者**换会话的次数」，与继承代结构上独立——承担者 v1 自己跨多会话时 `generation` 已 > 继承代。实证：adopter-rootorc-v2 `generation=3` 而继承代=2。于是会话名（`adopter-rootorc-v2`）携带了表里查不到的身份信息。

## 决策
`spec.json` 新增两字段，`generation` 语义**一字不改**：

- **`lineage`**（整数，权威字段）：角色继承代数，首任=1，每经一次 Mode B 交接 +1。**缺字段读作 1**（向后兼容，老条目/首任无需回填）。放 `spec.json` 因其是**稳态身份**（不随会话重启变），与 `runtime.json.generation`（活体、随重启变）分居两文件。
- **`lineage_origin`**（可选，**best-effort 面包屑**）：本代继承所依据的 handoff 信溯源（前任 session_id + 信名）。**显式定为非权威、可悬空**——交接信按协议 burn 后此值指向已烧文件；审计继承链去 git 历史 / ledger，**不得当审计指针用**。
- 全局 `index.json` 摘要带 `lineage`（缺省=1），服务跨项目「找当前代」；不带 `lineage_origin`。
- §2.1 加 generation/lineage **消歧句**——这是原始诉求核心。

判据一句话：**注册表是快照，答「当前第几代」（发现用）；不是账本，不答「继承链长什么样」（审计用）。**

## 被否方案
- **B：把继承代编进 `name`（`rootorc-v2`）**：改 name = 新建 leaf、旧条目变孤儿、历史断裂，且 name 一换 `generation` 归 1、丢失重启历史。否。
- **C：复用 `generation` 表继承代、重启不再 +1**：破坏 §2.2 既有语义与 ADR-0001/0002 状态模型，且丢重启历史。否。
- **全量 A：`lineage_origin` 作权威审计指针 + 注册表承载按代分组的继承链**：把快照表推成 ledger，与 ADR-0002「声明+读时派生、非历史存储、条目可 GC/重建」哲学冲突；且指针指向注定 burn 的信 = 天生悬空。**收窄**为 best-effort 面包屑 + 审计留给 ledger/git 历史。（需求方 adopter-rootorc-v2 复核后采纳此收窄。）

## 后果
- 正：会话名与表自洽；「找当前代承担者」可发现；零破坏（缺字段=首任）；快照/账本职责边界清晰。
- 负：继承链审计不在注册表内，需另经 git 历史 / ledger（有意为之）；`lineage_origin` 悬空时仅作面包屑，须靠文档纪律防误用（故 §2.1 + 本 ADR 反复标注非权威）。
- 遗留：按继承代分组的历史 GC 明确**撤回**（超快照表职责）。
