# harness 侧史凭据门：pre-commit 模板

本目录是侧史（`hgit` / `.harness-vcs`）的 **pre-commit 凭据门**。规范依据：
[`../../spec/guides/verification-and-gates.md`](../../spec/guides/verification-and-gates.md)
的「[allowlist over denylist](../../spec/guides/verification-and-gates.md#allowlist-over-denylist通则门问的是谁批准了不是它有什么问题)」
一节 —— 本门就是那一节里 `scope` 待落条目的**执行者**，两者必须同时在位。

## 为什么 ignore 类机制全都不行

| 防线 | 实测结果 |
|---|---|
| 文件名形态清单（`*.local.json` / `.env` / `*.pem` …） | 编写清单时就漏掉了实际命中的形态（`.local.md`、子目录里的 `.env`）。漏一格是**静默通过** |
| 目录级排除（把凭据目录写进 exclude） | 被 `add -f` **一票否决**。探针：`add <被 exclude 的路径>` → staged 0；`add -f <同一路径>` → staged **1** |

而 `hgit` 的既定用法本身就包含对整个 harness 目录树 `add -f`（`./hgit snapshot` 也是逐文件 `add -f`）。
⇒ **只有 pre-commit 检查已 staged 的内容**这一层绕不过去。

## 危害的形状：不是泄漏，是旁路 fail-closed 契约

侧史无 remote。真正的危害是：凭据管理器的正确设计是「**失效就删文件**」，于是消费者可以依赖
「**文件在 = 值有效**」；但**历史里的旧值不会随之删除** —— 读历史者会拿到一个「看起来有效、
实际已废」的凭据，而那条契约告诉它不必怀疑。**这是把一个 fail-closed 的设计变成 fail-open 的。**

## 两条设计原则

1. **按【分类】判，不按【形态】判。** sha256 摘要、按设计可公开的 key（publishable / anon 类）、
   账号标识符、占位符**都不是秘密**。**路径可疑而内容无真秘密 ⇒ 放行**，本门里也**没有**
   任何可疑路径名清单参与判决 —— 那正是上表第一行失效的那条防线。
   混报会让处置范围虚高，并**稀释**真正该处置的那一个。
2. **全程 fail-closed。** `GateUnavailable` 与顶层 `except Exception` 一律拒绝提交。
   由来是一次实测的 fail-open：早先用 `__file__` 的相对深度推仓根，文件被移动后推错
   ⇒ 子命令失败 ⇒ staged 列表为空 ⇒ **静默放行**。现在 git-dir 只从 `GIT_DIR` 取（git 调 hook 时保证设置），
   兜底是从 cwd 向上找 `.harness-vcs`，两者都拿不到就**拒绝**。
   > **一个 fail-open 的安全门比没有门更糟：它让人以为有保护。**

## allowlist：让「批准」和「绕过」一样便宜

位置 `$GIT_DIR/allowed-credentials`（即 `.harness-vcs/allowed-credentials`，与被守护物同处），
一行一条，加一条就是一条 `echo`：

```bash
echo '<相对仓根的路径>  # approver=<谁> date=<YYYY-MM-DD> scope=<授权范围> why=<理由/出处>' \
  >> .harness-vcs/allowed-credentials
```

**四段字段是真校验，不是提示文字**：缺任一段（或值仍是占位符、`date` 不是 `YYYY-MM-DD`）⇒
该条目**不生效**，且该次提交**按 fail-closed 被拒**，报出第几行缺哪个字段。

- **为什么不静默忽略那一条**：静默忽略会让写它的人以为豁免已生效，下一次真提交才发现门还在拦
  —— 或者更糟，以为门坏了而去绕过它。
- **为什么 `scope` 必写**：**授权不外推**。一条「这一个文件」的单点授权，不写范围就会被后来者
  读成「这类文件都可以」，而当时的意图已不可考。范围要写成能被机械核对的形状（哪个路径、
  哪几个 git 面、到什么时候为止），不要写「已批准」这种无边界的词。

## 判决面（**范例清单，不是穷举**）

按 [`generalization-boundary.md`](../../spec/guides/generalization-boundary.md)
「范例 vs 穷举」的标注纪律：下表是**范例**的 —— 不在表里**不等于**已被裁定为安全，
新形态请照两条设计原则自己判一次，并把补上的模式与理由一起提交。

| 类别 | 判决 | 形态 |
|---|---|---|
| 真秘密 | **拦** | 完整 JWT（附活性读数）、PEM 私钥块、已知秘密前缀（长度量词足以排除误报的那几类）、凭据字段名带非占位值 |
| 摘要 | 放行 | `sha256:` 前缀 / 64 位十六进制串 —— 不可逆，不是凭据 |
| 按设计可公开的 key | 放行 | publishable / anon / public-client 类；**值**也过这一层（它们常常就装在名叫 `api_key` 的字段里） |
| 占位符 | 放行 | `<…>` / `{{…}}` / `${…}` / `changeme` / `your-…` / `redacted` / `***` |

**已知假阳性一类**：anon / publishable key 若本身是 **JWT 形态**，仍会被 JWT 那条拦下
（JWT 检查不看标签，因为「标签说它是 anon」正是一个真 service key 最容易被误标的地方）。
处置就是 allowlist 一行 —— 这也是「豁免必须便宜」存在的理由。

## 自匹配防护（改这个文件时必读）

检测器天然含有它要检测的模式（grep 自己那个经典问题）。本门第一次提交自己时被自己拦下来过。
**给自己开一条路径例外是特例化**，且会随文件改名或被复制而失效；治本的做法是让裸字面量
**不能匹配自身**（源码里写 `sb[_]secret[_]` 而不是 `sb_secret_`）。

`tests/test_credential_gate.py` 会把本门源码喂给它自己的分类器并断言**零命中** ——
破坏这个性质会当场失败，而不是等到下一次有人试图提交这个门。

## 接线

`adopt.sh` 会把本模板装到 `.harness-vcs/hooks/pre-commit`（**幂等**：重复 adopt 不重复堆、
内容变化才重写）。已存在**用户自己的** `pre-commit` 时**不覆盖**，只大声告警并给手工合并指引：

```bash
# 手工合并：把本门作为独立脚本放到旁边，再从你自己的钩子里调它
cp <Arborist>/overlay/hook-templates/credential-gate/pre-commit .harness-vcs/hooks/credential-gate
chmod +x .harness-vcs/hooks/credential-gate
# 在你自己的 .harness-vcs/hooks/pre-commit 末尾追加（非零退出必须原样传出去，否则门 fail-open）：
#   "$(dirname "$0")/credential-gate" || exit $?
```

> 钩子住在 git-dir 里 ⇒ **不被侧史自己跟踪**，也不在 `./hgit snapshot` 白名单里。
> 要更新就重跑 `adopt.sh`。这与 git 对钩子的既有语义一致（钩子从不随仓分发）。

## 装完必须机械验证（**别只看文件在不在**）

门的回归必须**端到端**：`verification-and-gates.md`
「[门的回归必须端到端](../../spec/guides/verification-and-gates.md#门的回归必须端到端且测试的结构必须与真实调用路径同构)」
一节的实例 (i) 讲的就是这个门的上一次回归 —— 它直接 `import` 分类函数、跑过「数百个文件零误报」，
据此认为门已验，却**从未穿过「hook 被调用 → 拒绝提交」那条路径**；是一次真的绕过**提交成功了**才暴露。

所以下面这条探针必须**真的跑一次提交**（在一个**你不在意的临时目录**里，别在真实仓里做）：

```bash
probe="$(mktemp -d)"; cd "$probe"
git --git-dir=.harness-vcs --work-tree=. init -q
install -m 755 <Arborist>/overlay/hook-templates/credential-gate/pre-commit .harness-vcs/hooks/pre-commit
printf 'token = "%s"\n' "$(printf '%s' '{"alg":"HS256"}' | base64 | tr -d '=' | tr '/+' '_-').xxxxxxxxxx.yyyyyyyyyy" > fake.env
git --git-dir=.harness-vcs --work-tree=. add -f fake.env
# 显式给 identity：否则失败可能来自「没配 user.email」而不是门，读数就不可归因了
git --git-dir=.harness-vcs --work-tree=. -c user.name=probe -c user.email=probe@localhost commit -m probe
rc=$?; echo "rc=$rc"          # 期望非 0；先存 rc 再用，别对管道后的命令取 $?
git --git-dir=.harness-vcs --work-tree=. rev-list --count --all   # 期望 0 —— 提交必须没产生
```

**两条断言都要看**：`rc≠0` 说明门开了火，`rev-list --count` 为 0 说明**提交真的没产生** ——
只看 rc 不足以区分「拦住了」与「拦了但 git 仍然提交了」。
