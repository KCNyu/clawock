/**
 * dsh_bundle.js — shared by the DSH shoot tools (shoot_dsh_plugin.js,
 * shoot_dsh_queue.js): BUNDLE=<built lib/client.js> serves that client in
 * place of the installed one, so a branch's client can be shot on the live
 * host half before it is installed. INSTALLED names the installed copy
 * (default: the web profile's).
 */
const fs = require('fs');
const os = require('os');
const path = require('path');

/**
 * Serve BUNDLE instead of the installed client bundle. dsh wraps the file it
 * reads from disk, so the installed text is swapped inside the response (a
 * function replacement: a string one would expand the bundle's own `$'`/`$&`).
 */
async function serveBundle(page) {
  if (!process.env.BUNDLE) return;
  const installed = fs.readFileSync(process.env.INSTALLED
    || path.join(os.homedir(), '.dsh/profiles/web/node_modules/clawock-dsh/lib/client.js'), 'utf8');
  const bundle = fs.readFileSync(process.env.BUNDLE, 'utf8');
  await page.route((url) => url.pathname.startsWith('/plugins/') && url.href.includes('clawock-dsh/client.js'), async (route) => {
    const response = await route.fetch();
    const body = await response.text();
    if (!body.includes(installed)) throw new Error('the served client is not the installed bundle; cannot swap in BUNDLE');
    await route.fulfill({ response, body: body.replace(installed, () => bundle) });
  });
}

module.exports = { serveBundle };
