import { describe, expect, it } from 'vitest';
import type { StageEvent } from '../src/events.js';
import type { StreamFetch, StreamResponse } from '../src/http-source.js';
import { HttpFormationEventSource, parseFrame } from '../src/http-source.js';
import type { StreamState } from '../src/state.js';

/**
 * The transport, driven by a function that returns bytes.
 *
 * No server and no network anywhere in this file, which is the point of the fetch being injected.
 * A transport test that needed a running API would be one nobody runs, and the properties under
 * test are all about what happens when the bytes stop or arrive in the wrong shape, which is
 * awkward to arrange against a real server and trivial here.
 */

const encoder = new TextEncoder();

function frameOf(event: Partial<StageEvent> & { eventId: string }): string {
  const full = {
    captureId: 'batch-1',
    phase: 'media_extraction',
    stageIndex: 1,
    at: 1_700_000_000_000,
    ...event,
  };
  return `id: ${full.eventId}\ndata: ${JSON.stringify(full)}\n\n`;
}

/** A response whose body yields the given chunks, then ends. */
function responseOf(...chunks: string[]): StreamResponse {
  let index = 0;
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () =>
          index < chunks.length
            ? { done: false, value: encoder.encode(chunks[index++]!) }
            : { done: true },
        cancel: async () => undefined,
      }),
    },
  };
}

function collect(fetch: StreamFetch, from: string | null = null, token = 'secret-token') {
  const events: StageEvent[] = [];
  const states: StreamState[] = [];
  const source = new HttpFormationEventSource({
    baseUrl: '/api',
    token,
    fetch,
    retryMs: 1,
    // Retries are scheduled through an injected function that runs nothing, so a test never waits
    // and a test that expects no retry cannot pass by being fast.
    schedule: () => () => undefined,
  });
  const stop = source.subscribe('batch-1', from, (e) => events.push(e), (s) => states.push(s));
  return { events, states, stop };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('the formation transport', () => {
  it('sends the token in a header and never in the url', async () => {
    let seen: { url: string; headers: Record<string, string>; credentials: string } | null = null;
    const { stop } = collect(async (url, init) => {
      seen = { url, headers: { ...init.headers }, credentials: init.credentials };
      return responseOf();
    });
    await flush();
    stop();

    expect(seen!.headers['authorization']).toBe('Bearer secret-token');
    expect(seen!.url).not.toContain('secret-token');
    expect(seen!.headers['accept']).toBe('text/event-stream');
    expect(seen!.credentials).toBe('include');
  });

  it('uses the account cookie without sending an empty bearer credential', async () => {
    let seen: { headers: Record<string, string>; credentials: string } | null = null;
    const { stop } = collect(async (_url, init) => {
      seen = { headers: { ...init.headers }, credentials: init.credentials };
      return responseOf();
    }, null, '');
    await flush();
    stop();

    expect(seen!.headers).toEqual({ accept: 'text/event-stream' });
    expect(seen!.credentials).toBe('include');
  });

  it('resumes from the token the reducer last saw', async () => {
    let seen = '';
    const { stop } = collect(async (url) => {
      seen = url;
      return responseOf();
    }, 'event-42');
    await flush();
    stop();
    expect(seen).toContain('since=event-42');
  });

  it('reads events out of a stream that arrives in the wrong-sized pieces', async () => {
    // A frame split across two chunks is the normal case on a real connection, and half a JSON
    // document is not a smaller event.
    const whole = frameOf({ eventId: 'a' }) + frameOf({ eventId: 'b' });
    const cut = Math.floor(whole.length / 3);
    const { events, stop } = collect(async () =>
      responseOf(whole.slice(0, cut), whole.slice(cut)),
    );
    await flush();
    stop();
    expect(events.map((e) => e.eventId)).toEqual(['a', 'b']);
  });

  it('ignores a comment heartbeat rather than handing it to the reducer', async () => {
    const { events, stop } = collect(async () =>
      responseOf(': keep-alive\n\n', frameOf({ eventId: 'a' })),
    );
    await flush();
    stop();
    expect(events.map((e) => e.eventId)).toEqual(['a']);
  });

  it('drops a frame that would render a dishonest display, and keeps the last good state', async () => {
    // A negative counter is a pipeline bug. Repairing it here would put a plausible display over
    // the fault, so the frame is dropped and the previous state stays on screen.
    const bad = `data: ${JSON.stringify({
      eventId: 'bad',
      captureId: 'batch-1',
      phase: 'media_extraction',
      stageIndex: 1,
      at: 1,
      counters: { done: -3, total: null },
    })}\n\n`;
    const { events, stop } = collect(async () => responseOf(frameOf({ eventId: 'a' }), bad));
    await flush();
    stop();
    expect(events.map((e) => e.eventId)).toEqual(['a']);
  });

  it('reports a refused connection as lost rather than as a finished pipeline', async () => {
    const { states, stop } = collect(async () => ({ ok: false, status: 503, body: null }));
    await flush();
    stop();
    expect(states).toContain('lost');
  });

  it('reports a stream that ends normally as live, not as lost', async () => {
    // The server closes after a terminal event. A reconnecting spinner over a finished region
    // would be reporting a connection problem that is not one.
    const { states, stop } = collect(async () => responseOf(frameOf({ eventId: 'a' })));
    await flush();
    stop();
    expect(states.at(-1)).toBe('live');
    expect(states).not.toContain('lost');
  });

  it('stops when unsubscribed', async () => {
    let calls = 0;
    const { stop } = collect(async () => {
      calls += 1;
      throw new Error('down');
    });
    stop();
    await flush();
    expect(calls).toBeLessThanOrEqual(1);
  });
});

describe('one frame', () => {
  it('reads a data line', () => {
    expect(parseFrame(frameOf({ eventId: 'a' }).trimEnd())?.eventId).toBe('a');
  });

  it('is null for a comment', () => {
    expect(parseFrame(': keep-alive')).toBeNull();
  });

  it('is null for something that is not JSON', () => {
    expect(parseFrame('data: <html>a proxy said no</html>')).toBeNull();
  });
});
