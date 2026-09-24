// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd } from '../src/playcanvas/society/crowd.js';
import type { CrowdRenderableFactory, OwnedSocietyState } from '../src/playcanvas/society/types.js';

/*
 * A v2 state records one travel budget for everybody, a bound. Here it is 6 m a tick, presented
 * over a 6 s interval, so the bound's own pace is one metre a second and a 60 Hz frame is 1/60 m.
 */
const BUDGET_MM = 6_000;
const INTERVAL_MS = 6_000;
const FRAME_MS = 1000 / 60;
const NOMINAL = 1 / 60;

function crowd() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  const root = new pc.Entity('society');
  app.root.addChild(root);
  const factory: CrowdRenderableFactory = (_device, parent, identity) => {
    const entity = new pc.Entity(identity.inhabitantId);
    parent.addChild(entity);
    return {
      root: entity, subject: { kind: 'synthetic-inhabitant', ...identity }, standingHeight: 1.8, facing: 0,
      pose: (pose) => entity.setLocalPosition(pose.position[0], pose.position[1], pose.position[2]),
      setVisible: (visible) => { entity.enabled = visible; },
      destroy: () => entity.destroy(),
    };
  };
  const society = new SocietyCrowd(device, root, { factory });
  return { society, done: () => { society.destroy(); app.destroy(); } };
}

/** One walker's v2 state at a tick, with the path recorded for it, in metres. */
const v2 = (tick: number, path: readonly (readonly [number, number])[], budgetMm = BUDGET_MM): OwnedSocietyState => ({
  profile: 'exulanica-society/v2',
  society_id: 'society',
  branch_id: 'branch',
  tick,
  movement_budget_mm_per_tick: budgetMm,
  inhabitants: [{
    id: 'walker',
    synthetic: true,
    position_mm: [path.at(-1)![0] * 1000, path.at(-1)![1] * 1000],
    motion_path_mm: path.map(([x, z]) => [x * 1000, z * 1000] as const),
  }],
});

/** Frame by frame from `from` to `to`, delivering each state at its time; returns each frame's step. */
function watch(
  society: SocietyCrowd,
  from: number,
  to: number,
  deliveries: ReadonlyMap<number, OwnedSocietyState>,
  startLagMs: number,
): { at: number; step: number; x: number }[] {
  const steps: { at: number; step: number; x: number }[] = [];
  const waiting = new Map(deliveries);
  let held = society.positionOf('walker')!;
  for (let frame = 1; from + frame * FRAME_MS <= to; frame += 1) {
    const at = from + frame * FRAME_MS;
    // Each state is handed over once, on the first frame at or after the time it is read.
    for (const [when, state] of waiting) {
      if (when > at) continue;
      society.set(state, [0, 0], { nowMs: at, intervalMs: INTERVAL_MS, startLagMs });
      waiting.delete(when);
    }
    society.update(at);
    const now = society.positionOf('walker')!;
    steps.push({ at, step: Math.hypot(now[0] - held[0], now[1] - held[1]), x: now[0] });
    held = now;
  }
  return steps;
}

