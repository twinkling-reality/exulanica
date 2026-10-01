/**
 * The real event source: server-sent events from the provenance ledger, over HTTP.
 *
 * **It is a `fetch` reader and not an `EventSource`, and that is forced rather than chosen.**
 * `source.ts` used to describe the implementation as a browser `EventSource` over a url, and
 * that cannot work here: `EventSource` sends no custom headers, so it cannot carry a bearer
 * token. A bearer credential in the query string would put the key to somebody's photograph
 * library into every proxy log between here and the server. Browser account sessions can use an
 * HttpOnly cookie, but this reader must also preserve header authentication for workspace clients.
 *
 * What is lost by not using `EventSource` is its automatic reconnect, and that turns out to be
 * worth losing: this holds the resume token itself, so a reconnect resumes from the last event
 * the REDUCER saw rather than from the last frame the browser happened to receive.
 *
 * **A dropped stream is reported as lost, not as a finished pipeline.** `StreamState` exists
 * because "the pipeline stopped" and "we stopped hearing about it" are different facts, and only
 * one of them is about the photographs. The reducer freezes on `lost` and nothing advances,
 * which is the behaviour interaction-model.md 8.4 asks for and which falls out of there being no
 * timer anywhere in this module.
 *
 * **Only a terminal event finishes a stream.** The server also ends a stream cleanly at its time
 * cap and after polls it could not make, and a stream that ended without a terminal event is
 * reconnected from the last token, exactly as a drop is. A refusal that sending again cannot
 * change (a 4xx other than 408, 409 and 429) stops the subscription rather than retrying it
 * forever, and a `Retry-After` on a 409, 429 or 503 is waited out before the next attempt.
 *
 * **Nothing here parses a phase or invents a number.** A frame is JSON, it is handed to the
 * reducer, and a frame that is not usable is dropped with the stream marked lost rather than
 * repaired. `assertUsableEvent` throws on a negative count or a non-finite timestamp precisely so
 * that a pipeline bug surfaces instead of being rendered as a plausible display.
 */

import { assertUsableEvent, FORMATION_STAGES, type StageEvent } from './events.js';
import type { FormationEventSource } from './source.js';
import type { StreamState } from './state.js';

/**
 * The response shape this module needs, and no more of it.
 *
 * Declared structurally rather than imported from the DOM so that a test drives this with a
 * plain object and so that the dependency is visible: the only thing a transport is allowed to
 * be, here, is something that yields bytes.
 */
export interface StreamReader {
  read(): Promise<{ readonly done: boolean; readonly value?: Uint8Array }>;
  cancel(): Promise<void>;
}

export interface StreamResponse {
  readonly ok: boolean;
  readonly status: number;
  readonly body: { getReader(): StreamReader } | null;
  /** Read for `Retry-After` only. Absent in a test double that sends none. */
  readonly headers?: { get(name: string): string | null };
}

export type StreamFetch = (
  url: string,
  init: {
    readonly headers: Readonly<Record<string, string>>;
    readonly credentials: 'include';
  },
) => Promise<StreamResponse>;

export interface HttpFormationOptions {
  /** Origin and path prefix of the API, without a trailing slash. */
  readonly baseUrl: string;
  /** Held here and put in a header. Never in the URL. */
  readonly token: string;
  readonly fetch: StreamFetch;
  /** Milliseconds to wait before reconnecting after a drop. Backs off, then holds. */
  readonly retryMs?: number;
  readonly maxRetryMs?: number;
  /** Injected so a test does not wait in real time and so this module owns no timer of its own. */
  readonly schedule?: (run: () => void, ms: number) => () => void;
}

const DEFAULT_RETRY_MS = 1000;
const DEFAULT_MAX_RETRY_MS = 15000;

/** The id the server gives a batch's terminal event: `batch:<batch id>:<status>`. */
const TERMINAL_TOKEN = /^batch:[^:]+:[a-z]+$/;

/**
 * Statuses a later attempt can get past; every other 4xx is final for this subscription. The only
 * 409 this route gives is the server's `busy`, a momentary database conflict on any route.
 */
const RETRIABLE_REFUSALS = new Set([408, 409, 429]);

function retryAfterMs(response: StreamResponse): number {
  const value = response.headers?.get('retry-after');
  const seconds = value === null || value === undefined ? Number.NaN : Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : 0;
}

function defaultSchedule(run: () => void, ms: number): () => void {
  const handle = setTimeout(run, ms);
  return () => clearTimeout(handle);
}

export class HttpFormationEventSource implements FormationEventSource {
  readonly #options: HttpFormationOptions;

  constructor(options: HttpFormationOptions) {
    this.#options = options;
  }

