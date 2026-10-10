// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import type { OwnedSocietyState } from '../src/playcanvas/society/types.js';
import type { LookDrawing } from '../src/playcanvas/things/documents.js';
import { ThingLibrary, type HeldThings } from '../src/playcanvas/things/library.js';
import { ThingLayer, type PlacedThingRecord } from '../src/playcanvas/things/thing-layer.js';
import { canonicalBytes, servedLibrary, sha256 } from './things-fixtures.js';

/*
 * A thing of a kind its workspace keeps (a creature drafted from a person's words) lives in no
 * society: a society of things lists it neither among its things nor among its people. So it stands
 * where its version places it while such a society is drawn, as the things contract says ("stands
 * where it was placed"), and gives way to the crowd only once the state lists it as one of its
 * people. The plan, look and kind here are written by hand in the shapes the server's builder writes.
 */

const buffer = (bytes: Uint8Array): ArrayBuffer => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;

/** The hand-written body's joints at rest, glTF metres. */
const JOINTS: Record<string, [number, number, number]> = { root: [0, 0.5, 0], body: [0, 0.6, 0.2], head: [0, 0.9, 0.5] };

const plan = {
  profile: 'exulanica.body-plan/v1',
  key: 'hill_walker',
  version: 1,
  title: 'hill walker',
  bones: [
    { name: 'root', parent: null, required: true },
    { name: 'body', parent: 'root', required: true },
    { name: 'head', parent: 'body', required: true },
  ],
  limbs: [],
  sockets: [],
  size: { extent_mm: { length: { from: 900, to: 1100 }, width: { from: 300, to: 400 }, height: { from: 800, to: 1000 }, span: { from: 0, to: 0 } } },
  reach_mm: null,
  motions: { required: ['idle', 'walk'], optional: [] },
  moves: ['exulanica-movement/walking/v1'],
  reason: 'Written by hand for this test.',
  origin: { kind: 'drafted' },
};
const planRaw = canonicalBytes(plan);
const look = {
  profile: 'exulanica.look/v1',
  look: 'hill-walker-sketch',
  version: 1,
  label: 'a sketch of its body',
  body_plan: 'hill_walker/v1',
  look_kind: 'rigid_on_bones',
  container: { sha256: 'c'.repeat(64), bytes: 1024, media_type: 'model/gltf-binary' },
  height_mm: 900,
  sampling: 'linear',
};
const lookRaw = canonicalBytes(look);
const kind = {
  profile: 'exulanica.thing-kind/v1',
  kind: 'hill_walker',
  version: 1,
  label: 'hill walker',
  class: 'being',
  body: { plan: 'hill_walker/v1', plan_sha256: sha256(planRaw), extent_mm: { length: 1000, width: 350, height: 900, span: 0 } },
  looks: [{ look: 'hill-walker-sketch', version: 1, sha256: sha256(lookRaw) }],
};
const kindRaw = canonicalBytes(kind);
const kindDigest = sha256(kindRaw);

/** A blocky figure's joints in the T-pose (the things contract's figures), glTF metres. */
const BLOCKY: Record<string, [number, number, number]> = {
  hips: [0, 0.9, 0], spine: [0, 1, 0], chest: [0, 1.15, 0], neck: [0, 1.4, 0], head: [0, 1.45, 0],
  leftUpperLeg: [0.09, 0.86, 0], leftLowerLeg: [0.09, 0.46, 0], leftFoot: [0.09, 0.08, 0],
  rightUpperLeg: [-0.09, 0.86, 0], rightLowerLeg: [-0.09, 0.46, 0], rightFoot: [-0.09, 0.08, 0],
  leftUpperArm: [0.2, 1.35, 0], leftLowerArm: [0.46, 1.35, 0], leftHand: [0.7, 1.35, 0],
  rightUpperArm: [-0.2, 1.35, 0], rightLowerArm: [-0.46, 1.35, 0], rightHand: [-0.7, 1.35, 0],
};

