#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const DETAIL_PATH = "/assets/js/dashboard.render.js";
const TABS = ["drill", "risk", "market", "plan", "reflect"];
// Everything after the first paint reads the data branch instead of this origin
// (#367). Every page here stubs it: left unrouted it would put a live call to
// raw.githubusercontent.com on CI's critical path, and the bytes it would return
// are the ones already sitting in assets/data.
const LIVE_DATA_ORIGIN = "https://raw.githubusercontent.com/KCNyu/clawock/data-plane/";
const MIME = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

function serveWorkspace() {
  return http.createServer((request, response) => {
    const urlPath = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
    const relative = urlPath === "/" ? "index.html" : urlPath.replace(/^\/+/, "");
    const sourceRoot = relative.startsWith("assets/data/")
      ? ROOT
      : path.resolve(ROOT, "site");
    const filename = path.resolve(sourceRoot, relative);
    if (!filename.startsWith(sourceRoot + path.sep) || !fs.existsSync(filename) || fs.statSync(filename).isDirectory()) {
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

// Records which data files were served from the live branch, so a test can
// assert both that the first paint never went there and that a poll always does.
async function stubLiveOrigin(page, options = {}) {
  const served = [];
  await page.route(LIVE_DATA_ORIGIN + "**", async route => {
    const name = path.basename(new URL(route.request().url()).pathname);
    served.push(name);
    if (options.fail) return route.abort("failed");
    const file = path.resolve(ROOT, "assets/data", name);
    if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: "not found" });
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "access-control-allow-origin": "*",
      },
      body: fs.readFileSync(file, "utf8"),
    });
  });
  return served;
}

function observe(page) {
  const result = { detailRequests: 0, fullRequests: 0, failures: [], errors: [] };
  page.on("request", request => {
    const pathname = new URL(request.url()).pathname;
    if (pathname === DETAIL_PATH) result.detailRequests += 1;
    // Counted on either origin: the point of the assertion is that detail tabs
    // share one request for the full document, not where it was served from.
    if (pathname.endsWith("/assets/data/dashboard.json")) result.fullRequests += 1;
  });
  page.on("response", response => {
    const url = new URL(response.url());
    if (url.hostname === "127.0.0.1" && response.status() >= 400) {
      result.failures.push(`${response.status()} ${url.pathname}`);
    }
  });
  page.on("pageerror", error => result.errors.push(error.message));
  return result;
}

async function waitForData(page) {
  await page.waitForFunction(() => {
    const panel = document.querySelector('.panel[data-panel="hero"]');
    return DATA?.projection === "overview" &&
      !panel?.hasAttribute("aria-busy") &&
      !panel?.querySelector(".card.is-pending");
  });
}

async function waitForTab(page, tab) {
  await page.waitForFunction(tab => {
    const panel = document.querySelector(`.panel[data-panel="${tab}"]`);
    const coreReady = tab === "hero"
      ? DATA?.projection === "overview"
      : Array.isArray(DATA?.snapshots);
    return panel?.classList.contains("active") &&
      coreReady &&
      !panel.hasAttribute("aria-busy") &&
      !panel.querySelector(".card.is-pending");
  }, tab);
}

async function dispatchTouch(session, type, points) {
  await session.send("Input.dispatchTouchEvent", { type, touchPoints: points });
}

