// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  atlasVec3, islandId, localVec3, makeIsland, placement, sceneDisplayFrame,
} from '@exulanica/atlas-core';
import { mountObjects, type MountedObjects, type ObjectsDependencies } from '../src/composition/objects.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import type {
  AlternateVersion, AuthoredObject, ReviewedAsset, WorldObjectsClient,
} from '../src/world-objects-api.js';

/**
 * The authored-object surface, against a scripted authority.
 *
 * The thing under test is the ORDER: nothing reaches the client until the confirmation surface has
 * been shown and confirmed. So the client here is a script that records every call, and the
 * assertion that matters most in this file is the one that counts zero of them.
 *
 * The renderer is a script too. What the surface owes the renderer is a region-local pose and a
 * control call; what the renderer owes the surface is a refusal it can put on the screen. Neither
 * needs a GPU, and the container decoding that does is tested where it lives, in
 * `atlas-react/test/scene-objects.test.ts`.
 */

const REGION = islandId('region-a');
const SCENE = 'scene-a';
const STATE = 'a'.repeat(64);

/**
 * The region an object stands in, built the way the scene graph builds one.
 *
 * A hand-written literal is not enough: `footprintRadiusLocal` is what decides whether the visitor
 * is standing IN this region or merely nearest to it, and a fixture missing it made every
 * placement refuse. That is the same defect in miniature that the browser check found in the
 * product, so the fixture is built by the same function the application uses.
 */
const region = (footprintRadiusLocal = 20, awayBy = 0) => makeIsland({
  islandId: REGION,
  createdAt: 0,
  placement: placement(atlasVec3(awayBy, 0, 0), 0, 1),
  rung: 3,
  scaleIsMetric: false,
  footprintRadiusLocal,
  viewpointLocal: localVec3(0, 0, 0),
  anchors: [],
  layoutEntities: new Set(),
});

const asset = (over: Partial<ReviewedAsset> = {}): ReviewedAsset => Object.freeze({
  assetKey: 'cc0.marker-pillar',
  title: 'Marker pillar',
  summary: 'A square pillar.',
  mediaType: 'model/gltf-binary',
  contentSha256: 'b'.repeat(64),
  byteSize: 784,
  licenceId: 'CC0-1.0',
  licenceSha256: 'c'.repeat(64),
  availability: 'available',
  ...over,
});

const objectRecord = (over: Partial<AuthoredObject> = {}): AuthoredObject => Object.freeze({
  objectId: 'object:lantern',
  asset: asset(),
  regionId: String(REGION),
  transform: Object.freeze({
    coordinateSpace: 'region_local',
    coordinateUnit: 'millimetre',
    xMm: 1200, yMm: 0, zMm: -450, yawMicroradians: 0, scaleMilli: 1000,
  }),
  origin: Object.freeze({ kind: 'authored', role: 'fictional' as const }),
  behaviour: null,
  removed: false,
  ...over,
});

const version = (over: Partial<AlternateVersion> = {}): AlternateVersion => Object.freeze({
  schemaVersion: 1,
  versionId: '6f1d2c40-0000-7000-8000-000000000001',
  worldId: 'atlas:default',
  sourceSnapshotId: '6f1d2c40-0000-7000-8000-000000000002',
  parentVersionId: null,
  title: 'Lantern study',
  origin: 'authored',
  styleVersionId: null,
  stateSha256: STATE,
  editSeq: 0,
  sourceInvalidated: false,
  createdBy: '6f1d2c40-0000-7000-8000-000000000003',
  createdAt: '2026-09-09T12:00:00+00:00',
  objects: Object.freeze([]),
  elementOverrides: Object.freeze([]),
  edits: Object.freeze([]),
  ...over,
});

const edit = (editSeq: number, kind: string, over: Record<string, unknown> = {}) => Object.freeze({
  editId: `edit-${editSeq}`,
  editSeq,
  kind,
  objectId: 'object:lantern',
  elementId: null,
  undoneEditId: null,
  baseStateSha256: STATE,
  resultStateSha256: STATE,
  actor: 'actor',
  recordedAt: '2026-09-09T12:00:00+00:00',
  ...over,
});

