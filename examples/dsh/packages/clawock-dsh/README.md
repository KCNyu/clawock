# clawock-dsh

[![npm](https://img.shields.io/npm/v/clawock-dsh?label=NPM&style=flat-square&logo=npm&logoColor=white&labelColor=252b35&color=4b91c8)](https://www.npmjs.com/package/clawock-dsh)
[![Tests](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/harness-regression.yml?label=TESTS&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/harness-regression.yml)
[![License](https://img.shields.io/badge/license-MIT-738391?style=flat-square&labelColor=252b35)](https://github.com/KCNyu/clawock/blob/master/LICENSE)

**AI argues. Code settles. The losses stay on the page.**

> 把 [clawock](https://github.com/KCNyu/clawock) 的投资决策工作流装进
> DeepSeek Harness:agent 走完「读请求 → 研究 + 正反辩论 → 写决策 →
> Python 校验结算」四步,web GUI 里多一个 **Decision Mind** tab,把每笔
> 真实成交的决策轨迹钉在页面上。

第四步是核心:**模型永远不能给自己打分**。价格、风控、账本、战绩全部由
Python 独立结算,agent 写不到那段代码——下错单显示为一笔公开页上的亏损,
而不是一段更好听的文字。

- **Live proof** — 真实港美股账户,每个交易日都这么跑:
  <https://kcnyu.github.io/clawock/>
- **Evidence, wins and losses both** — <https://kcnyu.github.io/clawock/evidence.html>
- **Source and issues** — <https://github.com/KCNyu/clawock>

![Decision Mind tab inside the DSH web GUI](https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dsh-decision-mind.png)

---

## 安装

```bash
dsh plugin --profile web add clawock-dsh
```

rc.6 及以后 DSH 只扫项目根与用户根、不扫 node_modules,所以 skill 还要
再放一步到可发现的位置(任选其一):

```bash
# 用户级(推荐,任何 workspace 都生效)
cp -r ~/.dsh/profiles/web/node_modules/clawock-dsh/skills/investment-decision ~/.dsh/skills/

# 或项目级(标准 Agent Skill 根)
cp -r ~/.dsh/profiles/web/node_modules/clawock-dsh/skills/investment-decision <project>/.agents/skills/
```

然后重启 web profile,skill 即出现在 agent 的 skill 目录。

> 前提:agent 所在环境需要 Python ≥ 3.11,并且
> `python -m pip install clawock`。

## 快速开始

装完直接问:

```
你:帮我分析一下 0700.HK 能不能加点仓
```

agent 走完四步,给你一张决策卡:bull / bear / thesis / confidence /
action / run_id。判定和结算是 Python 算的,不是模型说的。

## 你得到什么

### 一个会辩论、不会自评的 agent

- 主动收集**正反双方**证据——发布时 Python 强制至少一条 opposing 论据,
  熊方必须是真反驳,不是稻草人;
- 有界行动:动作、数量、触发条件写进 `decision.json`,由 Python 校验;
- 情绪状态自认,non-calm 才会出现在面板里。

### 一个只读的 Decision Mind tab

装完后 web GUI 的会话视图多一个 **Decision Mind** tab。它只做一件事:
**每一笔真实成交,都是一条可以点开的决策轨迹**。

- **账本式分组**:一天一组,行内 = 日期 · 标的 · 动作 · 数量@价 ·
  T+1 判定 · 与计划反向标记 · 盈亏焦点数字,同组对齐、竖着扫就是比同一件事;
- **T+1 判定**用官方逐日收盘(`memory/bars/`),绝不读实时快照;未判出就
  显式写「T+1 未判」,不假装没这回事;
- **点开一条轨迹**:当时的计划 → 真实成交(与计划同向/反向)→ T+1 收盘 →
  本笔已实现 / 该持仓当前浮动——两个量永不共用一个「盈亏」标签;
- 没有当日计划的成交显式标注——不假装有判断。

面板是只读 Remote,不改任何文件;结算仍归 clawock 自己的机制。

## 它不做什么

- **不改文件**。面板只读;账本写入、发布只走 `clawock run` / brief 管线。
- **不替代 clawock**。skill 只把「什么时候跑、产出什么」讲给 agent 听,
  agent 调用的仍是同一套 CLI 与文件契约。
- **不发明判定**。没有 bar 就没有 T+1;`execution.status` 只渲染为
  「账本自评」小标签,成交与计划同向/反向另有独立判定。

## 验证装好了

重启后在会话里问「你现在带哪些 skill?」,应能看到 `investment-decision`;
或直接让 agent 执行 `clawock run prepare`,看它是否打印 `request_file`。

## FAQ

**skill 没出现?**
DSH 只扫 `~/.dsh/skills/` 和 `<project>/.agents/skills/` 两个根,不扫
node_modules——回到安装那一节检查 `cp` 那一步。

**Decision Mind 是空白的?**
面板读的是 clawock workspace(`CLAWOCK_WORKSPACE`)里的真实成交与决策
记录;workspace 还没有数据时 tab 是空的,不是装坏了。

**面板和公开 dashboard 是什么关系?**
同一个「决策轨迹」数据契约,两套渲染:插件是运行期读 workspace 的
TypeScript,网页是构建期算好塞进 `dashboard.json` 的 Python。两边的
规则常量与判词由测试钉住,不会漂移。

## 维护者

```bash
cd examples/dsh/packages/clawock-dsh
npm install --include=dev && npm run build   # 生成的 lib/ 提交入库,CI 断言零漂移
npm publish                                   # 发布当前版本
```

把当前 checkout 装进本机 live DSH(开发/自部署):
`ops/host/install_dsh_plugin.sh --restart`。README 截图一条命令:
`node site/tools/shoot_dsh_plugin.js` + `clawock validate-sidecar screenshots`。
