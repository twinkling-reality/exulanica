// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';

/*
 * A static look is drawn at its kind's size: its container scaled uniformly so its longest side is
 * its kind's box's longest side, the side the hands fit to a socket, whatever unit it was made in.
 * The sizes expected are the shipped kinds' boxes, read from the catalogs. A container's drawn size
 * is measured from the corners of its parts as the engine places them, not from the bounds the
 * drawing reads.
 */

const containers = vi.hoisted(() => ({ next: null as null | (() => unknown) }));
vi.mock('../src/playcanvas/scene-objects.js', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  createObjectContainerAsset: vi.fn(async () => containers.next!()),
}));

import { readBodyPlans } from '../src/playcanvas/things/documents.js';
import { ThingFigureMaker } from '../src/playcanvas/things/figure-maker.js';
import { LookRoleFigure, StaticFigure, slotToGltf } from '../src/playcanvas/things/figures.js';
import { ThingLibrary, type HeldThings } from '../src/playcanvas/things/library.js';
import { RigidOnBonesFigure } from '../src/playcanvas/things/rigid-on-bones.js';
import { canonicalBytes, servedLibrary, sha256, thingsJson } from './things-fixtures.js';

type Box = { width: number; depth: number; height: number };
const boxOf = (kind: string): Box => (thingsJson(`kinds/${kind}.json`)['body'] as { box_mm: Box }).box_mm;

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
  return { app, region };
}

/** A container of one box part, `size` metres (width, height, depth), standing on its base at the origin. */
function container(size: readonly [number, number, number]): pc.Entity {
  const model = new pc.Entity('container');
  const part = new pc.Entity('part');
  part.addComponent('render', { type: 'box' });
  part.setLocalScale(size[0], size[1], size[2]);
  part.setLocalPosition(0, size[1] / 2, 0);
  model.addChild(part);
  return model;
}

/** What `entity` draws, from its box parts' corners in the world: the engine's box is a unit cube. */
function drawn(entity: pc.Entity) {
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
  for (const render of entity.findComponents('render') as pc.RenderComponent[]) {
    const matrix = render.entity.getWorldTransform();
    for (const x of [-0.5, 0.5]) for (const y of [-0.5, 0.5]) for (const z of [-0.5, 0.5]) {
      const p = matrix.transformPoint(new pc.Vec3(x, y, z), new pc.Vec3());
      [p.x, p.y, p.z].forEach((v, axis) => { min[axis] = Math.min(min[axis]!, v); max[axis] = Math.max(max[axis]!, v); });
    }
  }
  const size = max.map((v, axis) => v - min[axis]!);
  return { min, max, size, longest: Math.max(...size) };
}

