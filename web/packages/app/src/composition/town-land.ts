/**
 * The land a town made on its land stands on, read through its world's version and drawn round
 * its tiles.
 *
 * A town on land's saved entry names its land by digest (`generatedGround.landSha256`). Its land
 * section (`GET /world/versions/{version}/land`, `exulanica.town-land/v1`) names every chunk round
 * the town and its backdrop by digest, and states its water. The page holds the section to its
 * entity tag, to the world it opened and to that digest, then reads each chunk and the backdrop
 * through the same version and holds each to the digest the section names (`readLandSection`), as
 * a site on land's are. While the kind worker is still making the land, the route answers 503 with
 * a `Retry-After`, and the page asks again after the seconds it states, for at most `LAND_WAIT_MS`
 * in all; the reads go a few at a time and a 429 for the workspace's share waits the same way
 * (`./share-reads.ts`). Land that cannot be read is not stood in for: the world does not open, as it does not
 * with a tile that is not the one its entry names. A town whose tiles still bake asks for its land
 * once beforehand (`askForTownLand`), so the server makes it beside the bakes and keeps it.
 *
 * The tiles draw the town and the terrain under it, and the land is drawn round them: every near
 * chunk no tile covers (a chunk is a tile's square, and chunk (x, y) lies under tile (x, y)), the
 * backdrop to the horizon and the water, under the environment root in the city's frame, with the
 * camera seeing as far as the backdrop reaches. The look's flat plane beyond a town is not drawn
 * (`withoutEdge`): the land is the town's edge. The town's people stand on the ground its tiles
 * walk, and on the land where they walk none (`townGround`), their region at the land's datum, so
 * each piece of its street furniture stands at its own record's height (`furnitureOnLand`), and
 * whoever sits on a bench sits on it, not at the datum.
 *
 * The page's people are drawn on every page, a town's tiles only where one is open, so the land is
 * kept here by the saved entry it was read for, as the town's furniture is (`./town-furniture.ts`),
 * and everything that draws it is loaded with it.
 */

import { LAND_CHUNK_MM, entityTagDigest, sceneryBeyond, type ResolvedStylePack, type Srgb8 } from '@exulanica/atlas-core';
import type { GeneratedTileAttachment, GeneratedTileHost, LoadedGeneratedTile } from '@exulanica/atlas-react/generated-tile';
import type { DrawnSiteLand, SiteLand } from '@exulanica/atlas-react/generated-site';
import { accessHeaders, type Credentials } from '../config.js';
import { readWithinShare } from './share-reads.js';
import type { GeneratedTile, SavedWorldEntry } from '../world-entry-api.js';

/** The profile of a town on its land's land section. */
export const TOWN_LAND_PROFILE = 'exulanica.town-land/v1';

/**
 * The longest a town's land is waited for while the server says it is still being made: as long
 * as the workspace keeps a town's opening up while its tiles bake (`BAKE_POLL_MS` times
 * `BAKE_READS` in `tools/previews/world-workspace/seams.mjs`).
 */
export const LAND_WAIT_MS = 300_000;

/** A town on land's land, read and held, and how to draw it round the town's tiles. */
/** What the land round a town wears: one material for every near chunk, with its surfaces over it. */
type LandGround = DrawnSiteLand['ground'][number]['material'];

/** A colour as a material's diffuse takes it: sRGB, each channel 0 to 1. */
type Rgb = readonly [number, number, number];

/** The look role a town's open ground is drawn in, which the land round it wears too. */
export const OPEN_GROUND_ROLE = 'ground.default';

/**
 * The swatch a look draws a town's open ground in: its `ground.default` surfaces' upward swatch
 * where it states one, else their swatch (`grass` in every shipped look, a setting's own key where
 * a setting gives that ground its colour). Null where the look draws that ground from a texture or
 * states none.
 */
export function openGroundSwatch(pack: Pick<ResolvedStylePack, 'surfaces'>): string | null {
  const surface = pack.surfaces[OPEN_GROUND_ROLE];
  return surface === undefined || !('swatch' in surface) ? null : surface.up ?? surface.swatch;
}

