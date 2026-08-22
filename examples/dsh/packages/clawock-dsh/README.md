# clawock-dsh

**AI argues. Code settles. The losses stay on the page.**

The [clawock](https://github.com/KCNyu/clawock) investment-decision workflow, as
a DeepSeek Harness plugin. A skill package that makes the agent walk four steps —
read the request, research and argue both sides, write the decision, then let
Python validate and settle it — plus a Decision Studio tab that renders the
request, the debate and the receipt as a conversation view inside the DSH web GUI.

The fourth step is the one that matters: the model never touches settlement.
Prices, FX, P&L and the scorecard are computed by code the agent cannot write to,
so a wrong call shows up as a loss on a public page instead of as a
better-sounding paragraph.

- **Live proof** — a real Hong Kong + US brokerage account, run this way every
  trading day: <https://kcnyu.github.io/clawock/>
- **Evidence, wins and losses both** — <https://kcnyu.github.io/clawock/evidence.html>
- **Source and issues** — <https://github.com/KCNyu/clawock>

![Decision Mind tab inside the DSH web GUI](https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dsh-decision-mind.png)

```bash
dsh plugin --profile web add clawock-dsh
```

Skill discovery needs one more step on rc.6 and later, covered in the
installation section below. The rest of this README is in Chinese; the full
English overview lives in the
[repository README](https://github.com/KCNyu/clawock#readme).

---

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

### 从 checkout 装到本机 DSH(开发/自部署)

发版之前想让本机 DSH 跑上当前 checkout,用同一条官方通道,别手抄目录:

```bash
ops/host/install_dsh_plugin.sh --restart
```

它 `npm pack` 出 tarball,再 `dsh plugin --profile web add <tarball>` —— 传
**tarball 而不是目录**是关键:目录规格 pnpm 只做 link,插件自己的
`dependencies` 一个都不装,这正是 2026-08-17 那次 dsh 崩溃循环 83 次的成因
(#709)。tarball 走的是和 registry 包一样的安装路径。文件名带内容哈希,因为
pnpm 对 `file:` tarball 按路径缓存:同名重打包会被 store 直接复用,于是桌面
上跑的还是上一版而每一步都报成功(实测过,所以脚本还会逐个 `cmp` 装好的
`lib/*.js` 和 checkout 的构建产物)。

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

## 这个插件不做什么(边界)

- **不改任何文件**。面板是只读 Remote;结算、账本写入、发布仍只走
  clawock 自己的机制(`clawock run` / brief 管线)。
- **不替代 clawock**。skill 只是把「什么时候跑、产出什么」讲给 agent
  听;agent 调用的仍是同一套 CLI 与文件契约。
- **不发明判定**。T+1 数字来自 `memory/bars/` 的官方逐日收盘,不是面板
  自己算的;没有 bar 就显式显示「T+1 未判」,绝不编一个结论。
- **不把计划当成交**。`execution.status` 只渲染为「账本自评」小标签,
  成交与计划同向/反向另有独立的 `alignment` 判定(二者曾在 #739 漂移,
  现由 `tests/test_decision_trace_parity.py` 钉住)。

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

- **主轴是真实成交**(portfolio.json trades[]),不是计划流水。一天是一个
  账本分组:同组内每笔成交一行,行内 = 日期 + 标的 + 动作 + 数量@价 +
  **T+1 判定**(官方逐日行情的 T+1 收盘对比成交价,`memory/bars/`,绝不读
  快照 `current_price`;未判出显式写「T+1 未判」,不假装没这回事)+ 与计划
  反向标记 + **盈亏焦点数字**。同组各行用 `subgrid` 共用一套列轨道,所以
  标的/动作/数量/盈亏在整组里对齐,竖着扫就是在比同一件事;窄于 520px
  时行折回两行(身份+金额 / 判定+日期)。
- **点开一条轨迹**:GitHub 式纵向时间线 —— 当时的计划(动作/股数@计划价/
  信心/驱动)→ **真实成交**(与计划同向/反向,`execution.status` 只是计划
  自己的「账本自评」小标签,不冒充这笔成交的执行结果)→ T+1 收盘 →
  **本笔已实现** / **该持仓当前浮动(非本笔)**,两个量永不共用一个
  「盈亏」标签。为什么(rationale,内部 breach id 已剥)/情绪压力(非 calm
  才显示)/备注用语义色左边框分层。
- **没有当日计划的成交显式标注**—— 不假装有判断:真实数据里过半成交
  找不到前后 3 天的同标的计划,这本身就是信息。SPCH 那种「计划 cut 却
  持续买入摊本」的纪律偏差,一条轨迹看得明明白白。
- **抬头只占一屏该占的**:统计卡(已实现/T+1/有当日计划)随内容滚走,常驻的只有
  一条约 40px 的筛选条 —— 这个 tab 的正事是一条可滚的列表,顶上停一块 100px 的
  常驻抬头等于每屏少看 2.5 笔成交。
- **抬头统计**:已实现盈亏(USD/HKD 分别计、折算 USD 等值,绝不混加)、
  T+1 卖飞/卖对(判出 X/Y 笔卖出,分母是卖出侧而非全部成交)、
  有当日计划 m/n(反向 N 笔);过滤:全部 / 无当日计划 / 卖出复盘 /
  有当日计划。

对话判定落账:`clawock record --subject ... --action ... --bull ... --bear
... --invalidation ... --emotion ...`(schema 见 `docs/decision-mind-ledger.md`,
bear 与失效条件强制,情绪自认)。面板不改任何文件,结算仍归既有机制。
同一个「决策轨迹」**数据契约**也渲染在公开 dashboard 的 Reflect 面板
(`build_decision_traces`)——但那是**另一套实现**:插件是运行期读 workspace 的
TypeScript(`src/ledger.ts::readTraces`),网页是构建期算好塞进 `dashboard.json`
的 Python。两边不共享代码,曾经因此漂移到判词都不一致(#739/#740),
现在由 `tests/test_decision_trace_parity.py` 钉住共用的规则常量与判词表。结构:

```
clawock-dsh
├── cordis.patch.yml       # profile patch 层:插入 clawock-dsh 行
├── src/                   # TypeScript 源码
│   ├── index.ts           # node 半区:@Remote 装饰器服务(只读 list/get/ledger/…)
│   ├── scan.ts / ledger.ts / freshness.ts   # 纯扫描逻辑(可单测,无依赖)
│   ├── client.ts          # client 半区:Decision Mind 组件 + store + 缓存
│   └── types.ts           # Remote 线类型(@typert object 面)
├── styles.module.css      # (在 src/ 下)CSS Modules:构建期哈希类名 + 由
│                          # loader 持有的 <style data-plugin> 注入
├── build.mjs              # 构建:就地跑官方 @deepseek-ai/dsh-typert-generator
│                          # + 两次 tsdown + 声明,产出 lib/
├── tsdown.host.config.mjs / tsdown.client.config.mjs   # 两个官方 pass
├── lib/                   # 提交的构建产物(CI 与 DSH 直接消费,不跑构建)
│   ├── index.js / scan.js / ledger.js / freshness.js
│   ├── client.js          # window.__ModuleLoader__ bundle
│   ├── typert.host.* / typert.client.* / typert.remote-client.*   # 生成工件
│   └── types/             # 声明
└── skills/                # agent skill(同上)
```

构建:`cd examples/dsh/packages/clawock-dsh && npm install --include=dev && npm run build`

生成器按 workspace 根的 `tsconfig.host.json` / `tsconfig.client.json` 发现包,
且只接受落在 `<root>/packages/` 下的 project reference(rc.6 `WorkspaceAnalyzer`
里写死的判据)——所以这个包就住在 `examples/dsh/packages/clawock-dsh`,
workspace 根是 `examples/dsh`(见 [../../README.md](../../README.md))。三个
pass 全部就地跑真实源码树,不再复刻临时 workspace(#731)。生成工件 commit
进仓库,`harness-regression.yml` 每个插件 PR 都重跑构建并断言 `lib/` 零 diff
——所以「lib/ 和 src/ 一致吗」是机检问题,不是记性问题。

验证状态:node 半区(扫描、run id 防路径穿越、Remote 标记)与 client 半区
(注册、模型投影)有单元测试;**tab 的浏览器目验需要在带 DSH 源码/工具链的
机器上 boot 后确认**(本仓库 CI 无法渲染 GUI)。

## 标准与机器门

接线标准(与 DSH rc.6 官方写法逐项对齐,历史偏离记录见 #729-732):

| 项 | 标准 | 本插件 |
| --- | --- | --- |
| 包位置 | 生成器只认 `<root>/packages/` 下的 project reference | `examples/dsh/packages/clawock-dsh`,workspace 根 `examples/dsh` |
| Host Remote | `TypertRemoteService` + `@Remote`,构建期由 `@deepseek-ai/dsh-typert-generator` 生成反射与 client contribution | ✅ |
| Client 纪律 | `register` 只在 `apply`;store 必须是 `createXxxStore()` 工厂;模块级零副作用;组件只吃 props | ✅ |
| 样式 | 构建期 CSS Modules,`<style data-plugin>` 由模块 loader 认领/卸载;手捏 `<style>` 即绕过归属 | ✅ |
| 宿主布局 | 内容列用宿主发布的 `--dsh-chat-content-width`(与 transcript/输入卡同一条宽度轴);浮动输入卡用 `--dsh-composer-height` 让位(官方 ui-trajectory 同款);中性色/字体走 `--dsw-*` token 跟随主题 | ✅,由 `decision_studio_plugin.spec.js` 的样式契约钉住 |
| 产物 | `lib/` 提交入库且**可复现**;类名哈希取包相对路径、region 注释去绝对路径 | ✅ |
| 依赖 | 安装态必须自足——`dsh_plugin_package_contract.mjs` 在空目录装 tarball 验证(曾因此 83 次崩溃循环,#709) | ✅ |

机器门(每个插件 PR 由 `harness-regression.yml` 把关,无需人记):

1. `npm run build` 重跑三个 pass(`lib/` 与 `src/` 零 diff,否则 CI 红);
2. `tests/decision_studio_plugin.spec.js` —— node 半区扫描/路径安全 + client
   bundle 注册/投影;
3. `tests/dsh_plugin_package_contract.mjs` —— 打包安装后每个 export 可加载;
4. `tests/test_decision_trace_parity.py` —— 插件 TS 与 dashboard Python 的
   判词表共用同一份常量(#739/#740 漂移的钉)。

所以「这个插件标准不标准」不是记性问题:上面任何一条被破坏,CI 直接红。

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
进了 DSH;独立预览页会和实际部署形态漂移。仓库里有现成脚本,一条命令截好:

```bash
ops/host/install_dsh_plugin.sh --restart   # live 插件 = checkout 构建产物
node site/tools/shoot_dsh_plugin.js        # → site/assets/dsh-decision-mind.png
clawock validate-sidecar screenshots       # 和 CI 同一个闸门
```

脚本默认连 `http://127.0.0.1:3081/`(systemd `dsh.service`,
`CLAWOCK_WORKSPACE` 指向 clawock 的 workspace),绕开 Tailscale/nginx/HTTPS
那一整套。环境变量:`DSH_URL`(其他 origin)、`SESSION`(会话标题片段,
默认点侧栏第一个)、`ROW`(展开第几笔,默认第 3 笔)、`OUT`(输出路径)。
Playwright 走自己管理的 Chromium(`~/.cache/ms-playwright/`;新机器上
`npx playwright install chromium` 装一次,原来的系统 Chromium 是个 snap,
2026-08-17 已从本机移除)。

脚本做对了几件手工容易错的事,别绕过它回去手写:

1. **tab 栏和 DSH 顶栏留在截图里**——那是「这是插件 tab、不是独立页」的证据;
2. 点击会话/点开轨迹后 **blur 掉键盘焦点**,否则行的 `:focus-visible`
   描边会作为一条蓝框留在成图里;
3. 用**单一矩形 `clip`** 截图(裁掉底部 `Message the agent` 输入框浮层),
   两段分别裁剪再拼接会在缝合处留 artifact;
4. 等 `domcontentloaded` + 显式延时,别用 `networkidle`——`/plugins/events`
   是没心跳的 SSE 长连接,networkidle 永远等不到。

自动刷新已接在 `.github/workflows/screenshot-refresh.yml`:提供 DSH origin
(dispatch 输入 `dsh_url` 或 repository variable `DSH_URL`)的 runner 会自动
重截并把新图放进同一个 commit;没有 DSH 的 hosted runner 跳过这一步。
若画面里有真 bug,先修代码再重截,不要用裁剪掩盖。

## 发布(脚本)

```bash
ops/publish/publish_dsh_plugin.sh          # 发布 package.json 当前版本
ops/publish/publish_dsh_plugin.sh 0.1.1    # 先升版本再发布
```

`release.yml` 在 v* tag 发版时自动调用(版本同步主包);脚本也可手动补发。
需要 npm 发布凭据(`NPM_TOKEN` 环境变量或本机 userconfig)。