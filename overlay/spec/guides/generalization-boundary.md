# 泛化边界：让同步机械化、隐私结构化（Arborist 技术基石）

> Arborist 模板（泛化、占位）与实例仓（具体值）**故意隔一道「泛化 gap」**（见 [`arborist-sync`](../../../skills/arborist-sync/SKILL.md)）。本篇是这道 gap 的**权威定义**：什么算「实例特定」、它该放哪、为什么这样能让**下行同步退化成 `git subtree`（机械）**、**公开上推退化成一次轻确认（而非费劲擦洗）**。
>
> 核心一句：**私有内容从一开始就别进被同步的文件——预防 > 检测 > 判断。**

## 为什么要这道边界

同步与隐私是同一枚硬币。若 guide 正文里混进实例具体值（绝对路径、产品代号、tracker ID…），会**同时坏两件事**：

- **同步**：拉更新要 sed 转换、要人调冲突；推贡献两侧永远不一致（漂移）。
- **隐私**：上推公开仓时，具体值就是泄漏——而散在正文里的**语义泄漏 regex 抓不全**（unknown unknowns）。

反过来，若 guide **天生只含泛化内容**：下行 = 纯拷贝 / `git subtree`；上行 = 结构上无私可泄，隐私门退化成一次点头。**这就是这道边界的全部收益。**

## 规则：被同步的 guide 不得含实例特定值

实例特定的东西只许落在**三处，且三处都不参与向上游同步**：

| 放哪 | 装什么 | 例子 | 谁读它 |
|---|---|---|---|
| **占位符**（guide 正文内） | 会被机械替换的路径/名字 | `<REPO_ROOT>` `<project>` `<HOME>` | `arborist-sync` 的 sed（pull 特化 / push 泛化） |
| **`workflow.md` 定制层** | 实例的**行为/策略**覆盖 | git/MR 流、Lane 触发、工具选型（有无 codegraph）、扫描器 | 运行时读 workflow.md 时（update-safe，不在 trellis update hash）。**注意：定制层正文本身不被 SessionStart / 每轮 breadcrumb 自动注入**——见下节「注入子集边界」 |
| **`host-config`**（`.trellis/host-config.yaml`；实例本地、`hgit` 记史、**永不同步**） | 实例**具体值**的单一真源 | 仓根绝对路径、项目名、Multica/tracker IDs、子树清单、语言/扫描器名、组织 git 约定、**spec/ADR 可见性档 `spec_visibility`** | 运行时 + `arborist-sync` 取值做替换 |

**授权判据**：往 guide 正文写一个值之前，问一句——「另一个仓 clone 这份 guide，这个值还成立吗？」不成立 → 它是实例特定的，**移出去**（上表三处之一），正文留占位或引 host-config 键。

> **推论（可见性/git 状态也是实例值）**：guide 正文若断言「spec/ADR 是 git-tracked、团队共享」，那是把一个**实例特定的可见性状态**焊进了同步物——换个 adopter（overlay 脚手架默认对产品仓隐身）该断言即为假，正是本判据要拦的错。可见性属实例值：其档位由 host-config `spec_visibility: product-git | machine-local` 定，guide 只描述**两个世界**、不预设某一个。此轴与「上行同步可见性」正交——`spec_visibility` 说的是 spec/ADR 是否进**产品仓 git**，非是否上推模板。两个世界各得/各失什么见 [`repomem-doc-boundary`](./repomem-doc-boundary.md) 「spec/ADR 可见性」节。

## 注入子集边界：定制层 ≠ 被加载

> 通则：**任何只注入一个文件【子集】的脚手架，都必须在文件里、在边界处，说明它注入的是哪个子集。** 否则子集外的内容读着完美、被版本管理、被别处引用，却**没有任何 session 会加载它**，与「根本不生效的规则」无法区分——直到出事。这是脚手架自造的陷阱，非作者之错。

Arborist 的活样本就在 `workflow.md`：SessionStart hook（`.claude/hooks/session-start.py` → `_build_workflow_overview`）只注入 `## Phase Index`→`## Phase 1: Plan` **一个范围**；每轮 breadcrumb（`inject-workflow-state.py`）只发 Phase Index 内的 `[workflow-state:*]` 块。而**定制层贴在 `## Core Principles` 之后 → 两个注入路径都够不着 → 定制层正文不被任何 session 自动加载**。

