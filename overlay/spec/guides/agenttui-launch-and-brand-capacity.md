# 安全启动 AgentTUI + brand-capacity observer

> 两项**共享契约**的启动侧姊妹规范：(1) 如何**安全启动一个独立 AgentTUI**（不依赖当前焦点 pane、不继承父身份、不代写 brand）；(2) 建新 Impler 前如何用一个**只观测的 brand-capacity observer** 按容量选 brand。二者共享同一底座——启动器只选**启动哪个 CLI 二进制**，被启动会话**自登记真实 brand**；observer 只**观测 + 只读推荐**，绝不启停会话、不改注册、不碰凭证。
>
> 姊妹规范：**[AgentTUI 注册表](./agenttui-registry.md)**（同伴发现 + 投递契约 §3）、**[工具注册表](./tool-registry.md)**（可选能力发现）。架构决策见 **[ADR-0007](./decisions/0007-agenttui-delivery-contract-pluggable-adapter.md)**（投递契约）与 **[ADR-0008](./decisions/0008-brand-capacity-and-safe-launch.md)**（本规范三决策）。

## 1. 安全启动 AgentTUI 契约

启动一个**新的、独立的** AgentTUI（非往已存在的活会话投递——那是 [agenttui-registry §3](./agenttui-registry.md) 的投递契约）时，必须满足以下不变量。命令一律用泛化占位（`<REPO_ROOT>` / `terminal_<N>` / `<claude|codex>`），照本机实况替换。

### 不变量

1. **一 tab 一 AgentTUI**：每个 Zellij tab 只承载一个 AgentTUI 会话，避免同 tab 内多会话身份/焦点混淆。
2. **以 new-tab 的初始命令原子启动**，而非往匿名焦点 pane 打字。启动同时**清除继承的 session-context 身份**，让子会话自建身份：

   ```
   zellij new-tab -- env -u TRELLIS_CONTEXT_ID <claude|codex>
   ```

   `TRELLIS_CONTEXT_ID` 是 session-context 身份变量；不 `-u` 清掉它，子会话会**继承父 session 身份**、进而投错 pane 或替被启动方猜/写 brand。
3. **resolve 并校验一个稳定的非插件 pane_id**，再做任何 bootstrap 写：

   ```
   zellij action list-panes --json --all
   ```

   按 `tab_name` + `cwd` + `command` 组合定位目标的 `terminal_<N>`（真实终端 pane，**排除插件 pane**）。多候选 / 冲突 / 无匹配 → **fail closed**（停下人工确认），绝不猜。
4. **所有 bootstrap 写显式定向到该 pane**，绝不写焦点 pane：

   ```
   zellij action write-chars --pane-id terminal_<N> "<bootstrap text>"
   ```
5. **被启动会话自登记其真实 brand 与 pane 引用**（见 [agenttui-registry §2](./agenttui-registry.md) 的 `spec.json.brand` / `runtime.pane_ref`）。**启动器绝不代写 brand**——它只选启动哪个 CLI 二进制，实际 runtime brand 由被启动会话按 [ADR-0006](./decisions/0006-runtime-brand-is-routing-authority.md) 自登记。
6. **绕过权限提示时保留 ask-first / HITL 边界**：被启动 CLI 若以绕过权限提示的模式运行，仍须遵守 [execution-policy](./execution-policy.md) 的 ask-first / HITL 门；guide 与 bootstrap 文案须显式标注越权面与人工确认点，不得因「已绕提示」而静默做不可逆操作。

> 与 [agenttui-registry §3](./agenttui-registry.md) 的投递契约同源：pane 定向（`--pane-id`）在两侧通用——启动侧用于 bootstrap 定向，投递侧用于跨会话注入。本规范是其**启动侧姊妹**。

## 2. brand-capacity observer 契约

`arborist_brand_capacity.py` 是一个**单写者、纯 stdlib、无网络、不读/存/打印凭证**的本地 observer。它**只观测 + 只读推荐**，**绝不**：启停会话、改 agent 注册、代写 brand、跨 brand 切既有 Impler（或其 L1 链）、做不可逆调度决策。

adopt 后铺在 `<REPO_ROOT>/.trellis/scripts/arborist_brand_capacity.py`（脚本按 `__file__.resolve().parents[2]` 定位仓根，故须两级深）。

### 2.1 CLI 表面

全局选项（均有默认，仓根 = `parents[2]`）：

