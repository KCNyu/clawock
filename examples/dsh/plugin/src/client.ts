/**
 * clawock-dsh browser bundle: the Decision Mind conversation-view tab.
 *
 * One organic view — the decision trace: real fills as the spine, the shared
 * decision ledger (memory/decisions.jsonl) soft-paired (±3 days) as the "why"
 * layer, and snapshot closes as the T+1 verdict. Fills without a decision say
 * so explicitly. Visual language: modern SaaS on DSH tokens, with the P&L
 * figure as the focal number and a GitHub-style vertical timeline in the
 * expandable detail.
 *
 * Official registration path: the generated Typert Remote contribution is
 * mounted through `ctx.remote.$mount(TYPERT_REMOTE)` (typert.remote-client,
 * emitted by the build), the tab registers through `ctx.slots.register` with
 * a per-session store, and `inject` declares the cordis service dependencies.
 */

import { TYPERT_REMOTE } from './typert.remote-client.js'
import type { TypertClientRemote, TypertRemoteContribution } from '@deepseek-ai/dsh-typert-protocol'
import type { Context } from '@deepseek-ai/cordis'
// The loader module table provides these at runtime; types come from the
// matching @types packages installed as devDependencies.
import * as React from 'react'
import * as clientRuntime from '@deepseek-ai/dsh-client-runtime/client'

type H = (type: any, props: any, ...children: any[]) => any
type StoreState = {
  filter: string
  open: string | null
  visibleDateCount: number
  foldedDates: string[]
  scrollTop: number
}
type StoreActions = {
  setFilter: (value: string) => void
  toggleOpen: (key: string) => void
  showMoreDates: (count: number) => void
  resetDates: () => void
  toggleDate: (date: string) => void
  setScrollTop: (value: number) => void
}
type StoreFace = { useStore: <S>(sel: (s: StoreState) => S) => S; actions: StoreActions }
type DataState = { traces: any[]; rate: number | null; loading: boolean; error: string | null; stale: boolean }

type DecisionMindProps = {
  sessionId: string
  traces: () => Promise<any>
  ledger: () => Promise<any>
  portfolio: () => Promise<any>
  useStore: StoreFace['useStore']
  actions: StoreFace['actions']
}

/** @typert object — client face surface for the Typert generator. */
export interface DecisionMindStoreShape {
  filter: string
  open: string | null
  visibleDateCount: number
  foldedDates: string[]
  scrollTop: number
}

const defineStore = (clientRuntime as any).defineStore
const useEffect = (React as any).useEffect
const useState = (React as any).useState
const h: H = (React as any).createElement

