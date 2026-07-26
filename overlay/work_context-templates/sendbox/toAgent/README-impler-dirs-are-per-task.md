<!-- 脚手架说明，非收件目录本身；铺进 .work_context/sendbox/toAgent/ 后可保留或删除。 -->

# impler 收件目录按任务限定，勿铺通用 `toImpler/`

`toRootOrche/` 与 `toSubOrche/` 是 per-project 近似单例，用通用目录即可，已随脚手架铺好。

**impler 是多实例**——每个并发任务一个 impler。因此**不铺通用 `toImpler/`**：多个并发 impler 的信落进同一目录会相互冲突。

派活给某 impler 时，**为该任务新建** `to<TaskName>Impler/`，TaskName 取任务 slug：

- 任务 `agent-auth` → `toAgentAuthImpler/`
- 任务 `eve-42`     → `toEve42Impler/`

信仍按 `from-<task>-<type>.md` 命名，落进对应任务目录，如 `toEve42Impler/from-eve-42-handoff.md`。

规范见 `guides/sendbox.md` §目录结构。