/** The renderer, scripted: it records what it was told to draw and answers what it refuses. */
function runtime() {
  const placed = new Map<string, { pose: unknown; motion: string }>();
  return {
    get objectIds() { return [...placed.keys()]; },
    motionStateOf: (id: string) => placed.get(id)?.motion ?? null,
    place: vi.fn(async (object: { objectId: string; behaviour: unknown; transform: unknown }) => {
      const behaviour = object.behaviour as { behaviourKey: string; behaviourVersion: number } | null;
      const supported = behaviour === null
        || (behaviour.behaviourKey === 'motion.bounded-path' && behaviour.behaviourVersion === 1);
      placed.set(object.objectId, {
        pose: object.transform,
        motion: behaviour === null ? 'none' : supported ? 'at-rest' : 'none',
      });
      return {
        objectId: object.objectId,
        motion: behaviour !== null && supported ? 'attached' as const : 'none' as const,
        notices: supported ? [] : [`“${behaviour!.behaviourKey}@${behaviour!.behaviourVersion}” is not a behaviour this build can run.`],
      };
    }),
    remove: vi.fn((id: string) => placed.delete(id)),
    setTransform: vi.fn((id: string, pose: unknown) => {
      const held = placed.get(id);
      if (held === undefined) return false;
      placed.set(id, { ...held, pose });
      return true;
    }),
    control: vi.fn((id: string, action: string) => {
      const held = placed.get(id);
      if (held === undefined) return { ok: false as const, reason: 'That object is not in this world.' };
      if (held.motion === 'none') {
        return { ok: false as const, reason: 'This object carries no motion this build can run, so there is nothing to start.' };
      }
      placed.set(id, {
        ...held,
        motion: action === 'trigger' ? 'running' : action === 'stop' ? 'held' : 'at-rest',
      });
      return { ok: true as const };
    }),
    poseOf: (id: string) => placed.get(id)?.pose ?? null,
  };
}

/** The authority, scripted: it records every call and answers whatever the test queued. */
function script(initial: AlternateVersion = version()) {
  const calls: { name: string; args: unknown[] }[] = [];
  let current = initial;
  let answer: unknown = null;
  const record = (name: string) => (...args: unknown[]) => {
    calls.push({ name, args });
    if (answer instanceof Error) { const thrown = answer; answer = null; throw thrown; }
    const queued = answer;
    answer = null;
    return Promise.resolve(queued ?? { kind: 'recorded', version: current });
  };
  return {
    calls,
    answerWith(next: unknown) { answer = next; },
    client: {
      connect: vi.fn(async () => {
        calls.push({ name: 'connect', args: [] });
        return { assets: [asset()], version: current };
      }),
      readVersion: vi.fn(async () => current),
      place: record('place'),
      move: record('move'),
      remove: record('remove'),
      undo: record('undo'),
    } as unknown as WorldObjectsClient,
  };
}

function harness(
  over: Partial<ObjectsDependencies> & {
    readonly noClient?: true;
    readonly footprint?: number;
    readonly awayBy?: number;
    readonly initial?: AlternateVersion;
  } = {},
  previewMode = false,
) {
  const objects = runtime();
  const authority = script(over.initial ?? version());
  const state = {
    atlas: {
      binding: {
        objects,
        cameraPose: () => ({ position: atlasVec3(0, 1.6, 0), forward: atlasVec3(0, 0, -1) }),
        engageFocusedAnchor: () => null,
        table: { atlasPositions: new Float32Array([0, 0, 0]) },
      },
    },
    displayFrames: new Map(),
    placedPointMaps: [{ islandId: REGION, sceneId: SCENE }],
    trainedGeometry: [],
    pointMaps: undefined,
  } as unknown as SessionState;
  const env = { preview: previewMode } as unknown as AppEnvironment;
  const travel: { message: string; kind?: string }[] = [];
  const mounted = mountObjects({
    env,
    state,
    credentials: { baseUrl: 'https://exulanica.test', token: 'token' },
    scene: {
      islands: [region(over.footprint, over.awayBy)],
    } as unknown as ObjectsDependencies['scene'],
    showTravelStatus: (message, kind) => travel.push({ message, ...(kind === undefined ? {} : { kind }) }),
    isWorldPrimary: () => true,
    hideWritePathConfirm: vi.fn(),
    ...(over.noClient === true ? {} : { client: authority.client }),
    loadBytes: async () => new ArrayBuffer(784),
    ...over,
  });
  document.body.append(mounted.panel.root, mounted.confirm.root);
  return { mounted, objects, authority, travel, state };
}

