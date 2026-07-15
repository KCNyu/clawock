#!/usr/bin/env bash
# Quick portfolio check through the two live market pipelines.
set -euo pipefail

cd "$(dirname "$0")"
python3 scripts/data/analyze_hk_stocks.py
python3 scripts/data/analyze_us_stocks.py
