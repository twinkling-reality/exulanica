import { createServer, loadConfigFromFile } from '../../../web/packages/app/node_modules/vite/dist/node/index.js';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { CAPTURE_ROUTE } from './front-door-routes.mjs';
import { capturePictures, capturesModule, readCaptureCatalog, scenePreviewWriteGuard } from './front-door-server.mjs';
import { observerRequestGuard } from './observer-request-guard.mjs';
import { patchSource } from './seams.mjs';

const root = fileURLToPath(new URL('../../../', import.meta.url)).replace(/\/$/, '');
const here = fileURLToPath(new URL('.', import.meta.url)).replace(/\/$/, '');
const runtimeStateFile = process.env.EXULANICA_REVIEW_RUNTIME_STATE_FILE;
if (!runtimeStateFile) throw Error('Set EXULANICA_REVIEW_RUNTIME_STATE_FILE to a private runtime descriptor.');
// A person's own install (scripts/acceptance/launch.py up --personal) names its slot's app port;
// otherwise the primary review's 19974 or the pilot observer's 20032.
const launchedPort = process.env.EXULANICA_WORKSPACE_PORT ? Number(process.env.EXULANICA_WORKSPACE_PORT) : null;
const reviewPort = launchedPort ?? Number(process.env.EXULANICA_REVIEW_PORT || 19974);
const observerOnly = process.env.EXULANICA_REVIEW_OBSERVER_ONLY === '1';
if (launchedPort !== null) {
  if (!Number.isInteger(launchedPort) || launchedPort < 1024 || launchedPort > 65535 || launchedPort === 20032 || observerOnly) throw Error('A launched workspace takes a private port of its own and is never the observer.');
} else if (![19974, 20032].includes(reviewPort) || observerOnly !== (reviewPort === 20032) || reviewPort === 20032 && !runtimeStateFile) throw Error('Use the primary19974 review or an explicitly configured pilot20032 observer.');
let runtime;
try { runtime = JSON.parse(readFileSync(runtimeStateFile, 'utf8')); }
catch { throw Error('The private runtime descriptor could not be read.'); }
if (!Number.isInteger(runtime.ports?.api) || runtime.ports.api < 1024 || runtime.ports.api > 65535 || typeof runtime.token_file !== 'string') throw Error('Review runtime API/token binding is invalid.');
if (observerOnly && runtime.ports.api !== 20031) throw Error('The pilot observer must use its isolated API20031.');
// Optional private captures for the front door's filmstrip; without them each card shows the
// picture this browser kept of its world.
const previewDirectory = process.env.EXULANICA_REVIEW_PREVIEWS_DIRECTORY || null;
const captures = readCaptureCatalog(previewDirectory);
const token = readFileSync(runtime.token_file, 'utf8').trim();
const api = 'http://127.0.0.1:' + runtime.ports.api;
process.env.VITE_EXULANICA_TOKEN = token;
process.env.VITE_EXULANICA_REVIEW_OBSERVER_ONLY = observerOnly ? '1' : '0';
process.env.EXULANICA_API_URL = api;
const loaded = await loadConfigFromFile({ command: 'serve', mode: 'development' }, root + '/web/packages/app/vite.config.ts');
const plugin = {
  name: 'private-blank-world-workspace',
  enforce: 'pre',
  ...capturesModule(captures),
  // The edits and their seams live in seams.mjs, which the app's tests check against the sources.
  transform(code, id) {
    return id.startsWith(root + '/') ? patchSource(id.slice(root.length + 1), code, here) : null;
  },
  configureServer(server) {
    // Before the API proxy: a scene preview only reads.
    server.middlewares.use(scenePreviewWriteGuard);
    if (observerOnly) server.middlewares.use('/api', observerRequestGuard);
    server.middlewares.use(CAPTURE_ROUTE.slice(0, -1), capturePictures(captures, previewDirectory));
  },
};
const server = await createServer({
  ...loaded.config, configFile: false, root: root + '/web/packages/app', cacheDir: root + '/.exulanica/local/preview-cache/' + reviewPort,
  plugins: [plugin, ...(loaded.config.plugins || [])],
  server: { ...loaded.config.server, watch: null, port: reviewPort, host: '127.0.0.1', strictPort: true, fs: { allow: [root] } },
});
await server.listen();
console.log('World workspace preview: http://127.0.0.1:' + reviewPort + '/');