| 选项 | 默认 | 说明 |
|---|---|---|
| `--repo` | 仓根（`parents[2]`） | 项目根 |
| `--config` | `.work_context/sendbox/_handoff-config.yaml` | host 路由配置（闭集来源） |
| `--state` | `.arborist/runtime/brand-capacity.json` | 快照落盘路径 |
| `--reports-dir` | `.arborist/runtime/brand-capacity-reports` | self-report 落地目录 |
| `--codex-sessions` | `~/.codex/sessions` | Codex rollout 扫描根 |
| `--claude-command` | `claude` | Claude Code 可执行名（collector 用） |
| `--claude-timeout-seconds` | `20` | collector 子进程超时 |
| `--lock` | `.arborist/runtime/brand-capacity.lock` | 单写者 flock 文件 |

子命令：

| 子命令 | 角色 | 行为 |
|---|---|---|
| `refresh` | 写者（取 flock） | 重建快照 + 原子写 `--state` + 打印 JSON |
| `status` | 无锁读者 | 打印当前快照 |
| `report --agent <name> --input <path>` | 写者（取 flock） | 按 `.arborist/agents/<name>/spec.json` 的真实 brand 校验后，原子写 `<reports-dir>/<name>.json`（self-report fallback 落地） |
| `recommend --role {impler,orchestrator} [--max-age-seconds N]` | 无锁读者（默认 `900`） | 打印建议；`selection_scope` 恒 `impler-creation-only` |
| `serve [--interval N] [--once]` | 写者（取 flock，`interval` 默认 `60`） | 前台周期 refresh 循环（**非 daemon**）；`--once` 单次即退 |

退出码：`0` 成功 / `1` `CapacityError`（锁占用、无 state、无候选、schema 非法等，stderr `error: <msg>`）/ `2` 兜底。成功输出均 stdout JSON。

- **原子写**：`0600` tmp + `fsync` + `rename`，失败不留 tmp。
- **单写者**：`flock(LOCK_EX|LOCK_NB)`，占用即 fail-closed（退 `1`），不等待。

### 2.2 快照 schema（source + freshness 显式）

快照落 `<REPO_ROOT>/.arborist/runtime/brand-capacity.json`（runtime 层，不入产品仓；脚本按需建目录）：

```
{
  "schema_version": <int>,
  "generated_at": <iso8601-Z>,
  "supported_brands": [<brand>, ...],        // 仅来自 host 闭集
  "brands": {
    "<brand>": {
      "status": "observed" | "unknown",
      "source": "polled" | "self-reported" | "unavailable",
      "observed_at": <iso8601-Z | null>,
      "windows": [
        { "name": <str>, "used_percent": <0-100>,
          "window_minutes": <int?>, "resets_at": <str|num?> }
      ]
    }, ...
  },
  "diagnostics": [ ... ]                       // 陈旧/歧义/失败原因，显式
}
```

- **unknown 行**（默认态 / 无可信观测）恒为：`status=unknown` + `source=unavailable` + `observed_at=null` + `windows=[]`。
- `observed_at=null` ⇒ **永远不能被当 fresh headroom**。
- freshness 由 `recommend` 用 `--max-age-seconds` 判定；超龄 → 退化为 unknown-for-selection。

### 2.3 数据源与 source/freshness 语义

- **闭集来源**：`supported_brands` **只**来自 host 路由配置（`--config`）的 `supported_brands` 列表（零依赖手写 parser，不引 YAML）。**不在闭集的已装 CLI 永不进候选**。无闭集 / 空列表 → fail-closed（`CapacityError`）。parser **仅认嵌套块状列表**（`supported_brands:` 键下方、缩进更深的 `- <brand>` 行，与随附 `_handoff-config.yaml` 模板形状一致）；flow 风格内联列表（`[a, b]`）或与键同缩进的列表**不识别** → 解析为空 → fail-closed（拒绝，而非降级）。
- **Codex（被动 polled）**：只读递归扫 `~/.codex/sessions/**/rollout-*.jsonl`，取最新一条记录里的 `rate_limits`（primary/secondary window）。值是权威服务端响应，但**被动落盘** → 靠 `observed_at` 判陈旧；无网络、不读凭证。
- **Claude Code**：见 §2.4 collector（`source=polled`）；collector 失败时以 `report` 落地的 in-session 自报作 `source=self-reported` fallback；二者皆无 → `unknown`。
- **禁**：cost / burn rate / time-to-window-boundary **一律不作 headroom**——只可进 `diagnostics` 作旁证，绝不进 `used_percent`。

## 2.4 Claude Code 容量 collector

