/**
 * The task chip's provider panel as conservative Markdown: the chat rendering of the same
 * panel.ts model the sidebar draws, for a chat reply (OpenClaw `/dispatch-list`).
 * It decides nothing — groups, rows, words, order and folding all come from the
 * model. Only the drawing is its own: a role is a character where the chip has
 * a glyph, a window's used share is a bar of blocks where the chip has a
 * hairline, and nothing relies on colour or on a monospaced font (WeChat has
 * neither).
 */
import { FACT_ORDER, FLAT_ROUNDS, RESIDENT_ROUNDS, ROW_KINDS, type Fact, type PanelModel, type ReceiptState, type RowView, type StateRole } from './panel.ts'
import type { Translate } from './copy.ts'

/** A role's glyph as one character, in the shape the chip draws (panel.ts STATE_ROLES). */
export const ROLE_MARK: Record<StateRole, string> = {
  run: '●', queue: '○', sleep: '☾', wait: '⌛', done: '✓', partial: '◐', fail: '✕', off: '–', unknown: '?', fallback: '↩',
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

/** One row on one line: name, value, [state], then its kind's facts in FACT_ORDER; a head's caption on the next. */
export function rowText(view: RowView, t: Translate): string[] {
  const kind = ROW_KINDS[view.kind]
  const value = kind.value && view.value != null ? (view.value.tone === 'low' ? '⚠' : '') + view.value.text : null
  const state = view.state === null ? null : ROLE_MARK[view.state.role] + view.state.text
  const facts = FACT_ORDER.filter((slot) => kind.facts.includes(slot) && view.facts[slot] != null)
    .map((slot) => factText(view.facts[slot]!, t))
    .filter((text) => text !== '')
  const line = [view.name, value, state].filter((part) => part !== null && part !== '').join('  ')
  const caption = (view.caption ?? []).map((part) => part.text).filter((text) => text !== '')
  return [
    facts.length === 0 ? line : line + ' · ' + facts.join(' · '),
    ...(caption.length === 0 ? [] : [caption.join(' · ')]),
  ]
}

// Dynamic row words are literal text, never Markdown markup supplied by a task name.
const literal = (text: string): string => text.replace(/([\\`*_[\]<>])/g, '\\$1').replace(/[\r\n]+/g, ' ')
const prose = (lines: string[]): string[] => lines.map(literal)

export function panelText(model: PanelModel, t: Translate): string {
  const out: string[] = ['# ' + literal(model.title)]
  for (const note of model.notices) out.push((note.bad ? '⚠ ' : '') + literal(note.text))
  if (model.empty !== null) out.push(literal(model.empty))
  for (const group of model.groups) {
    out.push('')
    const [head, ...caption] = rowText(group.head, t)
    out.push('## ' + literal(head!), ...prose(caption))
    if (group.balanceNote !== null) out.push('⚠ ' + literal(group.balanceNote))
    if (group.detail?.kind === 'windows') {
      for (const w of group.detail.windows) {
        const pct = w.percent === null ? '—' : Math.round(w.percent) + '%'
        out.push(`- **${literal(w.label)}** ${bar(w.fill)} ${pct}` + (w.reset === '' ? '' : ' ↻' + literal(w.reset)))
      }
    } else if (group.detail?.kind === 'text') {
      out.push(literal(group.detail.text))
    }
    for (const note of group.notes) out.push(literal(note))
    for (const { row } of group.tasks) out.push('- ' + literal(rowText(row, t)[0]!))
  }
  if (model.recent !== null) {
    out.push('', '## ' + literal(rowText(model.recent.head, t)[0]!))
    for (const row of model.recent.rows) out.push('- ' + literal(rowText(row, t)[0]!))
  }
  if (model.patrol !== null) {
    const [head, ...caption] = rowText(model.patrol.head, t)
    out.push('', '## ' + literal(head!), ...prose(caption))
    const rounds = model.patrol.rounds
    const resident = rounds.length <= FLAT_ROUNDS ? rounds.length : RESIDENT_ROUNDS
    for (const row of rounds.slice(0, resident)) out.push('- ' + literal(rowText(row, t)[0]!))
    if (rounds.length > resident) out.push(literal(t('queue.olderRounds', { n: rounds.length - resident })))
    if (model.patrol.progress !== null) {
      out.push('', '### ' + literal(model.patrol.progress.title), literal(model.patrol.progress.summary), literal(model.patrol.progress.scope))
      for (const warning of model.patrol.progress.warnings) out.push(literal(warning))
      out.push(literal(model.patrol.progress.areaNote))
    }
  }
  if (model.footer !== null) out.push('', '**' + literal((model.footer.bad ? '⚠ ' : '') + model.footer.text) + '**')
  return out.join('\n')
}
