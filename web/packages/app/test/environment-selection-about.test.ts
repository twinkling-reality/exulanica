// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import { islandId, type AtlasScene } from '@exulanica/atlas-core';
import { describeWorldKind, type WorldKind } from '@exulanica/atlas-react/playcanvas';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import { aboutWorld, aboutWorldLayers } from '../src/world-about.js';

/*
 * The About panel ("About this place") says what the open world is, from the kind of world the
 * renderer drew, and says nothing before it knows. A person's starter world is not described as
 * a district, and toggling the memory layer changes the sentence only where the ground has a
 * layer of its own.
 */

const STARTER_REGION = {
  regionId: islandId('region:starter'),
  module: { key: 'region.authored-ground' as const, version: 2 as const },
  ground: { kind: 'endless' as const, elevationMm: 0 },
  spawn: { xMm: 0, yMm: 0, zMm: 4000, yawMicroradians: 0 },
};

function mount(worldKind: WorldKind | undefined, savedStarter: boolean) {
  const missing = () => new ApiError(404, 'unknown_reference', 'no such society');
  const binding = {
    controls: { state: { x: 0, y: 1.68, z: 4 }, onInteract: null, forward: () => ({ x: 0, y: 0, z: -1 }) },
    camera: { forward: { x: 0, y: 0, z: -1 } }, invalidate: vi.fn(),
    ownedDistrict: null, generatedTile: null, authoredSociety: null,
    memoryLayerVisible: worldKind?.memoryLayerVisible ?? true, onMemoryLayerChange: null,
    setMemoryLayerVisible: vi.fn(),
  };
  const mounted = mountEnvironmentSelection({
    env: { canvas: document.createElement('canvas'), preview: false } as unknown as AppEnvironment,
    state: {
      atlas: worldKind === undefined ? { binding } : { binding, worldKind },
      activeWorldEntry: savedStarter
        ? { worldId: 'world:authored:saved', authoredVersionId: 'version', title: 'My world',
          authoredScene: { region: { regionId: 'region:starter' } } }
        : null,
    } as unknown as SessionState,
    scene: { islands: [] } as unknown as AtlasScene,
    credentials: { baseUrl: 'https://example.test', token: 'token' },
    showStatus: vi.fn(), admissionId: null,
    worldClient: { connect: vi.fn(async () => { throw missing(); }) } as never,
    societyClient: { read: vi.fn(async () => { throw missing(); }), events: vi.fn(async () => []) } as never,
    societyControlClient: { read: vi.fn(async () => { throw missing(); }) } as never,
  });
  document.body.append(mounted.root);
  const about = () => mounted.root.querySelector<HTMLElement>('.environment-selection-source')!.textContent;
  const memoryLayer = () => mounted.root.querySelector<HTMLInputElement>('.environment-selection-layer input')!;
  return { mounted, about, memoryLayer };
}

const toggle = (box: HTMLInputElement, checked: boolean): void => {
  box.checked = checked;
  box.dispatchEvent(new Event('change'));
};

describe('About this place states the kind of world that is open', () => {
  it('a saved starter world is described as an authored starter, and the memory toggle keeps it so', async () => {
    const starter = describeWorldKind({ authoredRegion: STARTER_REGION });
    const { mounted, about, memoryLayer } = mount(starter, true);
    expect(about()).toBe('');
    await mounted.begin();
    expect(about()).toBe(aboutWorld(starter));
    expect(about()).not.toMatch(/building forms|sidewalk|BUILDING footprints/i);
    toggle(memoryLayer(), false);
    expect(about()).toBe(aboutWorld(starter));
    toggle(memoryLayer(), true);
    expect(about()).toBe(aboutWorld(starter));
  });

  it('a district is described by its source-backed forms, and by its layers when they change', async () => {
    const district = describeWorldKind({ ownedDistrict: { document: {} as never, residentBytes: 100 } });
    const { mounted, about, memoryLayer } = mount(district, false);
    await mounted.begin();
    expect(about()).toBe(aboutWorld(district));
    toggle(memoryLayer(), true);
    expect(about()).toBe(aboutWorldLayers(district, true));
    toggle(memoryLayer(), false);
    expect(about()).toBe(aboutWorldLayers(district, false));
  });

  it('with no kind decided the panel claims nothing, rather than one kind of world for all', async () => {
    const { mounted, about, memoryLayer } = mount(undefined, true);
    await mounted.begin();
    expect(about()).toBe('');
    toggle(memoryLayer(), false);
    expect(about()).toBe('');
  });
});
