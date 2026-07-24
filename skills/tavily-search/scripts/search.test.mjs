#!/usr/bin/env node
// Tavily search.mjs failure-mode tests. A Tavily runtime failure (network error,
// HTTP error, unparseable body) must degrade to exit 0 with the "Web search
// unavailable" contract — never a non-zero exit, because search.mjs is invoked
// mid-turn as OPTIONAL enrichment and a non-zero exit gets upgraded to a
// run-level "Bash failed" that reds the whole cron (regression: 2026-07-20 08:19
// 盘前深度简报). The success path and real caller-bug exit codes must stay intact.
//
// Deterministic + offline: global fetch is stubbed via an --import preload and
// the credit ledger is redirected to a throwaway temp file.
// Run: node scripts/search.test.mjs
import { spawnSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SEARCH = join(HERE, "search.mjs");
const MOCK = join(HERE, "search.test.fetchmock.mjs");

let pass = 0;
let fail = 0;
const ok = (cond, msg) => {
  if (cond) pass++;
  else {
    fail++;
    console.log("  FAIL:", msg);
  }
};

function run(mode, args = ["hello world", "--bucket", "test"]) {
  const dir = mkdtempSync(join(tmpdir(), "tavily-search-"));
  const env = {
    ...process.env,
    TAVILY_API_KEY: "dummy-key",
    TAVILY_LEDGER_PATH: join(dir, "ledger.json"),
  };
  const argv = [];
  if (mode) {
    env.TAVILY_TEST_FETCH_MODE = mode;
    argv.push("--import", MOCK);
  }
  argv.push(SEARCH, ...args);
  return spawnSync("node", argv, { env, encoding: "utf8" });
}

// 1. HTTP error → graceful degrade, exit 0 (not a run-redding non-zero)
let r = run("httpError");
ok(r.status === 0, "httpError: exits 0");
ok(
  /Web search unavailable/.test(r.stdout) && /HTTP 429/.test(r.stdout),
  "httpError: degrade notice with status on stdout",
);

// 2. Network throw → graceful degrade, exit 0
r = run("network");
ok(r.status === 0, "network: exits 0");
ok(
  /Web search unavailable/.test(r.stdout) && /network error/.test(r.stdout),
  "network: degrade notice on stdout",
);

// 3. Malformed JSON body → graceful degrade, exit 0
r = run("badjson");
ok(r.status === 0, "badjson: exits 0");
ok(/unparseable/.test(r.stdout), "badjson: degrade notice on stdout");

// 4. Success path unchanged → exit 0, real results, NO degrade notice
r = run("success");
ok(r.status === 0, "success: exits 0");
ok(
  /## Sources/.test(r.stdout) && /T1/.test(r.stdout) && /ANS/.test(r.stdout),
  "success: prints answer + sources",
);
ok(!/Web search unavailable/.test(r.stdout), "success: no degrade notice");

// 5. Real caller bug (no query) must stay LOUD (exit 2), never swallowed
r = run(null, []);
ok(r.status === 2, "usage: no-args exits 2 (caller bug stays non-zero)");

console.log(`\nsearch.mjs degrade tests: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
