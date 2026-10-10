// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import { inhabitantRenderable } from '../src/playcanvas/character/inhabitant.js';
import type { LayeredCharacterRenderable } from '../src/playcanvas/character/renderable.js';
import { SocietyCrowd } from '../src/playcanvas/society/crowd.js';
import type { CrowdRenderableFactory, OwnedSocietyState, SocietyInhabitantSnapshot } from '../src/playcanvas/society/types.js';
import { ThingCrowdFigures } from '../src/playcanvas/things/crowd-figures.js';
import { ThingFigureMaker } from '../src/playcanvas/things/figure-maker.js';
import { ThingLibrary } from '../src/playcanvas/things/library.js';
import { SkinnedFigure } from '../src/playcanvas/things/skinned.js';
import { serveFixturePeople } from './served-people.js';
import { servedLibrary, thingsJson } from './things-fixtures.js';
import { KNIGHT_LOOK, KNIGHT_WALK, knightContainer } from './things-knight-rig.js';

/*
 * A being with nowhere to go stands. Someone with no path to walk this minute is turned by the
 * crowd toward whom they talk with and takes no step for it, and a walker's stride is the ground's
 * alone; a being of a society of things walks a short path at the pace its look declares, arrives,
 * and stands until the next minute is read.
 */

function setup() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem, pc.AnimComponentSystem];
  app.init(options);
  serveFixturePeople(app);
  const root = new pc.Entity('society');
  app.root.addChild(root);
  return { app, device, root };
}

const FRAME_MS = 1000 / 60;
/** The playback's own times at 1x: a minute every 8 s, learnt of up to 2 s late. */
const TIMING = { intervalMs: 8_000, startLagMs: 2_000 };

describe('a catalog person with no path to walk this minute', () => {
  /** One of the people: where they are, the path they walked this minute, and whom they talk with. */
  const person = (id: string, path: readonly (readonly [number, number])[], partner: string | null): SocietyInhabitantSnapshot => ({
    id, synthetic: true, position_mm: path.at(-1)!, motion_path_mm: path,
    ...(partner === null ? {} : {
      action: { kind: 'talk', status: 'active' as const, target_id: null, remaining_ticks: 3, reason: 'talking' },
      goal: { kind: 'talk' as const, target_id: null, reason: 'stopped_to_talk', partner_id: partner },
    }),
  });
  const state = (tick: number, inhabitants: SocietyInhabitantSnapshot[]): OwnedSocietyState => ({
    profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'branch', tick, movement_budget_mm_per_tick: 60_000, inhabitants,
  });

  it('takes no step however the crowd turns them: toward a partner walking by, then toward another', () => {
    const { device, root } = setup();
    // Each person's own catalog renderable, as the crowd makes it, read after every pose it is handed.
    const seen = new Map<string, { ground: number; stride: number; facing: number; arrived: boolean }[]>();
    let crowd: SocietyCrowd | null = null;
    const factory: CrowdRenderableFactory = (d, parent, identity, detail) => {
      const real = inhabitantRenderable(d, parent, identity, detail);
      const read = real as LayeredCharacterRenderable;
      const pose = real.pose.bind(real);
      read.pose = (handed) => {
        pose(handed);
        const list = seen.get(identity.inhabitantId) ?? [];
        seen.set(identity.inhabitantId, list);
        list.push({ ground: read.resolvedSpeed, stride: read.resolvedStrideSpeed, facing: read.facing, arrived: crowd?.walkEnded(identity.inhabitantId) ?? true });
      };
      return real;
    };
    crowd = new SocietyCrowd(device, root, { factory });
    const run = (from: number, to: number) => {
      for (let at = from + FRAME_MS; at <= to; at += FRAME_MS) crowd!.update(at);
    };
    // Ana stands at the middle. Ben starts north-east of her, Cal stands to her west.
    crowd.set(state(0, [person('ana', [[0, 0]], null), person('ben', [[4_000, -3_000]], null), person('cal', [[-3_000, 0]], null)]), [0, 0], { ...TIMING, nowMs: 0 });
    // Minute 1: Ana has no path and talks with Ben, who walks 6 m past her to the south-east.
    crowd.set(state(1, [person('ana', [[0, 0]], 'ben'), person('ben', [[4_000, -3_000], [4_000, 3_000]], 'ana'), person('cal', [[-3_000, 0]], null)]), [0, 0], { ...TIMING, nowMs: 0 });
    seen.clear();
    run(0, 8_000);
    // Minute 2: nobody has a path; Ana now talks with Cal, behind her.
    crowd.set(state(2, [person('ana', [[0, 0]], 'cal'), person('ben', [[4_000, 3_000]], null), person('cal', [[-3_000, 0]], 'ana')]), [0, 0], { ...TIMING, nowMs: 8_000 });
    run(8_000, 16_000);

    const ana = seen.get('ana')!;
    expect(ana.length).toBeGreaterThan(900);
    // She was turned: following Ben from north-east to south-east, then about to face Cal in the west.
    const facings = ana.map((pose) => pose.facing);
    expect(Math.max(...facings) - Math.min(...facings)).toBeGreaterThan(Math.PI / 2);
    // And through all of it she neither moved over the ground nor was drawn a stride.
    for (const [index, pose] of ana.entries()) {
      expect(pose.ground, `pose ${index}`).toBe(0);
      expect(pose.stride, `pose ${index}`).toBe(0);
    }
    // Ben walked, his stride exactly as fast as his ground from the first step, though he set off
    // the opposite way to the one he faced; once his walk had ended he was turned to face Ana and
    // took no step for that either.
    const ben = seen.get('ben')!;
    const walking = ben.filter((pose) => !pose.arrived);
    expect(walking.length).toBeGreaterThan(100);
    for (const [index, pose] of walking.entries()) expect(pose.stride, `walking pose ${index}`).toBe(pose.ground);
    expect(walking.at(-1)!.ground).toBeGreaterThan(1);
    const setOff = walking.slice(0, 30).map((pose) => pose.facing);
    expect(Math.max(...setOff) - Math.min(...setOff)).toBeGreaterThan(1);
    const stood = ben.slice(ben.findIndex((pose) => pose.arrived) + 1);
    expect(stood.length).toBeGreaterThan(300);
    for (const [index, pose] of stood.entries()) expect(pose.stride, `pose ${index} after arriving`).toBe(0);
    const turned = stood.map((pose) => pose.facing);
    expect(Math.max(...turned) - Math.min(...turned)).toBeGreaterThan(0.5);
    crowd.destroy();
  });
});

