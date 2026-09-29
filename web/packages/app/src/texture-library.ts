/**
 * The committed texture library a generated tile is dressed with: the manifest and every set.
 *
 * Both are files of this repository (`assets/textures/`), so the build emits them as assets and
 * the page fetches a set only when a tile it draws cites it. No route serves the published texture
 * library, so a baked tile is always dressed from these. Shared by the development preview
 * (`./dev/generated-tile-sources.ts`) and a saved generated world (`./composition/generated-world.ts`).
 */

import textureManifestUrl from '../../../../assets/textures/manifest.json?url';

/**
 * The committed sets' URLs, imported eagerly. The blobs sit outside the app's workspace, and Vite's
 * development server resolves a `?url` import of such a file only when a module imports it statically
 * (as the manifest above is); a lazy import of one is answered with its raw bytes instead of a URL
 * module, so the page could not load it. Eager imports are static, and they carry URLs, not bytes.
 * `test/generated-tile-sources.test.ts` resolves every pinned set through a real development server.
 */
const TEXTURE_SETS: Readonly<Record<string, string>> = import.meta.glob<string>(
  '../../../../assets/textures/blobs/*.ltex',
  { query: '?url', import: 'default', eager: true },
);

/** The committed texture library, which a tile from any source draws with. */
export interface CommittedTextureLibrary {
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

export async function committedTextureLibrary(): Promise<CommittedTextureLibrary> {
  const textureManifest = await bytesAt(textureManifestUrl, 'The texture manifest');
  return {
    textureManifest,
    async textureSet(contentSha256: string): Promise<Uint8Array> {
      const entry = Object.entries(TEXTURE_SETS).find(([candidate]) => baseName(candidate, '.ltex') === contentSha256);
      if (entry === undefined) throw new Error(`No committed texture set has digest ${contentSha256}`);
      return bytesAt(entry[1], `Texture set ${contentSha256}`);
    },
  };
}
