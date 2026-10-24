// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd } from '../src/playcanvas/society/crowd.js';
import { spacingSteps, walkingSteps, type Room } from '../src/playcanvas/society/spacing.js';
import type { CrowdFigures } from '../src/playcanvas/society/crowd.js';
import type { CrowdPose, CrowdRenderableFactory, OwnedSocietyState } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';

/*
 * No two people stand inside each other (DESIGN's T0): any two standing outdoors who are not talking
 * are drawn at least the people spacing apart, each half the shortfall back along the line between
 * them, a step held to the most one may take. Plain arithmetic: recorded 0.5 m apart with a 0.7 m
 * spacing, each stands 0.1 m back; recorded 0.2 m apart, each would need 0.25 m and takes the most,
 * 0.15 m, so they stand 0.5 m apart, or the whole 0.25 m where the room behind holds it and a body
 * more. Walkers (T0b): two walking the same way nearer than the walker spacing are drawn apart across
 * their way, each half the shortfall, and a walker passing someone standing within the pass aside is
 * drawn aside of them, the one standing never moved; each held as a stander's step is.
 */
const SPACING = 0.7;
const STEP = 0.15;
const TIMING = { nowMs: 0, intervalMs: 60_000, conversationMetres: 0.9, peopleSpacingMetres: SPACING, spacingStepMetres: STEP };
const APART = 0.7;
const ASIDE = 0.5;
const BODY = 0.25;
const WALKING = { ...TIMING, walkerSpacingMetres: APART, passAsideMetres: ASIDE, bodyDepthMetres: BODY };
/** Room everywhere as far as asked: nothing near. */
const OPEN: Room = (_at, _way, most) => most;


function setup(room: Room | null = null) {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  serveFixturePeople(app);
  const root = new pc.Entity('society');
  app.root.addChild(root);
  const poses = new Map<string, CrowdPose[]>();
  const factory: CrowdRenderableFactory = (_device, parent, identity) => {
    const entity = new pc.Entity(identity.inhabitantId);
    parent.addChild(entity);
    poses.set(identity.inhabitantId, []);
    return {
      root: entity, subject: { kind: 'synthetic-inhabitant', ...identity }, standingHeight: 1.7, facing: 0,
      pose: (pose) => { poses.get(identity.inhabitantId)!.push(pose); entity.setLocalPosition(...(pose.position as [number, number, number])); },
      setVisible: (visible) => { entity.enabled = visible; },
      destroy: () => entity.destroy(),
    };
  };
  const crowd = new SocietyCrowd(device, root, { factory });
  if (room !== null) crowd.setFigures({ figureFor: () => null, openAlong: room } satisfies CrowdFigures);
  const last = (id: string) => poses.get(id)!.at(-1)! as CrowdPose & { yaw?: number };
  let now = 0;
  /** Frames of a 60 Hz display for `seconds`. */
  const run = (seconds: number) => { for (let frame = 0; frame < Math.round(seconds * 60); frame += 1) crowd.update((now += 1000 / 60)); };
  return { crowd, last, run, at: () => now, done: () => { crowd.destroy(); app.destroy(); } };
}

type Path = readonly (readonly [number, number])[];
/** One person of a society of things: where the minute's path ends, and who they talk with, if anyone. */
function person(id: string, path: Path, partner: string | null): OwnedSocietyState['inhabitants'][number] {
  const end = path.at(-1)!;
  const standing = {
    id, synthetic: true as const,
    position_mm: [end[0] * 1000, end[1] * 1000] as const,
    motion_path_mm: path.map(([x, z]) => [x * 1000, z * 1000] as const),
  };
  if (partner === null) return standing;
  return {
    ...standing,
    action: { kind: 'talk', status: 'active' as const, target_id: null, remaining_ticks: 3, reason: 'talking' },
    goal: { kind: 'talk', reason: 'stopped_to_talk', target_id: null, partner_id: partner, duration_ticks: 3 },
  };
}

const state = (tick: number, inhabitants: OwnedSocietyState['inhabitants']): OwnedSocietyState => ({
  profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'branch', tick,
  movement_budget_mm_per_tick: 60_000, inhabitants,
});

