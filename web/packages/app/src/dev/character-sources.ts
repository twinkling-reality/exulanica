/**
 * DEVELOPMENT ONLY: character containers served from the repository for the preview route.
 *
 * Vite resolves each committed container under `assets/characters/` to a URL, and the page fetches
 * the bytes; the character host then checks length and SHA-256 against the catalog before decoding.
 * Nothing here is reachable from a production build: the only importer is
 * `composition/character.ts`, behind `import.meta.env.DEV` and the preview route, and
 * `test/character-sources.test.ts` builds the app and proves no container is emitted. A signed-in
 * world fetches the same bytes as reviewed assets from `/world/assets/<asset key>/bytes`.
 */

import { CHARACTER_CATALOG, type CharacterByteLoader } from '@exulanica/atlas-react/playcanvas';
import stylizedLooksUrl from '../../../../../assets/characters/stylized-looks.json?url';
import editableHumanUrl from '../../../../../assets/characters/makehuman-parametric-v1/default.look.json?url';

const CONTAINERS: Readonly<Record<string, () => Promise<string>>> = import.meta.glob<string>(
  '../../../../../assets/characters/**/*.glb',
  { query: '?url', import: 'default' },
);

const ROOT = '../../../../../assets/characters/';

/** Repository files by path under `assets/characters/`, as the catalog names them. */
export function developmentCharacterFiles(): readonly string[] {
  return Object.keys(CONTAINERS).map((path) => path.slice(ROOT.length)).sort();
}

/**
 * A loader for references that name their repository file. `files` maps a content digest to its
 * path under `assets/characters/`; a digest nobody listed is refused rather than guessed at.
 */
export function developmentCharacterLoader(files: ReadonlyMap<string, string>): CharacterByteLoader {
  return async (reference, signal) => {
    const file = files.get(reference.contentSha256);
    const resolve = file === undefined ? undefined : CONTAINERS[ROOT + file];
    if (resolve === undefined) throw new Error(`No committed character container has digest ${reference.contentSha256}`);
    const response = await fetch(await resolve(), { signal, credentials: 'same-origin' });
    if (!response.ok) throw new Error(`Character container ${file} unavailable: HTTP ${response.status}`);
    return response.arrayBuffer();
  };
}

/** Every catalog container's repository file, by content digest. */
export function catalogCharacterFiles(): Map<string, string> {
  const files = new Map<string, string>();
  for (const family of CHARACTER_CATALOG.families) {
    for (const base of family.bases) {
      files.set(base.asset.contentSha256, base.asset.file);
      for (const part of base.parts) if (part.asset) files.set(part.asset.contentSha256, part.asset.file);
    }
    for (const material of family.materials) files.set(material.asset.contentSha256, material.asset.file);
  }
  return files;
}

/**
 * The committed stylized looks: the editable human's default and the Quaternius looks, as the app's
 * look list reads them, with each container's repository file by digest.
 */
export async function developmentStylizedLooks(signal: AbortSignal): Promise<{ readonly looks: unknown; readonly files: Map<string, string> }> {
  const read = async (url: string, what: string): Promise<unknown> => {
    const response = await fetch(url, { signal, credentials: 'same-origin' });
    if (!response.ok) throw new Error(`${what} unavailable: HTTP ${response.status}`);
    return response.json() as Promise<unknown>;
  };
  const [stylized, editable] = await Promise.all([
    read(stylizedLooksUrl, 'Stylized character looks') as Promise<{ readonly profile?: unknown; readonly looks?: unknown }>,
    read(editableHumanUrl, 'The editable human') as Promise<{ readonly file?: unknown; readonly descriptor?: { readonly asset?: { readonly contentSha256?: unknown } } }>,
  ]);
  if (stylized.profile !== 'exulanica.character-stylized-looks/v1' || !Array.isArray(stylized.looks)) {
    throw new Error('The committed stylized looks could not be read.');
  }
  const files = new Map<string, string>();
  const bind = (look: { readonly file?: unknown; readonly descriptor?: { readonly asset?: { readonly contentSha256?: unknown } } }, folder: string) => {
    const digest = look.descriptor?.asset?.contentSha256;
    if (typeof digest === 'string' && typeof look.file === 'string') files.set(digest, `${folder}/${look.file}`);
  };
  bind(editable, 'makehuman-parametric-v1');
  for (const look of stylized.looks as { readonly file?: unknown }[]) bind(look, 'quaternius-modular-v2');
  return { looks: [editable, ...stylized.looks], files };
}
