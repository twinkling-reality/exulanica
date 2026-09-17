/**
 * Reading baked tiles from the product route, `GET /tiles` and `GET /tiles/{id}/bytes`.
 *
 * This is the path a person's walk takes, as against the development preview route, which loads
 * goldens committed to this repository with no credential and stays exactly as it is. A generated
 * corridor tile is never committed, so a walk over one can only come from here.
 *
 * Three rules shape everything below.
 *
 * **The caller checks the bytes.** The route names each container by its own digest, in the ETag and
 * again in the list, and this module hashes what arrived and refuses to hand on anything whose digest
 * is not the one claimed. A tile that fails that check is not drawn, it is refused with both digests
 * named, because bytes that are not what the row says they are could be anything.
 *
 * **List first, then fetch only what is missing.** The list route is metadata and spends no tile
 * quota, so a reload asks the list for a whole city in one request, compares each tile's
 * `container_sha256` against what is already held, and fetches a container only for a digest it does
 * not have. The route's `Cache-Control: private, no-cache` makes a browser revalidate every use, and
 * the route does not answer If-None-Match today, so a revalidation would cost the whole container;
 * comparing digests from the list costs one small request for the whole city instead. The request
 * still carries If-None-Match, so the day the route learns to answer 304 this module takes it for
 * free and nothing here has to change.
 *
 * **A refusal never guesses why.** The route answers 404 `unknown_reference` both for a key it does
 * not hold and for a credential without `tiles.materialise`, on purpose, so that neither answer tells
 * an outsider which it was. This module keeps them alike: it reports the route's own code and detail
 * and never dresses a 404 up as "not permitted" or "no such tile".
 */

import type { TextureSetDigest } from '@exulanica/atlas-core';

/** What the route serves a container as. Anything else is refused. */
export const BAKED_TILE_MEDIA_TYPE = 'application/vnd.exulanica.owd';

/** The only state whose bytes the route serves; the rest are skipped without a request. */
export const BAKED_TILE_SERVED_STATE = 'baked';

/** One tile as the list route documents it. Field names are the route's, in this codebase's case. */
export interface BakedTileSummary {
  readonly bakedTileId: string;
  readonly tileX: number;
  readonly tileY: number;
  readonly lod: number;
  readonly tileInputsDigest: string;
  readonly containerSha256: string;
  readonly containerBytes: number;
  readonly renderBatchSha256: string;
  readonly navEnvelopeSha256: string;
  /** `baked`, or a fault the bake recorded, such as `nondeterminism_detected`. */
  readonly state: string;
}

/**
 * A refusal from the route or from this module's own checks. `code` is the route's problem code
 * where the route answered one, and otherwise names the check that refused, so a caller can tell a
 * mismatched digest from a quota without reading prose.
 */
export class TileRouteRefusal extends Error {
  override readonly name = 'TileRouteRefusal';

  constructor(
    message: string,
    readonly code: string,
    readonly status: number | null = null,
  ) {
    super(message);
  }
}

/** Where the route is and what credential reaches it. The token holds `tiles.materialise`. */
export interface TileRouteAccess {
  /** The API's origin, with or without a trailing slash. */
  readonly baseUrl: string;
  /** The session's bearer token. Never logged, never retained by this module. */
  readonly token: string;
  /** The page's `fetch` by default; a test hands its own. */
  readonly fetch?: typeof globalThis.fetch;
}

/** A container this caller already holds, from an earlier load or a store of its own. */
export interface HeldTile {
  readonly containerSha256: string;
  readonly bytes: Uint8Array;
}

/** Why a fetch did or did not cross the network, which is what a budget record wants to know. */
export type TileBytesOrigin = 'held' | 'not-modified' | 'fetched';

export interface FetchedTile {
  readonly bakedTileId: string;
  readonly containerSha256: string;
  readonly bytes: Uint8Array;
  readonly origin: TileBytesOrigin;
  /** Bytes that crossed the network, so zero for a held or not-modified tile. */
  readonly transferredBytes: number;
  /** The route's `X-Exulanica-Tile-Inputs-Digest`, where it sent one. */
  readonly tileInputsDigest: string | null;
}

