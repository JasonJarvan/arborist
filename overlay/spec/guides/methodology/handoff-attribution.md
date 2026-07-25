# T9 · handoff 归因反模式

> 源：`handoff-bisect-window-attribution-anti-pattern`。强化 sendbox handoff。

## 核心

- **回归归因别只看 bisect 窗口**：把回归归因到"bisect 窗口内某 commit"时，若真因在**窗口前的依赖加载态**（import 时装的 handler、boot 时烘焙的 config、快照的 env），归因不可靠。
- **四步证伪**：① 先读窗口 diff；② 构造一个**可证伪**的"干净锚点"检查（假设某状态是干净的，去证明它其实不干净）；③ 物化锚点跑最小复现；④ 更正叙事。
- **handoff 模板加一行**："先验证所谓的干净锚点，再交办归因结论"——别把未经证伪的归因传给下个会话。

## 落点
`.work_context/handoff/` 模板（N19/N20，启用 sendbox 时）；trellis-break-loop 的调试纪律。
