# 工具注册表：可选能力的插件层

> 文件式注册表，声明「本机/本项目有哪些**可选工具/服务**可供 AgentTUI 调用」，形成轻量插件体系：agent 读表即知有哪些能力、怎么调、是否可用，**无需把工具硬编码进 harness**。纯静态表 + 约定驱动——**不做自动安装、不做自动接线（如自动改 MCP 配置）、不做能力路由/编排**。
>
> 姊妹规范：[AgentTUI 注册表](./agenttui-registry.md)——那张表 = 「本项目有谁」，本表 = 「有哪些可选能力可用」。两表同构、共用 `.arborist/` 级联、同由 gardener 维护，合起来构成 Arborist 的发现/插件层。

## 1. 位置：全局-项目级 级联

```
~/.arborist/tools/                # 全局（机器级服务，跨项目可用）
  <tool>.json
<repo>/.arborist/tools/           # 项目级（项目专属工具）
  <tool>.json
```

- **一个「插件」= 一条 `tool.json`**。机器级服务（如会话历史查看器）登记在全局；项目专属工具登记在项目级；同名条目**项目级覆盖全局**。
- **渐进式披露**：需要某能力时 → 读**全局 + 当前项目**两级工具表；命中 → 按 `availability` 自检在线 → 按 `invoke` 调用（操作步骤见 §3.3）。
- **git 隐身**：`.arborist/` 是机器本地态，须列入 `.git/info/exclude` + `.gitignore`（adopt 脚手架已代劳）；全局 `~/.arborist/` 天然在仓外。
- **泛化边界**（[generalization-boundary](./generalization-boundary.md)）：本 guide 与模板只含占位/泛化示例；端口、域名、二进制路径、版本号等**实例具体值只进机器本地的 `tool.json` 实体条目**，凭据则连实体条目也不进（见 §2 `auth`）。

## 2. `tool.json` schema

