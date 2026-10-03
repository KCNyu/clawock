# 提报格式与闸规则

只有候选经 `closed-lessons.md` 反证仍成立、准备提报时才读。本文件是草稿格式与闸规则的唯一说明；闸的实现是 `gate_issue.py`。

草稿格式：

```markdown
# [patrol] <一句话说清楚坏在哪>

## 现象
<具体到 文件:行（例如 src/clawock/harness/brief_postflight.py:120），引用原文，说清楚输入→错误输出>

## 为什么是问题
<依据：调用链、数据、提交记录；不要推测>

## 分级
严重度: <P0 / P1 / P2 / P3>
领域: <data / risk / delivery / dashboard / dsh / harness / ops / security / docs / debt>
类型: <bug / drift / false-alarm / gate-gap / regression / feature / debt>
关联: <同根因的已有 issue #N；没有就写「无」>

## 用户能看到的差别
SURFACE: <面板 / 简报 / 决策台账 / DSH 插件 / decimap / 站点静态页 / 投递 / CLI / 无（基础设施）>
现在: <今天 kcn 在那个面上看到什么>
修完: <修完看到什么，必须不同>
（选「无（基础设施）」时加一行 `先例: #N`，N 是本仓真实发生过的同类问题）

## 反证自查
全仓搜索: <实际跑过的 git grep 命令（不限目录），命中几处、在哪>
历史: <git log -S / blame 的结论，或相关 issue/PR 号>
设计意图: <附近注释/文档怎么解释这个取舍；为什么它仍是缺陷>
量化: <影响的实测数字>
对照已关: <closed-lessons.md / 已关 issue 里最像的一条号码，以及这条为什么不同；或「无同形态」>

## 建议修法
<最小改法，以及修完后怎么验证；说明不会引入新的正确性风险>

<!-- RED-CHECK
cd /root/wt-patrol && env -u CLAWOCK_WORKSPACE PYTHONPATH=src python3 -c "
import re
src = open('src/clawock/...').read()
assert <今天为假的条件>, '<打印出来的说明和数字>'
"
-->
```

## 分级（闸按证据核，不拒只降）

| 级 | 什么算 | 去向 |
|---|---|---|
| P0 | kcn 今天看到/收到的钱、仓位、决策数字错；成品丢了/发重/发不出去；公开泄露凭证 | 单独 issue，数量不限 |
| P1 | 会放过 P0 的闸/检测/watchdog 在真实数据上失明或 fail-open；让人学会忽略告警的假红 | 单独 issue，数量不限 |
| P2 | 看得到但不改变决策：标签/格式错、非金额的陈旧文案、CI 触发盲区、真实数据里还没出现的边界崩溃 | 单独 issue，数量不限 |
| P3 | 文档错字/顺序、样式与对比度、无害的标签不一致、内部卫生 | 单独 issue，数量不限 |

闸会自动降级并把理由写进 issue：P0/P1 的 文件:行 或判据里没有今天的真实产物（`assets/data/`、`memory/`、
`portfolio.json`、`logs/`、线上 URL）→ P2；P0 不是钱/决策/投递/泄露 → P1；`领域: docs` 或只改文档的 drift →
P3；只涉及 CSS/HTML/图片且不涉及数字或涨跌语义 → P3；`SURFACE: 无（基础设施）` 且不是 security → 最高 P2；
最近 14 天同一 领域/类型 被多次按 not planned 或 `patrol:noise` 关闭 → P3。降级不阻止提报；不以数量或繁忙程度限制发现。
没写 `## 分级` 的草稿按标题推断，照样提报，但推断比你自己写得粗。

`关联: #N`：#N 还 open → 这条作为补充评论挂到 #N（一个根因一条 issue）；#N 已关 → 按 `regression` 记，
正文写明「#N 的修复没覆盖到这里」。没写关联时，闸也会按「同一文件 + 同一函数 + 同一领域」找 14 天内 open 的巡检
issue，找到就挂过去。

## 功能提案（只在 peers 轮）

`类型: feature`，最高 P2，数量不限。除上面各节外再加一节：

```markdown
## 同类对标
来源: <peers.json 中的纯文本项目名 + 源码路径/机制说明；具体外部出处可放仓库文档>
痛点: <#N —— clawock 里这类问题真实发生过的 issue/PR>
契合: <为什么落在边界内：决策工作流 + 可验证 harness，港美股现金个股，不下单>
```

闸会核：来源仓库存在、未归档、一年内有提交；痛点的 #N 真实存在；标题和「契合」不落在边界外（下单、执行引擎、
做市、加密、合规报送……）。RED-CHECK 照旧要红：证明缺口今天就在（机制缺席的 grep、这类失败在真实产物里的计数）。
「现象」写对方怎么做（机制 + 链接），「建议修法」写 clawock 最小落地方式和验收判据。

