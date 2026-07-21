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
// A "hard cap" must hold under crashes AND concurrency, not just the happy
// path. Design:
//   - reserve() checks AND charges atomically under a lock before the API call,
//     so concurrent callers can't blow past the cap on a stale snapshot. Only a
//     DEFINITE non-billed outcome (an HTTP error response) refunds; ambiguous
//     network failures keep the reservation (conservative over-count), because
//     the reset could have arrived after Tavily already billed.
//   - The lock never fails OPEN: it is token-owned, a crashed-owner lock is
//     reclaimed race-free via atomic rename-steal, and if the lock genuinely
//     can't be taken reserve() DENIES → caller degrades to built-in search.
//   - Writes are atomic (temp + fsync + rename). A ledger that is unreadable or
//     semantically invalid for the current month is quarantined and replaced
//     with a POISONED (fully-exhausted) ledger, so it keeps failing closed for
//     the rest of the month instead of silently resetting the cap to 0. Recover
//     by deleting the ledger file (or waiting for the month to roll over).
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
import { randomBytes } from "node:crypto";

const LEDGER_PATH = process.env.TAVILY_LEDGER_PATH ?? "/root/.openclaw/tavily-credit-ledger.json";
const LOCK_PATH = LEDGER_PATH + ".lock";
const LOCK_STALE_MS = 15000; // a lockfile older than this is a crash leftover
const LOCK_WAIT_MS = 2000; // give up (fail-closed) after this long contending

const DEFAULTS = {
  monthly_limit: 1000,
  reserve: 50, // small cushion for the rare crash-after-reserve over-count
  buckets: {
    brief: { cap: 300, used: 0 }, // daily-deep-brief — the one guaranteed use
    report: { cap: 280, used: 0 }, // HK/US open+close core reports
    intraday: { cap: 120, used: 0 }, // event-triggered only (not every poll)
    research: { cap: 100, used: 0 }, // weekly catalyst / thesis-falsification
    extract: { cap: 80, used: 0 }, // raw filings/announcements only
    default: { cap: 60, used: 0 }, // anything unbucketed — kept small on purpose
  },
};

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

const isFiniteNum = (v) => typeof v === "number" && Number.isFinite(v);

