#!/usr/bin/env python3
"""assemble_dashboard_gif.py — stitch the per-tab mobile frames shot by
shoot_dashboard.js into assets/dashboard.gif (the README hero animation).

Run right after shoot_dashboard.js:
    node scripts/data/shoot_dashboard.js
    python3 scripts/data/assemble_dashboard_gif.py

Reads .gifframes/f{0..5}.png, scales to a uniform height, then cycles the 6 tabs
with a horizontal SWIPE transition between them (matching the dashboard's own
"‹ 左右滑动切换 ›" affordance) — each tab holds, then slides left to the next.
Quantized to a small palette to keep the file modest. Refreshed weekly by the
screenshot Action so it never drifts.
"""
import os
import sys
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FRAME_DIR = os.environ.get("FRAME_DIR", os.path.join(ROOT, ".gifframes"))
OUT = os.path.join(ROOT, "assets", "dashboard.gif")
HEIGHT = 760
COLORS = 96          # palette per frame (size vs. fidelity)
TWEENS = 4           # in-between slide frames per transition
HOLD_MS = 1400       # dwell on each tab
HOLD_REFLECT_MS = 2100  # the self-grading tab lingers longest
SLIDE_MS = 90        # each slide frame

# ease-out cubic — fast start, gentle landing (feels like a real flick)
def _ease(t):
    return 1 - (1 - t) ** 3

tabs = []
for i in range(6):
    p = os.path.join(FRAME_DIR, f"f{i}.png")
    if not os.path.exists(p):
        print(f"  ✗ missing frame {p}", file=sys.stderr)
        sys.exit(1)
    im = Image.open(p).convert("RGB")
    w = int(im.width * HEIGHT / im.height)
    tabs.append(im.resize((w, HEIGHT), Image.LANCZOS))

W = tabs[0].width
frames, durations = [], []
for i in range(6):
    # hold on tab i
    frames.append(tabs[i]); durations.append(HOLD_REFLECT_MS if i == 5 else HOLD_MS)
    nxt = (i + 1) % 6  # wrap reflect → hero for a seamless loop
    cur, nx = tabs[i], tabs[nxt]
    for k in range(1, TWEENS + 1):
        off = int(W * _ease(k / (TWEENS + 1)))       # 0 → W
        canvas = Image.new("RGB", (W, HEIGHT))
        canvas.paste(cur, (-off, 0))                 # current slides out left
        canvas.paste(nx, (W - off, 0))               # next slides in from right
        frames.append(canvas); durations.append(SLIDE_MS)

frames = [f.quantize(colors=COLORS, method=Image.MEDIANCUT, dither=Image.NONE) for f in frames]
frames[0].save(OUT, save_all=True, append_images=frames[1:],
               duration=durations, loop=0, optimize=True, disposal=2)
print(f"✓ wrote {OUT} ({os.path.getsize(OUT)//1024} KB, {frames[0].size}, {len(frames)} frames)")
