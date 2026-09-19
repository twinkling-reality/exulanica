/**
 * DEVELOPMENT EVALUATION of one baked generated tile, inside the normal shell.
 *
 * A generated tile may not appear in any person's world until a superseding governance ADR is
 * accepted in writing. So this module is reached only from `renderer.ts`, only behind
 * `import.meta.env.DEV`, and only when the synthetic preview route names a tile; it refuses to run
 * otherwise. A production build drops the branch and this module with it, which
 * `test/generated-tile-evaluation.test.ts` proves by building the app.
 *
 * The tile replaces the owned district for that page: same shell, same Companion, same reticle,
 * the tile's own ground (or a stated viewpoint when it has none) and the tile runtime's light. What
 * the tile does not draw is listed on screen, record by record, rather than filled in.
 */

import type { FetchedWalkWorld, LoadedGeneratedTile } from '@exulanica/atlas-react/generated-tile';
import { type BakedTileRequest, type WalkPose, credentials, developmentToken, statedWalkPose } from '../config.js';
import { el } from '../ui/dom.js';
import type { AppEnvironment } from './session-state.js';

export const GENERATED_TILE_EVALUATION_ATTRIBUTE = 'data-generated-tile-evaluation';
/**
 * Where the walk opened, as DATA rather than as prose, because a check that had to parse the
 * sentence would read a reworded default line as a stated pose and pass a frame nobody stated.
 * `stated` or `default`, and for a stated pose the four integers the walk named.
 */
export const GENERATED_TILE_OPENING_ATTRIBUTE = 'data-generated-tile-opening';
export const GENERATED_TILE_POSE_ATTRIBUTE = 'data-generated-tile-pose';
/**
 * WHAT THE WALK'S WORLD IS, AS DATA, for the same reason the opening pose is data: a check that had
 * to parse a sentence would read a reworded line as something it is not, and a record binding
 * several containers must be able to say what each one was for without depending on the wording of
 * the statement beside it. It states `opensOn`, the container the frames are OF, and two SETS,
 * `drawn` and `stoodOn`; see `stateWorld` for why a set rather than a relationship. `reach` is
 * `stated` or `unstated`, because a world of one tile because nobody said how far the walk goes is
 * a different fact from a world of one tile because there was nothing within reach.
 */
export const GENERATED_TILE_WORLD_ATTRIBUTE = 'data-generated-tile-world';

/** Where a tile's container came from, said on screen so no picture of a walk can hide it. */
export type TileProvenance =
  | { readonly kind: 'development'; readonly name: string; readonly containerSha256: string }
  | { readonly kind: 'route'; readonly bakedTileId: string; readonly containerSha256: string; readonly origin: string };

function provenanceLine(provenance: TileProvenance): string {
  if (provenance.kind === 'development') {
    // NOT "the committed golden": this development server serves whatever `dev/tiles/` holds in the
    // working tree, and a lane baking its own tile there is the normal case rather than the odd one.
    // The page cannot know what is committed, so it says what it does know, which is the digest, and
    // leaves the comparison to a reader who can make it.
    return `Container: ${provenance.name}.owd, served from this development server's working tree, `
      + `sha256 ${provenance.containerSha256}. This page cannot tell whether those bytes are the committed golden. `
      + 'Texture sets: the committed library.';
  }
  return `Container: fetched from /tiles as ${provenance.bakedTileId} (${provenance.origin}), sha256 ${provenance.containerSha256}. `
    + 'Texture sets: the committed library, because no route serves the published library yet.';
}

/**
 * The pose a walk opened at, and where it came from.
 *
 * A stated pose is the walk's own fact, given by whoever defines the walk, in integer millimetres of
 * the city frame with an integer facing, so two runs of one walk cannot differ by a rounding and no
 * bearing convention has to be agreed. An unstated pose falls to this runtime's default, which is a
 * guess dressed as a convention and must never be load bearing for anything scored: hence the line on
 * screen saying which of the two a frame is, because two frames that look alike, one reproducible and
 * one not, are otherwise indistinguishable in a record.
 */
interface Opening {
  readonly pose: WalkPose | null;
  readonly supported: boolean;
  readonly start: LoadedGeneratedTile['start'];
}

/**
 * The route obstruction rings this tile states, and what they are not.
 *
 * The caution travels with the number because a reader meeting rings for the first time will assume
 * they stop a body. They do not: they have no height, nothing in them blocks the capsule, and they
 * decide which way a walk faces. Horizontal blocking waits on a collision proxy no tile materialises.
 */
