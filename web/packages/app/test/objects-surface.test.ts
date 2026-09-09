// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  atlasVec3, islandId, localVec3, makeIsland, placement, sceneDisplayFrame,
} from '@exulanica/atlas-core';
import { mountObjects, type MountedObjects, type ObjectsDependencies } from '../src/composition/objects.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import type { AuthoredWorldVersion, WorldObjectsClient } from '../src/world-objects-api.js';

/**
 * The authored-object surface, against a scripted authority.
 *
 * The thing under test is the ORDER: nothing reaches the client until the confirmation surface
 * has been shown and confirmed. So the client here is a script that records every call, and the
 * assertion that matters most in this file is the one that counts zero of them.
 *
 * The renderer is a script too. What the surface owes the renderer is a transform and a control
 * call; what the renderer owes the surface is a refusal it can put on the screen. Neither needs a
 * GPU to be checked, and the container decoding that does is tested where it lives, in
 * `atlas-react/test/scene-objects.test.ts`.
 */

const REGION = islandId('region-volcanic');
const SCENE = 'scene-volcanic-01';

/**
 * The region an object stands in, built the way the scene graph builds one.
 *
 * A hand-written literal is not enough here: `footprintRadiusLocal` is what decides whether the
 * visitor is standing IN this region or merely nearest to it, and a fixture missing it made every
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

const VERSION: AuthoredWorldVersion = Object.freeze({
  worldVersionId: 'current',
  basedOnWorldVersionId: null,
  recordedSha256: 'a'.repeat(64),
  objects: Object.freeze([]),
});

function asset(over: Record<string, unknown> = {}) {
  return {
    assetId: 'standing-lantern',
    label: 'Standing lantern',
    container: 'glb/2.0',
    reference: Object.freeze({
      href: '/world-objects/assets/standing-lantern/bytes',
      contentSha256: 'b'.repeat(64),
      byteSize: 128,
    }),
    origin: 'fictional-source' as const,
    footprint: Object.freeze({ radius: 0.3, height: 1.6 }),
    supportedBehaviours: Object.freeze(['motion.bounded']),
    ...over,
  };
}

function objectRecord(over: Record<string, unknown> = {}) {
  return {
    objectId: 'obj-0001',
    assetId: 'standing-lantern',
    regionId: String(REGION),
    sceneId: SCENE,
    sceneFromObject: Object.freeze([1, 0, 0, 2, 0, 1, 0, 0, 0, 0, 1, -3, 0, 0, 0, 1]),
    origin: 'fictional-source' as const,
    behaviour: null,
    basedOnWorldVersionId: 'current',
    recordedSha256: 'c'.repeat(64),
    ...over,
  };
}

/** The renderer, scripted: it records what it was told to draw and answers what it refuses. */
function runtime() {
  const placed = new Map<string, { transform: readonly number[]; motion: string }>();
  return {
    calls: [] as { name: string; args: unknown[] }[],
    notices: [] as string[],
    get objectIds() { return [...placed.keys()]; },
    motionStateOf: (id: string) => placed.get(id)?.motion ?? null,
    place: vi.fn(async (object: { objectId: string; behaviour: unknown }, bytes: ArrayBuffer, frame: unknown) => {
      void bytes; void frame;
      const behaviour = object.behaviour as { behaviourId: string } | null;
      const supported = behaviour === null || behaviour.behaviourId === 'motion.bounded';
      placed.set(object.objectId, {
        transform: (object as unknown as { sceneFromObjectRowMajor: readonly number[] }).sceneFromObjectRowMajor,
        motion: behaviour === null ? 'none' : supported ? 'at-rest' : 'none',
      });
      return {
        objectId: object.objectId,
        motion: behaviour !== null && supported ? 'attached' as const : 'none' as const,
        notices: supported ? [] : [`“${behaviour!.behaviourId}” is not a supported behaviour.`],
      };
    }),
    remove: vi.fn((id: string) => placed.delete(id)),
    setTransform: vi.fn((id: string, transform: readonly number[]) => {
      const held = placed.get(id);
      if (held === undefined) return false;
      placed.set(id, { ...held, transform });
      return true;
    }),
    control: vi.fn((id: string, action: string) => {
      const held = placed.get(id);
      if (held === undefined) return { ok: false as const, reason: 'That object is not in this world.' };
      if (held.motion === 'none') {
        return { ok: false as const, reason: 'This object carries no supported motion, so there is nothing to run.' };
      }
      placed.set(id, {
        ...held,
        motion: action === 'trigger' ? 'running' : action === 'stop' ? 'held' : 'at-rest',
      });
      return { ok: true as const };
    }),
    transformOf: (id: string) => placed.get(id)?.transform ?? null,
  };
}