/** A container as the engine's reader would make it: one node a bone at its joint, or one part. */
function instance(drawing: LookDrawing) {
  const model = new pc.Entity(`model:${drawing.look}`);
  if (drawing.lookKind === 'rigid_on_bones') {
    for (const [bone, at] of Object.entries(drawing.look === look.look ? JOINTS : BLOCKY)) {
      const node = new pc.Entity(`bone:${bone}`);
      node.setLocalPosition(...at);
      model.addChild(node);
    }
  } else {
    model.addChild(new pc.Entity(`part:${drawing.look}`));
  }
  return Promise.resolve({ model, tracks: new Map<string, pc.AnimTrack>() });
}

async function setup() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem, pc.LightComponentSystem, pc.CameraComponentSystem];
  app.init(options);
  const region = new pc.Entity('region');
  app.root.addChild(region);
  const camera = new pc.Entity('camera');
  app.root.addChild(camera);
  const served = servedLibrary();
  const answers: Readonly<Record<string, Uint8Array>> = {
    [`kind:${kindDigest}`]: kindRaw, [`look:${sha256(lookRaw)}`]: lookRaw, [`plan:${sha256(planRaw)}`]: planRaw,
  };
  const get = (field: string) => async (digest: string) => {
    const found = answers[`${field}:${digest}`];
    return found === undefined ? null : buffer(found);
  };
  const held: HeldThings = { kind: get('kind'), look: get('look'), container: get('container'), plan: get('plan') };
  const library = new ThingLibrary(served.list, (digest) => served.fetch(digest), held);
  const layer = new ThingLayer({ app, camera, library, regionRoot: () => region, ringColour: '#f4ff91', instantiate: instance });
  const at = (x: number, z: number) => ({ xMm: x, yMm: 0, zMm: z, yawMicroradians: 0, scaleMilli: 1000 });
  await layer.setPlaced([
    { thingId: 'creature-1', kind: { source: 'workspace', sha256: kindDigest }, regionId: 'r', transform: at(3000, 0), removed: false },
    { thingId: 'knight-1', kind: served.kindRef('knight', 1), regionId: 'r', transform: at(0, 0), removed: false },
    { thingId: 'sword-1', kind: served.kindRef('sword', 1), regionId: 'r', transform: at(1000, 0), removed: false },
  ] satisfies PlacedThingRecord[]);
  for (let i = 0; i < 8; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
  return { layer, served };
}

describe('a thing of a kind its workspace keeps, while a society of things is drawn', () => {
  it('stands where its version places it, though the state lists it nowhere', async () => {
    const { layer, served } = await setup();
    expect(layer.misses).toEqual([]);
    const creature = layer.figureOf('creature-1')!;
    expect(creature.root.enabled).toBe(true);
    // A society of things as it is today: the knight one of its people, the sword carried away
    // (not among its things), and the creature in neither list.
    const state: OwnedSocietyState = {
      profile: 'exulanica-society/v7', tick: 3, things: [],
      inhabitants: [{ id: 'p-knight', synthetic: true, position_mm: [0, 0], kind: served.kindRef('knight', 1), came_by: 'placed', placed_id: 'knight-1' }],
    };
    layer.setSociety(state, null);
    expect(creature.root.enabled).toBe(true);
    expect(creature.root.getLocalPosition().x).toBeCloseTo(3, 6);
    // The rule is the creature's alone: the placed knight is the crowd's to draw and the carried
    // sword nobody's, exactly as before.
    expect(layer.figureOf('knight-1')!.root.enabled).toBe(false);
    expect(layer.figureOf('sword-1')!.root.enabled).toBe(false);
    // It can be picked where it stands: a ray down onto it names it.
    expect(layer.pick([3, 5, 0], [0, -1, 0])?.pick.placedId).toBe('creature-1');
  });

  it('gives way to the crowd once the state lists it as one of its people', async () => {
    const { layer, served } = await setup();
    const state: OwnedSocietyState = {
      profile: 'exulanica-society/v7', tick: 3, things: [],
      inhabitants: [{ id: 'p-creature', synthetic: true, position_mm: [3000, 0], kind: served.kindRef('knight', 1), came_by: 'placed', placed_id: 'creature-1' }],
    };
    layer.setSociety(state, null);
    expect(layer.figureOf('creature-1')!.root.enabled).toBe(false);
    // With no society drawn, it stands again.
    layer.setSociety(null, null);
    expect(layer.figureOf('creature-1')!.root.enabled).toBe(true);
  });
});