function ringLine(tile: LoadedGeneratedTile): string {
  const { obstacles, refused } = tile.routeObstructions;
  const records = new Set(obstacles.map((obstacle) => obstacle.id.slice(obstacle.id.indexOf(':') + 1))).size;
  const dropped = refused.length === 0 ? '' : `, ${refused.length} refused`;
  return `${obstacles.length} route obstruction rings from ${records} records${dropped}: stated for a route rule to read, `
    + 'not carried into movement, so they stop no body.';
}

/** Where the walk began and whether anybody stated it, which is what makes a frame reproducible. */
function openingLine(opening: Opening): string {
  if (opening.pose === null) {
    return 'Opened at this runtime\'s default pose: the middle of the nav_envelope\'s southern edge, facing north.';
  }
  const { xMm, yMm, facingDx, facingDy } = opening.pose;
  return `Opened at a stated pose: ${xMm}, ${yMm} mm, facing (${facingDx}, ${facingDy})${opening.supported ? '' : ', where the tile states no walkable surface'}.`;
}

/** One container of the world, as a record binds it. Coordinates beside the name, never instead. */
interface StatedContainer {
  readonly tile: string;
  readonly tileX: number;
  readonly tileY: number;
  readonly containerSha256: string;
}

/**
 * The world as data on the shell: what a check binds, beside the sentence a person reads.
 *
 * TWO SETS, AND THE READER TAKES THE DIFFERENCE. `drawn` is every container whose records reached
 * the frame and `stoodOn` is every container whose ground reached the walkable surface, each
 * including the tile the walk opens on. They hold the same containers today, because a walk draws
 * every neighbour it fetches, and the empty difference is therefore something a reader COMPUTES
 * rather than a field somebody maintains.
 *
 * THE FIELD THIS REPLACES NAMED A RELATIONSHIP RATHER THAN A SET. `stoodOnOnly` was correct while
 * neighbours were composed and never drawn; the moment they are drawn, its own name states
 * something untrue, into an append-only record. Keeping it and leaving it always empty would have
 * been worse than renaming it: an empty list reads as a distinction that is tracked and came out
 * empty, rather than one that is vestigial. The difference will not stay empty for ever. A
 * neighbour served its navigation sections alone, measured at 1,969,322 bytes against 11,630,504
 * for its whole container, is ground with no street, and on that day `stoodOn` is a superset of
 * `drawn` and this shape says so with nothing renamed.
 *
 * `opensOn` IS THE FACT NEITHER SET CARRIES. A frame is OF a container and a pose is ON one, and a
 * reader should not have to take the first entry of a list, which is a position rather than an
 * identity.
 *
 * EXPORTED FOR THE SAME REASON `worldLine` IS, and the reason is a limit rather than a convenience.
 * This repository commits ONE container, so no test that goes through the page can reach a world of
 * several: a second tile's bytes would have to be baked, and a partition of the committed document
 * shares its records with the golden, which this runtime rightly refuses as one record drawn twice.
 * Every branch below that tells the two sets apart is therefore unreachable through the page, and a
 * run of the real route is its only other exercise. Called directly, the branches can be reached.
 */
export function stateWorld(
  env: AppEnvironment,
  opensOn: StatedContainer,
  tile: LoadedGeneratedTile,
  world: FetchedWalkWorld | null,
): void {
  // THE COORDINATES, NOT ONLY THE NAME. A reader that had to parse `tile (3,0)` back into numbers
  // would be parsing a string this file formats, which is the same fault as binding the sentence
  // one level down.
  const byName = new Map<string, StatedContainer>([[tile.name, opensOn]]);
  for (const neighbour of world?.neighbours ?? []) {
    byName.set(neighbour.name, {
      tile: neighbour.name,
      tileX: neighbour.tileX,
      tileY: neighbour.tileY,
      containerSha256: neighbour.containerSha256,
    });
  }
  // THE RUNTIME'S ACCOUNT OF THE WORLD, HELD AGAINST THIS PAGE'S. The runtime says which containers
  // it drew and stood on; this page says which it fetched. They are two observations of one world
  // and a name in one and not the other is a world assembled from something nobody asked for.
  const stated = (one: { readonly name: string }): StatedContainer => {
    const container = byName.get(one.name);
    if (container === undefined) {
      throw new Error(`The runtime says its world holds ${one.name}, which this page did not fetch.`);
    }
    return container;
  };
  env.shell.setAttribute(GENERATED_TILE_WORLD_ATTRIBUTE, JSON.stringify({
    reach: world === null ? 'unstated' : 'stated',
    opensOn,
    drawn: tile.worldTiles.filter((one) => one.drawn).map(stated),
    stoodOn: tile.worldTiles.filter((one) => one.stoodOn).map(stated),
    neighbourTransferredBytes: world === null ? 0 : world.transferredBytes,
    absent: world === null ? [] : world.absent,
  }));
}

