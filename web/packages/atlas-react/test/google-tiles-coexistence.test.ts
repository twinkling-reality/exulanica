// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FirstPersonControls } from '../src/playcanvas/controls.js';
import { GOOGLE_REFERENCE_ORIGIN } from '../src/playcanvas/google-tiles-config.js';
import {
  GoogleTilesEnvironment,
  type GoogleTileHost,
} from '../src/playcanvas/google-tiles-environment.js';
import { googleLocalFrame } from '../src/playcanvas/google-tiles-frame.js';
import { GoogleTilesProvider } from '../src/playcanvas/google-tiles-provider.js';

function glb(): ArrayBuffer {
  const source = JSON.stringify({ asset: { version: '2.0', copyright: 'Fixture' } });
  const json = source.padEnd(Math.ceil(source.length / 4) * 4, ' ');
  const bytes = new Uint8Array(20 + json.length);
  const view = new DataView(bytes.buffer);
  view.setUint32(0, 0x46546c67, true);
  view.setUint32(4, 2, true);
  view.setUint32(8, bytes.length, true);
  view.setUint32(12, json.length, true);
  view.setUint32(16, 0x4e4f534a, true);
  bytes.set(new TextEncoder().encode(json), 20);
  return bytes.buffer;
}

describe('Atlas interaction coexistence with mocked Google tiles', () => {
  beforeEach(() => {
    document.body.replaceChildren();
    Object.defineProperty(document, 'pointerLockElement', {
      configurable: true,
      writable: true,
      value: null,
    });
  });

  it('leaves first-person movement, Interact, Companion and authored runtime ownership intact', async () => {
    const canvas = document.createElement('canvas');
    document.body.append(canvas);
    const controls = new FirstPersonControls(canvas, {
      x: 0, y: 1.62, z: 0, yaw: 0, pitch: 0,
    });
    const authoredRuntime = { interact: vi.fn() };
    const companion = vi.fn();
    controls.onInteract = authoredRuntime.interact;
    controls.onSummon = companion;
    Object.defineProperty(document, 'pointerLockElement', {
      configurable: true,
      writable: true,
      value: canvas,
    });
    document.dispatchEvent(new Event('pointerlockchange'));

    const config = { enabled: true, apiKey: 'fixture-key', ...GOOGLE_REFERENCE_ORIGIN };
    const ecef = googleLocalFrame(config.longitude, config.latitude).ecefOrigin;
    const root = JSON.stringify({ root: {
      geometricError: 0,
      transform: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, ecef[0], ecef[1], ecef[2], 1],
      boundingVolume: { sphere: [0, 0, 0, 10] },
      content: { uri: 'fixture.glb?session=fixture-session' },
    } });
    const provider = new GoogleTilesProvider(config, vi.fn(async (url: string) =>
      url.includes('root.json')
        ? new Response(root, { headers: { 'content-type': 'application/json' } })
        : new Response(glb(), { headers: { 'content-type': 'model/gltf-binary' } })));
    const host: GoogleTileHost<{ readonly id: string }> = {
      load: vi.fn(async (id: string) => ({ id })),
      setTransform: vi.fn(),
      setVisible: vi.fn(),
      release: vi.fn(),
    };
    const environment = new GoogleTilesEnvironment({
      config,
      provider,
      host,
      attribution: { update: vi.fn(), destroy: vi.fn() },
    });
    await environment.attach();
    environment.update([controls.state.x, controls.state.y, controls.state.z]);

    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyW' }));
    controls.update(0.2);
    expect(controls.state.z).not.toBe(0);
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyE' }));
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyX' }));
    expect(authoredRuntime.interact).toHaveBeenCalledTimes(1);
    expect(companion).toHaveBeenCalledTimes(1);

    environment.dispose();
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyE' }));
    expect(authoredRuntime.interact).toHaveBeenCalledTimes(2);
    controls.destroy();
  });
});