// Cross-process mutex. Token-owned so we only ever release our OWN lock; a
// crashed-owner (stale) lock is reclaimed race-free via atomic rename-steal
// (only one process can rename the path away). If the lock can't be taken we
// throw LedgerUnavailable so callers fail CLOSED rather than run unlocked.
function withLock(fn) {
  const token = `${process.pid}:${randomBytes(8).toString("hex")}`;
  const deadline = Date.now() + LOCK_WAIT_MS;
  let fd = null;
  while (fd === null) {
    try {
      fd = openSync(LOCK_PATH, "wx");
      writeFileSync(fd, token);
    } catch (err) {
      if (err.code !== "EEXIST") {
        // EACCES / EMFILE / etc. are real problems — do not run unlocked.
        throw new LedgerUnavailable(`lock error: ${err.code || err.message}`);
      }
      // Lock held. Reclaim it ONLY if it's a crash leftover, and do so
      // atomically: renaming the path away has exactly one winner; the loser
      // gets ENOENT and simply retries.
      let stale = false;
      try {
        stale = Date.now() - statSync(LOCK_PATH).mtimeMs > LOCK_STALE_MS;
      } catch {
        /* vanished — just retry */
      }
      if (stale) {
        const aside = `${LOCK_PATH}.stale.${token}`;
        try {
          renameSync(LOCK_PATH, aside);
          unlinkSync(aside);
          continue; // we won the steal — retry the exclusive create
        } catch {
          /* someone else stole it first — fall through to wait/retry */
        }
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
      // Only remove the lock if it is still OURS (a stale-steal may have handed
      // it to someone else while our fn ran — though fn is far shorter than the
      // stale threshold, so this is defence in depth).
      if (readFileSync(LOCK_PATH, "utf8") === token) unlinkSync(LOCK_PATH);
    } catch {
      /* not ours / already gone */
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
    monthly_limit: isFiniteNum(prev?.monthly_limit) ? prev.monthly_limit : DEFAULTS.monthly_limit,
    reserve: isFiniteNum(prev?.reserve) ? prev.reserve : DEFAULTS.reserve,
    total_used: 0,
    buckets: JSON.parse(JSON.stringify(DEFAULTS.buckets)),
  };
}

// A poisoned ledger is a valid, fully-exhausted ledger for the current month.
// We write it (atomically) when the on-disk ledger is unreadable/invalid so the
// guardrail keeps failing CLOSED consistently — not just on the first call —
// without ever inventing a spend figure we can't trust.
function poisonLedger() {
  const led = freshLedger(null);
  led.poisoned = true;
  led.total_used = led.monthly_limit; // remaining <= 0 → every reserve denied
  for (const b of Object.values(led.buckets)) b.used = b.cap;
  atomicWrite(led);
  return led;
}

// Full semantic validation of a same-month ledger. Anything off → not trusted.
function isSaneLedger(led) {
  if (!led || typeof led !== "object") return false;
  if (!isFiniteNum(led.total_used) || led.total_used < 0) return false;
  if (!isFiniteNum(led.monthly_limit) || led.monthly_limit <= 0) return false;
  if (!isFiniteNum(led.reserve) || led.reserve < 0 || led.reserve >= led.monthly_limit) return false;
  if (!led.buckets || typeof led.buckets !== "object") return false;
  for (const name of Object.keys(DEFAULTS.buckets)) {
    const b = led.buckets[name];
    if (b !== undefined) {
      if (!isFiniteNum(b.used) || b.used < 0 || !isFiniteNum(b.cap) || b.cap < 0) return false;
    }
  }
  return true;
}

// Must be called inside withLock. Returns a validated ledger for the current
// month. Creates a fresh one only when there is nothing to lose (no file, or a
// cleanly-parsed prior month). An EXISTING current-month file that is corrupt
// or semantically invalid is quarantined and replaced with a POISONED ledger.
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
    quarantine();
    console.error("[tavily] ledger unreadable — poisoned (fail-closed) until month rollover or manual reset");
    return poisonLedger();
  }
  // A cleanly-parsed prior month is safe to roll over to zero.
  if (led && typeof led === "object" && led.month !== month && isFiniteNum(led.total_used)) {
    const rolled = freshLedger(led);
    atomicWrite(rolled);
    return rolled;
  }
  // Same month (or a prior month we couldn't trust) → must be fully sane.
  if (led?.month === month && isSaneLedger(led)) {
    // Backfill any bucket the DEFAULTS added since the ledger was written.
    for (const [k, v] of Object.entries(DEFAULTS.buckets)) {
      if (!led.buckets[k]) led.buckets[k] = { ...v };
    }
    return led;
  }
  quarantine();
  console.error("[tavily] ledger invalid — poisoned (fail-closed) until month rollover or manual reset");
  return poisonLedger();
}

function quarantine() {
  try {
    renameSync(LEDGER_PATH, `${LEDGER_PATH}.corrupt.${Date.now()}`);
  } catch {
    /* ignore */
  }
}

// Atomically check the budget AND charge it. Returns:
//   { allowed:true,  month, bucket, total_used, bucket_used, bucket_cap, remaining }
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
      if (led.poisoned) {
        return { allowed: false, reason: "budget ledger poisoned (corrupt/invalid — fail-closed)", remaining };
      }
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
        month: led.month,
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

// Give a reservation back ONLY on a definite non-billed outcome (an HTTP error
// response) — never on an ambiguous network failure, which may have arrived
// after Tavily already billed. Refund is a no-op if the month has rolled over
// since the reservation (so we never deduct from a fresh month's spend), and
// best-effort under contention (a dropped refund is a safe over-count).
export function refund(bucketName, cost, month) {
  const key = resolveBucket(bucketName);
  try {
    withLock(() => {
      const led = loadLocked();
      if (led.poisoned) return; // don't touch a poisoned ledger
      if (month && led.month !== month) return; // reservation was a different month
      led.total_used = Math.max(0, led.total_used - cost);
      const bucket = led.buckets[key];
      if (bucket) bucket.used = Math.max(0, bucket.used - cost);
      atomicWrite(led);
    });
  } catch {
    console.error(`[tavily] refund of ${cost} to "${key}" skipped (ledger busy) — safe over-count`);
  }
}
