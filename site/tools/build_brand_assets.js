#!/usr/bin/env node
/**
 * Render the canonical vector app icon into the PNG sizes consumed by the site.
 *
 *   node site/tools/build_brand_assets.js
 *
 * No browser flag needed: Playwright launches the Chromium it manages itself.
 * This used to say `CHROME_EXE=/snap/bin/chromium` because the only Chromium on
 * the desk was a snap (Ubuntu's `chromium-browser` is a snap wrapper, so `apt
 * install` could not give you a real one) and Playwright's own build had not been
 * downloaded yet. Both facts changed: the managed build is installed and is what
 * the screenshot pipeline runs against, and the snap was removed on 2026-08-17.
 * `CHROME_EXE` is still honoured for pointing at some other binary; on a machine
 * with no managed build yet, `npx playwright install chromium` fetches it.
 *
 * The source of truth stays site/assets/icons/app-icon.svg. Do not hand-edit the PNGs.
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../..');
const SOURCE = path.join(ROOT, 'site/assets/icons/app-icon.svg');
const CHROME_EXE = process.env.CHROME_EXE || undefined;
const outputs = [
  ['favicon-64.png', 64],
  ['apple-touch-icon.png', 180],
  ['icon-192.png', 192],
  ['icon-512.png', 512],
  ['icon-maskable-512.png', 512],
];

(async () => {
  const svg = fs.readFileSync(SOURCE, 'utf8');
  const browser = await chromium.launch(
    CHROME_EXE ? { executablePath: CHROME_EXE, args: ['--no-sandbox'] } : {},
  );
  try {
    for (const [name, size] of outputs) {
      const context = await browser.newContext({
        viewport: { width: size, height: size },
        deviceScaleFactor: 1,
      });
      const page = await context.newPage();
      await page.setContent(
        `<style>*{box-sizing:border-box}html,body{margin:0;width:${size}px;height:${size}px;overflow:hidden}svg{display:block;width:${size}px;height:${size}px}</style>${svg}`,
      );
      await page.screenshot({
        path: path.join(ROOT, 'site/assets/icons', name),
        omitBackground: true,
      });
      await context.close();
      console.log(`rendered ${name} (${size}x${size})`);
    }
  } finally {
    await browser.close();
  }
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
