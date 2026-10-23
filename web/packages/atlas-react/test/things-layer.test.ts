// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import { readKindDrawing, type LookDrawing } from '../src/playcanvas/things/documents.js';
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

function setup(supportAvailable?: () => boolean, instantiate = instance) {
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
    app, camera, library, regionRoot: (id) => (id === 'a' ? region : null), ringColour: '#f4ff91', instantiate,
    ...(supportAvailable === undefined ? {} : {supportRoot: () => supportAvailable() ? app.root : null}),
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
  it('withholds only bound things, including a previously drawn item, without loading or grounding them', async () => {
    const { app, layer, served } = setup();
    const support = {
      profile: 'exulanica.support-reference/v1' as const, worldId: 'world:generated:test',
      sourceSnapshotId: '00000000-0000-0000-0000-000000000001', receiptSha256: 'a'.repeat(64),
      networkSha256: 'b'.repeat(64), regionId: 'a', surfaceId: 'deck',
    };
    const ordinary = placed(served, 'well-1', 'well');
    const before = placed(served, 'gate-1', 'gate');
    const bound = { ...before, transform: at(1000, 150, 2000), support };
    try {
      await layer.setPlaced([ordinary, before]);
      const prior = layer.figureOf('gate-1')!;
      const destroyed = vi.spyOn(prior, 'destroy');
      const make = vi.spyOn(layer.maker, 'make');
      await layer.setPlaced([ordinary, bound]);
      expect(destroyed).toHaveBeenCalledOnce();
      expect(make).not.toHaveBeenCalled();
      expect(layer.figureOf('gate-1')).toBeNull();
      expect(layer.drawn.map((one) => one.placedId)).toEqual(['well-1']);
      expect(layer.misses.map((one) => [one.placedId, one.reason]))
        .toEqual([['gate-1', 'support_projection_unavailable']]);
      // Repeated snapshots, removal/undo and changing a look cannot restore a grounded proxy.
      await layer.setPlaced([ordinary, bound]);
      await layer.setLook('gate-1', null);
      await layer.setPlaced([ordinary, { ...bound, removed: true }]);
      expect(layer.misses).toEqual([]);
      await layer.setPlaced([ordinary, bound]);
      expect(layer.figureOf('gate-1')).toBeNull();
      expect(make).not.toHaveBeenCalled();
      // An actual authored freeform move removes affinity; that distinct record can draw again.
      await layer.setPlaced([ordinary, before]);
      expect(layer.figureOf('gate-1')).not.toBeNull();
      expect(layer.misses).toEqual([]);
    } finally {
      layer.destroy();
      app.destroy();
    }
  });

  it('draws an admitted passive object in the source frame, independent of ground society omission or pose', async () => {
    let available = true;
    const {app, region, layer, served} = setup(() => available);
    region.setLocalPosition(10, 9, 5); // A translated society arrival must not add nine metres to support height.
    const bound = {...placed(served, 'gate-1', 'gate', at(1000, 3150, 2000)), support: {
      profile: 'exulanica.support-reference/v1' as const, worldId: 'world', sourceSnapshotId: 'snapshot',
      receiptSha256: 'a'.repeat(64), networkSha256: 'b'.repeat(64), regionId: 'a', surfaceId: 'deck',
    }};
    try {
      await layer.setPlaced([bound]);
      const figure = layer.figureOf('gate-1')!;
      expect(figure.root.parent).toBe(app.root);
      expect(figure.root.getPosition().y).toBeCloseTo(3.15);
      const emptySociety = {things: [], inhabitants: []} as unknown as Parameters<ThingLayer['setSociety']>[0];
      layer.setSociety(emptySociety, null); app.fire('update', .016);
      expect(figure.root.enabled).toBe(true);
      expect(layer.pick([1, 4, 8], [0, 0, -1])?.pick.placedId).toBe('gate-1');
      layer.setSociety({...emptySociety!, things: [{id: 'society-gate', placed_id: 'gate-1', kind: bound.kind,
        position_mm: [99000, 99000], height_mm: 0, yaw_microradians: 0, held_by: null}]} as never, null);
      app.fire('update', .016);
      expect(figure.root.getPosition().x).toBe(1); expect(figure.root.getPosition().y).toBeCloseTo(3.15);
      available = false;
      expect(layer.pick([1, 4, 8], [0, 0, -1])).toBeNull();
      app.fire('update', .016); expect(figure.root.enabled).toBe(false);
      await layer.setPlaced([bound]); expect(layer.figureOf('gate-1')).toBeNull();
      expect(layer.misses[0]?.reason).toBe('support_projection_unavailable');
      available = true; await layer.setPlaced([bound]); expect(layer.figureOf('gate-1')).not.toBeNull();
      await layer.setPlaced([{...bound, removed: true}]); expect(layer.figureOf('gate-1')).toBeNull();
      await layer.setPlaced([bound]); expect(layer.figureOf('gate-1')!.root.getPosition().y).toBeCloseTo(3.15);
    } finally {layer.destroy(); app.destroy();}
  });

  it('discards a pending supported figure after source withdrawal', async () => {
    let available = true, release!: () => void, entered = false;
    const pending = new Promise<void>(resolve => {release = resolve;});
    const {app, layer, served} = setup(() => available, async look => {entered = true; await pending; return instance(look);});
    const bound = {...placed(served, 'gate-1', 'gate', at(0, 150, 0)), support: {
      profile: 'exulanica.support-reference/v1' as const, worldId: 'world', sourceSnapshotId: 'snapshot',
      receiptSha256: 'a'.repeat(64), networkSha256: 'b'.repeat(64), regionId: 'a', surfaceId: 'deck',
    }};
    try {
      const loading = layer.setPlaced([bound]);
      await vi.waitFor(() => expect(entered).toBe(true));
      available = false; await layer.setPlaced([bound]); release(); await loading;
      expect(layer.figureOf('gate-1')).toBeNull(); expect(layer.drawn).toEqual([]);
    } finally {release(); layer.destroy(); app.destroy();}
  });

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

  it('hands the crowd the seats of the things it draws, where they stand now, and none of a thing taken away', async () => {
    const { layer, served } = setup();
    await layer.setPlaced([placed(served, 'bench-1', 'bench', at(1000, 0, -2000, 1_570_796)), placed(served, 'gate-1', 'gate', at(3000, 0, 0))]);
    const use = readKindDrawing(thingsJson('kinds/bench.v1.json')).use;
    expect(use?.places?.length).toBeGreaterThan(0);
    expect(layer.seating).toEqual([{ object: { objectId: 'bench-1', assetKey: 'thing:bench-1', ...at(1000, 0, -2000, 1_570_796) }, use }]);
    await layer.setPlaced([placed(served, 'bench-1', 'bench', at(4000, 0, -2000))]);
    expect(layer.seating.map((one) => [one.object.objectId, one.object.xMm, one.object.yawMicroradians])).toEqual([['bench-1', 4000, 0]]);
    await layer.setPlaced([{ ...placed(served, 'bench-1', 'bench'), removed: true }]);
    expect(layer.seating).toEqual([]);
  });

  it('hands no seat of a thing stood on a support, which stands in that support\'s frame', async () => {
    const { layer, served } = setup(() => true);
    const onDeck = { ...placed(served, 'bench-2', 'bench', at(1000, 3150, 2000)), support: {
      profile: 'exulanica.support-reference/v1' as const, worldId: 'world', sourceSnapshotId: 'snapshot',
      receiptSha256: 'a'.repeat(64), networkSha256: 'b'.repeat(64), regionId: 'a', surfaceId: 'deck',
    } };
    await layer.setPlaced([onDeck]);
    expect(layer.figureOf('bench-2')).not.toBeNull();
    expect(layer.seating).toEqual([]);
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
