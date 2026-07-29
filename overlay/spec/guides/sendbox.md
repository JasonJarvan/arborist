# Sendbox：跨 session 定向交办（<project> host 配置 + 信规范）

> 角色间（L4 RootOrche / L3 SubOrche / L2 Impler / L1 subagent）的异步文件交办。操作用 **`sendbox-protocol` skill**（handoff/inherit verbs）；本篇是 <project> 宿主配置 + **信的命名/frontmatter 规范**。吸纳自 HarnessStack longterm § Cross-Session Sendbox Convention。

## Handoff brand contract

**默认 brand-agnostic**：跨 session 交给 Impler、SubOrche、Reviewer 等执行角色的 handoff **默认不钉执行者 brand**。任何受支持 brand 的 session 都能接，谁接就以自己的 **actual runtime brand** 跑——作者不替未来的执行者预先钦定 provider。此时 `recipient_brand` / `route_policy` **省略**。

**仅能力驱动地钉 brand**：**只有当任务依赖某个 brand 独有的能力**（该 brand 特有的工具 / 特性，换 brand 无法等价完成）时，handoff 才携带顶层 `recipient_brand` + `route_policy`，把执行钉到该 brand。判据：

- 能写出「本任务非 `<brand>` 不可」的具体能力理由 → 钉 brand（带 `recipient_brand` + route block）。生成器只用 `(recipient_brand, lane, task_kind)` 从 `brand_routing.route_policies` 精确选择 leaf，不从作者 brand、模型名、目录名或旧信正文推断。
- 写不出这个理由 → **保持 brand-agnostic，省略 `recipient_brand` / `route_policy`**（这是默认，绝大多数 handoff 走这条）。
- 一旦钉了 brand：值缺失、未知或生成结果出现 brand mismatch —— handoff/inherit 都必须 fail closed，列出支持值并要求修正；不补默认值、不跨 brand fallback。

**与链内 same-brand 不变式区分（务必别混）**：上面讲的是**跨 session 替执行者预先钦定 brand**（默认不做）。它**不同于**链内不变式——一旦某 Impler 以某 brand 实际开跑，其向下所有 L1 subagent 必须同 brand、不伪装：

`effective_subagent_brand = impler.spec.brand`

（implement / TDD / refactor / Explore / check / challenge / research 都不跨 provider；见 ADR-0006。此不变式**恒成立**，与 handoff 是否钉 brand 无关：brand-agnostic handoff 只是把「以哪个 brand 开跑」留给接手方决定，接手后链内仍严格同 brand。）

Human 收件人不执行 task，从不带 brand。执行角色**默认也不带**；只有上述能力驱动情形才带。

宿主配置的 `brand_routing` 是**能力驱动 handoff 用到的路由表**（brand-agnostic handoff 不查它）。启用时必须采用 cc-sendbox 0.6 的 `brand_routing` schema：`task_executing_roles`、`supported_brands`、`same_brand_policy: strict`，以及精确三层 `route_policies.<brand>.<lane>.<task-kind>`。每个 leaf 都必须有全局唯一 `policy_id`、非空 `route_fragment` 和显式 `agent` / `model`（由 runtime 决定时写 YAML `null`）。缺 tuple、重复 ID 或旧 schema 都是不兼容配置，必须在写信前失败。

## 目录结构（`toAgent/` + `toHuman/`）
```
.work_context/sendbox/
  toAgent/                 # 收件人是 agent 角色
    toRootOrche/           # per-project 近似单例 → 通用目录
    toSubOrche/            # 同上
    to<TaskName>Impler/    # impler 多实例 → 按任务限定（如 toAgentAuthImpler/），勿铺通用 toImpler/
  toHuman/                 # 收件人是人
    toUser/
    toTestTeam/
```
- `<Role>`/`<Receiver>` 是**角色/职能**，非 session 名（session 短命、角色不）。
- **impler 收件目录必须按任务限定 `to<TaskName>Impler/`**：impler 是**多实例**（每个并发任务一个 impler），通用 `toImpler/` 会让多个并发 impler 的信在同一目录里相互冲突。理由分层：rootorc / suborc / gardener 近似 per-project 单例 → 保持通用 `toRootOrche/` 等；impler 多实例 → 必须任务限定。TaskName 取该任务 slug（如 `eve-42` → `toEve42Impler/`）。
- 都在 `.work_context/`（git-ignored → 本地；副仓 `hgit` 记历史）。

