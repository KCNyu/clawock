#!/usr/bin/env python3
"""assemble_dashboard_gif.py — stitch the per-tab mobile frames shot by
shoot_dashboard.js into assets/dashboard.gif (the README hero animation).

Run right after shoot_dashboard.js:
    node scripts/data/shoot_dashboard.js
    python3 scripts/data/assemble_dashboard_gif.py

Reads .gifframes/f{0..5}.png, scales to a uniform height, quantizes to a small
palette (keeps the file ~300KB + avoids inter-frame flicker), and writes a looping
GIF that cycles the 6 dashboard tabs. Refreshed weekly by the screenshot Action so
it never drifts.
"""
import os
import sys
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FRAME_DIR = os.environ.get("FRAME_DIR", os.path.join(ROOT, ".gifframes"))
OUT = os.path.join(ROOT, "assets", "dashboard.gif")
HEIGHT = 820
# per-frame dwell ms; Reflect (the self-grading tab) lingers longest
DURATIONS = [1500, 1600, 1600, 1600, 1600, 2200]

frames = []
for i in range(6):
    p = os.path.join(FRAME_DIR, f"f{i}.png")
    if not os.path.exists(p):
        print(f"  ✗ missing frame {p}", file=sys.stderr)
        sys.exit(1)
    im = Image.open(p).convert("RGB")
    w = int(im.width * HEIGHT / im.height)
    im = im.resize((w, HEIGHT), Image.LANCZOS)
    im = im.quantize(colors=128, method=Image.MEDIANCUT, dither=Image.NONE)
    frames.append(im)

frames[0].save(OUT, save_all=True, append_images=frames[1:],
               duration=DURATIONS, loop=0, optimize=True, disposal=2)
print(f"✓ wrote {OUT} ({os.path.getsize(OUT)//1024} KB, {frames[0].size})")
