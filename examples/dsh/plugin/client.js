/**
 * clawock-dsh browser bundle: the Decision Mind conversation-view tab.
 *
 * Shows whatever the OpenClaw desk produced — the shared decision ledger
 * (memory/decisions.jsonl), the portfolio, and recent daily plans — through
 * read-only Typert remotes. Hand-authored module-loader factory, no build
 * step. Visual language: restrained DSH-native light theme (ui-theme token
 * values), glass only on the sticky header, DeepSeek blue as the single
 * accent, semantic tints for pos/neg/warn.
 */
window.__ModuleLoader__.load({
  id: 'clawock-dsh',
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports
    var clientRuntime = require('@deepseek-ai/dsh-client-runtime/client')
    var React = require('react')
    var useEffect = React.useEffect
    var useState = React.useState
    var h = React.createElement

    // CSS injection lives in the factory closure (module-loader convention).
    var STYLE_ID = 'clawock-dsh-styles'
    if (!document.getElementById(STYLE_ID)) {
      var style = document.createElement('style')
      style.id = STYLE_ID
      style.textContent = [
        '.dml{--bg:#F9FAFB;--surface:#FFFFFF;--surface2:#F5F6F7;--text:#0F1115;--text2:#81858C;--text3:#ADB2B8;',
        '--brand:#4176E6;--brand-deep:#4868B2;--brand-soft:#EDF3FE;--border-l1:rgba(0,0,0,.04);--border-l2:rgba(0,0,0,.10);--border-card:rgba(0,0,0,.08);',
        '--hover:rgba(38,49,72,.06);--active:rgba(38,49,72,.12);',
        '--pos:#1E9E6C;--pos-soft:#E6FAED;--neg:#D64550;--neg-soft:#FEF2F2;--warn:#B77B16;--warn-soft:#FEF5E7;',
        '--shadow-lv2:0 4px 12px rgba(0,0,0,.02),0 2px 8px rgba(0,0,0,.04);--shadow-lv3:0 0 1px rgba(0,0,0,.2),0 0 4px rgba(0,0,0,.02),0 12px 32px rgba(0,0,0,.08);',
        '--radius-lg:14px;--radius-md:10px;--radius-sm:8px;--radius-pill:999px;',
        '--font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;',
        '--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;',
        'font:14px/1.55 var(--font);color:var(--text);-webkit-font-smoothing:antialiased;padding:4px 2px;',
        'background-image:radial-gradient(900px 300px at 50% -120px,rgba(65,118,230,.05),transparent 70%)}',
        '.dml .head{position:sticky;top:0;z-index:5;margin:-4px -2px 0;padding:12px 14px 10px;',
        'background:linear-gradient(180deg,rgba(249,250,251,.9),rgba(249,250,251,.72));',
        '-webkit-backdrop-filter:blur(20px);backdrop-filter:blur(20px);border-bottom:1px solid var(--border-l1)}',
        '.dml .title{display:flex;align-items:baseline;gap:10px;margin-bottom:10px}',
        '.dml .title h3{margin:0;font-size:16px;font-weight:700;letter-spacing:-.01em}',
        '.dml .title span{color:var(--text3);font-size:12px}',
        '.dml .seg{display:inline-flex;padding:2px;background:var(--surface2);border:1px solid var(--border-l2);border-radius:var(--radius-pill)}',
        '.dml .seg button{border:0;background:transparent;color:var(--text2);font-size:12.5px;font-weight:600;padding:4px 14px;border-radius:var(--radius-pill);cursor:pointer;transition:background .15s,color .15s}',
        '.dml .seg button:hover{background:var(--hover)}',
        '.dml .seg button.on{background:var(--surface);color:var(--brand);box-shadow:var(--shadow-lv2)}',
        '.dml .day{margin:18px 0 8px;color:var(--text3);font-size:11.5px;font-weight:700;letter-spacing:.06em;display:flex;align-items:center;gap:8px}',
        '.dml .day::after{content:"";flex:1;height:1px;background:linear-gradient(90deg,rgba(65,118,230,.2),transparent)}',
        '.dml .card{margin:8px 0;border:1px solid var(--border-card);border-radius:var(--radius-md);background:var(--surface);box-shadow:var(--shadow-lv2);overflow:hidden;transition:border-color .15s}',
        '.dml .card:hover{border-color:var(--border-l2)}',
        '.dml .row{display:flex;align-items:center;gap:10px;padding:12px 14px;cursor:pointer;transition:background .15s}',
        '.dml .row:hover{background:var(--hover)}.dml .row:active{background:var(--active)}.dml .row:focus-visible{outline:2px solid var(--brand);outline-offset:-2px}',
        '.dml .tk{font-weight:700;font-size:14px;min-width:118px}',
        '.dml .chip{display:inline-flex;align-items:center;gap:4px;padding:2px 10px;border-radius:var(--radius-pill);font-size:11.5px;font-weight:600}',
        '.dml .chip.add{color:var(--pos);background:var(--pos-soft)}.dml .chip.trim{color:var(--neg);background:var(--neg-soft)}',
        '.dml .chip.reject{color:var(--text2);background:var(--surface2)}.dml .chip.emo{color:var(--warn);background:var(--warn-soft)}',
        '.dml .chip.ok{color:var(--pos);background:var(--pos-soft)}.dml .chip.warn{color:var(--warn);background:var(--warn-soft)}',
        '.dml .chip.gray{color:var(--text3);background:var(--surface2)}',
        '.dml .conf{margin-left:auto;color:var(--text2);font-size:12px;font-family:var(--mono);font-variant-numeric:tabular-nums}',
        '.dml .chev{color:var(--text3);font-size:10px;transition:transform .18s}',
        '.dml .open .chev{transform:rotate(180deg)}',
        '.dml .detail{display:none;border-top:1px solid var(--border-l1);padding:16px;background:var(--bg)}',
        '.dml .open .detail{display:block}',
        '.dml .sec{font-size:11px;font-weight:700;letter-spacing:.08em;color:var(--text3);text-transform:uppercase;margin:14px 0 8px}',
        '.dml .sec:first-child{margin-top:0}',
        '.dml .vs{display:grid;grid-template-columns:1fr 1fr;gap:12px}',
        '.dml .side{padding:12px 14px;border-radius:var(--radius-sm);border:1px solid var(--border-l2)}',
        '.dml .side.bull{background:var(--pos-soft);border-color:rgba(30,158,108,.3)}',
        '.dml .side.bear{background:var(--neg-soft);border-color:rgba(214,69,80,.3)}',
        '.dml .side b{font-size:11px;letter-spacing:.08em;text-transform:uppercase}',
        '.dml .side.bull b{color:var(--pos)}.dml .side.bear b{color:var(--neg)}',
        '.dml .side p{margin:7px 0 4px;font-size:13px;color:var(--text)}',
        '.dml .side .src{color:var(--text3);font-size:12px}',
        '.dml .meter{height:8px;border-radius:var(--radius-pill);background:var(--border-l2);overflow:hidden;margin:8px 0 4px}',
        '.dml .meter>div{height:100%;border-radius:var(--radius-pill);background:linear-gradient(90deg,var(--brand-deep),var(--brand))}',
        '.dml .kv{display:flex;justify-content:space-between;gap:14px;padding:6px 0;border-bottom:1px solid var(--border-l1);font-size:13px}',
        '.dml .kv span{color:var(--text3);flex-shrink:0}.dml .kv:last-child{border-bottom:none}',
        '.dml ul.inv{margin:6px 0 0;padding-left:18px;color:var(--text2);font-size:13px}',
        '.dml ul.inv li{margin:3px 0}',
        '.dml .emo-note{margin-top:12px;padding:10px 14px;border-radius:var(--radius-sm);background:var(--warn-soft);border-left:3px solid var(--warn);font-size:13px;color:var(--text2)}',
        '.dml .acc{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px}',
        '.dml .stat{padding:10px 12px;border:1px solid var(--border-l2);border-radius:var(--radius-sm);background:var(--surface)}',
        '.dml .stat span{display:block;color:var(--text3);font-size:11px}.dml .stat b{font-size:13px;font-weight:600}',
        '.dml .okb{color:var(--pos)}.dml .negb{color:var(--neg)}.dml .warnb{color:var(--warn)}.dml .grayb{color:var(--text2)}',
        '.dml .mono{font-family:var(--mono);font-size:12px;color:var(--text2)}',
        '.dml table{width:100%;border-collapse:collapse;font-size:13px}',
        '.dml th{color:var(--text3);font-weight:600;text-align:left;padding:6px 10px;border-bottom:1px solid var(--border-l2);font-size:11.5px}',
        '.dml td{padding:7px 10px;border-bottom:1px solid var(--border-l1);font-variant-numeric:tabular-nums}',
        '.dml td.num{text-align:right;font-family:var(--mono);font-size:12.5px}',
        '.dml .pos{color:var(--pos)}.dml .neg{color:var(--neg)}.dml .row .pnl{font-size:12.5px}',
        '.dml .book{margin:12px 0}',
        '.dml .book h4{margin:0 0 8px;font-size:13px;font-weight:700;color:var(--text2)}',
        '.dml .plan{margin:8px 0;padding:12px 14px;border:1px solid var(--border-card);border-radius:var(--radius-md);background:var(--surface);box-shadow:var(--shadow-lv2)}',
        '.dml .plan .d{font-weight:700;font-size:13.5px;font-family:var(--mono)}',
        '.dml .plan .n{color:var(--text3);font-size:12.5px;margin-left:10px}',
        '.dml .empty{padding:26px 14px;text-align:center;color:var(--text3);font-size:13px}',
        '@media (max-width:390px){',
        '.dml .row{flex-wrap:wrap;min-height:44px}',
        '.dml .pnl{flex-basis:100%;font-size:17px}',
        '.dml .row .pnl{font-size:17px}',
        '.dml .conf{flex-basis:100%;margin-left:0}',
        '}',
      ].join('')
      document.head.appendChild(style)
    }

    /** Pure projection of one ledger entry into display fields (test seam). */
    function _displayEntry(entry) {
      var subject = entry.subject || {}
      var mind = entry.mind || {}
      var emotion = entry.emotion || {}
      var evaluation = entry.evaluation || {}
      var execution = entry.execution || {}
      return {
        id: entry.decision_id || null,
        ticker: subject.ticker || entry.ticker || '?',
        date: entry.decided_at || entry.plan_date || null,
        action: entry.action || 'hold',
        confidence: entry.confidence ?? null,
        drivenBy: entry.driven_by || null,
        source: entry.source || 'brief',
        bull: mind.bull && mind.bull.summary ? mind.bull.summary : null,
        bear: mind.bear && mind.bear.summary ? mind.bear.summary : null,
        thesis: mind.thesis || null,
        invalidation: Array.isArray(mind.invalidation) ? mind.invalidation : [],
        emotion: emotion.pressure || null,
        emotionNote: emotion.note || null,
        condition: entry.condition && entry.condition.description ? entry.condition.description : null,
        executionStatus: execution.status || null,
        outcome: evaluation.outcome || null,
        rationale: typeof entry.rationale === 'string' ? entry.rationale : null,
        market: subject.market || (entry.leg === 'US' ? 'US' : /^\d/.test(entry.ticker || '') ? 'HK' : 'US'),
        sizeShares: (entry.size && entry.size.shares) || null,
        sizePct: (entry.size && entry.size.pct) || null,
        // Real fill price beats the plan's simulation; flag when only the plan price exists.
        entryPrice: evaluation.execution_price ?? entry.simulated_entry_price ?? null,
        planPrice: evaluation.execution_price == null && entry.simulated_entry_price != null,
        capital: evaluation.capital || null,
      }
    }

    var ACTION_LABELS = {
      buy: '买入', add: '加仓', trim: '减仓', sell: '卖出', cut: '割肉',
      hold_and_watch: '持有观望', trim_on_rebound: '反弹减仓', t_only: '仅T+0', add_only_on_trigger: '触发加仓',
      reject: '不加', watch: '观望', hold: '持有', abstain: '弃权',
    }
    function actionLabel(action) { return ACTION_LABELS[action] || String(action) }

    /** Explicit outcome → tone map: only win is positive; loss/flat are negative. */
    function outcomeTone(outcome) {
      if (outcome === 'win') return 'ok'
      if (outcome === 'loss' || outcome === 'flat') return 'neg'
      return 'gray' // not_triggered | unknown | pending | missing
    }

    function Chip(props) {
      return h('span', { className: 'chip ' + props.tone }, props.children)
    }

    var ACTIVE_ACTIONS = ['add', 'buy', 'trim', 'sell', 'cut', 't_only', 'trim_on_rebound', 'add_only_on_trigger']

    function ActionChip(action) {
      var tone = action === 'add' || action === 'buy' ? 'add'
        : ACTIVE_ACTIONS.indexOf(action) >= 0 ? 'trim'
        : action === 'reject' || action === 'watch' || action === 'hold' || action === 'abstain' ? 'reject'
        : 'gray'
      return h(Chip, { tone: tone }, actionLabel(action))
    }

    function LedgerCard(props) {
      var d = props.entry
      var expanded = props.open
      var currentPnl = props.currentPnl
      var sizeText = null
      if (d.sizeShares) {
        var amount = d.sizeShares * (d.entryPrice || 0)
        var sym = d.market === 'HK' ? 'HK$' : '$'
        sizeText = d.sizeShares + ' 股' + (d.entryPrice ? ' @' + d.entryPrice + (d.planPrice ? ' (计划价)' : '') + (amount ? ' ≈' + sym + Math.round(amount).toLocaleString() : '') : '')
      } else if (d.sizePct) {
        sizeText = (d.sizePct * 100).toFixed(0) + '% 仓位'
      }
      var why = d.thesis || d.rationale || (d.bull ? d.bull.slice(0, 48) : null)
      if (why && why.length > 60) why = why.slice(0, 57) + '…'
      var pnl = props.currentPnl
      var tone = outcomeTone(d.outcome)
      return h('div', { className: 'card' + (expanded ? ' open' : '') },
        h('div', { className: 'row', role: 'button', tabIndex: 0, 'aria-expanded': expanded, onClick: props.onToggle },
          h('span', { className: 'tk' }, d.ticker),
          ActionChip(d.action),
          sizeText ? h('span', { className: 'mono', style: { color: 'var(--text2)' } }, sizeText) : null,
          d.emotion && d.emotion !== 'calm' ? h(Chip, { tone: 'emo' }, '⚡ ' + d.emotion) : null,
          h('span', { className: 'conf' }, (d.confidence ?? '—') + (d.drivenBy ? ' · ' + d.drivenBy : '')),
          h('span', { className: 'chev' }, '▾')),
        h('div', { style: { padding: '0 14px 10px', fontSize: 12.5, color: 'var(--text2)', display: 'flex', gap: 12, flexWrap: 'wrap' } },
          why ? h('span', null, '为什么: ' + why) : null,
          pnl !== null ? h('span', { className: 'pnl ' + (pnl < 0 ? 'neg' : 'pos') }, '现盈亏 ' + (pnl > 0 ? '+' : '') + pnl.toFixed(1) + '%') : null,
          d.outcome ? h('span', { className: tone === 'ok' ? 'pos' : tone === 'neg' ? 'neg' : 'grayb' }, 'outcome ' + d.outcome) : null),
        h('div', { className: 'detail' },
          d.bull || d.bear ? h('div', { className: 'vs' },
            h('div', { className: 'side bull' }, h('b', null, 'Bull'), h('p', null, d.bull || '—'), h('div', { className: 'src' }, 'evidence · decision time')),
            h('div', { className: 'side bear' }, h('b', null, 'Bear'), h('p', null, d.bear || '—'), h('div', { className: 'src' }, 'opposing · mandatory'))) : null,
          d.thesis ? h('div', { className: 'sec' }, 'Thesis') : null,
          d.thesis ? h('div', { className: 'kv' }, h('span', null, 'thesis'), h('b', null, d.thesis)) : null,
          d.confidence !== null ? h('div', { className: 'kv' }, h('span', null, 'confidence'), h('b', { className: 'mono' }, String(d.confidence))) : null,
          d.confidence !== null ? h('div', { className: 'meter' }, h('div', { style: { width: (d.confidence > 0 ? Math.max(4, Math.min(100, d.confidence * 100)) : 0) + '%' } })) : null,
          d.invalidation.length ? h('div', { className: 'sec' }, '可证伪条件') : null,
          d.invalidation.length ? h('ul', { className: 'inv' }, d.invalidation.map(function (c, i) { return h('li', { key: i }, c) })) : null,
          d.emotionNote ? h('div', { className: 'emo-note' }, '⚡ ' + d.emotionNote) : null,
          d.condition || d.executionStatus || d.outcome ? h('div', { className: 'sec' }, '对账') : null,
          (d.condition || d.executionStatus || d.outcome) ? h('div', { className: 'acc' },
            h('div', { className: 'stat' }, h('span', null, 'condition'), h('b', { className: 'grayb' }, d.condition || '—')),
            h('div', { className: 'stat' }, h('span', null, 'execution'), h('b', { className: d.executionStatus === 'followed' ? 'okb' : 'grayb' }, d.executionStatus || '—')),
            h('div', { className: 'stat' }, h('span', null, 'outcome'), h('b', { className: tone === 'ok' ? 'okb' : tone === 'neg' ? 'negb' : 'grayb' }, d.outcome || '—'))) : null))
    }

    function LedgerView(props) {
      var entries = props.entries
      if (!entries.length) return h('div', { className: 'empty' }, props.filterLabel === 'all' ? '账本为空 — 对话判定或盘前决策会出现在这里' : '暂无已执行的交易样本 — 切到「全部」可看全部记录')
      var groups = {}
      var order = []
      for (var i = entries.length - 1; i >= 0; i -= 1) {
        var d = entries[i]
        var key = (d.date || '').slice(0, 10) || 'unknown'
        if (!groups[key]) { groups[key] = []; order.push(key) }
        groups[key].push(d)
      }
      var pnlByTicker = {}
      for (var bi = 0; bi < (props.books || []).length; bi += 1) {
        var bookMarket = /^hk/i.test(props.books[bi].name || '') ? 'HK' : 'US'
        var bh = (props.books[bi].holdings || [])
        for (var hi = 0; hi < bh.length; hi += 1) {
          if (bh[hi].pnlPct !== null) pnlByTicker[bookMarket + ':' + bh[hi].ticker] = bh[hi].pnlPct
        }
      }
      var hasConversation = entries.some(function (e) { return e.source === 'conversation' })
      return h('div', null, order.map(function (key) {
        return h('div', { key: key },
          h('div', { className: 'day' }, key + (hasConversation ? ' · 对话' : '')),
          groups[key].map(function (d) {
            return h(LedgerCard, {
              key: d.id || d.ticker + key,
              entry: d,
              currentPnl: pnlByTicker[d.market + ':' + d.ticker] ?? pnlByTicker[d.ticker] ?? null,
              open: props.selected === d.id,
              onToggle: function () { props.onSelect(props.selected === d.id ? null : d.id) },
            })
          }))
      }))
    }

    function PortfolioView(props) {
      var books = props.books
      if (!books.length) return h('div', { className: 'empty' }, 'portfolio.json 未找到或为空')
      return h('div', null, books.map(function (book) {
        return h('div', { className: 'book card', key: book.name },
          h('div', { style: { padding: '12px 14px', borderBottom: '1px solid var(--border-l1)' } },
            h('span', { style: { fontWeight: 700 } }, book.name),
            h('span', { className: 'mono', style: { marginLeft: 10 } }, book.currency || '')),
          h('div', { style: { overflowX: 'auto' } },
            h('table', null,
              h('thead', null, h('tr', null,
                h('th', null, 'ticker'), h('th', { style: { textAlign: 'right' } }, 'shares'),
                h('th', { style: { textAlign: 'right' } }, 'price'), h('th', { style: { textAlign: 'right' } }, 'pnl%'))),
              h('tbody', null, book.holdings.map(function (hl) {
                return h('tr', { key: hl.ticker },
                  h('td', null, hl.ticker),
                  h('td', { className: 'num' }, String(hl.shares)),
                  h('td', { className: 'num' }, hl.price !== null ? String(hl.price) : '—'),
                  h('td', { className: 'num ' + (hl.pnlPct !== null && hl.pnlPct < 0 ? 'neg' : 'pos') },
                    hl.pnlPct !== null ? (hl.pnlPct > 0 ? '+' : '') + hl.pnlPct.toFixed(1) + '%' : '—'))
              })))))
      }))
    }

    function tradeLabel(trade, firstBuy) {
      if (trade.action === 'buy') return firstBuy ? '买入' : '加仓'
      if (trade.action === 'sell') {
        if (trade.note && trade.note.indexOf('清仓') >= 0) return '清仓'
        if (trade.note && trade.note.indexOf('减仓') >= 0) return '减仓'
        return '卖出'
      }
      return String(trade.action)
    }

    /** Actual operations: the real fills recorded in the portfolio trade ledger. */
    function TradeView(props) {
      var trades = props.trades || []
      if (!trades.length) return h('div', { className: 'empty' }, '还没有操作记录 — 成交会出现在这里')
      var firstBuys = {}
      for (var i = trades.length - 1; i >= 0; i -= 1) {
        var k = trades[i].market + ':' + trades[i].ticker
        if (trades[i].action === 'buy' && !firstBuys[k]) firstBuys[k] = trades[i].date
      }
      return h('div', null, trades.map(function (tr) {
        var sym = tr.market === 'HK' ? 'HK$' : '$'
        var amount = tr.shares && tr.price ? Math.round(tr.shares * tr.price).toLocaleString() : null
        var label = tradeLabel(tr, tr.date === firstBuys[tr.market + ':' + tr.ticker])
        var note = tr.note && tr.note.length > 90 ? tr.note.slice(0, 87) + '…' : tr.note
        return h('div', { className: 'card', key: tr.ticker + tr.date + tr.shares },
          h('div', { className: 'row', style: { cursor: 'default' } },
            h('span', { className: 'tk' }, tr.ticker),
            h(Chip, { tone: tr.action === 'buy' ? 'add' : 'trim' }, label),
            h('span', { className: 'mono', style: { color: 'var(--text2)' } },
              tr.shares + ' 股 @' + tr.price + (amount ? ' ≈' + sym + amount : '')),
            tr.realizedPnl !== null
              ? h('span', { className: 'pnl ' + (tr.realizedPnl < 0 ? 'neg' : 'pos'), style: { fontFamily: 'var(--mono)' } },
                  (tr.realizedPnl >= 0 ? '+' : '') + tr.realizedPnl.toFixed(2))
              : null,
            h('span', { className: 'conf' }, tr.date || ''),
            h('span', { className: 'chev' }, '')),
          note ? h('div', { style: { padding: '0 14px 10px', fontSize: 12, color: 'var(--text3)' } }, note) : null)
      }))
    }

    /** The conversation-view tab: desk data (operations / ledger / portfolio). */
    function DecisionMind(props) {
      var pair = useState({ view: 'ops', filter: 'trades', selected: null, ledger: [], portfolio: { books: [] }, loading: true, error: null })
      var state = pair[0]
      var setState = pair[1]
      var sessionId = props.sessionId
      useEffect(function () {
        var alive = true
        setState(function (c) { return Object.assign({}, c, { loading: true, error: null }) })
        Promise.all([props.ledger(), props.portfolio()]).then(function (results) {
          if (!alive) return
          setState(function (c) { return Object.assign({}, c, { ledger: results[0].entries, portfolio: results[1], loading: false }) })
        }, function (error) {
          if (!alive) return
          setState(function (c) { return Object.assign({}, c, { error: String(error && error.message ? error.message : error), loading: false }) })
        })
        return function () { alive = false }
      }, [sessionId])

      if (state.error) return h('div', { className: 'dml' }, h('div', { className: 'card' }, h('span', { style: { color: 'var(--neg)' } }, 'Decision Mind: ' + state.error)))
      var allEntries = state.ledger.map(_displayEntry)
      var entries = allEntries.filter(function (d) {
        if (state.filter === 'all') return true
        return d.executionStatus === 'followed' && ACTIVE_ACTIONS.indexOf(d.action) >= 0
      })
      var tradesCount = allEntries.filter(function (d) {
        return d.executionStatus === 'followed' && ACTIVE_ACTIONS.indexOf(d.action) >= 0
      }).length

      var body
      if (state.loading) body = h('div', { className: 'empty' }, 'Loading desk data…')
      else if (state.view === 'ops') body = h(TradeView, { trades: state.portfolio.trades })
      else if (state.view === 'ledger') body = h(LedgerView, { entries: entries, books: state.portfolio.books, filterLabel: state.filter, selected: state.selected, onSelect: function (id) { setState(function (c) { return Object.assign({}, c, { selected: id }) }) } })
      else body = h(PortfolioView, { books: state.portfolio.books })

      return h('div', { className: 'dml' },
        h('div', { className: 'head' },
          h('div', { className: 'title' },
            h('h3', null, '决策心智'),
            h('span', null,
              state.view === 'ops' ? '操作 ' + (state.portfolio.trades || []).length + ' 笔'
              : state.view === 'ledger' ? '显示 ' + entries.length + ' / 共 ' + allEntries.length + ' 条'
              : '持仓 ' + (state.portfolio.books || []).length + ' 组')),
          h('div', { className: 'seg' },
            h('button', { className: state.view === 'ops' ? 'on' : '', onClick: function () { setState(function (c) { return Object.assign({}, c, { view: 'ops' }) }) } }, '操作'),
            h('button', { className: state.view === 'ledger' ? 'on' : '', onClick: function () { setState(function (c) { return Object.assign({}, c, { view: 'ledger' }) }) } }, '账本'),
            h('button', { className: state.view === 'portfolio' ? 'on' : '', onClick: function () { setState(function (c) { return Object.assign({}, c, { view: 'portfolio' }) }) } }, '持仓')),
          state.view === 'ledger' ? h('div', { className: 'seg', style: { marginLeft: 8 } },
            h('button', { className: state.filter === 'trades' ? 'on' : '', onClick: function () { setState(function (c) { return Object.assign({}, c, { filter: 'trades' }) }) } }, '已执行交易 ' + tradesCount),
            h('button', { className: state.filter === 'all' ? 'on' : '', onClick: function () { setState(function (c) { return Object.assign({}, c, { filter: 'all' }) }) } }, '全部 ' + allEntries.length)) : null),
        body)
    }

    /** Minimal strict codecs (no zod external in the module table). */
    var passthroughSchema = { parse: function (value) { return value } }

    function remoteDescriptor(method) {
      return {
        id: 'clawock-dsh#clawockStudio/' + method,
        service: 'clawockStudio',
        namespace: 'clawockStudio',
        method: method,
        invocation: { kind: 'direct' },
        parameters: [],
        result: { mode: 'strict', typeSymbol: 'clawock-dsh#clawockStudio/' + method + ':result', schema: passthroughSchema },
      }
    }

    /** Client projection of the clawockStudio Remote face, mounted explicitly. */
    var TYPERT_REMOTE = {
      package: 'clawock-dsh',
      descriptors: ['list', 'get', 'ledger', 'portfolio', 'plans'].map(function (m) { return remoteDescriptor(m) }),
    }

    /** Services required by the registration and the mounted Remote face. */
    var inject = ['slots', 'remote']

    /** Register the Decision Mind tab into the conversation view ring. */
    async function apply(ctx) {
      await ctx.remote.$mount(TYPERT_REMOTE)
      var studioRemote = ctx.get('remote.clawockStudio')
      ctx.slots.inject('conversation.view', function () {
        return ctx.slots.register({
          name: 'conversation.view',
          id: 'decision-studio',
          order: 30,
          label: function () { return 'Decision Mind' },
          inject: function () {
            var call = async function (method, args) {
              var result = await studioRemote[method].apply(studioRemote, args || [])
              if (!result.ok) {
                throw new Error('clawockStudio.' + method + ' failed: ' + result.error.code + ': ' + result.error.message)
              }
              return result.value
            }
            return {
              ledger: function () { return call('ledger') },
              portfolio: function () { return call('portfolio') },
            }
          },
        }, DecisionMind)
      })
    }

    module.exports = { apply: apply, inject: inject, _displayEntry: _displayEntry }
    return module.exports
  },
})
