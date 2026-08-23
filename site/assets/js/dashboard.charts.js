  // ── Lazy chart init (perf) ──────────────────────────────────────────────
  // Hero's visual anchor is native Canvas, so first paint does not fetch or parse
  // ECharts. The heavier bundle remains tab-lazy for analytical detail charts.
  // Never initialize a chart in display:none.
  const NATIVE_CHART_FNS = {
    hero: () => { renderEquityChart(); },
  };
  const CHART_FNS = {
    drill:   () => { renderShadowPortfolioChart(); renderWeightConfidence(); },
    risk:    () => { renderSectorChart(); },
    reflect: () => { renderShadowChart(); renderRealizedChart(); renderDailyPnlChart(); },
  };
  const _chartTabsShown = new Set();
  let _echartsPromise = null;
  function whenEcharts(cb) {
    if (window.echarts) return cb();
    if (!_echartsPromise) {  // first chart tab shown → fetch the bundle once
      _echartsPromise = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = "assets/js/echarts.min.js";
        s.onload = () => window.echarts
          ? resolve(true)
          : reject(new Error("ECharts loaded without a global"));
        s.onerror = () => reject(new Error("ECharts bundle failed to load"));
        document.head.appendChild(s);
      }).catch(error => {
        console.error(error);
        _echartsPromise = null;       // a later activation may retry
        return false;
      });
    }
    _echartsPromise.then(ready => { if (ready && window.echarts) cb(); });
  }
  function paintCharts(t) {
    if (!DATA) return;
    if (NATIVE_CHART_FNS[t]) {
      readThemeCSS();
      NATIVE_CHART_FNS[t]();
      return;
    }
    if (!CHART_FNS[t]) return;
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
    if (!NATIVE_CHART_FNS[t] && !CHART_FNS[t]) return;
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
    // Reflect has already loaded ECharts. A market switch on Hero must not fetch
    // the heavy bundle merely to refresh a hidden detail chart.
    if (window.echarts) renderDailyPnlChart();
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

  function createNativeEquityChart(el) {
    el.innerHTML = `
      <canvas class="native-equity-canvas" role="img"
        aria-label="总利润、真实总资产、成本基础、基准与回撤历史图"></canvas>
      <div class="native-equity-tooltip" hidden></div>
      <label class="native-equity-window" hidden>
        <span>时间窗口</span>
        <input type="range" min="0" value="0" aria-label="净值图起始日期">
      </label>`;
    const canvas = el.querySelector(".native-equity-canvas");
    const tooltip = el.querySelector(".native-equity-tooltip");
    const windowControl = el.querySelector(".native-equity-window");
    const range = windowControl.querySelector("input");
    const ctx = canvas.getContext("2d");
    let model = null;
    let hoverIndex = null;
    let userWindow = false;
    let frame = 0;

    const finite = v => v != null && Number.isFinite(Number(v));
    const moneyAxis = (v, cur) =>
      cur + (Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + "k" : Math.round(v));
    const moneyTip = (v, cur) =>
      cur + Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });

    function scheduleDraw() {
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(draw);
    }

    function drawLine(points, xAt, yAt, spec) {
      ctx.beginPath();
      let started = false;
      points.forEach((v, i) => {
        if (!finite(v)) return;
        const x = xAt(i), y = yAt(Number(v));
        if (!started) { ctx.moveTo(x, y); started = true; }
        else ctx.lineTo(x, y);
      });
      if (!started) return;
      ctx.strokeStyle = spec.color;
      ctx.lineWidth = spec.width || 1.5;
      ctx.globalAlpha = spec.opacity == null ? 1 : spec.opacity;
      ctx.setLineDash(spec.dashed ? [5, 4] : []);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }

    function draw() {
      frame = 0;
      if (!model) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const sliderHeight = model.dates.length > 30 ? 26 : 0;
      const width = Math.max(280, el.clientWidth);
      const height = Math.max(220, el.clientHeight - sliderHeight);
      if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        canvas.style.width = width + "px";
        canvas.style.height = height + "px";
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      if (!model.dates.length) {
        ctx.fillStyle = chartTextColor();
        ctx.globalAlpha = .5;
        ctx.font = "13px " + (getCSS("--font") || "sans-serif");
        ctx.textAlign = "center";
        ctx.fillText("暂无快照历史", width / 2, height / 2);
        ctx.globalAlpha = 1;
        return;
      }

      const start = Math.min(Number(range.value) || 0, Math.max(0, model.dates.length - 2));
      const dates = model.dates.slice(start);
      const lines = model.lines.map(line => ({ ...line, values: line.values.slice(start) }));
      const dd = model.dd.slice(start);
      const left = width < 640 ? 48 : 68;
      const right = width < 640 ? 42 : 62;
      const top = width < 640 ? 58 : 42;
      const bottom = 28;
      const plotW = Math.max(1, width - left - right);
      const plotH = Math.max(1, height - top - bottom);
      const moneyValues = lines.flatMap(line => line.values.filter(finite).map(Number));
      if (finite(model.triggerLevel)) moneyValues.push(Number(model.triggerLevel));
      if (moneyValues.some(v => v <= 0) && moneyValues.some(v => v >= 0)) moneyValues.push(0);
      let minMoney = moneyValues.length ? Math.min(...moneyValues) : 0;
      let maxMoney = moneyValues.length ? Math.max(...moneyValues) : 1;
      const pad = Math.max((maxMoney - minMoney) * .08, 1);
      minMoney -= pad;
      maxMoney += pad;
      const minDd = Math.min(-1, ...dd.filter(finite).map(Number));
      const xAt = i => left + (dates.length <= 1 ? plotW / 2 : i * plotW / (dates.length - 1));
      const yMoney = v => top + (maxMoney - v) * plotH / (maxMoney - minMoney || 1);
      const yDd = v => top + (0 - v) * plotH / (0 - minDd || 1);

      ctx.font = "10px " + (getCSS("--mono") || "monospace");
      ctx.textBaseline = "middle";
      // 回撤轴的刻度步长随数据量级变化：minDd 只有 -1.4% 时，5 个刻度用
      // toFixed(0) 会压成 0% / -0% / -1% / -1% / -1%（实测线上就是这样）。
      // 精度跟着步长走，并把 -0 归零。
      const ddStep = Math.abs(minDd) / 4;
      const ddDigits = ddStep >= 1 ? 0 : ddStep >= 0.2 ? 1 : 2;
      const ddLabel = v => {
        const snapped = Math.abs(v) < Math.pow(10, -ddDigits) / 2 ? 0 : v;
        return snapped.toFixed(ddDigits) + "%";
      };
      for (let i = 0; i <= 4; i++) {
        const y = top + i * plotH / 4;
        const value = maxMoney - i * (maxMoney - minMoney) / 4;
        ctx.strokeStyle = chartGridColor();
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(width - right, y);
        ctx.stroke();
        ctx.fillStyle = chartLabelColor();
        ctx.textAlign = "right";
        ctx.fillText(moneyAxis(value, model.cur), left - 7, y);
        ctx.textAlign = "left";
        ctx.fillText(ddLabel(i * minDd / 4), width - right + 7, y);
      }

      const labelCount = Math.min(5, dates.length);
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      for (let i = 0; i < labelCount; i++) {
        const idx = labelCount === 1 ? 0 : Math.round(i * (dates.length - 1) / (labelCount - 1));
        ctx.fillStyle = chartLabelColor();
        ctx.fillText(String(dates[idx] || "").slice(5), xAt(idx), height - bottom + 8);
      }

      // Drawdown uses the secondary axis and is kept behind all money series.
      ctx.beginPath();
      let ddStarted = false;
      dd.forEach((v, i) => {
        if (!finite(v)) return;
        const x = xAt(i), y = yDd(Number(v));
        if (!ddStarted) { ctx.moveTo(x, y); ddStarted = true; }
        else ctx.lineTo(x, y);
      });
      if (ddStarted) {
        ctx.lineTo(xAt(dd.length - 1), yDd(0));
        ctx.lineTo(xAt(0), yDd(0));
        ctx.closePath();
        ctx.fillStyle = model.negative;
        ctx.globalAlpha = .13;
        ctx.fill();
        ctx.globalAlpha = 1;
      }

      // Profit remains the visual anchor with a subtle area to the zero line.
      const profit = lines[0];
      const profitPoints = profit.values.map((v, i) => finite(v) ? [xAt(i), yMoney(Number(v))] : null)
        .filter(Boolean);
      if (profitPoints.length) {
        ctx.beginPath();
        profitPoints.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
        const zeroY = Math.max(top, Math.min(top + plotH, yMoney(0)));
        ctx.lineTo(profitPoints[profitPoints.length - 1][0], zeroY);
        ctx.lineTo(profitPoints[0][0], zeroY);
        ctx.closePath();
        ctx.fillStyle = profit.color;
        ctx.globalAlpha = .08;
        ctx.fill();
        ctx.globalAlpha = 1;
      }

      lines.forEach(line => drawLine(line.values, xAt, yMoney, line));
      if (minMoney <= 0 && maxMoney >= 0) {
        const y = yMoney(0);
        ctx.strokeStyle = model.positive;
        ctx.globalAlpha = .5;
        ctx.setLineDash([2, 3]);
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(width - right, y);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
      }
      if (finite(model.triggerLevel)) {
        const y = yMoney(Number(model.triggerLevel));
        if (y >= top && y <= top + plotH) {
          ctx.strokeStyle = model.warning;
          ctx.setLineDash([5, 4]);
          ctx.beginPath();
          ctx.moveTo(left, y);
          ctx.lineTo(width - right, y);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = model.warning;
          ctx.textAlign = "right";
          ctx.textBaseline = "bottom";
          ctx.fillText(model.triggerLabel, width - right, y - 3);
        }
      }

      // Compact legend, wrapping naturally on narrow mobile canvases.
      let lx = 7, ly = 12;
      ctx.font = (width < 640 ? "9px " : "10px ") + (getCSS("--font") || "sans-serif");
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      [...lines, { name: "回撤", color: model.negative }].forEach(item => {
        const itemWidth = 25 + ctx.measureText(item.name).width;
        if (lx + itemWidth > width - 6) { lx = 7; ly += 16; }
        ctx.strokeStyle = item.color;
        ctx.lineWidth = item.width || 2;
        ctx.beginPath();
        ctx.moveTo(lx, ly);
        ctx.lineTo(lx + 15, ly);
        ctx.stroke();
        ctx.fillStyle = chartTextColor();
        ctx.fillText(item.name, lx + 19, ly);
        lx += itemWidth + 7;
      });

      if (hoverIndex != null && hoverIndex >= start) {
        const local = hoverIndex - start;
        const x = xAt(local);
        ctx.strokeStyle = getCSS("--focus") || "#8ED0FF";
        ctx.globalAlpha = .65;
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, top + plotH);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
    }

    function showTooltip(event) {
      if (!model || !model.dates.length) return;
      const rect = canvas.getBoundingClientRect();
      const left = rect.width < 640 ? 48 : 68;
      const right = rect.width < 640 ? 42 : 62;
      const start = Number(range.value) || 0;
      const count = model.dates.length - start;
      const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left - left) / Math.max(1, rect.width - left - right)));
      const local = count <= 1 ? 0 : Math.round(ratio * (count - 1));
      hoverIndex = start + local;
      const rows = model.lines.map(line => {
        const v = line.values[hoverIndex];
        return `<span style="color:${line.color}">●</span> ${escapeHtml(line.name)}: <b>${finite(v) ? moneyTip(v, model.cur) : DASH}</b>`;
      });
      const dd = model.dd[hoverIndex];
      const ddAbs = model.ddAbs[hoverIndex];
      let ddText = DASH;
      if (finite(dd)) ddText = Number(dd).toFixed(2) + "%";
      else if (finite(ddAbs)) {
        const amount = Number(ddAbs);
        ddText = `${amount < 0 ? "−" : ""}${moneyTip(Math.abs(amount), model.cur)}` +
          ` <span class="muted">(% 不适用)</span>`;
      }
      rows.push(`<span style="color:${model.negative}">●</span> 回撤: <b>${ddText}</b>`);
      const change = model.change[hoverIndex];
      if (finite(change)) {
        const sign = Number(change) >= 0 ? "+" : "-";
        const pct = model.changePct[hoverIndex];
        const pctText = finite(pct) ? ` (${sign}${Math.abs(Number(pct)).toFixed(2)}%)` : "";
        rows.push(`总利润较昨日: <b>${sign}${moneyTip(Math.abs(change), model.cur)}</b>${pctText}`);
      } else if (hoverIndex === 0) rows.push("总利润较昨日: <b>首日</b>");
      tooltip.innerHTML = `<b>${escapeHtml(model.dates[hoverIndex])}</b><br>${rows.join("<br>")}`;
      tooltip.hidden = false;
      const x = event.clientX - rect.left;
      tooltip.style.left = Math.min(Math.max(8, x + 12), Math.max(8, rect.width - tooltip.offsetWidth - 8)) + "px";
      tooltip.style.top = Math.max(8, event.clientY - rect.top - tooltip.offsetHeight - 10) + "px";
      scheduleDraw();
    }

    const hideTooltip = () => {
      hoverIndex = null;
      tooltip.hidden = true;
      scheduleDraw();
    };
    // Mouse/pen hover continuously. Touch uses a tap for inspection; if that
    // touch becomes a horizontal pager swipe the browser emits pointercancel,
    // which must remove the provisional tooltip instead of leaving it stuck.
    canvas.addEventListener("pointermove", event => {
      if (event.pointerType !== "touch") showTooltip(event);
    });
    canvas.addEventListener("pointerdown", event => {
      if (event.pointerType === "touch") showTooltip(event);
    });
    canvas.addEventListener("pointerleave", event => {
      // Touch emits pointerleave when the finger lifts; keep a deliberate tap's
      // tooltip visible. A real scroll is cleared by pointercancel instead.
      if (event.pointerType !== "touch") hideTooltip();
    });
    canvas.addEventListener("pointercancel", hideTooltip);
    document.addEventListener("pointerdown", event => {
      if (event.pointerType === "touch" && event.target !== canvas) hideTooltip();
    });
    range.addEventListener("input", () => {
      userWindow = true;
      hoverIndex = null;
      tooltip.hidden = true;
      scheduleDraw();
    });

    return {
      setModel(next) {
        const marketChanged = model && model.view !== next.view;
        const lengthChanged = !model || model.dates.length !== next.dates.length;
        model = next;
        range.max = String(Math.max(0, next.dates.length - 2));
        windowControl.hidden = next.dates.length <= 30;
        if (marketChanged || !userWindow || lengthChanged) {
          range.value = String(Math.max(0, next.dates.length - 30));
          userWindow = false;
        }
        scheduleDraw();
      },
      resize: scheduleDraw,
      dispose() {
        if (frame) cancelAnimationFrame(frame);
        el.innerHTML = "";
      },
    };
  }

  function renderEquityChart() {
    const el = document.getElementById("chart-equity");
    if (!el) return;
    if (!charts.equity) charts.equity = createNativeEquityChart(el);

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
    const snaps = (safe(DATA, "overview_equity") || safe(DATA, "snapshots") || [])
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
    // 卡一致。% 仅在利润峰值和当前利润都为正时给，否则 null=无红色填充。
    // 负利润阶段仍保留“峰值至当前”的金额差，tooltip 用它代替误导的负分母 %。
    let peak = -Infinity;
    const ddAbs = [];
    const ddPct = profit.map(v => {
      if (v == null) {
        ddAbs.push(null);
        return null;
      }
      if (v > peak) peak = v;
      ddAbs.push(r2(v - peak));
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

    const lines = [
      { name: "总利润", values: profit, color: green, width: 2.6 },
      { name: taName, values: ta, color: accent, width: 1.8 },
      { name: "成本基础", values: cost, color: dim, width: 1, dashed: true },
    ];
    if (showSPY) lines.push(
      { name: "SPY 等值", values: spy.line, color: benchColor, width: 1.4, opacity: .85 });
    if (showHSTECH) lines.push(
      { name: "恒科等值", values: hst.line, color: hkColor, width: 1.4, opacity: .85 });
    const triggerLabel = triggerLvl == null ? "" :
      `恒科200线触发 ${Math.round(hstech200)}` +
      (reclaimPct != null ? `（需${reclaimPct >= 0 ? "+" : ""}${reclaimPct.toFixed(0)}%）` : "");
    charts.equity.setModel({
      view, dates, lines, dd: ddPct, ddAbs, change: chg, changePct: chgPct, cur,
      positive: green, negative: red, warning: hkColor,
      triggerLevel: triggerLvl, triggerLabel,
    });
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