/**
 * The colour a look draws a town's open ground in, sRGB: its open ground's swatch
 * (`openGroundSwatch`) with the world's setting already over it, so the desert sand, snowfields or
 * field of grain a setting states. Null where the look draws that ground from a texture or states
 * none: the land then keeps its own plain ground.
 */
export function openGroundColour(pack: Pick<ResolvedStylePack, 'swatches' | 'surfaces'>): Srgb8 | null {
  const swatch = openGroundSwatch(pack);
  return swatch === null ? null : pack.swatches.get(swatch)?.srgb8 ?? null;
}

/**
 * The open ground of the look a town is drawn in, as its land wears it: the colour, sRGB 0 to 1, and
 * the swatch it is named by, which names the scenery the site scenery catalog stands on such ground
 * (trees on grass). A setting's own swatch names none, so a town in its setting's sand or snow
 * stands on that ground alone.
 */
export interface OpenGround {
  readonly rgb: Rgb;
  readonly swatch: string;
}

export interface TownLand {
  readonly land: SiteLand;
  /**
   * Draw the land under the host's environment root, leaving out the chunks `covered` names, in
   * `open` (the town's look's open ground) with the scenery that ground stands, or, where that is
   * null, in the land's own plain ground with none: with the material its near land wears, or null
   * where it drew none.
   */
  draw(
    host: GeneratedTileHost,
    covered: (chunkX: number, chunkY: number) => boolean,
    open?: OpenGround | null,
  ): { readonly ground?: LandGround | null; dispose(): void };
}

/** A navigation world's walked surface, as far as a person's height is read from it. */
interface WalkedSurface {
  readonly surface: { sample(east: number, south: number): { readonly height: number } | null };
}

let held: { readonly entryId: string; readonly town: TownLand } | null = null;

/** Where a land document of the town an entry opens is read: through its world's version. */
function landAddress(access: Credentials, entry: SavedWorldEntry, path: string): string {
  const query = new URLSearchParams({ world_id: entry.worldId });
  return `${access.baseUrl}/world/versions/${encodeURIComponent(entry.authoredVersionId)}/${path}?${query.toString()}`;
}

/**
 * Ask once for the land section of a town on land, neither waiting for nor reading the answer: the
 * server starts making the land and keeps it once made, so the read that opens the town finds it
 * made. A town on level ground asks nothing.
 */
export function askForTownLand(access: Credentials, entry: SavedWorldEntry): void {
  if (entry.generatedGround?.landSha256 === undefined) return;
  void fetch(landAddress(access, entry, 'land'), {
    headers: { ...accessHeaders(access), Accept: 'application/json' },
    credentials: 'same-origin',
  }).then((response) => response.body?.cancel(), () => {});
}

/**
 * The land a town on land's entry names, read through its world's version: the section, held to
 * its entity tag, its world and the entry's digest, and every chunk and the backdrop it names,
 * each held to the digest the section gives it.
 */
