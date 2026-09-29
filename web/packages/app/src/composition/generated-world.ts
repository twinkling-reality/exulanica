/**
 * A saved world generated from a recipe, drawn from its own baked tiles.
 *
 * The server declares what to draw on the world's saved entry (`generatedGround`): each tile the
 * world covers with its stored bake, the one region its people live in and where a person
 * arrives. This module follows that declaration and nothing else. Each tile's container is read
 * through the world's own version (`GET /world/versions/{version}/tiles/{baked_tile_id}/bytes`),
 * which serves a tile only to the world whose snapshot names it, and is held to the digest the
 * route states before anything draws it; the texture sets are the committed library
 * (`../texture-library.ts`). A tile still baking is not drawn and nothing is drawn in its place:
 * the page says the world is being built and looks again.
 *
 * A generated world's region is the city's own frame: east is the city's x, south its negative y,
 * the region origin the city's origin. The tile runtime draws every tile at its absolute city
 * position under the environment root, so the world's people hang from a root at that origin
 * (`hostGeneratedSociety` in `@exulanica/atlas-react/playcanvas`), and a person opens at the
 * served arrival point, facing the way the entry says a person arriving faces.
 */

import type { LoadedGeneratedTile } from '@exulanica/atlas-react/generated-tile';
import type { Credentials } from '../config.js';
import { fill, say } from '../ui/copy.js';
import { el } from '../ui/dom.js';
import type { GeneratedGround, SavedWorldEntry } from '../world-entry-api.js';
import type { AppEnvironment } from './session-state.js';
import { GENERATED_WORLD_READY_EVENT } from './generated-world-ready.js';
import { committedTextureLibrary } from '../texture-library.js';

/** The media type a baked tile's container is served as. */
const CONTAINER_MEDIA_TYPE = 'application/vnd.exulanica.owd';
/**
 * How often a page waiting for a world's tiles asks again, in milliseconds. One bake of the small
 * town's tile took 13.3 s on the development machine, and every tile is baked twice, so asking
 * every five seconds shows the world within five seconds of its last bake while asking a server
 * that is still baking a dozen times a minute at most.
 */
const WAITING_POLL_MS = 5_000;
/** Marks the notice a page waiting for its world shows, so a later mount replaces it. */
export const GENERATED_WORLD_WAITING_ATTRIBUTE = 'data-generated-world-waiting';


/** What the page draws of a saved generated world, once every tile it names is baked. */
export interface GeneratedWorld {
  readonly tile: LoadedGeneratedTile;
  readonly ground: GeneratedGround;
}

/** Why a saved generated world is not drawn yet: tiles still baking, or a bake that failed. */
export interface GeneratedWorldWaiting {
  readonly waiting: 'baking' | 'failed';
  readonly ground: GeneratedGround;
}