const button = (root: HTMLElement, label: string): HTMLButtonElement => {
  const all = [...root.querySelectorAll('button')];
  const found = all.find((node) => node.textContent === label)
    ?? all.find((node) => node.textContent?.startsWith(label) === true);
  if (found === undefined) throw new Error(`no “${label}” control in ${root.className}`);
  return found as HTMLButtonElement;
};

const writes = (calls: { name: string }[]): string[] =>
  calls.filter((call) => ['place', 'move', 'remove', 'undo'].includes(call.name))
    .map((call) => call.name);

const arrow = (code: string) => {
  window.dispatchEvent(new KeyboardEvent('keydown', { code, bubbles: true, cancelable: true }));
};

async function place(h: ReturnType<typeof harness>, motion = false): Promise<void> {
  if (motion) {
    const toggle = h.mounted.panel.root.querySelector<HTMLInputElement>('#object-placement-motion')!;
    toggle.checked = true;
    toggle.dispatchEvent(new Event('change'));
  }
  button(h.mounted.panel.root, 'Place before me').click();
}

beforeEach(() => { document.body.replaceChildren(); });

describe('nothing reaches the authority without a confirmation', () => {
  it('shows the confirmation surface and writes nothing when an object is placed', async () => {
    const h = harness();
    await h.mounted.begin();
    expect(writes(h.authority.calls)).toEqual([]);

    await place(h);
    expect(h.mounted.confirm.root.hidden).toBe(false);
    expect(h.mounted.confirm.root.textContent).toContain('Before anything is written');
    expect(h.mounted.confirm.root.textContent).toContain('Marker pillar');
    expect(writes(h.authority.calls)).toEqual([]);
  });

  it('sends the placement only once confirm is pressed, in the contract’s own fields', async () => {
    const h = harness();
    await h.mounted.begin();
    await place(h);
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['place']));

    const request = h.authority.calls.find((c) => c.name === 'place')!.args[1] as Record<string, unknown>;
    expect(request['assetSha256']).toBe('b'.repeat(64));
    expect(request['regionId']).toBe(String(REGION));
    expect(request['originRole']).toBe('fictional');
    expect(request['behaviour']).toBeNull();
    expect(String(request['objectId'])).toMatch(/^object-/);
    // Region-local millimetres, a step ahead of a visitor looking down region -Z.
    const pose = request['transform'] as Record<string, number>;
    expect(pose['yMm']).toBe(0);
    expect(pose['zMm']).toBeCloseTo(-2500, 0);
    expect(pose['scaleMilli']).toBe(1000);
    for (const value of Object.values(pose)) expect(Number.isSafeInteger(value)).toBe(true);
  });

  it('writes nothing when the confirmation is cancelled', async () => {
    const h = harness();
    await h.mounted.begin();
    await place(h);
    button(h.mounted.confirm.root, 'Cancel').click();
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(writes(h.authority.calls)).toEqual([]);
    await new Promise((resolve) => { setTimeout(resolve, 0); });
    expect(writes(h.authority.calls)).toEqual([]);
  });

  it('carries the chosen motion through in the reviewed parameter names and units', async () => {
    const h = harness();
    await h.mounted.begin();
    await place(h, true);
    expect(h.mounted.confirm.root.textContent).toContain('travelling');
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['place']));
    const request = h.authority.calls.find((c) => c.name === 'place')!.args[1] as Record<string, unknown>;
    expect(request['behaviour']).toEqual({
      behaviourKey: 'motion.bounded-path',
      behaviourVersion: 1,
      // The registry's own defaults, in the registry's own units.
      parameters: { axis: 'x', easing: 'smooth', travel_mm: 1000, period_milliseconds: 4000 },
    });
  });

  it('says a removal CAN be taken back, because the authority stores it rather than executing it', async () => {
    const h = harness({ initial: version({ objects: [objectRecord()], edits: [edit(1, 'add_object')] }) });
    await h.mounted.begin();
    button(h.mounted.panel.root, 'Remove').click();
    // The contract keeps the row with removed = true so undo restores the same identity. Saying
    // "this cannot be undone" here would be the false reversibility claim confirm.ts warns about.
    expect(h.mounted.confirm.root.textContent).toContain('reversible event');
    expect(h.mounted.confirm.root.textContent).not.toContain('This cannot be undone');
    expect(writes(h.authority.calls)).toEqual([]);
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['remove']));
  });

  it('reports a refused write in the confirmation surface and writes nothing more', async () => {
    const h = harness({ initial: version({ objects: [objectRecord()], edits: [edit(1, 'add_object')] }) });
    await h.mounted.begin();
    h.authority.answerWith(new Error('the authority refused'));
    button(h.mounted.panel.root, 'Remove').click();
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() =>
      expect(h.mounted.confirm.root.textContent).toContain('Nothing was written'));
    expect(h.mounted.confirm.root.textContent).toContain('the authority refused');
  });

  it('treats a moved base as a refusal that re-reads, never as an overwrite', async () => {
    const h = harness({ initial: version({ objects: [objectRecord()], edits: [edit(1, 'add_object')] }) });
    await h.mounted.begin();
    h.authority.answerWith({ kind: 'stale', current: version({ objects: [] }) });
    button(h.mounted.panel.root, 'Remove').click();
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() =>
      expect(h.mounted.panel.root.textContent).toContain('This world changed while you were deciding'));
    expect(writes(h.authority.calls)).toEqual(['remove']);
  });

  it('refuses to add to a version whose source was deleted, before staging anything', async () => {
    const h = harness({ initial: version({ sourceInvalidated: true }) });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Place before me').click();
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(writes(h.authority.calls)).toEqual([]);
    expect(h.mounted.panel.root.textContent).toContain('was deleted');
  });

  it('refuses an asset whose reviewed bytes are not in storage, and still lists it', async () => {
    const unavailable = asset({ availability: 'unavailable_asset' });
    const h = harness();
    (h.authority.client as unknown as { connect: unknown }).connect = vi.fn(async () => ({
      assets: [unavailable], version: version(),
    }));
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    // Listed, named, and unselectable: a storage failure must not become a shorter menu.
    expect(h.mounted.panel.root.textContent).toContain('Marker pillar');
    expect(h.mounted.panel.root.textContent).toContain('unavailable_asset');
    expect(button(h.mounted.panel.root, 'Place before me').disabled).toBe(true);
  });
});

