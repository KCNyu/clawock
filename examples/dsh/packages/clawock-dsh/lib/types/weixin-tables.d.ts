/**
 * WeChat table layout.
 *
 * WeChat's ClawBot chat renders a Markdown table natively on the phone — a
 * compact 2–3 column table of short cells comes out as a real table, and that
 * is the best shape for it. What it does not do is make a table readable:
 * every column is squeezed into the bubble, so a column whose cells are
 * sentences wraps every few characters and the row becomes a wall of text.
 * The plugins' own chat copy avoids tables for that reason (`src/text.ts`).
 *
 * This module rewrites only the tables that fit badly — wide, tall, or
 * sentence-celled — into "cards": one bold title line per row (the row's key
 * cells) and one flat bullet per remaining column. Bold and lists are what the
 * client renders best, and an 18-character column of prose never survives a
 * native table. Compact tables are left byte-for-byte alone, because the
 * native rendering is better than any text we could draw.
 *
 * Nothing here talks to the gateway: `formatWeixinTables` is pure text in,
 * text out, so the entry only has to decide *when* to call it.
 */
/** How outbound WeChat tables are treated. */
export type WeixinTableMode = 'auto' | 'cards' | 'off';
/** Display columns: a full-width character takes two cells in a phone line. */
export declare function displayWidth(text: string): number;
/**
 * Rewrite the tables in `text` that the phone cannot show well.
 *
 * `auto` keeps compact tables (the client renders them natively), `cards`
 * rewrites every table, `off` returns the text untouched. Fenced code is never
 * touched, and a table that already has no bars left is a no-op, so running
 * this twice is harmless.
 */
export declare function formatWeixinTables(text: string, mode?: WeixinTableMode): string;