闸会：核对每个 文件:行 存在；检查 SURFACE 声称的面你确实看过（路径出现在 文件:行 或判据里）；
**在 `/root/wt-patrol` 里真跑 RED-CHECK，要求它以 AssertionError/SystemExit 非零退出并打印说明**，
而且判据必须读你点名的文件；检查 `## 反证自查` 五行齐全；标题落进「拆分/重构/import 耗时/散落/抽常量」须真实先例；固定 DEBT-CHECK 证实的代码债务仅豁免此项和基础设施先例；
声称「没人用/没清理/没校验」的，RED-CHECK 里必须有不限目录的 `git grep`；和所有已有 issue 查重；提报数量不限。
判据先打印实际读到的值再断言，自己先跑一遍确认红的是你说的那件事（#1328、#1353 红的是正则和拼写）。
说「闸没看到 / 只看了一部分」的，判据要打印这道闸在今天真实数据上**进入判定的条数 / 总条数**（#2072、#2075 那样），
别只断言「某个样例漏了」。
RED-CHECK 只读：不许写 live、git 写操作、gh 写操作、装包、起浏览器。

## 闸拒绝之后

- 先判断是草稿格式/引号错误，还是真实行为推翻了前提。前者修好后在本地跑一遍证据再交闸，别把闸当试错编译器；
  后者放弃该候选，把证伪原因写进 ledger 的「别再查」。
- 能补证据就改草稿重试；**不要为了让断言变红而改成更弱的判据**。
- 闸通过后的去向（单独 issue / 补充到 #N）都算提报成功，照实写进 ledger。


## 第三方引用（写入 GitHub 前的硬规则）

GitHub issue、PR、评论只用纯文本项目名和自己的机制说明。禁止第三方 GitHub URL（包括 issue、PR、
commit、源码页）、owner/repo#编号、owner/repo@版本、@用户名；这些会生成跨仓库回链或通知。
外部可点击出处留在仓库文档或 peers.json。闸先私下核验来源与证据，写入前由 github_text.sanitize
清除引用，再用 validate 确认；标题、正文、判据日志、同根因补充评论和旧汇总都经过它。
clawock 自己的 #N 和仓库链接保留。

## 代码债务（固定静态契约，最高 P3）

`领域: debt`、`类型: debt`，`SURFACE: 无（基础设施）`。其余六节、反证、查重、文件行及实际跑红照旧。
只有固定判据证实的债务豁免「重构关键词先例」和「基础设施先例」；普通重构仍走原闸。
不是另设一个任意行数阈值：没有 `size` / `naming` / 任意命令检查。

在草稿加 `<!-- DEBT-CHECK` 换行 JSON 换行 `-->`。JSON 的 `check` 三选一：

- `duplicate-python`：`symbols` 是 2–10 个不同文件的 `path::function`，模块顶层函数至少 5 行；
  完整 AST（含参数、常量、引用、装饰器）须相同，仅忽略声明名和位置。相同只是复制证据，
  正文仍必须核对引用的全局绑定/输入契约，解释为什么表达同一事实；薄包装和不同语义的 resolve 不算。
- `import-cycle`：`modules` 是按环顺序排列的 `src/clawock/*.py` 路径；逐边核对模块顶层 import。
  函数内延迟 import 与重导出猜出来的环不算。解释这个环为何没有有意边界，给移除哪条边和守卫。
- `undeclared-import`：`source` 和 `import` 指明实际的外部 import；对照 pyproject 的全部依赖与 extras，
  声明存在就绿。命名映射保守，无法映射的发行包先核对真实包名，不能把动态 import 或 extra 漏装冒充未声明。

每种都要 `fact`（同一事实/契约）、`repair`（稳定 owner / 断边 / 声明的最小改法）、
`guard`（拟钉住什么回流），各至少 12 字符。列出全部检查文件的 文件:行；依赖检查也引用 pyproject.toml。
判据仅读已跟踪源码；找不到符号/语法错/探针失败是 INVALID，不能当红。先用当前代码跑绿时立刻放弃。

生成 RED-CHECK 的唯一命令（JSON 与 DEBT-CHECK 完全相同）：

```python
import sys
sys.path.insert(0, '/root/tools/clawock-patrol')
from debt_check import red_command
print(red_command(contract, '/root/tools/clawock-patrol'))
```

把打印的整行放进 RED-CHECK（不额外包 shell / 拼接其他命令）。闸先用同一 evaluator 测量，再实跑固定命令：
exit 1 + DEBT RED 是违反契约；exit 0 + DEBT GREEN 是证伪；exit 2 + INVALID 是探针坏了。
修完同一 JSON 必须绿，并给永久守卫。不得借 debt 类别提新功能、臆测交易风险或独立拆大文件。
