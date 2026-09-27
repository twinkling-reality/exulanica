/**
 * Keep a saved world's flight drawn: read its windows ahead of the flight's clock and hand them to
 * the renderer, which draws them and computes nothing.
 *
 * The flight keeps shared real time. The first read names no step: the server answers from its
 * clock's step and says where its clock was, and the page's copy of the clock starts there
 * (`FlightFlock`), so every page shows a world's birds in the same places at the same moment. While
 * the world is open, a window is read whenever less than `AHEAD_MS` of served steps is left ahead
 * of the clock, from where the served steps end, or from the clock when it has passed them (a page
 * left in the background); each kind's reviewed body and wing are fetched once, digest-verified,
 * before its flyers are drawn. A window whose input digest differs from the one being drawn is a
 * changed world, and its flight is drawn from the clock again.
 *
 * The page's clock follows the served one: every window it reads sets the page's clock again when
 * the two have drifted apart, and a read the server refuses as too far from its clock
 * (`flight_step_out_of_range`), as after a sleep that stopped the page's own clock, is read again
 * from the clock rather than taken as a refusal.
 *
 * An edit made on this page restarts the flight at once: a read in flight is aborted, and an answer
 * that arrives from before the edit is never drawn; the flyers are not drawn until the edited
 * world's first window arrives, because the old flight may cross whatever the edit put in its way.
 *
 * A kind whose parts are not in storage is named in the status and not drawn; nothing stands in
 * for it. A refusal the server will keep giving for this world as it stands (a 409: too many flyers,
 * a world it cannot place or too large to fly over; a 422: a window it will not serve, other than
 * one too far from the flight's clock, which is read again from the clock) or an answer
 * this client cannot read stops the reading until the world is edited, and the status names it in
 * words a person reads. Any other failure, among them a lapsed sign-in the page's session renews
 * (401), too many requests (429) and a server failure (5xx), is tried again later and later, up to
 * `MAX_BACKOFF_MS` apart. Stopping aborts a read in flight.
 */

import { islandId } from '@exulanica/atlas-core';
import {
  fetchVerifiedObjectAsset,
  type AtlasBinding,
  type FlightKindLook,
} from '@exulanica/atlas-react/playcanvas';
import { ApiError } from '@exulanica/graph-client';
import {
  FlightClient,
  FlightContractError,
  type FlightKindAsset,
  type FlightRead,
  type FlightUnplaced,
} from '../flight-api.js';

/** Served steps kept ahead of the page's clock before the next window is read: half a minute. */
export const AHEAD_MS = 30_000;
/** How often the page asks whether a window is due. */
export const POLL_MS = 5_000;
/** Steps a window asks for: the module's largest window, one simulated minute. */
export const WINDOW_STEPS = 600;
/** The longest wait between tries after a failure the server may not repeat. */
export const MAX_BACKOFF_MS = 60_000;

export interface SavedWorldFlightStatus {
  /** `flying` while windows arrive, `retrying` after a passing failure, `refused` when stopped by one. */
  readonly state: 'starting' | 'flying' | 'retrying' | 'refused';
  readonly flyers: number;
  readonly unplaced: readonly FlightUnplaced[];
  /** Kinds whose reviewed parts could not be drawn, each with the reason. */
  readonly undrawnKinds: readonly string[];
  readonly lateHome: number;
  readonly failure: string | null;
  /** While refused, one line a person reads naming why; otherwise null. */
  readonly refusalWords: string | null;
}

/** The statuses whose refusal the server keeps giving for a world until it is edited. */
const LASTING_STATUSES: ReadonlySet<number> = new Set([409, 422]);

/** Why a flight is refused, in words, by the server's refusal code. */
const REFUSAL_WORDS: Readonly<Record<string, string>> = {
  too_many_flyers: "this world's objects would host more flyers than one world may hold",
  flight_world_too_large: 'this world is too large to fly over',
  flight_unavailable: 'something in this world cannot be placed for flight',
  invalid_flight_kind: 'a kind of flyer is not stated correctly in its catalog',
  invalid_flight_input: "the server could not put this world's flight together",
  flight_state_mismatch: "the server could not put this world's flight together",
  flight_step_out_of_range: "this page asked for flight too far from the present moment; open the world again",
  flight_window_too_long: 'this page asked for more flight at once than the server serves',
};

