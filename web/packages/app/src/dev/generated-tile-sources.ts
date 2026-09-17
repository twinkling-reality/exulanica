/**
 * DEVELOPMENT ONLY: where the evaluation entry finds a baked tile and the texture sets it names.
 *
 * Served from the repository the way `config.ts` serves the owned district: Vite resolves each file
 * to a URL at build time, and the page fetches the bytes. Nothing here is reachable from a
 * production build, because the only importer is `composition/generated-tile.ts`, which is
 * imported only behind `import.meta.env.DEV`; `test/generated-tile-evaluation.test.ts` builds the
 * app and proves no tile, texture set or tile code is emitted.
 *
 * A tile is named by its file name without `.owd`, and only `./tiles/` is searched: pinned golden
 * bakes this entry carries for development (see `./tiles/README.md`). Baked corridor streets are not
 * files in the repository; they live in the baked tile store and a permission-gated route serves
 * them, so they are not reachable from here.
 */

import textureManifestUrl from '../../../../../assets/textures/manifest.json?url';

const TILES: Readonly<Record<string, () => Promise<string>>> = import.meta.glob<string>(
  './tiles/*.owd',
  { query: '?url', import: 'default' },
);

const TEXTURE_SETS: Readonly<Record<string, () => Promise<string>>> = import.meta.glob<string>(
  '../../../../../assets/textures/blobs/*.ltex',
  { query: '?url', import: 'default' },
);

export interface GeneratedTileSourceBytes {
  readonly name: string;
  readonly tile: Uint8Array;
  readonly textureManifest: Uint8Array;
  /** Bytes of a pinned set by its content digest, or a refusal if the repository has none. */
  readonly textureSet: (contentSha256: string) => Promise<Uint8Array>;
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

export async function generatedTileSource(name: string): Promise<GeneratedTileSourceBytes> {
  const matches = Object.entries(TILES).filter(([path]) => baseName(path, '.owd') === name);
  if (matches.length === 0) {
    const known = generatedTileNames();
    throw new Error(`No baked tile named ${name}. This server has ${known.length === 0 ? 'none' : known.join(', ')}.`);
  }
  if (matches.length > 1) throw new Error(`More than one baked tile is named ${name}: ${matches.map(([path]) => path).join(', ')}`);
  const [, resolve] = matches[0]!;
  const [tile, textureManifest] = await Promise.all([
    resolve().then((url) => bytesAt(url, `Tile ${name}`)),
    bytesAt(textureManifestUrl, 'The texture manifest'),
  ]);
  return {
    name,
    tile,
    textureManifest,
    async textureSet(contentSha256: string): Promise<Uint8Array> {
      const entry = Object.entries(TEXTURE_SETS).find(([candidate]) => baseName(candidate, '.ltex') === contentSha256);
      if (entry === undefined) throw new Error(`No committed texture set has digest ${contentSha256}`);
      return bytesAt(await entry[1](), `Texture set ${contentSha256}`);
    },
  };
}
