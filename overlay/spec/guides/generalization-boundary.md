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
| **`workflow.md` 定制层** | 实例的**行为/策略**覆盖 | git/MR 流、Lane 触发、工具选型（有无 codegraph）、扫描器 | 每轮 breadcrumb（update-safe，不在 trellis update hash） |
| **`host-config`**（`.trellis/host-config.yaml`；实例本地、`hgit` 记史、**永不同步**） | 实例**具体值**的单一真源 | 仓根绝对路径、项目名、Multica/tracker IDs、子树清单、语言/扫描器名、组织 git 约定 | 运行时 + `arborist-sync` 取值做替换 |

**授权判据**：往 guide 正文写一个值之前，问一句——「另一个仓 clone 这份 guide，这个值还成立吗？」不成立 → 它是实例特定的，**移出去**（上表三处之一），正文留占位或引 host-config 键。

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
