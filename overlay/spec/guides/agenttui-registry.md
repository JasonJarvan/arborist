# AgentTUI 注册表：并发 session 同伴发现层

> **AgentTUI** = 一个跑在终端里的 coding-agent TUI 会话（Claude Code / Codex …），以 **session-id 为主键**。本注册表是纯文件式静态表 + 约定驱动，回答「本项目/本机有哪些 AgentTUI、各自 role / description / 当前 task / session-id / 状态」，让并发 session 能**互相发现**。**core 无守护进程、无常驻自动投递 runtime**——CCB 式 A2A 自动回投 / `message→attempt→reply` 三段链 / callback 续跑仍属长期目标，另行追踪，不在本规范内。**往活 pane 的字节注入投递则不再是绝对 out-of-scope**：经 [ADR-0007](./decisions/0007-agenttui-delivery-contract-pluggable-adapter.md) 修订为受契约约束的**可插拔 adapter**——core 只规定投递【契约】、保持 transport 中立（仍无守护进程），具体 zellij pane / 字节注入是**参考 adapter · opt-in**、不在 core（契约见 §3「投递契约」）。投递 adapter 是**送达侧新增的一类更可靠选项**，不改下述三通道与「记录⊥送达正交」——durable 内容仍必留信不变。但**跨 session 触达本身是现成的**：Claude Code 原生支持 `claude -p --resume <session_id> "<msg>"` 向指定会话追加消息——注册表存 `session_id` 作触达句柄正是为了利用这一能力。触达分**三通道**（直投 / 写信 sendbox / 用户投），且**记录与送达两轴正交**——durable 内容必留信物（写信），是否另行直投作送达提醒由发送方定，见 §3 末「跨 session 触达」。
>
> 姊妹规范：**[工具注册表](./tool-registry.md)**（「本机/本项目有哪些可选能力可用」；本表 = 「有谁」）+ **[安全启动 AgentTUI + brand-capacity observer](./agenttui-launch-and-brand-capacity.md)**（**启动侧姊妹**：如何安全启动一个**新**独立 AgentTUI + 建 Impler 前按容量选 brand；本表 §3 投递契约 = 往**已存在**活会话注入，两侧共用 pane 寻址 `--pane-id`——注意 §3 已据实测记下：`--pane-id` 寻址**不免除聚焦**，跨 tab 需先 `focus-pane-id`）。三者同构、共用 `.arborist/` 级联、同由 gardener 维护。

## 1. 位置：全局-项目级 级联

```
~/.arborist/                      # 全局（机器本地，跨项目）
  index.json                      # 项目清单 + 各项目 AgentTUI 摘要（gardener 持有）
<repo>/.arborist/                 # 项目级（机器本地运行时态，git 隐身）
  agents/<name>/
    spec.json                     # 稳态身份
    runtime.json                  # 活体状态
```

- **渐进式披露**：需要读表时 → 先读**当前项目 `<repo>/.arborist/agents/*`**（+ 全局 index 摘要）；仅当确需触达**别的项目**的 AgentTUI，才经全局 `index.json` 查到目标项目路径，再读其 `.arborist/`。
- **git 隐身**：`.arborist/` 是机器本地运行时态（session-id 只对本机会话文件有意义），须列入 `.git/info/exclude` + `.gitignore`（adopt 脚手架已代劳）；全局 `~/.arborist/` 天然在仓外。
- **脚手架模板**：adopt 时铺 `<repo>/.arborist/templates/`（源：Arborist 仓 `overlay/arborist-templates/`），示例值即字段文档。

## 2. Schema

### 2.1 `spec.json`（身份，稳定，自登记时一次写成）

| 字段 | 说明 |
|---|---|
| `name` | 唯一名 = 目录键。归一化小写，建议满足 `^[a-z][a-z0-9_-]{0,31}$`；避开保留名（`all` / `user` / `system`）；同项目内唯一（gardener 校验） |
| `role` | `rootorc` / `suborc` / `impler` / `subimpler` / `gardener`（见 §2.4） |
| `brand` | 会话的 **actual runtime brand**：`claude-code` / `codex` /（可扩展）。自登记必须写正在运行本会话的真实 ATUI brand；不得按模板示例、期望路由或模型名猜测，也不得把一个 brand 伪装成另一个 brand。声明值与实际 runtime 不符时，注册校验必须 fail closed。 |
| `description` | 这个 AgentTUI 是干什么的（人读） |
| `task` | 当前在做的任务：自由文本或 task/issue 引用 |
| `project` | `{ "path": 项目根绝对路径, "project_id": 路径哈希 }`；约定 `project_id` = **`realpath` 归一化（解析 symlink、去尾斜杠）后**的绝对路径 sha256 前 12 位十六进制（保证跨表一致、可机械重算；不归一化会让同一仓经不同路径拼写裂成两条 index 记录） |
| `created` | 建立时间（ISO8601） |
| `lineage` | **角色继承代数**（整数，首任=1；每经一次 inheritance-mode 交接（sendbox Mode B：承担者换人、角色不变）+1）。**缺字段读作 `1`（首任）**，向后兼容。放 `spec.json` 因其是**稳态身份**——不随会话重启变，与 `runtime.json.generation`（会话重启代数）分居两文件。**消歧（俩概念被混淆的根因）：`generation` = 同一承担者换会话的次数；`lineage` = 换承担者的次数**——两者结构上独立、不可互推（承担者跨多会话时 generation 会大于 lineage） |
| `lineage_origin` | 可选。本代继承所依据的 handoff 信**溯源面包屑**（建议格式：`前任 session_id + 信文件名`）。**⚠️ 非权威、可悬空**——inheritance handoff 信按 sendbox 协议在承接方首个里程碑后 `burn`，此值届时指向已烧文件；**真要审计继承链请去 git 历史 / ledger，切勿把本字段当审计指针**。注册表是快照（见 [ADR-0002](./decisions/0002-agenttui-declared-derived-state-model.md)/[ADR-0005](./decisions/0005-agenttui-role-lineage-vs-generation.md)），只答「当前第几代」（发现用），不答「继承链长什么样」（审计用） |

### 2.2 `runtime.json`（活体，易变，可信触点刷新）

| 字段 | 说明 |
|---|---|
| `session_id` | **主键 / 触达句柄**。`claude -p --resume <session_id> "<msg>"` 向该会话**追加**一条消息并让其在自身完整上下文里处理（实测：append 非 fork，回复走调用方 stdout）。触达前须按 §3 末判活选通道 |
| `session_file` | 会话落盘**绝对路径**（判活探针，令读者零 brand 知识）。Claude Code：`~/.claude/projects/<munged-repo-path>/<session_id>.jsonl`（逐轮 append，mtime = 最近活动，已实证）；Codex：`~/.codex/sessions/YYYY/MM/DD/rollout-<ISO时间戳>-<session_id>.jsonl`（逐轮 append，mtime = 最近活动，**已实证**：`codex exec resume` 续同一 rollout、mtime 随 turn 递增、不新建文件，与 Claude Code 同——见 [ADR-0003](./decisions/0003-cross-session-reach-semantics.md) 实测边界） |
| `state` | **声明态**：`active` / `stopped`（`idle` 为保留枚举值，MVP 不自写，见 §3）。`stopped` 有**写入门槛**（仅会话真正结束才写，见 §3/§4）且遇活转录矛盾会被派生规则**降级为 contradiction**——声明态非确知，读者据 §3 现算，不无条件采信 `stopped` |
| `last_seen` | 心跳时间戳（ISO8601，可信触点顺带刷新）。**写 `stopped` 时也须记 `last_seen`**——它是活转录矛盾检测的基准：若 `session_file` mtime 晚于该 `stopped` 写入记录的 `last_seen`（容小段文件系统时钟偏移），即声明与派生活性证据矛盾（见 §3） |
| `generation` | 重启代数（同一 `name` 重启/换 session 时 +1） |
| `pane_ref` | 可选：**投递 adapter 用的** 终端复用器 pane/tab 引用。core 不强制（未启用活 pane 投递时置 `null`）；启用活 pane 投递 adapter 时按 [ADR-0007](./decisions/0007-agenttui-delivery-contract-pluggable-adapter.md) 契约填，供 adapter 寻址目标 pane。**它是启动时快照、会腐烂**：复用器 session 改名或换复用器后，整条 `pane_ref` 必须**重建**（不能只改 `multiplexer` 字段），否则注入会静默投空——见 §3 投递契约规则 5。注意：送达证据（transcript 字节边界 / per-send nonce / marker）是 **per-send 运行时态，不入本静态表**，故此表**不**新增存 nonce/证据的字段 |

#### 2.2.1 唯一性约束（规范性 · 机械执行者见 §4）

