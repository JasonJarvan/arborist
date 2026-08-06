# Arborist Guides

> Arborist 在 Trellis `.trellis/spec/guides/` 上叠加的**纪律与方法论**。规划/实现/评审时按需读对应 guide。总入口约定见 `.trellis/workflow.md` 的定制层。

> **可达性边界通告**：本 overlay 的可见性取决于宿主 `spec_visibility` 配置——`product-git`（spec/ADR 入产品仓 git，团队共享）或 `machine-local`（对产品仓隐身、副仓 `hgit` 记史，overlay 脚手架默认）。在 machine-local 或部分可见下，本 guide 集里的某些引用（`workflow.md` / `scripts/` / `host-config` / sendbox 等）在你的 checkout 里**可能打不开**。**打不开一个引用，不代表那条规则不存在**——照该规则执行，需要时另走渠道取到被隐身的文件。两个世界各得/各失什么、及部分可见的标注 pattern，见 [repomem-doc-boundary「spec/ADR 可见性」](./repomem-doc-boundary.md)。

## Guides

| Guide | 用途 | 何时读 |
|-------|------|--------|
| [角色层与任务分层 L1–L4](./roles-and-tiering.md) | L4 RootOrche / L3 SubOrche / L2 Impler / L1 subagent + 各级 steps + 生命周期场景 + ATUI 归属边界（通报⊥交办）+ worktree 步与纪律 | 多 session 协作、分解/派活、worktree 隔离 |
| [Execution Policy & Skip](./execution-policy.md) | 四级门控（auto/auto-judge/ask-first/HITL）+ Skip Bias + 跳过审计 + hooks add-only | 判断某步跑/跳、如何记录 |
| [RepoMem 层：文档边界与晋升](./repomem-doc-boundary.md) | 三层认知论 + Document Boundary 权威表 + Pairing Rules + persist 纪律 + read 装载 + spec/ADR 可见性（product-git vs machine-local）+ machine-local `path@commit` 持久性证明 + accepted ADR 事实性更正边界 + ADR 编号分配硬规则 | 沉淀知识、晋升 ADR、避免把「已物化」误报成「已持久」 |
| [泛化边界（技术基石）](./generalization-boundary.md) | 泛化 gap 定义 + host-config/定制层/占位 三处分流 + 结构性排除 + 注入子集边界 + **范例清单 vs 穷举清单（未标注一律读作范例；范例被当穷举用是单向失效）** + `spec_visibility` + 预防>检测>判断 | 撰写/同步 guide、公开上推去隐私、想让同步机械化、写任何清单 |
| [Verification & Gates](./verification-and-gates.md) | 门有执行者吗（通则，含共享命名空间/荣誉制记录/临时资源三形态 + 持久化两档 remote 强度）+ **「有一类规则只能由事故生成」通则**（实测清单 + 复盘必产规范增量 + 实测证据等级不需先有理论 + 自带现成解释的错误读数不会被追查 ⇒ 须落可证伪判据 + 事故生成的规则也要防假阳性）+ 记录的形状决定将来能不能重新判断 + **状态表里的「已落」必须附一条独立读数**（自报信道双向都会错 · 假 ✅ 让该项从视野消失 ⇒ 判不准时不标已落 · 汇报措辞不得可被读成完成态）+ **transient 载体销毁前必须抽取判据**（burn 的是载体不是判据 · 粒度/落点/执行者三缺口 · 引用作机械产物 · 落点分流 · 判不准的不 burn 转 archive）+ 观测不得扰动被观测者 + **门的回归必须端到端且测试结构与真实调用路径同构**（两维度实例：调用链层级 / 进程-shell 类型 · 制品到位≠路径生效）+ 多 lens 验证 + security-scan 接 MR 硬门 + 门的触发钉在 hazard 上 + **Allowlist over denylist**（问「谁批准了」不问「有什么问题」· 两个独立问题域收敛 · 配套必要条件=批准必须便宜 · `scope` 待落登记）+ 门控矩阵（代码评审 / claim provenance / ADR 编号 / harness persistence / 临时资源 / **AgentTUI 注册表一致性**行）+ landing manifest（含 History proof 必答项）+ Challenge-before-ack + 已知上游 Trellis 缺口 | 验证、发 MR、晋升知识、给荣誉制门配机械产物、事故复盘落规范、销毁任何 transient 载体前、设计新门 |
| [Sendbox 定向交办](./sendbox.md) | 跨 session 角色交办（read_first 绝对路径 + process-completeness + 生命周期/WIMTB）+ 持久化形态 A/B · fyi 信型 + **销毁前判据抽取（`lifecycle_executor` 必填 · 缺它不得声明 burn · 产物=可打开核对的引用）** + done 信/验收证据的 claim provenance 门（两个消费点 · 非通用 hook · 门/机制类结论的缺口须标到「层」）| durable handoff / 回报 / 写 done 信 / burn 或 archive 一封信之前 |
| [Dashboard 待办投影](./dashboard.md) | 跨 session「此刻轮到人做什么」单一视图 | 多 session/待办堆积 |
| [AgentTUI 注册表](./agenttui-registry.md) | 并发 session 同伴发现：`.arborist/` 级联 + spec/runtime schema + **§2.2.1 唯一性约束（`session_id` 全局唯一 + `pane_ref` 四元组〔含 `socket`：pane id 只在单个复用器 server 内唯一，缺 socket 会同时造成假冲突与漏报〕在可达 leaf 间唯一〔pane 顺序复用 ⇒ 高危 `pane-ref-conflict` 与低危 `stale-addressing-handle` 拆开〕+ 误投比不可达严重的后果分级）** + 声明/派生状态模型（含 stopped 写入 guard + 活转录矛盾检测/reconcile）+ 自登记（含写入路径 fail-closed 门）+ 投递契约（送达证据等级、pane 存在性探针、发送侧能力检查与 `no-operational-route`、投递前置校验两半、**五种「注册表看不出来的投不进/投不对」（含 delivered-but-verified-too-early 假阴性与构造侧内容损坏；分类按可观察签名、每格签名级 fixture + 独占性 已证明/假定 分级 + 必留 `unclassified` 格；末列只管可靠性轴，侵入性轴另计）+ 投递形态约定「durable 走信、直投只送短指针」+ 通则「送达 ≠ 迁移完成」（已迁移是逐调用方的事实，须枚举分类；merge 或一次投通都不算）+ `dump-screen` 诊断用途与边界**、**规则 8 接收侧 submit-ack 握手（因果判据 vs 旁观判据并存、不一致判读表、「ack 缺失 = 未确认 ≠ 未提交」的 fail-safe 方向、对七值模型的单向修正）**、随发 adapter 缺口清单）+ ****§2.1.1 `capabilities` 三值闭集（`available`/`policy-denied`/`unavailable`；策略禁用≠能力缺失，值命名上交对象；缺字段读作 unknown 非 available）** + §4 一致性 validator 检查（`validate_agenttui_registry.py`，只读无 `--fix`）** | 开新 session 自登记、找同伴、投递给同伴、gardener 维护注册表、体检注册表一致性 |
| [安全启动 AgentTUI + brand-capacity observer](./agenttui-launch-and-brand-capacity.md) | §1 安全启动独立 ATUI 契约（一 tab 一 ATUI + new-tab 清父身份 + resolve 稳定非插件 pane + 定向 bootstrap + 被启动方自登记 brand + HITL）；**不变量 7 启动路径人机同构（人机共用同一段启动逻辑 `scripts/atui_launch.sh`：幂等 / 一个环境变量可回退 / `"$@"` 参数不失真 / 两段式命名只做第一段 / `--dry-run` / 复用器不可用即 fail-closed 而非悄悄不套；**尚未接线**）+ 不变量 8 嵌套形态判定实验须 human 在场且顺序为「自识别门 → 改 launcher → smoke test」**；§2 单写者 observer 契约（CLI/schema/source+freshness）+ §2.4 Claude `/usage` collector；§3 建 Impler 前 selection 语义 | 启动独立新 AgentTUI、建新 Impler 前按容量选 brand |
| [工具注册表 / 插件层](./tool-registry.md) | 可选能力发现：`.arborist/tools/` 级联 + `tool.json` schema + required/optional 置备与逐工具 fallback + 工具已知局限（`known_limits`：静默漏/静默空 → 交叉核验 + prefer 必配 fallback） | 需要某可选能力（历史检索/台账/…）、登记新工具、adopt 置备、写「prefer tool X」的 spec 行 |
| [知识收尾（洁癖式）](./knowledge-closeout.md) | 交付后全仓知识一致性门：事实面矩阵 + 两阶段汇报 + 触发分级（含 `/neat` 手动触发词表，覆盖 fast-lane 跳过）+ landing manifest（无条件产出）；收尾方自跑 | full lane/milestone 收口、`/neat`/neat skill/洁癖 skill 显式点名、扫改动面外的过期文档/规则/记忆 |
| [HS 15-step 落点映射](./pipeline-mapping.md) | HarnessStack 15 步 → Trellis 3 阶段/guides 对照 | 想知道某方法论步进哪了 |
| [Engineering 方法论簇](./methodology/) | T1–T9（LLM 测试 / 验证纪律 / 契约防漂移 / MR / 依赖治理 / 数据契约 / 错误处理 / 本地文档 / handoff 归因）+ Tier3 | 对应场景取用 |
| [ADR 模板](./decisions/TEMPLATE.md) | 架构决策记录（三门自检 + `Origin` 溯源 + 起草为 `proposed-<slug>.md` 不占号 + 前后两次 validator） | 产生 durable 架构决策时 |
| [Acceptance evidence 模板](./_TEMPLATE-acceptance-evidence.md) | 验收结论按 实测/推断 分类，强制出处与未验证缺口（配 `validate_claim_provenance.py`） | 新建或实质重写验收证据文档时 |