async function testRuntime(browser, base) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const state = observe(page);
  await stubLiveOrigin(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  assert.equal(state.detailRequests, 0, "Overview downloaded the detail renderer");
  assert.equal(state.fullRequests, 0, "Overview downloaded the full dashboard document");
  await page.evaluate(() => {
    const original = window.render;
    window.__coreRenderCalls = 0;
    window.render = (...args) => {
      window.__coreRenderCalls += 1;
      return original(...args);
    };
  });
  await page.evaluate(() => loadData(false));
  assert.equal(await page.evaluate(() => window.__coreRenderCalls), 0,
    "unchanged Overview poll replayed the core renderer");

  for (const tab of TABS) {
    await page.click(`.tab-btn[data-tab="${tab}"]`);
    await waitForTab(page, tab);
  }
  assert.equal(state.detailRequests, 1, "detail tabs did not share one bundle request");
  assert.equal(state.fullRequests, 1, "detail tabs did not share one full dashboard request");
  assert.deepEqual(state.failures, []);
  assert.deepEqual(state.errors, []);

  const deep = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const deepState = observe(deep);
  await stubLiveOrigin(deep);
  await deep.goto(base + "#reflect", { waitUntil: "domcontentloaded" });
  await waitForTab(deep, "reflect");
  assert.equal(deepState.detailRequests, 1, "deep link did not load one detail bundle");
  assert.equal(deepState.fullRequests, 1, "deep link did not load one full dashboard");
  assert.deepEqual(deepState.failures, []);
  assert.deepEqual(deepState.errors, []);

  const rapid = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const rapidState = observe(rapid);
  await stubLiveOrigin(rapid);
  await rapid.route(`**${DETAIL_PATH}`, async route => {
    await new Promise(resolve => setTimeout(resolve, 250));
    await route.continue();
  });
  await rapid.goto(base, { waitUntil: "networkidle" });
  await waitForData(rapid);
  await rapid.evaluate(tabs => tabs.forEach(tab =>
    document.querySelector(`.tab-btn[data-tab="${tab}"]`).click()), TABS);
  await waitForTab(rapid, "reflect");
  assert.equal(rapidState.detailRequests, 1, "rapid activation duplicated the bundle request");
  assert.equal(rapidState.fullRequests, 1, "rapid activation duplicated the full dashboard request");
  assert.deepEqual(rapidState.failures, []);
  assert.deepEqual(rapidState.errors, []);

  const mismatch = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const mismatchState = observe(mismatch);
  await stubLiveOrigin(mismatch);
  let fullAttempt = 0;
  await mismatch.route(/\/assets\/data\/dashboard\.json(?:\?.*)?$/, async route => {
    fullAttempt += 1;
    if (fullAttempt > 1) return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    body.generated_at = "1999-01-01T00:00:00Z";
    await route.fulfill({
      status: response.status(),
      headers: { ...response.headers(), "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  });
  await mismatch.goto(base + "#risk", { waitUntil: "domcontentloaded" });
  await waitForTab(mismatch, "risk");
  assert.equal(fullAttempt, 2,
    "generation mismatch was not rejected and retried without cache");
  assert.deepEqual(mismatchState.failures, []);
  assert.deepEqual(mismatchState.errors, []);
}

async function testLiveDataOrigin(browser, base) {
  // The first paint must stay on this origin. `overview.json` is the only fetch
  // on the LCP path, so a second origin's handshake there is paid by every cold
  // visit — Lighthouse included — to save a wait nobody is watching yet.
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const state = observe(page);
  const served = await stubLiveOrigin(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  assert.deepEqual(served, [], "the first paint reached across origins for its data");

  // Every poll after it must read the branch, which is ~14 minutes ahead of
  // this origin during a session (#367). A poll that keeps reading Pages is the
  // regression this whole change exists to prevent.
  await page.evaluate(() => loadData(false));
  assert.deepEqual(served, ["overview.json"],
    "the background poll did not read the data branch");

  // The full document has to follow overview.json across, or the two halves of
  // one generation come from origins ~14 minutes apart and never line up.
  await page.click('.tab-btn[data-tab="risk"]');
  await waitForTab(page, "risk");
  assert.ok(served.includes("dashboard.json"),
    "the full document was not read from the data branch");
  assert.equal(state.fullRequests, 1, "the full document was fetched more than once");
  assert.deepEqual(state.failures, []);
  assert.deepEqual(state.errors, []);
  await page.close();

  // A data branch we cannot reach must cost one attempt, not one per poll, and
  // must leave a working page behind.
  const offline = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const offlineState = observe(offline);
  const attempts = await stubLiveOrigin(offline, { fail: true });
  await offline.goto(base, { waitUntil: "networkidle" });
  await waitForData(offline);
  await offline.evaluate(() => loadData(false));
  // Asserted here, before the next poll succeeds and repairs the label: the one
  // honest statement on screen is how old the generation being rendered is, and
  // a failed background poll must not overwrite it with a string that says
  // nothing about it.
  assert.match(await offline.evaluate(() =>
    document.getElementById("last-updated").textContent), /生成于/,
    "a failed poll replaced the age of the generation still on screen");
  // Three polls, not two. The second falls back and succeeds, and it is the
  // third that catches a fallback which forgets — re-promoting the dead origin
  // after every recovery makes every other poll fail.
  await offline.evaluate(() => loadData(false));
  await offline.evaluate(() => loadData(false));
  assert.equal(attempts.length, 1,
    "an unreachable data branch was retried on every poll instead of being dropped");
  await waitForData(offline);
  assert.deepEqual(offlineState.failures, []);
  assert.deepEqual(offlineState.errors, []);
  await offline.close();
}

async function testEquityTouch(browser, base) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  const page = await context.newPage();
  const state = observe(page);
  await stubLiveOrigin(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  await page.locator(".native-equity-canvas").scrollIntoViewIfNeeded();
  const box = await page.locator(".native-equity-canvas").boundingBox();
  assert(box, "equity canvas has no layout box");
  const session = await context.newCDPSession(page);
  const y = box.y + box.height / 2;

  await dispatchTouch(session, "touchStart", [{ x: box.x + box.width / 2, y }]);
  await dispatchTouch(session, "touchEnd", []);
  await page.waitForTimeout(100);
  assert(await page.locator(".native-equity-tooltip").isVisible(), "chart tap did not open its tooltip");

  await page.locator('.mkt-seg-btn[data-mkt="hk"]').first().click();
  await page.waitForFunction(() =>
    document.querySelector("#equity-title")?.textContent.includes("港股 HKD"));
  await dispatchTouch(session, "touchStart", [{ x: box.x + box.width / 2, y }]);
  await dispatchTouch(session, "touchEnd", []);
  await page.waitForTimeout(100);
  const hkTooltip = await page.locator(".native-equity-tooltip").innerText();
  assert.match(hkTooltip, /回撤:\s*(?:−?HK\$[\d,]+|[-\d.]+%)/,
    "HK drawdown still rendered as an empty dash");
  assert.match(hkTooltip, /% 不适用/,
    "negative-profit HK drawdown did not explain its amount fallback");

  const xs = [box.x + box.width - 5, 300, 250, 200, 150, 100, 45];
  await dispatchTouch(session, "touchStart", [{ x: xs[0], y }]);
  for (const x of xs.slice(1)) {
    await dispatchTouch(session, "touchMove", [{ x, y }]);
    await page.waitForTimeout(20);
  }
  await dispatchTouch(session, "touchEnd", []);
  await page.waitForFunction(() => document.querySelector(".tab-btn.active")?.dataset.tab === "drill");
  assert.equal(await page.locator(".native-equity-tooltip").isVisible(), false,
    "pager swipe left a stale chart tooltip");
  assert.deepEqual(state.failures, []);
  assert.deepEqual(state.errors, []);
  await context.close();
}

// `currentTab()` used to read pager.scrollLeft/clientWidth, which forces layout,
// and the hero render loop calls it between renderers — right after each one's
// DOM writes. That interleave cost 162ms of the 1,016ms spent in layout on a
// mobile startup profile (#442). It now reads an index the scroll handler
// already maintains every frame.
//
// The guard exists to stop a render in flight when the user navigates away, so
// "it no longer forces layout" is only half of what has to hold: the cache must
// also still tell the truth about where the pager is.
async function testTabGuardWithoutForcedLayout(browser, base) {
  const context = await browser.newContext({
    viewport: { width: 412, height: 823 }, isMobile: true, hasTouch: true,
  });
  const page = await context.newPage();
  await stubLiveOrigin(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);

  // 1. A full hero render must not read the pager's geometry at all. Counting on
  //    the element shadows the prototype getter, so this measures real accesses
  //    rather than trusting the source.
  const reads = await page.evaluate(async () => {
    const pager = document.getElementById("pager");
    const descriptor = Object.getOwnPropertyDescriptor(Element.prototype, "scrollLeft");
    let count = 0;
    Object.defineProperty(pager, "scrollLeft", {
      configurable: true,
      get() { count += 1; return descriptor.get.call(this); },
    });
    loadData(false);
    await new Promise(resolve => setTimeout(resolve, 1500));
    delete pager.scrollLeft;
    return count;
  });
  assert.equal(reads, 0,
    `hero render forced ${reads} layout-inducing read(s) of pager.scrollLeft`);

  // 2. The guard must observe a tab change immediately. This is stricter than
  //    the geometry was: scrollTo is smooth, so scrollLeft kept reporting the
  //    OLD tab for the length of the animation, and the render it was supposed
  //    to abort carried on until the scroll caught up.
  const afterGoTo = await page.evaluate(() => {
    goToTab("risk");
    return currentTab();
  });
  assert.equal(afterGoTo, "risk", "currentTab() did not follow goToTab synchronously");

  // 3. And it must not drift from a scroll the code did not initiate — a real
  //    swipe moves scrollLeft with no goToTab call anywhere.
  await page.evaluate(() => {
    const pager = document.getElementById("pager");
    pager.scrollLeft = TAB_ORDER.indexOf("market") * pager.clientWidth;
    pager.dispatchEvent(new Event("scroll"));
  });
  await page.waitForFunction(() => currentTab() === "market", null, { timeout: 4000 })
    .catch(() => { throw new Error("currentTab() drifted from an uninstrumented scroll"); });

  await context.close();
}

// The refresh button swaps its label to a CJK string ("已是最新" / "已更新 ✓") for
// 1.8s after a click. CJK has a line-break opportunity between every character,
// so a shrinkable flex item breaks it one glyph per line: the 36px pill became
// an 82px-tall column, and the topbar it overflowed painted the brand on top of
// the nav links. Both states are geometry, so measure them rather than grep the
// stylesheet for the properties that happen to fix them today.
async function testTopbarFitsWhenRefreshLabelSwaps(browser, base) {
  // 360px is the narrowest width the wordmark is promised in full. 320px is
  // past that: there the brand may reach its ellipsis, but it still may not be
  // painted over the links — an un-clipped h1 in a shrunk flex item overlaps
  // them instead of getting narrower.
  const phones = [{ width: 320, mayTruncate: true }, { width: 360 },
                  { width: 390 }, { width: 412 }];
  for (const { width, mayTruncate } of phones) {
    const context = await browser.newContext({
      viewport: { width, height: 800 }, isMobile: true, hasTouch: true,
    });
    const page = await context.newPage();
    await stubLiveOrigin(page);
    await page.goto(base, { waitUntil: "networkidle" });
    await waitForData(page);

    const idleHeight = (await page.locator("#refresh-btn").boundingBox()).height;
    await page.click("#refresh-btn");
    await page.waitForFunction(
      () => document.querySelector("#refresh-btn .lbl").textContent !== "Refresh",
      null, { timeout: 5000 },
    ).catch(() => { throw new Error(`refresh at ${width}px never reported back`); });

    const box = await page.evaluate(() => {
      const rect = el => el.getBoundingClientRect();
      const btn = document.getElementById("refresh-btn");
      const h1 = document.querySelector(".brand h1");
      const link = document.querySelector(".topbar-actions .nav-link");
      const row = document.querySelector(".topbar-row");
      return {
        label: btn.querySelector(".lbl").textContent,
        height: rect(btn).height,
        gap: rect(link).left - rect(h1).right,
        clipped: h1.scrollWidth > h1.clientWidth + 0.5,
        overflow: row.scrollWidth - row.clientWidth,
      };
    });
    assert(box.label !== "Refresh", `label did not swap at ${width}px`);
    assert(box.height <= idleHeight + 1,
      `refresh button grew to ${box.height}px showing "${box.label}" at ${width}px`);
    assert(box.gap >= 0,
      `brand overlaps the nav links by ${-box.gap}px at ${width}px`);
    assert(mayTruncate || !box.clipped, `brand wordmark is truncated at ${width}px`);
    assert(box.overflow <= 0, `topbar row overflows by ${box.overflow}px at ${width}px`);
    await context.close();
  }

  // The narrow layout drops the label to keep the row inside its width. That
  // must stay a narrow-viewport concession: on a desktop the button keeps its
  // text, and the feedback is the text.
  const desktop = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await stubLiveOrigin(desktop);
  await desktop.goto(base, { waitUntil: "networkidle" });
  await waitForData(desktop);
  assert(await desktop.locator("#refresh-btn .lbl").isVisible(),
    "desktop refresh button lost its text label");
  await desktop.close();

  // Hiding the label below 560px means today's two strings can no longer be
  // squeezed hard enough to break — which would leave the button's own
  // single-line guarantee untested until someone widens that breakpoint or adds
  // a fourth nav link. Feed it a label long enough to put the row over budget:
  // the button may become wide, it may not become tall.
  const stress = await browser.newPage({ viewport: { width: 600, height: 900 } });
  await stubLiveOrigin(stress);
  await stress.goto(base, { waitUntil: "networkidle" });
  await waitForData(stress);
  const grew = await stress.evaluate(() => {
    const btn = document.getElementById("refresh-btn");
    const before = btn.getBoundingClientRect().height;
    btn.querySelector(".lbl").textContent = "已是最新的一份生成数据";
    return btn.getBoundingClientRect().height - before;
  });
  assert(grew <= 1, `refresh button wrapped its label onto ${grew}px of extra lines`);
  await stress.close();
}

async function main() {
  const server = serveWorkspace();
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}/`;
  const executablePath = process.env.CHROME_EXE || undefined;
  const browser = await chromium.launch(executablePath ? {
    executablePath, args: ["--no-sandbox"],
  } : {});
  try {
    await testRuntime(browser, base);
    await testLiveDataOrigin(browser, base);
    await testEquityTouch(browser, base);
    await testTabGuardWithoutForcedLayout(browser, base);
    await testTopbarFitsWhenRefreshLabelSwaps(browser, base);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
