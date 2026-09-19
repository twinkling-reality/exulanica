/**
 * WHICH TILES A WALK'S WORLD IS, AND FETCHING THEM.
 *
 * A walk's world is the tile the page was asked for together with every tile of the same city seed
 * and level of detail whose own square lies within the route length plus the stopping margin of the
 * walk's start, each taken at its current bake. A tile the store names no current row for is simply
 * not in the world, and the ground ends at its neighbour's edge as the END OF THE LOADED WORLD
 * rather than as a hole in a street. A tile whose row is not `baked` is refused by name, because a
 * world that quietly drops a tile the store knows about is a world whose ground ends somewhere
 * nobody chose, and a walk over it would score a boundary as a defect.
 *
 * BOTH ABSENCES ARE NAMED AND THEY ARE DIFFERENT FACTS. A square the list holds no row for and a
 * square whose row is faulted are both ground this world does not have, and telling them apart is
 * the difference between "the city is that size" and "the bake of that tile failed". Neither is
 * inferred from a shorter list: the squares within reach are ENUMERATED and each is accounted for.
 *
 * WHOLE CONTAINERS ARE FETCHED, and that is deliberate rather than settled. Only a neighbour's
 * `nav_envelope` is ever read, and measured on the corridor a neighbour's navigation is 1,969,322
 * bytes against 11,630,504 for its container, so a route that served sections would move a sixth of
 * the bytes. Nothing serves one today, so that is a proposal with its own contract and its own tests
 * and not a thing this module pretends to have. The route serves whole containers and supports no
 * ranges (`tile-route.ts`), and a whole neighbour is smaller than the tile a walk already loads.
 */
import type { TextureSetDigest } from '@exulanica/atlas-core';
import {
  BAKED_TILE_SERVED_STATE,
  TileRouteRefusal,
  fetchBakedTile,
  type BakedTileSummary,
  type HeldTile,
  type TileRouteAccess,
} from './tile-route.js';

/** A tile's place in the city, as the list route names it. */
export interface TileCoordinate {
  readonly tileX: number;
  readonly tileY: number;
}

/** A square within reach of the walk that the world does not have, and which kind of absence it is. */
export interface AbsentTile extends TileCoordinate {
  /** `no_row` when the list names no tile there; otherwise the row's own state, such as a bake fault. */
  readonly reason: string;
}

export interface WalkWorldPlan {
  /** The tile the walk stands on, or null when the list names no row for the square it starts in. */
  readonly own: BakedTileSummary | null;
  /** Every other tile within reach whose row is served, nearest first, ties by row then column. */
  readonly neighbours: readonly BakedTileSummary[];
  /** Squares within reach this world has no ground for, each saying which kind of absence it is. */
  readonly absent: readonly AbsentTile[];
}

/** How far from a point the nearest part of a tile's square is, in millimetres. */
function reachToSquare(x: number, y: number, tile: TileCoordinate, sizeMm: number): number {
  const west = tile.tileX * sizeMm;
  const south = tile.tileY * sizeMm;
  const dx = Math.max(west - x, 0, x - (west + sizeMm));
  const dy = Math.max(south - y, 0, y - (south + sizeMm));
  return Math.hypot(dx, dy);
}

/**
 * The tiles a walk's world is made of, from the list the route served.
 *
 * `reachMm` is the route length plus its stopping margin, which is the distance the walk's own rule
 * asks for and NOT a radius chosen here. `tileSizeMm` comes from the tile being walked, whose header
 * states it, so nothing in this module restates a number the container already carries.
 */
