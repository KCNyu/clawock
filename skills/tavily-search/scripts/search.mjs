#!/usr/bin/env node

import { reserve, refund } from "../lib/ledger.mjs";

function usage() {
  console.error(`Usage: search.mjs "query" [-n 5] [--deep] [--topic general|news] [--days 7] [--bucket name]`);
  process.exit(2);
}

const args = process.argv.slice(2);
if (args.length === 0 || args[0] === "-h" || args[0] === "--help") usage();

const query = args[0];
let n = 5;
let searchDepth = "basic";
let topic = "general";
let days = null;
let bucket = "default"; // unbucketed calls are throttled hard on purpose

for (let i = 1; i < args.length; i++) {
  const a = args[i];
  if (a === "-n") {
    n = Number.parseInt(args[i + 1] ?? "5", 10);
    i++;
    continue;
  }
  if (a === "--deep") {
    searchDepth = "advanced";
    continue;
  }
  if (a === "--topic") {
    topic = args[i + 1] ?? "general";
    i++;
    continue;
  }
  if (a === "--days") {
    days = Number.parseInt(args[i + 1] ?? "7", 10);
    i++;
    continue;
  }
  if (a === "--bucket") {
    bucket = args[i + 1] ?? "default";
    i++;
    continue;
  }
  console.error(`Unknown arg: ${a}`);
  usage();
}

const apiKey = (process.env.TAVILY_API_KEY ?? "").trim();
if (!apiKey) {
  // Graceful degradation: Tavily is not configured (skill disabled / no key).
  // Exit 0 with a notice so a faithful call does NOT mark the whole cron run as
  // "Bash failed" / status=error. Callers should fall back to built-in web search.
  console.log(
    "## Web search unavailable\n\n" +
      "Tavily is not configured (TAVILY_API_KEY unset). " +
      "Skip this source and use your built-in web search instead.",
  );
  process.exit(0);
}

// Budget gate (hard guardrail). basic = 1 credit, advanced = 2.
// reserve() charges up front and atomically, so concurrent callers can't blow
// past the cap on a stale snapshot; a definite failure below refunds.
const cost = searchDepth === "advanced" ? 2 : 1;
const gate = reserve(bucket, cost);
if (!gate.allowed) {
  // Graceful degradation, same contract as the no-key path: exit 0 so a
  // faithful cron call is NOT marked failed; caller falls back to built-in search.
  console.log(
    "## Web search unavailable\n\n" +
      `Tavily budget guardrail: ${gate.reason}. ` +
      "Skip this source and use your built-in web search instead.",
  );
  process.exit(0);
}

const body = {
  api_key: apiKey,
  query: query,
  search_depth: searchDepth,
  topic: topic,
  max_results: Math.max(1, Math.min(n, 20)),
  include_answer: true,
  include_raw_content: false,
};

if (topic === "news" && days) {
  body.days = days;
}

let resp;
try {
  resp = await fetch("https://api.tavily.com/search", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
} catch (err) {
  // Network error → Tavily charged nothing, so give the reservation back.
  refund(gate.bucket, cost);
  throw err;
}

if (!resp.ok) {
  // A failed request does not consume Tavily credits, so refund the reservation.
  refund(gate.bucket, cost);
  const text = await resp.text().catch(() => "");
  throw new Error(`Tavily Search failed (${resp.status}): ${text}`);
}

// Success → the reservation stands. Log remaining budget to stderr (not stdout,
// so the report body stays clean).
console.error(
  `[tavily] charged ${cost} to "${gate.bucket}" — month ${gate.total_used} used, ${gate.remaining} left`,
);

const data = await resp.json();

// Print AI-generated answer if available
if (data.answer) {
  console.log("## Answer\n");
  console.log(data.answer);
  console.log("\n---\n");
}

// Print results
const results = (data.results ?? []).slice(0, n);
console.log("## Sources\n");

for (const r of results) {
  const title = String(r?.title ?? "").trim();
  const url = String(r?.url ?? "").trim();
  const content = String(r?.content ?? "").trim();
  const score = r?.score ? ` (relevance: ${(r.score * 100).toFixed(0)}%)` : "";
  
  if (!title || !url) continue;
  console.log(`- **${title}**${score}`);
  console.log(`  ${url}`);
  if (content) {
    console.log(`  ${content.slice(0, 300)}${content.length > 300 ? "..." : ""}`);
  }
  console.log();
}
