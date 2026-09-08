// Decision Map — 决策 × 做出时的信号快照，一块板 + 一条时间线 + 一个抽屉。
//
// 2026-09-09：这块东西原来是 /decimap/ 一张独立页（顶栏一个 Map）。它读的是
// 「过去的决策与当时的信号」，也就是 Reflect 那一栏在回答的问题，所以它搬进
// 了 Reflect 的一张卡，不再是站外的一页；页面本身留成一个跳转壳，老链接不断。
//
// 加载：Reflect 首次激活时由 dashboard.render.js 注入本文件，payload 走
// dashboard.ui.js 的 sidecar 机制（decision_map → reflect），所以 Overview
// 的首帧既不下这段代码也不下那 167KB。
//
// 抽屉与遮罩挂在 <body> 下、不在面板里：`.panel` 是 content-visibility: auto，
// 那等于 paint containment，会把 position:fixed 的后代锁进面板的盒子里。
(function () {
  'use strict';
  var SELL = { cut: 1, trim_on_rebound: 1, t_only: 1 };
  var BUY = { add_only_on_trigger: 1, add_on_breakout: 1 };
  var HOLD = { hold_and_watch: 1, watch: 1 };
  // 列头印的是账本里的动作键（`add_only_on_trigger`），一行 128px，在手机上
  // 是把格子挤出屏幕的那个东西，读起来也不像中文页面上的一列。中文名做表头、
  // 原键留在 title 里 —— 换个说法，不是换掉一个值。
  var ACTION_CN = {
    add_only_on_trigger: '触发加仓', add_on_breakout: '突破加仓',
    cut: '砍仓', trim_on_rebound: '反弹减仓', t_only: '只做 T',
    hold_and_watch: '持有观察', watch: '观察', reject: '否决',
  };
  function actionCn(action) { return ACTION_CN[action] || action; }
  // 六个信息源的族名同理：`bar` / `setup` 是账本里的键，不是中文页面上的一行
  // 标题。展开后的具体信号仍印原名 —— 那是标识符（`quant.dist_ma200_pct`），
  // 翻译它等于把一个可以去 grep 的东西变成猜谜。
  var KIND_CN = {
    bar: 'K 线', factor: '因子', news: '消息', peer: '同行',
    quant: '量化', setup: '形态',
  };
  function kindCn(kind) { return KIND_CN[kind] || kind; }
  var state = { data: null, horizon: 't5', ticker: '', open: {}, scale: 1 };

  function el(id) { return document.getElementById(id); }
  // Every string interpolated into innerHTML below goes through this. Ticker
  // symbols and action names are ours, but `rationale` is prose an LLM wrote
  // and the payload is fetched at runtime, so nothing here is trusted markup.
  function esc(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function fmt(value, digits) {
    if (value === null || value === undefined || isNaN(value)) return '—';
    return Number(value).toFixed(digits === undefined ? 2 : digits);
  }
  function signed(value, digits) {
    if (value === null || value === undefined || isNaN(value)) return '—';
    return (value >= 0 ? '+' : '') + Number(value).toFixed(digits === undefined ? 2 : digits);
  }
  function pct(value) {
    return value === null || value === undefined ? '—' : (value * 100).toFixed(0) + '%';
  }
  function actionClass(action) {
    if (BUY[action]) return 'is-buy';
    if (SELL[action]) return 'is-sell';
    if (HOLD[action]) return 'is-hold';
    return 'is-other';
  }

  // `decisions[field][i]` is an index into `codes[field]` for the coded
  // columns and a plain value for the rest. One accessor, so no call site has
  // to remember which is which.
  function cell(field, index) {
    var d = state.data, column = d.decisions[field];
    if (!column) return null;
    var raw = column[index];
    var vocabulary = (d.codes || {})[field];
    return vocabulary ? vocabulary[raw] : raw;
  }

  // The board's rows, in tree order: a kind, then its signals when open.
  function boardRows() {
    var d = state.data, out = [];
    (d.source_kind_cards || []).forEach(function (kind) {
      out.push({ card: kind, kind: true, name: kind.signal });
      if (!state.open[kind.signal]) return;
      d.info_source_cards.forEach(function (card) {
        if (card.source_kind === kind.signal) {
          out.push({ card: card, kind: false, name: card.signal });
        }
      });
    });
    return out;
  }

  // The fill scale is a display choice, so it is derived from the data and
  // stated in the legend rather than hard-coded. The 90th percentile of
  // |median|, not the maximum: one bucket of twelve decisions medians −35%,
  // and scaling to it left every other cell on the board colourless. Anything
  // past the cap is clipped to full colour and the legend says so.
  function fillScale(horizon) {
    // Every card, not just the visible rows: a value's colour must not change
    // because some other kind was expanded.
    var d = state.data, magnitudes = [];
    (d.source_kind_cards || []).concat(d.info_source_cards).forEach(function (card) {
      var buckets = card.by_action || {};
      Object.keys(buckets).forEach(function (action) {
        var median = buckets[action]['median_' + horizon + '_pct'];
        if (median !== null && median !== undefined) magnitudes.push(Math.abs(median));
      });
    });
    if (!magnitudes.length) return 1;
    magnitudes.sort(function (a, b) { return a - b; });
    return Math.max(0.5, magnitudes[Math.floor(magnitudes.length * 0.90)] || 1);
  }

  function cellHtml(row, action, horizon) {
    var bucket = (row.card.by_action || {})[action];
    if (!bucket) return '<td class="dm-empty">·</td>';
    var median = bucket['median_' + horizon + '_pct'];
    var settled = bucket['n_' + horizon];
    var weight = 0, pole = '';
    if (median !== null && median !== undefined) {
      weight = Math.min(1, Math.abs(median) / state.scale);
      pole = median >= 0 ? 'var(--dm-pos)' : 'var(--dm-neg)';
    }
    var background = weight
      ? 'background:color-mix(in oklab, ' + pole + ' '
        + (weight * 62).toFixed(1) + '%, var(--card))'
      : '';
    var title = row.name + ' · ' + actionCn(action) + '（' + action + '） · '
      + bucket.count + ' 条决策 · '
      + settled + ' 条已结算 · 中位 ' + horizon + ' ' + signed(median, 2)
      + '% · 胜率 ' + pct(bucket['win_rate_' + horizon]);
    return '<td class="dm-cell" style="' + background + '" tabindex="0" role="button"'
      + ' data-row="' + esc(row.name) + '" data-action="' + esc(action) + '"'
      + ' title="' + esc(title) + '" aria-label="' + esc(title) + '">'
      + '<span class="dm-n">' + bucket.count + '</span>'
      + '<span class="dm-m">' + signed(median, 1) + '</span></td>';
  }

  function icHtml(row, horizon) {
    if (row.kind) {
      return '<td class="dm-ic dm-empty" title="IC 是单个信号在截面上的秩相关，'
        + '按信息源汇总没有定义">·</td>';
    }
    var panel = row.card.panel && row.card.panel[horizon];
    if (!panel) {
      var dropped = (state.data.signal_panel || {}).dropped;
      return '<td class="dm-ic dm-empty" title="'
        + (dropped ? 'payload 降级时丢了，跑 clawock signal-panel 可复现'
                   : '这个信号没有进入过可评分的截面') + '">—</td>';
    }
    var band = panel.ic_cluster_ci95;
    var value = '<span class="dm-icval' + (panel.ic_clears_zero ? ' is-clear' : '')
      + '">' + signed(panel.mean_ic, 3) + '</span>';
    var whisker = '';
    if (band) {
      // One fixed axis for every row: IC lives in [-1, 1] and in practice well
      // inside [-0.5, 0.5], so the bars are comparable down the column.
      var span = 0.5;
      var place = function (point) {
        return Math.max(0, Math.min(100, (point + span) / (2 * span) * 100));
      };
      whisker = '<div class="dm-whisker">'
        + '<i style="left:' + place(band[0]).toFixed(1) + '%;width:'
        + Math.max(1, place(band[1]) - place(band[0])).toFixed(1) + '%"></i>'
        + '<s style="left:50%"></s>'
        + '<u style="left:' + place(panel.mean_ic).toFixed(1) + '%"></u></div>';
    }
    var title = row.name + ' ' + horizon + ' rank IC ' + signed(panel.mean_ic, 4)
      + (band ? ' · 95% CI [' + signed(band[0], 3) + ', ' + signed(band[1], 3) + ']' : '')
      + ' · ' + panel.n_sessions + ' 个交易日 · ' + panel.status;
    return '<td class="dm-ic" title="' + esc(title) + '">' + value + whisker + '</td>';
  }

  function renderBoard() {
    var d = state.data, horizon = state.horizon;
    var actions = d.actions || [];
    var rows = boardRows();
    state.scale = fillScale(horizon);

    var head = '<thead><tr><th class="dm-src">信息源</th>'
      + '<th class="dm-covh">覆盖</th>';
    actions.forEach(function (action) {
      head += '<th title="' + esc(action) + '">' + esc(actionCn(action)) + '</th>';
    });
    head += '<th>IC ' + esc(horizon) + '</th></tr></thead><tbody>';

    var body = '';
    rows.forEach(function (row) {
      var card = row.card;
      var name = row.kind
        ? '<button class="dm-twist" type="button" data-kind="' + esc(row.name) + '"'
          + ' title="' + esc(row.name) + '"'
          + ' aria-expanded="' + (state.open[row.name] ? 'true' : 'false') + '">'
          + '<i>&#9656;</i><span class="dm-kindname">' + esc(kindCn(row.name)) + '</span>'
          + '<span class="dm-count">' + (card.signals || []).length + '</span></button>'
        : '<span class="dm-name">' + esc(row.name) + '</span>';
      body += '<tr class="' + (row.kind ? 'dm-kind' : 'dm-signal') + '">'
        + '<th class="dm-src" scope="row">' + name + '</th>'
        + '<td class="dm-cov" title="' + esc(row.name + ' join 上了 '
            + card.decisions_joined + ' / ' + d.kpi.decisions + ' 条决策；快照年龄 中位 '
            + fmt(card.median_snapshot_age_sessions, 1) + ' / 最大 '
            + fmt(card.max_snapshot_age_sessions, 0) + ' session') + '">'
        + '<div class="dm-covbar"><i style="width:'
        + Math.min(100, card.decision_coverage_pct).toFixed(1) + '%"></i></div>'
        + '<span class="dm-covtext">' + card.decision_coverage_pct.toFixed(1) + '% · '
        + card.decisions_joined + '</span></td>';
      actions.forEach(function (action) { body += cellHtml(row, action, horizon); });
      body += icHtml(row, horizon) + '</tr>';
    });

    el('dm-board').innerHTML = head + body + '</tbody>';

    el('dm-scale').innerHTML =
      '<span class="dm-ramp">'
      + '<span style="background:color-mix(in oklab, var(--dm-neg) 62%, var(--card))"></span>'
      + '<span style="background:color-mix(in oklab, var(--dm-neg) 25%, var(--card))"></span>'
      + '<span style="background:var(--card)"></span>'
      + '<span style="background:color-mix(in oklab, var(--dm-pos) 25%, var(--card))"></span>'
      + '<span style="background:color-mix(in oklab, var(--dm-pos) 62%, var(--card))"></span>'
      + '</span>'
      + '<span>底色 = 中位 ' + esc(horizon) + ' 收益，满色 ≥±'
      + state.scale.toFixed(1) + '%；格里上行是决策条数 n。悬停看已结算条数与胜率。</span>';

    var caveat = (d.signal_panel || {}).interval_caveat;
    var selection = ((d.signal_panel || {}).selection || {})[horizon];
    var text = '这不是因果：一个信号出现在 <code>cut</code> 旁边，'
      + '可能是它促成了砍单，也可能是砍单那天恰好什么信号都在。';
    if (selection && selection.status === 'measured' && selection.pbo !== null
        && selection.pbo !== undefined) {
      text += ' 在这个横期上挑赢家的过拟合概率 <b>PBO ' + selection.pbo.toFixed(2)
        + '</b>（' + selection.n_splits + ' 次对半切分）'
        + (selection.pbo >= 0.5 ? '——<b>还不能挑赢家</b>。' : '。');
    }
    var refutation = ((d.signal_panel || {}).refutation || {})[horizon];
    if (refutation && refutation.signals) {
      // 置换检验回答的是区间回答不了的那个问题：把「谁持有这个值」在同一天内
      // 打乱之后，还剩多少信号能给出同样的 IC。两者不一致的那几条要点名。
      text += ' 把每个交易日内「哪只票拿哪个值」打乱重算，'
        + '<b>' + refutation.survives_refutation + '/' + refutation.signals
        + '</b> 条信号仍然给不出同样的 IC（其余 ' + refutation.fails_placebo
        + ' 条给得出，' + refutation.collecting + ' 条样本还不够）。';
      var contested = refutation.interval_clears_zero_but_placebo_does_not || [];
      if (contested.length) {
        text += ' <b>' + contested.length + '</b> 条的区间说它离开了零、'
          + '它自己的置换检验说没有：' + esc(contested.join('、')) + '。';
      }
    }
    if (caveat) text += ' 区间口径：' + esc(caveat);
    el('dm-caveat').innerHTML = text;
  }

  function renderKpi() {
    var d = state.data, k = d.kpi || {}, c = d.coverage || {}, g = d.degradation || {};
    // Every number here is echoed in the payload rather than counted in the
    // browser, so the strip and the file cannot drift apart.
    var parts = [
      '<span><b>' + (k.decisions || c.decisions) + '</b> 决策 · '
        + '<b>' + (k.sessions || c.sessions) + '</b> 个交易日 · '
        + '<b>' + (k.tickers || c.tickers) + '</b> 票</span>',
      '<span><b>' + (k.signals_referenced || c.signals) + '</b> 信号 / '
        + (d.source_kind_cards || []).length + ' 源 · <b>'
        + fmt(k.decision_signal_coverage_pct, 1) + '%</b> 有快照</span>',
      '<span>' + esc(c.first_decision) + ' → ' + esc(d.as_of)
        + (k.panel_as_of ? ' · IC 至 ' + esc(k.panel_as_of) : '') + '</span>'
    ];
    // 少了什么必须说，但它不该占三行英文：档位（闸按它断言）留在条上，代价那
    // 句原文收进下面「怎么读」里。一个安静地少给东西的页面比一个挂横幅的更坏。
    if (g.level && g.level !== 'full') {
      parts.push('<span class="dm-warn">降级 <b>' + esc(g.level) + '</b></span>');
    }
    el('dm-kpi').innerHTML = parts.join('');
    var cost = el('dm-degradation');
    if (cost) {
      cost.innerHTML = g.level && g.level !== 'full'
        ? '降级 <code>' + esc(g.level) + '</code>：' + esc(g.cost)
          + '（payload ' + Math.round((g.bytes || 0) / 1024) + ' KB）'
        : 'payload ' + Math.round((g.bytes || 0) / 1024) + ' KB，未降级。';
    }
  }

  function renderTimeline() {
    var d = state.data, html = '';
    var count = (d.decisions.decision_id || []).length;
    if (!count) {
      el('dm-timeline').innerHTML = '<p class="dm-sub" style="padding:10px 12px">'
        + '时间线在当前降级档位下不可用。</p>';
      return;
    }
    // 轴的两端取所有**能解析的** plan date 的最小/最大，不是第 0 条和最后
    // 一条。实测（2026-09-09，809 条决策）：`codes.plan_date[0]` 是空串，第 0
    // 条决策正好用的是它 ⇒ `Date.parse('')` = NaN ⇒ span 是 NaN ⇒ 每个点的
    // left 都是 "NaN%" ⇒ 浏览器丢掉这条声明 ⇒ 18 行里所有标记全叠在 x=0。
    // 线上那张独立页也是这么坏着的，没人看见：契约用的是一份写死 left 的
    // 合成 fixture，从来没跑过真 payload。
    var stamps = [];
    for (var i = 0; i < count; i++) {
      var t = Date.parse(cell('plan_date', i));
      if (!isNaN(t)) stamps.push(t);
    }
    if (!stamps.length) {
      el('dm-timeline').innerHTML = '<p class="dm-sub" style="padding:10px 12px">'
        + '这份 payload 里没有一条决策带得出 plan date，时间轴画不出来。</p>';
      return;
    }
    var first = Math.min.apply(null, stamps);
    var span = Math.max(1, Math.max.apply(null, stamps) - first);
    var undated = 0;
    Object.keys(d.ticker_timelines).sort().forEach(function (ticker) {
      if (state.ticker && ticker !== state.ticker) return;
      var dots = '';
      d.ticker_timelines[ticker].forEach(function (index) {
        var date = cell('plan_date', index);
        var at = Date.parse(date);
        // 没有日期的那一条放不到轴上。放在 0% 会读成「那天做的」——一个位置
        // 就是一个断言。数出来，在图例旁边说一声。
        if (isNaN(at)) { undated += 1; return; }
        var left = (at - first) / span * 100;
        var action = cell('action', index);
        dots += '<button class="dm-dot ' + actionClass(action) + '" style="left:'
          + left.toFixed(2) + '%" data-i="' + Number(index) + '" title="'
          + esc(date) + ' · ' + esc(action) + '" aria-label="'
          + esc(ticker) + ' ' + esc(date) + ' ' + esc(action) + '"></button>';
      });
      // 一整行都画不出点（那条票的决策全都没有日期），就不要那一行：一个
      // 空名字配一条空轨道读成「这只票什么都没做」。它们已经数进下面那句。
      if (!dots) return;
      html += '<div class="dm-row"><b>' + esc(ticker || '未具名') + '</b>'
        + '<div class="dm-track">' + dots + '</div></div>';
    });
    el('dm-timeline').innerHTML = html
      || '<p class="dm-sub" style="padding:10px 12px">没有匹配的票。</p>';
    var note = el('dm-undated');
    if (note) {
      note.textContent = undated
        ? '另有 ' + undated + ' 条决策没有 plan date，画不到轴上（它们仍在板的计数里）。'
        : '';
    }
  }

  // The drawer is modal: a scrim covers the page and Escape closes it. Until
  // #1350 that was true for the mouse only — nothing stopped Tab from walking
  // straight out of the drawer into the board behind the scrim, and closing
  // dropped focus on <body>, so a keyboard reader lost their place in a 741-row
  // table and had to start over.
  //
  // `inert` on the siblings is how the main dashboard already does this
  // (dashboard.hero.js:1510, dashboard.render.js:2821): it removes the
  // background from the tab order and from the accessibility tree in one
  // attribute, so the trap needs no keydown handler of its own to maintain.
  // The drawer and its scrim are children of #decimap too, so they are skipped
  // by identity rather than by making the whole container inert.
  let drawerReturnFocus = null;

  // Every ancestor level, not just #decimap: the page grew a shared header and
  // footer (#1211) that live outside #decimap, so inerting only the drawer's
  // siblings left nine real links in the tab order behind the scrim. It stayed
  // green because the test's 12 tabs happened to be fewer than the drawer's own
  // focusables — until a smaller payload (data commit 09f0b71c, no code change)
  // made the drawer short enough for Tab to reach them. Walking up to <body> is
  // the version that does not depend on how much is in the drawer.
  function setBackgroundInert(on) {
    const drawer = el('dm-drawer');
    const scrim = el('dm-scrim');
    if (!drawer) return;
    for (let node = drawer; node && node.parentElement && node !== document.body;
         node = node.parentElement) {
      for (const sibling of node.parentElement.children) {
        if (sibling === node || sibling === scrim) continue;
        sibling.inert = on;
      }
    }
  }

  function showDrawer(html) {
    // Captured before focus moves, so closing can put the reader back on the
    // cell or timeline marker they opened — not on <body>.
    drawerReturnFocus = document.activeElement;
    el('dm-drawer-body').innerHTML = html;
    el('dm-drawer').classList.add('is-open');
    el('dm-drawer').setAttribute('aria-hidden', 'false');
    el('dm-scrim').hidden = false;
    setBackgroundInert(true);
    el('dm-close').focus();
  }

  // A cell is a bucket, so opening one lists the decisions in it. The list is a
  // filter over published rows — this signal was present on that decision and
  // the action matches — never a recomputation of the bucket's own numbers,
  // which are printed above it exactly as the payload carries them.
  function openBucket(name, action) {
    var d = state.data, horizon = state.horizon;
    var position = d.signal_order.indexOf(name);
    var positions = position >= 0 ? [position]
      : d.signal_order.map(function (signal, index) {
          return signal.split('.')[0] === name ? index : -1;
        }).filter(function (index) { return index >= 0; });
    var card = (d.source_kind_cards || []).concat(d.info_source_cards)
      .filter(function (row) { return row.signal === name; })[0];
    var bucket = ((card || {}).by_action || {})[action] || {};

    var items = [], snapshots = d.decision_snapshots || [];
    (d.decisions.decision_id || []).forEach(function (id, index) {
      if (cell('action', index) !== action) return;
      var row = snapshots[index];
      if (!row) return;
      var present = positions.some(function (at) {
        return row[at] !== null && row[at] !== undefined;
      });
      if (present) items.push(index);
    });
    items.sort(function (a, b) {
      return String(cell('plan_date', b)).localeCompare(String(cell('plan_date', a)));
    });

    var html = '<h3>' + esc(name) + ' · ' + esc(action) + '</h3>'
      + '<p class="dm-sub">' + (bucket.count || 0) + ' 条决策 · '
      + (bucket['n_' + horizon] || 0) + ' 条在 ' + esc(horizon) + ' 上已结算 · 中位 '
      + signed(bucket['median_' + horizon + '_pct'], 2)
      + '% · 胜率 ' + pct(bucket['win_rate_' + horizon]) + '</p>';
    if (items.length < (bucket.count || 0)) {
      html += '<p class="dm-sub">下面只列得出 ' + items.length + ' 条：'
        + '较早的决策在当前降级档位下没有保留信号快照行，它们仍然计入上面的桶。</p>';
    }
    html += '<ul class="dm-hits">' + items.map(function (index) {
      return '<li><button type="button" data-i="' + index + '">'
        + '<span>' + esc(cell('ticker', index)) + ' <em>'
        + esc(cell('plan_date', index)) + '</em></span>'
        + '<em>' + (d.decisions[horizon][index] === null
            || d.decisions[horizon][index] === undefined
              ? '未结算' : signed(d.decisions[horizon][index], 2) + '%')
        + '</em></button></li>';
    }).join('') + '</ul>';
    showDrawer(html);
  }

  function openDecision(index) {
    var d = state.data;
    var snapshot = (d.decision_snapshots || [])[index];
    var html = '<h3>' + esc(cell('ticker', index)) + ' · '
      + esc(cell('action', index)) + '</h3>'
      + '<p class="dm-sub">' + esc(cell('plan_date', index)) + ' · '
      + esc(cell('driven_by', index) || '—') + ' · '
      + esc(cell('strategy_id', index) || '—') + '</p>';
    html += '<table class="dm-kv"><tbody>'
      + '<tr><th>信心</th><td>' + fmt(d.decisions.confidence[index], 2) + '</td></tr>'
      + '<tr><th>结果</th><td>' + esc(cell('outcome', index) || '—') + '</td></tr>'
      + '<tr><th>t1 / t5 / t20</th><td>' + fmt(d.decisions.t1[index]) + ' / '
      + fmt(d.decisions.t5[index]) + ' / ' + fmt(d.decisions.t20[index]) + '</td></tr>'
      + '<tr><th>快照年龄</th><td>'
      + fmt(d.decisions.snapshot_age_sessions[index], 0) + ' session</td></tr>'
      + '</tbody></table>';
    var keywords = (d.decisions.rationale_keywords || [])[index] || [];
    if (keywords.length) {
      html += '<p class="dm-sub">理由关键词：' + esc(keywords.join(' · ')) + '</p>';
    }
    if (d.decisions.rationale && d.decisions.rationale[index]) {
      html += '<p class="dm-sub">' + esc(d.decisions.rationale[index]) + '</p>';
    }
    if (snapshot) {
      var signalRows = '';
      d.signal_order.forEach(function (signal, position) {
        var value = snapshot[position];
        if (value === null || value === undefined) return;
        signalRows += '<tr><th>' + esc(signal) + '</th><td>' + fmt(value, 4) + '</td></tr>';
      });
      html += '<h3 style="margin-top:14px">决策时的信号</h3>'
        + (signalRows ? '<table class="dm-kv"><tbody>' + signalRows + '</tbody></table>'
                      : '<p class="dm-sub">这条决策的 plan date 上没有任何注册快照在年龄上限内。</p>');
    } else {
      html += '<h3 style="margin-top:14px">决策时的信号</h3>'
        + '<p class="dm-sub">这条决策早于 payload 的快照保留窗口（见顶部降级提示）。'
        + '完整值在 <code>memory/decisions.jsonl</code> 与注册历史里。</p>';
    }
    showDrawer(html);
  }

  function closeDrawer() {
    el('dm-drawer').classList.remove('is-open');
    el('dm-drawer').setAttribute('aria-hidden', 'true');
    el('dm-scrim').hidden = true;
    setBackgroundInert(false);
    // Lift inert before restoring focus: focus() on an inert element is a no-op.
    if (drawerReturnFocus && document.contains(drawerReturnFocus)) {
      drawerReturnFocus.focus();
    }
    drawerReturnFocus = null;
  }

  function renderAll() { renderKpi(); renderBoard(); renderTimeline(); }

  // 面板每次刷新都会拿到一份新的 payload；事件只绑一次，展开/横期/选票这些
  // 读者自己的状态因此不会被一次后台刷新重置。
  var bound = false;

  function bindOnce() {
    el('dm-horizon').addEventListener('click', function (event) {
      var button = event.target.closest('button[data-h]');
      if (!button) return;
      state.horizon = button.dataset.h;
      [].forEach.call(this.querySelectorAll('button'), function (other) {
        other.setAttribute('aria-pressed', other === button ? 'true' : 'false');
      });
      renderAll();
    });
    el('dm-ticker').addEventListener('change', function () {
      state.ticker = this.value; renderTimeline();
    });
    el('dm-expand').addEventListener('click', function () {
      var kinds = (state.data.source_kind_cards || []).map(function (row) {
        return row.signal;
      });
      var anyClosed = kinds.some(function (kind) { return !state.open[kind]; });
      kinds.forEach(function (kind) { state.open[kind] = anyClosed; });
      this.textContent = anyClosed ? '收起全部' : '展开全部';
      renderBoard();
    });
    el('dm-reset').addEventListener('click', function () {
      state.horizon = 't5'; state.ticker = ''; state.open = {};
      el('dm-ticker').value = '';
      el('dm-expand').textContent = '展开全部';
      [].forEach.call(el('dm-horizon').querySelectorAll('button'), function (button) {
        button.setAttribute('aria-pressed', button.dataset.h === 't5' ? 'true' : 'false');
      });
      renderAll();
    });
    el('dm-board').addEventListener('click', function (event) {
      var twist = event.target.closest('.dm-twist');
      if (twist) {
        state.open[twist.dataset.kind] = !state.open[twist.dataset.kind];
        renderBoard();
        return;
      }
      var target = event.target.closest('.dm-cell');
      if (target) openBucket(target.dataset.row, target.dataset.action);
    });
    el('dm-board').addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      var target = event.target.closest('.dm-cell');
      if (!target) return;
      event.preventDefault();
      openBucket(target.dataset.row, target.dataset.action);
    });
    el('dm-timeline').addEventListener('click', function (event) {
      var dot = event.target.closest('.dm-dot');
      if (dot) openDecision(Number(dot.dataset.i));
    });
    el('dm-drawer-body').addEventListener('click', function (event) {
      var hit = event.target.closest('.dm-hits button');
      if (hit) openDecision(Number(hit.dataset.i));
    });
    el('dm-close').addEventListener('click', closeDrawer);
    el('dm-scrim').addEventListener('click', closeDrawer);
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && el('dm-drawer').classList.contains('is-open')) {
        closeDrawer();
      }
    });
  }

  // 票列表跟着 payload 走，但读者选中的那一只要留住 —— 刷新不该把筛选清掉。
  function fillTickers() {
    var select = el('dm-ticker');
    var wanted = state.ticker;
    var options = ['<option value="">全部</option>'];
    Object.keys(state.data.ticker_timelines || {}).sort().forEach(function (ticker) {
      if (!ticker) return;   // 空票名（那条没有标的的决策）不是一个可选项
      options.push('<option value="' + esc(ticker) + '">' + esc(ticker) + '</option>');
    });
    select.innerHTML = options.join('');
    if (wanted && select.querySelector('option[value="' + wanted + '"]')) {
      select.value = wanted;
    } else {
      state.ticker = '';
    }
  }

  function boot(data) {
    if (!data || !el('decimap')) return;
    state.data = data;
    if (!bound) { bound = true; bindOnce(); }
    fillTickers();
    renderAll();
  }

  function fail(message) {
    if (!el('dm-kpi')) return;
    el('dm-kpi').innerHTML = '<span class="dm-warn">' + esc(message) + '</span>';
  }

  window.__decimap = { boot: boot, fail: fail };
})();
