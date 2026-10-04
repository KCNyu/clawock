/**
 * The task chip's provider panel as conservative Markdown: the chat rendering of the same
 * panel.ts model the sidebar draws, for a chat reply (OpenClaw `/dispatch-list`).
 * It decides nothing — groups, rows, words, order and folding all come from the
 * model. Only the drawing is its own: a role is a character where the chip has
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
/** One row on one line: name, value, [state], then its kind's facts in FACT_ORDER; a head's caption on the next. */
export declare function rowText(view: RowView, t: Translate): string[];
export declare function panelText(model: PanelModel, t: Translate): string;
