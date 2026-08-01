  // =========================================================
  // Tab switching
  // =========================================================
  // Tab order follows the button order in the tablist.
  const TAB_ORDER = Array.from(document.querySelectorAll(".tab-btn")).map(b => b.dataset.tab);

  const pager = document.getElementById("pager");
  const DESKTOP_MQ = window.matchMedia("(min-width: 1024px)");
  // The CSS breakpoint is the source of truth; matchMedia avoids a forced style
  // calculation after setActiveButton() has just changed panel classes.
  const pagerLive = () => !!pager && !DESKTOP_MQ.matches;

  // Respect OS-level reduced-motion: swap every smooth scroll for an instant one.
  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const SCROLL_BEHAVIOR = REDUCED_MOTION ? "auto" : "smooth";

  // Detail-tab desk rail: collapsed is the default at every breakpoint, with
  // the user's explicit disclosure choice persisted. Hero hides it because the
  // command center already promotes the same canonical KPIs.
  const DESK_RAIL_KEY = "clawock:desk-rail";
  const deskRail = document.getElementById("desk-rail");
  const deskRailToggle = document.getElementById("desk-rail-toggle");
  const deskRailExpanded = document.getElementById("desk-rail-expanded");
  function setDeskRailExpanded(open, persist = false) {
    if (!deskRail || !deskRailToggle || !deskRailExpanded) return;
    deskRail.classList.toggle("is-collapsed", !open);
    deskRailToggle.setAttribute("aria-expanded", open ? "true" : "false");
    deskRailExpanded.hidden = !open;
    if (persist) {
      try { localStorage.setItem(DESK_RAIL_KEY, open ? "open" : "closed"); } catch (e) {}
    }
  }
  function setDeskRailTab(t) {
    if (deskRail) deskRail.classList.toggle("is-overview", t === TAB_ORDER[0]);
  }
  let deskRailOpen = false;
  try { deskRailOpen = localStorage.getItem(DESK_RAIL_KEY) === "open"; } catch (e) {}
  setDeskRailExpanded(deskRailOpen);
  if (deskRailToggle) {
    deskRailToggle.addEventListener("click", () =>
      setDeskRailExpanded(deskRailToggle.getAttribute("aria-expanded") !== "true", true));
  }

  // Reflect the active tab in the button bar + a11y + desktop CSS. Does NOT move
  // the pager (the scroll position is the source of truth on mobile).
  function setActiveButton(t) {
    if (!TAB_ORDER.includes(t)) return;
    setDeskRailTab(t);
    document.querySelectorAll(".tab-btn").forEach(b => {
      const on = b.dataset.tab === t;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on);
    });
    document.querySelectorAll(".panel").forEach(p => {
      p.classList.toggle("active", p.dataset.panel === t);
    });
    if (DATA) {
      // Activation is the consumer boundary: mapped sidecars load first, then
      // this tab alone renders. Rapid swipes share in-flight fetches and the last
      // visible tab wins, so no hidden panel receives runtime DOM.
      activateTabData(t);
    }
    const btn = document.querySelector(`.tab-btn[data-tab="${t}"]`);
    if (btn) btn.scrollIntoView({ block: "nearest", inline: "center", behavior: SCROLL_BEHAVIOR });
    // Deep-link: keep the URL hash in sync (replaceState → no history spam while
    // swiping). Refresh / bookmark / shared link then lands on the same tab
    // instead of always resetting to Hero. Hero itself keeps a clean URL.
    const want = t === TAB_ORDER[0] ? "" : "#" + t;
    if ((location.hash || "") !== want) {
      history.replaceState(null, "", want || location.pathname + location.search);
    }
  }

  function currentTab() {
    if (pagerLive()) {
      const i = Math.round(pager.scrollLeft / (pager.clientWidth || 1));
      return TAB_ORDER[Math.max(0, Math.min(TAB_ORDER.length - 1, i))];
    }
    const active = document.querySelector(".tab-btn.active");
    return active ? active.dataset.tab : TAB_ORDER[0];
  }

  // Native scroll-snap does the gesture, preview, momentum & easing for free.
  // We just drive scrollLeft for button/keyboard nav and read it back for the indicator.
  function goToTab(t, smooth = true) {
    if (!TAB_ORDER.includes(t)) return false;
    const idx = TAB_ORDER.indexOf(t);
    if (pagerLive()) {
      pager.scrollTo({ left: idx * pager.clientWidth, behavior: smooth ? SCROLL_BEHAVIOR : "auto" });
    }
    setActiveButton(t);          // desktop / immediate highlight; scroll listener re-confirms
    return true;
  }
  function shiftTab(step) {
    const idx = TAB_ORDER.indexOf(currentTab());
    const next = idx + step;
    if (next < 0 || next >= TAB_ORDER.length) return false;
    return goToTab(TAB_ORDER[next]);
  }

  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => goToTab(btn.dataset.tab));
  });

  // Sync the active-tab indicator to the live scroll position (rAF-throttled).
  // On settle, nudge ECharts in the now-visible page to resize.
  if (pager) {
    let raf = 0, settleTimer = 0, lastIdx = -1;
    pager.addEventListener("scroll", () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const idx = Math.round(pager.scrollLeft / (pager.clientWidth || 1));
        if (idx !== lastIdx) {
          lastIdx = idx;
          const t = TAB_ORDER[Math.max(0, Math.min(TAB_ORDER.length - 1, idx))];
          setActiveButton(t);
        }
        clearTimeout(settleTimer);
        settleTimer = setTimeout(() => window.dispatchEvent(new Event("resize")), 120);
      });
    }, { passive: true });

    // Keep the current page aligned across orientation / viewport changes.
    let rzTimer = 0;
    window.addEventListener("resize", () => {
      if (!pagerLive()) return;
      clearTimeout(rzTimer);
      rzTimer = setTimeout(() => {
        const idx = TAB_ORDER.indexOf(currentTab());
        pager.scrollTo({ left: idx * pager.clientWidth, behavior: "auto" });
      }, 150);
    });
  }

  // Keyboard arrows mirror the swipe.
  document.addEventListener("keydown", e => {
    if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    if (e.key === "ArrowLeft") shiftTab(-1);
    else if (e.key === "ArrowRight") shiftTab(1);
  });

  // back-compat alias (older call sites used activateTab)
  function activateTab(t) { return goToTab(t); }

  // Deep-link IN: land on the tab named in the URL hash (e.g. /#gold), and follow
  // browser back/forward across tab switches (hashchange fires on those since we
  // only write the hash via replaceState while swiping).
  function tabFromHash() {
    const t = (location.hash || "").slice(1);
    return TAB_ORDER.includes(t) ? t : null;
  }
  window.addEventListener("hashchange", () => {
    const t = tabFromHash();
    if (t && t !== currentTab()) goToTab(t, false);
  });

  DESKTOP_MQ.addEventListener("change", () => { if (DATA) ensureVisibleCharts(); });

  const shadowPortfolioToggle = document.getElementById("shadow-portfolio-toggle");
  if (shadowPortfolioToggle) {
    shadowPortfolioToggle.addEventListener("click", () => {
      setShadowPortfolioExpanded(shadowPortfolioToggle.getAttribute("aria-expanded") !== "true");
    });
  }

  // Instant re-theme on OS dark/light flip (phones auto-switch at sunset): CSS vars
  // flip immediately but cached ECharts instances keep the old palette until the
  // next 60s poll. Dispose them so render() re-inits with the new theme colors.
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    invalidateThemeCSS();
    Object.keys(charts).forEach(k => {
      try { if (charts[k]) charts[k].dispose(); } catch (e) {}
      charts[k] = null;
    });
    if (DATA) render();
  });

  document.addEventListener("click", (e) => {
    const b = e.target.closest(".mkt-seg-btn");
    if (b && b.dataset.mkt) setMarketView(b.dataset.mkt);
    const jump = e.target.closest("[data-jump-tab]");
    if (jump && jump.dataset.jumpTab) goToTab(jump.dataset.jumpTab);
  });

  // =========================================================
  // Data load
  // =========================================================
  // Tracks the last `generated_at` we successfully rendered so we can tell the
  // user whether a refresh actually pulled new data vs. they got the same JSON.
  let LAST_LOADED_AT = null;
  let AUTO_REFRESH_TIMER = null;
  const SIDECAR_TAB = {
    macro: "market", sentiment: "market", influencer_feed: "market",
    us_news_digest: "market", em_news: "market",
    decision_audit: "reflect", shadow_portfolio: "drill",
    brief_projection: "drill",
  };
  const SIDECAR_STATE = new Map();
  let TAB_ACTIVATION_VERSION = 0;
  let DETAIL_RENDERERS_PROMISE = null;

  function _loadTabRuntime(t) {
    if (t === "hero" || hasTabRenderer(t)) return Promise.resolve();
    if (DETAIL_RENDERERS_PROMISE) return DETAIL_RENDERERS_PROMISE;
    DETAIL_RENDERERS_PROMISE = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "assets/js/dashboard.render.js";
      script.async = true;
      script.onload = () => hasTabRenderer(t)
        ? resolve()
        : reject(new Error("detail renderer registration failed"));
      script.onerror = () => reject(new Error("detail renderer load failed"));
      document.head.appendChild(script);
    }).catch(error => {
      DETAIL_RENDERERS_PROMISE = null;
      throw error;
    });
    return DETAIL_RENDERERS_PROMISE;
  }

  function _sidecarsForTab(t) {
    return Object.keys(SIDECAR_TAB).filter(k => SIDECAR_TAB[k] === t);
  }

  function _sidecarState(k) {
    if (!SIDECAR_STATE.has(k)) {
      SIDECAR_STATE.set(k, {
        value: null, serialized: null, ready: false, stale: true, inFlight: null,
      });
    }
    return SIDECAR_STATE.get(k);
  }

  function _applySidecars(target) {
    Object.keys(SIDECAR_TAB).forEach(k => {
      const state = _sidecarState(k);
      target[k] = state.ready ? state.value : null;
    });
  }

  function _markLoadedSidecarsStale() {
    SIDECAR_STATE.forEach(state => {
      // An in-flight request is already revalidating this consumer. Do not make
      // a second request race it merely because dashboard.json landed first.
      if (state.ready && !state.inFlight) state.stale = true;
    });
  }

  function _fetchSidecar(k, triggeredByUser, requestStamp) {
    const state = _sidecarState(k);
    if (state.inFlight) return state.inFlight;
    if (state.ready && !state.stale) return Promise.resolve(false);

    const bust = triggeredByUser ? "?t=" + requestStamp : "";
    state.inFlight = fetch("assets/data/" + k + ".json" + bust, {
      cache: triggeredByUser ? "no-store" : "no-cache",
    }).then(async response => response.ok ? await response.json() : null)
      .catch(() => null)
      .then(value => {
        // Sidecars publish independently from dashboard.json. Revalidate them,
        // but do not replay a tab's DOM when its serialized value is identical
        // to the value it already rendered.
        const serialized = JSON.stringify(value);
        const changed = !state.ready || serialized !== state.serialized;
        state.value = value;
        state.serialized = serialized;
        state.ready = true;
        state.stale = false;
        return changed;
      })
      .finally(() => { state.inFlight = null; });
    return state.inFlight;
  }

  async function _loadTabSidecars(t, triggeredByUser = false) {
    const keys = _sidecarsForTab(t);
    if (!keys.length) return false;
    const requestStamp = Date.now();
    const changed = await Promise.all(
      keys.map(k => _fetchSidecar(k, triggeredByUser, requestStamp)));
    return changed.some(Boolean);
  }

  function _paintActivatedTab(t) {
    if (!DATA || currentTab() !== t) return;
    renderTab(t);
    ensureTabCharts(t);
    const panel = document.querySelector(`.panel[data-panel="${t}"]`);
    if (panel) panel.removeAttribute("aria-busy");
    // Desktop shows one panel at a time. Let its layout settle before resizing
    // an existing chart; mobile's scroll-settle listener owns the same nudge.
    if (!pagerLive()) requestAnimationFrame(() =>
      requestAnimationFrame(() => window.dispatchEvent(new Event("resize"))));
  }

  function activateTabData(t) {
    const version = ++TAB_ACTIVATION_VERSION;
    const keys = _sidecarsForTab(t);
    const needsFetch = keys.some(k => {
      const state = _sidecarState(k);
      return !state.ready || state.stale || state.inFlight;
    });
    const panel = document.querySelector(`.panel[data-panel="${t}"]`);
    const needsRuntime = !hasTabRenderer(t);
    if ((needsFetch || needsRuntime) && panel) panel.setAttribute("aria-busy", "true");
    if (!needsFetch && !needsRuntime) {
      _paintActivatedTab(t);
      return;
    }
    Promise.all([_loadTabRuntime(t), _loadTabSidecars(t)])
      .then(() => {
        if (version !== TAB_ACTIVATION_VERSION || !DATA || currentTab() !== t) return;
        _applySidecars(DATA);
        _paintActivatedTab(t);
      })
      .catch(error => {
        console.error(error);
        if (version === TAB_ACTIVATION_VERSION && panel) panel.removeAttribute("aria-busy");
      });
  }

  function _formatRelative(iso) {
    if (!iso) return "—";
    const t = new Date(iso);
    if (isNaN(t)) return iso;
    const secs = Math.max(0, Math.round((Date.now() - t.getTime()) / 1000));
    if (secs < 60) return "刚刚";
    if (secs < 3600) return `${Math.round(secs / 60)} 分钟前`;
    if (secs < 86400) return `${Math.round(secs / 3600)} 小时前`;
    return `${Math.round(secs / 86400)} 天前`;
  }

  function _updateAgeLabel() {
    const el = document.getElementById("last-updated");
    if (!el || !DATA) return;
    const gen = DATA.generated_at || DATA.last_updated;
    const rel = _formatRelative(gen);
    // Two-line form: relative time + absolute timestamp tail
    const absTail = gen && gen.length > 16 ? gen.slice(11, 16) + " UTC" : (gen || "");
    el.textContent = `· 生成于 ${rel} · ${absTail}`;
    el.title = gen || "";
  }

  async function loadData(triggeredByUser = false) {
    const btn = document.getElementById("refresh-btn");
    if (btn) btn.classList.add("is-loading");
    if (triggeredByUser && btn) btn.setAttribute("disabled", "true");
    try {
      // Auto-polls revalidate via ETag/Last-Modified (`no-cache` → conditional GET,
      // 304 when unchanged = headers-only on mobile data instead of ~113KB/min).
      // A user-initiated refresh keeps the old cache-buster so it ALWAYS punches
      // through stale intermediary caches (WeChat webview / carrier proxies).
      const url = triggeredByUser
        ? "assets/data/dashboard.json?t=" + Date.now()
        : "assets/data/dashboard.json";
      const res = await fetch(url, { cache: triggeredByUser ? "no-store" : "no-cache" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const json = await res.json();
      // Tab activation is the only sidecar consumer boundary. A normal Hero
      // landing therefore makes no sidecar requests; a deep link waits for its
      // mapped dependencies before the first render. Later polls retain the
      // last good inactive-tab values, mark them stale, and revalidate only the
      // active tab. The next activation refreshes any inactive stale tab.
      let landing = currentTab();
      const firstLoad = DATA == null;
      if (firstLoad) {
        // A user can click/swipe while dashboard.json is in flight. Keep the
        // first paint complete for whichever tab is actually visible when its
        // dependencies finish, rather than rendering a partial new landing tab.
        do {
          landing = currentTab();
          await Promise.all([
            _loadTabRuntime(landing),
            _loadTabSidecars(landing, triggeredByUser),
          ]);
        } while (currentTab() !== landing);
      } else {
        _markLoadedSidecarsStale();
      }
      const newAt = json.generated_at;
      const hasNew = newAt && newAt !== LAST_LOADED_AT;
      if (firstLoad || hasNew) {
        _applySidecars(json);
        DATA = json;
        render();
      }
      // An unchanged generation still updates relative-time copy and refresh
      // feedback, but must not replace DATA or replay the same DOM every minute.
      _updateAgeLabel();
      if (!firstLoad && _sidecarsForTab(landing).length) {
        const expectedData = DATA;
        _loadTabSidecars(landing, triggeredByUser).then(sidecarsChanged => {
          if (!sidecarsChanged || DATA !== expectedData || currentTab() !== landing) return;
          _applySidecars(DATA);
          refreshTab(landing);
        });
      }
      if (btn) {
        btn.classList.remove("is-loading");
        if (triggeredByUser) {
          btn.removeAttribute("disabled");
          btn.classList.add(hasNew ? "fresh-flash" : "ok-flash");
          const lbl = btn.querySelector(".lbl");
          if (lbl) {
            const prev = lbl.textContent;
            lbl.textContent = hasNew ? "已更新 ✓" : "已是最新";
            setTimeout(() => {
              lbl.textContent = prev;
              btn.classList.remove("fresh-flash", "ok-flash");
            }, 1800);
          }
        } else if (hasNew) {
          // Quiet auto-refresh: just a soft border tint, no label flicker
          btn.classList.add("fresh-flash");
          setTimeout(() => btn.classList.remove("fresh-flash"), 1500);
        }
      }
      LAST_LOADED_AT = newAt;
    } catch (e) {
      console.error("Failed to load dashboard.json:", e);
      document.getElementById("last-updated").textContent = "load failed";
      if (btn) {
        btn.classList.remove("is-loading");
        btn.removeAttribute("disabled");
      }
    }
  }

  function _scheduleAutoRefresh() {
    // Re-pull dashboard.json every 60 s in the background so the user doesn't
    // have to keep clicking. Pauses while the tab is hidden to be polite.
    if (AUTO_REFRESH_TIMER) clearInterval(AUTO_REFRESH_TIMER);
    AUTO_REFRESH_TIMER = setInterval(() => {
      if (document.visibilityState !== "hidden") loadData(false);
    }, 60000);
    // Refresh "age" label more often than the data — keeps "X 分钟前" honest
    setInterval(_updateAgeLabel, 15000);
  }

  // Fold/unfold on header tap; remember per-card choice across visits.
  document.querySelectorAll(".card.fold-m").forEach(card => {
    const id = "fold:" + (card.dataset.foldId || "");
    try { if (localStorage.getItem(id) === "open") card.classList.add("open"); } catch (e) {}
    const h = card.querySelector(":scope > h3");
    if (h) h.addEventListener("click", () => {
      const open = card.classList.toggle("open");
      try { localStorage.setItem(id, open ? "open" : "closed"); } catch (e) {}
    });
  });

  // =========================================================
  // Wire up resize (theme changes are handled by the cache/dispose listener above)
  // =========================================================
  window.addEventListener("resize", () => {
    Object.values(charts).forEach(c => c && c.resize());
  });
  document.getElementById("refresh-btn").addEventListener("click", () => loadData(true));

  // =========================================================
  // Boot — text and native Hero chart paint without waiting for ECharts
  // =========================================================
  function boot() {
    // Hero uses a lightweight native Canvas. The ECharts bundle is fetched only
    // after a user enters a detail tab that owns an analytical chart.
    // Land on the deep-linked tab BEFORE first paint of data (instant, no animation).
    const t0 = tabFromHash();
    if (t0) goToTab(t0, false);
    loadData();
    _scheduleAutoRefresh();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