// CSS injection lives in the module scope (module-loader convention).
const STYLE_ID = 'clawock-dsh-styles'
if (typeof document !== 'undefined' && !document.getElementById(STYLE_ID)) {
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = [
    '.dmt{--bg:#F7F8FA;--surface:#FFFFFF;--text:#15171B;--text2:#61666B;--text3:#81858C;--cap:#ADB2B8;',
    '--brand:#4176E6;--brand-soft:#EDF3FE;--ok:#1B8644;--ok-soft:#E6FAED;--bad:#C01313;--bad-soft:#FDEBEE;--warn:#AA6924;',
    '--border:rgba(17,24,39,.06);--border2:rgba(17,24,39,.10);',
    '--hover:rgba(17,24,39,.05);--shadow-sm:0 1px 2px rgba(16,24,40,.04);--shadow-md:0 4px 16px rgba(16,24,40,.08);',
    '--veil:rgba(255,255,255,.92);--tint-soft:rgba(0,0,0,.03);--tint-border:rgba(0,0,0,.05);',
    '--tint-mid:rgba(0,0,0,.08);--tint-strong:rgba(0,0,0,.12);--brand-glow:rgba(65,118,230,.12);',
    '--t1-up-border:rgba(27,132,68,.18);--t1-down-border:rgba(192,19,19,.18);',
    '--radius:12px;--radius-sm:8px;',
    '--font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;',
    '--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;',
    'font:13px/1.45 var(--font);color:var(--text);-webkit-font-smoothing:antialiased;min-height:100%}',
    'body[data-ds-dark-theme] .dmt{--bg:#0F1115;--surface:#1B1B1C;--text:#EDEDEE;--text2:#A7ABB2;--text3:#7D8189;--cap:#5B5F66;',
    '--brand:#6C97F2;--brand-soft:#1E2A44;--ok:#3FCB74;--ok-soft:#153824;--bad:#F2554F;--bad-soft:#3B1516;--warn:#E0A752;',
    '--border:rgba(255,255,255,.08);--border2:rgba(255,255,255,.14);',
    '--hover:rgba(255,255,255,.07);--shadow-sm:0 1px 2px rgba(0,0,0,.3);--shadow-md:0 4px 16px rgba(0,0,0,.4);',
    '--veil:rgba(20,21,24,.85);--tint-soft:rgba(255,255,255,.06);--tint-border:rgba(255,255,255,.08);',
    '--tint-mid:rgba(255,255,255,.12);--tint-strong:rgba(255,255,255,.18);--brand-glow:rgba(108,151,242,.22);',
    '--t1-up-border:rgba(63,203,116,.35);--t1-down-border:rgba(242,85,79,.35)}',
    '.dmt .top{position:sticky;top:0;z-index:20;background:var(--veil);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);border-bottom:1px solid var(--border);padding:10px 16px 8px}',
    '.dmt .tt{display:flex;align-items:center;gap:8px;font:700 17px/1.3 var(--font);letter-spacing:-.01em}',
    '.dmt .tt::before{content:"";width:9px;height:9px;border-radius:3px;background:var(--brand)}',
    '.dmt .ts{font:400 11.5px/1.3 var(--font);color:var(--cap);margin-top:2px}',
    '.dmt .stats{display:flex;align-items:flex-end;gap:0;margin-top:8px;flex-wrap:wrap}',
    '.dmt .sg{display:flex;flex-direction:column;gap:2px;padding:0 14px}',
    '.dmt .sg+.sg{border-left:1px solid rgba(0,0,0,.08)}',
    '.dmt .sl{font:500 10.5px/1.3 var(--font);color:var(--cap);letter-spacing:.03em;white-space:nowrap}',
    '.dmt .sv{font:650 14px/1.3 var(--font);color:var(--text);font-variant-numeric:tabular-nums;white-space:nowrap}',
    '.dmt .sv.focus{font:700 16px/1.3 var(--font)}',
    '.dmt .sv.up{color:var(--ok)}.dmt .sv.down{color:var(--bad)}',
    '.dmt .rate{font:400 10.5px/1.3 var(--font);color:var(--cap);margin-left:auto;align-self:center}',
    '.dmt .filters{display:flex;gap:2px;margin-top:8px;flex-wrap:wrap}',
    '.dmt .ft{border:0;background:transparent;color:var(--text3);font:600 12px/1.4 var(--font);padding:5px 11px;border-radius:8px;cursor:pointer;transition:background .12s,color .12s}',
    '.dmt .ft:hover{background:var(--hover)}',
    '.dmt .ft.on{color:var(--text);background:rgba(17,24,39,.06)}',
    '.dmt .list{max-width:760px;margin:0 auto;padding:10px 16px 32px}',
    '.dmt .day{margin:16px 0 2px;display:flex;align-items:center;gap:8px;font:650 13px/1.3 var(--font);color:var(--text)}',
    '.dmt .day .n{color:var(--cap);font:400 10.5px/1.3 var(--mono);margin-left:auto}',
    '.dmt .day::after{content:"";flex:1;height:1px;background:var(--border);margin-left:6px}',
    '.dmt .day.fold{cursor:pointer;border-radius:8px;padding:2px 6px;margin-left:-6px}',
    '.dmt .day.fold:hover{background:var(--hover)}',
    '.dmt .day.fold .chev{margin-left:0;flex:none;width:14px;text-align:center}',
    '.dmt .cell{width:100%;margin:7px 0;border-radius:12px;border:1px solid var(--border);background:var(--surface);cursor:pointer;box-shadow:var(--shadow-sm);transition:box-shadow .15s,border-color .15s}',
    '.dmt .cell:hover{border-color:var(--border2);box-shadow:var(--shadow-md)}',
    '.dmt .cell.open{border-color:var(--brand);box-shadow:0 0 0 3px rgba(65,118,230,.12)}',
    '.dmt .main{display:flex;align-items:center;gap:12px;padding:13px 14px 6px}',
    '.dmt .dotm{flex:none;width:6px;height:6px;border-radius:50%;background:var(--cap);margin-right:2px}',
    '.dmt .cell.hasdec .dotm{background:var(--brand)}',
    '.dmt .tk{flex:0 1 auto;min-width:0;font:650 14.5px/1.4 var(--font);letter-spacing:-.01em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.dmt .mkt{font:700 9.5px/1 var(--font);margin-left:3px;vertical-align:2px;color:var(--brand)}',
    '.dmt .mkt.hk{color:var(--text3)}',
    '.dmt .tag{flex:none;display:inline-flex;align-items:center;height:20px;padding:0 7px;border-radius:6px;border:1px solid var(--tint-border);background:var(--tint-soft);font:600 11.5px/1 var(--font);color:var(--text2);letter-spacing:.02em}',
    '.dmt .qty{flex:0 1 auto;min-width:0;text-align:right;font:500 12.5px/1.4 var(--mono);color:var(--text2);font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.dmt .sp{flex:1 1 auto;min-width:8px}',
    '.dmt .pnl{flex:none;min-width:92px;text-align:right;font:700 16.5px/1.2 var(--font);font-variant-numeric:tabular-nums;letter-spacing:-.01em}',
    '.dmt .pnl.up{color:var(--ok)}.dmt .pnl.down{color:var(--bad)}.dmt .pnl.na{color:var(--cap);font-weight:500;font-size:13px}',
    '.dmt .sub{display:flex;align-items:center;gap:10px;padding:3px 14px 11px;font:400 11px/1.4 var(--font);color:var(--cap)}',
    '.dmt .t1{flex:none;display:inline-flex;align-items:center;height:18px;padding:0 6px;border-radius:5px;font:600 10.5px/1 var(--font);white-space:nowrap;font-variant-numeric:tabular-nums}',
    '.dmt .t1.up{color:var(--ok);background:var(--ok-soft);border:1px solid var(--t1-up-border)}',
    '.dmt .t1.down{color:var(--bad);background:var(--bad-soft);border:1px solid var(--t1-down-border)}',
    '.dmt .t1.flat{color:var(--text2);background:var(--tint-soft)}',
    '.dmt .sub .date{flex:none;font-variant-numeric:tabular-nums}',
    '.dmt .chev{margin-left:auto;flex:none;color:var(--cap);font-size:10px;transition:transform .15s}',
    '.dmt .cell.open .chev{transform:rotate(180deg)}',
    '.dmt .detail{display:grid;grid-template-rows:0fr;opacity:0;border-top:1px solid var(--tint-border);transition:grid-template-rows .24s cubic-bezier(.22,1,.36,1),opacity .15s ease;overflow:hidden}',
    '.dmt .cell.open .detail{grid-template-rows:1fr;opacity:1}',
    '.dmt .dinner{overflow:hidden;min-height:0;padding:12px 16px 14px}',
    '.dmt .trhead{display:flex;align-items:center;gap:6px;font:500 10.5px/1.3 var(--font);color:var(--cap);letter-spacing:.05em;margin-bottom:8px}',
    '.dmt .trhead::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--brand)}',
    '.dmt .trace{position:relative;padding-left:22px}',
    '.dmt .trace::before{content:"";position:absolute;left:5px;top:12px;bottom:10px;width:2px;background:var(--tint-mid)}',
    '.dmt .tnode{position:relative;padding:2px 0 14px}',
    '.dmt .tnode:last-child{padding-bottom:2px}',
    '.dmt .tnode::before{content:"";position:absolute;left:-22px;top:5px;width:10px;height:10px;border-radius:50%;background:var(--surface);border:2px solid var(--cap);box-sizing:border-box}',
    '.dmt .tnode.dec::before{border-color:var(--brand)}',
    '.dmt .tnode.follow::before{border-color:var(--ok)}.dmt .tnode.skip::before{border-color:var(--warn)}',
    '.dmt .tnode.win::before{border-color:var(--ok)}.dmt .tnode.loss::before{border-color:var(--bad)}',
    '.dmt .tnode .tw{font:400 10px/1.4 var(--mono);color:var(--cap);margin-bottom:1px}',
    '.dmt .tnode .n{font:500 10.5px/1.3 var(--font);color:var(--cap);letter-spacing:.04em;margin-bottom:2px}',
    '.dmt .tnode .v{font:600 13px/1.4 var(--font)}',
    '.dmt .tnode.win .v{color:var(--ok)}.dmt .tnode.loss .v{color:var(--bad)}',
    '.dmt .tnode.follow .v{color:var(--ok)}.dmt .tnode.skip .v{color:var(--warn)}',
    '.dmt .pchips{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 8px}',
    '.dmt .pc{font:400 11px/1.4 var(--font);padding:2px 8px;border-radius:6px;background:var(--tint-soft);border:1px solid var(--border);color:var(--text2)}',
    '.dmt .tnote{margin:7px 0;padding:3px 0 3px 10px;border-left:3px solid var(--tint-strong);font:400 11.5px/1.6 var(--font);color:var(--text2);white-space:pre-wrap;overflow-wrap:anywhere}',
    '.dmt .tnote.why{border-left-color:var(--brand)}',
    '.dmt .tnote.emo{border-left-color:var(--warn)}',
    '.dmt .tnote .k{color:var(--cap);font:600 10.5px/1.4 var(--font)}',
    '.dmt .tmiss{padding:7px 10px;border:1px dashed var(--border2);border-radius:6px;font:400 11.5px/1.5 var(--font);color:var(--cap);margin-top:8px}',
    '.dmt .empty{padding:48px 20px;text-align:center;color:var(--cap);font:400 13px/1.5 var(--font)}',
    '.dmt .trace-more{display:block;width:calc(100% - 32px);margin:10px 16px;padding:9px 12px;border:1px dashed var(--border2);border-radius:10px;background:var(--surface);color:var(--text2);font:600 12px/1.4 var(--font);cursor:pointer;transition:background .12s,border-color .12s,color .12s}',
    '.dmt .trace-more:hover{background:var(--hover);border-color:var(--brand);color:var(--text)}',
    '.dmt .skel{display:flex;align-items:center;gap:12px;padding:13px 16px;border:1px solid var(--border);border-radius:12px;background:var(--surface);margin:7px 0}',
    '.dmt .skel-dot{flex:none;width:6px;height:6px;border-radius:50%;background:var(--tint-strong)}',
    '.dmt .skel-bar{height:10px;border-radius:5px;background:var(--tint-mid)}',
    '.dmt .skel-bar.w40{width:40%}',
    '.dmt .skel-bar.w20{width:20%}',
    '@media (max-width:520px){',
    '.dmt .main{gap:8px;padding:12px 12px 6px}',
    '.dmt .tk{font-size:13.5px}',
    '.dmt .qty{font-size:11px;text-align:left}',
    '.dmt .pnl{min-width:84px;font-size:14.5px}',
    '.dmt .sub{gap:8px;padding:3px 12px 10px}',
    '.dmt .sg{padding:0 11px}',
    '.dmt .sv{font-size:13px}.dmt .sv.focus{font-size:14.5px}',
    '}',
    '@media (prefers-reduced-motion:reduce){',
    '.dmt *{transition:none!important;animation:none!important}',
    '}',
  ].join('')
  document.head.appendChild(style)
}