⇒ 放置纪律（`workflow-customization.md` 已落地为清单）：

- **正文**（策略/判据全文）留定制层：版本化、可被 guide 引用。
- **入口**：凡「必须到达每个 session」的规则，在**被注入范围内**（Phase Index 段）或对应 step 的 `get_context.py --mode phase --step X.Y` 详情里，留一行 `- [local]` 指针。
- **格式硬约束**：入口必须是 `- [local] …` **列表项**。`_strip_breadcrumb_tag_blocks` 把**行首** `[xxx]` 当 tag 剥掉——裸行 `[local] …` 的标签会被吃掉，`- [local] …`（前缀 `- `）整行保留。
- **机械核对**（别肉眼估）：import hook 模块 → 打印它构建的 overview → grep 关键字断言命中。片段见 `workflow-customization.md` 文末「注入放置验证片段」。这就是给「放对了吗」这道荣誉制门配一个机械产物（参 [`verification-and-gates`](./verification-and-gates.md)）。

## 绝不进入被同步文件的东西（结构性排除，机械可保证）

同步 allowlist **只含** `spec/guides/`、`workflow-customization.md`、`scripts/`。下列**都在范围外**，机制物理上碰不到：

- **个人身份**：`.developer`、`workspace/<you>/`（会话日志）
- **个人 WIP**：`tasks/`、`.runtime/sessions/`
- **运行时/机器态**：`.mcp.json`、`__pycache__`、`.harness-vcs/`
- **内部协调/策划**：`.work_context/` 正文（sendbox 信、reports、proposal）——**只同步模板骨架，不同步内容**
- **密钥 / 其它私有项目名 / 邮箱 / UUID**

→ 「没被看到 → 进不去」，这是最强的机械保证（**白名单 > 黑名单**）。

## 收益：同步 × 隐私 成本表

| | guide 混了实例值（坏） | guide 天生泛化（好） |
|---|---|---|
| 下行 pull | sed 特化 + 每次调冲突 | `git subtree`/纯拷贝，冲突才要人 |
| 上行 push → 内部源 | 泛化 + 冲突 | 近纯机械 |
| 上行 push → **公开 Arborist** | **每次费劲去隐私擦洗（必须模型/人）** | **一次轻确认**（结构上无私可泄） |
| 隐私保证 | 靠 regex 检测，漏语义 unknown | 靠结构预防，不漏 |

## 防御纵深：预防 > 检测 > 判断

三层，越靠前越强、越机械：

1. **预防（结构，机械保证）**：私有内容从不进被同步文件（allowlist + 上面三处分流）。消灭绝大多数。
2. **检测（正则，机械阻断门）**：`arborist-sync audit` 扫已知模式（绝对路径 / UUID / 密钥 / 邮箱 / 固定内部名清单）。抓可枚举残余。**push 前必过，不可跳。**
3. **判断（模型/人，公开边界不可省）**：审计**语义残余**——没进清单的新代号、正文里的内部描述、「通用术语 vs 产品代号」的判定。

**边界严格度按方向**：
- 公开边界（→ Arborist）：三层全留。
- 内部边界（→ 内部源）：可**免第 3 层去隐私**（代号内部可见），保留 1、2。
- 下行 / 本地：主要靠第 1 层。

## 与其它约定的关系（不复述，各管一轴）

- [`arborist-sync`](../../../skills/arborist-sync/SKILL.md)：本篇定义「什么可泛化 / 什么排除」；arborist-sync 是执行这道 gap 的**双向同步工具**。
- [`repomem-doc-boundary`](./repomem-doc-boundary.md)：那篇管「知识放哪层（task / spec / ADR）」；本篇管「同一份 spec 内，泛化 vs 实例怎么分」。**正交、叠加。**
- [`workflow-customization.md`](../../workflow-customization.md) / ADOPT「适配面」：本篇是它们的**原理**；它们是**落地清单**。

## 一句话

**别在事后擦隐私，让私有内容一开始就进不了被同步的文件。** 投资一次「泛化式撰写」（specifics 进 host-config / 定制层，guide 只留占位），换来长期机械同步 + 公开上推只剩一道轻确认。
