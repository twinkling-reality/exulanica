import { describe, expect, it, vi } from 'vitest';
import { GOOGLE_REFERENCE_ORIGIN } from '../src/playcanvas/google-tiles-config.js';
import {
  GoogleTilesEnvironment,
  type GoogleTileHost,
  type GoogleTilesAttribution,
} from '../src/playcanvas/google-tiles-environment.js';
import { googleLocalFrame } from '../src/playcanvas/google-tiles-frame.js';
import { GoogleTilesProvider } from '../src/playcanvas/google-tiles-provider.js';

interface Handle { readonly id: string }

function glb(copyright: string): ArrayBuffer {
  const source = JSON.stringify({ asset: { version: '2.0', copyright } });
  const padded = source.padEnd(Math.ceil(source.length / 4) * 4, ' ');
  const bytes = new Uint8Array(20 + padded.length);
  const view = new DataView(bytes.buffer);
  view.setUint32(0, 0x46546c67, true);
  view.setUint32(4, 2, true);
  view.setUint32(8, bytes.byteLength, true);
  view.setUint32(12, padded.length, true);
  view.setUint32(16, 0x4e4f534a, true);
  bytes.set(new TextEncoder().encode(padded), 20);
  return bytes.buffer;
}

function fixture() {
  const config = { enabled: true, apiKey: 'fixture-key', ...GOOGLE_REFERENCE_ORIGIN };
  const origin = googleLocalFrame(config.longitude, config.latitude).ecefOrigin;
  const root = JSON.stringify({
    root: {
      geometricError: 0,
      transform: [
        1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0,
        origin[0], origin[1], origin[2], 1,
      ],
      boundingVolume: { sphere: [0, 0, 0, 100] },
      content: { uri: 'fixture.glb?session=fixture-session' },
    },
  });
  const tile = glb('Fixture source');
  const fetcher = vi.fn(async (url: string) => url.includes('root.json')
    ? new Response(root, { status: 200, headers: { 'content-type': 'application/json' } })
    : new Response(tile, { status: 200, headers: { 'content-type': 'model/gltf-binary' } }));
  const handles: Handle[] = [];
  const host: GoogleTileHost<Handle> = {
    load: vi.fn(async (id: string) => {
      const handle = { id };
      handles.push(handle);
      return handle;
    }),
    setTransform: vi.fn(),
    setVisible: vi.fn(),
    release: vi.fn(),
  };
  const attribution: GoogleTilesAttribution = {
    update: vi.fn(),
    destroy: vi.fn(),
  };
  return {
    config,
    fetcher,
    handles,
    host,
    attribution,
    environment: new GoogleTilesEnvironment({
      config,
      provider: new GoogleTilesProvider(config, fetcher),
      host,
      attribution,
    }),
  };
}

async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe('Google tiles environment lifecycle', () => {
  it('loads only after an explicit view update and tears every runtime resource down', async () => {
    const test = fixture();
    await test.environment.attach();
    expect(test.fetcher).toHaveBeenCalledTimes(1);
    test.environment.update([0, 1.62, 0]);
    await settle();
    expect(test.fetcher).toHaveBeenCalledTimes(2);
    expect(test.host.load).toHaveBeenCalledTimes(1);
    expect(test.host.setVisible).toHaveBeenCalledWith(test.handles[0], true);
    expect(test.attribution.update).toHaveBeenCalledWith(true, ['Fixture source']);
    expect(test.environment.metrics()).toMatchObject({ residentTiles: 1, residentBytes: glb('Fixture source').byteLength });

    test.environment.dispose();
    expect(test.host.release).toHaveBeenCalledTimes(1);
    expect(test.attribution.update).toHaveBeenLastCalledWith(false, []);
    expect(test.attribution.destroy).toHaveBeenCalledTimes(1);
    expect(test.environment.metrics()).toMatchObject({
      activeRequests: 0,
      queuedRequests: 0,
      residentTiles: 0,
      residentBytes: 0,
    });
  });

  it('supports repeated independent attach and detach without accumulating provider state', async () => {
    for (let index = 0; index < 2; index++) {
      const test = fixture();
      await test.environment.attach();
      test.environment.update([0, 1.62, 0]);
      await settle();
      test.environment.dispose();
      expect(test.host.release).toHaveBeenCalledTimes(1);
      expect(test.attribution.destroy).toHaveBeenCalledTimes(1);
    }
  });

  it('fails closed when the mocked provider network is unavailable', async () => {
    const test = fixture();
    const unavailable = vi.fn();
    const environment = new GoogleTilesEnvironment({
      config: test.config,
      provider: new GoogleTilesProvider(test.config, vi.fn(async () => { throw new Error('offline'); })),
      host: test.host,
      attribution: test.attribution,
      onUnavailable: unavailable,
    });
    await environment.attach();
    expect(unavailable).toHaveBeenCalledTimes(1);
    environment.update([0, 1.62, 0]);
    expect(test.host.load).not.toHaveBeenCalled();
    environment.dispose();
  });
});