| 字段 | 说明 |
|---|---|
| `name` | 唯一名（文件名 = `<name>.json`；小写归一） |
| `description` | 能力说明：它能给你什么 |
| `kind` | `service-http` / `cli` / `mcp`（可扩展） |
| `invoke` | 怎么调：endpoint / 命令 / MCP server 名（按 kind，可多键并列） |
| `scope` | `global` / `project`（与所在级联层一致） |
| `requirement` | `required` / `optional`（决定 init 置备策略，见 §2.5） |
| `install` | 怎么安装/启用（命令或说明） |
| `fallback` | 缺席/拒装时的兜底行为（optional 工具必填——注册表的「不卡死」承诺靠它） |
| `availability` | 怎么判断它在线：探测命令 / 端口 / 进程（优先选**只读**探测命令） |
| `auth` | 是否需鉴权及方式——只记 flag/机制名，**凭据（token/密码/连接串）绝不入表**（注册表虽机器本地，仍属可读态） |
| `notes` | 属主 / 版本 / 注意事项（如「哪些子命令有副作用，勿经注册表调用」） |
| `known_limits`（可选） | 该能力的**已知局限**清单：每条 = 现象 + 触发条件 + fallback 动作。工具输出**不是完备事实**——凡有「静默漏/静默空」失效模式（不报错却结构性漏真相，`0 命中`与「不存在」不可区分）的工具须登记（见 [§3.4 已知局限](#已知局限)） |
| `architecture`（视需要） | 该工具的**部署形态**：仅当形态会误导运维推断时登记，如 `shared-daemon`（一 daemon 多 client；detach 后 `parent=1` 属正常，**勿按 parent-PID 判孤儿去 GC**） |

**空白模板**（登记新工具时抄；adopt 亦铺在 `<repo>/.arborist/templates/tools/`）：

```json
{
  "name": "<tool-name>",
  "description": "<它能给你什么能力>",
  "kind": "service-http | cli | mcp",
  "invoke": { "<方式>": "<endpoint / 命令 / MCP server 名>" },
  "scope": "global | project",
  "requirement": "required | optional",
  "install": "<怎么安装/启用>",
  "fallback": "<缺席/拒装时的兜底行为>",
  "availability": "<只读探测命令 / 端口 / 进程>",
  "auth": "<鉴权方式 flag 名；凭据不入表>",
  "notes": "<属主 / 版本 / 副作用警示>",
  "known_limits": ["<现象 + 触发条件 → fallback 动作>（可选；有静默漏/静默空失效模式的工具须填）"],
  "architecture": "<部署形态，如 shared-daemon（可选；仅当形态会误导运维推断时填）>"
}
```

## 2.5 依赖分级与 harness init 置备（核心注册要求）

每个可注册服务标 `requirement`，决定 **adopt/init 时的置备行为**：

| 级别 | 例子 | init（adopt.sh）行为 | 缺席后果 |
|---|---|---|---|
| `required` | Trellis、Superpowers | **醒目告警「不装没法用」+ 给出明确装法**；不中断铺设（铺设永远能完成），但 harness 视为不完整 | harness 不完整，核心 workflow 跑不起来 |
| `optional` | agentsview、Multica、codegraph | **逐个问用户要不要**——同意且已装 → 登记进注册表（写 `tool.json`，幂等：已存在不覆盖）；未装 → 只**打印装法**（不代装）；拒绝 → 记未登记，打印该工具 `fallback` 一行 | 该能力走 `fallback` 兜底，**不报错卡住** |

- **非交互降级**：stdin 非 TTY（CI / pipe）时不 prompt，只打印各工具「已装/未装 + 装法 + fallback」汇总，不失败。
- **边界（不可越）**：置备段**从不自动下载/安装任何东西、从不改 agent 配置（MCP 接线）**；「写注册表 JSON」属静态表铺设，不算接线。装好工具后的登记可重跑 adopt 或照 §2 模板手写。
- 置备由 `adopt.sh` / `ADOPT.md` 落地；运行时条目的维护归 gardener（§4）。

## 3. Worked examples

### 3.1 agentsview（`service-http`，optional）——首个注册工具

本机 AI agent 会话历史查看器：把各 coding-agent 的 session 同步进 SQLite，提供历史检索/分析/会话浏览。**泛化示例**（占位值；实体条目在各机器 `~/.arborist/tools/agentsview.json`，填实测值）：

```json
{
  "name": "agentsview",
  "description": "本机 AI agent 会话历史查看器：各 coding-agent 的 session 同步进 SQLite，历史检索/分析/会话浏览",
  "kind": "service-http",
  "invoke": {
    "web_ui": "http://127.0.0.1:<port>",
    "cli": "agentsview <command>",
    "mcp": "agentsview mcp"
  },
  "scope": "global",
  "requirement": "optional",
  "install": "从其发布渠道安装二进制；`agentsview serve` 启动",
  "fallback": "无历史 agent 检索能力 → 退回手翻本地 journal / 各 brand 会话目录（如 ~/.claude/projects/）",
  "availability": "`agentsview serve status` 输出 running（兜底：端口 LISTEN / 进程 `agentsview serve`）",
  "auth": "可选 `serve --require-auth`（bearer）；远程 CLI 用 `--server <url> --server-token-file <file>`；凭据不入表",
  "notes": "<版本>；写命令勿经注册表调用（见下）"
}
```

**只读 CLI 速查**（按 agent / 项目 / 时间检索历史的主力面；`--format human|json` / `--json` 一致可用）：

| 命令 | 用途 |
|---|---|
| `agentsview session list --agent <agent> --project <name> --since 14d --json` | 按 agent/项目/时间过滤列会话（核心检索入口；`--sort` / `--limit` / `--cursor` 分页） |
| `agentsview session search "<pattern>" --project <name> --in messages,tool_result --context 3 --json` | 跨会话全文/regex/语义（`--hybrid`）搜索 |
| `agentsview session get / messages / tool-calls / usage <id>` | 单会话钻取（元数据 / 消息窗口 / 工具调用 / token 成本） |
| `agentsview session export <id>` | 流式输出原始 JSONL（local only，写 stdout） |
| `agentsview projects --json` / `agentsview health` / `agentsview stats --since 28d` | 项目清单 / 会话健康度 / 窗口化分析 |
| `agentsview openapi` | 打印 OpenAPI 3.1 schema——HTTP API 的权威文档（`/api/v1/sessions`、`/api/v1/search`、`/api/v1/projects` …，走 HTTP 时只用 GET 类端点） |
| `agentsview mcp` | 现成**只读 MCP server**（`search_sessions` / `list_sessions` / `get_session_overview` / `get_messages` / `search_content` / `get_usage_summary`） |

注意：`sync` / `prune` / `import` / `secrets scan` / `pg push` 等**有副作用**，不属注册表声明的只读用途；`session search --reveal` 会显示未脱敏 secret 值，避免使用。时间过滤统一：`--since 14d|2w|YYYY-MM-DD`、`--date-from/--date-to`。

### 3.2 Multica（`cli`，optional）——「拒装 → 走兜底」样板

任务台账 / issue 追踪。泛化示例：

```json
{
  "name": "multica",
  "description": "任务台账 / issue 追踪：Trellis 任务与 issue 同步、WIMTB 上台账",
  "kind": "cli",
  "invoke": { "cli": "multica issue|project <subcommand> --output json" },
  "scope": "global",
  "requirement": "optional",
  "install": "`multica setup` / `multica login`",
  "fallback": "台账退化为本地 .trellis/tasks/ 目录 + sendbox 交办；WIMTB 退化为本地留档，不上台账",
  "availability": "`multica auth status` 通过",
  "auth": "`multica login`；workspace 经 env `MULTICA_WORKSPACE_ID`；凭据不入表",
  "notes": "只读候选：issue get/list/search/runs/run-messages、project get/list；Trellis 接点：config.yaml hooks after_start/after_archive → scripts/trellis_multica_sync.py"
}
```

这正是「可选服务拒装 → 走兜底」的样板：harness 不因缺 Multica 而卡死，只是失去持久台账——`fallback` 字段把降级路径写成表内契约，读表的 agent 缺席时照此办事即可。

### 3.3 操作说明：agent 发现 → 自检 → 调用

1. **发现**：需要某能力（如「查历史 agent 会话」）时，`ls ~/.arborist/tools/ <repo>/.arborist/tools/`，读各 `tool.json` 的 `description` 找匹配条目（同名以项目级为准）。
2. **自检**：跑该条目的 `availability` 探测（只读）。在线 → 下一步；不在线但已安装 → 可按 `install`/`notes` 提示启动（如起本地服务）；未命中条目或探测失败 → **按 `fallback` 兜底，不报错卡住**；工具似已装却未登记 → 可提请 gardener 登记（§4）。
3. **调用**：按 `kind` 选 `invoke` 里的方式——`cli` 直接执行（优先 JSON 输出）；`service-http` 走 endpoint（只用只读端点）；`mcp` 需该 server 已在 agent 配置中接线（注册表只声明存在，**不代接**）。需要鉴权时按 `auth` 记载的机制取用户配好的凭据，**不要把凭据回写进表**。

> **分词坑**：把多词子命令存进变量再执行时，zsh 默认不对未引用变量分词——整串被当成单个参数传入，部分 CLI 会**静默回退打印根 help**（探测看似成功实则没执行）。探测/调用脚本用 bash，或在 zsh 里显式分词（`${=cmd}`）。

<a id="已知局限"></a>
## 3.4 已知局限（known limits）：把「工具输出 ≠ 完备事实」写进注册条目

注册表原来只说「有哪些能力、怎么调、是否可用」，**没有放能力已知局限的位置**——读者遂把工具输出当完备事实。但很多工具都有「静默漏 / 静默空」失效模式：不报错，却结构性地看不到一部分真相，`0 命中` 与「不存在」不可区分。这类失效若不登记，读表的 agent 无从知道该交叉核验，据错误结论写进 guide、发上行信的事已实测发生过。

**两条规则（注册要求）：**

1. **局限属于条目**：工具的已知局限写进它**自己的** `tool.json`（`known_limits` 字段；部署形态会误导运维推断时另加 `architecture`）。gardener 校验时，凡有「静默漏/静默空」失效模式的工具，其条目应带 `known_limits`。
2. **`prefer` 必配 fallback**：任何写「prefer tool X」的 spec 行，**必须同时写出 X 的 fallback 动作**（局限触发时怎么办）。只推荐、不给退路的行视为不完整——因为「prefer」被字面执行时，正是局限咬人的地方。

> 与 §2 的 `fallback` 正交：`fallback` 管「工具**缺席**时的兜底」，`known_limits` 管「工具**在、但这次输出不完备**」。

**播种示例**（取自实测；codegraph / grep / 代码索引 daemon 均为通用工具，此处按能力泛化，不含任何单机实例值。overlay 未随附这三者的 `tool.json` 示例条目，故以下以示例形式列出；真机若登记这些工具，把对应条目搬进各机 `tool.json` 的 `known_limits` / `architecture`）：

- **codegraph 漏依赖注入 / 装饰器边** — `impact <symbol>` 对经 DI/装饰器在**另一文件**消费的符号，只返回定义文件内的符号，漏掉跨文件消费边（连 import 边都可能不算）。同类风险：任何运行期注册 / 反射接线（Spring、NestJS 装饰器…）。
  - **fallback**：codegraph 用于**定位**；`impact` 的结论须先用 `grep`/`rg` **交叉核验**才算 verified。按 impact 结果做 rename / 删除前尤须核验。
- **`grep -r` 静默跳过 symlink 目录** — `-r` 不跟随 symlink 目录，对含 symlink 的树返回**静默零命中**；当树里相当比例的条目是 symlink（指向外部 store）时，`-r` 结构上看不到其中一大部分，**`0 命中` ≠「不存在」**。
  - **fallback**：可能含 symlink 的树一律用 `-R`（或 `rg --follow`）；**此处 `0 命中` 不等于不存在**。典型场景是 **worktree**——harness overlay 目录以 symlink 链回主树后，worktree 里这些目录**普遍是 symlink**，`-r` 会让你误判「仓里没有 X」。见 [roles-and-tiering «worktree 步与纪律»](./roles-and-tiering.md#worktree-步与纪律l2l3-默认在-worktree-工作)。
- **分离守护进程 `parent=1` 不是孤儿** — 采「一 daemon-per-repo + thin-client-per-session」形态的工具（如代码索引 daemon），daemon detach 后 `parent=PID 1`，看着像孤儿遗留；但它正被多个 client 连着，且通常自带 idle 超时会自回收。按 parent-PID 推断去 kill「孤儿」会终止**正在服务**的 daemon，索引虽在、连着的 session 却断，「清理」为**负价值**。
  - **登记 `architecture: shared-daemon`**；纪律：**别按 parent-PID 推断做 GC**——要回收走工具自己的 stop / idle 机制。

## 4. 生命周期与角色

- **登记**：工具由 gardener（或安装该工具的人）按 §2 schema 写 `tool.json`——机器级服务进 `~/.arborist/tools/`，项目专属进 `<repo>/.arborist/tools/`；adopt 时 optional 工具经 §2.5 prompt 顺带登记。
- **发现**：任何 AgentTUI 读级联工具表即得可用能力清单；用前按 `availability` 自检（§3.3）。
- **gardener**：维护两级工具表——定期探活、剔除失效条目（工具已卸载/服务已废弃）、校验 name 唯一与 schema 完整（optional 条目必须带 `fallback`；有「静默漏/静默空」失效模式的工具须带 `known_limits`，见 [§3.4](#已知局限)）、把新装的机器级工具登记进全局表。
- **演进（留待长期）**：若将来某 AgentTUI 要把自身能力暴露给同伴，可让其 [AgentTUI 注册表](./agenttui-registry.md)条目引用它提供的 tool 条目——两表同构即为此留的口。

## 5. 许可与边界

注册的外部工具（agentsview、Multica、codegraph …）**只引用/声明，不打包、不再分发其代码**；Arborist 及本 guide 保持 Apache-2.0。自动安装、自动 MCP 接线、能力路由/编排、跨机工具共享均在本规范范围外。
