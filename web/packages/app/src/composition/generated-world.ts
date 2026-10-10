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
 * served arrival point, facing the way the entry says a person arriving faces. The served point is a
 * standing spot of the world's records, and the drawn ground (the tiles' `nav_envelope`) carves a
 * capsule's clearance round every obstruction on a footway, so a spot beside a tree can lie in the
 * tree pit's carve: a person then opens on the nearest drawn ground (`groundNear`), rather than on
 * none, which the walk would recover to the first tile's middle.
 *
 * Every generated world the page opens also draws its own traffic while its tiles are attached
 * (`withTraffic` in `tile-traffic.ts`), read through the world's version
 * (`GET /world/versions/{version}/traffic`). A world whose roads hold no traffic is refused by name,
 * and the page then says why in words chosen by the refusal's code (`trafficRefusalWords`), never
 * a blank; the shell's `data-tile-traffic` attribute states what was served and drawn.
 *
 * A world is drawn in the look the page chooses (`worldLookChoice` in `../world-look.ts`): the
 * address's, else the pack its appearance names, else the default; the tile look, or a style pack
 * the host serves, whose light the tiles are loaded in and whose surfaces, windows and vehicles dress
 * them once attached. A pack the page cannot read is not stood in for: the world opens in the tile
 * look, and the shell's `data-world-look` attribute states the pack asked for, what chose it, and
 * why it was not drawn. While the world is open it can be redrawn in another pack at once
 * (`./world-look-redraw.ts`): its tiles are loaded again from the bytes already held, in the new
 * pack's light, and swapped on the same host, so the person stays where they stand.
 */

import type { GeneratedTileAttachment, GeneratedTileHost, LoadedGeneratedTile } from '@exulanica/atlas-react/generated-tile';
import type { StreetFurniture } from '@exulanica/atlas-react/playcanvas';
import { rememberTownFurniture } from './town-furniture.js';
import { toApiError } from '@exulanica/graph-client';
import type { VehicleBodies } from '@exulanica/atlas-react/traffic';
import { accessHeaders, type Credentials } from '../config.js';
import { fill, say } from '../ui/copy.js';
import { el } from '../ui/dom.js';
import type { GeneratedGround, SavedWorldEntry } from '../world-entry-api.js';
import type { WorldStylePackBinding } from '../world-style-api.js';
import type { AppEnvironment } from './session-state.js';
import {
  GENERATED_WORLD_READY_EVENT,
  GENERATED_WORLD_WAITING_ATTRIBUTE,
  type GeneratedWorldReady,
} from './generated-world-ready.js';
import { committedTextureLibrary } from '../texture-library.js';
import { arrivalView, parkedFootprint, seatsOf, type PlanFootprint, type SightBlocker, type TownLife } from './arrival-view.js';
import { TOWN_FIRST_VIEW } from '../town-first-view.js';
import { WORLD_LOOK_ATTRIBUTE, swappableDrawing } from './world-look-redraw.js';

/** The media type a baked tile's container is served as. */
const CONTAINER_MEDIA_TYPE = 'application/vnd.exulanica.owd';
/**
 * How often a page waiting for a world's tiles asks again, in milliseconds. One bake of the small
 * town's tile took 13.3 s on the development machine, and every tile is baked twice, so asking
 * every five seconds shows the world within five seconds of its last bake while asking a server
 * that is still baking a dozen times a minute at most.
 */
const WAITING_POLL_MS = 5_000;
/**
 * The spacing of the rings the page searches for ground round a served arrival: the city grammar's
 * 50 mm dimension module, the finest step its surfaces are laid on.
 */
const GROUND_SEARCH_STEP_MM = 50;
/**
 * How far from the served arrival the page looks for ground: five metres, which keeps a person on
 * the footway the arrival names and in sight of it. Measured on a three-tile town whose arrival lay
 * in a tree pit's carve, ground was 570 mm east of the served point, 900 mm north and 1,600 mm south.
 */
