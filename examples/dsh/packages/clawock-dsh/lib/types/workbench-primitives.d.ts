/**
 * Workbench primitives — the only place a Workbench page may name a visual
 * class. Each primitive has one value set in `styles.module.css` (the token
 * block at the bottom of the sheet), so the queue, the task detail, History
 * and the brief sheet cannot drift apart again.
 *
 * The legacy class tokens (`wb-row`, `wb-group`, `tq-d-*`, …) are kept: the
 * geometry and plugin specs address them, and renaming would turn a design
 * contract into a test rewrite. A primitive owns the mapping instead, so a
 * page composes a role, not a class.
 *
 * Plain `createElement`, matching `client.ts`: the loader supplies React at
 * runtime and the bundle must stay free of JSX transforms.
 */
import * as React from 'react';
/** A DOM attribute bag a page passes through; the primitive owns the class. */
export type Attrs = Record<string, unknown>;
export declare function cx(...tokens: (string | false | null | undefined)[]): string;
/** One row: the queue and History share this exact height, padding and type. */
export declare function Row(props: {
    variant?: 'queue' | 'history';
    selected?: boolean;
    attrs?: Attrs;
    children?: React.ReactNode;
}): React.ReactElement;
/** A disclosure or a navigation header: one 36px band, one chevron. */
export declare function SectionHeader(props: {
    title: React.ReactNode;
    summary?: React.ReactNode;
    lead?: React.ReactNode;
    chevron?: React.ReactNode;
    tone?: 'danger' | 'neutral';
    as?: 'button' | 'div';
    attrs?: Attrs;
}): React.ReactElement;
/** One control: 32px, three intents. `pill` is the detail layer's 32px pill. */
export declare function Button(props: {
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
    pill?: boolean;
    plain?: boolean;
    attrs?: Attrs;
    children?: React.ReactNode;
}): React.ReactElement;
/** One status/count chip. */
export declare function Chip(props: {
    attrs?: Attrs;
    children?: React.ReactNode;
}): React.ReactElement;
/** One raised reading surface (a card is the page's only bordered block). */
export declare function Card(props: {
    attrs?: Attrs;
    children?: React.ReactNode;
}): React.ReactElement;
/** The one overlay: scrim, sheet, one 48px head with a close control. */
export declare function Sheet(props: {
    title: React.ReactNode;
    closeLabel: string;
    onClose: () => void;
    attrs?: Attrs;
    children?: React.ReactNode;
}): React.ReactElement;
/** One label/value line (definition list semantics, even when visually a row). */
export declare function Field(props: {
    label: React.ReactNode;
    value: React.ReactNode;
    sub?: React.ReactNode;
    control?: React.ReactNode[];
    after?: React.ReactNode;
    wide?: boolean;
    mono?: boolean;
    voice?: 'warn' | 'bad';
    attrs?: Attrs;
}): React.ReactElement;
/** One empty surface: title, optional body/meta, one action. */
export declare function EmptyState(props: {
    title?: React.ReactNode;
    body?: React.ReactNode;
    meta?: React.ReactNode;
    glyph?: React.ReactNode;
    action?: React.ReactNode;
    attrs?: Attrs;
}): React.ReactElement;
