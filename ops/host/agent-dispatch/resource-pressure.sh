#!/usr/bin/env bash
# Sourced by the runner/supervisor after limits.env. Empty stdout means admission is OK.
# Missing Linux telemetry defers patrol, not foreground tasks. Files are test seams.
memory_pressure_reason() {
  local available full
  available=$(awk '$1 == "MemAvailable:" {print $2}' "${AGENT_DISPATCH_MEMINFO:-/proc/meminfo}" 2>/dev/null)
  full=$(awk '$1 == "full" {for (i=2;i<=NF;i++) if ($i ~ /^avg60=/) {sub(/^avg60=/,"",$i); print $i}}' \
    "${AGENT_DISPATCH_MEMORY_PSI:-/proc/pressure/memory}" 2>/dev/null)
  if ! [[ "$available" =~ ^[0-9]+$ && "$full" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo 'memory telemetry unavailable; defer patrol'; return 0
  fi
  if [ "$available" -lt "$PATROL_MIN_AVAILABLE_KB" ]; then
    echo "memory headroom low: ${available} KiB available (< $PATROL_MIN_AVAILABLE_KB)"
  elif awk -v p="$full" -v cap="$PATROL_MAX_MEMORY_FULL_AVG60" 'BEGIN {exit !(p >= cap)}'; then
    echo "memory pressure: full avg60=$full (>= $PATROL_MAX_MEMORY_FULL_AVG60)"
  fi
  return 0
}
