---
layout: default
title: clawock · daily briefs
description: 全部历史每日深度简报 + 周复盘
---

# Briefs

## Daily Deep Brief

每个工作日 08:03 HKT，新的在前；没生成的那天照样列出。

<ul class="brief-list">
{% assign briefs = site.pages | where_exp: "p", "p.path contains 'memory/'" | where_exp: "p", "p.path contains '-pre-open'" %}
{% for d in site.data.daily_briefs %}
  {% assign hit = false %}
  {% for p in briefs %}{% if p.path == d.path %}{% assign hit = p %}{% endif %}{% endfor %}
  <li>
    {% if hit %}<a href="{{ hit.url | relative_url }}">{{ d.date }}</a>
    {% else %}<span class="brief-missing" title="当天的简报没有生成">{{ d.date }} · 未生成</span>{% endif %}
  </li>
{% endfor %}
</ul>

## Weekly Reviews

每周日 22:00 HKT · MiniMax-M3.1-Flash，无回退模型；没生成的那周照样列出。

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