const ACT: Record<string, string> = { buy: '买入', add: '加仓', trim: '减仓', sell: '卖出', cut: '割肉', hold: '持有',
  hold_and_watch: '持有', trim_on_rebound: '反弹减仓', t_only: '仅T+0',
  add_only_on_trigger: '触发加仓', reject: '不加', watch: '观望', abstain: '弃权' }
const DRV: Record<string, string> = { technical: '技术面', fundamental: '基本面', sentiment: '情绪面', mixed: '混合', risk_rule: '风控规则' }
const EXE: Record<string, [string, string]> = { followed: ['已遵守', 'follow'], not_followed: ['未执行', 'skip'], unknown: ['未知', ''] }
const EMO: Record<string, string> = { fomo: '追高冲动', revenge: '报复性', averaging_down: '摊薄冲动', fear: '恐慌',
  euphoria: '亢奋', calm: '平静', mixed: '混合' }

function esc(s: unknown): string { return String(s == null ? '' : s).replace(/</g, '&lt;') }

/** T+1 tone is action-aware: a rising price is good for the buyer and bad
 *  for the seller (卖飞). One sign rule for both would color buy gains red
 *  and buy losses green. */
export function t1Tone(action: string, delta: number): 'win' | 'loss' {
  const up = delta >= 0
  const sell = action === 'sell' || action === 'cut' || action === 'trim' || action === 'trim_on_rebound'
  if (sell) return up ? 'loss' : 'win'
  return up ? 'win' : 'loss'
}
export function t1ChipTone(action: string, delta: number): 'up' | 'down' | 'flat' {
  if (delta > -1 && delta < 1) return 'flat'
  const up = delta >= 1
  const sell = action === 'sell' || action === 'cut' || action === 'trim' || action === 'trim_on_rebound'
  if (sell) return up ? 'down' : 'up'
  return up ? 'up' : 'down'
}

