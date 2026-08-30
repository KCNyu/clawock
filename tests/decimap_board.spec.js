#!/usr/bin/env node
"use strict";

// The decision map, loaded as the real page against the real payload.
//
// It used to be four stacked views of one join: a status bar, 33 equal-sized
// cards, a signal x action table holding the *same* buckets the cards held, and
// a timeline. Two of those were the same data drawn twice, and the card grid
// gave a source that saw 12% of the book exactly as much area as one that saw
// 42% — on the page whose first number is coverage. It is now one board.
//
// These assertions are the ones that would let it silently regress: that the
// board is a tree over published roll-ups rather than sums taken in the browser,
// that a cell's colour never becomes its only channel, and that the page itself
// does not scroll sideways on a phone while the board does.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const SITE = path.resolve(ROOT, "site");
const LAYOUT = path.resolve(SITE, "_layouts/default.html");
const PAGE = path.resolve(SITE, "decimap/index.html");
const PAYLOAD = path.resolve(ROOT, "assets/data/decision_map.json");

/** Resolve the subset of Liquid the layout and the page use, as Jekyll would. */
function render() {
  const body = fs.readFileSync(PAGE, "utf8").replace(/^---[\s\S]*?---\n/, "");
  return fs.readFileSync(LAYOUT, "utf8")
    .replace(/\{\{\s*'([^']*)'\s*\|\s*relative_url\s*\}\}/g, "$1")
    .replace(/\{%\s*if [^%]*%\}([\s\S]*?)\{%\s*endif\s*%\}/g, "$1")
    .replace(/\{\{\s*content\s*\}\}/g, body)
    .replace(/\{%[\s\S]*?%\}/g, "")
    .replace(/\{\{[\s\S]*?\}\}/g, "");
}

function serve(html) {
  return http.createServer((request, response) => {
    const name = new URL(request.url, "http://localhost").pathname;
    if (name === "/decimap/" || name === "/") {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end(html);
      return;
    }
    const root = name.startsWith("/assets/data/") ? ROOT : SITE;
    const file = path.resolve(root, name.replace(/^\/+/, ""));
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file)
        || fs.statSync(file).isDirectory()) {
      response.writeHead(404).end("not found");
      return;
    }
    response.writeHead(200, {
      "content-type": name.endsWith(".json")
        ? "application/json; charset=utf-8" : "text/plain; charset=utf-8",
      "cache-control": "no-store",
    });
    fs.createReadStream(file).pipe(response);
  });
}

async function open(browser, base, width) {
  const context = await browser.newContext({
    viewport: { width, height: 1000 }, hasTouch: width < 600, isMobile: width < 600 });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(String(error)));
  await page.goto(base, { waitUntil: "networkidle" });
  await page.waitForSelector("#dm-board tbody tr");
  return { context, page, errors };
}

async function theBoardIsATreeOverThePublishedRollUps(browser, base, payload) {
  const { context, page, errors } = await open(browser, base, 1280);
  assert.deepEqual(errors, [], `page errors: ${errors.join(" | ")}`);

  const kinds = payload.source_kind_cards.length;
  assert.equal(await page.evaluate(() =>
    document.querySelectorAll("#dm-board tbody tr").length), kinds,
    "the board opens on one row per source kind");

  // The whole reason the roll-up is published: expanding must not change what
  // the parent row says, and the parent must not be the sum of its children.
  const before = await page.textContent("#dm-board tbody tr:first-child .dm-covtext");
  await page.click("#dm-board .dm-twist");
  const rowsAfter = await page.evaluate(() =>
    document.querySelectorAll("#dm-board tbody tr").length);
  const first = payload.source_kind_cards[0];
  assert.equal(rowsAfter, kinds + first.signals.length,
    "expanding a kind reveals exactly its signals");
  assert.equal(await page.textContent("#dm-board tbody tr:first-child .dm-covtext"),
    before, "the parent row's coverage changed when it was expanded");

  const childSum = payload.info_source_cards
    .filter(card => card.source_kind === first.signal)
    .reduce((total, card) => total + card.decisions_joined, 0);
  assert(first.decisions_joined < childSum,
    `${first.signal}: the roll-up (${first.decisions_joined}) is not smaller than `
    + `the sum of its signals (${childSum}) — this fixture cannot prove the `
    + "browser is not summing");
  assert((await page.textContent("#dm-board tbody tr:first-child .dm-covtext"))
    .includes(String(first.decisions_joined)),
    "the parent row prints the published roll-up");
  await context.close();
}

