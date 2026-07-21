---
name: tavily
description: AI-optimized web search via Tavily API. Returns concise, relevant results for AI agents.
homepage: https://tavily.com
metadata: {"clawdbot":{"emoji":"🔍","requires":{"bins":["node"],"env":["TAVILY_API_KEY"]},"primaryEnv":"TAVILY_API_KEY"}}
---

# Tavily Search

AI-optimized web search using Tavily API. Designed for AI agents - returns clean, relevant content.

## Search

```bash
node {baseDir}/scripts/search.mjs "query" --bucket research
node {baseDir}/scripts/search.mjs "query" -n 10 --bucket research
node {baseDir}/scripts/search.mjs "query" --deep --bucket research
node {baseDir}/scripts/search.mjs "query" --topic news --bucket research
```

## Options

- `-n <count>`: Number of results (default: 5, max: 20)
- `--deep`: Use advanced search for deeper research (slower, more comprehensive)
- `--topic <topic>`: Search topic - `general` (default) or `news`
- `--days <n>`: For news topic, limit to last n days
- `--bucket <name>`: **Which monthly budget bucket to charge** — `brief` / `report` / `intraday` / `research` / `extract` / `default`. Ad-hoc/manual research uses `--bucket research`. **Omitting it charges the small `default` bucket (60/mo)**, which is exhausted quickly on purpose.

## Budget (免费档 1000 credits/月, 全局共享)

basic 搜索 1 credit，`--deep` 2，extract 1/5 URL。硬护栏在 `lib/ledger.mjs`（本地月度账本，reservation 式扣费，超限 **exit 0** 优雅降级返回 "unavailable" — **别当报错**，退回内置搜索）。账本在仓库外 `/root/.openclaw/tavily-credit-ledger.json`；查真实账单：`curl -H "Authorization: Bearer $TAVILY_API_KEY" https://api.tavily.com/usage`（注意有延迟，不能当实时闸）。

## Extract content from URL

```bash
node {baseDir}/scripts/extract.mjs "https://example.com/article"
```

Notes:
- Needs `TAVILY_API_KEY` from https://tavily.com
- Tavily is optimized for AI - returns clean, relevant snippets
- Use `--deep` for complex research questions
- Use `--topic news` for current events
