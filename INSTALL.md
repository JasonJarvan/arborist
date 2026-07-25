# Install Arborist (agent-driven)

Arborist bundles no dependency code. The easiest install: open a fresh coding-agent
session **in your repo root** and paste the prompt below. The agent installs the
tools (Trellis; optional codegraph), runs `trellis init`, clones Arborist, and
runs `adopt.sh`. Prefer this over manual steps.

> Requires: Node.js + npm, git, and a repo you want to adopt Arborist into.
> The agent will make global npm installs and edit `.git/info/exclude` — it should
> confirm each side-effecting step with you.

---

```
你是安装助手。请把 Arborist（https://github.com/<owner>/arborist）装进当前 git 仓库。逐步做、每个有副作用的步骤先跟我确认：

1) 环境检查：node/npm/git 是否就绪；当前目录是否 git 仓库根。缺则停下告诉我。
2) 装依赖（全局 npm；已装则跳过；每类装前问我要不要）：
   - 必需：`npm i -g @mindfoldhq/trellis`
   - 可选（符号/调用图）：codegraph（`codegraph init && codegraph install` 建索引+MCP）
   注意：Trellis 为 AGPL-3.0，独立安装、各自 license；Arborist 只通过 CLI 与其互操作。
3) 初始化 Trellis：问我平台与开发者名，然后 `trellis init --<platforms> -u <name>`。
4) 取 Arborist 并叠加：
   `git clone https://github.com/<owner>/arborist.git /tmp/arborist && bash /tmp/arborist/adopt.sh`
   （adopt.sh 会铺 guides/scripts/hgit 与 .arborist/ 注册表脚手架、写 .git/info/exclude、建本地 .harness-vcs 历史仓，并按依赖分级告警 required 工具、逐个询问可选工具（agentsview/Multica/codegraph）——都在产品仓之外。）
5) 手动收尾（按 /tmp/arborist/ADOPT.md「手动收尾」）：把 overlay/workflow-customization.md 的块粘进 .trellis/workflow.md 并替换 <占位>（<REPO_ROOT> 换成本仓绝对路径）；按需配 Multica env。
6) 校验：`trellis update --dry-run` 应只把你改过的 config.yaml/workflow.md 列为「modified by you」；确认 spec/tasks/workspace 属「User data preserved」。
7) 报告：装了什么、改了哪些文件、下一步怎么开工（rootorc kickoff）。

先做第 1 步（环境检查），再逐步征询我。不要一次性全跑。
```

---

Manual install (if you'd rather not use an agent): see [ADOPT.md](./ADOPT.md).