function fmtMoney(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '—'
  return (v > 0 ? '+' : '') + Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })
}

function fmtPct(v: number | null | undefined, digits?: number): string {
  if (v == null || !isFinite(v)) return '—'
  return (v > 0 ? '+' : '') + Number(v).toFixed(digits || 1) + '%'
}

/** Display projection of one trace (test seam). */
export function _displayEntry(trace: any): any {
  const d = trace.decision || null
  return {
    ticker: trace.ticker || '?',
    market: trace.market || 'US',
    currency: trace.currency || 'USD',
    date: trace.date || null,
    action: trace.action || 'hold',
    shares: trace.shares || 0,
    price: trace.price ?? null,
    realizedPnl: trace.realizedPnl ?? null,
    note: trace.note || null,
    t1: trace.t1 || null,
    holdPnl: trace.holdPnl ?? null,
    decision: d,
  }
}

function Chip(props: any) { return h('span', { className: 'tag' }, props.children) }

function TraceDetail(props: any) {
  const t = props.trace
  const d = t.decision
  const sym = t.currency === 'HKD' ? 'HK$' : '$'
  if (!d) {
    const t1miss = t.t1 ? h('div', { className: 'tnode ' + t1Tone(t.action, t.t1.delta) },
      h('div', { className: 'n' }, 'T+1 结果'),
      h('div', { className: 'v' }, (t.t1.delta >= 0 ? '+' : '') + t.t1.delta + '%')) : null
    return h('div', null,
      h('div', { className: 'trhead' }, '决策轨迹 · 无关联记录'),
      h('div', { className: 'trace' },
        h('div', { className: 'tnode dec' },
          h('div', { className: 'n' }, '决策'),
          h('div', { className: 'v', style: { color: 'var(--cap)' } }, '无关联记录')),
        h('div', { className: 'tnode follow' },
          h('div', { className: 'n' }, '执行'),
          h('div', { className: 'v' }, (ACT[t.action] || t.action) + ' ' + t.shares + '股 @' + t.price + ' ' + sym)),
        t1miss),
      t.note ? h('div', { className: 'tnote' }, esc(t.note)) : null,
      h('div', { className: 'tmiss' }, '此笔无关联决策记录 — 事实保留,判断缺失显式标出'))
  }
  const exe = EXE[d.execution] || ['未知', '']
  const decV = (ACT[d.action] || d.action) + (d.confidence != null ? ' ' + Math.round(d.confidence * 100) + '%' : '') +
    (d.drivenBy ? ' · ' + (DRV[d.drivenBy] || d.drivenBy) : '')
  const why = d.rationale || d.bull || ''
  const emo = d.emotion && d.emotion !== 'calm' ? (EMO[d.emotion] || d.emotion) : null
  const chips = []
  if (d.condition) chips.push(h('span', { className: 'pc', key: 'c' }, '条件: ' + d.condition))
  if (d.sizeShares) chips.push(h('span', { className: 'pc', key: 's' }, '计划 ' + d.sizeShares + ' 股'))
  if (d.plannedPrice) chips.push(h('span', { className: 'pc', key: 'p' }, '计划价 ' + d.plannedPrice))
  const t1node = t.t1 ? h('div', { className: 'tnode ' + t1Tone(t.action, t.t1.delta) },
    h('div', { className: 'tw' }, t.t1.date),
    h('div', { className: 'n' }, 'T+1 结果'),
    h('div', { className: 'v' }, (t.t1.delta >= 0 ? '+' : '') + t.t1.delta + '%' + (t.action === 'sell' ? ' · ' + t.t1.verdict : ''))) : null
  let rv: string
  let rc: string
  if (t.realizedPnl != null) { rv = (t.realizedPnl >= 0 ? '+' : '') + Number(t.realizedPnl).toFixed(2) + ' ' + sym; rc = t.realizedPnl >= 0 ? 'win' : 'loss' }
  else if (t.holdPnl != null) { rv = fmtPct(t.holdPnl, 1); rc = t.holdPnl >= 0 ? 'win' : 'loss' }
  else { rv = '—'; rc = '' }
  return h('div', null,
    h('div', { className: 'trhead' }, '决策轨迹 · ' + (d.planDate || '')),
    h('div', { className: 'trace' },
      h('div', { className: 'tnode dec' },
        h('div', { className: 'tw' }, d.planDate || ''),
        h('div', { className: 'n' }, '计划'),
        h('div', { className: 'v' }, decV)),
      h('div', { className: 'tnode ' + (exe[1] || '') },
        h('div', { className: 'tw' }, t.date || ''),
        h('div', { className: 'n' }, '执行'),
        h('div', { className: 'v' }, exe[0] + (exe[1] === 'skip' ? ' — 实际动了手' : ''))),
      t1node,
      h('div', { className: 'tnode ' + rc },
        h('div', { className: 'n' }, '盈亏'),
        h('div', { className: 'v' }, rv))),
    chips.length ? h('div', { className: 'pchips' }, chips) : null,
    why ? h('div', { className: 'tnote why' }, h('span', { className: 'k' }, '为什么 '), esc(why)) : null,
    emo ? h('div', { className: 'tnote emo' }, h('span', { className: 'k' }, '情绪 '), '⚡ ' + emo) : null,
    t.note ? h('div', { className: 'tnote' }, h('span', { className: 'k' }, '备注 '), esc(t.note)) : null)
}

