// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { CHARACTER_RENDERABLE_TAG } from '../src/playcanvas/character/renderable.js';
import type { LookDrawing } from '../src/playcanvas/things/documents.js';
import { ThingCrowdFigures, ThingCrowdRenderable } from '../src/playcanvas/things/crowd-figures.js';
import { ThingFigureMaker } from '../src/playcanvas/things/figure-maker.js';
import { RigidOnBonesFigure } from '../src/playcanvas/things/rigid-on-bones.js';
import { ThingLibrary } from '../src/playcanvas/things/library.js';
import { ThingLayer, type PlacedThingRecord } from '../src/playcanvas/things/thing-layer.js';
import type { OwnedSocietyState, SocietyInhabitantSnapshot } from '../src/playcanvas/society/types.js';
import { servedLibrary, thingsJson } from './things-fixtures.js';

/** A blocky figure's joints in the T-pose (the things contract's figures), glTF metres. */
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
  const region = new pc.Entity('region');
  app.root.addChild(region);
  const camera = new pc.Entity('camera');
  app.root.addChild(camera);
  const served = servedLibrary();
  const library = new ThingLibrary(served.list, (digest) => served.fetch(digest));
  return { app, device, region, camera, served, library };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const identity = (inhabitantId: string) => ({ societyId: 'society', branchId: 'branch', inhabitantId });

