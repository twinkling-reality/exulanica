// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd } from '../src/playcanvas/society/crowd.js';
import { spacingSteps } from '../src/playcanvas/society/spacing.js';
import type { CrowdPose, CrowdRenderableFactory, OwnedSocietyState } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';

/*
 * No two people stand inside each other (DESIGN's T0): any two standing outdoors who are not talking
 * are drawn at least the people spacing apart, each half the shortfall back along the line between
 * them, a step held to the most one may take. Plain arithmetic: recorded 0.5 m apart with a 0.7 m
 * spacing, each stands 0.1 m back; recorded 0.2 m apart, each would need 0.25 m and takes the most,
 * 0.15 m, so they stand 0.5 m apart.
 */
const SPACING = 0.7;
const STEP = 0.15;
const TIMING = { nowMs: 0, intervalMs: 60_000, conversationMetres: 0.9, peopleSpacingMetres: SPACING, spacingStepMetres: STEP };


function setup() {
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

  it('stay at their recorded points when no spacing is handed, and a walker passing is not steered', () => {
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