function TraceCell(props: any) {
  const t = props.trace
  const open = props.open
  const sym = t.currency === 'HKD' ? 'HK$' : '$'
  const qty = t.shares + ' @' + t.price
  let pnl: any
  if (t.realizedPnl != null) pnl = h('span', { className: 'pnl ' + (t.realizedPnl >= 0 ? 'up' : 'down') },
    (t.realizedPnl >= 0 ? '+' : '') + Number(t.realizedPnl).toFixed(2) + ' ' + sym)
  else if (t.holdPnl != null) pnl = h('span', { className: 'pnl ' + (t.holdPnl >= 0 ? 'up' : 'down') }, fmtPct(t.holdPnl, 1))
  else pnl = h('span', { className: 'pnl na' }, '—')
  let t1tag: any = null
  if (t.t1) {
    const tc = t1ChipTone(t.action, t.t1.delta)
    const tlabel = 'T+1 ' + (t.t1.delta >= 0 ? '+' : '') + t.t1.delta + '%' + (t.action === 'sell' ? ' ' + t.t1.verdict : '')
    t1tag = h('span', { className: 't1 ' + tc }, tlabel)
  } else if (t.action === 'sell') {
    t1tag = h('span', { className: 't1 flat' }, 'T+1 —')
  }
  return h('div', { className: 'cell' + (t.decision ? ' hasdec' : '') + (open ? ' open' : ''), role: 'button', tabIndex: 0, 'aria-expanded': open, onClick: props.onToggle, onKeyDown: props.onKeyDown },
    h('div', { className: 'main' },
      h('span', { className: 'dotm' }),
      h('span', { className: 'tk' }, t.ticker, h('span', { className: 'mkt' + (t.market === 'HK' ? ' hk' : '') }, t.market === 'HK' ? '港' : '美')),
      h(Chip, null, ACT[t.action] || t.action),
      h('span', { className: 'qty' }, qty),
      h('span', { className: 'sp' }),
      pnl),
    h('div', { className: 'sub' },
      t1tag,
      h('span', { className: 'date' }, (t.date || '').slice(5)),
      h('span', { className: 'chev' }, '▾')),
    h('div', { className: 'detail' },
      h('div', { className: 'dinner' }, open ? h(TraceDetail, { trace: t }) : null)))
}

