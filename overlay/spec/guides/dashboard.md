# Dashboard：跨 session 待办用户动作投影（<project> host 配置）

> 一个人同时盯 1 RootOrche + N Impler 时，"哪个 session 在等我做什么"的单一视图。操作用 **`cc-dashboard` skill**；本篇是 <project> 宿主配置。是**投影层**（真相仍在 sendbox/Multica/task），不是真相源。

## <project> 配置
| 项 | 选择 |
|---|---|
| 数据位置 | `.work_context/Dashboard/index.md`（本地；副仓 `hgit` 记历史）|
| 动作列语言 | **中文**（对齐仓库语言政策）|
| Mark-done 归属 | 任何 session + 人都可标完成（单人多 session）|
| 归档保留 | 14 天滚动（默认）|
| 动作类型 | 决策 / 启动 / 评审 / 分诊 / 破坏性 / 运维（默认 6 类，不扩展）|

## 写触发（何时往 dashboard 加行）
- 任一 session 写了需要人处理的 sendbox 信（handoff 待启动、done 待评审、blocker、greenlight 请求）。
- 识别到新的**人-阻塞**动作：待你决策 / 待评审 MR / 待批准 security-scan / 待 HITL 晋升 / 待上线。

## 边界（不重复别的层）
- **不**镜像 Multica L2/L3 issue 追踪（Multica=工作单元粒度；dashboard=原子人-动作粒度）。
- **不**复述 task 进度矩阵 / 决策日志（那是 L3 dashboard / ADR）。
- 单条 = 一个"此刻轮到人做的动作"，做完即 mark-done → 14 天后归档。

## 目录
`.work_context/Dashboard/index.md` 已建（空表骨架）。多 session/待办堆积时由各 session 按写触发维护；人扫这一处即知全部待办。