/** The line a person reads when a flight is refused: why, in words, never a bare code. */
export function flightRefusalWords(error: unknown): string {
  if (error instanceof FlightContractError) return 'Flight stopped: this page cannot read the flight the server sent.';
  const code = error instanceof ApiError ? error.code : '';
  const words = REFUSAL_WORDS[code] ?? `the server refused it${code ? ` (${code})` : ''}`;
  return `Flight stopped: ${words}.`;
}

export interface SavedWorldFlightDeps {
  readonly credentials: { readonly baseUrl: string; readonly token: string; readonly csrfToken?: string };
  readonly worldId: string;
  readonly versionId: string;
  /** The authored region the flyers are drawn over, whose island the verified fetch names. */
  readonly regionId: string;
  readonly binding: () => AtlasBinding | null;
  readonly now?: () => number;
  readonly client?: Pick<FlightClient, 'window'>;
  readonly loadBytes?: (asset: FlightKindAsset) => Promise<ArrayBuffer>;
  readonly onStatus?: (status: SavedWorldFlightStatus) => void;
  readonly setInterval?: typeof globalThis.setInterval;
  readonly clearInterval?: typeof globalThis.clearInterval;
}

export interface SavedWorldFlight {
  /** Read the first window now, then keep reading ahead until stopped. */
  start(): Promise<void>;
  /** Read the next window if one is due. Called on the poll, and by a test directly. */
  poll(): Promise<void>;
  /** The world was edited: abort any read, draw none of the old flight, read the new one now. */
  restart(): Promise<void>;
  stop(): void;
  readonly status: SavedWorldFlightStatus;
}