/** Skeleton row for the cold-start loading state (no cache yet). */
function SkeletonRow() {
  return h('div', { className: 'skel' },
    h('div', { className: 'skel-dot' }),
    h('div', { className: 'skel-bar w40' }),
    h('div', { className: 'skel-bar w20' }))
}

function DecisionMind(props: DecisionMindProps) {
  const ui = props.useStore((s) => s)
  const acts = props.actions
  const dataPair = useState({ traces: [], rate: null, loading: true, error: null, stale: false } as DataState)
  const data: DataState = dataPair[0]
  const setData: (v: DataState | ((c: DataState) => DataState)) => void = dataPair[1]

  useEffect(() => {
    let alive = true
    const cached = traceCache
    if (cached) {
      // 缓存命中:同步渲染上一次快照,零 loading 帧。
      setData({ traces: cached.trades, rate: cached.rate, loading: false, error: null, stale: false })
    }
    props.traces().then((result: any) => {
      if (!alive) return
      const fresh = {
        workspaceKey: result.workspaceKey,
        signature: result.signature,
        trades: result.trades,
        rate: result.rate,
        fetchedAt: Date.now(),
      }
      const unchanged = cached !== null
        && cached.workspaceKey === fresh.workspaceKey
        && cached.signature === fresh.signature
      traceCache = fresh
      if (unchanged) return // 已同步渲染同一份数据,跳过重渲染
      setData({ traces: result.trades, rate: result.rate, loading: false, error: null, stale: false })
    }, (error: any) => {
      if (!alive) return
      if (traceCache) setData((c) => ({ ...c, stale: true }))
      else setData({ traces: [], rate: null, loading: false, error: String(error && error.message ? error.message : error), stale: false })
    })
    return () => { alive = false }
  }, [props.sessionId])

  // 滚动位置:存进官方 store,列表渲染后恢复,滚动时回写。
  useEffect(() => {
    if (data.loading) return
    const el = document.querySelector('.dmt') as HTMLElement | null
    if (!el) return
    let scroller: HTMLElement = el
    while (scroller.parentElement && scroller.scrollHeight <= scroller.clientHeight + 1) {
      scroller = scroller.parentElement as HTMLElement
    }
    if (ui.scrollTop > 0 && scroller.scrollHeight > scroller.clientHeight + 1) {
      scroller.scrollTop = ui.scrollTop
    }
    const onScroll = () => { acts.setScrollTop(scroller.scrollTop) }
    scroller.addEventListener('scroll', onScroll, { passive: true })
    return () => { scroller.removeEventListener('scroll', onScroll) }
  }, [data.loading])

  if (data.error) return h('div', { className: 'dmt' }, h('div', { className: 'empty' }, 'Decision Mind: ' + data.error))
  if (data.loading) return h('div', { className: 'dmt' },
    h('div', { className: 'top' },
      h('div', { className: 'tt' }, '决策轨迹'),
      h('div', { className: 'ts' }, '真实成交 × 决策账本 × T+1 结果')),
    h('div', { className: 'list' },
      h(SkeletonRow, { key: 'sk1' }),
      h(SkeletonRow, { key: 'sk2' }),
      h(SkeletonRow, { key: 'sk3' })))

  const traces = data.traces.map(_displayEntry)
  let filtered = traces.slice()
  if (ui.filter === 'miss') filtered = filtered.filter((t: any) => !t.decision)
  if (ui.filter === 'sold') filtered = filtered.filter((t: any) => t.action === 'sell')
  if (ui.filter === 'dec') filtered = filtered.filter((t: any) => t.decision)

  const usd = traces.filter((t: any) => t.realizedPnl != null && t.currency === 'USD').reduce((s: number, t: any) => s + t.realizedPnl, 0)
  const hkd = traces.filter((t: any) => t.realizedPnl != null && t.currency === 'HKD').reduce((s: number, t: any) => s + t.realizedPnl, 0)
  const fx = data.rate
  const totalUsd = usd + (fx ? hkd / fx : 0)
  const fw = traces.filter((t: any) => t.t1 && t.t1.verdict === '卖飞').length
  const ok = traces.filter((t: any) => t.t1 && t.t1.verdict === '卖对').length
  const matched = traces.filter((t: any) => t.decision).length

  const groups: Record<string, any[]> = {}
  filtered.forEach((t: any) => { const k = (t.date || '').slice(0, 10); (groups[k] = groups[k] || []).push(t) })
  const dates = Object.keys(groups).sort().reverse()

  const todayIso = (() => { const n = new Date(); return n.getFullYear() + '-' + String(n.getMonth() + 1).padStart(2, '0') + '-' + String(n.getDate()).padStart(2, '0') })()
  function rel(iso: string) {
    if (iso === todayIso) return '今天'
    const y = (d: string) => new Date(d + 'T00:00:00')
    const diff = Math.round((y(todayIso).getTime() - y(iso).getTime()) / 86400000)
    if (diff === 1) return '昨天'
    if (diff >= 2 && diff <= 7) return diff + '天前'
    return parseInt(iso.slice(5, 7)) + '月' + parseInt(iso.slice(8, 10)) + '日'
  }

  // Batch reveal + per-day accordion (plan #702 Phase 2): the newest
  // TRACE_FOLD_GROUPS date groups render expanded; older days load in
  // batches behind "show earlier" (trajectory loadOlder, same shape),
  // and any day header folds its rows — so "see everything" never means
  // one 100-cell wall at once. Stats stay computed over ALL fills.
  const TRACE_FOLD_GROUPS = 3
  const BATCH_GROUPS = 5
  const visibleDates = dates.slice(0, ui.visibleDateCount)
  const moreFills = dates.slice(ui.visibleDateCount, ui.visibleDateCount + BATCH_GROUPS)
    .reduce((sum: number, d: string) => sum + groups[d]!.length, 0)

  function renderDate(date: string) {
    const folded = ui.foldedDates.indexOf(date) >= 0
    return h('div', { key: date },
      h('div', {
        className: 'day fold',
        role: 'button',
        tabIndex: 0,
        'aria-expanded': folded ? 'false' : 'true',
        onClick: () => { acts.toggleDate(date) },
        onKeyDown: (e: any) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); acts.toggleDate(date) } },
      },
        h('span', { className: 'chev' }, folded ? '▸' : '▾'),
        rel(date),
        h('span', null, date),
        h('span', { className: 'n' }, groups[date]!.length)),
      folded ? null : groups[date]!.map((t: any, idx: number) => {
        // 下标兜底:ticker+date+shares 在同股同日同量时会撞 key。
        const key = t.ticker + t.date + t.shares + ':' + idx
        return h(TraceCell, {
          key,
          trace: t,
          open: ui.open === key,
          onToggle: () => { acts.toggleOpen(key) },
          onKeyDown: (e: any) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); acts.toggleOpen(key) } },
        })
      }))
  }

  let moreBtn: any = null
  if (visibleDates.length < dates.length) {
    moreBtn = h('button', { key: 'more', className: 'trace-more', onClick: () => { acts.showMoreDates(BATCH_GROUPS) } },
      '显示更早的 ' + moreFills + ' 笔成交')
  } else if (ui.visibleDateCount > TRACE_FOLD_GROUPS) {
    moreBtn = h('button', { key: 'more', className: 'trace-more', onClick: () => { acts.resetDates() } },
      '收起,只显示最近 ' + TRACE_FOLD_GROUPS + ' 组')
  }

  let body: any
  if (!filtered.length) body = h('div', { className: 'empty' }, '没有符合条件的成交')
  else {
    const kids = visibleDates.map(renderDate)
    if (moreBtn) kids.push(moreBtn)
    body = h('div', null, kids)
  }

  const stats = h('div', { className: 'stats' },
    h('div', { className: 'sg' }, h('span', { className: 'sl' }, '已实现 (USD 等值)'),
      h('span', { className: 'sv focus ' + (totalUsd >= 0 ? 'up' : 'down') }, fmtMoney(totalUsd))),
    h('div', { className: 'sg' }, h('span', { className: 'sl' }, 'T+1 卖飞/卖对'),
      h('span', { className: 'sv' }, h('span', { className: 'down' }, fw), ' / ', h('span', { className: 'up' }, ok))),
    h('div', { className: 'sg' }, h('span', { className: 'sl' }, '决策挂接'), h('span', { className: 'sv' }, matched + '/' + traces.length)),
    fx ? h('span', { className: 'rate' }, traces.length + ' 笔成交 · @' + fx) : h('span', { className: 'rate' }, traces.length + ' 笔成交'))

  const filters = h('div', { className: 'filters' },
    ['all', 'miss', 'sold', 'dec'].map((f) => {
      const label = { all: '全部', miss: '无决策', sold: '卖出复盘', dec: '挂接决策' }[f]
      return h('button', { key: f, className: 'ft' + (ui.filter === f ? ' on' : ''), onClick: () => { acts.setFilter(f) } }, label)
    }))

  return h('div', { className: 'dmt' },
    h('div', { className: 'top' },
      h('div', { className: 'tt' }, '决策轨迹'),
      h('div', { className: 'ts' }, '真实成交 × 决策账本 × T+1 结果' + (data.stale ? ' · 更新失败,显示此前快照' : '')),
      stats,
      filters),
    h('div', { className: 'list' }, body))
}