describe('a placement that cannot land honestly is refused, not faked', () => {
  it('refuses when the visitor is not standing in a region with reconstructed ground', async () => {
    const h = harness({ footprint: 2, awayBy: 500 });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Place before me').click();
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(writes(h.authority.calls)).toEqual([]);
    expect(h.mounted.panel.root.textContent).toContain('not standing in a region with reconstructed ground');
  });

  it('says so when no region in the world draws a reconstruction at all', async () => {
    const h = harness({ footprint: 2, awayBy: 500 });
    (h.state as unknown as { placedPointMaps: unknown }).placedPointMaps = [];
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Place before me').click();
    expect(h.mounted.panel.root.textContent).toContain('No region in this world draws a reconstruction');
    expect(writes(h.authority.calls)).toEqual([]);
  });

  it('stands the object at the visitor’s feet, and says why, when no cameras were recovered', async () => {
    const h = harness();
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Place before me').click();
    expect(h.mounted.confirm.root.textContent).toContain('standing at your feet');
    expect(h.mounted.confirm.root.textContent).toContain('no recovered cameras');
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['place']));
    const pose = (h.authority.calls.find((c) => c.name === 'place')!.args[1] as Record<string, unknown>)['transform'] as Record<string, number>;
    // Eye at 1.6 m, so feet at 0 mm.
    expect(pose['yMm']).toBe(0);
  });

  it('claims measured ground only when the frame was derived from cameras', async () => {
    const h = harness();
    (h.state as unknown as { displayFrames: Map<string, unknown> }).displayFrames = new Map([
      [SCENE, sceneDisplayFrame(
        [
          { position: [3, 0, 0], forward: [-1, 0, 0], up: [0, 0, 1] },
          { position: [-3, 0, 0], forward: [1, 0, 0], up: [0, 0, 1] },
          { position: [0, 0, 3], forward: [0, 0, -1], up: [0, 0, 1] },
        ],
        [[-4, -4, -4], [4, 4, 4]],
      )],
    ]);
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Place before me').click();
    expect(h.mounted.confirm.root.textContent).toContain('standing on the ground its cameras recovered');
    expect(h.mounted.confirm.root.textContent).not.toContain('at your feet');
  });
});

