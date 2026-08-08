(function () {
  // Detail-only renderer bundle. It is requested on the first non-Hero tab
  // activation, then registers its functions with the critical-path registry.
  // =========================================================
  // Render — orchestrates all sections
  // =========================================================
  // Watch Levels: render latest plan's watch_levels vs current price, color by proximity.
  // watch_levels keys are LLM-authored & free-form, so resolution is heuristic and
  // degrades gracefully (unmappable numeric → no distance; string → shown as condition).
  // Resolve + sort the latest plan's watch_levels into rows ordered by proximity
  // to firing (nearest numeric trigger first; condition-only rows last). Shared by
  // renderWatchLevels (full card) and renderTodayHighlights (Hero top strip).
  function computeWatchRows() {
    const plans = (safe(DATA, "recent_plans") || []).slice()
      .sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
    const latest = plans[0];
    const wl = latest ? safe(latest, "plan", "watch_levels") : null;
    if (!wl || typeof wl !== "object" || !Object.keys(wl).length) return { date: null, rows: [] };

    const hmap = {};
    flatHoldings().forEach(h => { if (h.ticker) hmap[String(h.ticker).toUpperCase()] = h; });
    const idx = safe(DATA, "indices") || {};
    const hkTot = safe(DATA, "totals", "hk") || {};
    const LABELS = { stop:"止损", support:"支撑", breakdown:"破位", target:"目标",
      derisk:"强制减仓", force:"强制减仓", trigger:"触发", resist:"压力", resistance:"压力" };

    function resolve(key) {
      const k = key.toLowerCase();
      if (k.includes("hstech")) return { cur: safe(idx,"HSTECH","price"), ccy:"", who:"恒科", strip:["hstech"] };
      if (k.includes("hsi") || k.includes("hang") || k.includes("seng")) return { cur: safe(idx,"HSI","price"), ccy:"", who:"恒指", strip:["hsi","hang","hangseng","seng"] };
      if (k.includes("spx") || k.includes("sp500")) return { cur: safe(idx,"SPX","price"), ccy:"", who:"SPX", strip:["spx","sp500"] };
      if (k.includes("ndx") || k.includes("nasdaq")) return { cur: safe(idx,"NDX","price"), ccy:"", who:"NDX", strip:["ndx","nasdaq"] };
      if (k.includes("book") || k.includes("derisk")) {
        // book_force_derisk_{hk,us}_pct = 账面回撤到 X% 强制减仓。是百分比阈值，
        // 不是价格 → 拿对应区域的账面回报率% 比较（旧代码误用绝对 HKD 金额→显示 -22042%）。
        const usTot = safe(DATA, "totals", "us") || {};
        const isUs = k.includes("us");
        const cur = isUs ? usTot.pnl_pct : hkTot.pnl_pct;
        // keep force/derisk tokens so labelOf → "强制减仓"; strip only who/unit tokens.
        return { cur, ccy:"%", who: isUs ? "账面 US" : "账面 HK",
                 strip:["book","hk","us","pct"], isPct:true };
      }
      const tok = key.split(/[_\-]/)[0];
      const h = hmap[tok.toUpperCase()];
      if (h) return { cur: h.current_price, ccy: h.region === "hk" ? "HKD" : "USD", who: tok.toUpperCase(), strip:[tok.toLowerCase()] };
      return { cur: null, ccy:"", who: null, strip: [] };
    }
    const labelOf = (toks) => {
      const joined = toks.join("_");
      for (const k in LABELS) if (joined.includes(k)) return LABELS[k];
      return toks.length ? toks.join(" ") : "触发位";
    };

    const rows = Object.entries(wl).map(([key, val]) => {
      const r = resolve(key);
      const who = r.who || key.split(/[_\-]/)[0].toUpperCase();
      const toks = key.toLowerCase().split(/[_\-]/).filter(t => !r.strip.includes(t) && t !== "hkd" && t !== "usd");
      const label = labelOf(toks);
      const numeric = (typeof val === "number" && isFinite(val));
      const cur = (numeric && r.cur != null && isFinite(r.cur)) ? r.cur : null;
      let dist = null, ad = null;
      // % thresholds (book derisk guards): distance is percentage POINTS (cur - val);
      // price levels: relative distance to the level.
      if (cur != null) {
        dist = r.isPct ? (cur - val) : (cur - val) / Math.abs(val) * 100;
        ad = Math.abs(dist);
      }
      return { who, label, val, cur, ccy: r.ccy, numeric, dist, ad, isPct: !!r.isPct,
               cond: numeric ? null : String(val) };
    });
    // nearest resolvable numeric → numeric-without-current → condition-only
    rows.sort((a, b) => {
      const rank = x => (x.ad != null ? 0 : (x.numeric ? 1 : 2));
      const ra = rank(a), rb = rank(b);
      if (ra !== rb) return ra - rb;
      return ra === 0 ? a.ad - b.ad : 0;
    });
    return { date: latest.date || null, rows };
  }

  function renderWatchLevels() {
    const card = document.getElementById("watch-levels-card");
    const list = document.getElementById("watch-levels-list");
    if (!card || !list) return;
    const { date, rows } = computeWatchRows();
    if (!rows.length) { card.style.display = "none"; return; }
    card.style.display = "";
    const dateEl = document.getElementById("watch-levels-date");
    if (dateEl) dateEl.textContent = date ? `${date} 计划` : "Watch Levels";

    list.innerHTML = rows.map(row => {
      if (!row.numeric) {
        return `<div class="wl-row wl-cond"><span class="wl-who">${escapeHtml(row.who)}</span>` +
          `<span class="wl-cond-txt">${escapeHtml(row.cond)}</span></div>`;
      }
      // % thresholds render as percentages + 百分点距离; price levels as money + relative %.
      const fmtVal = (v) => row.isPct ? fmtPct(v, 1) : fmtMoney(v, row.ccy);
      let curHtml = `<span class="wl-cur"></span>`;
      let distHtml = `<span class="wl-dist far">—</span>`;
      if (row.cur != null) {
        const cls = row.ad < 2 ? "near" : row.ad < 5 ? "mid" : "far";
        curHtml = `<span class="wl-cur">现 ${fmtVal(row.cur)}</span>`;
        const distTxt = row.isPct ? `${row.dist >= 0 ? "+" : ""}${row.dist.toFixed(1)}pp` : fmtPct(row.dist, 1);
        distHtml = `<span class="wl-dist ${cls}">${distTxt}${row.ad < 2 ? " ⚠️" : ""}</span>`;
      }
      return `<div class="wl-row"><span class="wl-who">${escapeHtml(row.who)}</span>` +
        `<span class="wl-label">${escapeHtml(row.label)}</span>` +
        `<span class="wl-target">${fmtVal(row.val)}</span>${curHtml}${distHtml}</div>`;
    }).join("");
  }

  // A. Hero top "今日要点" triage strip — pure synthesis of data already in
  // dashboard.json (no new fetch). Answers "what should I look at today" in 5s.
  function renderTodayHighlights() {
    const el = document.getElementById("today-highlights");
    if (!el) return;
    const chips = [];

    // 0. Regime — the day's default stance (same risk_on/neutral/risk_off the brief acts on)
    const rg = safe(DATA, "regime");
    if (rg && rg.label) {
      const map = { risk_on:  { cls:"hl-up",    ic:"🟢", stance:"默认持有, 别瞎动" },
                    neutral:  { cls:"hl-info",  ic:"⚪", stance:"按 frame 常规" },
                    risk_off: { cls:"hl-alert", ic:"🔴", stance:"防御, 优先减杠杆" } };
      const r = map[rg.label] || map.neutral;
      chips.push({ cls: r.cls, icon: r.ic,
        txt: `Regime ${escapeHtml(rg.label.replace("_"," "))} · ${escapeHtml(r.stance)}` });
    }

    // What changed since the previous decision set. Counts are dynamic and come
    // from the canonical delta payload; no live number is baked into static copy.
    const dd = safe(DATA, "decision_delta") || {};
    const changedN = (dd.changed || []).length;
    const newN = (dd.new || []).length;
    const triggeredN = (dd.triggered || []).length;
    if (dd.has_material_change || changedN || newN || triggeredN) {
      chips.push({
        cls: triggeredN ? "hl-alert" : "hl-info",
        icon: triggeredN ? "⚡" : "↻",
        txt: `决策变化 · 新增 ${newN} · 修改 ${changedN} · 触发 ${triggeredN}`,
      });
    }

    // (30d 自评指标 — 主动 vs 持有 alpha + catalyst 纪律 — 不再在此重复;
    //  它们是回顾性统计,归属正下方的 🪞 诚实自评卡,不属于「今日速读」。)

    // 1. Nearest-to-firing trigger (from the shared watch-level resolver)
    const near = (computeWatchRows().rows || []).find(r => r.ad != null);
    if (near) {
      const fire = near.ad < 2;
      chips.push({ cls: fire ? "hl-alert" : "hl-info", icon: fire ? "⚠️" : "🎯",
        txt: `${escapeHtml(near.who)} ${escapeHtml(near.label)} ${fmtMoney(near.val, near.ccy)}`
           + ` · 现 ${fmtMoney(near.cur, near.ccy)} (${fmtPct(near.dist,1)})${fire ? " 即将触发" : ""}` });
    }

    // 2. Biggest mover today (today_movers is pre-sorted by |pct| desc)
    const movers = safe(DATA, "today_movers") || [];
    if (movers.length) {
      const m = movers[0]; const up = (m.today_change_pct || 0) >= 0;
      chips.push({ cls: up ? "hl-up" : "hl-down", icon: up ? "📈" : "📉",
        txt: `今日最大波动 ${escapeHtml(m.ticker)} ${fmtPct(m.today_change_pct,1)}` });
    }

    // 3. Top anomaly (high severity first)
    const anomalies = (safe(DATA, "anomalies") || []).slice()
      .sort((a,b) => (b.severity==="high"?1:0) - (a.severity==="high"?1:0));
    if (anomalies.length) {
      const a = anomalies[0];
      const highN = anomalies.filter(x => x.severity === "high").length;
      chips.push({ cls: a.severity === "high" ? "hl-alert" : "hl-warn", icon: "🚩",
        txt: (highN > 1 ? `${highN} 项高危异常 · ` : `异常 `)
           + `${escapeHtml(a.ticker)}: ${escapeHtml(a.detail)}` });
    }

    // 4. Catalyst dated today
    const cat = safe(DATA, "catalysts") || {};
    // last_updated is HKT-local with slashes ("2026/05/29 12:00 HKT"); catalyst
    // dates use dashes — normalize separators so the match doesn't silently miss.
    const today = (String(safe(DATA, "last_updated") || "").slice(0,10).replace(/\//g, "-"))
      || new Date().toISOString().slice(0,10);
    const todays = [];
    (cat.macro_events||[]).forEach(e => { if (e.date === today) todays.push(`${e.type} ${e.detail}`); });
    (cat.earnings||[]).forEach(e => { if (String(e.date||"").slice(0,10) === today) todays.push(`财报 ${e.ticker||e.symbol||""}`); });
    (cat.fomc||[]).forEach(e => { if (String(e.date||"").slice(0,10) === today) todays.push(`FOMC ${e.detail||""}`); });
    if (todays.length) chips.push({ cls:"hl-info", icon:"📅", txt:`今日事件 · ${escapeHtml(todays[0])}` });

    if (!chips.length) {
      el.style.display = "";
      el.replaceChildren();
      return;
    }
    el.style.display = "";
    // The verdict column is intentionally compact. Movers/anomalies have their
    // own linked strip below and catalysts live in Signals, so the first three
    // decision-driving changes are the overview payload.
    el.innerHTML = chips.slice(0, 3).map(c =>
      `<span class="hl-chip ${c.cls}"><span class="hl-ic">${c.icon}</span>${c.txt}</span>`).join("");
  }

  // 🪞 诚实自评卡 — 把这轮做的诚实层(风险调整判决 / catalyst 纪律 / 辩论决断 / 因子 CI)聚一处
  function renderHonesty() {
    const card = document.getElementById("honesty-card");
    const el = document.getElementById("honesty-body");
    if (!card || !el) return;
    card.classList.remove("is-pending");
    const metrics = safe(DATA, "decision_metrics") || {};
    const delta = safe(DATA, "decision_delta") || {};
    const dm = safe(DATA, "debate_metrics");
    const drv = metrics.by_driver || {};
    if (!metrics.raw_decisions) { card.style.display = "none"; return; }
    const row = (label, val, color) =>
      `<div style="display:flex;justify-content:space-between;gap:var(--space-3);padding:5px 0;border-bottom:1px solid var(--border)">`
      + `<span style="color:var(--text-dim)">${label}</span>`
      + `<span style="font-family:var(--mono);text-align:right;color:${color || 'var(--text)'}">${val}</span></div>`;
    const rows = [];
    const active = metrics.active || {};
    if (active.avg_benefit_pct != null) {
      const ci = active.cluster_ci95 ? ` [${active.cluster_ci95[0].toFixed(2)}, ${active.cluster_ci95[1].toFixed(2)}]` : "";
      rows.push(row("主动 episode 平均方向分", `${active.avg_benefit_pct >= 0 ? "+" : ""}${active.avg_benefit_pct.toFixed(2)}%${ci} · n=${active.n_episodes}`,
        active.avg_benefit_pct >= 0 ? "var(--green)" : "var(--red)"));
    }
    // 同一队列的两行:这里曾把 30d 的平均收益和 episode_backtest 的**全量**资金加权
    // 并排显示,窗口不同、符号相反(-2.36% vs +0.83%),读者会当成"大仓位的 call 更准"。
    // 两行必须同源同窗;全量口径归金额曲线,那张图自己标了。
    if (active.capital_weighted_benefit_pct != null)
      rows.push(row("资金加权平均方向分", `${active.capital_weighted_benefit_pct >= 0 ? "+" : ""}${active.capital_weighted_benefit_pct.toFixed(2)}%`,
        active.capital_weighted_benefit_pct >= 0 ? "var(--green)" : "var(--red)"));
    rows.push(row("今日决策变化", `新增 ${(delta.new || []).length} · 修改 ${(delta.changed || []).length} · 触发 ${(delta.triggered || []).length} · override ${(delta.active_overrides || []).length}`, "var(--text-dim)"));
    if (dm && dm.decisiveness_pct != null)
      rows.push(row("辩论决断率", `${dm.decisiveness_pct}% · 其余=默认 HOLD`, "var(--text-dim)"));
    const fe = [];
    ["catalyst", "technical", "macro", "peer"].forEach(k => {
      const e = drv[k]; if (!e || e.win_rate == null) return;
      const ci = e.cluster_ci95, band = ci ? `[${ci[0].toFixed(1)}–${ci[1].toFixed(1)}]` : "";
      fe.push(`${k} ${(e.win_rate * 100).toFixed(0)}% ${band}`);
    });
    if (fe.length) rows.push(row("消息源 edge", fe.join(" · "), "var(--text-dim)"));
    el.innerHTML = rows.join("")
      + `<div style="color:var(--text-dim);font-size:10px;margin-top:var(--space-2)">算账在 Python：同策略连续决策按 episode 去重；一个 episode 只出一个样本、取其内部平均而非选某一条；被判定未触发的不结算；执行与建议质量分开统计。</div>`;
    card.style.display = "";
  }

  // Desk rail KPIs come straight from DATA so deep-linked/non-active panels never
  // have to render just to replace a rail dash. Formatting matches their canonical
  // cells, and the entire read/compute phase finishes before the DOM write phase.
  function syncDeskRail() {
    const us = safe(DATA, "totals", "us") || {};
    const hk = safe(DATA, "totals", "hk") || {};
    const fx = safe(DATA, "fx", "usdhkd");
    const metrics = safe(DATA, "decision_metrics") || {};
    const activeExec = safe(metrics, "execution_by_kind", "active") || {};
    const totalUsd = fx && us.value_usd != null && hk.value_hkd != null
      ? us.value_usd + hk.value_hkd / fx : null;
    const values = [
      ["dr-book", fmtMoney(totalUsd, "USD"), ""],
      ["dr-pnl-us", fmtMoney(us.today_change_usd, "USD"), pnlClass(us.today_change_usd)],
      ["dr-pnl-hk", fmtMoney(hk.today_change_hkd, "HKD"), pnlClass(hk.today_change_hkd)],
      ["dr-followed", activeExec.rate == null ? DASH : (activeExec.rate * 100).toFixed(1) + "%", "neutral"],
      ["dr-grade", metrics.brier == null ? DASH : metrics.brier.toFixed(3), ""],
    ];
    // Values and semantic classes are computed first, then committed together.
    // The old mirror alternated writes with getComputedStyle() five times, forcing
    // layout after the entire dashboard had just been mutated.
    values.forEach(([id, text, cls]) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = text;
      el.className = "dr-v" + (cls ? " " + cls : "");
    });
    const compact = document.getElementById("dr-compact");
    if (compact) {
      compact.textContent = `Book ${values[0][1]} · US ${values[1][1]} · HK ${values[2][1]} · Followed ${values[3][1]} · Brier ${values[4][1]}`;
      compact.title = compact.textContent;
    }

    // Hero promotion: rate includes its known execution sample; calibration
    // explicitly compares against the leave-one-out baseline and names n.
    const followed = document.getElementById("overview-followed");
    const followedMeta = document.getElementById("overview-followed-meta");
    const brier = document.getElementById("overview-brier");
    const brierMeta = document.getElementById("overview-brier-meta");
    const activeCal = safe(metrics, "calibration", "active") || {};
    if (followed) {
      followed.textContent = values[3][1];
      followed.className = "overview-discipline-value neutral";
    }
    if (followedMeta) {
      followedMeta.textContent = activeExec.known == null ? "known sample —" : `known n=${activeExec.known}`;
    }
    if (brier) {
      brier.textContent = metrics.brier == null ? DASH : metrics.brier.toFixed(3);
      brier.className = "overview-discipline-value " +
        (metrics.brier_beats_baseline === true ? "pos" :
          metrics.brier_beats_baseline === false ? "neg" : "neutral");
    }
    if (brierMeta) {
      const baseline = metrics.brier_baseline_loo ?? activeCal.baseline_loo;
      const n = activeCal.n;
      brierMeta.textContent = `vs LOO ${baseline == null ? DASH : baseline.toFixed(3)} · active n=${n == null ? DASH : n}`;
    }
  }

  function renderOverviewSummaries() {
    const moverEl = document.getElementById("overview-mover-summary");
    const anomalyCount = document.getElementById("overview-anomaly-count");
    const anomalySummary = document.getElementById("overview-anomaly-summary");
    const movers = (safe(DATA, "today_movers") || []).slice().sort((a, b) =>
      Math.abs(b.today_change_pct || 0) - Math.abs(a.today_change_pct || 0)
    );
    const anomalies = safe(DATA, "anomalies") || [];
    if (moverEl) {
      if (!movers.length) {
        moverEl.textContent = "No ≥3% movers";
        moverEl.className = "overview-mover-summary neutral";
      } else {
        const m = movers[0];
        moverEl.innerHTML = `<span class="tk">${escapeHtml(m.ticker || DASH)}</span>${fmtPct(m.today_change_pct, 1)}`;
        moverEl.className = "overview-mover-summary " + pnlClass(m.today_change_pct);
      }
    }
    if (anomalyCount) {
      anomalyCount.textContent = String(anomalies.length);
      anomalyCount.className = "overview-anomaly-count " +
        (anomalies.some(a => a.severity === "high") ? "neg" : anomalies.length ? "warn-text" : "pos");
    }
    if (anomalySummary) {
      const highN = anomalies.filter(a => a.severity === "high").length;
      const top = anomalies.find(a => a.severity === "high") || anomalies[0];
      anomalySummary.textContent = !anomalies.length
        ? "No anomalies detected."
        : `${highN} high · ${top?.ticker || DASH} ${top?.detail || ""}`;
    }
  }

  const TAB_RENDERERS = {
    hero: [
      renderTodayHighlights, renderHonesty, renderMarketSnapshot, renderTotals,
      renderTodayPnl, renderRiskGuardrail, renderOverviewSummaries, renderGoldDca,
    ],
    drill: [
      renderDecisionMatrix, renderHoldings, renderExtremes, renderMovers,
      renderAnomalies, render8dHeatmap, renderTodayRange, renderShadowPortfolioCard,
    ],
    risk: [
      renderRiskGuardrail, renderHHI, renderLeveragedETF, renderRiskMetrics, renderLevRegime,
      renderReentryRadar, renderBreakevenMath, renderHistoricalExtremes,
    ],
    market: [
      renderQuantSignals, renderT0Setups, renderCatalysts, renderInfluencer,
      renderNewsDigest, renderMacro, renderPeerDivergence, renderSectorContext,
    ],
    plan: [
      renderWatchLevels, renderPlanActions, renderPlanTimeline,
      renderBearCases, renderHiddenConcentration,
    ],
    reflect: [
      renderBehavioralReview, renderDecisionAudit, renderCalibBadge,
      renderPlanReview, renderCalibByTrigger, renderCalibByDriver,
      renderReflectKpi, renderDelta,
    ],
  };
  let RENDER_VERSION = 0;
  const _tabRenderVersion = new Map();

  function renderTab(t, version = RENDER_VERSION) {
    if (!DATA || !TAB_RENDERERS[t] || _tabRenderVersion.get(t) === version) return;
    TAB_RENDERERS[t].forEach(fn => fn());
    _tabRenderVersion.set(t, version);
    // Reservation stays in CSS for CLS, but an active panel must never retain a
    // stale visibility:hidden marker after its synchronous renderer pass.
    const panel = document.querySelector(`.panel[data-panel="${t}"]`);
    if (panel) panel.querySelectorAll(".card.is-pending").forEach(card =>
      card.classList.remove("is-pending"));
    if (t === "risk" || t === "market") updateFoldPeeks();
  }

  // Re-render the visible tab after its sidecars revalidate. Hidden tabs are
  // never runtime consumers: their cached data is marked stale by the poll and
  // they render only when activated.
  function refreshTab(t) {
    if (!DATA || !TAB_RENDERERS[t] || currentTab() !== t) return;
    TAB_RENDERERS[t].forEach(fn => fn());
    _tabRenderVersion.set(t, RENDER_VERSION);
    const panel = document.querySelector(`.panel[data-panel="${t}"]`);
    if (panel) panel.querySelectorAll(".card.is-pending").forEach(card =>
      card.classList.remove("is-pending"));
    if (t === "risk" || t === "market") updateFoldPeeks();
    if (currentTab() === t) ensureTabCharts(t);
  }

  function render() {
    if (!DATA) return;
    const version = ++RENDER_VERSION;
    const activeTab = currentTab();
    renderHeader();
    renderStatusBanner();
    syncDeskRail();                 // direct DATA path: never waits for Reflect
    renderTab(activeTab, version);  // first paint only pays for the visible tab
    renderBuildStatus();
    syncDeskRail();
    ensureVisibleCharts();
  }

  function quoteSessionLabel(market) {
    const oldest = market && market.oldest_quote_session;
    const newest = market && market.newest_quote_session;
    if (!oldest && !newest) return '行情会话未知';
    if (!oldest) return String(newest);
    if (!newest) return String(oldest);
    return oldest === newest ? String(newest) : `${oldest} → ${newest}`;
  }

  // ── A2 系统健康卡（页脚）──
  // 数据新鲜度 + 体检结论（A1）的被动展示。不推送（遵 feedback_no_individual_cron_alerts），
  // 让 stale / 体检异常一眼可见。绿=全新鲜且体检过；黄=有 stale 或 WARN；红=体检 ERROR。
  function renderBuildStatus() {
    const el = document.getElementById('build-status');
    if (!el) return;
    const bs = safe(DATA, 'build_status');
    if (!bs) { el.style.display = 'none'; return; }
    const wf = safe(DATA, 'workflow_outcomes') || {};
    const wfCounts = wf.counts || {};
    el.style.display = '';
    const ig = bs.integrity || {};
    const stale = bs.stale_files || [];
    const recovered = (wfCounts.recovered || 0) + (wfCounts.degraded || 0);
    const artifactOnly = wfCounts.artifact_only || 0;
    let dot, label;
    if ((wfCounts.failed || 0) > 0) {
      dot = '🔴'; label = `成品流程 ${wfCounts.failed} FAILED`;
    }
    else if (ig.error_count > 0) { dot = '🔴'; label = `体检 ${ig.error_count} ERROR`; }
    else if (stale.length || ig.warn_count > 0 || recovered || artifactOnly) {
      dot = '🟡';
      const bits = [];
      if (stale.length) bits.push(`${stale.length} 文件 stale`);
      if (ig.warn_count > 0) bits.push(`体检 ${ig.warn_count} WARN`);
      if (recovered) bits.push(`${recovered} 成品恢复/降级`);
      if (artifactOnly) bits.push(`${artifactOnly} 仅产物未确认投递`);
      label = bits.join(' · ');
    } else { dot = '🟢'; label = '数据健康 · 体检 ✓'; }
    if (wf.raw_error_but_product_usable) {
      label += ` · ${wf.raw_error_but_product_usable} 执行红/成品可用`;
    }
    // tooltip：逐文件年龄 + 体检 top + 每市场时点
    const lines = [];
    (bs.files || []).forEach(f => {
      if (!f.present) lines.push(`✗ ${f.name} 缺失`);
      else if (f.freshness_mode === 'scheduled_fire') {
        const deadline = f.deadline_at
          ? new Date(f.deadline_at).toLocaleString('zh-CN', {
              month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
              hour12: false, timeZone: 'Asia/Hong_Kong',
            })
          : '未知';
        lines.push(`${f.stale ? '⚠' : '·'} ${f.name}  ${f.age_hours}h · 应于 ${deadline} HKT 前刷新`);
      }
      else lines.push(`${f.stale ? '⚠' : '·'} ${f.name}  ${f.age_hours}h / SLA ${f.sla_hours}h`);
    });
    (ig.top || []).forEach(t => lines.push(`${t.level === 'ERROR' ? '🔴' : '🟡'} ${t.code}: ${t.msg}`));
    if (bs.markets) {
      Object.entries(bs.markets).forEach(([m, v]) =>
        lines.push(`${m.toUpperCase()}: 行情会话 ${quoteSessionLabel(v)}${v.closed_today ? ' (休市)' : ''}`));
    }
    (wf.recent || []).slice(0, 8).forEach(r => {
      const raw = (r.raw_execution || {}).status || 'unknown';
      const final = (r.final_product || {}).status || 'pending';
      const slot = (r.slot || '').replace('T', ' ').slice(5, 16);
      const readability = r.readability || {};
      const readabilityDetail = readability.status
        ? ` / 可读性=${readability.status}${Number.isFinite(readability.bytes) ? ` ${(readability.bytes / 1000).toFixed(1)}KB` : ''}`
        : '';
      lines.push(`流程 ${r.job} ${slot}: 执行=${raw} / 成品=${final}${readabilityDetail}`);
    });
    const gen = bs.generated_at ? bs.generated_at.replace('T', ' ').slice(0, 16) : '';
    el.innerHTML = `<span class="bs-dot">${dot}</span> <span class="bs-label">${label}</span>` +
      `<span class="bs-gen">构建 ${gen}</span>`;
    el.title = lines.join('\n');
  }

  // ── Mobile fold peeks ──
  // One-line summaries shown in the collapsed diagnostic cards' headers.
  // Reads the values straight from the already-rendered DOM (not from DATA)
  // so it never drifts from what the expanded card would show.
  function updateFoldPeeks() {
    const txt = (sel) => {
      const el = document.querySelector(sel);
      return el ? el.textContent.trim() : "";
    };
    const setPeek = (id, parts) => {
      const el = document.getElementById(id);
      if (el) el.textContent = parts.filter(Boolean).join(" · ");
    };
    setPeek("peek-conc", [
      txt("#hhi-us .inner") && "US " + txt("#hhi-us .inner"),
      txt("#hhi-hk .inner") && "HK " + txt("#hhi-hk .inner"),
    ]);
    setPeek("peek-lev", [txt("#lev-combined") && "综合 " + txt("#lev-combined")]);
    const alerts = txt("#risk-alert-count").replace(/[()\s]/g, "");
    setPeek("peek-riskm", [
      txt("#risk-beta-us") && "β " + txt("#risk-beta-us"),
      txt("#risk-vol") && "vol " + txt("#risk-vol"),
      alerts && alerts + "⚠",
    ]);
    setPeek("peek-levregime", [
      txt("#lev-regime-label") && "HK " + txt("#lev-regime-label"),
      txt("#lev-regime-cap"),
    ]);
    const qn = document.querySelectorAll("#quant-tbody tr").length;
    setPeek("peek-quant", [qn ? qn + " 标的信号" : ""]);
    const bn = document.querySelectorAll("#breakeven-list > *").length;
    setPeek("peek-breakeven", [bn ? bn + " 标的待回本" : ""]);
  }

  function renderHeader() {
    // Header age label is owned by loadData() / _updateAgeLabel — they keep it
    // synced with the relative-time formatter even between refreshes. Calling
    // _updateAgeLabel here just covers the first render before LAST_LOADED_AT is set.
    _updateAgeLabel();
  }

  // Display order for the Market Snapshot card.
  const MARKET_INDICES = ["SPX", "NDX", "DJI", "HSI", "HSTECH"];

  // Parse a YYYY/MM/DD or YYYY-MM-DD timestamp out of the source string so we
  // can flag stale (>1 trading day old) data with a ⚠ marker. Compare in UTC
  // calendar-day terms (Date.UTC truncates the time) so the same source string
  // doesn't look "1 day old" just because the user is in a different timezone.
  function _indexAgeDays(src) {
    if (!src) return null;
    const m = src.match(/(20\d\d)[-/](\d{2})[-/](\d{2})/);
    if (!m) return null;
    const srcUTC = Date.UTC(+m[1], +m[2] - 1, +m[3]);
    const now = new Date();
    const nowUTC = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    return Math.max(0, Math.round((nowUTC - srcUTC) / 86400000));
  }

  function renderMarketSnapshot() {
    const idx = safe(DATA, "indices") || {};
    const grid = document.getElementById("market-grid");
    const asof = document.getElementById("market-asof");
    const rsRow = document.getElementById("market-rs");
    if (!grid) return;

    const cells = MARKET_INDICES.filter(k => idx[k]).map(k => {
      const r = idx[k];
      const pct = r.change_pct;
      const cls = (pct == null) ? "neutral" : (pct > 0 ? "pos" : (pct < 0 ? "neg" : "neutral"));
      const ageDays = _indexAgeDays(r.source);
      const stale = ageDays != null && ageDays > 1;
      const priceTxt = (r.price != null)
        ? r.price.toLocaleString("en-US", { maximumFractionDigits: r.price < 100 ? 2 : 0 })
        : DASH;
      const pctTxt = (pct == null) ? DASH : `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`;
      const srcShort = (r.source || "").split(/[@(]/, 1)[0].trim().slice(0, 22);
      return `
        <div class="market-cell ${stale ? "stale" : ""}" title="${escapeHtml(r.source || "")}">
          <div class="lbl">${escapeHtml(k)}</div>
          <div class="val">${priceTxt}</div>
          <div class="pct ${cls}">${pctTxt}</div>
          <div class="src">${escapeHtml(srcShort)}</div>
        </div>`;
    });
    grid.innerHTML = cells.length ? cells.join("") : `<div class="empty-state">No index data.</div>`;

    // As-of line: most recent age across rendered cells
    const ages = MARKET_INDICES.map(k => idx[k] && _indexAgeDays(idx[k].source)).filter(a => a != null);
    if (ages.length && asof) {
      const minAge = Math.min(...ages);
      asof.textContent = minAge === 0 ? "(刚刚)" : minAge === 1 ? "(1 天前)" : `(${minAge} 天前)`;
    }

    // RS: our combined today_pct vs SPX/HSI (region-weighted)
    if (rsRow) {
      const delta = safe(DATA, "delta") || {};
      const usMine = delta.us?.today_pct;
      const hkMine = delta.hk?.today_pct;
      const spx = idx.SPX?.change_pct;
      const hsi = idx.HSI?.change_pct;
      const parts = [];
      if (usMine != null && spx != null) {
        const rs = usMine - spx;
        const cls = rs >= 0 ? "pos" : "neg";
        parts.push(`US 组合 ${usMine.toFixed(2)}% vs SPY ${spx > 0 ? "+" : ""}${spx.toFixed(2)}% → <b class="${cls}">${rs > 0 ? "+" : ""}${rs.toFixed(2)}pp</b>`);
      }
      if (hkMine != null && hsi != null) {
        const rs = hkMine - hsi;
        const cls = rs >= 0 ? "pos" : "neg";
        parts.push(`HK 组合 ${hkMine.toFixed(2)}% vs HSI ${hsi > 0 ? "+" : ""}${hsi.toFixed(2)}% → <b class="${cls}">${rs > 0 ? "+" : ""}${rs.toFixed(2)}pp</b>`);
      }
      rsRow.innerHTML = parts.length ? "RS: " + parts.join(" · ") : "";
    }
  }

  function renderTotals() {
    const us = safe(DATA, "totals", "us") || {};
    const hk = safe(DATA, "totals", "hk") || {};
    const fx = safe(DATA, "fx", "usdhkd");
    const fxMeta = safe(DATA, "fx") || {};

    document.getElementById("us-value").textContent = fmtMoney(us.value_usd, "USD");
    const usPnl = us.pnl_usd;
    const usPnlPct = us.pnl_pct;
    const usPnlEl = document.getElementById("us-pnl");
    usPnlEl.textContent = fmtMoney(usPnl, "USD") + " · " + fmtPct(usPnlPct);
    usPnlEl.className = "sub " + pnlClass(usPnl);

    document.getElementById("hk-value").textContent = fmtMoney(hk.value_hkd, "HKD");
    const hkPnl = hk.pnl_hkd;
    const hkPnlPct = hk.pnl_pct;
    const hkPnlEl = document.getElementById("hk-pnl");
    hkPnlEl.textContent = fmtMoney(hkPnl, "HKD") + " · " + fmtPct(hkPnlPct);
    hkPnlEl.className = "sub " + pnlClass(hkPnl);

    if (fx && us.value_usd != null && hk.value_hkd != null) {
      const totalUsd = us.value_usd + hk.value_hkd / fx;
      const totalHkd = us.value_usd * fx + hk.value_hkd;
      document.getElementById("combined-usd").textContent = fmtMoney(totalUsd, "USD");
      document.getElementById("combined-hkd").textContent = fmtMoney(totalHkd, "HKD");
      const fetchedAt = fxMeta.fetched_at ? new Date(fxMeta.fetched_at) : null;
      const fetched = fetchedAt && !isNaN(fetchedAt)
        ? fetchedAt.toISOString().replace("T", " ").slice(0, 16) + "Z" : "";
      const fxLine = `USDHKD ${fmtNum(fx, 4)}`
        + (fxMeta.source ? ` · ${fxMeta.source}` : "")
        + (fetched ? ` · ${fetched}` : "");
      document.getElementById("fx-rate-usd").textContent = fxLine;
      document.getElementById("fx-rate-hkd").textContent = fxLine;
    } else {
      document.getElementById("combined-usd").textContent = DASH;
      document.getElementById("combined-hkd").textContent = DASH;
      document.getElementById("fx-rate-usd").textContent = "FX unavailable";
      document.getElementById("fx-rate-hkd").textContent = "";
    }
  }

  function renderTodayPnl() {
    const us = safe(DATA, "totals", "us") || {};
    const hk = safe(DATA, "totals", "hk") || {};
    const usChg = us.today_change_usd;
    const hkChg = hk.today_change_hkd;
    // pct: today_change / (value - today_change) — approx today's pct vs yesterday
    const usPct = (us.value_usd != null && usChg != null && (us.value_usd - usChg) > 0)
                  ? (usChg / (us.value_usd - usChg) * 100) : null;
    const hkPct = (hk.value_hkd != null && hkChg != null && (hk.value_hkd - hkChg) > 0)
                  ? (hkChg / (hk.value_hkd - hkChg) * 100) : null;
    const usEl = document.getElementById("today-pnl-us");
    const hkEl = document.getElementById("today-pnl-hk");
    usEl.textContent = fmtMoney(usChg, "USD");
    usEl.className = "val " + pnlClass(usChg);
    hkEl.textContent = fmtMoney(hkChg, "HKD");
    hkEl.className = "val " + pnlClass(hkChg);
    document.getElementById("today-pnl-us-pct").textContent = usPct != null ? fmtPct(usPct) : DASH;
    document.getElementById("today-pnl-hk-pct").textContent = hkPct != null ? fmtPct(hkPct) : DASH;
  }

  function renderDelta() {
    const tbody = document.getElementById("delta-tbody");
    const d = safe(DATA, "delta");
    if (!d) {
      tbody.innerHTML = '<tr><td colspan="3" class="muted">No delta data yet.</td></tr>';
      return;
    }
    const rows = [
      ["Today", safe(d, "us", "today_pct"), safe(d, "hk", "today_pct")],
      ["7d", safe(d, "us", "7d_pct"), safe(d, "hk", "7d_pct")],
      ["30d", safe(d, "us", "30d_pct"), safe(d, "hk", "30d_pct")],
    ];
    tbody.innerHTML = rows.map(([label, u, h]) => `
      <tr>
        <td>${label}</td>
        <td class="${pnlClass(u)}">${fmtPct(u)}</td>
        <td class="${pnlClass(h)}">${fmtPct(h)}</td>
      </tr>
    `).join("");
  }

  function renderHHI() {
    const us = safe(DATA, "concentration", "us") || {};
    const hk = safe(DATA, "concentration", "hk") || {};
    paintHHI("hhi-us", us);
    paintHHI("hhi-hk", hk);
  }
  function paintHHI(id, leg) {
    const el = document.getElementById(id);
    if (!el) return;
    const hhi = leg.hhi;
    const top2 = leg.top2;
    const verdict = leg.verdict || {};
    const ring = el.querySelector(".hhi-ring");
    const inner = el.querySelector(".inner");
    const verdictEl = el.querySelector(".verdict");
    const top2El = el.querySelector(".top2");
    const level = String(verdict.level || "").toLowerCase();
    const state = level === "healthy" || level === "normal"
      ? "normal"
      : level === "danger" || level === "critical"
        ? "critical"
        : level === "moderate" || level === "concentrated" || level === "elevated"
          ? "elevated"
          : "neutral";
    const semanticColor = {
      normal: "var(--positive)",
      elevated: "var(--warning)",
      critical: "var(--negative)",
      neutral: "var(--neutral)",
    }[state];
    if (hhi != null) {
      // Map HHI 0-0.5 to 0-100% of ring (0.5 is essentially worst case for diversified)
      const pct = Math.min(100, Math.max(0, hhi / 0.5 * 100));
      ring.style.setProperty("--pct", pct.toFixed(1));
      ring.style.setProperty("--color", semanticColor);
      inner.textContent = hhi.toFixed(3);
    } else {
      inner.textContent = DASH;
    }
    verdictEl.textContent = verdict.label || DASH;
    verdictEl.style.color = semanticColor;
    top2El.textContent = top2 != null ? "Top 2: " + (top2 * 100).toFixed(1) + "%" : DASH;
  }

  function renderAnomalies() {
    // peer_divergence now has its own 同行背离 card (Market tab) — not in anomalies anymore
    const list = (safe(DATA, "anomalies") || []);
    const wrap = document.getElementById("anomaly-list");
    document.getElementById("anom-count").textContent = list.length ? `(${list.length})` : "";
    if (!list.length) {
      wrap.innerHTML = '<div class="empty-state">No anomalies detected.</div>';
      return;
    }
    const ICONS = {
      rsi_overbought: "🔥",
      peer_divergence: "↗",
      high_weight_loss: "❗",
      leveraged_etf_stop: "🛑",
    };
    wrap.innerHTML = list.map(a => {
      const icon = ICONS[a.type] || "⚠";
      const sev = a.severity || "medium";
      return `
        <div class="anomaly ${sev}">
          <span class="icon">${icon}</span>
          <div class="body">
            <span class="ticker">${a.ticker || DASH}</span>
            <span class="muted"> · ${a.type || ""}</span>
            <div class="detail">${a.detail || ""}</div>
          </div>
        </div>
      `;
    }).join("");
  }

  function renderSectorContext() {
    const wrap = document.getElementById("sector-context");
    if (!wrap) return;
    const ctx = safe(DATA, "market_context") || {};
    const sectors = ctx.sectors || [];
    const asof = document.getElementById("sector-context-asof");
    if (asof) {
      if (ctx.date) {
        const ageDays = Math.floor((Date.now() - new Date(ctx.date + "T00:00:00+08:00").getTime()) / 86400000);
        const stale = ageDays >= 1;
        asof.textContent = `as of ${ctx.date}` + (stale ? ` · ${ageDays}天前 · 待 brief 刷新` : "");
        asof.style.color = stale ? "var(--warning)" : "";
      } else {
        asof.textContent = "";
        asof.style.color = "";
      }
    }
    const narr = document.getElementById("sector-narrative");
    if (narr) {
      if (ctx.narrative) {
        narr.textContent = ctx.narrative;
        narr.style.display = "";
      } else {
        narr.style.display = "none";
      }
    }
    if (!sectors.length) {
      wrap.innerHTML = '<div class="empty-state">等待今日 brief 写入 sector-scan（08:00 HKT 后刷新）</div>';
      return;
    }
    const escape = s => String(s == null ? "" : s).replace(/[<>&"]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;","\"":"&quot;"}[c]));
    const rankClass = txt => {
      const t = (txt || "").toString();
      if (/领涨|领先|榜首|top/i.test(t)) return "lead";
      if (/落后|倒数|垫底|lag/i.test(t)) return "lag";
      return "";
    };
    wrap.innerHTML = sectors.map(s => {
      const movers = (s.top_movers || []).slice(0, 5).map(m => {
        const pct = m.pct == null ? "—" : fmtPct(m.pct, 1);
        const klass = pnlClass(m.pct);
        return `<span class="mover-inline"><span class="${klass}">${escape(m.ticker)} ${pct}</span>` +
               `${m.name ? `<span class="nm">${escape(m.name)}</span>` : ""}` +
               `${m.catalyst ? `<span class="cat">· ${escape(m.catalyst)}</span>` : ""}</span>`;
      }).join("");
      const selfRows = (s.self || []).map(sf => {
        const pct = sf.pct == null ? "" : fmtPct(sf.pct, 1);
        return `<span class="tk">${escape(sf.ticker)}</span> ${pct} · ` +
               `<span class="rank ${rankClass(sf.rank_text)}">${escape(sf.rank_text || "")}</span>` +
               `${sf.attribution ? ` — <span class="attr">${escape(sf.attribution)}</span>` : ""}`;
      }).join("<br>");
      const inBook = (s.tickers_in_book || []).join(", ");
      return `<div class="sector-block">
        <div class="theme">${escape(s.theme)} ${inBook ? `<span class="in-book">[持仓: ${escape(inBook)}]</span>` : ""}</div>
        <div class="movers">${movers || '<span class="muted" style="font-size:11px;opacity:0.55">— LLM 未填 top movers</span>'}</div>
        ${selfRows ? `<div class="self">${selfRows}</div>` : ""}
      </div>`;
    }).join("");
  }

  function renderMovers() {
    const wrap = document.getElementById("movers-scroll");
    const movers = (safe(DATA, "today_movers") || []).slice().sort((a, b) =>
      Math.abs(b.today_change_pct || 0) - Math.abs(a.today_change_pct || 0)
    );
    if (!movers.length) {
      wrap.innerHTML = '<div class="empty-state">No movers ≥3% today.</div>';
      return;
    }
    wrap.innerHTML = movers.map(m => {
      const p = m.today_change_pct;
      const dir = p > 0 ? "up" : p < 0 ? "down" : "";
      const ccy = m.region === "hk" ? "HKD" : "USD";
      const note = m.note ? `<div class="mover-note">${escLLM(m.note)}</div>` : "";
      return `
        <div class="mover-card ${dir}${m.note ? ' has-note' : ''}">
          <div class="tk">${m.ticker || DASH}</div>
          <div class="nm">${m.name || ""}</div>
          <div class="pct ${pnlClass(p)}">${fmtPct(p, 2)}</div>
          <div class="px">${fmtMoney(m.current_price, ccy)}</div>
          ${note}
        </div>
      `;
    }).join("");
  }

  function renderCatalysts() {
    const wrap = document.getElementById('catalysts-list');
    if (!wrap) return;
    const c = safe(DATA, 'catalysts') || {};
    const items = [
      ...(c.earnings || []).map(x => ({...x, _type: 'earnings'})),
      ...(c.fomc || []).map(x => ({...x, _type: 'fomc'})),
      ...(c.macro_events || []).map(x => ({...x, _type: 'macro'})),
    ];
    if (!items.length) {
      wrap.innerHTML = '<div class="empty-state">No upcoming catalysts (next 14d).</div>';
      return;
    }
    items.sort((a, b) => (a.date || '').localeCompare(b.date || ''));
    wrap.innerHTML = items.slice(0, 15).map(x => {
      const tag = x._type === 'earnings' ? (x.ticker || '?') :
                  x._type === 'fomc' ? 'FOMC' :
                  (x.type || 'MACRO');
      const detail = x.detail || x.title || x.time || '—';
      return `<div class="catalyst-row ${x._type}">
        <span class="date">${x.date || '—'}</span>
        <span class="ticker">${tag}</span>
        <span class="detail">${detail}</span>
      </div>`;
    }).join('');

    // 如果只有 macro_events 没 earnings / fomc, 提示用户
    const c2 = safe(DATA, 'catalysts') || {};
    if ((c2.summary?.earnings_count || 0) === 0 && (c2.summary?.fomc_in_window || 0) === 0) {
      const hint = document.createElement('div');
      hint.style.cssText = 'margin-top:var(--space-2);font-size:10.5px;color:var(--text-dim);text-align:center;';
      hint.textContent = 'No earnings / FOMC in 14d window; only macro events surfaced';
      wrap.appendChild(hint);
    }
  }

  function renderInfluencer() {
    const wrap = document.getElementById('infl-feed');
    const sumEl = document.getElementById('infl-summary');
    const asOf = document.getElementById('infl-asof');
    if (!wrap) return;
    const d = safe(DATA, 'influencer_feed') || {};
    const items = d.items || [];
    if (!items.length) {
      if (sumEl) sumEl.innerHTML = '';
      wrap.innerHTML = '<div class="empty-state">No influence signals (48h).</div>';
      return;
    }
    const c = d.counts || {};
    if (sumEl) {
      const chips = [];
      if (c.held_hits)   chips.push(`<span class="infl-chip held">撞持仓 ${c.held_hits}</span>`);
      if (c.new_ideas)   chips.push(`<span class="infl-chip idea">新机会 ${c.new_ideas}</span>`);
      if (c.sector_hits) chips.push(`<span class="infl-chip sect">板块相关 ${c.sector_hits}</span>`);
      sumEl.innerHTML = chips.join('');
    }
    if (asOf && d.generated_at) {
      const ago = Math.round((Date.now() - new Date(d.generated_at).getTime()) / 3.6e6);
      asOf.textContent = `Trump · Musk · Serenity · ${ago}h前${d.llm_filtered ? ' · LLM筛' : ''}`;
    }
    const stanceCls = (s) => ({endorse:'up', buy:'up', attack:'down', sell:'down'}[s] || 'flat');
    const stanceTxt = (s) => ({endorse:'看多', buy:'买入', attack:'看空', sell:'卖出', neutral:'中性'}[s] || s || '');
    wrap.innerHTML = items.map(it => {
      const held = it.held || [], ideas = it.new_ideas || [], sect = it.sector_holdings || [];
      const rowCls = held.length ? 'is-held' : (ideas.length ? 'is-idea' : '');
      const tags = [
        ...held.map(t => `<span class="infl-tag held">持仓 ${escapeHtml(t)}</span>`),
        ...ideas.map(t => `<span class="infl-tag idea">新机会 ${escapeHtml(t)}</span>`),
        ...sect.map(t => `<span class="infl-tag sect">板块·${escapeHtml(t)}</span>`),
        ...(it.sectors || []).map(s => `<span class="infl-tag sect">${escapeHtml(s)}</span>`),
      ].join('');
      const rel = (it.relevance != null) ? `rel ${it.relevance}` : '';
      const src = it.author === 'Musk' ? '新闻代理' : (it.author === 'Serenity' ? 'Substack' : '原帖');
      const link = it.url ? `<a href="${escapeHtml(it.url)}" target="_blank" rel="noopener" style="color:var(--text-dim)">↗</a>` : '';
      return `<div class="infl-row ${rowCls}">
        <div class="infl-hdr">
          <span class="infl-who ${it.author.toLowerCase()}">${escapeHtml(it.author)}</span>
          <span class="infl-stance ${stanceCls(it.stance)}">${escapeHtml(stanceTxt(it.stance))}</span>
          <span class="infl-rel">${rel}</span>
        </div>
        <div class="infl-sum">${escapeHtml(it.summary_cn || it.text || '')}</div>
        ${tags ? `<div class="infl-tags">${tags}</div>` : ''}
        <div class="infl-meta">${src}${link ? ' ' + link : ''}</div>
      </div>`;
    }).join('');
  }

  function renderPeerDivergence() {
    const wrap = document.getElementById('peer-div-list');
    const asOf = document.getElementById('peer-div-asof');
    if (!wrap) return;
    const card = wrap.closest('.card');
    const d = safe(DATA, 'peer_divergence') || {};
    const items = d.items || [];
    // Hide the whole card when there's nothing to show (consistent with
    // honesty/watch-levels) — an empty "今日无背离" card is just clutter on the
    // 8-card 信号 tab.
    if (!items.length) {
      if (card) card.style.display = 'none';
      return;
    }
    if (card) card.style.display = '';
    if (asOf) asOf.textContent = d.as_of ? `${d.as_of} 收盘 1d` : 'Peer Divergence';
    const fmtPctSigned = (v) => v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
    // divergence_pp > 0 → peer beat you (you lag); < 0 → you beat peer (you lead)
    const rows = items.map(it => {
      const gap = it.divergence_pp;
      const lag = (gap != null && gap > 0);
      const cls = lag ? 'lag' : 'lead';
      const gapTxt = gap == null ? '—'
        : (lag ? `落后 ${Math.abs(gap).toFixed(1)}pp` : `领先 ${Math.abs(gap).toFixed(1)}pp`);
      const peer = it.best_peer_name || it.best_peer || '同行';
      return `<div class="peer-div-row ${cls}">
        <div class="pd-top">
          <span class="pd-tk">${escapeHtml(it.ticker)}</span>
          <span class="pd-self">${fmtPctSigned(it.self_pct_1d)}</span>
          <span class="pd-gap ${cls}">${gapTxt}</span>
        </div>
        <div class="pd-vs">vs <b>${escapeHtml(peer)}</b> ${fmtPctSigned(it.peer_pct_1d)}</div>
      </div>`;
    }).join('');
    wrap.innerHTML = rows +
      '<div class="pd-caveat">同行报价为 best-effort 抓取，仅供参照；已过滤缺报价/陈旧快照。</div>';
  }

  function renderNewsDigest() {
    const wrap = document.getElementById('news-digest');
    if (!wrap) return;
    const d = safe(DATA, 'us_news_digest') || {};
    // US digest (English) — render if present
    let md = "";
    if (d.digest_markdown) {
      md = d.digest_markdown
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/^- (.+)$/gm, '<li>$1</li>');
      md = md.replace(/(<li>.*?<\/li>(\n<li>.*?<\/li>)*)/gs, '<ul>$1</ul>');
      md = md.replace(/\n\n/g, '<br>');
    }
    // Eastmoney Chinese info layer — HK holding news + 7x24 [info breadth]
    const em = safe(DATA, 'em_news') || {};
    let emHtml = "";
    const hn = em.holdings_news || {};
    const hk = Object.keys(hn);
    if (hk.length) {
      emHtml += '<h3>🇭🇰 港股中文消息 · 东财</h3>';
      hk.forEach(tk => {
        const v = hn[tk] || {};
        emHtml += `<div style="margin:3px 0"><strong>${escapeHtml(tk)} ${escapeHtml(v.name || '')}</strong>`;
        (v.items || []).slice(0, 2).forEach(it => {
          emHtml += `<div style="font-size:11px;opacity:.8">· [${escapeHtml(it.date || '')}] ${escapeHtml(it.title || '')}</div>`;
        });
        emHtml += '</div>';
      });
    }
    if (!md && !emHtml) {
      wrap.innerHTML = '<div class="empty-state">No digest yet.</div>';
      return;
    }
    const meta = d.generated_at ? new Date(d.generated_at).toLocaleString('zh-CN', {hour12: false}) : '—';
    wrap.innerHTML = `<div class="digest-meta">generated: ${meta}</div>${md}${emHtml}`;
  }

  function renderMacro() {
    const wrap = document.getElementById('macro-row');
    if (!wrap) return;
    const m = safe(DATA, 'macro') || {};
    const s = safe(DATA, 'sentiment') || {};

    // Regime badge — same risk_on/neutral/risk_off the brief acts on.
    const rgEl = document.getElementById('regime-badge');
    if (rgEl) {
      const rg = safe(DATA, 'regime');
      if (rg && rg.label) {
        const guard = rg.label === 'risk_on'  ? '默认 HOLD · 主动 call 封顶 ≤0.55'
                    : rg.label === 'risk_off' ? '防御优先 · 优先减杠杆'
                    : '按 frame 常规判断';
        rgEl.className = 'regime-badge ' + rg.label;
        rgEl.style.display = 'flex';
        rgEl.innerHTML = `<span class="rg-dot"></span>`
          + `<span class="rg-label">${escapeHtml(rg.label.replace('_',' '))}</span>`
          + `<span class="rg-reasons">${escapeHtml((rg.reasons || []).join(' · '))} → ${escapeHtml(guard)}</span>`;
      } else {
        rgEl.style.display = 'none';
      }
    }
    const cells = [];
    const fmt = (v, suffix='') => v == null || isNaN(v) ? DASH : (Number(v).toFixed(2) + suffix);
    // Trend tag: 'up'/'down'/'' so .sub can be color-coded
    const trend = (chg) => chg == null ? '' : (chg > 0 ? 'up' : (chg < 0 ? 'down' : ''));

    // Volatility / rates / dollar (existing)
    if (m.vix?.price != null) cells.push({lbl: 'VIX', val: fmt(m.vix.price), sub: fmtPct(m.vix.change_pct), cls: trend(m.vix.change_pct)});
    if (m.treasury_10y?.yield_pct != null) cells.push({lbl: '10Y Yield', val: fmt(m.treasury_10y.yield_pct, '%'), sub: ''});
    if (m.dxy?.price != null) cells.push({lbl: 'DXY', val: fmt(m.dxy.price), sub: fmtPct(m.dxy.change_pct), cls: trend(m.dxy.change_pct)});
    if (m.fear_greed?.score != null) cells.push({lbl: 'F&G', val: fmt(m.fear_greed.score), sub: m.fear_greed.rating || ''});

    // [A] Market indices — newly added so dashboard aligns with brief ▎大盘速读
    const idxFmt = (v) => v == null ? DASH : (v >= 1000 ? Math.round(v).toLocaleString() : fmt(v));
    if (m.spx?.price != null)    cells.push({lbl: 'SPX',    val: idxFmt(m.spx.price),    sub: fmtPct(m.spx.change_pct),    cls: trend(m.spx.change_pct)});
    if (m.nasdaq?.price != null) cells.push({lbl: 'NDX',    val: idxFmt(m.nasdaq.price), sub: fmtPct(m.nasdaq.change_pct), cls: trend(m.nasdaq.change_pct)});
    if (m.hsi?.price != null)    cells.push({lbl: 'HSI',    val: idxFmt(m.hsi.price),    sub: fmtPct(m.hsi.change_pct),    cls: trend(m.hsi.change_pct)});
    if (m.hstech?.price != null) cells.push({lbl: 'HSTECH', val: idxFmt(m.hstech.price), sub: fmtPct(m.hstech.change_pct), cls: trend(m.hstech.change_pct)});

    // Sentiment aggregate (kept as quick-glance counts; per-ticker drill below)
    if (s.tickers && Array.isArray(s.tickers)) {
      const totalReddit = s.tickers.reduce((sum, t) => sum + (t.reddit_mentions_7d || 0), 0);
      const totalNews = s.tickers.reduce((sum, t) => sum + ((t.google_news_en || []).length + (t.google_news_zh || []).length), 0);
      if (totalReddit > 0) cells.push({lbl: 'Reddit 7d', val: totalReddit, sub: 'mentions'});
      if (totalNews > 0) cells.push({lbl: 'News 7d', val: totalNews, sub: 'articles'});
    }

    if (m.fed_press?.length) {
      cells.push({lbl: 'Fed (7d)', val: m.fed_press.length, sub: 'press releases'});
    }

    if (!cells.length) {
      wrap.innerHTML = '<div class="empty-state">Macro feed stale (Yahoo rate-limited). Awaiting next macro-scan cron.</div>';
    } else {
      wrap.innerHTML = cells.map(c =>
        `<div class="macro-cell ${c.cls || ''}"><div class="lbl">${c.lbl}</div><div class="val">${c.val}</div>${c.sub ? `<div class="sub">${c.sub}</div>` : ''}</div>`
      ).join('');
    }

    // [D] Fed press top 3 — list instead of single-latest
    if (m.fed_press?.length) {
      const fedDiv = document.createElement('div');
      fedDiv.className = 'fed-latest';
      fedDiv.style.cssText = 'margin-top:8px;padding: var(--space-2) var(--space-3);background:var(--card-2);border-radius:var(--radius-sm);font-size:11.5px;border-left:3px solid var(--accent-2);';
      const rows = m.fed_press.slice(0, 3).map(p =>
        `<div style="margin:3px 0;">
          <span style="color:var(--text-dim);font-size:10px;margin-right:8px;">${p.date}</span>
          <a href="${p.url}" target="_blank" rel="noopener" style="color:var(--text);text-decoration:none;">${(p.title || '').substring(0, 130)}</a>
        </div>`).join('');
      fedDiv.innerHTML = `<div style="color:var(--text-dim);font-size:10px;margin-bottom:2px;">Fed press · past 7d</div>${rows}`;
      wrap.appendChild(fedDiv);
    }

    // [B] Per-ticker drill + [C] risk banner — render alongside macro
    renderSentimentDrill(s);
    renderRiskBanner(s);
  }

  // [B] Per-ticker sentiment drill — sorted by signal strength, collapsed by default
  function renderSentimentDrill(s) {
    const wrap = document.getElementById('sentiment-drill');
    if (!wrap) return;
    const tickers = (s && Array.isArray(s.tickers)) ? s.tickers : [];
    // Keep only tickers with any signal
    const withSignal = tickers
      .map(t => ({
        ticker: t.ticker,
        name: t.name || '',
        region: t.region || '',
        reddit: t.reddit_mentions_7d || 0,
        reddit_posts: t.reddit_posts || [],
        news: [...(t.google_news_en || []), ...(t.google_news_zh || [])],
      }))
      .filter(t => t.reddit > 0 || t.news.length > 0)
      .sort((a, b) => (b.reddit - a.reddit) || (b.news.length - a.news.length));
    if (!withSignal.length) { wrap.innerHTML = ''; return; }
    const regionTag = (r) => r === 'us_stocks' ? 'US' : (r === 'hk_stocks' ? 'HK' : '');
    wrap.innerHTML = withSignal.map(t => {
      const newsLis = t.news.slice(0, 3).map(n =>
        `<li>${(n.title || '').replace(/</g, '&lt;')}</li>`).join('');
      const redditLis = t.reddit_posts.slice(0, 3).map(p =>
        `<li>${(p.title || '').replace(/</g, '&lt;')} <span style="color:var(--text-dim);font-size:10px;">· ${p.score || 0}↑ ${p.num_comments || 0}💬</span></li>`).join('');
      return `<details class="sd-row">
        <summary>
          <span class="sd-tk">${t.ticker}</span>
          <span class="sd-reg">${regionTag(t.region)}</span>
          <span class="sd-counts"><strong>${t.reddit}</strong>R · <strong>${t.news.length}</strong>N</span>
        </summary>
        <div class="sd-body">
          ${newsLis ? `<div class="sd-grp">News</div><ul>${newsLis}</ul>` :
                      `<div class="sd-empty">no news headlines</div>`}
          ${redditLis ? `<div class="sd-grp">Reddit</div><ul>${redditLis}</ul>` : ''}
        </div>
      </details>`;
    }).join('');
  }

  // [C] Risk keyword banner — scans sentiment headlines for negative keywords
  function renderRiskBanner(s) {
    const wrap = document.getElementById('risk-banner');
    if (!wrap) return;
    const tickers = (s && Array.isArray(s.tickers)) ? s.tickers : [];
    // Match whole-word so "Mission" doesn't trip "miss". \b on letters; lowercase compare.
    const KWS = ['miss', 'sec', 'probe', 'fraud', 'lawsuit', 'downgrade',
                 'halt', 'recall', 'short report', 'subpoena', 'restate'];
    const hits = [];
    for (const t of tickers) {
      const corpus = [
        ...(t.google_news_en || []).map(n => n.title || ''),
        ...(t.google_news_zh || []).map(n => n.title || ''),
        ...(t.reddit_posts   || []).map(p => p.title || ''),
      ].join(' \n ').toLowerCase();
      const matched = [];
      for (const kw of KWS) {
        const re = kw.includes(' ')
          ? new RegExp(kw.replace(/ /g, '\\s+'), 'i')
          : new RegExp('\\b' + kw + '\\b', 'i');
        if (re.test(corpus)) matched.push(kw);
      }
      if (matched.length) hits.push({ticker: t.ticker, kws: matched});
    }
    if (!hits.length) { wrap.style.display = 'none'; wrap.innerHTML = ''; return; }
    wrap.style.display = '';
    wrap.innerHTML =
      `<div class="rb-hdr">⚠ Risk keywords (${hits.length})</div>` +
      hits.map(h =>
        `<div class="rb-row"><span class="rb-tk">${h.ticker}</span>` +
        h.kws.map(k => `<span class="rb-kw">${k}</span>`).join('') +
        `</div>`).join('');
  }

  function renderCalibBadge() {
    const cal = safe(DATA, "decision_metrics") || {};
    const brierEl = document.getElementById("brier-val");
    const metaEl = document.getElementById("brier-meta");
    const tierEl = document.getElementById("brier-tier");
    // Average benefit of the active calls. NOT an alpha-vs-hold comparison: the
    // passive episodes are a different sample (other tickers, dates, exposure), so
    // differencing the two hit rates measures nothing.
    const alphaEl = document.getElementById("alpha-line");
    if (alphaEl) {
      const vb = cal.active || {};
      if (vb.avg_benefit_pct != null) {
        const a = vb.avg_benefit_pct;
        const col = a > 0 ? "var(--green)" : (a < 0 ? "var(--red)" : "var(--gray)");
        const ci = vb.cluster_ci95 ? ` · cluster CI [${vb.cluster_ci95[0].toFixed(2)}, ${vb.cluster_ci95[1].toFixed(2)}]` : "";
        alphaEl.innerHTML = `🎯 主动决策 episode · <b style="color:${col}">${a > 0 ? "+" : ""}${a.toFixed(2)}%</b>`
          + `<span style="color:var(--text-faint)">${ci} · n=${vb.n_episodes || 0}</span>`;
      } else {
        alphaEl.textContent = "🎯 LLM vs 全持有基线 · 数据不足";
      }
    }
    if (cal.brier == null) {
      brierEl.textContent = DASH;
      metaEl.textContent = `n=${cal.settled_episodes || 0} · need settled episodes`;
      tierEl.textContent = "n/a";
      tierEl.className = "tier";
      return;
    }
    const b = cal.brier;
    // Grade against the leave-one-out constant forecast, not the in-sample b(1-b):
    // the latter is fitted on these same rows and would be too easy a bar. Absolute
    // tiers ("Fair" at 0.24) rated the score against nothing at all.
    const bl = cal.brier_baseline_loo != null ? cal.brier_baseline_loo : cal.brier_baseline_constant;
    const br = cal.base_rate;
    const mc = cal.mean_confidence;
    brierEl.textContent = b.toFixed(3);
    metaEl.textContent = (bl != null && br != null)
      ? `准度 ${b.toFixed(3)} · 闭眼总报 ${Math.round(br * 100)}% = ${bl.toFixed(3)} · n=${cal.settled_episodes ?? DASH}`
      : `Brier · episodes n=${cal.settled_episodes ?? DASH}`;
    let tier, cls;
    // "没信息量" would overclaim: the score still shows a little resolution, it is
    // the calibration that is broken. Name the actual defect.
    if (bl == null) { tier = "n/a"; cls = ""; }
    else if (b >= bl) {
      tier = (mc != null && br != null && mc > br + 0.05) ? "过度自信" : "不如基准";
      cls = "poor";
    }
    else if (bl - b < 0.02) { tier = "勉强打平"; cls = "fair"; }
    else if (bl - b < 0.05) { tier = "略有信息量"; cls = "good"; }
    else { tier = "有信息量"; cls = "excellent"; }
    tierEl.textContent = tier;
    tierEl.className = "tier " + cls;
  }

  // =========================================================
  // Drill
  // =========================================================
  function flatHoldings() {
    const us = (safe(DATA, "holdings", "us") || []).map(h => ({ ...h, region: "us" }));
    const hk = (safe(DATA, "holdings", "hk") || []).map(h => ({ ...h, region: "hk" }));
    return [...us, ...hk].filter(h => h.is_active !== false && (h.shares ?? 0) > 0);
  }

  // 持仓决策矩阵优先消费 harness 编译的 versioned projection。旧 dashboard
  // join 仅作跨版本部署期间的 fallback；Pages 不再是投资规则的 owner。
  function renderDecisionMatrix() {
    const card = document.getElementById('decision-matrix-card');
    if (!card) return;
    const projection = safe(DATA, "brief_projection") || {};
    const projected = projection.schema_version === 1
      ? (projection.tickers || [])
      : [];
    const H = safe(DATA, "holdings") || {};
    const holds = [...(H.us || []), ...(H.hk || [])].filter(h => h && h.is_active);
    if (!projected.length && !holds.length) { card.style.display = 'none'; return; }
    card.style.display = '';
    const qrows = ((safe(DATA, "quant_signals") || {}).rows) || {};
    // 杠杆 ETF→底层标的映射（量化按标的算，ETF 本身无 quant 行）。
    // 双源：lev_regime.us.names 的 etf/underlying + quant 行 note "X 的标的"。
    const etf2u = {};
    (((safe(DATA, "lev_regime") || {}).us || {}).names || []).forEach(n => {
      if (n.etf && n.underlying) etf2u[n.etf] = n.underlying;
    });
    Object.keys(qrows).forEach(u => {
      const m = (qrows[u].note || '').match(/^(\S+)\s*的标的/);
      if (m) etf2u[m[1]] = u;
    });
    const rg = safe(DATA, "risk_guardrail") || {};
    const action = {};
    (rg.breaches || []).forEach(b => { if (b.ticker && !action[b.ticker]) action[b.ticker] = { txt: '减仓', col: 'var(--warning)', kind: 'trim' }; });
    (rg.hard_stop_watch || []).forEach(s => { if (s.ticker) action[s.ticker] = { txt: '止损', col: 'var(--negative)', kind: 'stop' }; });
    const sign = v => v == null ? '' : `style="color:${v < 0 ? 'var(--negative)' : 'var(--positive)'}"`;
    const num = (v, suf = '') => v == null ? '—' : `${v}${suf}`;
    const rsiCls = r => r == null ? '' : (r >= 70 ? 'style="color:var(--negative)"' : (r <= 30 ? 'style="color:var(--positive)"' : ''));
    // 52w 位置条：0=近一年低位(便宜/绿) 100=近一年高位(追高/红)
    const rangeBar = p => {
      if (p == null) return '<span class="muted">—</span>';
      const pos = Math.max(0, Math.min(100, p));
      const col = p >= 80 ? 'var(--negative)' : (p <= 20 ? 'var(--positive)' : 'var(--neutral)');
      return `<span style="position:relative;width:52px;height:8px;background:rgba(128,128,128,.18);border-radius:4px;display:inline-block;vertical-align:middle">` +
        `<span style="position:absolute;left:${pos}%;top:-2px;width:3px;height:12px;background:${col};border-radius:2px;transform:translateX(-50%)"></span></span>` +
        `<span class="muted" style="font-size:10px;margin-left:5px">${Math.round(p)}</span>`;
    };
    let usedProxy = false;
    // 综合 verdict：状态分级(rank 越小越需关注)。强动作来自硬闸(kcn 已定框架)，
    // 其余仅给技术面状态，不臆造买卖结论(主动信号 edge 弱，见 calibration)。
    const verdict = (q, a) => {
      if (a && a.kind === 'stop') return { rank: 0, label: '止损/换1x', state: 'critical' };
      if (a && a.kind === 'trim') return { rank: 1, label: '减仓', state: 'elevated' };
      if (q.trend_on === true) return { rank: 4, label: '趋势ON', state: 'positive' };
      if (q.rsi14 != null && q.rsi14 <= 30) return { rank: 2, label: '超卖·观望', state: 'elevated' };
      if (q.tag || q.rsi14 != null) return { rank: 3, label: '趋势off·观望', state: 'neutral' };
      return { rank: 5, label: '—', state: 'neutral' };
    };
    const enriched = projected.length
      ? projected.map(row => {
          const q = row.technical || {};
          const proxy = q.is_proxy ? q.source_ticker : '';
          if (proxy) usedProxy = true;
          const riskAction = (row.risk || {}).action;
          const a = riskAction ? {
            txt: riskAction.label,
            col: riskAction.kind === 'stop' ? 'var(--negative)' : 'var(--warning)',
            kind: riskAction.kind,
          } : null;
          const live = holds.find(h => h.ticker === row.ticker) || {};
          return {
            h: {
              ticker: row.ticker,
              // Projection owns analysis; current marks remain live intraday.
              today_change_pct: live.today_change_pct ?? (row.facts || {}).today_change_pct,
              pnl_percent: live.pnl_percent ?? (row.facts || {}).pnl_pct,
            },
            q,
            a,
            proxy,
            v: row.status || verdict(q, a),
          };
        })
      : holds.map(h => {
          const usable = r => r && (!r.status || r.status === 'fresh');
          const direct = usable(qrows[h.ticker]) ? qrows[h.ticker] : null;
          const proxy = !direct && etf2u[h.ticker] && usable(qrows[etf2u[h.ticker]]) ? etf2u[h.ticker] : '';
          if (proxy) usedProxy = true;
          const q = direct || (proxy ? qrows[proxy] : {}) || {};
          const a = action[h.ticker];
          return { h, q, a, proxy, v: verdict(q, a) };
        });
    // 排序：需要动作的优先(rank 升序)，同级浮亏深的在前 → 最该看的在最上面
    enriched.sort((x, y) => (x.v.rank - y.v.rank) || ((x.h.pnl_percent ?? 0) - (y.h.pnl_percent ?? 0)));
    document.getElementById('decision-matrix-tbody').innerHTML = enriched.map(({ h, q, a, proxy, v }) => {
      const mk = proxy ? `<sup style="color:var(--muted,#9ca3af)" title="杠杆ETF · 量化列取底层 ${proxy}">▵</sup>` : '';
      return `<tr>` +
        `<td><strong>${h.ticker}</strong>${mk}</td>` +
        `<td style="font-size:11px"><span class="matrix-status ${v.state}">${v.label}</span></td>` +
        `<td class="num" ${sign(h.today_change_pct)}>${num(h.today_change_pct, '%')}</td>` +
        `<td class="num" ${sign(h.pnl_percent)}>${num(h.pnl_percent, '%')}</td>` +
        `<td>${rangeBar(q.pct_52w_range)}</td>` +
        `<td class="num" ${rsiCls(q.rsi14)}>${num(q.rsi14)}</td>` +
        `<td class="num" ${sign(q.dist_ma200_pct)}>${num(q.dist_ma200_pct, '%')}</td>` +
        `<td style="font-size:10px">${a ? `<span style="color:${a.col};font-weight:600">${a.txt}</span>` : '<span class="muted">—</span>'}</td>` +
        `</tr>`;
    }).join('');
    document.getElementById('decision-matrix-note').textContent =
      '综合：止损/减仓=硬闸规则(必动)，观望/趋势ON=技术状态(非买卖建议)。按需动作优先排序。'
      + '52w位置：绿=近一年低位(便宜)、红=高位(追高警惕)。'
      + (projected.length ? '数据由 harness projection 编译，页面不重算规则。' : '兼容模式：等待 projection。')
      + (usedProxy ? '▵=杠杆ETF量化列取底层标的。' : '');
  }

  function renderHoldings() {
    const tbody = document.getElementById("holdings-tbody");
    const data = flatHoldings();
    document.getElementById("holdings-count").textContent = data.length ? `(${data.length})` : "";
    const { key, dir } = holdingsSort;
    data.sort((a, b) => {
      const av = a[key], bv = b[key];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "string") return dir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      return dir === "asc" ? av - bv : bv - av;
    });
    const fmtShares = (n) => n == null || isNaN(n) ? DASH : Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
    const fmtPrice = (n, ccy) => n == null || isNaN(n) || n === 0 ? DASH : fmtMoney(n, ccy);
    const dualCell = (abs, pct, cls) => `
      <div class="${cls}">${fmtMoney(abs, ccy)}</div>
      <div class="cell-sub ${cls}">${fmtPct(pct)}</div>`;
    tbody.innerHTML = data.map(h => {
      const ccy = h.region === "hk" ? "HKD" : "USD";
      return `
        <tr>
          <td><span class="ticker region-${h.region}">${h.ticker || DASH}</span></td>
          <td class="name-cell">${h.name || ""}</td>
          <td class="num">${fmtShares(h.shares)}</td>
          <td class="num">${fmtPrice(h.cost_basis, ccy)}</td>
          <td class="num">${fmtPrice(h.current_price, ccy)}</td>
          <td class="num">${fmtMoney(h.current_value, ccy)}</td>
          <td class="num spark-cell">${sparklineSVG((safe(DATA, "holdings_history", h.ticker) || []), 56, 18)}</td>
          <td class="num cell-stack">
            <div class="${pnlClass(h.today_change)}">${fmtMoney(h.today_change, ccy)}</div>
            <div class="cell-sub ${pnlClass(h.today_change_pct)}">${fmtPct(h.today_change_pct)}</div>
          </td>
          <td class="num cell-stack">
            <div class="${pnlClass(h.pnl_abs)}">${fmtMoney(h.pnl_abs, ccy)}</div>
            <div class="cell-sub ${pnlClass(h.pnl_percent)}">${fmtPct(h.pnl_percent)}</div>
          </td>
        </tr>
      `;
    }).join("");

    // Wire sort headers
    document.querySelectorAll("#holdings-table thead th").forEach(th => {
      th.onclick = () => {
        const k = th.dataset.sort;
        if (!k) return;
        if (holdingsSort.key === k) {
          holdingsSort.dir = holdingsSort.dir === "asc" ? "desc" : "asc";
        } else {
          holdingsSort = { key: k, dir: "desc" };
        }
        document.querySelectorAll("#holdings-table thead th").forEach(x => {
          const isActive = x.dataset.sort === holdingsSort.key;
          x.classList.toggle("active-sort", isActive);
          const label = x.textContent.replace(/[▲▼]/g, "").trim();
          x.replaceChildren();
          x.append(label);
          if (isActive) {
            const arrow = document.createElement("span");
            arrow.className = "arr";
            arrow.textContent = holdingsSort.dir === "asc" ? "▲" : "▼";
            x.append(" ", arrow);
          }
        });
        renderHoldings();
      };
    });
  }

  function renderShadowPortfolioCard() {
    const empty = document.getElementById("shadow-portfolio-empty");
    const content = document.getElementById("shadow-portfolio-content");
    if (!empty || !content) return;
    const sidecar = safe(DATA, "shadow_portfolio");
    const summary = document.getElementById("shadow-portfolio-summary");
    const coverageNote = document.getElementById("shadow-coverage-note");
    if (sidecar && sidecar.computed === false) {
      if (summary) summary.textContent = "⚠️ 政策模拟本次无法计算";
      empty.textContent = "⚠️ 政策模拟本次无法计算";
      empty.style.display = "";
      content.style.display = "none";
      if (coverageNote) coverageNote.style.display = "none";
      return;
    }
    empty.textContent = "数据不足";
    const signedMoney = (value, currency) => {
      if (value == null || !isFinite(value)) return DASH;
      const sign = value > 0 ? "+" : value < 0 ? "−" : "";
      return sign + fmtMoney(Math.abs(value), currency);
    };
    const curves = (sidecar && sidecar.curves) || {};
    const skippedMarks = Object.values(curves).flatMap(
      book => safe(book, "mark_coverage", "skipped_dates") || []
    );
    if (coverageNote) {
      coverageNote.textContent = skippedMarks.length
        ? `⚠️ ${skippedMarks.length} 个市场交易日缺行情未计价`
        : "";
      coverageNote.style.display = skippedMarks.length ? "" : "none";
    }
    const counts = (sidecar && sidecar.fill_counts) || {};
    const countValue = key => counts[key] != null && Number.isFinite(Number(counts[key]))
      ? Number(counts[key]) : null;
    const realCount = countValue("real_trade");
    const ohlcCount = countValue("ohlc_assumption");
    const closeCount = countValue("canonical_close_fallback");
    const skippedCount = countValue("skipped");
    const assumedCount = ohlcCount == null && closeCount == null
      ? null : (ohlcCount || 0) + (closeCount || 0);
    if (summary) {
      const countText = value => value == null ? DASH : value.toLocaleString("en-US");
      summary.textContent = `⚠模拟·非实盘 · USD差 ${signedMoney(safe(sidecar, "cumulative_diff", "USD"), "USD")}`
        + ` · HKD差 ${signedMoney(safe(sidecar, "cumulative_diff", "HKD"), "HKD")}`
        + ` · real ${countText(realCount)} / assumed ${countText(assumedCount)} / skipped ${countText(skippedCount)}`
        + (skippedMarks.length ? ` · 缺行情 ${skippedMarks.length}` : "");
    }
    const hasData = ["USD", "HKD"].some(
      ccy => Array.isArray(safe(curves, ccy, "curve"))
        && safe(curves, ccy, "curve").some(
          row => row && row.followed_sim != null && row.buy_and_hold != null
            && Number.isFinite(Number(row.followed_sim))
            && Number.isFinite(Number(row.buy_and_hold))
        )
    );
    empty.style.display = hasData ? "none" : "";
    content.style.display = hasData ? "" : "none";
    if (!hasData) return;

    ["USD", "HKD"].forEach(currency => {
      const el = document.getElementById(`shadow-diff-${currency.toLowerCase()}`);
      if (!el) return;
      const value = safe(sidecar, "cumulative_diff", currency);
      el.textContent = signedMoney(value, currency);
      el.className = `val ${pnlClass(value)}`;
    });

    const countMap = {
      "shadow-fill-real": counts.real_trade,
      "shadow-fill-ohlc": counts.ohlc_assumption,
      "shadow-fill-close": counts.canonical_close_fallback,
      "shadow-fill-skipped": counts.skipped,
    };
    Object.entries(countMap).forEach(([id, value]) => {
      const el = document.getElementById(id);
      if (el) el.textContent = Number.isFinite(Number(value)) ? Number(value).toLocaleString("en-US") : "0";
    });
    const filled = ["real_trade", "ohlc_assumption", "canonical_close_fallback"]
      .reduce((sum, key) => sum + (Number(counts[key]) || 0), 0);
    const skipped = Number(counts.skipped) || 0;
    const total = filled + skipped;
    const constraint = document.getElementById("shadow-constraint-note");
    if (constraint) {
      const skippedPct = total ? Math.round(skipped / total * 100) : 0;
      constraint.textContent = total
        ? `受库存、现金或成交价约束：${skipped}/${total} 条腿未成交（${skippedPct}%）${skipped > filled ? "；绝大多数建议受约束未成交。" : "。"}`
        : "暂无可统计的模拟成交腿。";
    }
    const asof = document.getElementById("shadow-asof");
    if (asof) asof.textContent = sidecar.as_of ? ` · 数据 ${sidecar.as_of}` : "";
  }

  function renderRiskMetrics() {
    const r = safe(DATA, "risk") || {};
    const us = r.us || {}, hk = r.hk || {}, combined = r.combined || {}, lev = r.leveraged_exposure || {};
    const setNum = (id, v, fmt = 'num') => {
      const el = document.getElementById(id);
      if (!el) return;
      if (v == null || isNaN(v)) { el.textContent = DASH; el.className = "val neutral"; return; }
      let text;
      if (fmt === 'pct') text = (v * 100).toFixed(1) + '%';
      else if (fmt === 'pct_signed') text = (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
      else text = v.toFixed(2);
      el.textContent = text;
      // Color by sign / threshold
      let cls = "val";
      if (id === 'risk-beta-us' || id === 'risk-beta-hk') cls += v > 3 ? ' neg' : (v > 2 ? ' warn-text' : '');
      else if (id === 'risk-vol') cls += v > 0.5 ? ' neg' : (v > 0.35 ? ' warn-text' : '');
      else if (id === 'risk-sharpe') cls += v < 0 ? ' neg' : (v > 1 ? ' pos' : '');
      else if (id === 'risk-margin') cls += v < -10 ? ' neg' : '';
      el.className = cls;
    };
    setNum('risk-beta-us', us.beta_spx);
    setNum('risk-beta-hk', hk.beta_hsi);
    setNum('risk-vol', combined.vol_30d_annualized, 'pct');
    // Max DD 已移除 — 历史最大回撤集中显示在「历史利润极值 & 回撤恢复」卡(净化本金口径)，
    // 不在此处重复(且 Risk Metrics 是滚动 30d 风险统计，与全历史回撤口径不同)。
    setNum('risk-sharpe', combined.sharpe_30d);
    setNum('risk-margin', lev.margin_at_risk_pct);  // already in pct form

    const alerts = r.alerts || [];
    document.getElementById('risk-alert-count').textContent = alerts.length ? `(${alerts.length})` : '';
    const ICONS = { high_beta: '⚡', high_vol: '🌊', deep_dd: '📉', high_leverage: '⚠️', negative_sharpe: '➖' };
    const html = alerts.map(a =>
      `<div class="risk-alert ${a.severity || 'high'}">
         <span class="icon">${ICONS[a.type] || '⚠️'}</span>
         <div><strong>${a.type}</strong>: ${a.detail || ''}</div>
       </div>`
    ).join('');
    document.getElementById('risk-alerts').innerHTML = html;
  }

  function renderRiskGuardrail() {
    const g = safe(DATA, "risk_guardrail") || {};
    const targets = [
      {
        countEl: document.getElementById("guardrail-count"),
        dirEl: document.getElementById("guardrail-directive"),
        listEl: document.getElementById("guardrail-list"),
        compact: false,
      },
      {
        countEl: document.getElementById("overview-guardrail-count"),
        dirEl: document.getElementById("overview-guardrail-directive"),
        listEl: document.getElementById("overview-guardrail-list"),
        compact: true,
      },
    ].filter(t => t.countEl && t.listEl);
    if (!targets.length) return;
    if (g.computed === false || g.error) {
      targets.forEach(({ countEl, dirEl, listEl }) => {
        countEl.textContent = '⚠️ 算不出';
        countEl.style.color = 'var(--warning)';
        if (dirEl) dirEl.textContent = '风控数据计算失败，本次不作“无触发”判断。';
        listEl.innerHTML = '<div class="risk-alert medium"><span class="icon">⚠️</span>'
          + '<div><strong>风控卡不可用</strong><div class="muted" style="font-size:11px;margin-top:2px">'
          + '等待下次数据刷新重算</div></div></div>';
      });
      return;
    }
    const breaches = g.breaches || [], stops = g.hard_stop_watch || [];
    const n = g.breach_count || 0;
    const ICON = { single_name: '🎯', factor_concentration: '🧬', leveraged_exposure: '⚡', beta: '📈', regime_delever: '🧭' };
    const row = (icon, sev, detail, action) =>
      `<div class="risk-alert ${sev || 'high'}">
         <span class="icon">${icon}</span>
         <div><strong>${detail || ''}</strong>${action ? `<div class="muted" style="font-size:11px;margin-top:2px">→ ${action}</div>` : ''}</div>
       </div>`;
    const rows = [
      ...breaches.map(b => ({ icon: ICON[b.type] || '⚠️', severity: b.severity, detail: b.detail, action: b.action })),
      ...stops.map(s => ({ icon: '🛑', severity: 'high', detail: s.detail, action: s.action })),
    ];
    const compactRows = rows.slice().sort((a, b) =>
      Number(b.severity === "high") - Number(a.severity === "high"));
    targets.forEach(({ countEl, dirEl, listEl, compact }) => {
      countEl.textContent = n ? `${n} 触发` : '✅ 无';
      countEl.style.color = n ? 'var(--negative)' : 'var(--positive)';
      if (dirEl) dirEl.textContent = compact
        ? (g.directive || "")
        : [g.directive, g.reentry_rule].filter(Boolean).join(' ');
      const visibleRows = compact ? compactRows.slice(0, 3) : rows;
      const html = visibleRows.map(r => row(r.icon, r.severity, r.detail, compact ? "" : r.action)).join('');
      listEl.innerHTML = html || '<div class="muted" style="font-size:12px">仓位/单因子/杠杆均在阈值内 ✅</div>';
    });
  }

  function renderBreakevenMath() {
    const bm = safe(DATA, "breakeven_math");
    const card = document.getElementById('breakeven-card');
    if (!card) return;
    const rows = (bm && bm.rows) || [];
    if (!rows.length) { card.style.display = 'none'; return; }
    card.style.display = '';
    const html = rows.map(r => {
      let extra = '';
      if (r.leveraged && r.underlying_vol_pct != null) {
        extra = `<div class="muted" style="font-size:11px;margin-top:2px">标的σ ${r.underlying_vol_pct}% · 横盘 decay ≈${r.chop_drag_pct_per_month}%/月 · ` +
                `半年直线路径标的需 +${r.underlying_need_2x_6m_pct}%` +
                (r.swap_1x ? ` · 换 1x(${r.swap_1x}) 后需 +${r.underlying_need_if_1x_pct}%` : '') + `</div>`;
      }
      return `<div class="risk-alert ${r.leveraged ? 'high' : 'medium'}">
         <span class="icon">${r.leveraged ? '⚡' : '📐'}</span>
         <div><strong>${r.ticker}</strong> 浮亏 ${r.pnl_pct}% → 回本需 +${r.breakeven_need_pct}%${extra}</div>
       </div>`;
    }).join('');
    document.getElementById('breakeven-list').innerHTML = html;
    document.getElementById('breakeven-note').textContent = bm.note || '';
  }

  function renderQuantSignals() {
    const qs = safe(DATA, "quant_signals");
    const card = document.getElementById('quant-card');
    if (!card) return;
    const rows = (qs && qs.rows) || {};
    const names = Object.keys(rows);
    if (!names.length) { card.style.display = 'none'; return; }
    card.style.display = '';
    document.getElementById('quant-asof').textContent = qs.as_of || '';
    const num = (v, suf = '') => v == null ? '—' : `${v}${suf}`;
    const cls = v => v == null ? '' : (v < 0 ? 'style="color:var(--negative)"' : 'style="color:var(--positive)"');
    document.getElementById('quant-tbody').innerHTML = names.map(k => {
      const r = rows[k];
      const state = r.status && r.status !== 'fresh'
        ? `<div style="font-size:10px;color:var(--warning)">⚠ ${r.status} · ${r.row_as_of || r.last_good_as_of || '无日期'}${r.stale_reason ? ` · ${r.stale_reason}` : ''}</div>`
        : '';
      return `<tr><td><strong>${k}</strong>${r.note ? `<div class="muted" style="font-size:10px">${r.note}</div>` : ''}</td>` +
        `<td style="text-align:left;font-size:11px">${r.tag || ''}${state}</td>` +
        `<td class="num">${num(r.rsi14)}</td>` +
        `<td class="num">${num(r.zscore20)}</td>` +
        `<td class="num" ${cls(r.dist_ma200_pct)}>${num(r.dist_ma200_pct, '%')}</td>` +
        `<td class="num" ${cls(r.stop_distance_pct)}>${num(r.stop_distance_pct, '%')}</td>` +
        `<td class="num">${num(r.vol_target_weight)}</td></tr>`;
    }).join('');
    const rev = safe(DATA, "quant_signal_review");
    const edgeEl = document.getElementById('quant-edge');
    if (rev && rev.summary) {
      edgeEl.textContent = `因子 edge 自检（T+1 前瞻收益对账，样本随时间累积）：${rev.summary}`;
    } else {
      edgeEl.textContent = '因子 edge 自检：信号每日留痕中；公开 events/dates/tickers，聚类 CI 完全越过 50% 才允许进入决策。';
    }
  }

  function renderT0Setups() {
    const t0 = safe(DATA, "t0_setups");
    const card = document.getElementById('t0-card');
    if (!card) return;
    const rows = (t0 && t0.rows) || {};
    const names = Object.keys(rows);
    if (!names.length) { card.style.display = 'none'; return; }
    card.style.display = '';
    // 市场休市时这些是上一交易日收盘的牌面
    const closed = t0.market_closed || {};
    const anyClosed = Object.values(closed).some(Boolean);
    document.getElementById('t0-asof').textContent =
      (t0.as_of || '') + (anyClosed ? ' · 收盘牌面' : '');
    const num = (v, suf = '') => v == null ? '—' : `${v}${suf}`;
    const cls = v => v == null ? '' : (v < 0 ? 'style="color:var(--negative)"' : 'style="color:var(--positive)"');
    // 🔴 追高排前面（最该看的牌面）
    const order = { '🔴': 0, '🟡': 1, '⚪': 2 };
    names.sort((a, b) => (order[rows[a].grade] ?? 3) - (order[rows[b].grade] ?? 3));
    document.getElementById('t0-tbody').innerHTML = names.map(k => {
      const r = rows[k];
      const lev = r.leveraged ? `<span class="muted" style="font-size:10px"> ${r.leveraged}</span>` : '';
      const vw = (r.vs_vwap_pct != null)
        ? `<div class="muted" style="font-size:10px">VWAP ${r.vs_vwap_pct > 0 ? '+' : ''}${r.vs_vwap_pct}%</div>` : '';
      return `<tr><td><strong>${k}</strong>${lev}</td>` +
        `<td style="text-align:left;font-size:11px">${r.grade} ${r.grade_label}` +
        `<div class="muted" style="font-size:10px">${r.grade_reason || ''}</div>${vw}</td>` +
        `<td class="num">${num(r.range_pos, '%')}</td>` +
        `<td class="num" ${cls(r.today_change_pct)}>${num(r.today_change_pct, '%')}</td>` +
        `<td class="num" ${cls(r.gap_pct)}>${num(r.gap_pct, '%')}</td>` +
        `<td class="num">${num(r.range_used_atr, '×')}</td></tr>`;
    }).join('');
    // 数据背书：牌面命中率（T+1 对账，n<20 标样本不足）
    const rev = safe(DATA, "t0_setup_review");
    let backing = '';
    if (rev && rev.summary) {
      backing = ` ｜ 📐 牌面背书（${rev.days_logged || 0}日留痕·T+1）：${rev.summary}`;
    }
    document.getElementById('t0-note').textContent =
      (t0.note || '') + ' 区间位=现价在当日高低区间位置（越高越接近追在顶部）；振幅/ATR>1=今日已跑过一个典型日。' + backing;
  }

  function renderLevRegime() {
    const r = safe(DATA, "lev_regime");
    const card = document.getElementById('lev-regime-card');
    if (!card) return;
    if (!r || !r.tier) { card.style.display = 'none'; return; }
    card.style.display = '';
    const TIER = { green: '满杠杆制度', amber: '半杠杆制度', red: '清杠杆制度' };
    const hk = r.hk || r;   // top-level mirrors HK for backward compat
    const badge = document.getElementById('lev-regime-badge');
    badge.className = 'regime-badge ' + hk.tier;
    document.getElementById('lev-regime-label').textContent = TIER[hk.tier] || hk.tier;
    document.getElementById('lev-regime-cap').textContent =
      (hk.lev_cap_mult == null) ? '' : `杠杆ETF腿上限 ×${hk.lev_cap_mult}`;
    document.getElementById('lev-regime-rationale').textContent = r.rationale || hk.label || '';
    // re-entry trigger: % the close must rise to reclaim its 200DMA (unlocks re-leveraging)
    const reclaim = (close, ma) => (close && ma) ? (ma / close - 1) * 100 : null;
    const trigEl = document.getElementById('lev-regime-trigger');
    const hkRe = reclaim(hk.close, hk.ma);
    if (hk.ma == null) { trigEl.innerHTML = ''; }
    else if (hk.trend_on) {
      trigEl.innerHTML = `<span class="neutral">📍 HK 触发线 200线 ${Math.round(hk.ma)} · 已在线上 +${(-hkRe).toFixed(0)}% 缓冲（杠杆解锁中）</span>`;
    } else {
      trigEl.innerHTML = `<span class="warn-text">📍 HK 触发线：恒科站回 200线 <strong>${Math.round(hk.ma)}</strong>（需 +${hkRe.toFixed(0)}%）→ 杠杆腿上限放回 50%</span>`;
    }
    // US per-name rows
    const STATE = { cut: ['red', '⛔ 砍杠杆'], watch: ['warn-text', '👀 观察'], ok: ['neutral', '✅ 趋势ON'], unknown: ['neutral', '—'] };
    const us = r.us || {};
    const usEl = document.getElementById('lev-regime-us');
    const rows = (us.names || []).map(n => {
      const [cls, tag] = STATE[n.state] || STATE.unknown;
      const sev = n.state === 'cut' ? 'high' : (n.state === 'watch' ? 'medium' : 'low');
      const vol = n.vol_annualized != null ? (n.vol_annualized*100).toFixed(0)+'%' : '—';
      const re = reclaim(n.close, n.ma);
      // 短历史名(新上市)用短均线做右侧确认，标签随 ma_window 走，别误写"200线"
      const maLbl = (n.ma_window && n.ma_window < 200) ? `${n.ma_window}日均(右侧)` : '200线';
      const trig = (n.trend_on || re == null) ? '' : ` · <span class="warn-text">站回 ${Math.round(n.ma)}（+${re.toFixed(0)}%）${n.ma_window && n.ma_window < 200 ? '右侧再上2x' : '解锁2x'}</span>`;
      const basisNote = n.regime_basis && n.regime_basis.startsWith('short_ma')
        ? ` · <span class="muted">新上市不足200日线,短均线替代</span>` : '';
      return `<div class="risk-alert ${sev}"><span class="icon">🧭</span>
        <div><strong>${n.etf}=2x ${n.underlying} <span class="${cls}">${tag}</span></strong>
        <div class="muted" style="font-size:11px;margin-top:2px">距${maLbl} ${n.dist_ma_pct ?? '—'}% · 20日波动 ${vol}${n.vol_hot ? ' 🔥' : ''}${trig}${basisNote}</div></div></div>`;
    }).join('');
    usEl.innerHTML = rows || '<div class="muted" style="font-size:12px">无持仓 2x 单股 ETF</div>';
    document.getElementById('lev-regime-asof').textContent =
      `HSTECH ${r.as_of || ''} · 200日线 ${hk.ma ?? '?'} · HK波动 ${hk.vol_annualized != null ? (hk.vol_annualized*100).toFixed(0)+'%' : '?'} · US砍线 ${us.vol_hot_cap != null ? (us.vol_hot_cap*100).toFixed(0)+'%' : '?'}`;
  }

  function renderReentryRadar() {
    const r = safe(DATA, "reentry_radar");
    const card = document.getElementById('reentry-card');
    if (!card) return;
    if (!r || !(r.watches || []).length) { card.style.display = 'none'; return; }
    card.style.display = '';
    const num = (v, d = 0) => (v == null ? DASH : Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }));
    // 弹药(live 现金,不硬编码)
    const p = r.powder || {};
    const bits = [];
    if (p.us_cash_usd != null) bits.push(`US $${num(p.us_cash_usd, 0)}`);
    if (p.hk_cash_hkd != null) bits.push(`HK $${num(p.hk_cash_hkd, 0)}`);
    document.getElementById('reentry-powder').innerHTML =
      `<div style="padding:8px 12px;border-radius:6px;background:color-mix(in srgb,var(--accent) 8%,transparent);border:1px solid color-mix(in srgb,var(--accent) 25%,transparent)">
         <span class="muted" style="font-size:10px;text-transform:none;letter-spacing:0">待布局弹药</span>
         <div style="font-size:15px;font-weight:800;margin-top:2px">${bits.join('  ·  ') || DASH}</div>
         <div class="muted" style="font-size:10px;text-transform:none;letter-spacing:0;margin-top:2px">${r.triggered_count}/${r.total} 已触发 · 触发=收盘站回均线,右侧再布局</div>
       </div>`;
    // 每个受监控标的一行
    const rows = r.watches.map(w => {
      const on = w.trend_on;
      const dist = w.dist_ma_pct;
      const need = (w.close && w.ma && !on) ? (w.ma / w.close - 1) * 100 : null;
      const color = on ? 'var(--positive)' : (dist != null && dist > -3 ? 'var(--warning)' : 'var(--negative)');
      const mw = (w.ma_window && w.ma_window >= 200) ? '200DMA' : ((w.ma_window || '?') + '日线');
      const badge = on
        ? `<span style="color:var(--positive);font-weight:700">已站回·可布局</span>`
        : `<span style="color:${color}">还需 +${need != null ? need.toFixed(1) : '?'}% 站回${mw}</span>`;
      const prox = dist == null ? 0 : Math.max(0, Math.min(100, (1 + dist / 20) * 100));
      const mkt = w.market === 'HK' ? '🇭🇰' : '🇺🇸';
      const nameLine = w.etf ? `${w.name} <span class="muted" style="font-size:10px">(${w.etf} 2x)</span>` : w.name;
      return `
        <div style="padding:8px 0;border-top:1px solid var(--border,#2a2a2a)">
          <div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">
            <span style="font-weight:700;font-size:13px">${mkt} ${nameLine}</span>
            <span style="font-size:12px">${badge}</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px;margin-top:4px">
            <div style="flex:1;height:5px;border-radius:3px;background:var(--border,#2a2a2a);position:relative;overflow:hidden">
              <div style="position:absolute;left:0;top:0;bottom:0;width:${prox.toFixed(0)}%;background:${color};opacity:0.55"></div>
            </div>
            <span style="font-size:11px;color:${color};min-width:52px;text-align:right">${dist != null ? (dist > 0 ? '+' : '') + dist.toFixed(1) + '%' : DASH}</span>
          </div>
          <div class="muted" style="font-size:10px;text-transform:none;letter-spacing:0;margin-top:2px">
            现价 ${num(w.close, 2)} · ${mw} ${num(w.ma, 2)}${w.state ? ' · ' + w.state : ''}
          </div>
          ${w.note ? `<div class="muted" style="font-size:9px;text-transform:none;letter-spacing:0;margin-top:2px;opacity:0.75">${w.note}</div>` : ''}
        </div>`;
    }).join('');
    document.getElementById('reentry-list').innerHTML = rows;
    document.getElementById('reentry-asof').textContent =
      (r.as_of ? `数据 ${r.as_of} · ` : '') + '距均线越接近 0 越该盯 · 条件复用 lev_regime 右侧确认';
  }

  function renderGoldDca() {
    const g = safe(DATA, "gold_dca");
    const card = document.getElementById('gold-dca-card');
    if (!card) return;
    card.classList.remove("is-pending");
    if (!g || g.nav == null || g.principal_invested == null) { card.style.display = 'none'; return; }
    card.style.display = '';
    const num = (v, d = 0) => (v == null ? DASH : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d }));
    const cur = g.currency || 'CNY';
    const loss = (g.pnl_abs || 0) < 0;
    const pnlColor = loss ? 'var(--negative)' : 'var(--positive)';
    const sign = (g.pnl_percent || 0) >= 0 ? '+' : '';

    document.getElementById('gold-sub').textContent = `${g.fund_code} · ${g.fund_name}`;

    // hero: 现值 + 盈亏
    document.getElementById('gold-hero').innerHTML =
      `<div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin:2px 0 12px">
         <span style="font-size:26px;font-weight:800">¥${num(g.current_value)}</span>
         <span style="font-size:17px;font-weight:700;color:${pnlColor}">${sign}${num(g.pnl_percent, 2)}%</span>
         <span style="font-size:13px;color:${pnlColor}">${(g.pnl_abs >= 0 ? '+' : '')}¥${num(g.pnl_abs)}</span>
       </div>`;

    // stats grid
    const navChg = g.nav_change_pct;
    const navChgStr = navChg == null ? '' :
      ` <span style="color:${navChg >= 0 ? 'var(--positive)' : 'var(--negative)'};font-size:11px">${navChg >= 0 ? '+' : ''}${navChg.toFixed(2)}%</span>`;
    const cell = (label, val) => `<div style="flex:1 1 30%;min-width:90px;margin:5px 0">
        <div class="muted" style="font-size:10px;text-transform:none;letter-spacing:0">${label}</div>
        <div style="font-size:15px;font-weight:700;margin-top:1px">${val}</div></div>`;
    document.getElementById('gold-stats').innerHTML =
      `<div style="display:flex;flex-wrap:wrap;gap:2px 8px;padding:8px 0;border-top:1px solid var(--border,#2a2a2a)">
        ${cell('累计投入', '¥' + num(g.principal_effective != null ? g.principal_effective : g.principal_invested))}
        ${cell('平均成本', num(g.avg_cost, 4))}
        ${cell('当前净值', num(g.nav, 4) + navChgStr)}
        ${cell('回本需涨', `<span style="color:${loss ? 'var(--warning)' : 'var(--positive)'}">${(g.breakeven_upside_pct >= 0 ? '+' : '') + num(g.breakeven_upside_pct, 1)}%</span>`)}
        ${cell('已投', `${g.days_invested ?? DASH} 交易日`)}
        ${cell('约定投', `${g.installments_est ?? DASH} 笔 ×¥${num(g.daily_amount)}`)}
      </div>`;

    // 国内真基准：000217 跟随上金所国内现货金，这是用户判断回本的主口径。
    const dg = g.domestic_gold;
    const goldDomestic = document.getElementById('gold-domestic');
    if (goldDomestic) {
      if (!dg || dg.price_cny_g == null) {
        goldDomestic.innerHTML =
          `<div role="status" style="margin:12px 0 4px;padding:10px 12px;border-radius:6px;border:1px solid color-mix(in srgb,var(--warning) 25%,transparent);color:var(--warning);font-size:11px">
             上金所 Au99.99 暂无有效行情
           </div>`;
      } else {
        const dchg = dg.change_pct;
        const dcolor = dchg == null ? 'var(--neutral)' : (dchg >= 0 ? 'var(--positive)' : 'var(--negative)');
        const retained = dg.quote_status === 'retained';
        goldDomestic.innerHTML =
          `<div style="margin:12px 0 4px;padding:12px;border-radius:6px;background:color-mix(in srgb,var(--positive) 6%,transparent);border:1px solid color-mix(in srgb,var(--positive) 24%,transparent)">
             <div class="muted" style="font-size:10px;text-transform:none;letter-spacing:0">国内基准 · 上金所 Au99.99</div>
             <div style="display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:end;gap:10px;margin-top:7px">
               <div><div class="muted" style="font-size:10px">当前金价</div><div style="font-size:21px;font-weight:800;white-space:nowrap">¥${num(dg.price_cny_g, 2)}<span style="font-size:11px;color:var(--muted,#999)">/克</span></div></div>
               <div class="muted" aria-hidden="true" style="padding-bottom:4px">→</div>
               <div><div class="muted" style="font-size:10px">我的回本价</div><div style="font-size:21px;font-weight:800;color:var(--warning);white-space:nowrap">¥${num(dg.breakeven_cny_g, 2)}<span style="font-size:11px;color:var(--muted,#999)">/克</span></div></div>
             </div>
             <div class="muted" style="font-size:11px;margin-top:7px;text-transform:none;letter-spacing:0">
               距回本 <b style="color:var(--warning)">+${num(dg.breakeven_upside_pct, 2)}%</b>
               ${dchg == null ? '' : ` · 当日 <b style="color:${dcolor}">${dchg >= 0 ? '+' : ''}${num(dchg, 2)}%</b>`}
               ${dg.low_cny_g != null && dg.high_cny_g != null ? ` · 日内 ¥${num(dg.low_cny_g, 0)}~${num(dg.high_cny_g, 0)}` : ''}
             </div>
             <div class="muted" style="font-size:10px;margin-top:4px;text-transform:none;letter-spacing:0">
               ${dg.date || ''} 收盘 · 上金所${retained ? ' · ⚠️ 本次抓取失败，沿用上次有效值' : ''}
             </div>
           </div>`;
      }
    }

    // 伦敦金类比口径：折算成克/盎司 + 国际口径现值 + 伦敦金vs你基金归一趋势线
    // （kcn 日常看伦敦金现货趋势/新闻，这块把人民币基金翻译成他熟悉的口径）
    const ld = g.london;
    const goldLondon = document.getElementById('gold-london');
    if (goldLondon) {
      if (!ld || ld.xau_usd == null) { goldLondon.innerHTML = ''; }
      else {
        const xchg = ld.xau_change_pct;
        const xcolor = (xchg == null ? 'var(--neutral)' : (xchg >= 0 ? 'var(--positive)' : 'var(--negative)'));
        const xchgStr = xchg == null ? '' : ` · 当日 <span style="color:${xcolor};font-size:11px">${xchg >= 0 ? '+' : ''}${Number(xchg).toFixed(2)}%</span>`;
        const fundBeXau = ld.fund_breakeven_usd_oz != null
          ? ld.fund_breakeven_usd_oz
          : (g.nav ? ld.xau_usd * g.avg_cost / g.nav : null);
        const fundBePct = ld.fund_breakeven_upside_pct != null
          ? ld.fund_breakeven_upside_pct : g.breakeven_upside_pct;
        // 伦敦金保留为国际辅助口径，显式区分现价与真基金回本映射。
        let html =
          `<div style="margin:12px 0 4px;padding:8px 12px;border-radius:6px;background:color-mix(in srgb,var(--warning) 7%,transparent);border:1px solid color-mix(in srgb,var(--warning) 25%,transparent)">
             <div class="muted" style="font-size:10px;text-transform:none;letter-spacing:0">国际辅助 · 伦敦金 XAU/USD</div>
             <div style="display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:end;gap:10px;margin-top:7px">
               <div><div class="muted" style="font-size:10px">当前金价</div><div style="font-size:19px;font-weight:800;white-space:nowrap">$${num(ld.xau_usd, 2)}<span style="font-size:11px;color:var(--muted,#999)">/oz</span></div></div>
               <div class="muted" aria-hidden="true" style="padding-bottom:4px">→</div>
               <div><div class="muted" style="font-size:10px">按当前汇率回本</div><div style="font-size:19px;font-weight:800;color:var(--warning);white-space:nowrap">$${num(fundBeXau, 2)}<span style="font-size:11px;color:var(--muted,#999)">/oz</span></div></div>
             </div>
             <div class="muted" style="font-size:11px;margin-top:5px;text-transform:none;letter-spacing:0">
               距回本 <b style="color:var(--warning)">+${num(fundBePct, 2)}%</b>${xchgStr}
               ${ld.xau_high != null && ld.xau_low != null ? ` · 日内 ${num(ld.xau_low, 0)}~${num(ld.xau_high, 0)}` : ''}
               · USDCNY ${num(ld.usdcny, 4)} · 假设汇率/内外盘价差不变
             </div>`;
        const histSource = ld.hist_source || {};
        const histNames = {
          sina_global_futures_xau: '新浪 XAU 现货',
          eastmoney_gc00y_fallback: '东财 GC00Y 兜底',
          unavailable: '历史抓取失败',
          not_attempted: '历史未抓取',
        };
        html += `<div class="muted" style="font-size:10px;margin-top:4px;text-transform:none;letter-spacing:0">
          历史源 ${escapeHtml(histNames[histSource.name] || histSource.name || '未知')} · ${num(histSource.points || 0)} 点
        </div>`;
        if (ld.hist_advisory) {
          html += `<div role="status" style="font-size:10px;color:var(--warning);margin-top:4px;text-transform:none;letter-spacing:0">
            ℹ️ ${escapeHtml(ld.hist_advisory)}
          </div>`;
        }
        // 反事实 DCA 只是模拟对照，默认折叠，不再叫「我的平均成本」。
        const de = ld.dca_equiv;
        if (de && de.avg_cost_usd_oz != null) {
          const beColor = de.breakeven_upside_pct > 0 ? 'var(--negative)' : 'var(--positive)';
          const dColor = de.pnl_pct >= 0 ? 'var(--positive)' : 'var(--negative)';
          html +=
            `<details style="margin-top:8px;padding-top:8px;border-top:1px dashed color-mix(in srgb,var(--warning) 28%,transparent)">
               <summary class="muted" style="font-size:10px;text-transform:none;letter-spacing:0;cursor:pointer">模拟对照 · 若每个基金交易日直接买伦敦金</summary>
               <div style="margin-top:6px">
               <div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-top:2px">
                 <span style="font-size:17px;font-weight:800">$${num(de.avg_cost_usd_oz, 2)}<span style="font-size:11px;font-weight:600;color:var(--muted,#999)">/oz</span></span>
                 <span style="font-size:12px;font-weight:700;color:var(--muted,#999)">¥${num(de.avg_cost_cny_g, 2)}/克</span>
               </div>
               <div class="muted" style="font-size:11px;margin-top:3px;text-transform:none;letter-spacing:0">
                 现货 <b style="color:var(--text,#eee)">$${num(de.spot_usd_oz, 2)}</b>/oz · 回本需涨 <b style="color:${beColor}">${de.breakeven_upside_pct >= 0 ? '+' : ''}${num(de.breakeven_upside_pct, 2)}%</b>
                 ${de.current_value_cny != null ? `· 对应现值 <b style="color:${dColor}">¥${num(de.current_value_cny)}</b> (${de.pnl_pct >= 0 ? '+' : ''}${num(de.pnl_pct, 2)}%)` : ''}
               </div>
             </div>`;
          // 摊薄轨迹：继续同额定投伦敦金 → 均成本 $/oz 往下移、回本门槛下降
          const lproj = (de.projection || []).filter(p => p && p.avg_cost_usd_oz != null);
          if (lproj.length) {
            const MON = { 20: '+1月', 40: '+2月', 60: '+3月', 120: '+半年', 250: '+1年' };
            const lrows = lproj.map(p =>
              `<tr><td style="padding:4px 8px">${MON[p.days] || ('+' + p.days + '日')}</td>
                <td style="padding:4px 8px;text-align:right">$${num(p.avg_cost_usd_oz, 0)}</td>
                <td style="padding:4px 8px;text-align:right;color:var(--positive)">+${num(p.breakeven_upside_pct, 1)}%</td></tr>`).join('');
            html +=
              `<div class="muted" style="font-size:10px;margin:8px 0 2px;text-transform:none;letter-spacing:0">若金价/汇率不动、继续每日定投 → 持金成本 $/oz 下移</div>
               <table style="width:100%;font-size:12px;border-collapse:collapse">
                 <tr class="muted" style="font-size:10px"><th scope="col" style="padding:4px 8px;text-align:left;font-weight:inherit">继续</th><th scope="col" style="padding:4px 8px;text-align:right;font-weight:inherit">均成本/oz</th><th scope="col" style="padding:4px 8px;text-align:right;font-weight:inherit">回本只需涨</th></tr>
               ${lrows}</table>`;
          }
          html += `</div></details>`;
        }
        // 归一对比线：起投=100，伦敦金(USD) vs 你的基金(CNY)
        const cs = (ld.compare_series || []).filter(r => Array.isArray(r) && r[1] != null && r[2] != null);
        if (cs.length >= 2) {
          const W = 300, H = 56, P = 4;
          const all = cs.flatMap(r => [r[1], r[2]]);
          const lo = Math.min(...all), hi = Math.max(...all), rng = (hi - lo) || 1;
          const x = i => P + i * (W - 2 * P) / (cs.length - 1);
          const y = v => P + (H - 2 * P) * (1 - (v - lo) / rng);
          const lineF = cs.map((r, i) => `${x(i).toFixed(1)},${y(r[1]).toFixed(1)}`).join(' ');
          const lineL = cs.map((r, i) => `${x(i).toFixed(1)},${y(r[2]).toFixed(1)}`).join(' ');
          const fLast = cs[cs.length - 1][1], lLast = cs[cs.length - 1][2];
          const fColor = fLast >= 100 ? 'var(--positive)' : 'var(--negative)';
          html +=
            `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="none" style="margin-top:8px">
               <line x1="0" y1="${y(100).toFixed(1)}" x2="${W}" y2="${y(100).toFixed(1)}" stroke="var(--border,#3a3a3a)" stroke-width="0.8" stroke-dasharray="2 2"/>
               <polyline points="${lineL}" fill="none" stroke="var(--warning)" stroke-width="1.6"/>
               <polyline points="${lineF}" fill="none" stroke="${fColor}" stroke-width="1.6" stroke-dasharray="4 2"/>
             </svg>
             <div class="muted" style="font-size:10px;display:flex;justify-content:space-between;text-transform:none;letter-spacing:0;margin-top:1px">
               <span style="color:var(--warning)">伦敦金 ${lLast >= 100 ? '+' : ''}${num(lLast - 100, 1)}%</span>
               <span style="color:${fColor}">你的基金 ${fLast >= 100 ? '+' : ''}${num(fLast - 100, 1)}%</span>
               <span>起投=100 · 差因:汇率+费率</span>
             </div>`;
        }
        html += `</div>`;
        goldLondon.innerHTML = html;
      }
    }

    // sparkline (净值走势 + 起投点 + 区间高低)
    const hist = (g.nav_history || []).filter(p => Array.isArray(p) && p[1] != null);
    const sp = document.getElementById('gold-spark');
    if (hist.length >= 2) {
      const W = 300, H = 50, P = 4;
      const ys = hist.map(p => p[1]);
      const lo = Math.min(...ys), hi = Math.max(...ys), rng = (hi - lo) || 1;
      const x = i => P + i * (W - 2 * P) / (hist.length - 1);
      const y = v => P + (H - 2 * P) * (1 - (v - lo) / rng);
      const pts = hist.map((p, i) => `${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
      // 起投点位置
      let startIdx = hist.findIndex(p => p[0] >= (g.start_date || ''));
      if (startIdx < 0) startIdx = 0;
      const avg = g.avg_cost;
      const avgY = (avg >= lo && avg <= hi) ? y(avg) : null;
      const lastV = hist[hist.length - 1][1];
      sp.innerHTML =
        `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="none" style="margin-top:4px">
          ${avgY != null ? `<line x1="0" y1="${avgY.toFixed(1)}" x2="${W}" y2="${avgY.toFixed(1)}" stroke="var(--warning)" stroke-width="1" stroke-dasharray="3 2" opacity="0.7"/>` : ''}
          <polyline points="${pts}" fill="none" stroke="var(--warning)" stroke-width="1.6"/>
          <circle cx="${x(startIdx).toFixed(1)}" cy="${y(hist[startIdx][1]).toFixed(1)}" r="2.6" fill="#60a5fa"/>
          <circle cx="${x(hist.length - 1).toFixed(1)}" cy="${y(lastV).toFixed(1)}" r="2.6" fill="${pnlColor}"/>
        </svg>
        <div class="muted" style="font-size:10px;display:flex;justify-content:space-between;text-transform:none;letter-spacing:0">
          <span style="color:#60a5fa">${hist[startIdx][0]} 起投 ${num(hist[startIdx][1], 3)}</span>
          <span style="color:var(--warning)">成本线 ${num(avg, 3)}</span>
          <span>区间 ${num(lo, 3)}~${num(hi, 3)}</span>
        </div>`;
    } else { sp.innerHTML = ''; }

    // 定投摊薄预测 (假设净值不动, 继续投 → 回本门槛下移)
    const proj = g.projection || [];
    if (proj.length) {
      const MONTH = { 20: '+1月', 40: '+2月', 60: '+3月', 120: '+半年', 250: '+1年' };
      const rows = proj.map(p =>
        `<tr><td style="padding:4px 8px">${MONTH[p.days] || ('+' + p.days + '日')}</td>
          <td style="padding:4px 8px;text-align:right">${num(p.avg_cost, 3)}</td>
          <td style="padding:4px 8px;text-align:right;color:var(--positive)">+${num(p.breakeven_upside_pct, 1)}%</td></tr>`).join('');
      document.getElementById('gold-proj').innerHTML =
        `<div class="muted" style="font-size:10px;margin:8px 0 2px;text-transform:none;letter-spacing:0">若净值原地不动、继续每日定投 → 成本线/回本门槛下移</div>
         <table style="width:100%;font-size:12px;border-collapse:collapse">
           <tr class="muted" style="font-size:10px"><th scope="col" style="padding:4px 8px;text-align:left;font-weight:inherit">继续</th><th scope="col" style="padding:4px 8px;text-align:right;font-weight:inherit">平均成本</th><th scope="col" style="padding:4px 8px;text-align:right;font-weight:inherit">回本只需涨</th></tr>
           ${rows}</table>`;
    } else { document.getElementById('gold-proj').innerHTML = ''; }

    const rt = g.realtime;
    const auto = (g.auto_added_days || 0) > 0
      ? ` · 自动累加 ${g.auto_added_days} 日(待对账，基线 ${g.reconciled_date || ''})`
      : (g.reconciled_date ? ` · 已对账 ${g.reconciled_date}` : '');
    document.getElementById('gold-asof').textContent =
      `净值 ${g.nav_date || ''}` +
      (rt ? ` · 实时估值 ${num(rt.est_nav, 4)} (${rt.est_change_pct >= 0 ? '+' : ''}${rt.est_change_pct}%) @ ${(rt.est_time || '').slice(11)}` : '') +
      auto +
      ` · 独立人民币卡，不并入跨币种总额`;
  }

  function renderLeveragedETF() {
    const l = safe(DATA, "leveraged_etf") || {};
    const colorize = (v) => v == null ? "neutral" : (v >= 50 ? "neg" : (v >= 25 ? "warn-text" : "neutral"));
    // No leading + sign — these are exposure %s, not P&L gains
    const fmt = (v) => v == null ? DASH : `${v.toFixed(1)}%`;
    const setNum = (id, v) => {
      const el = document.getElementById(id);
      el.textContent = fmt(v);
      el.className = "val " + colorize(v);
    };
    setNum("lev-us", l.us_pct);
    setNum("lev-hk", l.hk_pct);
    setNum("lev-combined", l.combined_pct);
    const tk = (l.tickers || []);
    document.getElementById("lev-tickers").textContent = tk.length ? `2x/3x ETFs: ${tk.join(", ")}` : "—";
  }

  function renderTodayRange() {
    const list = safe(DATA, "today_ranges") || [];
    const wrap = document.getElementById("range-list");
    if (!list.length) {
      wrap.innerHTML = '<div class="empty-state">No range data yet.</div>';
      return;
    }
    const maxPct = Math.max(1, ...list.map(r => r.range_pct || 0));
    wrap.innerHTML = list.map(r => {
      const pctFill = ((r.range_pct || 0) / maxPct) * 100;
      // dot position: (current - low) / (high - low) * 100
      const spread = (r.high - r.low) || 1;
      const dotPct = Math.max(0, Math.min(100, ((r.current - r.low) / spread) * 100));
      return `
        <div class="range-row">
          <div class="tk">${r.ticker}</div>
          <div class="range-bar">
            <div class="fill" style="width:${pctFill}%"></div>
            <div class="dot" style="left:${dotPct}%"></div>
          </div>
          <div class="val">${fmtPct(r.range_pct, 1)}</div>
        </div>`;
    }).join("");
  }

  function renderExtremes() {
    // Old-key fallback keeps the card populated during a staggered HTML/JSON deploy.
    const ext = safe(DATA, "current_holdings_extremes") || safe(DATA, "all_time_extremes") || {};
    const render = (rows, elId) => {
      const el = document.getElementById(elId);
      if (!rows || !rows.length) {
        el.innerHTML = '<div class="empty-state">—</div>';
        return;
      }
      el.innerHTML = rows.map(r => `
        <div class="extremes-row">
          <span class="tk">${r.ticker}</span>
          <span class="${pnlClass(r.pnl_percent)}">${fmtPct(r.pnl_percent, 1)}</span>
        </div>`).join("");
    };
    render(ext.winners, "extremes-winners");
    render(ext.losers, "extremes-losers");
  }

  // Episode-level historical win-rate badge for a decision action.
  // Lets you discount each LLM action at a glance: ⚠ <45% (worse than coin flip),
  // ~ 45–60% (weak), ✓ ≥60% (holds up). n = sample size; faint when small.
  function bucketWinBadge(bucket) {
    const pb = safe(DATA, "decision_metrics", "by_action", bucket);
    if (!pb || pb.win_rate == null || !pb.n_episodes) return "";
    const wr = pb.win_rate * 100;
    let cls = "wr-ok", icon = "✓";
    if (wr < 45)      { cls = "wr-bad"; icon = "⚠"; }
    else if (wr < 60) { cls = "wr-mid"; icon = "~"; }
    const lowN = pb.n_episodes < 8 ? " wr-lown" : "";
    const tip = pb.n_episodes < 8 ? "episode 样本少，参考性弱" : `该动作 episode 胜率 ${wr.toFixed(0)}%`;
    return `<span class="bucket-wr ${cls}${lowN}" title="${tip}">${icon}${wr.toFixed(0)}%<span class="wr-n">n${pb.n_episodes}</span></span>`;
  }

  // driven_by → which data source drove the call. Color encodes edge (catalyst has
  // edge ~62%, technical ~47% none). Mirrors calibration_by_driver card semantics.
  const DRIVER_META = {
    technical:  { label: "技术",   cls: "drv-technical"  },
    catalyst:   { label: "催化",   cls: "drv-catalyst"   },
    sentiment:  { label: "情绪",   cls: "drv-sentiment"  },
    influencer: { label: "影响力", cls: "drv-influencer" },
    macro:      { label: "宏观",   cls: "drv-macro"      },
    peer:       { label: "同行",   cls: "drv-peer"       },
    risk_rule:  { label: "风控",   cls: "drv-macro"      },
  };
  function driverChip(driven_by) {
    const d = (driven_by || "").trim().toLowerCase();
    const m = DRIVER_META[d];
    if (!m) return "";
    return `<span class="drv-chip ${m.cls}" title="driven_by=${d}（该信号源的 30d edge 见 Calibration·By Driver 卡）">${m.label}</span>`;
  }

  function renderPlanActions() {
    const list = (safe(DATA, "recent_decisions") || []).slice(0, 8);
    const wrap = document.getElementById("plan-actions");
    if (!list.length) {
      wrap.innerHTML = '<div class="empty-state">No recent plan actions.</div>';
      return;
    }
    wrap.innerHTML = list.map(a => {
      const oc = a.outcome || "pending";
      const conf = a.confidence != null ? (a.confidence * 100).toFixed(0) + "%" : DASH;
      const pnl = a.benefit_t1_pct != null ? fmtPct(a.benefit_t1_pct) : DASH;
      const cond = a.condition || {};
      return `
        <div class="plan-action">
          <div>
            <div class="tk">${a.ticker || DASH}</div>
            <div class="date">${a.date || ""}</div>
          </div>
          <div>
            <div>${a.action || DASH}${bucketWinBadge(a.action)}${driverChip(a.driven_by)}</div>
            <div class="meta">${a.strategy_id || DASH} · conf ${conf} · ${cond.type || DASH} · 方向分 ${pnl}</div>
          </div>
          <div class="outcome ${oc}">${oc}</div>
        </div>
      `;
    }).join("");
  }

  // =========================================================
  // LLM narrative cards (text-only; keys never reach the client)
  // =========================================================
  const escLLM = s => String(s == null ? "" : s).replace(/[<>&"]/g,
    c => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "\"": "&quot;" }[c]));

  function renderBehavioralReview() {
    const br = safe(DATA, "behavioral_review");
    const card = document.getElementById("behavioral-review-card");
    if (!card) return;
    if (!br || !br.verdict) { card.style.display = "none"; return; }
    card.style.display = "";
    document.getElementById("br-verdict").textContent = br.verdict;
    const tagMeta = {
      edge:    { cls: "br-edge", icon: "✓" },
      bias:    { cls: "br-bias", icon: "⚠" },
      warning: { cls: "br-warn", icon: "🚩" },
    };
    document.getElementById("br-points").innerHTML = (br.points || []).map(p => {
      const tm = tagMeta[(p.tag || "").toLowerCase()] || { cls: "br-bias", icon: "·" };
      return `<div class="br-point ${tm.cls}"><span class="br-icon">${tm.icon}</span>`
           + `<span>${escLLM(p.text)}</span></div>`;
    }).join("");
    const meta = safe(DATA, "insights_meta") || {};
    document.getElementById("br-src").textContent = meta.source ? `源 ${meta.source}` : "";
  }

  function renderDecisionAudit() {
    const audit = safe(DATA, "decision_audit");
    const card = document.getElementById("decision-audit-card");
    if (!card) return;
    const timing = (audit && audit.timing_diagnostic) || {};
    const byCcy = timing.by_currency || {};
    if (!audit || !["HKD", "USD"].some(c => byCcy[c])) { card.style.display = "none"; return; }
    card.style.display = "";
    document.getElementById("timing-zones").innerHTML = ["HKD", "USD"].map(ccy => {
      const z = byCcy[ccy] || {};
      const ci = z.paired_ci95_bps;
      const dist = z.distribution_bps;
      return `<div class="timing-zone">
        <div class="muted">${ccy} · 严格配对 ${z.n_events || 0} 次 / ${z.n_blocks || 0} blocks</div>
        <div class="median">${z.median_bps == null ? DASH : `${z.median_bps >= 0 ? "+" : ""}${z.median_bps} bps`}</div>
        <div class="muted">paired CI ${ci ? `[${ci[0]}, ${ci[1]}] bps` : "—（blocks<3）"}</div>
        <div class="muted">${dist ? `分布 p10 ${dist.p10} · p25 ${dist.p25} · p50 ${dist.median} · p75 ${dist.p75} · p90 ${dist.p90}` : "暂无可唯一匹配的真实成交"}</div>
      </div>`;
    }).join("");

    const timingEvents = ["HKD", "USD"].flatMap(
      ccy => ((byCcy[ccy] || {}).events || []));
    document.getElementById("timing-events").innerHTML = timingEvents.length
      ? `<table><thead><tr><th>标的/日</th><th>方向·股数</th><th>AI 成交</th><th>同日收盘</th><th>好多少</th></tr></thead><tbody>`
        + timingEvents.map(e => `<tr>
          <td>${escapeHtml(e.ticker)}<div class="muted">${escapeHtml(e.session)} · ${e.currency}</div></td>
          <td>${e.direction === "sell" ? "卖" : "买"} ${e.shares}</td>
          <td class="num">${e.ai_execution_price}</td>
          <td class="num">${e.same_day_close}</td>
          <td class="num ${pnlClass(e.improvement_bps)}">${e.improvement_bps >= 0 ? "+" : ""}${e.improvement_bps} bps<div class="muted">${fmtMoney(e.improvement_amount, e.currency)}</div></td>
        </tr>`).join("")
        + `</tbody></table>`
      : '<div class="empty-state">暂无能按同票/同日/同方向/同股数唯一匹配的真实成交；不会拿 OHLC 假设成交冒充。</div>';
  }

  function renderBearCases() {
    const cases = safe(DATA, "bear_cases") || [];
    const card = document.getElementById("bear-cases-card");
    if (!card) return;
    if (!cases.length) { card.style.display = "none"; return; }
    card.style.display = "";
    document.getElementById("bear-cases-body").innerHTML = cases.map(c => `
      <div class="bear-case">
        <div class="bear-tk">${escLLM(c.ticker)}</div>
        <div class="bear-thesis">${escLLM(c.thesis)}</div>
        <div class="bear-meta"><span class="bear-lbl bl-fal">证伪</span>${escLLM(c.falsifier)}</div>
        <div class="bear-meta"><span class="bear-lbl bl-watch">盯</span>${escLLM(c.watch)}</div>
      </div>
    `).join("");
    const meta = safe(DATA, "insights_meta") || {};
    document.getElementById("bear-src").textContent = meta.source ? `源 ${meta.source}` : "";
  }

  function renderHiddenConcentration() {
    const hc = safe(DATA, "hidden_concentration");
    const card = document.getElementById("hidden-conc-card");
    if (!card) return;
    if (!hc || !hc.headline) { card.style.display = "none"; return; }
    card.style.display = "";
    const pct = hc.exposure_pct != null ? hc.exposure_pct : null;
    const barW = pct != null ? Math.max(0, Math.min(100, pct)) : 0;
    document.getElementById("hidden-conc-body").innerHTML = `
      <div class="hc-headline">${escLLM(hc.headline)}</div>
      <div class="hc-bar-row">
        <div class="hc-factor">${escLLM(hc.factor)}</div>
        <div class="hc-bar"><div class="hc-bar-fill" style="width:${barW}%"></div></div>
        <div class="hc-pct">${pct != null ? pct + "%" : DASH}</div>
      </div>
      <div class="hc-detail">${escLLM(hc.detail)}</div>
    `;
    const meta = safe(DATA, "insights_meta") || {};
    document.getElementById("hidden-conc-src").textContent = meta.source ? `源 ${meta.source}` : "";
  }

  function renderStatusBanner() {
    const txt = safe(DATA, "status_banner");
    const targets = [
      {
        banner: document.getElementById("status-banner"),
        text: document.getElementById("sb-text"),
        time: document.getElementById("sb-time"),
      },
      {
        banner: document.getElementById("overview-status-banner"),
        text: document.getElementById("overview-sb-text"),
        time: document.getElementById("overview-sb-time"),
      },
    ].filter(t => t.banner);
    if (!targets.length) return;
    if (!txt) {
      targets.forEach(({ banner }) => {
        banner.classList.add("is-pending");
        banner.setAttribute("aria-hidden", "true");
      });
      return;
    }
    const meta = safe(DATA, "status_banner_meta") || {};
    let t = "";
    if (meta.generated_at) {
      const d = new Date(meta.generated_at);
      if (!isNaN(d)) t = d.toLocaleTimeString("en-GB", {
        hour: "2-digit", minute: "2-digit", timeZone: "Asia/Hong_Kong",
      }) + " HKT";
    }
    targets.forEach(({ banner, text, time }) => {
      banner.classList.remove("is-pending");
      banner.removeAttribute("aria-hidden");
      if (text) text.textContent = txt;
      if (time) time.textContent = t;
    });
  }

  function renderReflectKpi() {
    const fx = safe(DATA, "fx", "usdhkd") || 7.83;
    const rv = safe(DATA, "realized_vs_unrealized") || {};
    const cap = safe(DATA, "capital_deployed") || {};

    const realizedUsd   = safe(rv, "combined_usd", "realized");
    const unrealizedUsd = safe(rv, "combined_usd", "unrealized");

    // Compute USD-eq daily series from snapshots (deduped by date, sorted ascending)
    const snaps = (safe(DATA, "snapshots") || [])
      .filter(s => s.us_total_value != null || s.hk_total_value != null);
    const byDate = new Map();
    snaps.forEach(s => byDate.set(s.date, s));
    const series = Array.from(byDate.values()).sort((a, b) => a.date.localeCompare(b.date));

    const dailyPnl = series.map(s => ({
      date: s.date,
      pnl: ((s.us_today_change ?? 0) + ((s.hk_today_change ?? 0) / fx)),
    }));
    // equity basis (持仓市值 + 已实现现金) so sells don't punch a fake cliff into the curve
    const bookUsd = series.map(s => (s.us_equity ?? 0) + ((s.hk_equity ?? 0) / fx));
    // Current holdings cost (USD-eq) for 浮动率 — from totals API (more authoritative
    // than digging through snapshots which may lag).
    const usCostNow = safe(DATA, "totals", "us", "cost_usd") ?? 0;
    const hkCostNowHkd = safe(DATA, "totals", "hk", "cost_hkd") ?? 0;
    const currentCostUsd = usCostNow + (hkCostNowHkd / fx);

    // 当前浮动率：仅看现持仓账面盈亏 / 现持仓成本
    const floatPct = currentCostUsd > 0 ? (unrealizedUsd / currentCostUsd) * 100 : null;

    // 总回报率 (option C 2026-05-22): (浮+已实现) / (当前持仓成本 + 累计已实现)
    // 不再用 Σbuys（会被 rotation churn 重复计算）
    const totalPnl = (realizedUsd ?? 0) + (unrealizedUsd ?? 0);
    const capUsd = safe(cap, "combined_usd");
    const totalRetPct = capUsd && capUsd > 0 ? (totalPnl / capUsd) * 100 : null;

    // Win days
    const realDays = dailyPnl.filter(d => d.pnl !== 0);
    const winDays = realDays.filter(d => d.pnl > 0).length;
    const winPct = realDays.length ? Math.round((winDays / realDays.length) * 100) : null;

    // Best / worst day
    let best = null, worst = null;
    dailyPnl.forEach(d => {
      if (d.pnl === 0) return;
      if (best == null || d.pnl > best.pnl) best = d;
      if (worst == null || d.pnl < worst.pnl) worst = d;
    });

    // All-time drawdown from running peak (USD-eq book series).
    // Also capture concrete $ amounts: all-time peak equity + the peak→trough $ drop
    // that produced the worst drawdown.
    let peak = -Infinity;
    let maxDd = 0;
    let peakAllTime = -Infinity;   // highest equity ever (USD-eq)
    let peakAtWorst = null, troughAtWorst = null;  // bracket the deepest DD
    bookUsd.forEach(v => {
      if (v == null) return;
      if (v > peak) peak = v;
      if (v > peakAllTime) peakAllTime = v;
      if (peak > 0) {
        const dd = (v - peak) / peak * 100;
        if (dd < maxDd) { maxDd = dd; peakAtWorst = peak; troughAtWorst = v; }
      }
    });
    const maxDdAbsUsd = (peakAtWorst != null && troughAtWorst != null)
      ? (peakAtWorst - troughAtWorst) : null;

    const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    const setClass = (id, c) => {
      const el = document.getElementById(id);
      if (el) { el.classList.remove("pos","neg","neutral"); el.classList.add(c); }
    };

    setVal("kpi-floatpct", floatPct != null ? fmtPct(floatPct, 2) : DASH);
    setVal("kpi-floatpct-abs", unrealizedUsd != null
      ? `${fmtMoney(unrealizedUsd, "USD")} / ${fmtMoney(currentCostUsd, "USD")}`
      : "现持仓账面");
    setClass("kpi-floatpct", pnlClass(floatPct));

    setVal("kpi-totalret", totalRetPct != null ? fmtPct(totalRetPct, 2) : DASH);
    setVal("kpi-totalret-abs", capUsd
      ? `${fmtMoney(totalPnl, "USD")} ÷ ${fmtMoney(capUsd, "USD")} 基准`
      : "(浮+已实现) ÷ 累计投入");
    setClass("kpi-totalret", pnlClass(totalRetPct));

    // 净本金回报率 (复利口径 2026-05-29): (浮+已实现) / (累计成本 − 已实现)
    const npr = safe(DATA, "net_principal_return") || {};
    const nprUsd    = safe(npr, "combined_usd", "net_principal");
    const nprPct    = safe(npr, "combined_usd", "return_pct");
    const nprProfit = safe(npr, "combined_usd", "total_profit");
    // 分母口径诚实标注：US 用 true_principal(真实本金)，HK 回退 net_principal(净投入)
    const nprBasis  = safe(npr, "combined_usd", "return_basis");
    const nprBasisLbl = nprBasis === "true_principal" ? "真实本金" : "净投入本金";
    setVal("kpi-netret", nprPct != null ? fmtPct(nprPct, 2) : DASH);
    setVal("kpi-netret-abs", nprUsd
      ? `${fmtMoney(nprProfit, "USD")} ÷ ${fmtMoney(nprUsd, "USD")} ${nprBasisLbl}`
      : `(浮+已实现) ÷ ${nprBasisLbl}`);
    setClass("kpi-netret", pnlClass(nprPct));

    setVal("kpi-realized", fmtMoney(realizedUsd, "USD"));
    setClass("kpi-realized", pnlClass(realizedUsd));

    setVal("kpi-windays", winPct != null ? winPct + "%" : DASH);
    setVal("kpi-windays-sub", realDays.length ? `${winDays}/${realDays.length} 天` : "no data");
    setClass("kpi-windays", winPct == null ? "neutral" :
                            winPct >= 55 ? "pos" :
                            winPct <= 40 ? "neg" : "neutral");

    setVal("kpi-bestday", best ? fmtMoney(best.pnl, "USD") : DASH);
    setVal("kpi-bestday-date", best ? best.date : "no data");
    // Color by actual sign — "best day" can be negative if no positive day exists yet
    setClass("kpi-bestday", pnlClass(best ? best.pnl : null));

    setVal("kpi-worstday", worst ? fmtMoney(worst.pnl, "USD") : DASH);
    setVal("kpi-worstday-date", worst ? worst.date : "no data");
    setClass("kpi-worstday", pnlClass(worst ? worst.pnl : null));

    setVal("kpi-maxdd", maxDd < 0 ? fmtPct(maxDd, 1) : (bookUsd.length ? "0.0%" : DASH));
    setClass("kpi-maxdd", maxDd < 0 ? "neg" : "neutral");
    // sub: concrete $ — peak→trough drop + all-time peak equity
    if (maxDd < 0 && maxDdAbsUsd != null) {
      setVal("kpi-maxdd-sub", `−${fmtMoney(maxDdAbsUsd, "USD")} · 峰值 ${fmtMoney(peakAllTime, "USD")}`);
    } else if (isFinite(peakAllTime)) {
      setVal("kpi-maxdd-sub", `峰值 ${fmtMoney(peakAllTime, "USD")}`);
    }

    // ── 分市场拆解卡：US / HK 各一张（净本金口径 + 已落袋/浮动构成）──
    const mktCards = document.getElementById("mkt-cards");
    if (mktCards) {
      const ccyMoney = (v, ccy, plus) => {
        if (v == null || !isFinite(v)) return DASH;
        const sym = ccy === "USD" ? "$" : "HK$";
        const sign = v < 0 ? "-" : (plus ? "+" : "");
        return sign + sym + Math.abs(Math.round(v)).toLocaleString("en-US");
      };
      const signNum = v => (v == null || !isFinite(v)) ? DASH
        : (v < 0 ? "-" : "+") + Math.abs(Math.round(v)).toLocaleString("en-US");
      const pct1 = v => (v != null ? fmtPct(v, 1) : DASH);
      const buildCard = (key, label, ccy) => {
        const r = safe(rv, key, "realized") ?? 0;
        const u = safe(rv, key, "unrealized") ?? 0;
        const cost = safe(DATA, "totals", key, ccy === "USD" ? "cost_usd" : "cost_hkd") ?? 0;
        const profit = r + u;
        // 本金优先用后端 true_principal（现金流账本峰值净投入＝真实自掏现金），
        // 否则回退 净投入本金=成本−已实现。回报率同源，避免卡片本地重算出 142% 虚高。
        const nprK = safe(DATA, "net_principal_return", key) || {};
        const tp = nprK.true_principal;
        const usingTrue = tp != null && tp > 0;
        const net = usingTrue ? tp : (cost - r);
        const netPct = (nprK.return_pct != null) ? nprK.return_pct : (net > 0 ? profit / net * 100 : null);
        const netLabel = usingTrue ? "真实本金" : "净投入本金";
        const floPct = cost > 0 ? u / cost * 100 : null;
        const totPct = (cost + r) > 0 ? profit / (cost + r) * 100 : null;
        const ref = Math.max(Math.abs(r), Math.abs(u), 1);
        const rW = Math.min(Math.abs(r) / ref * 100, 100);
        const uW = Math.min(Math.abs(u) / ref * 100, 100);
        return `<div class="mkt-card" data-mkt="${key}">`
          + `<div class="mkt-head"><span class="mkt-dot"></span>${label} <span class="muted">· ${ccy}</span></div>`
          + `<div class="mkt-ret-label">净本金回报率</div>`
          + `<div class="mkt-ret ${pnlClass(netPct)}">${netPct != null ? pct1(netPct) : DASH}</div>`
          + `<div class="mkt-stats">`
            + `<div class="mkt-stat"><span class="lbl">${netLabel}</span><span class="v">${ccyMoney(net, ccy, false)}</span></div>`
            + `<div class="mkt-stat"><span class="lbl">总盈亏</span><span class="v ${pnlClass(profit)}">${ccyMoney(profit, ccy, true)}</span></div>`
          + `</div>`
          + `<div class="mkt-comp">`
            + `<div class="mkt-comp-row"><span class="lbl">已落袋</span><div class="mkt-bar"><div class="mkt-bar-fill ${r < 0 ? "neg" : "pos"}" style="width:${rW}%"></div></div><span class="v ${pnlClass(r)}">${signNum(r)}</span></div>`
            + `<div class="mkt-comp-row"><span class="lbl">浮动</span><div class="mkt-bar"><div class="mkt-bar-fill ${u < 0 ? "neg" : "pos"}" style="width:${uW}%"></div></div><span class="v ${pnlClass(u)}">${signNum(u)}</span></div>`
          + `</div>`
          + `<div class="mkt-chips">`
            + `<span class="mkt-chip">浮动率 <b class="${pnlClass(floPct)}">${pct1(floPct)}</b></span>`
            + `<span class="mkt-chip">总回报率 <b class="${pnlClass(totPct)}">${pct1(totPct)}</b></span>`
          + `</div>`
        + `</div>`;
      };
      mktCards.innerHTML = buildCard("us", "US", "USD") + buildCard("hk", "HK", "HKD");
    }
  }

  // Bucket → human-readable Chinese label (consistent with brief / wechat output)
  const BUCKET_LABEL = {
    cut: "减仓",
    trim_on_rebound: "反弹减仓",
    hold_and_watch: "观望",
    t_only: "短 T",
    add_only_on_trigger: "触发加仓",
    watch: "观望",
  };

  // (dead duplicate renderPlanTimeline removed 2026-05-30 — the live definition below
  //  overrode it; it still rendered the legacy "5d" pnl label and a stale pnlClass path.)

  function renderPlanReview() {
    const calib = safe(DATA, "decision_metrics") || {};
    const settled = calib.settled_episodes || 0;
    const raw = calib.raw_decisions || 0;
    // Only the active leg is a real follow-through decision: "following" a hold
    // means sitting still, which scores itself ~97% and dragged the blended
    // number to a meaningless ~50%. See decision_v2.compute_metrics.
    const byKind = calib.execution_by_kind || {};
    const act = byKind.active || {};
    const pas = byKind.passive || {};
    const active = calib.active || {};
    const brier = calib.brier;

    const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    const setSub = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    const setClass = (id, c) => {
      const el = document.getElementById(id);
      if (el) { el.classList.remove("pos","neg","neutral"); el.classList.add(c); }
    };

    // 44 was labelled "plans logged" but is settled_episodes — settled strategy
    // threads, not plans, and not the same unit as the execution counts beside it.
    setVal("plan-total", raw > 0 ? String(raw) : DASH);
    setSub("plan-total-sub", settled > 0 ? `30 天 · 其中 ${settled} 条已能算输赢` : "30 天");

    if (act.rate == null) {
      setVal("plan-followed", DASH);
      setSub("plan-followed-sub", "还没有已知执行");
      setClass("plan-followed", "neutral");
    } else {
      // Deliberately neutral, never red: ignoring these calls is not a failure —
      // the win-rate cell right next door says acting on them averaged -3%.
      setVal("plan-followed", (act.rate * 100).toFixed(1) + "%");
      const passiveNote = pas.rate != null
        ? ` · 不用动的 hold ${Math.round(pas.rate * 100)}% 是坐着没动自动算听了`
        : "";
      // Rows whose verification window closed without an answer never resolve —
      // the ticker is in no holdings list, which is what a plan on a spot ticker
      // held through a 2x ETF looks like. They are out of the denominator above,
      // so the count has to be visible or the rate is quietly censored. Same
      // shape as the win-rate card's 「另有 N 条判不了」 note.
      const stranded = (act.stranded || 0) + (pas.stranded || 0);
      const strandedNote = stranded ? ` · 另有 ${stranded} 条永远验不了（不在分母）` : "";
      setSub("plan-followed-sub", `${act.followed}/${act.known} 条要动手的${passiveNote}${strandedNote}`);
      setClass("plan-followed", "neutral");
    }

    if (active.win_rate == null) {
      setVal("plan-winrate", DASH);
      setSub("plan-winrate-sub", "active episodes · 数据不足");
      setClass("plan-winrate", "neutral");
    } else {
      const wr = active.win_rate * 100;
      const avg = active.avg_benefit_pct;
      const ci = active.cluster_ci95 ? ` · CI [${active.cluster_ci95[0].toFixed(2)}, ${active.cluster_ci95[1].toFixed(2)}]` : "";
      setVal("plan-winrate", wr.toFixed(1) + "%");
      const cov = calib.coverage_active || {};
      const covNote = cov.episodes_unresolved
        ? ` · 另有 ${cov.episodes_unresolved} 条判不了（休市/需人工核实）`
        : "";
      setSub("plan-winrate-sub", `n=${active.n_episodes} · avg ${avg == null ? "—" : (avg >= 0 ? "+" : "") + avg.toFixed(2) + "%"}${ci}${covNote}`);
      setClass("plan-winrate", wr > 50 ? "pos" : (wr < 50 ? "neg" : "neutral"));
    }

    if (brier == null) {
      setVal("plan-brier", DASH);
      setSub("plan-brier-sub", "—");
      setClass("plan-brier", "neutral");
    } else {
      // A bare Brier under a "0 = perfect" caption reads as "0.295, not bad".
      // Stated-vs-actual is the version a human can check, and the high-confidence
      // split is where the damage actually is. The score itself lives on the
      // calibration card with its baseline.
      const mc = calib.mean_confidence, br = calib.base_rate;
      const hc = calib.high_confidence;
      setVal("plan-brier", (mc != null && br != null)
        ? `${Math.round(mc * 100)}% → ${Math.round(br * 100)}%`
        : brier.toFixed(3));
      const hcNote = hc && hc.n
        ? ` · 最有把握的 ${hc.n} 次只对了 ${hc.wins} 次`
        : "";
      setSub("plan-brier-sub", (mc != null && br != null)
        ? `说自己 ${Math.round(mc * 100)}% 把握，实际对 ${Math.round(br * 100)}%${hcNote}`
        : `准度 ${brier.toFixed(3)}`);
      setClass("plan-brier", calib.brier_beats_baseline === true ? "pos"
                           : calib.brier_beats_baseline === false ? "neg" : "neutral");
    }

    // Per-action episode metrics
    const container = document.getElementById("plan-bucket-bars");
    if (!container) return;
    const buckets = ["cut", "trim_on_rebound", "add_only_on_trigger", "add_on_breakout", "hold_and_watch", "watch", "t_only"];
    const perBucket = calib.by_action || {};

    const rows = buckets
      .map(b => ({ name: b, cal: perBucket[b] }))
      .filter(r => r.cal && r.cal.n_episodes)
      .map(r => {
        // Bar width + color = 30d win rate (same source/thresholds as the action badges),
        // so a long green bar = a bucket that historically pays off. followed stays as text.
        const wr = r.cal && r.cal.win_rate != null ? Math.round(r.cal.win_rate * 100) : null;
        const wn = r.cal && r.cal.n_episodes ? r.cal.n_episodes : 0;
        const wCls = wr == null ? "" : wr < 45 ? "wr-bad" : wr < 60 ? "wr-mid" : "wr-ok";
        const lowN = wn && wn < 8 ? " lown" : "";
        const winTxt = wr == null
          ? `<span class="muted">无 30d 样本</span>`
          : `<span class="n">win ${wr}%</span> <span class="muted">n${wn}</span>`;
        const followTxt = r.cal.avg_benefit_pct != null ? ` · avg ${r.cal.avg_benefit_pct >= 0 ? "+" : ""}${r.cal.avg_benefit_pct.toFixed(2)}%` : "";
        return `
          <div class="bucket-row">
            <div class="name">${r.name}</div>
            <div class="bar-wrap">
              <div class="bar-fill ${wCls}${lowN}" style="width:${wr == null ? 0 : wr}%"></div>
            </div>
            <div class="stat">${winTxt}${followTxt}</div>
          </div>`;
      })
      .join("");

    container.innerHTML = rows ||
      `<div style="text-align:center; color:var(--text-faint); font-size:12px; padding:20px 0;">
         No settled decision episodes yet.
       </div>`;
  }

  // =========================================================
  // Plan Timeline — full decision cards (plan + rationale + outcome)
  // =========================================================
  function renderPlanTimeline() {
    const wrap = document.getElementById("plan-timeline");
    if (!wrap) return;
    const card = wrap.closest('.card');
    const list = safe(DATA, "plan_timeline") || [];
    if (!list.length) { if (card) card.style.display = 'none'; return; }
    if (card) card.style.display = '';
    const fmtConf = c => (c == null ? DASH : (c * 100).toFixed(0) + "%");
    const fmtTriggerPrice = (p) => p == null ? "" : ` @ ${typeof p === "number" ? p.toLocaleString("en-US", { maximumFractionDigits: 4 }) : p}`;
    const fmtSize = (a) => {
      const parts = [];
      const size = a.size || {};
      if (size.pct != null) parts.push(`${size.pct}%`);
      if (size.shares != null) parts.push(`${Number(size.shares).toLocaleString("en-US")} 股`);
      return parts.length ? ` · ${parts.join(" / ")}` : "";
    };
    const fmtPnl = (p) => {
      if (p == null) return "";
      const cls = p >= 0 ? "pos" : "neg";
      const s = p >= 0 ? "+" : "";
      return `<div class="pt-pnl ${cls}" title="对下一个快照报价的方向分：正值表示这条建议的方向对了。报价时点不稳定，不等于 T+1 收益">方向分 ${s}${p.toFixed(2)}%</div>`;
    };
    wrap.innerHTML = list.map(a => {
      const oc = a.outcome || "pending";
      const followed = (a.execution || "unknown").toLowerCase();
      const c = a.condition || {};
      const trig = `${c.type || ""}${fmtTriggerPrice(c.price)}${fmtSize(a)}`;
      const cond = c.note ? `<div class="pt-trigger" title="${escapeHtml(c.note)}">${escapeHtml(c.note)}</div>` : "";
      const rationale = a.rationale ? `<div class="pt-rationale">${escapeHtml(a.rationale)}</div>` : "";
      const region = /^\d/.test(a.ticker) ? "HK" : "US";
      const followedTag = followed === "true"
        ? `<div class="pt-followed-true">✓ followed</div>`
        : followed === "false"
        ? `<div class="pt-followed-false">未执行</div>`
        : `<div class="pt-followed-false">待跟踪</div>`;
      return `
        <div class="pt-row outcome-${oc}">
          <div class="pt-head">
            <div class="pt-date">${a.date || ""}</div>
            <div class="pt-ticker">${escapeHtml(a.ticker || DASH)}</div>
            <div class="pt-region">${region}</div>
          </div>
          <div class="pt-body">
            <div class="pt-action">${escapeHtml(a.action || DASH)}${bucketWinBadge(a.action)} · ${escapeHtml(a.strategy_id || DASH)}</div>
            <div class="pt-trigger">${escapeHtml(trig)}</div>
            ${cond}
            ${rationale}
          </div>
          <div class="pt-side">
            <div class="pt-conf">conf ${fmtConf(a.confidence)}</div>
            <div class="outcome ${oc}">${oc}</div>
            ${followedTag}
            ${fmtPnl(a.benefit_t1_pct)}
          </div>
        </div>`;
    }).join("");
  }

  // =========================================================
  // Decision episodes by condition type
  // =========================================================
  function renderCalibByTrigger() {
    const el = document.getElementById("plan-trigger-bars");
    if (!el) return;
    const data = safe(DATA, "decision_metrics", "by_condition") || {};
    const entries = Object.entries(data)
      .map(([k, v]) => ({ name: k, ...v }))
      .filter(e => (e.n_episodes || 0) > 0);
    if (!entries.length) {
      el.innerHTML = '<div class="empty-state" style="font-size:11px">No trigger data yet.</div>';
      return;
    }
    // Sort: lowest win rate first (most actionable: "改/砍这类")
    entries.sort((a, b) => {
      const aw = a.win_rate == null ? 99 : a.win_rate;
      const bw = b.win_rate == null ? 99 : b.win_rate;
      return aw - bw;
    });
    const maxTotal = Math.max(...entries.map(e => e.n_episodes || 0));
    el.innerHTML = entries.map(e => {
      const total = e.n_episodes || 0;
      const scale = maxTotal > 0 ? total / maxTotal : 0;
      const winFrac = e.win_rate || 0;
      const lossFrac = 1 - winFrac;
      const pendFrac = 0;
      const ci = e.cluster_ci95;
      const ciTxt = ci ? ` avgCI[${ci[0].toFixed(1)}–${ci[1].toFixed(1)}]` : "";
      const edge = e.edge_significant ? "✓" : "";   // 整区间 > 50% 才打勾(紧凑,省手机宽度)
      const wrTxt = `${(e.win_rate * 100).toFixed(0)}%${ciTxt} n=${e.n_episodes}${edge}`;
      const alertCls = (e.win_rate < 0.4 && e.n_episodes >= 2) ? " alert" : "";
      const confTxt = e.avg_benefit_pct != null ? ` · avg ${e.avg_benefit_pct >= 0 ? "+" : ""}${e.avg_benefit_pct.toFixed(2)}%` : "";
      return `
        <div class="trig-row">
          <div class="trig-name">${escapeHtml(e.name)}</div>
          <div class="trig-bar" style="width:${(scale * 100).toFixed(1)}%; min-width:24px">
            <div class="seg-win" style="width:${(winFrac * 100).toFixed(1)}%"></div>
            <div class="seg-loss" style="width:${(lossFrac * 100).toFixed(1)}%"></div>
            <div class="seg-pending" style="width:${(pendFrac * 100).toFixed(1)}%"></div>
          </div>
          <div class="trig-stat${alertCls}">${wrTxt}${confTxt}</div>
        </div>`;
    }).join("");
  }

  // =========================================================
  // Decision episodes by driver
  // =========================================================
  function renderCalibByDriver() {
    const el = document.getElementById("plan-driver-bars");
    if (!el) return;
    const data = safe(DATA, "decision_metrics", "by_driver") || {};
    const entries = Object.entries(data)
      .map(([k, v]) => ({ name: k, ...v }))
      .filter(e => (e.n_episodes || 0) > 0);
    if (!entries.length) {
      el.innerHTML = '<div class="empty-state" style="font-size:11px">No driver data yet — '
        + 'plan actions need a driven_by tag (backfilling from next brief).</div>';
      return;
    }
    // Sort: lowest win rate first (most actionable: 哪个消息源最该降权)
    entries.sort((a, b) => {
      const aw = a.win_rate == null ? 99 : a.win_rate;
      const bw = b.win_rate == null ? 99 : b.win_rate;
      return aw - bw;
    });
    const maxTotal = Math.max(...entries.map(e => e.n_episodes || 0));
    el.innerHTML = entries.map(e => {
      const total = e.n_episodes || 0;
      const scale = maxTotal > 0 ? total / maxTotal : 0;
      const winFrac = e.win_rate || 0;
      const lossFrac = 1 - winFrac;
      const pendFrac = 0;
      const ci = e.cluster_ci95;
      const ciTxt = ci ? ` avgCI[${ci[0].toFixed(1)}–${ci[1].toFixed(1)}]` : "";
      const edge = e.edge_significant ? "✓" : "";   // 整区间 > 50% 才打勾(紧凑,省手机宽度)
      const wrTxt = `${(e.win_rate * 100).toFixed(0)}%${ciTxt} n=${e.n_episodes}${edge}`;
      const alertCls = (e.win_rate < 0.4 && e.n_episodes >= 2) ? " alert" : "";
      const confTxt = e.avg_benefit_pct != null ? ` · avg ${e.avg_benefit_pct >= 0 ? "+" : ""}${e.avg_benefit_pct.toFixed(2)}%` : "";
      return `
        <div class="trig-row">
          <div class="trig-name">${escapeHtml(e.name)}</div>
          <div class="trig-bar" style="width:${(scale * 100).toFixed(1)}%; min-width:24px">
            <div class="seg-win" style="width:${(winFrac * 100).toFixed(1)}%"></div>
            <div class="seg-loss" style="width:${(lossFrac * 100).toFixed(1)}%"></div>
            <div class="seg-pending" style="width:${(pendFrac * 100).toFixed(1)}%"></div>
          </div>
          <div class="trig-stat${alertCls}">${wrTxt}${confTxt}</div>
        </div>`;
    }).join("");
    // 顶部小结：catalyst 纪律 + 辩论决断率 [cut #1 / #4]
    const dm = safe(DATA, "debate_metrics"), metrics = safe(DATA, "decision_metrics") || {};
    const bits = [];
    if (metrics.active_overrides != null)
      bits.push(`active overrides ${metrics.active_overrides}`);
    if (dm && dm.decisiveness_pct != null)
      bits.push(`辩论决断率 ${dm.decisiveness_pct}%`);
    if (bits.length) el.insertAdjacentHTML("afterbegin",
      `<div style="font-size:11px;opacity:.75;margin-bottom:var(--space-2)">🎯 ${bits.join(" · ")}</div>`);
  }

  // =========================================================
  // 历史净值极值 — peak / trough / max drawdown (equity basis)
  // =========================================================
  function renderHistoricalExtremes() {
    const dd = safe(DATA, "drawdown") || {};
    const regions = [
      { key: "combined", name: "合计 (HKD)", data: dd.combined },
      { key: "us", name: "美股 (USD)", data: dd.us },
      { key: "hk", name: "港股 (HKD)", data: dd.hk },
    ];
    // window hint: span of the embedded snapshot series
    const snaps = safe(DATA, "snapshots") || [];
    const hintEl = document.getElementById("extremes-window");
    if (hintEl && snaps.length) {
      hintEl.textContent = `样本窗口 ${snaps[0].date} → ${snaps[snaps.length-1].date}（共 ${snaps.length} 个交易日快照）。`;
    }

    const money = (v, cur) => {
      if (v == null || !isFinite(v)) return DASH;
      const sym = cur === "USD" ? "$" : "HK$";
      return sym + Math.round(v).toLocaleString("en-US");
    };
    const dstr = d => d ? d.slice(5) : "";  // MM-DD

    const profitDd = (dd.profit) || {};
    const signed = (v, cur) => (v != null && isFinite(v) ? (v >= 0 ? "+" : "−") + money(Math.abs(v), cur) : DASH);
    regions.forEach(r => {
      const el = document.getElementById(`ext-region-${r.key}`);
      if (!el) return;
      const e = r.data;
      if (!e) { el.innerHTML = `<div class="ext-name">${r.name}</div><div class="muted" style="margin-top:8px">无数据</div>`; return; }
      const cur = e.currency;
      // PRIMARY = 总利润口径 (净化本金) — trade-invariant: 加减仓不会虚抬/虚降它，
      // 所以它的峰值才是"真·赚最多"那天。净值(市值+已实现)会被买入抬高(花掉的现金
      // 不计入)，故只作参考。p 缺失时退回 equity 作主显示。
      const p = profitDd[r.key];
      const head = p || e;                 // who drives the headline + at_low flag
      const atLow = !!head.at_low;
      el.classList.toggle("is-low", atLow);
      // 最大回撤 %: 仅利润全程为正时有意义(见 _profit_extremes 守卫)；港股利润为负→null。
      const ddPct = (p && p.max_dd_pct != null) ? p.max_dd_pct.toFixed(1) + "%" : null;
      // 回撤恢复 — 用「金额」算 → 不论利润正负都成立(港股深套也能给恢复%):
      //   recovery = (当前 − 最深谷) / (起跌峰 − 最深谷)，0%=仍在坑底，100%=已回到峰。
      //   US:(1945−1221)/(2148−1221)=78%; 港股:(−22913−(−25864))/(4811−(−25864))≈10%。
      let recovery = null;
      if (p && p.max_dd_peak_val != null && p.max_dd_trough_val != null) {
        const span = p.max_dd_peak_val - p.max_dd_trough_val;   // 跌幅 $ (>0)
        const curV = p.current && p.current.value;
        if (span > 0 && curV != null) {
          recovery = Math.max(0, Math.min(100, (curV - p.max_dd_trough_val) / span * 100));
        }
      }
      let recTier = "mid", recTxt = "无回撤数据";
      if (recovery != null) {
        if (recovery >= 70) { recTier = "good"; recTxt = recovery >= 95 ? "几乎完全恢复 ✓" : "已反弹大部分"; }
        else if (recovery >= 30) { recTier = "mid"; recTxt = "部分恢复中"; }
        else { recTier = "poor"; recTxt = recovery < 5 ? "贴底无反弹 — 谨慎" : "刚反弹一点 — 仍接近最低"; }
      }
      const recPctTxt = recovery == null ? DASH : (recovery > 0 && recovery < 1) ? "<1%" : recovery.toFixed(0) + "%";
      // 港股利润为负、回撤%无意义 → 显示金额跌幅；否则显示 %。
      const ddMain = ddPct ? `${ddPct}<small>${signed(p && p.max_dd_abs, cur)}</small>` : signed(p && p.max_dd_abs, cur);
      const recoveryBlock = `
        <div class="ext-dd">
          <div class="ext-row"><span class="k">从坑底恢复</span><span class="v"><b class="rec-${recTier}">${recPctTxt}</b></span></div>
          <div class="dd-bar"><div class="dd-bar-fill ${recTier}" style="width:${recovery == null ? 0 : recovery}%"></div></div>
          <div class="span">${recTxt}（恢复% = 从最深谷反弹回历史利润峰的比例，100%＝已回峰值）</div>
        </div>`;
      const profitPrimary = p ? `
        <div class="ext-head">
          <span class="ext-name">${r.name}</span>
          <span class="ext-flag ${atLow ? "low" : "ok"}">${atLow ? "● 现处历史最低利润" : "未创利润新低"}</span>
        </div>
        <div class="ext-row"><span class="k">历史最高利润</span><span class="v">${signed(p.peak && p.peak.value, cur)}<small>${dstr(p.peak && p.peak.date)}</small></span></div>
        <div class="ext-row"><span class="k">历史最低利润</span><span class="v ${(p.trough && p.trough.value) < 0 ? "neg" : ""}">${signed(p.trough && p.trough.value, cur)}<small>${dstr(p.trough && p.trough.date)}</small></span></div>
        <div class="ext-row"><span class="k">当前利润</span><span class="v ${(p.current && p.current.value) < 0 ? "neg" : ""}">${signed(p.current && p.current.value, cur)}<small>${dstr(p.current && p.current.date)}</small></span></div>
        <div class="ext-dd">
          <div class="ext-row"><span class="k">最大回撤</span><span class="v">${ddMain}</span></div>
          <div class="ext-row"><span class="k">距利润峰值</span><span class="v ${(p.from_peak_abs ?? 0) < 0 ? "neg" : ""}">${signed(p.from_peak_abs, cur)}</span></div>
          <div class="span">口径＝总利润（浮盈＋已实现，净化本金）；加减仓不影响它</div>
        </div>${recoveryBlock}` : `
        <div class="ext-head"><span class="ext-name">${r.name}</span></div>
        <div class="muted" style="margin-top:8px">无利润口径数据</div>`;
      // SECONDARY = 真实总资产（持仓市值 + 现金余额）。这是 trade-invariant 的"现在值多少钱"
      // ——买入只是现金→股票、总额不变，不像旧"净值口径"会被加仓虚抬。只有当前值(没存历史
      // 每日现金，做不了曲线)。港股现金未跟踪 → 标注。
      const tot = safe(DATA, "totals") || {};
      let taLine = "";
      if (r.key === "us") {
        const mv = safe(tot, "us", "value_usd"), cash = safe(tot, "us", "cash_usd");
        if (mv != null) {
          const total = cash != null ? mv + cash : null;
          taLine = `
            <div class="ext-row"><span class="k">　持仓市值</span><span class="v">${money(mv, "USD")}</span></div>
            <div class="ext-row"><span class="k">　＋现金</span><span class="v">${cash != null ? money(cash, "USD") : "<span class='muted'>未跟踪</span>"}</span></div>
            <div class="ext-row"><span class="k">＝真实总资产</span><span class="v" style="color:var(--accent)">${total != null ? money(total, "USD") : DASH}</span></div>`;
        }
      } else if (r.key === "hk") {
        const mv = safe(tot, "hk", "value_hkd"), cash = safe(tot, "hk", "cash_hkd");
        taLine = `
            <div class="ext-row"><span class="k">　持仓市值</span><span class="v">${money(mv, "HKD")}</span></div>
            <div class="ext-row"><span class="k">　＋现金</span><span class="v">${cash != null ? money(cash, "HKD") : "<span class='muted'>未跟踪</span>"}</span></div>
            <div class="ext-row"><span class="k">＝真实总资产</span><span class="v" style="color:var(--accent)">${cash != null ? money(mv + cash, "HKD") : "<span class='muted'>需港股现金</span>"}</span></div>`;
      } else { // combined: US(市值+现金)折美元 + HK(市值+现金)折美元
        const um = safe(tot, "us", "value_usd"), uc = safe(tot, "us", "cash_usd");
        const hm = safe(tot, "hk", "value_hkd"), hc = safe(tot, "hk", "cash_hkd");
        const fxc = safe(DATA, "fx", "usdhkd") || 7.83;
        if (um != null && hm != null) {
          const usTot = um + (uc || 0), hkTotUsd = (hm + (hc || 0)) / fxc;
          const partial = (uc == null || hc == null);
          taLine = `
            <div class="ext-row"><span class="k">美股总资产</span><span class="v">${money(usTot, "USD")}${uc == null ? "<small>无现金</small>" : ""}</span></div>
            <div class="ext-row"><span class="k">港股总资产≈</span><span class="v">${money(hkTotUsd, "USD")}${hc == null ? "<small>无现金</small>" : ""}</span></div>
            <div class="ext-row"><span class="k">＝合计(USD)</span><span class="v" style="color:var(--accent)">${money(usTot + hkTotUsd, "USD")}${partial ? "<small>偏低·缺现金</small>" : ""}</span></div>`;
        }
      }
      const assetSecondary = taLine ? `
        <div class="ext-dd" style="opacity:.85">
          <div class="span" style="margin-top:0"><b>真实总资产</b>（持仓市值 ＋ 现金，加减仓不影响）</div>
          ${taLine}
        </div>` : "";
      el.innerHTML = profitPrimary + assetSecondary;
    });
  }

  // =========================================================
  // 8d Return Heatmap (Drill)
  // =========================================================
  function render8dHeatmap() {
    const el = document.getElementById("ret-heatmap");
    if (!el) return;
    const hh = safe(DATA, "holdings_history") || {};
    const wc = safe(DATA, "weight_confidence") || [];
    const weightMap = {};
    wc.forEach(w => { weightMap[w.ticker] = w.weight_pct; });

    // Active tickers from holdings, then compute 8d return from history
    const active = [
      ...(safe(DATA, "holdings", "us") || []),
      ...(safe(DATA, "holdings", "hk") || []),
    ].filter(h => h.is_active !== false && (h.shares ?? 0) > 0);

    const rows = active.map(h => {
      // holdings_history pads missing days with null (e.g. a freshly-bought name
      // has null before entry) — filter to finite numbers so a null base doesn't
      // divide to Infinity (null===0 is false, then x/null → x/0 → Infinity).
      const series = (hh[h.ticker] || []).slice(-8)
        .filter(v => typeof v === "number" && isFinite(v));
      if (series.length < 2 || series[0] <= 0) return null;
      const ret = (series[series.length - 1] - series[0]) / series[0] * 100;
      if (!isFinite(ret)) return null;
      return {
        ticker: h.ticker,
        region: (h.currency === "HKD" ? "HK" : "US"),
        ret,
        weight: weightMap[h.ticker] ?? null,
        n: series.length,
        series,
      };
    }).filter(Boolean);

    if (!rows.length) {
      el.innerHTML = '<div class="empty-state">No price history.</div>';
      return;
    }

    rows.sort((a, b) => b.ret - a.ret);

    // Color: lerp red(<-5%)↔neutral(0%)↔green(>+5%); saturation maxes at ±10%
    const colorFor = (ret) => {
      const clamp = Math.max(-10, Math.min(10, ret));
      const t = (clamp + 10) / 20; // 0..1
      // red rgb(239,68,68) -> grey rgb(60,68,90) -> green rgb(52,211,153)
      let r, g, b;
      if (t < 0.5) {
        const k = t / 0.5;
        r = Math.round(239 + (60 - 239) * k);
        g = Math.round(68 + (68 - 68) * k);
        b = Math.round(68 + (90 - 68) * k);
      } else {
        const k = (t - 0.5) / 0.5;
        r = Math.round(60 + (52 - 60) * k);
        g = Math.round(68 + (211 - 68) * k);
        b = Math.round(90 + (153 - 90) * k);
      }
      // softer fill (alpha) + opaque text
      return { fill: `rgba(${r},${g},${b},0.85)`, text: "#fff" };
    };

    el.innerHTML = rows.map(r => {
      const { fill, text } = colorFor(r.ret);
      const sign = r.ret >= 0 ? "+" : "";
      const meta = r.weight != null
        ? `${r.weight.toFixed(1)}% ${r.region} leg内`
        : `${r.region}`;
      return `
        <div class="ret-cell" style="background:${fill}; color:${text}; border-color:transparent">
          <div class="rc-ticker" style="color:${text}">${escapeHtml(r.ticker)}</div>
          <div class="rc-spark">${sparklineSVG(r.series, 84, 22)}</div>
          <div class="rc-ret" style="color:${text}">${sign}${r.ret.toFixed(2)}%</div>
          <div class="rc-meta" style="color:rgba(255,255,255,0.75)">${meta}</div>
        </div>`;
    }).join("");
  }

  window.registerDetailRenderers({
    drill: TAB_RENDERERS.drill,
    risk: TAB_RENDERERS.risk,
    market: TAB_RENDERERS.market,
    plan: TAB_RENDERERS.plan,
    reflect: TAB_RENDERERS.reflect,
  });
}());
