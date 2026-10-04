#!/usr/bin/env node
/**
 * Capture a real task's complete detail panel, including its brief/append
 * history and progress timeline, from the installed live DSH bundle.
 * WebKit only: Linux Chromium does not reproduce this host's type/material.
 * The narrow, touch viewport keeps this panel readable in the README on phones.
 *
 * TASK_ID=<visible queue task id> PLAYWRIGHT_CORE=<matching playwright-core>
 *   node site/tools/shoot_dsh_task_detail.js
 * Env: DSH_URL (otherwise newest token URL in journalctl -u dsh), TASK_ID
 * (required), OUT, WIDTH (390), HEIGHT (3600), DSF (2), THEME (light|dark).
 * No bundle override: this captures the installed plugin. No task writes.
 * The viewport grows to fit the WHOLE panel without scrolling or cropping.
 * Hide the private session titles behind the glass, leaving the panel intact.
 * PUBLIC REPOSITORY: look at the picture before committing it. Every task
 * name, append excerpt and timeline entry in it is published; never ship
 * third-party private information, credentials or private session contents.
 * Internal session identifiers in timeline text are replaced with [redacted]
 * in the public capture only; event order, timestamps and layout stay intact.
 */
const { execFileSync } = require('child_process');
const path = require('path');
const { webkit } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');

function dshUrl() {
  if (process.env.DSH_URL) return process.env.DSH_URL;
  const log = execFileSync('journalctl', ['-u', 'dsh', '-n', '1000', '--no-pager'], { encoding: 'utf8' });
  const hit = [...log.matchAll(/dsh web: (http:\/\/127\.0\.0\.1:3081\/\?token=\S+)/g)].at(-1);
  if (!hit) throw new Error('no token URL in the dsh journal; set DSH_URL');
  return hit[1];
}

async function main() {
  const id = process.env.TASK_ID;
  if (!id || !/^[a-z0-9][a-z0-9-]{0,80}$/.test(id)) throw new Error('set TASK_ID to a visible task with complete history');
  if (process.env.BUNDLE) throw new Error('capture the installed bundle; unset BUNDLE');
  const width = Number(process.env.WIDTH || 390);
  let height = Number(process.env.HEIGHT || 3600);
  const dsf = Number(process.env.DSF || 2);
  const out = process.env.OUT || path.resolve(__dirname, '../assets/dsh-task-detail.png');
  const browser = await webkit.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width, height }, deviceScaleFactor: dsf, isMobile: true, hasTouch: true,
      colorScheme: process.env.THEME === 'dark' ? 'dark' : 'light',
    });
    const page = await context.newPage();
    await page.goto(dshUrl(), { waitUntil: 'domcontentloaded', timeout: 60000 });
    const sidebar = page.getByRole('button', { name: 'Open sidebar', exact: true });
    if (await sidebar.isVisible()) await sidebar.click();
    const queue = page.getByRole('button', { name: /^Quota · queue:/ });
    await queue.waitFor({ timeout: 30000 });
    await page.waitForTimeout(2000);
    await queue.click();
    const panel = page.locator('[data-clawock-popover="clawock-provider-balance"]');
    await panel.waitFor();
    await panel.locator(`[data-tq-task="${id}"]`).click();
    await panel.locator(`[data-tq-detail="${id}"]`).waitFor();
    await page.addStyleTag({ content: 'body * { visibility: hidden !important }'
      + ' [data-clawock-popover="clawock-provider-balance"], [data-clawock-popover="clawock-provider-balance"] *'
      + ' { visibility: visible !important }' });
    await panel.locator('[data-tq-action="brief"]').click();
    await panel.locator('[data-tq-brief]').waitFor();
    await panel.locator('[data-tq-action="timeline"]').click();
    const timeline = panel.locator('[data-tq-timeline]');
    await timeline.waitFor();
    if (!(await timeline.locator('li').count())) throw new Error('no timeline events; choose a task with complete history');
    await timeline.evaluate(root => {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode;
        node.textContent = node.textContent.replace(/session=[A-Za-z0-9_-]+/g, 'session=[redacted]')
          .replace(/(deliver it to session )\S+/g, '$1[redacted]');
      }
    });
    for (let attempt = 0; attempt < 5; attempt++) {
      await page.waitForTimeout(500);
      const overflow = await panel.evaluate(p => {
        const scroll = p.querySelector('[class*="tq-scroll"]');
        return scroll ? Math.max(0, scroll.scrollHeight - scroll.clientHeight) : 0;
      });
      if (overflow <= 1) break;
      height += overflow + 80;
      await page.setViewportSize({ width, height });
    }
    await page.mouse.move(width - 2, 2);
    await page.evaluate(() => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur(); });
    const clip = await panel.evaluate(p => {
      const scroll = p.querySelector('[class*="tq-scroll"]');
      if (scroll && scroll.scrollHeight > scroll.clientHeight + 1) throw new Error('detail still scrolls; raise HEIGHT');
      if (scroll && scroll.scrollTop > 0) throw new Error('detail is scrolled; refusing an incomplete capture');
      const b = p.getBoundingClientRect();
      const pad = 10;
      if (b.left < 0 || b.top < 0 || b.right > innerWidth || b.bottom > innerHeight)
        throw new Error(`whole panel does not fit: ${JSON.stringify(b.toJSON())}, viewport ${innerWidth}x${innerHeight}`);
      const x = Math.max(0, b.left - pad), y = Math.max(0, b.top - pad);
      return { x, y, width: Math.min(innerWidth, b.right + pad) - x,
        height: Math.min(innerHeight, b.bottom + pad) - y };
    });
    await page.screenshot({ path: out, clip });
    console.log(`wrote ${out} (${Math.round(clip.width * dsf)}x${Math.round(clip.height * dsf)})`);
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error.message); process.exit(1); });