function stateOpening(env: AppEnvironment, opening: Opening): void {
  env.shell.setAttribute(GENERATED_TILE_OPENING_ATTRIBUTE, opening.pose === null ? 'default' : 'stated');
  if (opening.pose === null) {
    env.shell.removeAttribute(GENERATED_TILE_POSE_ATTRIBUTE);
    return;
  }
  const { xMm, yMm, facingDx, facingDy } = opening.pose;
  env.shell.setAttribute(GENERATED_TILE_POSE_ATTRIBUTE, `${xMm},${yMm},${facingDx},${facingDy}`);
}

/**
 * WHICH CONTAINERS THIS WALK STANDS ON, AND WHICH OF THEM IT DRAWS.
 *
 * Every container within the walk's reach is drawn and stood on, so a camera at the end of a route
 * looks down a street rather than at the edge of the loaded world. A reader meeting several digests
 * and a walk that completed can tell what each one was for without remembering the evening it was
 * built, and a container that were ever stood on and not drawn would be named as such HERE rather
 * than left to be inferred from a count. The squares within reach that hold no ground are named for
 * the same reason: they are the edge of the loaded world, not a defect in a street, and a sampler
 * returning nothing there is correct.
 */
export function worldLine(world: FetchedWalkWorld | null, tile: LoadedGeneratedTile): string {
  if (world === null) {
    return 'World: this one tile. The walk stated no reach, so no neighbouring ground was asked for '
      + 'and the ground ends at this tile\'s own edge.';
  }
  const named = (one: { readonly name: string }): string => {
    const digest = one.name === tile.name ? '' : world.neighbours.find((each) => each.name === one.name)?.containerSha256;
    return digest === undefined || digest === '' ? one.name : `${one.name} ${digest.slice(0, 8)}`;
  };
  const drawn = tile.worldTiles.filter((one) => one.drawn).map(named);
  const groundOnly = tile.worldTiles.filter((one) => one.stoodOn && !one.drawn).map(named);
  const missing = world.absent.map((each) => `(${each.tileX},${each.tileY}) ${each.reason}`);
  return `World: ${tile.worldTiles.length} containers, opening on ${tile.name}. `
    + `Drawn and stood on: ${drawn.join(', ')}. `
    + `${groundOnly.length === 0 ? 'None is ground without a street.' : `STOOD ON AND NOT DRAWN: ${groundOnly.join(', ')}.`} `
    + `${world.transferredBytes.toLocaleString()} bytes fetched for the neighbours. `
    + `${missing.length === 0 ? 'Every square within reach has ground.' : `No ground within reach at: ${missing.join(', ')}.`}`;
}