/** Services required by the registration and the mounted Remote face. */
export const inject = ['slots', 'remote']

/**
 * Per-session UI state that survives tab unmounts: the ring remounts the
 * view on every switch (`only: active.id`), so open row / filter / batch /
 * folded days / scroll position must live in the official registration store
 * (kept alive for the registration's lifetime), not in component state.
 */
const decisionMindStore = defineStore({
  init: () => ({ filter: 'all', open: null, visibleDateCount: 3, foldedDates: [], scrollTop: 0 } as StoreState),
  actions: {
    setFilter: (draft: StoreState, value: string) => { draft.filter = value },
    toggleOpen: (draft: StoreState, key: string) => { draft.open = draft.open === key ? null : key },
    showMoreDates: (draft: StoreState, count: number) => { draft.visibleDateCount = draft.visibleDateCount + count },
    resetDates: (draft: StoreState) => { draft.visibleDateCount = 3 },
    toggleDate: (draft: StoreState, date: string) => {
      draft.foldedDates = draft.foldedDates.indexOf(date) >= 0
        ? draft.foldedDates.filter((d) => d !== date)
        : draft.foldedDates.concat([date])
    },
    setScrollTop: (draft: StoreState, value: number) => { draft.scrollTop = value },
  },
})

/**
 * Module-level data cache (lives with the module, i.e. across tab mounts):
 * the last fetched trace result keyed by the host's opaque workspaceKey.
 * A mount renders this synchronously — no loading frame — and re-fetches in
 * the background; the host answers a signature hit in µs (its own cache),
 * and an unchanged signature skips the re-render. Single-workspace
 * assumption; a mismatched key is simply a miss.
 */
