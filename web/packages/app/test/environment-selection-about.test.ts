// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import { islandId, type AtlasScene } from '@exulanica/atlas-core';
import { describeWorldKind, type WorldKind } from '@exulanica/atlas-react/playcanvas';
import type { GeneratedTileMount } from '@exulanica/atlas-react/generated-tile';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import { aboutWorld, aboutWorldLayers } from '../src/world-about.js';

/*
 * The About panel ("About this place") says what the open world is, from the kind of world the
 * renderer drew, and says nothing before it knows. A person's starter world is not described as
 * a district, and toggling the memory layer changes the sentence only where the ground has a
 * layer of its own. Its camera controls follow the same kind: each view is offered only in a
 * world that carries it out (`atlas-react/test/binding/world-views.test.ts` holds that against
 * the binding), and no view that depends on the kind is offered before the kind is known.
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
    cameraMode: 'first-person', setCameraMode: vi.fn(), setCameraFraming: vi.fn(),
    setCityView: vi.fn(), turnCamera: vi.fn(), setWalkAssist: vi.fn(),
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
  return { mounted, binding, about, memoryLayer, controls: () => controlsIn(mounted.root) };
}

/**
 * Every control the About panel offers, by the name a person reads: a button's or summary's
 * text, a select's label. A control inside a closed section is offered (it is a click away); one
 * under a hidden element, or out of the panel, is not.
 */
function controlsIn(root: HTMLElement): Map<string, HTMLElement> {
  const panel = root.querySelector<HTMLElement>('#world-panel-details')!;
  const hidden = (control: HTMLElement): boolean => {
    for (let node: HTMLElement | null = control; node !== null && node !== panel; node = node.parentElement) {
      if (node.hidden) return true;
    }
    return false;
  };
  const offered = new Map<string, HTMLElement>();
  for (const control of panel.querySelectorAll<HTMLElement>('button, select, summary')) {
    if (!hidden(control)) offered.set(control.getAttribute('aria-label') ?? control.textContent!.trim(), control);
  }
  return offered;
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

const ENDLESS = STARTER_REGION;
const FLAT = { ...STARTER_REGION, module: { key: 'region.authored-ground' as const, version: 1 as const },
  ground: { kind: 'flat' as const, halfWidthMm: 12_000, halfDepthMm: 12_000, elevationMm: 0 } };
const GOOGLE = { enabled: true, apiKey: 'test-key', longitude: -73.99, latitude: 40.74, altitude: 10 };
const DISTRICT = { document: {} as never, residentBytes: 100 };
const TILE = { attach: () => ({}) } as unknown as GeneratedTileMount;

/** The kinds of world `atlas-react/test/binding/world-kinds.ts` names (WORLD_KINDS), as options. */
const WORLD_KINDS = {
  'authored-endless': { authoredRegion: ENDLESS },
  'authored-with-estimate': { authoredRegion: ENDLESS, authoredPointMaps: [{ instanceId: 'estimate:test' }] },
  'authored-flat': { authoredRegion: FLAT },
  'personal-regions': {},
  'owned-district': { ownedDistrict: DISTRICT },
  'generated-tile': { generatedTile: TILE },
  'google-reference': { googleTiles: GOOGLE },
  'authored-and-google': { authoredRegion: ENDLESS, googleTiles: GOOGLE },
} as const;

/**
 * Which views each kind of world offers, and why. A district frames the city views on its own
 * buildings and is the only ground with a third-person camera; a Google reference frames the city
 * views on its own viewpoints. No other ground has either, so a control for them would do nothing.
 */
const OFFERED: Readonly<Record<keyof typeof WORLD_KINDS, readonly string[]>> = {
  'authored-endless': [],
  'authored-with-estimate': [],
  'authored-flat': [],
  'personal-regions': [],
  'owned-district': ['City overview', 'Street level', 'Third person (C)', 'Third-person framing'],
  'generated-tile': [],
  'google-reference': ['City overview', 'Street level'],
  'authored-and-google': ['City overview', 'Street level'],
};
/** The controls whose views depend on the kind of world. */
const KIND_VIEWS = ['City overview', 'Street level', 'Third person (C)', 'Third-person framing'];
/** Turning the view and movement assistance work in every world. */
const EVERY_WORLD = ['Camera framing', 'Rotate view 90°', 'Movement assistance', 'Walk forward', 'Run forward', 'Stop moving'];

const kindViews = (offered: Map<string, HTMLElement>) => [...offered.keys()].filter((name) => KIND_VIEWS.includes(name));
const cameraGroup = (root: HTMLElement) => root.querySelector<HTMLElement>('.world-panel-camera')!;

describe('About this place offers only the camera views the open world carries out', () => {
  for (const [name, options] of Object.entries(WORLD_KINDS) as [keyof typeof WORLD_KINDS, object][]) {
    it(`${name}: offers ${OFFERED[name].length === 0 ? 'no view that depends on the kind' : OFFERED[name].join(', ')}`, async () => {
      const kind = describeWorldKind(options as Parameters<typeof describeWorldKind>[0]);
      const { mounted, controls } = mount(kind, kind.ground.form.startsWith('authored'));
      expect(kindViews(controls())).toEqual([]);
      await mounted.begin();
      expect(kindViews(controls())).toEqual(OFFERED[name]);
      for (const always of EVERY_WORLD) expect(controls().has(always), always).toBe(true);
      // The camera row holds the buttons among them, and is hidden when it holds none.
      const row = cameraGroup(mounted.root);
      expect([...row.children].map((child) => child.textContent)).toEqual(
        OFFERED[name].filter((view) => view !== 'Third-person framing'));
      expect(row.hidden).toBe(row.children.length === 0);
    });
  }

  it('a district\'s views reach the binding: both city views, the third-person camera and its framing', async () => {
    const { mounted, binding, controls } = mount(describeWorldKind(WORLD_KINDS['owned-district']), false);
    await mounted.begin();
    const offered = controls();
    offered.get('City overview')!.click();
    offered.get('Street level')!.click();
    expect(binding.setCityView.mock.calls).toEqual([['overview'], ['street']]);
    offered.get('Third person (C)')!.click();
    expect(binding.setCameraMode).toHaveBeenLastCalledWith('third-person');
    const framing = offered.get('Third-person framing') as HTMLSelectElement;
    framing.value = '.85';
    framing.dispatchEvent(new Event('change'));
    expect(binding.setCameraFraming).toHaveBeenLastCalledWith(0.85);
    offered.get('Rotate view 90°')!.click();
    expect(binding.turnCamera).toHaveBeenCalledWith(Math.PI / 2);
  });

  it('with no kind decided, no view that depends on the kind is offered', async () => {
    const { mounted, controls } = mount(undefined, true);
    await mounted.begin();
    expect(kindViews(controls())).toEqual([]);
    expect(cameraGroup(mounted.root).hidden).toBe(true);
    for (const always of EVERY_WORLD) expect(controls().has(always), always).toBe(true);
  });
});
