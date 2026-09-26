// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';

/** Container assets as the society receives them: each part instantiates, and unload is counted. */
const created = vi.hoisted(() => [] as { unload: () => void; unloads: number; resource: unknown }[]);
vi.mock('../src/playcanvas/scene-objects.js', async (importOriginal) => {
  const engine = await import('playcanvas');
  return {
    ...await importOriginal<object>(),
    createObjectContainerAsset: vi.fn(async () => {
      const asset = {
        unloads: 0,
        unload() { asset.unloads += 1; },
        resource: { instantiateRenderEntity: () => new engine.Entity('part') },
      };
      created.push(asset);
      return asset;
    }),
  };
});

import { AuthoredRegionSociety } from '../src/playcanvas/society/authored-society.js';

const LOOK = { key: 'small_bird', wingHingeMm: [30, 6, 66] as const, maxBankMrad: 785, flapCycleMs: 120 };

function setup() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  app.init(options);
  const root = new pc.Entity('region');
  app.root.addChild(root);
  return { app, device, root };
}

describe('AuthoredRegionSociety flight assets', () => {
  it('releases a kind\'s body and wing when it is destroyed, and none before', async () => {
    created.length = 0;
    const { app, device, root } = setup();
    const removed: unknown[] = [];
    vi.spyOn(app.assets, 'remove').mockImplementation((asset) => { removed.push(asset); return true; });
    const society = new AuthoredRegionSociety(device, root);
    const bytes = new ArrayBuffer(4);
    await society.setFlightKind(app, LOOK, { assetKey: 'body', bytes }, { assetKey: 'wing', bytes });
    expect(society.hasFlightKind('small_bird')).toBe(true);
    expect(created.map((asset) => asset.unloads)).toEqual([0, 0]);
    society.clearFlight();
    expect(created.map((asset) => asset.unloads)).toEqual([0, 0]);
    society.destroy();
    expect(created.map((asset) => asset.unloads)).toEqual([1, 1]);
    expect(removed).toEqual(created);
  });

  it('releases parts that arrive after it was destroyed at once', async () => {
    created.length = 0;
    const { app, device, root } = setup();
    vi.spyOn(app.assets, 'remove').mockImplementation(() => true);
    const society = new AuthoredRegionSociety(device, root);
    const bytes = new ArrayBuffer(4);
    const loading = society.setFlightKind(app, LOOK, { assetKey: 'body', bytes }, { assetKey: 'wing', bytes });
    society.destroy();
    await loading;
    expect(created.map((asset) => asset.unloads)).toEqual([1, 1]);
    expect(society.hasFlightKind('small_bird')).toBe(false);
  });
});
