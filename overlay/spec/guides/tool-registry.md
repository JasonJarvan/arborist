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
  "notes": "<属主 / 版本 / 副作用警示>"
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

## 4. 生命周期与角色

- **登记**：工具由 gardener（或安装该工具的人）按 §2 schema 写 `tool.json`——机器级服务进 `~/.arborist/tools/`，项目专属进 `<repo>/.arborist/tools/`；adopt 时 optional 工具经 §2.5 prompt 顺带登记。
- **发现**：任何 AgentTUI 读级联工具表即得可用能力清单；用前按 `availability` 自检（§3.3）。
- **gardener**：维护两级工具表——定期探活、剔除失效条目（工具已卸载/服务已废弃）、校验 name 唯一与 schema 完整（optional 条目必须带 `fallback`）、把新装的机器级工具登记进全局表。
- **演进（留待长期）**：若将来某 AgentTUI 要把自身能力暴露给同伴，可让其 [AgentTUI 注册表](./agenttui-registry.md)条目引用它提供的 tool 条目——两表同构即为此留的口。

## 5. 许可与边界

注册的外部工具（agentsview、Multica、codegraph …）**只引用/声明，不打包、不再分发其代码**；Arborist 及本 guide 保持 Apache-2.0。自动安装、自动 MCP 接线、能力路由/编排、跨机工具共享均在本规范范围外。
