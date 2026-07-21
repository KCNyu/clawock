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
// Design for robustness (a "hard cap" must hold under crashes and concurrency):
//   - Charge is done by RESERVE, before the API call, atomically under a lock
//     (check + write in one critical section) → concurrent callers cannot blow
//     past the cap on a stale snapshot. A definite API failure REFUNDS.
//   - Locking never fails OPEN. If the lock can't be taken (and isn't a stale
//     leftover we can reclaim), reserve() DENIES → caller degrades gracefully
//     to built-in search. Conservative over-count is preferred to overspend.
//   - Writes are atomic (temp file + fsync + rename). A corrupt same-month
//     ledger is quarantined and treated as fail-closed — never silently reset
//     to 0 (which would forget the month's spend and re-open the floodgates).
//
// Buckets enforce the allocation so one use can't starve another. Calls without
// --bucket land in "default" (deliberately small) so unplanned usage is
// throttled instead of silently eating the month.

import {
  readFileSync,
  writeFileSync,
  openSync,
  closeSync,
  fsyncSync,
  renameSync,
  existsSync,
  unlinkSync,
  statSync,
} from "node:fs";

const LEDGER_PATH = process.env.TAVILY_LEDGER_PATH ?? "/root/.openclaw/tavily-credit-ledger.json";
const LOCK_PATH = LEDGER_PATH + ".lock";
const LOCK_STALE_MS = 15000; // a lockfile older than this is a crash leftover
const LOCK_WAIT_MS = 2000; // give up (fail-closed) after this long contending

// Global hard cap = monthly_limit - reserve. Reserve is now only a small extra
// cushion (for the rare crash-after-reserve, which over-counts safely), not the
// thing that saves us from a concurrency blowout — reservation does that.
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
const BUCKET_NAMES = Object.keys(DEFAULTS.buckets);

class LedgerUnavailable extends Error {}

