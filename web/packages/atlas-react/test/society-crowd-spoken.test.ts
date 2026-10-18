// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd } from '../src/playcanvas/society/crowd.js';
import { SPOKEN_FACING_MINUTES, spokenPartners } from '../src/playcanvas/society/spoken-partners.js';
import type { CrowdPose, CrowdRenderableFactory, OwnedSocietyState, SocietyHeardLine } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';

/*
 * Two who spoke by a line said to someone face each other while both stand: the one who heard it
 * faces its speaker and the speaker faces the one it was said to, for lines said within a few minutes
 * of the state's minute. Everyone here is first drawn facing north (no walk read yet), so a turn east
 * or west is the rule's alone.
 */
const TIMING = { nowMs: 0, intervalMs: 60_000 };

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
type Person = OwnedSocietyState['inhabitants'][number];

/** One standing (or walking) person of a society of things, with the lines they heard. */
function person(id: string, path: Path, heard: readonly SocietyHeardLine[] = []): Person {
  const end = path.at(-1)!;
  return {
    id, synthetic: true as const,
    position_mm: [end[0] * 1000, end[1] * 1000] as const,
    motion_path_mm: path.map(([x, z]) => [x * 1000, z * 1000] as const),
    ...(heard.length ? { heard } : {}),
  };
}

/** A line `from` said at `tick`, to `to` or (null) to everyone near, as a hearer keeps it. */
const line = (tick: number, from: string, to: string | null): SocietyHeardLine => ({
  tick, from, to, line: 'Have you seen the horned wanderer?', from_number: 1,
  from_kind: { kind: 'villager', version: 2, sha256: 'a'.repeat(64) },
});

const state = (tick: number, inhabitants: readonly Person[]): OwnedSocietyState => ({
  profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'branch', tick,
  movement_budget_mm_per_tick: 60_000, inhabitants: [...inhabitants],
});

/** Which way a yaw looks in the plan, east and south: forward is (-sin, -cos). */
const looks = (yaw: number) => [-Math.sin(yaw), -Math.cos(yaw)] as const;

describe('two who spoke by a line said to someone', () => {
  it('face each other while both stand: the one who heard faces its speaker, the speaker the one addressed', () => {
    const { crowd, last, run, done } = setup();
    // The asker at 10 m east asked the listener at 12 m (minute 45); the listener answered (46).
    crowd.set(state(47, [
      person('asker', [[10, 5]], [line(46, 'listener', 'asker')]),
      person('listener', [[12, 5]], [line(45, 'asker', 'listener')]),
    ]), [10, 5], TIMING);
    run(2);
    expect(looks(last('asker').yaw!)[0]).toBeCloseTo(1, 9);
    expect(looks(last('listener').yaw!)[0]).toBeCloseTo(-1, 9);
    done();
  });

  it('wait while the other walks up, and turn once both stand', () => {
    const { crowd, last, run, done } = setup();
    crowd.set(state(44, [person('asker', [[10, 5]]), person('listener', [[18, 5]])]), [10, 5], TIMING);
    run(1);
    // The listener heard the ask said to it, and walks 6 m toward the asker this minute.
    crowd.set(state(45, [person('asker', [[10, 5]]), person('listener', [[18, 5], [12, 5]], [line(45, 'asker', 'listener')])]), [10, 5], { ...TIMING, nowMs: 1000 });
    run(1 / 30);
    // The asker still faces north while the listener walks.
    expect(looks(last('asker').yaw!)[1]).toBeCloseTo(-1, 9);
    run(20);
    expect(looks(last('asker').yaw!)[0]).toBeCloseTo(1, 9);
    expect(looks(last('listener').yaw!)[0]).toBeCloseTo(-1, 9);
    done();
  });

  it('leave alone a line said to everyone near, a bystander who heard a line said to another, and an old line', () => {
    const { crowd, last, run, done } = setup();
    crowd.set(state(60, [
      // Said to everyone near: nobody is named.
      person('all-speaker', [[10, 5]]), person('all-hearer', [[12, 5]], [line(59, 'all-speaker', null)]),
      // A bystander kept a line said to the hearer beside it.
      person('speaker', [[20, 5]]), person('hearer', [[22, 5]], [line(59, 'speaker', 'hearer')]), person('bystander', [[21, 7]], [line(59, 'speaker', 'hearer')]),
      // Said to the old hearer more than the minutes ago.
      person('old-speaker', [[30, 5]]), person('old-hearer', [[32, 5]], [line(60 - SPOKEN_FACING_MINUTES - 1, 'old-speaker', 'old-hearer')]),
    ]), [10, 5], TIMING);
    run(2);
    for (const id of ['all-speaker', 'all-hearer', 'bystander', 'old-speaker', 'old-hearer']) expect(looks(last(id).yaw!)[1]).toBeCloseTo(-1, 9);
    expect(looks(last('speaker').yaw!)[0]).toBeCloseTo(1, 9);
    done();
  });

  it('pair each person with the latest of their lines, said or heard', () => {
    const partners = spokenPartners(state(50, [
      person('a', [[0, 0]], [line(46, 'b', 'a')]),
      // B heard A at 47 and C at 48: the latest names C for B, and B for C; A keeps B.
      person('b', [[1, 0]], [line(47, 'a', 'b'), line(48, 'c', 'b')]),
      person('c', [[2, 0]]),
    ]));
    expect(Object.fromEntries(partners)).toEqual({ a: 'b', b: 'c', c: 'b' });
    // At the bound's edge a line still counts; one minute past it does not.
    expect(spokenPartners(state(50, [person('a', [[0, 0]], [line(45, 'b', 'a')]), person('b', [[1, 0]])]), 5).get('a')).toBe('b');
    expect(spokenPartners(state(50, [person('a', [[0, 0]], [line(44, 'b', 'a')]), person('b', [[1, 0]])]), 5).size).toBe(0);
  });
});