const GROUND_SEARCH_REACH_MM = 5_000;
/** Marks the notice a page waiting for its world shows, so a later mount replaces it. */
export { GENERATED_WORLD_WAITING_ATTRIBUTE };
/** Marks the note saying why a world shows no vehicles; it names the refusal's code. */
export const WORLD_TRAFFIC_NOTE_ATTRIBUTE = 'data-world-traffic-note';
/** States the look a generated world is drawn in: the pack asked for, and whether it was drawn. */
export { WORLD_LOOK_ATTRIBUTE };
/** The prefix every refusal to read a generated world's records carries. */
const UNREADABLE_PREFIX = 'generated_world_';
/** What the note names when the page could not load its own traffic code. */
const TRAFFIC_NOT_LOADED = 'traffic_not_loaded';


/**
 * The town's street furniture, from every tile's own records, each piece once by identity (a tile
 * carries halo copies of its neighbours'). Furniture is where a town's people sit, and drawing them
 * there is not what a town's opening depends on: where the records cannot be read here, none is
 * kept and people are drawn as they are with no seat.
 */
function streetFurnitureOfTown(
  route: { readonly streetFurnitureOf?: (bytes: Uint8Array) => readonly StreetFurniture[] },
  containers: readonly { readonly bytes: Uint8Array }[],
): readonly StreetFurniture[] {
  try {
    const kept = new Map<string, StreetFurniture>();
    for (const { bytes } of containers) {
      for (const item of route.streetFurnitureOf?.(bytes) ?? []) if (!kept.has(item.identity)) kept.set(item.identity, item);
    }
    return [...kept.values()];
  } catch {
    return [];
  }
}

/** The record kind a tile states a building under, as its route obstructions name it. */
const MASSING_OBSTACLE = 'city.massing:';

/**
 * What stands in a sight line at a standing person's eye height in a town, as plan rings in the
 * region's frame (millimetres east and south): every building's base, from the obstructions the
 * loaded tiles already state, and each part of the town's street furniture and trees that crosses
 * eye height, from the tiles' own records. Where those cannot be read, none: the first view is
 * then chosen past parked vehicles alone, as before.
 */
function sightBlockersOfTown(
  route: { readonly sightBlockersOf?: (bytes: Uint8Array, heightMm: number) => readonly SightBlocker[] },
  containers: readonly { readonly bytes: Uint8Array }[],
  loaded: LoadedGeneratedTile,
): readonly SightBlocker[] {
  try {
    const eyeMm = loaded.navigationWorld.eyeHeight * 1000;
    const buildings = (loaded.routeObstructions?.obstacles ?? [])
      .filter((obstacle) => obstacle.id.startsWith(MASSING_OBSTACLE))
      .flatMap((obstacle) => obstacle.rings.map((ring) => ring.map((point) => [point.x * 1000, point.z * 1000] as const)));
    const standing = containers.flatMap(({ bytes }) => route.sightBlockersOf?.(bytes, eyeMm) ?? []);
    return [...buildings, ...standing];
  } catch {
    return [];
  }
}

/**
 * Where a town's life is, for its first view: the seats among its street furniture, found by shape,
 * and its doors onto a footway, each once by identity, from the tiles' own records. Where those
 * cannot be read, none, and the first view is chosen by openness alone.
 */
function lifeOfTown(
  route: { readonly doorsOf?: (bytes: Uint8Array) => readonly { readonly identity: string; readonly eastMm: number; readonly southMm: number }[] },
  containers: readonly { readonly bytes: Uint8Array }[],
  furniture: readonly StreetFurniture[],
): TownLife {
  try {
    const doors = new Map<string, readonly [number, number]>();
    for (const { bytes } of containers) {
      for (const door of route.doorsOf?.(bytes) ?? []) if (!doors.has(door.identity)) doors.set(door.identity, [door.eastMm, door.southMm]);
    }
    const rule = TOWN_FIRST_VIEW.life;
    return { seats: rule === undefined ? [] : seatsOf(furniture, rule), doors: [...doors.values()] };
  } catch {
    return { seats: [], doors: [] };
  }
}

