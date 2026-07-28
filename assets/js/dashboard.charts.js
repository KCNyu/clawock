  // ── Lazy chart init (perf) ──────────────────────────────────────────────
  // ECharts remains tab-lazy. Hero now owns the single Equity instance as its
  // visual anchor, so landing triggers only that chart; the other canvases still
  // wait for their detail tabs. Never initialize a chart in display:none.
  const CHART_FNS = {
    hero:    () => { renderEquityChart(); },
    drill:   () => { renderShadowPortfolioChart(); renderWeightConfidence(); },
    risk:    () => { renderSectorChart(); },
    reflect: () => { renderShadowChart(); renderRealizedChart(); renderDailyPnlChart(); },
  };
  const _chartTabsShown = new Set();
  let _echartsLoading = false;
  function whenEcharts(cb) {
    if (window.echarts) return cb();
    if (!_echartsLoading) {  // first chart tab shown → fetch the ~1MB bundle now, once
      _echartsLoading = true;
      const s = document.createElement("script");
      s.src = "assets/js/echarts.min.js";
      document.head.appendChild(s);
    }
    const iv = setInterval(() => { if (window.echarts) { clearInterval(iv); cb(); } }, 50);
  }
  function paintCharts(t) {
    if (!CHART_FNS[t] || !DATA) return;
    whenEcharts(() => {
      if (!DATA) return;
      readThemeCSS();               // one style read before any ECharts DOM writes
      CHART_FNS[t]();
    });
  }

  // Reflect owns the episode backtest. Prefer its lazy sidecar, with the old
  // dashboard.json location as a cross-version fallback while a code deploy and
  // the next cron-generated data deploy can briefly straddle schemas.
  function episodeBacktest() {
    return safe(DATA, "decision_audit", "episode_backtest")
      || safe(DATA, "episode_backtest")
      || {};
  }
  function ensureTabCharts(t) {
    if (!CHART_FNS[t]) return;
    _chartTabsShown.add(t);
    paintCharts(t);
  }
  // Desktop and mobile now both show ONE tab at a time, so only the active tab's
  // charts need drawing on load. Initializing a chart inside a display:none panel
  // yields a zero-width canvas, so we defer to the tab that's actually visible;
  // ensureTabCharts fires again on every tab switch (see setActiveButton).
  function ensureVisibleCharts() {
    ensureTabCharts(currentTab());
  }
  // Shadow is deliberately collapsed on every load, on both desktop and mobile.
  // Do not initialize ECharts while its body is hidden: that creates 0-width
  // canvases and makes the mobile GIF capture wait forever. Expanding paints after
  // layout, then explicitly resizes any existing instances.
  function setShadowPortfolioExpanded(open) {
    const toggle = document.getElementById("shadow-portfolio-toggle");
    const expanded = document.getElementById("shadow-portfolio-expanded");
    if (!toggle || !expanded) return;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    expanded.hidden = !open;
    if (!open) return;
    whenEcharts(() => {
      requestAnimationFrame(() => requestAnimationFrame(() => {
        renderShadowPortfolioChart();
        charts.shadowPortfolioUsd && charts.shadowPortfolioUsd.resize();
        charts.shadowPortfolioHkd && charts.shadowPortfolioHkd.resize();
      }));
    });
  }
  // Per-market view shared by Equity Curve + Daily P&L: 'combined' | 'us' | 'hk'.
  let MARKET_VIEW = "combined";
  function setMarketView(v) {
    if (v === MARKET_VIEW) return;
    MARKET_VIEW = v;
    document.querySelectorAll(".mkt-seg-btn").forEach(b =>
      b.classList.toggle("active", b.dataset.mkt === v));
    const sfx = v === "us" ? "· 美股 USD" : v === "hk" ? "· 港股 HKD" : "· USD-eq";
    const et = document.getElementById("equity-title");
    const dt = document.getElementById("dailypnl-title");
    if (et) et.textContent = `Equity Curve ${sfx}`;
    if (dt) dt.textContent = `Daily P&L + Cumulative ${sfx}`;
    // A deep link can land on Reflect before Hero has ever been visible. In that
    // case do not create Equity inside the hidden Hero panel at zero width; Hero's
    // lazy paint will pick up MARKET_VIEW when it is eventually opened.
    if (charts.equity || currentTab() === "hero") renderEquityChart();
    renderDailyPnlChart();
    requestAnimationFrame(() => {
      charts.equity && charts.equity.resize();
      charts.dailyPnl && charts.dailyPnl.resize();
    });
  }
  function renderShadowPortfolioChart() {
    if (!window.echarts) return;
    const expanded = document.getElementById("shadow-portfolio-expanded");
    if (!expanded || expanded.hidden) return;
    const sidecar = safe(DATA, "shadow_portfolio") || {};
    if (sidecar.computed === false) return;
    const hasData = ["USD", "HKD"].some(
      currency => (safe(sidecar, "curves", currency, "curve") || []).some(
        row => row && row.followed_sim != null && row.buy_and_hold != null
          && Number.isFinite(Number(row.followed_sim))
          && Number.isFinite(Number(row.buy_and_hold))
      )
    );
    // The card's non-chart renderer already shows "数据不足". Avoid initializing
    // ECharts inside its hidden content when the sidecar is missing or empty.
    if (!hasData) return;
    const accent = getCSS("--accent") || "#36A3FF";
    const baseline = getCSS("--warning") || "#E3A640";
    const isMobile = window.innerWidth < 1024;
    const configs = [
      { currency: "USD", id: "chart-shadow-usd", key: "shadowPortfolioUsd" },
      { currency: "HKD", id: "chart-shadow-hkd", key: "shadowPortfolioHkd" },
    ].map(config => ({
      ...config,
      el: document.getElementById(config.id),
    }));
    // Measure both containers before echarts.init() mutates either one. The old
    // forEach read the HKD width after the USD canvas write, forcing a sync reflow.
    const visibleConfigs = configs.filter(config =>
      config.el && config.el.clientWidth >= 50
    );

    visibleConfigs.forEach(({ currency, key, el }) => {
      if (!charts[key]) charts[key] = echarts.init(el, null, { renderer: "canvas" });
      const rows = (safe(sidecar, "curves", currency, "curve") || [])
        .filter(row => row && row.date);
      const dates = rows.map(row => row.date);
      const option = {
        ...baseChartOpts(),
        grid: { left: isMobile ? 55 : 66, right: 14, top: 38, bottom: dates.length > 8 ? 48 : 28 },
        legend: {
          data: ["followed 模拟净值", "buy-hold 基线"], top: 2,
          textStyle: { color: chartTextColor(), fontSize: 10 },
        },
        tooltip: {
          ...chartTooltip("axis", "cross"),
          valueFormatter: value => value == null ? DASH : fmtMoney(value, currency),
        },
        xAxis: chartAxis({
          type: "category", data: dates, boundaryGap: false,
          axisLabel: {
            color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono"),
            rotate: dates.length > 8 ? 35 : 0,
          },
        }),
        yAxis: chartAxis({
          type: "value", scale: true,
          axisLabel: {
            color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono"),
            formatter: value => {
              const symbol = currency === "USD" ? "$" : "HK$";
              return symbol + (Math.abs(value) >= 1000 ? (value / 1000).toFixed(1) + "k" : Math.round(value));
            },
          },
        }),
        series: [
          {
            name: "followed 模拟净值", type: "line",
            data: rows.map(row => row.followed_sim),
            showSymbol: dates.length <= 20, symbolSize: 4, smooth: false,
            connectNulls: false,
            itemStyle: { color: accent }, lineStyle: { color: accent, width: 2.4 },
          },
          {
            name: "buy-hold 基线", type: "line",
            data: rows.map(row => row.buy_and_hold),
            showSymbol: false, smooth: false, connectNulls: false,
            itemStyle: { color: baseline },
            lineStyle: { color: baseline, width: 1.8, type: "dashed" },
          },
        ],
      };
      if (!rows.length) {
        option.graphic = [{
          type: "text", left: "center", top: "middle",
          style: { text: "数据不足", fill: chartTextColor(), fontSize: 13, opacity: .55 },
        }];
      }
      charts[key].setOption(option, true);
    });
  }

  // =========================================================
  // Reflect — ECharts
  // =========================================================
  function chartTooltip(trigger = "axis", pointerType = "cross") {
    return {
      trigger,
      backgroundColor: "#111925",
      borderColor: "#31445A",
      borderWidth: 1,
      padding: [8, 12],
      textStyle: {
        color: "#F2F6FB",
        fontFamily: getCSS("--mono"),
        fontSize: 11,
      },
      extraCssText: "border-radius:8px;box-shadow:0 12px 32px rgba(0,0,0,.28);",
      axisPointer: {
        type: pointerType,
        lineStyle: { color: getCSS("--focus") || "#8ED0FF", width: 1 },
        crossStyle: { color: getCSS("--focus") || "#8ED0FF", width: 1 },
        shadowStyle: { color: "rgba(54,163,255,.08)" },
      },
    };
  }

  function chartAxis(overrides = {}) {
    return {
      axisTick: { show: false },
      axisLine: { show: false },
      splitLine: { lineStyle: { color: chartGridColor(), width: 1 } },
      axisLabel: {
        color: chartLabelColor(),
        fontSize: 10,
        fontFamily: getCSS("--mono"),
      },
      nameTextStyle: {
        color: chartLabelColor(),
        fontSize: 10,
        fontFamily: getCSS("--mono"),
      },
      ...overrides,
    };
  }

  function chartDataZoom(start) {
    const accent = getCSS("--accent") || "#36A3FF";
    return {
      type: "slider", start, end: 100, height: 16, bottom: 6,
      borderColor: chartGridColor(),
      backgroundColor: "transparent",
      fillerColor: echarts.color.modifyAlpha(accent, .18),
      dataBackground: {
        lineStyle: { color: chartLabelColor(), opacity: .35 },
        areaStyle: { color: chartLabelColor(), opacity: .08 },
      },
      selectedDataBackground: {
        lineStyle: { color: accent, opacity: .8 },
        areaStyle: { color: accent, opacity: .16 },
      },
      handleStyle: { color: accent, borderColor: accent },
      moveHandleStyle: { color: accent, opacity: .55 },
      emphasis: { handleStyle: { color: getCSS("--accent-strong") || "#1687E8" } },
      handleSize: "120%",
      textStyle: { color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono") },
    };
  }

  function baseChartOpts() {
    return {
      textStyle: { color: chartTextColor(), fontFamily: getCSS("--font") },
      backgroundColor: "transparent",
      animationDuration: 200,
      // Animate the FIRST paint only. Data-only updates (the 60s background poll, a
      // scoped sidecar refresh, a US/HK toggle) reapply the option on the existing
      // instance; a non-zero update duration re-runs the intro animation and reads as
      // a periodic flicker. 0 = the chart just snaps to the new data, no replay.
      animationDurationUpdate: 0,
      animationEasing: "cubicOut",
      animationEasingUpdate: "cubicOut",
      grid: { left: 50, right: 20, top: 30, bottom: 40, containLabel: true },
      tooltip: chartTooltip(),
      xAxis: chartAxis(),
      yAxis: chartAxis(),
    };
  }

  // The money chart this used to draw is retired, not restyled. It plotted
  // shares x (trigger price - next recorded price) and captioned it "what
  // listening to the AI earned", but 110 of the 113 active calls in it were never
  // executed, over half of the "next recorded price" marks are not closes, and the
  // trigger verdicts behind it come from day ranges that carry across sessions.
  // The algebra was fine; the claim on top of it was not, and a relabel would not
  // fix it — answering "how much more did I make by listening" needs real fills
  // and a parallel sell-at-close book to difference against. The card now says so.
  // The win-rate chart below it is a different quantity and stays.
  function renderShadowChart() {
    const card = document.getElementById("shadow-card");
    if (!card) return;
    // decision_money_impact is no longer published at all — not just unplotted — so
    // the card's visibility keys off the win-rate record that it still shows.
    const hasRecord = safe(episodeBacktest(), "horizons", "t1") != null;
    card.style.display = hasRecord ? "" : "none";
    if (!window.echarts) return;
    const green = getCSS("--positive") || "#28C08D";
    const dim = getCSS("--text-tertiary") || "#6E7D90";
    const isMobile = window.innerWidth < 1024;

    // A separate chart because win rate and money are different quantities: being
    // right often and being right when it is worth something are not the same
    // claim. The 50% line is a directional-hit reference, not P&L.
    const wrEl = document.getElementById("chart-ai-winrate");
    if (wrEl) {
      if (!charts.aiWinRate) charts.aiWinRate = echarts.init(wrEl, null, { renderer: "canvas" });
      const t1 = safe(episodeBacktest(), "horizons", "t1") || {};
      const allWrCurve = t1.all_win_rate_curve || [];
      const activeWrCurve = t1.active_win_rate_curve || [];
      const wrDates = [...new Set([...allWrCurve, ...activeWrCurve].map(p => p.date))].sort();
      const wrSeries = curve => {
        const map = Object.fromEntries(curve.map(p => [p.date, p.win_rate * 100]));
        let last = null;
        return wrDates.map(d => { if (map[d] != null) last = map[d]; return last; });
      };
      // Colour encodes which line you're reading, not whether it's any good. The two
      // lines are different sample pools and must not be read as active-vs-hold: 全量
      // mixes in the passive stances. The 50% line is the only reference here.
      const activeWrColor = getCSS("--accent") || "#36A3FF";
      charts.aiWinRate.setOption({
        ...baseChartOpts(),
        grid: { left: isMobile ? 42 : 52, right: isMobile ? 16 : 24, top: 34, bottom: wrDates.length > 6 ? 48 : 26 },
        legend: { data: ["全量AI胜率", "主动AI胜率", "50%参考"], top: 0,
          textStyle: { color: chartTextColor(), fontSize: isMobile ? 9 : 10 } },
        tooltip: { ...chartTooltip("axis", "cross"), valueFormatter: v => v == null ? "—" : v.toFixed(1) + "%" },
        xAxis: chartAxis({ type: "category", data: wrDates, boundaryGap: false,
          axisLabel: { color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono"), rotate: wrDates.length > 6 ? 35 : 0 } }),
        yAxis: chartAxis({ type: "value", min: 0, max: 100, interval: 25,
          axisLabel: { color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono"), formatter: v => v + "%" } }),
        series: [
          { name: "全量AI胜率", type: "line", data: wrSeries(allWrCurve), smooth: 0.1, showSymbol: false,
            itemStyle: { color: green }, lineStyle: { width: 2.2, color: green } },
          { name: "主动AI胜率", type: "line", data: wrSeries(activeWrCurve), smooth: 0.1, showSymbol: false,
            itemStyle: { color: activeWrColor }, lineStyle: { width: 2.2, color: activeWrColor } },
          { name: "50%参考", type: "line", data: wrDates.map(() => 50), showSymbol: false,
            itemStyle: { color: dim }, lineStyle: { width: 1.2, color: dim, type: "dashed" } },
        ],
      });
    }
  }

  function renderEquityChart() {
    const el = document.getElementById("chart-equity");
    if (!el || !window.echarts) return;
    if (!charts.equity) charts.equity = echarts.init(el, null, { renderer: "canvas" });

    const view = MARKET_VIEW;                       // 'combined' | 'us' | 'hk'
    const fx = safe(DATA, "fx", "usdhkd") || 7.83;
    // 基准新鲜度被动提示 — benchmark.json 停更(抓取限流)时 SPY/恒科等值线会退化成平线，
    // 给个小字标注省得误读为"持平"。被动展示，不推送(feedback_no_individual_cron_alerts)。
    const bmStale = safe(DATA, "benchmark", "staleness");
    const bmEl = document.getElementById("benchmark-stale");
    if (bmEl) {
      if (bmStale && bmStale.is_stale) {
        bmEl.textContent = `⚠ 基准数据延迟（SPY/恒科等值止于 ${bmStale.last_date}，落后 ${bmStale.days_behind} 天）`;
        bmEl.style.display = "";
      } else { bmEl.style.display = "none"; }
    }
    const snaps = (safe(DATA, "snapshots") || [])
      .filter(s => s.us_total_value != null || s.hk_total_value != null);
    const byDate = new Map();
    snaps.forEach(s => byDate.set(s.date, s));
    let series = Array.from(byDate.values()).sort((a, b) => a.date.localeCompare(b.date));
    // Collapse same-session snapshots (US session straddles HK midnight → two HK-dated
    // snapshots for ONE US session; weekend copies repeat Fri). Mirror renderDailyPnlChart:
    // key on us_asof/hk_asof per view, keep the LAST (most-settled) of consecutive dupes —
    // for a value curve that means no duplicate point for the same session. (cross-day fix,
    // 见 openclaw-us-crossday-double-count)
    const sameSession = (a, b) => {
      if (view === "us") return !!a.us_asof && a.us_asof === b.us_asof;
      if (view === "hk") return !!a.hk_asof && a.hk_asof === b.hk_asof;
      return !!a.us_asof && a.us_asof === b.us_asof && !!a.hk_asof && a.hk_asof === b.hk_asof;
    };
    series = series.filter((s, i) => {
      const next = series[i + 1];
      if (!next) return true;
      if (s.us_asof && s.hk_asof && next.us_asof && next.hk_asof) return !sameSession(s, next);
      return true;
    });
    // Per-market views label the x-axis by the true session date (≠ filename date).
    const dates = series.map(s =>
      view === "us" ? (s.us_asof || s.date) : view === "hk" ? (s.hk_asof || s.date) : s.date);
    const r2 = v => Math.round(v * 100) / 100;

    // ── Per-market basis ──────────────────────────────────────────────────
    // equity = 持仓市值 + 累计已实现 (so sells, holdings→cash, don't drop the curve).
    // US/combined in USD ($); HK in native HKD (HK$); combined folds HK→USD at FX.
    const cur = view === "hk" ? "HK$" : "$";
    const showSPY = view !== "hk";              // SPY overlay only where USD makes sense
    const showHSTECH = view !== "us";           // 恒科 overlay only where HK is in play
    const taName = view === "us" ? "美股总资产" : view === "hk" ? "港股总资产" : "真实总资产";
    // 真实总资产 = 持仓市值 + 现金 (trade-invariant 的"现在值多少钱"，加减仓不动它)。
    // 现金没记录的早期快照 → null → 线在该点断开(connectNulls 跨过)。这是替代旧"净值"线
    // (市值+已实现,会被加仓虚抬、对现金视而不见) 的纠正口径。US 自 6/12、HK/合计 自 6/18 起有。
    const ta = series.map(s => {
      if (view === "us") return (s.us_cash != null && s.us_total_value != null) ? r2(s.us_total_value + s.us_cash) : null;
      if (view === "hk") return (s.hk_cash != null && s.hk_total_value != null) ? r2(s.hk_total_value + s.hk_cash) : null;
      if (s.us_cash == null || s.hk_cash == null || s.us_total_value == null || s.hk_total_value == null) return null;
      return r2((s.us_total_value + s.us_cash) + ((s.hk_total_value + s.hk_cash) / fx));
    });
    // 净值(市值+已实现) — 不再画出(对现金视而不见、被加仓虚抬，对用户没用)，仅保留作
    // benchmark "SPY/恒科等值" 的归一锚点(全历史、value-scale)，故仍需算出但不进 seriesArr。
    const eq = series.map(s => {
      if (view === "us") return s.us_equity != null ? r2(s.us_equity) : null;
      if (view === "hk") return s.hk_equity != null ? r2(s.hk_equity) : null;
      return r2((s.us_equity ?? 0) + ((s.hk_equity ?? 0) / fx));
    });
    const cost = series.map(s => {
      let t;
      if (view === "us") t = s.us_total_cost;
      else if (view === "hk") t = s.hk_total_cost;
      else t = (s.us_total_cost ?? 0) + ((s.hk_total_cost ?? 0) / fx);
      return (t != null && t > 0) ? r2(t) : null;
    });
    // 总利润 = 浮盈 + 已实现 ( = 净值 − 成本基础 ). Nets out deployed capital, so its
    // peak is the TRUE profit peak — market value peaks when capital is most deployed,
    // which is not the same as making the most money (5/16 市值峰 ≠ 5/29 利润峰).
    // Same money axis as 净值; can go negative (HK underwater), which is the point.
    const profit = series.map(s => {
      if (view === "us") return s.us_profit != null ? r2(s.us_profit) : null;
      if (view === "hk") return s.hk_profit != null ? r2(s.hk_profit) : null;
      if (s.us_profit == null || s.hk_profit == null) return null;
      return r2(s.us_profit + (s.hk_profit / fx));
    });

    // 回撤 — 用 PROFIT(净化本金) 口径而非 净值。净值会被加仓虚抬(花掉的现金不计),
    // 使回撤恒显示 ~0%(假新高);profit 是 trade-invariant 的真回撤,与下方"历史利润极值"
    // 卡一致。% 仅在利润全程为正时给(running peak>0 且当前>0),否则 null=无红色填充。
    let peak = -Infinity;
    const ddPct = profit.map(v => {
      if (v == null) return null;
      if (v > peak) peak = v;
      return (peak > 0 && v > 0) ? Math.round(((v - peak) / peak) * 10000) / 100 : null;
    });
    // 总利润较昨日 — 用总利润(trade-invariant)算日变化，在 tooltip 与"回撤"分列，
    // 避免连续新高时回撤恒 0% 看起来像卡住。(原用净值,会被加仓污染)
    const chg = profit.map((v, i) =>
      (i > 0 && v != null && profit[i - 1] != null) ? r2(v - profit[i - 1]) : null);
    const chgPct = profit.map((v, i) =>
      (i > 0 && v != null && profit[i - 1] != null && profit[i - 1] !== 0)
        ? Math.round(((v - profit[i - 1]) / Math.abs(profit[i - 1])) * 10000) / 100 : null);

    // Benchmark overlay — "what if I bought N at the same amount on day 0?" Normalized
    // so bench[base] === eq[base], then scaled by close[i]/close[base], so it lands in
    // the SAME currency axis as the portfolio and the visual gap IS cumulative alpha.
    // Forward-fills across non-trading days so the line stays continuous.
    function benchLine(key) {
      const bm = safe(DATA, "benchmark", "series", key) || [];
      const bd = new Map(bm.map(b => [b.date, b.close]));
      let bIdx = -1, bClose = null;
      for (let i = 0; i < dates.length; i++) {
        if (eq[i] == null) continue;
        const c = bd.get(dates[i]);
        if (c != null) { bIdx = i; bClose = c; break; }
      }
      let last = null;
      const line = dates.map((d, i) => {
        if (bIdx < 0 || i < bIdx || !bClose) return null;
        const c = bd.get(d);
        if (c != null) last = c;
        if (last == null) return null;
        return r2(eq[bIdx] * (last / bClose));
      });
      return { line, bIdx, bClose };
    }
    const spy = showSPY ? benchLine("SPY") : { line: [], bIdx: -1, bClose: null };
    const hst = showHSTECH ? benchLine("HSTECH") : { line: [], bIdx: -1, bClose: null };

    const lr = safe(DATA, "lev_regime") || {};
    const hstech200 = lr.ma ?? safe(DATA, "lev_regime", "hk", "ma");
    const hstechClose = lr.close ?? safe(DATA, "lev_regime", "hk", "close");
    // 恒科200日线触发位 in the chart's currency (where the 恒科等值 line lands if HSTECH
    // reclaims its 200DMA → re-leverage cue).
    const triggerLvl = (showHSTECH && hstech200 && hst.bClose && hst.bIdx >= 0)
      ? r2(eq[hst.bIdx] * (hstech200 / hst.bClose)) : null;
    const reclaimPct = (hstech200 && hstechClose) ? (hstech200 / hstechClose - 1) * 100 : null;

    const accent = getCSS("--accent") || "#36A3FF";
    const red = getCSS("--negative") || "#F05B67";
    const green = getCSS("--positive") || "#28C08D";
    const dim = getCSS("--text-tertiary") || "#6E7D90";
    const benchColor = "#7C8CF2";
    const hkColor = getCSS("--warning") || "#E3A640";

    const axisMoney = v => cur + (Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + "k" : v);
    const tipMoney = v => cur + v.toLocaleString("en-US", { maximumFractionDigits: 0 });

    const isMobile = window.innerWidth < 1024;
    // 天数 >30 后启用底部缩放滑块，默认显示最近 ~30 天，可拖动看全程。
    const manyPts = dates.length > 30;
    const zoomStart = manyPts ? Math.max(0, (1 - 30 / dates.length) * 100) : 0;

    const legendData = ["总利润", taName, "成本基础"];
    if (showSPY) legendData.push("SPY 等值");
    if (showHSTECH) legendData.push("恒科等值");
    legendData.push("回撤");

    const seriesArr = [
      // 总利润(净化本金)= 主线：加减仓不影响它，它的峰值才是"真·赚最多"那天，
      // 与下方"历史利润极值"卡 + 回撤填充同口径。粗线 + 面积填充作视觉重心。
      { name: "总利润", type: "line", data: profit, yAxisIndex: 0,
        itemStyle: { color: green }, lineStyle: { width: 2.6, color: green }, smooth: 0.1,
        symbol: dates.length > 45 ? "none" : "circle", symbolSize: 5,
        areaStyle: { color: green, opacity: 0.08 }, z: 4, connectNulls: true,
        markLine: { symbol: "none", silent: true,
          lineStyle: { color: green, type: "dotted", width: 1, opacity: 0.5 },
          label: { color: green, fontSize: 9, position: "insideStartTop", formatter: "盈亏线 0" },
          data: [{ yAxis: 0 }] } },
      // 真实总资产(市值+现金)= value-scale 参考线，替代旧"净值"线。trade-invariant、
      // 是真·身家。现金有记录才画(US 6/12+、HK/合计 6/18+)，早期断开。
      { name: taName, type: "line", data: ta, yAxisIndex: 0,
        itemStyle: { color: accent }, lineStyle: { width: 1.8, color: accent }, smooth: 0.1,
        symbol: dates.length > 45 ? "none" : "circle", symbolSize: 4,
        z: 3, connectNulls: true },
      { name: "成本基础", type: "line", data: cost, yAxisIndex: 0,
        itemStyle: { color: dim }, lineStyle: { width: 1, type: "dashed", color: dim },
        symbol: "none", z: 2, connectNulls: true },
    ];
    if (showSPY) seriesArr.push(
      { name: "SPY 等值", type: "line", data: spy.line, yAxisIndex: 0,
        itemStyle: { color: benchColor }, lineStyle: { width: 1.4, color: benchColor, opacity: 0.85 },
        symbol: "none", smooth: 0.1, z: 2, connectNulls: true });
    if (showHSTECH) seriesArr.push(
      { name: "恒科等值", type: "line", data: hst.line, yAxisIndex: 0,
        itemStyle: { color: hkColor }, lineStyle: { width: 1.4, color: hkColor, opacity: 0.85 },
        symbol: "none", smooth: 0.1, z: 2, connectNulls: true,
        markLine: (triggerLvl == null) ? undefined : {
          symbol: "none", silent: true,
          lineStyle: { color: hkColor, type: "dashed", width: 1.2, opacity: 0.9 },
          label: { color: hkColor, fontSize: 9, position: "insideEndTop",
            formatter: () => `恒科200线触发 ${Math.round(hstech200)}` +
              (reclaimPct != null ? `（需${reclaimPct >= 0 ? "+" : ""}${reclaimPct.toFixed(0)}%）` : "") },
          data: [{ yAxis: triggerLvl }],
        },
      });
    seriesArr.push(
      { name: "回撤", type: "line", data: ddPct, yAxisIndex: 1,
        areaStyle: { color: red, opacity: 0.14 }, lineStyle: { color: red, opacity: 0.55, width: 1 },
        symbol: "none", smooth: 0.1, z: 1 });

    const opt = {
      ...baseChartOpts(),
      grid: { left: isMobile ? 48 : 72, right: isMobile ? 40 : 68, top: isMobile ? 56 : 38, bottom: manyPts ? 58 : 36 },
      legend: { data: legendData,
        // 总览默认展开恒科等值；分市场视图全部默认显示
        selected: (view === "combined" && showHSTECH) ? { "恒科等值": true } : {},
        textStyle: { color: chartTextColor(), fontSize: isMobile ? 9 : 10 },
        top: 4, itemGap: isMobile ? 8 : 10, itemWidth: isMobile ? 16 : 25, itemHeight: isMobile ? 8 : 14,
        padding: [0, 4] },
      tooltip: {
        ...chartTooltip("axis", "cross"),
        formatter: (params) => {
          const date = params[0]?.axisValue || "";
          const i = params[0]?.dataIndex;
          const lines = params.map(p => {
            const v = p.value;
            const isPct = p.seriesName === "回撤";
            const fmt = isPct
              ? (v != null ? `${v.toFixed(2)}%` : "—")
              : (v != null ? tipMoney(v) : "—");
            return `${p.marker} ${p.seriesName}: <b>${fmt}</b>`;
          });
          // 总利润较昨日 = 总利润两点之差(trade-invariant，不含加减仓噪声)，与"回撤"分列。
          // 注意：这≠"每日P&L图"的 today_change(今日盘中相对昨收)，两者口径不同。
          if (i != null && chg[i] != null) {
            const c = chg[i];
            const col = c > 0 ? green : c < 0 ? red : dim;
            const s = c >= 0 ? "+" : "-";
            const pctStr = chgPct[i] != null ? ` (${s}${Math.abs(chgPct[i]).toFixed(2)}%)` : "";
            const abs = Math.abs(c).toLocaleString("en-US", { maximumFractionDigits: 0 });
            lines.push(`<span style="color:${col}">总利润较昨日: <b>${s}${cur}${abs}</b>${pctStr}</span>`);
          } else if (i === 0) {
            lines.push(`<span style="color:${dim}">总利润较昨日: <b>首日</b></span>`);
          }
          return [date, ...lines].join("<br>");
        },
      },
      xAxis: chartAxis({
        type: "category", data: dates,
        axisLabel: { color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono"), rotate: dates.length > 6 ? 35 : 0,
          hideOverlap: true, formatter: (v) => (v || "").slice(5) },
      }),
      dataZoom: manyPts ? [
        chartDataZoom(zoomStart),
      ] : undefined,
      yAxis: [
        chartAxis({
          type: "value", name: isMobile ? "" : (view === "hk" ? "HKD" : "USD"),
          scale: true,
          // 恒科200线触发位高于净值顶 → 不抬高轴上限会被裁掉看不见。
          max: (triggerLvl != null) ? (v) => Math.max(v.max, triggerLvl) * 1.03 : undefined,
          axisLabel: { color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono"), formatter: axisMoney },
        }),
        chartAxis({
          type: "value", name: isMobile ? "" : "DD %", max: 0, position: "right",
          splitLine: { show: false },
          axisLabel: { color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono"), formatter: "{value}%" },
        }),
      ],
      series: seriesArr,
    };
    if (!dates.length) {
      opt.graphic = [{
        type: "text", left: "center", top: "middle",
        style: { text: "暂无快照历史", fill: chartTextColor(), fontSize: 13, opacity: 0.5 },
      }];
    }
    charts.equity.setOption(opt, true);
  }

  function renderDailyPnlChart() {
    const el = document.getElementById("chart-daily-pnl");
    if (!el || !window.echarts) return;
    if (!charts.dailyPnl) charts.dailyPnl = echarts.init(el, null, { renderer: "canvas" });

    const view = MARKET_VIEW;                       // 'combined' | 'us' | 'hk'
    const fx = safe(DATA, "fx", "usdhkd") || 7.83;
    const cur = view === "hk" ? "HK$" : "$";
    // Per-market daily change: US/combined in USD, HK in native HKD.
    const pnlOf = s => {
      if (view === "us") return s.us_today_change != null ? s.us_today_change : 0;
      if (view === "hk") return s.hk_today_change != null ? s.hk_today_change : 0;
      return (s.us_today_change ?? 0) + ((s.hk_today_change ?? 0) / fx);
    };
    const snaps = (safe(DATA, "snapshots") || [])
      .filter(s => s.us_today_change != null || s.hk_today_change != null);
    const byDate = new Map();
    snaps.forEach(s => byDate.set(s.date, s));
    let series = Array.from(byDate.values()).sort((a, b) => a.date.localeCompare(b.date));
    // Collapse consecutive snapshots that belong to the SAME trading session, keeping
    // the last (most-settled) one. Two reasons a session repeats across snapshots:
    //  1) weekend/holiday copies (Sat+Sun+Mon all carry Fri's move);
    //  2) a US session straddles HK midnight → lands in two HK-dated snapshots
    //     (the 2026-06-08/09 bug: US Jun-8 counted at both 6/8 and 6/9).
    // Key on session date (us_asof/hk_asof) per the active view so US sessions collapse
    // by US calendar, HK by HK calendar; fall back to today_change value if asof absent.
    const sameSession = (a, b) => {
      if (view === "us") return !!a.us_asof && a.us_asof === b.us_asof;
      if (view === "hk") return !!a.hk_asof && a.hk_asof === b.hk_asof;
      return !!a.us_asof && a.us_asof === b.us_asof && a.hk_asof === b.hk_asof;
    };
    series = series.filter((s, i) => {
      const next = series[i + 1];
      if (!next) return true;
      if (s.us_asof && s.hk_asof && next.us_asof && next.hk_asof) return !sameSession(s, next);
      return !(s.us_today_change === next.us_today_change && s.hk_today_change === next.hk_today_change);
    });

    // Per-market views label the x-axis by the true session date (≠ filename date).
    const dates = series.map(s =>
      view === "us" ? (s.us_asof || s.date) : view === "hk" ? (s.hk_asof || s.date) : s.date);
    const dailyPnl = series.map(s => Math.round(pnlOf(s) * 100) / 100);
    // Cumulative running sum
    let running = 0;
    const cumulative = dailyPnl.map(v => {
      running += (v || 0);
      return Math.round(running * 100) / 100;
    });

    const accent = getCSS("--accent") || "#36A3FF";
    const green = getCSS("--positive") || "#28C08D";
    const red = getCSS("--negative") || "#F05B67";

    const bars = dailyPnl.map(v => ({
      value: v,
      itemStyle: { color: v == null ? accent : (v >= 0 ? green : red), opacity: 0.85 },
    }));
    const axisMoney = v => cur + (Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + "k" : v);
    const tipMoney = v => cur + v.toLocaleString("en-US", { maximumFractionDigits: 0 });

    const isMobile = window.innerWidth < 1024;
    // 天数 >30 后启用底部缩放滑块，默认显示最近 ~30 天，可拖动看全程。
    const manyPts = dates.length > 30;
    const zoomStart = manyPts ? Math.max(0, (1 - 30 / dates.length) * 100) : 0;
    const opt = {
      ...baseChartOpts(),
      grid: { left: isMobile ? 56 : 70, right: isMobile ? 56 : 70, top: 34, bottom: manyPts ? 58 : 36 },
      legend: { data: ["每日 P&L", "累计"], textStyle: { color: chartTextColor(), fontSize: 10 }, top: 4, itemGap: 10 },
      tooltip: {
        ...chartTooltip("axis", "cross"),
        formatter: (params) => {
          const date = params[0]?.axisValue || "";
          const lines = params.map(p => {
            const v = p.value;
            return `${p.marker} ${p.seriesName}: <b>${v != null ? tipMoney(v) : "—"}</b>`;
          });
          return [date, ...lines].join("<br>");
        },
      },
      xAxis: chartAxis({
        type: "category", data: dates,
        axisLabel: { color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono"), rotate: dates.length > 6 ? 35 : 0,
          hideOverlap: true, formatter: (v) => (v || "").slice(5) },
      }),
      dataZoom: manyPts ? [
        chartDataZoom(zoomStart),
      ] : undefined,
      yAxis: [
        chartAxis({
          type: "value", name: `每日 ${cur}`,
          axisLabel: { color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono"), formatter: axisMoney },
        }),
        chartAxis({
          type: "value", name: `累计 ${cur}`, position: "right",
          splitLine: { show: false },
          axisLabel: { color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono"), formatter: axisMoney },
        }),
      ],
      series: [
        { name: "每日 P&L", type: "bar", data: bars, yAxisIndex: 0, barWidth: "55%" },
        { name: "累计", type: "line", data: cumulative, yAxisIndex: 1,
          itemStyle: { color: accent }, lineStyle: { width: 2 },
          symbol: dates.length > 45 ? "none" : "circle", symbolSize: 4, smooth: 0.1, z: 3 },
      ],
    };
    if (!dates.length) {
      opt.graphic = [{
        type: "text", left: "center", top: "middle",
        style: { text: "暂无每日 P&L 历史", fill: chartTextColor(), fontSize: 13, opacity: 0.5 },
      }];
    }
    charts.dailyPnl.setOption(opt, true);
  }

  function renderSectorChart() {
    const el = document.getElementById("chart-sector");
    if (!el || !window.echarts) return;
    if (!charts.sector) charts.sector = echarts.init(el, null, { renderer: "canvas" });

    const usList = (safe(DATA, "sector_exposure", "us")) || [];
    const hkList = (safe(DATA, "sector_exposure", "hk")) || [];
    // Combine into one donut by region tag
    const slices = [
      ...usList.map(r => ({ name: `US · ${r.sector}`, value: r.value, _pct: r.pct })),
      ...hkList.map(r => ({ name: `HK · ${r.sector}`, value: r.value, _pct: r.pct })),
    ];
    const small = slices.filter(r => Number.isFinite(Number(r._pct)) && Number(r._pct) < 3);
    const combined = slices.filter(r => !small.includes(r));
    if (small.length) {
      combined.push({
        name: "Other",
        value: small.reduce((sum, r) => sum + (Number(r.value) || 0), 0),
        _pct: small.reduce((sum, r) => sum + (Number(r._pct) || 0), 0),
        _members: small.map(r => r.name),
      });
    }

    const palette = [
      "#36A3FF", "#7C8CF2", "#3FB7A9", "#C9974A", "#A96FA8", "#71869D",
    ];

    const opt = {
      ...baseChartOpts(),
      tooltip: {
        ...chartTooltip("item", "line"),
        formatter: (p) => {
          const members = p.data._members?.length
            ? `<br><span style="color:#A6B2C1">${p.data._members.join(" · ")}</span>`
            : "";
          return `${p.name}<br>${p.value.toLocaleString()} (${p.data._pct?.toFixed(1)}%)${members}`;
        },
      },
      legend: {
        type: "scroll",
        orient: window.innerWidth >= 1024 ? "vertical" : "horizontal",
        right: window.innerWidth >= 1024 ? 8 : "center",
        top: window.innerWidth >= 1024 ? "center" : "bottom",
        textStyle: { color: chartTextColor(), fontSize: 10 },
      },
      series: [{
        type: "pie",
        radius: ["38%", "62%"],
        center: window.innerWidth >= 1024 ? ["38%", "50%"] : ["50%", "44%"],
        data: combined,
        itemStyle: { borderColor: getCSS("--surface-1") || "#0F1620", borderWidth: 2 },
        label: { show: false },
        emphasis: { label: { show: true, formatter: "{b}\n{d}%", color: chartTextColor(), fontSize: 11 } },
        color: palette,
      }],
    };
    if (!combined.length) {
      opt.graphic = [{
        type: "text", left: "center", top: "middle",
        style: { text: "No sector data", fill: chartTextColor(), fontSize: 13, opacity: 0.5 },
      }];
    }
    charts.sector.setOption(opt, true);
  }

  function renderRealizedChart() {
    const el = document.getElementById("chart-realized");
    if (!el || !window.echarts) return;
    if (!charts.realized) charts.realized = echarts.init(el, null, { renderer: "canvas" });

    const r = safe(DATA, "realized_vs_unrealized") || {};
    const fx = safe(DATA, "fx", "usdhkd") || 7.83;
    const us = r.us || {}; const hk = r.hk || {}; const cb = r.combined_usd || {};

    // Single USD-eq view, horizontal bars per region
    const cats = ["US", "HK", "合计"];
    const realized = [
      us.realized,
      hk.realized != null ? hk.realized / fx : null,
      cb.realized,
    ];
    const unrealized = [
      us.unrealized,
      hk.unrealized != null ? hk.unrealized / fx : null,
      cb.unrealized,
    ];

    const green = getCSS("--positive") || "#28C08D";
    const accent = getCSS("--accent") || "#36A3FF";

    const opt = {
      ...baseChartOpts(),
      grid: { left: 70, right: 50, top: 34, bottom: 28 },
      legend: { data: ["已实现", "浮动"], textStyle: { color: chartTextColor(), fontSize: 10 }, top: 4, itemGap: 10 },
      tooltip: {
        ...chartTooltip("axis", "shadow"),
        formatter: (params) => {
          const cat = params[0]?.axisValue || "";
          const lines = params.map(p =>
            `${p.marker} ${p.seriesName}: <b>${p.value != null ? "$" + p.value.toLocaleString("en-US", { maximumFractionDigits: 0 }) : "—"}</b>`
          );
          return [cat + " (USD-eq)", ...lines].join("<br>");
        },
      },
      xAxis: chartAxis({
        type: "value",
        axisLabel: { color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono"),
          formatter: (v) => "$" + (Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + "k" : v) },
      }),
      yAxis: chartAxis({
        type: "category", data: cats, inverse: true,
        splitLine: { show: false },
        axisLabel: { color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono"), fontWeight: 600 },
      }),
      series: [
        { name: "已实现", type: "bar", data: realized,
          itemStyle: { color: green, opacity: 0.9 }, barWidth: 18, barGap: "10%",
          label: { show: true, position: "right", color: chartTextColor(), fontSize: 10,
            formatter: (p) => p.value != null ? "$" + Math.round(p.value).toLocaleString() : "" } },
        { name: "浮动", type: "bar", data: unrealized,
          itemStyle: { color: accent, opacity: 0.9 }, barWidth: 18,
          label: { show: true, position: "right", color: chartTextColor(), fontSize: 10,
            formatter: (p) => p.value != null ? "$" + Math.round(p.value).toLocaleString() : "" } },
      ],
    };
    charts.realized.setOption(opt, true);
  }

  // =========================================================
  // Weight × Confidence Scatter (Drill, ECharts)
  // =========================================================
  function renderWeightConfidence() {
    const el = document.getElementById("chart-weight-conf");
    if (!el || !window.echarts) return;
    if (!charts.weightConf) charts.weightConf = echarts.init(el, null, { renderer: "canvas" });

    const list = safe(DATA, "weight_confidence") || [];
    const quadrantColor = {
      high_risk:      getCSS("--negative") || "#F05B67",
      conviction:     getCSS("--accent") || "#36A3FF",
      low_conv_small: getCSS("--warning") || "#E3A640",
      comfort:        getCSS("--positive") || "#28C08D",
      no_data:        getCSS("--neutral") || "#7E8DA1",
    };
    const points = list.map(p => ({
      name: p.ticker,
      value: [p.weight_pct, (p.avg_confidence != null ? p.avg_confidence * 100 : null), p.n_actions],
      itemStyle: { color: quadrantColor[p.quadrant] || quadrantColor.no_data },
      _quad: p.quadrant,
      _region: p.region,
    })).filter(p => p.value[1] != null);

    // No-data tickers: plot at conf=50 (mid) as grey ghost dots — still visible
    const ghosts = list.filter(p => p.avg_confidence == null).map(p => ({
      name: p.ticker,
      value: [p.weight_pct, 50, 0],
      itemStyle: { color: quadrantColor.no_data, opacity: 0.6 },
      _quad: "no_data",
      _region: p.region,
    }));

    const opt = {
      ...baseChartOpts(),
      grid: { left: 50, right: 30, top: 30, bottom: 50, containLabel: true },
      tooltip: {
        ...chartTooltip("item", "line"),
        formatter: (p) => {
          const q = p.data._quad === "high_risk" ? "⚠ High Risk"
                  : p.data._quad === "conviction" ? "Conviction"
                  : p.data._quad === "low_conv_small" ? "Low Conv (small)"
                  : p.data._quad === "comfort" ? "Comfort"
                  : "No data";
          return `<b>${p.data.name}</b> (${p.data._region.toUpperCase()})<br>
            weight within ${p.data._region.toUpperCase()} leg: ${p.value[0]}%<br>
            conf: ${p.value[1] == null ? "n/a" : p.value[1].toFixed(1) + "%"}<br>
            n_actions: ${p.value[2]}<br>
            <span style="color:${p.color}">${q}</span>`;
        },
      },
      xAxis: chartAxis({
        name: "Weight within US/HK leg %", nameLocation: "middle", nameGap: 28,
        // 70 leaves buffer for the 00100 bubble (weight ~57% + symbol radius ~42px)
        type: "value", min: 0, max: 70,
        splitLine: { lineStyle: { color: chartGridColor(), opacity: 0.5 } },
        axisLabel: { color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono"), formatter: "{value}%" },
      }),
      yAxis: chartAxis({
        name: "Avg Confidence %", nameLocation: "middle", nameGap: 40,
        type: "value", min: 30, max: 100,
        splitLine: { lineStyle: { color: chartGridColor(), opacity: 0.5 } },
        axisLabel: { color: chartLabelColor(), fontSize: 10, fontFamily: getCSS("--mono"), formatter: "{value}%" },
      }),
      // Reference lines: weight=20%, conf=65%
      series: [{
        type: "scatter",
        // Cap at 42 so even a 57% weight bubble fits inside the xAxis(=70) buffer
        symbolSize: (v) => Math.max(14, Math.min(42, 14 + v[0] * 0.6)),
        data: [...points, ...ghosts],
        label: {
          // bottom position avoids label colliding with neighbouring bubbles
          // (notably 00100/07226 cluster) and never overflows the right edge
          show: true, position: "bottom", distance: 4,
          fontSize: 10, color: chartTextColor(),
          formatter: (p) => p.data.name,
        },
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { color: chartGridColor(), type: "dashed", width: 1 },
          label: { show: false },
          data: [
            { xAxis: 20 },
            { yAxis: 65 },
          ],
        },
        markArea: {
          silent: true,
          itemStyle: { color: echarts.color.modifyAlpha(quadrantColor.high_risk, .06) },
          data: [[{ xAxis: 20, yAxis: 30 }, { xAxis: 70, yAxis: 65 }]],
        },
      }],
    };
    if (!points.length && !ghosts.length) {
      opt.graphic = [{
        type: "text", left: "center", top: "middle",
        style: { text: "No weight/confidence data", fill: chartTextColor(), fontSize: 13, opacity: 0.5 },
      }];
    }
    charts.weightConf.setOption(opt, true);
  }