export function createSavedWorldFlight(deps: SavedWorldFlightDeps): SavedWorldFlight {
  const now = deps.now ?? (() => performance.now());
  const abort = new AbortController();
  const client = deps.client
    ?? new FlightClient({ ...deps.credentials, worldId: deps.worldId, signal: abort.signal });
  const setTimer = deps.setInterval ?? globalThis.setInterval.bind(globalThis);
  const clearTimer = deps.clearInterval ?? globalThis.clearInterval.bind(globalThis);
  const loaded = new Set<string>();
  const undrawn = new Map<string, string>();
  let drawing: string | null = null;
  /** The step length of the flight being drawn, in milliseconds, from its latest window. */
  let stepMs = 0;
  let timer: ReturnType<typeof globalThis.setInterval> | null = null;
  /** Counts the edits this page has made; a read begun before the latest one is stale. */
  let epoch = 0;
  /** The read in flight, the edit count it began under, and what aborts it. */
  let inFlight: { readonly epoch: number; readonly abort: AbortController } | null = null;
  let stopped = false;
  /** Set by a refusal the server will keep giving: nothing is read again until an edit. */
  let refused = false;
  /** After a passing failure, how long to wait before the next try, and when that is. */
  let backoffMs = 0;
  let retryAtMs = 0;
  let status: SavedWorldFlightStatus = Object.freeze({
    state: 'starting', flyers: 0, unplaced: [], undrawnKinds: [], lateHome: 0, failure: null,
    refusalWords: null,
  });

  function report(
    read: FlightRead | null,
    failure: string | null,
    state: SavedWorldFlightStatus['state'],
    refusalWords: string | null = null,
  ): void {
    status = Object.freeze({
      state,
      flyers: read?.window.flyers.length ?? status.flyers,
      unplaced: read?.unplaced ?? status.unplaced,
      undrawnKinds: Object.freeze([...undrawn].map(([key, why]) => `${key}: ${why}`)),
      lateHome: status.lateHome + (read?.lateHome ?? 0),
      failure,
      refusalWords,
    });
    deps.onStatus?.(status);
  }

  /** Whether a failure is one the server will keep giving for this world as it stands. */
  function lasting(error: unknown): boolean {
    return error instanceof FlightContractError
      || (error instanceof ApiError && LASTING_STATUSES.has(error.status));
  }

  function bytesOf(asset: FlightKindAsset): Promise<ArrayBuffer> {
    if (deps.loadBytes !== undefined) return deps.loadBytes(asset);
    return fetchVerifiedObjectAsset(
      islandId(deps.regionId),
      {
        assetKey: asset.assetKey,
        mediaType: asset.mediaType ?? '',
        contentSha256: asset.contentSha256 ?? '',
        byteSize: asset.byteSize ?? 0,
      },
      abort.signal,
      deps.credentials,
    );
  }

  async function load(read: FlightRead): Promise<void> {
    const binding = deps.binding();
    const society = binding?.authoredSociety ?? null;
    if (binding === null || society === null) return;
    for (const kind of read.kinds) {
      const look: FlightKindLook = kind.look;
      if (loaded.has(look.key) || undrawn.has(look.key)) continue;
      const missing = [kind.body, kind.wing].find((part) => part.availability !== 'available');
      if (missing !== undefined) {
        undrawn.set(look.key, `${missing.assetKey} is ${missing.availability}`);
        continue;
      }
      try {
        const [body, wing] = await Promise.all([bytesOf(kind.body), bytesOf(kind.wing)]);
        if (stopped) return;
        await society.setFlightKind(
          binding.app,
          look,
          { assetKey: kind.body.assetKey, bytes: body },
          { assetKey: kind.wing.assetKey, bytes: wing },
        );
        loaded.add(look.key);
      } catch (error) {
        undrawn.set(look.key, error instanceof Error ? error.message : String(error));
      }
    }
  }

  /** Whether a read is not to be drawn: the page stopped, or an edit came after the read began. */
  function stale(mine: { readonly epoch: number }): boolean {
    return stopped || mine.epoch !== epoch;
  }

  async function read(fromStep: number | null, mine: { readonly epoch: number; readonly abort: AbortController }): Promise<void> {
    let answer: FlightRead;
    try {
      answer = await client.window(deps.versionId, fromStep, WINDOW_STEPS, mine.abort.signal);
    } catch (error) {
      // A step too far from the flight's clock: the page's own clock stopped, as in a sleep, while
      // the shared one did not. Read from the clock; the answer sets the page's clock again.
      if (fromStep === null || !(error instanceof ApiError) || error.code !== 'flight_step_out_of_range') throw error;
      await read(null, mine);
      return;
    }
    if (stale(mine)) return;
    const society = deps.binding()?.authoredSociety ?? null;
    if (society === null) return;
    if (drawing !== null && answer.window.inputSha256 !== drawing && fromStep !== null) {
      // The world changed since the last window: draw its new flight from the clock.
      drawing = null;
      society.clearFlight();
      await read(null, mine);
      return;
    }
    await load(answer);
    if (stale(mine)) return;
    society.setFlight(answer.window, now());
    drawing = answer.window.inputSha256;
    stepMs = answer.window.stepMs;
    backoffMs = 0;
    report(answer, null, 'flying');
    deps.binding()?.invalidate();
  }

  async function poll(): Promise<void> {
    if (stopped || (inFlight !== null && inFlight.epoch === epoch)) return;
    const society = deps.binding()?.authoredSociety ?? null;
    if (society === null) return;
    if (refused || now() < retryAtMs) return;
    const next = society.flightNextStep;
    const at = society.flightStepAt(now());
    // A window is due when less than AHEAD_MS of served steps is left ahead of the clock.
    if (drawing !== null && next !== null && at !== null && (next - at) * stepMs >= AHEAD_MS) return;
    // From where the served steps end, unless the clock has passed them: then from the clock.
    const from = drawing === null || next === null || at === null || next < Math.floor(at) ? null : next;
    const mine = { epoch, abort: new AbortController() };
    inFlight = mine;
    try {
      await read(from, mine);
    } catch (error) {
      if (!stale(mine)) {
        const message = error instanceof ApiError ? error.code : error instanceof Error ? error.message : String(error);
        if (lasting(error)) {
          refused = true;
          report(null, message, 'refused', flightRefusalWords(error));
        } else {
          backoffMs = Math.min(MAX_BACKOFF_MS, backoffMs === 0 ? POLL_MS : backoffMs * 2);
          retryAtMs = now() + backoffMs;
          report(null, message, 'retrying');
        }
      }
    } finally {
      if (inFlight === mine) inFlight = null;
    }
  }

  return {
    async start(): Promise<void> {
      await poll();
      if (!stopped) timer = setTimer(() => { void poll(); }, POLL_MS);
    },
    poll,
    async restart(): Promise<void> {
      // Whatever was being read describes the world before the edit: abort it, draw nothing of
      // the old flight, and read the edited world's flight from the clock now.
      epoch += 1;
      inFlight?.abort.abort();
      inFlight = null;
      refused = false;
      backoffMs = 0;
      retryAtMs = 0;
      drawing = null;
      deps.binding()?.authoredSociety?.clearFlight();
      await poll();
    },
    stop(): void {
      stopped = true;
      inFlight?.abort.abort();
      abort.abort();
      if (timer !== null) clearTimer(timer);
      timer = null;
      deps.binding()?.authoredSociety?.clearFlight();
    },
    get status() {
      return status;
    },
  };
}
