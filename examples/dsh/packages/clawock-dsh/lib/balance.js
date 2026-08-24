import { readFileSync } from "node:fs";
//#region src/balance.ts
const DEFAULT_BALANCE_BASE_URL = "https://api.deepseek.com";
const DEFAULT_BALANCE_THRESHOLD = 20;
const DEFAULT_BALANCE_REFRESH_MS = 6e4;
const DEFAULT_MINIMAX_BASE_URL = "https://api.minimaxi.com";
const DEFAULT_MINIMAX_LOW_PCT = 20;
const DEFAULT_OPENCLAW_CONFIG_PATH = "/root/.openclaw/openclaw.json";
const DEFAULT_CLAUDE_CREDENTIALS_PATH = "/root/.claude/.credentials.json";
const DEFAULT_CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage";
const DEFAULT_CLAUDE_LOW_PCT = 20;
const TTL_MS = 6e4;
const TIMEOUT_MS = 15e3;
/**
* The credentials seam reference the official DeepSeek adapter resolves.
* A plain string on purpose, not credentialRef(): the branding helper is a
* no-op at runtime, and importing @deepseek-ai/dsh-credentials would drag its
* cordis Events augmentation into the typert analysis — which registers this
* package in the host face with zero discoverable services (the protocol
* lives in node_modules, where the generator's symbol checks cannot see it)
* and fails the "publishes Remote artifacts" gate. The seam itself resolves
* by name, so the reference needs no import to work.
*/
/**
* The credentials seam reference the official DeepSeek adapter resolves.
* A plain string on purpose, not credentialRef(): the branding helper is a
* no-op at runtime, and importing @deepseek-ai/dsh-credentials would drag its
* cordis Events augmentation into the typert analysis — which registers this
* package in the host face with zero discoverable services (the protocol
* lives in node_modules, where the generator's symbol checks cannot see it)
* and fails the "publishes Remote artifacts" gate. The seam itself resolves
* by name, so the reference needs no import to work.
*/
const DEEPSEEK_KEY_REF = "DEEPSEEK_API_KEY";
/** Same seam discipline for MiniMax: the harness's MiniMax adapter's ref. */
const MINIMAX_KEY_REF = "MINIMAX_API_KEY";
/**
* Pick the CNY entry case-insensitively; fall back to the first entry when
* the account has no CNY row. Mirrors upstream DeepSeekMonitorWindows'
* eq_ignore_ascii_case.
*/
function pickCnyBalanceInfo(infos) {
	if (!Array.isArray(infos) || infos.length === 0) return void 0;
	return infos.find((entry) => (entry.currency ?? "").toUpperCase() === "CNY") ?? infos[0];
}
/**
* Tolerant parse: a missing field degrades to '' / false rather than throwing,
* so a shape drift upstream reads as an empty box, never as a crashed tab.
*/
function parseBalancePayload(body, asOf) {
	const raw = typeof body === "object" && body !== null ? body : {};
	const entry = pickCnyBalanceInfo(raw.balance_infos);
	return {
		isAvailable: raw.is_available === true,
		unit: "money",
		currency: typeof entry?.currency === "string" ? entry.currency : "",
		totalBalance: typeof entry?.total_balance === "string" ? entry.total_balance : "",
		grantedBalance: typeof entry?.granted_balance === "string" ? entry.granted_balance : "",
		toppedUpBalance: typeof entry?.topped_up_balance === "string" ? entry.topped_up_balance : "",
		asOf,
		note: "",
		windows: []
	};
}
const finiteNumber = (value) => typeof value === "number" && isFinite(value) ? value : null;
/**
* Used percent of one quota window — the chip's display direction (kcn:
* 「已使用」比「剩余」直观). The explicit percent field reports REMAINING and
* is complemented here; raw counts are already consumption and divide as-is
* (MiniMax ships both shapes across plan generations). null = unreadable,
* never guessed.
*/
function windowUsedPercent(entry) {
	const direct = finiteNumber(entry.current_interval_remaining_percent);
	if (direct !== null) return Math.min(100, Math.max(0, 100 - direct));
	const total = finiteNumber(entry.current_interval_total_count);
	const used = finiteNumber(entry.current_interval_usage_count);
	if (total !== null && total > 0 && used !== null && used >= 0) return Math.min(100, Math.max(0, used / total * 100));
	return null;
}
/**
* Reset stamps the panel can lay out: within 48h a bare local clock,
* farther out the weekday comes along ('周四 21:00'). Accepts epoch seconds,
* epoch milliseconds and RFC3339 strings — MiniMax sends epochs while
* Claude sends ISO.
*/
function formatReset(epochOrIso) {
	let ms = null;
	if (typeof epochOrIso === "number" && isFinite(epochOrIso) && epochOrIso > 0) ms = epochOrIso > 0xe8d4a51000 ? epochOrIso : epochOrIso * 1e3;
	else if (typeof epochOrIso === "string" && epochOrIso !== "") {
		const at = new Date(epochOrIso);
		if (!isNaN(at.getTime())) ms = at.getTime();
	}
	if (ms === null) return "";
	const at = new Date(ms);
	const hhmm = String(at.getHours()).padStart(2, "0") + ":" + String(at.getMinutes()).padStart(2, "0");
	if (at.getTime() - Date.now() < 1728e5) return hhmm;
	return [
		"周日",
		"周一",
		"周二",
		"周三",
		"周四",
		"周五",
		"周六"
	][at.getDay()] + " " + hhmm;
}
/**
* The successful Token Plan payload → snapshot. Percent-based by design:
* plans report either percent fields or raw counts, and tokens are not money
* — the chip reads "窗口额度用了多少"(已使用方向), never a fabricated ¥ figure.
*/
function parseMinimaxRemains(body, asOf) {
	const raw = typeof body === "object" && body !== null ? body : {};
	const buckets = Array.isArray(raw.model_remains) ? raw.model_remains : [];
	const entry = buckets.find((b) => b.model === "general") ?? buckets[0];
	if (entry === void 0) throw new Error("MiniMax 响应里没有 model_remains 数据");
	const used = windowUsedPercent(entry);
	const weeklyRemaining = finiteNumber(entry.current_weekly_remaining_percent);
	const weeklyUsed = weeklyRemaining === null ? null : Math.min(100, Math.max(0, 100 - weeklyRemaining));
	const windows = [];
	if (used !== null) windows.push({
		label: "5h",
		percent: Math.round(used),
		resetAt: formatReset(entry.end_time)
	});
	if (weeklyUsed !== null) windows.push({
		label: "周",
		percent: Math.round(weeklyUsed),
		resetAt: formatReset(entry.weekly_end_time)
	});
	const notes = [];
	if (used !== null) notes.push("5h 窗口已使用 " + Math.round(used) + "%");
	if (weeklyUsed !== null) notes.push("周窗口已使用 " + Math.round(weeklyUsed) + "%");
	return {
		isAvailable: used !== null && used < 100,
		unit: "pct",
		currency: "",
		totalBalance: used === null ? "" : String(Math.round(used)),
		grantedBalance: "",
		toppedUpBalance: "",
		asOf,
		note: notes.join(" · "),
		windows
	};
}
/** Seam reference first, then the ambient environment variable of the same name. */
function resolveSeamThenEnv(deps, ref) {
	return async () => {
		const resolved = await deps.credentials.resolve(ref);
		if (resolved !== void 0 && typeof resolved.value === "string" && resolved.value !== "") return resolved.value;
		const ambient = process.env[ref];
		return ambient !== void 0 && ambient !== "" ? ambient : void 0;
	};
}
/** Tolerant JSON file read: missing/unreadable/invalid all yield undefined. */
function readJsonFile(path) {
	try {
		const parsed = JSON.parse(readFileSync(path, "utf8"));
		return typeof parsed === "object" && parsed !== null ? parsed : void 0;
	} catch {
		return;
	}
}
/** kcn keeps provider keys in the openclaw gateway config at this pointer. */
function readOpenclawProviderKey(configPath, provider) {
	const key = (((readJsonFile(configPath)?.models ?? {}).providers ?? {})[provider] ?? {}).apiKey;
	return typeof key === "string" && key !== "" ? key : void 0;
}
function createQuotaService(deps, spec) {
	let snapshot = null;
	let fetchedAt = 0;
	let inFlight = null;
	const resolveKey = async () => spec.resolveApiKey(deps);
	const run = async (apiKey) => {
		try {
			snapshot = await spec.fetchFresh(apiKey);
			fetchedAt = Date.now();
			return {
				configured: true,
				snapshot,
				status: "fresh",
				low: spec.isLow(snapshot),
				message: null,
				threshold: spec.threshold,
				refreshMs: spec.refreshMs
			};
		} catch (cause) {
			const message = cause instanceof Error ? cause.message : String(cause);
			if (snapshot !== null) return {
				configured: true,
				snapshot,
				status: "stale",
				low: spec.isLow(snapshot),
				message,
				threshold: spec.threshold,
				refreshMs: spec.refreshMs
			};
			return {
				configured: true,
				snapshot: null,
				status: "failed",
				low: false,
				message,
				threshold: spec.threshold,
				refreshMs: spec.refreshMs
			};
		}
	};
	const exec = async (force) => {
		const apiKey = await resolveKey();
		if (apiKey === void 0) return {
			configured: false,
			snapshot: null,
			status: "no-key",
			low: false,
			message: spec.noKeyMessage,
			threshold: spec.threshold,
			refreshMs: spec.refreshMs
		};
		if (!force && snapshot !== null && Date.now() - fetchedAt < TTL_MS) return {
			configured: true,
			snapshot,
			status: "cached",
			low: spec.isLow(snapshot),
			message: null,
			threshold: spec.threshold,
			refreshMs: spec.refreshMs
		};
		return run(apiKey);
	};
	return { 
	/**
	* Cached-or-fetch read. A concurrent caller (a poll tick racing a manual
	* click) JOINS the in-flight run instead of stampeding the upstream —
	* one request per window, however many faces ask.
	*/
async get(force) {
		if (inFlight !== null) return inFlight;
		const pending = exec(force);
		inFlight = pending;
		try {
			return await pending;
		} finally {
			inFlight = null;
		}
	} };
}
const numOrInfinity = (value) => {
	const parsed = Number.parseFloat(value);
	return isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY;
};
/**
* The snapshot's used-percent reading, or null when it isn't a percent unit
* or carries no parseable number. The null guard is the point: under the old
* REMAINING direction an unreadable value read as +∞ and safely missed the
* watermark; under USED that same +∞ would read as "everything consumed" and
* light every red dot. An absent reading must stay silent.
*/
function usedPercentOf(snapshot) {
	if (snapshot.unit !== "pct") return null;
	const parsed = Number.parseFloat(snapshot.totalBalance);
	return isFinite(parsed) ? parsed : null;
}
/** DeepSeek row: official money balance, CNY entry preferred. */
function createBalanceService(deps, config = {}) {
	const baseUrl = config.baseUrl ?? "https://api.deepseek.com";
	const threshold = typeof config.threshold === "number" && isFinite(config.threshold) ? config.threshold : 20;
	return createQuotaService(deps, {
		resolveApiKey: resolveSeamThenEnv(deps, DEEPSEEK_KEY_REF),
		noKeyMessage: "未配置 DeepSeek API Key(设置 → 模型 → DeepSeek)",
		threshold,
		refreshMs: typeof config.refreshMs === "number" && isFinite(config.refreshMs) ? config.refreshMs : DEFAULT_BALANCE_REFRESH_MS,
		async fetchFresh(apiKey) {
			let response;
			try {
				response = await fetch(`${baseUrl}/user/balance`, {
					headers: {
						authorization: `Bearer ${apiKey}`,
						accept: "application/json"
					},
					signal: AbortSignal.timeout(TIMEOUT_MS)
				});
			} catch (cause) {
				throw new Error(`网络请求失败:${cause instanceof Error ? cause.message : String(cause)}`);
			}
			if (response.status === 401) throw new Error("API Key 无效或已过期");
			if (response.status === 429) throw new Error("请求过于频繁,请稍后再试");
			if (!response.ok) throw new Error(`余额接口返回 HTTP ${response.status}`);
			let body;
			try {
				body = await response.json();
			} catch {
				throw new Error("解析余额数据失败");
			}
			return parseBalancePayload(body, (/* @__PURE__ */ new Date()).toISOString());
		},
		isLow: (snapshot) => snapshot.unit === "money" && snapshot.isAvailable && numOrInfinity(snapshot.totalBalance) <= threshold
	});
}
/** MiniMax row: official Token Plan quota windows, percent-based. */
function createMinimaxService(deps, config = {}) {
	const baseUrl = config.baseUrl ?? "https://api.minimaxi.com";
	const lowPct = typeof config.lowPct === "number" && isFinite(config.lowPct) ? config.lowPct : 20;
	const seamEnv = resolveSeamThenEnv(deps, config.keyRef ?? "MINIMAX_API_KEY");
	const openclawPath = config.openclawConfigPath ?? "/root/.openclaw/openclaw.json";
	return createQuotaService(deps, {
		resolveApiKey: async () => await seamEnv() ?? readOpenclawProviderKey(openclawPath, "minimax"),
		noKeyMessage: "未配置 MiniMax API Key(凭据缝 / 环境变量 / openclaw 配置均无)",
		threshold: lowPct,
		refreshMs: DEFAULT_BALANCE_REFRESH_MS,
		async fetchFresh(apiKey) {
			let response;
			try {
				response = await fetch(`${baseUrl}/v1/token_plan/remains`, {
					headers: {
						authorization: `Bearer ${apiKey}`,
						accept: "application/json"
					},
					signal: AbortSignal.timeout(TIMEOUT_MS)
				});
			} catch (cause) {
				throw new Error(`网络请求失败:${cause instanceof Error ? cause.message : String(cause)}`);
			}
			if (!response.ok) throw new Error(`MiniMax 接口返回 HTTP ${response.status}`);
			let body;
			try {
				body = await response.json();
			} catch {
				throw new Error("解析 MiniMax 数据失败");
			}
			const raw = typeof body === "object" && body !== null ? body : {};
			const code = raw.base_resp?.status_code;
			if (code !== void 0 && code !== 0) {
				const msg = typeof raw.base_resp?.status_msg === "string" && raw.base_resp.status_msg !== "" ? raw.base_resp.status_msg : `错误码 ${code}`;
				throw new Error(code === 1004 ? `MiniMax API Key 无效或已过期(${msg})` : `MiniMax 接口错误:${msg}`);
			}
			return parseMinimaxRemains(body, (/* @__PURE__ */ new Date()).toISOString());
		},
		isLow: (snapshot) => {
			const used = usedPercentOf(snapshot);
			return used !== null && used >= 100 - lowPct;
		}
	});
}
/**
* Read Claude Code's OAuth credentials. The file belongs to Claude Code —
* this service only READS it; rotating/refreshing stays their job, so an
* expired token surfaces as a failed row telling kcn to run claude once.
*/
function readClaudeCredentials(path) {
	const creds = readJsonFile(path)?.claudeAiOauth;
	if (creds === void 0 || typeof creds !== "object") return void 0;
	return { creds };
}
/**
* Successful usage payload → snapshot, in USED percent — utilization already
* IS consumption, so it renders verbatim with no complementing (kcn:
* 「已使用」比「剩余」直观). five_hour gates active sessions so it is the
* headline; any bucket may be absent/null depending on plan.
*/
function parseClaudeUsage(body, asOf) {
	const raw = typeof body === "object" && body !== null ? body : {};
	const u5 = finiteNumber(raw.five_hour?.utilization);
	const u7 = finiteNumber(raw.seven_day?.utilization);
	if (u5 === null && u7 === null) throw new Error("Claude 响应里没有可用的用量窗口");
	const used = u5 === null ? null : Math.round(Math.min(100, Math.max(0, u5)));
	const windows = [];
	if (u5 !== null) windows.push({
		label: "会话",
		percent: used,
		resetAt: formatReset(raw.five_hour?.resets_at ?? null)
	});
	if (u7 !== null) windows.push({
		label: "本周",
		percent: Math.round(Math.min(100, Math.max(0, u7))),
		resetAt: formatReset(raw.seven_day?.resets_at ?? null)
	});
	const notes = [];
	if (u5 !== null) notes.push("会话窗口已使用 " + used + "%");
	if (u7 !== null) notes.push("本周已使用 " + Math.round(u7) + "%");
	const extraUtil = raw.extra_usage?.is_enabled === true ? finiteNumber(raw.extra_usage?.utilization ?? void 0) : null;
	if (extraUtil !== null) notes.push("附加额度已用 " + Math.round(extraUtil) + "%");
	return {
		isAvailable: used === null ? false : used < 100,
		unit: "pct",
		currency: "",
		totalBalance: used === null ? "" : String(used),
		grantedBalance: "",
		toppedUpBalance: "",
		asOf,
		note: notes.join(" · "),
		windows
	};
}
/** Claude row: subscription rate-limit windows via the OAuth usage endpoint. */
function createClaudeService(deps, config = {}) {
	const credentialsPath = config.credentialsPath ?? "/root/.claude/.credentials.json";
	const usageUrl = config.usageUrl ?? "https://api.anthropic.com/api/oauth/usage";
	const lowPct = typeof config.lowPct === "number" && isFinite(config.lowPct) ? config.lowPct : 20;
	return createQuotaService(deps, {
		resolveApiKey: async () => readClaudeCredentials(credentialsPath)?.creds.accessToken,
		noKeyMessage: "未找到 Claude 登录(~/.claude/.credentials.json)",
		threshold: lowPct,
		refreshMs: DEFAULT_BALANCE_REFRESH_MS,
		async fetchFresh() {
			const entry = readClaudeCredentials(credentialsPath);
			if (entry === void 0) throw new Error("Claude 登录文件不存在或已损坏");
			const { creds } = entry;
			if (typeof creds.accessToken !== "string" || creds.accessToken === "") throw new Error("Claude 登录文件里没有 accessToken");
			if (typeof creds.expiresAt === "number" && Date.now() > creds.expiresAt) throw new Error("Claude 登录已过期,请在终端跑一次 claude 刷新登录");
			let response;
			try {
				response = await fetch(usageUrl, {
					headers: {
						authorization: `Bearer ${creds.accessToken}`,
						accept: "application/json",
						"anthropic-beta": "oauth-2025-04-20"
					},
					signal: AbortSignal.timeout(TIMEOUT_MS)
				});
			} catch (cause) {
				throw new Error(`网络请求失败:${cause instanceof Error ? cause.message : String(cause)}`);
			}
			if (response.status === 401 || response.status === 403) throw new Error("Claude 登录无效或已过期");
			if (response.status === 429) throw new Error("请求过于频繁,请稍后再试");
			if (!response.ok) throw new Error(`Claude 用量接口返回 HTTP ${response.status}`);
			let body;
			try {
				body = await response.json();
			} catch {
				throw new Error("解析 Claude 数据失败");
			}
			return parseClaudeUsage(body, (/* @__PURE__ */ new Date()).toISOString());
		},
		isLow: (snapshot) => {
			const used = usedPercentOf(snapshot);
			return used !== null && used >= 100 - lowPct;
		}
	});
}
//#endregion
export { DEEPSEEK_KEY_REF, DEFAULT_BALANCE_BASE_URL, DEFAULT_BALANCE_REFRESH_MS, DEFAULT_BALANCE_THRESHOLD, DEFAULT_CLAUDE_CREDENTIALS_PATH, DEFAULT_CLAUDE_LOW_PCT, DEFAULT_CLAUDE_USAGE_URL, DEFAULT_MINIMAX_BASE_URL, DEFAULT_MINIMAX_LOW_PCT, DEFAULT_OPENCLAW_CONFIG_PATH, MINIMAX_KEY_REF, createBalanceService, createClaudeService, createMinimaxService, formatReset, parseBalancePayload, parseClaudeUsage, parseMinimaxRemains, pickCnyBalanceInfo, readClaudeCredentials, readJsonFile, windowUsedPercent };
