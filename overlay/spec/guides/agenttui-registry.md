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

### 1.1 入口形态与仓根归属（规范性 · 机械执行者见下 · fail-closed 方向已定）

能力脚本有**两种入口形态**，二者的仓根语义**相反**，混同即静默误投：

| 入口形态 | 脚本位置 | 「谁在调我」怎么答 | 显式信号 |
|---|---|---|---|
| **项目内 adopted copy** | `<repo>/.trellis/scripts/<x>.py` | 按脚本位置推导（`parents[2]`）**正确** —— `__file__` 确实在调用方仓里 | `ARBORIST_ENTRY_FORM=project-copy`（可省） |
| **全局单份权威入口** | 机器级单份 + shim（`<ARBORIST_HOME>/bin/<name>`） | **无从推导** —— `parents[2]` 得到的是**承载权威脚本的那个仓**，与调用方无关 | `ARBORIST_ENTRY_FORM=global-authority`（shim 必须导出） |

> **规范：全局入口的每一个读写项目状态的子命令，缺 `--repo` 必须在读取任何仓状态之前拒绝**（非零退出 + 说明「全局入口必须显式给调用方仓根」）。项目内副本**不**受此限。**区分点是入口形态，不是子命令。**

**为什么必须是拒绝而不是推导**（实测读数，去实例值）：

| 面 | 缺 `--repo` 的旧行为 | 为什么比「不可达」严重 |
|---|---|---|
| 投递 | 按 `parents[2]` 推出**权威仓**并继续执行。既有的仓根门只证明「那里像个项目仓」（`.trellis/` 或 `.git/` 在），**不证明那是调用方仓** | 上次只因权威仓**恰好**没有同名 agent 才在后续读取处失败 —— 那是偶然，不是门。有同名 agent 时就是**误投**（§2.2.1：一个能被看见的失败恒优于一个看不见的成功） |
| 容量观测 | **rc=0**，返回权威仓快照：格式完好、`generated_at` 与各品牌观测值都属别人 | 这里**没有任何后续兜底会失败** ⇒ 「推导成功但仓错误」，调用方无从察觉。**已真实发生** |

**判据的优先级与 fail-closed 方向**：① 显式信号（环境变量）优先 —— 只有铺入口的那一方知道自己铺的是什么；② 信号缺失时退回**结构判据**：脚本是否真的位于 `.trellis/scripts/`（这是在核对推导**自身的前置条件**，不是猜路径）；③ 信号值不认识 ⇒ 判 `unknown`，**不得**回退到结构判据（信号打错字不能静默重开推导）；④ **判不准即要求显式 `--repo`**。

**豁免**：仅顶层 `--help`，且它豁免的原因是**调用顺序**（argparse 在门之前处理掉它），不是一张会腐烂的白名单。随发脚本的每个子命令都读写项目状态，故豁免清单**为空**。

**契约必须两跳都成立**：信封的 `reply_command` 必须携带**本次已解析的** `--repo`，不得让回复方从 `__file__` 重新推导 —— 否则第一跳传对了，第二跳又落回同一条错仓推导。回复入口优先用稳定的全局 shim 形态，但**无论哪种形态都必须带 `--repo`**：入口形态是优化，`--repo` 是正确性要求。

