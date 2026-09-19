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

import { credentials, developmentToken } from '../config.js';

/**
 * The ONE path the probe below asks about, as a constant and never an argument.
 *
 * A hook that takes a path is an authenticated request proxy reachable from page context. A hook
 * that probes one path is a probe: it answers exactly one question and can answer no other.
 */
const PROBE_PATH = '/graph';

declare global {
  interface Window {
    __exulanicaTileCapture?: () => unknown;
    __exulanicaTileRouteObstructions?: () => unknown;
    __exulanicaTileUnavailableSurfaces?: () => unknown;
    __exulanicaProbeProductApi?: () => Promise<unknown>;
  }
}

/**
 * Ask the product API for one path WITH THIS PAGE'S OWN CREDENTIAL, and hand back the status alone.
 *
 * WHY THIS EXISTS, and it will not be obvious later: the visual gate records how a page proved who
 * it was, and one clause of the condition this preview is scored under is that the product API was
 * asked for something outside tiles AND REFUSED IT. The page asks for the graph only in some states,
 * and not in the clean profile a gate run launches, so the evidence was absent exactly when it was
 * needed.
 *
 * NOTHING REACHABLE FROM PAGE CONTEXT COULD ASK THIS QUESTION UNTIL THIS HOOK EXISTED. MEASURED
 * 2026-09-19 from inside the page: a bare `fetch('/api/graph')` answers 401, and so does a bare
 * fetch of `/api/tiles`, THE SAME ROUTE THIS PAGE WAS SERVED 200 ON IN THAT RUN. The credential is
 * attached by the application's own request path and nothing ambient carries it, so a bare fetch
 * answers a DIFFERENT QUESTION THAT LOOKS IDENTICAL: "asked and not served" is literally true of a
 * 401, and a gate reading it would have scored a run on evidence about an anonymous request.
 *
 * WHAT IT RETURNS AND WHAT IT CANNOT. The status and the path, and nothing else: no body, no
 * headers, and never the token. GET only, one constant path, no argument of any kind. It cannot be
 * asked about another endpoint, so it is not a general capability wearing a narrow name.
 */
async function exposeProductApiProbe(): Promise<void> {
  window.__exulanicaProbeProductApi = async () => {
    const token = developmentToken();
    if (token === null) {
      return { path: `/api${PROBE_PATH}`, status: null, asked: false };
    }
    const response = await fetch(`${credentials(token).baseUrl}${PROBE_PATH}`, {
      method: 'GET',
      headers: { authorization: `Bearer ${token}` },
    });
    return { path: `/api${PROBE_PATH}`, status: response.status, asked: true };
  };
}

export async function exposeTileCapture(preview: boolean, tile: LoadedGeneratedTile): Promise<void> {
  if (!import.meta.env.DEV || !preview) return;
  await exposeProductApiProbe();
  const { beginTileCapture } = await import('@exulanica/atlas-react/generated-tile');
  window.__exulanicaTileCapture = beginTileCapture;
  // BOTH HALVES, because the runtime separates them: the rings it carries, and the regions it refused
  // with the reason for each. A hook that handed back only the obstacles would say "16 rings" where
  // the tile says "16 rings and none refused", and a reader could not tell a tile whose regions all
  // stood from one whose regions were quietly dropped.
  window.__exulanicaTileRouteObstructions = () => tile.routeObstructions;
  // EVERY SURFACE DRAWN AS UNAVAILABLE, COUNTED BY THE REASON THE RUNTIME STATES, verbatim.
  //
  // The metric a driver already reads is one total, and a total cannot be read: a surface no
  // material record dresses and a surface whose texture set could not be fetched are both counted
  // there, and on this fixture a run that fetches nothing reports about six times a run that does.
  // A reader holding the total alone cannot tell which kind of run made it.
  //
  // GROUPED BY THE RUNTIME'S OWN STRING and by nothing else. Any category this hook invented would
  // be a second place where reasons are defined, and the two would drift; the caller gets what the
  // tile says and counts it. If that is ever too many strings to be useful, the collapse belongs
  // where the reasons are written rather than here.
  window.__exulanicaTileUnavailableSurfaces = () => {
    const byReason = new Map<string, number>();
    for (const range of tile.ranges) {
      if (range.state !== 'drawn') continue;
      for (const surface of range.surfaces) {
        if (surface.state !== 'unavailable') continue;
        const reason = surface.reason ?? '';
        byReason.set(reason, (byReason.get(reason) ?? 0) + 1);
      }
    }
    return [...byReason].map(([reason, surfaces]) => ({ reason, surfaces }));
  };
}
