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
  // 第四次迭代修正二（券商终端化）：状态/数值/档位一律徽章 chip（label+
  // value+delta 三段式，tone ok/warn/bad），同类一排、放不下折行，不做段落；
  // 能画的数据画微图（接近度计量条、异动零轴迷你柱），文字退为 caption。
  // 判词句本体由 CSS 压成一行 caption —— 成段 prose 在这张卡里没有位置。
  function renderTodayHighlights() {
    const el = document.getElementById("today-highlights");
    const mvEl = document.getElementById("today-movers");
    if (!el) return;
    const chips = [];
    const chip = (tone, k, v, d, meterPct) =>
      `<span class="hl-chip tone-${tone}"><span class="hl-k">${k}</span>`
      + (v ? `<span class="hl-v">${v}</span>` : "")
      + (d ? `<span class="hl-d">${d}</span>` : "")
      + (meterPct == null ? ""
        : `<span class="hl-meter" aria-hidden="true"><i style="width:${meterPct.toFixed(1)}%"></i></span>`)
      + `</span>`;

    // 0. Regime — the day's default stance (same risk_on/neutral/risk_off the brief acts on)
    const rg = safe(DATA, "regime");
    if (rg && rg.label) {
      const map = { risk_on:  { tone:"ok",   stance:"默认持有" },
                    neutral:  { tone:"flat", stance:"按 frame 常规" },
                    risk_off: { tone:"bad",  stance:"防御·先减杠杆" } };
      const r = map[rg.label] || map.neutral;
      chips.push(chip(r.tone, "Regime",
        escapeHtml(rg.label.replace("_", " ")), escapeHtml(r.stance)));
    }

    // What changed since the previous decision set. Counts are dynamic and come
    // from the canonical delta payload; no live number is baked into static copy.
    const dd = decisionDeltaSummary();
    const changedN = dd.changed_count || 0;
    const newN = dd.new_count || 0;
    const triggeredN = dd.triggered_count || 0;
    if (dd.has_material_change || changedN || newN || triggeredN) {
      chips.push(chip(triggeredN ? "bad" : changedN || newN ? "warn" : "ok",
        "决策变化·新/改/触", `${newN}/${changedN}/${triggeredN}`));
    }

    // 30d 自评里只放一枚 Brier：它是「今日判定」这张牌自己的成绩单（判得准
    // 不准 vs 留一法基线），首屏别处没有。执行率/样本不放 —— 正上方 hero-rail
    // 第四格已经是「遵守率 30D 8.5% · 主动 call n=82」，同一个数说两遍。
    // （第七次迭代把执行纪律牌删掉时，唯一独有的就是这一枚，并进来。）
    const dm = safe(DATA, "decision_metrics") || {};
    if (dm.brier != null) {
      chips.push(chip(dm.brier_beats_baseline ? "ok" : "warn", "Brier·30d",
        Number(dm.brier).toFixed(3),
        dm.brier_baseline_loo == null ? "" : `基线 ${Number(dm.brier_baseline_loo).toFixed(3)}`));
    }

    // 1. Nearest-to-firing trigger (from the shared watch-level resolver)。
    // 接近度画成计量条：|dist| 归一到 0~10%（10% 外一律读作「远」），条只答
    // 「多近」，精确距离仍在 delta 文本；轨宽写死在 CSS，不随数据变。
    const near = (computeWatchRows().rows || []).find(r => r.ad != null);
    if (near) {
      const fire = near.ad < 2;
      const meter = Math.max(0, Math.min(100, 100 - near.ad * 10));
      chips.push(chip(fire ? "bad" : near.ad < 5 ? "warn" : "flat",
        `${escapeHtml(near.who)}·${escapeHtml(near.label)}`,
        fmtMoney(near.val, near.ccy),
        `现 ${fmtMoney(near.cur, near.ccy)} ${fmtPct(near.dist, 1)}${fire ? " ⚠" : ""}`,
        meter));
    }

    // 2. Movers today (today_movers is pre-sorted by |pct| desc)：不另设
    //    「最大波动」chip —— top3 本来就画成零轴柱（图为主），首格即最大，
    //    同一个数说两遍是把首屏读成对账单。
    const movers = (safe(DATA, "today_movers") || []).slice(0, 3);

    // 3. 异常不在这里出 chip：下面 overview-strip 的「异常」格印的是同一条
    //    （实测两处都是「6 · SPCH weight 79.6% + pnl -31.0%」），而那格还多
    //    一个 high 计数。同一个数在首屏出现两次就是 kcn 说的「和下面重复」。

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
    if (todays.length) {
      const head = todays[0].split(" ")[0] || "";
      const rest = todays[0].slice(head.length).trim();
      chips.push(chip("flat", "今日事件", escapeHtml(head), escapeHtml(rest)));
    }

    if (!chips.length && !movers.length) {
      el.style.display = "";
      el.replaceChildren();
      if (mvEl) mvEl.replaceChildren();
      return;
    }
    el.style.display = "";
    // The verdict column is intentionally compact. Movers/anomalies have their
    // own linked strip below and catalysts live in Signals, so the first three
    // decision-driving changes are the overview payload.
    // No icon slot: the old 7px status dot read as AI-flavoured (kcn: 彩色圆点
    // = AI 味). Row semantics live in position, weight and — for true alerts —
    // the red text colour, never in a coloured dot.
    // 异动条（第八次迭代把竖柱转成横条）：竖柱在 1144px 宽的牌上是三根
    // 14px 的孤棍，宽度全是空的；横条一行一只（ticker | 零轴分叉条 | pct），
    // 窄盒宽盒都填得满，且 ticker/pct 回到同一行而不是柱下 caption。
    // 条长 = |pct| 归一后取半幅的 92%，写百分比 —— 构图随盒子变、不随数据变。
    const maxAbs = Math.max(...movers.map(x => Math.abs(x.today_change_pct || 0)), 1);
    const mvRow = x => {
      const pct = x.today_change_pct || 0;
      const w = Math.abs(pct) / maxAbs * 46;
      return `<div class="hl-mv">`
        + `<span class="hl-mv-t">${escapeHtml(x.ticker || DASH)}</span>`
        + `<span class="hl-mv-bar"><i class="${pct >= 0 ? "up" : "down"}"`
        + ` style="width:${w.toFixed(1)}%"></i></span>`
        + `<span class="hl-mv-p ${pct >= 0 ? "pos" : "neg"}">${fmtPct(pct, 1)}</span></div>`;
    };
    const moversRow = movers.length
      ? `<div class="hl-movers" role="img" aria-label="今日异动前 ${movers.length}：`
        + movers.map(x => `${x.ticker} ${fmtPct(x.today_change_pct, 1)}`).join("、")
        + `"><div class="hl-mv-head">今日异动</div>${movers.map(mvRow).join("")}</div>`
      : "";
    // chip 与异动条各自落到自己的挂载点：≥1024 时它们是牌上左右两栏，
    // 窄档回到上下两带（版式全在 CSS，渲染端不判断宽度）。
    el.innerHTML = chips.slice(0, 5).join("");
    if (mvEl) mvEl.innerHTML = moversRow;
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
      + `<div style="color:var(--text-dim);font-size:var(--fs-micro);margin-top:var(--space-2)">算账在 Python：同策略连续决策按 episode 去重；一个 episode 只出一个样本、取其内部平均而非选某一条；被判定未触发的不结算；执行与建议质量分开统计。</div>`;
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

  // 「今日异动」那格在第七次迭代随 DOM 一起删了：它只印首位异动一个数，
  // 而判定牌的零轴柱印的是同一份 today_movers 的 top3。这里只剩异常两格。
  function renderOverviewSummaries() {
    const anomalyCount = document.getElementById("overview-anomaly-count");
    const anomalySummary = document.getElementById("overview-anomaly-summary");
    const anomalies = safe(DATA, "anomalies") || [];
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
      renderCommandDeck, renderDataHealth, renderCronSchedule, renderRiskGuardrail, renderOverviewSummaries,
      renderMarketSnapshot, renderTodayHighlights, renderHonesty, renderGoldDca,
      setupVerdictDeck,
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

  // Overview is the only runtime on the startup path. Its eight independent
  // projections used to land in one multi-second mobile task; yield between
  // them so the browser can paint and accept input while preserving the exact
  // same final DOM. Detail activations stay synchronous after an explicit tab
  // choice, where one atomic update is preferable to a partially refreshed tab.
  function renderLandingTab(t, version, done) {
    if (t !== "hero" || !hasTabRenderer(t)) {
      renderTab(t, version);
      done();
      return;
    }
    const renderers = TAB_RENDERERS[t];
    let index = 0;
    const step = () => {
      if (version !== RENDER_VERSION) return;
      if (currentTab() !== t) {
        done();
        return;
      }
      renderers[index++]();
      if (index < renderers.length) {
        setTimeout(step, 0);
        return;
      }
      _tabRenderVersion.set(t, version);
      const panel = document.querySelector(`.panel[data-panel="${t}"]`);
      if (panel) panel.querySelectorAll(".card.is-pending").forEach(card =>
        card.classList.remove("is-pending"));
      done();
    };
    step();
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
    renderLandingTab(activeTab, version, () => {
      renderBuildStatus();
      syncDeskRail();
      ensureVisibleCharts();
    });
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
      dot = 'bad'; label = `成品流程 ${wfCounts.failed} FAILED`;
    }
    else if (ig.error_count > 0) { dot = 'bad'; label = `体检 ${ig.error_count} ERROR`; }
    else if (stale.length || ig.warn_count > 0 || recovered || artifactOnly) {
      dot = 'warn';
      const bits = [];
      if (stale.length) bits.push(`${stale.length} 文件 stale`);
      if (ig.warn_count > 0) bits.push(`体检 ${ig.warn_count} WARN`);
      if (recovered) bits.push(`${recovered} 成品恢复/降级`);
      if (artifactOnly) bits.push(`${artifactOnly} 仅产物未确认投递`);
      label = bits.join(' · ');
    } else { dot = 'ok'; label = '数据健康 · 体检通过'; }
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
    (ig.top || []).forEach(t => lines.push(`${t.level === 'ERROR' ? '[ERROR]' : '[WARN]'} ${t.code}: ${stripEmoji(t.msg)}`));
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
    el.innerHTML = `<span class="bs-dot" data-tone="${dot}" aria-hidden="true"></span> <span class="bs-label">${label}</span>` +
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

  // 数据面的中文名。build_status.files[] 给的是机器文件名，读者不该被要求认识
  // peer_residual.json。未登记的新文件回落到去掉后缀的原名，不留空也不报错。(#876)
  const DATA_FILE_CN = {
    "portfolio.json": "持仓与账本",
    "benchmark.json": "基准对照",
    "catalysts.json": "催化剂日程",
    "cross_sectional_factor.json": "横截面因子",
    "em_news.json": "港股中文消息",
    "influencer_feed.json": "影响力雷达",
    "lev_regime.json": "杠杆刻度盘",
    "macro.json": "宏观指标",
    "news_evidence_graph.json": "新闻证据图",
    "peer_residual.json": "同行残差",
    "quant_signal_review.json": "因子自检",
    "quant_signals.json": "量化因子",
    "risk.json": "风险指标",
    "sentiment.json": "市场情绪",
    "us_news_digest.json": "美股新闻摘要",
    "t0_setups.json": "T+0 牌面",
    "t0_setup_review.json": "牌面背书",
    "decision_audit.json": "择时诊断",
    "shadow_portfolio.json": "政策模拟",
    "brief_projection.json": "简报投影",
    "workflow-outcomes.json": "流程账本",
    "cron-heartbeats.json": "定时心跳",
    "integrity_report.json": "体检报告",
    "coverage.json": "测试覆盖率",
    "readme_metrics.json": "README 指标",
    "overview.json": "总览快照",
    "dashboard.json": "面板数据",
  };
  const dataFileCn = name => DATA_FILE_CN[name] || String(name || "").replace(/\.json$/, "");

  // 负号在货币符号外面：−$1,361 而不是 $-1,361。只用于首屏指挥台，
  // 不改全局 fmtMoney（别处的断言吃的是旧格式）。
  function heroMoney(v, ccy) {
    if (v == null || !isFinite(v)) return DASH;
    const body = fmtMoney(Math.abs(v), ccy);
    return (v < 0 ? "−" : v > 0 ? "+" : "") + body;
  }

  // 首屏指挥台：一个主数 + 一条统计轨，取代 book / today / discipline 三张卡。(#874)
  function renderCommandDeck() {
    const pnlEl = document.getElementById("hero-pnl");
    const subEl = document.getElementById("hero-sub");
    const railEl = document.getElementById("hero-rail");
    if (!pnlEl || !subEl || !railEl) return;

    const us = safe(DATA, "totals", "us") || {};
    const hk = safe(DATA, "totals", "hk") || {};
    const fx = safe(DATA, "fx", "usdhkd");
    const fxMeta = safe(DATA, "fx") || {};
    const rv = safe(DATA, "realized_vs_unrealized") || {};
    const m = safe(DATA, "decision_metrics") || {};

    const has = v => v != null && isFinite(v);
    const eq = (usd, hkd) => (fx && has(usd) && has(hkd)) ? usd + hkd / fx : null;
    // totals.pnl 是「浮动」——市值减成本，没算落袋的部分。把它当「总盈亏」摆首屏
    // 是错的口径：总盈亏 = 已实现 + 浮动，和 Reflect 的总回报率分子同源。
    const unrealUsd = eq(us.pnl_usd, hk.pnl_hkd);
    // 首屏第一帧吃的是精简的 overview.json，里面没有 realized_vs_unrealized；
    // totals 两份 payload 都有，所以优先 rv、缺了就从 totals 现算，不留破折号。
    const realUsd = has(safe(rv, "combined_usd", "realized"))
      ? safe(rv, "combined_usd", "realized")
      : eq(us.realized_usd, hk.realized_hkd);
    const totalUsd = (has(realUsd) && has(unrealUsd)) ? realUsd + unrealUsd : unrealUsd;
    const bookUsd = eq(us.value_usd, hk.value_hkd);
    const todayUsd = eq(us.today_change_usd, hk.today_change_hkd);
    const todayPct = (has(bookUsd) && has(todayUsd) && (bookUsd - todayUsd) > 0)
      ? todayUsd / (bookUsd - todayUsd) * 100 : null;

    pnlEl.textContent = heroMoney(totalUsd, "USD");
    pnlEl.className = "hero-deck-pnl " + pnlClass(totalUsd);
    // 首屏只回答三件事：赚亏多少、其中落袋多少、今天涨没涨。账面与 FX 降到
    // 下面那条安静行 —— 原来它们挤在同一行，1440 宽下必折行，折行是首屏最
    // 显眼的「乱」。(#879)
    // 三段各自成一个 span：CSS 让段内 nowrap、段间可折行。原来整行是
    // `nowrap + text-overflow: ellipsis`，390px 上稳定截在「今日 +$807.18…」，
    // 今日涨跌幅从来没显示过 —— 首屏截掉一个数字就是丢信息，不是排版取舍。
    // 「今日」从这里拿掉：它在下面统计轨里有自己的一格，而且那一格还带 14 天
    // 的每日柱。同一个数在一屏里出现两次不是信息更全，是把首屏读成一张对账单
    // （kcn 2026-08-24：「下面其实和中间数字信息重复」）。副行只留主数拆不出来
    // 的那一半：落袋 vs 浮动。
    subEl.innerHTML =
      `<span class="hds-seg">已实现 <b class="${pnlClass(realUsd)}">${heroMoney(realUsd, "USD")}</b></span>`
      + `<span class="hds-sep">·</span>`
      + `<span class="hds-seg">浮动 <b class="${pnlClass(unrealUsd)}">${heroMoney(unrealUsd, "USD")}</b></span>`;

    const fxEl = document.getElementById("fx-rate-usd");
    if (fxEl) {
      if (fx) {
        const at = fxMeta.fetched_at ? new Date(fxMeta.fetched_at) : null;
        const stamp = at && !isNaN(at) ? at.toISOString().replace("T", " ").slice(0, 16) + "Z" : "";
        // 逐段包 span：整行以前是一个 textContent，浏览器于是在任何空格处
        // 断行 —— 1200 档实测把时间戳劈成「2026-」+「08-24 00:03Z」，一个
        // 值被折成两半。段内 nowrap、段间可断，和上面那行副行同一套规矩。
        // 账面总额也拿掉了：它逐字等于统计轨里美股 + 港股两格之和（换算后），
        // 首屏因此有两处在说同一笔钱。这一行退回它本来的职责——出处：汇率、
        // 汇率来源、取数时刻。
        const segs = [`USDHKD ${fmtNum(fx, 4)}`];
        if (fxMeta.source) segs.push(String(fxMeta.source));
        if (stamp) segs.push(stamp);
        // 分隔点跟着前一段走、断行机会交给 <wbr>：否则折行会落在分隔点之前，
        // 第二行以「· 」开头，读起来像少了个词。
        fxEl.innerHTML = segs
          .map((t, i) => `<span>${escapeHtml(t)}${i < segs.length - 1 ? " · " : ""}</span>`
            + (i < segs.length - 1 ? "<wbr>" : ""))
          .join("");
      } else {
        fxEl.textContent = "FX unavailable";
      }
    }

    // 分市场的今日涨跌幅：原来的 Today's P&L 卡有这两个数，合并后不能丢
    const ae = safe(m, "execution_by_kind", "active") || {};
    // 一格一次视觉起停：值和「它自己的变化」并成一行，限定语进标签，
    // 只有真正额外的信息（样本量、基线）才留副行。信息一条不少。(#879)
    const legPct = (v, chg) => (has(v) && has(chg) && (v - chg) > 0) ? chg / (v - chg) * 100 : null;
    const cell = (k, v, s, cls) =>
      `<div class="hero-rail-cell"><div class="hero-rail-k">${k}</div>`
      + `<div class="hero-rail-v ${cls || ""}">${v}</div>`
      + (s ? `<div class="hero-rail-s">${s}</div>` : "") + `</div>`;
    const withDelta = (v, delta, cls) =>
      `${v} <span class="hero-rail-d ${cls || ""}">${delta}</span>`;

    // 比例条：玻璃凹槽 + 受光的填充。条本身不带涨跌色 —— 它答的是「这笔钱有
    // 多大一块」，不是赚还是亏，上涨跌色会把两个问题搅在一起。
    const railMeter = (pct, caption) => {
      const w = (pct == null || !isFinite(pct)) ? null : Math.max(0, Math.min(100, pct));
      return `<div class="rc-meter" aria-hidden="true">`
        + (w == null ? "" : `<i style="width:${w.toFixed(1)}%"></i>`)
        + `</div><div class="rc-cap">${caption}</div>`;
    };

    // 近 n 个交易日的每日盈亏柱。数据源就是 spark 那条序列的一阶差分 ——
    // 同源同算法，不另开一条口径（首屏两处画同一件事却对不上，是这块面板
    // 反复出过的问题）。
    const dailyBars = (n) => {
      const pts = heroProfitSeries();
      if (pts.length < 3) return `<div class="rc-bars" aria-hidden="true"></div>`;
      const d = [];
      for (let i = Math.max(1, pts.length - n); i < pts.length; i++) {
        d.push({ date: pts[i].date, v: pts[i].v - pts[i - 1].v });
      }
      const maxAbs = Math.max(...d.map(x => Math.abs(x.v)), 1);
      const w = 100 / d.length;
      const bars = d.map((x, i) => {
        const h = Math.max(4, Math.abs(x.v) / maxAbs * 46);
        const cls = x.v > 0 ? "up" : x.v < 0 ? "down" : "flat";
        const pos = x.v >= 0 ? `bottom:50%` : `top:50%`;
        // 槽位中心对齐：(i+0.5)/n 让每根柱落在自己槽位的正中，首末柱两侧
        // 各留半个槽位。此前用 i/n 对齐，第一根柱的中心正好压在容器左缘，
        // 9px 柱的一半（4.5px）被推出容器外 —— 疏密随宽度变、粗细不变
        // 的规矩不动，动的只是柱在槽内的落点。
        return `<i class="${cls}" style="left:${((i + 0.5) * w).toFixed(2)}%;`
          + `width:${Math.max(1.2, w * 0.58).toFixed(2)}%;${pos};height:${h.toFixed(1)}%"></i>`;
      }).join("");
      const up = d.filter(x => x.v > 0).length;
      return `<div class="rc-bars" role="img" aria-label="`
        + `近 ${d.length} 个交易日每日盈亏：${up} 天为正、${d.length - up} 天为负">`
        + `${bars}</div><div class="rc-cap">近 ${d.length} 日 · ${up} 涨 ${d.length - up} 跌</div>`;
    };
    // 统计轨四格，每格自带一件图形：
    //   · 美股 / 港股 —— 值 + 占账面比例条（比例是形状问题，不是数字问题）
    //   · 距峰值 —— 峰→现回撤 + 自最低收复量表（同一序列的第三个参照点）
    //   · 遵守率 30d —— 值 + 量表条
    // 今日搬进了自己那一行（上面），自评 Brier 挪出首屏（Reflect 的 Brier 卡、
    // 决策带 KPI、Plan 三处都在，首屏这格是全站第四份）。
    const shareUs = (has(us.value_usd) && has(bookUsd) && bookUsd > 0)
      ? us.value_usd / bookUsd * 100 : null;
    const shareHk = (has(hk.value_hkd) && has(bookUsd) && fx && bookUsd > 0)
      ? (hk.value_hkd / fx) / bookUsd * 100 : null;
    // 距峰值：与 spark/柱图同一条序列上的「峰 → 现」。主数答「比起投点」，
    // 今日行答「比昨天」，这一格答「比这一轮最高点」—— 三个参照点互相不可
    // 推导，少了它，「这轮回撤收复了多少」在首屏没有答案（风控页那套回撤
    // 闸问的是同一个问题）。量表是自最低点的收复进度，说明行给峰值本身。
    const ptsAll = heroProfitSeries();
    let peakCell = null;
    if (ptsAll.length >= 3) {
      let hi = -Infinity, hiAt = "", lo = Infinity;
      ptsAll.forEach(p => {
        if (p.v > hi) { hi = p.v; hiAt = p.date; }
        if (p.v < lo) lo = p.v;
      });
      const nowV = ptsAll[ptsAll.length - 1].v;
      const dd = nowV - hi;
      const span = hi - lo;
      const recov = span > 0 ? Math.max(0, Math.min(100, (nowV - lo) / span * 100)) : null;
      peakCell = cell("距峰值",
        `<span class="${pnlClass(dd)}">${heroMoney(dd, "USD")}</span>`,
        railMeter(recov, `峰值 ${heroMoney(hi, "USD")} · ${String(hiAt || "").slice(5)}`));
    }
    railEl.innerHTML = [
      cell("美股", withDelta(fmtMoney(us.value_usd, "USD"),
        `${heroMoney(us.pnl_usd, "USD")} · ${fmtPct(us.pnl_pct)}`, pnlClass(us.pnl_usd)),
        railMeter(shareUs, `占账面 ${shareUs == null ? DASH : shareUs.toFixed(0) + "%"}`)),
      cell("港股", withDelta(fmtMoney(hk.value_hkd, "HKD"),
        `${heroMoney(hk.pnl_hkd, "HKD")} · ${fmtPct(hk.pnl_pct)}`, pnlClass(hk.pnl_hkd)),
        railMeter(shareHk, `占账面 ${shareHk == null ? DASH : shareHk.toFixed(0) + "%"}`)),
      peakCell,
      cell("遵守率 30d", ae.rate == null ? DASH : (ae.rate * 100).toFixed(1) + "%",
        // stranded = 核验窗口关闭时仍没有答案的 call，永远不会结算。只报 known
        // 会高估这个比率覆盖了多少记录，所以两个数一起给。
        railMeter(ae.rate == null ? null : ae.rate * 100,
          `主动 call · n=${ae.known == null ? DASH : ae.known}`
          + (ae.stranded ? ` · ${ae.stranded} 未能核验` : ""))),
    ].filter(Boolean).join("");

    // 今日行：一个 USD-eq 合计 + 美股/港股两个分项 + 一条与上方走势图同宽的
    // 每日盈亏柱。三个数放在一起才有意义（合计回答「今天亏了多少」，分项回答
    // 「亏在哪边」），柱子回答「这根在最近的分布里算大还是算小」。
    const todayEl = document.getElementById("hero-today");
    if (todayEl) {
      const usTodayPct = legPct(us.value_usd, us.today_change_usd);
      const hkTodayPct = legPct(hk.value_hkd, hk.today_change_hkd);
      const leg = (k, v, pct, cls) =>
        `<span class="ht-leg"><span class="ht-leg-k">${k}</span>`
        + `<b class="${cls}">${v}</b>`
        + (pct == null ? "" : ` <span class="${pnlClass(pct)}">${fmtPct(pct)}</span>`)
        + `</span>`;
      todayEl.innerHTML =
        `<div class="ht-nums">`
        + `<div class="overview-card-kicker">今日 · USD 等值</div>`
        + `<div class="ht-total ${pnlClass(todayUsd)}">${heroMoney(todayUsd, "USD")}`
        + (todayPct == null ? "" : ` <span class="ht-total-pct">${fmtPct(todayPct)}</span>`)
        + `</div>`
        + `<div class="ht-legs">`
        + leg("美股", heroMoney(us.today_change_usd, "USD"), usTodayPct,
          pnlClass(us.today_change_usd))
        + `<span class="hds-sep">·</span>`
        + leg("港股", heroMoney(hk.today_change_hkd, "HKD"), hkTodayPct,
          pnlClass(hk.today_change_hkd))
        + `</div></div>`
        + `<div class="ht-chart">${dailyBars(20)}</div>`;
    }

    renderHeroSpark();
  }

  // 首屏缩略走势：主数（总盈亏 = 已实现 + 浮动）自己的历史。
  // 口径必须和下面那张 Equity Curve 的「总利润」线**同源同算法**，否则一屏里
  // 两条线画同一件事却形状不同 —— 所以这里照抄 charts.js 的合并视图逻辑：
  // 同一日期只留一条、连续两条属于同一交易时段的只留后一条（美股时段跨港股
  // 午夜会落进两个港股日期，见 openclaw-us-crossday-double-count）。
  // 日期跟着值一起带出来：走势条要标注的「最低点在哪天」只能来自这里，
  // 在渲染端重新对齐一次序列必然会和这里的去重逻辑漂移。
  function heroProfitSeries() {
    const fx = safe(DATA, "fx", "usdhkd");
    if (!fx) return [];
    const snaps = (safe(DATA, "overview_equity") || safe(DATA, "snapshots") || [])
      .filter(s => s.us_total_value != null || s.hk_total_value != null);
    const byDate = new Map();
    snaps.forEach(s => byDate.set(s.date, s));
    let series = Array.from(byDate.values()).sort((a, b) => a.date.localeCompare(b.date));
    series = series.filter((s, i) => {
      const next = series[i + 1];
      if (!next) return true;
      if (s.us_asof && s.hk_asof && next.us_asof && next.hk_asof) {
        return !(s.us_asof === next.us_asof && s.hk_asof === next.hk_asof);
      }
      return true;
    });
    return series
      .map(s => (s.us_profit == null || s.hk_profit == null)
        ? null
        : { date: s.date, v: s.us_profit + s.hk_profit / fx })
      .filter(p => p && isFinite(p.v));
  }

  // 「2026-07-24」→「07-24」：走势条的脚注要的是位置，不是完整日期，年份
  // 已经由出处行给了。
  function heroSparkDay(iso) {
    return typeof iso === "string" && iso.length >= 10 ? iso.slice(5) : String(iso || "");
  }

  function renderHeroSpark() {
    const host = document.getElementById("hero-spark");
    if (!host) return;
    const pts = heroProfitSeries();
    // 两点以下画不出趋势。容器高度由 CSS 占住，所以这里清空不会让页面跳。
    if (pts.length < 3) { host.replaceChildren(); return; }

    const vals = pts.map(p => p.v);
    const W = 1000, H = 200, PAD = 6;            // viewBox 坐标，实际尺寸由 CSS 给
    const lo = Math.min(...vals, 0), hi = Math.max(...vals, 0);
    const span = (hi - lo) || 1;
    const x = i => PAD + i * (W - PAD * 2) / (vals.length - 1);
    const y = v => PAD + (hi - v) * (H - PAD * 2) / span;
    const line = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
    const zeroY = y(0);
    const area = `${line} L${x(vals.length - 1).toFixed(1)} ${zeroY.toFixed(1)} L${x(0).toFixed(1)} ${zeroY.toFixed(1)} Z`;
    const last = vals[vals.length - 1];
    const tone = last > 0 ? "pos" : last < 0 ? "neg" : "flat";

    // 最低点：给这条线一把标尺。没有它，形状只说得出「跌过又爬回来一点」，
    // 说不出跌到过哪、爬回来多少 —— 而那正是大数字回答不了的那半个问题。
    let li = 0;
    for (let i = 1; i < vals.length; i++) if (vals[i] < vals[li]) li = i;
    const lowest = vals[li];
    // 最低点就在末端时没有「自最低」可说（那句会退化成 +$0）。
    const recovered = li < vals.length - 2 ? last - lowest : null;

    const label = `总盈亏 ${vals.length} 个交易日走势：最低 ${heroMoney(lowest, "USD")}`
      + `（${pts[li].date}）`
      + (recovered != null ? `，自最低 ${heroMoney(recovered, "USD")}` : "")
      + `，最高 ${heroMoney(Math.max(...vals), "USD")}，当前 ${heroMoney(last, "USD")}`;

    const foot =
      `<span class="hs-foot-range">${escapeHtml(heroSparkDay(pts[0].date))} → `
      + `${escapeHtml(heroSparkDay(pts[pts.length - 1].date))} · ${vals.length} 个交易日</span>`
      + `<span class="hs-foot-low">最低 ${escapeHtml(heroMoney(lowest, "USD"))}`
      + `（${escapeHtml(heroSparkDay(pts[li].date))}）`
      + (recovered != null
        ? ` · 自最低 ${escapeHtml(heroMoney(recovered, "USD"))}`
        : "")
      + `</span>`;

    host.innerHTML =
      `<div class="hs-plot">`
      + `<svg class="hero-spark-svg ${tone}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"`
      + ` role="img" aria-label="${escapeHtml(label)}">`
      + `<defs><linearGradient id="hs-fade" gradientUnits="objectBoundingBox"`
      + ` x1="0" y1="0" x2="0" y2="1">`
      + `<stop offset="0" class="hs-fade-near"/><stop offset="1" class="hs-fade-far"/>`
      + `</linearGradient></defs>`
      + `<path class="hs-area" d="${area}"/>`
      + `<line class="hs-zero" x1="0" y1="${zeroY.toFixed(1)}" x2="${W}" y2="${zeroY.toFixed(1)}"/>`
      // 最低点竖线把脚注里的「最低」钉在曲线上的具体位置：从画布顶垂到那个
      // 点为止。（不能反过来从最低点垂到底：最低点就是画布底，那条线长度为
      // 零，画了等于没画。）比零轴更淡，才不会被读成第二条坐标轴。
      + `<line class="hs-low" x1="${x(li).toFixed(1)}" y1="0"`
      + ` x2="${x(li).toFixed(1)}" y2="${y(lowest).toFixed(1)}"/>`
      + `<path class="hs-line" d="${line}"/>`
      + `</svg>`
      // 零轴刻度已去掉（kcn 2026-08-24：「大图的 0 可以不要」）。零轴那条线
      // 本身留着 —— 它是曲线读正负的唯一参照，标签只是给它写名字，而这条线
      // 在一张只有一个量纲的图里不需要名字。
      + `</div>`
      + `<div class="hs-foot">${foot}</div>`;
      // 端点标记已移除（kcn 2026-08-24：spark 末端涨跌色圆点没用，去掉）。
  }

  // 数据健康：一块牌上压着三个互不相干的问题 —— ①页面上的数字新不新鲜
  // ②体检有没有报错 ③今天的成品有没有送出去。原来它们被压成「一行判词 +
  // 一条灰 meta」：判词借的是当下最坏的那一条，另外两条的状态读不出来，
  // 也读不出该不该动手（kcn 2026-09-01：「我也不知道该怎么看」）。
  // 现在固定三条泳道 —— 位置不动，每条各带一枚处置牌。判词只回答第一个
  // 问题：**一个任务没落地不等于页面上的数字是错的**，这两件事必须分开说，
  // 否则「简报 FAILED」会把一屏可信的数字染成红的。
  // 判过期只认 f.stale —— files[] 有两种新鲜度模式（max_age 比 sla_hours，
  // scheduled_fire 比 deadline_at），自己再算一遍 age>sla 会造出一批假警报。
  function renderDataHealth() {
    const root = document.getElementById("data-health");
    if (!root) return;
    const bs = safe(DATA, "build_status");
    if (!bs) { root.style.display = "none"; return; }
    root.style.display = "";

    const verdictEl = document.getElementById("dh-verdict") || document.getElementById("dh-title");
    const metaEl = document.getElementById("dh-meta");
    const stripEl = document.getElementById("dh-strip");
    const filesEl = document.getElementById("dh-files");
    const ig = bs.integrity || {};
    const wf = safe(DATA, "workflow_outcomes") || {};
    const wc = wf.counts || {};
    const files = (bs.files || []).slice();
    const late = files.filter(f => f.present === false || f.stale);
    const missing = files.filter(f => f.present === false);
    const failed = wc.failed || 0;
    const soft = (wc.recovered || 0) + (wc.degraded || 0);
    const okCount = wc.success || 0;
    const pending = wc.pending || 0;
    const slotTotal = okCount + soft + failed + pending;
    const igErr = ig.error_count || 0;
    const igWarn = ig.warn_count || 0;
    const igTop = (ig.top || [])[0] || null;
    const dropped = wf.wechat_dropped_slots || [];
    const droppedTotal = wf.wechat_dropped_telegram_covered || dropped.length;
    // 窗口写不出来就不写 —— 「37 档」配一个猜出来的小时数比没有小时数更坏。
    const winH = Number(wf.window_hours) > 0 ? Number(wf.window_hours) : null;

    // 点名读的是台账自己给的 degraded_slots（全窗口、有上限），不是 recent ——
    // recent 是尾巴不是集合，忙日里它一条降级都装不下（实测 16 条尾巴全是
    // 盘中盯盘，16:00 那次「恢复」早被挤出去了）。
    const SOFT_CN = { recovered: "恢复", degraded: "降级", artifact_only: "仅存档",
                      failed: "FAILED" };
    const jobsWith = (...states) => (wf.degraded_slots || [])
      .filter(r => states.includes((r || {}).status))
      .map(r => ({ job: r.job || "未具名任务", what: SOFT_CN[r.status] || r.status || "",
                   slot: String(r.slot || "").slice(0, 16).replace("T", " ") }));
    // 名单有上限，点不满就说「等 N 档」，不假装列全。
    const nameThem = (total, rows) => {
      if (!rows.length) return "";
      const shown = rows.slice(0, 2);
      const head = shown.map(r => `${r.job} ${r.what}`.trim()).join(" · ");
      return total > shown.length ? `${head} 等 ${total} 档` : head;
    };

    // 期限用量：max_age 用 age/sla；scheduled_fire 只有到期时刻，用「离截止还有多久
    // ÷ 24h」表达，两者都只是粗略的紧张程度，精确判定始终以 f.stale 为准。
    const usage = f => {
      if (f.present === false || f.stale) return 1;
      // 上游判 stale 有两种模式，这里只做「紧张程度」的粗略表达。未判 stale 的
      // 一律封顶 0.7，否则会画出一根满格的条却标着「在期」，自相矛盾。
      const raw = (() => {
        if (f.freshness_mode === "scheduled_fire") {
          const d = f.deadline_at ? new Date(f.deadline_at) : null;
          if (!d || isNaN(d)) return 0.4;
          const left = (d.getTime() - Date.now()) / 3600000;
          return left <= 0 ? 0.7 : 1 - Math.min(left, 24) / 24;
        }
        if (!f.sla_hours || f.age_hours == null) return 0.4;
        return f.age_hours / f.sla_hours;
      })();
      return Math.max(0.08, Math.min(0.7, raw));
    };
    const stateOf = f => f.present === false ? "missing" : (f.stale ? "late" : "ok");
    const detailOf = f => {
      if (f.present === false) return "文件缺失";
      if (f.freshness_mode === "scheduled_fire") {
        const d = f.deadline_at ? new Date(f.deadline_at) : null;
        const when = d && !isNaN(d)
          ? d.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit",
              minute: "2-digit", hour12: false, timeZone: "Asia/Hong_Kong" }) + " HKT"
          : "未知";
        return `${f.age_hours == null ? DASH : f.age_hours + "h"} · 应于 ${when} 前刷新`;
      }
      return `${f.age_hours == null ? DASH : f.age_hours + "h"} / 期限 ${f.sla_hours}h`;
    };

    // ── 三条泳道 ───────────────────────────────────────────────────────
    // 处置牌只有四种，含义写在卡片底部那行说明里，不靠读者猜：
    //   需处理 = 页面数字或成品真的受影响；观察 = 兜底已经生效，只记不动；
    //   已知不修 = kcn 已经拍板不处理；正常 = 没有要说的。
    const setLane = (key, tone, stat, note, chip) => {
      const lane = document.getElementById(`dh-lane-${key}`);
      if (lane) lane.dataset.tone = tone;
      const statEl = document.getElementById(`dh-${key}-stat`);
      const noteEl = document.getElementById(`dh-${key}-note`);
      const chipEl = document.getElementById(`dh-${key}-chip`);
      if (statEl) statEl.textContent = stat;
      if (noteEl) noteEl.textContent = note;
      if (chipEl) { chipEl.textContent = chip; chipEl.dataset.act = chip; }
    };
    // 构成条：只画有数的段，段宽按档数成比例 —— 「今天有多少比例是好的」
    // 是一眼能读的形状，一串数字不是。
    const drawBar = (id, parts) => {
      const el = document.getElementById(id);
      if (!el) return;
      const live = parts.filter(p => p.n > 0);
      const total = live.reduce((a, p) => a + p.n, 0);
      el.innerHTML = !total ? "" : live.map(p =>
        `<i class="dh-part is-${p.k}" style="flex:${p.n}"`
        + ` title="${escapeHtml(p.t)} ${p.n} 档"></i>`).join("");
    };
    // 体检没有分母（不存在「一共检查了 N 项」这个数），所以画计数点不画
    // 构成条 —— 一根没有分母的比例条是编出来的。
    const drawPips = (id, spec) => {
      const el = document.getElementById(id);
      if (!el) return;
      const out = [];
      spec.forEach(([kind, n, title]) => {
        for (let i = 0; i < Math.min(n, 10); i++) {
          out.push(`<i class="dh-pip is-${kind}" title="${escapeHtml(title)}"></i>`);
        }
      });
      el.innerHTML = out.join("");
    };

    const tightest = files.slice().sort((a, b) => usage(b) - usage(a))[0];
    setLane("files",
      missing.length ? "bad" : (late.length ? "warn" : "ok"),
      `${files.length - late.length}/${files.length} 在期`,
      late.length
        ? `逾期：${late.map(f => dataFileCn(f.name)).join("、")} —— 页面上这几块是旧数字`
        : (tightest ? `最紧张 ${dataFileCn(tightest.name)}（${detailOf(tightest)}）` : ""),
      late.length ? "需处理" : "正常");

    setLane("integrity",
      igErr ? "bad" : (igWarn ? "warn" : "ok"),
      `${igErr} ERROR · ${igWarn} WARN`,
      igTop ? String(igTop.msg || igTop.code || "") : "无异常",
      igErr ? "需处理" : (igWarn ? "观察" : "正常"));
    drawPips("dh-integrity-shape", igErr || igWarn
      ? [["bad", igErr, "ERROR"], ["warn", igWarn, "WARN"]]
      : [["ok", 1, "无异常"]]);

    setLane("delivery",
      failed ? "bad" : (soft ? "warn" : "ok"),
      winH ? `${slotTotal} 档 / ${winH}h` : `${slotTotal} 档`,
      failed
        ? `${nameThem(failed, jobsWith("failed")) || `${failed} 档 FAILED`} —— 成品没落地`
        : (soft
            ? `${nameThem(soft, jobsWith("recovered", "degraded")) || `${soft} 档恢复或降级`} · 成品已送达`
            : "全部按时送达"),
      failed ? "需处理" : (soft ? "观察" : "正常"));
    drawBar("dh-delivery-shape", [
      { k: "ok", n: okCount, t: "成功" },
      { k: "warn", n: soft, t: "恢复或降级" },
      { k: "bad", n: failed, t: "FAILED" },
      { k: "idle", n: pending, t: "进行中" },
    ]);

    // ── 判词只回答一件事：页面上的数字能不能信 ─────────────────────────
    // 数据面逾期 / 体检 ERROR 会让读者正在看的数字变旧或变错；一个任务
    // FAILED 不会 —— 它影响的是成品有没有送出去与有没有归档。两者混成
    // 一句会让人要么过度紧张，要么把真的过期当成「又是那个失败的任务」。
    const trustBroken = late.length || igErr;
    const todoCount = (late.length ? 1 : 0) + (igErr ? 1 : 0) + (failed ? 1 : 0);
    const watchCount = (igErr ? 0 : (igWarn ? 1 : 0)) + (failed ? 0 : (soft ? 1 : 0));
    const tone = (trustBroken || failed) ? "bad" : ((igWarn || soft) ? "warn" : "ok");
    const disposition = todoCount ? `${todoCount} 件要处理`
      : (watchCount ? `${watchCount} 件观察中` : "无事可做");
    const trustText = trustBroken
      ? `页面数字存疑 · ${late.length ? `${late.length} 个数据面逾期` : `体检 ${igErr} 项 ERROR`}`
      : "页面数字可用";
    root.dataset.tone = tone;
    if (verdictEl) {
      // 两截分开着色：把「页面数字可用」印成红的（因为别处有个任务挂了）
      // 正是这块牌以前最误导人的地方。
      verdictEl.innerHTML =
        `<span class="dh-trust" data-trust="${trustBroken ? "broken" : "ok"}">`
        + `${escapeHtml(trustText)}</span> · `
        + `<span class="dh-todo" data-sev="${todoCount ? "bad" : (watchCount ? "warn" : "ok")}">`
        + `${escapeHtml(disposition)}</span>`;
    }

    if (metaEl) {
      const bits = [];
      // 微信单通道掉投：上游 ret=-2，kcn 已定不修也不告警（#771），但「这一
      // 窗口掉了几档」必须答得上来。它不改 tone，也不占泳道 —— 成品由
      // Telegram 兜住了，它属于「已知不修」，位置就该在这条安静的行里。
      if (droppedTotal) bits.push(`微信掉投 ${droppedTotal} 档 · TG 已兜 · 已知不修`);
      if (bs.generated_at) bits.push(`构建 ${String(bs.generated_at).replace("T", " ").slice(0, 16)}`);
      metaEl.textContent = bits.join(" · ");
    }

    if (stripEl) {
      stripEl.innerHTML = files.map(f => {
        const st = stateOf(f);
        const pctUsed = Math.round(usage(f) * 100);
        return `<span class="dh-seg is-${st}" style="--used:${pctUsed}%"`
          + ` title="${escapeHtml(dataFileCn(f.name))} · ${escapeHtml(f.name)} · ${escapeHtml(detailOf(f))}">`
          + `<i></i></span>`;
      }).join("");
    }

    const caption = document.getElementById("dh-caption");
    if (caption) {
      caption.textContent = "处置：需处理＝页面数字或成品真的受影响，要动手；"
        + "观察＝兜底已生效、成品到了，只记不动；已知不修＝已拍板不处理。";
    }

    if (filesEl) {
      // 逐项第一组是「处置清单」：只列 需处理 的那几条，每条带下一步该去
      // 哪看。剩下两组（投递掉投 / 数据面逐项）是台账，不是待办。
      const todo = [];
      late.forEach(f => todo.push({
        name: dataFileCn(f.name), where: f.name, why: detailOf(f),
        next: f.present === false ? "文件没生成，查它的生成任务" : "页面上这块是旧数字，查它的生成任务",
      }));
      (ig.top || []).filter(t => String(t.level || "").toUpperCase() === "ERROR").forEach(t => todo.push({
        name: "体检", where: String(t.code || ""), why: String(t.msg || ""),
        next: "看 assets/data/integrity_report.json",
      }));
      jobsWith("failed").forEach(r => todo.push({
        name: r.job, where: r.slot, why: "成品未落地（final_product=failed）",
        next: "看 workflow-outcomes.json 里这一槽的 stages",
      }));
      const todoRows = todo.length
        ? `<div class="dh-sub">处置 · 需处理</div>`
          + todo.map(t => `<div class="dh-row is-todo">`
            + `<span class="dh-name">${escapeHtml(t.name)}</span>`
            + `<span class="dh-file">${escapeHtml(t.where)}</span>`
            + `<span class="dh-bar"></span>`
            + `<span class="dh-detail">${escapeHtml(t.why)}</span>`
            + `<span class="dh-state">${escapeHtml(t.next)}</span></div>`).join("")
        : "";

      const unnamed = Math.max(0, droppedTotal - dropped.length);
      const deliveryRows = dropped.length
        ? `<div class="dh-sub">投递 · 微信掉投（上游 ret=-2，已知不修）</div>`
          + dropped.map(r => `<div class="dh-row is-delivery">`
            + `<span class="dh-name">${escapeHtml(r.job || "未具名任务")}</span>`
            + `<span class="dh-file">${escapeHtml(String(r.slot || "").slice(0, 16).replace("T", " "))}</span>`
            + `<span class="dh-bar"></span>`
            + `<span class="dh-detail">微信 sendMessage ret=-2 prepare failed</span>`
            + `<span class="dh-state">TG 已兜</span></div>`).join("")
          // 名单有上限，超出的那几档必须说出来 —— 否则「掉投 9 档」配 8 行
          // 会读成列全了。
          + (unnamed
            ? `<div class="dh-row is-delivery"><span class="dh-name muted">另有 ${unnamed} 档</span>`
              + `<span class="dh-file"></span><span class="dh-bar"></span>`
              + `<span class="dh-detail">更早的槽位见 workflow-outcomes.json</span>`
              + `<span class="dh-state"></span></div>`
            : "")
        : "";

      filesEl.innerHTML = todoRows + deliveryRows + `<div class="dh-sub">数据面</div>` + files
        .slice()
        .sort((a, b) => usage(b) - usage(a))
        .map(f => {
          const st = stateOf(f);
          const label = st === "missing" ? "缺失" : st === "late" ? "逾期" : "在期";
          return `<div class="dh-row is-${st}">`
            + `<span class="dh-name">${escapeHtml(dataFileCn(f.name))}</span>`
            + `<span class="dh-file">${escapeHtml(f.name)}</span>`
            + `<span class="dh-bar"><i style="width:${Math.round(usage(f) * 100)}%"></i></span>`
            + `<span class="dh-detail">${escapeHtml(detailOf(f))}</span>`
            + `<span class="dh-state">${label}</span>`
            + `</div>`;
        }).join("");
    }

    const toggle = document.getElementById("dh-toggle");
    if (toggle && toggle.dataset.wired !== "1") {
      toggle.dataset.wired = "1";
      toggle.addEventListener("click", () => {
        const open = toggle.getAttribute("aria-expanded") !== "true";
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        toggle.textContent = open ? "收起" : "逐项";
        if (filesEl) filesEl.hidden = !open;
      });
    }
  }

  // ── 定时任务时刻表 ──
  // 每槽一枚灯。状态不在这里推导：dashboard.json 的 cron_schedule 里已经是
  // workflow-outcomes 账本 final_product 的定论，前端只做「定论 → 颜色」的映射。
  // 未知状态刻意落到 unknown（灰）而不是绿——新状态该被看见，不该被默认成好。
  const CRON_STATES = {
    ok:          { tone: "ok",      cn: "正常" },
    recovered:   { tone: "ok-soft", cn: "兜底补上" },
    degraded:    { tone: "warn",    cn: "降级送达" },
    failed:      { tone: "bad",     cn: "未落地" },
    missed:      { tone: "bad",     cn: "没跑" },
    running:     { tone: "live",    cn: "进行中" },
    upcoming:    { tone: "idle",    cn: "待跑" },
    unmonitored: { tone: "idle",    cn: "账本看不到" },
    unknown:     { tone: "idle",    cn: "状态未知" },
  };

  function renderCronSchedule() {
    const root = document.getElementById("cron-board");
    if (!root) return;
    const cs = safe(DATA, "cron_schedule");
    const jobs = (cs && cs.jobs) || [];
    if (!jobs.length) { root.hidden = true; return; }
    root.hidden = false;
    root.classList.remove("is-pending");

    const rowsEl = document.getElementById("cb-rows");
    const counts = {};
    let scheduled = 0;
    jobs.forEach(j => (j.slots || []).forEach(s => {
      const key = CRON_STATES[s.state] ? s.state : "unknown";
      counts[key] = (counts[key] || 0) + 1;
      if (key !== "unmonitored") scheduled += 1;
    }));
    const n = k => counts[k] || 0;
    const landed = n("ok") + n("recovered");
    const broken = n("failed") + n("missed");

    // 判词只说落地了多少、坏了多少。把「兜底补上」单列，因为它和「首次即成」
    // 是两件事：都送到了，但一个烧掉了一次尝试。
    // 判词只能说到证据为止：有降级就不许说「正常」，有兜底就点出来——都送到了，
    // 但一个是首次即成、一个烧掉了一次尝试，混成一句话就把区别抹掉了。
    const verdictEl = root.querySelector(".cb-verdict");
    if (verdictEl) {
      verdictEl.textContent =
        broken ? `${broken} 槽没落地`
        : n("degraded") ? `${n("degraded")} 槽降级送达`
        : n("recovered") ? `${n("recovered")} 槽靠兜底补上`
        : (n("upcoming") + n("running") ? "已跑的都正常" : "今天全部正常");
    }
    root.dataset.tone = broken ? "bad" : (n("degraded") || n("recovered") ? "warn" : "ok");

    const bits = [];
    if (landed) bits.push(`${landed} 落地`);
    if (n("recovered")) bits.push(`其中 ${n("recovered")} 靠兜底`);
    if (n("degraded")) bits.push(`${n("degraded")} 降级`);
    if (broken) bits.push(`${broken} 没落地`);
    if (n("running")) bits.push(`${n("running")} 进行中`);
    if (n("upcoming")) bits.push(`${n("upcoming")} 待跑`);
    const metaEl = document.getElementById("cb-meta");
    if (metaEl) {
      metaEl.textContent = `${cs.date || ""} · 共 ${scheduled} 槽` +
        (bits.length ? ` · ${bits.join(" · ")}` : "");
    }

    const legendEl = document.getElementById("cb-legend");
    if (legendEl) {
      legendEl.innerHTML = ["ok", "recovered", "degraded", "missed", "upcoming"]
        .map(k => `<span class="cb-key"><i class="cb-dot" data-tone="${CRON_STATES[k].tone}"></i>`
          + `${escapeHtml(CRON_STATES[k].cn)}</span>`).join("");
    }

    if (rowsEl) {
      rowsEl.innerHTML = jobs.map(j => {
        const slots = (j.slots || []).map(s => {
          const st = CRON_STATES[s.state] ? s.state : "unknown";
          const label = `${j.job} ${s.at} ${CRON_STATES[st].cn}`;
          return `<span class="cb-slot" data-tone="${CRON_STATES[st].tone}" title="${escapeHtml(label)}"`
            + ` aria-label="${escapeHtml(label)}"><i class="cb-dot" data-tone="${CRON_STATES[st].tone}"></i>`
            + `${escapeHtml(s.at)}</span>`;
        }).join("");
        return `<div class="cb-row"${j.unmonitored ? ' data-unmonitored="1"' : ""}>`
          + `<span class="cb-job">${escapeHtml(j.job)}</span>`
          + `<span class="cb-slots">${slots}</span></div>`;
      }).join("");
    }
  }

  function flatHoldings() {
    const us = (safe(DATA, "holdings", "us") || []).map(h => ({ ...h, region: "us" }));
    const hk = (safe(DATA, "holdings", "hk") || []).map(h => ({ ...h, region: "hk" }));
    return [...us, ...hk].filter(h => h.is_active !== false && (h.shares ?? 0) > 0);
  }

  // 持仓决策矩阵优先消费 harness 编译的 versioned projection。旧 dashboard
  // join 仅作跨版本部署期间的 fallback；Pages 不再是投资规则的 owner。
  // ── 判定牌组（第六次迭代）──────────────────────────────────────────
  // 形态不变（单词卡牌组：顶牌全显、下层露边、横滑/指示点/方向键换牌），
  // 画风与配色一字未动；这一轮只修「堆叠交互诡异」的四个几何/行为来源：
  //  1. 滑出层的位移 before 实测跑到 x=-160（牌组左缘 x=28 之外），盖住
  //     相邻区块 —— 牌桌没有边。stage 改 overflow:clip，抽走的牌消失在
  //     台面边缘（CSS 侧）。
  //  2. 中间态是两套牌位拼出来的：滑出层横移 × 升起层原地缩放，而第三张
  //     在整段过程里冻在 m=2、等 idx 一变才跳。改成单一连续模型 —— 每张
  //     牌的位姿只由「深度 d = i - cur」推出，d<0 是正在抽走，d≥0 是台面
  //     第 d 层。没有分支，也就没有撕裂。
  //  3. 深度改成固定 8px 露边 + 固定 8px 单边缩进（由 scaleX 换算）。原来
  //     的 uniform scale 让露边随宽度变，1200 档只露 4px，读作「牌没放齐」。
  //     z-index 同时降为静态 n-i：牌只会往左抽走，压序永远是「序号小的在
  //     上」，逐帧改 z 是多余的闪烁源。
  //  4. 撤掉两件自我表演：7s 自动轮播（首屏不该有自己转的东西；换牌三通道
  //     仍在）与整叠 0.97 按压缩放（1144px 的面缩 3% 读作版面抽搐，跟手
  //     位移本身就是按压反馈）。
  // 物理保留 Apple Fluid Interfaces 那套：手势 1:1 跟手、任意时刻可打断可
  // 反向、释放把速度交给弹簧、落点用动量投影、边界 rubber-band 渐进抵抗；
  // 阻尼统一临界（换牌不弹），一次只走一张。只写 transform/opacity，禁
  // keyframes；reduced-motion 直接落位。
  // ⚠ 与 dashboard.render.js 的本函数逐字同步（parity 棘轮只准同步）。
  function setupVerdictDeck() {
    const deck = document.getElementById("verdict-deck");
    const stage = document.getElementById("verdict-deck-stage");
    if (!deck || !stage || deck.dataset.deckBound) return;
    deck.dataset.deckBound = "1";
    const cards = Array.from(stage.querySelectorAll(".deck-card"));
    const n = cards.length;
    if (!n) return;
    const dotsBox = document.getElementById("verdict-deck-dots");
    const RM = window.matchMedia("(prefers-reduced-motion: reduce)");
    const SPRING = 0.26;      // 换牌弹簧 response（秒）：实测到位（≤1.7px
                              // 残差）397ms，压在「轮播切换 ≤400ms」之内
    const PROJ_D = 0.998;     // 动量投影衰减（iOS 食谱）
    const HORIZON = PROJ_D / (1 - PROJ_D) / 1000;   // ≈0.499s
    const PEEK = 8;           // 每层露边（px；恒定，不随宽度变）
    const INSET = 8;          // 每层单边缩进（px；由 scaleX 换算）
    const DEPTH = 2;          // 台面上最多两层露边
    const SNAP = 0.25;        // 换一张的位移阈值（牌宽占比；动量投影后判）
    let idx = 0;        // 吸附位
    let cur = 0;        // 连续位置（牌为单位；静止时 == idx）
    let velC = 0;       // 弹簧速度（cards/s；跟手速度在释放时换算交接）
    let raf = 0;
    let drag = null;    // { x0, lx, lt, moved }
    let vPxMs = 0;      // 跟手速度（px/ms，EMA）
    let movedFlag = false;   // 拖过的手不触发牌内点击
    const dots = [];
    for (let i = 0; i < n; i++) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "deck-dot";
      b.setAttribute("aria-label", `第 ${i + 1} 张：${cards[i].dataset.theme || ""}`);
      b.addEventListener("click", () => goTo(i));
      dotsBox.appendChild(b); dots.push(b);
      cards[i].style.zIndex = n - i;
    }
    const W = () => stage.clientWidth || 1;
    function pose(i) {
      const el = cards[i];
      const d = i - cur;
      let tx = 0, ty = 0, sx = 1, op = 1, vis = true;
      if (d <= -1 || d > DEPTH + 0.2) {
        vis = false;                                   // 抽完的 / 太深的
      } else if (d < 0) {
        const u = -d;                                  // 抽走进度 0→1
        tx = -u * W();
        op = u <= 0.5 ? 1 : Math.max(0, 1 - (u - 0.5) / 0.5);
      } else {
        const dd = Math.min(d, DEPTH);                 // 台面第 d 层
        ty = PEEK * dd;
        sx = Math.max(0, 1 - 2 * INSET * dd / W());
      }
      el.style.visibility = vis ? "visible" : "hidden";
      el.style.opacity = op === 1 ? "" : op.toFixed(3);
      el.style.transform =
        `translate3d(${tx.toFixed(2)}px, ${ty.toFixed(2)}px, 0) scaleX(${sx.toFixed(5)})`;
      const top = i === idx && d === 0;
      if (el.inert !== !top) el.inert = !top;
      el.setAttribute("aria-hidden", top ? "false" : "true");
    }
    function paint() { for (let i = 0; i < n; i++) pose(i); }
    function paintDots() {
      dots.forEach((d, i) => d.setAttribute("aria-current", i === idx ? "true" : "false"));
    }
    function spring(target) {
      cancelAnimationFrame(raf);
      if (RM.matches) { cur = target; idx = target; velC = 0; raf = 0; enter(); paint(); paintDots(); return; }
      const omega = 2 * Math.PI / SPRING;
      const k = omega * omega, c = 2 * omega;     // ζ=1：临界阻尼，换牌不过冲
      let t0 = performance.now();
      const step = (t) => {
        const dt = Math.min(Math.max((t - t0) / 1000, 0.001), 1 / 30); t0 = t;
        velC += (-k * (cur - target) - c * velC) * dt;
        cur += velC * dt;
        if (Math.abs(cur - target) < 0.0015 && Math.abs(velC) < 0.02) {
          cur = target; velC = 0; idx = target; raf = 0;
          enter(); paint(); paintDots();
          return;
        }
        paint();
        raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    }
    function goTo(i) {
      i = Math.max(0, Math.min(n - 1, i));
      // 指示点点到第 4 张不该让中间两张各飞一遍（实测 >1s，破 400ms 闸）：
      // 先把位置瞬移到目标的邻位，只演一张牌的抽走/上浮，换牌时长有界。
      if (Math.abs(i - idx) > 1) {
        idx = i - Math.sign(i - idx); cur = idx; velC = 0; paint(); paintDots();
      }
      spring(i);
    }
    // 牌内元素入场 stagger（30~80ms）：只在每张牌第一次成为顶牌时播一次。
    function enter() {
      const el = cards[idx];
      if (el.dataset.staggered || RM.matches) return;
      el.dataset.staggered = "1";
      el.classList.add("deck-preenter", "deck-enter");
      // 强制 reflow 让初态落定后立即摘除 —— 不用双 rAF：落定后页面可能
      // 不再产帧（headless/后台标签），rAF 回调会饿死，牌就永远停在初态。
      void el.offsetWidth;
      el.classList.remove("deck-preenter");
      setTimeout(() => el.classList.remove("deck-enter"), 450);
    }
    stage.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      if (raf) { cancelAnimationFrame(raf); raf = 0; }   // 弹簧随时可打断
      drag = { x0: e.clientX, lx: e.clientX, lt: performance.now(), moved: false };
      vPxMs = 0;
      try { stage.setPointerCapture(e.pointerId); } catch (_) {}
      stage.classList.add("is-dragging");
    });
    stage.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const now = performance.now();
      const dx = e.clientX - drag.x0;
      if (Math.abs(dx) > 6) { drag.moved = true; movedFlag = true; }
      const instV = (e.clientX - drag.lx) / Math.max(now - drag.lt, 1);
      vPxMs = instV * 0.75 + vPxMs * 0.25;               // EMA 平滑
      drag.lx = e.clientX; drag.lt = now;
      let off = dx;                                      // 1:1 跟手（尊重抓取偏移）
      if ((idx === 0 && dx > 0) || (idx === n - 1 && dx < 0)) {
        const over = Math.abs(dx);
        off = Math.sign(dx) * over / (1 + over / 110);   // rubber-band 渐进抵抗
      }
      cur = idx - off / W();
      paint();
    });
    const release = () => {
      if (!drag) return;
      const moved = drag.moved;
      drag = null;
      stage.classList.remove("is-dragging");
      if (!moved) { cur = idx; velC = 0; paint(); return; }
      // 速度交接给弹簧；落点 = 动量投影过阈值就走一张，绝不跳两张 ——
      // 一叠牌一次只抽一张，这是牌组的语言，也让 1:1 跟手不必拖满整张牌宽。
      // 速度上限 4 cards/s ≈ 两倍于人手最猛的甩动：不夹的话一次抽动能
      // 灌进十几 cards/s，弹簧被推得大幅过冲，落位要 500ms 以上。
      velC = Math.max(-4, Math.min(4, -vPxMs * 1000 / W()));
      const proj = cur + velC * HORIZON - idx;
      const step = Math.abs(proj) > SNAP ? Math.sign(proj) : 0;
      spring(Math.max(0, Math.min(n - 1, idx + step)));
    };
    stage.addEventListener("pointerup", release);
    stage.addEventListener("pointercancel", release);
    // 拖过的手不触发牌内点击（capture 阶段吞掉）。
    stage.addEventListener("click", (e) => {
      if (movedFlag) { e.stopPropagation(); e.preventDefault(); movedFlag = false; }
    }, true);
    stage.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") { e.preventDefault(); goTo(idx - 1); }
      if (e.key === "ArrowRight") { e.preventDefault(); goTo(idx + 1); }
    });
    window.addEventListener("resize", () => { cur = idx; velC = 0; paint(); }, { passive: true });
    paint(); paintDots(); enter();
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
          + '<div><strong>风控卡不可用</strong><div class="muted" style="font-size:var(--fs-xs);margin-top:2px">'
          + '等待下次数据刷新重算</div></div></div>';
      });
      return;
    }
    const breaches = g.breaches || [], stops = g.hard_stop_watch || [];
    const n = g.breach_count || 0;
    const ICON = { single_name: '', factor_concentration: '', leveraged_exposure: '', beta: '', regime_delever: '' };
    const row = (icon, sev, detail, action) =>
      `<div class="risk-alert ${sev || 'high'}">
         <span class="icon">${icon}</span>
         <div><strong>${detail || ''}</strong>${action ? `<div class="muted" style="font-size:var(--fs-xs);margin-top:2px">→ ${action}</div>` : ''}</div>
       </div>`;
    const rows = [
      ...breaches.map(b => ({ icon: ICON[b.type] || '', severity: b.severity, detail: stripEmoji(b.detail), action: stripEmoji(b.action) })),
      ...stops.map(s => ({ icon: '', severity: s.severity || 'critical', detail: stripEmoji(s.detail), action: stripEmoji(s.action) })),
    ];
    // 严重度排序（第八次迭代）：原来把 hard stop 一律降写成 high，再按
    // 「是不是 high」排 —— 同为 high 时排序稳定，于是 6 条 breach 永远排在
    // 3 条 hard stop 前面，牌上那三个槽位只看得到限额比例，而「已经跌穿
    // -18% 硬止损线」的三只（数据里本来就是 critical）从不上首屏。槽位按
    // 数据自己的严重度给，不按数组下标给。
    const SEV_RANK = { critical: 3, high: 2, medium: 1 };
    const compactRows = rows.slice().sort((a, b) =>
      (SEV_RANK[b.severity] || 0) - (SEV_RANK[a.severity] || 0));
    targets.forEach(({ countEl, dirEl, listEl, compact }) => {
      // 「9 触发」红字是判定卡里最后一个裸读数：数量改用点阵计数表达
      // （一眼扫出严重度，不用读数），精确值退到 aria-label/title。槽位
      // 固定 10 个 —— 图形宽度是构图的函数，不是 breach_count 的函数
      // （CLS 预留判据）；超容收进 +n，轨宽不变。
      const CAP = 10;
      const dots = [];
      for (let i = 0; i < CAP; i++)
        dots.push(`<i class="gt-dot${i < Math.min(n, CAP) ? " on" : ""}"></i>`);
      if (n > CAP) dots.push(`<i class="gt-more">+${n - CAP}</i>`);
      countEl.innerHTML = n
        ? `<span class="gt-tally" role="img" aria-label="${n} 项硬闸触发中"`
          + ` title="${n} 项触发">${dots.join("")}</span>`
        : '无';
      countEl.style.color = n ? '' : 'var(--positive)';
      if (dirEl) dirEl.textContent = compact
        ? stripEmoji(g.directive)
        : stripEmoji([g.directive, g.reentry_rule].filter(Boolean).join(' '));
      const visibleRows = compact ? compactRows.slice(0, 3) : rows;
      const html = visibleRows.map(r => row(r.icon, r.severity, r.detail, compact ? "" : r.action)).join('');
      // 牌上只有三个槽位，9 条里剩下的 6 条原来是无声消失的（表头点阵是
      // 严重度密度，读不出「还有几条没列」）。补一行尾注说清被折叠的量。
      const hidden = compact ? Math.max(0, compactRows.length - visibleRows.length) : 0;
      const tail = hidden
        ? `<div class="overview-gates-more">另有 ${hidden} 项未列出</div>` : '';
      listEl.innerHTML = (html && html + tail)
        || '<div class="muted" style="font-size:var(--fs-sm)">仓位/单因子/杠杆均在阈值内</div>';
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
    // 回本状态分档：净值在成本线上方（含打平）之后，整套「回本需涨」的话术
    // 都要换方向 —— 需涨变负数不是「要跌」，是已经在上面了。2026-08-24 起
    // 持仓真实越线（avg_cost 3.3538 / nav 3.3774），下面所有回本表述按此分档。
    const aboveWater = g.breakeven_upside_pct != null && g.breakeven_upside_pct <= 0;

    document.getElementById('gold-sub').textContent = `${g.fund_code} · ${g.fund_name}`;

    // hero: 现值 + 盈亏
    document.getElementById('gold-hero').innerHTML =
      `<div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin:2px 0 12px">
         <span style="font-size:var(--fs-xxl);font-weight:700">¥${num(g.current_value)}</span>
         <span style="font-size:var(--fs-lg);font-weight:700;color:${pnlColor}">${sign}${num(g.pnl_percent, 2)}%</span>
         <span style="font-size:var(--fs-md);color:${pnlColor}">${(g.pnl_abs >= 0 ? '+' : '')}¥${num(g.pnl_abs)}</span>
       </div>`;

    // stats grid
    const navChg = g.nav_change_pct;
    const navChgStr = navChg == null ? '' :
      ` <span style="color:${navChg >= 0 ? 'var(--positive)' : 'var(--negative)'};font-size:var(--fs-xs)">${navChg >= 0 ? '+' : ''}${navChg.toFixed(2)}%</span>`;
    const cell = (label, val) => `<div style="flex:1 1 30%;min-width:90px;margin:5px 0">
        <div class="muted" style="font-size:var(--fs-micro);text-transform:none;letter-spacing:0">${label}</div>
        <div style="font-size:var(--fs-lg);font-weight:700;margin-top:1px">${val}</div></div>`;
    document.getElementById('gold-stats').innerHTML =
      `<div style="display:flex;flex-wrap:wrap;gap:2px 8px;padding:8px 0;border-top:1px solid var(--border,#2a2a2a)">
        ${cell('累计投入', '¥' + num(g.principal_effective != null ? g.principal_effective : g.principal_invested))}
        ${cell('平均成本', num(g.avg_cost, 4))}
        ${cell('当前净值', num(g.nav, 4) + navChgStr)}
        ${aboveWater
          ? cell('成本线上方', `<span style="color:var(--positive)">+${num(-(g.breakeven_upside_pct || 0), 1)}%</span>`)
          : cell('回本需涨', `<span style="color:var(--warning)">${g.breakeven_upside_pct == null ? DASH : '+' + num(g.breakeven_upside_pct, 1) + '%'}</span>`)}
        ${cell('已投', `${g.days_invested ?? DASH} 交易日`)}
        ${cell('约定投', `${g.installments_est ?? DASH} 笔 ×¥${num(g.daily_amount)}`)}
      </div>`;

    // 国内真基准：000217 跟随上金所国内现货金，这是用户判断回本的主口径。
    const dg = g.domestic_gold;
    const goldDomestic = document.getElementById('gold-domestic');
    if (goldDomestic) {
      if (!dg || dg.price_cny_g == null) {
        goldDomestic.innerHTML =
          `<div role="status" style="margin:12px 0 4px;padding:10px 12px;border-radius:6px;border:1px solid color-mix(in srgb,var(--warning) 25%,transparent);color:var(--warning);font-size:var(--fs-xs)">
             上金所 Au99.99 暂无有效行情
           </div>`;
      } else {
        const dchg = dg.change_pct;
        const dcolor = dchg == null ? 'var(--neutral)' : (dchg >= 0 ? 'var(--positive)' : 'var(--negative)');
        const retained = dg.quote_status === 'retained';
        // 国内口径自己的回本分档（与基金口径同号，但各自算，不借用）。
        const dgAbove = dg.breakeven_upside_pct != null && dg.breakeven_upside_pct <= 0;
        const dgBeColor = dgAbove ? 'var(--positive)' : 'var(--warning)';
        const dgBeTxt = dgAbove
          ? `成本线上方 <b style="color:${dgBeColor}">${num(-(dg.breakeven_upside_pct || 0), 2)}%</b>`
          : `距回本 <b style="color:${dgBeColor}">${dg.breakeven_upside_pct == null ? DASH : '+' + num(dg.breakeven_upside_pct, 2) + '%'}</b>`;
        goldDomestic.innerHTML =
          `<div style="margin:12px 0 4px;padding:12px;border-radius:6px;background:color-mix(in srgb,var(--positive) 6%,transparent);border:1px solid color-mix(in srgb,var(--positive) 24%,transparent)">
             <div class="muted" style="font-size:var(--fs-micro);text-transform:none;letter-spacing:0">国内基准 · 上金所 Au99.99</div>
             <div style="display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:end;gap:10px;margin-top:7px">
               <div><div class="muted" style="font-size:var(--fs-micro)">当前金价</div><div style="font-size:var(--fs-xl);font-weight:700;white-space:nowrap">¥${num(dg.price_cny_g, 2)}<span style="font-size:var(--fs-xs);color:var(--muted,#999)">/克</span></div></div>
               <div class="muted" aria-hidden="true" style="padding-bottom:4px">→</div>
               <div><div class="muted" style="font-size:var(--fs-micro)">我的回本价</div><div style="font-size:var(--fs-xl);font-weight:700;color:${dgBeColor};white-space:nowrap">¥${num(dg.breakeven_cny_g, 2)}<span style="font-size:var(--fs-xs);color:var(--muted,#999)">/克</span></div></div>
             </div>
             <div class="muted" style="font-size:var(--fs-xs);margin-top:7px;text-transform:none;letter-spacing:0">
               ${dgBeTxt}
               ${dchg == null ? '' : ` · 当日 <b style="color:${dcolor}">${dchg >= 0 ? '+' : ''}${num(dchg, 2)}%</b>`}
               ${dg.low_cny_g != null && dg.high_cny_g != null ? ` · 日内 ¥${num(dg.low_cny_g, 0)}~${num(dg.high_cny_g, 0)}` : ''}
             </div>
             <div class="muted" style="font-size:var(--fs-micro);margin-top:4px;text-transform:none;letter-spacing:0">
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
        const xchgStr = xchg == null ? '' : ` · 当日 <span style="color:${xcolor};font-size:var(--fs-xs)">${xchg >= 0 ? '+' : ''}${Number(xchg).toFixed(2)}%</span>`;
        const fundBeXau = ld.fund_breakeven_usd_oz != null
          ? ld.fund_breakeven_usd_oz
          : (g.nav ? ld.xau_usd * g.avg_cost / g.nav : null);
        const fundBePct = ld.fund_breakeven_upside_pct != null
          ? ld.fund_breakeven_upside_pct : g.breakeven_upside_pct;
        const fundAbove = fundBePct != null && fundBePct <= 0;
        const fundBeColor = fundAbove ? 'var(--positive)' : 'var(--warning)';
        const fundBeTxt = fundAbove
          ? `成本线上方 <b style="color:${fundBeColor}">${num(-fundBePct, 2)}%</b>`
          : `距回本 <b style="color:${fundBeColor}">${fundBePct == null ? DASH : '+' + num(fundBePct, 2) + '%'}</b>`;
        // 伦敦金保留为国际辅助口径，显式区分现价与真基金回本映射。
        let html =
          `<div style="margin:12px 0 4px;padding:8px 12px;border-radius:6px;background:color-mix(in srgb,var(--warning) 7%,transparent);border:1px solid color-mix(in srgb,var(--warning) 25%,transparent)">
             <div class="muted" style="font-size:var(--fs-micro);text-transform:none;letter-spacing:0">国际辅助 · 伦敦金 XAU/USD</div>
             <div style="display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:end;gap:10px;margin-top:7px">
               <div><div class="muted" style="font-size:var(--fs-micro)">当前金价</div><div style="font-size:var(--fs-xl);font-weight:700;white-space:nowrap">$${num(ld.xau_usd, 2)}<span style="font-size:var(--fs-xs);color:var(--muted,#999)">/oz</span></div></div>
               <div class="muted" aria-hidden="true" style="padding-bottom:4px">→</div>
               <div><div class="muted" style="font-size:var(--fs-micro)">按当前汇率回本</div><div style="font-size:var(--fs-xl);font-weight:700;color:${fundBeColor};white-space:nowrap">$${num(fundBeXau, 2)}<span style="font-size:var(--fs-xs);color:var(--muted,#999)">/oz</span></div></div>
             </div>
             <div class="muted" style="font-size:var(--fs-xs);margin-top:5px;text-transform:none;letter-spacing:0">
               ${fundBeTxt}${xchgStr}
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
        html += `<div class="muted" style="font-size:var(--fs-micro);margin-top:4px;text-transform:none;letter-spacing:0">
          历史源 ${escapeHtml(histNames[histSource.name] || histSource.name || '未知')} · ${num(histSource.points || 0)} 点
        </div>`;
        if (ld.hist_advisory) {
          html += `<div role="status" style="font-size:var(--fs-micro);color:var(--warning);margin-top:4px;text-transform:none;letter-spacing:0">
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
               <summary class="muted" style="font-size:var(--fs-micro);text-transform:none;letter-spacing:0;cursor:pointer">模拟对照 · 若每个基金交易日直接买伦敦金</summary>
               <div style="margin-top:6px">
               <div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-top:2px">
                 <span style="font-size:var(--fs-lg);font-weight:700">$${num(de.avg_cost_usd_oz, 2)}<span style="font-size:var(--fs-xs);font-weight:600;color:var(--muted,#999)">/oz</span></span>
                 <span style="font-size:var(--fs-sm);font-weight:700;color:var(--muted,#999)">¥${num(de.avg_cost_cny_g, 2)}/克</span>
               </div>
               <div class="muted" style="font-size:var(--fs-xs);margin-top:3px;text-transform:none;letter-spacing:0">
                 现货 <b style="color:var(--text,#eee)">$${num(de.spot_usd_oz, 2)}</b>/oz · 回本需涨 <b style="color:${beColor}">${de.breakeven_upside_pct >= 0 ? '+' : ''}${num(de.breakeven_upside_pct, 2)}%</b>
                 ${de.current_value_cny != null ? `· 对应现值 <b style="color:${dColor}">¥${num(de.current_value_cny)}</b> (${de.pnl_pct >= 0 ? '+' : ''}${num(de.pnl_pct, 2)}%)` : ''}
               </div>
             </div>`;
          // 摊薄轨迹：继续同额定投伦敦金 → 均成本 $/oz 移动方向由数据说话
          //（现货在均价下方时摊薄下移、上方时反而上抬 —— 回本后这句文案
          // 曾固定写「下移」，与它自己表格里的数字打架）。
          const lproj = (de.projection || []).filter(p => p && p.avg_cost_usd_oz != null);
          if (lproj.length) {
            const MON = { 20: '+1月', 40: '+2月', 60: '+3月', 120: '+半年', 250: '+1年' };
            const lDir = de.avg_cost_usd_oz != null && lproj[lproj.length - 1].avg_cost_usd_oz >= de.avg_cost_usd_oz ? '上移' : '下移';
            const deAbove = de.breakeven_upside_pct != null && de.breakeven_upside_pct <= 0;
            const lrows = lproj.map(p =>
              `<tr><td style="padding:4px 8px">${MON[p.days] || ('+' + p.days + '日')}</td>
                <td style="padding:4px 8px;text-align:right">$${num(p.avg_cost_usd_oz, 0)}</td>
                <td style="padding:4px 8px;text-align:right;color:${deAbove ? 'var(--text-secondary)' : 'var(--positive)'}">${p.breakeven_upside_pct == null ? DASH : (p.breakeven_upside_pct >= 0 ? '+' : '') + num(p.breakeven_upside_pct, 1) + '%'}</td></tr>`).join('');
            html +=
              `<div class="muted" style="font-size:var(--fs-micro);margin:8px 0 2px;text-transform:none;letter-spacing:0">若金价/汇率不动、继续每日定投 → 持金成本 $/oz ${lDir}</div>
               <table style="width:100%;font-size:var(--fs-sm);border-collapse:collapse">
                 <tr class="muted" style="font-size:var(--fs-micro)"><th scope="col" style="padding:4px 8px;text-align:left;font-weight:inherit">继续</th><th scope="col" style="padding:4px 8px;text-align:right;font-weight:inherit">均成本/oz</th><th scope="col" style="padding:4px 8px;text-align:right;font-weight:inherit">距成本线</th></tr>
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
             <div class="muted" style="font-size:var(--fs-micro);display:flex;justify-content:space-between;text-transform:none;letter-spacing:0;margin-top:1px">
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
      // 成本线的颜色跟着回本状态走：在上方=要守的线（amber），越线之后=
      // 已经站上去的参照（绿）。线本身语义不变，只换情绪。
      const costColor = aboveWater ? 'var(--positive)' : 'var(--warning)';
      sp.innerHTML =
        `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="none" style="margin-top:4px">
          ${avgY != null ? `<line x1="0" y1="${avgY.toFixed(1)}" x2="${W}" y2="${avgY.toFixed(1)}" stroke="${costColor}" stroke-width="1" stroke-dasharray="3 2" opacity="0.7"/>` : ''}
          <polyline points="${pts}" fill="none" stroke="var(--warning)" stroke-width="1.6"/>
          <circle cx="${x(startIdx).toFixed(1)}" cy="${y(hist[startIdx][1]).toFixed(1)}" r="2.6" fill="var(--accent)"/>
          <circle cx="${x(hist.length - 1).toFixed(1)}" cy="${y(lastV).toFixed(1)}" r="2.6" fill="${pnlColor}"/>
        </svg>
        <div class="muted" style="font-size:var(--fs-micro);display:flex;justify-content:space-between;text-transform:none;letter-spacing:0">
          <span style="color:var(--accent)">${hist[startIdx][0]} 起投 ${num(hist[startIdx][1], 3)}</span>
          <span style="color:${costColor}">成本线 ${num(avg, 3)}</span>
          <span>区间 ${num(lo, 3)}~${num(hi, 3)}</span>
        </div>`;
    } else { sp.innerHTML = ''; }

    // 定投摊薄预测 (假设净值不动, 继续投 → 成本线移动方向由数据说话：
    // 净值在成本线下方时定投把它往下拽，越线之后同样的机制反过来把它
    // 抬高 —— 文案跟着数字走，不再固定写「下移」。)
    const proj = g.projection || [];
    if (proj.length) {
      const MONTH = { 20: '+1月', 40: '+2月', 60: '+3月', 120: '+半年', 250: '+1年' };
      const projDir = g.avg_cost != null && proj[proj.length - 1].avg_cost >= g.avg_cost ? '上移、安全垫收窄' : '下移';
      const rows = proj.map(p =>
        `<tr><td style="padding:4px 8px">${MONTH[p.days] || ('+' + p.days + '日')}</td>
          <td style="padding:4px 8px;text-align:right">${num(p.avg_cost, 3)}</td>
          <td style="padding:4px 8px;text-align:right;color:${aboveWater ? 'var(--text-secondary)' : 'var(--positive)'}">${p.breakeven_upside_pct == null ? DASH : (p.breakeven_upside_pct >= 0 ? '+' : '') + num(p.breakeven_upside_pct, 1) + '%'}</td></tr>`).join('');
      document.getElementById('gold-proj').innerHTML =
        `<div class="muted" style="font-size:var(--fs-micro);margin:8px 0 2px;text-transform:none;letter-spacing:0">若净值原地不动、继续每日定投 → 成本线${projDir}</div>
         <table style="width:100%;font-size:var(--fs-sm);border-collapse:collapse">
           <tr class="muted" style="font-size:var(--fs-micro)"><th scope="col" style="padding:4px 8px;text-align:left;font-weight:inherit">继续</th><th scope="col" style="padding:4px 8px;text-align:right;font-weight:inherit">平均成本</th><th scope="col" style="padding:4px 8px;text-align:right;font-weight:inherit">距成本线</th></tr>
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
    // 判词句里的数字是这句话的骨架。仓库字规是「mono 只用于数字与代码」，
    // 但这句话此前整句 sans，数字埋在 prose 里没有排版层级 —— 层级靠字族
    // 切换，不靠放大加重（大字报的根子就是拿字号当层级）。escapeHtml 之
    // 后再包：正则只命中 [+-0-9.%]，包出来的 span 无注入面。
    const verdictNums = s => escapeHtml(s)
      .replace(/[+-]?\d+(?:\.\d+)?%/g, m => `<span class="sb-n">${m}</span>`);
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
      // 数据已经渲染过一轮了，所以这是「今天没有盘中横幅」，不是「还没加载」。
      // 收掉高度，别在判定卡标题下留一条空带。
      targets.forEach(({ banner }) => {
        banner.classList.remove("is-pending");
        banner.classList.add("is-empty");
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
      banner.classList.remove("is-empty");
      banner.removeAttribute("aria-hidden");
      if (text) text.innerHTML = verdictNums(txt);
      if (time) time.textContent = t;
    });
  }