describe('the people spacing, worked out', () => {
  const at = (id: string, x: number, z = 0) => ({ id, at: [x, z] as const });
  const near = (step: readonly [number, number] | undefined, x: number, z: number) => {
    expect(step![0]).toBeCloseTo(x, 9);
    expect(step![1]).toBeCloseTo(z, 9);
  };

  it('steps two standing nearer than the spacing half the shortfall apart, along the line between them', () => {
    const steps = spacingSteps([at('a', 10), at('b', 10.5)], SPACING, STEP);
    near(steps.get('a'), -0.1, 0);
    near(steps.get('b'), 0.1, 0);
  });

  it('holds a step to the most one may take, so a body never reaches a wall', () => {
    const steps = spacingSteps([at('a', 10), at('b', 10.2), at('c', 10, 0.1)], SPACING, STEP);
    for (const step of steps.values()) expect(Math.hypot(step[0], step[1])).toBeLessThanOrEqual(STEP + 1e-12);
    // b is pushed away from both a and c: further than one step allows, so it takes exactly the most.
    expect(Math.hypot(...steps.get('b')!)).toBeCloseTo(STEP, 9);
  });

  it('parts two at one point east and west, the lesser id to the west, and leaves anyone far enough alone', () => {
    const steps = spacingSteps([at('m', 3), at('k', 3), at('far', 30)], SPACING, STEP);
    near(steps.get('k'), -0.15, 0);
    near(steps.get('m'), 0.15, 0);
    expect(steps.has('far')).toBe(false);
    expect(spacingSteps([at('a', 0), at('b', 0.1)], 0, STEP).size).toBe(0);
  });
});

describe('walkers across their way, worked out', () => {
  const walker = (id: string, x: number, z: number, way: readonly [number, number] = [1, 0]) => ({ id, at: [x, z] as const, way });
  const still = (id: string, x: number, z: number) => ({ id, at: [x, z] as const });
  const near = (step: readonly [number, number] | undefined, x: number, z: number) => {
    expect(step![0]).toBeCloseTo(x, 9);
    expect(step![1]).toBeCloseTo(z, 9);
  };
  const free = { apart: APART, aside: ASIDE, stepMost: 1, bodyDepth: BODY };

  it('parts two walking the same way nearer than the spacing, each half the shortfall across their way', () => {
    // Both walk east, 0.3 m apart north and south: each steps 0.2 m away from the other.
    const steps = walkingSteps([walker('a', 10, 5), walker('b', 10.1, 5.3)], [], free);
    near(steps.get('a'), 0, -0.2);
    near(steps.get('b'), 0, 0.2);
    // Two on one line part by id, the lesser to their right (south, walking east).
    const one = walkingSteps([walker('m', 3, 1), walker('k', 3.2, 1)], [], free);
    near(one.get('k'), 0, 0.35);
    near(one.get('m'), 0, -0.35);
  });

  it('leaves two walking opposite ways, the spacing apart, or one behind the other, on their lines', () => {
    expect(walkingSteps([walker('a', 10, 5), walker('b', 10, 5.3, [-1, 0])], [], free).size).toBe(0);
    expect(walkingSteps([walker('a', 10, 5), walker('b', 10, 5 + APART)], [], free).size).toBe(0);
    // One behind the other on one line, two body depths or more apart: bodies that do not meet, walking on.
    expect(walkingSteps([walker('a', 10, 5), walker('b', 10 + 2 * BODY + 0.01, 5)], [], free).size).toBe(0);
    expect(walkingSteps([walker('a', 10, 5), walker('b', 10 + 2 * BODY - 0.01, 5)], [], free).size).toBe(2);
    expect(walkingSteps([walker('a', 10, 5), walker('b', 10, 5.3)], [], { ...free, apart: 0, aside: 0 }).size).toBe(0);
  });

  it('steps a walker passing someone standing the whole shortfall aside, away from them, and never the one standing', () => {
    // Walking east, someone standing 0.1 m south of the line just ahead: the walker steps 0.4 m north.
    const steps = walkingSteps([walker('w', 10, 5)], [still('s', 10.2, 5.1)], free);
    near(steps.get('w'), 0, -0.4);
    expect(steps.has('s')).toBe(false);
    // From twice the pass aside ahead until a pass aside behind; not further ahead or once past.
    near(walkingSteps([walker('w', 10, 5)], [still('s', 10 + 2 * ASIDE - 0.01, 5.1)], free).get('w'), 0, -0.4);
    expect(walkingSteps([walker('w', 10, 5)], [still('s', 10 + 2 * ASIDE + 0.01, 5.1)], free).size).toBe(0);
    near(walkingSteps([walker('w', 10, 5)], [still('s', 10 - ASIDE + 0.01, 5.1)], free).get('w'), 0, -0.4);
    expect(walkingSteps([walker('w', 10, 5)], [still('s', 10 - ASIDE - 0.01, 5.1)], free).size).toBe(0);
    // From one standing on the line, to the side with more room: south (their right) where north is tight, and back.
    const tight = (way: number): Room => (_at, w, most) => Math.min(most, w[1] * way > 0 ? 2 : 0.3);
    near(walkingSteps([walker('w', 10, 5)], [still('s', 10.2, 5)], { ...free, room: tight(1) }).get('w'), 0, 0.5);
    near(walkingSteps([walker('w', 10, 5)], [still('s', 10.2, 5)], { ...free, room: tight(-1) }).get('w'), 0, -0.5);
    // T0c: someone 0.1 m south of the line with a wall 0.3 m north of the walker: no room that way for the step and a
    // body, so the walker passes south of them, 0.6 m across, ending the pass aside clear; with room both ways or none
    // said, away from them as before.
    const wall = (_at: readonly [number, number], w: readonly [number, number], most: number) => Math.min(most, w[1] < 0 ? 0.3 : 2);
    near(walkingSteps([walker('w', 10, 5)], [still('s', 10.2, 5.1)], { ...free, room: wall }).get('w'), 0, 0.6);
    near(walkingSteps([walker('w', 10, 5)], [still('s', 10.2, 5.1)], { ...free, room: OPEN }).get('w'), 0, -0.4);
    near(walkingSteps([walker('w', 10, 5)], [still('s', 10.2, 5.1)], free).get('w'), 0, -0.4);
    // Room enough that way for the step and a body (0.7 m): away from them, though the other side has more.
    const enough = (_at: readonly [number, number], w: readonly [number, number], most: number) => Math.min(most, w[1] < 0 ? 0.7 : 2);
    near(walkingSteps([walker('w', 10, 5)], [still('s', 10.2, 5.1)], { ...free, room: enough }).get('w'), 0, -0.4);
    // A wall both ways and the other side no roomier: away from them, held to the most one step takes.
    const narrow = (_at: readonly [number, number], w: readonly [number, number], most: number) => Math.min(most, w[1] < 0 ? 0.3 : 0.2);
    near(walkingSteps([walker('w', 10, 5)], [still('s', 10.2, 5.1)], { ...free, stepMost: STEP, room: narrow }).get('w'), 0, -STEP);
    // One standing a pass aside or more off the line is passed on it.
    expect(walkingSteps([walker('w', 10, 5)], [still('s', 10.2, 5 + ASIDE + 0.01)], free).size).toBe(0);
  });

  it('holds a step to the most one takes where the room is not known, and to the room less a body where it is', () => {
    const at = [walker('w', 10, 5)], stander = [still('s', 10.2, 5.1)];
    near(walkingSteps(at, stander, { ...free, stepMost: STEP }).get('w'), 0, -STEP);
    // 0.5 m open north: the step goes as far as leaves a body's depth, 0.25 m.
    near(walkingSteps(at, stander, { ...free, stepMost: STEP, room: (_a, _w, most) => Math.min(most, 0.5) }).get('w'), 0, -0.25);
    near(walkingSteps(at, stander, { ...free, stepMost: STEP, room: OPEN }).get('w'), 0, -0.4);
  });
});

