#!/usr/bin/env python3
"""Render an intraday holdings card to PNG via matplotlib (NO model — pure Python
draw; snap chromium is sandbox-confined and can't write our paths). CJK via Noto
Sans CJK. Green=gain / Red=loss (US/HK app convention).

One image = 标题 + 指数 + 总览 + 持仓表(全列含成本) + 我的看法(渲进图). WeChat
intraday delivery sends ONLY this image (kcn: 微信发截图、不要文字、参考 TG 那张),
which sidesteps WeChat's mobile monospace-table wrapping and its no-image+text-mix
limit. Same image doubles as the Telegram cold-session backup.

data json: {title, index, summary, cols[], aligns[]('l'|'r'), xs[], signed_cols[],
            rows[[...]], index_color, summary_color, narrative}

build_card_from_report() parses a delivered report (table + 我的看法) into this
dict so both intraday_postflight (WeChat) and intraday_watchdog (Telegram) share
one code path.
"""
import re
import sys
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import Rectangle

for _cand in ("Noto Sans CJK SC", "Noto Sans CJK HK", "Noto Sans CJK JP"):
    try:
        fm.findfont(_cand, fallback_to_default=False)
        plt.rcParams["font.family"] = _cand
        break
    except Exception:
        pass

GAIN, LOSS, FG, MUTED, BG = "#3fb950", "#f85149", "#e6edf3", "#8b949e", "#0d1117"
DPI = 300          # HD — kcn 要高清
# Narrower width → portrait aspect → WeChat shows a BIGGER image bubble (landscape
# images render as a small wide-but-short thumbnail). 8-col table still fits.
FIG_W = 8.5


def _wrap(text, width_vw):
    """Wrap one paragraph to <= width_vw visual width per line (CJK = 2, ASCII = 1)."""
    out, cur, cw = [], "", 0
    for ch in text:
        w = 2 if ord(ch) > 127 else 1
        if cur and cw + w > width_vw:
            out.append(cur)
            cur, cw = "", 0
        cur += ch
        cw += w
    if cur:
        out.append(cur)
    return out or [""]


# Emoji Noto Sans CJK lacks → render as tofu boxes. Strip them but KEEP the
# geometric symbols ▲▼▎◎ (U+25xx, not in these ranges) which render fine.
_EMOJI = re.compile(r'[\U0001F000-\U0001FAFF☀-➿️✅⚠]')


def _clean(s):
    return _EMOJI.sub('', s or '').strip()


def _sign_color(v):
    s = str(v).strip()
    if s in ("", "0", "0.0", "—", "-"):
        return FG
    if s.startswith(("−", "-")):
        return LOSS
    return GAIN


