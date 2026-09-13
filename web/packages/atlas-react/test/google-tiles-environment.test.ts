import * as pc from 'playcanvas';
import { describe, expect, it, vi } from 'vitest';
import { GOOGLE_REFERENCE_ORIGIN } from '../src/playcanvas/google-tiles-config.js';
import {
  GoogleTilesEnvironment,
  PlayCanvasGoogleTileHost,
  playCanvasGltfTileTransform,
  type GoogleTileHost,
  type GoogleTilesAttribution,
} from '../src/playcanvas/google-tiles-environment.js';
import {
  googleLocalFrame,
} from '../src/playcanvas/google-tiles-frame.js';
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
  it('undoes the PlayCanvas glTF axis conversion before applying ECEF transforms', () => {
    const matrix = playCanvasGltfTileTransform([
      1, 0, 0, 0,
      0, 1, 0, 0,
      0, 0, 1, 0,
      0, 0, 0, 1,
    ]);
    const playCanvasPoint = [1, 3, -2] as const;
    const converted = [0, 1, 2].map((row) =>
      matrix[row]! * playCanvasPoint[0] +
      matrix[4 + row]! * playCanvasPoint[1] +
      matrix[8 + row]! * playCanvasPoint[2]);
    expect(converted).toEqual([1, 2, 3]);
  });

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

  it('keeps additive parent content visible while children refine', async () => {
    const config = { enabled: true, apiKey: 'fixture-key', ...GOOGLE_REFERENCE_ORIGIN };
    const origin = googleLocalFrame(config.longitude, config.latitude).ecefOrigin;
    const root = JSON.stringify({ root: {
      geometricError: 100,
      refine: 'ADD',
      transform: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, origin[0], origin[1], origin[2], 1],
      boundingVolume: { sphere: [0, 0, 0, 100] },
      content: { uri: 'parent.glb?session=fixture-session' },
      children: [{
        geometricError: 0,
        boundingVolume: { sphere: [0, 0, 0, 50] },
        content: { uri: 'child.glb?session=fixture-session' },
      }],
    } });
    const host: GoogleTileHost<Handle> = {
      load: vi.fn(async (id: string) => ({ id })),
      setTransform: vi.fn(),
      setVisible: vi.fn(),
      release: vi.fn(),
    };
    const provider = new GoogleTilesProvider(config, vi.fn(async (url: string) =>
      url.includes('root.json')
        ? new Response(root, { headers: { 'content-type': 'application/json' } })
        : new Response(glb('Fixture source'), { headers: { 'content-type': 'model/gltf-binary' } })));
    const environment = new GoogleTilesEnvironment({
      config,
      provider,
      host,
      attribution: { update: vi.fn(), destroy: vi.fn() },
    });

    await environment.attach();
    environment.update([0, 1.62, 0]);
    await settle();
    expect(host.load).toHaveBeenCalledWith('root', expect.any(ArrayBuffer), expect.any(AbortSignal));
    environment.update([0, 1.62, 0]);
    expect(host.setVisible).toHaveBeenCalledWith({ id: 'root' }, true);
    await settle();
    expect(host.load).toHaveBeenCalledWith('root/0', expect.any(ArrayBuffer), expect.any(AbortSignal));
    environment.dispose();
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

  it('prioritizes nearby region centres instead of source order', async () => {
    const config = { enabled: true, apiKey: 'fixture-key', ...GOOGLE_REFERENCE_ORIGIN };
    const frame = googleLocalFrame(config.longitude, config.latitude);
    const longitudeOffsets = [20, 15, 10, 5, 0];
    const radians = (degrees: number): number => degrees * Math.PI / 180;
    const root = JSON.stringify({
      root: {
        geometricError: 1000,
        boundingVolume: { sphere: [...frame.ecefOrigin, 10_000_000] },
        children: longitudeOffsets.map((offset) => ({
          geometricError: 0,
          boundingVolume: {
            region: [
              radians(config.longitude + offset - 0.01),
              radians(config.latitude - 0.01),
              radians(config.longitude + offset + 0.01),
              radians(config.latitude + 0.01),
              0,
              100,
            ],
          },
          content: { uri: `tile-${offset}.glb?session=fixture-session` },
        })),
      },
    });
    const requested: string[] = [];
    const fetcher = vi.fn(async (url: string) => {
      requested.push(url);
      return url.includes('root.json')
        ? new Response(root, { headers: { 'content-type': 'application/json' } })
        : new Response(glb('Fixture source'), {
          headers: { 'content-type': 'model/gltf-binary' },
        });
    });
    const host: GoogleTileHost<Handle> = {
      load: vi.fn(async (id: string) => ({ id })),
      setTransform: vi.fn(),
      setVisible: vi.fn(),
      release: vi.fn(),
    };
    const environment = new GoogleTilesEnvironment({
      config,
      provider: new GoogleTilesProvider(config, fetcher),
      host,
      attribution: { update: vi.fn(), destroy: vi.fn() },
      maximumTiles: 4,
    });

    await environment.attach();
    environment.update([0, 1.62, 0]);
    await settle();

    expect(requested.some((url) => url.includes('tile-0.glb'))).toBe(true);
    expect(requested.some((url) => url.includes('tile-20.glb'))).toBe(false);
    environment.dispose();
  });

  it('preserves the glTF root transform beneath the local-frame wrapper', async () => {
    const content = { name: 'source-root' };
    const wrapper = {
      name: '',
      enabled: true,
      children: [] as unknown[],
      position: [0, 0, 0],
      addChild(child: unknown) { this.children.push(child); },
      setLocalPosition(value: pc.Vec3) { this.position = [value.x, value.y, value.z]; },
      setLocalEulerAngles: vi.fn(),
      setLocalScale: vi.fn(),
      destroy: vi.fn(),
    };
    const root = {
      addChild: vi.fn(),
    };
    const registry = { fire: vi.fn(), _loader: { clearCache: vi.fn() } };
    const assets = {
      add: vi.fn((asset: pc.Asset) => {
        (asset as { registry: unknown }).registry = registry;
      }),
      remove: vi.fn(),
      load: vi.fn((asset: pc.Asset) => {
        asset.resource = {
          instantiateRenderEntity: () => content,
          destroy: vi.fn(),
        } as never;
        asset.fire('load', asset);
      }),
    };
    const host = new PlayCanvasGoogleTileHost(
      { assets } as unknown as pc.AppBase,
      root as unknown as pc.Entity,
      (name) => {
        wrapper.name = name;
        return wrapper as unknown as pc.Entity;
      },
    );

    const handle = await host.load('fixture', glb('Fixture source'), new AbortController().signal);
    host.setTransform(handle, [
      1, 0, 0, 0,
      0, 1, 0, 0,
      0, 0, 1, 0,
      10, 20, 30, 1,
    ]);

    expect(handle.entity.name).toBe('google-tile:fixture');
    expect(wrapper.children).toEqual([content]);
    expect(wrapper.position).toEqual([10, 20, 30]);
    expect(root.addChild).toHaveBeenCalledWith(wrapper);
    host.release(handle);
    expect(wrapper.destroy).toHaveBeenCalledTimes(1);
  });
});
