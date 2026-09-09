#!/usr/bin/env node
"use strict";

// The decision map, measured in the place it now lives.
//
// 2026-09-09: this was a standalone page at /decimap/ with its own header entry.
// It answers "which sources stood next to which action, and what happened
// after" — the question the dashboard's Reflect tab is for — so the board, the
// timeline and the drawer moved into a card there, and the page became a
// redirect. The contract did not change: it drives the same ids, now inside the
// dashboard, reached by deep-linking `#reflect`.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const SITE = path.resolve(ROOT, "site");
const PAYLOAD = path.resolve(ROOT, "assets/data/decision_map.json");
// Everything after the first paint reads the data branch. Left unrouted it puts
// a live call to raw.githubusercontent.com on CI's critical path for bytes that
// are already sitting in assets/data (same reasoning as dashboard_tab_runtime).
const LIVE_DATA_ORIGIN = "https://raw.githubusercontent.com/KCNyu/clawock/data-plane/";
const MIME = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

function serve() {
  return http.createServer((request, response) => {
    const urlPath = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
    const relative = urlPath === "/" ? "index.html" : urlPath.replace(/^\/+/, "");
    const sourceRoot = relative.startsWith("assets/data/") ? ROOT : SITE;
    const filename = path.resolve(sourceRoot, relative);
    if (!filename.startsWith(sourceRoot + path.sep) || !fs.existsSync(filename)
        || fs.statSync(filename).isDirectory()) {
      response.writeHead(404).end("not found");
      return;
    }
    response.writeHead(200, {
      "content-type": MIME[path.extname(filename)] || "application/octet-stream",
      "cache-control": "no-store",
    });
    fs.createReadStream(filename).pipe(response);
  });
}

/** Serve every payload from the tree, with `decision_map.json` optionally patched. */
async function routeData(page, patchedMap) {
  const answer = async route => {
    const name = path.basename(new URL(route.request().url()).pathname);
    if (patchedMap && name === "decision_map.json") {
      return route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: patchedMap,
      });
    }
    const file = path.resolve(ROOT, "assets/data", name);
    if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: "not found" });
    await route.fulfill({
      status: 200,
      headers: { "content-type": "application/json; charset=utf-8" },
      body: fs.readFileSync(file, "utf8"),
    });
  };
  await page.route(LIVE_DATA_ORIGIN + "**", answer);
  if (patchedMap) await page.route("**/assets/data/decision_map.json*", answer);
}

async function open(browser, base, width, patchedMap) {
  const context = await browser.newContext({
    viewport: { width, height: 1000 }, hasTouch: width < 600, isMobile: width < 600 });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(String(error)));
  await routeData(page, patchedMap);
  // The card lives in Reflect; the hash is the dashboard's own deep link.
  await page.goto(base + "#reflect", { waitUntil: "networkidle" });
  await page.waitForSelector("#dm-board tbody tr", { timeout: 20000 });
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

