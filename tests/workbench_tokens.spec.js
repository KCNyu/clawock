#!/usr/bin/env node
/**
 * Workbench token + primitive contract.
 *
 * kcn 2026-11-08: the Workbench still read as "no single standard — spacing,
 * order, alignment and type are all irregular". #3306/#3307 aligned one batch
 * of values; this test makes the standard structural:
 *
 *   1. one token block, measured from dsh's Automation tasks plugin;
 *   2. the Workbench layer below it may not contain a bare px or #hex;
 *   3. the eight primitives own every visual class the pages use.
 *
 * Scope note: the file also carries the older Decision Mind dashboard sheet.
 * That surface has its own type/colour contract (and its own tests); the
 * Workbench layer begins at the token marker and is the surface this task
 * converts. The gate is therefore closed over the Workbench layer, not over
 * the dashboard's frozen values.
 *
 * Run: node tests/workbench_tokens.spec.js
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
const PRIMITIVES_FILE = path.join(PKG, "src", "workbench-primitives.ts");
const css = fs.readFileSync(CSS_FILE, "utf8");
const client = fs.readFileSync(CLIENT_FILE, "utf8");
const primitives = fs.readFileSync(PRIMITIVES_FILE, "utf8");

const MARKER = "/* wb-tokens:start */";
const END = "/* wb-tokens:end */";
const start = css.indexOf(MARKER);
const end = css.indexOf(END);
assert.ok(start > 0 && end > start, "the Workbench token block markers are present");
const tokens = css.slice(start + MARKER.length, end);
const layer = css.slice(start);

function stripComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, "");
}

