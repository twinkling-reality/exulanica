// @vitest-environment node
import { createHash } from 'node:crypto';
import { createServer as createHttpServer, type Server } from 'node:http';
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createServer, type ViteDevServer } from 'vite';

/**
 * The development evaluation route must be able to load every texture set a tile can cite.
 *
 * Checked through a real Vite development server built from the app's own configuration, the way a
 * browser loads the route: the dev sources module is requested and transformed, each texture set URL
 * it imports is requested as an import, and the URL that answers is fetched for the set's bytes, which
 * must hash to the manifest's pin. A `?url` import Vite does not resolve answers with the file's raw
 * bytes instead of a URL module; that is the failure this holds against.
 */

// Relative to web/, where the suite runs.
const APP = resolve('packages/app');
const MANIFEST = resolve('../assets/textures/manifest.json');

interface PinnedSet { readonly set_id: string; readonly content_sha256: string; readonly byte_size: number }
const pinned = (JSON.parse(readFileSync(MANIFEST, 'utf8')) as { readonly sets: readonly PinnedSet[] }).sets;

let vite: ViteDevServer;
let http: Server;
let origin: string;

beforeAll(async () => {
  vite = await createServer({
    root: APP,
    configFile: join(APP, 'vite.config.ts'),
    logLevel: 'error',
    appType: 'custom',
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  http = createHttpServer(vite.middlewares);
  await new Promise<void>((done) => http.listen(0, '127.0.0.1', done));
  const address = http.address();
  if (address === null || typeof address === 'string') throw new Error('the test server has no port');
  origin = `http://127.0.0.1:${address.port}`;
}, 60_000);

afterAll(async () => {
  await new Promise<void>((done) => http?.close(() => done()));
  await vite?.close();
});

describe('the development evaluation route resolves the texture sets a tile cites', () => {
  it('answers every pinned set with a URL module whose URL serves exactly the pinned bytes', async () => {
    const sources = await fetch(`${origin}/src/dev/generated-tile-sources.ts`);
    expect(sources.status).toBe(200);
    const code = await sources.text();
    expect(pinned.length).toBeGreaterThan(0);
    for (const set of pinned) {
      const specifier = [...code.matchAll(/"([^"]+\.ltex\?[^"]*url[^"]*)"/g)]
        .map((match) => match[1]!)
        .find((candidate) => candidate.includes(set.content_sha256));
      expect(specifier, `${set.set_id} is imported by the dev sources`).toBeDefined();
      const module = await fetch(`${origin}${specifier!.includes('import') ? specifier : specifier!.replace('?', '?import&')}`);
      expect(module.status).toBe(200);
      expect(module.headers.get('content-type'), `${set.set_id} answers with a module, not its bytes`).toMatch(/javascript/);
      const url = (await module.text()).match(/export default "([^"]+)"/)?.[1];
      expect(url, `${set.set_id} resolves to a URL`).toBeDefined();
      const blob = await fetch(`${origin}${url}`);
      expect(blob.status).toBe(200);
      const bytes = Buffer.from(await blob.arrayBuffer());
      expect(bytes.byteLength).toBe(set.byte_size);
      expect(createHash('sha256').update(bytes).digest('hex')).toBe(set.content_sha256);
    }
  }, 120_000);
});
