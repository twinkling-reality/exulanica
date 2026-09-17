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
import { type BakedTileRequest, credentials, developmentToken } from '../config.js';
import { el } from '../ui/dom.js';
import type { AppEnvironment } from './session-state.js';

export const GENERATED_TILE_EVALUATION_ATTRIBUTE = 'data-generated-tile-evaluation';

/** Where a tile's container came from, said on screen so no picture of a walk can hide it. */
export type TileProvenance =
  | { readonly kind: 'committed'; readonly name: string }
  | { readonly kind: 'route'; readonly bakedTileId: string; readonly containerSha256: string; readonly origin: string };

function provenanceLine(provenance: TileProvenance): string {
  if (provenance.kind === 'committed') {
    return `Container: the golden ${provenance.name} committed to this repository. Texture sets: the committed library.`;
  }
  return `Container: fetched from /tiles as ${provenance.bakedTileId} (${provenance.origin}), sha256 ${provenance.containerSha256}. `
    + 'Texture sets: the committed library, because no route serves the published library yet.';
}

function statement(tile: LoadedGeneratedTile, provenance: TileProvenance): HTMLElement {
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
  const [{ loadGeneratedTile }, { parseTextureSetManifest }, sources] = await Promise.all([
    import('@exulanica/atlas-react/generated-tile'),
    import('@exulanica/atlas-core'),
    import('../dev/generated-tile-sources.js'),
  ]);
  const source = await sources.generatedTileSource(name);
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
  env.shell.append(statement(tile, { kind: 'committed', name }));
  return tile;
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
  env.shell.setAttribute(GENERATED_TILE_EVALUATION_ATTRIBUTE, bakedTileId);
  env.shell.querySelector('.generated-tile-evaluation')?.remove();
  env.shell.append(statement(tile, {
    kind: 'route', bakedTileId, containerSha256: fetched.containerSha256, origin: fetched.origin,
  }));
  return tile;
}
