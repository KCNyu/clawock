import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
//#region src/ledger.ts
/**
* Read-only readers over the OpenClaw desk's produced data: the shared
* decision ledger, the portfolio, and recent daily plans. Pure Node, no
* Cordis/typert dependencies — unit-testable in isolation.
*
* These are the files the OpenClaw runtime produces every day, so whatever
* OpenClaw writes, this DSH plugin can show.
*/
const PLAN_PATTERN = /^(\d{4}-\d{2}-\d{2})-plan\.json$/;
function readJson(path) {
	if (!existsSync(path)) return null;
	try {
		return JSON.parse(readFileSync(path, "utf8"));
	} catch {
		return null;
	}
}
/**
* Parse the decision ledger (memory/decisions.jsonl) — one JSON object per
* line. Malformed lines are skipped, never fatal: the desk's own writer
* round-trips the file and this view must survive any of its states.
* @param workspace - desk workspace root.
* @returns `{ entries, path }`; entries are in file order (oldest first).
*/
function readLedger(workspace) {
	const path = join(workspace, "memory", "decisions.jsonl");
	const entries = [];
	if (existsSync(path)) {
		const lines = readFileSync(path, "utf8").split("\n");
		for (const line of lines) {
			if (!line.trim()) continue;
			try {
				entries.push(JSON.parse(line));
			} catch {}
		}
	}
	return {
		entries,
		path
	};
}
/**
* Summarize the portfolio (portfolio.json): per-book holdings with the desk's
* own money fields, plus the flattened trade log (newest first).
* @param workspace - desk workspace root.
* @returns `{ books, trades, lastUpdated }`.
*/
function readPortfolio(workspace) {
	const doc = readJson(join(workspace, "portfolio.json"));
	if (doc === null || typeof doc !== "object" || Array.isArray(doc)) return {
		books: [],
		trades: [],
		lastUpdated: null,
		marketContext: {}
	};
	const books = [];
	const trades = [];
	const portfolios = doc["portfolios"];
	if (portfolios !== null && typeof portfolios === "object" && !Array.isArray(portfolios)) for (const [name, book] of Object.entries(portfolios)) {
		if (book === null || typeof book !== "object" || Array.isArray(book)) continue;
		const bookObj = book;
		if (!Array.isArray(bookObj["holdings"])) continue;
		const rawHoldings = bookObj["holdings"].filter((h) => h !== null && typeof h === "object");
		const holdings = rawHoldings.filter((h) => Number(h["shares"] ?? h["quantity"] ?? 0) > 0).map((h) => ({
			ticker: String(h["ticker"] ?? h["stock_name"] ?? h["name"] ?? "?"),
			shares: Number(h["shares"] ?? h["quantity"] ?? 0),
			cost: h["cost_basis"] == null ? null : Number(h["cost_basis"]),
			price: h["current_price"] == null ? null : Number(h["current_price"]),
			pnlPct: h["pnl_percent"] == null ? null : Number(h["pnl_percent"]),
			pnlAbs: h["pnl_abs"] == null ? null : Number(h["pnl_abs"])
		}));
		if (holdings.length === 0) continue;
		const market = /^hk/i.test(name) ? "HK" : "US";
		const currency = typeof bookObj["currency"] === "string" ? bookObj["currency"] : market === "HK" ? "HKD" : "USD";
		books.push({
			name,
			currency,
			truePrincipal: bookObj["true_principal"] == null ? null : Number(bookObj["true_principal"]),
			holdings
		});
		for (const holding of rawHoldings) {
			const rawTrades = holding["trades"];
			if (!Array.isArray(rawTrades)) continue;
			for (const tr of rawTrades) {
				if (tr === null || typeof tr !== "object") continue;
				const trObj = tr;
				trades.push({
					ticker: String(holding["ticker"] ?? holding["stock_name"] ?? holding["name"] ?? "?"),
					market,
					currency,
					date: typeof trObj["date"] === "string" ? trObj["date"] : null,
					action: typeof trObj["action"] === "string" ? trObj["action"] : "buy",
					shares: Number(trObj["shares"] ?? 0),
					price: trObj["price"] == null ? null : Number(trObj["price"]),
					realizedPnl: trObj["realized_pnl"] == null ? null : Number(trObj["realized_pnl"]),
					note: typeof trObj["note"] === "string" ? trObj["note"] : null
				});
			}
		}
	}
	trades.sort((a, b) => (a.date ?? "") < (b.date ?? "") ? 1 : -1);
	return {
		books,
		trades,
		lastUpdated: typeof doc["last_updated"] === "string" ? doc["last_updated"] : null,
		marketContext: doc["market_context"] ?? {}
	};
}
/**
* List recent daily plans (memory/YYYY-MM-DD-plan.json), newest first.
* @param workspace - desk workspace root.
* @param limit - how many plans to return.
*/
function readPlans(workspace, limit = 14) {
	const plans = [];
	let files = [];
	try {
		files = readdirSync(join(workspace, "memory"));
	} catch {
		return { plans };
	}
	const dated = files.map((name) => PLAN_PATTERN.exec(name)).filter((m) => m !== null).map((m) => ({
		date: m[1],
		name: m[0]
	})).sort((a, b) => a.date < b.date ? 1 : -1).slice(0, limit);
	for (const file of dated) {
		const doc = readJson(join(workspace, "memory", file.name));
		if (doc === null || typeof doc !== "object" || Array.isArray(doc)) continue;
		const docObj = doc;
		plans.push({
			date: file.date,
			decisions: Array.isArray(docObj["decisions"]) ? docObj["decisions"].length : 0,
			title: typeof docObj["title"] === "string" ? docObj["title"] : null
		});
	}
	return { plans };
}
/** A bar file is `memory/bars/<ticker>.json`; the ticker is a path component. */
const TICKER_PATTERN = /^[A-Za-z0-9.\-]{1,15}$/;
/** Bar keys are exchange session dates. */
const SESSION_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
/**
* Ordering key for ISO dates (no Date TZ pitfalls). Monotonic, so it is safe
* for `<`/`>` comparison and sorting — but the *difference* between two of
* these is NOT a day count (2026-08-31 → 2026-09-01 differs by 2, not 1).
* Use `dayGap` whenever a real distance is needed.
*/
function dayNum(iso) {
	if (typeof iso !== "string") return null;
	const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
	if (!m) return null;
	return Number(m[1]) * 400 + Number(m[2]) * 32 + Number(m[3]);
}
/** UTC midnight epoch for an ISO date, for real calendar-day arithmetic. */
function utcDay(iso) {
	if (typeof iso !== "string") return null;
	const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
	if (!m) return null;
	return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}