async function theDrawerTrapsFocusAndGivesItBack(browser, base) {
  /* The drawer is modal for the mouse — scrim, Escape — and until #1350 it was
     not modal for the keyboard: Tab walked straight out of it into the board
     behind the scrim, and closing dropped focus on <body>, so a reader lost
     their place in a 741-row table.

     Behavioural on purpose. `inert` is the mechanism, but asserting the
     attribute would pass on a page where the drawer never opens; what has to
     hold is that the tabbing reader cannot leave and gets their cell back. */
  const { context, page } = await open(browser, base, 1280);
  await page.evaluate(() => document.querySelector("#dm-board .dm-cell").focus());
  const opener = await page.evaluate(() => {
    const cell = document.querySelector("#dm-board .dm-cell");
    cell.click();
    return cell.textContent.trim();
  });
  await page.waitForSelector(".dm-drawer.is-open");

  // 抽屉与遮罩挂在 <body> 下（面板是 content-visibility: auto ⇒ paint
  // containment，position:fixed 的后代会被锁进面板的盒子）。所以「背景」是
  // body 的其余子节点：顶栏、tab 条、整个 pager、页脚，一个都不许留下。
  const outside = await page.evaluate(() =>
    [...document.body.children]
      .filter(el => el.id !== "dm-drawer" && el.id !== "dm-scrim"
        && el.tagName !== "SCRIPT" && !el.inert)
      .map(el => el.id || el.tagName));
  assert.deepEqual(outside, [],
    `these siblings stayed reachable behind the open drawer: ${outside.join(", ")}`);

  // 12 tabs only proves the trap holds while the drawer is long enough to
  // absorb them — that is exactly how this contract went green on a page whose
  // header links were never inerted (a smaller payload, no code change, later
  // made Tab reach them). Enumerate instead: nothing focusable anywhere on the
  // page may be reachable while the drawer is open.
  const reachable = await page.evaluate(() => {
    const drawer = document.getElementById("dm-drawer");
    const FOCUSABLE = "a[href], button, input, select, textarea, [tabindex]";
    return [...document.querySelectorAll(FOCUSABLE)]
      .filter(el => !drawer.contains(el) && !el.closest("[inert]") && !el.inert
        && el.offsetParent !== null)
      .map(el => el.id || `${el.tagName}.${el.className}`);
  });
  assert.deepEqual(reachable, [],
    `these controls stayed in the tab order behind the open drawer: ${reachable.join(", ")}`);

  for (let i = 0; i < 12; i++) await page.keyboard.press("Tab");
  const stillInside = await page.evaluate(() =>
    document.getElementById("dm-drawer").contains(document.activeElement));
  assert(stillInside, "12 tabs walked focus out of the open drawer");

  await page.keyboard.press("Escape");
  await page.waitForTimeout(80);
  const back = await page.evaluate(() => ({
    id: document.activeElement && document.activeElement.id,
    tag: document.activeElement && document.activeElement.tagName,
    text: document.activeElement && document.activeElement.textContent.trim(),
    inertLeft: [...document.getElementById("decimap").children].filter(el => el.inert).length,
  }));
  assert.equal(back.inertLeft, 0, "closing the drawer left the page inert");
  assert.notEqual(back.tag, "BODY",
    "closing the drawer dropped focus on <body> instead of the cell that opened it");
  assert.equal(back.text, opener,
    `focus came back to ${back.tag}#${back.id}, not the cell that opened the drawer`);
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

// The refutation sentence is served a payload that carries the block, rather
// than whichever payload the publisher last committed. The block appears on
// master the first time the publisher runs after this merges, and a browser
// assertion that only fires once the artifact catches up is an assertion that
// has never run.
async function theCaveatReportsWhatSurvivedItsPlacebo(browser, base, payload) {
  const patched = JSON.parse(JSON.stringify(payload));
  patched.signal_panel = patched.signal_panel || {};
  patched.signal_panel.refutation = {
    t1: { signals: 33, collecting: 3, fails_placebo: 30, one_name_flips_it: 0,
          survives_refutation: 0,
          interval_clears_zero_but_placebo_does_not: ["factor.rank.relative_strength"] },
    t5: { signals: 33, collecting: 3, fails_placebo: 22, one_name_flips_it: 0,
          survives_refutation: 8, interval_clears_zero_but_placebo_does_not: [] },
    t20: { signals: 33, collecting: 27, fails_placebo: 2, one_name_flips_it: 0,
           survives_refutation: 4, interval_clears_zero_but_placebo_does_not: [] },
  };
  {
    const { context, page } = await open(browser, base, 1280, JSON.stringify(patched));
    const t5 = (await page.textContent("#dm-caveat")).replace(/\s+/g, "");
    assert(t5.includes("8/33"),
      `the caveat does not report the t5 survivor count: ${t5}`);
    assert(!t5.includes("factor.rank.relative_strength"),
      "nothing is contested at t5 in this fixture; naming a signal there is wrong");

    await page.click('#dm-horizon button[data-h="t1"]');
    await page.waitForTimeout(120);
    const t1 = (await page.textContent("#dm-caveat")).replace(/\s+/g, "");
    assert(t1.includes("0/33"),
      `switching horizon did not move the survivor count: ${t1}`);
    assert(t1.includes("factor.rank.relative_strength"),
      "a signal whose interval and whose own placebo disagree must be named");
    await context.close();
  }
}


// 时间线画的是真 payload，不是一份写死 left 的合成 fixture。
//
// 2026-09-09 实测：`codes.plan_date[0]` 是空串，第 0 条决策正好用它 ⇒ 轴的
// 起点是 `Date.parse('')` = NaN ⇒ 每个点的 left 都是 "NaN%" ⇒ 浏览器丢掉这条
// 声明 ⇒ 18 行里 800 多个标记全叠在 x=0。线上那张独立页也一直是这么坏着的：
// 唯一碰过时间线的断言用的是自己造的 dots（left 写死 12/34/61/88%），所以它
// 永远绿。这条闸改成量真数据画出来的位置。
async function theTimelineSpreadsRealDatesAcrossItsAxis(browser, base) {
  const { context, page } = await open(browser, base, 1280);
  const timeline = await page.evaluate(async () => {
    document.querySelector("#dm-timeline-note > summary").click();
    await new Promise(resolve => setTimeout(resolve, 60));
    const dots = [...document.querySelectorAll("#dm-timeline .dm-dot")];
    const lefts = dots.map(dot => dot.style.left);
    return {
      rows: document.querySelectorAll("#dm-timeline .dm-row").length,
      dots: dots.length,
      unplaced: lefts.filter(left => !/^-?\d+(\.\d+)?%$/.test(left)).length,
      distinct: new Set(lefts).size,
      max: Math.max(...lefts.map(parseFloat).filter(n => !isNaN(n))),
      unnamed: [...document.querySelectorAll("#dm-timeline .dm-row b")]
        .filter(name => !name.textContent.trim()).length,
      undated: (document.getElementById("dm-undated") || {}).textContent || "",
    };
  });
  assert(timeline.rows > 1 && timeline.dots > 20,
    `the timeline drew ${timeline.dots} markers over ${timeline.rows} rows`);
  assert.equal(timeline.unplaced, 0,
    `${timeline.unplaced} markers carry no usable left — they all stack on the axis origin`);
  assert(timeline.distinct > 10,
    `every marker landed on ${timeline.distinct} distinct position(s): the axis collapsed`);
  assert(timeline.max > 90,
    `the rightmost marker sits at ${timeline.max}% — the axis is not spanning its own range`);
  assert.equal(timeline.unnamed, 0, "a timeline row has no ticker name");
  // 放不上轴的那些不许无声消失。
  const payload = JSON.parse(fs.readFileSync(PAYLOAD, "utf8"));
  const undated = (payload.decisions.plan_date || [])
    .filter(code => !(payload.codes.plan_date || [])[code]).length;
  if (undated) {
    assert(timeline.undated.includes(String(undated)),
      `${undated} decisions have no plan date and the card never says so: `
      + `"${timeline.undated}"`);
  }
  await context.close();
}

async function main() {
  if (!fs.existsSync(PAYLOAD)) {
    console.log("decimap board contract: skipped, no assets/data/decision_map.json");
    return;
  }
  const payload = JSON.parse(fs.readFileSync(PAYLOAD, "utf8"));
  const server = serve();
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}/`;
  const executablePath = process.env.CHROME_EXE || undefined;
  const browser = await chromium.launch(executablePath ? {
    executablePath, args: ["--no-sandbox"],
  } : {});
  try {
    await theBoardIsATreeOverThePublishedRollUps(browser, base, payload);
    await noCellUsesColourAsItsOnlyChannel(browser, base);
    await aCellOpensTheDecisionsItCounts(browser, base);
    await theDrawerTrapsFocusAndGivesItBack(browser, base);
    await thePageNeverScrollsSidewaysButTheBoardDoes(browser, base);
    await theTimelineSpreadsRealDatesAcrossItsAxis(browser, base);
    await theKpiStripPrintsWhatThePayloadHolds(browser, base, payload);
    await theCaveatReportsWhatSurvivedItsPlacebo(browser, base, payload);
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
