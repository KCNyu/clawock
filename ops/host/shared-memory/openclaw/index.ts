import { appendFile, mkdir, readdir, readFile, realpath, stat } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join, relative, resolve, sep } from "node:path";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

// Read-only view of the coding agents' shared Markdown memory for an OpenClaw assistant.
// It registers a memory corpus supplement: `memory_search corpus=all` and `memory_get` on a
// `shared-memory/<topic>.md` path return the store's topics. It never writes the store: the
// only store calls are readdir/readFile/stat/realpath. Its one write is a private recall
// event (`recall.jsonl` under the state directory), best-effort and outside the store.
// OpenClaw's short-term recall (what dreaming promotes into the assistant's public
// MEMORY.md) records only its own memory index hits, so nothing returned here is promoted.

export const CORPUS = "shared-memory";
const PREFIX = `${CORPUS}/`;
const MAX_SNIPPET = 700;
const DEFAULT_LINES = 200;
const MAX_LINES = 400;
const MAX_FILE_BYTES = 256 * 1024;

// Same list as memctl's SECRET_PATTERNS (tests/test_shared_memory_corpus.py holds them together).
export const SECRET_PATTERNS: RegExp[] = [
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/g,
  /\bsk-(?:ant-)?[A-Za-z0-9_-]{24,}/g,
  /\bgh[pousr]_[A-Za-z0-9]{30,}/g,
  /\bgithub_pat_[A-Za-z0-9_]{30,}/g,
  /\bAKIA[0-9A-Z]{16}\b/g,
  /\bLTAI[0-9A-Za-z]{12,}\b/g,
  /\bxox[baprs]-[A-Za-z0-9-]{10,}/g,
  /\b\d{8,10}:AA[A-Za-z0-9_-]{30,}\b/g,
  /\bctxdb-[A-Za-z0-9]{16,}/g,
  /\bAIza[0-9A-Za-z_-]{35}\b/g,
  /\btvly-[A-Za-z0-9_-]{20,}/g,
  /\btp-[A-Za-z0-9]{30,}/g,
  /\bnsec1[02-9ac-hj-np-z]{50,}/g,
  /\b(?:api[_-]?key|secret|token|passw(?:or)?d)\b["']?\s*[:=]\s*["']?[A-Za-z0-9_\-/+=]{24,}/gi,
];

export function redact(text: string): string {
  return SECRET_PATTERNS.reduce((out, pattern) => out.replace(pattern, "[REDACTED]"), text);
}

// One append per returned topic, in the same private file `memory.py` writes. No query,
// no snippet, no session key. The plugin must still answer a search if this fails.
export function recallLogPath(): string {
  const state = process.env.SHARED_MEMORY_STATE || join(homedir(), ".local", "state", "shared-memory");
  return process.env.SHARED_MEMORY_RECALL_LOG || join(state, "recall.jsonl");
}

export async function recordRecall(source: string, topics: string[]): Promise<void> {
  if (["0", "off", "false"].includes((process.env.SHARED_MEMORY_RECALL || "").toLowerCase())) return;
  const clean = [...new Set(topics
    .map((topic) => topic.replace(/\.md$/, "").trim())
    .filter((topic) => topic && !topic.includes("..") && /^[A-Za-z0-9_./-]+$/.test(topic)))];
  if (!clean.length) return;
  try {
    const path = recallLogPath();
    await mkdir(dirname(path), { recursive: true, mode: 0o700 });
    await appendFile(path, JSON.stringify({ ts: new Date().toISOString(), source, topics: clean }) + "\n",
      { mode: 0o600 });
  } catch {}
}

// The owner and every configured session (direct, group, channel, cron, subagent) may
// read the shared store. Only a keyless call is refused: without a session key the
// plugin cannot tell whether the caller is configured, so it fails closed. This one
// predicate is shared by the corpus supplement and the built-in-index middleware.
export function sessionAllowed(sessionKey: string | undefined): boolean {
  return typeof sessionKey === "string" && sessionKey.trim().length > 0;
}

// The built-in index stores extraPaths files by their path relative to the workspace
// (`../../state/shared-memory-vector/topic.md`); the supplement uses `shared-memory/`.
// Both spellings name the same private store, so one predicate guards the merge layer.
const SHARED_INDEX_DIR = "shared-memory-vector";

export type RecallIsolationOptions = { vectorRoot?: string };

function defaultVectorRoot(): string {
  return join(homedir(), ".openclaw", "state", SHARED_INDEX_DIR);
}

export function isSharedMemoryRecallPath(path: string | undefined, options: RecallIsolationOptions = {}): boolean {
  if (!path) return false;
  const normalized = path.replace(/\\/g, "/").replace(/^\.\//, "");
  if (normalized === CORPUS || normalized.startsWith(PREFIX)) return true;
  if (new RegExp(`(?:^|/)${SHARED_INDEX_DIR}(?:/|$)`).test(normalized)) return true;
  const root = resolve(expandHome(options.vectorRoot || defaultVectorRoot()));
  const candidate = resolve(expandHome(normalized));
  return candidate === root || candidate.startsWith(root + sep);
}

// Reusable at every recall merge point: the corpus supplement, the built-in
// vector/text hits, and any future index layer. Any configured session keeps the
// shared-store results; a keyless call loses them and keeps its own.
export function filterSharedMemoryRecall<T extends { path?: unknown }>(
  results: T[],
  sessionKey: string | undefined,
  options: RecallIsolationOptions = {},
): T[] {
  if (!Array.isArray(results) || sessionAllowed(sessionKey)) return results;
  return results.filter((result) => !isSharedMemoryRecallPath(
    result && typeof result === "object" && typeof result.path === "string" ? result.path : undefined,
    options,
  ));
}

// OpenClaw's built-in memory hits do not pass through the corpus supplement. This
// tool-result middleware is the merge-layer seam: it is registered only for the
// openclaw runtime, sees the real session key, and refuses keyless results before
// the model (or a later recall recorder) can use them. `memory_get` is guarded too,
// because knowing a staging path is enough to read it.
const recallSessionKeys = new Map<string, string>();
const MAX_RECALL_SESSION_KEYS = 256;

// The tool-result middleware context in OpenClaw 2026.7.1-2 carries the runtime
// and cwd but not the session key. `before_tool_call` does carry it, so remember
// the key for the duration of the call and consume it by toolCallId. The map is
// bounded and entries are deleted when the result passes through.
export function rememberRecallSession(toolCallId: string | undefined, sessionKey: string | undefined): void {
  if (!toolCallId || !sessionKey) return;
  if (recallSessionKeys.size >= MAX_RECALL_SESSION_KEYS) {
    const oldest = recallSessionKeys.keys().next().value;
    if (oldest) recallSessionKeys.delete(oldest);
  }
  recallSessionKeys.set(toolCallId, sessionKey);
}

export function createRecallSessionHook() {
  return (event: { toolName?: string; toolCallId?: string }, ctx: { sessionKey?: string; toolCallId?: string }): void => {
    if (event?.toolName !== "memory_search" && event?.toolName !== "memory_get") return;
    rememberRecallSession(event.toolCallId ?? ctx?.toolCallId, ctx?.sessionKey);
  };
}

export function createSharedMemoryRecallMiddleware(_options: RecallIsolationOptions = {}) {
  return async (
    event: { toolName?: string; toolCallId?: string; args?: Record<string, unknown>; result?: unknown },
    ctx: { sessionKey?: string },
  ): Promise<{ result: unknown } | undefined> => {
    const sessionKey = ctx?.sessionKey ?? (event?.toolCallId ? recallSessionKeys.get(event.toolCallId) : undefined);
    if (event?.toolCallId) recallSessionKeys.delete(event.toolCallId);
    if (sessionAllowed(sessionKey)) return undefined;
    if (event?.toolName !== "memory_search" && event?.toolName !== "memory_get") return undefined;
    // Without a session identity no part of a memory result is authorized.
    // Rebuild every response channel: retaining a second text block or an
    // unrecognized details shape would leak the very content being denied.
    const payload = {
      results: [], text: "", disabled: true,
      error: "memory recall is not available without a configured session",
    };
    return { result: {
      isError: true,
      content: [{ type: "text", text: JSON.stringify(payload) }],
      details: payload,
    } };
  };
}

type Topic = { rel: string; name: string; description: string; tags: string; kind?: string; scope?: string; updated?: string; body: string; bodyLine: number; archived: boolean };

function expandHome(path: string): string {
  return path === "~" ? homedir() : path.startsWith("~/") ? join(homedir(), path.slice(2)) : path;
}

function parse(rel: string, text: string): Topic {
  const archived = rel.startsWith("archive/");
  const fallback = rel.replace(/^archive\//, "").replace(/\.md$/, "");
  const match = /^---\n([\s\S]*?)\n---\n?/.exec(text);
  const head = match?.[1] ?? "";
  const field = (key: string) => new RegExp(`^\\s*${key}:\\s*(.+)$`, "m").exec(head)?.[1]?.trim().replace(/^["']|["']$/g, "");
  return {
    rel, archived, name: field("name") || fallback, description: field("description") ?? "",
    tags: field("tags") ?? "", kind: field("type"), scope: field("scope"), updated: field("updated"),
    body: match ? text.slice(match[0].length) : text,
    bodyLine: match ? match[0].split("\n").length - 1 : 0,
  };
}

// Query matching follows memory.py's search (the spec is in ../README.md § Search matching;
// tests/test_shared_memory_corpus.py runs both on the same cases): words split on whitespace and
// punctuation, a Han run of five or more characters is cut into the store's own words, a shorter
// Han word must occur as written (a four-character one the store never writes may match as its two
// halves in one topic), and a topic lacking a Han word as written earns partial credit from the
// longest of the store's words inside it.
const HAN = "\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff";
const QUERY_WORD_RE = new RegExp(`[${HAN}]+|[^\\s${HAN}\\u2000-\\u206f\\u3000-\\u303f\\uff01-\\uff0f\\uff1a-\\uff20\\uff3b-\\uff40\\uff5b-\\uff65]+`, "gu");
const HAN_START = new RegExp(`^[${HAN}]`, "u");
const HAN_LONG = new RegExp(`^[${HAN}]{3,}$`, "u");
const HAN_WORD_MAX = 4;
export const SEARCH_COVERAGE = 0.6;
const MAX_QUERY = 256;
const MAX_WORDS = 16;
const EDGE_PUNCT = /^["'`()[\]{}<>,;:!?]+|["'`()[\]{}<>,;:!?]+$/g;

type Frequency = (piece: string) => number;

export function segmentHan(run: string, frequency: Frequency, longest = HAN_WORD_MAX): string[] {
  type Option = [number, number, number, string[]];
  const best: Option[] = [[0, 0, 0, []]];
  for (let end = 1; end <= run.length; end++) {
    const [dropped, count, rarity, pieces] = best[end - 1];
    let pick: Option = [dropped + 1, count, rarity, pieces];
    for (let size = 2; size <= Math.min(longest, end); size++) {
      const piece = run.slice(end - size, end);
      const df = frequency(piece);
      if (!df) continue;
      const [d, c, r, p] = best[end - size];
      const option: Option = [d, c + 1, r - Math.log(df), [...p, piece]];
      if (option[0] < pick[0] || (option[0] === pick[0] && (option[1] < pick[1] || (option[1] === pick[1] && option[2] < pick[2])))) pick = option;
    }
    best.push(pick);
  }
  return best[run.length][3];
}

export function queryWords(query: string, frequency: Frequency): { words: string[][]; missing: string[] } {
  const words: string[][] = [];
  const missing: string[] = [];
  for (let token of query.toLowerCase().match(QUERY_WORD_RE) ?? []) {
    if (!HAN_START.test(token)) {
      token = token.replace(EDGE_PUNCT, "");
      if (token) words.push([token]);
    } else if (token.length <= HAN_WORD_MAX) {
      const halves = [token.slice(0, 2), token.slice(2)];
      if (token.length < 2 || frequency(token)) words.push([token]);
      else if (token.length === 4 && halves.every((half) => frequency(half))) words.push(halves);
      else missing.push(token);
    } else {
      const pieces = segmentHan(token, frequency);
      words.push(...pieces.map((piece) => [piece]));
      if (pieces.length === 0) missing.push(token);
    }
  }
  const seen = new Set<string>();
  return { words: words.filter((word) => !seen.has(word.join("\0")) && seen.add(word.join("\0"))), missing };
}

export function fallbackPieces(word: string[], frequency: Frequency): string[] {
  if (word.length > 1) return word;
  return HAN_LONG.test(word[0]) ? segmentHan(word[0], frequency, word[0].length - 1) : [];
}

export function wordCredit(haystack: string, word: string[], fallback: string[]): number {
  if (word.every((piece) => haystack.includes(piece))) return 1;
  const longest = Math.max(0, ...fallback.filter((piece) => haystack.includes(piece)).map((piece) => piece.length));
  return longest / word.join("").length;
}

function count(haystack: string, needle: string): number {
  let n = 0;
  for (let at = haystack.indexOf(needle); at !== -1 && n < 5; at = haystack.indexOf(needle, at + needle.length)) n++;
  return n;
}

export function createSharedMemoryCorpus(options: { root?: string; includeArchive?: boolean; warn?: (msg: string) => void }) {
  const root = resolve(expandHome(options.root || "~/.shared-memory"));
  const includeArchive = options.includeArchive !== false;
  const cache = new Map<string, { key: string; topic: Topic }>();
  let warned = false;
  const warn = (error: unknown) => {
    if (!warned) options.warn?.(`shared-memory corpus unavailable: ${String((error as Error)?.message ?? error)}`);
    warned = true;
  };

  async function within(rel: string): Promise<string | null> {
    if (!/^(?:archive\/)?[A-Za-z0-9][A-Za-z0-9_.-]*\.md$/.test(rel) || rel.includes("..")) return null;
    const real = await realpath(root);
    const file = await realpath(join(real, rel));
    return file.startsWith(real + sep) && relative(real, file) === rel ? file : null;
  }

  async function load(rel: string): Promise<Topic | null> {
    const file = await within(rel);
    if (!file) return null;
    const info = await stat(file);
    if (!info.isFile() || info.size > MAX_FILE_BYTES) return null;
    const key = `${info.mtimeMs}:${info.size}`;
    const hit = cache.get(rel);
    if (hit?.key === key) return hit.topic;
    const topic = parse(rel, redact(await readFile(file, "utf8")));
    cache.set(rel, { key, topic });
    return topic;
  }

  async function listing(): Promise<string[]> {
    const names = (await readdir(root)).filter((n) => n.endsWith(".md")).sort();
    if (!includeArchive) return names;
    const archived = await readdir(join(root, "archive")).catch(() => [] as string[]);
    return [...names, ...archived.filter((n) => n.endsWith(".md")).sort().map((n) => `archive/${n}`)];
  }

  // Defensive: exact normalized-snippet duplicates are currently zero, but if a
  // public rule and a private evidence topic ever repeat the same paragraph, keep
  // one hit. Prefer the higher score; on a tie prefer investment/persona (the
  // direct-chat rule) and then the stable path.
  function dedupeScored<T extends { score: number; path: string; snippet: string; scope?: string }>(rows: T[]): T[] {
    const best = new Map<string, T>();
    for (const row of rows) {
      const key = row.snippet.toLowerCase().replace(/\s+/g, " ").trim().slice(0, 300);
      const old = best.get(key);
      if (!old) { best.set(key, row); continue; }
      const rank = (value: string | undefined) => value === "investment" || value === "persona" ? 0 : 1;
      const oldRank = rank(old.scope), newRank = rank(row.scope);
      if (row.score > old.score + 1e-12 || (Math.abs(row.score - old.score) <= 1e-12
          && (newRank < oldRank || (newRank === oldRank && row.path < old.path)))) {
        best.set(key, row);
      }
    }
    return [...best.values()].sort((a, b) => b.score - a.score || a.path.localeCompare(b.path));
  }

  return {
    async search(params: { query: string; maxResults?: number; agentSessionKey?: string; corpus?: string }) {
      try {
        if ((params.corpus && params.corpus !== "all") || !sessionAllowed(params.agentSessionKey)) return [];
        const topics = [];
        for (const rel of await listing()) {
          const topic = await load(rel).catch(() => null);
          if (topic) {
            // Tags are write-time metadata; search them next to the description, but keep
            // snippets on the description/body readers expect.
            const [name, desc, body] = [topic.name, `${topic.description} ${topic.tags}`, topic.body]
              .map((t) => t.toLowerCase());
            topics.push({ topic, name, desc, body, hay: `${name}\0${desc}\0${body}\0${rel.toLowerCase()}` });
          }
        }
        const frequencies = new Map<string, number>();
        const frequency = (piece: string) => {
          if (!frequencies.has(piece)) frequencies.set(piece, topics.filter((t) => t.hay.includes(piece)).length);
          return frequencies.get(piece)!;
        };
        const words = queryWords((params.query ?? "").slice(0, MAX_QUERY), frequency).words.slice(0, MAX_WORDS);
        // Weight each word by how rare it is (BM25's idf); a word no topic contains drops out
        // instead of diluting every topic's coverage.
        const weights = new Map<string[], { w: number; fallback: string[] }>();
        for (const word of words) {
          const df = topics.filter((t) => word.every((piece) => t.hay.includes(piece))).length;
          if (df) weights.set(word, { w: Math.log(1 + (topics.length - df + 0.5) / (df + 0.5)), fallback: fallbackPieces(word, frequency) });
        }
        const total = [...weights.values()].reduce((a, b) => a + b.w, 0);
        const matched = [];
        for (const t of total > 0 ? topics : []) {
          let weight = 0, covered = 0, literal = false;
          const pieces: string[] = [];
          for (const [word, { w, fallback }] of weights) {
            const credit = wordCredit(t.hay, word, fallback);
            if (credit === 0) continue;
            literal ||= credit === 1;
            covered += w * credit;
            // A partly matched word counts the longest of its pieces the topic contains.
            const hit = credit === 1 ? word : [fallback.filter((p) => t.hay.includes(p)).sort((a, b) => b.length - a.length)[0]];
            pieces.push(...hit);
            for (const part of hit) weight += (w * credit / hit.length) * (4 * count(t.name, part) + 3 * count(t.desc, part) + count(t.body, part));
          }
          // A topic must contain some word as written; partial credit only adds to that.
          if (literal) matched.push({ t, coverage: covered / total, weight, pieces });
        }
        // Keep the topics covering most of what the best one covers.
        const best = Math.max(0, ...matched.map((m) => m.coverage));
        const scored = [];
        for (const { t: { topic }, coverage, weight, pieces } of matched.filter((m) => m.coverage >= SEARCH_COVERAGE * best - 1e-9)) {
          const score = coverage * coverage * (0.5 + 0.5 * Math.min(1, weight / 30)) * (topic.archived ? 0.6 : 1);
          const lines = topic.body.split("\n");
          const first = Math.max(0, lines.findIndex((l) => pieces.some((p) => l.toLowerCase().includes(p))));
          const snippet = [topic.description, ...lines.slice(Math.max(0, first - 1), first + 3)].filter(Boolean).join("\n").slice(0, MAX_SNIPPET);
          scored.push({
            corpus: CORPUS, path: PREFIX + topic.rel, title: topic.name, kind: topic.kind,
            scope: topic.scope, score, snippet,
            startLine: topic.bodyLine + first + 1, endLine: topic.bodyLine + first + 3, sourceType: CORPUS,
            provenanceLabel: "coding agents' shared memory (read-only)", updatedAt: topic.updated,
          });
        }
        const hits = dedupeScored(scored)
          .slice(0, Math.max(1, Math.min(params.maxResults ?? 6, 20)));
        await recordRecall("openclaw-supplement",
          hits.map((hit) => hit.path.slice(PREFIX.length).replace(/\.md$/, "")));
        return hits;
      } catch (error) {
        warn(error);
        return [];
      }
    },

    async get(params: { lookup: string; fromLine?: number; lineCount?: number; agentSessionKey?: string }) {
      try {
        if (!sessionAllowed(params.agentSessionKey) || !params.lookup?.startsWith(PREFIX)) return null;
        const rel = params.lookup.slice(PREFIX.length);
        const file = await within(rel);
        if (!file) return null;
        const info = await stat(file);
        if (!info.isFile() || info.size > MAX_FILE_BYTES) return null;
        const all = redact(await readFile(file, "utf8")).split("\n");
        const from = Math.max(1, Math.floor(params.fromLine ?? 1));
        const count = Math.max(1, Math.min(Math.floor(params.lineCount ?? DEFAULT_LINES), MAX_LINES));
        const slice = all.slice(from - 1, from - 1 + count);
        const topic = parse(rel, all.join("\n"));
        const result = {
          corpus: CORPUS, path: params.lookup, title: topic.name, kind: topic.kind, content: slice.join("\n"),
          fromLine: from, lineCount: slice.length, sourceType: CORPUS,
          provenanceLabel: "coding agents' shared memory (read-only)", updatedAt: topic.updated,
        };
        await recordRecall("openclaw-get", [rel.replace(/\.md$/, "")]);
        return result;
      } catch (error) {
        warn(error);
        return null;
      }
    },
  };
}

export default function register(api: OpenClawPluginApi) {
  const config = (api.pluginConfig ?? {}) as Record<string, unknown>;
  api.registerMemoryCorpusSupplement(createSharedMemoryCorpus({
    root: typeof config.root === "string" ? config.root : undefined,
    includeArchive: config.includeArchive !== false,
    warn: (msg) => api.logger?.warn?.(msg),
  }));
  // The middleware is the extraPaths merge-layer gate. It is on by default so a
  // future `agents.defaults.memorySearch.extraPaths` change cannot make the
  // built-in index return private notes to a keyless session.
  if (config.isolateBuiltinIndex !== false && typeof api.registerAgentToolResultMiddleware === "function") {
    if (typeof api.on === "function") api.on("before_tool_call", createRecallSessionHook());
    api.registerAgentToolResultMiddleware(createSharedMemoryRecallMiddleware({
      vectorRoot: typeof config.vectorRoot === "string" ? config.vectorRoot : undefined,
    }), { runtimes: ["openclaw"] });
  }
}