/** The authority, scripted: it records every call and answers whatever the test queued. */
function script(initial: AuthoredWorldVersion = VERSION) {
  const calls: { name: string; args: unknown[] }[] = [];
  let current = initial;
  let answer: unknown = null;
  const record = (name: string) => (...args: unknown[]) => {
    calls.push({ name, args });
    if (answer instanceof Error) { const thrown = answer; answer = null; throw thrown; }
    const queued = answer;
    answer = null;
    return Promise.resolve(queued ?? {
      kind: 'recorded',
      receipt: {
        objectId: 'obj-new', worldVersionId: 'current', basedOnWorldVersionId: 'current',
        recordedSha256: 'd'.repeat(64), alreadyRecorded: false,
      },
    });
  };
  return {
    calls,
    setVersion(next: AuthoredWorldVersion) { current = next; },
    answerWith(next: unknown) { answer = next; },
    client: {
      connect: vi.fn(async (id: string) => {
        calls.push({ name: 'connect', args: [id] });
        return { registry: { registryVersion: 1, assets: [asset()] }, version: current };
      }),
      refreshObjects: vi.fn(async () => {
        calls.push({ name: 'refreshObjects', args: [] });
        return current;
      }),
      place: record('place'),
      move: record('move'),
      setBehaviour: record('setBehaviour'),
      remove: record('remove'),
    } as unknown as WorldObjectsClient,
  };
}

function harness(
  over: Partial<ObjectsDependencies> & { readonly noClient?: true; readonly footprint?: number; readonly awayBy?: number } = {},
  previewMode = false,
) {
  const objects = runtime();
  const authority = script();
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
    loadBytes: async () => new ArrayBuffer(128),
    ...over,
  });
  document.body.append(mounted.panel.root, mounted.confirm.root);
  return { mounted, objects, authority, travel, state };
}

const button = (root: HTMLElement, label: string): HTMLButtonElement => {
  const all = [...root.querySelectorAll('button')];
  // Exact first: several controls are one word and must not match a row that merely starts with it.
  const found = all.find((node) => node.textContent === label)
    ?? all.find((node) => node.textContent?.startsWith(label) === true);
  if (found === undefined) throw new Error(`no “${label}” control in ${root.className}`);
  return found as HTMLButtonElement;
};