function statement(
  tile: LoadedGeneratedTile,
  provenance: TileProvenance,
  opening: Opening,
  world: FetchedWalkWorld | null,
): HTMLElement {
  const drawn = tile.ranges.filter((range) => range.state === 'drawn');
  const named = (range: LoadedGeneratedTile['ranges'][number]): string =>
    `${range.kind}${range.identity === null ? '' : ` ${range.identity}`}`;
  // Drawing is per surface, so an unavailable surface is listed with its record, role and orientation.
  const unavailableSurfaces = drawn.flatMap((range) => range.state !== 'drawn' ? [] : range.surfaces
    .filter((surface) => surface.state === 'unavailable')
    .map((surface) => `${named(range)} ${surface.role} (${surface.orientation}): ${surface.reason ?? ''}`));
  const notDrawn = tile.ranges.flatMap((range) => range.state === 'drawn' ? [] : [`${named(range)}: ${range.reason}`]);
  const lines = [
    `Development evaluation of generated tile ${tile.name}. Not part of any world.`,
    tile.navigation.viewpointOnly
      ? `Viewpoint only: ${tile.navigation.support.state === 'unavailable' ? tile.navigation.support.reason : ''}`
      : `Standing on the tile's nav_envelope. ${tile.navigation.collisionState.reason}`,
    `${drawn.length} of ${tile.ranges.length} records drawn; ${unavailableSurfaces.length} `
      + `${unavailableSurfaces.length === 1 ? 'surface' : 'surfaces'} drawn as unavailable.`,
    provenanceLine(provenance),
    worldLine(world, tile),
    openingLine(opening),
    ringLine(tile),
  ];
  const items = [...unavailableSurfaces, ...notDrawn].map((text) => el('li', { text }));
  return el('section', {
    class: 'generated-tile-evaluation',
    role: 'note',
    'aria-label': 'Generated tile evaluation',
    // The bottom left column the proof lens and environment selection use, so the scene segments
    // panel, anchored just right of that column, never covers the statement.
    style: 'position:fixed;left:var(--gap);bottom:12px;box-sizing:border-box;width:min(24rem,calc(100vw - 2 * var(--gap)));'
      + 'z-index:5;padding:8px 10px;'
      + 'font:12px/1.4 ui-monospace,Menlo,monospace;color:#f4f1ea;background:rgba(12,14,18,.78);border-radius:6px',
  }, [
    ...lines.map((line) => el('p', { text: line, style: 'margin:0 0 2px' })),
    el('details', {}, [
      el('summary', { text: `Unavailable or not drawn (${items.length})` }),
      el('ul', { style: 'margin:4px 0 0;padding-left:16px;max-height:30vh;overflow:auto' }, items),
    ]),
  ]);
}

export async function prepareGeneratedTileEvaluation(env: AppEnvironment, name: string): Promise<LoadedGeneratedTile> {
  if (!import.meta.env.DEV || !env.preview) {
    throw new Error('A generated tile can be evaluated only on the development preview route.');
  }
  const [{ loadGeneratedTile, tilePlacement, tileToRenderer }, { ambientTextureSetDigest, parseTextureSetManifest }, sources] = await Promise.all([
    import('@exulanica/atlas-react/generated-tile'),
    import('@exulanica/atlas-core'),
    import('../dev/generated-tile-sources.js'),
  ]);
  // A malformed pose refuses the whole request here exactly as it does on the product route: a
  // silent fallback is how a frame that is not reproducible ends up in a record looking like one.
  const pose = statedWalkPose(window.location.search, env.preview);
  if (pose === 'malformed') {
    throw new Error('The stated pose is not four integers with a direction, so this walk is refused rather than opened at a default.');
  }
  const source = await sources.generatedTileSource(name);
  const digest = ambientTextureSetDigest();
  if (digest === null) {
    throw new Error('This page has no crypto.subtle, so no tile can be checked against its own records.');
  }
  const containerSha256 = hex(await digest.digest('SHA-256', source.tile));
  const manifest = parseTextureSetManifest(source.textureManifest);
  const tile = await loadGeneratedTile({
    name,
    bytes: source.tile,
    manifest,
    fetchSet: (entry) => source.textureSet(entry.contentSha256),
  });
  // The title stays the preview's own: the visual gate harness holds the shell to it.
  env.shell.setAttribute(GENERATED_TILE_EVALUATION_ATTRIBUTE, name);
  env.shell.querySelector('.generated-tile-evaluation')?.remove();
  const opening = openTile(tile, pose, tileToRenderer);
  env.shell.append(statement(tile, { kind: 'development', name, containerSha256 }, opening, null));
  // A committed golden has no rows to compose a world from, so its world is this one tile and the
  // attribute says the reach was never stated rather than leaving a reader to infer it. It carries
  // no row either, so its coordinates come from the container's own tile record.
  const placed = tilePlacement(source.tile);
  stateWorld(env, { tile: tile.name, tileX: placed.tileX, tileY: placed.tileY, containerSha256 }, tile, null);
  stateOpening(env, opening);
  await (await import('../dev/tile-capture.js')).exposeTileCapture(env.preview, tile);
  return { ...tile, start: opening.start };
}

function hex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** Containers this page already fetched, by key, so a reload inside one page asks for no bytes. */
const held = new Map<string, { readonly containerSha256: string; readonly bytes: Uint8Array }>();

