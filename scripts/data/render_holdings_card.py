#!/usr/bin/env python3
"""Render a holdings card to PNG via matplotlib (NO model — pure Python draw;
snap chromium is sandbox-confined and can't write our paths). CJK via Noto Sans
CJK. Green=gain / Red=loss (US/HK app convention). Used by intraday_watchdog so
the table shows as a proper broker card on mobile instead of monospace pipes.

data json: {title, index, summary, cols[], aligns[]('l'|'r'), xs[], signed_cols[],
            rows[[...]], index_color, summary_color}
"""
import sys, json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

for cand in ("Noto Sans CJK SC", "Noto Sans CJK HK", "Noto Sans CJK JP"):
    try:
        fm.findfont(cand, fallback_to_default=False); plt.rcParams["font.family"] = cand; break
    except Exception: pass

GAIN, LOSS, FG, MUTED, BG = "#3fb950", "#f85149", "#e6edf3", "#8b949e", "#0d1117"

def sign_color(v):
    s = str(v).strip()
    if s in ("", "0", "0.0", "—", "-"): return FG
    if s.startswith(("−", "-")): return LOSS
    return GAIN

def render(d, out):
    rows, cols, aligns, xs = d["rows"], d["cols"], d["aligns"], d["xs"]
    signed = set(d.get("signed_cols", []))
    n = len(rows)
    fig = plt.figure(figsize=(9.8, 1.95 + 0.46*(n+1)), dpi=200); fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0,0,1,1]); ax.set_axis_off(); ax.set_xlim(0,100); ax.set_ylim(0,100)
    y = 96
    ax.text(2.5, y, d["title"], color=FG, fontsize=19, fontweight="bold", va="top"); y-=7
    ax.text(2.5, y, d["index"], color=d.get("index_color","#c9d1d9"), fontsize=13, va="top"); y-=6.6
    ax.text(2.5, y, d["summary"], color=d.get("summary_color","#c9d1d9"), fontsize=13, va="top"); y-=6.2
    top = y
    for j,c in enumerate(cols):
        ha = "left" if aligns[j]=="l" else "right"
        ax.text(xs[j], top, c, color=MUTED, fontsize=11, ha=ha, va="top", fontweight="bold")
    ax.plot([2.5,99],[top-3.4,top-3.4], color="#30363d", lw=1.2)
    ry = top-6.2; rh = (ry-3.5)/n
    for r in rows:
        for j,cell in enumerate(r):
            ha = "left" if aligns[j]=="l" else "right"
            color = FG if j==0 else (sign_color(cell) if j in signed else FG)
            ax.text(xs[j], ry, str(cell), color=color, fontsize=13.5, ha=ha, va="top",
                    fontweight="bold" if j==0 else "normal")
        ax.plot([2.5,99],[ry-rh+1.4, ry-rh+1.4], color="#21262d", lw=0.8)
        ry -= rh
    fig.savefig(out, facecolor=BG, bbox_inches="tight", pad_inches=0.18); print("wrote", out)

if __name__ == "__main__":
    render(json.load(open(sys.argv[1])), sys.argv[2])
