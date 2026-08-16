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

## Decision Mind 面板

装完后,web GUI 的会话视图多一个 **Decision Mind** tab(只读)。它只做
一件事:**每一笔真实成交,都是一条可以点开的决策轨迹**。

- **主轴是真实成交**(portfolio.json trades[]),不是计划流水。每行 =
  标的 + 动作 + 数量@价 + **盈亏焦点数字**,副行是 **T+1 判定**
  (快照收盘价对比成交价:卖飞/卖对)+ 日期。
- **点开一条轨迹**:GitHub 式纵向时间线 —— 当时计划(动作/信心/驱动 +
  条件/计划股数/计划价)→ 执行(是否遵守)→ T+1 结果 → 盈亏(已实现
  或持仓现值)。为什么(rationale)/情绪压力(非 calm 才显示)/备注
  用语义色左边框分层。
- **没有决策的成交显式标注**「无关联决策记录」—— 不假装有判断。
  SPCH 那种「计划 cut 却持续买入摊本」的纪律偏差,一条轨迹看得明明白白。
- **抬头统计**:已实现盈亏(USD/HKD 分别计、折算 USD 等值,绝不混加)、
  T+1 卖飞/卖对计数、决策挂接率;过滤:全部 / 无决策 / 卖出复盘 /
  挂接决策。

对话判定落账:`clawock record --subject ... --action ... --bull ... --bear
... --invalidation ... --emotion ...`(schema 见 `docs/decision-mind-ledger.md`,
bear 与失效条件强制,情绪自认)。面板不改任何文件,结算仍归既有机制。
同一个「决策轨迹」数据契约也渲染在公开 dashboard 的 Reflect 面板
(`build_decision_traces`)——插件与网页同一份加工逻辑。结构:

对话判定落账:`clawock record --subject ... --action ... --bull ... --bear
... --invalidation ... --emotion ...`(schema 见 `docs/decision-mind-ledger.md`,
bear 与失效条件强制,情绪自认)。面板不改任何文件,结算仍归既有机制。结构:

```
clawock-dsh
├── cordis.patch.yml       # profile patch 层:插入 clawock-dsh 行
├── src/                   # TypeScript 源码
│   ├── index.ts           # node 半区:@Remote 装饰器服务(只读 list/get/ledger/…)
│   ├── scan.ts / ledger.ts / freshness.ts   # 纯扫描逻辑(可单测,无依赖)
│   ├── client.ts          # client 半区:Decision Mind 组件 + store + 缓存
│   └── types.ts           # Remote 线类型(@typert object 面)
├── build.mjs              # 构建:临时 Harness 形态 workspace 里跑官方
│                          # @deepseek-ai/dsh-typert-generator,产出 lib/
├── lib/                   # 提交的构建产物(CI 与 DSH 直接消费,不跑构建)
│   ├── index.js / scan.js / ledger.js / freshness.js
│   ├── client.js          # window.__ModuleLoader__ bundle
│   ├── typert.host.* / typert.client.* / typert.remote-client.*   # 生成工件
│   └── types/             # 声明
└── skills/                # agent skill(同上)
```

构建:`cd examples/dsh/plugin && npm install --include=dev && npm run build`
(rc.6 生成器只认 Harness monorepo 布局——`@deepseek-ai/dsh-typert-protocol`
必须是 sibling workspace 包——build.mjs 在临时目录复刻该布局生成后拷回;
生成工件 commit 进仓库,同 dsh-notebook/dsh-workspace-plugin 的做法)。

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

## 截图(README / 营销素材)

面板的宣传图/README 截图必须从**真实运行中的 DSH**里截,不能截独立预览页——
只有带上 DSH 自己的 chrome(顶栏、tab 栏、session 侧栏)才能证明插件真的装
进了 DSH;独立预览页会和实际部署形态漂移。方法(本机已跑通):

1. DSH 后端直接开在 `http://127.0.0.1:3081/`(systemd `dsh.service`,
   `CLAWOCK_WORKSPACE` 指向 clawock 的 workspace)。本机截图直连这个地址,
   绕开 Tailscale/nginx/HTTPS 那一整套。
2. Playwright 用系统 Chromium(不是 Playwright 自带那个,本机版本对不上),
   `device_scale_factor=2` 保证文字清晰:
   ```python
   from playwright.sync_api import sync_playwright
   with sync_playwright() as p:
       b = p.chromium.launch(executable_path='/usr/bin/chromium-browser', args=['--no-sandbox'])
       page = b.new_page(viewport={'width': 1440, 'height': 1100}, device_scale_factor=2)
       page.goto('http://127.0.0.1:3081/', wait_until='networkidle', timeout=20000)
   ```
3. 侧栏点进一个真实 session,等加载完,点顶部 `Decision Mind` tab。**tab 栏
   和 DSH 顶栏必须留在截图里**——那正是「这是插件 tab、不是独立页」的证据。
4. 展开一笔有完整决策轨迹(计划→执行→T+1→盈亏)的真实成交:
   ```python
   cell = page.locator('.cell', has_text='TICKER').filter(has_text='AMOUNT').first
   cell.scroll_into_view_if_needed(); cell.click()
   ```
5. 用**单一矩形 `clip`** 截图,不要两段分别裁剪再拼接(拼接会留缝)。裁掉底部
   `Message the agent` 输入框浮层即可。若画面里有真 bug,先修代码再重截,不要
   用裁剪掩盖。

## 发布(脚本)

```bash
ops/publish/publish_dsh_plugin.sh          # 发布 package.json 当前版本
ops/publish/publish_dsh_plugin.sh 0.1.1    # 先升版本再发布
```

`release.yml` 在 v* tag 发版时自动调用(版本同步主包);脚本也可手动补发。
需要 npm 发布凭据(`NPM_TOKEN` 环境变量或本机 userconfig)。