机制：子进程机械跑

```
claude -p /usage --output-format json
```

- **外部进程随时可 poll**，**不要求**已有登记 / 活跃交互 session；observer 借本机 Claude CLI 登录态运行内置 `/usage`，但**不读取 / 复制 / 传递任何 token**（no-credentials 边界不破）。子进程 stdin 断开、并清除继承的 `TRELLIS_CONTEXT_ID`，不泄父身份。
- 成功观察 = 主动 poll → `source=polled`。`observed_at` = **observer 调用时刻**，只表**查询新鲜度**，**不冒充服务端数据生成时刻**——Claude 内部有 `cachedUsageUtilization`，未证明每次 `/usage` 都绕缓存做服务器往返；按 `--max-age-seconds` 消费。它**不是** in-session self-report 的实现机制。
- **采信门（全部满足才落 headroom，否则 fail-closed 到 unknown）**：
  1. `is_error` 为 `False` 且 `subtype == "success"`；
  2. `num_turns == 0` 且 `total_cost_usd == 0`（零副作用证明，确保没跑 model turn）；
  3. 输出 `result` 命中明确的 session / week 用量行，可映射到 `windows[]`。
- **fail-closed 面**：collector 缺失 / 超时（短超时）/ 格式漂移 / 非零退出 / 采信门任一不过 → **不落 headroom**，记 `diagnostics`，该 brand 回退 unknown（或 self-report fallback）。
- **`source=self-reported`** = collector 失败时的**独立可信 fallback**：已登记会话在会话内跑 `/usage` 得到的观测，经 `report --agent <name> --input <path>` 落地（按该 agent `spec.json` 的真实 brand 校验，brand 不符即拒、不落 headroom）。二者皆无 → `unknown`。

> **契约定位（supersede 说明）**：collector 让 Claude Code 可被**随时 poll**，因此 **supersede** 上游 issue #14 正文那句 prose「Claude Code headroom is unknown unless a registered session self-reports」。理由:该 prose 写就时尚未发现「外部进程可机械借登录态 poll `/usage` 且零副作用」这一能力;collector 是其后发现的更强路径,self-report 从「唯一来源」降为「collector 失败时的 fallback」。self-report 仍作为一等 CLI 操作（`report`）+ brand-mismatch 校验保留,故 AC 无冲突。字段行为标注 Claude Code 版本相关;字段漂移则 collector 降级 best-effort、fail-closed 到 unknown,不影响其余路径。

## 3. selection 语义（仅建新 Impler）

`recommend` 的建议**仅在建新 Impler 前合法**（输出 `selection_scope=impler-creation-only`）。

- **优先 fresh、可比的容量观测**：fresh headroom（`status=observed` 且未超 `max-age` 且有可比 `used_percent`）压过 role affinity；选 fresh 候选里**最小 window headroom 最大**者。
- **role affinity 只作显式标注的 fallback / tie-breaker**：全无 fresh 观测时才退化到 role affinity，且输出 `decision_quality=role-affinity-fallback` 显式标注；有 fresh 时 affinity 仅用于并列破平。
- **launcher 选二进制，session 自登记 brand**：推荐只影响「启动哪个 CLI 二进制」；被启动会话仍按 §1.5 / ADR-0006 自登记真实 brand。
- **既有 Impler 及其 L1 链绝不跨 brand 切换**：容量中途耗尽 → **停下，handoff 给新建 Impler**（`constraints` 字段显式声明此不变量），绝不把运行中的 Impler 换 brand。

## 4. 边界 / HITL / multi-account

- **cost / burn / time-to-boundary 不作 headroom**（见 §2.3）。
- **multi-account 歧义（已知局限，非机械检测）**：observer **不区分**共享 `~/.codex/sessions` 的多个本地账户——它取全局最新的一条 rollout 观测，**不做账户分区、不检测歧义、不为此自动记 `diagnostics`**。因此**跨账户场景必须由人工解决/确认**：若本机有多个 Codex 账户共用会话目录，observer 报的 headroom 可能来自**另一账户**（且会被标 fresh），此时**不可依赖其推荐**，须人工判定当前会话账户的真实容量。这是文档化的边界，不是自动兜底。
- **无网络、无凭证**：observer 全程无网络访问，不读 / 存 / 打印任何 token；collector 借本机 CLI 登录态但不碰 token。
- **observer 不是执行者**：任何「按推荐启动会话」的动作都在 observer 之外，由 §1 的启动契约 + 人工 / 编排层执行；observer 只产出只读建议。
