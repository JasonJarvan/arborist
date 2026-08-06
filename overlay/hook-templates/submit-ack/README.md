# 接收侧 submit-ack 握手：钩子接线模板

本目录是 `agenttui_submit_ack.py` 的**接收侧**接线物。规范见
[`../../spec/guides/agenttui-registry.md`](../../spec/guides/agenttui-registry.md) §3
「接收侧 submit-ack 握手」。**先读那一节的 fail-safe 方向**（ack 缺失 = 未确认，**不是**未提交），
再决定怎么接线——接错方向的后果是重复投递，而不是少一条日志。

## 为什么需要它

投递侧现有的唯一送达判据是「发送方去翻目标 transcript 找 nonce」，那是**旁观**判据：它有落盘延迟，
且**分不出**「文字堆在输入框从未提交」与「已提交但未落盘」。接收 CLI 的**提交钩子**只在真的提交时触发，
所以它是**因果**判据。

## 两种接线形态（**优先选 A**）

| | 形态 A：**同级追加一条钩子命令** | 形态 B：**把片段粘进既有钩子脚本** |
|---|---|---|
| 改动面 | 只改 host 的 hook 配置，**既有脚本零改动** | 改既有脚本正文 |
| 「不改变既有行为」 | **结构性成立**（既有脚本没被碰过；本命令 stdout 恒为空、退出码恒 0） | 需要靠测试保证 |
| `trellis update` 覆盖既有脚本时 | 不受影响 | **会被覆盖，须重贴** |
| 适用 | 默认 | host 只支持单条 hook 命令时 |

**形态 A 是首选，理由是判据层面的**：契约要求「新增的观测动作必须先证明它不扰动被观测者」
（`verification-and-gates.md`）。形态 A 里既有钩子脚本**在字节层面没有变化**，这个证明是结构性的；
形态 B 只能靠测试证明，而测试只覆盖被测到的那些输出。

## 形态 A 接线

前置：`agenttui_submit_ack.py` 已铺到 `<repo>/.trellis/scripts/`（adopt 脚手架代劳）。

**Claude Code** —— 在 `.claude/settings.json`（或 `.claude/settings.local.json`，见下「坑」）的
`hooks.UserPromptSubmit` **数组里，既有那条之后**追加：

```json
{
  "type": "command",
  "command": "python3 .trellis/scripts/agenttui_submit_ack.py record --brand claude-code",
  "timeout": 10
}
```

**Codex** —— 在 `.codex/hooks.json` 的 `hooks.UserPromptSubmit` 数组里同样追加（注意 `-X utf8`，
与该 brand 既有钩子命令的写法一致）：

```json
{
  "type": "command",
  "command": "python3 -X utf8 .trellis/scripts/agenttui_submit_ack.py record --brand codex",
  "timeout": 10
}
```

`--brand` 写**本会话真实 runtime brand**（[ADR-0006](../../spec/guides/decisions/0006-runtime-brand-is-routing-authority.md)：
runtime brand 是路由权威）。别按模板示例或期望路由填——填错只会让 ack 表里的 `receiver_brand` 说谎，
而那一列的用途正是「哪个 brand 的钩子确实装上了」。

## 形态 B 接线

把同目录下对应 brand 的片段**逐字**贴进既有 UserPromptSubmit 钩子脚本：

- Claude Code：[`claude-code.snippet.py`](./claude-code.snippet.py)
- Codex：[`codex.snippet.py`](./codex.snippet.py)

贴入位置：**载入 hook payload 之后、任何 `print` 之前**。片段自己不 print、不 raise、不改变控制流。

## 装完必须机械验证（别只看配置文件长得对）

```bash
# 1) 表的位置（不写任何东西）
python3 .trellis/scripts/agenttui_submit_ack.py print-path

# 2) 喂一个假 payload 给 record：stdout 必须为空、退出码必须为 0
printf '%s' '{"prompt":"[ARBORIST-DIRECT:v1]\nfrom=a\nto=b\nnonce=probe-000\n\nmessage:\nhi","cwd":"'"$PWD"'"}' \
  | python3 .trellis/scripts/agenttui_submit_ack.py record --brand <你的 brand>
rc=$?; echo "rc=$rc"        # 先存 rc 再用，别对管道后的命令取 $?

# 3) 读回来
python3 .trellis/scripts/agenttui_submit_ack.py lookup --nonce probe-000
```

第 3 步应给出 `ack_status: acked`。**注意这条探针只证明「模块能写能读」，不证明 host 真的调了它**——
后者要靠**在目标会话里真的提交一次带信封的 prompt**，再 `lookup` 那个 nonce。

## 已知坑（这一条会让整件事静默失效）

`.claude/settings.json` 若已被产品仓 git 跟踪，`trellis init -y` 会**跳过**它以免覆盖团队文件，
**后果是 hook 一条都没装上，而 init 本身不报错**（见 [`../../../ADOPT.md`](../../../ADOPT.md) 前置一节）。
此时 ack 也不会有。⇒ 这正是规范里「**ack 缺失只能读作未确认，不得读作未提交**」的实测由来之一。

## 隐私与体积

ack 记录**不含消息正文**，只含能证明「这个 nonce 被提交了」的最小集：nonce、时间、接收方身份、
以及提交内容里**匹配到的信封头字段**（`from` / `from_brand` / `to` / `provenance`）。逐字段的理由见规范那一节。
