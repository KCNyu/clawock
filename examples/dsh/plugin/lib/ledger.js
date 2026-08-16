import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
//#region packages/clawock-dsh/src/ledger.ts
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
		lastUpdated: null
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
		lastUpdated: typeof doc["last_updated"] === "string" ? doc["last_updated"] : null
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
const SNAPSHOT_PATTERN = /^(\d{4}-\d{2}-\d{2})\.json$/;
/** Day number for window arithmetic (no Date TZ pitfalls for ISO dates). */
function dayNum(iso) {
	if (typeof iso !== "string") return null;
	const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
	if (!m) return null;
	return Number(m[1]) * 400 + Number(m[2]) * 32 + Number(m[3]);
}
/**
* Price lookup per ticker across daily snapshots: { ticker: { date: price } }.
* Snapshots carry `current_price` per holding; the newest day with a price
* after a trade date is its T+1 close.
*/
function readSnapshotPrices(workspace) {
	const byTicker = {};
	let files = [];
	try {
		files = readdirSync(join(workspace, "memory", "snapshots"));
	} catch {
		return byTicker;
	}
	for (const name of files) {
		const m = SNAPSHOT_PATTERN.exec(name);
		if (!m) continue;
		const doc = readJson(join(workspace, "memory", "snapshots", name));
		if (doc === null || typeof doc !== "object" || Array.isArray(doc)) continue;
		const portfolios = doc["portfolios"];
		if (portfolios === null || typeof portfolios !== "object" || Array.isArray(portfolios)) continue;
		for (const book of Object.values(portfolios)) {
			if (book === null || typeof book !== "object" || Array.isArray(book)) continue;
			const holdings = book["holdings"];
			if (!Array.isArray(holdings)) continue;
			for (const h of holdings) {
				if (h === null || typeof h !== "object") continue;
				const hObj = h;
				const ticker = hObj["ticker"];
				const price = hObj["current_price"];
				if (typeof ticker === "string" && typeof price === "number") {
					byTicker[ticker] ??= {};
					byTicker[ticker][m[1]] = price;
				}
			}
		}
	}
	return byTicker;
}
/** First close at least `n` trading days after `date` for `ticker`. */
function futureClose(byTicker, ticker, date, n) {
	const days = byTicker[ticker];
	if (!days) return null;
	const base = dayNum(date);
	if (base === null) return null;
	const hit = Object.keys(days).filter((d) => (dayNum(d) ?? 0) > base).sort()[n - 1];
	if (hit === void 0) return null;
	return {
		date: hit,
		price: days[hit]
	};
}
/** One real fill, enriched for the trace view. */
function enrichTrade(trade, byTicker, decByKey, books) {
	const out = {
		...trade,
		holdPnl: null,
		t1: null,
		decision: null
	};
	const t1 = futureClose(byTicker, trade.ticker, trade.date, 1);
	if (t1 !== null && trade.price != null) {
		const delta = (t1.price - trade.price) / trade.price * 100;
		out.t1 = {
			date: t1.date,
			price: Math.round(t1.price * 100) / 100,
			delta: Math.round(delta * 100) / 100,
			verdict: trade.action === "sell" ? delta > 1 ? "卖飞" : delta < -1 ? "卖对" : "持平" : delta > 0 ? "涨" : "跌"
		};
	}
	const prefix = trade.ticker + ":";
	let best = null;
	let bestDiff = 99;
	for (const [k, rows] of Object.entries(decByKey)) {
		if (!k.startsWith(prefix)) continue;
		const dt = k.slice(prefix.length);
		const diff = Math.abs((dayNum(dt) ?? 0) - (dayNum(trade.date) ?? 0));
		if (diff <= 3 && diff < bestDiff) {
			best = rows[rows.length - 1] ?? null;
			bestDiff = diff;
		}
	}
	if (best !== null && typeof best === "object" && !Array.isArray(best)) {
		const b = best;
		b["subject"];
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
			rationale: typeof b["rationale"] === "string" ? b["rationale"] : null,
			bull: typeof bull["summary"] === "string" ? bull["summary"] : null,
			bear: typeof bear["summary"] === "string" ? bear["summary"] : null,
			emotion: typeof emotion["pressure"] === "string" ? emotion["pressure"] : null,
			emotionNote: typeof emotion["note"] === "string" ? emotion["note"] : null,
			execution: typeof execution["status"] === "string" ? execution["status"] : null,
			condition: typeof condition["description"] === "string" ? condition["description"] : null,
			sizeShares: size["shares"] == null ? null : Number(size["shares"]),
			sizePct: size["pct"] == null ? null : Number(size["pct"]),
			plannedPrice: evaluation["execution_price"] != null ? Number(evaluation["execution_price"]) : b["simulated_entry_price"] != null ? Number(b["simulated_entry_price"]) : null,
			source: typeof b["source"] === "string" ? b["source"] : "brief"
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
	const { books, trades, lastUpdated } = readPortfolio(workspace);
	const byTicker = readSnapshotPrices(workspace);
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
	const enriched = trades.map((t) => enrichTrade(t, byTicker, decByKey, books));
	const doc = readJson(join(workspace, "portfolio.json"));
	const marketContext = doc !== null && typeof doc === "object" && !Array.isArray(doc) ? doc["market_context"] ?? {} : {};
	return {
		trades: enriched,
		rate: typeof marketContext["usdhk_rate"] === "number" ? marketContext["usdhk_rate"] : null,
		rateSource: typeof marketContext["usdhk_source"] === "string" ? marketContext["usdhk_source"] : null,
		lastUpdated
	};
}
//#endregion
export { readLedger, readPlans, readPortfolio, readSnapshotPrices, readTraces };