## 持久化与可见性（形态 A / B —— **本布局 = 形态 B**）
信件的持久化与可见性取决于宿主仓 git 配置，两形态，adopt 时确定并写明：

- **形态 A —— sendbox 纳入宿主 git**：信随分支合并流动，跨 worktree / 跨 checkout / 跨机器协作方可见、可经 MR 评审；代价是内部协作记录进产品仓历史。
- **形态 B —— sendbox 排除出宿主 git（Arborist 脚手架默认推荐，本仓即此）**：`.work_context/` 被 `.git/info/exclude` 排除、由副仓 `hgit` 记史。含义：
  - **`sendbox-protocol` skill 的「把信提交在 worktree 分支上、随合并流动」这条 Cross-cwd 路径在本布局不成立**——信不在产品 git 里。跨 worktree / 跨 cwd 只能**用绝对路径直写宿主主仓**的 sendbox——**这才是 `read_first` 必须绝对路径的根因**（不只是「相对路径悬空」，是信与规范本身都不在 worktree 里；worktree 里静默拿到空结果比报错更危险）。
  - **可回溯性靠 `hgit`（人工触发、无 remote）**：无步骤强制 `hgit` 时「有历史」是习惯非保证，换机 / 删除即全丢——而信的 lifecycle 常含跨天 `persist`，此承诺要额外留意。
  - **跨机 / 跨人不可见**：协作方在另一台机器上，这封信对它不存在；跨机需另走渠道。
  - **精确暂存到文件**：`hgit add <file>` 按文件、勿整目录 `add -A`——整目录会把并发会话改到一半的文件一并提交。
- **脱敏 × git 归属**：若你用的写信技能在信尾追加 `<!-- These letters are committed to git … -->`，**那句在形态 B 不成立**（信不进产品 git，别据它判断可见性 / 该不该写敏感信息）；但**脱敏要求两形态都保留**——任何形态下都不写明文密钥 / token / PII（本机 `hgit` 同样是可读态）。

## 信命名规范
`from-<task>-<type>.md` —— `<task>` = 来源 L2/L3 task 的 slug；`<type>` ∈
`handoff`（派活）· `done`（交付回报）· `ack`（确认）· `blocker`（阻塞）· `greenlight`（放行请求）· `plan-ready`（计划待评审）· `decisions`（决策记录）· `smoke`（人工 smoke 手册）· `fyi`（通报：我在自己 lane 处理 / 已处理，你知道就好——**不转移归属、不请求行动**；与 `blocker`「我卡住你来定」语义相反。防「通报被当交办」，见 [roles-and-tiering.md](./roles-and-tiering.md)「ATUI 归属边界」）。
例：`toAgent/toEve42Impler/from-eve-42-handoff.md`（impler 目录按任务限定 `to<TaskName>Impler/`，见 §目录结构）、`toHuman/toUser/from-eve-42-greenlight.md`。

## Frontmatter 规范
**单收件人 + 瞬态**信可省 frontmatter（默认 burn，收件人 lifecycle 结束即 `rm`）。**多收件人 / durable** 信**必须**带：
```yaml
---
recipients:
  - role: <Impler|SubOrche|RootOrche|User|TestTeam>
    purpose: <为何读这封>
    lifecycle: <终止条件，如 "L2 started" / "signed off">
recipient_brand: <claude-code|codex>  # 可选；仅能力驱动 handoff 用（任务依赖某 brand 独有能力时才带），否则省略 → 谁接谁定
route_policy:                         # 可选；与 recipient_brand 成对出现，仅能力驱动 handoff 用
  policy_id: <selected-policy-id>
  lane: <fast|full>
  task_kind: <implement|explore|check|challenge|research>
  agent: <selected-agent-or-null>
  model: <selected-model-or-null>
on_lifecycle_end: burn | archive | wimtb   # wimtb=蒸馏进对应 Multica issue 后 rm
task: <L2/L3 task 目录>
multica_issue: <task.json.meta.multica_issue，如有>
created: <YYYY-MM-DD>
created_in: <来源角色/session>
---
```
- 无 frontmatter 又无单一明确收件人的信 = 畸形。