describe('a society\'s things drawn by their looks', () => {
  it('draws a person of a kind by its first look, and one of the world\'s people as today', async () => {
    const { app, device, region, served, library } = setup();
    const figures = new ThingCrowdFigures({ maker: new ThingFigureMaker({ app, library, instantiate: instance }) });
    const knight: SocietyInhabitantSnapshot = { id: 'knight-1', synthetic: true, position_mm: [0, 0], kind: served.kindRef('knight', 1), came_by: 'placed' };
    const villager: SocietyInhabitantSnapshot = { id: 'villager-1', synthetic: true, position_mm: [0, 0], kind: served.kindRef('villager', 1), came_by: 'populated' };
    // The villager's look is the people catalog's: drawn as everyone is.
    const villagerLook = (thingsJson('kinds/villager.v1.json')['looks'] as { look: string }[])[0]!.look;
    expect(thingsJson(`looks/${villagerLook}.v1.json`)['look_kind']).toBe('catalog_person');
    expect(figures.figureFor(villager)).toBeNull();
    const named = figures.figureFor(knight)!;
    const renderable = named.factory(device, region, identity('knight-1'), 'near') as ThingCrowdRenderable;
    // The native character runtime leaves it alone: it draws itself.
    expect(renderable.root.tags.has(CHARACTER_RENDERABLE_TAG)).toBe(true);
    renderable.pose({ position: [3, 0, 4], deltaSeconds: 1 / 60, yaw: Math.PI / 2 } as never);
    expect(renderable.figure).toBeNull();
    for (let i = 0; i < 6; i += 1) await settle();
    // Made after the pose: the last pose is handed over, so it stands where the crowd put it.
    expect(renderable.figure).toBeInstanceOf(RigidOnBonesFigure);
    expect(renderable.figure!.root.getPosition().toArray()).toEqual([3, 0, 4]);
    expect(figures.figureOf('knight-1')).toBe(renderable.figure);
    renderable.destroy();
    expect(figures.figureOf('knight-1')).toBeNull();
  });

  it('names a person whose kind the library does not hold', async () => {
    const { app, device, region, library } = setup();
    const figures = new ThingCrowdFigures({ maker: new ThingFigureMaker({ app, library, instantiate: instance }) });
    const odd: SocietyInhabitantSnapshot = { id: 'odd-1', synthetic: true, position_mm: [0, 0], kind: { kind: 'knight', version: 1, sha256: '0'.repeat(64) } };
    const named = figures.figureFor(odd)!;
    named.factory(device, region, identity('odd-1'), 'near');
    for (let i = 0; i < 6; i += 1) await settle();
    expect(figures.misses.map((miss) => [miss.subjectId, miss.reason])).toEqual([['odd-1', 'not_in_library']]);
  });

  it('hides placed beings for the crowd, stands objects where the state says, and puts a held one in its holder\'s hand', async () => {
    const { app, device, region, camera, served, library } = setup();
    const layer = new ThingLayer({ app, camera, library, regionRoot: () => region, ringColour: '#f4ff91', instantiate: instance });
    const at = (x: number, z: number) => ({ xMm: x, yMm: 0, zMm: z, yawMicroradians: 0, scaleMilli: 1000 });
    const placed = (thingId: string, kind: string, version: number, x: number, z: number): PlacedThingRecord =>
      ({ thingId, kind: served.kindRef(kind, version), regionId: 'r', transform: at(x, z), removed: false });
    await layer.setPlaced([placed('knight-1', 'knight', 1, 0, 0), placed('sword-1', 'sword', 1, 2000, 0), placed('well-1', 'well', 1, -4000, 0)]);
    const figures = new ThingCrowdFigures({ maker: layer.maker });
    const holder = figures.figureFor({ id: 'p-knight', synthetic: true, position_mm: [1000, 1000], kind: served.kindRef('knight', 1) })!
      .factory(device, region, identity('p-knight'), 'near') as ThingCrowdRenderable;
    holder.pose({ position: [1, 0, 1], deltaSeconds: 1 / 60, yaw: 0 } as never);
    for (let i = 0; i < 6; i += 1) await settle();
    // A held thing names its holder's socket (THINGS 3b) and has no position of its own.
    const society = (heldBy: string | null): OwnedSocietyState => ({
      profile: 'exulanica-society/v7', tick: 2, inhabitants: [],
      things: [
        { id: 't-sword', placed_id: 'sword-1', kind: served.kindRef('sword', 1), position_mm: heldBy === null ? [5000, 500] : null, yaw_microradians: heldBy === null ? 0 : null, held_by: heldBy, ...{ socket: heldBy === null ? null : 'hand.right' } },
        { id: 't-well', placed_id: 'well-1', kind: served.kindRef('well', 1), position_mm: [-3000, 2000], yaw_microradians: 0, held_by: null },
      ],
    });
    layer.setSociety(society('p-knight'), figures);
    (layer as unknown as { step(dt: number): void }).step(1 / 60);
    // The placed knight is the society's person now: its standing figure here is not drawn.
    expect(layer.figureOf('knight-1')!.root.enabled).toBe(false);
    // The well stands at the state's point, not the version's.
    expect(layer.figureOf('well-1')!.root.getPosition().toArray()).toEqual([-3, 0, 2]);
    // The sword is in the holder's right hand: its grip at the hand's joint, under the holder.
    const sword = layer.figureOf('sword-1')!;
    expect(sword.root.enabled).toBe(true);
    const hand = (holder.figure as RigidOnBonesFigure).socketPosition('hand.right')!;
    const grip = thingsJson('kinds/sword.v1.json')['offers'] as { key: string; parameters: { grip: { z_mm: number } } }[];
    const gripUp = grip.find((offer) => offer.key === 'holdable')!.parameters.grip.z_mm / 1000;
    const gripPoint = sword.root.getWorldTransform().transformPoint(new pc.Vec3(0, gripUp, 0), new pc.Vec3());
    expect(gripPoint.distance(hand)).toBeLessThan(1e-6);
    // The holder's figure learns its right hand holds something: at the crowd's next pose it carries
    // the sword in front of it (it faces -Z at facing 0), and the sword stays in the hand.
    holder.pose({ position: [1, 0, 1], deltaSeconds: 1 / 60, yaw: 0 } as never);
    const carried = (holder.figure as RigidOnBonesFigure).socketPosition('hand.right')!;
    expect(hand.z - carried.z).toBeGreaterThan(0.15);
    const gripNow = sword.root.getWorldTransform().transformPoint(new pc.Vec3(0, gripUp, 0), new pc.Vec3());
    expect(gripNow.distance(carried)).toBeLessThan(1e-6);
    // Put down: back in the region, where the state puts it.
    layer.setSociety(society(null), figures);
    (layer as unknown as { step(dt: number): void }).step(1 / 60);
    expect(sword.root.parent).toBe(region);
    expect(sword.root.getPosition().toArray()).toEqual([5, 0, 0.5]);
    // Without a society, the version alone: everything stands where it was placed.
    layer.setSociety(null, null);
    (layer as unknown as { step(dt: number): void }).step(1 / 60);
    expect(layer.figureOf('knight-1')!.root.enabled).toBe(true);
    expect(layer.figureOf('well-1')!.root.getPosition().toArray()).toEqual([-4, 0, 0]);
  });
});