describe('a nudge is shown at once and written once', () => {
  const withObject = () => harness({
    initial: version({ objects: [objectRecord()], edits: [edit(1, 'add_object')] }),
  });

  it('moves the object in the world and sends nothing until it is saved', async () => {
    const h = withObject();
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Marker pillar').click();

    arrow('ArrowLeft');
    arrow('ArrowLeft');
    arrow('PageUp');
    expect(h.objects.setTransform).toHaveBeenCalledTimes(3);
    expect(writes(h.authority.calls)).toEqual([]);
    expect(h.mounted.panel.root.textContent).toContain('Not saved yet');

    button(h.mounted.panel.root, 'Save this position').click();
    expect(writes(h.authority.calls)).toEqual([]);
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['move']));

    const moved = h.authority.calls.find((c) => c.name === 'move')!.args[2] as Record<string, number>;
    // Two quarter-metre steps left and one up, in whole millimetres.
    expect(moved['xMm']).toBe(1200 - 500);
    expect(moved['yMm']).toBe(250);
    for (const value of Object.values(moved)) expect(Number.isSafeInteger(value)).toBe(true);
  });

  it('puts the object back where it is saved when the nudge is discarded', async () => {
    const h = withObject();
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Marker pillar').click();
    arrow('ArrowRight');
    button(h.mounted.panel.root, 'Put it back').click();
    expect(writes(h.authority.calls)).toEqual([]);
    expect(h.objects.poseOf('object:lantern')).toMatchObject({ xMm: 1200, yMm: 0, zMm: -450 });
    expect(h.mounted.panel.root.textContent).not.toContain('Not saved yet');
  });

  it('ignores the arrow keys while the surface is closed or something is being typed into', async () => {
    const h = withObject();
    await h.mounted.begin();
    arrow('ArrowLeft');
    expect(h.objects.setTransform).not.toHaveBeenCalled();

    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Marker pillar').click();
    const input = document.createElement('input');
    document.body.append(input);
    input.dispatchEvent(new KeyboardEvent('keydown', { code: 'ArrowLeft', bubbles: true }));
    expect(h.objects.setTransform).not.toHaveBeenCalled();
  });

  it('asks for a selection rather than moving nothing', async () => {
    const h = withObject();
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    arrow('ArrowLeft');
    expect(h.mounted.panel.root.textContent).toContain('Choose an object in the list first');
    expect(h.objects.setTransform).not.toHaveBeenCalled();
  });

  it('opens and closes the surface on its own key', async () => {
    const h = harness();
    await h.mounted.begin();
    expect(h.mounted.panel.visible()).toBe(false);
    arrow('KeyP');
    expect(h.mounted.panel.visible()).toBe(true);
    arrow('KeyP');
    expect(h.mounted.panel.visible()).toBe(false);
  });
});

describe('undo is the authority’s, not this surface’s memory of one', () => {
  it('offers nothing to take back on a version with no edits', async () => {
    const h = harness();
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    expect(button(h.mounted.panel.root, 'Take back the last change').disabled).toBe(true);
  });

  it('offers the newest edit no undo already names, and sends undo once confirmed', async () => {
    const h = harness({
      initial: version({
        objects: [objectRecord()],
        editSeq: 3,
        edits: [
          edit(1, 'add_object'),
          edit(2, 'move_object'),
          edit(3, 'undo', { editId: 'edit-3', undoneEditId: 'edit-2' }),
        ],
      }),
    });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    const undo = button(h.mounted.panel.root, 'Take back the last change');
    expect(undo.disabled).toBe(false);
    undo.click();
    // Edit 2 is already named by the undo at 3, and 3 is itself an undo, so 1 is next.
    expect(h.mounted.confirm.root.textContent).toContain('an object you added');
    expect(writes(h.authority.calls)).toEqual([]);
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['undo']));
  });

  it('disables the control when every edit has already been taken back', async () => {
    const h = harness({
      initial: version({
        edits: [edit(1, 'add_object'), edit(2, 'undo', { editId: 'edit-2', undoneEditId: 'edit-1' })],
      }),
    });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    expect(button(h.mounted.panel.root, 'Take back the last change').disabled).toBe(true);
  });
});

