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
import { el } from '../ui/dom.js';
import type { AppEnvironment } from './session-state.js';

export const GENERATED_TILE_EVALUATION_ATTRIBUTE = 'data-generated-tile-evaluation';

function statement(tile: LoadedGeneratedTile): HTMLElement {
  const drawn = tile.ranges.filter((range) => range.state === 'drawn');
  const unavailableSurfaces = drawn.filter((range) => range.state === 'drawn' && range.surface === 'unavailable');
  const notDrawn = tile.ranges.filter((range) => range.state !== 'drawn');
  const lines = [
    `Development evaluation of generated tile ${tile.name}. Not part of any world.`,
    tile.navigation.viewpointOnly
      ? `Viewpoint only: ${tile.navigation.support.state === 'unavailable' ? tile.navigation.support.reason : ''}`
      : `Standing on the tile's nav_envelope. ${tile.navigation.collisionState.reason}`,
    `${drawn.length} of ${tile.ranges.length} records drawn; ${unavailableSurfaces.length} drawn as unavailable surface.`,
  ];
  const items = [...unavailableSurfaces, ...notDrawn].map((range) =>
    el('li', { text: `${range.kind}${range.identity === null ? '' : ` ${range.identity}`}: ${range.reason ?? ''}` }));
  return el('section', {
    class: 'generated-tile-evaluation',
    role: 'note',
    'aria-label': 'Generated tile evaluation',
    style: 'position:fixed;left:12px;bottom:12px;max-width:min(34rem,45vw);z-index:5;padding:8px 10px;'
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
  env.shell.setAttribute(GENERATED_TILE_EVALUATION_ATTRIBUTE, name);
  document.title = `${document.title}: generated tile ${name}`;
  env.shell.querySelector('.generated-tile-evaluation')?.remove();
  env.shell.append(statement(tile));
  return tile;
}
