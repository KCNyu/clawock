# Archived OpenClaw decoupling plan

**Status**: archived / superseded; do not execute as an operations runbook
**Created**: 2026-05-19  
**Goal**: clawock 变成 self-contained agent，context 不再被 openclaw 全局 bootstrap 注入；LLM 调用自接以规避 openclaw 上游 bug（xiaomi thinking hard-guard、minimax adaptive 解析等）

> 这是一份 2026-05-19 的历史设计草案。里面的 `cron/jobs.json`、MiniMax M2.7、
> fallback 顺序和迁移命令都已过期。当前运行说明以根目录 `TOOLS.md` /
> `docs/reference/scripts.md`、
> `openclaw cron list --json` 和 `config/cron-schedules.json` 为准。

---

## Why now / why later

**Why decouple at all**:
- ctx 隔离：现在 openclaw `bootstrapMaxChars: 16000` 把 SOUL/USER/MEMORY/TOOLS 等 838 行 MD 塞进**每个 session**（含跟 clawock 无关的 chat）。clawock 应该只在自己的 cron run 中加载这些。
- LLM 自接：上游 openclaw 对 xiaomi `thinking="high"` 硬锁 `off`、MiniMax adaptive 被解释成 high 等问题，需要重启 gateway + 经常追 release notes 修。自接 OpenAI-compat client 完全免疫。
- 可移植：朋友/未来 SaaS 想用 clawock 不应该被强迫装 openclaw。
- 测试隔离：`python3 cli.py brief` 直接跑，不用过 openclaw gateway，可加 pytest。

**Why deferred**:
- 当前 self-evolution loop（calibration + risk metrics）还没经过一周完整数据验证
- 上周末刚做的 thinking 分层 + cron failure-alert + cron-health 巡检 还在 burn-in
- openclaw 跑得已经稳定（cron stall 已修，xiaomi work-around 已就位）
- 等数据 > 重构 — 不应该让重构打断现在的 burn-in

**Trigger to revisit**:
- ✅ 5 月 26 后看 brier_30d 第一个有意义值
- ✅ 想给朋友试用 clawock
- ✅ openclaw 出 breaking change（plugin API 大改 / cron 行为变化）
- ✅ xiaomi 修了 multi-turn 但 openclaw 没跟进
- ✅ 想接 Claude Desktop / Cursor / Aider 这种 host 互通

---

## Current coupling map

```
openclaw 给 clawock 提供:
  1. Cron daemon  (~/.openclaw/cron/jobs.json + scheduler)
  2. LLM fallback chain  (MiniMax → Xiaomi → GLM → DeepSeek → Claude → GPT)
  3. Channel adapter  (openclaw-weixin / telegram plugins)
  4. Bootstrap context injection  (BOOTSTRAP.md 强行 prepend prompt)
  5. agents.defaults.workspace 指向 clawock repo

clawock 自有:
  - scripts/harness/*  (preflight + postflight 4-step 协议)
  - scripts/data/*  (业务: 抓价/算指标/风险/校准)
  - skills/*  (LLM prompt 模板)
  - memory/* + portfolio.json + calibration.csv  (state)
  - context: SOUL/USER/MEMORY/TOOLS/AGENTS/BOOTSTRAP/CLAUDE/INVESTMENT_SOP/IDENTITY (9 个 MD)
```

---

## 6 步实施（按依赖）

### 1. Repo 物理隔离 (~1h)

- `git mv` clawock 仓库根目录到 `~/clawock/`（或保留位置但改名 symlink）
- 新建 `~/clawock/context/` 子目录，把 9 个 baseline MD 移进去
- openclaw.json 改 `agents.defaults.workspace: /root/clawock`
- openclaw.json 删 `bootstrapExtraFiles` 引用 BOOTSTRAP.md 这种全局注入（如果有）

**Acceptance**: openclaw doctor 不报 workspace 错误 + 老 cron 仍 work

### 2. CLI 入口 (~2h)

新建 `cli.py` 用 argparse / Click:

```python
clawock brief                      # daily-deep-brief 完整 4-step
clawock report --market hk --phase open  # Mode 6
clawock intraday --market us       # Mode 7
clawock dashboard                  # 重建 dashboard.json
clawock mark-followed --auto       # backfill calibration
clawock health                     # system_check + cron-health
```

每个 subcommand 内部:
1. 跑 preflight 生成 context.json
2. 调 LLM (`from llm import generate_brief`)
3. 跑 postflight 校验 + commit + push

