// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd } from '../src/playcanvas/society/crowd.js';
import { CHARACTER_CATALOG } from '../src/playcanvas/character/catalog-data.js';
import { farAppearance, postureSeatMetres } from '../src/playcanvas/character/far.js';
import { inhabitantLookOf } from '../src/playcanvas/character/inhabitant.js';
import { SEAT_APPROACH_METRES, placeDrawing, type KindUse, type SeatingLayout } from '../src/playcanvas/society/seating.js';
import type { CrowdPose, CrowdRenderableFactory, OwnedSocietyState } from '../src/playcanvas/society/types.js';

/*
 * People at the objects they use: seated on the seat their place has, at the seat's height and
 * facing, or standing at the place facing the object, and drawn as everyone else where the place
 * cannot be found. The layout comes from places the server turned (fixtures/society-seating.json).
 */

interface Case {
  readonly asset_key: string;
  readonly transform: { x_mm: number; y_mm: number; z_mm: number; yaw_microradians: number; scale_milli: number };
  readonly turned_places_mm: [number, number][];
  readonly use: { affordance: string; places: { position_mm: number[]; faces: string; seat: { position_mm: number[]; faces: string } | null }[] | null };
}
// Tests run from web/; a happy-dom module URL is not a file path.
const CASES = (JSON.parse(readFileSync(resolve('packages/atlas-react/test/fixtures/society-seating.json'), 'utf8')) as { cases: Case[] }).cases;
/** The yaw at which a bench once lost its middle place to rounding: not a tidy angle. */
const YAW = 47_856;
const caseOf = (key: string) => CASES.find((item) => item.asset_key === key && item.transform.yaw_microradians === YAW)!;

function layoutOf(items: readonly Case[]): SeatingLayout {
  const uses = new Map<string, KindUse>();
  for (const item of items) {
    uses.set(item.asset_key, {
      affordance: item.use.affordance,
      places: item.use.places && item.use.places.map((place) => ({
        positionMm: place.position_mm as [number, number],
        faces: place.faces as never,
        seat: place.seat && { positionMm: place.seat.position_mm as [number, number, number], faces: place.seat.faces as never },
      })),
    });
  }
  return {
    uses,
    objects: items.map((item, index) => ({
      objectId: `object:${index}`, assetKey: item.asset_key,
      xMm: item.transform.x_mm + index * 10_000, yMm: item.transform.y_mm, zMm: item.transform.z_mm,
      yawMicroradians: item.transform.yaw_microradians, scaleMilli: item.transform.scale_milli,
    })),
    targets: new Map(items.map((_, index) => [`target:${index}`, `object:${index}`] as const)),
  };
}

const BENCH = caseOf('cc0.bench');
const STALL = caseOf('cc0.market-stall');
const LAYOUT = layoutOf([BENCH, STALL]);
/** A turned place of object `index` in the layout, where the society stands its occupant. */
const placeOf = (index: number, item: Case, place: number) =>
  [item.turned_places_mm[place]![0] + index * 10_000, item.turned_places_mm[place]![1]] as const;

function person(id: string, at: readonly [number, number], kind: string, target: string | null) {
  return {
    id, synthetic: true as const, position_mm: at, motion_path_mm: [at] as const,
    action: { kind, status: 'active' as const, target_id: target, remaining_ticks: 2, reason: 'test' },
  };
}

const STATE: OwnedSocietyState = {
  profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'branch', tick: 1,
  movement_budget_mm_per_tick: 60_000,
  inhabitants: [
    person('resting', placeOf(0, BENCH, 1), 'rest', 'target:0'),
    person('visiting', placeOf(1, STALL, 0), 'visit', 'target:1'),
    person('lost', placeOf(0, BENCH, 0), 'rest', 'target:unknown'),
  ],
};

function setup(drawsSeats: boolean, nearLimit?: number) {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  const root = new pc.Entity('society');
  app.root.addChild(root);
  const poses = new Map<string, CrowdPose[]>();
  const factory: CrowdRenderableFactory = (_device, parent, identity) => {
    const entity = new pc.Entity(identity.inhabitantId);
    parent.addChild(entity);
    poses.set(identity.inhabitantId, []);
    return {
      root: entity, subject: { kind: 'synthetic-inhabitant', ...identity }, standingHeight: 1.7, facing: 0,
      ...(drawsSeats ? { drawsSeats: true } : {}),
      pose: (pose) => { poses.get(identity.inhabitantId)!.push(pose); entity.setLocalPosition(...(pose.position as [number, number, number])); },
      setVisible: (visible) => { entity.enabled = visible; },
      destroy: () => entity.destroy(),
    };
  };
  const crowd = new SocietyCrowd(device, root, { factory, ...(nearLimit === undefined ? {} : { nearLimit }) });
  crowd.set(STATE, [0, 0], { nowMs: 0, intervalMs: 1_000 }, LAYOUT);
  return { crowd, poses, root };
}

