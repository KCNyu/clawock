#!/usr/bin/env node
// Robustness tests for the Tavily credit ledger (the hard budget guardrail).
// Run: node lib/ledger.test.mjs   (self-contained, uses a throwaway temp path)
//
// Covers the failure modes that make or break a "hard cap": stale/held locks,
// corrupt-file handling, per-bucket and global caps, refunds, prototype-key
// safety. The multi-process concurrency case (N parallel reservers can't exceed
// the cap) is verified separately since it needs real subprocesses.

import { writeFileSync, readFileSync, openSync, closeSync, utimesSync, rmSync, existsSync, mkdtempSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const DIR = mkdtempSync(join(tmpdir(), "tavily-ledger-"));
const LP = join(DIR, "ledger.json");
process.env.TAVILY_LEDGER_PATH = LP;
const { reserve, refund } = await import("./ledger.mjs");

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) pass++; else { fail++; console.log("  FAIL:", m); } };
const wipe = () => { for (const f of readdirSync(DIR)) rmSync(join(DIR, f), { force: true }); };
const read = () => JSON.parse(readFileSync(LP, "utf8"));

// charging + bucket routing
wipe();
let r = reserve("brief", 1); ok(r.allowed && r.total_used === 1 && r.bucket === "brief", "basic charge -> brief=1");
r = reserve("report", 2); ok(r.allowed && r.total_used === 3 && r.bucket_used === 2, "deep charge -> report=2");
r = reserve("nope", 1); ok(r.allowed && r.bucket === "default", "unknown bucket -> default");
r = reserve("__proto__", 1); ok(r.allowed && r.bucket === "default", "prototype key -> default (no pollution)");

// per-bucket cap
wipe();
for (let i = 0; i < 60; i++) reserve("default", 1);
r = reserve("default", 1); ok(!r.allowed && /bucket exhausted/.test(r.reason), "per-bucket cap enforced");
ok(read().buckets.default.used === 60, "bucket never charged past cap");

// global cap + boundary
wipe();
reserve("brief", 1); let l = read(); l.total_used = 949; l.buckets.brief.used = 1; writeFileSync(LP, JSON.stringify(l));
ok(!reserve("brief", 2).allowed, "global cap: 949+2>950 denied");
ok(reserve("brief", 1).allowed && read().total_used === 950, "global cap boundary: 949+1=950 allowed");

// refund (with month guard)
wipe();
let g = reserve("report", 2); refund("report", 2, g.month);
l = read(); ok(l.total_used === 0 && l.buckets.report.used === 0, "refund restores total+bucket");
refund("report", 5, g.month); ok(read().total_used === 0, "refund floors at 0 (never negative)");
reserve("report", 2); refund("report", 2, "1999-01");
ok(read().total_used === 2, "refund with a different month is a no-op (no cross-month deduction)");

// corrupt ledger -> poisoned, quarantined, and stays fail-closed on EVERY call
wipe();
reserve("brief", 5);
writeFileSync(LP, "{ not json ");
r = reserve("brief", 1);
ok(!r.allowed && /poison/.test(r.reason), "corrupt ledger -> deny (poisoned, fail-closed)");
ok(readdirSync(DIR).some(f => f.includes("corrupt")), "corrupt ledger quarantined (not silently zeroed)");
r = reserve("brief", 1);
ok(!r.allowed && /poison|budget/.test(r.reason), "corrupt ledger stays fail-closed on the SECOND call too");
ok(read().total_used >= read().monthly_limit - read().reserve, "poisoned ledger reads as exhausted, not reset to 0");

// semantically invalid ledger (parses fine, bad numbers) -> poisoned too
wipe();
reserve("brief", 1); l = read(); l.total_used = -999; writeFileSync(LP, JSON.stringify(l));
r = reserve("brief", 1);
ok(!r.allowed && /poison/.test(r.reason), "invalid schema (negative total) -> poisoned (fail-closed)");

// array `buckets` parses as object but must be rejected (would reset caps to 0)
wipe();
reserve("brief", 1); l = read(); l.buckets = []; writeFileSync(LP, JSON.stringify(l));
r = reserve("brief", 1);
ok(!r.allowed && /poison/.test(r.reason), "array buckets -> poisoned (not silently cap-reset)");

// malformed PRIOR-month config must NOT carry into the new month
wipe();
reserve("brief", 1); l = read(); l.month = "1999-01"; l.reserve = -1; l.monthly_limit = 999999; writeFileSync(LP, JSON.stringify(l));
r = reserve("brief", 1);
ok(r.allowed, "prior-month rollover proceeds");
l = read();
ok(l.reserve === 50 && l.monthly_limit === 1000, "malformed prior-month config clamped to DEFAULTS on rollover");

// stale lock reclaimed
wipe();
reserve("brief", 1);
const lock = LP + ".lock";
closeSync(openSync(lock, "wx"));
const old = (Date.now() - 60000) / 1000; utimesSync(lock, old, old);
ok(reserve("brief", 1).allowed && read().total_used === 2, "stale lock reclaimed -> proceeds");
ok(!existsSync(lock), "stale lock cleaned up after use");

// fresh held lock -> fail-closed (never runs unlocked)
wipe();
reserve("brief", 1);
const fd = openSync(lock, "wx");
r = reserve("brief", 1);
ok(!r.allowed && /unavailable|busy/.test(r.reason), "held lock -> deny (fail-closed, not fail-open)");
ok(read().total_used === 1, "held-lock denial did NOT write unlocked");
closeSync(fd);

rmSync(DIR, { recursive: true, force: true });
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
