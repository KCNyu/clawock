#!/usr/bin/env node
/**
 * Workbench typography contract: one role ladder, no raw declarations.
 *
 * Run: node tests/workbench_typography.spec.js
 * CI:  ci.yml's Decision Studio plugin job runs it with the plugin contract.
 *
 * kcn 2026-11-07: "字体那些也要用统一的规范 不同状态 不同主题 不同情况都要用
 * 规范而不是手写". This file checks the static half (tokens + type table +
 * no literals); tests/workbench_overlap.spec.js checks the computed half
 * (the same role resolves to the same font-size in every state and theme).
 */
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const ROOT = path.join(__dirname, "..");
const PKG = path.join(ROOT, "examples", "dsh", "packages", "clawock-dsh");
const CSS_FILE = path.join(PKG, "src", "styles.module.css");
const CLIENT_FILE = path.join(PKG, "src", "client.ts");
const TABLE_FILE = path.join(ROOT, "docs", "design", "workbench-type.md");
const css = fs.readFileSync(CSS_FILE, "utf8");
const client = fs.readFileSync(CLIENT_FILE, "utf8");
const table = fs.readFileSync(TABLE_FILE, "utf8");

const ROOT_BLOCK = /\.dmt,\s*\.pbc,\s*\.wb\s*\{([\s\S]*?)\}/.exec(css);
assert.ok(ROOT_BLOCK, "the shared type ladder block is present");

function tokens(prefix) {
  const found = new Map();
  const re = new RegExp("--" + prefix + "-[a-z0-9-]+\\s*:\\s*([^;]+);", "g");
  for (const match of ROOT_BLOCK[1].matchAll(re)) found.set(match[0].split(":")[0].trim(), match[1].trim());
  return found;
}

const fsTokens = tokens("fs");
const lhTokens = tokens("lh");
const lsTokens = tokens("ls");
const fwTokens = tokens("fw");

function px(value) {
  const match = /^(-?\d+(?:\.\d+)?)px$/.exec(value.trim());
  return match === null ? null : Number(match[1]);
}

/** Parse the Markdown table into role rows. */
function parseTable(markdown) {
  const rows = [];
  for (const line of markdown.split("\n")) {
    if (!line.trim().startsWith("|")) continue;
    const cells = line.split("|").slice(1, -1).map((cell) => cell.trim());
    if (cells.length !== 6) continue;
    if (cells[0] === "语义角色" || /^-+$/.test(cells[0].replace(/\s/g, ""))) continue;
    rows.push({ role: cells[0], size: cells[1], weight: cells[2], line: cells[3], value: cells[4], where: cells[5] });
  }
  return rows;
}

const rows = parseTable(table);

test("type table: every required role exists, with a real size/weight/line token", () => {
  assert.ok(rows.length >= 12, "the table is not a stub (" + rows.length + " roles)");
  const required = ["页面标题", "分组标题", "行标题", "主指标", "次指标", "说明/meta", "chip", "按钮", "tab", "空态标题", "错误文本", "角标数字"];
  for (const role of required) {
    const row = rows.find((entry) => entry.role === role);
    assert.ok(row, "type table lacks the required role: " + role);
  }
  for (const row of rows) {
    const size = /^`(--fs-[a-z0-9-]+)`$/.exec(row.size);
    const weight = /^`(--fw-[a-z0-9-]+)`$/.exec(row.weight);
    const line = /^`(--lh-[a-z0-9-]+)`$/.exec(row.line);
    assert.ok(size, row.role + ": size must be one --fs-* token, got " + row.size);
    assert.ok(weight, row.role + ": weight must be one --fw-* token, got " + row.weight);
    assert.ok(line, row.role + ": line height must be one --lh-* token, got " + row.line);
    assert.ok(fsTokens.has(size[1]), row.role + ": " + size[1] + " is not defined in the CSS root");
    assert.ok(fwTokens.has(weight[1]), row.role + ": " + weight[1] + " is not defined in the CSS root");
    assert.ok(lhTokens.has(line[1]), row.role + ": " + line[1] + " is not defined in the CSS root");
    const value = fsTokens.get(size[1]);
    assert.equal(row.value, value, row.role + ": table value " + row.value + " != " + size[1] + " (" + value + ")");
    assert.ok(/^`?\.[a-z0-9-]/i.test(row.where.replace(/^`/, "")) || row.where.includes("`.wb-"),
      row.role + ": 'used where' names at least one class");
  }
  // The ladder is one step per role, not a second 0.5px ladder.
  const sizes = [...new Set(rows.map((row) => row.size))];
  assert.equal(sizes.length, new Set([...fsTokens.keys()].filter((name) => name !== "--fs-badge")).size,
    "every --fs-* size (except the badge) is represented by at least one role");
});

