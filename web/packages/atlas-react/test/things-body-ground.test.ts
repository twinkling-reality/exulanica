// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { pickReach, type InhabitantIdentity, type SocietyInhabitantSnapshot } from '../src/playcanvas/society/types.js';
import { bodyGround, readBodyMotion } from '../src/playcanvas/things/body-motion.js';
import { ThingCrowdFigures, type ThingCrowdRenderable } from '../src/playcanvas/things/crowd-figures.js';
import { readKindDrawing, type LookDrawing } from '../src/playcanvas/things/documents.js';
import { ThingFigureMaker } from '../src/playcanvas/things/figure-maker.js';
import { ThingLibrary, type HeldThings } from '../src/playcanvas/things/library.js';
import { ringRadius } from '../src/playcanvas/things/ring.js';
import { canonicalBytes, servedLibrary, sha256, until } from './things-fixtures.js';

/*
 * A body whose kind states its extent is picked over the ground it covers and turns no faster than
 * its size lets it; anyone else is picked and turned as before. The bodies are the fixtures this
 * server assembles (`scripts/things/creature_plan_fixtures.py`); what each should be is worked
 * from its recipe's extent and the catalog's turn speed.
 */

const read = (path: string) => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const RECIPES_FILE = read('../../../../tests/fixtures/creatures/creatures.v1.json') as Record<'held_out' | 'development', Record<string, { recipe: { extent_mm: { length: number; width: number; height: number; span: number } } }>>;
const RECIPES = { ...RECIPES_FILE.held_out, ...RECIPES_FILE.development };
const CATALOG = read('../../../../assets/catalogs/thing-presentation/body-motion.v1.json') as { entries: { key: string; value: number }[] };
const MOTION = readBodyMotion(CATALOG);
/** The catalog's turn speed, metres a second, read from the file by its key. */
const END_SPEED = CATALOG.entries.find((entry) => entry.key === 'turn_end_speed_mm_per_second')!.value / 1000;
const fixture = (name: string) => read(`./fixtures/creature-plans/${name}.json`) as { plan: unknown; look: { look: string }; kind: unknown; joints_m: Record<string, [number, number, number]> };
const buffer = (bytes: Uint8Array): ArrayBuffer => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
const settle = async () => {
  for (let i = 0; i < 8; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
};

describe('the extent a drafted kind states', () => {
  it.each(Object.keys(RECIPES).sort())('reaches the drawing of %s as its recipe wrote it', (name) => {
    expect(readKindDrawing(fixture(name).kind).extentMm).toEqual(RECIPES[name]!.recipe.extent_mm);
  });

  it('is absent from a shipped kind, which states none', () => {
    const served = servedLibrary();
    const knight = served.bytes.get(served.kindRef('knight', 1).sha256)!;
    expect(readKindDrawing(JSON.parse(new TextDecoder().decode(knight))).extentMm).toBeNull();
  });
});

describe('the ground a body covers and how fast it turns', () => {
  it('is half its width and half its length, and its ends sweep at the catalog\'s speed', () => {
    // The dragon's recipe: 12 m long, 2.2 m wide. Its ends are 6 m from its middle.
    const dragon = bodyGround(RECIPES['dragon']!.recipe.extent_mm, 1, MOTION);
    expect(dragon.footprint).toEqual({ halfAcross: 1.1, halfAlong: 6 });
    expect(END_SPEED).toBe(3);
    expect(dragon.turnRate).toBeCloseTo(0.5, 12);
    // A quarter turn takes it about 3 seconds, as the catalog's reason says.
    expect(Math.PI / 2 / dragon.turnRate!).toBeCloseTo(3.14, 2);
    // A body half a metre long turns a quarter in about a tenth of a second.
    const small = bodyGround({ length: 500, width: 300 }, 1, MOTION);
    expect(Math.PI / 2 / small.turnRate!).toBeCloseTo(0.13, 2);
    // The spider is wider than it is long: its longer side sets the turn.
    expect(bodyGround(RECIPES['spider']!.recipe.extent_mm, 1, MOTION).turnRate).toBeCloseTo(END_SPEED / 0.7, 12);
    // Drawn at half its size, it covers half the ground and turns twice as fast.
    expect(bodyGround(RECIPES['dragon']!.recipe.extent_mm, 0.5, MOTION)).toEqual({ footprint: { halfAcross: 0.55, halfAlong: 3 }, turnRate: 1 });
    // With no table a body turns at once.
    expect(bodyGround(RECIPES['dragon']!.recipe.extent_mm, 1, null).turnRate).toBeNull();
  });

  it('is picked over its footprint turned as it is drawn, and anyone else by a person\'s box', () => {
    const dragon = { halfAcross: 1.1, halfAlong: 6 };
    expect(pickReach(null, 1.234)).toEqual([0.34, 0.34]);
    // Facing +z: across the world's x, along its z. A quarter turn swaps them.
    expect(pickReach(dragon, 0)).toEqual([1.1, 6]);
    const [x, z] = pickReach(dragon, Math.PI / 2);
    expect(x).toBeCloseTo(6, 12);
    expect(z).toBeCloseTo(1.1, 12);
    // An eighth turn: the box of the turned footprint, (1.1 + 6) / sqrt 2 each way.
    for (const reach of pickReach(dragon, Math.PI / 4)) expect(reach).toBeCloseTo(7.1 / Math.SQRT2, 12);
    // Facing backwards is the same ground.
    for (const [i, reach] of pickReach(dragon, Math.PI).entries()) expect(reach).toBeCloseTo([1.1, 6][i]!, 12);
  });
});

/** A blocky figure's joints in the T-pose (the things contract's figures), glTF metres. */
const BLOCKY: Record<string, [number, number, number]> = {
  hips: [0, 0.9, 0], spine: [0, 1, 0], chest: [0, 1.15, 0], neck: [0, 1.4, 0], head: [0, 1.45, 0],
  leftUpperLeg: [0.09, 0.86, 0], leftLowerLeg: [0.09, 0.46, 0], leftFoot: [0.09, 0.08, 0],
  rightUpperLeg: [-0.09, 0.86, 0], rightLowerLeg: [-0.09, 0.46, 0], rightFoot: [-0.09, 0.08, 0],
  leftUpperArm: [0.2, 1.35, 0], leftLowerArm: [0.46, 1.35, 0], leftHand: [0.7, 1.35, 0],
  rightUpperArm: [-0.2, 1.35, 0], rightLowerArm: [-0.46, 1.35, 0], rightHand: [-0.7, 1.35, 0],
};

/** The engine and a library that holds the dragon as a workspace would, beside the shipped things. */
function world(withTable: boolean) {
  const canvas = document.createElement('canvas');
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
  options.componentSystems = [pc.RenderComponentSystem, pc.LightComponentSystem, pc.CameraComponentSystem];
  app.init(options);
  const dragon = fixture('dragon');
  const planRaw = canonicalBytes(dragon.plan), lookRaw = canonicalBytes(dragon.look), kindRaw = canonicalBytes(dragon.kind);
  const answers: Readonly<Record<string, Uint8Array>> = { [`kind:${sha256(kindRaw)}`]: kindRaw, [`look:${sha256(lookRaw)}`]: lookRaw, [`plan:${sha256(planRaw)}`]: planRaw };
  const get = (field: string) => async (digest: string) => {
    const found = answers[`${field}:${digest}`];
    return found === undefined ? null : buffer(found);
  };
  const held: HeldThings = { kind: get('kind'), look: get('look'), container: get('container'), plan: get('plan') };
  const served = servedLibrary();
  const library = new ThingLibrary(served.list, (digest) => served.fetch(digest), held);
  /** A container as the engine's reader would make it: one node a bone at its joint, or one part. */
  const instantiate = (drawing: LookDrawing) => {
    const model = new pc.Entity(`model:${drawing.look}`);
    if (drawing.look === dragon.look.look) {
      for (const [bone, at] of Object.entries(dragon.joints_m)) {
        const node = new pc.Entity(`bone:${bone}`);
        node.setLocalPosition(...at);
        model.addChild(node);
      }
    } else if (drawing.lookKind === 'rigid_on_bones') {
      for (const [bone, at] of Object.entries(BLOCKY)) {
        const node = new pc.Entity(`bone:${bone}`);
        node.setLocalPosition(...at);
        model.addChild(node);
      }
    } else {
      model.addChild(new pc.Entity(`part:${drawing.look}`));
    }
    return Promise.resolve({ model, tracks: new Map<string, pc.AnimTrack>() });
  };
  const maker = new ThingFigureMaker({ app, library, instantiate, ...(withTable ? { bodyMotion: MOTION } : {}) });
  return { app, maker, served, kindDigest: sha256(kindRaw), dragon };
}

describe('a drafted body\'s figure, made through the page\'s own maker', () => {
  it('is posed by the table it is handed, covers its kind\'s ground and turns at its size\'s rate', async () => {
    const { app, maker, kindDigest } = world(true);
    const made = (await maker.make(app.root, { name: 'thing:dragon', thingId: 'dragon', kind: { source: 'workspace', sha256: kindDigest }, look: null }))!;
    const figure = made.figure;
    expect(figure.footprint).toEqual({ halfAcross: 1.1, halfAlong: 6 });
    expect(figure.turnRate).toBeCloseTo(0.5, 12);
    // Its pick volume is its ground to its look's height (2.6 m), and the ring around it takes it in.
    expect(figure.pickVolume).toEqual({ kind: 'box', min: [-1.1, 0, -6], max: [1.1, 2.6, 6] });
    expect(ringRadius(figure.pickVolume)).toBeCloseTo(Math.hypot(1.1, 6) + 0.12, 12);
    // The table reached the figure: its wings lie folded inside its width (they are drawn spread to 4.3 m).
    figure.pose({ position: [0, 0, 0], facing: 0, deltaSeconds: 0 });
    const tips = (figure.root.find((node) => /^bone:wing1(Left|Right)3$/u.test(node.name)) as pc.Entity[]).map((node) => {
      const at = figure.root.getWorldTransform().clone().invert().transformPoint(node.getPosition());
      return Math.abs(at.x);
    });
    expect(tips).toHaveLength(2);
    for (const x of tips) expect(x).toBeLessThan(1.1);
  });

  it('with no table stands as its look drew it, turns at once and still covers its ground', async () => {
    const { app, maker, kindDigest } = world(false);
    const figure = (await maker.make(app.root, { name: 'thing:dragon', thingId: 'dragon', kind: { source: 'workspace', sha256: kindDigest }, look: null }))!.figure;
    expect(figure.turnRate).toBeNull();
    expect(figure.footprint).toEqual({ halfAcross: 1.1, halfAlong: 6 });
    figure.pose({ position: [0, 0, 0], facing: 0, deltaSeconds: 0 });
    const tips = (figure.root.find((node) => /^bone:wing1(Left|Right)3$/u.test(node.name)) as pc.Entity[]).map((node) => Math.abs(figure.root.getWorldTransform().clone().invert().transformPoint(node.getPosition()).x));
    for (const x of tips) expect(x).toBeCloseTo(4.34, 2);
  });

  it('a shipped figure states no ground and no turn rate, and is picked as it was', async () => {
    const { app, maker, served } = world(true);
    const knight = served.kindRef('knight', 1);
    const figure = (await maker.make(app.root, { name: 'thing:knight', thingId: 'knight', kind: { key: knight.kind, version: knight.version, sha256: knight.sha256 }, look: null }))!.figure;
    expect(figure.footprint ?? null).toBeNull();
    expect(figure.turnRate ?? null).toBeNull();
  });
});

describe('a drafted body walked by the crowd', () => {
  async function walked(withTable: boolean) {
    const { app, maker, kindDigest } = world(withTable);
    const figures = new ThingCrowdFigures({ maker });
    const person: SocietyInhabitantSnapshot = { id: 'p-dragon', synthetic: true, position_mm: [0, 0], kind: { source: 'workspace', sha256: kindDigest }, came_by: 'placed', placed_id: 'creature:1' };
    const identity: InhabitantIdentity = { societyId: 'society', branchId: 'main', inhabitantId: 'p-dragon' };
    const renderable = figures.figureFor(person)!.factory(app.graphicsDevice, app.root, identity, 'near') as ThingCrowdRenderable;
    await settle();
    await until(() => renderable.figure !== null || figures.misses.length > 0, 'the dragon\'s figure');
    expect(figures.misses).toEqual([]);
    expect(renderable.figure).not.toBeNull();
    return renderable;
  }
  const at = (yaw: number, deltaSeconds: number, more: { discontinuity?: boolean } = {}) => ({ position: [0, 0, 0] as const, yaw, deltaSeconds, ...more });

  it('turns toward the way it walks at half a radian a second, the shorter way round, and stops there', async () => {
    const dragon = await walked(true);
    expect(dragon.footprint).toEqual({ halfAcross: 1.1, halfAlong: 6 });
    dragon.pose(at(0, 0, { discontinuity: true }));
    expect(dragon.facing).toBe(0);
    // One second toward a quarter turn: half a radian.
    dragon.pose(at(Math.PI / 2, 1));
    expect(dragon.facing).toBeCloseTo(0.5, 12);
    dragon.pose(at(Math.PI / 2, 0.1));
    expect(dragon.facing).toBeCloseTo(0.55, 12);
    // A frame of no time turns nothing.
    dragon.pose(at(Math.PI / 2, 0));
    expect(dragon.facing).toBeCloseTo(0.55, 12);
    // It arrives, exactly, and stays.
    for (let i = 0; i < 40; i += 1) dragon.pose(at(Math.PI / 2, 0.1));
    expect(dragon.facing).toBe(Math.PI / 2);
    // The shorter way: from a quarter turn to just short of a full turn it turns back through zero.
    dragon.pose(at(2 * Math.PI - 0.2, 1));
    expect(dragon.facing).toBeCloseTo(Math.PI / 2 - 0.5, 12);
    // A jump (the clock scrubbed, a first frame) faces at once.
    dragon.pose(at(3, 0.016, { discontinuity: true }));
    expect(dragon.facing).toBe(3);
  });

  it('turns at once where no table is handed', async () => {
    const dragon = await walked(false);
    dragon.pose(at(0, 0, { discontinuity: true }));
    dragon.pose(at(Math.PI / 2, 0.016));
    expect(dragon.facing).toBe(Math.PI / 2);
  });
});