**Acceptance**: `python3 cli.py brief` 不经过 openclaw 能产生完整 pre-open.md + plan.json + commit + WeChat 推送

### 3. LLM 自接 client (~6h) — 这部分最有价值，避开上游 bug

新建 `clawock/llm.py`:

```python
class LLMClient:
    """OpenAI-compatible client with fallback chain.
    Bypasses openclaw's per-model hard-guards (xiaomi thinking=off,
    minimax adaptive→high mistranslation, etc)."""
    
    PRIMARY = ('minimax', 'MiniMax-M2.7', {
        'base_url': 'https://api.minimaxi.chat/v1',
        'thinking': {'type': 'medium'},  # 直接传，不经 openclaw 解析
    })
    FALLBACKS = [
        ('xiaomi', 'mimo-v2.5-pro', {
            'base_url': 'https://token-plan-cn.xiaomimimo.com/v1',
            # multi-turn 时自动注入 reasoning_content 持久化
            'persist_reasoning_content': True,
        }),
        ('glm', 'glm-5.1', {...}),
        ('deepseek', 'deepseek-v4-pro', {...}),
        ('anthropic', 'claude-sonnet-4-6', {...}),
        ('openai', 'gpt-5.5', {...}),
    ]
    
    def generate(self, messages, **kwargs):
        for provider, model, cfg in [PRIMARY] + FALLBACKS:
            try:
                return self._call(provider, model, cfg, messages, **kwargs)
            except (APIError, TimeoutError) as e:
                self.log.warn(f'{provider} failed: {e}, falling back')
        raise NoProviderAvailable()
```

**关键差异（vs openclaw）**:
- xiaomi multi-turn: client 自己 persist `reasoning_content` 进 history（参考 cherry-studio PR #12084 模式），不靠上游 fix
- minimax thinking: 直接传 API 接受的值（medium/high），不经 openclaw 抽象层翻译
- Cost telemetry: 自记 prompt_tokens / completion_tokens 到 metrics file，能算 API 月成本

**Acceptance**:
- 单 ticker 多轮 + tool calls 测 xiaomi 200 OK
- MiniMax `thinking=high` 真正传到 API（看 request log）
- 一个 provider 502 自动降级到 fallback

### 4. Prompt 拼装层 (~2h)

`clawock/prompt.py`:

```python
def build_brief_prompt(date):
    """Compose prompt = context MDs + skill template + preflight context.json"""
    parts = []
    # ctx
    for fn in ['SOUL.md', 'USER.md', 'MEMORY.md', 'TOOLS.md', 'INVESTMENT_SOP.md']:
        parts.append(f"# {fn}\n\n" + (CTX_DIR/fn).read_text())
    # skill
    parts.append((SKILL_DIR/'daily-deep-brief/SKILL.md').read_text())
    # ephemeral context
    parts.append("# Today's preflight context\n\n```json\n" + 
                 (TMP_DIR/f'brief-context-{date}.json').read_text() + "\n```")
    return parts
