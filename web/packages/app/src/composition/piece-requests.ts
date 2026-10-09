/**
 * New pieces of a world's look, after the person said yes to them in a Companion plan (GEN's G4):
 * while any piece request the plan made is still waiting, one line in the status place says so and
 * whether the piece maker is running; when a request's new pieces are taken into the world's look, a
 * notice says what arrived and offers Take back; when they are not, it says why in words; pieces
 * taken back are said nothing about. The world's requests are read every 15 s while any is open
 * (`GET /world/piece-requests?world_id=`), and never once none is.
 */

import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';
import type { ToastStack } from '../ui/system/components.js';

/** One piece request as the world's list states it, in the page's words. */
export interface PieceRequestView {
  readonly id: string;
  /** The thing's kind as the kind catalog labels it, or null for a kind no longer shipped. */
  readonly label: string | null;
  /** `requested` and `queued` wait; the rest are ends. */
  readonly state: string;
  /** What became of the pieces in the look, once the look was asked to take them, or null. */
  readonly lookStep: { readonly kind: string; readonly reason: string | null } | null;
}

export interface PieceRequestsRead {
  readonly requests: readonly PieceRequestView[];
  /** Whether the piece maker runs now, and until when. */
  readonly session: { readonly state: 'running' | 'off'; readonly until: string | null };
}

const OPEN_STATES: ReadonlySet<string> = new Set(['requested', 'queued']);
const ENDED_STATES: ReadonlySet<string> = new Set(['failed', 'cancelled']);
export const PIECE_POLL_MS = 15_000;

const record = (value: unknown): Record<string, unknown> =>
  (value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {});

export function parsePieceRequests(value: unknown): PieceRequestsRead {
  const body = record(value);
  const rows = Array.isArray(body['piece_requests']) ? body['piece_requests'] : [];
  const session = record(body['session']);
  return {
    requests: rows.flatMap((row) => {
      const request = record(row);
      const id = request['piece_request_id'];
      if (typeof id !== 'string') return [];
      const kind = record(request['kind']);
      const step = request['look_step'] === null || request['look_step'] === undefined ? null : record(request['look_step']);
      return [{
        id,
        label: typeof kind['label'] === 'string' ? kind['label'] : null,
        state: typeof request['state'] === 'string' ? request['state'] : 'requested',
        lookStep: step === null || typeof step['kind'] !== 'string' ? null
          : { kind: step['kind'], reason: typeof step['reason'] === 'string' ? step['reason'] : null },
      }];
    }),
    session: {
      state: session['state'] === 'running' ? 'running' : 'off',
      until: typeof session['until'] === 'string' ? session['until'] : null,
    },
  };
}

/** The world's piece requests, and taking a request's pieces back out of its look. */
export class PieceRequestsClient {
  readonly #transport: Transport;
  readonly #worldId: string;

  constructor(options: TransportOptions & { readonly worldId: string }) {
    this.#transport = new Transport(options);
    this.#worldId = options.worldId;
  }

