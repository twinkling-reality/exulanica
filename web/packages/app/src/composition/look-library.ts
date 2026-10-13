/**
 * The looks the host serves, read once for the page: each pack as the Look sheet and the Look row
 * offer it, its picture, and which pack the host draws a world in when the world names none.
 *
 * `world-look.js` loads with a generated world's tiles, never with the page, so it is loaded here
 * on demand too. Pictures are fetched by the digest the list names and held to it
 * (`stylePackContent`), kept for the page's life as page-local addresses; a pack with none, or one
 * that could not be read, has none. The default is the pack the host's list marks default
 * (`listedDefault`), which is the page's own `DEFAULT_WORLD_LOOK` only from a host that marks none.
 *
 * What a world is drawn in now is matched by the exact digest its appearance names (`listedVersion`):
 * a pack's current version, an earlier one the host still serves, or none the host lists.
 */

import type { Credentials } from '../config.js';
import { type LookNow, type LookOption, type LookSettings } from '../ui/look-sheet.js';
import type { ListedStylePack } from '../world-look.js';
import type { WorldStylePackBinding } from '../world-style-api.js';

export interface LookLibrary {
  readonly packs: readonly ListedStylePack[];
  /** Each pack as a person is offered it, pictures fetched, in the list's order. */
  readonly options: readonly LookOption[];
  /** The pack a world naming none is drawn in, or null where there is none to name. */
  readonly defaultId: string | null;
  /** The named parts a world's setting is chosen from, or null from a host that lists none. */
  readonly settings: LookSettings | null;
  /** The exact pack to ask for, by the list's version and digest; null for one not listed. */
  binding(packId: string): WorldStylePackBinding | null;
  /**
   * What a world bound to `bound` (null for none, which is the default) is drawn in, for the Look
   * sheet: the pack, and an earlier version or a pack the host does not serve, said with it.
   */
  now(bound: WorldStylePackBinding | null): Promise<{ readonly packId: string | null; readonly how: LookNow }>;
}

/** Said in the Look sheet when a world names a look this host does not list, so it is drawn plainly. */
export const UNSERVED_LOOK_WORDS = 'This world names a look this server does not offer, so it is drawn in its plain tiles. Choose a look to draw it in.';

/**
 * Said in the Look sheet for a world wearing its workspace's own look of new pieces: the look it is
 * drawn on (`title`, null when this host no longer offers it) and whether the own look may be worn.
 */
export function ownLookWords(title: string | null, wearable: boolean): string {
  if (title === null) return 'This world\'s own look of new pieces is drawn on a look this server no longer offers, so it is drawn in its plain tiles. Choose a look to draw it in.';
  if (!wearable) return `This world's own look of new pieces can no longer be worn, so it is drawn in ${title}.`;
  return `This world wears its own look, with new pieces made for it on ${title}. Choosing a look here replaces it.`;
}

const pictures = new Map<string, Promise<string | null>>();

function picture(
  access: Credentials, pack: ListedStylePack, shown: { readonly preview_sha256?: string | null; readonly preview_media_type?: string | null } = pack,
): Promise<string | null> {
  const sha = shown.preview_sha256 ?? null;
  if (sha === null) return Promise.resolve(null);
  let held = pictures.get(sha);
  if (held === undefined) {
    held = import('../world-look.js')
      .then((look) => pack.source === 'workspace'
        ? look.ownLookContent(access, pack.manifest_sha256, sha, `${pack.title}'s picture`)
        : look.stylePackContent(access, sha, `${pack.title}'s picture`))
      .then((bytes) => URL.createObjectURL(new Blob([bytes], { type: shown.preview_media_type ?? 'image/jpeg' })))
      .catch(() => { pictures.delete(sha); return null; });
    pictures.set(sha, held);
  }
  return held;
}

/** The host's looks, with their pictures and default; a list that cannot be read rejects. */
export async function readLookLibrary(access: Credentials): Promise<LookLibrary> {
  const look = await import('../world-look.js');
  const [hostPacks, ownPacks, settings] = await Promise.all([look.listedStylePacks(access),
    look.listedWorkspaceStylePacks(access).catch(() => []), look.listedSettings(access).catch(() => null)]);
  const packs = [...hostPacks, ...ownPacks];
  const choiceId = (pack: ListedStylePack): string => pack.source === undefined ? pack.pack_id
    : `${pack.source}:${pack.pack_id}:${pack.version}:${pack.manifest_sha256}`;
  const shown = await Promise.all(packs.map((pack) => picture(access, pack)));
  const options: readonly LookOption[] = packs.map((pack, index) => ({
    choiceId: choiceId(pack), packId: pack.pack_id, title: pack.title, description: pack.description, authors: pack.authors,
    licence: pack.licence, picture: shown[index] ?? null, version: pack.version, changes: pack.changes ?? null,
  }));
  const defaultPack = look.listedDefault(hostPacks);
  const defaultId = defaultPack === undefined ? look.DEFAULT_WORLD_LOOK : choiceId(defaultPack);
  return {
    packs,
    options,
    defaultId,
    settings,
    binding(packId) {
      const matches = packs.filter(pack => choiceId(pack) === packId || pack.pack_id === packId);
      const listed = matches.length === 1 ? matches[0] : undefined;
      return listed === undefined ? null : { packId: listed.pack_id, version: listed.version, manifestSha256: listed.manifest_sha256,
        ...(listed.source === 'workspace' ? { own: { base: listed.ownBase ?? null, wearable: true } } : {}) };
    },
    async now(bound) {
      if (bound === null) return { packId: defaultId, how: {} };
      const ownListed = look.listedVersion(packs.filter(pack => pack.source === 'workspace'), bound.manifestSha256);
      if (bound.own !== undefined && (ownListed === undefined || !bound.own.wearable)) {
        const base = bound.own.base === null ? undefined : look.listedVersion(packs, bound.own.base.manifestSha256);
        const title = base === undefined ? null : base.pack.title;
        // One that may not be worn is drawn in its base, which the sheet then shows as chosen.
        const shown = base !== undefined && !bound.own.wearable ? choiceId(base.pack) : null;
        return { packId: shown, how: { notice: ownLookWords(title, bound.own.wearable) } };
      }
      const found = bound.own === undefined
        ? look.listedVersion(hostPacks, bound.manifestSha256) : ownListed;
      if (found === undefined) return { packId: null, how: { notice: UNSERVED_LOOK_WORDS } };
      if (found.current) return { packId: choiceId(found.pack), how: {} };
      const version = found.pack.earlier_versions?.find((one) => one.manifest_sha256 === bound.manifestSha256);
      return {
        packId: choiceId(found.pack),
        how: { earlier: { packId: choiceId(found.pack), version: found.version, picture: await picture(access, { ...found.pack, manifest_sha256: bound.manifestSha256 }, version) } },
      };
    },
  };
}