export async function loadTownLand(access: Credentials, entry: SavedWorldEntry, landSha256: string): Promise<TownLand> {
  const [
    { attachLandRound, byTheSea, drawSiteScenery, parseSiteLandSection, readLandSection }, { sha256Hex }, { LAND_SURFACES }, { SITE_SCENERY }, { SURFACE_MATERIALS },
  ] = await Promise.all([
    import('@exulanica/atlas-react/generated-site'),
    import('@exulanica/atlas-react/playcanvas'),
    import('../land-surfaces.js'),
    import('../site-scenery.js'),
    import('../surface-materials.js'),
  ]);
  let bytes = 0;
  const until = Date.now() + LAND_WAIT_MS;
  /** A land document, held to `sha256`, or for the section, to the digest of its own bytes. */
  const read = async (path: string, sha256: string | null): Promise<unknown> => {
    let response: Response;
    for (;;) {
      response = await readWithinShare(landAddress(access, entry, path), {
        headers: { ...accessHeaders(access), Accept: 'application/json' },
        credentials: 'same-origin',
      }, until);
      // Still being made: asked again after the seconds stated, a second at least, until the wait is spent.
      const stated = response.status === 503 ? Number(response.headers.get('Retry-After') ?? Number.NaN) : Number.NaN;
      const ms = Math.max(1, stated) * 1000;
      if (!Number.isFinite(stated) || Date.now() + ms > until) break;
      await new Promise((done) => { setTimeout(done, ms); });
    }
    if (!response.ok) throw new Error(`This town's land could not be read: HTTP ${response.status}.`);
    const body = new Uint8Array(await response.arrayBuffer());
    const tag = entityTagDigest(response.headers.get('ETag'));
    if (tag === null || tag !== (sha256 ?? sha256Hex(body))) throw new Error("This town's land arrived as a document its section does not name.");
    bytes += body.byteLength;
    return JSON.parse(new TextDecoder().decode(body));
  };
  const section = await read('land', null);
  const row = typeof section === 'object' && section !== null && !Array.isArray(section) ? section as Record<string, unknown> : {};
  if (row['profile'] !== TOWN_LAND_PROFILE) throw new Error(`This town's land is not stated as ${TOWN_LAND_PROFILE}.`);
  if (row['world_id'] !== entry.worldId) throw new Error("This town's land was stated for another world.");
  const named = parseSiteLandSection(row['land']);
  if (named.landSha256 !== landSha256) throw new Error("This town's land is not the land its entry names.");
  const [chunks, backdrop] = await Promise.all([
    Promise.all(named.chunks.map(async ({ chunk: [x, y], sha256 }) => [`${x},${y}`, await read(`land/chunks/${x}/${y}`, sha256)] as const)),
    read('land/backdrop', named.backdropSha256),
  ]);
  const land = readLandSection(named, new Map(chunks), backdrop, sha256Hex, bytes);
  return Object.freeze({
    land,
    draw: (host: GeneratedTileHost, covered: (chunkX: number, chunkY: number) => boolean, open: OpenGround | null = null) => {
      const round = attachLandRound(host, land, covered, LAND_SURFACES, open?.rgb);
      // What stands on the land past the town, as a place stands its scenery beyond it: the site
      // scenery catalog's entry for the town's open ground, on dry land only and never on the sand
      // by the sea, from the town's rectangle (the chunks under its tiles) outward.
      const scenery = open === null ? undefined : SITE_SCENERY.byMaterial.get(open.swatch);
      const under = land.chunks.filter((chunk) => covered(chunk.chunkX, chunk.chunkY));
      let stood: { destroy(): void } | null = null;
      if (scenery !== undefined && under.length > 0) {
        const xs = under.map((chunk) => chunk.chunkX), ys = under.map((chunk) => chunk.chunkY);
        const west = Math.min(...xs) * LAND_CHUNK_MM, south = Math.min(...ys) * LAND_CHUNK_MM;
        const extent = { widthMm: (Math.max(...xs) + 1) * LAND_CHUNK_MM - west, depthMm: (Math.max(...ys) + 1) * LAND_CHUNK_MM - south };
        const pieces = sceneryBeyond(entry.worldId, extent, scenery)
          .map((piece) => ({ ...piece, xMm: piece.xMm + west, yMm: piece.yMm + south }))
          .filter((piece) => land.dryAt(piece.xMm, piece.yMm) && !byTheSea(land, LAND_SURFACES, piece.xMm, piece.yMm));
        if (pieces.length > 0) {
          const drawn = drawSiteScenery(host.app.graphicsDevice, { scenery, pieces }, SURFACE_MATERIALS, land.groundMm);
          host.environmentRoot.addChild(drawn.root);
          stood = drawn;
        }
      }
      return { ground: round.drawn.ground[0]?.material ?? null, dispose: () => { stood?.destroy(); round.dispose(); } };
    },
  });
}

/** A look with no flat plane beyond the tiles, for a town whose land is its edge. */
export function withoutEdge<Look extends object>(look: Look): Look {
  return 'edge' in look && look.edge !== null ? { ...look, edge: null } : look;
}

