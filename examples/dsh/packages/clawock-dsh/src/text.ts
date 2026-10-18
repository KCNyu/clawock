/**
 * The task chip's provider panel as conservative Markdown: the chat rendering of the same
 * panel.ts model the sidebar draws, for a chat reply (OpenClaw `/dispatch-list`).
 * It decides nothing — groups, rows, words and order all come from the model.
 * Only the drawing is its own: a role is a character where the chip has
 * a glyph, a window's used share is a bar of blocks where the chip has a
 * hairline, and nothing relies on colour or on a monospaced font (WeChat has
 * neither).
 */
import { FACT_ORDER, ROW_KINDS, type Fact, type PanelModel, type ReceiptState, type RowView, type StateRole, type StatsView } from './panel.ts'
import type { Translate } from './copy.ts'

/** A role's glyph as one character, in the shape the chip draws (panel.ts STATE_ROLES). */
export const ROLE_MARK: Record<StateRole, string> = {
  run: '●', queue: '○', sleep: '☾', wait: '⌛', done: '✓', partial: '◐', fail: '✕', off: '⊖', unknown: '?', fallback: '↩',
}

const RECEIPT_MARK: Record<ReceiptState, string> = { sent: '✓', failed: '✕', unknown: '?', planned: '…' }

const BAR_CELLS = 10

/** A used share as a bar of blocks: ▓ used, ░ left. */
export function bar(fill: number | null): string {
  if (fill === null) return '░'.repeat(BAR_CELLS)
  const used = Math.max(0, Math.min(BAR_CELLS, Math.round(fill / (100 / BAR_CELLS))))
  return '▓'.repeat(used) + '░'.repeat(BAR_CELLS - used)
}

function factText(fact: Fact, t: Translate): string {
  const words = fact.receipts != null
    ? fact.receipts.map(({ ch, state }) => t('queue.ch.' + ch) + RECEIPT_MARK[state]).join(' ')
    : fact.text
  return fact.mark == null ? words : words + ' ' + ROLE_MARK[fact.mark.role] + fact.mark.text
}

/**
 * One row on one line, then a head's caption on the next.
 *
 * A list row (a task, an ended task, a round) LEADS with its state: a chat has no columns, so
 * the start of the line is the only place every row shares, and what a reader scans a list for
 * is the state (is anything stuck, did it fail). A head (a source, a section) leads with its
 * name, then its reading and state. `warn: false` leaves the low mark off a source's reading
 * when a window line below carries it (see panelText).
 */
export function rowText(view: RowView, t: Translate, opts: { warn?: boolean } = {}): string[] {
  const kind = ROW_KINDS[view.kind]
  const value = kind.value && view.value != null ? (view.value.tone === 'low' && opts.warn !== false ? '⚠' : '') + view.value.text : null
  const state = view.state === null ? null : ROLE_MARK[view.state.role] + view.state.text
  const facts = FACT_ORDER.filter((slot) => kind.facts.includes(slot) && view.facts[slot] != null)
    .map((slot) => factText(view.facts[slot]!, t))
    .filter((text) => text !== '')
  const listed = view.kind === 'task' || view.kind === 'ended' || view.kind === 'round'
  const line = (listed ? [state, view.name] : [view.name, value, state]).filter((part) => part !== null && part !== '').join(listed ? ' ' : '  ')
  const caption = (view.caption ?? []).map((part) => part.text).filter((text) => text !== '')
  return [
    facts.length === 0 ? line : line + ' · ' + facts.join(' · '),
    ...(caption.length === 0 ? [] : [caption.join(' · ')]),
  ]
}

