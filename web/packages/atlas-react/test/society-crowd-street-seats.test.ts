// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd } from '../src/playcanvas/society/crowd.js';
import { CHARACTER_CATALOG } from '../src/playcanvas/character/catalog-data.js';
import { farAppearance, postureSeatMetres } from '../src/playcanvas/character/far.js';
import { inhabitantLookOf } from '../src/playcanvas/character/inhabitant.js';
import type { SeatingLayout, StreetFurniture } from '../src/playcanvas/society/seating.js';
import type { CrowdPose, CrowdRenderableFactory, OwnedSocietyState } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';

/*
 * A town resident resting on a street bench. A living action names a destination, never a target,
 * and a town's bench is a record of its tiles, not an object of the version: the resident is
 * recorded at a point of the bench itself. The bench is the catalog's own
 * (assets/catalogs/street-furniture.v2.json: a board whose top is 480 mm up, a back 200 mm to the
 * right of the way it faces), standing at (10 m, -20 m) and facing east, so by the grammar's frame
 * rule its back is to the south and whoever sits on it looks north, which is yaw 0 here.
 */
interface CatalogPart {
  readonly offset_x_mm: number; readonly offset_y_mm: number; readonly offset_z_mm: number;
  readonly size_x_mm: number; readonly size_y_mm: number; readonly size_z_mm: number;
}
// Tests run from web/.
const CATALOG = JSON.parse(readFileSync(resolve('../assets/catalogs/street-furniture.v2.json'), 'utf8')) as {
  entries: { key: string; parts: CatalogPart[] }[];
};
const BENCH: StreetFurniture = {
  identity: 'bench-1', eastMm: 10_000, southMm: -20_000, facing: [1, 0],
  parts: CATALOG.entries.find((entry) => entry.key === 'bench')!.parts.map((part) => ({
    alongMm: part.offset_x_mm, leftMm: part.offset_y_mm, bottomMm: part.offset_z_mm,
    sizeAlongMm: part.size_x_mm, sizeLeftMm: part.size_y_mm, heightMm: part.size_z_mm,
  })),
};
const SEAT_TOP_METRES = 0.48;
/** One of the bench's two seats, as a town states it: 350 mm from its base along its direction. */
const SEAT_MM = [10_350, -20_000] as const;
const TOWN: SeatingLayout = { uses: new Map(), objects: [], targets: new Map(), streetFurniture: [BENCH] };
const NO_FURNITURE: SeatingLayout = { uses: new Map(), objects: [], targets: new Map() };

/** A living town's person: an action at a destination, with no target. */
function resident(id: string, at: readonly [number, number], kind: string | null) {
  return {
    id, synthetic: true as const, position_mm: at, motion_path_mm: [at] as const, walk_speed_mm_per_tick: 70_000, indoors: false,
    ...(kind === null ? {} : { action: { kind, status: 'active' as const, destination_id: 'furniture:bench-1', remaining_ticks: 5, reason: 'test' } }),
  };
}

const state = (inhabitants: OwnedSocietyState['inhabitants']): OwnedSocietyState => ({
  profile: 'exulanica-society/v5', society_id: 'society', branch_id: 'branch', tick: 1, inhabitants,
});

function setup(inhabitants: OwnedSocietyState['inhabitants'], layout: SeatingLayout | null) {
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
      root: entity, subject: { kind: 'synthetic-inhabitant', ...identity }, standingHeight: 1.7, facing: 0, drawsSeats: true,
      pose: (pose) => { poses.get(identity.inhabitantId)!.push(pose); entity.setLocalPosition(...(pose.position as [number, number, number])); },
      setVisible: (visible) => { entity.enabled = visible; },
      destroy: () => entity.destroy(),
    };
  };
  const crowd = new SocietyCrowd(device, root, { factory });
  crowd.set(state(inhabitants), [10, -20], { nowMs: 0, intervalMs: 60_000 }, layout);
  let now = 0;
  for (let frame = 0; frame < 4 * 60; frame += 1) crowd.update((now += 1000 / 60));
  const last = (id: string) => poses.get(id)!.at(-1)! as CrowdPose & { yaw?: number };
  return { crowd, last, done: () => { crowd.destroy(); app.destroy(); } };
}