const writes = (calls: { name: string }[]): string[] =>
  calls.filter((call) => ['place', 'move', 'remove', 'setBehaviour'].includes(call.name))
    .map((call) => call.name);

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
    expect(h.mounted.confirm.root.textContent).toContain('Standing lantern');
    // The whole point of this file.
    expect(writes(h.authority.calls)).toEqual([]);
  });

  it('sends the placement only once confirm is pressed, and re-reads afterwards', async () => {
    const h = harness();
    await h.mounted.begin();
    await place(h);
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['place']));

    const call = h.authority.calls.find((entry) => entry.name === 'place')!;
    const request = call.args[1] as Record<string, unknown>;
    expect(request['assetId']).toBe('standing-lantern');
    expect(request['regionId']).toBe(String(REGION));
    expect(request['sceneId']).toBe(SCENE);
    expect(request['behaviour']).toBeNull();
    expect(request['sceneFromObject']).toHaveLength(16);
    // Placed on the region's ground, a step ahead of a visitor looking down display -Z.
    const transform = request['sceneFromObject'] as number[];
    expect(transform[7]).toBe(0);
    expect(transform[11]).toBeCloseTo(-2.5, 6);
    await vi.waitFor(() => {
      expect(h.authority.calls.some((entry) => entry.name === 'refreshObjects')).toBe(true);
      expect(h.mounted.confirm.root.hidden).toBe(true);
    });
  });

  it('writes nothing when the confirmation is cancelled', async () => {
    const h = harness();
    await h.mounted.begin();
    await place(h);
    button(h.mounted.confirm.root, 'Cancel').click();
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(writes(h.authority.calls)).toEqual([]);

    // And a confirm pressed afterwards has nothing staged to send.
    await new Promise((resolve) => { setTimeout(resolve, 0); });
    expect(writes(h.authority.calls)).toEqual([]);
  });

  it('carries the chosen motion through the confirmation into the request', async () => {
    const h = harness();
    await h.mounted.begin();
    await place(h, true);
    expect(h.mounted.confirm.root.textContent).toContain('moving up and down');
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['place']));
    const request = h.authority.calls.find((entry) => entry.name === 'place')!.args[1] as Record<string, unknown>;
    expect(request['behaviour']).toEqual({
      behaviourId: 'motion.bounded',
      parameters: { axis: 'y', amplitude: 0.35, period: 4 },
    });
  });

  it('says a removal cannot be undone, because re-adding is a different object', async () => {
    const authority = script({ ...VERSION, objects: [objectRecord()] });
    const h = harness({ client: authority.client });
    await h.mounted.begin();
    button(h.mounted.panel.root, 'Remove').click();
    expect(h.mounted.confirm.root.textContent).toContain('This cannot be undone.');
    expect(writes(authority.calls)).toEqual([]);
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(writes(authority.calls)).toEqual(['remove']));
  });

  it('reports a refused write in the confirmation surface and writes nothing more', async () => {
    const authority = script({ ...VERSION, objects: [objectRecord()] });
    const h = harness({ client: authority.client });
    await h.mounted.begin();
    authority.answerWith(new Error('the authority refused'));
    button(h.mounted.panel.root, 'Remove').click();
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() =>
      expect(h.mounted.confirm.root.textContent).toContain('Nothing was written'));
    expect(h.mounted.confirm.root.textContent).toContain('the authority refused');
  });

  it('treats a moved base as a refusal that re-reads, never as an overwrite', async () => {
    const authority = script({ ...VERSION, objects: [objectRecord()] });
    const h = harness({ client: authority.client });
    await h.mounted.begin();
    authority.answerWith({ kind: 'stale', current: { ...VERSION, objects: [] } });
    button(h.mounted.panel.root, 'Remove').click();
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() =>
      expect(h.mounted.panel.root.textContent).toContain('This world changed while you were deciding'));
    expect(writes(authority.calls)).toEqual(['remove']);
    expect(h.mounted.panel.root.textContent).toContain('nothing was written');
  });
});

/**
 * The two defects the browser check found, kept fixed.
 *
 * Both were invisible to every test that existed at the time, and both produced the same symptom:
 * the interface said the placement had worked and the visitor could see nothing.
 */
