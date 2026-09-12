#!/usr/bin/env node
"use strict";

// The Jekyll chrome, measured on a phone.
//
// `site/index.html` is `layout: null` — the dashboard is its own document, and
// `tests/dashboard_tab_runtime.spec.js` covers its header. Everything else on
// the site (briefs, evidence, faq, and now the decision map) is rendered into
// `site/_layouts/default.html`, and that header had no coverage at all. It
// showed: the brand plus five nav links come to roughly 382px, a 375px phone
// wrapped them onto a second line, and `justify-content: space-between` pushed
// that line hard against the right edge on every non-dashboard page.
//
// A CSS rule cannot be asserted by reading it, so this renders the real layout
// (Liquid resolved the way Jekyll would for a static link) and measures boxes.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const LAYOUT = path.resolve(ROOT, "site/_layouts/default.html");
// The decision map's styles moved into the dashboard stylesheet when the board
// moved into the Reflect tab (2026-09-09). The phone-geometry rules this file
// measures — the pointer-coarse touch targets and the bottom-sheet drawer —
// are the same rules; only their address changed.
const DASHBOARD_CSS = path.resolve(ROOT, "site/assets/css/dashboard.css");
const DM_CSS_START = "/* ── 决策地图（Reflect 卡内）";
const DM_CSS_END = "/* Equity Curve 卡的专属规则";

// The phones this has to hold: the narrowest still in use, and a current one.
const WIDTHS = [320, 390];

/** Resolve the subset of Liquid the layout uses, as Jekyll would for a page. */
function render(content, { url = "/decimap/" } = {}) {
  let html = fs.readFileSync(LAYOUT, "utf8");
  html = html
    // {{ '/briefs.html' | relative_url }} -> /briefs.html
    .replace(/\{\{\s*'([^']*)'\s*\|\s*relative_url\s*\}\}/g, "$1")
    // {% if page.url contains 'decimap' %}active{% endif %}
    .replace(/\{%\s*if ([^%]*?)\s*%\}([\s\S]*?)\{%\s*endif\s*%\}/g,
      (_, condition, body) => {
        const match = /contains '([^']+)'/.exec(condition);
        return match && url.includes(match[1]) ? body : "";
      })
    .replace(/\{\{\s*content\s*\}\}/g, content)
    .replace(/\{%[\s\S]*?%\}/g, "")
    .replace(/\{\{[\s\S]*?\}\}/g, "");
  return html;
}

/** The decision-map stylesheet plus a timeline dense enough to aim at. */
function decimapFixture() {
  const css = fs.readFileSync(DASHBOARD_CSS, "utf8");
  const from = css.indexOf(DM_CSS_START);
  const to = css.indexOf(DM_CSS_END, from);
  // Slice, don't inline the whole sheet: dashboard.css redefines :root, and a
  // fixture that quietly stops carrying the rules it measures is a test that
  // passes because it tests nothing.
  assert(from > 0 && to > from,
    "the decision-map block is no longer where this fixture slices it out of "
    + "dashboard.css — re-point the markers, do not delete the assertion");
  const style = `<style>${css.slice(from, to)}</style>`;
  const dots = [12, 34, 61, 88].map(left =>
    `<button class="dm-dot is-buy" style="left:${left}%"></button>`).join("");
  return `${style}
    <div class="decimap">
      <h1>Decision Map</h1>
      <div class="dm-timeline">
        <div class="dm-row"><b>0700.HK</b><div class="dm-track" id="track">${dots}</div></div>
      </div>
      <div class="dm-board-wrap"><table class="dm-board"><tr><th class="dm-src">bar</th><td class="dm-cell">1</td></tr></table></div>
      <aside class="dm-drawer" id="drawer"><div>body</div></aside>
    </div>`;
}

function serve(html) {
  return http.createServer((request, response) => {
    const name = new URL(request.url, "http://localhost").pathname;
    if (name === "/" || name === "/decimap/") {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end(html);
      return;
    }
    const file = path.resolve(ROOT, "site", name.replace(/^\/+/, ""));
    if (!file.startsWith(path.resolve(ROOT, "site") + path.sep) || !fs.existsSync(file)
        || fs.statSync(file).isDirectory()) {
      response.writeHead(404).end("not found");
      return;
    }
    response.writeHead(200, { "content-type": "application/octet-stream" });
    fs.createReadStream(file).pipe(response);
  });
}

