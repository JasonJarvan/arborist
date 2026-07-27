# AgentTUI zellij 投递 adapter（可插拔参考 · opt-in）

`agenttui_deliver_zellij.py` 是活 pane 投递的**参考 adapter**，**不是 core**，`adopt.sh`
**默认不安装**它。规范是 [ADR-0007](../spec/guides/decisions/0007-agenttui-delivery-contract-pluggable-adapter.md)
的**投递契约**（另见 agenttui-registry §3「投递契约」）：core 只规定契约、保持 transport
中立、无守护进程；这里的 zellij pane + 字节注入只是满足契约的一种传输，可整体替换。

adapter 实现契约四条：brand + 活性感知的 submit 路由（active codex → 发一次 Tab byte 9
入队不 steer；idle codex 与 claude-code → Enter byte 13）；不盲目重发入队键；送达证据
message-specific（注入前记字节边界、per-send nonce、仅当本 nonce marker 越界命中才
`delivered`，否则 `queued-unverified`，绝不假阳性）；fail-closed（pane 命令成功 / pane
存在 / 转录 size 增长 / mtime 变化都不是证据）。入参全部参数化（目标 session_file、brand、
activity、信封、nonce、pane 引用），无实例值。

**换传输**：注入与读取被隔离在两个可注入 seam —— `PaneInjector`（`write_envelope` /
`send_submit_key`）与 `TranscriptReader`（`size` / `read_since`）。要换成 tmux / iTerm /
app-server 等，只需实现这两个 Protocol 并传给 `ZellijDeliveryAdapter(injector, reader)`，
契约逻辑（路由、边界、越界 nonce 验证、不重发）无需改动。回归测试
`tests/test_agenttui_delivery.py` 正是用 fake seam 在无真 zellij / 无真 session 下跑通。

**⚠️ 已知缺口 — 启用前须补 pane 寻址**：默认 `ZellijPaneInjector` 收 `pane_ref` 但
**未用它定向**——底层 `zellij action write-chars`/`write` 实际发到**当前聚焦的 pane**。
故本参考实现只在「目标恰为当前聚焦 pane」的单/受控环境下正确；**真多 pane 环境启用前，
必须先补 pane 寻址**（如先 `zellij action focus` 切到目标 pane，或换用支持 pane target
的传输）。fail-closed 仍成立：即便投错 pane，目标 transcript 里不会出现本次 nonce
marker → 返回 `queued-unverified`，不会假阳性报 `delivered`（只是送不到、不会误报送到）。

**启用**：opt-in，自行调用 `python3 overlay/scripts/agenttui_deliver_zellij.py --help`
（或把它接进你自己的编排层）。退出码：`delivered`=0，`queued-unverified`=3。
