/**
 * The looks the host serves, read once for the page: each pack as the Look sheet and the Look row
 * offer it, its picture, and which pack the host draws a world in when the world names none.
 *
 * `world-look.js` loads with a generated world's tiles, never with the page, so it is loaded here
 * on demand too. Pictures are fetched by the digest the list names and held to it
 * (`stylePackContent`), kept for the page's life as page-local addresses; a pack with none, or one
 * that could not be read, has none. The default is the pack the host's list marks default
 * (`listedDefault`), which is the page's own `DEFAULT_WORLD_LOOK` only from a host that marks none.
 */

import type { Credentials } from '../config.js';
import type { LookOption } from '../ui/look-sheet.js';
import type { ListedStylePack } from '../world-look.js';
import type { WorldStylePackBinding } from '../world-style-api.js';

export interface LookLibrary {
  readonly packs: readonly ListedStylePack[];
  /** Each pack as a person is offered it, pictures fetched, in the list's order. */
  readonly options: readonly LookOption[];
  /** The pack a world naming none is drawn in, or null where there is none to name. */
  readonly defaultId: string | null;
  /** The exact pack to ask for, by the list's version and digest; null for one not listed. */
  binding(packId: string): WorldStylePackBinding | null;
}

const pictures = new Map<string, Promise<string | null>>();

function picture(access: Credentials, pack: ListedStylePack): Promise<string | null> {
  const sha = pack.preview_sha256 ?? null;
  if (sha === null) return Promise.resolve(null);
  let held = pictures.get(sha);
  if (held === undefined) {
    held = import('../world-look.js')
      .then((look) => look.stylePackContent(access, sha, `${pack.title}'s picture`))
      .then((bytes) => URL.createObjectURL(new Blob([bytes], { type: pack.preview_media_type ?? 'image/jpeg' })))
      .catch(() => { pictures.delete(sha); return null; });
    pictures.set(sha, held);
  }
  return held;
}

/** The host's looks, with their pictures and default; a list that cannot be read rejects. */
export async function readLookLibrary(access: Credentials): Promise<LookLibrary> {
  const look = await import('../world-look.js');
  const packs = await look.listedStylePacks(access);
  const shown = await Promise.all(packs.map((pack) => picture(access, pack)));
  const options: readonly LookOption[] = packs.map((pack, index) => ({
    packId: pack.pack_id, title: pack.title, description: pack.description, authors: pack.authors,
    licence: pack.licence, picture: shown[index] ?? null,
  }));
  return {
    packs,
    options,
    defaultId: look.listedDefault(packs)?.pack_id ?? look.DEFAULT_WORLD_LOOK,
    binding(packId) {
      const listed = packs.find((pack) => pack.pack_id === packId);
      return listed === undefined ? null : { packId: listed.pack_id, version: listed.version, manifestSha256: listed.manifest_sha256 };
    },
  };
}