function endpoint(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/+$/, '')}${path}`;
}

function caller(access: TileRouteAccess): typeof globalThis.fetch {
  const found = access.fetch ?? globalThis.fetch;
  if (typeof found !== 'function') {
    throw new TileRouteRefusal('This page has no fetch, so no baked tile can be read.', 'no_fetch');
  }
  return found;
}

/**
 * The route's problem body, where it sent one. A refusal that is not JSON, or is JSON of another
 * shape, still refuses: the status is what matters and the body is reported as it arrived.
 */
async function refusalOf(response: Response, what: string): Promise<TileRouteRefusal> {
  let code = `http_${response.status}`;
  let detail = response.statusText;
  try {
    const body: unknown = await response.json();
    if (body !== null && typeof body === 'object') {
      const problem = body as { readonly code?: unknown; readonly detail?: unknown };
      if (typeof problem.code === 'string') code = problem.code;
      if (typeof problem.detail === 'string') detail = problem.detail;
    }
  } catch {
    // A refusal with no readable body is still a refusal; the status carries it.
  }
  return new TileRouteRefusal(`${what} refused (${response.status} ${code}): ${detail}`, code, response.status);
}

const HEX_64 = /^[0-9a-f]{64}$/;

function summaryOf(document: unknown, at: number): BakedTileSummary {
  if (document === null || typeof document !== 'object') {
    throw new TileRouteRefusal(`The tile list's entry ${at} is not an object.`, 'malformed_list');
  }
  const row = document as Record<string, unknown>;
  const text = (key: string): string => {
    const value = row[key];
    if (typeof value !== 'string') throw new TileRouteRefusal(`The tile list's entry ${at} has no ${key}.`, 'malformed_list');
    return value;
  };
  const whole = (key: string): number => {
    const value = row[key];
    if (typeof value !== 'number' || !Number.isInteger(value)) {
      throw new TileRouteRefusal(`The tile list's entry ${at} has no ${key}.`, 'malformed_list');
    }
    return value;
  };
  const digest = (key: string): string => {
    const value = text(key);
    if (!HEX_64.test(value)) throw new TileRouteRefusal(`The tile list's entry ${at} has a ${key} that is not a digest.`, 'malformed_list');
    return value;
  };
  return Object.freeze({
    bakedTileId: text('baked_tile_id'),
    tileX: whole('tile_x'),
    tileY: whole('tile_y'),
    lod: whole('lod'),
    tileInputsDigest: digest('tile_inputs_digest'),
    containerSha256: digest('container_sha256'),
    containerBytes: whole('container_bytes'),
    renderBatchSha256: digest('render_batch_sha256'),
    navEnvelopeSha256: digest('nav_envelope_sha256'),
    state: text('state'),
  });
}

/**
 * Every tile stored for one city, newest bake per key, as the route lists them. Metadata only: no
 * container crosses the network and no tile quota is spent, so a walk may call this on every reload.
 */
export async function listBakedTiles(
  access: TileRouteAccess,
  query: { readonly citySeed: string; readonly lod?: number },
): Promise<readonly BakedTileSummary[]> {
  if (!HEX_64.test(query.citySeed)) {
    throw new TileRouteRefusal(`A city seed is 64 hex characters; this one is "${query.citySeed}".`, 'bad_city_seed');
  }
  const search = new URLSearchParams({ city_seed: query.citySeed });
  if (query.lod !== undefined) search.set('lod', String(query.lod));
  const response = await caller(access)(endpoint(access.baseUrl, `/tiles?${search.toString()}`), {
    headers: { Authorization: `Bearer ${access.token}`, Accept: 'application/json' },
  });
  if (!response.ok) throw await refusalOf(response, `The tile list for city ${query.citySeed}`);
  const body: unknown = await response.json();
  if (body === null || typeof body !== 'object') {
    throw new TileRouteRefusal('The tile list is not an object.', 'malformed_list');
  }
  const tiles = (body as { readonly tiles?: unknown }).tiles;
  if (!Array.isArray(tiles)) throw new TileRouteRefusal('The tile list carries no tiles.', 'malformed_list');
  return Object.freeze(tiles.map((document, at) => summaryOf(document, at)));
}

/** The tile at one coordinate and level of detail, or null where the city has none there. */
export function tileAt(
  tiles: readonly BakedTileSummary[],
  at: { readonly tileX: number; readonly tileY: number; readonly lod: number },
): BakedTileSummary | null {
  return tiles.find((tile) => tile.tileX === at.tileX && tile.tileY === at.tileY && tile.lod === at.lod) ?? null;
}

