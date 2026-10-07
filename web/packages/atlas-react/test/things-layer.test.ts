// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import type { LookDrawing } from '../src/playcanvas/things/documents.js';
import { ThingLibrary } from '../src/playcanvas/things/library.js';
import { ThingLayer, type PlacedThingRecord } from '../src/playcanvas/things/thing-layer.js';
import { servedLibrary, thingsJson } from './things-fixtures.js';

/** A blocky figure's joints in the T-pose (the things contract's figures), glTF metres. */
const BLOCKY: Record<string, [number, number, number]> = {
  hips: [0, 0.9, 0], spine: [0, 1, 0], chest: [0, 1.15, 0], neck: [0, 1.4, 0], head: [0, 1.45, 0],
  leftUpperLeg: [0.09, 0.86, 0], leftLowerLeg: [0.09, 0.46, 0], leftFoot: [0.09, 0.08, 0],
  rightUpperLeg: [-0.09, 0.86, 0], rightLowerLeg: [-0.09, 0.46, 0], rightFoot: [-0.09, 0.08, 0],
  leftUpperArm: [0.2, 1.35, 0], leftLowerArm: [0.46, 1.35, 0], leftHand: [0.7, 1.35, 0],
  rightUpperArm: [-0.2, 1.35, 0], rightLowerArm: [-0.46, 1.35, 0], rightHand: [-0.7, 1.35, 0],
};

/** A container instance as the engine's reader would make one: the scene root's nodes as children. */
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
  const region = new pc.Entity('authored-region:a');
  region.setLocalPosition(10, 0, 5);
  app.root.addChild(region);
  const camera = new pc.Entity('camera');
  camera.addComponent('camera');
  app.root.addChild(camera);
  const served = servedLibrary();
  const library = new ThingLibrary(served.list, (digest) => served.fetch(digest));
  const layer = new ThingLayer({
    app, camera, library, regionRoot: (id) => (id === 'a' ? region : null), ringColour: '#f4ff91', instantiate: instance,
  });
  return { app, region, layer, served };
}

const at = (x: number, y: number, z: number, yawMicroradians = 0) => ({ xMm: x, yMm: y, zMm: z, yawMicroradians, scaleMilli: 1000 });

function placed(served: ReturnType<typeof servedLibrary>, thingId: string, kind: string, transform = at(0, 0, 0), regionId = 'a'): PlacedThingRecord {
  return { thingId, kind: served.kindRef(kind, 1), regionId, transform, removed: false };
}

/** The look kind of a kind's first look, read from the committed documents. */
function firstLookKind(kind: string): string {
  const look = (thingsJson(`kinds/${kind}.v1.json`)['looks'] as { look: string }[])[0]!.look;
  return thingsJson(`looks/${look}.v1.json`)['look_kind'] as string;
}