test("no raw font-size / line-height / letter-spacing / font-weight declarations", () => {
  const raw = [
    ["font-size", /font-size\s*:\s*[0-9]/g, "font-size"],
    ["line-height", /line-height\s*:\s*[0-9]/g, "line-height"],
    ["letter-spacing", /letter-spacing\s*:\s*[0-9.-]/g, "letter-spacing"],
    ["font-weight", /font-weight\s*:\s*[0-9]/g, "font-weight"],
    ["font shorthand", /font\s*:\s*(?:[0-9]|var\(--fs-[a-z0-9-]+\)\s*\/)/g, "font shorthand"],
  ];
  for (const [label, re] of raw) {
    const hits = [...css.matchAll(re)];
    assert.equal(hits.length, 0, label + " literals remain: " + hits.slice(0, 3).map((hit) => hit[0]).join(", "));
  }
  // Inline styles are part of the contract too (client.ts may not reintroduce a size).
  const inline = [...client.matchAll(/\b(fontSize|lineHeight|letterSpacing|fontWeight)\b\s*:/g)];
  assert.equal(inline.length, 0, "client.ts inline styles set type directly: " + inline.map((hit) => hit[0]).join(", "));
  assert.doesNotMatch(client, /(?:font-size|line-height|letter-spacing)\s*:\s*['"`]?\d/,
    "client.ts embeds a raw type declaration");
});

test("every token used by a rule is defined once in the shared root", () => {
  for (const [property, prefix] of [["font-size", "fs"], ["line-height", "lh"], ["letter-spacing", "ls"], ["font-weight", "fw"]]) {
    const used = new Set([...css.matchAll(new RegExp(property + "\\s*:\\s*var\\(--(" + prefix + "-[a-z0-9-]+)\\)", "g"))]
      .map((match) => "--" + match[1]));
    for (const name of used) {
      assert.ok(prefix === "fs" ? fsTokens.has(name) : prefix === "lh" ? lhTokens.has(name)
        : prefix === "ls" ? lsTokens.has(name) : fwTokens.has(name), property + " uses undefined " + name);
    }
  }
  // No solved value hides in a second alias.
  assert.doesNotMatch(css, /--wb-(?:body|title|badge)-size\s*:/, "the old ad-hoc aliases must stay gone");
});

test("state and theme selectors never change font-size or line-height", () => {
  // Walk top-level rules; a state/theme selector may change colour or a weight
  // token, never the size or the line. @media bodies are walked recursively by
  // the same matcher because they also contain state selectors.
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rule = /([^{}]+)\{([^{}]*)\}/g;
  const bad = [];
  for (const match of stripped.matchAll(rule)) {
    const selector = match[1].trim();
    const body = match[2];
    const stateful = /data-wb-(?:tone|provider-state|provider-signal)|data-ds-dark-theme|:disabled|\[disabled\]|data-wb-providers-(?:empty|loading|error)|data-wb-empty|data-tq-stats-error|prefers-reduced-motion/.test(selector);
    if (!stateful) continue;
    if (/(?:^|;)\s*(?:font-size|line-height)\s*:/.test(body)) bad.push(selector);
  }
  assert.deepEqual(bad, [], "state/theme selectors change type size: " + bad.join(" | "));
});

test("the table documents the host gap and the state/theme rule", () => {
  assert.match(table, /宿主缺口/, "the table must name the host gap");
  assert.match(table, /--dsw-font-family/, "the host family token is named");
  assert.match(table, /明|dark|theme/i, "the theme rule is documented");
  assert.match(table, /颜色|color/i, "state changes are limited to colour/weight");
});
