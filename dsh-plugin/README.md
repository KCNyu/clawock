# clawock-dsh

clawock 的 DeepSeek Harness 插件:一个纯 skill 包,把 investment-decision
决策工作流注入 DSH agent。零 Node 代码——clawock 是 Python CLI,skill
只负责告诉 agent 怎么走「读请求 → 写决策 → Python 校验」三步。

## 安装

```bash
# 从 npm(发布后)
dsh plugin --profile web add clawock-dsh

# 或从 git 源
dsh plugin --profile web add https://github.com/KCNyu/clawock#dsh-plugin
```

装完重启 web profile,skill 即生效。

## 前提

agent 所在环境需要 clawock(Python ≥ 3.11):

```bash
python -m pip install clawock
```

## 装了之后

agent 在需要做投资决策时自动使用本 skill:跑 `clawock run prepare` 读
request、写 `decision.json`(带证据、带反方)、`clawock run publish` 校验并
出回执。模型永远不能给自己打分——价格、风控、账本、战绩全部由 Python
独立结算。

## 为什么是 skill 而不是工具

clawock 的契约是文件 + CLI,DSH 的 bash 工具已经能执行全部命令;skill
只需要把「什么时候跑、产出什么、什么不可协商」讲清楚。这也是 clawock
harness-agnostic 定位的一部分——同一份契约,OpenClaw skill / Claude Code
指令 / Codex AGENTS.md / DSH skill 各有一个壳,内容同构
([examples/harness-agnostic](../../examples/harness-agnostic/README.md))。

## 发布

```bash
cd dsh-plugin
npm publish
```

需要 npm 账号;包名 `clawock-dsh` 发布前检查是否被占用。
