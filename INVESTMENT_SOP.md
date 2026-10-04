# Investment question SOP

Follow this sequence for any question about holdings, P&L, a US or HK position, adding or
trimming, valuation or sentiment. It is read on demand; it is not injected.

## Sources

| Need | Source |
|---|---|
| Holdings, cost, realised P&L | `portfolio.json` (`shares > 0` is active, `shares == 0` is exited) |
| Data rules, standing preferences | `MEMORY.md` (injected in direct chat; read it only when it is not in context) |
| Skill routing, commands, fallbacks | `TOOLS.md` |
| Skill output format | `skills/<name>/SKILL.md`, the mode the question maps to |

## Sequence

1. Read `portfolio.json` for the current holdings and cost. Skip names with `shares == 0`.
2. Pick the skill from `TOOLS.md` § Skill 路由表.
3. Fetch live prices before any price-dependent statement:
   - US: `clawock analyze-us [TICKER]`
   - HK: `clawock analyze-hk [TICKER]`
   - prices only: `clawock us-quotes`
4. Answer in the skill's output format.
5. After a trade, record it in `portfolio.json` (`holdings[].trades[]`, then
   `clawock reconcile`) and commit as `AGENTS.md` § Runtime commits lists.

Do not state P&L without step 3. The data rules are in `MEMORY.md` § 数据规则 and are not
repeated here.

## Output

- Holdings answers are tables (three or more data points).
- Give the call directly. No hedging and no "not financial advice" disclaimer.
- Label each number as live, closing or cached.
- When a fetch failed, name the source and how old the fallback is.
- End with the data timestamp: `数据: clawock analyze-us|analyze-hk {timestamp}`.

## What goes where

| Event | Update |
|---|---|
| Trade filled | `portfolio.json` |
| Strategy or standing preference changed | `MEMORY.md` |
| Data source or fallback order changed | `MEMORY.md` + `docs/reference/tool-operations.md` |
| Skill output format changed | the mode section in `skills/<name>/SKILL.md`; cron follows it |

Keep holdings, ticker lists and amounts out of `MEMORY.md`. `portfolio.json` is the only
copy.
