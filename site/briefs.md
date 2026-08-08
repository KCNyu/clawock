---
layout: default
title: clawock · daily briefs
description: 全部历史每日深度简报 + 手写笔记 + plan.json
---

# Daily Briefs

每个工作日 08:00 HKT 自动跑 Tier 1/2/3 + Judge 全 swarm 分析 → markdown 落盘 + WeChat 推送 + dashboard 数据刷新。

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

## Weekly Reviews · Xiaomi 周复盘

由 `.github/workflows/weekly-review.yml` 每周日 22:00 HKT 自动跑（Xiaomi MiMo v2.5-pro · thinking enabled · max 32K）。

<ul class="brief-list">
{% assign weeklies = site.pages | where_exp: "p", "p.path contains 'memory/weekly/'" | sort: 'path' | reverse %}
{% for f in weeklies %}
  <li>
    <a href="{{ f.url | relative_url }}">{{ f.path | split: '/' | last | replace: '.md', '' }}</a>
  </li>
{% endfor %}
</ul>

## Daily Notes · 手写笔记

<ul class="brief-list">
{% for f in sorted %}
  {% if f.path contains '/memory/' and f.extname == '.md' and f.name != '_TEMPLATE.md' %}
    {% unless f.path contains '-pre-open' or f.path contains 'recovery_log' or f.path contains '6_month_review' or f.path contains 'archive_index' %}
  <li>
    <a href="https://github.com/KCNyu/clawock/blob/master{{ f.path }}">{{ f.name | replace: '.md', '' }}</a>
  </li>
    {% endunless %}
  {% endif %}
{% endfor %}
</ul>

## Plan archive · 历史 plan.json

Self-learning loop 用，给次日 retrospective 算 trigger / P&L / confidence calibration。

<ul class="brief-list">
{% for f in sorted %}
  {% if f.path contains '/memory/' and f.extname == '.json' and f.path contains '-plan' %}
  <li>
    <a href="https://github.com/KCNyu/clawock/blob/master{{ f.path }}">{{ f.name }}</a>
  </li>
  {% endif %}
{% endfor %}
</ul>

## Skills

完整 skill 列表见 GitHub：[skills/ 目录](https://github.com/KCNyu/clawock/tree/master/skills)

- [daily-deep-brief](https://github.com/KCNyu/clawock/blob/master/skills/daily-deep-brief/SKILL.md) — 08:00 HKT 全 swarm
- [hk-stock-analysis](https://github.com/KCNyu/clawock/blob/master/skills/hk-stock-analysis/SKILL.md) — 港股 Mode 1-7
- [us-stock-analysis](https://github.com/KCNyu/clawock/blob/master/skills/us-stock-analysis/SKILL.md) — 美股 Mode 1-7
- [portfolio-swarm-review](https://github.com/KCNyu/clawock/blob/master/skills/portfolio-swarm-review/SKILL.md) — 手动深度组合分析
- [portfolio-risk-review](https://github.com/KCNyu/clawock/blob/master/skills/portfolio-risk-review/SKILL.md) — 风险视角组合 review
- [openclaw-tune](https://github.com/KCNyu/clawock/blob/master/skills/openclaw-tune/SKILL.md) — openclaw 系统级维护

## 📚 Reference

- [README](README.html) — 项目总览 + 架构 + cron map
- [Dashboard](./) — 实时持仓 + 集中度 + retrospective
