// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd } from '../src/playcanvas/society/crowd.js';
import type { OwnedSocietyState, SocietyInhabitantSnapshot } from '../src/playcanvas/society/types.js';
import type { LookDrawing } from '../src/playcanvas/things/documents.js';
import { ThingCrowdFigures } from '../src/playcanvas/things/crowd-figures.js';
import { ThingLayer, type PlacedThingRecord } from '../src/playcanvas/things/thing-layer.js';
import { servedLibrary, until } from './things-fixtures.js';
import { ThingLibrary } from '../src/playcanvas/things/library.js';
import { serveFixturePeople } from './served-people.js';

/*
 * A placed being faces the same way whoever draws it: the layer before a society holds it, and the
 * crowd once one does, until it first walks. The expected facing is the layer's drawing of the same
 * placement, which turns it by the authored objects' rule.
 */

const BLOCKY: Record<string, [number, number, number]> = {
  hips: [0, 0.9, 0], spine: [0, 1, 0], chest: [0, 1.15, 0], neck: [0, 1.4, 0], head: [0, 1.45, 0],
  leftUpperLeg: [0.09, 0.86, 0], leftLowerLeg: [0.09, 0.46, 0], leftFoot: [0.09, 0.08, 0],
  rightUpperLeg: [-0.09, 0.86, 0], rightLowerLeg: [-0.09, 0.46, 0], rightFoot: [-0.09, 0.08, 0],
  leftUpperArm: [0.2, 1.35, 0], leftLowerArm: [0.46, 1.35, 0], leftHand: [0.7, 1.35, 0],
  rightUpperArm: [-0.2, 1.35, 0], rightLowerArm: [-0.46, 1.35, 0], rightHand: [-0.7, 1.35, 0],
};

function instance(look: LookDrawing) {
  const model = new pc.Entity(`model:${look.look}`);
  if (look.lookKind === 'rigid_on_bones') {
    for (const [bone, at] of Object.entries(BLOCKY)) {
      const node = new pc.Entity(`bone:${bone}`);
      node.setLocalPosition(...at);
      model.addChild(node);
    }
  } else {
    model.addChild(new pc.Entity(`part:${look.look}`));
  }
  return Promise.resolve({ model, tracks: new Map<string, pc.AnimTrack>() });
}

function setup() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem, pc.LightComponentSystem, pc.CameraComponentSystem];
  app.init(options);
  serveFixturePeople(app);
  const region = new pc.Entity('region');
  app.root.addChild(region);
  const camera = new pc.Entity('camera');
  app.root.addChild(camera);
  const served = servedLibrary();
  const library = new ThingLibrary(served.list, (digest) => served.fetch(digest));
  const layer = new ThingLayer({ app, camera, library, regionRoot: () => region, ringColour: '#f4ff91', instantiate: instance });
  const societyRoot = new pc.Entity('society');
  region.addChild(societyRoot);
  const crowd = new SocietyCrowd(device, societyRoot, {});
  return { served, layer, crowd };
}

const settle = async () => {
  for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
};
const step = (layer: ThingLayer) => (layer as unknown as { step(dt: number): void }).step(1 / 60);

/** Where a figure's front points on the ground: its -Z at facing 0, turned by its world rotation. */
function front(root: pc.Entity): [number, number] {
  const ahead = root.getRotation().transformVector(new pc.Vec3(0, 0, -1), new pc.Vec3());
  return [ahead.x, ahead.z];
}

async function drawnBothWays(yawMicroradians: number, figuresFirst: boolean) {
  const { served, layer, crowd } = setup();
  const record: PlacedThingRecord = {
    thingId: 'knight-1', kind: served.kindRef('knight', 1), regionId: 'r',
    transform: { xMm: 2000, yMm: 0, zMm: 1000, yawMicroradians, scaleMilli: 1000 }, removed: false,
  };
  await layer.setPlaced([record]);
  step(layer);
  await settle();
  await until(() => layer.figureOf('knight-1') !== null, 'the placed knight\'s figure');
  step(layer);
  const byLayer = front(layer.figureOf('knight-1')!.root);
  const figures = new ThingCrowdFigures({
    maker: layer.maker,
    placedYawOf: (placedId) => (placedId === record.thingId ? record.transform.yawMicroradians : null),
  });
  const knight: SocietyInhabitantSnapshot = {
    id: 'p-knight', synthetic: true, position_mm: [2000, 1000], motion_path_mm: [[2000, 1000]],
    kind: served.kindRef('knight', 1), came_by: 'placed', placed_id: 'knight-1',
  };
  const state: OwnedSocietyState = { profile: 'exulanica-society/v7', society_id: 's', branch_id: 'b', tick: 0, inhabitants: [knight], things: [] };
  // The app may read the first minute before the things' figures are ready, or after.
  if (figuresFirst) crowd.setFigures(figures);
  crowd.set(state, [0, 0]);
  if (!figuresFirst) crowd.setFigures(figures);
  crowd.update(1_000);
  await settle();
  await until(() => figures.figureOf('p-knight') !== null, 'the knight\'s figure in the crowd');
  crowd.update(1_000 + 1000 / 60);
  const byCrowd = front(figures.figureOf('p-knight')!.root);
  return { byLayer, byCrowd, crowd, figures, served, knight };
}

describe('a placed being faces as it was placed, whoever draws it', () => {
  it.each([
    ['yaw 0, figures first', 0, true],
    ['yaw 0, figures after the first minute', 0, false],
    ['a quarter turn and a bit', 1_900_000, true],
    ['a quarter turn and a bit, figures after', 1_900_000, false],
  ])('%s: the crowd at minute 0 faces as the layer drew it', async (_name, yaw, figuresFirst) => {
    const { byLayer, byCrowd } = await drawnBothWays(yaw, figuresFirst);
    expect(byCrowd[0]).toBeCloseTo(byLayer[0], 6);
    expect(byCrowd[1]).toBeCloseTo(byLayer[1], 6);
  });

  it('faces the way it walks once it walks, and keeps that facing', async () => {
    const { byLayer, crowd, figures, knight } = await drawnBothWays(0, true);
    // Placed at yaw 0, its front is toward +Z (the authored objects' rule).
    expect(byLayer[1]).toBeCloseTo(1, 6);
    const walked: OwnedSocietyState = {
      profile: 'exulanica-society/v7', society_id: 's', branch_id: 'b', tick: 1, things: [],
      inhabitants: [{ ...knight, position_mm: [6000, 1000], motion_path_mm: [[2000, 1000], [6000, 1000]] }],
    };
    crowd.set(walked, [0, 0]);
    for (let now = 2_000; now <= 120_000; now += 1000 / 60) crowd.update(now);
    const east = front(figures.figureOf('p-knight')!.root);
    expect(east[0]).toBeCloseTo(1, 6);
    // Asked again for its figure (a look chosen), it is not turned back to its placed yaw.
    crowd.refreshFigures();
    crowd.update(120_100);
    await settle();
    await until(() => figures.figureOf('p-knight') !== null, 'the knight\'s figure, asked again');
    crowd.update(120_200);
    const after = front(figures.figureOf('p-knight')!.root);
    expect(after[0]).toBeCloseTo(1, 6);
  });
});