def render(d, out):
    rows, cols, aligns, xs = d["rows"], d["cols"], d["aligns"], d["xs"]
    signed = set(d.get("signed_cols", []))
    narrative = (d.get("narrative") or "").strip()
    n = len(rows)

    narr_lines = []
    if narrative:
        wrap_vw = int(FIG_W * 6.8)  # scale wrap width to figure width (avoid overflow)
        for para in narrative.split("\n"):
            para = para.rstrip()
            if not para:
                narr_lines.append("")
            else:
                narr_lines.extend(_wrap(para, wrap_vw))

    # Vertical budget in "row units" (≈ one body line); fig height scales to fit.
    U_TITLE, U_INDEX, U_SUM, U_GAP, U_HEAD, U_ROW, U_NARR = 2.2, 1.6, 1.6, 1.1, 1.7, 1.6, 1.2
    units = U_TITLE + U_INDEX + U_SUM + U_GAP + U_HEAD + n * U_ROW + 1.2
    if narr_lines:
        units += 1.8 + len(narr_lines) * U_NARR
    # 0.50 (was 0.34): taller image → more portrait aspect → WeChat shows a ~1.5×
    # bigger bubble. Width stays so the table isn't cramped (kcn 要再大点).
    fig_h = max(4.8, units * 0.50)

    fig = plt.figure(figsize=(FIG_W, fig_h), dpi=DPI)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off()
    ax.set_xlim(0, 100); ax.set_ylim(0, units)

    def T(x, yy, s, **kw):
        # parse_math=False: '$' in US figures ($3,040, +$412…) would otherwise be
        # read as mathtext, dropping CJK between a pair into the math font (tofu).
        ax.text(x, yy, s, va="top", parse_math=False, **kw)

    y = units - U_TITLE
    T(2.5, y, d["title"], color=FG, fontsize=27, fontweight="bold")
    y -= U_INDEX
    if d.get("index"):
        T(2.5, y, d["index"], color=d.get("index_color", "#c9d1d9"), fontsize=18)
    y -= U_SUM
    if d.get("summary"):
        T(2.5, y, d["summary"], color=d.get("summary_color", "#c9d1d9"), fontsize=18)
    y -= U_GAP

    for j, c in enumerate(cols):
        ha = "left" if aligns[j] == "l" else "right"
        T(xs[j], y, c, color=MUTED, fontsize=16, ha=ha, fontweight="bold")
    ax.plot([1.5, 98.5], [y - 0.55, y - 0.55], color="#30363d", lw=1.5)
    y -= U_HEAD
    for idx, r in enumerate(rows):
        if idx % 2 == 1:  # zebra stripe — subtle alt-row band for a tidy table
            ax.add_patch(Rectangle((1.5, y - U_ROW + 0.55), 97.0, U_ROW,
                                   facecolor="#161b22", edgecolor="none", zorder=0))
        for j, cell in enumerate(r):
            ha = "left" if aligns[j] == "l" else "right"
            color = FG if j == 0 else (_sign_color(cell) if j in signed else FG)
            T(xs[j], y, str(cell), color=color, fontsize=18, ha=ha,
              fontweight="bold" if j == 0 else "normal", zorder=3)
        y -= U_ROW

    if narr_lines:
        y -= 0.9
        for ln in narr_lines:
            if ln.startswith("▎"):
                T(2.5, y, ln, color="#58a6ff", fontsize=18, fontweight="bold")
            else:
                T(2.5, y, ln, color="#c9d1d9", fontsize=16)
            y -= U_NARR

    fig.savefig(out, facecolor=BG, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    print("wrote", out)


# ── parse a delivered report into card_data (shared by postflight + watchdog) ──

def build_card_from_report(report_text):
    """Parse `header + index + summary + holdings table + 我的看法` into card_data
    (incl narrative). Returns None if no holdings table found → caller falls back
    to plain text. Column x-anchors computed for whatever column count the table
    has (intraday is 8-col incl 成本; image isn't width-constrained)."""
    lines = report_text.splitlines()
    tbl_idx = [i for i, l in enumerate(lines) if l.strip().startswith("|")]
    if len(tbl_idx) < 3:
        return None
    header = [c.strip() for c in lines[tbl_idx[0]].strip().strip("|").split("|")]
    ncol = len(header)
    if not 5 <= ncol <= 9:
        return None
    rows = []
    for i in tbl_idx[1:]:
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if len(cells) != ncol or cells[0] == "代码" or set(cells[0]) <= set("-: "):
            continue
        rows.append(cells)
    if not rows:
        return None

    pre = [l.strip() for l in lines[:tbl_idx[0]] if l.strip()]
    raw_title = pre[0] if pre else "持仓盯盘"
    title = _clean(raw_title)
    summary_raw = next((l for l in pre if "市值" in l), "")
    summary = _clean(summary_raw)
    index = _clean(next((l for l in pre[1:] if l != summary_raw and "市值" not in l), ""))
    narrative = "\n".join(_clean(l) for l in lines[tbl_idx[-1] + 1:]).strip()

    # Content-aware column layout: each column gets width ∝ its widest cell
    # (header or data), packed left→right with a fixed gap, so numbers line up in
    # tight neat columns instead of floating at evenly-spaced anchors. 代码 left-
    # aligned at the left edge; every numeric column right-aligned at its right
    # edge (so decimals/signs stack). Rightmost column lands exactly at RIGHT.
    def _vw(s):
        return sum(2 if ord(c) > 127 else 1 for c in str(s))
    colw = [max([_vw(header[j])] + [_vw(r[j]) for r in rows]) for j in range(ncol)]
    GAPC, LEFT, RIGHT = 2.6, 2.5, 98.5
    total = sum(colw) + GAPC * (ncol - 1)
    scale = (RIGHT - LEFT) / total
    xs, aligns, cur = [], [], LEFT
    for j in range(ncol):
        wpx = colw[j] * scale
        if j == 0:
            xs.append(cur); aligns.append("l")          # left edge, left-aligned
        else:
            xs.append(cur + wpx); aligns.append("r")     # right edge, right-aligned
        cur += wpx + GAPC * scale
    return {
        "title":         title.strip(),
        "index":         index,
        "index_color":   GAIN if "▲" in index else (LOSS if "▼" in index else "#c9d1d9"),
        "summary":       summary,
        "summary_color": LOSS if ("浮盈 -" in summary or "浮盈 −" in summary) else GAIN,
        "cols":          header,
        "aligns":        aligns,
        "xs":            xs,
        "signed_cols":   [i for i, h in enumerate(header) if "%" in h or "$" in h],
        "rows":          rows,
        "narrative":     narrative,
    }


if __name__ == "__main__":
    render(json.load(open(sys.argv[1])), sys.argv[2])
