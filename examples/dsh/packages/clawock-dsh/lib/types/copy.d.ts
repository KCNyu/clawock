/**
 * The plugin's copy and the few formatters every surface shares: the zh/en
 * dictionaries, the translator, and how a quota window's length and reset
 * read in the active locale. No React and no DOM, so the browser panel and the
 * text rendering of the same panel (text.ts) say the same words.
 */
import type { BalanceResult } from './types.ts';
/** Dictionary namespace declared by every registration in this bundle. */
export declare const LOCALE_NS = "clawock";
/**
 * Translate one dictionary key with optional `{name}` params. Hand-declared
 * rather than derived from the host's `TranslateNS<NS>`: that type needs the
 * `LocaleNamespaceMap` merge the locale plugin owns, and this file's rule is to
 * hand-declare what cannot be derived without a cross-plugin type import (the
 * same reason `sessionId` is declared, not derived).
 */
export type Translate = (key: string, params?: Record<string, unknown>) => string;
/**
 * This plugin's copy, in the locales the browser client ships (`zh`, `en` —
 * `dsh-client-locale`'s LOCALE_IDS). Keys are grouped by surface; the two
 * dictionaries must carry the same key set, which `tests/decision_studio_plugin.spec.js`
 * enforces so a missing translation cannot ship.
 */
export declare const dictionaries: Record<string, Record<string, string>>;
/**
 * Bind a dictionary to a lookup shaped exactly like the host's `t` seat, with
 * `{name}` interpolation. The host supplies the real one through the slot
 * registration (`locale: LOCALE_NS`); this factory exists so a render can be
 * exercised without a locale service — the same seam the tests use.
 */
export declare function createTranslator(dict: Record<string, string>): Translate;
/**
 * Window length in minutes → the label in the active locale, host string as
 * fallback. The structured fields are typed `| null` but read `== null`: a
 * host that predates them omits the key entirely, so the value that actually
 * arrives is `undefined`. Checking only for null rendered `NaN m` against a
 * previous-version host — the exact half-deployed case this fallback exists
 * for, caught by the projection test rather than in the browser.
 */
export declare function windowLabelOf(t: Translate, window: {
    label: string;
    durationMins?: number | null;
}): string;
/** The reset instant → the stamp in the active locale, host string as fallback. */
export declare function resetStampOf(t: Translate, window: {
    resetAt: string;
    resetAtMs?: number | null;
}, now: number): string;
/** Every window of a snapshot, named and stamped for the active locale. */
export declare function windowsOf(t: Translate, result: BalanceResult, now: number): {
    label: string;
    percent: number | null;
    reset: string;
}[];
