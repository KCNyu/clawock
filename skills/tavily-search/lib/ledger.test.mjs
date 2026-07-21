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

// refund
wipe();
reserve("report", 2); refund("report", 2);
l = read(); ok(l.total_used === 0 && l.buckets.report.used === 0, "refund restores total+bucket");
refund("report", 5); ok(read().total_used === 0, "refund floors at 0 (never negative)");

// corrupt ledger -> fail-closed, quarantined, NOT zeroed
wipe();
reserve("brief", 5);
writeFileSync(LP, "{ not json ");
r = reserve("brief", 1);
ok(!r.allowed && /ledger unavailable/.test(r.reason), "corrupt ledger -> deny (fail-closed)");
ok(readdirSync(DIR).some(f => f.includes("corrupt")), "corrupt ledger quarantined (not silently zeroed)");

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