/** What the page draws of a saved generated world, once every tile it names is baked. */
export interface GeneratedWorld {
  readonly tile: LoadedGeneratedTile;
  readonly ground: GeneratedGround;
  /**
   * The look it is drawn in: the pack asked for (null for the tile look), what chose it, whether it
   * was drawn and why not.
   */
  readonly look: {
    readonly pack: string | null;
    readonly source: 'address' | 'world' | 'default' | 'redraw';
    readonly drawn: boolean;
    readonly reason: string | null;
    /** The world's own setting, stated only for a world that has one: whether it was drawn, and why not. */
    readonly setting?: { readonly drawn: boolean; readonly reason: string | null };
  };
  /** The bodies its traffic takes from its pack while its tiles are attached, if any. */
  readonly bodies: () => VehicleBodies | null;
  /**
   * The same tiles, as loaded, in another look: nothing is fetched, verified or decoded again;
   * refused, and nothing changed, when the pack cannot be read.
   */
  readonly relook: (choice: import('../world-look.js').WorldLookChoice) => Promise<{
    readonly tile: LoadedGeneratedTile;
    readonly bodies: () => VehicleBodies | null;
    readonly look: GeneratedWorld['look'];
  }>;
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
    headers: { ...accessHeaders(access), Accept: CONTAINER_MEDIA_TYPE },
    credentials: 'same-origin',
  });
  if (!response.ok) {
    // The route's refusal is kept as the cause, by its code, so the page can say why in words.
    throw new Error(`Tile ${bakedTileId} of this world could not be read: HTTP ${response.status}.`, {
      cause: await toApiError(response),
    });
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
 * The drawn ground nearest a served point, in the region's frame (east and south millimetres), with
 * its height in metres: the point itself when ground is drawn there, or else the first point with
 * ground on rings `GROUND_SEARCH_STEP_MM` apart, each walked from the way a person arriving faces and
 * alternately either side of it; null when none lies within `GROUND_SEARCH_REACH_MM`.
 */
export function groundNear(
  surface: { sample(x: number, z: number): { readonly height: number } | null },
  eastMm: number,
  southMm: number,
  facing: readonly [east: number, south: number],
): { readonly eastMm: number; readonly southMm: number; readonly heightM: number } | null {
  const at = (east: number, south: number) => surface.sample(east / 1000, south / 1000);
  const here = at(eastMm, southMm);
  if (here !== null) return { eastMm, southMm, heightM: here.height };
  const ahead = Math.atan2(facing[1], facing[0]);
  for (let radius = GROUND_SEARCH_STEP_MM; radius <= GROUND_SEARCH_REACH_MM; radius += GROUND_SEARCH_STEP_MM) {
    const count = Math.ceil((2 * Math.PI * radius) / GROUND_SEARCH_STEP_MM);
    for (let turn = 0; turn < count; turn += 1) {
      const side = turn % 2 === 0 ? 1 : -1;
      const angle = ahead + side * Math.ceil(turn / 2) * ((2 * Math.PI) / count);
      const east = eastMm + radius * Math.cos(angle);
      const south = southMm + radius * Math.sin(angle);
      const found = at(east, south);
      if (found !== null) return { eastMm: east, southMm: south, heightM: found.height };
    }
  }
  return null;
}

/** How long a dressed town's first view waits for the parked vehicles before it stands without them. */
const PARKED_VEHICLES_MS = 4000;

/**
 * The placed things' plan points, as the world's version states them, or null where the version
 * cannot be read: the town is then looked at as one with nothing known placed. Whether anything is
 * placed decides which first view a town opens with, so this read is waited for like the tiles and
 * loses no race: a town opens the same way when it is made and when it is opened again.
 */
async function placedThings(
  access: Credentials, entry: SavedWorldEntry,
): Promise<readonly (readonly [number, number])[] | null> {
  try {
    const [{ Transport }, { parseVersion }] = await Promise.all([
      import('@exulanica/graph-client'), import('../world-objects-api.js'),
    ]);
    const version = parseVersion(await new Transport(access).getJson<unknown>(
      `/world/versions/${encodeURIComponent(entry.authoredVersionId)}`, { world_id: entry.worldId },
    ));
    return (version.things ?? []).filter((thing) => !thing.removed)
      .map((thing) => [thing.transform.xMm, thing.transform.zMm] as const);
  } catch {
    return null;
  }
}

/**
 * The vehicles parked at the traffic's current second, or none where they cannot be read in time.
 * Only a town with things placed looks past them (a scene behind a parked car), and what is parked
 * is the traffic's state at that second, so nothing else of the first view is chosen by this read.
 */
async function parkedNow(access: Credentials, entry: SavedWorldEntry): Promise<readonly PlanFootprint[]> {
  const read = async (): Promise<readonly PlanFootprint[]> => {
    const { WorldTrafficClient } = await import('../traffic-api.js');
    const traffic = await new WorldTrafficClient(access).window(entry.worldId, entry.authoredVersionId, null, 1);
    const parkedMode = traffic.window.modes.indexOf('parked');
    return traffic.window.vehicles
      .filter((vehicle) => vehicle.mode[0] === parkedMode)
      .flatMap((vehicle) => parkedFootprint(vehicle) ?? []);
  };
  return Promise.race([
    read().catch(() => []),
    new Promise<readonly PlanFootprint[]>((resolve) => { setTimeout(() => resolve([]), PARKED_VEHICLES_MS); }),
  ]);
}

/**
 * The world an entry declares, loaded and ready to mount, or why it is not drawn yet. Null for an
 * entry that declares no generated ground.
 */
export async function loadGeneratedWorld(
  access: Credentials,
  entry: SavedWorldEntry,
  search: string = typeof window === 'undefined' ? '' : window.location.search,
  bound: WorldStylePackBinding | null = null,
): Promise<GeneratedWorld | GeneratedWorldWaiting | null> {
  const ground = entry.generatedGround ?? null;
  if (ground === null) return null;
  if (ground.tiles.some((tile) => tile.state === 'failed')) return { waiting: 'failed', ground };
  if (ground.tiles.some((tile) => tile.state !== 'baked')) return { waiting: 'baking', ground };
  // What the first look faces and sees past, read beside the tiles: the version's placed things,
  // waited for, and, only where something is placed, what is parked now, never waited on for long.
  const placing = placedThings(access, entry).then((targets) => targets ?? []);
  const parking = placing.then((targets) => (targets.length === 0 ? [] : parkedNow(access, entry)));
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
  const furniture = streetFurnitureOfTown(route, containers);
  rememberTownFurniture(entry.entryId, furniture);
  const worldLook = await import('../world-look.js');
  type Prepared = import('../world-look.js').PreparedWorldLook;
  type Choice = import('../world-look.js').WorldLookChoice;
  /** The pack a choice draws: its own, or for the default the pack the host's list marks so, by its digest. */
  const resolved = async (choice: Choice): Promise<Choice> => {
    if (choice.source !== 'default') return choice;
    const listed = worldLook.listedDefault(await worldLook.listedStylePacks(access));
    if (listed === undefined) throw new Error('The host lists no default style pack');
    return { ...choice, packId: listed.pack_id, manifestSha256: listed.manifest_sha256 };
  };
  /** The pack a resolved choice names, read and its pieces fetched; null for the tile look. Throws when it cannot be read. */
  const prepare = (choice: Choice): Promise<Prepared | null> => (
    choice.packId === null
      ? Promise.resolve(null)
      : worldLook.prepareWorldLook(
        access, choice.packId, library.textureManifest, containers.map((one) => one.bytes), choice.manifestSha256,
        choice.ownBase ?? null, choice.setting ?? null,
      )
  );
  /** The world's tiles in a prepared pack's light and dressed by it, or in the tile look. */
  const dressedIn = (plain: LoadedGeneratedTile, prepared: Prepared | null): { tile: LoadedGeneratedTile; bodies: () => VehicleBodies | null } => {
    const dressed = prepared === null ? null : worldLook.inWorldLook(plain, prepared);
    return { tile: dressed?.tile ?? plain, bodies: dressed?.bodies ?? (() => null) };
  };
  /** What a prepared look says of the world's own setting, for the look's state; nothing for a world with none. */
  const settingOf = (one: Prepared | null): { readonly setting?: { readonly drawn: boolean; readonly reason: string | null } } => (
    one === null || one.setting === null ? {} : { setting: one.setting }
  );
  let choice = worldLook.worldLookChoice(search, bound);
  let prepared: Prepared | null = null;
  let reason: string | null = null;
  try {
    choice = await resolved(choice);
    prepared = await prepare(choice);
  } catch (error) {
    reason = error instanceof Error ? error.message : String(error);
  }
  const plain = await route.loadGeneratedTile({
    name: first!.name,
    bytes: first!.bytes,
    manifest: parseTextureSetManifest(library.textureManifest),
    fetchSet: (set) => library.textureSet(set.contentSha256),
    ...(neighbours.length === 0 ? {} : { neighbours }),
    ...(prepared === null ? {} : { look: prepared.look }),
  });
  const drawn = dressedIn(plain, prepared);
  const loaded = drawn.tile;
  // Where a person arrives is the world's own spawn, served in the region's frame: east, height,
  // south. The renderer's frame is east, up and south in metres, so it is read across unchanged.
  // Its yaw 0 looks north with forward (-sin yaw, 0, -cos yaw), so a facing of (east, south) is
  // yaw = atan2(-east, -south).
  const [east, height, south] = ground.arrivalMm;
  const [facingEast, facingSouth] = ground.arrivalFacingMm;
  const stand = groundNear(loaded.navigationWorld.surface, east, south, [facingEast, facingSouth]);
  const surface = loaded.navigationWorld.surface;
  // Facing the placed things, from the nearest spot whose sight of them nothing parked blocks. With
  // nothing placed the view is chosen from the town's own tiles alone and the parked vehicles, which
  // may or may not arrive in time, are not asked after: the town opens the same way either way.
  const [targets, parked] = await Promise.all([placing, parking]);
  const view = arrivalView({
    eastMm: stand?.eastMm ?? east, southMm: stand?.southMm ?? south, facing: [facingEast, facingSouth],
    targets, parked,
    ground: (e, s) => surface.sample(e / 1000, s / 1000) !== null,
    // What stands at eye height in the town's own records, how a town with nothing placed is looked
    // at, and the seats and doors that view is chosen by.
    blockers: sightBlockersOfTown(route, containers, loaded),
    open: TOWN_FIRST_VIEW,
    life: lifeOfTown(route, containers, furniture),
  });
  const standHeight = view.moved ? surface.sample(view.eastMm / 1000, view.southMm / 1000)?.height ?? null : null;
  const start = {
    x: view.eastMm / 1000,
    y: (standHeight ?? stand?.heightM ?? height / 1000) + loaded.navigationWorld.eyeHeight,
    z: view.southMm / 1000,
    yaw: view.yaw,
    pitch: 0,
  };
  return {
    tile: { ...loaded, start },
    ground,
    look: { pack: choice.packId, source: choice.source, drawn: prepared !== null, reason, ...settingOf(prepared) },
    bodies: drawn.bodies,
    async relook(asked) {
      const next = await resolved(asked);
      const nextPrepared = await prepare(next);
      // A look is read only when tiles are attached, so the tiles as loaded are drawn again in the
      // new pack's light: nothing is fetched, verified or decoded a second time.
      const again = dressedIn(plain.inLook(nextPrepared?.look ?? route.TILE_LOOK_V1), nextPrepared);
      return {
        tile: { ...again.tile, start },
        bodies: again.bodies,
        look: { pack: next.packId, source: next.source, drawn: nextPrepared !== null, reason: null, ...settingOf(nextPrepared) },
      };
    },
  };
}

/**
 * The world's tiles as the page mounts them, with a look that can be swapped while they stay
 * mounted: what `redrawWorldLook` draws in while this world is attached.
 */
export function switchableWorld(
  world: GeneratedWorld,
  stated: (look: GeneratedWorld['look']) => void,
  shell: Element,
): { readonly tile: LoadedGeneratedTile; readonly bodies: () => VehicleBodies | null; readonly bodiesChanged: (listener: () => void) => () => void } {
  let current: { readonly tile: LoadedGeneratedTile; readonly bodies: () => VehicleBodies | null } = world;
  const listeners = new Set<() => void>();
  const drawing = swappableDrawing(world.tile, (choice) => world.relook(choice), (next) => next.tile, (next) => {
    current = next;
    for (const listener of listeners) listener();
    stated({ ...next.look, source: 'redraw' });
  }, shell);
  return {
    bodies: () => current.bodies(),
    bodiesChanged(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    tile: { ...world.tile, attach: (host) => drawing.attach(host) },
  };
}

/** Whether a load finished with a world to mount, rather than one still being built. */
export function isGeneratedWorld(
  value: GeneratedWorld | GeneratedWorldWaiting | null,
): value is GeneratedWorld {
  return value !== null && 'tile' in value;
}

/** Where the entry's tiles stand, as the server now says: all baked, one failed, or still baking. */
async function bakeState(
  access: Credentials,
  entry: SavedWorldEntry,
): Promise<'baked' | 'failed' | 'baking'> {
  const response = await fetch(`${access.baseUrl}/world-entries/${encodeURIComponent(entry.entryId)}`, {
    headers: { ...accessHeaders(access), Accept: 'application/json' },
    credentials: 'same-origin',
  });
  if (!response.ok) return 'baking';
  const body = await response.json() as { generated_ground?: { tiles?: readonly { state?: string }[] } };
  const tiles = body.generated_ground?.tiles ?? [];
  if (tiles.some((tile) => tile.state === 'failed')) return 'failed';
  return tiles.length > 0 && tiles.every((tile) => tile.state === 'baked') ? 'baked' : 'baking';
}

/**
 * While a world's tiles bake, reads its entry every `WAITING_POLL_MS`, and at once whenever the page
 * is shown again, since a hidden page's timers are held back. Once every tile is baked or one has
 * failed it stops and announces the world can be opened again, which then draws it or says why
 * not. It stops as well once its words are taken down, when another world is opened.
 */
function watchBakes(env: AppEnvironment, access: Credentials, entry: SavedWorldEntry, words: Element): void {
  let done = false;
  let reading = false;
  const stop = (): void => {
    done = true;
    window.clearInterval(timer);
    document.removeEventListener('visibilitychange', shown);
  };
  const check = (): void => {
    if (done || reading) return;
    if (!words.isConnected) {
      stop();
      return;
    }
    reading = true;
    void bakeState(access, entry).then((state) => {
      reading = false;
      if (done || state === 'baking') return;
      stop();
      const detail: GeneratedWorldReady = { entryId: entry.entryId };
      env.shell.dispatchEvent(new CustomEvent(GENERATED_WORLD_READY_EVENT, { bubbles: true, detail }));
    }, () => {
      reading = false;
    });
  };
  const shown = (): void => {
    if (document.visibilityState === 'visible') check();
  };
  const timer = window.setInterval(check, WAITING_POLL_MS);
  document.addEventListener('visibilitychange', shown);
}

/**
 * Why a world shows no vehicles, in words, from the traffic route's refusal code: the words the
 * copy states for that code, one sentence for every refusal to read the world's records, and the
 * code itself inside a general sentence for any other, so the page is never blank about it.
 */
export function trafficRefusalWords(code: string): string {
  if (code.startsWith(UNREADABLE_PREFIX)) return say('world.traffic.unreadable');
  const key = `world.traffic.${code}`;
  const words = say(key);
  return words === key ? fill('world.traffic.other', { reason: code }) : words;
}

/**
 * The world's tiles, with the world's own traffic drawn while they are attached. A refusal the
 * server will keep giving is said in words on the shell until the tiles are taken down.
 */
async function withWorldTraffic(
  env: AppEnvironment,
  access: Credentials,
  entry: SavedWorldEntry,
  tile: LoadedGeneratedTile,
  bodies: () => VehicleBodies | null = () => null,
  bodiesChanged?: (listener: () => void) => () => void,
): Promise<LoadedGeneratedTile> {
  const note = (): Element | null => env.shell.querySelector(`[${WORLD_TRAFFIC_NOTE_ATTRIBUTE}]`);
  const explain = (code: string): void => {
    note()?.remove();
    env.shell.append(el('p', {
      class: 'world-traffic-note', role: 'status', text: trafficRefusalWords(code),
      [WORLD_TRAFFIC_NOTE_ATTRIBUTE]: code,
    }));
  };
  // Taking the tiles down takes the note down, and the drawn state when there is one.
  const cleared = (drawn: LoadedGeneratedTile, stated: string | null): LoadedGeneratedTile => ({
    ...drawn,
    attach(host: GeneratedTileHost): GeneratedTileAttachment {
      const attachment = drawn.attach(host);
      return {
        metrics: attachment.metrics,
        get animating() {
          return attachment.animating ?? false;
        },
        dispose() {
          attachment.dispose();
          note()?.remove();
          if (stated !== null) env.shell.removeAttribute(stated);
        },
      };
    },
  });
  let modules: [typeof import('./tile-traffic.js'), typeof import('../traffic-api.js')];
  try {
    modules = await Promise.all([import('./tile-traffic.js'), import('../traffic-api.js')]);
  } catch {
    // The world opens without its vehicles rather than not at all, and says so.
    explain(TRAFFIC_NOT_LOADED);
    return cleared(tile, null);
  }
  const [{ TILE_TRAFFIC_ATTRIBUTE, withTraffic }, { WorldTrafficClient }] = modules;
  const client = new WorldTrafficClient(access);
  return cleared(withTraffic(
    tile,
    {
      window: (fromSecond, seconds, signal) =>
        client.window(entry.worldId, entry.authoredVersionId, fromSecond, seconds, signal),
    },
    (state) => {
      env.shell.setAttribute(TILE_TRAFFIC_ATTRIBUTE, JSON.stringify(state));
      if (state.state !== 'refused' || state.reason === null) {
        note()?.remove();
        return;
      }
      explain(state.reason);
    },
    bodies,
    bodiesChanged,
  ), TILE_TRAFFIC_ATTRIBUTE);
}

/**
 * The tile to mount for a saved generated world, with its traffic, or null while the world is not
 * drawn yet, in which case the page says why and, while tiles are baking, opens the world again
 * once every one is baked or one has failed.
 */
export async function openGeneratedWorld(
  env: AppEnvironment,
  access: Credentials,
  entry: SavedWorldEntry,
  bound: WorldStylePackBinding | null = null,
): Promise<LoadedGeneratedTile | null> {
  env.shell.querySelector(`[${GENERATED_WORLD_WAITING_ATTRIBUTE}]`)?.remove();
  const loaded = await loadGeneratedWorld(access, entry, undefined, bound);
  if (loaded === null) return null;
  if (isGeneratedWorld(loaded)) {
    const stated = (look: GeneratedWorld['look']): void => env.shell.setAttribute(WORLD_LOOK_ATTRIBUTE, JSON.stringify(look));
    stated(loaded.look);
    const world = switchableWorld(loaded, stated, env.shell);
    return withWorldTraffic(env, access, entry, world.tile, world.bodies, world.bodiesChanged);
  }
  const words = loaded.waiting === 'baking'
    ? fill('world.generated.baking', { recipe: loaded.ground.recipeLabel })
    : say('world.generated.failed');
  const note = el('p', {
    class: 'reconstruction-loading', role: 'status', text: words,
    [GENERATED_WORLD_WAITING_ATTRIBUTE]: loaded.waiting,
  });
  env.shell.append(note);
  if (loaded.waiting === 'baking') watchBakes(env, access, entry, note);
  return null;
}
