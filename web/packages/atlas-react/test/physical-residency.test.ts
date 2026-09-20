import { describe, expect, it, vi } from 'vitest';
import { islandId, type ResidencyAction } from '@exulanica/atlas-core';
import {
  PhysicalResidencyRuntime,
  fetchAuthenticatedAsset,
  type AssetBytes,
  type PhysicalAssetDescriptor,
  type PhysicalResidencyAdapter,
  type ResidencyPhysicalEvent,
} from '../src/playcanvas/physical-residency.js';

const id = islandId('region-a');
const descriptor = (availability: PhysicalAssetDescriptor['availability'] = 'available'):
PhysicalAssetDescriptor => ({
  islandId: id,
  stage: 'full',
  path: '/world/assets/artifact-a',
  availability,
  expectedSha256: null,
  expectedBytes: 4,
  fallback: 'proxy',
});
const load: ResidencyAction = {
  type: 'load',
  request: { requestId: 'request-1', islandId: id, from: 'stub', to: 'full' },
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function harness(fetchResult: Promise<AssetBytes> = Promise.resolve({
  bytes: new Uint8Array([1, 2, 3, 4]).buffer,
  rangeOutcome: 'partial',
  acceptRanges: true,
  contentRange: 'bytes 0-3/4',
})) {
  const events: ResidencyPhysicalEvent[] = [];
  const published: string[] = [];
  const disposedDecoded: string[] = [];
  const disposedUploaded: string[] = [];
  const settled: [string, boolean][] = [];
  const indexReasons: string[] = [];
  let failRestore = false;
  const adapter: PhysicalResidencyAdapter<string, string> = {
    fetch: vi.fn(() => fetchResult),
    decode: vi.fn(() => 'decoded'),
    upload: vi.fn(() => {
      if (failRestore) throw new Error('GPU remained unavailable');
      return 'uploaded';
    }),
    publish: (_island, stage) => published.push(stage),
    unpublish: vi.fn(),
    disposeDecoded: (value) => disposedDecoded.push(value),
    disposeUploaded: (value) => disposedUploaded.push(value),
    settle: (requestId, ok) => settled.push([requestId, ok]),
    onEvent: (event) => events.push(event),
    requireWorldIndex: (reason) => indexReasons.push(reason),
  };
  return {
    adapter, events, published, disposedDecoded, disposedUploaded, settled, indexReasons,
    failRestore: () => { failRestore = true; },
  };
}

describe('physical residency execution', () => {
  it('fetches, decodes, uploads, publishes, downgrades, and disposes in order', async () => {
    const values = harness();
    const runtime = new PhysicalResidencyRuntime([descriptor()], values.adapter);
    runtime.execute([load]);
    await runtime.whenIdle();
    expect(values.events.map((event) => event.state)).toEqual([
      'fetching', 'decoding', 'uploading', 'published',
    ]);
    expect(values.published).toEqual(['full']);
    expect(values.settled).toEqual([['request-1', true]]);

    runtime.execute([{ type: 'release', islandId: id, from: 'full', to: 'proxy' }]);
    expect(values.events.at(-1)?.state).toBe('released');
    expect(values.disposedDecoded).toEqual(['decoded']);
    expect(values.disposedUploaded).toEqual(['uploaded']);
  });

  it('never publishes a stale fetch even when the transport resolves after cancellation', async () => {
    const pending = deferred<AssetBytes>();
    const values = harness(pending.promise);
    const runtime = new PhysicalResidencyRuntime([descriptor()], values.adapter);
    runtime.execute([load]);
    runtime.execute([{ type: 'cancel', requestId: 'request-1', islandId: id }]);
    pending.resolve({
      bytes: new Uint8Array([1, 2, 3, 4]).buffer,
      rangeOutcome: 'ignored', acceptRanges: false, contentRange: null,
    });
    await runtime.whenIdle();
    expect(values.published).toEqual([]);
    expect(values.settled).toEqual([['request-1', false]]);
    expect(values.events.map((event) => event.state)).toContain('stale');
  });

  it('keeps missing, unavailable, unsupported, and deleted states distinct', () => {
    for (const availability of ['unavailable', 'unsupported', 'deleted'] as const) {
      const values = harness();
      const runtime = new PhysicalResidencyRuntime([descriptor(availability)], values.adapter);
      runtime.execute([load]);
      expect(values.events[0]?.state).toBe(availability);
      expect(values.adapter.fetch).not.toHaveBeenCalled();
    }
    const values = harness();
    new PhysicalResidencyRuntime([], values.adapter).execute([load]);
    expect(values.events[0]?.state).toBe('missing');
  });

  it('reuploads retained decoded data after context restore and requires the Index on failure', async () => {
    const values = harness();
    const runtime = new PhysicalResidencyRuntime([descriptor()], values.adapter);
    runtime.execute([load]);
    await runtime.whenIdle();
    runtime.contextLost();
    expect(values.events.at(-1)?.state).toBe('context-lost');
    values.failRestore();
    await runtime.contextRestored();
    expect(values.indexReasons[0]).toContain('GPU remained unavailable');
  });
});

describe('authenticated asset range observation', () => {
  it('keeps the bearer out of the URL and records an honored partial response', async () => {
    const fetch = vi.fn(async (_url: string | URL | Request, _init?: RequestInit) =>
      new Response(new Uint8Array([1, 2, 3, 4]), {
        status: 206,
        headers: { 'accept-ranges': 'bytes', 'content-range': 'bytes 0-3/100' },
      }));
    const result = await fetchAuthenticatedAsset(descriptor(), new AbortController().signal, {
      baseUrl: 'https://exulanica.test/api/', token: 'private-token', range: [0, 3],
      fetch: fetch as typeof globalThis.fetch,
    });
    expect(fetch.mock.calls[0]![0]).toBe('https://exulanica.test/api/world/assets/artifact-a');
    expect(String(fetch.mock.calls[0]![0])).not.toContain('private-token');
    expect(fetch.mock.calls[0]![1]?.headers).toMatchObject({
      authorization: 'Bearer private-token', range: 'bytes=0-3',
    });
    expect(fetch.mock.calls[0]![1]?.credentials).toBe('include');
    expect(result).toMatchObject({ rangeOutcome: 'partial', acceptRanges: true });
  });

  it('uses the account cookie without sending an explicit empty bearer', async () => {
    const fetch = vi.fn(async (_url: string | URL | Request, _init?: RequestInit) =>
      new Response(new Uint8Array([1, 2, 3, 4]), { status: 200 }));
    await fetchAuthenticatedAsset(descriptor(), new AbortController().signal, {
      baseUrl: 'https://exulanica.test/api', token: '',
      fetch: fetch as typeof globalThis.fetch,
    });
    expect(fetch.mock.calls[0]![1]?.headers).toEqual({});
    expect(fetch.mock.calls[0]![1]?.credentials).toBe('include');
  });

  it('reports a server that ignored Range instead of claiming streaming', async () => {
    const fetch = vi.fn(async () => new Response(new Uint8Array([1, 2, 3, 4]), { status: 200 }));
    const result = await fetchAuthenticatedAsset(descriptor(), new AbortController().signal, {
      baseUrl: 'https://exulanica.test/api', token: 'token', range: [0, 3],
      fetch: fetch as typeof globalThis.fetch,
    });
    expect(result.rangeOutcome).toBe('ignored');
    expect(result.contentRange).toBeNull();
  });
});
