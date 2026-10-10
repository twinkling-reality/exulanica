// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { CHARACTER_CATALOG } from '../src/playcanvas/character/catalog-data.js';
import { farAppearance } from '../src/playcanvas/character/far.js';
import { inhabitantLookOf } from '../src/playcanvas/character/inhabitant.js';
import { SocietyCrowd } from '../src/playcanvas/society/crowd.js';
import type { CrowdPose, CrowdRenderableFactory, OwnedSocietyState } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';

/*
 * Two people who stand talking are drawn a conversation apart, however near the society recorded
 * them. The distances here are plain arithmetic on the states: recorded 0.4 m apart and drawn 0.9 m
 * apart, each stands (0.9 - 0.4) / 2 = 0.25 m back along the line between them, about the point
 * midway between their recorded points, which does not move.
 */
const CONVERSATION = 0.9;
const TIMING = { nowMs: 0, intervalMs: 60_000, conversationMetres: CONVERSATION };

/** A person's own walking pace, metres a second, from the people catalog and never from the crowd. */
const paceOf = (id: string) => {
  const appearance = farAppearance(CHARACTER_CATALOG, inhabitantLookOf(CHARACTER_CATALOG, id));
  const base = CHARACTER_CATALOG.families.flatMap((family) => family.bases).find((one) => one.baseId === appearance.baseId)!;
  return (base.clips.walk.speedMillimetresPerSecond / base.restHeightMillimetres) * appearance.heightMetres;
};

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

/** Which way a yaw looks in the plan, east and south: forward is (-sin, -cos). */
const looks = (yaw: number) => [-Math.sin(yaw), -Math.cos(yaw)] as const;

