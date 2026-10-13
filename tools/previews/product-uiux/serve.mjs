import { createServer, loadConfigFromFile } from '../../../web/packages/app/node_modules/vite/dist/node/index.js';
import { readFileSync, existsSync, statSync, createReadStream } from 'node:fs';
import { resolve, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import {interactiveEntryRedirect, isScenePreview} from './world-handoff.mjs';

const root = fileURLToPath(new URL('../../../', import.meta.url)).replace(/\/$/, '');
const here = fileURLToPath(new URL('.', import.meta.url)).replace(/\/$/, '');
const runtimeStateFile = process.env.EXULANICA_REVIEW_RUNTIME_STATE_FILE;
if (!runtimeStateFile) throw Error('Set EXULANICA_REVIEW_RUNTIME_STATE_FILE to a private runtime descriptor.');
let runtime;
try { runtime = JSON.parse(readFileSync(runtimeStateFile, 'utf8')); }
catch { throw Error('The private runtime descriptor could not be read.'); }
if (!Number.isInteger(runtime.ports?.api) || typeof runtime.token_file !== 'string') throw Error('Invalid preview runtime descriptor.');
const previewDirectory = process.env.EXULANICA_REVIEW_PREVIEWS_DIRECTORY || here + '/world-previews';
let previewCatalog;
try { previewCatalog = JSON.parse(readFileSync(previewDirectory + '/catalog.json', 'utf8')); }
catch { throw Error('The private preview catalog could not be read.'); }
if (previewCatalog.profile !== 'exulanica.private-world-preview/v1' || !Array.isArray(previewCatalog.captures)) throw Error('Invalid private preview catalog.');
const token = readFileSync(runtime.token_file, 'utf8').trim();
const api = 'http://127.0.0.1:' + runtime.ports.api;
process.env.VITE_EXULANICA_TOKEN = token;
process.env.EXULANICA_API_URL = api;
const loaded = await loadConfigFromFile({ command: 'serve', mode: 'development' }, root + '/web/packages/app/vite.config.ts');
const hook = 'void objects.begin(state.activeWorldEntry?.authoredVersionId);';
const entryHook = '  replaceSurface(shell, [yourWorlds.root]);';
const startHook = '    await mountNoWorld({ retry: () => start(token, csrfToken) });';
const openHook = `    await openWorldEntryContext(state, entry);
    state.worldEntryError = null;
    shell.removeAttribute('data-world-state');
    await mount();
  };
  // Create a world opens over Your worlds`;
const contentTypes = { '.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.json':'application/json', '.svg':'image/svg+xml', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.png':'image/png', '.avif':'image/avif', '.webp':'image/webp', '.woff2':'font/woff2', '.md':'text/plain' };
function servePrivateFile(directory, req, res, fallback = false, homeHooks = false) {
  let path;
  try { path = decodeURIComponent(new URL(req.url || '/', 'http://localhost').pathname); } catch { res.statusCode=400; res.end(); return; }
  const parent = resolve(directory);
  let file = resolve(parent, '.' + path);
  if (file !== parent && !file.startsWith(parent + '/')) { res.statusCode=404; res.end(); return; }
  if (existsSync(file) && statSync(file).isDirectory()) file = resolve(file, 'index.html');
  if (!existsSync(file) && fallback) file = resolve(parent, 'index.html');
  if (!existsSync(file)) { res.statusCode=404; res.end(); return; }
  res.setHeader('Cache-Control','no-store'); res.setHeader('Content-Type',contentTypes[extname(file)] || 'application/octet-stream');
  if (extname(file) === '.html') {
    let html = readFileSync(file,'utf8');
    if (homeHooks && !html.includes('/review-home-assets/private-home.js')) html = html.replace('</body>','<script type="module" src="/review-home-assets/private-home.js"></script></body>');
    if (homeHooks && !html.includes('/review-home-assets/private-home.css')) html = html.replace('</head>','<link rel="stylesheet" href="/review-home-assets/private-home.css"></head>');
    res.end(html);
  } else createReadStream(file).pipe(res);
}
const plugin = {
  name: 'private-product-interaction-review',
  enforce: 'pre',
  transformIndexHtml(html) {
    return html.replace('</head>', `<script type="module" src="/@fs/${here}/entry.ts"></script></head>`);
  },
  transform(code, id) {
    if (id === here + '/entry.ts') return code.replace("import previews from './world-previews/catalog.json';", 'const previews = ' + JSON.stringify(previewCatalog) + ';');
    if (id !== root + '/web/packages/app/src/main.ts') return;
    if (![hook, entryHook, startHook, openHook, 'picture: worldPicture,'].every(seam => code.includes(seam))) throw Error('Native review mount or entry seam changed.');
    return `import { mountEntryReview, reviewWorldPicture, reviewOpenEntry, reviewReturnToChooser } from '/@fs/${here}/entry.ts';\nimport { mountReadonlyScenePreview } from '/@fs/${here}/entry-preview.ts';\n` + code
      .replace("returnToWorlds.addEventListener('click', () => window.location.reload());", "returnToWorlds.addEventListener('click', () => reviewReturnToChooser(state.activeWorldEntry?.entryId));")
      .replace('const leave = (): void => window.location.reload();', 'const leave = (): void => reviewReturnToChooser(state.activeWorldEntry?.entryId);')
      .replace('picture: worldPicture,', 'picture: entry => reviewWorldPicture(entry) ?? worldPicture(entry),')
      .replace(entryHook, entryHook + '\n  mountEntryReview({root:yourWorlds.root,entries:state.savedWorldEntries});')
      .replace(openHook, `    reviewOpenEntry(entry.entryId);
  };
  // Create a world opens over Your worlds`)
      .replace(startHook, `    const reviewEntryId = new URLSearchParams(location.search).get('entry');
    if (reviewEntryId) {
      const reviewEntry = state.savedWorldEntries.find(entry => entry.entryId === reviewEntryId);
      if (reviewEntry && !new URLSearchParams(location.search).has('capture') && !new URLSearchParams(location.search).has('livePreview')) { reviewOpenEntry(reviewEntry.entryId); return; }
      if (reviewEntry) { await openWorldEntryContext(state, reviewEntry); state.worldEntryError = null; shell.removeAttribute('data-world-state'); await mount(); return; }
      pendingEntryProblem = 'This saved-world link is no longer available. Choose a world here.';
    }
` + startHook)
      .replace('void environmentSelection.begin();', 'await environmentSelection.begin();')
      .replace(hook, `await objects.begin(state.activeWorldEntry?.authoredVersionId);
      if (new URLSearchParams(location.search).has('livePreview')) mountReadonlyScenePreview({state,renderer});
`);
  },
  configureServer(server) {
    server.middlewares.use((req,res,next)=>{
      const destination=interactiveEntryRedirect(req.url || '/');
      if(destination && (req.method==='GET' || req.method==='HEAD')) {res.statusCode=302;res.setHeader('Cache-Control','no-store');res.setHeader('Location',destination);res.end();return;}
      next();
    });
    // Enforce inert scene previews before native API proxy middleware runs.
    server.middlewares.use((req,res,next)=>{
      let preview=false;
      try { preview=isScenePreview(new URL(req.headers.referer || 'http://localhost')); } catch {}
      if(preview && req.method!=='GET') {res.statusCode=405;res.setHeader('Content-Type','application/json');res.end(JSON.stringify({detail:'The world preview is read-only.'}));return;}
      next();
    });
    server.middlewares.use('/home', (req,res) => servePrivateFile(here + '/home-dist',req,res,true,true));
    server.middlewares.use('/review-home-assets', (req,res) => servePrivateFile(here + '/home-dist',req,res,false,true));
    server.middlewares.use('/review-world-previews', (req,res) => servePrivateFile(previewDirectory,req,res));
    // Public media retain absolute URLs in the landing source. Serve only media here;
    // a missing image must return 404 rather than the app's HTML fallback.
    server.middlewares.use((req,res,next) => {
      const path = new URL(req.url || '/', 'http://localhost').pathname;
      if (/^\/(worlds|product)\/.*\.(jpg|jpeg|png|webp|avif|svg)$/.test(path)) return servePrivateFile(here + '/home-dist',req,res);
      next();
    });
    server.middlewares.use('/review-api', async (req, res) => {
      res.setHeader('Cache-Control', 'no-store');
      res.setHeader('Content-Type', 'application/json');
      if (req.method !== 'GET') { res.statusCode = 405; res.end(JSON.stringify({ detail: 'Use the native review controls for changes.' })); return; }
      try {
        const response = await fetch(api + (req.url || '/'), { headers: { Authorization: 'Bearer ' + token }, signal: AbortSignal.timeout(15000) });
        res.statusCode = response.status;
        res.end(await response.text());
      } catch { res.statusCode = 502; res.end(JSON.stringify({ detail: 'The saved world could not be reached. Try again.' })); }
    });
  },
};
const server = await createServer({
  ...loaded.config, configFile: false, root: root + '/web/packages/app', cacheDir: root + '/.exulanica/local/preview-cache/19972',
  plugins: [plugin, ...(loaded.config.plugins || [])],
  server: { ...loaded.config.server, watch: null, port: 19972, host: '127.0.0.1', strictPort: true, fs: { allow: [root] } },
});
await server.listen();
console.log('Product interaction review: http://127.0.0.1:19972/');