describe('a removed object is kept by the authority and not drawn', () => {
  it('draws only what is not removed, and lists only that', async () => {
    const h = harness({
      initial: version({
        objects: [objectRecord(), objectRecord({ objectId: 'object:plinth', removed: true })],
        edits: [edit(1, 'add_object')],
      }),
    });
    await h.mounted.begin();
    expect(h.objects.objectIds).toEqual(['object:lantern']);
    expect(h.mounted.panel.root.textContent).toContain('Marker pillar');
    expect(h.mounted.panel.root.querySelectorAll('.object-placement-item')).toHaveLength(1);
  });
});

describe('running a motion writes nothing, and a refusal is visible', () => {
  it('triggers, stops and resets through the renderer alone', async () => {
    const h = harness({
      initial: version({
        objects: [objectRecord({
          behaviour: {
            behaviourKey: 'motion.bounded-path',
            behaviourVersion: 1,
            parameters: { axis: 'y', easing: 'smooth', travel_mm: 1000, period_milliseconds: 4000 },
          },
        })],
        edits: [edit(1, 'add_object')],
      }),
    });
    await h.mounted.begin();

    for (const [label, expected] of [
      ['Start', 'running'], ['Stop', 'held'], ['Reset', 'at-rest'],
    ] as const) {
      button(h.mounted.panel.root, label).click();
      expect(h.objects.motionStateOf('object:lantern')).toBe(expected);
    }
    expect(writes(h.authority.calls)).toEqual([]);
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(h.mounted.panel.root.textContent).toContain('Back exactly where it was placed');
  });

  it('says why a behaviour this build cannot run did not start, and keeps saying it', async () => {
    const h = harness({
      initial: version({
        objects: [objectRecord({
          behaviour: { behaviourKey: 'motion.orbit', behaviourVersion: 1, parameters: {} },
        })],
        edits: [edit(1, 'add_object')],
      }),
    });
    await h.mounted.begin();
    expect(h.mounted.panel.root.textContent).toContain('motion.orbit@1');
    expect(h.travel.some((e) => e.message.includes('motion.orbit') && e.kind === 'failure')).toBe(true);
    expect(h.mounted.panel.root.textContent).toContain('motion this build cannot run');
    expect(button(h.mounted.panel.root, 'Start').disabled).toBe(true);
  });

  it('reports an object whose bytes could not be verified without losing the rest', async () => {
    let first = true;
    const h = harness({
      initial: version({
        objects: [objectRecord(), objectRecord({ objectId: 'object:plinth' })],
        edits: [edit(1, 'add_object')],
      }),
      loadBytes: async () => {
        if (first) { first = false; throw new Error('asset SHA-256 does not match'); }
        return new ArrayBuffer(784);
      },
    });
    await h.mounted.begin();
    expect(h.travel.some((e) => e.message.includes('SHA-256'))).toBe(true);
    // The second object is still drawn: one failed asset is not a failed world.
    expect(h.objects.objectIds).toEqual(['object:plinth']);
    expect(h.mounted.panel.root.textContent).toContain('SHA-256');
  });
});

describe('the development preview draws and never sends', () => {
  it('places for the session only and says the change was not saved', async () => {
    const h = harness({ noClient: true }, true);
    await h.mounted.begin();
    expect(h.mounted.panel.root.textContent).toContain('not saved');

    await place(h);
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(h.objects.place).toHaveBeenCalled());
    expect(writes(h.authority.calls)).toEqual([]);
    expect(h.mounted.panel.root.textContent).toContain('for this session only');
  });
});

describe('teardown', () => {
  it('stops listening for keys once disposed', async () => {
    const h = harness({
      initial: version({ objects: [objectRecord()], edits: [edit(1, 'add_object')] }),
    });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Marker pillar').click();
    (h.mounted as MountedObjects).dispose();
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'ArrowLeft' }));
    expect(h.objects.setTransform).not.toHaveBeenCalled();
  });
});