describe('the people spacing where the room is known', () => {
  const at = (id: string, x: number) => ({ id, at: [x, 0] as const });

  it('takes the whole shortfall past the most one step takes where the room behind holds it and a body', () => {
    const steps = spacingSteps([at('a', 10), at('b', 10.2)], SPACING, STEP, OPEN, BODY);
    expect(steps.get('a')![0]).toBeCloseTo(-0.25, 9);
    expect(steps.get('b')![0]).toBeCloseTo(0.25, 9);
    // 0.3 m open behind each: no more than the most one step takes.
    const tight = spacingSteps([at('a', 10), at('b', 10.2)], SPACING, STEP, (_a, _w, most) => Math.min(most, 0.3), BODY);
    expect(tight.get('a')![0]).toBeCloseTo(-STEP, 9);
  });
});

describe('people standing near each other', () => {
  it('are drawn the spacing apart where recorded nearer, as a step, and their recorded points do not move', () => {
    const { crowd, last, run, done } = setup();
    crowd.set(state(1, [person('west', [[10, 5]], null), person('east', [[10.5, 5]], null)]), [10, 5], TIMING);
    run(2);
    expect(last('west').position[0]).toBeCloseTo(9.9, 9);
    expect(last('east').position[0]).toBeCloseTo(10.6, 9);
    expect(crowd.positionOf('west')).toEqual([10, 5]);
    done();
  });

  it('part only as far as the most one step takes when recorded very near', () => {
    const { crowd, last, run, done } = setup();
    crowd.set(state(1, [person('west', [[10, 5]], null), person('east', [[10.2, 5]], null)]), [10, 5], TIMING);
    run(2);
    expect(last('east').position[0] - last('west').position[0]).toBeCloseTo(0.5, 9);
    done();
  });

  it('part the whole spacing where the room behind each holds the step and a body', () => {
    const { crowd, last, run, done } = setup(OPEN);
    crowd.set(state(1, [person('west', [[10, 5]], null), person('east', [[10.2, 5]], null)]), [10, 5], WALKING);
    run(2);
    expect(last('east').position[0] - last('west').position[0]).toBeCloseTo(SPACING, 9);
    done();
  });

  it('stay at their recorded points when no spacing is handed, and a walker passing is not steered without a pass aside', () => {
    const { crowd, last, run, done } = setup();
    crowd.set(state(1, [person('west', [[10, 5]], null), person('east', [[10.5, 5]], null)]), [10, 5], { nowMs: 0, intervalMs: 60_000 });
    run(2);
    expect(last('west').position[0]).toBeCloseTo(10, 9);
    done();
    const walking = setup();
    // One walks the minute's path past another standing on it: it walks its own line, and the one
    // standing is not pushed by it.
    walking.crowd.set(state(1, [person('walker', [[8, 5]], null), person('stander', [[10.3, 5]], null)]), [10, 5], TIMING);
    walking.run(1);
    walking.crowd.set(state(2, [person('walker', [[8, 5], [12, 5]], null), person('stander', [[10.3, 5]], null)]), [10, 5], { ...TIMING, nowMs: walking.at() });
    // Frame by frame while the walker passes: it keeps its line and the one standing never moves.
    let nearest = Number.POSITIVE_INFINITY;
    for (let frame = 0; frame < 60 * 60; frame += 1) {
      walking.run(1 / 60);
      nearest = Math.min(nearest, Math.abs(walking.last('walker').position[0] - 10.3));
      expect(walking.last('walker').position[2]).toBeCloseTo(5, 9);
      expect(walking.last('stander').position[0]).toBeCloseTo(10.3, 9);
      if (walking.last('walker').position[0] > 11) break;
    }
    expect(nearest).toBeLessThan(0.3);
    walking.done();
  });
});