/** The layer minus its token block, comments and media-query preludes. */
function declarations(text) {
  return stripComments(text.slice(end + END.length).replace(/^[^\n]*/, ""))
    // A custom property is not allowed in a prelude, so breakpoints stay raw.
    .replace(/@media[^{]*\{/g, "@media {")
    .replace(/@supports[^{]*\{/g, "@supports {");
}

const body = declarations(layer);
const rawPx = [...body.matchAll(/(?<![\w.-])(?:\d+(?:\.\d+)?|\.\d+)px\b/g)].map((m) => m[0]);
const rawHex = [...body.matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((m) => m[0]);

test("the Workbench layer has no bare px or #hex outside the token block", () => {
  assert.deepEqual(rawPx, [], "raw px values remain: " + rawPx.join(", "));
  assert.deepEqual(rawHex, [], "raw hex colours remain: " + rawHex.join(", "));
});

test("no rule anywhere in the stylesheet paints a raw #hex (only token definitions may)", () => {
  // The dashboard above the marker keeps its frozen dimensions, but colour is
  // already a closed alias ladder there too; this pins that half file-wide.
  const noComments = stripComments(css).replace(/--[a-zA-Z0-9-]+\s*:[^;]+;/g, "");
  const stray = [...noComments.matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((match) => match[0]);
  assert.deepEqual(stray, [], "raw hex outside a token definition: " + stray.join(", "));
});

function block(text) {
  const found = {};
  for (const match of text.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) found[match[1]] = match[2].trim();
  return found;
}
const t = block(tokens);
const root = /\.dmt,\s*\.pbc,\s*\.wb\s*\{([\s\S]*?)\}/.exec(css);
assert.ok(root, "the shared type ladder is present");
const rootTokens = block(root[1]);

function resolve(name, depth = 0) {
  assert.ok(depth < 6, "token alias loop at " + name);
  const value = t[name] ?? rootTokens[name];
  assert.ok(value !== undefined, "undefined token " + name);
  const alias = /^var\((--[a-z0-9-]+)\)$/.exec(value);
  return alias === null ? value : resolve(alias[1], depth + 1);
}

test("spacing is the measured 4/8/12/16/20/24/32 scale, one token each", () => {
  const steps = [4, 8, 12, 16, 20, 24, 32];
  for (let index = 0; index < steps.length; index += 1) {
    assert.equal(resolve("--wb-space-" + (index + 1)), steps[index] + "px", "spacing step " + steps[index]);
  }
  assert.equal(Object.keys(t).filter((name) => name.startsWith("--wb-space-")).length, steps.length,
    "no second spacing ladder");
});

test("radius is 8 / 12 / 16", () => {
  assert.equal(resolve("--wb-radius-sm"), "8px");
  assert.equal(resolve("--wb-radius-md"), "12px");
  assert.equal(resolve("--wb-radius-lg"), "16px");
});

test("the four host type pairs are present and used by a role", () => {
  const pairs = new Set();
  for (const [name, value] of Object.entries(t)) {
    if (!name.startsWith("--wb-font-")) continue;
    const line = name.replace("--wb-font-", "--wb-line-");
    if (t[line] === undefined) continue;
    pairs.add(resolve(name) + "/" + resolve(line));
  }
  for (const pair of ["13px/20px", "14px/22px", "20px/28px", "13px/21px"]) {
    assert.ok(pairs.has(pair), "missing host type pair " + pair + " in " + [...pairs].join(", "));
  }
  // The host's row title is 14/23, not a second ladder: it is the measured row.
  assert.ok(t["--wb-line-row"] !== undefined, "the host row line token exists");
});

test("three surfaces, each with background + border + shadow, all host aliases", () => {
  for (const tier of ["flat", "raised", "sheet"]) {
    for (const part of ["bg", "border", "shadow"]) {
      const name = "--wb-surface-" + tier + "-" + part;
      assert.ok(t[name] !== undefined, "missing " + name);
    }
    assert.match(t["--wb-surface-" + tier + "-bg"], /--dsw-alias-bg-(base|layer-[12])/,
      tier + " background must be a host alias");
    assert.match(t["--wb-surface-" + tier + "-border"], /--dsw-alias-border-l[1-4]/,
      tier + " border must be a host alias");
  }
  assert.match(t["--wb-surface-raised-shadow"], /--dsw-shadow-lv1/);
  assert.match(t["--wb-surface-sheet-shadow"], /--dsw-shadow-lv3/);
  assert.equal(t["--wb-surface-flat-shadow"], "none", "flat has no shadow (host bg-base)");
});

test("text is three levels and dividers are two levels, all host aliases", () => {
  for (const level of [1, 2, 3]) {
    assert.match(t["--wb-text-" + level], /--dsw-alias-label-(primary|secondary|tertiary)/);
  }
  assert.match(t["--wb-line-1"], /--dsw-alias-border-l3/);
  assert.match(t["--wb-line-2"], /--dsw-alias-border-l4/);
});

test("the layer defines every Workbench class the client and primitives use", () => {
  const used = new Set();
  for (const source of [client, primitives]) {
    for (const match of source.matchAll(/cx\(([^)]*)\)/g)) {
      for (const name of match[1].matchAll(/'([a-zA-Z0-9-]+)'/g)) {
        if (name[1].startsWith("wb-")) used.add(name[1]);
      }
    }
    for (const match of source.matchAll(/className:\s*'([^']+)'/g)) {
      for (const name of match[1].split(" ")) if (name.startsWith("wb-")) used.add(name);
    }
  }
  const defined = new Set([...layer.matchAll(/\.(wb-[a-zA-Z0-9-]+)/g)].map((match) => match[1]));
  // `wb-prov-` / `wb-act-` are state/variant prefixes, and `wb-hist-wrap` is
  // a layout wrapper the older sheet never styled (it stays unhashed on
  // purpose: the geometry spec finds the list by the hashed `wb-hist`).
  const dynamic = (name) => name === "wb-prov-" || name === "wb-act-" || name === "wb-hist-wrap";
  const missing = [...used].filter((name) => !dynamic(name) && !defined.has(name));
  assert.deepEqual(missing, [], "classes with no rule in the Workbench layer: " + missing.join(", "));
});

test("each primitive is the only place its class is written", () => {
  // The page composes roles; the primitive owns the class mapping. A page
  // that writes `wb-row`/`wb-group`/`tq-d-field` directly has bypassed it.
  for (const name of ["wb-row", "wb-group", "tq-d-field", "wb-act"]) {
    const pageUses = [...client.matchAll(new RegExp("'" + name + "'", "g"))].length;
    assert.equal(pageUses, 0, "client.ts names the primitive class " + name + " directly");
  }
  for (const name of ["Row", "SectionHeader", "Button", "Chip", "Card", "Sheet", "Field", "EmptyState"]) {
    assert.match(primitives, new RegExp("export function " + name + "\\b"), "missing primitive " + name);
  }
});

test("the eight primitives are all composed by the four converted surfaces", () => {
  // Workbench 首頁、任務詳情、History、brief sheet all live in client.ts.
  for (const name of ["Row", "SectionHeader", "Button", "Card", "Sheet", "Field", "EmptyState"]) {
    assert.ok(client.includes("h(" + name + ","), "client.ts does not compose " + name);
  }
  assert.ok(client.includes("h(WorkbenchChip,"), "client.ts does not compose Chip");
});
