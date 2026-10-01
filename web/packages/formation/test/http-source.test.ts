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

/** A batch's terminal event: an outcome, which sorts after every stage. */
function terminalFrame(eventId: string): string {
  return frameOf({
    eventId,
    phase: 'ready',
    stageIndex: 6,
    outcome: { rung: 4, openQuestions: 0, photographsAvailable: 1 },
  });
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

  it('reports a stream that ends after its outcome as live, not as lost', async () => {
    // The server closes after a terminal event. A reconnecting spinner over a finished region
    // would be reporting a connection problem that is not one.
    const { states, stop } = collect(async () =>
      responseOf(frameOf({ eventId: 'a' }), terminalFrame('batch:batch-1:succeeded')),
    );
    await flush();
    stop();
    expect(states.at(-1)).toBe('live');
    expect(states).not.toContain('lost');
  });

  it('resumes from the last token when a stream ends without an outcome', async () => {
    // The server ends a stream at its time cap, or after polls it could not make, with the
    // pipeline still running; the client picks it up where it left off.
    const urls: string[] = [];
    const waits: number[] = [];
    const responses = [
      responseOf(frameOf({ eventId: 'a' })),
      responseOf(terminalFrame('batch:batch-1:ready')),
    ];
    const source = new HttpFormationEventSource({
      baseUrl: '/api',
      token: 'secret-token',
      fetch: async (url) => {
        urls.push(url);
        return responses.shift()!;
      },
      retryMs: 1,
      schedule: (run, ms) => {
        waits.push(ms);
        run();
        return () => undefined;
      },
    });
    const events: StageEvent[] = [];
    const stop = source.subscribe('batch-1', null, (e) => events.push(e), () => undefined);
    await flush();
    await flush();
    stop();
    expect(urls).toHaveLength(2);
    expect(urls[1]).toContain('since=a');
    expect(events.map((e) => e.eventId)).toEqual(['a', 'batch:batch-1:ready']);
    expect(waits).toHaveLength(1);
  });

  it('does not reconnect a subscription resumed from its terminal event', async () => {
    let calls = 0;
    const { states, stop } = collect(async () => {
      calls += 1;
      return responseOf();
    }, 'batch:batch-1:succeeded');
    await flush();
    stop();
    expect(calls).toBe(1);
    expect(states).not.toContain('lost');
  });

  it('stops on a refusal that sending again cannot change', async () => {
    let calls = 0;
    let scheduled = 0;
    const source = new HttpFormationEventSource({
      baseUrl: '/api',
      token: 'secret-token',
      fetch: async () => {
        calls += 1;
        return { ok: false, status: 422, body: null };
      },
      schedule: () => {
        scheduled += 1;
        return () => undefined;
      },
    });
    const states: StreamState[] = [];
    const stop = source.subscribe('batch-1', 'not-a-token', () => undefined, (s) => states.push(s));
    await flush();
    stop();
    expect(calls).toBe(1);
    expect(scheduled).toBe(0);
    expect(states.at(-1)).toBe('lost');
  });

  it('waits at least as long as the server asks before trying again', async () => {
    const waits: number[] = [];
    const source = new HttpFormationEventSource({
      baseUrl: '/api',
      token: 'secret-token',
      fetch: async () => ({
        ok: false,
        status: 503,
        body: null,
        headers: { get: (name: string) => (name === 'retry-after' ? '7' : null) },
      }),
      retryMs: 1,
      schedule: (_run, ms) => {
        waits.push(ms);
        return () => undefined;
      },
    });
    const stop = source.subscribe('batch-1', null, () => undefined, () => undefined);
    await flush();
    stop();
    expect(waits).toEqual([7000]);
  });

  it('retries a momentary conflict with backoff, waiting at least as long as asked', async () => {
    // The server answers 409 busy on any route for a transient database conflict, with a
    // Retry-After. It is the only 409 this route gives, and a later attempt gets past it.
    const waits: number[] = [];
    const busy = (retryAfter: string | null): StreamResponse => ({
      ok: false,
      status: 409,
      body: null,
      headers: { get: (name: string) => (name === 'retry-after' ? retryAfter : null) },
    });
    const responses = [busy('1'), busy(null), responseOf(terminalFrame('batch:batch-1:ready'))];
    let calls = 0;
    const source = new HttpFormationEventSource({
      baseUrl: '/api',
      token: 'secret-token',
      fetch: async () => {
        calls += 1;
        return responses.shift()!;
      },
      retryMs: 100,
      schedule: (run, ms) => {
        waits.push(ms);
        run();
        return () => undefined;
      },
    });
    const events: StageEvent[] = [];
    const states: StreamState[] = [];
    const stop = source.subscribe('batch-1', null, (e) => events.push(e), (s) => states.push(s));
    await flush();
    await flush();
    await flush();
    stop();
    expect(calls).toBe(3);
    expect(waits).toEqual([1000, 200]);
    expect(events.map((e) => e.eventId)).toEqual(['batch:batch-1:ready']);
    expect(states.at(-1)).toBe('live');
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