function currentMonth() {
  // Asia/Shanghai to line up with the HKT trading calendar the crons use.
  const d = new Date(Date.now() + 8 * 3600 * 1000);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function resolveBucket(name) {
  // Own-property check only — avoids prototype keys (__proto__, constructor)
  // resolving to inherited objects and slipping past the caps.
  return Object.hasOwn(DEFAULTS.buckets, name) ? name : "default";
}

// Cross-process mutex. Reclaims a stale (crashed-owner) lock by age; otherwise
// throws LedgerUnavailable so callers fail CLOSED rather than run unlocked.
function withLock(fn) {
  const deadline = Date.now() + LOCK_WAIT_MS;
  let fd = null;
  while (fd === null) {
    try {
      fd = openSync(LOCK_PATH, "wx");
    } catch (err) {
      if (err.code !== "EEXIST") {
        // EACCES / EMFILE / etc. are real problems — do not run unlocked.
        throw new LedgerUnavailable(`lock error: ${err.code || err.message}`);
      }
      // Lock held. Reclaim it if it's a crash leftover.
      try {
        const age = Date.now() - statSync(LOCK_PATH).mtimeMs;
        if (age > LOCK_STALE_MS) {
          unlinkSync(LOCK_PATH);
          continue; // retake immediately
        }
      } catch {
        // Lock vanished between open and stat — just retry.
      }
      if (Date.now() > deadline) {
        throw new LedgerUnavailable("ledger busy (lock contention timed out)");
      }
      const until = Date.now() + 25; // bounded short wait, not a hot spin
      while (Date.now() < until) {
        /* wait */
      }
    }
  }
  try {
    return fn();
  } finally {
    closeSync(fd);
    try {
      unlinkSync(LOCK_PATH);
    } catch {
      /* ignore */
    }
  }
}

function atomicWrite(obj) {
  const tmp = `${LEDGER_PATH}.tmp.${process.pid}`;
  const fd = openSync(tmp, "w");
  try {
    writeFileSync(fd, JSON.stringify(obj, null, 2));
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  renameSync(tmp, LEDGER_PATH); // atomic on the same filesystem
}

function freshLedger(prev) {
  return {
    month: currentMonth(),
    monthly_limit: prev?.monthly_limit ?? DEFAULTS.monthly_limit,
    reserve: prev?.reserve ?? DEFAULTS.reserve,
    total_used: 0,
    buckets: JSON.parse(JSON.stringify(DEFAULTS.buckets)),
  };
}

// Must be called inside withLock. Returns a validated ledger for the current
// month, creating a fresh one only when there is genuinely nothing to lose
// (no file, or a cleanly-parsed prior month). A corrupt EXISTING file is
// quarantined and throws — we never zero-out a month we can't read.
function loadLocked() {
  const month = currentMonth();
  if (!existsSync(LEDGER_PATH)) {
    const led = freshLedger(null);
    atomicWrite(led);
    return led;
  }
  let led;
  try {
    led = JSON.parse(readFileSync(LEDGER_PATH, "utf8"));
  } catch {
    // Corrupt file. Do NOT reset to 0 — quarantine and fail closed.
    try {
      renameSync(LEDGER_PATH, `${LEDGER_PATH}.corrupt.${Date.now()}`);
    } catch {
      /* ignore */
    }
    throw new LedgerUnavailable("ledger unreadable (quarantined corrupt file)");
  }
  if (!led || typeof led !== "object" || typeof led.total_used !== "number" || led.total_used < 0) {
    throw new LedgerUnavailable("ledger schema invalid");
  }
  if (led.month !== month) {
    const rolled = freshLedger(led);
    atomicWrite(rolled);
    return rolled;
  }
  // Normalize buckets: backfill any missing, drop obviously bad shapes.
  if (!led.buckets || typeof led.buckets !== "object") led.buckets = {};
  for (const [k, v] of Object.entries(DEFAULTS.buckets)) {
    const b = led.buckets[k];
    if (!b || typeof b.used !== "number" || b.used < 0 || typeof b.cap !== "number") {
      led.buckets[k] = { ...v };
    }
  }
  if (typeof led.monthly_limit !== "number") led.monthly_limit = DEFAULTS.monthly_limit;
  if (typeof led.reserve !== "number") led.reserve = DEFAULTS.reserve;
  return led;
}

// Atomically check the budget AND charge it. Returns:
//   { allowed:true,  remaining, total_used, bucket, bucket_used, bucket_cap }
//   { allowed:false, reason, remaining? }
// On lock/ledger trouble it DENIES (fail-closed) rather than run unlocked.
export function reserve(bucketName, cost) {
  const key = resolveBucket(bucketName);
  try {
    return withLock(() => {
      const led = loadLocked();
      const bucket = led.buckets[key];
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
          reason: `Tavily "${key}" bucket exhausted (${bucket.used}/${bucket.cap})`,
          remaining,
        };
      }
      led.total_used += cost;
      bucket.used += cost;
      atomicWrite(led);
      return {
        allowed: true,
        bucket: key,
        total_used: led.total_used,
        bucket_used: bucket.used,
        bucket_cap: bucket.cap,
        remaining: globalCap - led.total_used,
      };
    });
  } catch (err) {
    if (err instanceof LedgerUnavailable) {
      return { allowed: false, reason: `budget ledger unavailable (${err.message})` };
    }
    throw err;
  }
}

// Give a reservation back after a DEFINITE remote failure (non-2xx / network
// error) — Tavily does not charge for those. Best-effort: if the ledger is
// momentarily locked we drop the refund (conservative over-count), never crash.
export function refund(bucketName, cost) {
  const key = resolveBucket(bucketName);
  try {
    withLock(() => {
      const led = loadLocked();
      led.total_used = Math.max(0, led.total_used - cost);
      const bucket = led.buckets[key];
      if (bucket) bucket.used = Math.max(0, bucket.used - cost);
      atomicWrite(led);
    });
  } catch {
    // Refund lost → we over-counted by `cost`. Safe direction; log and move on.
    console.error(`[tavily] refund of ${cost} to "${key}" skipped (ledger busy)`);
  }
}
