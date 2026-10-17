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
export type WeixinTableMode = 'auto' | 'cards' | 'off'

/** A table whose widest cell is longer than this is prose, not a cell. */
const MAX_NATIVE_CELL = 12
/** The whole table must fit a phone line (display columns, CJK counts as two). */
const MAX_NATIVE_WIDTH = 30
const MAX_NATIVE_COLUMNS = 3
const MAX_NATIVE_ROWS = 12
/** A first cell this short is an index/PR number and belongs in the title. */
const INDEX_CELL_WIDTH = 6
/** The cell beside an index is a title, not prose, only while it stays this short. */
const TITLE_CELL_WIDTH = 16

const CJK = /[\u1100-\u115f\u2e80-\u303e\u3041-\u33ff\u3400-\u4dbf\u4e00-\u9fff\ua000-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe30-\ufe4f\uff00-\uff60\uffe0-\uffe6]/

/** Display columns: a full-width character takes two cells in a phone line. */
export function displayWidth(text: string): number {
  let width = 0
  for (const ch of text) width += CJK.test(ch) ? 2 : 1
  return width
}

/** The text a reader sees, with the inline markers the client renders removed. */
function visibleText(text: string): string {
  return text
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\*\*|__|`/g, '')
}

function cellWidth(text: string): number {
  return displayWidth(visibleText(text))
}

function hasCJK(text: string): boolean {
  return CJK.test(text)
}

/** Split a GFM row on unescaped pipes outside inline code; drop the outer ones. */
function splitCells(line: string): string[] {
  let row = line.trim()
  if (row.startsWith('|')) row = row.slice(1)
  if (row.endsWith('|') && !row.endsWith('\\|')) row = row.slice(0, -1)
  const cells: string[] = []
  let cell = ''
  let inCode = false
  for (let i = 0; i < row.length; i += 1) {
    const ch = row[i]
    if (ch === '\\' && row[i + 1] === '|') {
      cell += '\\|'
      i += 1
      continue
    }
    if (ch === '`') {
      inCode = !inCode
      cell += ch
      continue
    }
    if (ch === '|' && !inCode) {
      cells.push(cell.trim())
      cell = ''
      continue
    }
    cell += ch
  }
  cells.push(cell.trim())
  return cells
}

function isTableRow(line: string): boolean {
  return /^\s*\|/.test(line)
}

function isDelimiterRow(line: string): boolean {
  if (!line.includes('|')) return false
  const cells = splitCells(line)
  return cells.length > 0 && cells.every((cell) => /^:?-+:?$/.test(cell))
}

function isFence(line: string): boolean {
  return /^\s*```/.test(line)
}

/** A first cell worth folding into the title with the cell beside it. */
function isIndexCell(text: string): boolean {
  return text !== '' && cellWidth(text) <= INDEX_CELL_WIDTH
}

function label(header: string, value: string): string {
  if (!header) return value
  return `${header}${hasCJK(header) || hasCJK(value) ? '：' : ': '}${value}`
}

/** One row as its card lines; an all-empty row renders nothing. */
function renderCard(cells: string[], headers: string[]): string[] {
  if (cells.every((cell) => cell === '')) return []
  let title = cells[0] ?? ''
  let first = 1
  // A short first cell owns the row. Short beside it joins the title; long beside it is
  // content, so the index stays a bold marker and the sentence stays a sentence.
  let lede = ''
  if (cells.length >= 2 && isIndexCell(title) && (cells[1] ?? '') !== '') {
    if (cellWidth(cells[1] ?? '') <= TITLE_CELL_WIDTH) {
      title = `${title} · ${cells[1]}`
      first = 2
    } else if (cells.length === 2) {
      // The sentence carries the row; a bold index marks it and the sentence stays plain.
      lede = (cells[1] ?? '').replace(/\*\*/g, '')
      first = 2
    }
  }
  if (title === '' && cells.length >= 2) {
    title = cells[1] ?? ''
    first = 2
  }
  const lines: string[] = []
  const plainTitle = title.replace(/\*\*/g, '').trim()
  if (lede) lines.push(`**${plainTitle}** ${lede}`.trim())
  else if (plainTitle) lines.push(`**${plainTitle}**`)
  for (let i = first; i < cells.length; i += 1) {
    const value = (cells[i] ?? '').trim()
    if (!value) continue
    const header = (headers[i] ?? '').trim()
    lines.push(`- ${label(header, value)}`)
  }
  return lines
}

/** Whether the client's native table is the better shape for this table. */
function fitsNatively(headers: string[], rows: string[][]): boolean {
  const columns = headers.length
  if (columns === 0 || columns > MAX_NATIVE_COLUMNS) return false
  if (rows.length > MAX_NATIVE_ROWS) return false
  const widths = headers.map((header, column) =>
    Math.max(cellWidth(header), ...rows.map((row) => cellWidth(row[column] ?? ''))),
  )
  if (Math.max(...widths) > MAX_NATIVE_CELL) return false
  const width = widths.reduce((sum, column) => sum + column, 0) + 3 * columns + 1
  return width <= MAX_NATIVE_WIDTH
}

/**
 * Rewrite the tables in `text` that the phone cannot show well.
 *
 * `auto` keeps compact tables (the client renders them natively), `cards`
 * rewrites every table, `off` returns the text untouched. Fenced code is never
 * touched, and a table that already has no bars left is a no-op, so running
 * this twice is harmless.
 */
export function formatWeixinTables(text: string, mode: WeixinTableMode = 'auto'): string {
  if (mode === 'off' || !text || !text.includes('|')) return text
  const lines = text.split('\n')
  const out: string[] = []
  let fence = false
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]!
    if (fence) {
      if (isFence(line)) fence = false
      out.push(line)
      continue
    }
    if (isFence(line)) {
      fence = true
      out.push(line)
      continue
    }
    if (!isTableStart(lines, i)) {
      out.push(line)
      continue
    }
    const headerCells = splitCells(line)
    const body: string[][] = []
    let end = i + 2
    while (end < lines.length && isTableRow(lines[end]!) && !isDelimiterRow(lines[end]!)) {
      body.push(splitCells(lines[end]!))
      end += 1
    }
    const columns = Math.max(headerCells.length, ...body.map((cells) => cells.length))
    const headers = Array.from({ length: columns }, (_, column) => headerCells[column] ?? '')
    const rows = body.map((cells) => Array.from({ length: columns }, (_, column) => cells[column] ?? ''))
    // A header with no body is not a table to lay out; keep the original lines.
    if (rows.length === 0 || (mode === 'auto' && fitsNatively(headers, rows))) {
      for (let keep = i; keep < end; keep += 1) out.push(lines[keep]!)
      i = end - 1
      continue
    }
    const cards = columns === 1
      ? rows.map((cells) => (cells[0] ? [`- ${cells[0]}`] : []))
      : rows.map((cells) => renderCard(cells, headers))
    let wrote = false
    for (const card of cards) {
      if (card.length === 0) continue
      if (wrote) out.push('')
      out.push(...card)
      wrote = true
    }
    i = end - 1
  }
  return out.join('\n')
}

/** A header row immediately followed by a delimiter row, both starting with `|`. */
function isTableStart(lines: string[], index: number): boolean {
  return (
    index + 1 < lines.length &&
    isTableRow(lines[index]!) &&
    isDelimiterRow(lines[index + 1]!)
  )
}