async function noCellUsesColourAsItsOnlyChannel(browser, base) {
  const { context, page } = await open(browser, base, 1280);
  const cells = await page.evaluate(() =>
    [...document.querySelectorAll("#dm-board .dm-cell")].map(cell => ({
      n: cell.querySelector(".dm-n").textContent.trim(),
      median: cell.querySelector(".dm-m").textContent.trim(),
      tinted: getComputedStyle(cell).backgroundColor,
      label: cell.getAttribute("aria-label") || "",
    })));
  assert(cells.length >= 10, `only ${cells.length} cells on the board`);
  for (const cell of cells) {
    assert(/^\d+$/.test(cell.n), `cell count is not a number: ${cell.n}`);
    assert(/^[+-]/.test(cell.median) || cell.median === "—",
      `a tinted cell must print its sign, got "${cell.median}"`);
    assert(cell.label.includes("胜率"),
      "every cell carries its own numbers in an accessible label");
  }
  // And a tint actually happens, or the assertion above is vacuous.
  assert(cells.some(cell => cell.tinted !== cells[0].tinted)
    || cells.some(cell => cell.median.startsWith("+"))
      && cells.some(cell => cell.median.startsWith("-")),
    "no cell on the board is tinted at all");
  await context.close();
}

async function aCellOpensTheDecisionsItCounts(browser, base) {
  const { context, page } = await open(browser, base, 1280);
  await page.click("#dm-board .dm-cell");
  await page.waitForSelector(".dm-drawer.is-open");
  const heading = await page.textContent(".dm-drawer h3");
  assert(heading.includes("·"), `drawer heading is not "source · action": ${heading}`);
  const hits = await page.evaluate(() =>
    document.querySelectorAll(".dm-hits button").length);
  assert(hits > 0, "the bucket drawer listed no decisions");
  await page.click(".dm-hits button");
  await page.waitForTimeout(120);
  assert((await page.textContent(".dm-drawer")).includes("决策时的信号"),
    "a decision in the bucket does not open its own snapshot");
  await context.close();
}

async function thePageNeverScrollsSidewaysButTheBoardDoes(browser, base) {
  for (const width of [320, 390, 1280]) {
    const { context, page } = await open(browser, base, width);
    const measured = await page.evaluate(() => {
      const wrap = document.querySelector(".dm-board-wrap");
      const source = document.querySelector("#dm-board .dm-src");
      return {
        page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        board: wrap.scrollWidth - wrap.clientWidth,
        sticky: getComputedStyle(source).position,
      };
    });
    assert(measured.page <= 1,
      `${width}px: the document scrolls sideways by ${measured.page}px`);
    assert.equal(measured.sticky, "sticky",
      `${width}px: the source column must stay put while the actions scroll`);
    if (width < 600) {
      assert(measured.board > 0,
        `${width}px: a nine-column board that needs no scroll is suspicious`);
    }
    await context.close();
  }
}

async function theKpiStripPrintsWhatThePayloadHolds(browser, base, payload) {
  const { context, page } = await open(browser, base, 1280);
  const text = (await page.textContent("#dm-kpi")).replace(/\s+/g, "");
  for (const value of [payload.kpi.decisions, payload.kpi.sessions,
                       payload.kpi.tickers, payload.kpi.signals_referenced]) {
    assert(text.includes(String(value)),
      `the KPI strip does not print ${value}; it must echo the payload, not count`);
  }
  assert(text.includes(payload.kpi.panel_as_of),
    "the panel's own as_of is not named beside the map's");
  if (payload.degradation.level !== "full") {
    assert(text.includes(payload.degradation.level),
      "a degraded payload must say so in the strip");
  }
  await context.close();
}

async function main() {
  if (!fs.existsSync(PAYLOAD)) {
    console.log("decimap board contract: skipped, no assets/data/decision_map.json");
    return;
  }
  const payload = JSON.parse(fs.readFileSync(PAYLOAD, "utf8"));
  const server = serve(render());
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}/decimap/`;
  const executablePath = process.env.CHROME_EXE || undefined;
  const browser = await chromium.launch(executablePath ? {
    executablePath, args: ["--no-sandbox"],
  } : {});
  try {
    await theBoardIsATreeOverThePublishedRollUps(browser, base, payload);
    await noCellUsesColourAsItsOnlyChannel(browser, base);
    await aCellOpensTheDecisionsItCounts(browser, base);
    await thePageNeverScrollsSidewaysButTheBoardDoes(browser, base);
    await theKpiStripPrintsWhatThePayloadHolds(browser, base, payload);
    console.log("decimap board contract: ok");
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
