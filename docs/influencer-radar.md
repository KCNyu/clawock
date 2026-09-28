# Influencer radar

The README keeps one paragraph on this; the detail lives here. 中文在后。

## English

The system scans **eight sources across US and HK** twice every trading day over
a rolling 48-hour lookback window: **Trump** (Truth Social, first-party), **Musk**
(news aggregation), **Cathie Wood / ARK Invest** (their published daily trades —
ticker, direction, share count, ETF weight), **Serenity** (public Substack posts),
and four media-proxied figures with no fetchable first-party feed — **段永平**,
**洪灏** (HK media), **Michael Burry** and **Pelosi** (congressional disclosures).
An LLM then filters the noise and links what's left to actual holdings and
sectors: stance (endorse / oppose), relevance, and a plain-language summary. Who
said what, and whether it touches your book, is already sitting in the pre-open
brief — nobody has to go scroll social media for it.

Each source carries its own candidate budget, so no single loud feed (Trump can
post dozens of times a day) can crowd the others out of the LLM batch. What each
source is and how fresh it is (a first-party post, a news proxy, a disclosed
trade from 30–45 days ago) is kept per item and shown in the dashboard card.

A concrete example: in the scan of 2026-08-17 21:54 UTC, five Musk/SpaceX
posts all matched real holdings (held_hits=5, the SPCH/SPCX cluster), and the
next morning's brief carried it verbatim — 撞持仓 (5 条全中 SPCH/SPCX). The
scan the following day's brief quotes (2026-08-18 21:52 UTC) found 1 post and
**zero holding hits** — an empty result is published as an empty result, not
skipped. Both entries can be checked against the published briefs of those
two days. Misses go in the brief exactly as often as they happen.

## 中文

系统每个交易日扫描两次(周一至五 UTC 12:50、周日至四 UTC 21:40;滚动回看 48 小时)
**特朗普(Truth Social 一手源)、马斯克(新闻聚合)**等影响者的公开动态,LLM 过滤后
自动关联持仓与板块:标出立场(endorse / oppose)、相关度,并生成中文摘要。谁说了什么、
和你的持仓有没有关系,盘前简报里直接可见——不用自己刷社交媒体。

例:UTC 2026-08-17 21:54 那次扫描,马斯克 SpaceX 相关的 5 条动态全部命中 SPCH/SPCX
持仓(held_hits=5),简报原样记下「撞持仓 (5 条全中 SPCH/SPCX)」;**次日简报引用的
UTC 2026-08-18 21:52 扫描只有 1 条动态、零持仓命中(held_hits=0),照实记空**——命中
或落空都进简报,这里展示的是一次命中。两段都能从 8-18、8-19 两天的 pre-open 简报原文复核。
