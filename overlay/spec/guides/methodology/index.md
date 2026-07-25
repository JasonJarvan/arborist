# Engineering 方法论簇（persist 提炼自 the origin harness RepoMem）

> 从 the origin harness 的 RepoMem persist 语料里提炼的**可泛化工程纪律**（已剥离产品特定细节）。每篇标源 nugget 便于溯源。产品特定条目已丢弃。

| 簇 | 文件 | 一句话 |
|---|---|---|
| T1 | [agent-and-llm-testing.md](./agent-and-llm-testing.md) | LLM 工具选择随机 → N+1 变体矩阵 + 真 provider 随机 smoke + force-pick + mock 不烧 token |
| T2 | [verification-discipline.md](./verification-discipline.md) | 绿≠可发布；回归用 baseline-diff；feature+test 同 commit |
| T3+T6 | [contracts-and-drift.md](./contracts-and-drift.md) | 跨边界契约单一真源 + 双向 drift 门 + parity 测试；数据字段同 scope / 预留字段需读者 / 双路径 parity |
| T4 | [mr-and-git-discipline.md](./mr-and-git-discipline.md) | 机械改动拆独立 commit；格式化淹没 review → path-scope clean MR |
| T5 | [dependency-and-migration.md](./dependency-and-migration.md) | vendor pin/阶段化；4 级 fallback 阶梯；adapter/绞杀者；DSL vs 原生 |
| T7 | [error-handling.md](./error-handling.md) | 窄异常 + typed re-raise + 可区分 reason，别把失败模式压成一个 |
| T8 | [local-docs-and-ignore.md](./local-docs-and-ignore.md) | 三层 gitignore；trunk-vs-local docs 边界 |
| T9 | [handoff-attribution.md](./handoff-attribution.md) | 回归归因别只看 bisect 窗口；先证伪"干净锚点" |
| Tier3 | [misc-patterns.md](./misc-patterns.md) | override fail-closed / 配置默认真实生效点 / append 半行修复 / out-param / build-vs-buy / plan 前研究框架默认 / gap triage / 存储旁路 reader |

> 定位：这些是 **persist/memory（约定/坑）+ 少量 persist/architecture（决策原则）**。真正过三门的具体决策进 ADR（`../decisions/`）。