function etagDigest(response: Response): string | null {
  const etag = response.headers.get('ETag');
  if (etag === null) return null;
  const bare = etag.replace(/^W\//, '').replace(/^"/, '').replace(/"$/, '');
  return HEX_64.test(bare) ? bare : null;
}

/**
 * One container, verified against the digest its own row claims, ready to hand to
 * `loadGeneratedTile`. The bytes are never returned unchecked and never partially: the route serves
 * whole containers and supports no ranges.
 *
 * `expect` is the tile's row from the list. Given it, a `held` container whose digest already matches
 * is returned without any request at all, which is what makes a reload cost nothing. Given a tile
 * whose state is not `baked`, this refuses before the request, since the route would answer 409 and
 * the list already said so.
 */
export async function fetchBakedTile(
  access: TileRouteAccess,
  request: {
    readonly bakedTileId: string;
    readonly expect?: BakedTileSummary;
    readonly held?: HeldTile;
    readonly digest: TextureSetDigest;
  },
): Promise<FetchedTile> {
  const { bakedTileId, expect, held, digest } = request;
  if (expect !== undefined && expect.bakedTileId !== bakedTileId) {
    throw new TileRouteRefusal(
      `Tile ${bakedTileId} was asked for with the row of ${expect.bakedTileId}.`,
      'mismatched_expectation',
    );
  }
  if (expect !== undefined && expect.state !== BAKED_TILE_SERVED_STATE) {
    throw new TileRouteRefusal(
      `Tile ${bakedTileId} is ${expect.state}, and only a ${BAKED_TILE_SERVED_STATE} tile is served.`,
      expect.state,
    );
  }
  const wanted = expect?.containerSha256 ?? held?.containerSha256 ?? null;
  if (held !== undefined && expect !== undefined && held.containerSha256 === expect.containerSha256) {
    return Object.freeze({
      bakedTileId,
      containerSha256: held.containerSha256,
      bytes: held.bytes,
      origin: 'held' as const,
      transferredBytes: 0,
      tileInputsDigest: expect.tileInputsDigest,
    });
  }

  const headers: Record<string, string> = {
    Authorization: `Bearer ${access.token}`,
    Accept: BAKED_TILE_MEDIA_TYPE,
  };
  // Free the day the route answers it, harmless until then.
  if (held !== undefined) headers['If-None-Match'] = `"${held.containerSha256}"`;
  const response = await caller(access)(endpoint(access.baseUrl, `/tiles/${bakedTileId}/bytes`), { headers });

  if (response.status === 304) {
    if (held === undefined) {
      throw new TileRouteRefusal(`Tile ${bakedTileId} answered not modified, and nothing was held to use.`, 'unasked_not_modified', 304);
    }
    return Object.freeze({
      bakedTileId,
      containerSha256: held.containerSha256,
      bytes: held.bytes,
      origin: 'not-modified' as const,
      transferredBytes: 0,
      tileInputsDigest: expect?.tileInputsDigest ?? null,
    });
  }
  if (!response.ok) throw await refusalOf(response, `Tile ${bakedTileId}`);

  const served = response.headers.get('Content-Type');
  if (served !== null && !served.startsWith(BAKED_TILE_MEDIA_TYPE)) {
    throw new TileRouteRefusal(
      `Tile ${bakedTileId} arrived as ${served}, and a container is ${BAKED_TILE_MEDIA_TYPE}.`,
      'wrong_media_type',
      response.status,
    );
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  const measured = hex(await digest.digest('SHA-256', bytes));
  const claimed = etagDigest(response);
  if (claimed !== null && claimed !== measured) {
    throw new TileRouteRefusal(
      `Tile ${bakedTileId} hashes to ${measured}, and the route named it ${claimed}.`,
      'digest_mismatch',
      response.status,
    );
  }
  if (wanted !== null && wanted !== measured) {
    throw new TileRouteRefusal(
      `Tile ${bakedTileId} hashes to ${measured}, and its row records ${wanted}.`,
      'digest_mismatch',
      response.status,
    );
  }
  if (claimed === null && wanted === null) {
    throw new TileRouteRefusal(
      `Tile ${bakedTileId} arrived with no digest to check it against, so it is not drawn.`,
      'unnamed_container',
      response.status,
    );
  }
  if (expect !== undefined && expect.containerBytes !== bytes.length) {
    throw new TileRouteRefusal(
      `Tile ${bakedTileId} is ${bytes.length} bytes, and its row records ${expect.containerBytes}.`,
      'wrong_length',
      response.status,
    );
  }
  return Object.freeze({
    bakedTileId,
    containerSha256: measured,
    bytes,
    origin: 'fetched' as const,
    transferredBytes: bytes.length,
    tileInputsDigest: response.headers.get('X-Exulanica-Tile-Inputs-Digest'),
  });
}

function hex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}
