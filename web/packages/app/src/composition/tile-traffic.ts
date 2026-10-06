/**
 * A generated world's traffic, drawn while its tiles are attached.
 *
 * The tiles a walk draws are a mount the binding attaches; `withTraffic` wraps it so that attaching
 * it also draws the world's vehicles (`TrafficLayer`), read window by window from a
 * `TrafficReader`, and disposing it stops them. There are two readers: a saved world's own traffic
 * (`GET /world/versions/{version_id}/traffic`, `worldTrafficReader` in `generated-world.ts`), drawn
 * in every generated world the page opens, and, on the development preview only, a baked city's
 * (`GET /tiles/traffic`, `withTileTraffic`, reached only from `generated-tile.ts`).
 *
 * The traffic keeps shared real time. The first read names no second: the server answers from its
 * clock and says where that clock was, and the layer's copy of the clock starts there. While the
 * tile is attached, a window is read whenever less than `AHEAD_MS` of served seconds is left ahead
 * of the clock, from where the served seconds end, or from the clock when it has passed them. A
 * read the server refuses as too far from its clock is read again from the clock. A refusal the
 * server will keep giving for this city (404, 409, 422) or an answer this client cannot read stops
 * the reading and is stated; anything else is tried again later and later, up to `MAX_BACKOFF_MS`.
 *
 * What the page draws and does not is stated on the shell as data (`TILE_TRAFFIC_ATTRIBUTE`): the
 * vehicles served, drawn, held without ground, the clock's second, and that no walker's crossing
 * is fed to the traffic.
 */

import { ApiError, type TransportOptions } from '@exulanica/graph-client';
import type { GeneratedTileAttachment, GeneratedTileHost, LoadedGeneratedTile } from '@exulanica/atlas-react/generated-tile';
import type { TrafficWindow } from '@exulanica/atlas-react/traffic';
import { TrafficClient, TrafficContractError } from '../traffic-api.js';
import type { AppEnvironment } from './session-state.js';

export const TILE_TRAFFIC_ATTRIBUTE = 'data-tile-traffic';
/** Served seconds kept ahead of the page's clock before the next window is read: half a minute. */
export const AHEAD_MS = 30_000;
/** How often the page asks whether a window is due. */
export const POLL_MS = 5_000;
/** Seconds a window asks for: the roads module's largest window, one minute. */
export const WINDOW_SECONDS = 60;
/** The longest wait between tries after a failure the server may not repeat. */
export const MAX_BACKOFF_MS = 60_000;

export interface TileTrafficState {
  readonly state: 'starting' | 'driving' | 'retrying' | 'refused';
  readonly vehicles: number;
  readonly drawn: number;
  readonly hidden: number;
  /** The signals the served window names, and their heads lit at the last draw. */
  readonly signals: number;
  readonly lightsLit: number;
  readonly clockSecond: number | null;
  readonly crossingsFed: false;
  readonly reason: string | null;
}

/** Reads a world's traffic, a window at a time. */
export interface TrafficReader {
  /** The window of `seconds` seconds from `fromSecond`, or from the server's clock when null. */
  window(fromSecond: number | null, seconds: number, signal?: AbortSignal): Promise<{ readonly window: TrafficWindow }>;
}

export interface TileTrafficDeps {
  readonly reader: TrafficReader;
  /** The bodies a style pack draws vehicles in, asked for when the layer is made; none draws boxes. */
  readonly bodies?: () => import('@exulanica/atlas-react/traffic').VehicleBodies | null;
  /**
   * Subscribes a listener told when those bodies change, as when the world is redrawn in another
   * pack; the layer then asks `bodies` again. Returns the listener's removal.
   */
  readonly bodiesChanged?: (listener: () => void) => () => void;
  readonly now?: () => number;
  readonly setTimer?: (callback: () => void, ms: number) => unknown;
  readonly clearTimer?: (handle: unknown) => void;
  readonly report?: (state: TileTrafficState) => void;
}

function lasting(error: unknown): boolean {
  if (error instanceof TrafficContractError) return true;
  return error instanceof ApiError && [404, 409, 422].includes(error.status);
}

/**
 * DEVELOPMENT EVALUATION: the tile a baked city's walk draws, with the city's traffic
 * (`GET /tiles/traffic`) drawn while it is attached. `access` is the credential the walk fetched
 * its tiles with.
 */
export function withTileTraffic(
  tile: LoadedGeneratedTile,
  access: TransportOptions,
  worldSeed: string,
  env: AppEnvironment,
): LoadedGeneratedTile {
  const client = new TrafficClient(access);
  return withTraffic(
    tile,
    { window: (fromSecond, seconds, signal) => client.window(worldSeed, fromSecond, seconds, signal) },
    (state) => env.shell.setAttribute(TILE_TRAFFIC_ATTRIBUTE, JSON.stringify(state)),
  );
}

/**
 * The tile, with the traffic `reader` reads drawn while it is attached, each state reported, its
 * vehicles in the `bodies` a style pack draws them in when there are any.
 */