describe('a static look drawn at its kind\'s size', () => {
  it('draws a container made at another size as long as its kind, its shape and its ground contact kept', () => {
    const { region } = setup();
    const box = boxOf('sword.v3');
    // A sword made shorter than its kind, as an imported asset scaled to stand inside the box is.
    const made: [number, number, number] = [0.238, 0.839, 0.062];
    const model = container(made);
    const figure = new StaticFigure(region, model, 'thing:sword', box);
    const seen = drawn(figure.root);
    expect(seen.longest).toBeCloseTo(Math.max(box.width, box.depth, box.height) / 1000, 6);
    expect(seen.size[0]! / seen.size[1]!).toBeCloseTo(made[0] / made[1], 6);
    expect(seen.size[2]! / seen.size[1]!).toBeCloseTo(made[2] / made[1], 6);
    expect(seen.min[1]).toBeCloseTo(0, 6);
    // The kind's box still answers what is picked and where its mark stands.
    expect(figure.standingHeight).toBe(box.height / 1000);
  });

  it('scales about the figure\'s ground contact, so a container whose node stands aside keeps its place in proportion', () => {
    const { region } = setup();
    const box = boxOf('sword.v3');
    const made: [number, number, number] = [0.238, 0.839, 0.062];
    const model = container(made);
    model.setLocalPosition(0.1, 0, 0);
    const figure = new StaticFigure(region, model, 'thing:sword', box);
    const seen = drawn(figure.root);
    const scale = Math.max(box.width, box.depth, box.height) / 1000 / Math.max(...made);
    expect((seen.min[0]! + seen.max[0]!) / 2).toBeCloseTo(0.1 * scale, 6);
    expect(seen.min[1]).toBeCloseTo(0, 6);
  });

  it('fits the longest side whichever way the thing lies, not its height', () => {
    const { region } = setup();
    // A flat thing: its box is widest across, its container taller in proportion than the box.
    const box: Box = { width: 200, depth: 150, height: 40 };
    const figure = new StaticFigure(region, container([0.4, 0.1, 0.3]), 'thing:flat', box);
    const seen = drawn(figure.root);
    expect(seen.longest).toBeCloseTo(0.2, 6);
    expect(seen.size[1]).toBeCloseTo(0.05, 6);
  });

  it('draws a container made at its kind\'s size exactly as it was made', () => {
    const { region } = setup();
    const box = boxOf('lantern.v1');
    const model = container([box.width / 1000, box.height / 1000, box.depth / 1000]);
    const figure = new StaticFigure(region, model, 'thing:lantern', box);
    expect(figure.kindScale).toBe(1);
    expect(model.getLocalScale().toArray()).toEqual([1, 1, 1]);
    expect(model.getLocalPosition().toArray()).toEqual([0, 0, 0]);
  });

  it('leaves a container that draws nothing, and a look role made at its box, as they are', () => {
    const { region } = setup();
    const empty = new pc.Entity('empty');
    expect(new StaticFigure(region, empty, 'thing:empty', boxOf('lantern.v1')).kindScale).toBe(1);
    expect(empty.getLocalScale().toArray()).toEqual([1, 1, 1]);
    const role = new LookRoleFigure(region, 'thing:role', boxOf('well.v2'), new pc.StandardMaterial());
    expect(role.kindScale).toBe(1);
    expect(drawn(role.root).size.map((v) => Math.round(v * 1000))).toEqual([boxOf('well.v2').width, boxOf('well.v2').height, boxOf('well.v2').depth]);
  });

  it('reads a pixel-art look the workspace keeps, samples it nearest and draws it in a hand at its kind\'s size', async () => {
    const { app, region } = setup();
    const served = servedLibrary();
    // A look built from a picture, as a game item's is: static, rigid, sampled by the nearest texel,
    // its container made at the size its kind's box states.
    const bytes = new TextEncoder().encode('glTF stand-in container of a picture made a thing');
    const look = {
      ...thingsJson('looks/primitive-lantern.v1.json'),
      look: 'pixel-lantern', label: 'pixel lantern', sampling: 'nearest',
      container: { sha256: sha256(bytes), bytes: bytes.byteLength, media_type: 'model/gltf-binary' },
    };
    const raw = canonicalBytes(look);
    const named = { key: 'pixel-lantern', version: 1, sha256: sha256(raw) };
    const buffer = (b: Uint8Array) => b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
    const held: HeldThings = {
      kind: async () => null,
      look: async (digest) => (digest === named.sha256 ? buffer(raw) : null),
      container: async (digest) => (digest === named.sha256 ? buffer(bytes) : null),
    };
    const library = new ThingLibrary(served.list, (digest) => served.fetch(digest), held);
    const box = boxOf('lantern.v1');
    const texture = { minFilter: pc.FILTER_LINEAR_MIPMAP_LINEAR, magFilter: pc.FILTER_LINEAR };
    containers.next = () => ({
      resource: {
        instantiateRenderEntity: () => container([box.width / 1000, box.height / 1000, box.depth / 1000]),
        textures: [{ resource: texture }],
        animations: [],
      },
      unload: () => undefined,
    });
    const maker = new ThingFigureMaker({ app, library });
    const kind = served.kindRef('lantern', 1);
    const item = (await maker.make(region, { name: 'thing:carried', thingId: 'carried', kind: { key: kind.kind, version: kind.version, sha256: kind.sha256 }, look: named }))!;
    expect(item.look).toBe('pixel-lantern/v1');
    expect([texture.minFilter, texture.magFilter]).toEqual([pc.FILTER_NEAREST, pc.FILTER_NEAREST]);
    // In a blocky figure's right hand, as the layer hands it over: its grip at the hand, its length the kind's.
    const plans = readBodyPlans(thingsJson('body-plans.v1.json'));
    const holder = new RigidOnBonesFigure(region, blocky(), plans.get('humanoid/v1')!, 'thing:holder', 1700, 1700);
    holder.pose({ position: [1, 0, 2], facing: 0, deltaSeconds: 1 / 60, holding: new Set(['hand.right']) });
    holder.hold('hand.right', item.figure.root, item.kind.grip!);
    const grip = item.kind.grip!;
    const gripAt = item.figure.root.getWorldTransform().transformPoint(new pc.Vec3(...slotToGltf(grip.x_mm, grip.y_mm, grip.z_mm)), new pc.Vec3());
    expect(gripAt.distance(holder.socketPosition('hand.right')!)).toBeLessThan(1e-6);
    expect(drawn(item.figure.root).longest).toBeCloseTo(Math.max(box.width, box.depth, box.height) / 1000, 6);
  });
});

/** A blocky figure's joints in the T-pose (the things contract's figures), glTF metres. */
function blocky(): pc.Entity {
  const joints: Record<string, [number, number, number]> = {
    hips: [0, 0.9, 0], spine: [0, 1, 0], chest: [0, 1.15, 0], neck: [0, 1.4, 0], head: [0, 1.45, 0],
    leftUpperLeg: [0.09, 0.86, 0], leftLowerLeg: [0.09, 0.46, 0], leftFoot: [0.09, 0.08, 0],
    rightUpperLeg: [-0.09, 0.86, 0], rightLowerLeg: [-0.09, 0.46, 0], rightFoot: [-0.09, 0.08, 0],
    leftUpperArm: [0.2, 1.35, 0], leftLowerArm: [0.46, 1.35, 0], leftHand: [0.7, 1.35, 0],
    rightUpperArm: [-0.2, 1.35, 0], rightLowerArm: [-0.46, 1.35, 0], rightHand: [-0.7, 1.35, 0],
  };
  const model = new pc.Entity('blocky');
  for (const [bone, at] of Object.entries(joints)) {
    const node = new pc.Entity(`bone:${bone}`);
    node.setLocalPosition(...at);
    model.addChild(node);
  }
  return model;
}
