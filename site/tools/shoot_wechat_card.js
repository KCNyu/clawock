#!/usr/bin/env node
// Render a chat card's markdown inside a 390px WeChat-style bubble and shoot it.
//
//   PLAYWRIGHT_CORE=<path to playwright-core> node site/tools/shoot_wechat_card.js card.md out.png
//
// A schematic, not a phone capture: it draws the markdown subset that the
// WeChat channel's StreamingMarkdownFilter passes through unchanged (headings
// #–####, blockquotes, `-` lists, tables, ---, **bold**, `code`) roughly as the
// client shows it, so a card's layout can be reviewed in a PR. Whether a real
// client renders each construct is still a phone check. Generalised from the
// one-off table shot behind #3060's docs/design/dispatch-stats-wechat.png.
const fs = require('fs');
const { webkit } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');

const [input, output, clock = '11:04'] = process.argv.slice(2);
if (!input || !output) {
  console.error('usage: shoot_wechat_card.js <card.md> <out.png> [HH:MM]');
  process.exit(2);
}

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const inline = (s) => esc(s)
  .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
  .replace(/`([^`]+)`/g, '<code>$1</code>');
const cells = (line) => line.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());

function render(markdown) {
  const lines = markdown.replace(/\n+$/, '').split('\n');
  const out = [];
  for (let i = 0; i < lines.length;) {
    const line = lines[i];
    const t = line.trim();
    if (!t) { i += 1; continue; }
    const heading = /^(#{1,4})\s+(.*)$/.exec(t);
    if (heading) { out.push(`<div class="h${heading[1].length}">${inline(heading[2])}</div>`); i += 1; continue; }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(t)) { out.push('<hr>'); i += 1; continue; }
    if (t.startsWith('>')) {
      const body = [];
      while (i < lines.length && lines[i].trim().startsWith('>')) {
        body.push(lines[i].trim().replace(/^>\s?/, '')); i += 1;
      }
      const paras = body.filter((p) => p.trim());
      out.push(`<blockquote>${paras.map((p) => `<p>${inline(p)}</p>`).join('')}</blockquote>`);
      continue;
    }
    if (t.startsWith('|')) {
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) { rows.push(lines[i]); i += 1; }
      const head = cells(rows[0]);
      const align = cells(rows[1]).map((c) => (c.endsWith(':') ? 'right' : 'left'));
      const body = rows.slice(2).map(cells);
      out.push(`<table><thead><tr>${head.map((c, k) => `<th style="text-align:${align[k]}">${inline(c)}</th>`).join('')}</tr></thead>`
        + `<tbody>${body.map((r) => `<tr>${r.map((c, k) => `<td style="text-align:${align[k]}">${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
      continue;
    }
    if (/^[-*]\s+/.test(t)) {
      const items = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*]\s+/, '')); i += 1;
      }
      out.push(`<ul>${items.map((x) => `<li>${inline(x)}</li>`).join('')}</ul>`);
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|>|\||[-*]\s|-{3,})/.test(lines[i].trim())) {
      para.push(lines[i].trim()); i += 1;
    }
    const label = para.length === 1 && /^\*\*[^*]+\*\*$/.test(para[0]);
    out.push(`<p class="${label ? 'label' : ''}">${para.map(inline).join('<br>')}</p>`);
  }
  return out.join('\n');
}

const html = `<!doctype html><html lang="zh"><head><meta charset="utf-8"><style>
  * { box-sizing: border-box; }
  body { margin: 0; background: #fff; font-family: "PingFang SC", "Noto Sans CJK SC", "Noto Sans CJK", sans-serif; }
  .phone { width: 390px; background: #ededed; }
  .nav { height: 52px; border-bottom: .5px solid #d8d8d8; display: flex; align-items: center; padding: 0 12px; }
  .back { font-size: 30px; color: #111; margin-top: -3px; }
  .title { flex: 1; text-align: center; font-size: 17px; font-weight: 600; color: #111; margin-right: 22px; }
  .more { font-size: 20px; color: #111; }
  .chat { padding: 18px 14px 22px; }
  .time { text-align: center; font-size: 12px; color: #9a9a9a; margin: 4px 0 16px; }
  .row { display: flex; align-items: flex-start; gap: 10px; }
  .avatar { width: 38px; height: 38px; border-radius: 5px; background: #1f5c4a; color: #fff; font-size: 13px; font-weight: 700;
    display: flex; align-items: center; justify-content: center; flex: none; }
  .bubble { position: relative; background: #fff; border-radius: 6px; padding: 11px 12px 12px; width: 318px;
    font-size: 14px; line-height: 1.55; color: #111; overflow-wrap: anywhere; }
  .bubble::before { content: ""; position: absolute; left: -6px; top: 13px; border: 6px solid transparent; border-right-color: #fff; border-left: 0; }
  .h1, .h2 { font-size: 17px; font-weight: 700; margin: 2px 0 6px; }
  .h3 { font-size: 15px; font-weight: 700; margin: 12px 0 4px; }
  .h4 { font-size: 14px; font-weight: 700; margin: 10px 0 4px; }
  p { margin: 4px 0; }
  p.label { margin: 14px 0 2px; }  /* a bold label after a blank line: WeChat keeps the empty line */
  ul { margin: 2px 0 4px; padding-left: 18px; }
  li { margin: 2px 0; }
  blockquote { margin: 4px 0; padding: 2px 0 2px 9px; border-left: 3px solid #d6d6d6; color: #555; }
  blockquote p { margin: 2px 0; }
  code { font-family: Menlo, "SF Mono", monospace; font-size: 12.5px; background: #f2f2f2; border-radius: 3px; padding: 0 3px; }
  hr { border: 0; border-top: .5px solid #e3e3e3; margin: 8px 0; }
  table { width: 100%; border-collapse: collapse; table-layout: auto; font-size: 11px; line-height: 1.35; margin: 4px 0; }
  th { font-size: 10px; font-weight: 500; color: #888; padding: 4px 3px; border-bottom: .5px solid #e3e3e3; white-space: nowrap; }
  td { padding: 4px 3px; border-bottom: .5px solid #efefef; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .composer { height: 54px; background: #f7f7f7; border-top: .5px solid #d8d8d8; }
</style></head><body>
<div class="phone">
  <div class="nav"><div class="back">‹</div><div class="title">OpenClaw</div><div class="more">···</div></div>
  <div class="chat"><div class="time">${esc(clock)}</div><div class="row"><div class="avatar">OC</div>
    <div class="bubble">${render(fs.readFileSync(input, 'utf8'))}</div></div></div>
  <div class="composer"></div>
</div></body></html>`;

(async () => {
  const browser = await webkit.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 430, height: 1200 }, deviceScaleFactor: 2 });
  await page.setContent(html, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await page.locator('.phone').screenshot({ path: output });
  await browser.close();
  console.log(`wrote ${output}`);
})().catch((e) => { console.error(e); process.exit(1); });
