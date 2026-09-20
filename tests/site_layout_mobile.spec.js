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
//
// The layout links `assets/css/dashboard.css` rather than inlining a copy of it
// (#1702), and the server below serves `site/` — so what this measures is the
// page's real stylesheet, not a fixture's idea of it.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const LAYOUT = path.resolve(ROOT, "site/_layouts/default.html");

// The phones this has to hold: the narrowest still in use, and a current one.
const WIDTHS = [320, 390];

/** Resolve the subset of Liquid the layout uses, as Jekyll would for a page. */
function render(content, { url = "/briefs.html" } = {}) {
  let html = fs.readFileSync(LAYOUT, "utf8");
  // if / elsif / else, because the menu's own label is written that way: a
  // resolver that only understands `if` renders the trigger with no text, and
  // then every width measured below is the width of a button with nothing in
  // it — the one thing on this bar that a page name can make wider.
  const truthy = condition =>
    [...condition.matchAll(/contains '([^']+)'/g)].some(m => url.includes(m[1]))
    || [...condition.matchAll(/page\.url == '([^']+)'/g)].some(m => url === m[1]);
  html = html
    // {{ '/briefs.html' | relative_url }} -> /briefs.html
    .replace(/\{\{\s*'([^']*)'\s*\|\s*relative_url\s*\}\}/g, "$1")
    .replace(/\{%\s*if ([^%]*?)\s*%\}([\s\S]*?)\{%\s*endif\s*%\}/g,
      (_, condition, body) => {
        const branches = [{ condition, body: "" }];
        let cursor = branches[0], last = 0, match;
        const clause = /\{%\s*(?:elsif ([^%]*?)|else)\s*%\}/g;
        while ((match = clause.exec(body))) {
          cursor.body = body.slice(last, match.index);
          cursor = { condition: match[1] || null, body: "" };
          branches.push(cursor);
          last = match.index + match[0].length;
        }
        cursor.body = body.slice(last);
        const hit = branches.find(b => b.condition === null || truthy(b.condition));
        return hit ? hit.body : "";
      })
    .replace(/\{\{\s*content\s*\}\}/g, content)
    .replace(/\{%[\s\S]*?%\}/g, "")
    .replace(/\{\{[\s\S]*?\}\}/g, "");
  return html;
}

/** A timeline dense enough to aim at, drawn by the page's own stylesheet. */
function decimapFixture() {
  const dots = [12, 34, 61, 88].map(left =>
    `<button class="dm-dot is-buy" style="left:${left}%"></button>`).join("");
  return `
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
    if (name === "/" || name === "/decimap/" || name === "/briefs.html") {
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
    // A stylesheet served as octet-stream is a stylesheet the browser refuses
    // to apply — which would make every measurement below the geometry of an
    // unstyled page, and every assertion pass or fail for the wrong reason.
    const TYPES = { ".css": "text/css", ".js": "text/javascript",
                    ".json": "application/json", ".svg": "image/svg+xml" };
    response.writeHead(200, {
      "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(response);
  });
}

async function navStaysOnOneRowAndNothingScrollsSideways(browser, base) {
  for (const width of WIDTHS) {
    const context = await browser.newContext({
      viewport: { width, height: 720 }, hasTouch: true, isMobile: true });
    const page = await context.newPage();
    await page.goto(base, { waitUntil: "load" });

    // The four destinations live in a <details> panel, which the UA hides
    // until it is open — so open it before measuring, exactly as a reader
    // would. Measuring a closed panel yields four zero-height boxes and the
    // touch-target assertion below would pass on nothing.
    await page.click(".site-menu-btn");
    await page.waitForTimeout(120);

    const nav = await page.evaluate(() =>
      [...document.querySelectorAll(".site-menu-item")].map(link => {
        const box = link.getBoundingClientRect();
        return { text: link.textContent.trim(), top: Math.round(box.top),
                 left: Math.round(box.left), right: Math.round(box.right),
                 height: Math.round(box.height) };
      }));
    // Four since FAQ became a first-class destination instead of a dashboard-
    // footer-only link. The count stays asserted rather than derived, so that
    // dropping a link is a decision someone makes here.
    // The validation ledger stopped being its own page (2026-09-12, #1472):
    // `证据台账` is an in-page anchor now, and a same-page link is not a nav
    // destination.
    assert.equal(nav.length, 4, `expected four destinations, got ${nav.length}`);
    assert.deepEqual(nav.map(link => link.text).sort(),
      ["Briefs", "Dashboard", "FAQ", "GitHub"],
      "the shared header's destinations changed without this assertion");

    // A disclosure lists its items vertically; what must not happen is a
    // second column or a wrapped label, which is what "rows" is checking now.
    const lefts = new Set(nav.map(link => link.left));
    assert.equal(lefts.size, 1,
      `${width}px: the menu laid its items out in ${lefts.size} columns — ` +
      nav.map(l => `${l.text}@${l.left}`).join(" "));

    // 44px, the floor the trigger already held: on a phone the items are the
    // target, and a 35px row in a menu opened by a 44px button is the one place
    // on the page where "where can I go" is the hardest thing to hit.
    for (const link of nav) {
      assert(link.height >= 44,
        `${width}px: "${link.text}" is ${link.height}px tall; a touch target is not a mouse target`);
    }
    const trigger = await page.evaluate(() =>
      Math.round(document.querySelector(".site-menu-btn").getBoundingClientRect().height));
    assert(trigger >= 44, `${width}px: the menu trigger is ${trigger}px tall`);

    // The row is allowed to scroll on the narrowest phone, but the page is not.
    const overflow = await page.evaluate(() => ({
      page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      menuRight: Math.round(document.querySelector(".site-menu-panel").getBoundingClientRect().right),
      viewport: document.documentElement.clientWidth,
    }));
    assert(overflow.page <= 1,
      `${width}px: the document scrolls sideways by ${overflow.page}px`);
    assert(overflow.menuRight <= overflow.viewport + 1,
      `${width}px: the open menu runs ${overflow.menuRight - overflow.viewport}px past the viewport`);

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
  const base = `http://127.0.0.1:${server.address().port}/briefs.html`;
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