/**
 * A baked corridor tile fetched from the product route, drawn on the same development page.
 *
 * THE SPLIT, and it is a decision rather than an accident: the CONTAINER comes from `/tiles` with
 * this session's credential, because a generated tile is never committed to this repository, and the
 * TEXTURE SETS come from the committed library through this development page, because they are
 * committed and no route serves the published texture library yet. The statement on screen says so,
 * so no picture of this street implies a product path that does not exist.
 *
 * The credential is the development token and nothing else: with no token this refuses in plain
 * words rather than asking the route anonymously, because an anonymous ask is answered 404 exactly
 * as an unknown tile is, and a walker would be told the wrong thing.
 */
export async function prepareBakedTileWalk(env: AppEnvironment, request: BakedTileRequest): Promise<LoadedGeneratedTile> {
  if (!import.meta.env.DEV || !env.preview) {
    throw new Error('A baked tile can be walked only on the development preview route.');
  }
  const token = developmentToken();
  if (token === null) {
    throw new Error('No development token, so no baked tile can be asked for: the route serves a credential holding tiles.materialise and nothing else.');
  }
  const [route, { ambientTextureSetDigest, parseTextureSetManifest }, sources] = await Promise.all([
    import('@exulanica/atlas-react/generated-tile'),
    import('@exulanica/atlas-core'),
    import('../dev/generated-tile-sources.js'),
  ]);
  const access = { baseUrl: credentials(token).baseUrl, token };
  const digest = ambientTextureSetDigest();
  if (digest === null) {
    throw new Error('This page has no crypto.subtle, so no container can be checked against its own digest.');
  }

  let summary: Awaited<ReturnType<typeof route.listBakedTiles>>[number] | undefined;
  let neighbourhood: Awaited<ReturnType<typeof route.listBakedTiles>> = [];
  let bakedTileId: string;
  if (request.kind === 'key') {
    bakedTileId = request.bakedTileId;
  } else {
    const tiles = await route.listBakedTiles(access, { citySeed: request.citySeed, lod: request.lod });
    neighbourhood = tiles;
    const found = route.tileAt(tiles, { tileX: request.tileX, tileY: request.tileY, lod: request.lod });
    if (found === null) {
      throw new Error(`City ${request.citySeed} has no tile at (${request.tileX}, ${request.tileY}) at level of detail ${request.lod}.`);
    }
    summary = found;
    bakedTileId = found.bakedTileId;
  }

  const fetched = await route.fetchBakedTile(access, {
    bakedTileId,
    ...(summary === undefined ? {} : { expect: summary }),
    ...(held.has(bakedTileId) ? { held: held.get(bakedTileId)! } : {}),
    digest,
  });
  held.set(bakedTileId, { containerSha256: fetched.containerSha256, bytes: fetched.bytes });

  // THE WALK'S WORLD, which is more than this tile whenever the walk states how far it may go.
  // A tile is 128,000 mm across and a route is longer, so the ground a route needs does not fit on
  // the tile it is laid on. Only the neighbours' nav_envelope is ever read: THE COMPOSED WORLD IS
  // WALKABLE PAST THE EDGE AND NOT DRAWN PAST IT, and a camera looking past the edge sees no street.
  const placement = route.tilePlacement(fetched.bytes);
  // A ROW AND ITS CONTAINER MUST AGREE ABOUT WHICH TILE THIS IS, and the container is the one that
  // decides, because the bytes state their own identity and a row only points at them. They are
  // checked because THIS is what the neighbours are chosen against: a row naming the wrong container
  // would otherwise compose a world out of another part of the city, and every tile would arrive
  // verified, whole, and in the wrong place.
  if (summary !== undefined
    && (summary.tileX !== placement.tileX || summary.tileY !== placement.tileY || summary.lod !== placement.lod)) {
    throw new Error(
      `The route lists ${bakedTileId} at (${summary.tileX}, ${summary.tileY}) level ${summary.lod}, `
      + `and the container it served says it is (${placement.tileX}, ${placement.tileY}) level ${placement.lod}.`,
    );
  }
  if (request.kind === 'coordinate' && request.citySeed !== placement.worldSeed) {
    throw new Error(
      `This walk asked for world ${request.citySeed} and the container it was served belongs to ${placement.worldSeed}.`,
    );
  }
  let world: Awaited<ReturnType<typeof route.fetchWalkWorld>> | null = null;
  if (request.reachMm !== null) {
    const listed = summary === undefined
      ? await route.listBakedTiles(access, { citySeed: placement.worldSeed, lod: placement.lod })
      : neighbourhood;
    const plan = route.walkWorldTiles(listed, {
      standingOn: placement,
      // A STATED pose is measured from exactly; without one the reach is taken from the whole
      // square, because an unstated walk opens at the runtime's default and that is decided after
      // the world exists. See `walk-world.ts`.
      ...(request.pose === null ? {} : { startMm: [request.pose.xMm, request.pose.yMm] as const }),
      reachMm: request.reachMm,
      lod: placement.lod,
      tileSizeMm: placement.tileSizeMm,
    });
    world = await route.fetchWalkWorld(access, plan, {
      digest,
      worldSeed: placement.worldSeed,
      held: new Map([...held.values()].map((entry) => [entry.containerSha256, entry])),
    });
    plan.neighbours.forEach((row, at) => {
      held.set(row.bakedTileId, { containerSha256: row.containerSha256, bytes: world!.neighbours[at]!.bytes });
    });
  }

  const library = await sources.committedTextureLibrary();
  const tile = await route.loadGeneratedTile({
    name: bakedTileId,
    bytes: fetched.bytes,
    manifest: parseTextureSetManifest(library.textureManifest),
    fetchSet: (entry) => library.textureSet(entry.contentSha256),
    ...(world === null ? {} : { neighbours: world.neighbours }),
  });
  const opening = openTile(tile, request.pose, route.tileToRenderer);
  env.shell.setAttribute(GENERATED_TILE_EVALUATION_ATTRIBUTE, bakedTileId);
  env.shell.querySelector('.generated-tile-evaluation')?.remove();
  env.shell.append(statement(tile, {
    kind: 'route', bakedTileId, containerSha256: fetched.containerSha256, origin: fetched.origin,
  }, opening, world));
  stateWorld(env, {
    tile: tile.name, tileX: placement.tileX, tileY: placement.tileY, containerSha256: fetched.containerSha256,
  }, tile, world);
  stateOpening(env, opening);
  await (await import('../dev/tile-capture.js')).exposeTileCapture(env.preview, tile);
  return { ...tile, start: opening.start };
}