## Handoff 信必备正文（交办给执行角色，见 `_TEMPLATE-handoff.md`）
1. **`read_first`（绝对路径，硬性 N19）**：`<REPO_ROOT>/.trellis/workflow.md` + 相关 guides + 该任务 `prd.md`（worktree/独立 session 看不到被 exclude 的 harness overlay，相对路径悬空）。
2. **process-completeness（N20）**：遵标准 Pipeline，或逐条声明短路的 step（接收方抄进自己 task 记录）；不得静默省略 TDD/security-scan/HITL。
3. **任务引用** + Multica issue。
4. **（仅能力驱动 handoff）recipient brand + route block**：默认省略——brand-agnostic handoff 不写 `recipient_brand` / `route_policy`，谁接谁以自己的 actual runtime brand 跑。仅当任务依赖某 brand 独有能力时才带：顶层 `recipient_brand` 与 `route_policy` 必须来自 `_handoff-config.yaml` 的精确 `(brand, lane, task_kind)` leaf；`policy_id` / `agent` / `model` 必须一致，正文只渲染该 leaf 的 `route_fragment`。

## Done 信与验收证据的 claim provenance 门

**为什么有这条门**：本轮连栽三次「文档/声称承诺了代码做不到的事」——技能自称有 fixtures/quick-validate（实为零测试）、承诺 durable 文件「会现形」（在该仓 tracked `.gitignore` 配置下为假）、把「只验了配置」描述成「已验跨机持久性」。三个不同作者（含写这条门的人自己）都栽了 ⇒ 靠自觉无效，按 [`verification-and-gates`](./verification-and-gates.md) 的「门有执行者吗」通则，这条要的是**机械产物**：一张必填的表 + 一个会失败的 validator。

### 1. 触发与执行模型（**两个消费点，不是通用 task hook**）

门只在两个时刻被答复，且都在**消费该证据的那条流程里**：

1. **新 done 信发出前**；
2. **新建 / 实质重写的 acceptance evidence 被接受前**。

**诚实说明执行者边界**：done 信通常落在被排除出产品 git 的 sendbox（见上「持久化与可见性（形态 A / B）」），**任何 CI 都看不见任意 adopter 的 sendbox**——所以不存在「CI 会替你把这条门跑了」。CI 能校验的只是 validator 自身行为；让门在真信上生效的，是那两个时刻的人/agent 对**精确路径**跑它。它也**不是**挂在每个 task 上的通用 hook：不产生对外验收结论的任务不进本门。

存量边界按**消费时点**判定，不按文件创建时间或 mtime：

- 门启用前已被接受、消费完成的历史产物**不追溯**；
- 即使写于门启用前，只要仍在等待首次接受，就必须先迁成标准四列表；
- 已消费的历史产物若被拿来支撑**新一轮**验收，重新进入本门；
- **实质重写等同于新产物**，进入本门。

判据只问一句：**这次受门保护的验收消费是否已经发生？** 尚未发生就按新门办；已发生且没有新一轮消费才属不追溯。

### 2. 命令

```sh
python3 <REPO_ROOT>/.trellis/scripts/validate_claim_provenance.py <精确路径> [...]
```

退出码：`0` 全部合格；`1` 校验失败；`2` 用法/环境问题（输入不可读 ⇒ fail closed，什么都没校验）。给的是**精确文件路径**，不是目录——目录展开会让「顺手多带几个文件」冒充「逐条核过」。

