#!/usr/bin/env python3
"""assemble_dashboard_gif.py — stitch the per-tab scroll frames shot by
shoot_dashboard.js into site/assets/dashboard.gif (the README hero animation).

Run right after shoot_dashboard.js:
    node site/tools/shoot_dashboard.js
    python3 site/tools/assemble_dashboard_gif.py

shoot_dashboard.js writes, per tab i, a sequence .gifframes/f{i}_{0..n}.png captured
while scrolling that tab's content top→bottom. This script plays each tab as: hold at
top → scroll down (the captured vertical frames) → SWIPE LEFT to the next tab
(horizontal slide, composited here). Both axes match the dashboard's own scrollable
panels + "‹ 左右滑动切换 ›". Quantized to a small palette to keep the file modest.
The workflow builds it only on manual dispatch after a UI change; scheduled weekly
runs refresh the two live PNGs and skip these expensive frames.
"""
import glob
import os
import re
import sys
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FRAME_DIR = os.environ.get("FRAME_DIR", os.path.join(ROOT, ".gifframes"))
# Overridable so this script can be exercised without writing over the committed
# animation. It used to be a hardcoded path, which meant the only way to run it
# for verification was to copy the file into a throwaway directory tree and run
# the copy — so nothing ever ran the real one outside the weekly cron (#754).
OUT = os.environ.get("GIF_OUT") or os.path.join(ROOT, "site", "assets", "dashboard.gif")

OW = 640             # output width (frames scaled to this; height follows aspect)
                     # 640 ≈ 2× the README's 300px display = crisp on retina; source
                     # frames are 800px so ≤800 stays real detail (no upscaling)
COLORS = 256         # GIF max — a single global palette (built from all frames below)
                     # keeps the UI's real colors instead of washing them out to grey
TWEENS = 6           # horizontal slide frames per transition
HOLD_TOP_MS = 1200   # dwell at the top of each tab
HOLD_TOP_REFLECT_MS = 1900   # the self-grading tab (tab 5) lingers longest
HOLD_BOTTOM_MS = 850         # pause once scrolled to the bottom
VSCROLL_MS = 110     # each vertical-scroll frame
SLIDE_MS = 80        # each horizontal-slide frame

SEED_GLOBS = [       # where the UI's own chromatic colors are defined; scanned so
                     # their exact values can be protected in the GIF palette below
    os.path.join("site", "assets", "css", "dashboard.css"),
    os.path.join("site", "_layouts", "default.html"),
    os.path.join("site", "assets", "js", "*.js"),
]


def _ui_seed_colors():
    """Exact chromatic hex colors the shipped dashboard sources define."""
    found = set()
    for pattern in SEED_GLOBS:
        for path in glob.glob(os.path.join(ROOT, pattern)):
            try:
                text = open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for hx in re.findall(r"#[0-9a-fA-F]{6}\b", text):
                color = tuple(int(hx[i:i + 2], 16) for i in (1, 3, 5))
                if max(color) - min(color) > 40:   # chromatic only: neutrals quantize fine
                    found.add(color)
    return sorted(found)


def _ease(t):        # ease-in-out cubic — smooth start & stop
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def _load_tab(i):
    """Ordered, uniform-width scroll frames for tab i (f{i}_0, f{i}_1, …)."""
    paths = glob.glob(os.path.join(FRAME_DIR, f"f{i}_*.png"))
    if not paths:
        print(f"  ✗ no frames for tab {i} (run shoot_dashboard.js first)", file=sys.stderr)
        sys.exit(1)
    paths.sort(key=lambda p: int(re.search(r"_(\d+)\.png$", p).group(1)))
    out = []
    for p in paths:
        im = Image.open(p).convert("RGB")
        out.append(im.resize((OW, int(im.height * OW / im.width)), Image.LANCZOS))
    return out


tabs = [_load_tab(i) for i in range(6)]
VH = tabs[0][0].height   # every viewport frame is the same size

frames, durations = [], []
for i in range(6):
    seq, nxt_top = tabs[i], tabs[(i + 1) % 6][0]   # wrap reflect → hero for a loop
    for j, fr in enumerate(seq):
        frames.append(fr)
        if j == 0:
            durations.append(HOLD_TOP_REFLECT_MS if i == 5 else HOLD_TOP_MS)
        elif j == len(seq) - 1:
            durations.append(HOLD_BOTTOM_MS)       # linger at the bottom
        else:
            durations.append(VSCROLL_MS)
    # horizontal swipe from this tab's last (bottom) frame to the next tab's top
    out_frame = seq[-1]
    for k in range(1, TWEENS + 1):
        off = int(OW * _ease(k / (TWEENS + 1)))
        canvas = Image.new("RGB", (OW, VH))
        canvas.paste(out_frame, (-off, 0))
        canvas.paste(nxt_top, (OW - off, 0))
        frames.append(canvas)
        durations.append(SLIDE_MS)

# One global palette derived from every frame → colors stay true and stable
# across frames (per-frame palettes drift toward grey and flicker). No dither: the UI
# is flat color, and dithering just adds noise + bloats the file.
#
# MEDIANCUT alone washed the accents out: ~95% of every frame is near-white, so its
# population-based box split spent ~205 of 256 slots on indistinguishable whites and
# left the whole saturated UI sharing 2-3 muddy entries — #36A3FF mapped ~105 RGB
# units away, which read as a grey hero animation. Seed the palette with the UI's
# exact chromatic colors first (echarts' default light palette included — charts use
# it whenever they don't override the series colors), then let MEDIANCUT fill the
# rest with the neutrals it is good at; mapping stays nearest-color without dither.
_stack = Image.new("RGB", (OW, VH * len(frames)))
for _i, _f in enumerate(frames):
    _stack.paste(_f, (0, VH * _i))
_seeds = _ui_seed_colors()
_fill = _stack.quantize(colors=max(32, COLORS - len(_seeds)),
                        method=Image.MEDIANCUT).getpalette()
_palette, _seen = [], set()
for _c in _seeds + list(zip(_fill[0::3], _fill[1::3], _fill[2::3])):
    if _c not in _seen:
        _seen.add(_c)
        _palette.append(_c)
_pal = Image.new("P", (1, 1))
_flat = [v for _c in _palette[:COLORS] for v in _c]
_pal.putpalette(_flat + [0] * (768 - len(_flat)))
frames = [f.quantize(palette=_pal, dither=Image.Dither.NONE) for f in frames]
frames[0].save(OUT, save_all=True, append_images=frames[1:],
               duration=durations, loop=0, optimize=True, disposal=2)
print(f"✓ wrote {OUT} ({os.path.getsize(OUT)//1024} KB, {frames[0].size}, {len(frames)} frames)")
