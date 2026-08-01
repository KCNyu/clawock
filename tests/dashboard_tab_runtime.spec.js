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
    const filename = path.resolve(ROOT, relative);
    if (!filename.startsWith(ROOT + path.sep) || !fs.existsSync(filename) || fs.statSync(filename).isDirectory()) {
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

function observe(page) {
  const result = { detailRequests: 0, fullRequests: 0, failures: [], errors: [] };
  page.on("request", request => {
    const pathname = new URL(request.url()).pathname;
    if (pathname === DETAIL_PATH) result.detailRequests += 1;
    if (pathname === "/assets/data/dashboard.json") result.fullRequests += 1;
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
  await deep.goto(base + "#reflect", { waitUntil: "domcontentloaded" });
  await waitForTab(deep, "reflect");
  assert.equal(deepState.detailRequests, 1, "deep link did not load one detail bundle");
  assert.equal(deepState.fullRequests, 1, "deep link did not load one full dashboard");
  assert.deepEqual(deepState.failures, []);
  assert.deepEqual(deepState.errors, []);

  const rapid = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const rapidState = observe(rapid);
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

async function testEquityTouch(browser, base) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  const page = await context.newPage();
  const state = observe(page);
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
    await testEquityTouch(browser, base);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
