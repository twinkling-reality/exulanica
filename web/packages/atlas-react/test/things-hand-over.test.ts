// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import type { LookDrawing } from '../src/playcanvas/things/documents.js';
import { ThingCrowdFigures, type ThingCrowdRenderable } from '../src/playcanvas/things/crowd-figures.js';
import { RigidOnBonesFigure } from '../src/playcanvas/things/rigid-on-bones.js';
import { ThingLibrary } from '../src/playcanvas/things/library.js';
import { ThingLayer, type PlacedThingRecord } from '../src/playcanvas/things/thing-layer.js';
import type { OwnedSocietyState } from '../src/playcanvas/society/types.js';
import { servedLibrary, thingsJson, until } from './things-fixtures.js';

/*
 * A thing changing hands moves when the later of the two people's drawn walks ends (the rule agreed
 * for THINGS 3b): until then it is in the giver's socket; a pick up and a put down wait on the
 * actor's own walk; a pair already in reach exchanges at once. Where each walk stands is the
 * crowd's to say (`walkEnded`); it is set by hand here.
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

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const identity = (inhabitantId: string) => ({ societyId: 'society', branchId: 'branch', inhabitantId });

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
  const library = new ThingLibrary(served.list, (digest) => served.fetch(digest));
  const layer = new ThingLayer({ app, camera, library, regionRoot: () => region, ringColour: '#f4ff91', instantiate: instance });
  const at = (x: number, z: number) => ({ xMm: x, yMm: 0, zMm: z, yawMicroradians: 0, scaleMilli: 1000 });
  await layer.setPlaced([{ thingId: 'sword-1', kind: served.kindRef('sword', 1), regionId: 'r', transform: at(2000, 0), removed: false } satisfies PlacedThingRecord]);
  const figures = new ThingCrowdFigures({ maker: layer.maker });
  // Two people of the knight's kind, the giver at x 1 m and the taker at x -1 m.
  const people = new Map<string, ThingCrowdRenderable>();
  const person = (id: string, x: number) => {
    const made = figures.figureFor({ id, synthetic: true, position_mm: [x * 1000, 0], kind: served.kindRef('knight', 1) })!
      .factory(device, region, identity(id), 'near') as ThingCrowdRenderable;
    made.pose({ position: [x, 0, 0], deltaSeconds: 1 / 60, yaw: 0 } as never);
    people.set(id, made);
    return made;
  };
  person('giver', 1);
  person('taker', -1);
  for (let i = 0; i < 8; i += 1) await settle();
  await until(() => [...people.values()].every((one) => one.figure !== null), 'the two people\'s figures');
  /** The crowd makes a person again where they stand (as a changed look does): the old figure goes. */
  const remake = async (id: string, x: number) => {
    people.get(id)!.destroy();
    const made = person(id, x);
    for (let i = 0; i < 8; i += 1) await settle();
    await until(() => made.figure !== null, `${id}'s figure, made again`);
    return made;
  };
  const ended = new Map<string, boolean>();
  const walkEnded = (id: string) => ended.get(id) ?? true;
  const step = () => (layer as unknown as { step(dt: number): void }).step(1 / 60);
  const sword = layer.figureOf('sword-1')!;
  const grip = (thingsJson('kinds/sword.v1.json')['offers'] as { key: string; parameters: { grip: { z_mm: number } } }[])
    .find((offer) => offer.key === 'holdable')!.parameters.grip.z_mm / 1000;
  /** Whose right hand the sword's grip is in, or null when it is in neither. */
  const inHandOf = (): string | null => {
    const point = sword.root.getWorldTransform().transformPoint(new pc.Vec3(0, grip, 0), new pc.Vec3());
    for (const [id, renderable] of people) {
      const hand = (renderable.figure as RigidOnBonesFigure).socketPosition('hand.right')!;
      if (point.distance(hand) < 1e-6) return id;
    }
    return null;
  };
  const state = (heldBy: string | null, ground: [number, number] = [5000, 500]): OwnedSocietyState => ({
    profile: 'exulanica-society/v7', tick: 2, inhabitants: [],
    things: [{
      id: 't-sword', placed_id: 'sword-1', kind: served.kindRef('sword', 1),
      position_mm: heldBy === null ? ground : null, yaw_microradians: heldBy === null ? 0 : null, held_by: heldBy,
      ...{ socket: heldBy === null ? null : 'hand.right' },
    }],
  });
  return { layer, figures, sword, ended, walkEnded, step, inHandOf, state, region, remake };
}