describe('opening the first alternate through confirmation', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  const returnedId = '6f1d2c40-0000-7000-8000-000000000020';
  const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

  function emptyWorld() {
    const connect = vi.fn(async (versionId?: string) => ({
      assets: [asset()],
      version: versionId === undefined ? null : version({ versionId }),
    }));
    const placeObject = vi.fn();
    const client = { connect, place: placeObject } as unknown as WorldObjectsClient;
    const fetcher = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetcher);
    return { ...harness({ client }), connect, placeObject, fetcher };
  }

  it('stages bootstrap for an empty world and sends no POST before confirmation or after cancel', async () => {
    const h = emptyWorld();
    h.fetcher.mockResolvedValueOnce(response({ current_topology_digest: STATE }));
    await h.mounted.begin();
    expect(h.mounted.panel.root.textContent).toContain('open an alternate version first');
    await place(h);
    await vi.waitFor(() => expect(h.mounted.confirm.root.hidden).toBe(false));
    expect(h.mounted.confirm.root.textContent).toContain('Open an alternate version');
    expect(h.fetcher).toHaveBeenCalledTimes(1);
    expect(h.fetcher.mock.calls[0]![0]).toBe('https://exulanica.test/world/styles/current');
    expect(h.fetcher.mock.calls[0]![1]?.method).toBeUndefined();
    expect(h.placeObject).not.toHaveBeenCalled();
    button(h.mounted.confirm.root, 'Cancel').click();
    await new Promise((resolve) => { setTimeout(resolve, 0); });
    expect(h.fetcher).toHaveBeenCalledTimes(1);
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(h.connect).toHaveBeenCalledTimes(1);
    h.mounted.dispose();
  });

  it('POSTs exactly the reviewed digest on confirm and reconnects to the returned version ID', async () => {
    const h = emptyWorld();
    h.fetcher
      .mockResolvedValueOnce(response({ current_topology_digest: STATE }))
      .mockResolvedValueOnce(response({ version_id: returnedId }));
    await h.mounted.begin();
    await place(h);
    await vi.waitFor(() => expect(h.mounted.confirm.root.hidden).toBe(false));
    expect(h.fetcher).toHaveBeenCalledTimes(1);
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(h.connect).toHaveBeenLastCalledWith(returnedId));
    const [url, request] = h.fetcher.mock.calls[1]!;
    expect(url).toBe('https://exulanica.test/world/versions/bootstrap');
    expect(request?.method).toBe('POST');
    expect(JSON.parse(String(request?.body))).toEqual({ base_topology_digest: STATE });
    expect(request?.headers).toEqual({ Authorization: 'Bearer token', 'Content-Type': 'application/json' });
    expect(h.fetcher).toHaveBeenCalledTimes(2);
    expect(h.placeObject).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(h.mounted.panel.root.textContent).toContain('Alternate version opened'));
    expect(h.mounted.confirm.root.hidden).toBe(true);
    h.mounted.dispose();
  });

  it('keeps a stale 409 actionable and rereads the digest before another confirmation', async () => {
    const h = emptyWorld();
    const freshDigest = 'f'.repeat(64);
    h.fetcher
      .mockResolvedValueOnce(response({ current_topology_digest: STATE }))
      .mockResolvedValueOnce(response({ code: 'protected_topology_conflict' }, 409))
      .mockResolvedValueOnce(response({ current_topology_digest: freshDigest }))
      .mockResolvedValueOnce(response({ version_id: returnedId }));
    await h.mounted.begin();
    await place(h);
    await vi.waitFor(() => expect(h.mounted.confirm.root.hidden).toBe(false));
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(h.mounted.confirm.root.textContent).toContain('Nothing was written'));
    expect(h.mounted.confirm.root.textContent).toContain('Choose “Place before me” again');
    expect(h.connect).toHaveBeenCalledTimes(1);
    expect(h.fetcher).toHaveBeenCalledTimes(2);
    button(h.mounted.confirm.root, 'Close').click();
    await place(h);
    await vi.waitFor(() => expect(h.mounted.confirm.root.textContent).toContain('Open an alternate version'));
    expect(h.fetcher).toHaveBeenCalledTimes(3);
    expect(h.fetcher.mock.calls[2]![1]?.method).toBeUndefined();
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(h.connect).toHaveBeenLastCalledWith(returnedId));
    expect(JSON.parse(String(h.fetcher.mock.calls[3]![1]?.body))).toEqual({ base_topology_digest: freshDigest });
    expect(h.placeObject).not.toHaveBeenCalled();
    h.mounted.dispose();
  });
});
