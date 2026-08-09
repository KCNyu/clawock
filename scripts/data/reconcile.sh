#!/usr/bin/env bash
# reconcile.sh — the one command to run after ANY edit to portfolio.json trades,
# cash_adjustments, or holdings. Replaces the error-prone "remember to run
# recompute_cash AND recompute_realized" 铁律 with a single structural step, then
# verifies the book against every money-conservation gate.
#
#   bash scripts/data/reconcile.sh            # recompute in place + verify
#   bash scripts/data/reconcile.sh --dry-run  # show what WOULD change, write nothing
#
# derive_cash / _aggregate are pure and unit-tested (tests/test_derivations.py);
# this just chains them + the integrity gate so nothing gets forgotten.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

DRY=""
[ "${1:-}" = "--dry-run" ] && DRY="--dry-run"

echo "▸ recompute aggregates (leaf shares/price/cost → current_value, totals, pnl)…"
clawock aggregates $DRY

echo "▸ recompute cash (baseline + trades cashflow + adjustments)…"
clawock cash $DRY

echo "▸ recompute realized P&L (Σ sell trades)…"
clawock realized $DRY

echo "▸ integrity gate (TCV / cost / pnl / CASH_RECON / COST_BASIS / FX)…"
python3 scripts/data/preflight_integrity.py
rc=$?

echo
if [ "$rc" = "0" ]; then
  echo "✅ reconciled — portfolio.json passes all money-conservation checks."
  [ -n "$DRY" ] && echo "   (dry-run: no files written)"
else
  echo "🔴 integrity ERRORs remain after recompute — inspect above."
  echo "   (a deposit/withdrawal not recorded in cash_adjustments, or a half-entered"
  echo "    trade ledger, can legitimately fail this — fix the input, don't force it.)"
fi
exit $rc
