#!/usr/bin/env bash
# Record a scroll-through of the LIVE dashboard → optimized GIF for the README hero.
# Runs locally (this server has ffmpeg + system chromium); no cloud action needed.
#   refresh_dashboard_gif.sh            # just rebuild docs/dashboard-demo.gif
#   refresh_dashboard_gif.sh --publish  # also commit + push (bot identity)
set -euo pipefail
cd /root/.openclaw/workspace

VID_DIR=/tmp/clawock-vid
OUT=docs/dashboard-demo.gif

# 1. ensure Playwright lib is present (uses the system chromium via CHROME_PATH /
#    the recorder's executablePath resolver — no browser download).
if ! node -e "require.resolve('playwright')" 2>/dev/null; then
  echo "installing playwright lib (browser download skipped)…"
  PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install playwright@1.60.0 --silent --no-save
fi

# 2. record the webm
rm -rf "$VID_DIR"
node scripts/data/shoot_dashboard_gif.js
VID=$(cat "$VID_DIR/video-path.txt")

# 3. webm → GIF: drop the ~3.5s page-load head, cap length, optimize palette.
mkdir -p docs
ffmpeg -y -ss 3.5 -t 13 -i "$VID" \
  -vf "fps=10,scale=780:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=160[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3" \
  -loop 0 "$OUT" >/dev/null 2>&1
SZ=$(du -h "$OUT" | cut -f1)
echo "  ✓ $OUT rebuilt ($SZ)"

# 4. optional publish
if [[ "${1:-}" == "--publish" ]]; then
  if git diff --quiet -- "$OUT"; then
    echo "  no visual change — nothing to commit"
    exit 0
  fi
  git -c user.name="github-actions[bot]" \
      -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
      add "$OUT" && \
  git -c user.name="github-actions[bot]" \
      -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
      commit -q -m "docs: refresh dashboard demo GIF $(date -u +%Y-%m-%d)"
  bash scripts/data/safe_push.sh
fi