let traceCache: { workspaceKey: string; signature: string; trades: any[]; rate: number | null; fetchedAt: number } | null = null

/** Client contribution context: the face the slot renderer hands us. */
interface ClientContributionContext {
  slots: any
  remote: TypertClientRemote
  get: (name: string) => any
  inject?: (deps: readonly string[], cb: (scope: any) => void) => any
}

/** Register the Decision Mind tab into the conversation view ring. */
export async function apply(ctx: Context & ClientContributionContext): Promise<void> {
  await ctx.remote.$mount(TYPERT_REMOTE as TypertRemoteContribution)
  const studioRemote = ctx.get('remote.clawockStudio')
  ctx.slots.inject('conversation.view', () => ctx.slots.register({
    name: 'conversation.view',
    id: 'decision-studio',
    order: 30,
    label: () => 'Decision Mind',
    store: decisionMindStore,
    inject: () => {
      const call = async (method: string, args?: any[]): Promise<any> => {
        const result = await studioRemote[method].apply(studioRemote, args || [])
        if (!result.ok) {
          throw new Error('clawockStudio.' + method + ' failed: ' + result.error.code + ': ' + result.error.message)
        }
        return result.value
      }
      return {
        traces: () => call('traces'),
        ledger: () => call('ledger'),
        portfolio: () => call('portfolio'),
        get: (runId: string) => call('get', [runId]),
      }
    },
  }, DecisionMind))
}
