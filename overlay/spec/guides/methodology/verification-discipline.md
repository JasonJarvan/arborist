# T2 · 验证纪律（绿≠可发布）

> 源：`programmatic-rpc-smoke-pattern` · `regression-judged-by-baseline-diff` · `test-feature-sync-discipline`。强化 `../verification-and-gates.md`。

## 核心

- **程序化/单元 smoke 绿 ≠ 可发布**：跨层路由 / UI 契约只有**真跑一次端到端**才验得到。规则：先写快速可 CI 的程序化 smoke，再至少启动真实 UI/端到端走一遍；明确每层能验/不能验什么。别让"程序化绿"制造已就绪的错觉（"CLI 能跑、UI 不行"即此味）。
- **回归判定用 baseline-diff**：全量测试有既有失败底数时，回归 = "改动前后 FAILED 清单**逐条 diff**"，**不是**"期望 0 失败"。底数内失败、单跑能绿的 flake 不算回归。
- **feature 与 test 同步**：流程层——补丁**同 PR 同 commit** 同步改 feature 与 test，reviewer 必查；机制层——snapshot golden file + 跳 UI 的 contract/semantic test。反模式：测试从实现源反推期望值（tautology）；loose UI/文案断言双向脆弱。

## 落点
workflow.md 2.2 / verification-and-gates 的判定口径；testing guide。