/**
 * The walk's opening pose in the renderer's frame, or the tile's own default where none was stated.
 *
 * The tile frame has x east, y north and z up in millimetres; the renderer has x east, y up and z
 * south in metres, and yaw 0 looks north with forward (-sin yaw, 0, -cos yaw). So a facing of (dx, dy)
 * is yaw = atan2(-dx, dy): east (1, 0) gives -90 degrees, whose forward is (1, 0, 0), which is east.
 *
 * THERE ARE TWO YAW ZEROS IN THIS TREE AND THEY ARE A HALF TURN APART. The one above is the camera's,
 * with forward (-sin yaw, 0, -cos yaw) as `atlas-binding.ts` states it, so yaw 0 looks north.
 * `atlas-core`'s own basis has yaw 0 looking along +Z, the opposite pole, and the two are reconciled
 * in exactly one place: `Controls.forward()` adds a single `Math.PI`, with its reason written beside
 * it. A reader meeting this header and then meeting atlas-core would otherwise find two conventions
 * and no sentence saying so. Checked against both, and against a measurement rather than only a
 * convention: the corridor lane committed a facing of (1, 0) before any walk existed, and a trace of
 * 3,000 steps moved the walker from x 262,017 to x 383,999, increasing, which is east in the tile
 * frame.
 * The height is the envelope's, sampled where the walk begins, so a stated pose stands on the ground
 * rather than at a stated altitude; where the envelope has no support there, the pose is still honoured
 * and the statement says the tile states no walkable surface there, rather than moving the walk
 * somewhere nobody asked for.
 */
export function openTile(
  tile: LoadedGeneratedTile,
  pose: WalkPose | null,
  toRenderer: (x: number, y: number, z: number) => readonly [number, number, number],
): Opening {
  if (pose === null) return { pose: null, supported: true, start: tile.start };
  const [x, , z] = toRenderer(pose.xMm, pose.yMm, 0);
  const sample = tile.navigationWorld.surface.sample(x, z);
  const yaw = Math.atan2(-pose.facingDx, pose.facingDy);
  const y = (sample?.height ?? tile.start.y - tile.navigationWorld.eyeHeight) + tile.navigationWorld.eyeHeight;
  return { pose, supported: sample !== null, start: { x, y, z, yaw, pitch: 0 } };
}
