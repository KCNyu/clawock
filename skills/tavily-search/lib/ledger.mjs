// Tavily monthly credit ledger — the HARD budget guardrail.
//
// Why this exists: the free "Researcher" plan is 1000 credits/month, shared
// globally. Tavily's /usage endpoint lags badly (still 0 minutes after real
// calls), so it CANNOT gate a call in real time. This local ledger is the
// source of truth for gating; /usage is only a coarse periodic reconciliation.
//
// All Tavily calls go through search.mjs / extract.mjs, so charging here covers
// every code path. Pricing (verified against Tavily docs): basic search = 1
// credit, advanced (--deep) = 2, extract = 1 credit per 5 URLs.
//
// Buckets enforce codex's allocation so one use can't starve another. Calls
// without --bucket land in "default" (deliberately small) so any unplanned
// usage is naturally throttled instead of silently eating the month.

import { readFileSync, writeFileSync, openSync, closeSync, existsSync, unlinkSync } from "node:fs";

const LEDGER_PATH = process.env.TAVILY_LEDGER_PATH ?? "/root/.openclaw/tavily-credit-ledger.json";
const LOCK_PATH = LEDGER_PATH + ".lock";

// Global hard cap = monthlyLimit - reserve. Reserve absorbs the tiny
// precheck→commit race and any /usage-vs-ledger drift.
const DEFAULTS = {
  monthly_limit: 1000,
  reserve: 50,
  buckets: {
    brief: { cap: 300, used: 0 }, // daily-deep-brief — the one guaranteed use
    report: { cap: 280, used: 0 }, // HK/US open+close core reports
    intraday: { cap: 120, used: 0 }, // event-triggered only (not every poll)
    research: { cap: 100, used: 0 }, // weekly catalyst / thesis-falsification
    extract: { cap: 80, used: 0 }, // raw filings/announcements only
    default: { cap: 60, used: 0 }, // anything unbucketed — kept small on purpose
  },
};

function currentMonth() {
  // Asia/Shanghai to line up with the HKT trading calendar the crons use.
  const d = new Date(Date.now() + 8 * 3600 * 1000);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function withLock(fn) {
  // Cross-process mutex via O_EXCL lockfile. Crons are staggered so contention
  // is rare; retry briefly, then proceed unlocked rather than block a report.
  let fd = null;
  for (let i = 0; i < 50; i++) {
    try {
      fd = openSync(LOCK_PATH, "wx");
      break;
    } catch {
      const until = Date.now() + 20;
      while (Date.now() < until) {
        /* tiny spin */
      }
    }
  }
  try {
    return fn();
  } finally {
    if (fd !== null) {
      closeSync(fd);
      try {
        unlinkSync(LOCK_PATH);
      } catch {
        /* ignore */
      }
    }
  }
}

function load() {
  let led;
  if (existsSync(LEDGER_PATH)) {
    try {
      led = JSON.parse(readFileSync(LEDGER_PATH, "utf8"));
    } catch {
      led = null;
    }
  }
  const month = currentMonth();
  if (!led || led.month !== month) {
    // New month → reset. (Approximates Tavily's cycle by calendar month; the
    // /usage reconciliation can correct if the real reset date differs.)
    led = {
      month,
      monthly_limit: led?.monthly_limit ?? DEFAULTS.monthly_limit,
      reserve: led?.reserve ?? DEFAULTS.reserve,
      total_used: 0,
      buckets: JSON.parse(JSON.stringify(DEFAULTS.buckets)),
    };
    writeFileSync(LEDGER_PATH, JSON.stringify(led, null, 2));
  }
  // Backfill any bucket added to DEFAULTS after the ledger was created.
  for (const [k, v] of Object.entries(DEFAULTS.buckets)) {
    if (!led.buckets[k]) led.buckets[k] = { ...v };
  }
  return led;
}

// Returns { allowed, reason, remaining } WITHOUT charging.
export function precheck(bucketName, cost) {
  return withLock(() => {
    const led = load();
    const bucket = led.buckets[bucketName] ?? led.buckets.default;
    const globalCap = led.monthly_limit - led.reserve;
    const remaining = globalCap - led.total_used;
    if (led.total_used + cost > globalCap) {
      return {
        allowed: false,
        reason: `monthly Tavily budget reached (${led.total_used}/${globalCap} used, reserve ${led.reserve})`,
        remaining,
      };
    }
    if (bucket.used + cost > bucket.cap) {
      return {
        allowed: false,
        reason: `Tavily "${bucketName}" bucket exhausted (${bucket.used}/${bucket.cap})`,
        remaining,
      };
    }
    return { allowed: true, reason: "", remaining };
  });
}

// Charge AFTER a successful API response (failed/429 requests don't cost
// credits on Tavily's side, so we never charge for them).
export function commit(bucketName, cost) {
  return withLock(() => {
    const led = load();
    const bucket = led.buckets[bucketName] ?? led.buckets.default;
    const key = led.buckets[bucketName] ? bucketName : "default";
    led.total_used += cost;
    led.buckets[key].used += cost;
    writeFileSync(LEDGER_PATH, JSON.stringify(led, null, 2));
    const globalCap = led.monthly_limit - led.reserve;
    return {
      total_used: led.total_used,
      bucket_used: led.buckets[key].used,
      bucket_cap: led.buckets[key].cap,
      remaining: globalCap - led.total_used,
    };
  });
}