export function walkWorldTiles(
  tiles: readonly BakedTileSummary[],
  walk: {
    readonly startMm: readonly [number, number];
    readonly reachMm: number;
    readonly lod: number;
    readonly tileSizeMm: number;
  },
): WalkWorldPlan {
  const { startMm: [x, y], reachMm, lod, tileSizeMm } = walk;
  if (tileSizeMm <= 0) throw new TileRouteRefusal(`A tile is ${tileSizeMm} mm across, so no world can be laid out.`, 'bad_tile_size');
  if (reachMm < 0) throw new TileRouteRefusal(`A walk reaching ${reachMm} mm reaches nowhere.`, 'bad_reach');
  const atLod = tiles.filter((tile) => tile.lod === lod);
  const standing: TileCoordinate = { tileX: Math.floor(x / tileSizeMm), tileY: Math.floor(y / tileSizeMm) };
  const within: TileCoordinate[] = [];
  for (let tileY = Math.floor((y - reachMm) / tileSizeMm); tileY <= Math.floor((y + reachMm) / tileSizeMm); tileY += 1) {
    for (let tileX = Math.floor((x - reachMm) / tileSizeMm); tileX <= Math.floor((x + reachMm) / tileSizeMm); tileX += 1) {
      if (reachToSquare(x, y, { tileX, tileY }, tileSizeMm) <= reachMm) within.push({ tileX, tileY });
    }
  }
  const rowOf = (at: TileCoordinate): BakedTileSummary | undefined =>
    atLod.find((tile) => tile.tileX === at.tileX && tile.tileY === at.tileY);
  const own = rowOf(standing);
  const neighbours: BakedTileSummary[] = [];
  const absent: AbsentTile[] = [];
  for (const at of within) {
    const row = rowOf(at);
    if (row === undefined) {
      absent.push({ ...at, reason: 'no_row' });
      continue;
    }
    if (row.state !== BAKED_TILE_SERVED_STATE) {
      absent.push({ ...at, reason: row.state });
      continue;
    }
    if (at.tileX === standing.tileX && at.tileY === standing.tileY) continue;
    neighbours.push(row);
  }
  neighbours.sort((a, b) => {
    const near = reachToSquare(x, y, a, tileSizeMm) - reachToSquare(x, y, b, tileSizeMm);
    if (near !== 0) return near;
    return a.tileY - b.tileY || a.tileX - b.tileX;
  });
  return {
    own: own !== undefined && own.state === BAKED_TILE_SERVED_STATE ? own : null,
    neighbours: Object.freeze(neighbours),
    absent: Object.freeze(absent),
  };
}

/** How a neighbour is named wherever a refusal or a record has to say which tile it was. */
export function tileName(tile: TileCoordinate): string {
  return `tile (${tile.tileX},${tile.tileY})`;
}

export interface FetchedWalkWorld {
  /** Ready to hand to `loadGeneratedTile` as its `neighbours`, in the order they were asked for. */
  readonly neighbours: readonly { readonly name: string; readonly bytes: Uint8Array }[];
  /** Bytes that crossed the network for the neighbours alone, so zero when every one was held. */
  readonly transferredBytes: number;
  /** Squares within reach this world has no ground for, carried through from the plan. */
  readonly absent: readonly AbsentTile[];
}

/**
 * Fetch every neighbour in a plan, verified against the digest its own row claims.
 *
 * A neighbour already held at the digest the row names costs no request at all, which is what
 * `fetchBakedTile` is for. A refusal is not caught here: a tile the store says it has and cannot
 * serve stops the walk rather than shrinking the world behind the walker's back.
 */
export async function fetchWalkWorld(
  access: TileRouteAccess,
  plan: WalkWorldPlan,
  options: { readonly digest: TextureSetDigest; readonly held?: ReadonlyMap<string, HeldTile> },
): Promise<FetchedWalkWorld> {
  const neighbours: { readonly name: string; readonly bytes: Uint8Array }[] = [];
  let transferredBytes = 0;
  for (const row of plan.neighbours) {
    // `held` is left OUT rather than passed as undefined: this package sets
    // exactOptionalPropertyTypes, so an absent tile and a tile held at no digest are different
    // arguments, and only one of them means "ask the route".
    const already = options.held?.get(row.containerSha256);
    const fetched = await fetchBakedTile(access, already === undefined
      ? { bakedTileId: row.bakedTileId, expect: row, digest: options.digest }
      : { bakedTileId: row.bakedTileId, expect: row, held: already, digest: options.digest });
    transferredBytes += fetched.transferredBytes;
    neighbours.push({ name: tileName(row), bytes: fetched.bytes });
  }
  return { neighbours: Object.freeze(neighbours), transferredBytes, absent: plan.absent };
}
