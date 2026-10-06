/**
 * The look a generated world opens in: one of the host's committed style packs, or the tile look.
 *
 * A pack (`docs/style-pack-contract.md`) is data the host serves, never part of the page's bundle,
 * as no 3D content is: `GET /world/style-packs` lists the packs, and `GET /world/style-packs/{sha256}`
 * serves a manifest or a piece by the SHA-256 of its bytes. The page finds the pack in the list,
 * fetches its manifest by the digest the list names and holds the bytes to it, reads the manifest
 * with the browser's reader against the look-family catalog and the texture library, and fetches
 * each piece by the digest its manifest states, held to it again. Then the world is drawn in it:
 * the pack's default light preset becomes the tiles' render look, its surfaces dress the town's
 * texture sets, its window pieces stand in the facades' openings, its vehicles are the traffic's
 * bodies, and its ink outlines the tiles when its shading draws ink. Nothing about the world's
 * records, its navigation or what anyone can walk on changes; taking the tiles down puts everything
 * back.
 *
 * Which pack (`worldLookChoice`): the one the page's address names (`?look=toon`, `cozy`,
 * `finished`, or `today` for the tile look), which is presentation only and read from a closed list
 * of words for the team's packs; else the pack the world's appearance names (its style version's
 * binding), fetched by the very manifest digest it names; else `DEFAULT_WORLD_LOOK`.
 */

import type { LookFamily, ResolvedStylePack } from '@exulanica/atlas-core';
import type { GeneratedTileAttachment, GeneratedTileHost, LoadedGeneratedTile, RenderLook } from '@exulanica/atlas-react/generated-tile';
import type { FetchedPieces, OpeningSlot, PackVehicleBodies, TownLookRoles } from '@exulanica/atlas-react/style-pack';
import type { VehicleBodies } from '@exulanica/atlas-react/traffic';
import type { Credentials } from './config.js';
import type { WorldStylePackBinding } from './world-style-api.js';
import lookFamilyText from '../../../../assets/catalogs/world-kinds/look-family.v1.json?raw';
import townRolesText from '../../../../assets/style-packs/town-look-roles.v1.json?raw';
import colourTableText from '../../../../assets/colour/srgb8-linear16.v1.json?raw';

/** The profile of the host's list of committed packs. */
export const STYLE_PACK_LIST_PROFILE = 'exulanica.style-pack-list/v1';

/** The team's packs a page's address may name, by the word it names them with. */
export const WORLD_LOOKS = Object.freeze({
  toon: 'exulanica.toon-town',
  cozy: 'exulanica.cozy-town',
  finished: 'exulanica.finished-town',
} as const);

/** The pack a generated world opens in when the address names none: the cozy town. */
export const DEFAULT_WORLD_LOOK: string | null = WORLD_LOOKS.cozy;

/**
 * The pack the page's address names: a pack id, null for the tile look (`today`), or undefined when
 * it names none of the closed list's words.
 */
export function addressedWorldLook(search: string): string | null | undefined {
  const word = new URLSearchParams(search).get('look');
  if (word === 'today') return null;
  if (word !== null && Object.hasOwn(WORLD_LOOKS, word)) return WORLD_LOOKS[word as keyof typeof WORLD_LOOKS];
  return undefined;
}

/** The look a generated world is drawn in, and what chose it. */
export interface WorldLookChoice {
  /** The pack, or null for the tile look. */
  readonly packId: string | null;
  /** The manifest a world's appearance names exactly; null to read the host's list for the pack. */
  readonly manifestSha256: string | null;
  readonly source: 'address' | 'world' | 'default' | 'redraw';
}

/** The address's pack, else the pack the world's appearance names, else the default. */
export function worldLookChoice(search: string, bound: WorldStylePackBinding | null): WorldLookChoice {
  const addressed = addressedWorldLook(search);
  if (addressed !== undefined) return { packId: addressed, manifestSha256: null, source: 'address' };
  if (bound !== null) return { packId: bound.packId, manifestSha256: bound.manifestSha256, source: 'world' };
  return { packId: DEFAULT_WORLD_LOOK, manifestSha256: null, source: 'default' };
}

/** One pack as the host lists it. */
export interface ListedStylePack {
  readonly pack_id: string;
  readonly version: number;
  readonly manifest_sha256: string;
  readonly title: string;
  /** What the pack looks like, in the pack's own words. */
  readonly description: string;
  readonly authors: readonly string[];
  readonly licence: { readonly id: string; readonly attribution: string | null };
  /** The pack's preview picture by digest, fetched like any piece; null for a pack with none. */
  readonly preview_sha256?: string | null;
  readonly preview_media_type?: string | null;
}

/** A pack read, resolved and its pieces fetched and checked, ready to draw a world in. */
export interface PreparedWorldLook {
  readonly packId: string;
  readonly pack: ResolvedStylePack;
  readonly look: RenderLook;
  readonly families: ReadonlyMap<string, LookFamily>;
  readonly roles: TownLookRoles;
  readonly pieces: FetchedPieces;
  /** The windows of the world's facades, which the pack's window pieces stand in. */
  readonly slots: readonly OpeningSlot[];
  readonly style: typeof import('@exulanica/atlas-react/style-pack');
  readonly attachTileInk: typeof import('@exulanica/atlas-react/generated-tile').attachTileInk;
}

function lookFamilies(): ReadonlyMap<string, LookFamily> {
  const catalog = JSON.parse(lookFamilyText) as {
    entries: { key: string; fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }[];
  };
  return new Map(catalog.entries.map((entry) => [entry.key, {
    fit: entry.fit, dressing: entry.dressing, fillMinimumPermille: entry.fill_minimum_permille, fillMaximumPermille: entry.fill_maximum_permille,
  }]));
}

