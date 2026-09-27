#!/usr/bin/env node
/**
 * shoot_dsh_queue.js — capture the sidebar provider panel's dispatch queue in a
 * live DeepSeek Harness, for the clawock-dsh README's Dispatch queue section.
 *
 * A manual refresh for the same reason as shoot_dsh_plugin.js: the picture is
 * the real panel on a real host (a CI runner has no DSH and no dispatcher).
 * WebKit, because this host's visual checks are single-engine WebKit (Linux
 * Chromium does not reproduce the host's type and material), and that needs a
 * playwright-core whose version matches ~/.cache/ms-playwright/webkit-*.
 *
 *   node site/tools/shoot_dsh_queue.js      # → site/assets/dsh-dispatch-queue.png
 *   clawock validate-sidecar screenshots    # same gate CI runs
 *
 * The repository is public and the panel shows this host's live queue, so the
 * frame is cut to the agent groups at the top (their quota windows and tasks)
 * and stops before the first provider that has no agent, which is where the
 * account balances start. The panel is glass: whatever sits behind it (the
 * session list, i.e. private chat titles) shows through, so everything but the
 * panel is hidden before the shot — the panel itself is untouched. Look at the
 * picture before committing it: every task name in it is published.
 *
 * Env: DSH_URL (default: the newest token URL in `journalctl -u dsh`),
 *      PLAYWRIGHT_CORE (module path), OUT, WIDTH/HEIGHT/DSF, THEME (light|dark).
 */
const { execFileSync } = require('child_process');
const path = require('path');

const { webkit } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const ROOT = path.resolve(__dirname, '../..');
const OUT = process.env.OUT || path.join(ROOT, 'site/assets/dsh-dispatch-queue.png');
const WIDTH = Number(process.env.WIDTH || 1280);
const HEIGHT = Number(process.env.HEIGHT || 900);
const DSF = Number(process.env.DSF || 2);

function dshUrl() {
  if (process.env.DSH_URL) return process.env.DSH_URL;
  // dsh 0.1.2+ lets a browser in only through the token URL it logs at start.
  const log = execFileSync('journalctl', ['-u', 'dsh', '-n', '1000', '--no-pager'], { encoding: 'utf8' });
  const hit = [...log.matchAll(/dsh web: (http:\/\/127\.0\.0\.1:3081\/\?token=\S+)/g)].at(-1);
  if (!hit) throw new Error('no token URL in the dsh journal; set DSH_URL');
  return hit[1];
}

async function main() {
  const browser = await webkit.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: WIDTH, height: HEIGHT }, deviceScaleFactor: DSF,
    colorScheme: process.env.THEME === 'dark' ? 'dark' : 'light',
  });
  const page = await context.newPage();
  // /plugins/events is an SSE stream, so the network never goes idle: wait on the DOM.
  await page.goto(dshUrl(), { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.locator('[data-pp-row]').first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(2000);
  await page.locator('[data-pp-row]').first().click();
  const panel = page.locator('[data-clawock-popover="clawock-provider-balance"]');
  await panel.waitFor({ timeout: 10000 });
  // visibility is inherited but a descendant can take it back, so this blanks the page behind
  // the panel and nothing inside it.
  await page.addStyleTag({ content: 'body * { visibility: hidden !important }'
    + ' [data-clawock-popover="clawock-provider-balance"], [data-clawock-popover="clawock-provider-balance"] *'
    + ' { visibility: visible !important }' });
  await page.waitForTimeout(800);

  const clip = await panel.evaluate((p) => {
    const box = p.getBoundingClientRect();
    // The first group that is a provider without an agent (a balance) ends the frame.
    const stop = [...p.querySelectorAll('[data-pp-group]')].find((g) => !g.hasAttribute('data-tq-group'));
    const bottom = stop ? stop.getBoundingClientRect().top : box.bottom;
    const pad = 10;
    return { x: Math.max(0, box.left - pad), y: Math.max(0, box.top - pad),
      width: box.width + 2 * pad, height: bottom - box.top + pad };
  });
  await page.screenshot({ path: OUT, clip });
  console.log(`wrote ${OUT} (${Math.round(clip.width * DSF)}x${Math.round(clip.height * DSF)})`);
  await browser.close();
}

main().catch((err) => { console.error(err); process.exit(1); });