describe('two people who stand talking', () => {
  it('are drawn a conversation apart, each a step back, facing each other, where they were recorded nearer', () => {
    const { crowd, last, run, done } = setup();
    // Recorded 0.4 m apart on an east-west line, at 10.0 and 10.4 m east.
    crowd.set(state(1, [person('west', [[10, 5]], 'east'), person('east', [[10.4, 5]], 'west')]), [10, 5], TIMING);
    run(2);
    expect(last('west').position[0]).toBeCloseTo(9.75, 9);
    expect(last('east').position[0]).toBeCloseTo(10.65, 9);
    expect(last('west').position[2]).toBeCloseTo(5, 9);
    expect(last('east').position[2]).toBeCloseTo(5, 9);
    expect(last('east').position[0] - last('west').position[0]).toBeCloseTo(CONVERSATION, 9);
    // Each faces the other: west looks east, east looks west.
    expect(looks(last('west').yaw!)[0]).toBeCloseTo(1, 9);
    expect(looks(last('east').yaw!)[0]).toBeCloseTo(-1, 9);
    // Presentation only: the recorded points are what they were.
    expect(crowd.positionOf('west')).toEqual([10, 5]);
    expect(crowd.positionOf('east')).toEqual([10.4, 5]);
    done();
  });

  it('take the step at their own walking pace, never as a jump', () => {
    const { crowd, last, run, done } = setup();
    crowd.set(state(1, [person('west', [[10, 5]], 'east'), person('east', [[10.4, 5]], 'west')]), [10, 5], TIMING);
    run(1 / 60);
    const first = last('west').position[0];
    run(1 / 60);
    // Between two frames of a 60 Hz display they move a sixtieth of their own pace, and after both
    // they are still short of the whole quarter metre.
    expect(first - last('west').position[0]).toBeCloseTo(paceOf('west') / 60, 6);
    expect(10 - last('west').position[0]).toBeGreaterThan(0);
    expect(10 - last('west').position[0]).toBeLessThan(0.25);
    run(1);
    expect(last('west').position[0]).toBeCloseTo(9.75, 9);
    done();
  });

  it('stay where they were recorded when that is already a conversation apart, or when no distance is handed', () => {
    const far = setup();
    far.crowd.set(state(1, [person('west', [[10, 5]], 'east'), person('east', [[11.21, 5]], 'west')]), [10, 5], TIMING);
    far.run(2);
    expect(far.last('west').position[0]).toBe(10);
    expect(far.last('east').position[0]).toBe(11.21);
    far.done();
    const silent = setup();
    silent.crowd.set(state(1, [person('west', [[10, 5]], 'east'), person('east', [[10.4, 5]], 'west')]), [10, 5], { nowMs: 0, intervalMs: 60_000 });
    silent.run(2);
    expect(silent.last('west').position[0]).toBe(10);
    expect(silent.last('east').position[0]).toBe(10.4);
    silent.done();
  });

  it('part east and west when they were recorded at one point', () => {
    const { last, run, crowd, done } = setup();
    crowd.set(state(1, [person('alba', [[10, 5]], 'bram'), person('bram', [[10, 5]], 'alba')]), [10, 5], TIMING);
    run(2);
    // The lesser id stands to the west.
    expect(last('alba').position[0]).toBeCloseTo(10 - CONVERSATION / 2, 9);
    expect(last('bram').position[0]).toBeCloseTo(10 + CONVERSATION / 2, 9);
    expect(last('alba').position[2]).toBeCloseTo(5, 9);
    done();
  });

  it('step along the line between them whichever way it runs', () => {
    const { last, run, crowd, done } = setup();
    // 0.5 m apart along a 3-4-5 line: (0.3, 0.4). Each steps 0.2 m back: (0.12, 0.16).
    crowd.set(state(1, [person('one', [[10, 5]], 'two'), person('two', [[10.3, 5.4]], 'one')]), [10, 5], TIMING);
    run(2);
    expect(last('one').position[0]).toBeCloseTo(9.88, 9);
    expect(last('one').position[2]).toBeCloseTo(4.84, 9);
    expect(last('two').position[0]).toBeCloseTo(10.42, 9);
    expect(last('two').position[2]).toBeCloseTo(5.56, 9);
    done();
  });

  it('wait for the one still walking up, and leave alone someone whose partner talks with another', () => {
    const { crowd, last, run, done } = setup();
    // The east one is recorded walking 6 m to stand 0.4 m from the west one: about five seconds at any pace.
    crowd.set(state(0, [person('west', [[10, 5]], null), person('east', [[16.4, 5]], null), person('third', [[10, 5.3]], null)]), [10, 5], TIMING);
    crowd.set(state(1, [
      person('west', [[10, 5]], 'east'), person('east', [[16.4, 5], [10.4, 5]], 'west'),
      // Names the west one, who names somebody else: no conversation is theirs.
      person('third', [[10, 5.3]], 'west'),
    ]), [10, 5], TIMING);
    run(1);
    expect(last('west').position[0]).toBe(10);
    expect(last('third').position).toEqual([10, 0, 5.3]);
    run(9);
    expect(last('west').position[0]).toBeCloseTo(9.75, 9);
    expect(last('east').position[0]).toBeCloseTo(10.65, 9);
    expect(last('third').position).toEqual([10, 0, 5.3]);
    done();
  });

  it('walk on from where they stood when the talk is over, back onto the recorded path', () => {
    const { crowd, last, run, at, done } = setup();
    crowd.set(state(1, [person('west', [[10, 5]], 'east'), person('east', [[10.4, 5]], 'west')]), [10, 5], TIMING);
    run(2);
    expect(last('west').position[0]).toBeCloseTo(9.75, 9);
    // The next minute the west one walks 20 m south with nothing to do; the other stays.
    crowd.set(state(2, [person('west', [[10, 5], [10, 25]], null), person('east', [[10.4, 5]], null)]), [10, 5], { ...TIMING, nowMs: at() });
    run(1 / 60);
    // No jump back to the recorded point: within a frame's walk of where they stood.
    expect(Math.abs(last('west').position[0] - 9.75)).toBeLessThan(0.05);
    run(3);
    // On the recorded path again, which runs along 10 m east.
    expect(last('west').position[0]).toBeCloseTo(10, 9);
    expect(last('west').position[2]).toBeGreaterThan(6);
    expect(last('east').position[0]).toBeCloseTo(10.4, 9);
    done();
  });
});
