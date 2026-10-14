// What the workspace server adds for its front door (front-door.ts): the private captures a person
// may supply for the filmstrip, and the rule that a scene preview only reads. serve.mjs uses these;
// verify-front-door.mjs checks them.
import { createReadStream, existsSync, readFileSync, statSync } from 'node:fs';
import { extname, resolve } from 'node:path';
import { isScenePreview } from './front-door-routes.mjs';

export const CAPTURE_CATALOG_PROFILE = 'exulanica.private-world-preview/v1';
/** What a capture was taken of; the page shows it only while all of these still hold. */
const IDENTITIES = Object.freeze(['entry_id', 'world_id', 'version_id', 'authored_state_sha256', 'style_version_id']);
const PICTURES = Object.freeze({ '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.avif': 'image/avif' });
const CAPTURES_MODULE = 'virtual:front-door-captures';

/**
 * The captures a private catalog names, reduced to what the page matches on. A catalog with a capture
 * that names no picture file or lacks an identity is refused whole.
 */
export function checkedCaptureCatalog(catalog) {
  if (catalog?.profile !== CAPTURE_CATALOG_PROFILE || !Array.isArray(catalog.captures)) {
    throw Error('The private capture catalog is not a capture catalog.');
  }
  return {
    profile: CAPTURE_CATALOG_PROFILE,
    captures: catalog.captures.map((one) => {
      const file = one?.file;
      const picture = typeof file === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]*$/u.test(file)
        && Object.hasOwn(PICTURES, extname(file).toLowerCase());
      if (!picture || IDENTITIES.some((key) => typeof one[key] !== 'string' || one[key] === '')) {
        throw Error('A capture in the private catalog names no picture or no identity.');
      }
      return Object.fromEntries([...IDENTITIES, 'file'].map((key) => [key, one[key]]));
    }),
  };
}

/**
 * The private capture catalog in `directory` (EXULANICA_REVIEW_PREVIEWS_DIRECTORY), checked. Without
 * a directory there are no captures, and each card shows the picture this browser kept of its world.
 */
export function readCaptureCatalog(directory) {
  if (!directory) return { profile: CAPTURE_CATALOG_PROFILE, captures: [] };
  let catalog;
  try { catalog = JSON.parse(readFileSync(resolve(directory, 'catalog.json'), 'utf8')); }
  catch { throw Error('The private capture catalog could not be read.'); }
  return checkedCaptureCatalog(catalog);
}

/** Plugin hooks that hand the page the checked catalog as `virtual:front-door-captures`. */
export function capturesModule(catalog) {
  const resolved = '\0' + CAPTURES_MODULE;
  return {
    resolveId: (source) => (source === CAPTURES_MODULE ? resolved : null),
    load: (id) => (id === resolved ? `export default ${JSON.stringify(catalog)};\n` : null),
  };
}

/** Middleware serving the catalog's own pictures from `directory`, and nothing else. */
export function capturePictures(catalog, directory) {
  const files = new Set(catalog.captures.map((one) => one.file));
  return (req, res) => {
    let name = '';
    try { name = decodeURIComponent(new URL(req.url || '/', 'http://127.0.0.1/').pathname.slice(1)); } catch { /* not a name */ }
    const file = directory && files.has(name) ? resolve(directory, name) : null;
    if (file === null || (req.method !== 'GET' && req.method !== 'HEAD') || !existsSync(file) || !statSync(file).isFile()) {
      res.statusCode = 404;
      res.end();
      return;
    }
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('Content-Type', PICTURES[extname(file).toLowerCase()]);
    if (req.method === 'HEAD') { res.end(); return; }
    createReadStream(file).pipe(res);
  };
}

/**
 * A scene preview only reads. A request its page makes with any other method is refused here, before
 * the API proxy, as the page's own guard (front-door-preview.ts) refuses it first.
 */
export function scenePreviewWriteGuard(req, res, next) {
  let preview = false;
  try { preview = isScenePreview(new URL(req.headers?.referer || 'http://127.0.0.1/')); } catch { /* no page named */ }
  if (!preview || req.method === 'GET' || req.method === 'HEAD') { next(); return; }
  res.statusCode = 405;
  res.setHeader('Allow', 'GET, HEAD');
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify({ detail: 'The world preview is read-only.' }));
}