注册表无守候进程、每个写入者各写自己那条 leaf，故下列两条唯一性**结构上可能被违反**，且**必须由 validator 机械检查**（`validate_agenttui_registry.py`，见 §4）——只写在这里而无执行者，按 [verification-and-gates「没有执行者的门是装饰」](./verification-and-gates.md#门有执行者吗通则没有机械产物的规则是装饰) 就是装饰。

- **`session_id` 全局唯一 —— 一个会话属于一个项目。** 同一 `session_id` 不得出现在**多个项目**的 leaf 里（也不得在同一项目里被两条 leaf 声称）。真归属可由该 leaf 的 `session_file` 路径、或该 pane 的实际 cwd 判定；不属于本项目的那条应删。**这条是根约束、不受有效态限定**——重复登记无论 `state` 写什么都是错登记。
- **`pane_ref` 唯一性 —— 一个 pane 一个「活」agent**，键是 `(multiplexer, session, pane_id)` **三元组**（同一 `pane_id` 落在两个复用器 session 下不算撞）。它形式上是上一条的推论，**但必须独立检查**：两个**不同** session 声称同一 pane 说明至少一条 `pane_ref` 已腐烂（见上表 `pane_ref` 行「启动时快照、会腐烂」），而 `session_id` 唯一性检查看不见这一格。
  - **⚠️ 唯一性只在「有效态可达」的 leaf 之间强制**（`active` / 保留值 `idle`；`state` 缺失或未知值按可达处理——猜「大概死了」会把高危发现压掉）。**理由：pane 会被顺序复用**——一个 session 结束、下一个在同一 pane 里起来，旧 leaf 若还留着非空 `pane_ref`，这是**完全正常**的残留，不是冲突。按朴素「三元全局唯一」实现会把它报成冲突，而**假阳性多的 validator 会被人忽略，那比没有更糟**。
  - **故拆成两条独立发现，不得折进一条**（两者处置完全相反：一个要当场停下来修，一个批量清扫；混在一起高危会淹在低危里）：

  | 发现 | 判定集合 | 语义 | 严重度 |
  |---|---|---|---|
  | **`pane-ref-conflict`** | **仅**有效态可达的 leaf 之间 | 两个**活体**抢同一个 pane ⇒ 会打到别人的 pane，**必须立刻判** | 高危（validator 非零退出）|
  | **`stale-addressing-handle`** | `state` 非可达（`stopped` 等）**却仍带非空 `pane_ref`** | 该清理的残留（很可能只是 pane 已被后续 session 复用）；**不得计入唯一性冲突** | 低危（warning，不影响退出码）|

**违反的后果分级（决定处置优先级，不是修辞）**：

| 形态 | 失败方式 | 波及范围 |
|---|---|---|
| **不可达**（half-registered，见 §4） | **响亮**：投递按规则 5/6 preflight 失败，报 `no-operational-route` 并非零退出 | 只影响这一次投递 |
| **误投**（`pane-ref-conflict`：`pane_ref` 被多条**可达** leaf 声称 / 已腐烂） | **静默**：注入命令 rc=0（pane 不存在时 stdout 还完全为空，见 §3 规则 5），发送方读不出任何异常 | **污染第三方会话**——信封落进一个毫不相干的 ATUI 的 composer |

⇒ **误投比不可达严重，优先处置。** 理由是**谁承担代价、以及故障能不能被看见**：不可达当场就被 fail-closed 挡住、只有发送方受影响，代价有界且有人会看到；误投既不报错、又把代价转移给一个从未参与本次投递的第三方会话（它收到一段莫名指令，可能照做），且没有任何机械信号会让任何一方察觉。**一个能被看见的失败恒优于一个看不见的成功。**

### 2.3 全局 `index.json`（摘要级，gardener 维护）

`{ "projects": [ { "project_id", "path", "name", "agents": [ { "name", "role", "brand", "state", "session_id", "lineage" } ] } ] }` —— 仅作跨项目发现的入口，细节以各项目 `.arborist/agents/*` 为准。摘要带 `lineage`（缺省=1）是为跨项目「找当前那一代承担者」的常见意图；不带 `lineage_origin`（溯源属细节，且非权威，见 §2.1）。

- **摘要与 leaf 的两份拷贝必须一致，且 leaf 为准**：`role` / `brand` / `state` / `lineage`（缺省 1）在两处同时存在，任一处漂移都会让跨项目读者按摘要作出错误路由（如按摘要的旧 `brand` 选 submit 键）。不一致时**以 leaf 为准**（§1「细节以各项目 `.arborist/agents/*` 为准」），修的是摘要。
- **摘要与 leaf 的存在性也必须成对**：只有一边即 `half-registered`（两方向定义与修法见 §4）。
- **`project_id` 是可机械重算的派生值，不是可手抄的字面值**：照 §2.1 的算法（`realpath` 归一化后 sha256 前 12 位）**重算比对**；手抄或从别的项目复制会让同一仓在跨表读者眼里裂成两条记录。
- 以上三条与 §2.2.1 两条唯一性同由 `validate_agenttui_registry.py` 检查（§4）。

### 2.4 role 枚举（语义对齐 [roles-and-tiering.md](./roles-and-tiering.md)）

| role | 级 | 说明 |
|---|---|---|
| `rootorc` | L4 | 开发产品本身、对人、编排整仓 |
| `suborc` | L3 | 子编排，管一批 impler |
| `impler` | L2 | 实现一个可独立验证交付 |
| `subimpler` | L1 | session 内短生命 subagent（implement/check/research）；**默认不入表**——短命、无需被发现，仅作保留枚举值 |
| `gardener` | meta | 横切：维护 harness + AgentTUI/工具两注册表（登记/清理条目、持全局 index）；非 L 链一环 |

## 3. 状态模型（读表方必读）

- **声明态**（agent 自写，仅两个可信触点）：`active` —— session start 自登记及心跳触点写；`stopped` —— **仅会话真正结束时写**（写入门槛见下「stopped 写入门槛（Guard）」；含糊措辞「干净收尾」已作废，因它把任务生命周期事件误当会话结束）。崩溃/关终端没有回调，崩溃路径的 `stopped` 永远不会被写——这是结构性事实，读者不得假设声明态完备；且自写的 `stopped` 可因范畴错误而失真（见下 reconcile），读者亦不得无条件采信。
- **`idle` 是派生态**：agent 空闲时不在运行，物理上无法自写。schema 保留该枚举值，兼容未来平台 hook 机械写入的增强（留验证的增强路径，MVP 不依赖）。
- **有效态 = f(声明态, last_seen 新鲜度, session_file mtime 探针)**，由**读者读表时现算**（无守护进程，观测退化为读时派生）：

| 条件（按序判定） | 有效态 |
|---|---|
| 声明 `stopped`，但 `session_file` 存在且转录 mtime 落在**新鲜窗口**内（距今 < idle 阈值，**或**晚于该 `stopped` 写入记录的 `last_seen`，容小段文件系统时钟偏移） | **contradiction —— 可疑 stopped / 疑似仍活**：reader 视其为 reachable/active；validator 报该不一致叶子；owner 以 heartbeat 修复；**gardener 复核前不得据此 GC** |
| 声明 `stopped`（无上述矛盾证据） | stopped |
| `session_file` mtime 距今 < idle 阈值 | active |
| mtime 距今 ≥ idle 阈值 且 < stale 阈值 | idle（推定） |
| mtime 距今 ≥ stale 阈值，或 `session_file` 不存在 | stopped/stale（推定；gardener GC 候选） |

- 阈值：idle **15min** / stale **24h**，均为**建议默认值**，按项目节奏可调。`session_file` 不可读时退用 `last_seen` 作新鲜度依据（较粗：只反映可信触点，不反映逐轮活动）。
- **探针局限（必须知道）**：会话落盘是 open-append-close 写入，空闲期无进程持有其 fd ⇒ 无法经 fd 把 pid 映射回 session；mtime 停跳时，「idle 但终端还开着」与「已关终端」**不可区分**。因此 idle 与 stopped/stale 一律是**推定，不是确知**。
- **stopped 写入门槛（Guard）**：`stopped` 是**会话生命周期**信号，不是任务生命周期信号。
  - **会话真正结束**才可写 `stopped` = AgentTUI teardown，**或** Mode-B 角色交接（sendbox inheritance：承担者换人、当前会话不再续该角色）。
  - 明确**不构成**会话结束、因而**不得**触发 `stopped` 写入的事件：任务完成 / 任务 archive / 末条 assistant 回复 / 等待用户输入 / prompt 空闲 / compact / 上下文重置。这些是任务或轮次事件，会话线程仍会继续处理后续 turn。
  - **session 不得在自身仍是活 session 时写 `stopped`**——防「archive 完顺手标 `stopped` 却继续处理用户 turn」这一任务-会话生命周期**范畴错误**（本 guard 的直接由来）。收尾（任务/里程碑洁癖收口）只刷 `last_seen` 心跳、更新 `task`，**不写 `stopped`**。
  - 若配备生命周期命令（adopter 自置），`stop` 应要求**显式会话结束确认**（confirm-session-exit），`heartbeat` 应同时刷项目级 leaf 与全局 index。具体命令名/路径属 adopter 本地，不入本规范。
- **活转录矛盾检测（reconcile：declared `stopped` 不再无条件优先）**：读者现算有效态时，先按上表首行做 reconcile——当声明 `stopped` 与**新鲜 live 派生证据**矛盾（`session_file` 存在且转录 mtime 落在**新鲜窗口**内）时，**不采信 `stopped`**，标记为 **contradiction**（可疑 stopped / 疑似仍活），有效态视为 reachable/active。
  - **新鲜窗口的判定**（复用 §2.2 已实证的 mtime 探针，Claude Code 与 Codex 同）：`stat` 该 `session_file` 的 mtime，满足任一即算「新鲜、与 stopped 矛盾」——(a) mtime 距今 < idle 阈值（转录近期仍在逐轮 append）；(b) mtime **晚于**该 `stopped` 写入时记录的 `last_seen`（容小段文件系统时钟偏移）——即「声明停后转录还在写」。`session_file` 不可读时退用 `last_seen`（较粗），无矛盾证据可判则回落到 stopped。
  - **判据 (a) 的预期短暂误报窗（须知，免得读者惊讶）**：刚**干净 teardown** 的会话，末轮留下的 mtime 在其后一个 idle 窗口内仍是「近期」——此时「末轮遗留的新鲜 mtime」与「仍在 append」不可区分，判据 (a) 会把这个**真已结束**的会话误判为 contradiction。这是预期的**短暂误报窗**，危害低：越过 idle 阈值后 mtime 停跳、判据 (a) 不再命中，有效态自愈回落到 stopped；期间保守视为 reachable/active、不 GC，也只是延后清理而非误删。判据 (b)（mtime 晚于 stopped 的 `last_seen`）才是**精确**的范畴错误探测器——只在「声明停后转录确实又写了」时命中，无此误报窗。
  - **mtime 推进不区分「活会话自写」与「外部 headless 触达」⇒ contradiction 是弱信号**：外部 `codex exec resume` / `claude -p --resume` 触达目标会话，同样会**推进其 `session_file` mtime**（那是投递方写进对方 transcript 的字节）。于是一个**真已停止**、并无活会话的条目，会因被外部触达而命中判据 (b)、被判成 contradiction。**实测（上游 gardener 于本仓复现）**：某声明 `stopped` 的 leaf 在数日后被外部 `codex exec resume` 触达，其 transcript mtime 随即前移到当日 → 触发 contradiction，但该会话并未复活。
    - 故 contradiction 应读作「**声明与文件证据不一致，需复核**」，**不是**「仍活」的确证——连判据 (b) 也只精确探测「声明停后转录又被写」，**不区分写入者**。
    - 复核动作：查**增长内容的性质**——是活会话自身的轮次（用户/助手交替、工具调用），还是**外部注入的信封 / headless 一次性回应**（后者常表现为孤立的注入消息 + 无后续交互）。后者 ⇒ 判定为「已停止 + 被外部触达」，而非疑似仍活。
    - 原约束不变：**复核前不得据此 GC**（弱信号不能反向变成删除许可）。
  - **对 reader / gardener 的约束**：contradiction 条目**不得据以 GC**，gardener 须先复核（如经 §3 末通道触达 owner、或等新鲜窗口过后 mtime 停跳再判）；validator 应把该不一致叶子报出；owner（本人）下一个可信触点以 heartbeat 修复（改回 `active` 并刷 `last_seen`）。参见 [ADR-0002](./decisions/0002-agenttui-declared-derived-state-model.md) Amendment。
- **GC 保守原则**：gardener 清理的是**注册表条目，不是会话**；条目可由本人随时重建，误删无害——但仍应保守（只 GC 超 stale 阈值者），避免把仍活跃的同伴从发现视野里抹掉。
- **Human-direct 豁免**：由 human 直接启动、且不需要被其他 AgentTUI 发现或路由的 **human-direct harness** 会话不属于注册对象。它们 **must not be reported as unregistered**，也不得因为没有 `spec.json` 被 validator 或 gardener GC 当作残缺注册项。会话一旦要参与 A2A 发现或路由，豁免即结束，并须按 actual runtime brand 自登记。

**跨 session 触达（三通道 + 记录⊥送达正交）**：`session_id` 是触达句柄。跨 session 通信有**三个通道**（user 定义 2026-07-23）：

| 通道 | 定义 |
|---|---|
| **① 直投** | `claude -p --resume <session_id> "<msg>"`——**不论对方活性**（对活 session 注入受支持，见 [ADR-0003](./decisions/0003-cross-session-reach-semantics.md) Amendment）。向其 `.jsonl` **追加**消息（实测 append 非 fork、携带完整历史上下文）；异步单向、无原生回执 |
| **② 写信 / sendbox** | 定向信落 sendbox（见 [sendbox](./sendbox.md)）/ Agent Teams mailbox——产生 outlive 会话、可审计、可 HITL 的**信物（记录）** |
| **③ 用户投** | 用户亲自把 prompt 发给目标 session——**仅当用户明确说「给我 prompt 我去说」之类**才用；缺省不选它 |

**选择规则（记录与送达两轴正交，不是二选一）**：
- **记录轴（是否需要信物）**：**durable 承诺级**（handoff / decisions / plan-ready / 交付 done）→ **必写信**（信 = 记录 / 信物；为 outlive 会话、可审计、落定前 HITL）；**瞬态 chatter**（催活 / 问答 / 通知 / ack）→ 无需写信。
- **送达轴（怎么送达 / 提醒）**：**直投**是送达提醒，由发送方自定——**写信不排斥同时直投，直投也不豁免写信**（内容 durable 时）。
- 故：durable = 写信（必）+ 直投（可选，作送达提醒）〔或 ③ 用户投〕；瞬态 = 直投即可（无需写信）〔或 ③〕。
- 用户说「你告诉 xxx 去做什么」= 一条**直投**指令；其内容若 durable，则成为**信 + 直投**。只有用户明确要 prompt 时才是 **③ 用户投**。
- 活性探针的剩余价值：预估对方多快看到 + gardener GC，**不再决定通道**。

- **单向、无原生回执**：`--resume` 是「投递并让对方处理」，`-p` 回复走**调用方 stdout**、不进对方 TUI；要双向 / 等回复需外层协调（sendbox 回信 / mailbox / 轮询）。
- **NOTE（机制事实，非禁令）**：即便对方是活 TUI，`-p --resume` 的回复仍返回**调用方 stdout**，对方的活 TUI 界面上**不会可见地弹出**这条注入 / 回复；这只是回执机制的客观描述，不构成对活 peer 注入的禁止。
- **Agent Teams mailbox**（`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`，`~/.claude/teams/<team>/inboxes/<agent>.json`）是原生结构化 A2A，但实验性 + 限 team 范畴、非任意 session 对投；作可选增强，非本表依赖。
- **lookup 定位（已回填 2026-07-29；实测来自一个 adopter 实例的 dogfood 巡检，上游 gardener 未独立复现）**——原「疑似须在原 session 创建目录内执行、跨目录行为未实证」按 brand 拆开定论：
  - **Codex**：`codex exec resume <session_id>` **跨目录可行**——不必在原 session 的创建目录内执行（rollout 按全局 `~/.codex/sessions/` 定位）。
  - **Claude Code**：`claude --resume`（含 `-p --resume`）**跨目录必失败**——必须在**目标项目目录**（原 session 的项目根或其 worktree）内执行才能定位 `.jsonl`（会话文件按 munged 项目路径分目录存放，见 §2.2）。
  - **对调用方的硬要求**：跨项目直投 Claude Code 会话前必须先切到目标项目路径——注册表 `spec.project.path` 正是为此而存。省掉这步会得「resume 找不到 session」的失败，**而非**「目标不存在」。
- **实测边界**：append-非-fork + 上下文携带已由 gardener 在一次性 session 实证（见 [ADR 0003](./decisions/0003-cross-session-reach-semantics.md)）。早期版本曾因「活-TUI 并发 resume 未实证」对活 peer 采保守「不注入」规则；**已更正**——对活 session 的 `--resume` 注入受支持（user 决定 2026-07-23，ADR-0003 Amendment），通道选择改按三通道 + 记录⊥送达正交模型（上表）。

**投递契约（规范性 · 任何活 pane 投递 adapter 必须满足 · 权威见 [ADR-0007](./decisions/0007-agenttui-delivery-contract-pluggable-adapter.md)）**：往活 pane 注入字节把消息送进对方 transcript，是通道①之外**送达侧新增的一类更可靠选项**（记录⊥送达正交不变：durable 内容仍必留信）。core 只规定以下契约、保持 transport 中立；具体终端复用器（zellij 等）与字节注入实现是 **opt-in 参考 adapter，不在 core**。任何投递 adapter 必须满足：

1. **brand + 活性感知的 submit 路由**：活性取自 §3 读时派生态（contradiction 按活跃处理）。
   - 有效**活跃** + `brand=codex` → 写入信封后**发一次 Tab（byte `9`）入队**到下一 turn，**不 steer** 当前 turn（让当前 turn 先跑完，防外部 agent 把决策注入到实现进行到一半之中）；
   - **空闲 Codex** → 发 **Enter（byte `13`）** 提交；
   - **Claude Code** → **不分活性一律 Enter 提交**。**为何不照搬 Codex 的 Tab**（#12 官方补充裁定）：Claude Code 官方 keybinding 只有 `chat:submit`=Enter，其 Tab 用于 autocomplete / tab 导航，**没有 Codex-Tab 那样的独立「入队到下一 turn」动作**；目标忙碌时由 **Claude Code 自身的 receiver-side queue** 在当前 turn 跑完后处理，故活跃/空闲都用 Enter。**⚠️ 勿给 Claude Code 套用 Codex 的 Tab**——那会落进 autocomplete/导航语义、不入队提交，是误改。
   - 与 [ADR-0006](./decisions/0006-runtime-brand-is-routing-authority.md) 一致：submit-key 路由本身即 brand-keyed，是「按实际 brand 路由」在投递维度的延伸。
2. **不盲目重发入队键**：送达未观测到时**不得**重发 Tab——盲目重发会入队重复信封。
3. **送达证据必须 message-specific（fail-closed，绝不假阳性）**：每次发送生成**唯一 nonce** 写入信封；注入前记录目标 transcript 的**位置指纹 = inode + size**（不是裸字节偏移）。验证时分两路，并**显式标注证据等级**：
   - 指纹**可核对**（inode 未变、size 未缩小）→ 在字节边界**之后**搜 nonce，命中即 `delivered`，证据等级 `evidence=envelope-nonce-found-after-boundary`（强）。
   - 指纹**不匹配**（inode 变 / size 变小 / 无法核对）⇒ 目标会话文件**被重写**，字节偏移不再对应「投递后新增」→ **降级为全文件 nonce 搜索**，命中即 `delivered`，证据等级 `evidence=envelope-nonce-found-fullfile`（弱于 after-boundary，但**仍是送达证据**）；**不得**因指纹不匹配就直接返回 `queued-unverified`。
   - **「transcript 单调 append」不是可依赖的不变量**：Claude Code 的 **compact / rollout 重写**会原地重写会话文件。**实测**（一个 adopter 实例的 dogfood 巡检；上游 gardener 未独立复现）：一次投递后全文件 grep 到该 nonce 多次、目标输入框已清空（**确实送达**），但按边界做 `tail -c +N` 检测得 **0 次**——目标刚做过 compact、文件被重写。裸边界检测在此产生**假阴性**（实为送达、判为未送达），而假阴性会让调用方据 `queued-unverified` **重发** ⇒ **重复投递**，正是规则 2 要防的事。
   - **为何全文搜索不构成假阳性（须论证，别当例外网开一面）**：nonce 是 **per-send 唯一**的，只可能由本次发送写入 ⇒ 全文命中 ⇒ 本次信封确实进了对方 transcript。字节边界原本防的是「把历史里的旧 marker 当本次送达」——**唯一 nonce 已在源头排除该情形**，故边界只是**证据强度的加成**，不是防假阳性的必要条件。（推论：若某 adapter 用**可复用的固定 marker** 而非唯一 nonce，则全文降级对它**不成立**，必须留在边界路。）
   - 仍然：pane 命令成功 / pane 存在 / 转录 size 增长 / mtime 变化**都不是**送达证据（忙碌目标会自行增长转录）；**peer 回复是唯一的语义 ACK**。
4. **fail-closed**：未验证即 `queued-unverified`，绝不当 `delivered`。「未验证」= **两路都没搜到 nonce**（含降级后的全文搜索），不是「指纹核不上」。
5. **pane 存在性 preflight 必须选「对不存在的 pane 会明确报错」的探针，且按 **stdout 与 stderr 合并文本**判定**（诊断文本可能只出现在 stderr——zellij 实测即如此；transport 中立表述；zellij 侧的具体裁定见下「参考 adapter」段）：**禁用**「对不存在的 pane 静默返回空」的读屏类命令作存在性判据（会得**假阳性**：把不存在的 pane 认作存在）；且**不得把退出码当作成功依据**——复用器可能对「pane 不存在」也返回 rc=0（zellij 六格实测里四格如此）。反向也不成立：探针对不存在的 pane 可能返回非零，但**不得**据此把非零当拒绝依据，见下「参考 adapter」段那条未解决矛盾。存在性 preflight 只解决**寻址**，本身**不是**送达证据（规则 3 不变）。
   - **「按合并文本判定、不靠 rc」不只适用于探针，也适用于注入与提交命令本身**：复用器对「目标 session 名不存在」也可能 **rc=0，而说明只出现在 stderr（stdout 里甚至装的是正常内容，如 session 列表）**（实测文本见下「参考 adapter」段的 zellij 裁定）。⇒ 调用方若按 `$?` 判成功，会把「整条命令打进虚空」读成「已发出」。
   - **最坏情形：连 stdout 判定都救不了** —— **session 存在、但 pane 不存在**时，注入命令可能 **rc=0 且 stdout 与 stderr 两条流全空**（zellij 实测，见下）。这一格没有任何事后文本可依据。⇒ **本规则的存在性 preflight 不是优化，而是唯一能在注入前发现该情形的手段**（会报错的探针至少会打印 not found）；一旦注入已经发出，唯一判据只剩规则 3 的**送达证据（nonce）**。
   - **本规则只管 pane 存在性，不覆盖「`pane_ref.session` 腐烂」**：复用器 session **改名**后，据启动时环境快照推断出的 `pane_ref.session` 即失效（复用器把 session 名注入子进程环境时是**启动时快照**，改名不回写已运行的进程），且因上一条会**静默成功**——信封喷进虚空。故**换复用器或改名后，所有既有 `pane_ref` 必须整条重建，不能只改 `multiplexer` 字段**。（证据等级：**下游实测，上游未独立复现**。）
6. **发送侧能力检查（发之前先问「我投得进去吗」）**：发送方必须校验**本次路由实际要用的**那条投递能力**现在还在**——**走 pane 就校验 pane 侧能力（复用器 CLI + 目标 pane 存在，按规则 5），走 resume 才校验 resume 侧 CLI**；不得为了「看起来更严格」去校验本次不用的能力（那只会在无关缺失时误拒）。
   - 校验不过、或**推不出任何可用的 operational 路由** ⇒ 报 **`no-operational-route`** 且**非零退出**。
   - **`no-operational-route` 与规则 3 的 `queued-unverified` 语义必须分开**：前者是「**没发出去**」（发送侧前提不成立，重试是安全且必要的），后者是「**发了但没验到**」（可能已送达，盲目重发会重复入队，见规则 2）。把二者混成一个状态，调用方就无法判断该不该重发。
   - **禁止静默回落到 `claude -p --resume`**：pane 路由不可用时悄悄改走 resume，会把「定向注入到活 TUI」换成「往会话文件追加、回复走调用方 stdout、对方界面上看不见」（§3 末 NOTE），且**代价与语义都变了却没人被告知**。要走 resume 必须是**显式选择**（调用方指定或配置声明），不是失败兜底。
   - **对称性论证（这是补对称，不是新原则）**：adapter 对 codex 分支**早已**明确拒绝——活 Codex TUI 而无 `pane_ref` 时直接报错，不去猜一条更差的路；而 claude-code 分支在同样处境下却**静默**回落 `claude -p --resume`。同一处境、两个 brand 两种行为，本规则把 claude-code 拉回与 codex 一致的 fail-closed 形状。

**投递前置校验（统一契约：动手前先验前提，验不过就拒绝，不猜、不静默降级）**：上面规则 5/6 各管一半前提；两半共用**同一形状**，故在此收成**一条**契约，避免各处再写各自的临时门。

| 半边 | 问题 | 硬规则 | 拒绝时 |
|---|---|---|---|
| **路径推导** | 「我该往哪写？」 | 由脚本位置反推仓根（`__file__` 上溯 N 级那一族做法）**必须校验推导结果真是项目仓**——目标目录须含 `.trellis/` 或 `.git/`。推不出、或推出来的不是项目仓 ⇒ 拒绝；**绝不 `mkdir` 造一个假注册表**（`mkdir -p` 恰好会把错位置造得「像是本来就有」）。自登记时目标 `.arborist/` 不存在的处置**不在此复述**，见 §5 第 8 点（fail-closed 报 `half-registered`、不得静默上移父目录）。 | 非零退出 + 明确说出「推导出的路径不是项目仓」 |
| **路由推导** | 「我投得进去吗？」 | 推不出可达路由即 fail-closed（规则 6）；pane 存在性用**会报错**的探针并**解析 stdout+stderr 合并文本**（规则 5），禁用「对不存在 pane 静默返回空 + rc=0」的读屏类命令；**路由与传输必须分层**——preflight 与路由判据定义在「**本次路由所需能力**」这一抽象层上，**不得**把某个具体复用器的名字/命令硬编进路由判定（那样每换一次复用器都要改路由代码，而契约本该只换 adapter）。 | `no-operational-route` + 非零退出（**≠** `queued-unverified`）|

- **两半均已在随发 adapter 落地**（2026-07-30；此前为「规范已落、实现未收敛」）：`scripts/agenttui.py` ①推导出的仓根须含 `.trellis/` 或 `.git/`，否则非零退出拒绝（且**不创建**任何目录），可用 `--repo` 显式指定；②路由改为**能力层**判定——`build_route` 只问「这个 `pane_ref` 有无已注册 transport / 该 transport 可用吗 / 目标 pane 存在吗」，具体复用器命令收在 `PaneTransport` 子类里，复用器名→transport 的映射只在一处注册表；③有发送侧能力检查与 `no-operational-route`（非零退出）。**仍有未实现项**（规则 3 的双指纹/证据等级），逐条见下「随发 adapter 的契约缺口」。

- **参考 adapter（随发 · opt-in · 二选一别混）**：
  - `scripts/agenttui.py`（adopt 铺到 `<repo>/.trellis/scripts/`）是本契约的 **operational 参考实现**——按注册表 `pane_ref` 经 **transport 抽象**寻址注入（随发只注册了 zellij 一个 transport，其 `write-chars --pane-id` 细节在该 transport 内部）；调用见工具表条目 `agenttui-direct`（`python3 .trellis/scripts/agenttui.py {status|send|heartbeat|stop}`，发前可 `--dry-run` 验路由——dry-run **不跑**存在性探针，因为探针会抢焦点）。**operational 投递一律走它**（而非下面那个演示脚本）。
    - **调用方须知的两处行为**（按规则 6 落地，非默认兜底）：①目标无可达 pane 时**不再**自动改走 `claude -p --resume`——要走 resume 必须显式加 `--allow-resume`，否则报 `no-operational-route` 并**非零退出**；②`no-operational-route` 的结构化输出带 `reason` / `detail` / `remedy` / `sent=false` / `retry_safe=true`，与 `queued-unverified`（`sent=true` / `retry_safe=false`）**字面区分**——照它判断该不该重发。
    - **⚠️ 它仍未满足契约全部条款**——剩余缺口逐条列在下方「随发 adapter 的契约缺口」，别读成「已满足全部契约」。
  - **`--pane-id` 寻址不免除聚焦（已据实更正）**：本段早前写作「**定向注入**（不靠焦点）」，**那是错的**。**实测**（一个 adopter 实例的 dogfood 巡检；上游 gardener 未独立复现）：`zellij action write-chars --pane-id <目标 pane>` **跨 tab 不生效**，跨 tab 投递必须先 `zellij action focus-pane-id <目标 pane>` 把焦点移过去。
    - **后果 = 一条已知架构局限**：投递因此会**抢焦点**，与「人类正在同一 zellij session 里操作（切 tab / 移焦点）」**结构性冲突**——人类的一次切 tab 就能让并发投递投错或被打断。本 guide **只记录该局限**，不承诺任何具体替代方案；终端复用器的选择**正在评估**（core 仍 transport 中立，见 [ADR-0007](./decisions/0007-agenttui-delivery-contract-pluggable-adapter.md) Amendment）。
    - 规避（当前唯一诚实建议）：跨 tab 投递期间避免人机同时操作同一 session；或把被投递的 AgentTUI 放在人类不手动切换的 session/tab 里。
  - **zellij 侧读数总表（对应契约规则 5）——附原始读数，勿只记结论**。下表每格都是同一版本（`zellij 0.44.3`）上的直接观测，**rc / stdout / stderr 三者分开记**：

    | 命令与情形 | rc | stdout | stderr |
    |---|---|---|---|
    | `action dump-screen -p … --pane-id <不存在>` | `0` | **空** | 空 |
    | `action focus-pane-id <不存在>` | **`2`** | **空** | `Pane with id Terminal(<N>) not found` |
    | `action focus-pane-id <存在、且当前已聚焦>` | **`2`** | **空** | `Pane Terminal(<N>) is already focused` |
    | `action focus-pane-id <存在、未聚焦>`（聚焦真的发生了）| `0` | 空 | 空 |
    | `action write-chars --pane-id … `（**session 不存在**）| `0` | **session 列表**（不是错误信息）| `Session '<name>' not found. The following sessions are active:` |
    | `action write --pane-id … <byte>`（**session 不存在**）| `0` | 同上 | 同上 |
    | `action write-chars --pane-id <不存在>`（session 存在）| `0` | **空** | **空** |
    | `action write --pane-id <不存在> <byte>`（session 存在）| `0` | **空** | **空** |

    由此得到三条**替代此前表述**的结论：
    1. **`dump-screen` 仍然禁用**作存在性判据（rc=0 + 空 = 假阳性），未变。
    2. **`focus-pane-id` 对不存在的 pane 是 `rc=2`，且诊断文本在 `stderr`**。⇒ 此前写的「它 rc 也是 0 ⇒ 必须解析 stdout」**两处都错**：rc 不是 0，文本也不在 stdout。正确表述是**判据须合并 `stdout` + `stderr` 文本**（随发 adapter 一直是这么做的，故功能未受影响，是**文档错、实现对**）。
    3. **注入与提交命令的 rc 确实不可信**（六格里四格是 rc=0 而实际失败），这一条**成立且未变**；但「按 stdout 判」应收窄为「按 stdout+stderr 合并文本判」——session 不存在时 stdout 里装的是 session 列表，只看 stdout 会把列表当成正常输出。
    4. **最坏那格仍然无解且更彻底**：session 在、pane 不在时，注入与提交都是 **rc=0 且两条流全空**。这一格正是「存在性 preflight 是唯一事前手段、nonce 是唯一事后判据」的来源。

    > **`rc=2` 的真正含义（此前被记为「一处未解决矛盾」，现已实测解决）**：两份独立报告曾对「已聚焦的 pane」给出 `rc=0`+空 与 `rc=2`+`already focused` 两个读数。本仓对**自己占用的 pane** 直接实测，得到 **`rc=2` + stderr `Pane Terminal(<N>) is already focused`**，重复两次一致。
    >
    > ⚠️ **本节此前有一句错的理由，一并更正**：这次测量当时的说法是「对自己占用的 pane 测**不抢任何人的焦点**，所以这一格本来就可测」。**那个推理是错的**，它把「我这个进程跑在这个 pane 里」等同于「这个 pane 是客户端的焦点」——**进程所在 ≠ 客户端焦点**。本次之所以确实没抢，只是因为它**恰好**返回了 `rc=2`（目标本来就在焦点上）；若当时返回 `rc=0`，那这条命令就把客户端视图**拽到了**这个 pane 上。⇒ 正确表述是：**事前无法保证不抢，事后由 rc 告知抢没抢**。这条错误的价值大于它的代价——它直接给出了下面那个探测器。
    >
    > ⇒ 两份读数不是矛盾，是**同一条规则的两个分支**：`rc=2` 的含义是「**请求的聚焦变更没有发生**」。而它有**两个性质完全相反**的原因：
    >
    > | rc | stderr | 真实含义 | 对投递意味着 |
    > |---|---|---|---|
    > | `0` | 空 | 聚焦**发生了** | 可投 |
    > | `2` | `… is already focused` | 目标**本来就在焦点上** | **可投**，而且这是 pane **存在**的正面证据 |
    > | `2` | `Pane with id … not found` | 目标**不存在** | **不可投**（`no-operational-route`）|
    >
    > ⇒ **`rc` 单独无法区分「良性的已在那」与「致命的不存在」** —— 这两格 rc 相同、性质相反。这才是「**不得把非零 rc 当拒绝依据**」的实测理由（此前只是因为读数矛盾而保守）。若有人把探针「优化」成按非零 rc 拒绝，会把**最常见**的「目标已聚焦」判成不可达 —— 而那正是一次已验证成功的投递所处的状态。判据必须是**文本**：只有 not-found 类文本才是拒绝依据；`already focused` 属于**通过**。
    >
    > 实现现状与此一致（`ZELLIJ_NOT_FOUND_PATTERNS` 只匹配 not-found 类，`already focused` 不匹配 ⇒ 不拒绝），但这条**过去是隐式的**（靠「不匹配即通过」），现在把它写成显式规则，以免后来者以为那是漏配。
    >
    > 仍未测的条件（留作缺口，需 human 在场，因为测它会切换活动 tab）：**pane 在其所属 tab 内是焦点、但该 tab 不是当前活动 tab**；以及**该 session 无 client attach**。上表 a+b 同时成立那格已测准。

    > **由此得到一个免费的焦点抢夺探测器（已实现）**：既然 `rc=0` 恰恰意味着「聚焦**真的发生了**」，那么探针的 rc **本身就是一个抢焦点探测器**——它无法**事前**预测，但能**事后**如实告知：
    >
    > | 探针读数 | `addressing_intrusion` | 含义 |
    > |---|---|---|
    > | `rc=0` + 空 | `focus-moved` | 这次投递**抢了**焦点（有人的视图被拽走）|
    > | `rc=2` + `already focused` | `already-focused` | 目标本来就在焦点上，**没打扰任何人** |
    > | not-found 类 | **不记值**（`null`）| 什么都没投出去；记成 `none` 会**注水分母**、低估真实抢焦率 |
    > | 其它非零 | `unknown` | **不得**当作「没抢」；未知不得计入良性 |
    >
    > ⇒ adapter 本来就在每次投递前调这条命令，只要把这个读数记进投递结果（已加进结构化输出），就能**统计出抢焦点的实际发生率**：**不需要新实验、不需要 human 在场、不打断任何人。**
    >
    > **它回答的是「侵入性轴」两问里更该先知道的那一问**：它**不能**回答「换复用器能否免于抢焦点」（那仍需在场实验），但它能回答「**抢焦点到底有多频繁、值不值得为它迁移**」。若实测绝大多数投递是 `already-focused`，那迁移的性价比要重估；若绝大多数是 `focus-moved`，迁移提案就有了量化依据。**先有分母，再做实验。**
    >
    > **⚠️ 这个分母有两条会让它系统性低估的陷阱，两条都已在实现里处置**（若不处置，事后补做要**重采数据**）：
    >
    > 1. **测量行为本身改变被测量的量。** 探针**就是**聚焦命令，所以**第一次**投递把 pane 拽到焦点之后，紧接着投向**同一个 pane** 的每一次都必然读到 `already-focused` —— 哪怕第一次刚刚真抢过。⇒ 高频往返（一次真抢 + N 次良性读数）会把比值稀释到接近零：**越是打扰频繁的场景，统计上看起来越干净。** 处置：**只记事件、不记比值** —— 每次投递追加一条事件记录（含时间戳），折叠连发交给分析侧（它能看见事件之间的间隔），脚本内**不计算任何比率**（有测试机械钉住这一点）。
    > 2. **聚合掩盖分层差异。** 抢焦点的危害取决于 human 当时在哪，不取决于聚合比例：投进他正在看的 session/tab 与投进没人看的 pane 是**两类事件**，混成一个比值既说明不了「有多常见」也说明不了「有多严重」。⇒ 处置：每条事件自带分层字段 —— `same_multiplexer_session`、`active_tab_before` / `active_tab_after`、以及**最强打扰信号** `tab_switched`（human 的整个视图换了 tab）。
    >
    > **未知一律记 `null`，绝不记「没发生」**：任一读数取不到 ⇒ `tab_switched: null`（不是 `false`）；探针判不可达 ⇒ **不记 intrusion 值**（什么都没投出去，记成 `already-focused` 会**注水分母**）；不认识的非零读数 ⇒ `unknown`，不并入良性。**缺读数与「没打扰」必须可区分**，否则低估方向是单向的。
    >
    > **测量不得扰动不测量的调用方**：取活动 tab 需多跑一条只读命令，因此它**只在真的要记录时才执行**（per-transport 的 `observe_addressing`，默认关）。这不只是省开销 —— 无条件多跑一条命令会改变**每个**调用方看到的命令序列，那本身就是上面第 1 条的同一个毛病。这条也有回归测试：不记录时命令数必须与加此功能之前一致。
    >
    > **已知缺口（如实记，不编）**：`dump-layout` 给不出 pane→tab 映射，所以「**目标 pane 属于哪个 tab**」无法直接读到；当前用「投递前后的活动 tab 是否变化」作代理指标。它能捕到「切了 tab」这个最强打扰，但**不能**区分「同 tab 内换 pane」与「目标本就在活动 tab 里」。
    > **该缺口影响精度、不影响结论方向，不得为它阻塞**：能测到的恰好是**最强那一格**（切 tab = human 整个视图被换掉），而迁移决策要的正是这一格。⇒ 缺的是「弱打扰内部如何细分」，不是「有没有强打扰」。

    > 附带：仍挂着的那格「pane 在自己 tab 内是焦点、但该 tab 非活动 tab」正好是这个探测器的关键边界——若那格也返回 `rc=0`（即会切 tab），那么「切 tab」这种**更强**的打断会被同一个计数器一并捕获，无需另立指标。

    > **采集纪律：合并流的诊断会让流归属不可观测。** 上面那处「诊断在 stderr 不在 stdout」之所以长期没被发现，是因为采集时用了 `2>&1` **把两条流合并**——于是「这段文本属于哪条流」这个区分在读数里**结构上不可见**。持有原始数据却看不见它。⇒ 凡**要据某条流做判定**的实测，采集时**两条流必须分开记录**（分别跑一次 `2>/dev/null` 与 `2>&1 >/dev/null`，或分别重定向到两个文件）。合并流只适合「看看它说了什么」，不适合作为判据来源。

    > **证据标签授予纪律（本节自身就是反例）**：上面被更正的那条，此前挂的是本仓最强的证据标签「**已独立复现**」——而它错了两处。⇒ **授予「已独立复现」必须附原始读数（命令 + rc + stdout 原文 + stderr 原文）；只有结论没有读数的，只能标「已声称复现」。** 理由不是形式主义：同版本、同命令，两个报告都能给出不同的 rc（见上方矛盾），**只标版本救不了，只有原始读数能交叉核验**。证据分级只在标签授予纪律可信时才有意义。
    - 关联：`pane_ref.session` 会因 zellij session **改名**而腐烂——`ZELLIJ_SESSION_NAME` 是**启动时快照**、不回写已运行的进程，故据它推断的 `pane_ref.session` 改名后失效，并落进第一格**静默成功**（证据等级：**下游实测，上游未独立复现**）。规则 5 只管 pane 存在性、**不覆盖这一类**；改名或换复用器后 `pane_ref` 必须整条重建。
  - `scripts/agenttui_deliver_zellij.py` 是**契约的 seam 化演示，非 operational**：默认注入器**收 `pane_ref` 却不定向、只写当前焦点 pane**，跨 session / 跨 brand（目标 pane ≠ 焦点 pane）必投错——**未补 `--pane-id` 前不得当跨 pane operational 路**（下游把它误当正道，正是跨 brand 发信「表现不佳 / 不稳定」的根因）。
- **⚠️ 随发 adapter 的契约缺口（截至 2026-07-30，必须可见——契约不得被读成「代码已做到」）**：随发 `scripts/agenttui.py` **尚未**实现下列契约条款，port 任务另行追踪；在它补齐前，调用方须自行承担对应风险：
  - **规则 3 的 inode+size 双指纹与全文降级**：**仍未实现**——只记 size 作起始偏移，且当**现 size 小于该偏移**（= 文件被重写/截短）时**直接判未命中** ⇒ 目标做过 compact / 会话文件被重写时返回**假阴性** `queued-unverified`（重发风险，见规则 2）。
  - **规则 3 的证据等级标注**：**仍未实现**——命中只记单一 `envelope-nonce-found`，不区分 `…-after-boundary` / `…-fullfile`，调用方读不出证据强度。
  规范先于实现落定是**刻意**的（契约是判据、实现向它收敛）；但**凡未实现处必须像这样逐条标注**，不得笼统写成「参考 adapter 已满足上述契约」。
- **✅ 已收敛的条目（2026-07-30 实现，本清单据实改写；留档以便对照上面那两条仍缺的）**——同时列出**实现带来的已知代价**，别读成「无副作用」：
  - **规则 5 的存在性 preflight（解析合并文本）**：已实现——注入前用 `focus-pane-id` 探针并**按 stdout+stderr 合并文本**判 `Pane with id … not found` / `Session '…' not found`，**不把退出码当成功或拒绝依据**（原因见上方未解决矛盾）；探针失败即 `no-operational-route`、**零注入命令**。**禁用** `dump-screen -p`（对不存在 pane 静默返回空 + rc=0）作判据。
  - **`--pane-id` 前置 `focus-pane-id` 聚焦**：已实现，且**与上一条是同一个命令**——存在性探针本身就是聚焦命令，故跨 tab 投递前焦点必然已移到目标 pane。**代价照旧**：投递**抢焦点**，与人类同 session 操作结构性冲突（上文「已知架构局限」，未消除）；`--dry-run` 因此**不跑**探针（也就不做该次校验），输出里如实标注。
  - **规则 5 的「注入/提交命令也按 stdout 判定」**：已实现——注入与提交命令都按 stdout/stderr 文本判失败，退出码不作成功证据。**但最坏那格无解**：session 在、pane 不在时注入是 rc=0 + 两条流全空 ⇒ 代码**不得**据此判成功，判据只剩规则 3 的 nonce（提交命令被文本判失败时，因字节已发出，报 `queued-unverified` 而非 `no-operational-route`）。
  - **规则 6 的发送侧能力检查 + `no-operational-route`**：已实现——只校验**本次路由用得到**的能力（走 pane 校验 transport 可用 + pane 存在；走 resume 才 `which` 对应 resume CLI），无可用 operational 路由 ⇒ `no-operational-route` + 非零退出；claude-code 分支**不再静默回落** resume（与 codex 分支同形拒绝），resume 须 `--allow-resume` 显式选择。
  - **「投递前置校验」两半**：已实现——路径推导侧见上（仓根须含 `.trellis/` 或 `.git/`，拒绝时不创建任何目录）；路由推导侧改为能力层判定，具体复用器命令封在 transport 子类内、映射集中在一处注册表，故换复用器只加 transport、契约与路由代码不动。
- **五种「注册表看不出来的投不进 / 投不对」（全部已实测 · 一致性 validator 也查不出 · 别指望注册表告诉你 · 覆盖度的如实表述见本条末，勿写成「病因已覆盖」）**：注册表一致性（§2.2.1 / §4）能排除**归属错**与**寻址错**，但下面这些形态在注册表里**一模一样**——`state=active`、`pane_ref` 有效、`session_file` mtime 新鲜、一致性检查全绿——投递却到不了目的地，或**到了但不是你想说的话**：

  **读表前必读 —— 分类的输入是「可观察签名」，不是底层病因。** 任何分类器（人或代码）**看不见**目标的鉴权状态、看不见沙箱边界、看不见 composer 内部；它只看见三类签名：**屏幕形态**（读屏文本）、**写入/提交命令的 stdout**、**transcript 里有无越界 nonce**。下表末二列正是照这条区分开的：能不能造出**签名**（可以，五格都能）与「该签名是否**只可能**由这一格的病因产生」（多数**未证明**）是两件事。

  | # | 形态 | 失败发生在哪一侧 | 读数 | 唯一可用判据 | 换终端复用器能否解决**本格的送达失败** | 签名 fixture 可复现？ | 签名→病因 映射独占性 |
  |---|---|---|---|---|---|---|---|
  | 1 | **沙箱半聋**（能被投、自己**发不出**；默认沙箱隔离复用器 unix socket）| **发送侧**（本机环境）| `no-operational-route` 或注入无声无效 | 发送侧能力检查（规则 6）；出向单测 | **不能**——tmux 同样靠 unix socket，须靠 bypass 启动约定 | ✅ 不带 bypass 起一个会话；或单测经 seam 注入「复用器不可用」 | **假定** |
  | 2 | **认证失效**（字节收到、提交键也生效，目标 CLI 无法处理：屏幕上是 token 刷新失败 / 要求重新登录；**transcript 永无痕迹**）| **接收侧**（目标 CLI 层，消息从未进会话）| `queued-unverified` | **读屏**（见下 `dump-screen`）——transcript 上永远看不到 | **不能**——与传输无关 | ✅ 往测试 pane 注入**伪造的**该错误文本。**注意它测的是「认不认得这个屏幕形态」，不是鉴权本身** | **假定** |
  | 3 | **长文本损坏 + 未提交**（文本到了 composer 但被**截断/丢字符**，且**未入队**）| **传输侧 → 接收侧 composer** | `queued-unverified` | **读屏**（唯一能看到「被截断」的手段）| **不能**——对因修法在写入方式（bracketed-paste 一次性写入）与投递形态（短指针，见下），不在复用器选择上 | ✅ 写入文本**而不发提交键** | **假定** |
  | 4 | **delivered-but-verified-too-early**（其实**成功了**：nonce 确实在目标 transcript 里，只是 verify 窗口跑在目标 CLI 落盘之前）| **验证侧**（既非传输也非接收故障）| `queued-unverified`（**假阴性**）| 事后重搜 nonce（放宽窗口后即命中）| **不能**——是时序问题 | ✅ 把验证窗口调小；或让 fake transcript 在窗口**后期**才写入 nonce | **假定** |
  | 5 | **构造侧内容损坏**（信封在**离开发送方之前**就已缺字）| **构造侧**（发送方自己）| **完全的绿**：投递成功、nonce 越界命中、所有门全绿 | 发送前对信封**自校验**（回读比对）或结构性禁用会触发替换的引用形式；**投递侧任何探测都测不到** | **不能**——与传输选择完全无关 | ✅ 平凡（构造一条会被替换吞字的信封） | **已证明**——回读比对**直接**判定「正文与源不一致」，不依赖排除法 |
  | — | **`unclassified`（必须保留的一格）** | 未知 | 任意 | **签名不匹配任何已知形态** ⇒ 落这一格 | 不适用 | 不适用（它就是「都不匹配」）| 不适用 |

  > **为什么 `unclassified` 是硬要求**：**没有这一格，分类器会被迫把新病因塞进最像的已知格里**——那不是分类，是掩盖。本轮已经**两次**证明这件事会发生：形态数从三扩到五，两个新格（验证太早、构造侧损坏）在被发现前，其签名都曾被归进已有的解释里（前者被读成「目标在排队」，后者干脆全绿无人怀疑）。⇒ 落 `unclassified` 是**正当结论**，不是失败；把它硬塞进第 1–5 格才是。

  > **`unclassified` 必须捕获原始签名，只计数的桶是装饰**：一个只 `+1` 的 `unclassified` 桶，和「没有执行者的门」是同一个东西——数字会涨，但没有人因此学到第六种形态是什么。⇒ **每一次落 `unclassified` 都必须当场捕获并持久化完整原始签名**：读屏全文、写入与提交两个命令的 stdout 原文、transcript 越界检查的原始读数、时间戳、目标标识；落成 durable 文件，**不是只加一个计数**。
  >
  > 理由是一次真实的侥幸：本轮之所以能把两条失败分成两种形态，靠的是「之前几次尝试的痕迹**还留在屏幕上**」——那是运气，不是机制。屏幕会滚走、容器会销毁、pane 会被复用；**新病因的原始材料只在它发生的那一刻存在，事后无法补采。** ⇒ 捕获必须与发生**同步**，否则第六格永远只能等下一次侥幸。
  >
  > 推论：既然完备性假设已被推翻两次，就该**预期它会被推翻第三次**。`unclassified` 的原始签名档案的价值**不在当下分类**，在**下一次扩格**——它是唯一能让第三次比前两次更快被识别的东西。

  > **判定顺序：逻辑上独占的判据放最前，靠排除法的放最后**（降低暴露面，不解决独占性本身）。构造侧回读比对是唯一**不依赖排除法**的判据，应最先跑；`假定` 独占的分支放后面。这样最弱的推断只在最强的都失败后才运行，且一旦前面命中，后面依赖完备性假设的分支**根本不会被执行**。

  > **⚠️ 四格的独占性是「假定」，不是「已证明」**：独占性（这个签名**只可能**由这一格的病因产生）建立在「**已知病因集合完备**」这个假设上，而该假设在本轮**被推翻过两次**（三格 → 五格）。⇒ 第 1–4 格的映射标 `假定`：签名匹配只说明「与该形态一致」，**不构成**「病因即此」。要把某格升为 `已证明`，得给它一条**像形态 5 那样直接判定**的判据（不依赖排除法）。

  > **⚠️ 末列只管一条轴，别把它读成对复用器选择的结论。** 末列问的是**可靠性轴**（送达成不成），这一轴上五格**零格**要求换复用器。但复用器选择的剩余候选价值落在**另一条轴 —— 侵入性轴**（送达要付什么代价）：本仓另有一条**独立实测尚未被推翻**——定向写入**跨 tab 不生效、必须先抢焦点**（见下「`--pane-id` 寻址不免除聚焦」），而抢焦点会**打断正在同一复用器里工作的人类**。这是一个真实成本，且**任何投递侧修法都不碰它**（上文那次成功的投递同样是先聚焦的，故这条未被该实测触及）。⇒ **不得**据本表得出「换复用器已被证据否掉」的结论；两条轴合成一列，会让一个真实成本从账上消失。

  - **形态 2 的触发模式常量单独标 provenance（`provenance: single-observation`）**：用来识别该屏幕形态的那段文本模式（屏上的重新登录 / token 刷新失败提示）**只来自单次观察**——不是穷举过该 CLI 各版本各语言各种失败提示的结果。⇒ 它的**证据等级低于该形态本身**（形态确实发生过；模式常量只见过一次长什么样），二者必须分开记，否则会把「见过一次的字符串」当成稳定契约。
    - **匹配失败时的行为（fail-closed，硬规则）**：屏幕内容**不匹配**该模式时，**必须降级为 `unclassified`**，**不得归入最近的一格**。理由与上条同：模式常量既然只有单次观察，那么「不匹配」的最可能原因是**模式不全**，而不是「病因不是这个」；此时按相似度就近归类会**凭一个未验证的常量**给出一个确定的错误结论。
    - 推论：这段模式常量属**实现**（投递 adapter 的分类器），随观察增加而更新；每次扩充都应记下新观察的出处，别让它悄悄从 `single-observation` 变成看不出出处的「魔法字符串」。
  - **形态 1–3 同一读数、修法完全不同**：规则 3 的 nonce 判据对它们给出**同一个** `queued-unverified`（形态 2 的字节从未进 transcript、形态 3 的信封不完整或未提交，都搜不到 nonce）。⇒ `queued-unverified` **不是**可直接据以重发的诊断结论，它只是「没验到」；重发对形态 1/2 无效（发送端或认证坏了，重发多少次都一样），对形态 3 也未必有效。别把它当成「网络抖了一下、再发一次就好」。
  - **形态 4 的详情与后果（已实测：一次真实同仓投递，目标 brand=`claude-code`）**：目标 transcript 里 nonce **确实存在**（`type=user` 的一条记录），但当次 verify 窗口是 `PANE_VERIFY_ATTEMPTS=10 × PANE_VERIFY_INTERVAL_SECONDS=0.1` ⇒ **总窗口仅 1 秒**，grep 在目标 CLI 落盘**之前**就跑完了，于是返回 `queued-unverified`。
    - **它会污染前三种病因的样本集**：任何「投递失败率」统计都被它**抬高**，而它**根本不是失败**。⇒ 统计投递可靠性前必须先把这一格排除（对每个 `queued-unverified` 事后重搜一次 nonce），否则会给一个不存在的问题分配工时，并把真正的形态 1/2/3 稀释掉。
    - **这类假阴性最危险的地方不是抬高统计，而是它自带一个听起来合理的现成解释，于是没有人会去查。** 同一批实测里，另一个目标的 `queued-unverified` / `evidence=none` 当时被解释为「目标正在 turn 中、消息躺在接收队列里」——而目标**其实收到了并照办了**。按 1 秒窗的发现，那极可能就是同一个假阴性，而那句「已入队」的解释是**事后编的、且不可证伪**。**一个无法被解释的错误读数会被追查；一个能被解释的错误读数会被归档。**
      - ⇒ **规范要求**：凡读数为「未验证」，处置必须给出**可证伪**的判据——读屏分类（形态 2/3）、越界 nonce 重搜（形态 4）、或目标的**实际行为**（它照办了吗）。**不接受「大概是在排队 / 目标忙」这类不可证伪的叙述**作为结论；它不是诊断，是把一个待查读数关掉。
    - **标定数据（三次独立实例，同一形态）**：三次投递均返回 `queued-unverified` / `evidence=none` 而实际已送达；其中一次精测到真实落盘延迟 **< 5 秒**（5s 时重搜 nonce 已命中，15s/30s 不变）。⇒ 窗口取 **15–30 秒**，并保持**命中即早退**。
    - **⇒ 已修（随发 adapter）**：常数改为**以秒表达的窗口** `PANE_VERIFY_WINDOW_SECONDS`（20s）+ 退避轮询 + 命中即早退；活跃 codex（Tab 入队）单独一档 `PANE_VERIFY_QUEUED_WINDOW_SECONDS`（短），因为按契约它的 nonce 本就要等到 turn 边界之后，等满窗口只是白等。
      - **为什么把总时长写进常数名**：旧形式 `attempts × interval` 把「总窗口是多久」藏在乘法里——**这正是没人注意到它只有 1 秒的原因**。可 grep 到的名字必须自己说明总时长。
      - **方向比数值重要（防止被「让 send 更快返回」优化回去）**：命中即早退 ⇒ 成功路径**不付额外等待**，窗口开大**几乎零代价**；取小的代价是把送达误报成未验证，**并触发一次多余的提交键**（下一条）。⇒ **窗口取大是 fail-safe 方向，取小是 fail-dangerous 方向。**
    - **连带后果（比统计污染更实际，已随窗口一并消除）**：判定未送达后，adapter 对**非 codex-active** 目标会**再送一次提交键**。⇒ 那 1 秒假阴性不只让读数错，它**正在造成重复提交**。窗口修好后该重发变得罕见（这正是期望行为：重发条件不变，只是不再被假阴性触发）。回归测试钉住两条：延迟落盘仍判 `delivered`，且**提交键只按一次**。
    - **排序约束（否则分类器会继承污染）**：**在窗口修好之前收集的任何投递分类数据都带着这个假阴性**。⇒ 要么**先修窗口再收数据**，要么把修复前的样本**明确标为 `suspect`**。拿修复前的样本去训练/校准任何「失败原因分类」都会把该假阴性固化成一类真病因。
  - **形态 5 的详情（已实测：一次真实同仓投递，发送方 brand=`claude-code`）**：发送方在**双引号 shell 字符串**里用反引号包术语，被 shell 当成**命令替换**执行掉，两个关键词从信封正文里**消失**。此后一路正常：投递成功、nonce 在目标 transcript 越界命中、所有门全绿；接收方读到的是一句**语义被掏空但语法通顺**的话（形如「二选一 —— (带可核对证据) 或 (带理由)」，本该是「[A] delivered，带可核对证据 / [B] abandoned，带理由」）——**通顺**正是它危险的地方，接收方没有理由怀疑。
    - **判据与前四格不在同一侧**：前四格靠投递侧探测（读屏分类、transcript nonce、能力检查），这一格**投递侧任何探测都测不到**——信封里少的那几个字，nonce 一样在、边界一样对。只能在**发送前**处置，两条手段规范都给出：
      - **结构性消除（首选）**：信封构造路径**禁止使用会触发替换的引用形式**（双引号 + 反引号 / `$(...)`），改用**不做替换**的引用（如 quoted heredoc）。这类问题一旦能被消除，就不该只靠检测。
      - **检测（兜底）**：构造后**回读比对**——把即将发送的正文与源正文**逐字**比对，不一致即拒发。
    - 与本条相关的实现修法归投递可靠性那条线，本节只记规范。
  - **注册表不该为此新增字段**：五者都是**运行时/一次性**故障（沙箱、凭证、composer 状态、验证时序、本次信封的构造），随时变化；注册表是静态发现快照（ADR-0002），把它们塞进 leaf 只会得到一张更容易腐烂的表。这也是为什么「注册表全绿」永远不能被读成「投得进去」。
  - **codex 目标的投递路径已验证可用（实测，非推断）**：一次手工投递对**一个 codex 目标**走完整条链并验证成功——记边界 → 聚焦 → 写入**短指针**文本 → 等约 1s → 送 **Tab**（活跃 codex 按规则 1）→ **等约 25 秒** → nonce 越界命中 2 次 ⇒ `delivered`。与此前两次失败相比**只有两个变量不同：文本很短、验证窗口 25 秒**（随发 adapter 是 1 秒）。⇒ 「codex 路径投不通」的说法应收敛为「**codex 路径在短文本 + 足够窗口下已验证可用**」，剩余失败点只有两格：**长文本损坏**（形态 3）与**验证太早**（形态 4）。
  - **投递形态约定（建议性条款 · 动机是上面这次实测，不是美学）**：**durable 内容走信（sendbox），直投只送短指针**（信的路径 + 一句话意图），不要把长信封整段直投。理由有两条实测支撑：① 它**天然避开形态 3**（长文本在 composer 侧被截断）；② 它与「记录⊥送达正交」本就一致——durable 内容必留信，直投只是送达提醒，那么直投里放的就该是**指针**而非内容副本。这是建议而非硬规则：短内容的瞬态 chatter 直接投正文仍然合适。

    **⚠️ 但「什么时候该直投」需要一条判据，否则这条约定会被系统性用反**（实测：两个协作方在一晚里各投了十余封长信封直投，其中绝大多数是**对话**）。判据来自「记录⊥送达正交」本身，此前一直被用反：

    > **直投是「送达提醒」，durable 信才是「记录」。⇒ 只有需要对方立刻改变行为的消息才直投**（阻塞、纠错、撤回一个正在被执行的错误决定）；**其余一律落信，等对方自然取信。**

    **为什么用反是系统性的、而非疏忽**：最高频、最不 durable 的内容（对话）**恰恰是最不需要直投的那一类**，但它也是最容易顺手直投的那一类——因为它正在发生。而当双方都在活跃工作时，收件箱本来就会被看到，直投买到的那点即时性并不改变任何行为。

    **它的成本现在是可测的**（见上方焦点抢夺事件记录）：一次直投可能把 human 的**整个视图切到另一个 tab**（实测 `tab_switched: true`，`active_tab_before` 正是他当时在看的 tab）。⇒ 「少投几次」不是礼貌问题，是一条**有量的**改进。反过来说，**在能测到这个成本之前照旧是无知，测到之后照旧就不是了。**
  - **本表覆盖度的如实表述（措辞是规范性的，不得简写）**：

    > **覆盖 5 种已知形态，每格有签名级 fixture；其中 1 格的触发模式常量仅凭单次观察，且 4 格的「签名→病因」映射独占性依赖「已知病因集合完备」这一已被两次推翻的假设。**

    **禁止**把它写成「覆盖 5 种病因」「投递失败已分类完毕」之类——那是虚报：有 fixture 只证明**签名**可复现，不证明**病因**被覆盖；而已知形态集合本轮已被扩过两次，没有理由认为第三次不会发生。

  - **收束（本节最强的一条结论）**：**nonce 判据证明的是「这个信封到了」，不是「我想说的话到了」。** 形态 5 是它的存在性证明——全绿而语义已损。凡把「所有门全绿」读成「沟通成功」的地方，都少了一道**构造侧**的校验。
  - **本节是 [verification-and-gates 通则](./verification-and-gates.md#门有执行者吗通则没有机械产物的规则是装饰)「门不要求全部已验证，门要求未验证的缺口必须写出来」的第三次应用**，且这次的应用点**比前两次细一层**：缺口不在「**有没有测试**」（五格都有 fixture），而在「**测试证明的到底是哪一层**」——签名层可复现，病因层多数仍是假定。⇒ 写缺口时要标到**层**，不要停在「已有测试覆盖」；「有测试」和「测的是你以为的那件事」是两个声称。

- **`dump-screen` 的正当用途与边界（三条，别把第一条读成放宽规则 5）**：
  - **✅ 可用于事后诊断**：投递后读屏，把「**文本没到 composer**」与「**文本到了 composer 但没提交**」分开——这正是上面形态 2/3 与「正常入队等下一 turn」的鉴别手段，也是目前唯一能看到形态 3「被截断」的办法。它读的是**屏幕现状**，而屏幕上确实有内容可读时，读到的东西是可信的。
  - **❌ 不可用于存在性 preflight**：对**不存在的 pane** 它**静默返回空且 rc=0**（上游 gardener 已独立复现）⇒ 用作存在性判据必然**假阳性**（把不存在的 pane 认作存在）。规则 5 已明确禁用，本条不放宽。
  - **❌ 也不是送达证据**：规则 3 的送达证据只认 **per-send nonce 出现在目标 transcript 里**。屏幕上看见自己的文本只说明「字节到了 composer」，**不等于**已提交、已进 transcript、已被处理（形态 3 就是屏幕有字而未入队）。
  - **❌ 更测不出构造侧损坏（形态 5）**：屏幕上会**如实显示**那句已经缺字的话——读屏只能证明「屏幕上那些字到了」，无法知道**本该**是哪些字。构造侧只能在发送前自校验。
  - 区别的根子：**「读到空」不可信（可能是 pane 不存在），「读到内容」可信**。所以它能作阳性诊断，不能作存在性判定或送达判定。

- **契约里的 nonce ≠ §5.2 自识别 nonce**（用途不同，勿混淆）：本节的 per-send nonce 是**送达证据**——证明「这一条信封确实进了对方 transcript」；§5.2（自登记步骤 2）的无桥接 nonce grep 是**自识别探针**——本会话往自己终端吐一个随机串、再回自己 brand 目录 grep 定位**自身** `session_id`/`session_file`。前者验对端送达、后者定位本端句柄，各自独立。
- **证据是 per-send 运行时态，不入注册表**：字节边界 / nonce / marker 均随单次发送产生与消亡，注册表是静态发现表，**不**为其新增字段（`pane_ref` 只存寻址句柄，见 §2.2）。
- **候选未来 transport（备注，非依赖）**：官方 **Channels** 能把外部事件推进一个已运行的 Claude Code 会话，是一个**候选未来投递 transport**（成熟后可作满足本契约的又一 adapter 后端）；但它当前仍是 **research preview**、且**需会话启动时显式 opt-in**，故**暂不作 Arborist 默认依赖**（与「可插拔 adapter、opt-in、transport 中立」一致）。

## 4. 生命周期与角色分工

- **自登记（主路径）**：AgentTUI 启动读 harness 后，**自建**整条 leaf（spec.json + runtime.json，单写者原子写）。自建覆盖所有角色——rootorc / gardener 没有 handoff 信，登记不能挂在派活方身上。
- **handoff 供素材**：经 sendbox handoff 而来的会话，信中 role / task / description 直接用作 spec.json 素材；派活方可在信中提醒「按注册表规范自登记」，但**不代写**——session_id 在会话创建前不存在，派活方物理上写不了。
- **心跳**：处理 turn 的可信触点（每轮收尾、阶段切换等）顺带刷 `runtime.json.last_seen`；约定驱动，无守护进程。
- **收尾（任务/里程碑）≠ 会话结束**：任务完成 / archive / 末条回复 / 等用户输入 / compact / 上下文重置**都不是会话结束**，此时只刷 `last_seen` 心跳、**不写 `stopped`**。`state: "stopped"` 仅在**会话真正结束**（AgentTUI teardown 或 Mode-B 角色交接、当前会话不再续任）时写；**session 不得在自身仍活时标 `stopped`**（见 §3「stopped 写入门槛」）。误标的 `stopped` 会被读者 reconcile 成 contradiction（§3），且下一次可信触点应由本人 heartbeat 改回。
- **gardener**：持有并更新全局 `index.json`（跨项目摘要汇总）；按 §3 保守 GC stale 条目；校验 name 唯一；**跑注册表一致性 validator（必答时刻：周期性维护时 + 任何 GC / 批量注册表改动的前后各一次，接 [verification-and-gates 门控矩阵](./verification-and-gates.md#门控矩阵每个门一个必答时刻)「AgentTUI 注册表一致性」行，留痕落既有 landing manifest，不另造留痕机制）**；探针遗留项由 gardener 实测后回填本 guide：codex mtime **已实证**（见 §2.2）、跨目录/跨项目 `--resume` lookup **已回填**（见 §3 末，来自 adopter 实例实测、上游未独立复现）；**仍待实证**——无桥接自识别兜底（nonce grep，§5.2）。
- **half-registered 检测有两个方向，两向都须可检测并显式报为 `half-registered`**（旧表述只隐含了一向，据此写的检查会漏掉另一向）：
  - **方向 A：全局 index 有摘要、项目 leaf 不存在** —— 例：`<repo>/.arborist/agents/` 被下行同步或清理抹掉（一个 adopter 实例实测），而 index 摘要仍在。
  - **方向 B：项目 leaf 存在、全局 index 无该条** —— 例：自登记只写了 leaf、没追加 index 摘要（**上游本仓实测**）。§5 自登记第 6 点本就把「追加 index」列为可选（否则留给 gardener 汇总），故 B 向是**常态漏洞而非罕见事故**，检查必须覆盖。
  - 两向都**既不是**「未登记」**也不是**「已登记」，应显式报 `half-registered`：A 由 owner 以自登记/`register-self` 重建 leaf 修复（心跳无法修复不存在的文件），B 由 owner heartbeat 或 gardener 汇总补 index 摘要修复。**两向均不得据此 GC**（A 的摘要不是残渣，可能只是 leaf 被误删）。
- **注册表一致性的机械执行者 = `validate_agenttui_registry.py`（gardener 职责）**：上面这两向、以及 §2.2.1 / §2.3 的唯一性与自洽约束，此前**只有规范、没有任何执行者**（按 [verification-and-gates 通则](./verification-and-gates.md#门有执行者吗通则没有机械产物的规则是装饰) 即装饰门）。现由一个**只读** validator 承担，六条检查逐条对应本规范条款：

  | # | 检查 | 规范出处 | 报的 code |
  |---|---|---|---|
  | 1 | `session_id` 全局唯一（一个会话一个项目），**不受有效态限定** | §2.2.1 | `duplicate-session-id` |
  | 2 | `pane_ref` 三元组唯一，**只在有效态可达的 leaf 之间**，**独立于 1 查**；非可达却带 `pane_ref` 的另列为低危 warning、**不计入冲突**（pane 顺序复用是正常残留） | §2.2.1 | `pane-ref-conflict`（高危）/ `stale-addressing-handle`（warning）|
  | 3 | half-registered **方向 A**：index 有摘要、leaf 不存在 | §4 本节 | `half-registered` |
  | 4 | half-registered **方向 B**：leaf 存在、index 无摘要 | §4 本节 | `half-registered` |
  | 5 | leaf 的 `spec.project.path` = 它实际所在的仓根，且 `project_id` 照 §2.1 算法**重算**相符 | §2.1 + §5 第 8 点 | `project-mismatch` / `project-id-mismatch` |
  | 6 | index 摘要与 leaf 的 `role`/`brand`/`state`/`lineage`（缺省 1）一致，**以 leaf 为准** | §1 + §2.3 | `index-leaf-disagreement` |

  - 调用：`python3 .trellis/scripts/validate_agenttui_registry.py [--global-index PATH] [--project PATH ...]`；不传 `--project` 时待查项目集来自全局 index 的 `projects[].path`。退出码 `0` 一致（warning 可存在）/ `1` 有不一致 / `2` 全局 index 缺失或非法 JSON（**fail-closed**——「读不到 index」不等于「没什么可查」）。低危 warning 印在**单独分节**、不影响退出码——把清理项与误投风险混印，等于让高危发现淹在低危里。
  - **它是 validator，不是 fixer：刻意没有 `--fix`。** 修一条 leaf 往往要判「这个会话到底属于哪个项目」，且跨项目删别人的 leaf 属别的 lane 的处置权；工具只负责把冲突双方的**具体路径**指出来。它也**不联网、不读凭证、不启停会话**。
  - 单个项目路径不存在（index 指向已删仓）→ 报出来但**继续查其余**，最后统一非零退出：一条坏数据不得挡住整表体检。
  - 检查 5 是「字段全对却落错位置」那类事故（§5 第 8 点）的**机械检测**——那次事故里注册表**字段自洽、看起来是好的**，错的只有落盘位置，恰是没人核对的那一项。
- **rootorc / suborc / impler**：登记自身、读表知同伴、专注本职；**subimpler 不建条目**。
- **归属边界（跨 ATUI 别抢活）**：ATUI 只管自己 lane 的活；别的 ATUI 就其自身 lane 的**通报**（`fyi`）是 FYI 非交办，默认「知道了」不接手；看见别人 lane 的问题 → 告诉归属方或 human。权威定义见 [roles-and-tiering.md](./roles-and-tiering.md)「ATUI 归属边界」。

## 5. 操作说明：首次进项目怎么读表 / 自登记

**读表（发现同伴）**

1. `ls <repo>/.arborist/agents/` —— 目录名即同伴名；逐个读 `spec.json` + `runtime.json`。
2. 按 §3 派生规则现算各自有效态（`stat` 其 `session_file` 的 mtime）。
3. 需跨项目 → 读 `~/.arborist/index.json` 查目标项目 `path` → 再读其 `.arborist/`。

**自登记（建自己那条 leaf）**

1. 定 `name`：小写归一；查 `agents/` 下无重名。**默认用 `<role>-<task/issue>` 命名**（如 `impler-eve68`）——降低同角色并发会话撞名概率；gardener 唯一性校验兜底。
2. 取 `session_id`：已 adopt Trellis + Arborist 的仓，Bash 环境直接读 `TRELLIS_CONTEXT_ID`（SessionStart hook 桥接注入，形如 `claude_<session-id>`，去前缀即得）；或从平台 hook stdin 载荷取 `session_id` / `transcript_path`。无桥接环境的兜底法（向会话输出一个随机 nonce，再到 brand 会话目录 grep 含该 nonce 的最新文件）**待实证**。**此处 nonce 是「自识别」用途**——定位**本会话自身**的 `session_id`/`session_file`；与 §3「投递契约」（[ADR-0007](./decisions/0007-agenttui-delivery-contract-pluggable-adapter.md)）里验证**对端送达**的 per-send nonce 是不同用途，勿混淆。
3. 取 `session_file`：`transcript_path` 直接给出；否则按 brand 路径推导（见 §2.2）。
4. `mkdir -p <repo>/.arborist/agents/<name>/`，写 spec.json + runtime.json（`brand` = actual runtime brand；`state: "active"`、`generation: 1`、`lineage: 1`（首任；经 Mode B 继承则见第 7 点）；字段示例见 `<repo>/.arborist/templates/`）。
5. 同一 `name` 重启换新 session：更新 runtime.json（新 session_id / session_file，`generation` +1），spec.json 不动（`lineage` 是稳态身份，重启不变）。
6. （可选）把自己追加进全局 `~/.arborist/index.json` 摘要（含 `lineage`）；不追加则留给 gardener 汇总。
7. **经继承接管（sendbox Mode B）**：若本会话是经 inheritance-mode handoff 接管某角色（承担者换人、角色不变），spec.json 写 `lineage = 前任 lineage + 1`、`lineage_origin = 前任 session_id + 交接信名`（面包屑，非权威，见 §2.1）；`generation` 仍按本会话自身重启计（新会话即 1，与 lineage 无关）。
8. **写入路径 fail-closed 门（`.arborist/` 必须就在仓根下）**——这是 §3「投递前置校验」**路径推导**那一半在自登记侧的落点（同一条契约、同一形状：动手前先验前提，验不过就拒绝）：leaf 只能落在 `<repo>/.arborist/agents/<name>/`，其中 `<repo>` = 本项目根，且与写入的 `spec.project.path` **同一路径**。**若目标 `<repo>/.arborist/` 目录不存在，必须 fail-closed 并报 `half-registered`，不得静默上移到父目录、也不得靠 `mkdir -p` 顺手造出一整条新路径**——`mkdir -p` 恰好会把错位置造得「像是本来就有」，从外面看不出错。
   - **真实故障形态（须知，因为它完全静默）**：某写入方的 leaf 内容**全部正确**（`project.path` / `project_id` 都指向真仓），却把整个 `.arborist/` 写在了**仓的父目录**下；多日无人察觉，多条 leaf 与配套的唤醒/触达基础设施全落在错处，而注册表**字段自洽、看起来是好的**——错的只有落盘位置，恰是没人核对的那一项。**该现场的成因另有其人、尚未定位**；本门只消除**同形故障**，不声称修好了那次事故的根因。
   - 机械检查：写入前 `test -d <repo>/.arborist`（adopt 脚手架应已铺好；不存在 ⇒ 说明本仓未 adopt 或路径推导错了，**都该 fail-closed 而非补建**）；写入后核对 leaf 的实际落盘路径以 `<repo>/.arborist/agents/` 为前缀，且 `<repo>` 与 `spec.project.path` 一致。
9. **写 `stopped` 的门槛（自登记指南硬约束）**：只有**会话真正结束**（AgentTUI teardown 或 Mode-B 角色交接、当前会话不再续任）才写 `state: "stopped"`——任务完成 / archive / 末条回复 / 等用户输入 / prompt 空闲 / compact / 上下文重置**都不是会话结束**（定义见 §3「stopped 写入门槛」）。**严禁在本会话仍将继续处理 turn 时标 `stopped`**；这类场景只刷 `last_seen` 心跳。**修复误标**：本人下一个可信触点直接把 `state` 改回 `active` 并刷 `last_seen`（heartbeat 同步项目 leaf 与全局 index）；gardener 复核到 contradiction 条目时亦按此修复、不 GC。

## 6. 许可说明

本规范的机制思路（spec/runtime 两文件分离、扫目录即发现、last_seen + generation 判活等）借鉴自 CCB（AGPL-3.0）的**设计概念**，全部以自有措辞重述，未复制其任何源码或原文；Arborist 及本 guide 保持 Apache-2.0。