describe('a version\'s placed things, drawn by their looks', () => {
  it('draws each thing by the look kind of its kind\'s first look, where the version puts it', async () => {
    const { layer, served } = setup();
    await layer.setPlaced([
      placed(served, 'knight-1', 'knight', at(1000, 0, 2000)),
      placed(served, 'spirit-1', 'lantern_spirit', at(-1500, 0, 500)),
      placed(served, 'sword-1', 'sword', at(0, 0, -1000, 1_570_796)),
      placed(served, 'well-1', 'well', at(-4000, 0, -3000)),
      placed(served, 'gate-1', 'gate', at(4500, 0, -6000)),
    ]);
    expect(layer.misses).toEqual([]);
    expect(Object.fromEntries(layer.drawn.map((one) => [one.placedId, one.lookKind]))).toEqual({
      'knight-1': firstLookKind('knight'),
      'spirit-1': firstLookKind('lantern_spirit'),
      'sword-1': firstLookKind('sword'),
      'well-1': firstLookKind('well'),
      'gate-1': firstLookKind('gate'),
    });
    // Region-local millimetres, under the region's own entity at (10, 0, 5).
    const knight = layer.figureOf('knight-1')!.root.getPosition();
    expect([knight.x, knight.y, knight.z]).toEqual([11, 0, 7]);
    // A yaw turns a thing's front (+Z) as it turns an authored object's: a quarter turn faces +X.
    const sword = layer.figureOf('sword-1')!.root;
    const front = sword.getWorldTransform().transformVector(new pc.Vec3(0, 0, 1), new pc.Vec3());
    expect(front.x).toBeCloseTo(1, 5);
    expect(front.z).toBeCloseTo(0, 5);
    // The figure standing in a rigid look faces the same way as an object with the same yaw.
    await layer.setPlaced([placed(served, 'knight-1', 'knight', at(1000, 0, 2000, 1_570_796))]);
    const knightLook = layer.figureOf('knight-1')!.root.children[0] as pc.Entity;
    const knightFront = knightLook.getWorldTransform().transformVector(new pc.Vec3(0, 0, 1), new pc.Vec3()).normalize();
    expect(knightFront.x).toBeCloseTo(1, 5);
  });

  it('draws a light as a light of the look\'s colour and range, floating over its point', async () => {
    const { layer, served } = setup();
    await layer.setPlaced([placed(served, 'spirit-1', 'lantern_spirit', at(0, 0, 0))]);
    const lightDoc = thingsJson('looks/spirit-light.v1.json')['light'] as { colour: string; intensity_milli: number; radius_mm: number };
    const light = layer.figureOf('spirit-1')!.root.findComponent('light') as pc.LightComponent;
    expect(light.type).toBe('omni');
    expect(light.range).toBe(lightDoc.radius_mm / 1000);
    expect(light.intensity).toBe(lightDoc.intensity_milli / 1000);
    expect(light.color.toString(false)).toBe(lightDoc.colour);
    const plan = (thingsJson('body-plans.v1.json')['entries'] as { key: string; reason: string }[]).find((entry) => entry.key === 'bodiless')!;
    expect(plan.reason).toContain('drawn floating');
    expect(light.entity.getPosition().y).toBeGreaterThan(0.9);
    expect(light.entity.getPosition().y).toBeLessThan(1.6);
  });

  it('moves a moved thing without making it again, and takes a removed one away', async () => {
    const { layer, served } = setup();
    await layer.setPlaced([placed(served, 'well-1', 'well', at(0, 0, 0)), placed(served, 'gate-1', 'gate', at(3000, 0, 0))]);
    const well = layer.figureOf('well-1');
    await layer.setPlaced([placed(served, 'well-1', 'well', at(2000, 0, 0)), { ...placed(served, 'gate-1', 'gate'), removed: true }]);
    expect(layer.figureOf('well-1')).toBe(well);
    // The next frame stands it where the version now says.
    (layer as unknown as { step(dt: number): void }).step(1 / 60);
    expect(well!.root.getPosition().x).toBeCloseTo(12, 6);
    expect(layer.figureOf('gate-1')).toBeNull();
    expect(layer.drawn.map((one) => one.placedId)).toEqual(['well-1']);
  });

  it('draws nothing for a thing it cannot draw, and names why', async () => {
    const { layer, served } = setup();
    await layer.setPlaced([
      placed(served, 'far-1', 'well', at(0, 0, 0), 'b'),
      { thingId: 'odd-1', kind: { kind: 'well', version: 1, sha256: '0'.repeat(64) }, regionId: 'a', transform: at(0, 0, 0), removed: false },
    ]);
    expect(layer.drawn).toEqual([]);
    expect(Object.fromEntries(layer.misses.map((miss) => [miss.placedId, miss.reason]))).toEqual({
      'far-1': 'region_not_drawn',
      'odd-1': 'not_in_library',
    });
  });

  it('picks the nearest thing a ray meets and rings it', async () => {
    const { layer, served } = setup();
    await layer.setPlaced([
      placed(served, 'well-1', 'well', at(0, 0, -5000)),
      placed(served, 'knight-1', 'knight', at(0, 0, -2000)),
    ]);
    // From in front of both (world z = 5 + 3), level with a chest, looking along -Z: the knight is nearer.
    const hit = layer.pick([10, 1.2, 8], [0, 0, -1]);
    expect(hit?.pick).toEqual({ placedId: 'knight-1', thingId: null, subjectId: null });
    expect(hit?.distance).toBeGreaterThan(4.5);
    expect(layer.pick([10, 1.2, 8], [0, 0, 1])).toBeNull();
    layer.setPicked(hit!.pick);
    const ring = layer.figureOf('knight-1')!.root.findByName('thing-pick-ring') as pc.Entity;
    expect(ring?.enabled).toBe(true);
    layer.setPicked(null);
    expect(layer.figureOf('knight-1')!.root.findByName('thing-pick-ring')).toBeNull();
  });

  it('draws a thing in another look of its body where it stands, and refuses a look of another body by name', async () => {
    const { layer, served } = setup();
    await layer.setPlaced([placed(served, 'knight-1', 'knight', at(1000, 0, 2000, 1_570_796))]);
    const before = layer.figureOf('knight-1')!;
    const where = before.root.getPosition().clone();
    const lookOf = (look: string) => served.list.looks.find((one) => one.look === look)!;
    const traveller = lookOf('blocky-traveller');
    await layer.setLook('knight-1', { key: traveller.look, version: traveller.version, sha256: traveller.sha256 });
    const after = layer.figureOf('knight-1')!;
    expect(after).not.toBe(before);
    expect(layer.drawn).toEqual([{ placedId: 'knight-1', lookKind: 'rigid_on_bones', look: 'blocky-traveller/v1' }]);
    expect(after.root.getPosition().distance(where)).toBeLessThan(1e-9);
    // A light is a look for a body with no bones: a knight is never drawn in it.
    const light = lookOf('spirit-light');
    await layer.setLook('knight-1', { key: light.look, version: light.version, sha256: light.sha256 });
    expect(layer.drawn).toEqual([]);
    expect(layer.misses.map((miss) => [miss.placedId, miss.reason])).toEqual([['knight-1', 'look_unfit']]);
    await layer.setLook('knight-1', null);
    expect(layer.drawn).toEqual([{ placedId: 'knight-1', lookKind: 'rigid_on_bones', look: 'blocky-knight/v1' }]);
  });
});