/** Frames of a 60 Hz display from `from` for `seconds`. */
function run(crowd: SocietyCrowd, seconds: number, from = 0): number {
  let now = from;
  for (let frame = 0; frame < Math.round(seconds * 60); frame += 1) crowd.update((now += 1000 / 60));
  return now;
}

const last = (poses: Map<string, CrowdPose[]>, id: string) => poses.get(id)!.at(-1)! as CrowdPose & { yaw?: number };

/** Where the resting person's pelvis goes, and how high their root sits so it rests there. */
function benchSeat() {
  const found = placeDrawing(LAYOUT, 'target:0', STATE.inhabitants[0]!.position_mm);
  if (found.kind !== 'place' || found.drawing.seat === null) throw new Error('the bench place has no seat');
  const appearance = farAppearance(CHARACTER_CATALOG, inhabitantLookOf('resting'));
  const lift = found.drawing.seat.position[1] - postureSeatMetres(appearance, 'perched');
  return { seat: found.drawing.seat, lift };
}

describe('a person using an object', () => {
  it('walks to stand before the seat, then lowers onto it at its height and facing', () => {
    const { crowd, poses } = setup(true);
    const { seat, lift } = benchSeat();
    // Positive control: the root is lifted, so a pose at the ground plane would be wrong.
    expect(lift).toBeGreaterThan(0.01);
    run(crowd, 4);
    const all = poses.get('resting')!;
    const pose = all.at(-1)! as CrowdPose & { yaw?: number };
    expect(pose.position[0]).toBeCloseTo(seat.position[0], 9);
    expect(pose.position[1]).toBeCloseTo(lift, 9);
    expect(pose.position[2]).toBeCloseTo(seat.position[2], 9);
    expect(pose.yaw).toBeCloseTo(seat.facing, 12);
    expect(pose).toMatchObject({ activity: 'rest', seated: true, groundY: 0 });
    expect(crowd.seatedOn('resting')).toBe(true);
    // The seat posture starts only where they stand before the seat, a stride from its point.
    const first = all.findIndex((p) => p.seated === true);
    expect(first).toBeGreaterThan(0);
    const [fx, , fz] = all[first]!.position;
    expect(Math.hypot(fx - seat.position[0], fz - seat.position[2])).toBeCloseTo(SEAT_APPROACH_METRES, 1);
    // Before it, they walk on the ground on their feet: no posture, not even resting on the ground.
    expect(all.slice(0, first).every((p) => p.position[1] === 0 && p.seated === undefined && p.activity === null)).toBe(true);
    // What the simulation says stays where it put them: the place, not the seat.
    const [x, z] = STATE.inhabitants[0]!.position_mm;
    expect(crowd.positionOf('resting')).toEqual([x / 1000, z / 1000]);
  });

  it('is on the seat at once under reduced motion', () => {
    const { crowd, poses } = setup(true);
    crowd.update(Number.MAX_SAFE_INTEGER);
    const { seat, lift } = benchSeat();
    const pose = last(poses, 'resting');
    [seat.position[0], lift, seat.position[2]].forEach((v, i) => expect(pose.position[i]).toBeCloseTo(v, 9));
    expect(pose.seated).toBe(true);
  });

  it('drops the seat at once when moved without walking, rather than gliding from it', () => {
    const { crowd, poses } = setup(true);
    run(crowd, 4);
    expect(crowd.seatedOn('resting')).toBe(true);
    // Minutes this crowd never read: the person is 20 m away and walking.
    const away = [20_000, 0] as const;
    crowd.set({
      ...STATE, tick: 5,
      inhabitants: [{ ...person('resting', away, 'visit', null), motion_path_mm: [away] }],
    }, [0, 0], { nowMs: 5_000, intervalMs: 1_000 }, LAYOUT);
    expect(crowd.jumps.map((jump) => jump.reason)).toEqual(['minutes-not-read']);
    crowd.update(5_000 + 1000 / 60);
    const pose = last(poses, 'resting');
    expect([pose.position[0], pose.position[1], pose.position[2]]).toEqual([20, 0, 0]);
  });

  it('gets up at once when a later layout has no seat for them, feet on the ground as they rise', () => {
    const { crowd, poses } = setup(true);
    run(crowd, 4);
    expect(crowd.seatedOn('resting')).toBe(true);
    const before = poses.get('resting')!.length;
    // The bench is taken away and no new state has been read.
    crowd.setLayout({ ...LAYOUT, objects: LAYOUT.objects.filter((object) => object.assetKey !== 'cc0.bench') });
    expect(crowd.seatingMisses).toContainEqual({ inhabitantId: 'resting', reason: 'object-not-drawn' });
    run(crowd, 4, 4_000);
    const rising = poses.get('resting')!.slice(before);
    // Every pose above the ground plants the feet, and none is in the seat posture.
    expect(rising.every((p) => p.seated === undefined && (p.position[1] === 0 || p.groundY === 0))).toBe(true);
    const [x, z] = STATE.inhabitants[0]!.position_mm;
    const end = rising.at(-1)!;
    expect([end.position[0], end.position[1], end.position[2]]).toEqual([x / 1000, 0, z / 1000]);
  });

  it('comes to a chair from beside it, never through the table', () => {
    const CAFE = caseOf('cc0.cafe-table');
    const layout = layoutOf([CAFE]);
    const { crowd, poses } = setup(true);
    const at = placeOf(0, CAFE, 0);
    crowd.set({ ...STATE, tick: 2, inhabitants: [person('diner', at, 'rest', 'target:0')] }, [0, 0], { nowMs: 0, intervalMs: 1_000 }, layout);
    run(crowd, 4);
    const path = poses.get('diner')!;
    expect(path.at(-1)!.seated).toBe(true);
    // The table top is 700 mm across about the object's centre; a body is about 0.2 m from its
    // centre to its side, so its centre stays that far outside the top.
    const [cx, cz] = [CAFE.transform.x_mm / 1000, CAFE.transform.z_mm / 1000];
    const nearest = Math.min(...path.map((p) => Math.hypot(p.position[0] - cx, p.position[2] - cz)));
    expect(nearest).toBeGreaterThan(0.35 + 0.2);
  });

  it('visits the stall standing at its place, facing the counter', () => {
    const { crowd, poses } = setup(true);
    run(crowd, 1);
    const found = placeDrawing(LAYOUT, 'target:1', STATE.inhabitants[1]!.position_mm);
    if (found.kind !== 'place') throw new Error('the stall place was not found');
    const pose = last(poses, 'visiting');
    expect(pose.yaw).toBeCloseTo(found.drawing.facing, 12);
    expect(pose.position[1]).toBe(0);
    expect(pose.seated).toBeUndefined();
    expect(crowd.seatedOn('visiting')).toBe(false);
  });

  it('faces the counter on arriving after the visit completed, as a one-minute visit does', () => {
    const { crowd, poses } = setup(true);
    const at = placeOf(1, STALL, 0);
    // They walk in from the east, so the way they walked is not the way the counter is.
    const from = [at[0] + 3_000, at[1]] as const;
    const timing = { intervalMs: 8_000, startLagMs: 2_000 };
    const visitor = (tick: number, status: 'active' | 'completed', path: readonly (readonly [number, number])[]) => ({
      ...STATE, tick,
      inhabitants: [{
        ...person('visiting', path.at(-1)!, 'visit', 'target:1'), motion_path_mm: path,
        action: { kind: 'visit', status, target_id: 'target:1', remaining_ticks: status === 'active' ? 1 : 0, reason: 'test' },
      }],
    });
    crowd.set(visitor(2, 'active', [from]), [0, 0], { ...timing, nowMs: 0 }, LAYOUT);
    crowd.set(visitor(3, 'active', [from, at]), [0, 0], { ...timing, nowMs: 0 }, LAYOUT);
    crowd.update(8_000);
    // The next minute says the visit is over before they reach the stall.
    crowd.set(visitor(4, 'completed', [at]), [0, 0], { ...timing, nowMs: 8_000 }, LAYOUT);
    for (let now = 8_000; now <= 11_000; now += 1000 / 60) crowd.update(now);
    const found = placeDrawing(LAYOUT, 'target:1', at);
    if (found.kind !== 'place') throw new Error('the stall place was not found');
    const pose = last(poses, 'visiting');
    expect(pose.activity).toBeNull();
    expect(pose.yaw).toBeCloseTo(found.drawing.facing, 12);
    // Positive control: the way they walked in was a quarter turn from it.
    expect(Math.abs(Math.cos(found.drawing.facing - Math.PI / 2))).toBeLessThan(0.5);
  });

  it('is drawn by the rule for everyone, with the reason named, where the place is not found', () => {
    const { crowd, poses } = setup(true);
    run(crowd, 1);
    expect(crowd.seatingMisses).toEqual([{ inhabitantId: 'lost', reason: 'target-unknown' }]);
    const pose = last(poses, 'lost');
    expect(pose.position[1]).toBe(0);
    expect(pose.seated).toBeUndefined();
  });

  it('stands at the place when the renderable draws no seat posture, rather than hovering over it', () => {
    const { crowd, poses } = setup(false);
    run(crowd, 1);
    const pose = last(poses, 'resting');
    const [x, z] = STATE.inhabitants[0]!.position_mm;
    expect([pose.position[0], pose.position[1], pose.position[2]]).toEqual([x / 1000, 0, z / 1000]);
    const found = placeDrawing(LAYOUT, 'target:0', [x, z]);
    if (found.kind !== 'place') throw new Error('unmatched');
    expect(pose.yaw).toBeCloseTo(found.drawing.facing, 12);
  });

  it('draws a far figure on the seat too, at the same height', () => {
    const { crowd, root } = setup(true, 0);
    crowd.update(Number.MAX_SAFE_INTEGER);
    const { seat, lift } = benchSeat();
    const figures = root.findByName('society-far-figures')!.children as pc.Entity[];
    const heights = figures.map((figure) => figure.getLocalPosition().y);
    expect(heights.some((y) => Math.abs(y - lift) < 1e-9)).toBe(true);
    const seated = figures.find((figure) => Math.abs(figure.getLocalPosition().x - seat.position[0]) < 1e-9)!;
    expect(seated.getLocalPosition().z).toBeCloseTo(seat.position[2], 9);
  });

  it('faces by the rule of the activity: a partner for a talk, and held for an activity with none', () => {
    const { crowd, poses } = setup(true);
    const talking = (id: string, at: readonly [number, number], partner: string) => ({
      ...person(id, at, 'talk', null), goal: { kind: 'visit' as const, target_id: null, reason: 'test', partner_id: partner },
    });
    crowd.set({
      ...STATE, tick: 2,
      inhabitants: [
        talking('a', [0, 0], 'b'), talking('b', [2_000, 0], 'a'),
        person('new', [0, 5_000], 'juggle', null),
      ],
    }, [0, 0], { nowMs: 0, intervalMs: 1_000 }, LAYOUT);
    run(crowd, 1);
    // Facing +X, toward the partner two metres east, is a quarter turn clockwise from -Z.
    expect(last(poses, 'a').yaw).toBeCloseTo(-Math.PI / 2, 9);
    expect(last(poses, 'b').yaw).toBeCloseTo(Math.PI / 2, 9);
    expect(crowd.seatingMisses).toEqual([{ inhabitantId: 'new', reason: 'activity-has-no-facing' }]);
  });

  it('arrives within a walk when the next minute adds nothing, rather than never', () => {
    const { crowd } = setup(true);
    const walking = (tick: number, path: readonly (readonly [number, number])[]) => ({
      ...STATE, tick,
      inhabitants: [{ ...person('walker', path.at(-1)!, 'rest', null), motion_path_mm: path }],
    });
    // Each minute is expected 8 s after the last and learnt of 2 s late, so a walk is spread over
    // 10 s; the next minute arrives at 8 s, when a fifth of the 4 m is left.
    const timing = { intervalMs: 8_000, startLagMs: 2_000 };
    crowd.set(walking(3, [[0, 0]]), [0, 0], { ...timing, nowMs: 0 });
    crowd.set(walking(4, [[0, 0], [4_000, 0]]), [0, 0], { ...timing, nowMs: 0 });
    crowd.update(8_000);
    expect(crowd.activityOf('walker')).toBeNull();
    crowd.set(walking(5, [[4_000, 0]]), [0, 0], { ...timing, nowMs: 8_000 });
    // The 0.8 m left is walked at the person's own pace, about a metre a second, not spread over
    // another 10 s, where a fifth would be left again at every minute.
    crowd.update(9_000);
    crowd.update(9_100);
    expect(crowd.activityOf('walker')).toBe('rest');
  });

  it('draws nobody differently without a layout', () => {
    const canvas = document.createElement('canvas');
    const device = new pc.NullGraphicsDevice(canvas);
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem];
    app.init(options);
    const root = new pc.Entity('society');
    app.root.addChild(root);
    const crowd = new SocietyCrowd(device, root, { nearLimit: 0 });
    crowd.set(STATE, [0, 0], { nowMs: 0, intervalMs: 1_000 });
    crowd.update(Number.MAX_SAFE_INTEGER);
    expect(crowd.seatingMisses).toEqual([]);
    expect(crowd.seatedOn('resting')).toBe(false);
  });
});
