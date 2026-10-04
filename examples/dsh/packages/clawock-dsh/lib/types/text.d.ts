/**
 * The task chip's provider panel as conservative Markdown: the chat rendering of the same
 * panel.ts model the sidebar draws, for a chat reply (OpenClaw `/dispatch-list`).
 * It decides nothing — groups, rows, words and order all come from the model.
 * Only the drawing is its own: a role is a character where the chip has
 * a glyph, a window's used share is a bar of blocks where the chip has a
 * hairline, and nothing relies on colour or on a monospaced font (WeChat has
 * neither).
 */
import { type PanelModel, type RowView, type StateRole } from './panel.ts';
import type { Translate } from './copy.ts';
/** A role's glyph as one character, in the shape the chip draws (panel.ts STATE_ROLES). */
export declare const ROLE_MARK: Record<StateRole, string>;
/** A used share as a bar of blocks: ▓ used, ░ left. */
export declare function bar(fill: number | null): string;
/**
 * One row on one line, then a head's caption on the next.
 *
 * A list row (a task, an ended task, a round) LEADS with its state: a chat has no columns, so
 * the start of the line is the only place every row shares, and what a reader scans a list for
 * is the state (is anything stuck, did it fail). A head (a source, a section) leads with its
 * name, then its reading and state. `warn: false` leaves the low mark off a source's reading
 * when a window line below carries it (see panelText).
 */
export declare function rowText(view: RowView, t: Translate, opts?: {
    warn?: boolean;
}): string[];
/**
 * The message, top to bottom in the model's order. Three levels and no more: the title (H1); the
 * two sections that are lists of their own, what just ended and patrol (H2); a provider is a bold
 * line, not a heading, so five providers do not become five headings between the reader and the
 * rows. Under a provider: its windows, what it says about itself, then its live tasks, every one
 * a flat list item. That is the one construct that keeps one fact per line whether or not the
 * client renders Markdown: a bare line after a list item is that item's continuation.
 *
 * A source's low mark sits on the window that is at its limit, not on the headline reading: the
 * headline is the short window, and `⚠0%` read as a fault when it was the week that was spent.
 * A chat cannot unfold, so patrol prints every round the host sent (at most eight) instead of a
 * "N earlier rounds" line nobody can open. The coverage archive (lens/area tables) is the
 * sidebar's; here it speaks only when one of its sources could not be read.
 */
export declare function panelText(model: PanelModel, t: Translate): string;