describe('people walking', () => {
  /** Two walking east from x 8 to 12 on lines `gap` metres apart north and south, frame by frame. */
  function inStep(room: Room | null, gap: number) {
    const walking = setup(room);
    walking.crowd.set(state(1, [person('north', [[8, 5]], null), person('south', [[8, 5 + gap]], null)]), [10, 5], WALKING);
    walking.run(1);
    walking.crowd.set(state(2, [person('north', [[8, 5], [12, 5]], null), person('south', [[8, 5 + gap], [12, 5 + gap]], null)]), [10, 5], { ...WALKING, nowMs: walking.at() });
    const apart: number[] = [];
    for (let frame = 0; frame < 60 * 60; frame += 1) {
      walking.run(1 / 60);
      const [n, s] = [walking.last('north').position, walking.last('south').position];
      if (n[0] > 11.5) break;
      if (n[0] > 9) apart.push(s[2] - n[2]);
    }
    walking.done();
    return apart;
  }

  it('are drawn the walker spacing apart across their way when walking in step nearer, room allowing', () => {
    const apart = inStep(OPEN, 0.2);
    expect(Math.min(...apart.slice(-30))).toBeCloseTo(APART, 2);
    // Where the room is not known each takes no more than the most one step takes.
    expect(Math.max(...inStep(null, 0.2))).toBeCloseTo(0.2 + 2 * STEP, 2);
  });

  it('pass someone standing aside of them, back on their line once past, the one standing never moved', () => {
    // At a person's own pace, and at the faster pace a short minute asks.
    for (const intervalMs of [60_000, 2_000]) {
      const walking = setup(OPEN);
      walking.crowd.set(state(1, [person('walker', [[8, 5]], null), person('stander', [[10.3, 5]], null)]), [10, 5], { ...WALKING, intervalMs });
      walking.run(1);
      walking.crowd.set(state(2, [person('walker', [[8, 5], [14, 5]], null), person('stander', [[10.3, 5]], null)]), [10, 5], { ...WALKING, intervalMs, nowMs: walking.at() });
      let nearest = Number.POSITIVE_INFINITY;
      for (let frame = 0; frame < 60 * 60; frame += 1) {
        walking.run(1 / 60);
        const w = walking.last('walker').position, s = walking.last('stander').position;
        nearest = Math.min(nearest, Math.hypot(w[0] - s[0], w[2] - s[2]));
        expect(s[0]).toBeCloseTo(10.3, 9);
        expect(s[2]).toBeCloseTo(5, 9);
        if (w[0] > 13.5) break;
      }
      // Never nearer than a body's width, centre to centre.
      expect(nearest).toBeGreaterThan(ASIDE - 0.01);
      if (intervalMs === 60_000) expect(walking.last('walker').position[2]).toBeCloseTo(5, 3);
      walking.done();
    }
  });
});
