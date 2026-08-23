  // =========================================================
  // Utilities — null-safe formatters
  // =========================================================
  const DASH = "—"; // em-dash for missing values

  const fmtMoney = (v, ccy) => {
    if (v == null || !isFinite(v)) return DASH;
    const sym = ccy === "USD" ? "$" : ccy === "HKD" ? "HK$" : "";
    const n = Math.abs(v) >= 1000
      ? v.toLocaleString("en-US", { maximumFractionDigits: 0 })
      : v.toLocaleString("en-US", { maximumFractionDigits: 2 });
    return sym + n;
  };
  const fmtPct = (v, digits = 2) => {
    if (v == null || !isFinite(v)) return DASH;
    const s = v >= 0 ? "+" : "";
    return s + v.toFixed(digits) + "%";
  };
  const fmtNum = (v, digits = 2) => {
    if (v == null || !isFinite(v)) return DASH;
    return v.toFixed(digits);
  };
  const pnlClass = (v) => {
    if (v == null || !isFinite(v)) return "neutral";
    if (v > 0) return "pos";
    if (v < 0) return "neg";
    return "neutral";
  };
  // Inline-SVG sparkline. Handles null gaps and degenerate (flat / 1-point) series.
  function sparklineSVG(series, w = 56, h = 18) {
    const pts = (series || []).filter(v => v != null && isFinite(v));
    if (pts.length < 2) {
      return `<svg width="${w}" height="${h}" class="spark muted-spark"><line x1="2" y1="${h/2}" x2="${w-2}" y2="${h/2}" stroke="currentColor" stroke-width="1" opacity="0.3"/></svg>`;
    }
    const min = Math.min(...pts), max = Math.max(...pts);
    const range = max - min || 1;
    const stepX = (w - 4) / (pts.length - 1);
    const path = pts.map((v, i) => {
      const x = 2 + i * stepX;
      const y = h - 2 - ((v - min) / range) * (h - 4);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    const first = pts[0], last = pts[pts.length - 1];
    const cls = last > first ? "spark-up" : (last < first ? "spark-down" : "spark-flat");
    const lastX = 2 + (pts.length - 1) * stepX;
    const lastY = h - 2 - ((last - min) / range) * (h - 4);
    return `<svg width="${w}" height="${h}" class="spark ${cls}" viewBox="0 0 ${w} ${h}">
      <path d="${path}" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="1.6" fill="currentColor"/>
    </svg>`;
  }

  // 数据串里混进来的 emoji（硬闸 directive 的 ⛔🧭、体检的 🔴🟡）一律不渲染：
  // 状态由文字和颜色承担，emoji 只会把面板拉回「AI 生成」的观感。(#869 #874)
  const EMOJI_RE = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/gu;
  const stripEmoji = (s) => String(s == null ? "" : s).replace(EMOJI_RE, "").replace(/\s{2,}/g, " ").trim();

  const escapeHtml = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  const safe = (obj, ...path) => {
    let cur = obj;
    for (const k of path) {
      if (cur == null) return null;
      cur = cur[k];
    }
    return cur == null ? null : cur;
  };

  // =========================================================
  // Theme detection — for ECharts dark/light
  // =========================================================
  const isDark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;
  const THEME_CSS_KEYS = [
    "--accent", "--accent-strong", "--border-subtle", "--focus", "--font",
    "--mono", "--negative", "--neutral", "--positive", "--surface-1",
    "--text-primary", "--text-tertiary", "--warning",
  ];
  let _themeCSS = null;
  function readThemeCSS() {
    if (_themeCSS) return _themeCSS;
    const styles = getComputedStyle(document.documentElement);
    _themeCSS = Object.fromEntries(
      THEME_CSS_KEYS.map(k => [k, styles.getPropertyValue(k).trim()])
    );
    return _themeCSS;
  }
  const getCSS = (varName) => readThemeCSS()[varName] || "";
  const invalidateThemeCSS = () => { _themeCSS = null; };
  const chartTextColor = () => getCSS("--text-primary") || (isDark() ? "#F2F6FB" : "#101821");
  const chartLabelColor = () => getCSS("--text-tertiary") || (isDark() ? "#818EA0" : "#5E6D7D");
  const chartGridColor = () => getCSS("--border-subtle") || (isDark() ? "#1D2937" : "#D8E0E8");

  // =========================================================
  // State
  // =========================================================
  let DATA = null;
  let holdingsSort = { key: "current_value", dir: "desc" };
  const charts = {
    equity: null, dailyPnl: null, realized: null, sector: null,
    weightConf: null, shadow: null, aiWinRate: null,
    shadowPortfolioUsd: null, shadowPortfolioHkd: null,
  };

