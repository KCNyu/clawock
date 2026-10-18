import { readdir, readFile, realpath, stat } from "node:fs/promises";
import { homedir } from "node:os";
import { join, relative, resolve, sep } from "node:path";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

// Read-only view of the coding agents' shared Markdown memory for an OpenClaw assistant.
// It registers a memory corpus supplement: `memory_search corpus=all` and `memory_get` on a
// `shared-memory/<topic>.md` path return the store's topics. It never writes: the only
// filesystem calls are readdir/readFile/stat/realpath. OpenClaw's short-term recall (what
// dreaming promotes into the assistant's public MEMORY.md) records only its own memory index
// hits, so nothing returned here is promoted.

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

// Private notes surface only in a one-to-one chat with the owner: never in a group or a
// channel, and never in cron or other keyless runs whose output may be published.
export function sessionAllowed(sessionKey: string | undefined): boolean {
  if (!sessionKey) return false;
  const tokens = sessionKey.toLowerCase().split(":").filter(Boolean);
  if (tokens.some((t) => t === "group" || t === "channel" || t === "cron" || t === "subagent")) return false;
  if (tokens.includes("direct") || tokens.includes("dm")) return true;
  return tokens.length === 3 && tokens[0] === "agent" && tokens[2] === "main";
}

type Topic = { rel: string; name: string; description: string; kind?: string; updated?: string; body: string; bodyLine: number; archived: boolean };

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
    kind: field("type"), updated: field("updated"), body: match ? text.slice(match[0].length) : text,
    bodyLine: match ? match[0].split("\n").length - 1 : 0,
  };
}

function terms(query: string): string[] {
  const out = new Set<string>();
  for (const word of query.toLowerCase().match(/[\p{L}\p{N}_-]+/gu) ?? []) {
    if (/\p{Script=Han}/u.test(word) && word.length > 2) {
      for (let i = 0; i < word.length - 1; i++) out.add(word.slice(i, i + 2));  // CJK has no spaces
    } else if (word.length > 1) out.add(word);
  }
  return [...out].slice(0, 24);
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

  return {
    async search(params: { query: string; maxResults?: number; agentSessionKey?: string; corpus?: string }) {
      try {
        if ((params.corpus && params.corpus !== "all") || !sessionAllowed(params.agentSessionKey)) return [];
        const wanted = terms(params.query ?? "");
        if (wanted.length === 0) return [];
        const scored = [];
        for (const rel of await listing()) {
          const topic = await load(rel).catch(() => null);
          if (!topic) continue;
          const name = topic.name.toLowerCase(), desc = topic.description.toLowerCase(), body = topic.body.toLowerCase();
          let weight = 0, matched = 0;
          for (const term of wanted) {
            const w = 4 * count(name, term) + 3 * count(desc, term) + count(body, term);
            if (w > 0) { matched++; weight += w; }
          }
          if (matched === 0) continue;
          const coverage = matched / wanted.length;
          const score = coverage * coverage * (0.5 + 0.5 * Math.min(1, weight / 12)) * (topic.archived ? 0.6 : 1);
          const lines = topic.body.split("\n");
          const first = Math.max(0, lines.findIndex((l) => wanted.some((t) => l.toLowerCase().includes(t))));
          const snippet = [topic.description, ...lines.slice(Math.max(0, first - 1), first + 3)].filter(Boolean).join("\n").slice(0, MAX_SNIPPET);
          scored.push({
            corpus: CORPUS, path: PREFIX + rel, title: topic.name, kind: topic.kind, score, snippet,
            startLine: topic.bodyLine + first + 1, endLine: topic.bodyLine + first + 3, sourceType: CORPUS,
            provenanceLabel: "coding agents' shared memory (read-only)", updatedAt: topic.updated,
          });
        }
        return scored.sort((a, b) => b.score - a.score || a.path.localeCompare(b.path))
          .slice(0, Math.max(1, Math.min(params.maxResults ?? 6, 20)));
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
        return {
          corpus: CORPUS, path: params.lookup, title: topic.name, kind: topic.kind, content: slice.join("\n"),
          fromLine: from, lineCount: slice.length, sourceType: CORPUS,
          provenanceLabel: "coding agents' shared memory (read-only)", updatedAt: topic.updated,
        };
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
}