// Dynamic row words are literal text, never Markdown markup supplied by a task name.
const literal = (text: string): string => text.replace(/([\\`*_[\]<>])/g, '\\$1').replace(/[\r\n]+/g, ' ')
const prose = (lines: string[]): string[] => lines.map(literal)

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
export function panelText(model: PanelModel, t: Translate): string {
  const out: string[] = ['# ' + literal(model.title)]
  for (const note of model.notices) out.push((note.bad ? '⚠ ' : '') + literal(note.text))
  if (model.empty !== null) out.push(literal(model.empty))
  for (const group of model.groups) {
    out.push('')
    const windows = group.detail?.kind === 'windows' ? group.detail.windows : []
    const [head, ...caption] = rowText(group.head, t, { warn: !windows.some((w) => w.state === 'low') })
    const name = group.head.name
    out.push(['**' + literal(name) + '**' + literal(head!.slice(name.length).replace(/^ +/, ' ')), ...prose(caption)].join(' · '))
    if (group.balanceNote !== null) out.push('- ⚠ ' + literal(group.balanceNote))
    for (const w of windows) {
      const pct = w.percent === null ? '—' : Math.round(w.percent) + '%'
      out.push(`- **${literal(w.label)}** ${bar(w.fill)} ${pct}` + (w.state === 'low' ? ' ⚠' : '') + (w.reset === '' ? '' : ' ↻' + literal(w.reset)))
    }
    if (group.detail?.kind === 'text') out.push('- ' + literal(group.detail.text))
    for (const note of group.notes) out.push('- ' + literal(note))
    for (const { row } of group.tasks) out.push('- ' + literal(rowText(row, t)[0]!))
  }
  if (model.recent !== null) {
    out.push('', '## ' + literal(rowText(model.recent.head, t)[0]!))
    for (const row of model.recent.rows) out.push('- ' + literal(rowText(row, t)[0]!))
  }
  if (model.patrol !== null) {
    const [head, ...caption] = rowText(model.patrol.head, t)
    out.push('', '## ' + literal(head!), ...prose(caption))
    for (const row of model.patrol.rounds) out.push('- ' + literal(rowText(row, t)[0]!))
    for (const alert of model.patrol.progress?.alerts ?? []) out.push('- ⚠ ' + literal(alert))
  }
  if (model.footer !== null) out.push('', literal((model.footer.bad ? '⚠ ' : '') + model.footer.text))
  return out.join('\n')
}

/** One Markdown table cell: a literal `|` would open a column, so escape it. */
const cell = (text: string): string => text.replace(/([\\`*_[\]<>|])/g, '\\$1').replace(/[\r\n]+/g, ' ')

/**
 * `/dispatch-stats`: a table by default (the WeChat channel passes tables through its
 * Markdown filter; `plain` is the bar fallback for a client that shows the pipes).
 * One title, one table, one caveat line — no process prose. The same `StatsView`
 * the chip draws, so the chat and the chip cannot disagree.
 */
export function statsText(view: StatsView, t: Translate, plain = false): string {
  const out = ['# ' + literal(view.title + ' · ' + view.window)]
  if (view.empty !== '') {
    out.push('', literal(view.empty), '', literal(view.footnote))
    return out.join('\n')
  }
  if (view.agents.length === 0) {
    out.push('', literal(view.headline), '', literal(view.footnote))
    return out.join('\n')
  }
  if (plain) {
    out.push('', literal(view.headline))
    for (const agent of view.agents) {
      out.push('', literal(agent.label + '  ' + bar(agent.share * 100) + '  ' + agent.tokensText + ' · ' + agent.costText))
      const parts = [
        t('stats.table.settled') + ' ' + agent.settled,
        t('stats.table.done') + ' ' + agent.done,
        t('stats.table.partial') + ' ' + agent.partial,
        t('stats.table.unfinished') + ' ' + agent.unfinished,
        ...(agent.live > 0 ? [t('stats.card.live', { n: agent.live })] : []),
      ]
      out.push(literal(parts.join(' · ')))
    }
    out.push('', literal(view.footnote))
    return out.join('\n')
  }
  const header = [
    t('stats.table.agent'), t('stats.table.doneSettled'),
    t('stats.table.partial'), t('stats.table.unfinished'), t('stats.table.tokens'),
  ]
  const row = (label: string, a: { settled: number; done: number; partial: number; unfinished: number; tokensText: string; costText: string }): string =>
    '| ' + [label, a.done + '/' + a.settled, String(a.partial), String(a.unfinished), a.tokensText + ' · ' + a.costText]
      .map(cell).join(' | ') + ' |'
  out.push('', '| ' + header.map(cell).join(' | ') + ' |', '|' + '---|'.repeat(header.length))
  for (const agent of view.agents) out.push(row(agent.label, agent))
  out.push(row(t('stats.table.total'), view.totals))
  out.push('', literal(view.footnote))
  return out.join('\n')
}
