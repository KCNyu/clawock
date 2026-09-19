/**
 * Provider account balances for the session header chip — official endpoints
 * answered with the SAME keys the harness's adapters use (credentials seam
 * references, falling back to ambient environment variables):
 *
 *   - deepseek: `GET https://api.deepseek.com/user/balance` (money, CNY row)
 *   - minimax:  `GET {base}/v1/token_plan/remains` (Token Plan quota windows;
 *     `base_resp.status_code` is the business verdict — 0 ok, 1004 auth —
 *     and a HTTP-200 body can still be an auth failure)
 *   - claude:   `GET /api/oauth/usage` (subscription windows)
 *   - codex:    official `codex app-server` JSON-RPC
 *     `account/rateLimits/read` (ChatGPT subscription quota windows)
 *
 * Every quota provider is reduced to the same shape before it leaves this
 * file: a list of windows built by `quotaWindow` (label derived from the
 * window's length, one reset-stamp format) and a snapshot built by
 * `quotaSnapshot` (one note wording, one availability rule, one low rule).
 * The parsers below only translate each vendor's field names — they used to
 * each spell labels, notes and reset clocks their own way, which is how the
 * same 5-hour window read '5h' on one row and '会话' on the next.
 *
 * One cache per provider, one source of truth: the gateway instance owns
 * them, so a stale read, a failed refresh and a rotated key all resolve
 * against the same object. Upstream is hit at most once per TTL window
 * unless the client forces a refresh; a failed refresh keeps the last good
 * snapshot and reports 'stale' instead of dropping a real number for a
 * transient 429. Keys are never logged, shipped, or stored anywhere here.
 *
 * All error reporting is in-band: `get()` never throws — statuses
 * 'no-key' / 'failed' / 'stale' carry a Chinese `message` the view renders
 * verbatim.
 */
import type { BalanceResult, BalanceSnapshot, BalanceWindow } from './types.ts';
export declare const DEFAULT_BALANCE_BASE_URL = "https://api.deepseek.com";
export declare const DEFAULT_BALANCE_THRESHOLD = 20;
export declare const DEFAULT_BALANCE_REFRESH_MS = 60000;
export declare const DEFAULT_MINIMAX_BASE_URL = "https://api.minimaxi.com";
export declare const DEFAULT_MINIMAX_LOW_PCT = 20;
/**
 * The three file-backed defaults hang off the ACTIVE user's home, never a
 * literal `/root/...`. This package is published to npm, so an absolute home
 * directory would ship one machine's layout as everyone's default (and would
 * read the wrong account under another uid). Each path stays overridable from
 * the profile row (see cordis.patch.yml); on this root-owned host they resolve
 * to exactly the previous literals.
 */
export declare const DEFAULT_OPENCLAW_CONFIG_PATH: string;
export declare const DEFAULT_CLAUDE_CREDENTIALS_PATH: string;
export declare const DEFAULT_CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage";
export declare const DEFAULT_CLAUDE_LOW_PCT = 20;
export declare const DEFAULT_CODEX_COMMAND: string;
export declare const DEFAULT_CODEX_LOW_PCT = 20;
export declare const DEFAULT_CODEX_REFRESH_MS = 300000;
/**
 * Expand one leading `~` in a configured path. The defaults above are already
 * home-relative, and the profile row is hand-written YAML, so `~/.claude/...`
 * is the form a user naturally writes for an override — without this it would
 * be taken literally and read as a file named `~`. Only a leading `~` followed
 * by `/` or the end of the string expands; a `~` inside a path is a real name
 * and is left alone. Exported because the behaviour is worth pinning in tests.
 */