describe('a rigged being of a society of things', () => {
  it('walks a short path at the pace its look declares, arrives, and stands until the next minute', async () => {
    const { app, device, root } = setup();
    const served = servedLibrary();
    const library = new ThingLibrary(served.list, (digest) => served.fetch(digest));
    const figures = new ThingCrowdFigures({
      maker: new ThingFigureMaker({
        app, library,
        instantiate: (look) => {
          if (look.look !== KNIGHT_LOOK.look) throw new Error(`this test draws only ${KNIGHT_LOOK.look}`);
          return Promise.resolve(knightContainer());
        },
      }),
    });
    const crowd = new SocietyCrowd(device, root);
    crowd.setFigures(figures);
    // The knight's kind lists the rigged look first, and is drawn at the look's own height.
    const kind = thingsJson('kinds/knight.v2.json') as { looks: { look: string }[]; body: { height_mm: { from: number; to: number } } };
    expect(kind.looks[0]!.look).toBe(KNIGHT_LOOK.look);
    expect(KNIGHT_LOOK.heightMm).toBeGreaterThanOrEqual(kind.body.height_mm.from);
    expect(KNIGHT_LOOK.heightMm).toBeLessThanOrEqual(kind.body.height_mm.to);
    const knight = (path: readonly (readonly [number, number])[]): SocietyInhabitantSnapshot => ({
      id: 'knight-1', synthetic: true, position_mm: path.at(-1)!, motion_path_mm: path,
      kind: served.kindRef('knight', 2), came_by: 'placed',
      action: { kind: 'stand', status: 'active', target_id: null, remaining_ticks: 1, reason: 'standing_a_while' },
    });
    const state = (tick: number, path: readonly (readonly [number, number])[]): OwnedSocietyState => ({
      profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'branch', tick, movement_budget_mm_per_tick: 60_000,
      inhabitants: [knight(path)], things: [],
    });
    crowd.set(state(0, [[0, 0]]), [0, 0], { ...TIMING, nowMs: 0 });
    await vi.waitFor(() => expect(figures.figureOf('knight-1')).toBeInstanceOf(SkinnedFigure), { timeout: 2000, interval: 5 });
    const anim = figures.figureOf('knight-1')!.root.findComponent('anim') as pc.AnimComponent;

    // Minute 1 is read at 8 s: a 3 m walk. Spread over the 10 s to the next expected minute it
    // would creep at 0.3 m/s; the look declares 0.504 m/s, so the walk takes 5.95 s.
    crowd.set(state(1, [[0, 0], [3_000, 0]]), [0, 0], { ...TIMING, nowMs: 8_000 });
    let held = crowd.positionOf('knight-1')!;
    const steps: { at: number; step: number; blend: number; cadence: number; activity: string | null }[] = [];
    for (let at = 8_000 + FRAME_MS; at <= 16_000; at += FRAME_MS) {
      crowd.update(at);
      const now = crowd.positionOf('knight-1')!;
      steps.push({ at: at - 8_000, step: Math.hypot(now[0] - held[0], now[1] - held[1]), blend: anim.getFloat('speed'), cadence: anim.speed, activity: crowd.activityOf('knight-1') });
      held = now;
    }
    const walkSeconds = 3 / KNIGHT_WALK;
    expect(walkSeconds).toBeCloseTo(5.952, 3);
    const walking = steps.filter(({ at }) => at > 2 * FRAME_MS && at < walkSeconds * 1000 - FRAME_MS);
    for (const { at, step, activity } of walking) {
      expect(step, `frame at ${at.toFixed(0)} ms`).toBeCloseTo((KNIGHT_WALK * FRAME_MS) / 1000, 9);
      expect(activity).toBeNull();
    }
    // At its declared pace the walk clip plays whole at its own cadence, once the speed it reads has settled.
    for (const { at, blend, cadence } of walking.filter(({ at }) => at > 3_000)) {
      expect(blend, `frame at ${at.toFixed(0)} ms`).toBeCloseTo(KNIGHT_WALK, 6);
      expect(cadence, `frame at ${at.toFixed(0)} ms`).toBeCloseTo(1, 6);
    }
    // Arrived, it stands where it is and is drawn doing what its state says, until the minute ends.
    const arrived = steps.filter(({ at }) => at > walkSeconds * 1000 + FRAME_MS);
    expect(arrived.length).toBeGreaterThan(100);
    for (const { at, step, activity } of arrived) {
      expect(step, `frame at ${at.toFixed(0)} ms`).toBe(0);
      expect(activity).toBe('stand');
    }
    expect(crowd.positionOf('knight-1')).toEqual([3, 0]);
    // A second after arriving no stride is left: the idle clip alone.
    for (const { at, blend, cadence } of arrived.filter(({ at }) => at > walkSeconds * 1000 + 1_000)) {
      expect(blend, `frame at ${at.toFixed(0)} ms`).toBe(0);
      expect(cadence).toBe(1);
    }
    crowd.destroy();
  });
});