## ADR Index（RepoMem.read 必读）

> 规划前必扫，避免重复决策 / 违背既有约束。ADR 只收过三门（难逆/反直觉/真权衡）的架构决策；可逆实现选择留 task notes 或相应 guide。

| ADR | 标题 | Status | Origin |
|---|---|---|---|
| [0001](./decisions/0001-agenttui-session-id-primary-key.md) | AgentTUI 注册表以 session-id 为主键 | accepted | dogfood |
| [0002](./decisions/0002-agenttui-declared-derived-state-model.md) | AgentTUI 状态用声明态+读时派生态模型（无守护进程） | accepted（+2026-07-26 amend.） | dogfood |
| [0003](./decisions/0003-cross-session-reach-semantics.md) | `session_id` 触达语义 = `--resume` 追加，据活性选通道 | accepted（+2026-07-30 amend. 2：cwd 硬前置） | gardener |
| [0004](./decisions/0004-closeout-split-l2-draft-l4-accept.md) | 收尾职责分层 — L2 起草 / L4 轻量 accept | accepted | rootorc-methodology |
| [0005](./decisions/0005-agenttui-role-lineage-vs-generation.md) | AgentTUI 注册表补角色继承代数 lineage（与 generation 正交） | accepted | adopter-rootorc-v2 + gardener |
| [0006](./decisions/0006-runtime-brand-is-routing-authority.md) | actual runtime brand 是 subagent 路由唯一权威 | accepted（+2026-07-26 amend.） | human brand-compat ruling + gardener |
| [0007](./decisions/0007-agenttui-delivery-contract-pluggable-adapter.md) | AgentTUI 活 pane 投递 = 契约进规范 + 具体传输作可插拔 adapter | accepted（+07-29 amend.：双指纹/全文降级 + 抢焦点局限 + 规则 5 存在性探针 + 跨目录 resume 回填；+07-30 amend.2：规则 6 发送侧能力检查、否决 `brand_version`） | dogfood + rootorc |
| [0008](./decisions/0008-brand-capacity-and-safe-launch.md) | 容量是观测非权威 headroom / observer 只观测 / launcher 选二进制 session 自登记 brand | accepted | issue #14 |