describe('a thing changing hands, as the people walk to it', () => {
  it('stays in the giver\'s hand until the later of the two walks ends', async () => {
    const { layer, figures, ended, walkEnded, step, inHandOf, state } = await setup();
    layer.setSociety(state('giver'), figures, walkEnded);
    step();
    expect(inHandOf()).toBe('giver');
    // The next minute hands it over; both are still walking to each other.
    ended.set('giver', false).set('taker', false);
    layer.setSociety(state('taker'), figures, walkEnded);
    step();
    expect(inHandOf()).toBe('giver');
    // The giver has arrived; the taker has not: still the giver's.
    ended.set('giver', true);
    step();
    expect(inHandOf()).toBe('giver');
    // Both have arrived: the taker's.
    ended.set('taker', true);
    step();
    expect(inHandOf()).toBe('taker');
  });

  it('keeps what a visitor carries out in its hand while the crowd draws it walking into its gate', async () => {
    const { layer, figures, walkEnded, step, inHandOf, state, sword } = await setup();
    layer.setSociety(state('taker'), figures, walkEnded);
    step();
    expect(inHandOf()).toBe('taker');
    // The next minute the taker has gone home with the sword: the state lists neither, and the crowd
    // still draws the taker walking back into its gate.
    let walking = true;
    layer.setSociety({ ...state('taker'), tick: 3, things: [] }, figures, walkEnded, (id) => id === 'taker' && walking);
    step();
    expect(inHandOf()).toBe('taker');
    expect(sword.root.enabled).toBe(true);
    // In its gate: gone, and the sword with it.
    walking = false;
    step();
    expect(sword.root.enabled).toBe(false);
  });

  it('keeps it in hand when its holder is made again, as a changed look makes them', async () => {
    const { layer, figures, walkEnded, step, inHandOf, state, sword, remake } = await setup();
    layer.setSociety(state('giver'), figures, walkEnded);
    step();
    expect(inHandOf()).toBe('giver');
    const again = await remake('giver', 1);
    step();
    // The sword is the layer's own drawing, lent to the hand: whole, and in the new figure's hand.
    expect(sword.root.children.length).toBeGreaterThan(0);
    expect(sword.root.parent).toBe(again.figure!.root);
    expect(inHandOf()).toBe('giver');
    expect(sword.root.enabled).toBe(true);
  });

  it('waits for the giver too when the taker arrives first', async () => {
    const { layer, figures, ended, walkEnded, step, inHandOf, state } = await setup();
    layer.setSociety(state('giver'), figures, walkEnded);
    step();
    ended.set('giver', false).set('taker', true);
    layer.setSociety(state('taker'), figures, walkEnded);
    step();
    expect(inHandOf()).toBe('giver');
    ended.set('giver', true);
    step();
    expect(inHandOf()).toBe('taker');
  });

  it('exchanges at once between two already in reach', async () => {
    const { layer, figures, walkEnded, step, inHandOf, state } = await setup();
    layer.setSociety(state('giver'), figures, walkEnded);
    step();
    layer.setSociety(state('taker'), figures, walkEnded);
    step();
    expect(inHandOf()).toBe('taker');
  });

  it('is picked up when the actor\'s walk ends, and put down when it ends again', async () => {
    const { layer, figures, sword, ended, walkEnded, step, inHandOf, state, region } = await setup();
    layer.setSociety(state(null, [5000, 500]), figures, walkEnded);
    step();
    expect(sword.root.getPosition().toArray()).toEqual([5, 0, 0.5]);
    ended.set('giver', false);
    layer.setSociety(state('giver'), figures, walkEnded);
    step();
    // Still on the ground where the last minute left it.
    expect(inHandOf()).toBeNull();
    expect(sword.root.parent).toBe(region);
    expect(sword.root.getPosition().toArray()).toEqual([5, 0, 0.5]);
    ended.set('giver', true);
    step();
    expect(inHandOf()).toBe('giver');
    // Put down at a new point: in the hand until the walk there ends, then on the ground.
    ended.set('giver', false);
    layer.setSociety(state(null, [-3000, 2000]), figures, walkEnded);
    step();
    expect(inHandOf()).toBe('giver');
    ended.set('giver', true);
    step();
    expect(sword.root.parent).toBe(region);
    expect(sword.root.getPosition().toArray()).toEqual([-3, 0, 2]);
  });
});
