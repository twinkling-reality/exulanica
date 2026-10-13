import { createServer, loadConfigFromFile } from '../../../web/packages/app/node_modules/vite/dist/node/index.js';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { observerRequestGuard } from './observer-request-guard.mjs';

const root = fileURLToPath(new URL('../../../', import.meta.url)).replace(/\/$/, '');
const here = fileURLToPath(new URL('.', import.meta.url)).replace(/\/$/, '');
const runtimeStateFile = process.env.EXULANICA_REVIEW_RUNTIME_STATE_FILE;
if (!runtimeStateFile) throw Error('Set EXULANICA_REVIEW_RUNTIME_STATE_FILE to a private runtime descriptor.');
const reviewPort = Number(process.env.EXULANICA_REVIEW_PORT || 19974);
const observerOnly = process.env.EXULANICA_REVIEW_OBSERVER_ONLY === '1';
if (![19974, 20032].includes(reviewPort) || observerOnly !== (reviewPort === 20032) || reviewPort === 20032 && !runtimeStateFile) throw Error('Use the primary19974 review or an explicitly configured pilot20032 observer.');
let runtime;
try { runtime = JSON.parse(readFileSync(runtimeStateFile, 'utf8')); }
catch { throw Error('The private runtime descriptor could not be read.'); }
if (!Number.isInteger(runtime.ports?.api) || runtime.ports.api < 1024 || runtime.ports.api > 65535 || typeof runtime.token_file !== 'string') throw Error('Review runtime API/token binding is invalid.');
if (observerOnly && runtime.ports.api !== 20031) throw Error('The pilot observer must use its isolated API20031.');
const token = readFileSync(runtime.token_file, 'utf8').trim();
const api = 'http://127.0.0.1:' + runtime.ports.api;
process.env.VITE_EXULANICA_TOKEN = token;
process.env.VITE_EXULANICA_REVIEW_OBSERVER_ONLY = observerOnly ? '1' : '0';
process.env.EXULANICA_API_URL = api;
const loaded = await loadConfigFromFile({ command: 'serve', mode: 'development' }, root + '/web/packages/app/vite.config.ts');
const mountHook = 'void objects.begin(state.activeWorldEntry?.authoredVersionId);';
const startHook = '    await mountNoWorld({ retry: () => start(token, csrfToken) });';
const pickHook = '    const pickAlong = (';
const plugin = {
  name: 'private-blank-world-workspace',
  enforce: 'pre',
  transform(code, id) {
    if (id === root + '/web/packages/app/src/composition/environment-selection.ts') {
      if (!code.includes(pickHook)) throw Error('Native read-only picker seam changed.');
      return code.replace(pickHook, '    atlas.__workspacePick = pickedAlong;\n' + pickHook);
    }
    if (id !== root + '/web/packages/app/src/main.ts') return;
    if (![mountHook, startHook, 'void environmentSelection.begin();'].every(seam => code.includes(seam))) throw Error('Native workspace seam changed.');
    return `import { mountContextualWorld } from '/@fs/${here}/contextual-world.ts';\n` + code
      .replace(startHook, `    const reviewEntryId = new URLSearchParams(location.search).get('entry');
    if (reviewEntryId) {
      const reviewEntry = state.savedWorldEntries.find(entry => entry.entryId === reviewEntryId);
      if (reviewEntry) { await openWorldEntryContext(state, reviewEntry); state.worldEntryError = null; shell.removeAttribute('data-world-state'); await mount(); return; }
      pendingEntryProblem = 'This saved world is no longer available. Choose a world here.';
    }
` + startHook)
      .replace('void environmentSelection.begin();', 'await environmentSelection.begin();')
      .replace(mountHook, `await objects.begin(state.activeWorldEntry?.authoredVersionId);
      if (state.activeWorldEntry) await mountContextualWorld({state, renderer, selection: environmentSelection, objects});`);
  },
  configureServer(server) {
    if (observerOnly) server.middlewares.use('/api', observerRequestGuard);
    server.middlewares.use('/review-api', async (req, res) => {
      res.setHeader('Cache-Control', 'no-store');
      res.setHeader('Content-Type', 'application/json');
      if (req.method !== 'GET') { res.statusCode = 405; res.end(JSON.stringify({ detail: 'Use the native controls for changes.' })); return; }
      try {
        const response = await fetch(api + (req.url || '/'), { headers: { Authorization: 'Bearer ' + token }, signal: AbortSignal.timeout(15000) });
        res.statusCode = response.status;
        res.end(await response.text());
      } catch { res.statusCode = 502; res.end(JSON.stringify({ detail: 'The saved world could not be reached. Try again.' })); }
    });
  },
};
const server = await createServer({
  ...loaded.config, configFile: false, root: root + '/web/packages/app', cacheDir: root + '/.exulanica/local/preview-cache/' + reviewPort,
  plugins: [plugin, ...(loaded.config.plugins || [])],
  server: { ...loaded.config.server, watch: null, port: reviewPort, host: '127.0.0.1', strictPort: true, fs: { allow: [root] } },
});
await server.listen();
console.log('World workspace preview: http://127.0.0.1:' + reviewPort + '/?entry=<owned-entry-id>');