describe('a placement that cannot land honestly is refused, not faked', () => {
  it('refuses when the visitor is not standing in a region with reconstructed ground', async () => {
    // A region far across the world is still the NEAREST reconstructed region. Reaching it would
    // drop the object onto THAT region's ground, out of sight, and report success.
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
    // The harness supplies no display frames, so every region falls back to the identity, whose
    // y = 0 is the scene's arbitrary origin rather than a floor anyone is standing on.
    expect(h.mounted.confirm.root.textContent).toContain('standing at your feet');
    expect(h.mounted.confirm.root.textContent).toContain('no recovered cameras');
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['place']));
    const request = h.authority.calls.find((c) => c.name === 'place')!.args[1] as Record<string, unknown>;
    // The visitor's eye is at 1.6, so their feet are at 0, which is where it lands.
    expect((request['sceneFromObject'] as number[])[7]).toBeCloseTo(0, 6);
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
  const arrow = (code: string) => {
    window.dispatchEvent(new KeyboardEvent('keydown', { code, bubbles: true, cancelable: true }));
  };

  it('moves the object in the world and sends nothing until it is saved', async () => {
    const authority = script({ ...VERSION, objects: [objectRecord()] });
    const h = harness({ client: authority.client });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Standing lantern').click();

    arrow('ArrowLeft');
    arrow('ArrowLeft');
    arrow('PageUp');
    expect(h.objects.setTransform).toHaveBeenCalledTimes(3);
    expect(writes(authority.calls)).toEqual([]);
    expect(h.mounted.panel.root.textContent).toContain('Not saved yet');

    button(h.mounted.panel.root, 'Save this position').click();
    expect(writes(authority.calls)).toEqual([]);
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(writes(authority.calls)).toEqual(['move']));

    const moved = authority.calls.find((call) => call.name === 'move')!.args[2] as number[];
    expect(moved[3]).toBeCloseTo(2 - 0.5, 6);
    expect(moved[7]).toBeCloseTo(0.25, 6);
  });

  it('puts the object back where it is saved when the nudge is discarded', async () => {
    const authority = script({ ...VERSION, objects: [objectRecord()] });
    const h = harness({ client: authority.client });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Standing lantern').click();
    arrow('ArrowRight');
    button(h.mounted.panel.root, 'Put it back').click();
    expect(writes(authority.calls)).toEqual([]);
    expect(h.objects.transformOf('obj-0001')).toEqual(objectRecord().sceneFromObject);
    expect(h.mounted.panel.root.textContent).not.toContain('Not saved yet');
  });

  it('ignores the arrow keys while the surface is closed or something is being typed into', async () => {
    const authority = script({ ...VERSION, objects: [objectRecord()] });
    const h = harness({ client: authority.client });
    await h.mounted.begin();
    arrow('ArrowLeft');
    expect(h.objects.setTransform).not.toHaveBeenCalled();

    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Standing lantern').click();
    const input = document.createElement('input');
    document.body.append(input);
    input.dispatchEvent(new KeyboardEvent('keydown', { code: 'ArrowLeft', bubbles: true }));
    expect(h.objects.setTransform).not.toHaveBeenCalled();
  });

  it('asks for a selection rather than moving nothing', async () => {
    const authority = script({ ...VERSION, objects: [objectRecord()] });
    const h = harness({ client: authority.client });
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

describe('running a motion writes nothing, and a refusal is visible', () => {
  it('triggers, stops and resets through the renderer alone', async () => {
    const authority = script({
      ...VERSION,
      objects: [objectRecord({
        behaviour: { behaviourId: 'motion.bounded', parameters: { axis: 'y', amplitude: 1, period: 4 } },
      })],
    });
    const h = harness({ client: authority.client });
    await h.mounted.begin();

    for (const [label, expected] of [
      ['Start', 'running'], ['Stop', 'held'], ['Reset', 'at-rest'],
    ] as const) {
      button(h.mounted.panel.root, label).click();
      expect(h.objects.motionStateOf('obj-0001')).toBe(expected);
    }
    expect(writes(authority.calls)).toEqual([]);
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(h.mounted.panel.root.textContent).toContain('Back exactly where it was placed');
  });

  it('says why an unsupported behaviour did not run, on the object and on the status line', async () => {
    const authority = script({
      ...VERSION,
      objects: [objectRecord({ behaviour: { behaviourId: 'motion.orbit', parameters: {} } })],
    });
    const h = harness({ client: authority.client });
    await h.mounted.begin();
    // Refused at placement, and the refusal stays on the object rather than scrolling away.
    expect(h.mounted.panel.root.textContent).toContain('motion.orbit');
    expect(h.travel.some((entry) => entry.message.includes('motion.orbit') && entry.kind === 'failure'))
      .toBe(true);
    expect(h.mounted.panel.root.textContent).toContain('motion not supported here');

    // And refused again when a person actually presses something.
    const start = button(h.mounted.panel.root, 'Start');
    expect(start.disabled).toBe(true);
  });

  it('reports an object whose bytes could not be verified without losing the rest', async () => {
    const authority = script({
      ...VERSION,
      objects: [objectRecord(), objectRecord({ objectId: 'obj-0002' })],
    });
    let first = true;
    const h = harness({
      client: authority.client,
      loadBytes: async () => {
        if (first) { first = false; throw new Error('asset SHA-256 does not match'); }
        return new ArrayBuffer(128);
      },
    });
    await h.mounted.begin();
    expect(h.travel.some((entry) => entry.message.includes('SHA-256'))).toBe(true);
    // The second object is still drawn: one failed asset is not a failed world.
    expect(h.objects.objectIds).toEqual(['obj-0002']);
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
    const authority = script({ ...VERSION, objects: [objectRecord()] });
    const h = harness({ client: authority.client });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Standing lantern').click();
    (h.mounted as MountedObjects).dispose();
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'ArrowLeft' }));
    expect(h.objects.setTransform).not.toHaveBeenCalled();
  });
});
