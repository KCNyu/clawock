#!/usr/bin/env bash
# render_architecture.sh — rasterize the architecture diagram HTML → docs/architecture.png
# at 2x scale (retina, matches the dashboard's dark theme). Uses Playwright (it grabs the
# screenshot buffer in-process and writes via Python, which — unlike raw `chromium
# --screenshot` — works inside containers where the renderer runs in a private namespace).
#
#   pip install playwright && python3 -m playwright install chromium
#   bash scripts/data/render_architecture.sh
#
# Re-run whenever scripts/data/architecture_diagram.html changes.
set -e
cd "$(dirname "$0")/../.."

python3 - <<'PY'
import os
from playwright.sync_api import sync_playwright
html = os.path.abspath("scripts/data/architecture_diagram.html")
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    pg = ctx.new_page()
    pg.goto(f"file://{html}", wait_until="networkidle")
    pg.wait_for_timeout(400)
    pg.screenshot(path="docs/architecture.png")
    b.close()
print("✓ wrote docs/architecture.png")
PY