/** How high a person's root sits so their pelvis rests on the board's top, from the people catalog. */
const liftOf = (id: string) =>
  SEAT_TOP_METRES - postureSeatMetres(farAppearance(CHARACTER_CATALOG, inhabitantLookOf(CHARACTER_CATALOG, id)), 'perched');

describe('a town resident resting on a street bench', () => {
  it('sits on the board, at their own place on it, with their back to the backrest', () => {
    const { crowd, last, done } = setup([resident('resting', SEAT_MM, 'rest')], TOWN);
    // Positive control: the perched posture's own seat is not at the board's top for this person, so
    // their root is moved to rest them on it, and a pose left on the ground plane would differ.
    expect(Math.abs(liftOf('resting'))).toBeGreaterThan(0.005);
    const pose = last('resting');
    expect(pose.position[0]).toBeCloseTo(10.35, 9);
    expect(pose.position[1]).toBeCloseTo(liftOf('resting'), 9);
    expect(pose.position[2]).toBeCloseTo(-20, 9);
    // Looking north: forward is (-sin yaw, -cos yaw) in east and south.
    expect(-Math.sin(pose.yaw!)).toBeCloseTo(0, 9);
    expect(-Math.cos(pose.yaw!)).toBeCloseTo(-1, 9);
    expect(pose).toMatchObject({ activity: 'rest', seated: true, groundY: 0 });
    expect(crowd.seatedOn('resting')).toBe(true);
    expect(crowd.seatingMisses.filter((miss) => miss.reason !== 'activity-has-no-facing')).toEqual([]);
    done();
  });

  it('seats two residents side by side on the one bench', () => {
    const { crowd, last, done } = setup(
      [resident('resting', SEAT_MM, 'rest'), resident('beside', [9_650, -20_000], 'rest')], TOWN,
    );
    expect(crowd.seatedOn('resting')).toBe(true);
    expect(crowd.seatedOn('beside')).toBe(true);
    expect(last('beside').position[0]).toBeCloseTo(9.65, 9);
    expect(last('beside').yaw).toBeCloseTo(last('resting').yaw!, 9);
    done();
  });

  it('draws a town with no furniture read, and a resident resting off any, as before: on the ground', () => {
    const none = setup([resident('resting', SEAT_MM, 'rest')], NO_FURNITURE);
    expect(none.crowd.seatedOn('resting')).toBe(false);
    expect(none.last('resting').position[1]).toBe(0);
    expect(none.last('resting')).not.toHaveProperty('seated');
    none.done();
    // Three metres along the kerb from the bench: nothing is under them.
    const off = setup([resident('resting', [13_350, -20_000], 'rest')], TOWN);
    expect(off.crowd.seatedOn('resting')).toBe(false);
    expect(off.last('resting').position[1]).toBe(0);
    off.done();
  });

  it('leaves someone the state gives nothing to do standing, even at a point of the bench', () => {
    const { crowd, last, done } = setup([resident('passing', SEAT_MM, null)], TOWN);
    expect(crowd.seatedOn('passing')).toBe(false);
    expect(last('passing').position[1]).toBe(0);
    done();
  });

  it('finds the seat again when the furniture is read after the people are', () => {
    const { crowd, last, done } = setup([resident('resting', SEAT_MM, 'rest')], NO_FURNITURE);
    expect(crowd.seatedOn('resting')).toBe(false);
    crowd.setLayout(TOWN);
    let now = 4_000;
    for (let frame = 0; frame < 4 * 60; frame += 1) crowd.update((now += 1000 / 60));
    expect(crowd.seatedOn('resting')).toBe(true);
    expect(last('resting').position[1]).toBeCloseTo(liftOf('resting'), 9);
    done();
  });
});
