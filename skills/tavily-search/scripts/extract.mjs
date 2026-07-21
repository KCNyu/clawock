#!/usr/bin/env node

import { reserve, refund } from "../lib/ledger.mjs";

function usage() {
  console.error(`Usage: extract.mjs "url1" ["url2" ...] [--bucket name]`);
  process.exit(2);
}

const args = process.argv.slice(2);
if (args.length === 0 || args[0] === "-h" || args[0] === "--help") usage();

// Parse args explicitly so the --bucket VALUE is consumed and never mistaken
// for a URL (that would inflate the extract cost and POST a junk URL to Tavily).
let bucket = "extract";
const urls = [];
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === "--bucket") {
    bucket = args[i + 1] ?? bucket;
    i++;
    continue;
  }
  if (a.startsWith("-")) continue; // ignore unknown flags
  urls.push(a);
}

if (urls.length === 0) {
  console.error("No URLs provided");
  usage();
}

const apiKey = (process.env.TAVILY_API_KEY ?? "").trim();
if (!apiKey) {
  // Graceful degradation, matching search.mjs (exit 0, not 1) so a faithful
  // cron call is not marked failed.
  console.log(
    "## Content extraction unavailable\n\n" +
      "Tavily is not configured (TAVILY_API_KEY unset). Use your built-in fetch/scrape instead.",
  );
  process.exit(0);
}

// Budget gate. Tavily bills extract at 1 credit per 5 URLs (basic). reserve()
// charges up front and atomically; a definite failure below refunds.
const cost = Math.max(1, Math.ceil(urls.length / 5));
const gate = reserve(bucket, cost);
if (!gate.allowed) {
  console.log(
    "## Content extraction unavailable\n\n" +
      `Tavily budget guardrail: ${gate.reason}. Use your built-in fetch/scrape instead.`,
  );
  process.exit(0);
}

let resp;
try {
  resp = await fetch("https://api.tavily.com/extract", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      api_key: apiKey,
      urls: urls,
    }),
  });
} catch (err) {
  refund(gate.bucket, cost);
  throw err;
}

if (!resp.ok) {
  refund(gate.bucket, cost);
  const text = await resp.text().catch(() => "");
  throw new Error(`Tavily Extract failed (${resp.status}): ${text}`);
}

console.error(
  `[tavily] extract charged ${cost} to "${gate.bucket}" — month ${gate.total_used} used, ${gate.remaining} left`,
);

const data = await resp.json();

const results = data.results ?? [];
const failed = data.failed_results ?? [];

for (const r of results) {
  const url = String(r?.url ?? "").trim();
  const content = String(r?.raw_content ?? "").trim();
  
  console.log(`# ${url}\n`);
  console.log(content || "(no content extracted)");
  console.log("\n---\n");
}

if (failed.length > 0) {
  console.log("## Failed URLs\n");
  for (const f of failed) {
    console.log(`- ${f.url}: ${f.error}`);
  }
}