function hex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function hostGet(access: Credentials, path: string, what: string): Promise<Response> {
  const response = await fetch(`${access.baseUrl}${path}`, {
    headers: { Authorization: `Bearer ${access.token}` },
    credentials: 'same-origin',
  });
  if (!response.ok) throw new Error(`${what} unavailable: HTTP ${response.status}`);
  return response;
}

/** The host's committed packs. */
export async function listedStylePacks(access: Credentials): Promise<readonly ListedStylePack[]> {
  const list = await (await hostGet(access, '/world/style-packs', 'The style pack list')).json() as {
    profile?: unknown; packs?: unknown;
  };
  if (list.profile !== STYLE_PACK_LIST_PROFILE || !Array.isArray(list.packs)) {
    throw new Error(`The style pack list is not ${STYLE_PACK_LIST_PROFILE}`);
  }
  return list.packs as readonly ListedStylePack[];
}

/** The bytes the host serves for `sha256`, held to that digest. */
export async function stylePackContent(access: Credentials, sha256: string, what: string): Promise<Uint8Array<ArrayBuffer>> {
  if (!/^[0-9a-f]{64}$/.test(sha256)) throw new Error(`${what} is not named by a SHA-256`);
  const response = await hostGet(access, `/world/style-packs/${sha256}`, what);
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (hex(await crypto.subtle.digest('SHA-256', bytes)) !== sha256) {
    throw new Error(`${what} arrived as bytes that are not the ones its digest names`);
  }
  return bytes;
}

/**
 * Read the host's pack `packId` against the texture library the world is drawn with, fetch and
 * check its pieces, and find the windows of the world's tile `containers`. `manifestSha256` names
 * the exact manifest a world's appearance names; without it the host's list names the current one.
 */
export async function prepareWorldLook(
  access: Credentials,
  packId: string,
  textureManifest: Uint8Array,
  containers: readonly Uint8Array[],
  manifestSha256: string | null = null,
): Promise<PreparedWorldLook> {
  let digest = manifestSha256;
  if (digest === null) {
    const listed = (await listedStylePacks(access)).find((entry) => entry.pack_id === packId);
    if (listed === undefined) throw new Error(`The host serves no style pack ${packId}`);
    digest = listed.manifest_sha256;
  }
  const manifest = await stylePackContent(access, digest, `${packId} manifest`);
  const [style, { attachTileInk }, { parseTextureSetManifest, readStylePackManifest, resolveStylePack }] = await Promise.all([
    import('@exulanica/atlas-react/style-pack'),
    import('@exulanica/atlas-react/generated-tile'),
    import('@exulanica/atlas-core'),
  ]);
  const { fetchPackPieces, renderLookOfPreset } = style;
  const families = lookFamilies();
  const textureSets = new Set(parseTextureSetManifest(textureManifest).byId.keys());
  const read = readStylePackManifest(JSON.parse(new TextDecoder().decode(manifest)), { families, textureSets });
  if (read.pack_id !== packId) throw new Error(`The manifest served for ${packId} names ${read.pack_id}`);
  const pack = resolveStylePack([read]);
  const look = renderLookOfPreset(pack.light.presets[pack.light.default_preset]!, pack.shading, pack.edge);
  const table = (JSON.parse(colourTableText) as { values: number[] }).values;
  const pieces = await fetchPackPieces(pack, Object.keys(pack.modules), table, (file) => (
    stylePackContent(access, file.sha256, `${packId} ${file.path}`)
  ));
  const slots = style.containerOpeningSlots(containers);
  return { packId, pack, look, families, roles: JSON.parse(townRolesText) as TownLookRoles, pieces, slots, style, attachTileInk };
}

/** A world's tile drawn in a prepared pack, and the vehicle bodies its traffic takes while attached. */
export interface WorldInLook {
  readonly tile: LoadedGeneratedTile;
  readonly bodies: () => VehicleBodies | null;
}

/** The tile, dressed in `prepared` when it is attached. The tile must have been loaded with `prepared.look`. */
export function inWorldLook(tile: LoadedGeneratedTile, prepared: PreparedWorldLook): WorldInLook {
  const { style, slots } = prepared;
  let bodies: PackVehicleBodies | null = null;
  return {
    bodies: () => bodies,
    tile: {
      ...tile,
      attach(host: GeneratedTileHost): GeneratedTileAttachment {
        const attachment = tile.attach(host);
        const shading = prepared.look.shading;
        const pieces = style.uploadPackPieces(host.app.graphicsDevice, prepared.pieces);
        const surfaces = style.dressTownSurfaces(host.environmentRoot, prepared.pack, prepared.roles, prepared.families, shading);
        const windows = style.dressSlots(host.environmentRoot, slots, prepared.pack, prepared.families, pieces, shading);
        const lines = shading.ink === null
          ? null
          : prepared.attachTileInk(host.app.graphicsDevice, host.environmentRoot, shading.ink, undefined, ['generated-tile:', 'style-pack:pieces']);
        bodies = style.packVehicleBodies(prepared.pack, prepared.families, pieces, shading);
        return {
          metrics: attachment.metrics,
          get animating() {
            return attachment.animating ?? false;
          },
          dispose() {
            bodies?.dispose();
            bodies = null;
            lines?.dispose();
            windows.dispose();
            surfaces.dispose();
            pieces.dispose();
            attachment.dispose();
          },
        };
      },
    },
  };
}
