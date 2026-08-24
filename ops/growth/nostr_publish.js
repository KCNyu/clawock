#!/usr/bin/env node
/*
 * nostr_publish.js — publish a public kind-1 note to Nostr relays.
 *
 * openclaw's bundled Nostr channel is NIP-04 DM-only, so for public
 * broadcasting (Rick's scorecard posts) we sign + publish directly with
 * nostr-tools (already vendored by the @openclaw/nostr plugin).
 *
 *   NOSTR_PRIVATE_KEY=<nsec|hex> node nostr_publish.js  <<< "post text"
 *   echo "..." | node ops/growth/nostr_publish.js --dry-run
 *
 * Prints the author npub, event id, and an njump.me permalink.
 */
const fs = require("fs");
const path = require("path");
const { createRequire } = require("module");

// --- locate nostr-tools inside the installed openclaw nostr plugin ---------
function findNostrTools() {
  if (process.env.NOSTR_TOOLS_PATH) return process.env.NOSTR_TOOLS_PATH;
  const base = "/root/.openclaw/npm/projects";
  let dirs = [];
  try {
    dirs = fs.readdirSync(base).filter((d) => d.startsWith("openclaw-nostr-"));
  } catch (_) { /* ignore */ }
  for (const d of dirs) {
    const p = path.join(base, d, "node_modules/@openclaw/nostr/node_modules/nostr-tools");
    if (fs.existsSync(p)) return p;
  }
  return "nostr-tools"; // last resort: hope it's on NODE_PATH
}
const nt = createRequire(findNostrTools() + "/")("nostr-tools");
const { finalizeEvent, getPublicKey, SimplePool, nip19 } = nt;

const RELAYS = (process.env.NOSTR_RELAYS ||
  "wss://relay.damus.io,wss://nos.lol,wss://relay.primal.net,wss://relay.nostr.band"
).split(",").map((s) => s.trim()).filter(Boolean);

function parseKey(raw) {
  raw = (raw || "").trim();
  if (!raw) throw new Error("NOSTR_PRIVATE_KEY is empty");
  if (raw.startsWith("nsec")) {
    const { type, data } = nip19.decode(raw);
    if (type !== "nsec") throw new Error("not an nsec key");
    return data; // Uint8Array
  }
  if (/^[0-9a-fA-F]{64}$/.test(raw)) return Uint8Array.from(Buffer.from(raw, "hex"));
  throw new Error("key must be nsec... or 64-char hex");
}

async function main() {
  const dryRun = process.argv.includes("--dry-run");
  const text = fs.readFileSync(0, "utf8").trim(); // stdin
  if (!text) throw new Error("empty post (nothing on stdin)");

  const sk = parseKey(process.env.NOSTR_PRIVATE_KEY);
  const pk = getPublicKey(sk);
  const npub = nip19.npubEncode(pk);

  const evt = finalizeEvent(
    { kind: 1, created_at: Math.floor(Date.now() / 1000), tags: [], content: text },
    sk
  );

  console.error(`author : ${npub}`);
  console.error(`event  : ${evt.id}`);
  console.error(`chars  : ${text.length}`);
  if (dryRun) {
    console.error("DRY RUN — not published.");
    console.log(JSON.stringify(evt, null, 2));
    return;
  }

  const pool = new SimplePool();
  const results = await Promise.allSettled(pool.publish(RELAYS, evt));
  // pool.publish RESOLVES a relay it could not even connect to, with the
  // string "connection failure: …" (nostr-tools abstract-pool.js); only an
  // explicit OK / rejection from a connected relay settles the promise the
  // way its status suggests. Counting settled-fulfilled results as published
  // therefore reported green on a day when every relay was unreachable —
  // accepted, not confirmed, which for a broadcast is a silent drop.
  const failed = [];
  let ok = 0;
  for (const r of results) {
    if (r.status === "fulfilled" && !String(r.value ?? "").startsWith("connection failure")) {
      ok += 1;
    } else {
      const why = r.status === "fulfilled"
        ? String(r.value ?? "")
        : String((r.reason && r.reason.message) || r.reason || "rejected");
      failed.push(why);
    }
  }
  if (failed.length) {
    console.error(`not accepted (${failed.length}/${RELAYS.length}): ${failed.join(" | ")}`);
  }
  console.error(`published to ${ok}/${RELAYS.length} relays`);
  console.error(`view   : https://njump.me/${nip19.neventEncode({ id: evt.id, relays: RELAYS.slice(0, 2) })}`);
  try { pool.close(RELAYS); } catch (_) { /* ignore */ }
  if (ok === 0) process.exit(1);
}

main().catch((e) => { console.error("ERROR:", e.message); process.exit(1); });
