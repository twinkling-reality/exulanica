import { describe, expect, it, vi } from 'vitest';
import { GOOGLE_REFERENCE_ORIGIN } from '../src/playcanvas/google-tiles-config.js';
import {
  GoogleTilesProvider,
  admitGoogleTilesUrl,
} from '../src/playcanvas/google-tiles-provider.js';

const config = {
  enabled: true,
  apiKey: 'test-secret-key',
  ...GOOGLE_REFERENCE_ORIGIN,
};

function response(body: string | Uint8Array, contentType: string): Response {
  const value = typeof body === 'string' ? body : body.slice().buffer;
  return new Response(value, { status: 200, headers: { 'content-type': contentType } });
}

describe('Google tiles provider admission', () => {
  it('admits only exact official HTTPS 3D Tiles URLs', () => {
    expect(admitGoogleTilesUrl('https://tile.googleapis.com/v1/3dtiles/root.json').hostname)
      .toBe('tile.googleapis.com');
    for (const value of [
      'http://tile.googleapis.com/v1/3dtiles/root.json',
      'https://evil.tile.googleapis.com/v1/3dtiles/root.json',
      'https://tile.googleapis.com/maps/other',
      'https://tile.googleapis.com/v1/3dtiles/root.json?other=value',
      'https://user@tile.googleapis.com/v1/3dtiles/root.json',
    ]) expect(() => admitGoogleTilesUrl(value)).toThrow('Google tile URL rejected');
  });

  it('propagates the root session and key without exposing either in failures', async () => {
    const requests: string[] = [];
    const fetcher = vi.fn(async (url: string) => {
      requests.push(url);
      if (requests.length === 1) {
        return response('{"root":{"content":{"uri":"child.glb?session=test-session"}}}', 'application/json');
      }
      if (requests.length === 2) return response(new Uint8Array([1, 2, 3]), 'model/gltf-binary');
      throw new Error(`unsafe ${url}`);
    });
    const provider = new GoogleTilesProvider(config, fetcher);
    await provider.openRoot(new AbortController().signal);
    await provider.fetchContent('child.glb?session=test-session', new AbortController().signal);
    expect(new URL(requests[0]!).searchParams.get('key')).toBe('test-secret-key');
    expect(new URL(requests[1]!).searchParams.get('session')).toBe('test-session');
    expect(new URL(requests[1]!).searchParams.get('key')).toBe('test-secret-key');

    await expect(provider.fetchContent('failed.glb', new AbortController().signal))
      .rejects.toThrow('Google tile request failed');
    try {
      await provider.fetchContent('failed.glb', new AbortController().signal);
    } catch (error) {
      expect(String(error)).not.toContain('test-secret-key');
      expect(String(error)).not.toContain('test-session');
      expect(String(error)).not.toContain('failed.glb');
    }
  });

  it('uses ordinary HTTP caching and never requests offline persistence or prefetch', async () => {
    let receiver: unknown;
    const fetcher = vi.fn(async (_url: string, _init: RequestInit) =>
      response('{}', 'application/json')).mockImplementation(
      async function (this: unknown, _url: string, _init: RequestInit) {
        receiver = this;
        return response('{}', 'application/json');
      },
    );
    const provider = new GoogleTilesProvider(config, fetcher);
    await provider.openRoot(new AbortController().signal);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(receiver).toBe(globalThis);
    expect(fetcher.mock.calls[0]![1]).toMatchObject({
      cache: 'default',
      credentials: 'omit',
      redirect: 'error',
      method: 'GET',
    });
  });
});
