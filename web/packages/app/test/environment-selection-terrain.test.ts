// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import type { AtlasScene } from '@exulanica/atlas-core';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
afterEach(() => document.body.replaceChildren());
it('normal terrain E and click inspect exact source parts without creating a society or authored object', async () => {
  let current = true;
  const prior = vi.fn();
  const controls = { state: { x: 0, y: 1.68, z: 0 }, onInteract: prior as (() => void) | null,
    onPointerPick: null as ((x: number, y: number) => boolean) | null };
  const canvas = document.createElement('canvas');
  vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 100, height: 100 } as DOMRect);
  const updates = new Set<() => void>();
  const app = { graphicsDevice: { canvas }, on: (_event: string, callback: () => void) => updates.add(callback),
    off: (_event: string, callback: () => void) => updates.delete(callback) };
  const hit = { kind: 'terrain-dressing', instanceId: 'west-gateway', assetKey: 'reviewed.gateway',
    contentSha256: 'a'.repeat(64), nodeIndex: 5, meshIndex: 3, primitiveIndex: 1, distance: 4 };
  const binding = { controls, app,
    camera: { getPosition: () => ({ x: 0, y: 1.68, z: 0 }), camera: { nearClip: .1, farClip: 100,
      screenToWorld: (_x: number, _y: number, depth: number, out: { set(x: number, y: number, z: number): unknown }) => out.set(0, 1.68, -depth) } },
    interactionRay: () => ({ origin: [0, 1.68, 0], direction: [0, 0, -1] }),
    pickSourceSurface: vi.fn(() => current ? hit : null), sourceSurfaceCurrent: () => current,
    invalidate: vi.fn(), ownedDistrict: null, authoredSociety: null,
  };
  const worldClient = { connect: vi.fn() };
  const societyClient = { read: vi.fn(), create: vi.fn() };
  const onSelect = vi.fn();
  const mounted = mountEnvironmentSelection({
    env: { canvas, preview: false } as unknown as AppEnvironment,
    state: { atlas: { binding }, activeWorldEntry: { worldId: 'world', authoredVersionId: 'version',
      title: 'Waterside', generatedTerrain: { regionId: 'terrain' } } } as unknown as SessionState,
    scene: { islands: [] } as unknown as AtlasScene,
    credentials: { baseUrl: 'https://example.test', token: 'token' }, showStatus: vi.fn(), admissionId: null,
    worldClient: worldClient as never, societyClient: societyClient as never, onSelect,
  });
  document.body.append(mounted.root);
  try {
    await mounted.begin();
    controls.onInteract!();
    const inspector = mounted.root.querySelector<HTMLElement>('.living-world-inspector')!;
    expect(inspector.hidden).toBe(false);
    expect(inspector.querySelector('h3')?.textContent).toBe('West gateway');
    expect(inspector.textContent).toContain('Immutable scenery');
    expect(inspector.textContent).toContain(hit.contentSha256);
    expect(inspector.textContent).toContain('5 / 3 / 1');
    expect(inspector.querySelector('.living-world-actions')?.children.length).toBe(0);
    expect(onSelect).toHaveBeenLastCalledWith(null);
    expect(controls.onPointerPick!(50, 50)).toBe(true);
    expect(binding.pickSourceSurface).toHaveBeenCalledTimes(2);
    const modal = document.createElement('section');
    modal.setAttribute('aria-modal', 'true');
    document.body.append(modal);
    expect(controls.onPointerPick!(50, 50)).toBe(false);
    expect(binding.pickSourceSurface).toHaveBeenCalledTimes(2);
    modal.remove();
    expect(worldClient.connect).not.toHaveBeenCalled();
    expect(societyClient.read).not.toHaveBeenCalled();
    expect(societyClient.create).not.toHaveBeenCalled();
    current = false;
    for (const update of updates) update();
    expect(inspector.hidden).toBe(true);
    expect(controls.onPointerPick!(50, 50)).toBe(false);
    controls.onInteract!();
    expect(prior).toHaveBeenCalledOnce();
  } finally { mounted.dispose(); }
  expect(controls.onInteract).toBe(prior);
  expect(controls.onPointerPick).toBeNull();
  expect(updates.size).toBe(0);
});