export function withTraffic(
  tile: LoadedGeneratedTile,
  reader: TrafficReader,
  report: (state: TileTrafficState) => void,
  bodies: () => import('@exulanica/atlas-react/traffic').VehicleBodies | null = () => null,
  bodiesChanged?: (listener: () => void) => () => void,
): LoadedGeneratedTile {
  return {
    ...tile,
    attach(host: GeneratedTileHost): GeneratedTileAttachment {
      const attachment = tile.attach(host);
      const traffic = startTileTraffic(host, tile, {
        reader, report, bodies, ...(bodiesChanged === undefined ? {} : { bodiesChanged }),
      });
      return {
        metrics: attachment.metrics,
        get animating() {
          return (attachment.animating ?? false) || traffic.animating;
        },
        dispose() {
          traffic.stop();
          attachment.dispose();
        },
      };
    },
  };
}

export interface TileTraffic {
  readonly animating: boolean;
  stop(): void;
}

/** Draw a city's traffic under the host's environment root, reading windows ahead of its clock. */
export function startTileTraffic(
  host: GeneratedTileHost,
  tile: Pick<LoadedGeneratedTile, 'navigationWorld'>,
  deps: TileTrafficDeps,
): TileTraffic {
  const now = deps.now ?? (() => performance.now());
  const setTimer = deps.setTimer ?? ((callback, ms) => setInterval(callback, ms));
  const clearTimer = deps.clearTimer ?? ((handle) => clearInterval(handle as ReturnType<typeof setInterval>));
  let layer: import('@exulanica/atlas-react/traffic').TrafficLayer | null = null;
  let stopped = false;
  let reading: AbortController | null = null;
  let refused = false;
  let retryAtMs = 0;
  let backoffMs = 0;
  let vehicles = 0;
  let signals = 0;
  let clockSecond: number | null = null;
  let state: TileTrafficState['state'] = 'starting';
  let reason: string | null = null;

  const report = (): void => {
    deps.report?.({
      state,
      vehicles,
      drawn: layer?.drawnCount ?? 0,
      hidden: layer?.hidden ?? 0,
      signals,
      lightsLit: layer?.lightsLit ?? 0,
      clockSecond,
      crossingsFed: false,
      reason,
    });
  };

  // A redraw in another pack hands the layer that pack's bodies; a layer not made yet asks for them
  // when it is made.
  const unsubscribe = deps.bodiesChanged?.(() => layer?.setBodies(deps.bodies?.() ?? null)) ?? null;

  const ready = (async () => {
    const [{ TrafficLayer }, { tileToRenderer }] = await Promise.all([
      import('@exulanica/atlas-react/traffic'),
      import('@exulanica/atlas-react/generated-tile'),
    ]);
    if (stopped) return;
    const surface = tile.navigationWorld.surface;
    layer = new TrafficLayer(
      host.environmentRoot,
      (xMm, yMm) => {
        const [x, , z] = tileToRenderer(xMm, yMm, 0);
        return surface.sample(x, z)?.height ?? null;
      },
      tileToRenderer,
      deps.bodies?.() ?? null,
    );
  })();

  async function read(fromSecond: number | null): Promise<void> {
    const abort = new AbortController();
    reading = abort;
    try {
      const answer = await deps.reader.window(fromSecond, WINDOW_SECONDS, abort.signal);
      if (stopped || layer === null) return;
      layer.setWindow(answer.window, now());
      vehicles = answer.window.vehicles.length;
      signals = answer.window.signals.length;
      clockSecond = answer.window.clockSecond;
      state = 'driving';
      reason = null;
      backoffMs = 0;
    } catch (error) {
      if (stopped) return;
      if (fromSecond !== null && error instanceof ApiError && error.code === 'traffic_second_out_of_range') {
        await read(null);
        return;
      }
      reason = error instanceof ApiError ? error.code : error instanceof Error ? error.message : String(error);
      if (lasting(error)) {
        refused = true;
        state = 'refused';
      } else {
        state = 'retrying';
        backoffMs = Math.min(MAX_BACKOFF_MS, backoffMs === 0 ? POLL_MS : backoffMs * 2);
        retryAtMs = now() + backoffMs;
      }
    } finally {
      if (reading === abort) reading = null;
      report();
    }
  }

  async function poll(): Promise<void> {
    await ready;
    if (stopped || reading !== null || refused || layer === null || now() < retryAtMs) return;
    const next = layer.nextSecond;
    const at = layer.secondAt(now());
    if (next !== null && at !== null && (next - at) * 1000 >= AHEAD_MS) return;
    await read(next === null || at === null || next < Math.floor(at) ? null : next);
  }

  const onUpdate = (): void => {
    layer?.update(now());
  };
  host.app.on('update', onUpdate);
  const timer = setTimer(() => void poll(), POLL_MS);
  void poll();
  report();

  return {
    get animating() {
      return layer?.animating ?? false;
    },
    stop() {
      stopped = true;
      unsubscribe?.();
      clearTimer(timer);
      reading?.abort();
      host.app.off('update', onUpdate);
      layer?.destroy();
      layer = null;
    },
  };
}
