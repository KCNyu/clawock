# 决策心智账本 — Decision Mind Ledger (schema v0 草案)

> 讨论稿,未落库。用途:把对话与盘前产生的**投资判定**冻结为
> 「思想快照 + 情绪压力 + 可证伪条件」的结构化记录,事后自动对账。
> 与券商流水、交易日记的区别:对抗性结构(bear 强制)+ 情绪冻结 +
> 确定性对账 + 校准统计。

## 一条记录 = 决策卡(冻结)+ 对账(事后填写)

```json
{
  "schema_version": 0,
  "decision_id": "dec-<12hex>",
  "subject": { "ticker": "00100", "market": "HK", "currency": "HKD" },
  "decided_at": "2026-08-16T13:45:00+08:00",
  "source": "conversation",                  // conversation | brief
  "action": "reject",                        // buy/add/trim/sell/hold/watch/reject/abstain
  "confidence": 0.65,                        // 0..1
  "driven_by": "fundamental",                // technical|fundamental|sentiment|mixed

  "mind": {                                  // ← 思想快照(append-only,冻结)
    "bull": { "summary": "...", "evidence": ["..."] },
    "bear": { "summary": "...", "evidence": ["..."] },   // 强制非空:无反方不许落账
    "thesis": "...",
    "invalidation": ["缩量企稳", "2 日不创新低", "站回 340"]   // 可证伪条件
  },

  "emotion": {                               // ← 情绪压力层(决策时自评)
    "pressure": "averaging_down",            // fomo|revenge|averaging_down|fear|euphoria|calm|mixed
    "note": "浮亏 -40% 的摊本冲动,判定时明确压过;这次忍住没加"
  },

  "accounting": {                            // ← 对账(事后,只允许更新这里)
    "trigger": { "status": "pending", "condition": "站回 340", "price_at_decision": 329.0 },
    "execution": { "executed": false, "note": "判定为不加,未产生订单" },
    "outcome": { "grade": "pending" },       // correct|wrong|mixed|pending
    "calibration": { "confidence_bin": "0.6-0.7", "hit": null }
  }
}
```

## 字段规则(不可协商)

1. **bear 强制非空** —— 没有真实反方的判定不许落账(对抗性结构的核心)
2. **mind 与 emotion 冻结** —— 落账后不可改;只有 `accounting` 可被
   evaluation 机制更新(触发/执行/结果/校准)
3. **可证伪优先** —— `invalidation` 必须写可观察条件,不写空话
4. **情绪默认诚实** —— 默认 `calm`;浮亏摊本/FOMO/报复性场景要求自认
   (账本的价值一半在这里)
5. **action 枚举对齐 clawock 决策契约**,与盘前简报决策同词表

## 与现有系统关系

- **数据落点**:对话决策写入 `memory/decisions.jsonl`(与盘前决策同账本,
  真源一个)或单开 `memory/conversation-decisions.jsonl`(待定,见讨论)
- **对账**:复用现有 evaluation 机制(`triggered/executed` 语义),执行标记
  走 `clawock mark-followed`
- **面板**:DSH Decision Studio 从「runs 调试视图」改为「决策心智视图」:
  日期/标的/动作/信心/情绪/对账状态,展开看决策卡全貌
- **校准**:`confidence_bin` 汇入命中率统计,回答「我的 0.65 准不准」

## 样例一(今天真实):MiniMax 加仓判定 → 未加仓

```
00100 MINIMAX-W · 2026-08-16 · action reject(加仓) · 0.65 · fundamental
Bull   营收 +159% YoY;入通/海外霸榜/高盛三催化叙事
Bear   净利率 -2368%、负债率 343%、每股净资产 -24.37;z+2.8σ 情绪极值反转
Thesis 高增长救不了资不抵债,情绪反转期先活下来
失效   缩量企稳 + 2 日不创新低 + 站回 340
情绪   averaging_down —— 浮亏 -40% 的摊本冲动被压过,这次忍住没加
对账   execution=未加仓(判定被遵守)· trigger=pending(等 340/企稳)
```

## 样例二(历史复盘,可选补录):SPCH 无限子弹流

```
SPCH · 2026-06-23 · action add(第 6 次摊本) · 0.3 · sentiment
Bull   无限子弹流,均价摊低后回本更快
Bear   minmax 立场=反对:逆硬止损线第 6 次,累计加仓逼近 $3000
Thesis 只要反弹就回本(事后看:反弹出现但被更高成本拖累)
失效   单日 -15% 或正股单周 -25% 升级 P0
情绪   averaging_down —— 明确自认:这单是情绪驱动
对账   execution=已执行 10 股 @13.13 · outcome=mixed
```

## 面板设计(与 dashboard 同风格)

- 令牌:bg #070A0F / 卡片 #202E3E / border #1D2937 / accent #36A3FF /
  正 #28C08D / 负 #F05B67 / 警示 #E3A640(全部取自 dashboard.css)
- 列表卡:日期分组,每张卡 = 标的 + action 胶囊(加=绿/减=红/观望=灰)+
  信心 + 情绪胶囊(非 calm 才显示,警示色)+ 对账状态胶囊(已触发/已执行/待定)
- 展开详情:Bull/Bear 对置条(正绿负红 + 证据计数)、信心计量条、
  失效条件列表、情绪注记、对账区(触发/执行/校准)
- 预览:`decision-mind-ledger.html`(静态 mock,本机可开)

## 数据互通(OpenClaw ↔ DSH,一个账本两个入口)

- **唯一真源**:`<workspace>/memory/decisions.jsonl`。OpenClaw 盘前简报的
  决策与 DSH 对话判定写同一个账本,两边都能读。
- **DSH 读 OpenClaw 产出**:面板 node 半区读取该文件(默认工作区
  `/root/.openclaw/workspace`,可配置),按 decision_group_id/decided_at
  分组;旧记录没有 mind/emotion 字段时降级渲染(只有动作/条件/对账)。
- **对话判定落账**:skill 规范——verdict 产生时追加一条,`source:
  "conversation"`,字段与现有 schema 兼容(condition 用同形结构,以便
  每日 settle 自动对账触发/执行)。
- **互通已验证(源码读证)**:`brief_postflight.log_decisions` 为
  load → upsert/settle → 全量写回,不删外部记录;实现时用复制账本做
  迁移测试钉住「对话记录经 postflight 一轮后仍在且被 settle」。
- **kcn 自用**:面板默认指向每日 OpenClaw 运行的真实工作区,
  决策记录实时可见。