function hex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** One baked tile's bytes through the world's version, held to the digest the route names. */
async function worldTileBytes(
  access: Credentials,
  entry: SavedWorldEntry,
  bakedTileId: string,
): Promise<Uint8Array> {
  const query = new URLSearchParams({ world_id: entry.worldId });
  const url = `${access.baseUrl}/world/versions/${encodeURIComponent(entry.authoredVersionId)}`
    + `/tiles/${encodeURIComponent(bakedTileId)}/bytes?${query.toString()}`;
  const response = await fetch(url, {
    headers: { Authorization: `Bearer ${access.token}`, Accept: CONTAINER_MEDIA_TYPE },
    credentials: 'same-origin',
  });
  if (!response.ok) {
    throw new Error(`Tile ${bakedTileId} of this world could not be read: HTTP ${response.status}.`);
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  const stated = response.headers.get('ETag')?.replaceAll('"', '') ?? null;
  const actual = hex(await crypto.subtle.digest('SHA-256', bytes));
  if (stated === null || stated !== actual) {
    throw new Error(`Tile ${bakedTileId} arrived as bytes that are not the ones the route named.`);
  }
  return bytes;
}

/**
 * The world an entry declares, loaded and ready to mount, or why it is not drawn yet. Null for an
 * entry that declares no generated ground.
 */
export async function loadGeneratedWorld(
  access: Credentials,
  entry: SavedWorldEntry,
): Promise<GeneratedWorld | GeneratedWorldWaiting | null> {
  const ground = entry.generatedGround ?? null;
  if (ground === null) return null;
  if (ground.tiles.some((tile) => tile.state === 'failed')) return { waiting: 'failed', ground };
  if (ground.tiles.some((tile) => tile.state !== 'baked')) return { waiting: 'baking', ground };
  const [route, { parseTextureSetManifest }, library] = await Promise.all([
    import('@exulanica/atlas-react/generated-tile'),
    import('@exulanica/atlas-core'),
    committedTextureLibrary(),
  ]);
  const containers = await Promise.all(ground.tiles.map(async (tile) => ({
    name: tile.bakedTileId!,
    bytes: await worldTileBytes(access, entry, tile.bakedTileId!),
  })));
  const [first, ...rest] = containers;
  const neighbours: readonly { readonly name: string; readonly bytes: Uint8Array }[] = rest;
  const loaded = await route.loadGeneratedTile({
    name: first!.name,
    bytes: first!.bytes,
    manifest: parseTextureSetManifest(library.textureManifest),
    fetchSet: (set) => library.textureSet(set.contentSha256),
    ...(neighbours.length === 0 ? {} : { neighbours }),
  });
  // Where a person arrives is the world's own spawn, served in the region's frame: east, height,
  // south. The renderer's frame is east, up and south in metres, so it is read across unchanged.
  // Its yaw 0 looks north with forward (-sin yaw, 0, -cos yaw), so a facing of (east, south) is
  // yaw = atan2(-east, -south).
  const [east, height, south] = ground.arrivalMm;
  const [facingEast, facingSouth] = ground.arrivalFacingMm;
  const start = {
    x: east / 1000,
    y: height / 1000 + loaded.navigationWorld.eyeHeight,
    z: south / 1000,
    yaw: Math.atan2(-facingEast, -facingSouth),
    pitch: 0,
  };
  return { tile: { ...loaded, start }, ground };
}

/** Whether a load finished with a world to mount, rather than one still being built. */
export function isGeneratedWorld(
  value: GeneratedWorld | GeneratedWorldWaiting | null,
): value is GeneratedWorld {
  return value !== null && 'tile' in value;
}

/** Every tile of the entry's world is baked, as the server now says, read from its entry. */
async function allBaked(access: Credentials, entry: SavedWorldEntry): Promise<boolean> {
  const response = await fetch(`${access.baseUrl}/world-entries/${encodeURIComponent(entry.entryId)}`, {
    headers: { Authorization: `Bearer ${access.token}`, Accept: 'application/json' },
    credentials: 'same-origin',
  });
  if (!response.ok) return false;
  const body = await response.json() as { generated_ground?: { tiles?: readonly { state?: string }[] } };
  const tiles = body.generated_ground?.tiles ?? [];
  return tiles.length > 0 && tiles.every((tile) => tile.state === 'baked');
}

/**
 * The tile to mount for a saved generated world, or null while the world is not drawn yet, in
 * which case the page says why and, while tiles are baking, opens the world again once they are.
 */
export async function openGeneratedWorld(
  env: AppEnvironment,
  access: Credentials,
  entry: SavedWorldEntry,
): Promise<LoadedGeneratedTile | null> {
  env.shell.querySelector(`[${GENERATED_WORLD_WAITING_ATTRIBUTE}]`)?.remove();
  const loaded = await loadGeneratedWorld(access, entry);
  if (loaded === null) return null;
  if (isGeneratedWorld(loaded)) return loaded.tile;
  const words = loaded.waiting === 'baking'
    ? fill('world.generated.baking', { recipe: loaded.ground.recipeLabel })
    : say('world.generated.failed');
  env.shell.append(el('p', {
    class: 'reconstruction-loading', role: 'status', text: words,
    [GENERATED_WORLD_WAITING_ATTRIBUTE]: loaded.waiting,
  }));
  if (loaded.waiting === 'baking') {
    const timer = window.setInterval(() => {
      void allBaked(access, entry).then((baked) => {
        if (!baked) return;
        window.clearInterval(timer);
        env.shell.dispatchEvent(new CustomEvent(GENERATED_WORLD_READY_EVENT, { bubbles: true }));
      });
    }, WAITING_POLL_MS);
  }
  return null;
}