**机械执行者**：端到端回归（穿过「脚本被铺在哪 / 环境变量说什么」这一层，见 [verification-and-gates](./verification-and-gates.md#门的回归必须端到端且测试的结构必须与真实调用路径同构)），含**同名 agent fixture**——专门钉住「上次只是恰好没同名」那个偶然。工具条目侧的执行者见 [tool-registry](./tool-registry.md) 的入口形态一致性 validator。

> **这条属于一个更大的通则**：凡一个定位参数缺失时会「回退到某个默认目标」而非报错的接口，一律要在我们这一层包成 fail-closed。判据与前两次实例见 [verification-and-gates](./verification-and-gates.md#缺定位参数时静默回退到默认目标的接口一律在我们这一层包成-fail-closed)。

## 2. Schema

> **通用条款（适用于本篇每一个可选字段，不只是某一次的新增）：「没人写过」与「有人写错了」必须分开判。**
> **字段缺失**读作 `unknown`，**不得**读作最宽松的那个值，也**不该**红灯——现存 leaf 全都没有后来新增的字段，把缺失当违规会造出一整面假阳性，而假阳性多的门会被学会忽略。
> **字段存在但值不可识别**必须**拒绝**，且**不得宽容地归一化**——宽容接受会让旧形态（例如一个本该被取代的布尔）静默留在库里，那等于新语义**从未落地**。
> 两者的区别是**谁的责任**：前者是 schema 演进的正常代价，后者是一次写错，而只有后者有人可以去修。


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
| `foreign_repo_registration` | 可选，**且它的出现把这条 leaf 定义为「跨仓镜像」**（详见 §2.2.2）。三字段**全部必填**：`home_registry`（**权威 leaf 目录的绝对路径**）/ `reason` / `authorized_by`。带该字段时**本 leaf 的 `runtime.json` 不是权威** —— 投递侧必须改从 `home_registry` 读 runtime 半边。缺任一字段、或 `home_registry` 非绝对路径 / 不可达 / 名字与项目对不上 ⇒ **fail closed**（不得回落到本 leaf 那份拷贝）。**它此前是「事实存在但规范里没有」的字段**——这正是它腐烂多时无人管的根因，故补进 schema 本身 |
| `lineage_origin` | 可选。本代继承所依据的 handoff 信**溯源面包屑**（建议格式：`前任 session_id + 信文件名`）。**⚠️ 非权威、可悬空**——inheritance handoff 信按 sendbox 协议在承接方首个里程碑后 `burn`，此值届时指向已烧文件；**真要审计继承链请去 git 历史 / ledger，切勿把本字段当审计指针**。注册表是快照（见 [ADR-0002](./decisions/0002-agenttui-declared-derived-state-model.md)/[ADR-0005](./decisions/0005-agenttui-role-lineage-vs-generation.md)），只答「当前第几代」（发现用），不答「继承链长什么样」（审计用） |

#### 2.1.1 `capabilities`：记原因，不记布尔（规范性）

可选对象；每个键是一项**门可能要求的能力**（当前唯一定义键：`dispatch_subagent`），值是**三值之一**：

| 值 | 含义 | 解除需要 | **上交对象** |
|---|---|---|---|
| `available` | 能力存在且当前可用 | — | — |
| `policy-denied` | **能力存在**，但承载的指令/配置禁止本会话使用它 | **一句话即可解除** | **human** |
| `unavailable` | 承载本身没有这个工具 | 换承载或换 brand | **L4 / 上游** |

**为什么不能记成一个布尔 `can_dispatch`（这是本节存在的全部理由）**：

> **策略禁用 ≠ 能力缺失。两者效果完全相同（都派不出去），恢复路径完全不同。**

活实例：一个会话 brand 正确、AgentTool **存在且可用**，但承载指令含「未经请求不得调用它」⇒ **brand 正确、能力存在、门无法自动满足** 三个条件同时成立。布尔字段把这一格与「根本没有这个工具」压成同一个值，而**不可分的直接后果是上交时给不出「上交给谁、要它做什么」** —— 于是上交沦为一句「我做不了」，**实际等于静默跳过**。

**执行策略（规范性）**：

> 强制门遇到能力分支时，**一律上交，不得静默跳过**。上交对象由**原因**决定：`policy-denied` → human；`unavailable` → L4/上游。
> **两种情况都必须在任务记录里留下「门未执行 + 原因 + 已上交给谁」**，否则后续读者会把「**门没报错**」读成「**门通过了**」。

**与两条已落通则的关系（三者是同一机制的三面，别只记住一条）**：

| | 形态 |
|---|---|
| [门的回归必须端到端](./verification-and-gates.md#门的回归必须端到端且测试的结构必须与真实调用路径同构) | **测了,但没测到门** |
| **本节** | **没测,但看起来像测过**（门静默跳过，记录上没有任何异常） |
| [状态表的「已落」必须附独立读数](./verification-and-gates.md#状态表里的已落必须附一条独立读数) | **没做,而表上写着做了** |

**缺字段的读法**：整个 `capabilities` 缺失或某键缺失 ⇒ 读作 **`unknown`，不读作 `available`**。理由与本篇其它 fail-safe 同向：把「没写」读成「能用」，会让门在**它其实派不出去**的会话里被判为已满足。

### 2.2 `runtime.json`（活体，易变，可信触点刷新）

| 字段 | 说明 |
|---|---|
| `session_id` | **主键 / 触达句柄**。`claude -p --resume <session_id> "<msg>"` 向该会话**追加**一条消息并让其在自身完整上下文里处理（实测：append 非 fork，回复走调用方 stdout）。触达前须按 §3 末判活选通道 |
| `session_file` | 会话落盘**绝对路径**（判活探针，令读者零 brand 知识）。Claude Code：`~/.claude/projects/<munged-repo-path>/<session_id>.jsonl`（逐轮 append，mtime = 最近活动，已实证）；Codex：`~/.codex/sessions/YYYY/MM/DD/rollout-<ISO时间戳>-<session_id>.jsonl`（逐轮 append，mtime = 最近活动，**已实证**：`codex exec resume` 续同一 rollout、mtime 随 turn 递增、不新建文件，与 Claude Code 同——见 [ADR-0003](./decisions/0003-cross-session-reach-semantics.md) 实测边界） |
| `state` | **声明态**：`active` / `stopped`（`idle` 为保留枚举值，MVP 不自写，见 §3）。`stopped` 有**写入门槛**（仅会话真正结束才写，见 §3/§4）且遇活转录矛盾会被派生规则**降级为 contradiction**——声明态非确知，读者据 §3 现算，不无条件采信 `stopped` |
| `last_seen` | 心跳时间戳（ISO8601，可信触点顺带刷新）。**写 `stopped` 时也须记 `last_seen`**——它是活转录矛盾检测的基准：若 `session_file` mtime 晚于该 `stopped` 写入记录的 `last_seen`（容小段文件系统时钟偏移），即声明与派生活性证据矛盾（见 §3） |
| `generation` | 重启代数（同一 `name` 重启/换 session 时 +1） |
| `pane_ref` | 可选：**投递 adapter 用的** 终端复用器 pane/tab 引用。core 不强制（未启用活 pane 投递时置 `null`）；启用活 pane 投递 adapter 时按 [ADR-0007](./decisions/0007-agenttui-delivery-contract-pluggable-adapter.md) 契约填，供 adapter 寻址目标 pane。字段：`multiplexer` / `session` / `pane_id`，外加**可选 `socket`**（见下方 `pane_ref.socket` 一行）。**`multiplexer` 值域 = 随发 adapter 的 transport 注册表键，当前两个并存：`zellij` / `tmux`**（并存是刻意的——迁移按 pane 逐个进行，不做 flag day；值域权威在代码那张注册表，规范这一行与它同步）。**它是启动时快照、会腐烂**：复用器 session 改名或换复用器后，整条 `pane_ref` 必须**重建**（**不能只改 `multiplexer` 字段**——只改这一个字段等于把旧复用器的地址挂在新复用器名下，两套寻址语义不同，得到的是一个语法合法、语义错位的句柄），否则注入会静默投空——见 §3 投递契约规则 5。注意：送达证据（transcript 字节边界 / per-send nonce / marker）是 **per-send 运行时态，不入本静态表**，故此表**不**新增存 nonce/证据的字段 |
| `pane_ref.socket` | **可选**：`pane_id` 所属的复用器 **server**（`-L <名>` 或 `-S <路径>`）。**缺省 = 该 transport 的默认 server**，故本字段出现之前写下的每条 `pane_ref` 寻址不变（向后兼容是硬要求，不是好意）。**它在「pane id 只在单个 server 内唯一」的复用器上是必需维度**：tmux 的 `%N` 只在一个 tmux server 内唯一，缺这一维时 `(multiplexer, session, pane_id)` 命名的是**一个 pane 号**而非一个 pane —— 同机多 server 时，默认 server 上**恰好**存在同号 pane 且其 session 名也相同，则每道检查全过、信封落进第三方 composer（§2.2.1 判为最严重那一格）。**判名/判路径按值自身形态**：含路径分隔符按 socket 路径，否则按 socket 名（与复用器自己那两个选项同一区分，故不必再造第二个字段，也不存在一个值两种含义）。**⛔ 严禁把 socket 塞进 `session` 字段**——字段名与内容不符今天不花钱，却误导之后每一个读者，包括那个专门用来发现句柄腐烂的 session 核对。**缺省与显式 `default` 视为同一 server**（默认 socket 本就名为 `default`；不等同就会把唯一性判在拼写上而不是判在 pane 上）。 |

#### 2.2.1 唯一性约束（规范性 · 机械执行者见 §4）

注册表无守候进程、每个写入者各写自己那条 leaf，故下列两条唯一性**结构上可能被违反**，且**必须由 validator 机械检查**（`validate_agenttui_registry.py`，见 §4）——只写在这里而无执行者，按 [verification-and-gates「没有执行者的门是装饰」](./verification-and-gates.md#门有执行者吗通则没有机械产物的规则是装饰) 就是装饰。

- **`session_id` 全局唯一 —— 一个会话属于一个项目。** 同一 `session_id` 不得出现在**多个项目**的 leaf 里（也不得在同一项目里被两条 leaf 声称）。真归属可由该 leaf 的 `session_file` 路径、或该 pane 的实际 cwd 判定；不属于本项目的那条应删。**这条是根约束、不受有效态限定**——重复登记无论 `state` 写什么都是错登记。
- **`pane_ref` 唯一性 —— 一个 pane 一个「活」agent**，键是 `(multiplexer, socket, session, pane_id)` **四元组**（同一 `pane_id` 落在两个复用器 session 下不算撞；落在两个 **server** 上同样不算撞）。**socket 必须进 key**，理由是它两个方向都会错：pane id 只在单个 server 内唯一 ⇒ 不带 socket 时，两个**不同**的真实 pane 会撞成同一个键（**假冲突**），而两条**真在抢同一个 pane** 的 leaf 也可能因一处拼写差异被判为不撞（**漏报**）。缺省 socket 归一化为默认 server 名，故本字段出现前写下的 `pane_ref` 判定不变；归一化是**纯字面**的（socket 路径不与 socket 名互相解析——那需要写 leaf 那一方的 socket 目录与 uid），残留缺口见 §3 缺口清单。它形式上是上一条的推论，**但必须独立检查**：两个**不同** session 声称同一 pane 说明至少一条 `pane_ref` 已腐烂（见上表 `pane_ref` 行「启动时快照、会腐烂」），而 `session_id` 唯一性检查看不见这一格。
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

**⚠️ 先判性质，再判对错：跨仓「重复」有两种，只有一种是错的。** 本节的 tiebreak 曾被（本仓自己）当成「跨仓重复 = 错登记 ⇒ 删掉错的那条」，**那个前提是错的**。逐条读内容后实测：全部跨仓 `pane-ref-conflict` / `duplicate-session-id` 案例里，多数是**自述的、有授权来源的跨仓镜像登记** —— leaf 里带着自陈字段（例如声明本条只为跨仓直投而存在、指明权威条目在哪个仓、以及授权出处），`project.path` **刻意**指向该 agent 真实工作目录所在的那个仓。

| 性质 | 特征 | 处置 |
|---|---|---|
| **错登记** | 无任何自陈标记；两条各自声称自己是权威；`project.path` 与 leaf 实际所在仓不一致且无解释 | 按下表 tiebreak 出具名裁定，由归属 lane 删错的那条 |
| **跨仓镜像 / peer 登记** | leaf **自陈**其为镜像（权威条目位置 + 存在理由 + 授权出处）；两条**共享同一 `session_id` 与同一 `session_file`**（因为本就是同一个会话） | **不得删** —— 删掉的唯一后果是对方再也无法跨仓直投它。这是 **schema 缺口**，不是脏数据 |

⇒ **`session_id` 全局唯一那条根约束需要一个一等的例外表达。** 当前规范只有「一个会话属于一个项目」，于是**合法的跨仓可达性只能靠伪装成重复登记来实现**，而 validator 必然把它报成高危。**结论：这一族告警不能靠删数据消掉**；正确修法是给跨仓 peer 一个一等 schema 字段，并让 `duplicate-session-id` / `pane-ref-conflict` / `project-mismatch` 三项检查对**带该字段且自陈完整**的条目降级为 info（仍列出，便于审计），对**不带标记**的保持高危。

**这条修法当前的实况（逐项，勿读成「已满足」）**：

| 分项 | 状态 |
|---|---|
| 一等 schema 字段 | **已落定** = `foreign_repo_registration`，规范见 §2.1 表 + **§2.2.2** |
| 投递侧按 home 取权威 + fail closed | **已实现**（§2.2.2 契约 1–5，有端到端测试） |
| validator 报镜像腐烂 | **已实现** = 检查 7（`mirror-stale` 等，见 §4） |
| 上述三项检查对镜像降级为 info | **未实现** ⇒ 镜像条目仍会被 `duplicate-session-id` / `pane-ref-conflict` / `project-mismatch` 报成高危，那**仍是已知假阳性**，处置一律「出裁定、不删」（有测试钉住这一格未修，以免规范与实现悄悄漂开） |

**残留的真实风险（不因是镜像而消失）**：镜像两条共享同一 `pane_ref`，所以**当前**投递会落到同一个真实目标、**不会**打进第三方；但该 pane 被后续 session 复用之后，validator 报的「静默误投」就会变成真的。⇒ **本 adapter 的投递路径已不再受此影响**（§2.2.2：一律读 home，绝不读镜像那份拷贝）；**但任何直接读镜像 leaf 的读者仍会中招** ⇒ 镜像的寻址字段与权威条目不一致时由 validator 检查 7 报 `mirror-stale`。

**跨仓冲突的机械 tiebreak（规范性 · 用于上表「错登记」一类 · 因为这一类按构造就没有 owner）**：`pane-ref-conflict` 与 `duplicate-session-id` 的案例**全部**发生在**两个不同项目仓之间**（A 仓的 leaf 与 B 仓的 leaf 声称同一个 pane / 同一会话）。对这一类，「修复归各自 lane」**不成立**：**每个 lane 单看自己那条都是自洽的，冲突只在全局可见**——可预期的结果是两边都认为对方错、或两边互等，于是每条高危冲突各自卡住。故：

| 条目 | 规则 |
|---|---|
| **判定输入优先级** | ① 该 pane 的**真实 cwd**（经该 pane 内进程的工作目录判定）> ② 两条 leaf 各自的 `session_file` 归属 > ③ `last_seen`。**⚠️ 优先级 ② 是 brand 相关的，不通用**：一种 brand 的会话文件按项目路径分目录（见 §2.2），故其路径本身即归属证据；**另一种 brand 的 rollout 日志存放在一个全局目录、不按 cwd 分目录** ⇒ 对它 `session_file` 路径**不含任何归属信息**，用它判归属会得出错误结论。该 brand 的替代读数是 **rollout 首条记录里会话自述的 cwd**（会话自己记下的工作目录）。⇒ 任何「可从 session_file 路径判定归属」的提示文本必须**限定 brand**，不得写成通则。**高优先级读数存在时不得用低优先级读数翻案**；三级全取不到 ⇒ 不裁定，升给 human。 |
| **判定必须在全局做** | 一次、看齐所有声称方后作出，**不得让两个 lane 各自判自己那条**（那正是上面互等的成因）。 |
| **判定产物 = 一条具名裁定** | 必须写明：哪条**合法**、哪条**删**、以及**依据的原始读数**（不是「按惯例」「看起来像」）。裁定发给**被判错那条所属 lane** 执行删除——跨项目删别人仓里的 leaf 属于那个 lane 的处置权。 |
| **validator 只读、不代替裁定** | validator **报告**冲突并**输出裁定所需的全部读数**（两条 leaf 的完整路径 + 各自 `session_id` / `session_file` / `state` / `last_seen` / `pane_ref`），使裁定者不必再手工回查；但它**不裁定、不删、无 `--fix`**。**报告 ≠ 交办**（同 §4 末「归属边界」）。 |
| **真实 cwd 不自动取（须知，别当缺功能）** | 取它需要「pane → 进程」映射，而参考复用器里唯一能可靠报出 pane 存在性的命令**就是聚焦命令**（会把 human 的视图拽到该 pane），layout dump 又给不出 pane→pid ⇒ **没有只读替代**。按 [verification-and-gates「新增的观测动作必须先证明它不扰动被观测者」](./verification-and-gates.md#新增的观测动作必须先证明它不扰动被观测者)，会移动别人视图的观测**不是只读**，更不该藏在一个会被**批量**执行（GC 前后各一次）的 validator 里。⇒ validator 输出该读数为 **`unknown` 并写明为什么不能自动取**，由人工补齐。**机械证明**：该 validator **不执行任何外部命令**（有测试钉住），故加这些读数**没有**新增任何观测动作。 |

⇒ **误投比不可达严重，优先处置。** 理由是**谁承担代价、以及故障能不能被看见**：不可达当场就被 fail-closed 挡住、只有发送方受影响，代价有界且有人会看到；误投既不报错、又把代价转移给一个从未参与本次投递的第三方会话（它收到一段莫名指令，可能照做），且没有任何机械信号会让任何一方察觉。**一个能被看见的失败恒优于一个看不见的成功。**

#### 2.2.2 跨仓镜像：`foreign_repo_registration`（规范性 · 机械执行者 = validator 检查 7 + 投递侧 `load_agent`）

**为什么存在**：投递规划只吃**一个**仓根，sender 与 target 都从它加载 ⇒ 「A 仓的 sender 投给 B 仓的 target」**在参数上无法表达**。既有做法（人类授权、已在用）是在**发送方那个仓**里也给目标建一份 leaf，即镜像。镜像**不是脏数据、不得删**（删掉的唯一后果是该仓再也无法直投它，见 §2.2.1 那张性质表）。

**必带三字段**（缺任一 ⇒ 与「无标记的错登记」不可区分，validator 报 `mirror-declaration-incomplete`）：

| 字段 | 内容 |
|---|---|
| `home_registry` | **权威 leaf 目录的绝对路径**（`<home 仓>/.arborist/agents/<name>/`）。相对路径 ⇒ 会按读者当时的 cwd 解析 ⇒ 一律拒 |
| `reason` | 这条镜像为什么存在（例：仅为跨仓直投） |
| `authorized_by` | 授权出处（谁、何时） |

镜像的 `project.path` / `project_id` 指向该 agent **真实 home 项目**（不是宿主仓）——这是刻意的，见 §2.2.1。

**权威规则（一条）：镜像的 `runtime.json` 不是权威，权威永远是 `home_registry` 指向的那一份。**

理由是机械的、不是风格问题：目标的心跳**只写它自己 home 那条 leaf**，镜像那份 runtime 是建镜像时的**整份拷贝**，此后**永不自动更新** ⇒ 它**按构造**会腐烂。而 `pane_ref` 是启动时快照 + **pane 会被顺序复用**（已实测）⇒ 陈旧 `pane_ref` 寻址到的是**那个 pane 现在的占用者** = §2.2.1 后果分级里最严重那一格（**静默误投**）。

⇒ 投递侧（`load_agent`）契约：

1. leaf 的 spec 含 `foreign_repo_registration` 时，**runtime 半边一律从 `home_registry` 读**（`session_id` / `session_file` / `state` / `last_seen` / `pane_ref` 全部取 home 值）；镜像那份**不得用于寻址**。
2. **`home_registry` 必须过路径校验**：绝对路径、是目录、其 `spec.json` 的 `name` 与本 leaf 同名、其 `project.path` 与本 leaf 声明的 `project.path` 一致（否则镜像指错了 home）、且 home 自身**不得**也是镜像（**不追镜像链**，避免环）。
3. **任一校验不过 ⇒ fail closed（抛错），绝不回落到镜像那份拷贝。** **为什么不回落**：按 §2.2.1 的后果分级，回落是把一个**响亮的错误**（不可达：当场报错、只影响这一次投递、有人会看到）换成一次**安静的误投**（污染一个从未参与本次投递的第三方会话、无任何机械信号）。**一个能被看见的失败恒优于一个看不见的成功** ⇒ 回落这条路在本节被显式禁止。
4. **镜像那份 runtime 拷贝保留、但降级为诊断用**：与 home 的**寻址字段**（`session_id` / `session_file` / `pane_ref`）不一致时，**在投递路径上大声报出来**（说明用的是 home 的值、镜像那份已陈旧），**不静默同步** —— 静默同步会掩盖「镜像正在腐烂」这个事实本身，而那个事实正是「每次投递都必须读 home」的理由。
5. **不带该字段的 leaf 行为逐字不变**（有回归测试钉住）。
6. **派生自 1 的一条：经镜像写心跳落在 home 那条 leaf 上**（因为 runtime 的读写位置都改成了 home），镜像那份拷贝**不会**被顺带刷新。这是刻意的 —— 刷新它就等于「静默同步」，见第 4 条；且写入仍受既有 session 核对约束（只有该会话本人的 `session_id` 能对上），故这不是一条跨仓写别人 leaf 的口子。

**寻址字段 vs 快照字段（严重度分级的判据 = 该字段做什么，不是漂了多少）**：

| 类 | 字段 | 不一致的后果 | validator 严重度 |
|---|---|---|---|
| **寻址** | `session_id`（resume 句柄）/ `pane_ref`（pane 地址）/ `session_file`（一切可达性派生所依据的探针） | 决定信封去哪 ⇒ 陈旧即误投（对任何**直接读这条镜像**的读者） | **failure**（`mirror-stale`，非零退出） |
| **快照** | `last_seen` / `state` / `generation` / `description` / `task` … | 不决定信封去哪 | **warning**（`mirror-snapshot-drift`）——镜像**本就是**快照，为此红灯会让**每条镜像永久红灯**，而假阳性多的门会被学会忽略（同 `stale-addressing-handle` 的理由） |

### 2.3 全局 `index.json`（摘要级，gardener 维护）

`{ "projects": [ { "project_id", "path", "name", "alias"?, "agents": [ { "name", "role", "brand", "state", "session_id", "lineage" } ] } ] }` —— 仅作跨项目发现的入口，细节以各项目 `.arborist/agents/*` 为准。摘要带 `lineage`（缺省=1）是为跨项目「找当前那一代承担者」的常见意图；不带 `lineage_origin`（溯源属细节，且非权威，见 §2.1）。

- **`alias`（可选）—— 项目的简写/别名**，供人和工具在**不适合用长仓名**的位置引用该项目。三条约束：
  - **`alias` 不是身份，`project_id` 才是。** 别名可改、可重复出现在人写的文本里；任何**寻址与去重**一律按 `project_id`（§2.1 的派生值）。⇒ 工具**不得**用 `alias` 做键，也不得据它判两条记录是否同一项目。
  - **值域受限，因为它会进入外部命名空间**：`[a-z][a-z0-9-]{0,31}`（小写、连字符）。理由不是美观 —— 别名会被拼进**终端复用器的 session 名**一类外部标识，而那些命名空间通常禁止 `.` `:` 与空格；把限制写在源头，比在每个消费点各自转义更不容易漏。
  - **缺省即回落到 `name`**，不得因为缺 `alias` 而失败（它是便利字段，不是必填身份）。

- **摘要与 leaf 的两份拷贝必须一致，且 leaf 为准**：`role` / `brand` / `state` / `lineage`（缺省 1）在两处同时存在，任一处漂移都会让跨项目读者按摘要作出错误路由（如按摘要的旧 `brand` 选 submit 键）。不一致时**以 leaf 为准**（§1「细节以各项目 `.arborist/agents/*` 为准」），修的是摘要。
- **摘要与 leaf 的存在性也必须成对**：只有一边即 `half-registered`（两方向定义与修法见 §4）。
- **`project_id` 是可机械重算的派生值，不是可手抄的字面值**：照 §2.1 的算法（`realpath` 归一化后 sha256 前 12 位）**重算比对**；手抄或从别的项目复制会让同一仓在跨表读者眼里裂成两条记录。
  - **规则前移到写入时（这一条才是对因，读表侧校验只是兜底）**：`project_id` 在**自登记写入路径上由 `realpath` 计算**，**不接受手填字面值**（落点见 §5 第 4 点）；若目标位置已有值且与重算不符 ⇒ **fail closed**，不得覆盖也不得沿用。ADR-0007 amendment 已在**发送侧**写死同一条（按 realpath 重算、不符即拒），本条把它前移到**写入侧**——只在发送侧校验，等于允许错误先被写下来。
  - **模板不得给可填空位**：`overlay/arborist-templates/` 里 `spec.json` 与 `index.json` 的 `project_id` 占位**明写「由 realpath 计算、不是填空位」并给出计算命令**（`validate_agenttui_registry.py --print-project-id <repo>`），而非一个形如 `<project-id>` 的空槽——**空槽本身就是手抄的邀请**。
  - **这是「预防 > 检测 > 判断」的实例**：validator 能检测它（§4 检查 5），但只要写入路径还接受手写值，**它就永远有活干**——被检测出的每一条都是本可以不发生的。⇒ 判断（人去看哪个值对）最贵，检测次之，**让错值写不进去最便宜**。
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

1. **brand + submit 态感知的 submit 路由 —— 而「可达态」与「submit 态」必须分开取值**：
   - **⚠️ 可达 ≠ 正在跑 turn（这条曾被合成一个值，是一个已实测的错）**：§3 读时派生态（含 contradiction）只回答**「该走活 pane 还是 stopped-session resume」**——它描述「**最近可达**」，**不证明当前 turn 正在执行**。刚跑完一个 turn 的目标仍落在新鲜窗口内，按新鲜度当「活跃」就会把 **Tab 发给一个空闲 composer**：Tab 在空闲态**什么也不入队**，信封留在输入框里不提交（下游实测；反向亦已实测：真忙目标的 Tab 入队后 nonce 到 turn 结束才出现，早期 grep miss 被当成失败而重投 ⇒ 重复决策）。
   - **Codex 的 submit 态必须另从目标 transcript 的最新完整 turn-boundary 事件取得**（`event_msg.payload.type`）：`task_started` = **active** → 发一次 **Tab（byte `9`）** 入队到下一 turn，**不 steer** 当前 turn（让当前 turn 先跑完，防外部 agent 把决策注入到实现进行到一半之中）；`task_complete` = **idle** → 发 **Enter（byte `13`）** 立即提交。
   - **取不到可信 boundary ⇒ 注入前 fail closed**，**不得**拿 transcript 新鲜度猜提交键（fail-closed 的相位与结果值见规则 5）。
   - **非空但未以换行终止的 JSONL 尾记录 = unknown**，**不得**跳过它去复用更早的 boundary——那会自信地报出「这条记录写入之前」的状态。
   - **pane settle 延迟结束后、真正按键前必须再读一次**：turn 可能恰好在「写入」与「提交」之间结束，此时计划中的 Tab 已经不再正确。
   - **Claude Code** → **不分活性一律 Enter 提交，且不读 turn boundary**。**为何不照搬 Codex 的 Tab**（#12 官方补充裁定）：Claude Code 官方 keybinding 只有 `chat:submit`=Enter，其 Tab 用于 autocomplete / tab 导航，**没有 Codex-Tab 那样的独立「入队到下一 turn」动作**；目标忙碌时由 **Claude Code 自身的 receiver-side queue** 在当前 turn 跑完后处理，故活跃/空闲都用 Enter。**⚠️ 勿给 Claude Code 套用 Codex 的 Tab**——那会落进 autocomplete/导航语义、不入队提交，是误改。
   - **写入方式：Codex 的信封必须按「一次性成帧粘贴」写入**（终端标准 bracketed paste `ESC[200~` / `ESC[201~`），**不得**把整封信当高速按键流裸写。下游实测（某一 Codex 版本）：裸写会被归类为 paste burst，burst 未结束时 **Enter 的行为是往 composer 追加换行而不是提交** —— 目标机械判定为 idle、两次提交键命令均 rc=0，信封仍滞留 composer；改用成帧粘贴后 nonce 约一秒后出现。**这是「写入方式」层的对因修法（形态 3），与路由、复用器选择无关**——契约层只问「本次写入是否需要成帧」，成帧**机制**属 transport（有原生 paste 原语的 transport 应改用它）。
     - **成帧是按 brand 的白名单，不是无条件**：只对已有实测支持的 brand 开（当前仅 codex）。其它 brand 的 composer 可能有自己的 paste 处理，**无实测就不加**（同名 ≠ 同能力）。
   - 与 [ADR-0006](./decisions/0006-runtime-brand-is-routing-authority.md) 一致：submit-key 路由本身即 brand-keyed，是「按实际 brand 路由」在投递维度的延伸。
2. **不盲目重发入队键**：送达未观测到时**不得**重发 Tab——盲目重发会入队重复信封。
   - **idle Codex 的一次 Enter 未验证时，补发 Enter 前必须再次确认 submit 态仍为 idle**；已变 active 或 unknown 就停止（`submit-unverified`），**不得** steer 一个刚开始的 turn。Claude Code 的补发不受此限（其 receiver-side queue 负责排队）。
3. **送达证据必须 message-specific（fail-closed，绝不假阳性）**：每次发送生成**唯一 nonce** 写入信封；注入前记录目标 transcript 的**位置指纹 = inode + size**（不是裸字节偏移）。验证时分两路，并**显式标注证据等级**：
   - 指纹**可核对**（inode 未变、size 未缩小）→ 在字节边界**之后**搜 nonce，命中即 `delivered`，证据等级 `evidence=envelope-nonce-found-after-boundary`（强）。
   - 指纹**不匹配**（inode 变 / size 变小 / 无法核对）⇒ 目标会话文件**被重写**，字节偏移不再对应「投递后新增」→ **降级为全文件 nonce 搜索**，命中即 `delivered`，证据等级 `evidence=envelope-nonce-found-fullfile`（弱于 after-boundary，但**仍是送达证据**）；**不得**因指纹不匹配就直接返回一个未验证值（规则 4 的 `submit-unverified` 等）。
   - **「transcript 单调 append」不是可依赖的不变量**：Claude Code 的 **compact / rollout 重写**会原地重写会话文件。**实测**（一个 adopter 实例的 dogfood 巡检；上游 gardener 未独立复现）：一次投递后全文件 grep 到该 nonce 多次、目标输入框已清空（**确实送达**），但按边界做 `tail -c +N` 检测得 **0 次**——目标刚做过 compact、文件被重写。裸边界检测在此产生**假阴性**（实为送达、判为未送达），而假阴性会让调用方据那个未验证读数（现为 `submit-unverified`）**重发** ⇒ **重复投递**，正是规则 2 要防的事。
   - **为何全文搜索不构成假阳性（须论证，别当例外网开一面）**：nonce 是 **per-send 唯一**的，只可能由本次发送写入 ⇒ 全文命中 ⇒ 本次信封确实进了对方 transcript。字节边界原本防的是「把历史里的旧 marker 当本次送达」——**唯一 nonce 已在源头排除该情形**，故边界只是**证据强度的加成**，不是防假阳性的必要条件。（推论：若某 adapter 用**可复用的固定 marker** 而非唯一 nonce，则全文降级对它**不成立**，必须留在边界路。）
   - 仍然：pane 命令成功 / pane 存在 / 转录 size 增长 / mtime 变化**都不是**送达证据（忙碌目标会自行增长转录）；**peer 回复是唯一的语义 ACK**。
4. **fail-closed，且结果必须按「已执行的动作」分类 —— 不许用一个 unverified 桶混装**：未搜到 nonce 绝不当 `delivered`（「未验证」= **两路都没搜到 nonce**，含降级后的全文搜索，不是「指纹核不上」）。但**「没验到」不是一个结论，只是一个读数**：下表每一格的正确调用方动作**互相矛盾**（等 turn 边界 / 恢复 composer 里已有的文本 / 去查一条没回话的命令），把它们合成一个值，调用方就无法知道自己在哪一格。**故结果值域按已执行动作展开为七值**（`no-operational-route` 属规则 6，是第八个、语义上「没发出去」那一格）：

   | `delivery` | 已执行到哪一步 | 调用方动作 | `retry_safe` |
   |---|---|---|---|
   | `pre-injection-rejected` | submit 态不可读，**零 pane 命令** | 待状态可读后重试 | **true** |
   | `delivered` | 本次 nonce 出现在 pre-send 边界之后 | 等语义 peer ACK | false |
   | `queued-for-next-turn` | 活跃 Codex 的 Tab 已执行，nonce 尚未出现 | **等 turn 边界，不得重投** | false |
   | `submit-unverified` | Enter 已执行，nonce 未观测到 | 查目标或等 ACK，不得盲目重投 | false |
   | `composer-unsubmitted` | 文本已写入，按键前刷新为 unknown，**未发任何键** | **恢复既有 composer，不得重写信封** | false |
   | `write-unverified` | 写入命令非零/超时（未回话） | 查目标，不得重投 | false |
   | `submit-command-unverified` | 提交键命令非零/超时（未回话） | 查目标或等 ACK，不得盲目重投 | false |

   - **每个结构化 pane 结果必须同时输出**：`submit_action`、`recommended_action`、`verification_guidance`、`retry_safe`、本次 nonce、message-specific `evidence`（`envelope-nonce-found` 或 `none`）、`acknowledged=false`（直到 peer 回复）。
   - **`retry_safe=true` 只允许出现在机械可证「零 pane 命令」的路径上**——即 `pre-injection-rejected` 与 `no-operational-route` 两格。**命令失败不等于零副作用**：一条非零或超时的 pane 命令**可能已经产生副作用**，故 `*-unverified` 一律 false。
   - **`queued-for-next-turn` 必须附 `verification_guidance=early-transcript-miss-is-not-nondelivery-evidence`**：调用方不得因一次早期 transcript 零命中而重投；等 turn 边界或 peer ACK。
   - **禁止用预测式命名**（`will-land` / `stranded` 之类）：那是在无证据的情况下预测结果。名字只许说**已经做过什么**。
5. **pane 存在性 preflight 必须选「对不存在的 pane 会明确报错」的探针，且按 **stdout 与 stderr 合并文本**判定**（诊断文本可能只出现在 stderr——zellij 实测即如此；transport 中立表述；zellij 侧的具体裁定见下「参考 adapter」段）：**禁用**「对不存在的 pane 静默返回空」的读屏类命令作存在性判据（会得**假阳性**：把不存在的 pane 认作存在）；且**不得把退出码当作成功依据**——复用器可能对「pane 不存在」也返回 rc=0（zellij 六格实测里四格如此）。反向也不成立：探针对不存在的 pane 可能返回非零，但**不得**据此把非零当拒绝依据，见下「参考 adapter」段那条未解决矛盾。存在性 preflight 只解决**寻址**，本身**不是**送达证据（规则 3 不变）。
   - **「按合并文本判定、不靠 rc」不只适用于探针，也适用于注入与提交命令本身**：复用器对「目标 session 名不存在」也可能 **rc=0，而说明只出现在 stderr（stdout 里甚至装的是正常内容，如 session 列表）**（实测文本见下「参考 adapter」段的 zellij 裁定）。⇒ 调用方若按 `$?` 判成功，会把「整条命令打进虚空」读成「已发出」。
   - **最坏情形：连 stdout 判定都救不了** —— **session 存在、但 pane 不存在**时，注入命令可能 **rc=0 且 stdout 与 stderr 两条流全空**（zellij 实测，见下）。这一格没有任何事后文本可依据。⇒ **本规则的存在性 preflight 不是优化，而是唯一能在注入前发现该情形的手段**（会报错的探针至少会打印 not found）；一旦注入已经发出，唯一判据只剩规则 3 的**送达证据（nonce）**。
     - **该最坏格是 per-复用器的，不是通则 —— 在 tmux 上它不存在（实测）**：同样处境（pane 不存在）下 tmux 的注入命令自身 **rc=1 + `can't find pane:` 文本**，事后有文本可判。⇒ 对 tmux 而言，上一条「preflight 是唯一事前手段」的**理由**不成立，事前 preflight 的效力**从**「唯一能发现该情形的手段」**降为**「省一次无效注入的优化」：即规则 5 的事前 preflight 在 tmux 上从**必需**降为**优化**。
     - **⚠️ 但降级只写进规范、不得写进代码**（两条理由，缺一条这个降级就会变成一个 bug）：① 契约是 **transport 中立**的，「先验存在性再注入」这一形状对所有 transport 一致，按复用器开关 preflight 等于把复用器名重新硬编回路由层（正是 ADR-0007 要拆掉的东西）；② 降级**只对 tmux 成立**，且它成立的依据是一次 detached-server 实测，不是一条跨版本承诺。⇒ **adapter 在任何 transport 上都照跑 preflight**（有测试钉住路由层不含复用器名）；本条降级的用途是判定优先级——tmux 侧不必再把 preflight 当成不可省的安全垫来论证，而不是允许省掉它。
   - **「fail closed」必须连相位一起写，否则它是歧义的**（「拒绝了」没说清**目标 pane 有没有已经被写入**）：
     | 相位 | 处置 | 结果值 | 退出码 |
     |---|---|---|---|
     | 首次规划即 submit 态 unknown | **零 pane 命令** | `pre-injection-rejected`（`submit_action=none-pre-injection`、`retry_safe=true`）| 非零 |
     | 文本已写入 pane 后刷新为 unknown | **不发任何提交键** | `composer-unsubmitted` | 非零 |
     | 首次 Enter 后 submit 态变 active/unknown | **不补第二次 Enter** | `submit-unverified` | — |
     | 写入/提交命令非零或超时 | 保留 nonce + 失败相位，明确禁止盲目重投 | `write-unverified` / `submit-command-unverified` | 非零 |
   - **本规则只管 pane 存在性，不覆盖「`pane_ref.session` 腐烂」**：复用器 session **改名**后，据启动时环境快照推断出的 `pane_ref.session` 即失效（复用器把 session 名注入子进程环境时是**启动时快照**，改名不回写已运行的进程），且因上一条会**静默成功**——信封喷进虚空。故**换复用器或改名后，所有既有 `pane_ref` 必须整条重建，不能只改 `multiplexer` 字段**。（证据等级：**下游实测，上游未独立复现**。）
6. **发送侧能力检查（发之前先问「我投得进去吗」）**：发送方必须校验**本次路由实际要用的**那条投递能力**现在还在**——**走 pane 就校验 pane 侧能力（复用器 CLI + 目标 pane 存在，按规则 5），走 resume 才校验 resume 侧 CLI**；不得为了「看起来更严格」去校验本次不用的能力（那只会在无关缺失时误拒）。
   - 校验不过、或**推不出任何可用的 operational 路由** ⇒ 报 **`no-operational-route`** 且**非零退出**。
   - **`no-operational-route` 与规则 4 的每一个 `*-unverified` 语义必须分开**：前者是「**没发出去**」（发送侧前提不成立，重试是安全且必要的），后者是「**发了但没验到**」（可能已送达，盲目重发会重复入队，见规则 2）。把二者混成一个状态，调用方就无法判断该不该重发。
     - **与 `pre-injection-rejected` 也须分开**（两者都「没发出去」且 `retry_safe=true`，但**修法不同**）：`no-operational-route` = **路由本身坏了**（改修路由/重建 `pane_ref`）；`pre-injection-rejected` = 路由没问题，只是**目标 submit 态此刻读不出**（重新读状态即可）。混成一格会把「去修 pane_ref」和「过一会再读」压成同一个建议。退出码也应可区分。
   - **禁止静默回落到 `claude -p --resume`**：pane 路由不可用时悄悄改走 resume，会把「定向注入到活 TUI」换成「往会话文件追加、回复走调用方 stdout、对方界面上看不见」（§3 末 NOTE），且**代价与语义都变了却没人被告知**。要走 resume 必须是**显式选择**（调用方指定或配置声明），不是失败兜底。
   - **对称性论证（这是补对称，不是新原则）**：adapter 对 codex 分支**早已**明确拒绝——活 Codex TUI 而无 `pane_ref` 时直接报错，不去猜一条更差的路；而 claude-code 分支在同样处境下却**静默**回落 `claude -p --resume`。同一处境、两个 brand 两种行为，本规则把 claude-code 拉回与 codex 一致的 fail-closed 形状。
7. **resume transport 不得握有目标 turn 的生杀权**（本条与「resume 是否显式 opt-in」**正交**：opt-in 只改「谁来选这条路」，不改选中之后谁掌握它的生命周期）：`codex exec resume` / `claude -p --resume` 的进程承载目标**整个 turn**，不是一条有界的「写消息」命令。把它跑在发送方的 timeout 之下，等于**让发送方的耐心成为目标的 deadline**——一次发送侧观察超时会 SIGKILL 一个正常工作的 runner，中断一个可能**已经写过文件、已经调用过外部系统**的 turn。
   - **必须以独立 process session（detached）启动，并断开发送方 stdin**；`--timeout` 只限制**本次 nonce 观察窗**，观察结束**不得** terminate/kill runner。
   - **runner 的输出不得接管道**：被放弃的 runner 若管道缓冲写满，会**卡在目标的 turn 里面**——那是同一类 bug 的更安静版本。落到文件（或等价的非阻塞去处）；**也不该直接丢弃**，因为 `-p` 形态下 runner 的 stdout 是目标回复**唯一**出现的地方。未在观察窗内退出时，须把该输出位置**如实报出**。
   - 结果值域：nonce 命中 = `delivered`（**仍只证明 transport entry**，须同时标 `task_completion=unverified`）；观察窗结束但 runner 仍活 = `resume-started-unverified`；runner 在 nonce 命中前退出 = `resume-exited-unverified`。三者 `retry_safe` 均为 false。
   - **runner 退出（哪怕 rc=0）不证明零副作用**：turn 可能已读写或调用外部系统，调用方须先查 durable 产物 / peer ACK 再决定是否重跑。
8. **接收侧 submit-ack 握手（因果判据 · 降级的前置条件）**：规则 3 的 nonce 判据是**旁观**——发送方去翻对方 transcript。它有两个已实测的局限：①它落后于目标 CLI 自己的落盘（形态 4：1 秒窗口把已送达读成未验证，并**触发了一次重复提交**）；②它**分不出**「文字堆在 composer 从未提交」与「已提交但未落盘」，而前者是 human 报告的当前最大痛点。⇒ 契约新增一条**接收侧**判据：目标 CLI 的「用户提交了一条 prompt」钩子，**只在真的提交时触发**，故它是**因果**判据。
   - **两者并存、不互斥，各证明不同的一件事**（把它们合成一个「送达」布尔值会丢掉正是要用的那个区分）：

     | 判据 | 性质 | 证明什么 | 不证明什么 |
     |---|---|---|---|
     | **submit-ack**（接收侧钩子写的记录） | **因果** | 这个 nonce **被提交了**（钩子只在真提交时触发） | 不证明它已进转录、已被处理、已被理解 |
     | **transcript nonce**（规则 3） | **旁观** | 这个信封**进了目标的会话记录** | 不证明它是**被提交**的（重写/compact 后的全文命中亦算，见规则 3） |

   - **两者不一致时怎么读（规范性）**：

     | ack | transcript nonce | 读作 | 调用方动作 |
     |---|---|---|---|
     | 有 | 有 | 已提交且已落盘 | 等语义 peer ACK |
     | **有** | **无** | **已提交、尚未落盘**（正是形态 4 那一格，现在有正面证据了） | **不得重发、不得降级**；等落盘或等 peer ACK |
     | 无 | 有 | 进了转录但本仓没有 ack（多半是接收侧钩子未装，见下） | 按 `delivered` 读；**别据「无 ack」反推有问题** |
     | 无 | 无 | **未确认**（**不是**未提交） | 见下条：不得据此断言未提交 |

   - **⚠️ ack 缺失 ≠ 未提交 —— 本条是本节最重要的 fail-safe 方向，方向选在这一侧是有理由的，不是保守习惯。** ack 可能因为与「目标有没有提交」**完全无关**的原因而缺失：接收侧钩子从未安装；`settings.json` 被产品仓 git 跟踪导致 `trellis init -y` **静默跳过**整个 hook 安装（`ADOPT.md` 已记这个坑，且 init **不报错**）；接收仓未铺 ack 模块；ack 写入本身失败（磁盘/权限）。⇒ **ack 缺失只能降级为「未确认」（`unconfirmed`），不得断言「未提交」。**
     - **为什么方向必须是这一侧**：两个方向的错误代价**不对称**。误报「未确认」的代价是**多等一会、少一次降级**（有界，且没有第三方承担）；误报「未提交」的代价是**触发能力阶梯降级 ⇒ 换一条手段再投一遍 ⇒ 目标收到两份同样的指令**——那正是规则 2 与阶梯纪律 1 要防的事，且它是**静默**的（没有任何一方会收到信号）。按「一个能被看见的失败恒优于一个看不见的成功」，方向只能选在「未确认」这一侧。
     - **推论（写给阶梯实现者）**：ack **只能用来阻止降级，不能用来触发降级**。「本级已确认失败」这个降级前置条件，**不能**由「没读到 ack」满足。
   - **对规则 4 七值结果模型的影响（ack 只做单向修正）**：
     - **可因 ack 而升级**：`submit-unverified` / `queued-for-next-turn` / `submit-command-unverified` / `write-unverified` —— 有 ack ⇒ 该信封**确实被提交了**，这几格的「没验到」被正面证据推翻，处置一律变为「等落盘 / 等 peer ACK」，**禁止重发**。
     - **可因 ack 而被证伪的一格**：`composer-unsubmitted` 的语义是「文本已写入、**未发任何键**」。它与「被提交」在逻辑上互斥 ⇒ 若该 nonce 竟有 ack，说明**发送侧的相位判断错了**（例如人手动按了提交键）。这一格出现 ack 属**矛盾**，应如实报出并按「已提交」处置（**不得**按 `composer-unsubmitted` 的建议去「恢复既有 composer」——那会得到重复文本）。
     - **`composer-unsubmitted` 与 `submit-unverified` 的区分从此有了正面证据**：此前两者都只是「没验到」的不同相位描述（发送侧自述做过什么），无任何接收侧证据；现在 `submit-unverified` + 有 ack ⇒ 确已提交，`submit-unverified` + 无 ack ⇒ 仍是**未确认**（**不是** `composer-unsubmitted`）。
     - **不得因 ack 而降级任何一格，也不得新增 `not-submitted` 之类的值**（值域里没有它，正是上一条 fail-safe 的机械落点）。
   - **ack 表的形状（规范性）**：全局单份、**append-only、一行一条 JSON**（多个 ATUI 并发写，read-modify-write 会丢记录）；位置 `~/.arborist/submit-acks.jsonl`，与 `focus-intrusion.jsonl` 同一命名与权限风格（**新建时** 0600；**既有 mode 保留不动**——收紧别人的运行时文件权限是独立授权范围，不是写入的副作用）。**不得含消息正文**（隐私 + 体积），只存能证明「这个 nonce 被提交了」的最小集。字段：

     | 字段 | 为什么需要它 |
     |---|---|
     | `ack_version` | 记录 schema 版本；读者遇未知版本应**跳过**而非猜 |
     | `nonce` | **与发送侧结果的唯一 join key**（per-send 唯一，故命中即本次） |
     | `acked_at` | ISO8601 **带时区**——跨机比较需要偏移；也用于与发送侧的观察窗对时 |
     | `protocol` | 信封协议版本（`ARBORIST-DIRECT:v1`），使未来换信封格式时旧记录仍可判读 |
     | `receiver_brand` | 哪个 brand 的钩子写的。与 [ADR-0006](./decisions/0006-runtime-brand-is-routing-authority.md) 一致；也是「这个 brand 的钩子确实装上了」的唯一证据列 |
     | `receiver_agent` | 接收方注册表 leaf 名（按 `session_id` 反查；未登记 ⇒ `null`）——让 ack 能对回注册表 |
     | `receiver_project_path` / `receiver_project_id` | 接收方项目。`project_id` **由注册表 validator 那一份实现计算**，取不到即 `null`；**不得另写一套算法**（§2.3：两套派生算法必然让同一仓裂成两个 id） |
     | `receiver_session_id` | 哪个**会话**提交的——注册表主键，比 agent 名更硬 |
     | `hook_event` | 哪个钩子事件产生了本条，使记录可溯源到具体钩子 |
     | `envelope_header` | 提交内容里**匹配到的信封头字段**（`from` / `from_brand` / `to` / `provenance`）——这是**钩子自己能证明的东西**，也让读者区分「正是那封」与「另一封恰好带 nonce 的信」。**扫描在信封头处终止，正文结构上进不来** |

     - **未知一律记 `null`，不省略字段**：缺省字段与「钩子证不出这一项」不可区分（同焦点观测那节的「未知不得记成没发生」）。
   - **接口（规范性 · 发送侧据此接线）**：`scripts/agenttui_submit_ack.py`（adopt 铺到 `<repo>/.trellis/scripts/`）。
     - 接收侧：`record_submit_ack(payload, *, receiver_brand=None, log_path=None) -> (records, warnings)`；CLI `record`（钩子 payload 走 stdin）。
     - 发送侧：`lookup_ack(nonce, log_path=None) -> dict`（含 `ack_status` ∈ {`acked`, `unconfirmed`}、`ack_count`、`acks`、`table_readable`、`reading_guidance`）与 `read_acks(nonce, log_path=None) -> list`（表整体读不到时 raise `AckTableUnreadable`——「我没法看」必须与「我看了没有」可区分）；CLI `lookup --nonce`，退出码 **0 = `acked`** / **1 = `unconfirmed`（缺 ack）** / **3 = 表读不到（同样是 `unconfirmed`）**；`print-path` 打印表位置。
     - **`record` 的两条硬约束**（都有机械测试钉住）：**恒退出 0** 且 **stdout 恒为空**。理由不是洁癖：提交钩子非零退出会**阻断真人的一次提交**，而某些 brand 会把钩子 stdout 当作注入上下文 ⇒ 一次误 print 就改变了目标看到的东西。所有失败降级为 stderr 警告。
   - **接线形态（两种，优先第一种）**：①**同级追加一条钩子命令**（既有钩子脚本**零改动**）；②把片段粘进既有钩子脚本。**优先 ① 的理由是判据层面的**：按 [verification-and-gates「新增的观测动作必须先证明它不扰动被观测者」](./verification-and-gates.md#新增的观测动作必须先证明它不扰动被观测者)，形态 ① 里既有脚本**字节层面未变**，该证明是**结构性**的；形态 ② 只能靠测试证明，而测试只覆盖被测到的那些输出。两形态的模板与逐 brand 接线见 Arborist 源树 `overlay/hook-templates/submit-ack/`（与 `overlay/workflow-customization.md` 同类：**adopter 手工接线物，不铺进产品仓**——接线要改的是 host 的 hook 配置，铺一份拷贝进来只会多一处会腐烂的副本）。
     - **ack 记录**是新增的观测动作，其不扰动性另有两条机械证明：`record` 不执行任何外部命令、不读屏、不碰目标 pane（它跑在**接收侧自己的**钩子里，与投递路径无交集）；形态 ② 的片段有**差分测试**——同一个钩子 fixture 粘与不粘，stdout 与退出码逐字节相同。
   - **⚠️ 发送侧消费尚未接线（截至本节写就时）**：上面的**读取接口已存在并有测试**，但随发 `scripts/agenttui.py` **尚未**调用它——即投递结果里还**没有** ack 相关字段，七值升级也**还没有**在代码里发生。本条按本节末「凡未实现处必须逐条标注」的纪律记在此处，**不得**把它读成「ack 已并入投递判定」。

**投递前置校验（统一契约：动手前先验前提，验不过就拒绝，不猜、不静默降级）**：上面规则 5/6 各管一半前提；两半共用**同一形状**，故在此收成**一条**契约，避免各处再写各自的临时门。

| 半边 | 问题 | 硬规则 | 拒绝时 |
|---|---|---|---|
| **路径推导** | 「我该往哪写？」 | 由脚本位置反推仓根（`__file__` 上溯 N 级那一族做法）**必须校验推导结果真是项目仓**——目标目录须含 `.trellis/` 或 `.git/`。推不出、或推出来的不是项目仓 ⇒ 拒绝；**绝不 `mkdir` 造一个假注册表**（`mkdir -p` 恰好会把错位置造得「像是本来就有」）。自登记时目标 `.arborist/` 不存在的处置**不在此复述**，见 §5 第 8 点（fail-closed 报 `half-registered`、不得静默上移父目录）。 | 非零退出 + 明确说出「推导出的路径不是项目仓」 |
| **路由推导** | 「我投得进去吗？」 | 推不出可达路由即 fail-closed（规则 6）；pane 存在性用**会报错**的探针并**解析 stdout+stderr 合并文本**（规则 5），禁用「对不存在 pane 静默返回空 + rc=0」的读屏类命令；**路由与传输必须分层**——preflight 与路由判据定义在「**本次路由所需能力**」这一抽象层上，**不得**把某个具体复用器的名字/命令硬编进路由判定（那样每换一次复用器都要改路由代码，而契约本该只换 adapter）。 | `no-operational-route` + 非零退出（**≠** 规则 4 的任何 `*-unverified`）|

- **两半均已在随发 adapter 落地**（2026-07-30；此前为「规范已落、实现未收敛」）：`scripts/agenttui.py` ①推导出的仓根须含 `.trellis/` 或 `.git/`，否则非零退出拒绝（且**不创建**任何目录），可用 `--repo` 显式指定；②路由改为**能力层**判定——`build_route` 只问「这个 `pane_ref` 有无已注册 transport / 该 transport 可用吗 / 目标 pane 存在吗」，具体复用器命令收在 `PaneTransport` 子类里，复用器名→transport 的映射只在一处注册表；③有发送侧能力检查与 `no-operational-route`（非零退出）。**仍有未实现项**（规则 3 的双指纹/证据等级），逐条见下「随发 adapter 的契约缺口」。

- **参考 adapter（随发 · opt-in · 二选一别混）**：
  - `scripts/agenttui.py`（adopt 铺到 `<repo>/.trellis/scripts/`）是本契约的 **operational 参考实现**——按注册表 `pane_ref` 经 **transport 抽象**寻址注入（随发注册了**两个并存**的 transport：`zellij` 与 `tmux`，各自的命令行细节只在各自子类内部，见下两张读数总表；选哪个由 `pane_ref.multiplexer` 决定，迁移逐 pane 进行）；调用见工具表条目 `agenttui-direct`（`python3 .trellis/scripts/agenttui.py {status|send|heartbeat|stop}`，发前可 `--dry-run` 验路由——dry-run **不跑**存在性探针，因为探针会抢焦点）。**operational 投递一律走它**（而非下面那个演示脚本）。
    - **调用方须知的三处行为**（按规则 6 落地，非默认兜底）：①目标无可达 pane 时**不再**自动改走 `claude -p --resume`——要走 resume 必须显式加 `--allow-resume`，否则报 `no-operational-route` 并**非零退出**；②`no-operational-route` 的结构化输出带 `reason` / `detail` / `remedy` / `sent=false` / `retry_safe=true`，与规则 4 的各 `*-unverified`（`sent=true` / `retry_safe=false`）**字面区分**——照它判断该不该重发；③**pane 结果值域是规则 4 的七值**（不再有单一的 `queued-unverified`），每条结果带 `submit_action` / `recommended_action` / `verification_guidance`；退出码：`delivered` 与 `queued-for-next-turn` = 0（后者是契约预期状态，不是错误），`composer-unsubmitted` / `write-unverified` / `submit-command-unverified` = 2，`pre-injection-rejected` = 4，`no-operational-route` = 3。**`submit-unverified` 退出 0**（与旧 `queued-unverified` 一致，避免改变既有调用方的成败判断）——它的「不确定」信息在 JSON 里，别拿退出码当送达证据。
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
  - **tmux 侧读数总表（第二个随发 transport · 对应契约规则 5）——附原始读数，勿只记结论**。下表每格都是同一版本（`tmux 3.4`）上的直接观测，**rc / 输出分开记**；**采集边界（先读，否则会高估这份证据）**：全部读数取自一个**私有 socket 的 detached server**（`tmux -f /dev/null -L <自取名>`，用完 `kill-server`），**未触碰**任何真人终端、未触碰默认 socket。故「活动 pane / 活动 window 未变」是**服务端状态层**的读数，**不是**「一个真人正看着的附着 client 未被扰动」——后者需 human smoke test，**本表不声称已验证**。

    | 命令与情形 | rc | 输出 |
    |---|---|---|
    | `send-keys -t <存在的 pane> -l <text>`（目标**不在活动 window 内**）| `0` | 空；目标**完整收到**，其它 pane **零串投**；session 活动 window 与各 pane `pane_active` 前后**完全未变** |
    | `send-keys -t <不存在> -l X` | **`1`** | `can't find pane: <目标>` |
    | `list-panes -t <不存在>` | **`1`** | `can't find pane: <目标>` |
    | `capture-pane -p -t <不存在>` | **`1`** | `can't find pane: <目标>` |
    | `has-session -t <不存在>` | **`1`** | `can't find session: <名>` |
    | 连不上的 socket | **`1`** | `error connecting to <socket 路径>` |
    | **`display-message -p -t <不存在> '#{pane_id}'`** | **`0`** | **静默回落到「当前 pane」的属性**（输出是当前 pane 的值，不是错误）|
    | `send-keys -l <4016 字节一次性写入>` | `0` | 目标**逐字节完整**（长度与内容全等）|
    | `load-buffer` + `paste-buffer -p -t <pane>` | `0` | 目标收到完整内容（bracketed-paste 官方一等通路）|

    由此得到四条结论：

    1. **`send-keys -t` 是真定向、跨 window 生效、且零聚焦副作用** ⇒ **tmux 侧的存在性探针不必是聚焦命令**，这是它相对 zellij 的**实质**优势（zellij 的 `write-chars --pane-id` 跨 tab 不生效、必须先 `focus-pane-id`，见下条）。证据等级：**本机实测（detached server，服务端状态层）+ 官方文档**（`send-keys` 文档未记任何选择/聚焦副作用，而改变活动 pane 是 `select-pane` 的显式职责）。
    2. **存在性探针用 `list-panes -t` 或 `capture-pane -t`**（不存在 ⇒ rc=1 + `can't find pane:` 文本）。判据仍按 **stdout+stderr 合并文本**（与 zellij 侧同一条纪律）——tmux 的 rc 可信度确实更高，但**不得**把 rc 当唯一判据，理由见下一条。
    3. **`display-message -p -t <不存在>` 严禁用作存在性判据**：**rc=0 且静默回落到当前 pane** ⇒ 用它做判据必然**假阳性**（把不存在的 pane 认作存在），且更坏——回落来的属性属于**另一个** pane，读起来像一次成功。
    4. **写入层不再是可疑项**：4016 字节一次 `send-keys -l` 逐字节完整 ⇒ 形态 3（长文本损坏）在 tmux 的**写入层**不复现。这**不**证明 zellij 写入层是元凶（zellij 侧未测），只把它从可疑名单里挪走。

    > **通则（这是本节最该被记住的一条，比两张表都重要）：每种复用器都有一个「看起来最自然的读属性命令」，而它恰恰是**静默回落、rc=0** 的那个。** 两次实测已并列证明：
    >
    > | 复用器 | 那条「最自然」的命令 | 读数 | 为什么危险 |
    > |---|---|---|---|
    > | zellij | `action dump-screen -p … --pane-id <不存在>` | **rc=0 + 空** | 空输出被读成「pane 在、只是屏幕空」⇒ 假阳性 |
    > | tmux | `display-message -p -t <不存在> '#{…}'` | **rc=0 + 当前 pane 的属性** | 有输出、格式正确、**属于别的 pane** ⇒ 假阳性，且比空输出更难怀疑 |
    >
    > ⇒ **换复用器时必须重新逐格实测，不能假定同名命令同语义**（连「读一个 pane 的属性」这种同名同义的动作，两家的失败语义都相反）。这也是为什么本 guide 对每个 transport 各存一张原始读数表，而不是把结论合成一段通用描述——**合成会把恰恰相反的那一格抹平**。
    >
    > 推论（授予证据标签的纪律，见上文 zellij 段末）：上表两行都附了 rc 与输出原文，故可标「已实测」；任何**只有结论、没有读数**的复用器条目只能标「已声称」，不得据以改判据。

    - **tmux 侧对 `pane_ref` 腐烂面的影响（比「少一个 bug」更结构性）**：tmux 的 pane id 形如 `%N`，官方文档明确其**在该 pane 生命期内不变**，且**免疫 window/session 改名与索引重排**（实测：`rename-session` 后 `send-keys -t %N` 仍解析成功）。⇒ 与 zellij 侧「`pane_ref.session` 会因改名腐烂、且腐烂后**静默**投空」形成对比：tmux 的寻址锚在终身不变的 id 上，**不锚在名字上**。
      - 但随发 adapter **仍然核对** `pane_ref.session`（探针读回该 pane 实际所属 session 名，不符即拒并要求整条重建）。**这不是多余**：一个字段与现实不符的 `pane_ref` 已经腐烂，而「照 id 投得进去」正是让腐烂**继续隐身**的原因；核对把改名后果从**静默投错**变成**响亮拒绝**（`no-operational-route`），符合本 guide「一个能被看见的失败恒优于一个看不见的成功」。
      - **⚠️ 该核对不是跨 server 的证明**：两个不同 tmux server 可以各有同名 session 与同号 pane，核对不排除这种撞车。**对因已落地**：`pane_ref.socket`（§2.2）—— 探针、写入、提交**三条命令一律寻址该 socket**，故存在性 preflight 问的是「本次投递要用的那个 server 上的那个 pane」，而不是另一个恰好有同号 pane 的 server。缺省 socket 时三条命令与本字段出现之前**逐字相同**（有测试钉住）。残留缺口（同一 server 的两种拼写、以及不认识该字段的 transport）见下方缺口清单。
    - **自识别句柄**：tmux 把 pane id 注入子进程环境变量 **`TMUX_PANE`**（`$TMUX` 第一段是 socket 路径），⇒ 被投递方可**权威自报**自己是哪个 pane，不必像现行 zellij 流程那样按 `tab_name`+`cwd`+`command` 组合去**猜**自己是哪个 pane（那正是 `pane-ref-conflict` 一族的成因之一）。对应 zellij 的 `ZELLIJ_SESSION_NAME` + pane id 组合。
  - `scripts/agenttui_deliver_zellij.py` 是**契约的 seam 化演示，非 operational**：默认注入器**收 `pane_ref` 却不定向、只写当前焦点 pane**，跨 session / 跨 brand（目标 pane ≠ 焦点 pane）必投错——**未补 `--pane-id` 前不得当跨 pane operational 路**（下游把它误当正道，正是跨 brand 发信「表现不佳 / 不稳定」的根因）。
- **⚠️ 随发 adapter 的契约缺口（截至 2026-08-05，必须可见——契约不得被读成「代码已做到」）**：随发 `scripts/agenttui.py` **尚未**实现下列契约条款，port 任务另行追踪；在它补齐前，调用方须自行承担对应风险：
  - **规则 3 的 inode+size 双指纹与全文降级**：**仍未实现**——只记 size 作起始偏移，且当**现 size 小于该偏移**（= 文件被重写/截短）时**直接判未命中** ⇒ 目标做过 compact / 会话文件被重写时返回**假阴性**（现在这个假阴性落在 `submit-unverified` 那一格；重发风险，见规则 2）。
  - **规则 3 的证据等级标注**：**仍未实现**——命中只记单一 `envelope-nonce-found`，不区分 `…-after-boundary` / `…-fullfile`，调用方读不出证据强度。
  - **五种形态的读屏分类器（含 `unclassified` 一格与其原始签名归档）**：**仍未实现**——adapter 目前**不做任何读屏分类**，也不写 `unclassified` 档案。它能区分的只是**已执行的动作**（规则 4 的七值：文本有没有写、键有没有按、命令有没有回话、nonce 有没有出现），**不能**区分「文本到了 composer 但被截断」（形态 3）与「目标要求重新登录」（形态 2）——这两格在规则 4 的值域里都表现为 `submit-unverified`。⇒ 下表的形态**只是诊断词汇表，不是 adapter 的输出值域**；形态 2 的模式常量（`provenance: single-observation`）在代码里**尚不存在**。
  - **形态 3 的对因修法只覆盖「写入方式」这一半**：bracketed-paste 成帧已实现（见下方 ✅），但它**只**针对「高速按键流被当成 paste burst、Enter 被吞成换行」这一机制；**不声称**覆盖形态 1（沙箱）与形态 2（认证），也不声称覆盖长文本在 composer 侧的其它损坏形式。
  - **paste 成帧只对 codex 开**：claude-code 未开，因为**没有实测**支持在那里成帧（同名 ≠ 同能力）。这是**证据缺口，不是契约缺口**——规则 1 要求的是「按 brand 白名单」，而白名单当前只有一格。
  - **socket 归一化是纯字面的 ⇒ 一个 server 写成两种拼写时，唯一性检查漏报**（2026-08-06 随 socket 维度落地一并记；**这是残留缺口，不是设计意图**）：`pane_ref.socket` 已进 schema 与唯一性 key（见 §2.2 / §2.2.1），但缺省与显式值的等价判定**只做字面归一化**（空/缺省/`default` 三者等价）。**socket 路径与 socket 名不互相解析** —— 把名解析成路径需要「写 leaf 那一方」的 socket 目录与 uid，而 leaf 里没有这两项 ⇒ 同一个 server 一处写名、另一处写路径时，validator 判为两个 server、**漏报**一次真冲突。⇒ 处置是**约定**：同一台机器上对同一 server 只用一种拼写（推荐 `-L` 名）。**方向说明**：本缺口的失败方向是漏报（不是假冲突），故它**不会**让 validator 变吵；代价是那一格误投要靠约定而非机械门挡住。
  - **不认识 socket 的 transport 会静默忽略它 —— 无机械检查**：`socket` 只对「pane id 仅 server 内唯一」的 transport 有意义；若有人给 `multiplexer=zellij` 的 leaf 写上 `socket`，该 transport 的命令构造**不读它**，字段就成了一个看起来生效、实际无效的装饰。**当前既无 validator 检查、也无写入侧拒绝**（要做得先给 transport 声明「我认哪些 `pane_ref` 字段」，那会把字段值域接进路由层，须与 ADR-0007 的 transport 中立一起设计）。⇒ 在它落地前，`socket` 只在 tmux leaf 上写。
  - **✅ 规则 8 的发送侧消费已实现**（2026-08-06）：投递后查 ack 表，结果里带 `ack_status` / `ack_count` / `ack_detail`（**成功路径也带** —— 这一对证据的价值在于**组合**）。落地的四格判读与**唯一一处行为改变**：

    | ack | transcript nonce | 判读 | 行为 |
    |---|---|---|---|
    | 有 | 有 | `delivered`（双证据） | 正常 |
    | **有** | **无** | **已提交、尚未落盘** | **抑制那一次重发** ← 唯一的行为改变，也是 ack 存在的全部理由 |
    | 无 | 有 | `delivered`（钩子可能未装） | 正常 |
    | 无 | 无 | `unconfirmed` | 保留既有的**单次**重发 |

    - **`table-unreadable` 与 `unconfirmed` 是两个值，不得合并**：「我没能看」与「我看了、没有」允许的动作不同。ack 模块不存在时读作 `table-unreadable`（该设施可能只是没被采纳，这**不是**关于目标行为的证据）。
    - **ack 缺失一律不阻止既有重发**：fail-safe 方向是单侧的 —— 缺失只能降级为「未确认」，既不得断言「未提交」，也不得据此**禁止**那次已被契约允许的重发。
    - **查表失败绝不让投递失败**（异常一律吞掉并降级为 `table-unreadable` + stderr 警告）：**观测不得改变被观测的交付**。
    - 重发之后**重读一次** ack，否则最终报告会用一个陈旧读数、低估已知信息。
  - **⚠️ 跨项目投递：靠「自声明镜像」承载，且镜像的 runtime 曾是陈旧的（2026-08-06 修一半）** —— 原文这一格写的是「随发 adapter 不支持跨项目投递 ⇒ 整套契约在跨项目场景下全部失效」。**据实改写**：`load_agent(repo, name)` 仍只吃**一个**仓根（sender 与 target 都从它加载），跨项目投递的**既有承载方式**是 §2.2.2 的**自声明镜像** —— 在发送方那个仓里也给目标建一份 leaf。走这条路时**全部契约照旧生效**（规则 5 preflight、规则 6 能力检查、七值结果模型、规则 8 ack、成帧写入、焦点记录），因为它走的就是同一个 adapter。

    **逐项状态（勿笼统读成「已满足」）**：

    | 分项 | 状态 |
    |---|---|
    | 镜像的 runtime 半边改从 `home_registry` 读（权威侧） | **已实现**（§2.2.2 契约 1） |
    | `home_registry` 路径/同名/同项目校验 + 不追镜像链 | **已实现**（契约 2） |
    | 校验不过时 **fail closed**、不回落到镜像那份陈旧拷贝 | **已实现**（契约 3；理由 = §2.2.1 后果分级「误投 > 不可达」） |
    | 镜像陈旧时在投递路径上**大声报出** | **已实现**（契约 4：投递 payload 的 `warnings` + `target_mirror_stale_fields` + `target_runtime_authority`，stderr 同步打印） |
    | validator 报镜像腐烂（三态严重度分级） | **已实现** = 检查 7（§4） |
    | **`load_agent` 直接跨仓寻址**（无需在本仓建镜像 leaf） | **未实现** ⇒ 跨项目投递**仍要求先有人类授权的镜像 leaf**；没有镜像 ⇒ 没有可达路由，只能退回手工 raw 注入（见下方「过渡期的唯一诚实处置」） |
    | 三项唯一性检查对镜像**降级为 info** | **未实现**（见 §2.2.1 那张实况表）⇒ 每条镜像仍会各报一次已知假阳性 |
    | 镜像 leaf 的**自动建立/回收** | **未实现**，且刻意不做：建镜像 = 让另一个仓获得直投本 agent 的能力，属人类授权项（`authorized_by` 就是为此存在） |
    | 镜像那份 runtime 拷贝的**自动同步** | **刻意不做**（不是缺口）：静默同步会掩盖「镜像正在腐烂」这个事实，而那个事实正是「每次投递读 home」的理由 |

    **原文那条归因仍然成立，且是这次修法的依据**：手工注入者**必须自己重新实现路由**，而契约有六条规则 ⇒ **那类错误是缺口的产物，不是疏忽的产物**。同理，镜像 runtime 的陈旧也不是「谁忘了同步」——它按构造必然发生，故修法是**在读侧改权威**，不是加一条「记得同步镜像」的纪律。

    > **原始归因（这决定修法，所以留档）**：已实测的一次跨项目投递里，投递方对一个空闲目标用了**入队键**而非提交键，违反规则 1。把它记成「**某人的路由错误**」是错的归因 —— 手工注入者**必须自己重新实现路由**（活性判定、brand 键映射、间隔、验证），而契约有六条规则，人在现场逐条正确实现的概率很低。⇒ **这类错误是缺口的产物，不是疏忽的产物。** 记成疏忽 ⇒ 下一个人照样犯；记成缺口 ⇒ 去补缺口。
    >
    > 同族通则见 [`verification-and-gates`](./verification-and-gates.md)：**没有执行者的门是装饰** —— 而这里更进一步：**有实现却对某一整类场景不可用的契约，等于在那一类场景里退化成装饰**，且退化是**静默**的（调用方看不到自己绕过了什么）。

    **过渡期的唯一诚实处置（仅适用于「目标在别的仓且本仓没有镜像 leaf」那一格 —— 有镜像时请走 adapter）**：跨项目投递前**明确记下自己绕过了哪些规则**，并**逐条手工执行**（至少：按目标真实活性选键、注入后**等 composer 就绪再提交**、验证 nonce 越界命中、失败不盲目重发）。**不得**因为「手工投递成功过」就认为契约已被满足。

  规范先于实现落定是**刻意**的（契约是判据、实现向它收敛）；但**凡未实现处必须像这样逐条标注**，不得笼统写成「参考 adapter 已满足上述契约」。

  > **通则：送达 ≠ 迁移完成（`delivery ≠ migration`）。** 一次投递成功、一个 adapter 被合并、一条契约被 accept —— 三者**都不是**「调用方已经在走这条契约」。本契约的执行者是**每一个调用方**，故「已迁移」是一个**逐调用方**的事实：只能靠**枚举全部调用方并分类**来声称，至少三类——**已走 adapter** / **仍在手工 raw 注入**（则按上面「过渡期的唯一诚实处置」逐条记下绕过了哪些规则）/ **无可达路由**（`no-operational-route`，须先补 registry 与 `pane_ref`）。⇒ **审计不完成，不得宣称同步/迁移完成**；拿一次成功的投递、一个 merge 或一条 accepted 规范去支撑「已迁移」，是用证明力更弱的东西冒充结论。
  >
  > 同族见 [`verification-and-gates`](./verification-and-gates.md#门的回归必须端到端且测试的结构必须与真实调用路径同构)：**制品到位 ≠ 路径生效**，merge 不等于门在真实调用路径上被证明会拦。两条的共同形状是把**一个更容易得到的读数**（合并了 / 投通了）读成**那个真正想要的结论**（全部调用方都受契约保护）。
- **✅ tmux transport 的两条缺口已由一次人机同场 smoke test 关闭（2026-08-06 实测）**——原文两条分别是「不抢焦点只证到服务端状态层、未证到附着 client」与「提交键语义未在真 ATUI 上验证」。测法与逐格读数：

  | 测项 | 读数 |
  |---|---|
  | **抢焦点（真人正在看的情况下）** | 目标 ATUI 住在人类**未在看**的那些 tab 里；投递前后**外层活动 tab 逐字未变**，两个目标 pane 的 active 标志亦未变 ⇒ **零焦点副作用**。这次是**附着 client 在场**下测的，不再是 detached server |
  | **提交键语义（两个 brand 各一次真 ATUI）** | 直发契约字节（`Enter` = `0x0d`）后，**两个 brand 的信封 nonce 都进了各自的会话记录** ⇒ 「Enter=13 这套契约在 tmux 下照旧」从推断升为**实测** |

  > ⚠️ **这次成功不得被读成「tmux 解决了 composer 不提交那个痛点」。** 变量没有控制在痛点条件上：本次是**短消息 + 目标 idle**，而这两项**此前已各自被证明是成功的充分条件**（同一现象在另一复用器上、短文本 + 足够窗口时也成功）。⇒ 本次只证「tmux 下提交键语义照旧」与「不抢焦点」，**未**证任何关于长文本/活跃目标的事。**本条不因后续任何实现改动而变为已验证**——加 socket 维度、改 launcher、加测试都不触及这个条件组合。
  >
  > **要把它变成已验证，重测必须同时满足下列条件（缺一条读数就不可用）**：
  >
  > | 条件 | 为什么缺它读数不可用 |
  > |---|---|
  > | **长信封**（量级取自形态 3 的历史观察：整段信而非短指针；写入层已单独测到 4016 字节完整，故门槛要**高于**已测量级才有增量） | 形态 3 的签名是「文本到了 composer 但被截断/未提交」，短文本按构造测不到它 |
  > | **目标处于活跃状态**（正在跑 turn，按契约走入队键而非立即提交） | idle 目标此前已被证明是成功的充分条件 ⇒ 在 idle 下成功不构成任何增量证据 |
  > | **逐字节比对**：把目标 composer/transcript 里的正文与源正文**逐字**比对，不是「看起来对」 | 形态 5 已证明「语法通顺而语义已损」不会被任何门发现；只有逐字比对能判截断/丢字符 |
  > | **构造侧先自校验**（发送前回读比对信封正文） | 否则一次「缺字」读数分不出是构造侧（形态 5）还是传输/composer 侧（形态 3） |
  > | **两条复用器各测一次**（同一长信封、同一活跃目标） | 只测 tmux 只能说「tmux 下没复现」，不能说「另一个是元凶」——zellij 写入层至今**未测** |
  >
  > **⚠️ 该重测需要一个真的活跃 ATUI 作目标，故它属于「验证需要人在场」那一族**：按上方那条方法论，应在**人本来就在场**时顺手做，不单独排期。

  > **顺带一条方法论**：这次能一次关掉两条缺口，靠的是人类**恰好已经起了真 ATUI**。此前这两条挂着「未验证」的真实原因不是难测，而是**测它需要打扰真人**——所以它们一直等在那里。⇒ 凡缺口的成因是「验证需要人在场」，应当在**人本来就在场**的时刻顺手清掉，而不是单独排期（单独排期的代价是打扰，于是被无限推迟）。

- **✅ 已收敛的条目（2026-07-30 实现，本清单据实改写；留档以便对照上面那两条仍缺的）**——同时列出**实现带来的已知代价**，别读成「无副作用」：
  - **规则 5 的存在性 preflight（解析合并文本）**：已实现——注入前用 `focus-pane-id` 探针并**按 stdout+stderr 合并文本**判 `Pane with id … not found` / `Session '…' not found`，**不把退出码当成功或拒绝依据**（原因见上方未解决矛盾）；探针失败即 `no-operational-route`、**零注入命令**。**禁用** `dump-screen -p`（对不存在 pane 静默返回空 + rc=0）作判据。
  - **`--pane-id` 前置 `focus-pane-id` 聚焦**：已实现，且**与上一条是同一个命令**——存在性探针本身就是聚焦命令，故跨 tab 投递前焦点必然已移到目标 pane。**代价照旧**：投递**抢焦点**，与人类同 session 操作结构性冲突（上文「已知架构局限」，未消除）；`--dry-run` 因此**不跑**探针（也就不做该次校验），输出里如实标注。
  - **规则 5 的「注入/提交命令也按 stdout 判定」**：已实现——注入与提交命令都按 stdout/stderr 文本判失败，退出码不作成功证据。**但最坏那格无解**：session 在、pane 不在时注入是 rc=0 + 两条流全空 ⇒ 代码**不得**据此判成功，判据只剩规则 3 的 nonce（提交命令被文本判失败时，因字节已发出，报 `submit-command-unverified` 而非 `no-operational-route`）。
  - **规则 6 的发送侧能力检查 + `no-operational-route`**：已实现——只校验**本次路由用得到**的能力（走 pane 校验 transport 可用 + pane 存在；走 resume 才 `which` 对应 resume CLI），无可用 operational 路由 ⇒ `no-operational-route` + 非零退出；claude-code 分支**不再静默回落** resume（与 codex 分支同形拒绝），resume 须 `--allow-resume` 显式选择。
  - **「投递前置校验」两半**：已实现——路径推导侧见上（仓根须含 `.trellis/` 或 `.git/`，拒绝时不创建任何目录）；路由推导侧改为能力层判定，具体复用器命令封在 transport 子类内、映射集中在一处注册表，故换复用器只加 transport、契约与路由代码不动。
  - **规则 1 的「可达态 / submit 态分离」+ 规则 4 的七值结果模型**（2026-08-05 上游自一个下游采纳仓 port）：已实现——Codex 的提交键改由**目标 transcript 的最新 turn-boundary 事件**决定（不再用新鲜度），settle 后按键前**再刷新一次**，未终止的 JSONL 尾记录按 unknown 处理；结果按已执行动作分七值并带 `submit_action` / `recommended_action` / `verification_guidance` / `retry_safe`。**`retry_safe=true` 仅两格**（`pre-injection-rejected`、`no-operational-route`），且有机械测试钉住这一点。**代价 / 边界**：①`pre-injection-rejected` 时**连 `--dry-run` 也拒绝**（不肯展示一个猜出来的键）；②转录里没有 `task_started`/`task_complete` 的 Codex 目标（例如极早期或异常 rollout）现在**投不出去**而不是猜 Enter——这是刻意的 fail-closed，但确实**收紧**了此前会「蒙一个键」的路径。
  - **规则 1 的 bracketed-paste 成帧（形态 3 的写入方式修法）**：已实现——**仅 codex**；契约层只表达「本次写入需成帧」这一能力意图，`ESC[200~`/`ESC[201~` 只出现在 transport 子类里（机械测试钉住路由层不含该机制）。**它不改路由、不改复用器选择、不改命令条数**——同一条写入命令，只是 payload 被包住。
  - **第二个 pane transport（`tmux`）与既有 `zellij` transport 并存**（2026-08-06）：已实现——**不是「迁移到 tmux」**，两者同时注册，`pane_ref.multiplexer` 决定用哪个，故既有 pane 可**逐个迁**、不必一次性切；契约与路由代码**一行未动**（这正是 ADR-0007 transport 中立要买的东西：换/加复用器 = 加一个子类 + 一条注册表项）。tmux 侧照实测实现：探针用 `list-panes -t`（**禁用** `display-message -p -t`，理由见上方通则表）、判据按 stdout+stderr 合并文本、寻址锚在终身不变的 `%N`、成帧复用基类 bracketed-paste 经 `send-keys -l` 写入、提交键直发契约字节（`-H`）。**代价 / 边界**：①「不抢焦点」只证到服务端状态层；②只支持默认 tmux server（`pane_ref` 无 socket 维度）；③提交键语义未在真 ATUI 上验证——三条都在上方缺口清单里逐条列出，**别读成「tmux 侧已完全可靠」**。（①③ 已于 2026-08-06 由一次人机同场 smoke test 关闭，见上方 ✅ 那条；② 已由 `pane_ref.socket` 关闭，见下条。）
  - **`pane_ref.socket`：pane 寻址补上 server 维度（2026-08-06）**——已实现：schema 加**可选** `socket` 字段（缺省 = 默认 server，故既有 `pane_ref` 命令行逐字不变）、tmux transport 的**三条命令**（探针 / 写入 / 提交）一律带 `-L <名>` 或 `-S <路径>`（按值自身形态判名或路径）、§2.2.1 唯一性 key 扩为四元组、validator 与该 key 同步。**它关掉的是一格静默误投**：pane id 只在单个 server 内唯一，同机多 server 时默认 server 上恰好有同号且同名 session 的 pane，就会每道检查全过而信封落进第三方 composer。**代价 / 边界**：①归一化是纯字面的（路径与名不互相解析）⇒ 同一 server 两种拼写会**漏报**冲突；②不认识该字段的 transport 会**静默忽略**它，且当前无机械检查——两条都在下方缺口清单里。**同时明确禁止**把 socket 塞进 `session` 字段（字段名与内容不符 = 埋雷），有测试钉住 session 字段只作 session 名核对。
  - **规则 7 的 resume 生命周期 detach**：已实现——runner 以独立 process session 启动、stdin 接 `DEVNULL`、输出落私有文件（**不接管道**，以免被放弃的 runner 写满缓冲卡在目标 turn 里），`--timeout` 只限制 nonce 观察窗，**代码里没有任何 kill/terminate/送信号路径**（机械测试钉住）；结果为 `delivered` / `resume-started-unverified` / `resume-exited-unverified`，附 `runner_pid` / `runner_state` / `runner_returncode` / `task_completion=unverified`。**代价**：runner 未在观察窗内退出时，它的输出不会出现在本次 stdout 上，只以 `runner_output_path` 报出位置（**该文件不会被本进程清理**——runner 还在写）。
- **五种「注册表看不出来的投不进 / 投不对」（全部已实测 · 一致性 validator 也查不出 · 别指望注册表告诉你 · 覆盖度的如实表述见本条末，勿写成「病因已覆盖」）**：注册表一致性（§2.2.1 / §4）能排除**归属错**与**寻址错**，但下面这些形态在注册表里**一模一样**——`state=active`、`pane_ref` 有效、`session_file` mtime 新鲜、一致性检查全绿——投递却到不了目的地，或**到了但不是你想说的话**：

  **读表前必读（一）—— 「读数」列写的是规则 4 展开前的粗读数，且它到七值的映射不是一对一。** 规则 4 现在把 pane 结果按**已执行动作**分成七值，但那**不是**病因分类：形态 2（认证失效）与形态 3（截断未提交）都落在 `submit-unverified` 那一格里，**adapter 分不开它们**（要分开必须读屏，而读屏分类器**尚未实现**，见上方缺口清单）。⇒ 拿到 `submit-unverified` 不等于知道自己在哪一格；本表的形态是**诊断词汇表**，规则 4 的七值是**adapter 的输出值域**，两者不可互相代入。

  **读表前必读（二）—— 分类的输入是「可观察签名」，不是底层病因。** 任何分类器（人或代码）**看不见**目标的鉴权状态、看不见沙箱边界、看不见 composer 内部；它只看见三类签名：**屏幕形态**（读屏文本）、**写入/提交命令的 stdout**、**transcript 里有无越界 nonce**。下表末二列正是照这条区分开的：能不能造出**签名**（可以，五格都能）与「该签名是否**只可能**由这一格的病因产生」（多数**未证明**）是两件事。

  | # | 形态 | 失败发生在哪一侧 | 读数 | 唯一可用判据 | 换终端复用器能否解决**本格的送达失败** | 签名 fixture 可复现？ | 签名→病因 映射独占性 |
  |---|---|---|---|---|---|---|---|
  | 1 | **沙箱半聋**（能被投、自己**发不出**；默认沙箱隔离复用器 unix socket）| **发送侧**（本机环境）| `no-operational-route` 或注入无声无效 | 发送侧能力检查（规则 6）；出向单测 | **不能**——tmux 同样靠 unix socket，须靠 bypass 启动约定 | ✅ 不带 bypass 起一个会话；或单测经 seam 注入「复用器不可用」 | **假定** |
  | 2 | **认证失效**（字节收到、提交键也生效，目标 CLI 无法处理：屏幕上是 token 刷新失败 / 要求重新登录；**transcript 永无痕迹**）| **接收侧**（目标 CLI 层，消息从未进会话）| `submit-unverified`（旧：`queued-unverified`）| **读屏**（见下 `dump-screen`）——transcript 上永远看不到 | **不能**——与传输无关 | ✅ 往测试 pane 注入**伪造的**该错误文本。**注意它测的是「认不认得这个屏幕形态」，不是鉴权本身** | **假定** |
  | **3a** | **文本损坏 + 未提交**（文本到了 composer 但被**截断/丢字符**，且**未入队**）| **传输侧 → 接收侧 composer** | `submit-unverified` / 写入后未按键那一支是 `composer-unsubmitted` | **读屏**：屏上文本**与信封不一致**（有缺字）| **不能**——对因在写入方式（bracketed-paste 原子交付）| ✅ 写入被人为截断的文本且不发提交键 | **假定** |
  | **3b** | **提交键早于 composer 就绪**（文本到了 composer、**逐字完整**、composer **未清空**、无认证报错、transcript 零命中）| **接收侧 composer 的时序** | 同上 | **读屏**：屏上文本**与信封逐字一致**却未提交 ⇒ 与 3a 的判别点就在**有没有缺字** | **不能**——对因在**等 composer 就绪**，不在复用器选择上 | ✅ 注入长文本后**立即**发提交键 | **假定** |
  | 4 | **delivered-but-verified-too-early**（其实**成功了**：nonce 确实在目标 transcript 里，只是 verify 窗口跑在目标 CLI 落盘之前）| **验证侧**（既非传输也非接收故障）| `submit-unverified`（**假阴性**；旧：`queued-unverified`）| 事后重搜 nonce（放宽窗口后即命中）| **不能**——是时序问题 | ✅ 把验证窗口调小；或让 fake transcript 在窗口**后期**才写入 nonce | **假定** |
  | 5 | **构造侧内容损坏**（信封在**离开发送方之前**就已缺字）| **构造侧**（发送方自己）| **完全的绿**：投递成功、nonce 越界命中、所有门全绿 | 发送前对信封**自校验**（回读比对）或结构性禁用会触发替换的引用形式；**投递侧任何探测都测不到** | **不能**——与传输选择完全无关 | ✅ 平凡（构造一条会被替换吞字的信封） | **已证明**——回读比对**直接**判定「正文与源不一致」，不依赖排除法 |
  | 6 | **目标尚未就绪**（新起的 ATUI 还在自更新/初始化，**CLI 进程尚未接管终端**；字节被它前面的 shell 或安装程序吃掉）| **接收侧，在 CLI 启动之前** | `queued-unverified` | **读屏**（屏上是安装/初始化输出，不是 composer）| **不能** —— 与传输无关 | ✅ 向一个尚未接管终端的 pane 投递 | **假定** |
  | — | **`unclassified`（必须保留的一格）** | 未知 | 任意 | **签名不匹配任何已知形态** ⇒ 落这一格 | 不适用 | 不适用（它就是「都不匹配」）| 不适用 |

  > **形态 3 必须拆成 3a / 3b —— 实测把此前的归因推翻了一半**（2026-08-06）。两次向不同 codex 目标投**长信封**，签名完全相同：注入后发提交键 → 读数未验证；读屏显示**文本在 composer、composer 未清空、无认证报错、transcript 零命中**。按此前的单一格描述，这就是「长文本损坏」。**但两次补发一次提交键都成功了，且文本逐字无缺**。
  >
  > **变量对照（这是结论的全部依据）**：
  >
  > | 次 | 提交键 | 注入→提交的间隔 | 结果 |
  > |---|---|---|---|
  > | ① | 先发了**错误的键**（对空闲目标用了入队键，违反规则 1）| 约 1 分钟后补正确键 | **成功** |
  > | ② | 键**正确** | 仅约 1 秒 | **失败**；再补一次同样的键 | **成功** |
  >
  > ⇒ 两次失败的共同变量**不是键、不是文本完整性**，而是**注入与提交之间的间隔**：长文本尚未被 composer 吞完，提交键就到了，于是被吞进 paste 流或被忽略。**判别 3a / 3b 只需看屏上文本有没有缺字。**
  >
  > **对因修法不同，所以不能合成一格**：3a 要**原子交付**（bracketed-paste 成帧）；3b 要**等 composer 就绪**。
  >
  > **⚠️ 3b 的修法不得是「把提交延时常数调大」。** 那是**数值会被后人优化掉**的那类修法（同 §3 验证窗口那条：**方向比数值重要**）。正确形状是**等一个可观测信号** —— 例如注入后轮询读屏，直到屏上出现**信封尾部若干字符**再发提交键，把「等够了吗」从**计时**变成**判据**。这与规则 8 的 ack 是同一条思路：**用被观测方产生的证据取代发送方的估计。**（读屏在此是**合法用途** —— 就绪判据与事后分类；它仍**不是**存在性 preflight、**不是**送达证据。）
  >
  > **一条待验的推断（若成立，会提高那笔 port 的价值）**：原子交付很可能**同时**缓解 3a 与 3b —— 整块被终端一次吞下，提交键就不会与 paste 流交错。但**「原子」只保证一次写调用，不保证终端已处理完** ⇒ 它可能只是**缩小**时间窗而非消除。⇒ 不得据此取消 3b 的就绪判据；两者**并存**，判据是兜底。

  > **形态 6 是唯一「等待有效」的一格，因此它必须与其余各格分开**（2026-08-06 实测）：一次向刚起的 ATUI 投递，读屏显示该 pane 正在跑**包管理器自更新**（屏上是安装器的进度输出）——**CLI 进程还没接管终端**，字节落进它前面的 shell。读数与其余各格**一样**是 `queued-unverified`，但处置**相反**：
  >
  > | | 形态 1–5 | **形态 6** |
  > |---|---|---|
  > | 重发 | 无效或有害 | 无效 |
  > | **等待** | **无效**（等不会让沙箱、认证、截断、构造错误自己好） | **✅ 有效——这是唯一一格** |
  >
  > ⇒ 把形态 6 混进其余各格会导致**两种相反的错误**：当成 1–5 处理 ⇒ 放弃了一个只需等待的目标；反过来把 1–5 当成 6 ⇒ 无限等待一个永远不会好的目标。
  >
  > **就绪判据必须是因果的，不能靠读屏猜**：「屏幕上看起来像 composer」是**旁观**判据（初始化中的 CLI 可能已经画出提示符却还没接管输入）。因果判据是 **「目标已完成自登记」** —— 自登记是目标**自己执行**的动作，它成立即证明该 CLI 已经起来、能读 harness、能写文件。这与 [规则 8 的 ack](#) 是同一条思路：**接收方自己产生的证据，强于发送方的旁观。**
  >
  > **形态 6 还要再分成两半，而两半的处置相反（同一轮实测的续集，第四次细分）**：紧接上一次观测，同一个 pane 后来显示 **`Update ran successfully! Please restart …`** —— 自更新完成了，但 **CLI 要求人工重启、不会自行启动**。那个 pane 此刻只是一个 shell，先前投进去的信封被 shell 当命令吃掉，而目标 ATUI **从未存在**。
  >
  > | | **6a 启动中** | **6b 启动未完成且不会自行完成** |
  > |---|---|---|
  > | 屏幕签名 | 安装/初始化的进度输出 | **明确的「请重启」一类提示** |
  > | **等待** | **✅ 有效** | **❌ 无效** —— 必须重新执行启动动作 |
  > | 投递落在哪 | CLI 尚未接管的终端 | **一个普通 shell**（信封被当命令执行/丢弃） |
  >
  > ⇒ **这次细分本身印证了「就绪判据必须是因果的」**：6a 与 6b 的**屏幕签名可以区分**，但那是**猜**（要认识每种 CLI 的重启提示文本，而那是 §3 里已标为 `single-observation` 的那类脆弱常量）；而**「等多久都不自登记」直接判定 6b**，不需要认识任何提示文本。**屏幕形态能猜，自登记能判。**
  >
  > ⇒ **启动侧不变量（分两种投递方，不得写成一条）**。先前把它写成「自登记完成前不得向它投递」——**那条有逻辑漏洞**：自登记要求该会话**先被激活**（它刚起来不会自己动作），而激活靠的正是第一条消息 ⇒ 按那条写法**永远投不出第一条**。正确形状：
  >
  > | 投递方 | 前置 | 判据 |
  > |---|---|---|
  > | **派生方的第一条**（激活 + 交付 handoff 指针） | 只要求 **CLI 已接管终端** | 这一条**自带判据**：投一条带 nonce 的短指针，nonce 进目标 transcript ⇒ 既证明就绪、又证明收到。**未进 ⇒ 属形态 6a，等待后重投**（这是**唯一**允许重投同一封的情形，因为只有这一格「等待有效」——见上表） |
  > | **第三方的后续投递** | 要求**自登记已完成** | 注册表里有它的 leaf。没有 leaf 就无从寻址，猜 pane 即 §5.0 明令禁止的那类错认 |
  >
  > ⇒ 两者的差别不是严格程度，而是**信息来源**：派生方**知道**自己刚起了什么、在哪个 pane，所以它有权探测；第三方**只能从注册表知道**，而注册表在自登记前是空的。**把两者合成一条，就会要么禁掉第一条投递、要么放任第三方去猜。**这条同时解释了一个此前没人归因的失败类 —— 新起 ATUI 存在一个**就绪窗口期**，期间任何投递都会落进虚空，而读数与「目标坏了」不可区分。（启动方自身的「等二进制就绪」重试只保护启动方，**不保护投递方**。）

  > **为什么 `unclassified` 是硬要求**：**没有这一格，分类器会被迫把新病因塞进最像的已知格里**——那不是分类，是掩盖。本轮已经**五次**证明这件事会发生：形态数从三扩到五、再扩到六、六又分成 6a/6b、三又分成 3a/3b，两个新格（验证太早、构造侧损坏）在被发现前，其签名都曾被归进已有的解释里（前者被读成「目标在排队」，后者干脆全绿无人怀疑）。⇒ 落 `unclassified` 是**正当结论**，不是失败；把它硬塞进第 1–5 格才是。

  > **`unclassified` 必须捕获原始签名，只计数的桶是装饰**：一个只 `+1` 的 `unclassified` 桶，和「没有执行者的门」是同一个东西——数字会涨，但没有人因此学到第六种形态是什么。⇒ **每一次落 `unclassified` 都必须当场捕获并持久化完整原始签名**：读屏全文、写入与提交两个命令的 stdout 原文、transcript 越界检查的原始读数、时间戳、目标标识；落成 durable 文件，**不是只加一个计数**。
  >
  > 理由是一次真实的侥幸：本轮之所以能把两条失败分成两种形态，靠的是「之前几次尝试的痕迹**还留在屏幕上**」——那是运气，不是机制。屏幕会滚走、容器会销毁、pane 会被复用；**新病因的原始材料只在它发生的那一刻存在，事后无法补采。** ⇒ 捕获必须与发生**同步**，否则第六格永远只能等下一次侥幸。
  >
  > 推论：既然完备性假设已被推翻两次，就该**预期它会被推翻第三次**。`unclassified` 的原始签名档案的价值**不在当下分类**，在**下一次扩格**——它是唯一能让第三次比前两次更快被识别的东西。

  > **判定顺序：逻辑上独占的判据放最前，靠排除法的放最后**（降低暴露面，不解决独占性本身）。构造侧回读比对是唯一**不依赖排除法**的判据，应最先跑；`假定` 独占的分支放后面。这样最弱的推断只在最强的都失败后才运行，且一旦前面命中，后面依赖完备性假设的分支**根本不会被执行**。

  > **⚠️ 五格的独占性是「假定」，不是「已证明」**：独占性（这个签名**只可能**由这一格的病因产生）建立在「**已知病因集合完备**」这个假设上，而该假设在本轮**被推翻过五次**（三格 → 五格 → 六格 → 6a/6b → 3a/3b）。⇒ 第 1–4 与 6 格的映射标 `假定`：签名匹配只说明「与该形态一致」，**不构成**「病因即此」。要把某格升为 `已证明`，得给它一条**像形态 5 那样直接判定**的判据（不依赖排除法）。

  > **⚠️ 末列只管一条轴，别把它读成对复用器选择的结论。** 末列问的是**可靠性轴**（送达成不成），这一轴上五格**零格**要求换复用器。但复用器选择的剩余候选价值落在**另一条轴 —— 侵入性轴**（送达要付什么代价）：本仓另有一条**独立实测尚未被推翻**——定向写入**跨 tab 不生效、必须先抢焦点**（见下「`--pane-id` 寻址不免除聚焦」），而抢焦点会**打断正在同一复用器里工作的人类**。这是一个真实成本，且**任何投递侧修法都不碰它**（上文那次成功的投递同样是先聚焦的，故这条未被该实测触及）。⇒ **不得**据本表得出「换复用器已被证据否掉」的结论；两条轴合成一列，会让一个真实成本从账上消失。

  - **形态 2 的触发模式常量单独标 provenance（`provenance: single-observation`）**：用来识别该屏幕形态的那段文本模式（屏上的重新登录 / token 刷新失败提示）**只来自单次观察**——不是穷举过该 CLI 各版本各语言各种失败提示的结果。⇒ 它的**证据等级低于该形态本身**（形态确实发生过；模式常量只见过一次长什么样），二者必须分开记，否则会把「见过一次的字符串」当成稳定契约。
    - **匹配失败时的行为（fail-closed，硬规则）**：屏幕内容**不匹配**该模式时，**必须降级为 `unclassified`**，**不得归入最近的一格**。理由与上条同：模式常量既然只有单次观察，那么「不匹配」的最可能原因是**模式不全**，而不是「病因不是这个」；此时按相似度就近归类会**凭一个未验证的常量**给出一个确定的错误结论。
    - 推论：这段模式常量属**实现**（投递 adapter 的分类器），随观察增加而更新；每次扩充都应记下新观察的出处，别让它悄悄从 `single-observation` 变成看不出出处的「魔法字符串」。
  - **形态 1–3 同一读数、修法完全不同**：规则 3 的 nonce 判据对它们给出**同一个**「没验到」读数（形态 2 的字节从未进 transcript、形态 3 的信封不完整或未提交，都搜不到 nonce）——规则 4 把结果按动作展开后，形态 2/3/4 仍**共享** `submit-unverified` 这一格。⇒ `submit-unverified` **不是**可直接据以重发的诊断结论，它只是「没验到」；重发对形态 1/2 无效（发送端或认证坏了，重发多少次都一样），对形态 3 也未必有效。别把它当成「网络抖了一下、再发一次就好」。
    - **规则 4 消掉的是另一类混装**：它把「**做过什么动作**」分开了（有没有按键、命令有没有回话、是不是入队等 turn），**没有**分开「**为什么没验到**」。前者可从命令与相位机械判定，后者需要读屏。⇒ 别把七值读成「病因已分类」。
  - **形态 4 的详情与后果（已实测：一次真实同仓投递，目标 brand=`claude-code`）**：目标 transcript 里 nonce **确实存在**（`type=user` 的一条记录），但当次 verify 窗口是 `PANE_VERIFY_ATTEMPTS=10 × PANE_VERIFY_INTERVAL_SECONDS=0.1` ⇒ **总窗口仅 1 秒**，grep 在目标 CLI 落盘**之前**就跑完了，于是返回 `queued-unverified`。
    - **它会污染前三种病因的样本集**：任何「投递失败率」统计都被它**抬高**，而它**根本不是失败**。⇒ 统计投递可靠性前必须先把这一格排除（对每个未验证读数——现为 `submit-unverified`——事后重搜一次 nonce），否则会给一个不存在的问题分配工时，并把真正的形态 1/2/3 稀释掉。
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

    > **覆盖 6 种已知形态，每格有签名级 fixture；其中 1 格的触发模式常量仅凭单次观察，且 5 格的「签名→病因」映射独占性依赖「已知病因集合完备」这一已被五次推翻的假设。**

    **禁止**把它写成「覆盖 5 种病因」「投递失败已分类完毕」之类——那是虚报：有 fixture 只证明**签名**可复现，不证明**病因**被覆盖；而已知形态集合本轮已被扩过两次，没有理由认为第三次不会发生。

  - **形态 5 的签名描述已被更正（第二次实测，另一个独立发送方）**：此前隐含的签名是「**文本变短 / 缺字**」。第二次实例证明那是**错的**：

    > **发送侧损坏的可观察签名不是「文本变短」，而是「文本仍自洽，但少了具体值」。**

    第二次实例的读数：发送方同样在**双引号内用反引号**包住两段读数（一条实测命令输出、一条命令行形态），两段被替换执行掉，投出去的正文**只多了两个空格**。⇒ 三条推论，方向都与旧签名相反：

    1. **分类器不得只比长度。** 少两个反引号跨度可能只差几个字节，甚至（替换有输出时）**变长**。
    2. **收信侧结构上检测不出来。** 实测：接收方**完全没察觉**，是读到发送方的更正才知道——因为**投出去的字节里没有任何东西说明「这里原本有一段」**。⇒ **这道校验必须做在发送侧，不能指望收信方发现。**
    3. **被抽掉的恰是「具体值」那一类**（读数、路径、命令、标识符），因为那正是人会用反引号包起来的东西。⇒ 损坏后的正文保留全部论证结构而**丢掉全部可核对性**——它读起来像一个**没给证据的断言**，而不像一条坏消息。

    **机械修法（不是「小心引用」）**：`send` 提供 `--message-file <路径>`（`-` 表示 stdin），正文**不经过 shell 引用**。⇒ 这一格被**移除**而不是被警告。凡正文含反引号、`$(...)`、或换行，**一律用文件形态**。另配一道 fail-closed：**空正文拒绝发送** —— 空正文是整段被替换吞掉时**最可能的可观察痕迹**，而一个成功送达的空信封在接收侧与「发送方没话说」**不可区分**。

  - **收束（本节最强的一条结论）**：**nonce 判据证明的是「这个信封到了」，不是「我想说的话到了」。** 形态 5 是它的存在性证明——全绿而语义已损。凡把「所有门全绿」读成「沟通成功」的地方，都少了一道**构造侧**的校验。
  - **本节是 [verification-and-gates 通则](./verification-and-gates.md#门有执行者吗通则没有机械产物的规则是装饰)「门不要求全部已验证，门要求未验证的缺口必须写出来」的第三次应用**，且这次的应用点**比前两次细一层**：缺口不在「**有没有测试**」（五格都有 fixture），而在「**测试证明的到底是哪一层**」——签名层可复现，病因层多数仍是假定。⇒ 写缺口时要标到**层**，不要停在「已有测试覆盖」；「有测试」和「测的是你以为的那件事」是两个声称。

- **`dump-screen` 的正当用途与边界（三条，别把第一条读成放宽规则 5）**：
  - **✅ 可用于事后诊断**：投递后读屏，把「**文本没到 composer**」与「**文本到了 composer 但没提交**」分开——这正是上面形态 2/3 与「正常入队等下一 turn」的鉴别手段，也是目前唯一能看到形态 3「被截断」的办法。它读的是**屏幕现状**，而屏幕上确实有内容可读时，读到的东西是可信的。
  - **❌ 不可用于存在性 preflight**：对**不存在的 pane** 它**静默返回空且 rc=0**（上游 gardener 已独立复现）⇒ 用作存在性判据必然**假阳性**（把不存在的 pane 认作存在）。规则 5 已明确禁用，本条不放宽。
  - **❌ 也不是送达证据**：规则 3 的送达证据只认 **per-send nonce 出现在目标 transcript 里**。屏幕上看见自己的文本只说明「字节到了 composer」，**不等于**已提交、已进 transcript、已被处理（形态 3 就是屏幕有字而未入队）。
  - **❌ 更测不出构造侧损坏（形态 5）**：屏幕上会**如实显示**那句已经缺字的话——读屏只能证明「屏幕上那些字到了」，无法知道**本该**是哪些字。构造侧只能在发送前自校验。
  - 区别的根子：**「读到空」不可信（可能是 pane 不存在），「读到内容」可信**。所以它能作阳性诊断，不能作存在性判定或送达判定。

- **契约里的 nonce ≠ §5.2 自识别 nonce**（用途不同，勿混淆）：本节的 per-send nonce 是**送达证据**——证明「这一条信封确实进了对方 transcript」；§5.2（自登记步骤 2）的无桥接 nonce grep 是**自识别探针**——本会话往自己终端吐一个随机串、再回自己 brand 目录 grep 定位**自身** `session_id`/`session_file`。前者验对端送达、后者定位本端句柄，各自独立。
- **证据是 per-send 运行时态，不入注册表**：字节边界 / nonce / marker 均随单次发送产生与消亡，注册表是静态发现表，**不**为其新增字段（`pane_ref` 只存寻址句柄，见 §2.2）。规则 8 的 **submit-ack 表同理不是注册表的一部分**——它是一份**独立的 append-only 事件表**（`~/.arborist/submit-acks.jsonl`），与 `focus-intrusion.jsonl` 同类：per-send 事件流，不是发现快照，故注册表 leaf 不为它加任何字段，validator 也不查它。
- **候选未来 transport（备注，非依赖）**：官方 **Channels** 能把外部事件推进一个已运行的 Claude Code 会话，是一个**候选未来投递 transport**（成熟后可作满足本契约的又一 adapter 后端）；但它当前仍是 **research preview**、且**需会话启动时显式 opt-in**，故**暂不作 Arborist 默认依赖**（与「可插拔 adapter、opt-in、transport 中立」一致）。

## 4. 生命周期与角色分工

- **自登记（主路径）**：AgentTUI 启动读 harness 后，**自建**整条 leaf（spec.json + runtime.json，单写者原子写）。自建覆盖所有角色——rootorc / gardener 没有 handoff 信，登记不能挂在派活方身上。

#### 5.0-b 复用器 session 命名与两段式改名（当 ATUI 由复用器承载时）

> **本节是建议，不是规范要求。** 它的目的只有一个：**便于人查找**。⇒ **已经存在且可辨认的名字一律沿用，不得为了统一格式去改名**——改名的收益是「整齐」，代价是可能腐烂寻址句柄（见下表），这笔交换不成立。凡「已有名字看一眼就知道是谁」（形如 `<项目简称>-<角色><序号>`）即视为**合格**，无需向下面的形态收敛。

**建议形态（新建时可用）**：`<project alias 或 name>-<任务名>-<role>`。项目段取 §2.3 的 `alias`（缺省回落 `name`）——**取自注册表，不取目录名**：目录可以被改名、可以有多个工作树指向同一项目，而注册表里的项目身份是唯一的。

**鸡生蛋问题与解法（两段式）**：launcher 起 session 时，**任务名与 role 还不存在** —— 它们是 ATUI 自登记时（甚至是与人对话后）才确定的。项目段可由 cwd 反查注册表得到，另两段不可。⇒
1. launcher 先用 `<project alias 或 name>-<pid>` 起（可预测、不撞名）；
2. **ATUI 自登记时把 session 改名**为完整形态。

**这个解法是否安全，取决于该复用器的 pane 句柄里有没有 session 名**：

| 句柄形态 | 改名安全吗 |
|---|---|
| 句柄**含 session 名**（如 `{multiplexer, socket, session, pane_id}`） | **不安全** —— 改名即让既有 `pane_ref` 腐烂（§3 已实测这一类：句柄静默失效、注入喷进虚空）。**注意本仓现行 tmux `pane_ref` 正落在这一格**：寻址锚虽是终身不变的 pane id，但句柄**带 session 字段且投递前核对它**（§3 tmux 段），故改名会让既有句柄**响亮失效**。⇒ 要用两段式第二段，必须与**整条重建 `pane_ref`** 同时发生；随发 launcher 因此**只做第一段、不代改名** |
| 句柄**理论上**是全局唯一且终身不变的 pane id | **仍不安全** —— 见下方更正 |

> **⚠️ 更正（此前这里写错了）**：先前的结论是「若该复用器的 pane id 全局唯一且终身不变，则改名安全」。**按当前实现不成立** —— **`pane_ref` schema 对所有复用器都含 `session` 字段，而投递前会核对它**（对不上即报 session 不匹配）。⇒ 即使 pane id 本身免疫改名，**改 session 名仍然让既有 `pane_ref` 失效**。
>
> ⇒ **两段式命名当前对所有复用器都不可用**（除非同时**整条重建** `pane_ref`，而那正是「不得只改一个字段」那条规则要求的）。因此 launcher **不得代为改名**。
>
> 「句柄形态决定改名是否安全」这条推理**本身仍然成立**，错的是把「pane id 不含 session 名」当成了「**句柄**不含 session 名」—— 句柄是**整个 `pane_ref`**，不是其中的 pane id 字段。**一个字段免疫，不等于句柄免疫。**
>
> 这也是为什么「换复用器」的评估必须逐格看**句柄形态**（整条 `pane_ref` 加上投递侧实际核对哪些字段），而不是只看投递命令、更不是只看 pane id 的性质。

**session 生命周期须与人类的关闭动作对齐（实测，且默认值是危险的那一侧）**：

| 复用器行为 | 人类关掉承载它的外层窗口/tab 之后 | 后果 |
|---|---|---|
| 默认（客户端断开即 detach、session 保留） | session **仍在**、其中的 ATUI **继续运行** | **比残留一个句柄严重得多**：一个还在工作、还在消耗额度的 agent，而人类已认为它被关掉了；注册表也读不出这个状态 |
| 设为「最后一个客户端断开即销毁 session」 | session 与 ATUI **一并结束** | 与人类「关窗口 = 关掉它」的心智模型一致 |

⇒ **必须显式清理，且推荐手段 = 复用器内建的「最后一个客户端断开即销毁 session」**（不是 `trap` 信号 —— 那条曾被推荐过、已被实测推翻，事故留档见下方警告）。**选它的理由只有一条，但很硬**：它**不依赖信号、不依赖承载它的是脚本 shell 还是交互 shell**，因此对「测试里的形态」与「人类粘命令的真实形态」**同构** —— 而上一版正是死在这个不同构上。

**这个手段的已知代价（必须与手段同句给出，别只写「推荐它」）**：

| 代价 | 内容 | 谁受影响 |
|---|---|---|
| **判据是推论、不是因果** | 它只看「当下有没有客户端」，**分不出**「人类关掉了窗口」与「人类只是暂时离开」 | 见下一行 |
| **内层 detach 会被误伤** | 内层 detach 同样让 session 变成无客户端 ⇒ 一次内层 detach 就销毁一个正在工作的 agent | 只影响**用内层 detach** 的人；**用外层 detach 的人不受影响**（外层 detach 不销毁 pane，内层客户端仍附着） |

**开启时机是一条实测出来的硬约束（写错顺序会杀掉 agent）**：

| 读数（**实测**：私有 socket 的 detached server，用完 `kill-server`；另用假 pty 客户端测附着那两格） | 值 |
|---|---|
| 对一个**当下无客户端**的 session 直接开该选项 | **session 当场被销毁**（server 随之消失） |
| 改为「**第一个客户端附着时**才开该选项」（复用器的 attach 事件钩子），未附着期间 | session **存活**，选项**为空**（未开） |
| 同上，客户端附着后 | 选项变 **on** |
| 同上，客户端被杀（≈人类关掉外层窗口） | session 与其中进程**一并结束** |

⇒ **规范性**：该选项**必须由「客户端已附着」这一事件触发开启，不得在建 session 时直接开**。否则「detached 起、还没人来看」的 ATUI 会在出生的瞬间被销毁 —— 而 detached 承载被投递的 ATUI 是一个**已实测可行**的正当形态（§3 tmux 段：无客户端附着的 server 上投递全部成功）。
**连带的诚实边界**：一个**起了就从未被附着过**的 session 因此**不会**自动消失，需显式销毁；这条必须由 launcher 在该分支上如实告知（随发 launcher 已照此打印）。

| 人类动作 | 内层 session | 机制与读数 |
|---|---|---|
| **关闭外层 tab / pane** | **一并结束**（前提：已附着过 ⇒ 选项已开） | 关 pane 杀掉内层客户端 ⇒ 内层 session 无客户端 ⇒ 内建销毁生效（**实测**） |
| **detach 外层 session**（整个会话挂起、稍后重入） | **保留、继续运行** | 外层 detach 不销毁 pane ⇒ 内层客户端仍附着（**实测**：外层客户端断开后两层 session 均存活） |
| **detach 内层 session** | **被销毁**（上表第二条代价） | 内层 detach 让 session 变成无客户端 ⇒ 与「关窗口」不可区分 |
| ATUI 自己退出 | 自然结束 | 内层 session 随之结束、attach 返回 |

> **⚠️ 实测推翻了「trap SIGHUP」这个手段（本条是一次「测试与实际不同构」的事故留档）**：先前据「关 pane 会发可捕获的 `SIGHUP`」推出「launcher `trap` 它即可清理」，并**在脚本 shell 承载的测试里端到端验证通过**。随后在**真实用法**下失败，逐格读数：
>
> | 读数 | 值 |
> |---|---|
> | 外层 pane 关闭后，内层 client | **已断开**（关 pane 确实杀掉了 client） |
> | 内层 session | **仍存在** |
> | 内层的 ATUI 进程 | **仍在运行** |
>
> **成因：两次的进程结构不同构。** 测试里 pane 的唯一前台进程**就是那个脚本**，它自己 `trap`；真实用法里人类是**在交互 shell 里粘贴命令**，`trap` 落在**交互 shell** 上，而交互 shell 有 job control，其 `SIGHUP` 处理与脚本 shell **不同** ⇒ trap 未执行，于是留下**看不见的活体**（一个仍在工作、仍在消耗额度的 agent，而人类已认为它被关掉）。
>
> ⇒ **可靠手段回到「最后一个客户端断开即销毁 session」这个复用器内建选项**（已按上文改为推荐手段，并连同其代价与开启时机一并写在上面）：它**不依赖信号、不依赖 shell 类型**，因此对「脚本承载」与「交互 shell 粘命令」**同构**。
>
> **本条已升格为通则，正文不在这里**：见 [`verification-and-gates`](./verification-and-gates.md#门的回归必须端到端且测试的结构必须与真实调用路径同构)「门的回归必须端到端，且测试的结构必须与真实调用路径同构」——本例是它在**进程 / shell 类型**这一维度上的实例（另一维度是**调用链层级**）。本节留的是**案卷**（逐格读数 + 成因），判据以那边为准。
>
> 本例落在通则上的形状：「信号确实到达」与「`trap` 确实执行」是**两个不同的命题**，测通第一个推不出第二个 —— 而中间那一步差异（脚本 shell vs 有 job control 的交互 shell）**在测试内部不可见**，所以测试是全绿的。

> **⚠️ 两层复用器的 detach 是两个不同的动作，规范里必须始终指明是哪一层。** 本仓在设计过程中**已经因为混淆这两者而一度得出相反结论**（把「人类会 detach」读成内层 detach，从而错判上述清理手段有危险，并据此在规范里写下过一条错处方）。⇒ 凡涉及嵌套形态，**「detach」一词不得单独出现**，必须写成「外层 detach」或「内层 detach」。

**实测边界（如实记）**：以上读数取自**独立的测试会话 / 私有 socket 上的 detached server**（不触碰任何真人终端，用完销毁），逐格记录「动作 → 内层 session 是否存活」；附着那两格用的是一个**假 pty 客户端**，不是真人终端。**未验证**：① 真人终端上「关掉外层 tab」是否与「杀掉客户端进程」逐格同构（按构造应当同构，但**未在真人终端上测**）；② 其它复用器实现是否有等价的「无客户端即销毁」选项与 attach 事件钩子——这**不是**标准要求，而是该实现的**观测行为**；换实现必须重测（同 §3「每种复用器都有一个看起来最自然却静默回落的命令」那条通则）。

#### 5.7 上卷的创建语义与「两半分别报告」（实现契约）

**创建而非拒绝**：全局摘要的上卷在**项目条目或 agent 摘要缺失时创建它**，不再拒绝。判据：**摘要派生自 leaf，而 leaf 是权威（§2.3）⇒ 生成摘要不需要任何 leaf 没有的信息，没有可猜的东西。** 拒绝的后果是：一个**刚刚正确自登记**的会话，其**首次心跳必然失败** —— leaf 在、摘要不在，恰是被拒绝的那个状态。⇒ 那不是防错的门，而是让「自登记 → 心跳」这条被文档化的序列**无法走完**。

**创建必须留痕、不得静默**：创建出的条目带 `created_by`，使审计能区分「上卷生成的」与「人写的」。静默创建会让一个**推导错误的 `project_id`** 看起来像一直就在那儿 —— 那正是路径推导 fail-closed 门要消除的失败形状。

**两半分别报告（跨两个文件做不到真原子，所以不假装原子）**：先写 leaf、再上卷摘要；结果**分别**报告两半（`leaf` / `summary`），**成功时也报**。

> **核心危害不是「不原子」，而是调用方读不出真实状态。** 原先是 leaf 已写盘、却向调用方报 `error`，而调用方无从区分「什么都没发生」与「一半发生了」——读成前者就会以为心跳没落地，而它落地了。
>
> **先写 leaf 是刻意的**：它是权威，且「leaf 无摘要」是一个**有名字、可检测**的状态（方向 B）并有既定修法；反向的「摘要无 leaf」是方向 A，指向一个**可能不存在**的 agent。两者必有一个先落 ⇒ 让**失败形态可诊断**的那个先落。

**⚠️ 剩余失败一律标「不可自愈」，且禁止建议重试**：创建路径落地后，「条目缺失」这一类失败**不再可能发生**；剩下的只有**结构损坏**（index 的数组不是数组）与 **I/O**（不可读/不可写/非法 JSON）——**它们不会因为重跑而改善**。

> 这一条是被一次复核逼出来的，值得留档：本节初稿是「报告两半 + 建议重试」，而那是**退步** —— 它把一个**响亮的错误**换成了一个**安静的半成功**。**响亮的错误读数会被追查，安静的半成功不会。** 且对剩余失败类，建议重试会把调用方送进一个**永不可能成功**的循环。
>
> ⇒ 剩余失败的**执行者是注册表一致性 validator**（它把「leaf 无摘要」报成方向 B，且有必答时刻：周期性维护、任何批量改动前后），**不是**「有人会读 stderr」——心跳是自动调用的，**没有人在看它的 stderr**。凡把「有人会看到告警」当执行者的设计，一律按 [verification-and-gates](./verification-and-gates.md) 那条判为**装饰**。

#### 5.0 pane 自识别门（写入前 · 规范性 · **不得**与写入后的唯一性检查互相替代）

**问题**：自登记要填 `pane_ref`，而会话判断「我在哪个 pane」的最自然手段是**读复用器注入的环境变量**。这个手段**不可靠，且失败是静默的** —— 已实测两次真实错认：一次认成**别人的** pane、一次**继承了发送方的** pane。写错的 `pane_ref` 不会报错，只会让后续投递打到无关的会话里。

**根规则（形态式，承重的那条）**：

> **凡自识别证据不足以「唯一确定」该 pane ⇒ 拒绝写入。**

它**不列举**冲突形态，只要求一件事:**唯一性的证明**。故一个从未被想到的冲突形态**落进同一条规则**，而不需要新开一格。

**推论（这是上面那条的应用，不是另一条规则）**：复用器环境变量只是「待证线索」，不是身份证明 —— 它单独**不构成唯一性证明**。必须用**独立的第二条证据**佐证（复用器侧列出该 pane 的**运行命令**与**工作目录**，与本会话声称的身份/cwd 比对），矛盾则 **fail closed、不登记**。

> **⚠️ 下面这张表是【诊断索引】，不是【判定依据】。** 它列的是**已实测过的**冲突形态，价值在于告诉你**该往哪看**；但判定一律回到上面那条根规则。
> **为什么必须这样分层**（判据见 [`verification-and-gates`](./verification-and-gates.md#枚举式检查在结构上弱于形态式检查)）：这张表是**枚举式**的，它的覆盖面**等于写表人当时的想象力** ⇒ 若拿它当判定依据，它**必然**会被下一个没想到的形态绕过，而那是**结构必然、不是运气**。本篇已有一个同形状的实证：投递失败形态表的形态集合被推翻**五次**。
> ⇒ **处置不是删掉这张表**（那会丢掉一份真实的诊断经验），而是**降级为索引、判定交给根规则**。

| 情形（诊断索引） | 处置 |
|---|---|
| 匹配的 pane 存在、非插件 pane；但**取不到** command/cwd | 仅当**另有一条独立且无冲突的身份佐证**、且该 pane **未被其它活体 leaf 持有**时可登记；**必须记录本次是降级判定** |
| command/cwd 可取，但**与声称的身份/cwd 矛盾** | **fail closed，不登记** |
| **headless resume / app-server 轮次暴露的是发送方的复用器环境变量** | **忽略该环境变量**；**不得**据它把自己登记成发送方的 pane |
| 候选 pane **已被另一条活体 leaf 持有** | **fail closed，不登记** |
| **嵌套复用器只暴露外层 pane** | **在未证明「外层 pane 能稳定转发到目标 TUI」之前不得猜填** |
| brand 不支持 / 与实际 runtime 不符 | **fail closed** |

| **上表未列出的任何情形** | 回到根规则：**不能唯一确定 ⇒ 拒绝写入**。「表里没有」**不是**放行理由 |

**为什么它不能被写入后的唯一性检查（§2.2.1 / §4）替代 —— 两者必须并存**：

| | 自识别门（本节） | 唯一性检查（§2.2.1） |
|---|---|---|
| 时机 | **写入前** | **写入后** |
| 防的是 | **写错值本身** | 两条 leaf 的值已经**互相冲突** |
| 能力边界 | 能拦住「我把别人的 pane 写成自己的」 | **只有在两条 leaf 都写完之后**才可能发现冲突；若只有一条被写错（另一条尚未存在或本就不在表里），唯一性检查**永远发现不了** |

⇒ 只有事后唯一性检查 = 只能在**已经污染之后**报警，且**漏掉单边错认**。

**对嵌套启动形态的直接后果（本仓当前正在评估的形态）**：若 ATUI 运行在「外层复用器 pane → 内层复用器 pane → TUI」的嵌套里，则**必须填内层句柄**，且**必须先证明该内层句柄能定向到这个 TUI**（一次带唯一 nonce 的定向注入 + 目标 transcript 越界命中）。**读到外层句柄就填**是上表最后一行明令禁止的情形 —— 它恰是那两次实测错认的成因。

> **一条已发生的示范性违规（去人格化留档）**：本仓曾有条目的 `pane_ref` 是**从进程环境变量反查**写入的 —— 正是本门判为不可信的方法。那次的值**恰好是对的**（当时未嵌套、非 headless），但**方法不成立**，不得作为先例。「值对了」与「方法可靠」是两件事；本仓另有一条通则说的是同一件事：[能被解释的错误读数会被归档](./verification-and-gates.md#新增的观测动作必须先证明它不扰动被观测者)，而侥幸正确的读数连「错误读数」都不算，更不会被追查。

- **handoff 供素材**：经 sendbox handoff 而来的会话，信中 role / task / description 直接用作 spec.json 素材；派活方可在信中提醒「按注册表规范自登记」，但**不代写**——session_id 在会话创建前不存在，派活方物理上写不了。
- **心跳**：处理 turn 的可信触点（每轮收尾、阶段切换等）顺带刷 `runtime.json.last_seen`；约定驱动，无守护进程。
- **收尾（任务/里程碑）≠ 会话结束**：任务完成 / archive / 末条回复 / 等用户输入 / compact / 上下文重置**都不是会话结束**，此时只刷 `last_seen` 心跳、**不写 `stopped`**。`state: "stopped"` 仅在**会话真正结束**（AgentTUI teardown 或 Mode-B 角色交接、当前会话不再续任）时写；**session 不得在自身仍活时标 `stopped`**（见 §3「stopped 写入门槛」）。误标的 `stopped` 会被读者 reconcile 成 contradiction（§3），且下一次可信触点应由本人 heartbeat 改回。
- **gardener**：持有并更新全局 `index.json`（跨项目摘要汇总）；按 §3 保守 GC stale 条目；校验 name 唯一；**跑注册表一致性 validator（必答时刻：周期性维护时 + 任何 GC / 批量注册表改动的前后各一次，接 [verification-and-gates 门控矩阵](./verification-and-gates.md#门控矩阵每个门一个必答时刻)「AgentTUI 注册表一致性」行，留痕落既有 landing manifest，不另造留痕机制）**；探针遗留项由 gardener 实测后回填本 guide：codex mtime **已实证**（见 §2.2）、跨目录/跨项目 `--resume` lookup **已回填**（见 §3 末，来自 adopter 实例实测、上游未独立复现）；**仍待实证**——无桥接自识别兜底（nonce grep，§5.2）。
- **half-registered 检测有两个方向，两向都须可检测并显式报为 `half-registered`**（旧表述只隐含了一向，据此写的检查会漏掉另一向）：
  - **方向 A：全局 index 有摘要、项目 leaf 不存在** —— 例：`<repo>/.arborist/agents/` 被下行同步或清理抹掉（一个 adopter 实例实测），而 index 摘要仍在。
  - **方向 B：项目 leaf 存在、全局 index 无该条** —— 例：自登记只写了 leaf、没追加 index 摘要（**上游本仓实测**）。§5 自登记第 6 点**曾**把「追加 index」列为可选（已更正为必须，见 §5.6 与 §5.7）——那是 B 向成为**常态漏洞而非罕见事故**的成因，检查必须覆盖。
  - 两向都**既不是**「未登记」**也不是**「已登记」，应显式报 `half-registered`：A 由 owner **重新自登记**重建 leaf 修复（心跳无法修复不存在的文件；⚠️ 早前文本提到的 `register-self` 子命令**在随发 adapter 里并不存在** —— 那是一条**指向不存在执行者**的修法，本身即「装饰」的实例，故此处改为指自登记），B 由 owner heartbeat **自动修复**（§5.7：上卷现在会创建缺失的摘要与项目条目）或 gardener 汇总补 index 摘要修复。**两向均不得据此 GC**（A 的摘要不是残渣，可能只是 leaf 被误删）。
- **注册表一致性的机械执行者 = `validate_agenttui_registry.py`（gardener 职责）**：上面这两向、以及 §2.2.1 / §2.3 的唯一性与自洽约束，此前**只有规范、没有任何执行者**（按 [verification-and-gates 通则](./verification-and-gates.md#门有执行者吗通则没有机械产物的规则是装饰) 即装饰门）。现由一个**只读** validator 承担，七条检查逐条对应本规范条款：

  | # | 检查 | 规范出处 | 报的 code |
  |---|---|---|---|
  | 1 | `session_id` 全局唯一（一个会话一个项目），**不受有效态限定** | §2.2.1 | `duplicate-session-id` |
  | 2 | `pane_ref` 四元组（含 `socket`，缺省归一化为默认 server）唯一，**只在有效态可达的 leaf 之间**，**独立于 1 查**；非可达却带 `pane_ref` 的另列为低危 warning、**不计入冲突**（pane 顺序复用是正常残留） | §2.2.1 | `pane-ref-conflict`（高危）/ `stale-addressing-handle`（warning）|
  | 3 | half-registered **方向 A**：index 有摘要、leaf 不存在 | §4 本节 | `half-registered` |
  | 4 | half-registered **方向 B**：leaf 存在、index 无摘要 | §4 本节 | `half-registered` |
  | 5 | leaf 的 `spec.project.path` = 它实际所在的仓根，且 `project_id` 照 §2.1 算法**重算**相符（**这是兜底**——对因是写入侧计算该值，见 §2.3 / §5 第 4 点）| §2.1 + §2.3 + §5 第 4/8 点 | `project-mismatch` / `project-id-mismatch` |
  | 6 | index 摘要与 leaf 的 `role`/`brand`/`state`/`lineage`（缺省 1）一致，**以 leaf 为准** | §1 + §2.3 | `index-leaf-disagreement` |
  | 7 | 跨仓镜像（带 `foreign_repo_registration`）的自陈完整、`home_registry` 可达且同名同项目、且其 runtime 拷贝与 home 的**寻址字段**一致；**非寻址字段**不一致只报 warning（镜像本就是快照，为此红灯会让每条镜像永久红灯） | §2.1 + **§2.2.2** | `mirror-stale`（高危）/ `mirror-declaration-incomplete` / `mirror-home-unreachable` / `mirror-home-mismatch` / `mirror-snapshot-drift`（warning）|

  - 调用：`python3 .trellis/scripts/validate_agenttui_registry.py [--global-index PATH] [--project PATH ...]`；不传 `--project` 时待查项目集来自全局 index 的 `projects[].path`。退出码 `0` 一致（warning 可存在）/ `1` 有不一致 / `2` 全局 index 缺失或非法 JSON（**fail-closed**——「读不到 index」不等于「没什么可查」）。低危 warning 印在**单独分节**、不影响退出码——把清理项与误投风险混印，等于让高危发现淹在低危里。
  - **它是 validator，不是 fixer：刻意没有 `--fix`。** 修一条 leaf 往往要判「这个会话到底属于哪个项目」，且跨项目删别人的 leaf 属别的 lane 的处置权；工具只负责把冲突双方的**具体路径**指出来。它也**不联网、不读凭证、不启停会话、不执行任何外部命令**。
  - **检查 7 不删镜像、也不代为同步**：`mirror-stale` 的处置是「重抄一份 home runtime，或干脆删掉那份拷贝」，由**镜像所在仓的 gardener** 执行；validator 只报。它也**不会**因为一条 leaf 是镜像就压掉检查 1/2/5 —— 那三项对镜像的高危报告是**已知假阳性**（降级为 info **尚未实现**，见 §2.2.1 实况表），处置一律「出裁定、不删」。
  - **检查 1/2 的发现自带裁定所需读数**（因为这两类实测都跨仓、按构造没有 owner，规则见 §2.2.1「跨仓冲突的机械 tiebreak」）：每条发现后附**每个声称方**的完整路径 + `session_id` / `session_file` / `state` / `last_seen` / `pane_ref`，外加优先级最高的「该 pane 真实 cwd」一行——后者固定报 **`unknown` 并写明为什么不自动取**（取它只能用会抢焦点的聚焦命令，见 §2.2.1 末行；缺读数与「读到了没有」必须可区分，故不报空）。目的是让裁定能**只据报告**作出，而不是让 validator 代替裁定。
  - **另一个「计算而非接受」的落点**：`--print-project-id <repo>` 打印按 `realpath` 重算的 `project_id`（§2.3 / §5 第 4 点），供自登记写入路径调用；给的路径不是已存在目录时 **exit 2 fail closed**——`realpath` 会把打错的路径同样消化成一个看上去很正常的 id，那正是本模式要消除的失败。它不读全局 index（写入发生在有表可查之前）。
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
   - **`project.project_id` 必须**由 `project.path` 的 `realpath` **计算**，**不得手填、不得从别的 leaf 或别的项目复制**：`python3 .trellis/scripts/validate_agenttui_registry.py --print-project-id <repo>`（照 §2.1 算法，与 validator 检查 5 同一份实现，故不会有两套算法）。模板里该字段**不是空位**（见 §2.3）。
   - **已有值与重算不符 ⇒ fail closed**：停下报错，不覆盖、不沿用——两者都会把一个已知错误的归属值继续传播（覆盖还会连带抹掉「这里曾经不一致」这个唯一线索）。
   - 理由见 §2.3「预防 > 检测 > 判断」：写入路径只要还接受字面值，检测端就永远在清同一类错误。
5. 同一 `name` 重启换新 session：更新 runtime.json（新 session_id / session_file，`generation` +1），spec.json 不动（`lineage` 是稳态身份，重启不变）。
6. **必须**把自己上卷进全局 `~/.arborist/index.json` 摘要（含 `lineage`）。**此前这里写的是「（可选）不追加则留给 gardener 汇总」——那是错的**，且它与注入给每个 session 的那条本地入口（明写「同步全局 index 摘要」）**直接矛盾**。三个理由：
   - **§4 要求摘要与 leaf 成对存在**；写了 leaf 不上卷，产生的正是 half-registered 方向 B ⇒ 把它写成「可选」等于把一个**已定义的不一致态**写成合法选项——那也正是方向 B 成为**常态漏洞**的成因。
   - **能恢复成对的唯一执行者是 leaf 的写者。** gardener 的周期性汇总是**兜底**，不是主路径；把主路径寄托在别人的周期性动作上就是荣誉制。
   - 上卷**不需要任何 leaf 没有的信息**（摘要字段全部派生自 leaf）⇒ 「可选」换不来任何自由度，只换来漂移。

   随发 adapter 的 `heartbeat` 现在会**创建缺失的项目条目与 agent 摘要**（见 §5.7），所以这一步在实现上也不再依赖谁记得做。
7. **经继承接管（sendbox Mode B）**：若本会话是经 inheritance-mode handoff 接管某角色（承担者换人、角色不变），spec.json 写 `lineage = 前任 lineage + 1`、`lineage_origin = 前任 session_id + 交接信名`（面包屑，非权威，见 §2.1）；`generation` 仍按本会话自身重启计（新会话即 1，与 lineage 无关）。
8. **写入路径 fail-closed 门（`.arborist/` 必须就在仓根下）**——这是 §3「投递前置校验」**路径推导**那一半在自登记侧的落点（同一条契约、同一形状：动手前先验前提，验不过就拒绝）：leaf 只能落在 `<repo>/.arborist/agents/<name>/`，其中 `<repo>` = 本项目根，且与写入的 `spec.project.path` **同一路径**。**若目标 `<repo>/.arborist/` 目录不存在，必须 fail-closed 并报 `half-registered`，不得静默上移到父目录、也不得靠 `mkdir -p` 顺手造出一整条新路径**——`mkdir -p` 恰好会把错位置造得「像是本来就有」，从外面看不出错。
   - **真实故障形态（须知，因为它完全静默）**：某写入方的 leaf 内容**全部正确**（`project.path` / `project_id` 都指向真仓），却把整个 `.arborist/` 写在了**仓的父目录**下；多日无人察觉，多条 leaf 与配套的唤醒/触达基础设施全落在错处，而注册表**字段自洽、看起来是好的**——错的只有落盘位置，恰是没人核对的那一项。**该现场的成因另有其人、尚未定位**；本门只消除**同形故障**，不声称修好了那次事故的根因。
   - 机械检查：写入前 `test -d <repo>/.arborist`（adopt 脚手架应已铺好；不存在 ⇒ 说明本仓未 adopt 或路径推导错了，**都该 fail-closed 而非补建**）；写入后核对 leaf 的实际落盘路径以 `<repo>/.arborist/agents/` 为前缀，且 `<repo>` 与 `spec.project.path` 一致。
9. **写 `stopped` 的门槛（自登记指南硬约束）**：只有**会话真正结束**（AgentTUI teardown 或 Mode-B 角色交接、当前会话不再续任）才写 `state: "stopped"`——任务完成 / archive / 末条回复 / 等用户输入 / prompt 空闲 / compact / 上下文重置**都不是会话结束**（定义见 §3「stopped 写入门槛」）。**严禁在本会话仍将继续处理 turn 时标 `stopped`**；这类场景只刷 `last_seen` 心跳。**修复误标**：本人下一个可信触点直接把 `state` 改回 `active` 并刷 `last_seen`（heartbeat 同步项目 leaf 与全局 index）；gardener 复核到 contradiction 条目时亦按此修复、不 GC。

## 6. 许可说明

本规范的机制思路（spec/runtime 两文件分离、扫目录即发现、last_seen + generation 判活等）借鉴自 CCB（AGPL-3.0）的**设计概念**，全部以自有措辞重述，未复制其任何源码或原文；Arborist 及本 guide 保持 Apache-2.0。