/**
 * The town's tiles with its land drawn round them whenever they are attached: every chunk no tile
 * covers, the backdrop and the water, taken away again with them, in `open` (the open ground of
 * the look the tiles are drawn in, with the scenery it stands) or the land's own where that is null.
 * The tiles' own ground, where no street, footway or lot stands, wears what the land round them
 * wears, so the town's unbuilt land meets its land in one ground rather than in a tile of bare soil
 * (the texture set a town's terrain is dressed in, which its tree pits share and so wear too); the
 * tiles' own material comes back before either is taken away.
 */
export function withTownLand(
  tile: LoadedGeneratedTile,
  town: TownLand,
  tiles: readonly Pick<GeneratedTile, 'tileX' | 'tileY'>[],
  open: OpenGround | null = null,
): LoadedGeneratedTile {
  const under = new Set(tiles.map((one) => `${one.tileX},${one.tileY}`));
  return {
    ...tile,
    attach(host: GeneratedTileHost): GeneratedTileAttachment {
      const attachment = tile.attach(host);
      const drawn = town.draw(host, (chunkX, chunkY) => under.has(`${chunkX},${chunkY}`), open);
      const restore = wearLandGround(host, terrainSets(tile), drawn.ground ?? null);
      return {
        metrics: attachment.metrics,
        get animating() {
          return attachment.animating ?? false;
        },
        dispose() {
          restore();
          drawn.dispose();
          attachment.dispose();
        },
      };
    },
  };
}

/** The texture sets a tile's ground is drawn in: those of its terrain surfaces. */
function terrainSets(tile: LoadedGeneratedTile): ReadonlySet<string> {
  const sets = new Set<string>();
  for (const range of tile.ranges ?? []) {
    if (range.state !== 'drawn') continue;
    for (const surface of range.surfaces) {
      if (surface.role === 'terrain' && surface.textureSetId !== null) sets.add(surface.textureSetId);
    }
  }
  return sets;
}

/** Have every tile batch drawn in one of `sets` wear `ground`; what puts their own material back. */
function wearLandGround(host: GeneratedTileHost, sets: ReadonlySet<string>, ground: LandGround | null): () => void {
  if (ground === null || sets.size === 0) return () => {};
  const kept: { instance: { material: LandGround }; material: LandGround }[] = [];
  for (const set of sets) {
    for (const entity of host.environmentRoot.find((node) => node.name === `generated-tile:${set}`)) {
      for (const instance of (entity as typeof host.environmentRoot).render?.meshInstances ?? []) {
        kept.push({ instance, material: instance.material });
        instance.material = ground;
      }
    }
  }
  return () => {
    for (const { instance, material } of kept) instance.material = material;
  };
}

/**
 * A town on land's street furniture as its people's region reads it: the region stands at the land's
 * datum, so each piece's base stands at its record's own height above it. A piece whose record
 * states none is left at the datum.
 */
export function furnitureOnLand<Piece extends { readonly zMm?: number }>(furniture: readonly Piece[]): (Piece & { readonly baseMm?: number })[] {
  return furniture.map((piece) => (piece.zMm === undefined ? piece : { ...piece, baseMm: piece.zMm }));
}

/** Keep the land read for a saved entry's town, in place of any kept before; null keeps none. */
export function rememberTownLand(entryId: string, town: TownLand | null): void {
  held = town === null ? null : { entryId, town };
}

/**
 * Where a saved entry's town on land stands its people: on the ground its tiles walk, and on its
 * land where they walk none, in metres east and south. Undefined for a town on level ground, or
 * another entry, whose people stand at its arrival's height.
 */
export function townGround(entryId: string, walked: WalkedSurface): ((east: number, south: number) => number) | undefined {
  if (held === null || held.entryId !== entryId) return undefined;
  const { land } = held.town;
  return (east, south) => walked.surface.sample(east, south)?.height ?? land.groundM(east, south);
}