async function navStaysOnOneRowAndNothingScrollsSideways(browser, base) {
  for (const width of WIDTHS) {
    const context = await browser.newContext({
      viewport: { width, height: 720 }, hasTouch: true, isMobile: true });
    const page = await context.newPage();
    await page.goto(base, { waitUntil: "load" });

    const nav = await page.evaluate(() =>
      [...document.querySelectorAll(".topbar-actions .nav-link")].map(link => {
        const box = link.getBoundingClientRect();
        return { text: link.textContent.trim(), top: Math.round(box.top),
                 left: Math.round(box.left), right: Math.round(box.right),
                 height: Math.round(box.height) };
      }));
    // Three since the validation ledger stopped being its own page (2026-09-12,
    // #1472): `证据台账` is an in-page anchor now, and a same-page link is not a
    // nav destination. Before that it was four (the decision map left the header
    // on 2026-09-09). The count stays asserted rather than derived, so that
    // dropping a link is a decision someone makes here.
    assert.equal(nav.length, 3, `expected three nav links, got ${nav.length}`);
    // The ledger is an in-page anchor in the dashboard's own header, not a
    // destination on this shared layout — so it must NOT be here, and the three
    // that remain are named so a silent drop still fails.
    assert.deepEqual(nav.map(link => link.text).sort(),
      ["Briefs", "Dashboard", "GitHub"],
      "the shared header's destinations changed without this assertion");

    const rows = new Set(nav.map(link => link.top));
    assert.equal(rows.size, 1,
      `${width}px: nav wrapped onto ${rows.size} rows — ` +
      nav.map(l => `${l.text}@${l.top}`).join(" "));

    for (const link of nav) {
      assert(link.height >= 34,
        `${width}px: "${link.text}" is ${link.height}px tall; a touch target is not a mouse target`);
    }

    // The row is allowed to scroll on the narrowest phone, but the page is not.
    const overflow = await page.evaluate(() => ({
      page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      navScroll: document.querySelector(".topbar-actions").scrollWidth
        - document.querySelector(".topbar-actions").clientWidth,
    }));
    assert(overflow.page <= 1,
      `${width}px: the document scrolls sideways by ${overflow.page}px`);
    if (width === 390) {
      assert(overflow.navScroll <= 1,
        `390px: the nav needs ${overflow.navScroll}px of scroll — it should fit outright`);
    }

    // A wrapped nav used to land underneath the brand; on one row it must not.
    const brand = await page.evaluate(() =>
      Math.round(document.querySelector(".brand").getBoundingClientRect().bottom));
    assert(nav[0].top >= brand - 2 || nav[0].left >= 0,
      `${width}px: nav overlaps the brand`);
    await context.close();
  }
}

async function timelineDotsAreAimableWithAFinger(browser, base) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 720 }, hasTouch: true, isMobile: true });
  const page = await context.newPage();
  await page.goto(base, { waitUntil: "load" });

  const reach = await page.evaluate(() => {
    const dot = document.querySelector("#track .dm-dot");
    const box = dot.getBoundingClientRect();
    const x = box.left + box.width / 2;
    const centre = box.top + box.height / 2;
    let above = 0;
    while (above < 40 && document.elementFromPoint(x, centre - above - 1) === dot) above += 1;
    let below = 0;
    while (below < 40 && document.elementFromPoint(x, centre + below + 1) === dot) below += 1;
    return { width: Math.round(box.width), reachable: above + below + 1 };
  });

  // 9px of dot was the whole target before; the pointer-coarse block adds
  // vertical slop, where there is nothing else to hit.
  assert(reach.width >= 12,
    `the timeline dot is ${reach.width}px across on a touch screen`);
  assert(reach.reachable >= 30,
    `a finger has ${reach.reachable}px of vertical reach on a timeline dot`);

  // The slop must not reach the neighbouring dot: on a busy ticker they sit a
  // few pixels apart, and horizontal slop only moves the mis-taps around.
  const bleeds = await page.evaluate(() => {
    const [first, second] = document.querySelectorAll("#track .dm-dot");
    const a = first.getBoundingClientRect();
    const b = second.getBoundingClientRect();
    const midpoint = (a.right + b.left) / 2;
    return document.elementFromPoint(midpoint, a.top + a.height / 2) !== document.body
      && (a.right + b.left) / 2 - a.right < 3;
  });
  assert(!bleeds, "a dot's hit area reaches halfway to its neighbour");
  await context.close();
}

async function theDrawerBecomesASheetInsteadOfCoveringThePage(browser, base) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 720 }, hasTouch: true, isMobile: true });
  const page = await context.newPage();
  await page.goto(base, { waitUntil: "load" });
  const drawer = await page.evaluate(() => {
    const element = document.querySelector("#drawer");
    element.classList.add("is-open");
    const box = element.getBoundingClientRect();
    return { width: Math.round(box.width), top: Math.round(box.top),
             bottom: Math.round(box.bottom), viewport: window.innerHeight };
  });
  assert.equal(drawer.width, 390,
    `the phone drawer is ${drawer.width}px wide; a 6% sliver of scrim is not a panel`);
  assert(drawer.top > 40,
    `the sheet starts at ${drawer.top}px — the page underneath must stay reachable`);
  assert(drawer.bottom >= drawer.viewport - 1,
    "the sheet does not reach the bottom of the screen");
  await context.close();
}

async function main() {
  const html = render(decimapFixture());
  const server = serve(html);
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}/decimap/`;
  const executablePath = process.env.CHROME_EXE || undefined;
  const browser = await chromium.launch(executablePath ? {
    executablePath, args: ["--no-sandbox"],
  } : {});
  try {
    await navStaysOnOneRowAndNothingScrollsSideways(browser, base);
    await timelineDotsAreAimableWithAFinger(browser, base);
    await theDrawerBecomesASheetInsteadOfCoveringThePage(browser, base);
    console.log("site layout mobile contract: ok");
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