```

**关键**：这是真正的"ctx 隔离" — clawock 完全自控注入哪些 MD，openclaw 不参与。

**Acceptance**: 不同 cron 拼出不同 prompt size（brief ~50KB，Mode 7 ~10KB），不再被 openclaw 16KB cap 切

### 5. WeChat delivery (~30min)

`clawock/delivery/wechat.py`:

**选项 A（推荐 MVP）**: 仍调 openclaw subprocess
```python
subprocess.run(['openclaw', 'message', 'send', '--channel', 'openclaw-weixin', ...])
```
零维护，仍依赖 openclaw 但只在 delivery 这一步

**选项 B（完全独立）**: 接 wxpusher.zjiecode.com（个人微信推送，免费）
```python
requests.post('https://wxpusher.zjiecode.com/api/send/message', json={...})
```
30 分钟接入 + 完全独立

**当前推荐 A** — wechat 渠道维护成本太低，没必要重造轮子

### 6. Cron payload 改写 (~30min)

`~/.openclaw/cron/jobs.json` 改每个 payload.message:

原（800 字 4-step 详细说明）:
```
你是 Rick，kcn 的 daily-deep-brief 助手...
Step 1 - Preflight: python3 scripts/harness/brief_preflight.py
Step 2 - 读 context.json...
Step 3 - LLM 合成...
Step 4 - Postflight...
```

新（单行命令）:
```
bash -c "cd ~/clawock && python3 cli.py brief --deliver wechat"
```

**Acceptance**: openclaw 完全不需要"理解" harness，纯当 cron 执行器

---

## 工程量总计

| 步骤 | 估时 | 优先级 |
|---|---|---|
| 1. Repo 隔离 | 1h | P0 |
| 2. CLI 入口 | 2h | P0 |
| 3. LLM 自接 client | 6h | **P0（这是抗 openclaw bug 关键）** |
| 4. Prompt 拼装 | 2h | P0 |
| 5. WeChat delivery (A) | 30min | P1 |
| 6. Cron payload | 30min | P1 |
| 验证 + memory + doc | 2h | P0 |
| **合计** | **14h** | 一个周末 + 两个工作日晚上 |

---

## 风险 + Rollback

| 风险 | 缓解 |
|---|---|
| 切换过程中某天 brief 没产出 | 周末做（无交易日 brief）+ 老 path 保留为 fallback cron job |
| 自接 LLM client 有 bug | Stage 3 实现完先用 mock test + 跟 openclaw 输出并行跑 1 周对账 |
| Cost 失控（自调 API 计费意外） | `llm.py` 加 daily_cost_cap，超 RMB 50 自动停 |
| WeChat 推送丢失 | Stage 5 选项 A（沿用 openclaw 渠道）暂不动 |

Rollback:
```bash
# 仍保留 ~/.openclaw/workspace symlink → ~/clawock
# 仍保留旧 cron jobs.json.bak
cp ~/.openclaw/cron/jobs.json.bak.pre-decouple ~/.openclaw/cron/jobs.json
pkill -9 -f openclaw.gateway   # systemd 自动重启读老 jobs
```

---

## 不做（明确划线）

- ❌ 自己写 cron daemon（systemd timer 替代 openclaw cron 没价值，openclaw cron 已稳）
- ❌ 自己写 channel 协议（WeChat / Telegram 重投入大，零边际收益）
- ❌ 自己写 memory-core（openclaw dreaming + main.sqlite 跟投资场景无关，让它继续跑就行）
- ❌ MCP server 模式（过度设计，等真有 Cursor / Claude Desktop 需求再说）

---

## 启动 checklist（未来想做时按此做）

- [ ] 上一周 cron stability 没新 stall
- [ ] calibration loop 已经有 ≥5 followed=true 数据
- [ ] risk.json 每日刷新一周
- [ ] dashboard 没新 schema 变化挂着
- [ ] 周末（无 cron 干扰）
- [ ] 备份 `~/.openclaw/openclaw.json` + `~/.openclaw/cron/jobs.json`
- [ ] 备份 clawock 仓库 git push 到 master
- [ ] 准备 14h 连续工作时间（拆成 2 个周末 OK）

---

## 附:dashboard.json 单一 committer(2026-05-30 评估,终局并入本计划)

**背景**:dashboard.json 是 100% 派生产物,却被 ~16 次/天、多个互不感知的写者(host harness ×4 +
5 个 GHA + 手动)抢提交到 master。2026-05-30 给 `safe_push.sh` 加了 `rebase.autoStash` 后,争用从
"高频致命"降到"偶发自愈、用户无感"(冲突时留本地、≤30min 被下次 intraday 重发)。

**当下决定**:**不单独做**。概率低 + 后果轻 + 处于 burn-in("等数据 > 重构")→ ROI 不足。

**终局正解(Option 2,与本 decouple 合流)**:dashboard.json 只装 portfolio 派生数据;
macro / sentiment / influencer_feed / news / catalysts 这些子文件**由前端 `index.html` 各自
fetch 渲染**,GHA 永不碰 dashboard.json → 真正 disjoint 写集。这是个前端解耦工程,正好等启动
decouple、前端本来就要动时一起做。

**若需提前止血(Option 1,留作配方)**:GHA 撤销"rebuild+commit dashboard"、只提交子文件;
dashboard 只由 host 提交,任何 build+commit+push dashboard 抢同一把 `/tmp/dashboard_publish.lock`;
新增系统 crontab `publish_dashboard.sh`(flock 守卫,周末也跑)补周末刷新。

**复活触发条件**:
- [ ] cron-health / safe_push 日志反复出现 dashboard `exit 2`(留本地)事件 → 上 Option 1
- [ ] 启动本 decouple 计划 / 前端重构 → 顺带做 Option 2
- [ ] dashboard 出现用户可见的陈旧 > 30min(自愈失效)

---

_本 plan 由 Claude Code 在 2026-05-19 起草。clawock burn-in 完毕后回来按此 execute。_
