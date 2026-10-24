# Data coverage and health

Sources are independent operators, not URL counts. A mirror of the same filing
adds an access route, not independent financial evidence. Coverage varies by
instrument: a provider listed below does not promise every new IPO or ETF.

| Surface / entry | Assets and fields | Sources and independence | Failure behavior |
|---|---|---|---|
| US quotes (`analyze-us`, `us-quotes`) | US stocks/ETFs: price, prior close, day change, range, volume | Nasdaq, Eastmoney, Finnhub, Yahoo, Alpha Vantage, Polygon, Tencent; key-dependent providers require existing credentials | Completeness/freshness-ranked fallbacks; missing requested tickers prevent whole-leg write; incomplete data explicitly flagged |
| HK quotes (`analyze-hk`) | HK stocks/ETFs: price, prior close, range, volume | Tencent + Eastmoney cross-check; Stooq and Yahoo fallback | Disagreement is surfaced; OHLC-only Stooq cannot invent a previous close; new IPO coverage may effectively be Tencent-only |
| Daily / intraday bars (`bars`, quant, intraday recommendations) | Registered equities, ETFs and underlying indices; OHLCV and sessions | Tencent daily plus asset-specific history providers; intraday provider coverage is separate | Canonical merge rejects conflicts and records them; gaps and stale sessions reported by integrity; no invented bars |
| FX (`fx`) | USD/HKD conversion | Frankfurter (ECB), ExchangeRate-API Open, Yahoo | 4h cache; Open API checks base, success and provider age; all routes fail → explicitly stale cache, then explicitly labelled peg estimate; cached-only readers return unavailable when absent |
| Fund flows (`fundflow`) | Provider-covered HK/US instruments; daily classified order-size net flows | Eastmoney only (one operator) | `status=unavailable` on empty/failed response, not zero flow; source and latest data date included. This is vendor-classified order flow, not audited institutional cash movements |
| Financial statements / fundamentals (`fundamentals`, `filings`) | HK/US issuer periods: revenue, profit, EPS, margins, balance/cash-flow items | Eastmoney for HK/US; SEC XBRL for US (independent access, issuer-reported facts) | Empty Eastmoney result is explicitly unavailable; US exchange-suffix retry is the same source; SEC needs a configured identifying contact, not an API key. ETFs require underlying look-through |
| Disclosures / catalysts | US SEC forms, HK announcements, earnings and official event dates | SEC submissions/full-text, Nasdaq/Finnhub mirrors, HKEXnews, Tencent; mirrors do not count as new underlying facts | Source status and publication time retained; date-only mirrors cannot manufacture acceptance times |
| Macro (`macro`) | VIX, 10Y yield, DXY, HSI/HSTECH, SPX, Nasdaq Composite, F&G and Fed releases | Stooq/Tencent/Yahoo according to symbol; Cboe official VIX fallback; CNN; Federal Reserve | `coverage` reports each quote's availability/date independently. A current SPX cannot hide stale VIX. New-producer snapshots recheck series dates on brief read and omit bad rows |
| Volatility structure / tail risk (`macro`) | Cboe VIX (30-day), VIX9D, VIX3M, SKEW; same-session VIX/VIX3M ratio | Cboe official daily CSVs (one independent operator, four series) | Requires latest completed US session; missing prior session means unknown change; mismatched dates mean no ratio. Daily closes, not intraday ticks or return forecasts. Included in brief context; three added indices shown with dates |
| News / attention / statements | Per-issuer HK/US headlines, publication times, market flashes; Reddit attention and public-person statements | Tencent, Eastmoney, Google News RSS, Yahoo RSS, 同花顺, Finnhub; DeepSeek/Tavily search; Reddit and individual statement sources | Per-source status, cache windows and evidence timestamps; unavailable is not “no news”. Search requires existing credentials. Attention is not analyst consensus |
| Portfolio risk (`portfolio-risk`, `integrity`) | Exposure, concentration, underlying leverage, beta, range/stop checks, cash and P&L reconciliation | Derived from ledger, canonical bars, registry and FX; not another independent data vendor | Missing evidence stays unknown; integrity distinguishes arithmetic errors, quote warnings and rejected bar conflicts |

## Health entry points

- `clawock integrity`: ledger conservation, missing quotes, previous-close
  coverage, dated canonical bars, conflicts and source distribution. Its CLI
  writes an audit artifact; `portfolio.integrity.check(path)` is the read-only API.
- `clawock validate-sidecar macro|sentiment|…`: publication shape and usable
  coverage gates. Macro accepts partial coverage, but never a new snapshot with
  zero healthy market quotes. See `publish/artifacts.py` for each sidecar.
- `strategies.plugins.morning_scans.Scans`: file freshness, market-session gate,
  then per-series filtering and coverage in the brief's macro reading.
- `ops/system_check.py`: host/configuration, scheduled scan delivery, calendar
  horizon, benchmark freshness, read budgets and publication checks.
- Dashboard data-health card: generated-file freshness, integrity, product
  delivery and scheduled jobs. A recent file timestamp alone is not proof that
  all its upstream series worked; inspect the per-source/per-series fields.

## Source contracts and gaps

Cboe CSVs are linked from its [historical data page](https://www.cboe.com/tradable_products/vix/vix_historical_data/).
Only latest closes, their genuine previous closes and provenance are retained;
full downloaded history is not archived by this scanner. Fetches have 10-second
timeouts and at most four concurrent macro tasks. No account or subscription is
created. Refer to [third-party data](../legal/third-party-data.md) for rights.

ExchangeRate-API's [Open API](https://www.exchangerate-api.com/docs/free) updates
daily and requires attribution: **[Rates by ExchangeRate-API](https://www.exchangerate-api.com/)**.
It replaces exchangerate.host's key-required endpoint. The returned base must be
USD and the provider update must be no more than 96 hours old. It is a daily
reference conversion rate, not an executable FX quote.

Remaining coverage gaps include reliable HK IPO backup quotes, independent
order-flow definitions, analyst consensus/revisions, credit spreads, and a
complete official yield curve. DXY and Yahoo 10Y can remain unavailable during
Yahoo throttling. Do not relabel futures, different indices, short interest or
news sentiment as substitutes for those fields. A proposed paid route needs
instrument coverage, licensing/redistribution terms and a current vendor quote;
no subscription, registration or contractual commitment is made by this code.