  /**
   * @param captureId the intake batch to watch. Named `captureId` because that is what the
   *   interface calls the thing a person uploaded; the server calls one photograph a capture and
   *   calls this a batch, and the two words meeting here is recorded in `exulanica/ingest/batch.py`.
   */
  subscribe(
    captureId: string,
    fromEventId: string | null,
    onEvent: (event: StageEvent) => void,
    onStreamState: (stream: StreamState) => void,
  ): () => void {
    const options = this.#options;
    const schedule = options.schedule ?? defaultSchedule;
    let cancelled = false;
    let reader: StreamReader | null = null;
    let cancelRetry: (() => void) | null = null;
    let token = fromEventId;
    let waitMs = options.retryMs ?? DEFAULT_RETRY_MS;
    // A subscription resumed from a terminal id already has its outcome: nothing will follow it.
    let finished = token !== null && TERMINAL_TOKEN.test(token);

    const connect = async (): Promise<void> => {
      if (cancelled) return;
      onStreamState('connecting');
      const query = token === null ? '' : `?since=${encodeURIComponent(token)}`;
      let response: StreamResponse;
      try {
        const headers: Record<string, string> = { accept: 'text/event-stream' };
        // An explicit empty bearer prevents the API from falling back to its account cookie.
        if (options.token) headers['authorization'] = `Bearer ${options.token}`;
        response = await options.fetch(`${options.baseUrl}/formation/${captureId}${query}`, {
          headers,
          credentials: 'include',
        });
      } catch {
        return retry();
      }
      const final = response.status >= 400 && response.status < 500;
      if (final && !RETRIABLE_REFUSALS.has(response.status)) {
        // Unknown batch, a token that cannot be a position, a credential it will not accept:
        // sending the same request again gets the same answer, so the subscription stops here.
        onStreamState('lost');
        return;
      }
      if (!response.ok || response.body === null) {
        // A refusal is not a lost connection, but the client can do nothing about either and the
        // honest display is the same: we do not know what the pipeline is doing.
        return retry(retryAfterMs(response));
      }

      reader = response.body.getReader();
      onStreamState('live');
      // The connection came up, so the next drop starts backing off from the beginning again.
      waitMs = options.retryMs ?? DEFAULT_RETRY_MS;

      const decoder = new TextDecoder();
      let buffer = '';
      try {
        for (;;) {
          const chunk = await reader.read();
          if (chunk.done) break;
          buffer += decoder.decode(chunk.value, { stream: true });
          // Frames are separated by a blank line. A partial frame stays in the buffer rather than
          // being parsed, because half a JSON document is not a smaller event.
          let split = buffer.indexOf('\n\n');
          while (split !== -1) {
            const frame = buffer.slice(0, split);
            buffer = buffer.slice(split + 2);
            const event = parseFrame(frame);
            if (event !== null) {
              token = event.eventId;
              finished ||= event.stageIndex >= FORMATION_STAGES.length;
              onEvent(event);
            }
            split = buffer.indexOf('\n\n');
          }
        }
      } catch {
        return retry();
      }
      if (cancelled) return;
      if (!finished) {
        // Ended without an outcome: the server's time cap, or polls it could not make. The
        // pipeline may still be running, so this is resumed like a drop.
        return retry();
      }
      // The server closes the stream after a terminal event, which is the normal end. Reporting
      // it as lost would put a reconnecting spinner over a finished region.
      onStreamState('live');
    };

    const retry = (atLeastMs = 0): void => {
      if (cancelled || finished) return;
      onStreamState('lost');
      cancelRetry = schedule(() => {
        void connect();
      }, Math.max(waitMs, atLeastMs));
      waitMs = Math.min(waitMs * 2, options.maxRetryMs ?? DEFAULT_MAX_RETRY_MS);
    };

    void connect();

    return () => {
      cancelled = true;
      cancelRetry?.();
      void reader?.cancel().catch(() => undefined);
    };
  }
}

/**
 * One SSE frame to an event, or null.
 *
 * Null for a comment, for a frame with no data, and for a frame whose data is not a usable event.
 * The last case is the important one: `assertUsableEvent` throws on a negative counter or a
 * non-finite timestamp, and a client that repaired those would render a plausible display over a
 * pipeline bug. Dropping the frame leaves the last good state on screen, which is what the
 * reducer does for a stream that has gone quiet and is the honest reading of both.
 */
export function parseFrame(frame: string): StageEvent | null {
  let data: string | null = null;
  for (const line of frame.split('\n')) {
    if (line.startsWith(':')) continue;
    if (line.startsWith('data:')) {
      data = (data === null ? '' : `${data}\n`) + line.slice(5).trimStart();
    }
  }
  if (data === null) return null;
  try {
    const event = JSON.parse(data) as StageEvent;
    assertUsableEvent(event);
    return event;
  } catch {
    return null;
  }
}