export declare function expandHome(value: string): string;
/** The credentials capability, narrowed to what these services use. */
export interface BalanceCredentials {
    resolve(ref: string): Promise<{
        value: string;
    } | undefined>;
}
export interface BalanceConfig {
    /** DeepSeek upstream base; the service appends /user/balance. */
    baseUrl?: string;
    /** Red-dot threshold in the displayed entry's currency (CNY/USD units). */
    threshold?: number;
    /** Suggested client poll interval in ms. */
    refreshMs?: number;
}
export interface MinimaxConfig {
    /** Upstream base; the service appends /v1/token_plan/remains. */
    baseUrl?: string;
    /** Credentials seam reference for the MiniMax key (env fallback same name). */
    keyRef?: string;
    /**
     * Red dot watermark in REMAINING terms: warn when a quota window's
     * remaining percent has fallen to/below this (default 20). The chip
     * displays the used direction (≥ `100 - lowPct`% used), but the config
     * keeps its original meaning so existing values stay valid.
     */
    lowPct?: number;
    /**
     * openclaw gateway config to fall back to when the seam and env are both
     * unset — kcn keeps provider keys at models.providers.<name>.apiKey there.
     */
    openclawConfigPath?: string;
}
export interface ClaudeConfig {
    /** Claude Code's OAuth credentials file (claudeAiOauth.accessToken). */
    credentialsPath?: string;
    /** The undocumented /api/oauth/usage endpoint; overridable for tests. */
    usageUrl?: string;
    /** Red dot watermark in REMAINING terms (default 20, i.e. ≥80% used). */
    lowPct?: number;
}
export interface CodexConfig {
    /** Codex CLI executable that owns ChatGPT auth and the app-server protocol. */
    command?: string;
    /** Red dot watermark in remaining terms (default 20 = ≥80% used). */
    lowPct?: number;
    /** Codex app-server polling cadence; slower than HTTP-only providers by default. */
    refreshMs?: number;
}
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
export declare const DEEPSEEK_KEY_REF = "DEEPSEEK_API_KEY";
/** Same seam discipline for MiniMax: the harness's MiniMax adapter's ref. */
export declare const MINIMAX_KEY_REF = "MINIMAX_API_KEY";
/** One balance_infos entry, as far as this service reads it. */
export interface BalanceInfoEntry {
    currency?: string;
    total_balance?: string;
    granted_balance?: string;
    topped_up_balance?: string;
}
/**
 * Pick the CNY entry case-insensitively; fall back to the first entry when
 * the account has no CNY row. Mirrors upstream DeepSeekMonitorWindows'
 * eq_ignore_ascii_case.
 */
export declare function pickCnyBalanceInfo(infos: readonly BalanceInfoEntry[] | undefined): BalanceInfoEntry | undefined;
/**
 * Tolerant parse: a missing field degrades to '' / false rather than throwing,
 * so a shape drift upstream reads as an empty box, never as a crashed tab.
 */
export declare function parseBalancePayload(body: unknown, asOf: string): BalanceSnapshot;
/** Epoch seconds, epoch milliseconds or an RFC3339 string → epoch ms; null when unreadable. */
export declare function toEpochMs(value: number | string | null | undefined): number | null;
/**
 * The single reset-stamp format, same for every provider and every window:
 * '今天 21:00' / '明天 09:00' when it lands within the next calendar day,
 * otherwise the full date '9/20 周日 20:00'. A weekly reset used to read just
 * '周日 20:00' — with no date, a week-long window's reset could be this
 * Sunday or the next, and it said nothing about which.
 */
export declare function formatReset(value: number | string | null | undefined, now?: number): string;
/** A window's label from its length: 300 → '5h', 10080 → '周', 1440 → '1天'. */
export declare function windowLabel(durationMins: number | null, fallback: string): string;
/** What a provider parser knows about one window, in its own units. */
export interface QuotaWindowInput {
    /** Used percent (0-100); null when the plan does not report it this cycle. */
    usedPercent: number | null;
    /** Window length in minutes, when the vendor says (or it can be derived). */
    durationMins: number | null;
    /** When the window frees up: epoch s/ms or RFC3339. */
    resetsAt: number | string | null | undefined;
    /** Label to use when the length is unknown ('5h' / '周'). */
    fallbackLabel: string;
}
/** One vendor window → the wire window, or null when it carries no reading. */
export declare function quotaWindow(input: QuotaWindowInput, now?: number): BalanceWindow | null;
/**
 * Readable windows → the quota snapshot. The headline is the first window;
 * the note reads every window the same way ('5h 已用 12%,今天 21:00 重置');
 * a quota account is available only while no window is exhausted, unless the
 * vendor states availability itself (`isAvailable`).
 */