describe('a paced crowd', () => {
  it('walks a short recorded path evenly until the next minute arrives, never stopping between them', () => {
    const { society, done } = crowd();
    // The bound allows 60 m a tick; each minute's recorded walk is 3 m, as in a small square.
    const wide = 60_000;
    society.set(v2(0, [[0, 0]], wide), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    // Each tick's path is read 700 ms after its minute begins: the late reads a poll produces.
    const deliveries = new Map([
      [0, v2(1, [[0, 0], [3, 0]], wide)],
      [6_700, v2(2, [[3, 0], [6, 0]], wide)],
      [12_700, v2(3, [[6, 0], [9, 0]], wide)],
    ]);
    const steps = watch(society, 0, 26_000, deliveries, 1_000);
    // From the first frame until the last minute's walk is done, the walker moves on every frame.
    const walking = steps.filter(({ at }) => at > 2 * FRAME_MS && at < 19_000);
    for (const { at, step } of walking) expect(step, `frame at ${at.toFixed(0)} ms`).toBeGreaterThan(0);
    // Within a minute the pace is even: 3 m over the interval and the lag, then only what is left.
    const first = steps.filter(({ at }) => at > 2 * FRAME_MS && at < 6_700);
    const firstPace = (3 / (INTERVAL_MS + 1_000)) * FRAME_MS;
    for (const { at, step } of first) expect(step, `frame at ${at.toFixed(0)} ms`).toBeCloseTo(firstPace, 9);
    // Never faster than the bound's own pace allows (60 m in 6 s is 1/6 m a frame).
    expect(Math.max(...steps.map(({ step }) => step))).toBeLessThan((wide / 1000 / INTERVAL_MS) * FRAME_MS);
    expect(society.positionOf('walker')).toEqual([9, 0]);
    expect(society.jumps).toEqual([]);
    done();
  });

  it('walks a recorded speed at that speed, standing once the path is done (the control for the above)', () => {
    const { society, done } = crowd();
    const at = (tick: number, path: readonly (readonly [number, number])[]): OwnedSocietyState => {
      const state = v2(tick, path);
      const { movement_budget_mm_per_tick: _bound, ...rest } = state;
      return { ...rest, inhabitants: state.inhabitants.map((p) => ({ ...p, walk_speed_mm_per_tick: 60_000 })) };
    };
    society.set(at(0, [[0, 0]]), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    const steps = watch(society, 0, 6_000, new Map([[0, at(1, [[0, 0], [3, 0]])]]), 0);
    // 3 m at 60 m a tick takes 0.3 s of the 6 s interval: the walker stands for most of it.
    expect(steps.filter(({ step }) => step > 0).length).toBeLessThan(25);
    expect(steps.filter(({ step }) => step === 0).length).toBeGreaterThan(300);
    done();
  });

  it('stands between minutes when told of no delay (the control for the lag above)', () => {
    const { society, done } = crowd();
    society.set(v2(0, [[0, 0]]), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    const deliveries = new Map([[0, v2(1, [[0, 0], [6, 0]])], [6_700, v2(2, [[6, 0], [12, 0]])]]);
    const steps = watch(society, 0, 12_000, deliveries, 0);
    const stood = steps.filter(({ at, step }) => at > 6_100 && at < 6_600 && step === 0);
    expect(stood.length).toBeGreaterThan(20);
    done();
  });

  it('catches up along the recorded path, never faster than half again the pace', () => {
    const { society, done } = crowd();
    society.set(v2(0, [[0, 0]]), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    // Two minutes read almost together: twelve metres of recorded walking wait at once.
    const deliveries = new Map([[0, v2(1, [[0, 0], [0, 6]])], [100, v2(2, [[0, 6], [6, 6]])]]);
    const trail: (readonly [number, number])[] = [];
    const waiting = new Map(deliveries);
    let held = [0, 0] as readonly [number, number];
    let fastest = 0;
    for (let at = FRAME_MS; at <= 14_000; at += FRAME_MS) {
      for (const [when, state] of waiting) {
        if (when > at) continue;
        society.set(state, [0, 0], { nowMs: at, intervalMs: INTERVAL_MS, startLagMs: 1_000 });
        waiting.delete(when);
      }
      society.update(at);
      const now = society.positionOf('walker')!;
      fastest = Math.max(fastest, Math.hypot(now[0] - held[0], now[1] - held[1]));
      trail.push(now);
      held = now;
    }
    expect(fastest).toBeGreaterThan(NOMINAL * 1.05);
    expect(fastest).toBeLessThanOrEqual(NOMINAL * 1.5 + 1e-9);
    // Along the recorded corner, never across it: every point is on one of the two recorded legs.
    for (const [x, z] of trail) expect(Math.abs(x) < 1e-9 || Math.abs(z - 6) < 1e-9).toBe(true);
    // Caught up: the whole twelve metres in less time than walking them at the pace would take.
    expect(society.positionOf('walker')).toEqual([6, 6]);
    expect(society.jumps).toEqual([]);
    done();
  });

  it('carries someone too far behind forward along their own path, and names it', () => {
    const { society, done } = crowd();
    society.set(v2(0, [[0, 0]]), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    society.set(v2(1, [[0, 0], [6, 0]]), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    society.set(v2(2, [[6, 0], [12, 0]]), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    expect(society.jumps).toEqual([]);
    society.set(v2(3, [[12, 0], [18, 0]]), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    expect(society.jumps).toEqual([
      { inhabitantId: 'walker', reason: 'too-far-behind', tick: 3, unreadTicks: 0, metres: 12 },
    ]);
    // Carried to where the last minute's walk begins, which is still walked.
    expect(society.positionOf('walker')).toEqual([12, 0]);
    society.update(3_000);
    expect(society.positionOf('walker')![0]).toBeCloseTo(15, 6);
    done();
  });

  it('names a jump over minutes it never read, and walks the latest recorded path from its start', () => {
    const { society, done } = crowd();
    society.set(v2(0, [[0, 0]]), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    society.set(v2(1, [[0, 0], [6, 0]]), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    society.update(6_000);
    society.set(v2(4, [[20, 0], [23, 0]]), [0, 0], { nowMs: 6_000, intervalMs: INTERVAL_MS });
    expect(society.jumps).toEqual([
      { inhabitantId: 'walker', reason: 'minutes-not-read', tick: 4, unreadTicks: 2, metres: 14 },
    ]);
    expect(society.positionOf('walker')).toEqual([20, 0]);
    society.update(12_000);
    expect(society.positionOf('walker')).toEqual([23, 0]);
    // The next snapshot with nothing to name clears the list.
    society.set(v2(5, [[23, 0]]), [0, 0], { nowMs: 12_000, intervalMs: INTERVAL_MS });
    expect(society.jumps).toEqual([]);
    done();
  });

  it('does not jump anyone who stood still through the minutes it never read', () => {
    const { society, done } = crowd();
    society.set(v2(0, [[6, 0]]), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    society.set(v2(4, [[6, 0], [9, 0]]), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    expect(society.jumps).toEqual([]);
    // 3 m spread over the 6 s interval: a quarter of it walked after 1.5 s.
    society.update(1_500);
    expect(society.positionOf('walker')![0]).toBeCloseTo(6.75, 6);
    done();
  });

  it('names a path that starts somewhere else, a state that is not newer, and one with no path', () => {
    const { society, done } = crowd();
    society.set(v2(0, [[0, 0]]), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    society.set(v2(1, [[4, 0], [5, 0]]), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    expect(society.jumps.map(({ reason, metres }) => [reason, metres])).toEqual([['path-starts-elsewhere', 4]]);
    society.update(6_000);
    society.set(v2(1, [[8, 0]]), [0, 0], { nowMs: 6_000, intervalMs: INTERVAL_MS });
    expect(society.jumps.map(({ reason, metres }) => [reason, metres])).toEqual([['not-newer', 3]]);
    const pathless = v2(2, [[10, 0]]);
    society.set({ ...pathless, inhabitants: [{ id: 'walker', synthetic: true, position_mm: [10_000, 0] }] },
      [0, 0], { nowMs: 6_000, intervalMs: INTERVAL_MS });
    expect(society.jumps.map(({ reason, metres }) => [reason, metres])).toEqual([['no-recorded-path', 2]]);
    done();
  });
});
