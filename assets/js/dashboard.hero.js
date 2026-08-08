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
    const watchHoldings = safe(DATA, "watch_holdings");
    (Array.isArray(watchHoldings) ? watchHoldings : flatHoldings())
      .forEach(h => { if (h.ticker) hmap[String(h.ticker).toUpperCase()] = h; });
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

  function decisionDeltaSummary() {
    const summary = safe(DATA, "decision_delta_summary");
    if (summary) return summary;
    const delta = safe(DATA, "decision_delta") || {};
    return {
      new_count: (delta.new || []).length,
      changed_count: (delta.changed || []).length,
      triggered_count: (delta.triggered || []).length,
      active_overrides_count: (delta.active_overrides || []).length,
      has_material_change: !!delta.has_material_change,
    };
  }

  // A. Hero top "今日要点" triage strip — pure synthesis of the compiled
  // Overview projection. Answers "what should I look at today" in 5s.
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
    const dd = decisionDeltaSummary();
    const changedN = dd.changed_count || 0;
    const newN = dd.new_count || 0;
    const triggeredN = dd.triggered_count || 0;
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
    const delta = decisionDeltaSummary();
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
    rows.push(row("今日决策变化", `新增 ${delta.new_count || 0} · 修改 ${delta.changed_count || 0} · 触发 ${delta.triggered_count || 0} · override ${delta.active_overrides_count || 0}`, "var(--text-dim)"));
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
      // The denominator and what it drops, together. `stranded` rows are calls
      // whose verification window closed without an answer and never resolves,
      // so a bare `known n=` overstates how much of the record this rate covers.
      const stranded = activeExec.stranded;
      followedMeta.textContent = activeExec.known == null
        ? "known sample —"
        : `known n=${activeExec.known}` + (stranded ? ` · ${stranded} unverifiable` : "");
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

  // Hero owns the only renderer registry that is present on the critical path.
  // Detail renderers register after their deferred script loads; keeping the
  // registry mutable avoids parsing 100KB+ of functions that Overview cannot call.
  const TAB_RENDERERS = {
    hero: [
      renderTodayHighlights, renderHonesty, renderMarketSnapshot, renderTotals,
      renderTodayPnl, renderRiskGuardrail, renderOverviewSummaries, renderGoldDca,
    ],
  };
  let RENDER_VERSION = 0;
  const _tabRenderVersion = new Map();

  function registerDetailRenderers(renderers) {
    Object.entries(renderers || {}).forEach(([tab, functions]) => {
      if (tab === "hero" || !Array.isArray(functions)) return;
      TAB_RENDERERS[tab] = functions;
    });
  }
  window.registerDetailRenderers = registerDetailRenderers;

  function hasTabRenderer(t) {
    return Array.isArray(TAB_RENDERERS[t]);
  }

  function renderTab(t, version = RENDER_VERSION) {
    if (!DATA || !hasTabRenderer(t) || _tabRenderVersion.get(t) === version) return;
    TAB_RENDERERS[t].forEach(fn => fn());
    _tabRenderVersion.set(t, version);
    const panel = document.querySelector(`.panel[data-panel="${t}"]`);
    if (panel) panel.querySelectorAll(".card.is-pending").forEach(card =>
      card.classList.remove("is-pending"));
    if (t === "risk" || t === "market") updateFoldPeeks();
  }

  function refreshTab(t) {
    if (!DATA || !hasTabRenderer(t) || currentTab() !== t) return;
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
    syncDeskRail();
    renderTab(activeTab, version);
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

  function flatHoldings() {
    const us = (safe(DATA, "holdings", "us") || []).map(h => ({ ...h, region: "us" }));
    const hk = (safe(DATA, "holdings", "hk") || []).map(h => ({ ...h, region: "hk" }));
    return [...us, ...hk].filter(h => h.is_active !== false && (h.shares ?? 0) > 0);
  }

  // 持仓决策矩阵优先消费 harness 编译的 versioned projection。旧 dashboard
  // join 仅作跨版本部署期间的 fallback；Pages 不再是投资规则的 owner。
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
