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

import type { LoadedGeneratedTile } from '@exulanica/atlas-react/generated-tile';
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

/** Where the walk began and whether anybody stated it, which is what makes a frame reproducible. */
function openingLine(opening: Opening): string {
  if (opening.pose === null) {
    return 'Opened at this runtime\'s default pose: the middle of the nav_envelope\'s southern edge, facing north.';
  }
  const { xMm, yMm, facingDx, facingDy } = opening.pose;
  return `Opened at a stated pose: ${xMm}, ${yMm} mm, facing (${facingDx}, ${facingDy})${opening.supported ? '' : ', where the tile states no walkable surface'}.`;
}

/** The opening as data on the shell: what a check binds, beside the sentence a person reads. */
function stateOpening(env: AppEnvironment, opening: Opening): void {
  env.shell.setAttribute(GENERATED_TILE_OPENING_ATTRIBUTE, opening.pose === null ? 'default' : 'stated');
  if (opening.pose === null) {
    env.shell.removeAttribute(GENERATED_TILE_POSE_ATTRIBUTE);
    return;
  }
  const { xMm, yMm, facingDx, facingDy } = opening.pose;
  env.shell.setAttribute(GENERATED_TILE_POSE_ATTRIBUTE, `${xMm},${yMm},${facingDx},${facingDy}`);
}

function statement(tile: LoadedGeneratedTile, provenance: TileProvenance, opening: Opening): HTMLElement {
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
    openingLine(opening),
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
  const [{ loadGeneratedTile, tileToRenderer }, { ambientTextureSetDigest, parseTextureSetManifest }, sources] = await Promise.all([
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
  env.shell.append(statement(tile, { kind: 'development', name, containerSha256 }, opening));
  stateOpening(env, opening);
  await (await import('../dev/tile-capture.js')).exposeTileCapture(env.preview);
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
  let bakedTileId: string;
  if (request.kind === 'key') {
    bakedTileId = request.bakedTileId;
  } else {
    const tiles = await route.listBakedTiles(access, { citySeed: request.citySeed, lod: request.lod });
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

  const library = await sources.committedTextureLibrary();
  const tile = await route.loadGeneratedTile({
    name: bakedTileId,
    bytes: fetched.bytes,
    manifest: parseTextureSetManifest(library.textureManifest),
    fetchSet: (entry) => library.textureSet(entry.contentSha256),
  });
  const opening = openTile(tile, request.pose, route.tileToRenderer);
  env.shell.setAttribute(GENERATED_TILE_EVALUATION_ATTRIBUTE, bakedTileId);
  env.shell.querySelector('.generated-tile-evaluation')?.remove();
  env.shell.append(statement(tile, {
    kind: 'route', bakedTileId, containerSha256: fetched.containerSha256, origin: fetched.origin,
  }, opening));
  stateOpening(env, opening);
  await (await import('../dev/tile-capture.js')).exposeTileCapture(env.preview);
  return { ...tile, start: opening.start };
}

/**
 * The walk's opening pose in the renderer's frame, or the tile's own default where none was stated.
 *
 * The tile frame has x east, y north and z up in millimetres; the renderer has x east, y up and z
 * south in metres, and yaw 0 looks north with forward (-sin yaw, 0, -cos yaw). So a facing of (dx, dy)
 * is yaw = atan2(-dx, dy): east (1, 0) gives -90 degrees, whose forward is (1, 0, 0), which is east.
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
