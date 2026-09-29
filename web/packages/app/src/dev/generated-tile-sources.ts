/**
 * DEVELOPMENT ONLY: where the evaluation entry finds a baked tile.
 *
 * Served from the repository the way `config.ts` serves the owned district: Vite resolves each file
 * to a URL at build time, and the page fetches the bytes. Nothing here is reachable from a
 * production build, because the only importer is `composition/generated-tile.ts`, which is
 * imported only behind `import.meta.env.DEV`; `test/generated-tile-evaluation.test.ts` builds the
 * app and proves no development tile is emitted.
 *
 * A tile is named by its file name without `.owd`, and only `./tiles/` is searched: pinned golden
 * bakes this entry carries for development (see `./tiles/README.md`). Baked corridor streets are not
 * files in the repository; they live in the baked tile store and a permission-gated route serves
 * them, so they are not reachable from here.
 *
 * The texture library is separate from the tiles on purpose, and it is not development only: a
 * saved generated world is dressed from the same committed sets
 * (`../texture-library.ts`), so both paths read that one module. Where the container
 * comes from is the part that differs, and it is the part that must never be committed.
 */

import { type CommittedTextureLibrary, committedTextureLibrary } from '../texture-library.js';

export { type CommittedTextureLibrary, committedTextureLibrary };

const TILES: Readonly<Record<string, () => Promise<string>>> = import.meta.glob<string>(
  './tiles/*.owd',
  { query: '?url', import: 'default' },
);

export interface GeneratedTileSourceBytes extends CommittedTextureLibrary {
  readonly name: string;
  readonly tile: Uint8Array;
}

async function bytesAt(url: string, what: string): Promise<Uint8Array> {
  const response = await fetch(url, { credentials: 'same-origin' });
  if (!response.ok) throw new Error(`${what} unavailable: HTTP ${response.status}`);
  return new Uint8Array(await response.arrayBuffer());
}

function baseName(path: string, extension: string): string {
  const file = path.slice(path.lastIndexOf('/') + 1);
  return file.endsWith(extension) ? file.slice(0, -extension.length) : file;
}

/** The tile names this development server can serve. */
export function generatedTileNames(): readonly string[] {
  return Object.keys(TILES).map((path) => baseName(path, '.owd')).sort();
}

/** A pinned development tile by name, with the committed texture library it is dressed from. */
export async function generatedTileSource(name: string): Promise<GeneratedTileSourceBytes> {
  const matches = Object.entries(TILES).filter(([path]) => baseName(path, '.owd') === name);
  if (matches.length === 0) {
    const known = generatedTileNames();
    throw new Error(`No baked tile named ${name}. This server has ${known.length === 0 ? 'none' : known.join(', ')}.`);
  }
  if (matches.length > 1) throw new Error(`More than one baked tile is named ${name}: ${matches.map(([path]) => path).join(', ')}`);
  const [, resolve] = matches[0]!;
  const [tile, library] = await Promise.all([
    resolve().then((url) => bytesAt(url, `Tile ${name}`)),
    committedTextureLibrary(),
  ]);
  return { name, tile, ...library };
}
