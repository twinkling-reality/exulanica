/**
 * DEVELOPMENT ONLY: what a driver outside the page needs from the tile this page mounted.
 *
 * The two guards are the ones the tile evaluation itself sits behind, and they are the whole of the
 * safety argument: this module is imported only from `composition/generated-tile.ts`, which runs only
 * when `import.meta.env.DEV` is true AND the page is the synthetic preview route. A production build
 * drops the branch, the import and this file with it, which
 * `test/generated-tile-evaluation.test.ts` proves by building the app.
 *
 * It is on `window` because the driver is outside the page: a headless browser evaluating an
 * expression cannot reach a module's exports, only what the page has put somewhere it can name.
 *
 * TWO HOOKS: one to step the runtime a stated frame at a time, and one to read the route obstruction
 * rings the tile states. Those rings were reachable at `navigationWorld.polygonObstacles` until they
 * were taken out of it, because that field is collided against and a ring stopped a walker 344 mm
 * from a bench. They are stated on the tile now, and the evaluation panel reads them from there to
 * say how many there are. A driver that had to read that sentence would make a scored verdict depend
 * on its wording, so the same object the panel reads is handed back as data.
 */

import type { LoadedGeneratedTile } from '@exulanica/atlas-react/generated-tile';

declare global {
  interface Window {
    __exulanicaTileCapture?: () => unknown;
    __exulanicaTileRouteObstructions?: () => unknown;
  }
}

export async function exposeTileCapture(preview: boolean, tile: LoadedGeneratedTile): Promise<void> {
  if (!import.meta.env.DEV || !preview) return;
  const { beginTileCapture } = await import('@exulanica/atlas-react/generated-tile');
  window.__exulanicaTileCapture = beginTileCapture;
  // BOTH HALVES, because the runtime separates them: the rings it carries, and the regions it refused
  // with the reason for each. A hook that handed back only the obstacles would say "16 rings" where
  // the tile says "16 rings and none refused", and a reader could not tell a tile whose regions all
  // stood from one whose regions were quietly dropped.
  window.__exulanicaTileRouteObstructions = () => tile.routeObstructions;
}
