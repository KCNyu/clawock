---
layout: default
title: clawock · daily briefs
description: 全部历史每日深度简报 + 周复盘
---

# Daily Briefs

每个工作日 08:03 HKT 自动跑 Tier 1/2/3 + Judge 全 swarm 分析 → markdown 落盘 + WeChat 推送 + dashboard 数据刷新。

## Daily Deep Brief · 盘前深度简报

按日期倒序（Pages 站内渲染，不跳 GitHub）：

<ul class="brief-list">
{% assign briefs = site.pages | where_exp: "p", "p.path contains 'memory/'" | where_exp: "p", "p.path contains '-pre-open'" | sort: 'path' | reverse %}
{% for f in briefs %}
  <li>
    <a href="{{ f.url | relative_url }}">{{ f.path | split: '/' | last | replace: '.md', '' | replace: '-pre-open', '' }}</a>
  </li>
{% endfor %}
</ul>

## Weekly Reviews · 周复盘

由 `.github/workflows/weekly-review.yml` 每周日 22:00 HKT 自动跑（MiniMax-M3 · thinking enabled · max 32K，失败时回退 OpenCode Zen 的 deepseek-v4-flash）。

列的是**每一个应该有复盘的 ISO 周**，不是每一个存在的文件——2026-W33 与 2026-W35 的排程跑挂了（provider 三次超时 + 回退腿 401），没有任何东西会补跑，所以缺口留在这里给人看见，而不是让周号自己跳过去。

<ul class="brief-list">
{% assign weeklies = site.pages | where_exp: "p", "p.path contains 'memory/weekly/'" %}
{% for w in site.data.weekly_reviews %}
  {% assign hit = false %}
  {% for p in weeklies %}{% if p.path == w.path %}{% assign hit = p %}{% endif %}{% endfor %}
  <li>
    {% if hit %}<a href="{{ hit.url | relative_url }}">{{ w.week }}</a>
    {% else %}<span class="brief-missing" title="该周的排程跑失败，未生成">{{ w.week }} · 未生成</span>{% endif %}
  </li>
{% endfor %}
</ul>

## Skills

完整 skill 列表见 GitHub：[skills/ 目录](https://github.com/KCNyu/clawock/tree/master/skills)

- [daily-deep-brief](https://github.com/KCNyu/clawock/blob/master/skills/daily-deep-brief/SKILL.md) — 08:03 HKT 全 swarm
- [hk-stock-analysis](https://github.com/KCNyu/clawock/blob/master/skills/hk-stock-analysis/SKILL.md) — 港股 Mode 1-7
- [us-stock-analysis](https://github.com/KCNyu/clawock/blob/master/skills/us-stock-analysis/SKILL.md) — 美股 Mode 1-7
- [portfolio-swarm-review](https://github.com/KCNyu/clawock/blob/master/skills/portfolio-swarm-review/SKILL.md) — 手动深度组合分析
- [portfolio-risk-review](https://github.com/KCNyu/clawock/blob/master/skills/portfolio-risk-review/SKILL.md) — 风险视角组合 review
- [openclaw-tune](https://github.com/KCNyu/clawock/blob/master/skills/openclaw-tune/SKILL.md) — openclaw 系统级维护

## 📚 Reference

- [README](https://github.com/KCNyu/clawock#readme) — 项目总览 + 架构 + cron map
- [Dashboard](./) — 实时持仓 + 集中度 + retrospective