export declare function quotaSnapshot(windows: readonly (BalanceWindow | null)[], asOf: string, options?: {
    isAvailable?: boolean;
    extraNotes?: readonly string[];
}): BalanceSnapshot;
/**
 * The shared low rule for quota rows. `lowPct` keeps its original 「剩余水位」
 * meaning (warn when remaining ≤ lowPct), which in the used direction is any
 * window at ≥ 100 − lowPct — the weekly window counts as much as the short
 * one, because an exhausted week blocks work just as surely.
 */
export declare function quotaIsLow(snapshot: BalanceSnapshot, lowPct: number): boolean;
/** One model_remains bucket, as far as this service reads it. */
export interface MinimaxRemainsEntry {
    /** Bucket name. The live API calls it `model_name`; older payloads `model`. */
    model_name?: string;
    model?: string;
    start_time?: number;
    end_time?: number;
    current_interval_remaining_percent?: number;
    current_interval_total_count?: number;
    current_interval_usage_count?: number;
    weekly_start_time?: number;
    weekly_end_time?: number;
    current_weekly_remaining_percent?: number;
    current_weekly_total_count?: number;
    current_weekly_usage_count?: number;
    [key: string]: unknown;
}
/** The interval window's used percent (kept exported: the tests pin both shapes). */
export declare function windowUsedPercent(entry: MinimaxRemainsEntry): number | null;
/**
 * The successful Token Plan payload → snapshot. Percent-based by design:
 * tokens are not money — the chip reads "窗口额度用了多少", never a ¥ figure.
 */
export declare function parseMinimaxRemains(body: unknown, asOf: string, now?: number): BalanceSnapshot;
/** One usage window: utilization is the % already consumed (0-100). */
export interface ClaudeUsageWindow {
    utilization?: number;
    resets_at?: string | null;
}
/**
 * Successful usage payload → snapshot. utilization already IS consumption,
 * so it passes through untouched; any bucket may be absent/null by plan.
 */
export declare function parseClaudeUsage(body: unknown, asOf: string, now?: number): BalanceSnapshot;
/** One Codex app-server quota window (`account/rateLimits/read`). */
export interface CodexRateLimitWindow {
    usedPercent?: number;
    windowDurationMins?: number | null;
    resetsAt?: number | null;
}
/** Official app-server response → the chip's used-percent snapshot. */
export declare function parseCodexRateLimits(body: unknown, asOf: string, now?: number): BalanceSnapshot;
export type BalanceService = {
    get(force: boolean): Promise<BalanceResult>;
};
/** Tolerant JSON file read: missing/unreadable/invalid all yield undefined. */
export declare function readJsonFile(path: string): Record<string, unknown> | undefined;
/** DeepSeek row: official money balance, CNY entry preferred. */
export declare function createBalanceService(deps: {
    credentials: BalanceCredentials;
}, config?: BalanceConfig): BalanceService;
/** MiniMax row: official Token Plan quota windows, percent-based. */
export declare function createMinimaxService(deps: {
    credentials: BalanceCredentials;
}, config?: MinimaxConfig): BalanceService;
/**
 * Ask Codex itself for ChatGPT limits. The CLI owns auth and refresh; this
 * plugin never reads or forwards tokens. One short-lived JSONL app-server is
 * cheaper and safer than duplicating Codex's private HTTP/auth behavior.
 */
export declare function readCodexRateLimits(command: string, timeoutMs?: number): Promise<unknown>;
/** Codex row: ChatGPT subscription quota through the official app-server. */
export declare function createCodexService(deps: {
    credentials: BalanceCredentials;
}, config?: CodexConfig): BalanceService;
/** Claude Code's stored OAuth identity — token plus the plan it belongs to. */
interface ClaudeCredentials {
    accessToken?: string;
    refreshToken?: string;
    expiresAt?: number;
    subscriptionType?: string;
    rateLimitTier?: string;
}
/**
 * Read Claude Code's OAuth credentials. The file belongs to Claude Code —
 * this service only READS it; rotating/refreshing stays their job, so an
 * expired token surfaces as a failed row telling kcn to run claude once.
 */
export declare function readClaudeCredentials(path: string): {
    creds: ClaudeCredentials;
} | undefined;
/** Claude row: subscription rate-limit windows via the OAuth usage endpoint. */
export declare function createClaudeService(deps: {
    credentials: BalanceCredentials;
}, config?: ClaudeConfig): BalanceService;
export {};
