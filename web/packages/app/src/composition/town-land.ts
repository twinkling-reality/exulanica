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
 * in all. Land that cannot be read is not stood in for: the world does not open, as it does not
 * with a tile that is not the one its entry names.
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

import type { GeneratedTileAttachment, GeneratedTileHost, LoadedGeneratedTile } from '@exulanica/atlas-react/generated-tile';
import type { DrawnSiteLand, SiteLand } from '@exulanica/atlas-react/generated-site';
import { accessHeaders, type Credentials } from '../config.js';
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

export interface TownLand {
  readonly land: SiteLand;
  /**
   * Draw the land under the host's environment root, leaving out the chunks `covered` names: with
   * the material its near land wears, or null where it drew none.
   */
  draw(host: GeneratedTileHost, covered: (chunkX: number, chunkY: number) => boolean): { readonly ground?: LandGround | null; dispose(): void };
}

/** A navigation world's walked surface, as far as a person's height is read from it. */
interface WalkedSurface {
  readonly surface: { sample(east: number, south: number): { readonly height: number } | null };
}

let held: { readonly entryId: string; readonly town: TownLand } | null = null;

/**
 * The land a town on land's entry names, read through its world's version: the section, held to
 * its entity tag, its world and the entry's digest, and every chunk and the backdrop it names,
 * each held to the digest the section gives it.
 */
export async function loadTownLand(access: Credentials, entry: SavedWorldEntry, landSha256: string): Promise<TownLand> {
  const [{ attachLandRound, parseSiteLandSection, readLandSection }, { sha256Hex }, { LAND_SURFACES }] = await Promise.all([
    import('@exulanica/atlas-react/generated-site'),
    import('@exulanica/atlas-react/playcanvas'),
    import('../land-surfaces.js'),
  ]);
  const query = new URLSearchParams({ world_id: entry.worldId });
  const version = `${access.baseUrl}/world/versions/${encodeURIComponent(entry.authoredVersionId)}`;
  let bytes = 0;
  const until = Date.now() + LAND_WAIT_MS;
  /** A land document, held to `sha256`, or for the section, to the digest of its own bytes. */
  const read = async (path: string, sha256: string | null): Promise<unknown> => {
    let response: Response;
    for (;;) {
      response = await fetch(`${version}/${path}?${query.toString()}`, {
        headers: { ...accessHeaders(access), Accept: 'application/json' },
        credentials: 'same-origin',
      });
      // Still being made: asked again after the seconds stated, a second at least, until the wait is spent.
      const stated = response.status === 503 ? Number(response.headers.get('Retry-After') ?? Number.NaN) : Number.NaN;
      const ms = Math.max(1, stated) * 1000;
      if (!Number.isFinite(stated) || Date.now() + ms > until) break;
      await new Promise((done) => { setTimeout(done, ms); });
    }
    if (!response.ok) throw new Error(`This town's land could not be read: HTTP ${response.status}.`);
    const body = new Uint8Array(await response.arrayBuffer());
    const tag = response.headers.get('ETag')?.replaceAll('"', '');
    if (tag === undefined || tag !== (sha256 ?? sha256Hex(body))) throw new Error("This town's land arrived as a document its section does not name.");
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
    draw: (host: GeneratedTileHost, covered: (chunkX: number, chunkY: number) => boolean) => {
      const round = attachLandRound(host, land, covered, LAND_SURFACES);
      return { ground: round.drawn.ground[0]?.material ?? null, dispose: () => round.dispose() };
    },
  });
}

/** A look with no flat plane beyond the tiles, for a town whose land is its edge. */
export function withoutEdge<Look extends object>(look: Look): Look {
  return 'edge' in look && look.edge !== null ? { ...look, edge: null } : look;
}

/**
 * The town's tiles with its land drawn round them whenever they are attached: every chunk no tile
 * covers, the backdrop and the water, taken away again with them. The tiles' own ground, where no
 * street, footway or lot stands, wears what the land round them wears, so the town's unbuilt land
 * meets its land in one ground rather than in a tile of bare soil (the texture set a town's terrain
 * is dressed in, which its tree pits share and so wear too); the tiles' own material comes back
 * before either is taken away.
 */
export function withTownLand(tile: LoadedGeneratedTile, town: TownLand, tiles: readonly Pick<GeneratedTile, 'tileX' | 'tileY'>[]): LoadedGeneratedTile {
  const under = new Set(tiles.map((one) => `${one.tileX},${one.tileY}`));
  return {
    ...tile,
    attach(host: GeneratedTileHost): GeneratedTileAttachment {
      const attachment = tile.attach(host);
      const drawn = town.draw(host, (chunkX, chunkY) => under.has(`${chunkX},${chunkY}`));
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
