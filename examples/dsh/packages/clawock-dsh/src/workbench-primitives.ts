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
import * as React from 'react'
import styles from './styles.module.css'

const { createElement } = React
type ElementProps = Record<string, unknown> | null
const h = createElement as (type: unknown, props?: ElementProps, ...children: unknown[]) => React.ReactElement

/** A DOM attribute bag a page passes through; the primitive owns the class. */
export type Attrs = Record<string, unknown>

export function cx(...tokens: (string | false | null | undefined)[]): string {
  const out: string[] = []
  for (const token of tokens) {
    if (token === '' || token === false || token === null || token === undefined) continue
    out.push(styles[token] ?? token)
  }
  return out.join(' ')
}

function attrsOf(attrs: Attrs | undefined, className: string): Attrs {
  const rest: Attrs = { ...(attrs ?? {}) }
  const caller = rest.className
  delete rest.className
  return { ...rest, className: caller === undefined || caller === '' ? className : className + ' ' + String(caller) }
}

/** One row: the queue and History share this exact height, padding and type. */
export function Row(props: {
  variant?: 'queue' | 'history'
  selected?: boolean
  attrs?: Attrs
  children?: React.ReactNode
}): React.ReactElement {
  const attrs = { ...(props.attrs ?? {}) }
  const tag = typeof attrs.as === 'string' ? attrs.as : 'button'
  delete attrs.as
  const dom = tag === 'button' ? { type: 'button', ...attrs } : attrs
  return h(tag, attrsOf(dom, cx('wb-row', props.variant === 'history' && 'wb-hist-row', props.selected && 'wb-row-on')), props.children)
}

/** A disclosure or a navigation header: one 36px band, one chevron. */
export function SectionHeader(props: {
  title: React.ReactNode
  summary?: React.ReactNode
  lead?: React.ReactNode
  chevron?: React.ReactNode
  tone?: 'danger' | 'neutral'
  as?: 'button' | 'div'
  attrs?: Attrs
}): React.ReactElement {
  if (props.as === 'div') {
    return h('div', attrsOf({ role: 'heading', 'aria-level': 3, ...(props.attrs ?? {}) }, cx('tq-d-sec-title')), props.title)
  }
  const tone = props.tone ?? 'neutral'
  return h('button', attrsOf({ type: 'button', 'data-wb-tone': tone, ...(props.attrs ?? {}) }, cx('wb-group')),
    props.lead ?? null,
    h('span', { className: cx('wb-group-title') }, props.title),
    props.summary === undefined || props.summary === '' ? null : h('span', { className: cx('wb-group-summary') }, props.summary),
    h('span', { className: cx('wb-group-chev'), 'aria-hidden': 'true' }, props.chevron ?? null))
}

/** One control: 32px, three intents. `pill` is the detail layer's 32px pill. */
export function Button(props: {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  pill?: boolean
  plain?: boolean
  attrs?: Attrs
  children?: React.ReactNode
}): React.ReactElement {
  const variant = props.variant ?? 'secondary'
  const legacy = props.plain === true
    ? ''
    : props.pill === true
      ? cx('tq-pill', variant === 'danger' && 'tq-danger')
      : cx('wb-act', 'wb-act-' + variant)
  const attrs: Attrs = { type: 'button', ...(props.attrs ?? {}) }
  const tag = typeof attrs.as === 'string' ? attrs.as : 'button'
  delete attrs.as
  return h(tag, attrsOf(attrs, legacy), props.children)
}

/** One status/count chip. */
export function Chip(props: {
  attrs?: Attrs
  children?: React.ReactNode
}): React.ReactElement {
  return h('span', attrsOf(props.attrs, cx('wb-ov-chip')), props.children)
}

/** One raised reading surface (a card is the page's only bordered block). */
export function Card(props: {
  attrs?: Attrs
  children?: React.ReactNode
}): React.ReactElement {
  return h('div', attrsOf(props.attrs, cx('wb-card')), props.children)
}

/** The one overlay: scrim, sheet, one 48px head with a close control. */
export function Sheet(props: {
  title: React.ReactNode
  closeLabel: string
  onClose: () => void
  attrs?: Attrs
  children?: React.ReactNode
}): React.ReactElement {
  const attrs = { ...(props.attrs ?? {}) }
  const sheet = typeof attrs.sheet === 'string' ? attrs.sheet : ''
  delete attrs.sheet
  return h('div', attrsOf({ ...attrs, 'data-wb-overlay': 'sheet' }, cx('wb-overlay')),
    h('div', {
      className: cx('wb-scrim'), 'data-wb-scrim': 'true', 'aria-hidden': 'true',
      onClick: props.onClose,
    }),
    h('div', {
      className: cx('wb-sheet'), role: 'dialog', 'aria-modal': 'true', 'aria-label': props.title,
      ...(sheet === '' ? {} : { 'data-wb-sheet': sheet }),
    },
      h('div', { className: cx('wb-sheet-head') },
        h('span', { className: cx('wb-sheet-title') }, props.title),
        h('button', {
          type: 'button', className: cx('wb-sheet-close'), 'data-wb-sheet-back': 'true',
          'aria-label': props.closeLabel, title: props.closeLabel, onClick: props.onClose,
        }, '×')),
      h('div', { className: cx('wb-sheet-body', 'pbc', 'tqf') }, props.children)))
}

/** One label/value line (definition list semantics, even when visually a row). */
export function Field(props: {
  label: React.ReactNode
  value: React.ReactNode
  sub?: React.ReactNode
  control?: React.ReactNode[]
  after?: React.ReactNode
  wide?: boolean
  mono?: boolean
  voice?: 'warn' | 'bad'
  attrs?: Attrs
}): React.ReactElement {
  const control = props.control == null || props.control.length === 0 ? null : props.control
  return h('div', attrsOf({
    'data-tq-field': props.attrs?.['data-tq-field'],
    ...(props.attrs ?? {}),
  }, cx('tq-d-field', control !== null && !props.wide && 'tq-d-has-control')),
    h('dt', { className: cx('tq-d-k') }, props.label),
    h('dd', {
      className: cx('tq-d-v', props.mono === true && 'tq-mono'),
      ...(props.voice === undefined ? {} : { 'data-voice': props.voice }),
    }, props.value),
    props.sub == null || props.sub === '' ? null : h('dd', { className: cx('tq-d-sub') }, props.sub),
    control === null ? null : h('dd', { className: cx('tq-d-control', props.wide && 'tq-d-control-wide') }, ...control),
    props.after == null ? null : h('dd', { className: cx('tq-d-after') }, props.after))
}

/** One empty surface: title, optional body/meta, one action. */
export function EmptyState(props: {
  title?: React.ReactNode
  body?: React.ReactNode
  meta?: React.ReactNode
  glyph?: React.ReactNode
  action?: React.ReactNode
  attrs?: Attrs
}): React.ReactElement {
  return h('div', attrsOf(props.attrs, cx('wb-empty')),
    props.glyph === undefined ? null : h('span', { className: cx('wb-empty-glyph'), 'aria-hidden': 'true' }, props.glyph),
    props.title === undefined ? null : h('div', { className: cx('wb-empty-title') }, props.title),
    props.body === undefined ? null : h('div', { className: cx('wb-empty-body') }, props.body),
    props.meta === undefined ? null : h('div', { className: cx('wb-empty-meta') }, props.meta),
    props.action === undefined ? null : props.action)
}