/** Signed calendar-day distance `to - from`; null when either side is unparseable. */
function dayGap(from, to) {
	const a = utcDay(from);
	const b = utcDay(to);
	if (a === null || b === null) return null;
	return Math.round((b - a) / 864e5);
}
/**
* How far after a fill a close may sit and still be called "T+1".
* A Friday fill settles against Monday (3 calendar days); one intervening
* public holiday makes 4. Anything beyond that is a different horizon and
* must not be labelled T+1 — see the snapshot-coverage note on `futureClose`.
*/
const T1_MAX_GAP_DAYS = 4;
/**
* Shared dead zone for T+1 readings: a move smaller than this reads as flat
* for every action. Host-side single source of truth so the chip, the trace
* node and the verdict text can never disagree (they used to: three separate
* thresholds coloured the same fill two different ways).
*/
const T1_FLAT_BAND_PCT = 1;
/** Actions that reduce a position — a rising price is bad news for these. */
const SELL_ACTIONS = /* @__PURE__ */ new Set([
	"sell",
	"cut",
	"trim",
	"trim_on_rebound"
]);
function isSellAction(action) {
	return SELL_ACTIONS.has(action);
}
/** Actions that add to a position. */
const ADD_ACTIONS = /* @__PURE__ */ new Set(["buy", "add"]);
/**
* 'same' | 'opposite' | 'other' — the plan's direction against the fill's.
*
* Mirrors `_plan_fill_alignment` in src/clawock/publish/dashboard.py; the two
* implementations are pinned together by tests/test_decision_trace_parity.py.
*/
function planFillAlignment(planAction, fillAction) {
	if (typeof planAction !== "string" || typeof fillAction !== "string") return null;
	if (planAction === fillAction) return "same";
	const sideOf = (action) => ADD_ACTIONS.has(action) ? "add" : SELL_ACTIONS.has(action) ? "reduce" : null;
	const planSide = sideOf(planAction);
	const fillSide = sideOf(fillAction);
	if (planSide === null || fillSide === null) return "other";
	return planSide === fillSide ? "same" : "opposite";
}
/**
* A rationale fit for a reader: the risk engine's internal breach ids stripped.
*
* The raw field carries things like "硬止损 -27.23% ≤ -18% (breach
* risk-95ac7f6cd591 30d)" — the hash says nothing to anyone outside the
* process, and it is sitting in the one field a reader opens to understand
* *why*. Mirrors `_readable_rationale` in dashboard.py, minus the 140-char
* truncation: that exists to fit a published payload cap, which this panel
* (reading the workspace at runtime) does not have.
*/
function readableRationale(text) {
	if (typeof text !== "string") return null;
	const cleaned = text.replace(/\s*\((?:breach\s+)?risk-[0-9a-f]{6,}(?:\s+\d+d)?\)/g, "").replace(/[ \t]{2,}/g, " ").trim();
	return cleaned === "" ? null : cleaned;
}
/** Good/bad/flat reading of a T+1 move, action-aware and dead-zoned. */
function t1ToneOf(action, delta) {
	if (Math.abs(delta) < 1) return "flat";
	const up = delta > 0;
	return isSellAction(action) ? up ? "loss" : "win" : up ? "win" : "loss";
}
/** Chinese verdict text for a T+1 move, on the same dead zone as `t1ToneOf`. */
function t1VerdictOf(action, delta) {
	if (Math.abs(delta) < 1) return "持平";
	const up = delta > 0;
	return isSellAction(action) ? up ? "卖飞" : "卖对" : up ? "涨" : "跌";
}
/**
* Session close per ticker from the canonical bar store: { ticker: { date: close } }.
*
* Reads `memory/bars/<ticker>.json`, the same store the Python settlement path
* uses — deliberately NOT `memory/snapshots/*.json`.
*
* A snapshot is a *portfolio* file whose `current_price` carries the vintage of
* whichever cron happened to write it. `src/clawock/market_data/bars.py`
* measured it on 00100 across 15 snapshots: the previous close 7 times, that
* day's close 3 times, an intraday print 5 times. Worse, the field is carried
* forward once a position is closed — NVDA sat at a frozen 213 for five
* straight sessions while its real closes ran 222.32 / 220.61 / 223.47 /
* 219.51 / 215.33. Settlement migrated off snapshots for exactly this reason;
* this view stayed behind and marked 82% of its T+1 deltas against a price the
* rest of the system had already disowned, flipping 10 verdicts outright.
*
* Bars are session-dated, unadjusted, and never contain an unfinished session,
* so a close read here is the same number the ledger settles against. Only the
* tickers actually traded are read, which is also why this is cheaper than the
* full snapshot scan it replaces.
*
* @param workspace - desk workspace root.
* @param tickers - the tickers to load; anything else on disk is not read.
*/
function readBarCloses(workspace, tickers) {
	const byTicker = {};
	for (const ticker of new Set(tickers)) {
		if (!TICKER_PATTERN.test(ticker)) continue;
		const doc = readJson(join(workspace, "memory", "bars", `${ticker}.json`));
		if (doc === null || typeof doc !== "object" || Array.isArray(doc)) continue;
		const bars = doc["bars"];
		if (bars === null || typeof bars !== "object" || Array.isArray(bars)) continue;
		const closes = {};
		for (const [date, bar] of Object.entries(bars)) {
			if (!SESSION_DATE_PATTERN.test(date)) continue;
			if (bar === null || typeof bar !== "object" || Array.isArray(bar)) continue;
			const close = bar["close"];
			if (typeof close === "number" && isFinite(close)) closes[date] = close;
		}
		if (Object.keys(closes).length > 0) byTicker[ticker] = closes;
	}
	return byTicker;
}
/**
* The n-th snapshot close strictly after `date` for `ticker` — but only when
* it actually lands inside `maxGapDays` calendar days of the fill.
*
* The snapshot series is not a trading calendar: it starts the day the desk
* began writing `memory/snapshots/`, and it has holes whenever the daily job
* missed a run. Without the gap ceiling this function happily returns "the
* next close we happen to own", which for fills predating the series is
* months later — those were being rendered under a literal "T+1" label. A
* horizon we cannot actually observe must read as unknown, not as a verdict.
*/
function futureClose(byTicker, ticker, date, n, maxGapDays = 4) {
	const days = byTicker[ticker];
	if (!days) return null;
	const base = dayNum(date);
	if (base === null) return null;
	const hit = Object.keys(days).filter((d) => (dayNum(d) ?? 0) > base).sort()[n - 1];
	if (hit === void 0) return null;
	const gap = dayGap(date, hit);
	if (gap === null || gap > maxGapDays) return null;
	return {
		date: hit,
		price: days[hit]
	};
}
/** One real fill, enriched for the trace view. */
function enrichTrade(trade, byTicker, decByTicker, books) {
	const out = {
		...trade,
		holdPnl: null,
		t1: null,
		decision: null,
		side: isSellAction(trade.action) ? "reduce" : ADD_ACTIONS.has(trade.action) ? "add" : null
	};
	const t1 = futureClose(byTicker, trade.ticker, trade.date, 1);
	if (t1 !== null && trade.price != null) {
		const delta = Math.round((t1.price - trade.price) / trade.price * 100 * 100) / 100;
		out.t1 = {
			date: t1.date,
			price: Math.round(t1.price * 100) / 100,
			delta,
			verdict: t1VerdictOf(trade.action, delta),
			tone: t1ToneOf(trade.action, delta)
		};
	}
	let best = null;
	let bestDiff = Number.POSITIVE_INFINITY;
	for (const row of decByTicker[trade.ticker] ?? []) {
		const gap = dayGap(row.date, trade.date);
		if (gap === null) continue;
		const diff = Math.abs(gap);
		if (diff <= 3 && diff < bestDiff) {
			best = row.entry;
			bestDiff = diff;
		}
	}
	if (best !== null && typeof best === "object" && !Array.isArray(best)) {
		const b = best;
		const mind = b["mind"] ?? {};
		const emotion = b["emotion"] ?? {};
		const size = b["size"] ?? {};
		const evaluation = b["evaluation"] ?? {};
		const bull = mind["bull"] ?? {};
		const bear = mind["bear"] ?? {};
		const execution = b["execution"] ?? {};
		const condition = b["condition"] ?? {};
		out.decision = {
			planDate: typeof b["plan_date"] === "string" ? b["plan_date"] : typeof b["decided_at"] === "string" ? b["decided_at"].slice(0, 10) : null,
			action: typeof b["action"] === "string" ? b["action"] : null,
			confidence: b["confidence"] == null ? null : Number(b["confidence"]),
			drivenBy: typeof b["driven_by"] === "string" ? b["driven_by"] : null,
			rationale: readableRationale(typeof b["rationale"] === "string" ? b["rationale"] : null),
			bull: typeof bull["summary"] === "string" ? bull["summary"] : null,
			bear: typeof bear["summary"] === "string" ? bear["summary"] : null,
			emotion: typeof emotion["pressure"] === "string" ? emotion["pressure"] : null,
			emotionNote: typeof emotion["note"] === "string" ? emotion["note"] : null,
			execution: typeof execution["status"] === "string" ? execution["status"] : null,
			condition: typeof condition["description"] === "string" ? condition["description"] : null,
			sizeShares: size["shares"] == null ? null : Number(size["shares"]),
			sizePct: size["pct"] == null ? null : Number(size["pct"]),
			plannedPrice: evaluation["execution_price"] != null ? Number(evaluation["execution_price"]) : b["simulated_entry_price"] != null ? Number(b["simulated_entry_price"]) : null,
			source: typeof b["source"] === "string" ? b["source"] : "brief",
			alignment: planFillAlignment(typeof b["action"] === "string" ? b["action"] : null, trade.action)
		};
	}
	const row = books.find((bk) => bk.holdings.some((h) => h.ticker === trade.ticker))?.holdings.find((h) => h.ticker === trade.ticker);
	if (row) out.holdPnl = row.pnlPct;
	return out;
}
/**
* The decision trace data: every real fill as a trace node with its
* soft-paired decision and T+1 verdict, newest first. This is the organic
* view the plugin shows — one list, one spine (real fills), decisions as
* the "why" layer, no parallel tabs.
* @param workspace - desk workspace root.
* @returns `{ trades, rate, rateSource, lastUpdated }` — `trades` is the
*          enriched fill list; `rate` is the USD/HKD FX rate when the desk
*          published one in portfolio.json market_context (else null).
*/
function readTraces(workspace) {
	const { books, trades, lastUpdated, marketContext } = readPortfolio(workspace);
	const byTicker = readBarCloses(workspace, trades.map((t) => t.ticker));
	const decByKey = {};
	const { entries } = readLedger(workspace);
	for (const e of entries) {
		if (e === null || typeof e !== "object" || Array.isArray(e)) continue;
		const eObj = e;
		const subject = eObj["subject"];
		const tk = typeof eObj["ticker"] === "string" ? eObj["ticker"] : subject !== null && subject !== void 0 && typeof subject["ticker"] === "string" ? subject["ticker"] : void 0;
		const dt = typeof eObj["plan_date"] === "string" ? eObj["plan_date"] : typeof eObj["decided_at"] === "string" ? eObj["decided_at"].slice(0, 10) : void 0;
		if (typeof tk !== "string" || typeof dt !== "string" || !dt) continue;
		decByKey[tk + ":" + dt] ??= [];
		decByKey[tk + ":" + dt].push(e);
	}
	const decByTicker = {};
	for (const [key, rows] of Object.entries(decByKey)) {
		const sep = key.lastIndexOf(":");
		const ticker = key.slice(0, sep);
		const entry = rows[rows.length - 1];
		if (entry === void 0) continue;
		(decByTicker[ticker] ??= []).push({
			date: key.slice(sep + 1),
			entry
		});
	}
	return {
		trades: trades.map((t) => enrichTrade(t, byTicker, decByTicker, books)),
		rate: typeof marketContext["usdhk_rate"] === "number" ? marketContext["usdhk_rate"] : null,
		rateSource: typeof marketContext["usdhk_source"] === "string" ? marketContext["usdhk_source"] : null,
		lastUpdated
	};
}
//#endregion
export { T1_FLAT_BAND_PCT, T1_MAX_GAP_DAYS, dayGap, isSellAction, planFillAlignment, readBarCloses, readLedger, readPlans, readPortfolio, readTraces, readableRationale, t1ToneOf, t1VerdictOf };