### 3. 契约

done 回投用 `<REPO_ROOT>/.work_context/sendbox/_TEMPLATE-done.md`（adopt 铺，与 `_TEMPLATE-handoff.md` 同目录）。所有会被收件方用于验收、决策或继续实现的结论，必须逐条进入标准表；表外叙述可解释上下文，但**不算验收证据**。canonical 表头为 **schema v1**，四列定序：

| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| `<单一结论>` | `实测` | `<命令输出 / artifact / path:line>` | `无` 或具体缺口 |
| `<单一结论>` | `推断` | `<已核前提 + 推理依据>` | `<尚未验证的具体一步>` |

- **表头是本框架的 schema 选择，不是业务耦合**。validator 按上面四个列名**精确匹配**（列名后的括号注解如 `（实测/推断）` 会被剥掉），**不做模糊表头猜测、不认英文别名**：认不出的表头一律报「缺表」，绝不半校验。要加英文别名 ⇒ 那是**显式版本化的 schema 变更**（声明 v2 表头集并同步模板），不是教匹配器去猜。
- 类别只允许 `实测` / `推断`；一行同时含两者时**必须拆行**。
- `实测` 的出处必须能让第二读者复核；只写「我看过」「测试绿」不够。
- `推断` 不是违规，但必须写出已核前提，并在「未验证缺口」点明哪一步尚未验证；**`推断 + 未验证缺口=无` 不合格**。
- `实测` 确无缺口时写 `无`（不是留空）。**单表达到 4 行后**，若所有行的非 `无` 缺口经规范化后完全相同，validator 视为「必填字段被一个复制常量满足」并 fail。共同限制确实适用于全表时，也要逐行写清它如何约束**该条**结论；**不提供字符串豁免**。

### 4. 校验与错误矩阵

| 条件 | 结果 |
|---|---|
| 缺 canonical 四列表（含表头认不出的情形）| fail (1) |
| canonical 表头后没有合法 Markdown 分隔行 | fail (1) |
| 结论 / 出处 / 未验证缺口 为空或仍是 `<占位符>` / `TBD` 等 | fail (1) |
| 类别不是 `实测` / `推断` | fail (1) |
| `推断` 的未验证缺口为 `无` / `none` / `N/A` | fail (1) |
| 单表 ≥4 行且整列复制同一个非 `无` 缺口 | fail (1)；逐行改成 `无` 或与该结论相关的具体缺口 |
| 输入路径不是文件 / 不可读 / 非 UTF-8 | fail closed (2)，不给任何合格结论 |
| 至少一张 canonical 表，且每行满足契约 | pass (0) |

### 5. Good / Base / Bad