  async list(): Promise<PieceRequestsRead> {
    return parsePieceRequests(await this.#transport.getJson<unknown>('/world/piece-requests', { world_id: this.#worldId }));
  }

  async takeBack(id: string): Promise<void> {
    await this.#transport.postJson<unknown>(`/world/piece-requests/${encodeURIComponent(id)}/take-back`, {});
  }
}

/** Why new pieces were not taken into the look, by the look step's reason. */
export const NOT_APPLIED_WORDS: Readonly<Record<string, string>> = Object.freeze({
  look_changed: 'the world\'s look changed while they were made',
  no_piece_within: 'none of them fitted the size the thing has',
  replaced: 'newer pieces replaced them',
  look_refused: 'the look did not take them',
  look_check_failed: 'they did not pass the look\'s checks',
  look_not_ready: 'the look was not ready for them',
  look_write_busy: 'the look was being changed by something else',
  look_chain_full: 'the look holds as many versions as it may',
});

const thing = (label: string | null): string => (label === null ? 'a thing' : `the ${label}`);
const listed = (labels: readonly string[]): string =>
  (labels.length <= 1 ? labels[0] ?? 'some things' : `${labels.slice(0, -1).join(', ')} and ${labels.at(-1)}`);

/** The waiting line: what is being made, and whether the piece maker runs and until when. */
export function waitingWords(open: readonly PieceRequestView[], session: PieceRequestsRead['session']): string {
  const labels = [...new Set(open.map((request) => thing(request.label)))];
  const until = session.until === null ? null : new Date(session.until);
  const when = session.state === 'running'
    ? (until === null || Number.isNaN(until.getTime()) ? 'The piece maker is running.'
      : `The piece maker runs until ${until.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.`)
    : 'Waiting for the piece maker to start.';
  return `Making new pieces for ${listed(labels)}. ${when}`;
}

/**
 * Watch the requests a plan made until each has an outcome: hold the waiting line while any waits,
 * then say each outcome once. Returns the stop.
 */
export function watchPieceRequests(deps: {
  readonly ids: readonly string[];
  readonly client: Pick<PieceRequestsClient, 'list' | 'takeBack'>;
  readonly hold: (words: string | null) => void;
  readonly toasts: Pick<ToastStack, 'show'> | null;
  /** Run `tick` every `ms`; returns the stop. Tests pass their own. */
  readonly every?: (tick: () => void, ms: number) => () => void;
}): () => void {
  const asked = new Set(deps.ids);
  const told = new Set<string>();
  const every = deps.every ?? ((tick: () => void, ms: number) => {
    const timer = window.setInterval(tick, ms);
    return () => window.clearInterval(timer);
  });
  let stopped = false;
  let stopTimer: (() => void) | null = null;
  const stop = (): void => {
    if (stopped) return;
    stopped = true;
    stopTimer?.();
    deps.hold(null);
  };
  const takeBack = (request: PieceRequestView): void => {
    void deps.client.takeBack(request.id).then(
      () => deps.toasts?.show({ message: `Taken back: ${thing(request.label)} looks as it did before.`, tone: 'info' }),
      (error: unknown) => deps.toasts?.show({
        message: error instanceof ApiError && error.code === 'piece_not_taken_in'
          ? `The pieces for ${thing(request.label)} were not in the look, so nothing was taken back.`
          : `The pieces for ${thing(request.label)} could not be taken back. Try again.`,
        tone: 'caution',
      }),
    );
  };
  const tell = (request: PieceRequestView): void => {
    if (told.has(request.id)) return;
    if (request.lookStep?.kind === 'applied') {
      told.add(request.id);
      deps.toasts?.show({
        message: `New pieces arrived for ${thing(request.label)}.`, tone: 'positive', durationMs: null,
        action: { label: 'Take back', run: () => takeBack(request) },
      });
    } else if (request.lookStep?.kind === 'not_applied') {
      told.add(request.id);
      const why = request.lookStep.reason === null ? undefined : NOT_APPLIED_WORDS[request.lookStep.reason];
      deps.toasts?.show({ message: `The new pieces for ${thing(request.label)} were not used${why === undefined ? '' : `: ${why}`}.`, tone: 'caution' });
    } else if (request.lookStep !== null) {
      // Taken back (or asked to be): said nothing about, as the person chose it.
      told.add(request.id);
    } else if (ENDED_STATES.has(request.state)) {
      told.add(request.id);
      deps.toasts?.show({ message: `The piece maker could not make the pieces for ${thing(request.label)}.`, tone: 'caution' });
    }
  };
  const read = async (): Promise<void> => {
    if (stopped) return;
    let answer: PieceRequestsRead;
    try {
      answer = await deps.client.list();
    } catch {
      return;
    }
    if (stopped) return;
    const mine = answer.requests.filter((request) => asked.has(request.id));
    for (const request of mine) tell(request);
    const waiting = mine.filter((request) => !told.has(request.id));
    if (waiting.length === 0) { stop(); return; }
    const open = waiting.filter((request) => OPEN_STATES.has(request.state));
    deps.hold(waitingWords(open.length === 0 ? waiting : open, answer.session));
  };
  stopTimer = every(() => { void read(); }, PIECE_POLL_MS);
  void read();
  return stop;
}
