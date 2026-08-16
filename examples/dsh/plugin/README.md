# clawock-dsh

clawock 的 DeepSeek Harness 插件:skill 包 + Decision Studio 面板,把
investment-decision 决策工作流注入 DSH agent。skill 负责告诉 agent 怎么走
「读请求 → 研究 + 正反辩论 → 写决策 → Python 校验结算」四步;面板把
request / debate / 回执渲染成 web GUI 里的会话视图 tab。

## 安装(rc.6 及以后验证过的接线)

```bash
dsh plugin --profile web add clawock-dsh
```

这一步把包装进 profile(pnpm 安装到
`~/.dsh/profiles/web/node_modules/`),并因为包声明了
`dsh.bundle.patch` 而成为真正的 profile 层(patch 行 `clawock-studio`
提供 Decision Studio 的只读 Remote 网关)。**skill 的发现仍按 rc.6 规则**:
DSH 只扫项目根与用户根,不扫 node_modules —— 所以还需要一步把 skill
放到可发现的位置(任选其一):

```bash
# 用户级(推荐,任何 workspace 都生效)
cp -r ~/.dsh/profiles/web/node_modules/clawock-dsh/skills/investment-decision ~/.dsh/skills/

# 或项目级(openclaw/clawock 也认的标准 Agent Skill 根)
cp -r ~/.dsh/profiles/web/node_modules/clawock-dsh/skills/investment-decision <project>/.agents/skills/
```

然后重启 web profile,skill 即出现在 agent 的 skill 目录里。

> 更省事的路:clawock 本身就把同一个 skill 装进标准 Agent Skill 根
> (`clawock workflow install investment-decision --workspace <project>` →
> `<project>/.agents/skills/`),DSH 同样会扫到这个位置。npm 插件是另一条
> 分发通道,并预留未来的 UI 贡献位。

## 前提

agent 所在环境需要 clawock(Python ≥ 3.11):

```bash
python -m pip install clawock
```

## 装了之后

用户说「分析一下 X / 做个投资决策」时,agent 自动走:

1. `clawock run prepare` → 读带指纹认证的 request(`context` + 三道闸:
   支持证据下限 / 反对证据下限 / 无一手来源的置信度上限);
2. 用 DSH 自带的工具研究,并**主动收集反方论据**(发布时 Python 强制
   至少一条 opposing 证据,熊方必须是真反驳,不是稻草人);
3. 写 `decision.json`(bull/bear 辩论 + thesis + 有界 action);
4. `clawock run publish` → 出回执,agent 给你一张「决策卡」(bull / bear /
   thesis / confidence / action / run_id)。

模型永远不能给自己打分——价格、风控、账本、战绩全部由 Python 独立结算。

## 快速上手对话

```
你:安装好之后,帮我分析一下 0700.HK 能不能加点仓
agent:准备请求…(clawock run prepare)
      ┌─ 我会先收集双方证据再下结论 ─┐
      ├ Bull  业绩文件确认增长(primary)  ├
      ├ Bear  估值高于五年区间(market)   ├
      └ 输出 + Python 校验 + 出回执 ┘
      Subject 0700 (HK/HKD)  ·  Action add ·  confidence 0.7 …
      Receipt published · run_id <id> · 证书已钉住
```

## Decision Studio 面板

装完后,web GUI 的会话视图多一个 **Decision Studio** tab(只读):

- **运行列表**:本 workspace(`$CLAWOCK_WORKSPACE` 或 dsh 进程 cwd)里所有
  已 prepare 的 run —— ticker / action / 有无回执 / as_of,按时间倒序;
- **选中一个 run**:certified request(文档指纹数 + 三道闸)、debate 证据
  表(supporting 绿 / opposing 红)、thesis + action + confidence、回执
  横幅(published 绿 / 未发布红 + run_id + generation)。

数据源是只读的:`.clawock/work/<run_id>/request.json`、workspace 根
`decision.json`、`.clawock/runs/<run_id>/manifest.json`。面板不改任何文件,
结算仍归 `clawock run publish`。结构:

```
clawock-dsh
├── cordis.patch.yml   # profile patch 层:插入 clawock-studio Remote 网关行
├── lib/index.js       # node 半区:TypertRemoteService(只读 list/get)
├── lib/scan.js        # 纯扫描逻辑(可单测)
├── client.js          # client 半区:module-loader bundle,注册 conversation.view tab
└── skills/            # agent skill(同上)
```

验证状态:node 半区(扫描、run id 防路径穿越、Remote 标记)与 client 半区
(注册、模型投影)有单元测试;**tab 的浏览器目验需要在带 DSH 源码/工具链的
机器上 boot 后确认**(本仓库 CI 无法渲染 GUI)。

## 为什么是 skill + 面板而不是工具

clawock 的契约是文件 + CLI,DSH 的 bash 工具已经能执行全部命令;skill
只需要把「什么时候跑、产出什么、什么不可协商」讲清楚。这也是 clawock
harness-agnostic 定位的一部分——同一份契约,OpenClaw skill / Claude Code
指令 / Codex AGENTS.md / DSH skill 各有一个壳,内容同构
([../../README.md](../../README.md))。面板只是同一份只读数据的另一种
呈现,不改变契约。

## 校验安装成功

重启后在会话里问「你现在带哪些 skill?」应能看到 `investment-decision`;
或直接让 agent 执行 `clawock run prepare`,看它是否打印 `request_file`。
如果 skill 没出现,检查上一步的 `cp` 目标是否在
`~/.dsh/skills/` 或 `<project>/.agents/skills/`(DSH 只扫这两个根,
不扫 node_modules)。

## 发布(脚本)

```bash
ops/publish/publish_dsh_plugin.sh          # 发布 package.json 当前版本
ops/publish/publish_dsh_plugin.sh 0.1.1    # 先升版本再发布
```

`release.yml` 在 v* tag 发版时自动调用(版本同步主包);脚本也可手动补发。
需要 npm 发布凭据(`NPM_TOKEN` 环境变量或本机 userconfig)。