- **Good**：`实测` 行给命令与结果 artifact；`推断` 行给已核前提并明确尚未跑的那步线上验证。
- **Base**：实测确无缺口写 `无`，不是留空。
- **Base**：三行以内可共享同一真实缺口；四行以上的共同限制须逐行说明与各结论的关系。
- **Bad**：写「测试绿，所以线上安全」并把整句标成 `实测` —— 应拆成一条实测 + 一条推断。
- **Bad**：八条异质结论的缺口列复制同一句「未覆盖真机」——其中 diff/lint 结论与真机无关，常量虽满足必填形状，却让读者跳过整列、并淹没真正有该缺口的那几行。
- **Bad（已发生过的权威文本反例，通用化叙述）**：某 adopting repo 的一份 accepted ADR 把「**实测**：继承进程组的孙进程会被回收」写成全称的「孙进程都会被回收」。后来一个真 `setsid()` 的孙进程反例证明逃逸后代不在原进程组内。若当时出处栏写清了「被测进程的建组方式」，「窄实测」与「全称结论」的范围不一致会在接受**前**直接显形 —— 这正是出处栏存在的理由（该类事实性更正怎么走见 [`repomem-doc-boundary`](./repomem-doc-boundary.md#accepted-adr-的事实性更正边界)）。

### 6. Wrong vs Correct

```text
Wrong:   端口规则已验证        | 实测 | 测试绿                       | 无
Correct: 测试端口为 <value>    | 实测 | `path:line` / 命令输出        | 无
         规则适用于全部 probe  | 推断 | 已核调用点列表               | 尚未枚举动态调用

Wrong:   4+ 条异质结论 | 实测 | 各自出处 | 每行复制同一句非空缺口
Correct: 无缺口的行写「无」；真有共同限制的行写清该限制如何约束本行结论
```

验收证据文档另有模板：[`_TEMPLATE-acceptance-evidence.md`](./_TEMPLATE-acceptance-evidence.md)。门在 gate matrix 里的必答时刻与留痕位见 [`verification-and-gates`](./verification-and-gates.md#门控矩阵每个门一个必答时刻)。

## 自动路由 vs 人确认（durable 边界，A2A 自动化判据）
交办可自动化（若接入了某个瞬态通信后端）到什么程度，按下列切分：
- **瞬态 = 全自动、免确认**：ack / 状态 / done 通知 / blocker 上报 / 提问 —— 纯协调 chatter，直接自动路由。
- **durable = 自动送达 + 落定前人确认**：满足任一——① 映射到某 task/EVE；② 产生/改变决策、计划、晋升候选；③ 需 outlive 会话成为记录（plan-ready / decisions / 改 scope 的 delivery / 晋升候选）。**自动送达**，但接收侧/门在"认作已承诺/落定"前**停下等 user 确认**（对齐 HITL/ask-first）。
- 一句话：**协调 chatter 全自动；承诺级记录 自动送达 + 落定前人确认。**

## 生命周期
- 瞬态（ack/greenlight/blocker/done/fyi）→ **burn**。
- durable 且映射 L2/L3 → **wimtb**（蒸馏进 Multica issue + 附原信 → 验证 → `rm`；同 verification-and-gates WIMTB 不变式）。
- 无 EVE 的 durable 信 → 留 `.work_context/` 或升级 guide，不硬塞无关 issue。

## Inherit（接收方"继承"handoff——handoff 的读取侧）
handoff 是**写**（派活方投信）；inherit 是**读/接管**（接收会话"继承"这封信开工）。接收角色开一个新 session 后：
1. **校验 recipient brand + route policy（仅当 handoff 钉了 brand）**：若信**未带** `recipient_brand`（默认 brand-agnostic）→ 任何受支持 brand 的 session 都可继承，直接以**当前 actual runtime brand** 开跑，无需校验此步。若信**带了** `recipient_brand`（能力驱动）→ 它必须是受支持值且与当前 actual runtime brand 一致；再按 frontmatter 的 lane/task_kind 重解 config leaf，并核对 `policy_id` / `agent` / `model` 与正文 Selected route，任一不一致即停止继承。（注：无论哪种，接手后链内 L1 派活仍严格遵 `effective_subagent_brand = impler.spec.brand`。）
2. **读 `read_first`**（信里列的绝对路径：workflow.md + 相关 guides + 该任务 prd）——绝对路径保证 worktree/独立 session 也能加载被 exclude 的 harness overlay（N19）。
3. **按 process-completeness 声明续流程**：遵 workflow.md 标准 Pipeline，或采纳信里逐条声明的短路 step（抄进自己 task 记录，不静默绕门）。
4. **认领任务**：从信的 `task` 字段定位 L2/L3 task 目录 + Multica issue，进入对应 Phase（如"从 Phase 2 TDD 入"）。
5. 完成后按信尾写 `from-<task>-done.md` 回投来源角色。
> handoff/inherit 是一对动作，操作可由 `sendbox-protocol` skill 的 handoff/inherit verbs 执行；本节定义 Arborist 语义。

## 与 Trellis 的关系
Trellis 无原生定向交办；`trellis mem`+journal+task 目录覆盖"回忆/连续性"，sendbox 补"定向指令"层。live 多代理才考虑 `trellis channel`。
