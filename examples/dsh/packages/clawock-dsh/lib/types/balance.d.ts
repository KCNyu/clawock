/**
 * Provider account balances for the session header chip — official endpoints
 * answered with the SAME keys the harness's adapters use (credentials seam
 * references, falling back to ambient environment variables):
 *
 *   - deepseek: `GET https://api.deepseek.com/user/balance` (money, CNY row)
 *   - minimax:  `GET {base}/v1/token_plan/remains` (Token Plan quota windows;
 *     `base_resp.status_code` is the business verdict — 0 ok, 1004 auth —
 *     and a HTTP-200 body can still be an auth failure)
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
import type { BalanceResult, BalanceSnapshot } from './types.ts';
export declare const DEFAULT_BALANCE_BASE_URL = "https://api.deepseek.com";
export declare const DEFAULT_BALANCE_THRESHOLD = 20;
export declare const DEFAULT_BALANCE_REFRESH_MS = 60000;
export declare const DEFAULT_MINIMAX_BASE_URL = "https://api.minimaxi.com";
export declare const DEFAULT_MINIMAX_LOW_PCT = 20;
export declare const DEFAULT_OPENCLAW_CONFIG_PATH = "/root/.openclaw/openclaw.json";
export declare const DEFAULT_CLAUDE_CREDENTIALS_PATH = "/root/.claude/.credentials.json";
export declare const DEFAULT_CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage";
export declare const DEFAULT_CLAUDE_LOW_PCT = 20;
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
    /** Red dot when a quota window's remaining percent drops to/below this. */
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
    /** Red dot when the session window's remaining percent drops to/below this. */
    lowPct?: number;
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
/** The credentials capability, narrowed to what this service uses. */
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
/** One model_remains bucket, as far as this service reads it. */
export interface MinimaxRemainsEntry {
    model?: string;
    current_interval_remaining_percent?: number;
    current_interval_total_count?: number;
    current_interval_usage_count?: number;
    current_weekly_remaining_percent?: number;
    end_time?: number;
    [key: string]: unknown;
}
/**
 * Remaining percent of one quota window: the explicit percent field when the
 * plan reports one, otherwise derived from total/used counts (MiniMax ships
 * both shapes across plan generations). null = unreadable, never guessed.
 */
export declare function windowRemainingPercent(entry: MinimaxRemainsEntry): number | null;
/**
 * Reset stamps the panel can lay out: within 48h a bare local clock,
 * farther out the weekday comes along ('周四 21:00'). Accepts epoch seconds,
 * epoch milliseconds and RFC3339 strings — MiniMax sends epochs while
 * Claude sends ISO.
 */
export declare function formatReset(epochOrIso: number | string | null | undefined): string;
/**
 * The successful Token Plan payload → snapshot. Percent-based by design:
 * plans report either percent fields or raw counts, and tokens are not money
 * — the chip reads "还剩多少窗口额度", never a fabricated ¥ figure.
 */
export declare function parseMinimaxRemains(body: unknown, asOf: string): BalanceSnapshot;
/** Tolerant JSON file read: missing/unreadable/invalid all yield undefined. */
export declare function readJsonFile(path: string): Record<string, unknown> | undefined;
/** DeepSeek row: official money balance, CNY entry preferred. */
export declare function createBalanceService(deps: {
    credentials: BalanceCredentials;
}, config?: BalanceConfig): {
    get(force: boolean): Promise<BalanceResult>;
};
/** MiniMax row: official Token Plan quota windows, percent-based. */
export declare function createMinimaxService(deps: {
    credentials: BalanceCredentials;
}, config?: MinimaxConfig): {
    get(force: boolean): Promise<BalanceResult>;
};
/** Claude Code's stored OAuth identity — token plus the plan it belongs to. */
interface ClaudeCredentials {
    accessToken?: string;
    refreshToken?: string;
    expiresAt?: number;
    subscriptionType?: string;
    rateLimitTier?: string;
}
/** One usage window: utilization is the % already consumed (0-100). */
export interface ClaudeUsageWindow {
    utilization?: number;
    resets_at?: string;
}
/**
 * Read Claude Code's OAuth credentials. The file belongs to Claude Code —
 * this service only READS it; rotating/refreshing stays their job, so an
 * expired token surfaces as a failed row telling kcn to run claude once.
 */
export declare function readClaudeCredentials(path: string): {
    creds: ClaudeCredentials;
} | undefined;
/**
 * Successful usage payload → snapshot, in REMAINING percent (utilization is
 * consumption). five_hour gates active sessions so it is the headline; any
 * bucket may be absent/null depending on plan.
 */
export declare function parseClaudeUsage(body: unknown, asOf: string): BalanceSnapshot;
/** Claude row: subscription rate-limit windows via the OAuth usage endpoint. */
export declare function createClaudeService(deps: {
    credentials: BalanceCredentials;
}, config?: ClaudeConfig): {
    get(force: boolean): Promise<BalanceResult>;
};
export {};
