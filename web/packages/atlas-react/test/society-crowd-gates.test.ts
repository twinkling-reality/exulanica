// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { CHARACTER_CATALOG } from '../src/playcanvas/character/catalog-data.js';
import { farAppearance } from '../src/playcanvas/character/far.js';
import { inhabitantLookOf } from '../src/playcanvas/character/inhabitant.js';
import { SocietyCrowd, type CrowdFigures } from '../src/playcanvas/society/crowd.js';
import type { OwnedSocietyState, SocietyInhabitantSnapshot } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';
import { KNIGHT_WALK } from './things-knight-rig.js';

/*
 * A visitor who crossed in through a gate, standing within 5 m of it, is drawn stepping out of the
 * gate at the state that first holds it and back into it at the state that no longer does, at its
 * own walking pace: the pace its figure states, taken up as soon as the figure states it, else the
 * catalog person's for its id. The state records neither step. One farther from its gate goes where
 * it stands. Points are the society's own frame (the crowd's root is not moved here), in metres;
 * times are the caller's clock.
 */

const TRAVELLER = { kind: 'traveller', version: 1, sha256: 'b'.repeat(64) };

/**
 * The catalog person's walking pace for an id, metres a second, from the people catalog and never
 * from the crowd: the walk clip's measured ground speed at its base's rest height, scaled to the
 * height of the look the id draws.
 */
function catalogPace(id: string): number {
  const appearance = farAppearance(CHARACTER_CATALOG, inhabitantLookOf(CHARACTER_CATALOG, id));
  const base = CHARACTER_CATALOG.families.flatMap((family) => family.bases).find((one) => one.baseId === appearance.baseId)!;
  return (base.clips.walk.speedMillimetresPerSecond / base.restHeightMillimetres) * appearance.heightMetres;
}

/** `stated` is the pace each traveller's figure states now, or null while it states none (as before it is made). */
function setup(stated: { pace: number | null } = { pace: null }) {
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
  const drawn = new Map<string, pc.Entity>();
  // Travellers are drawn by their look: a figure whose root stands where the crowd poses it.
  const figures: CrowdFigures = {
    figureFor(person) {
      if (person.kind?.kind !== 'traveller') return null;
      return {
        key: 'traveller',
        factory: (_device, parent, identity) => {
          const entity = new pc.Entity(`thing:${identity.inhabitantId}`);
          parent.addChild(entity);
          drawn.set(identity.inhabitantId, entity);
          return {
            root: entity, subject: { kind: 'synthetic-inhabitant', ...identity }, standingHeight: 1.7, facing: 0,
            get walkSpeed() { return stated.pace; },
            pose: (pose) => entity.setLocalPosition(...pose.position),
            setVisible: (visible) => { entity.enabled = visible; },
            destroy: () => { drawn.delete(identity.inhabitantId); entity.destroy(); },
          };
        },
      };
    },
  };
  const crowd = new SocietyCrowd(device, root);
  crowd.setFigures(figures);
  /** Where a traveller is drawn now, plan metres east and south, or null when it is not drawn or unseen. */
  const at = (id: string): [number, number] | null => {
    const entity = drawn.get(id);
    if (entity === undefined || !entity.enabled) return null;
    const p = entity.getLocalPosition();
    return [Number(p.x.toFixed(6)), Number(p.z.toFixed(6))];
  };
  return { crowd, at };
}

const traveller = (id: string, at: readonly [number, number]): SocietyInhabitantSnapshot =>
  ({ id, synthetic: true, kind: TRAVELLER, position_mm: at, motion_path_mm: [at], came_by: 'crossed' } as SocietyInhabitantSnapshot);

const minute = (tick: number, people: SocietyInhabitantSnapshot[]): OwnedSocietyState => ({
  profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'branch', tick, inhabitants: people,
  movement_budget_mm_per_tick: 60_000,
} as OwnedSocietyState);

describe('a visitor stepping out of its gate and back into it', () => {
  it('steps out of the gate it came through once the gate is read, walks back into it when it leaves, and goes there', () => {
    const { crowd, at } = setup();
    const timing = (nowMs: number) => ({ nowMs, intervalMs: 10_000 });
    crowd.set(minute(1, []), [0, 0], timing(0));
    // The page draws a minute's state first and reads its events just after: three visitors have just
    // crossed in, and none is drawn until the gate it came through is read (or the 3 s wait ends).
    crowd.set(minute(2, [traveller('near-gate', [0, -6000]), traveller('far-gate', [0, 4000]), traveller('unread', [3000, 0])]), [0, 0], timing(1_000));
    expect([at('near-gate'), at('far-gate'), at('unread')]).toEqual([null, null, null]);
    // The events read: one's gate stands 2 m beyond where the state places it, another's 20 m off.
    crowd.setGates(new Map([['near-gate', [0, -8000]], ['far-gate', [20_000, -6000]]]));
    crowd.update(1_200);
    expect(at('near-gate')).toEqual([0, -8]);
    expect(at('far-gate')).toEqual([0, 4]);
    expect(at('unread')).toBeNull();
    // Out of its gate at its own walking pace: its figure states none, so the catalog person's for
    // its id, between 1.0 and 1.4 m/s, which covers the 2 m within two seconds.
    const pace = catalogPace('near-gate');
    expect(pace).toBeGreaterThan(1.0);
    expect(pace).toBeLessThan(1.4);
    crowd.update(2_200);
    expect(at('near-gate')![1]).toBeCloseTo(-8 + pace, 6);
    crowd.update(3_200);
    expect(at('near-gate')).toEqual([0, -6]);
    // The one whose gate was never read is drawn where it stands once the wait ends.
    crowd.update(4_000);
    expect(at('unread')).toEqual([3, 0]);
    // Leaving: the state has none of them; the near one walks back into its gate, the others are gone.
    crowd.set(minute(3, []), [0, 0], timing(5_000));
    expect(crowd.isLeaving('near-gate')).toBe(true);
    expect(at('near-gate')).toEqual([0, -6]);
    expect([at('far-gate'), at('unread')]).toEqual([null, null]);
    crowd.update(6_000);
    expect(at('near-gate')![1]).toBeCloseTo(-6 - pace, 6);
    crowd.update(7_000);
    expect(crowd.isLeaving('near-gate')).toBe(false);
    expect(at('near-gate')).toBeNull();
  });

  it('steps out at once, at its own pace, when its gate was read before the state that holds it', () => {
    const { crowd, at } = setup();
    const timing = (nowMs: number) => ({ nowMs, intervalMs: 10_000 });
    const pace = catalogPace('early');
    crowd.set(minute(1, []), [0, 0], timing(0));
    crowd.setGates(new Map([['early', [0, -8000]]]));
    crowd.set(minute(2, [traveller('early', [0, -6000])]), [0, 0], timing(1_000));
    expect(at('early')).toEqual([0, -8]);
    crowd.update(2_000);
    expect(at('early')![1]).toBeCloseTo(-8 + pace, 6);
    crowd.update(3_000);
    expect(at('early')).toEqual([0, -6]);
  });

  it('steps at the pace its figure states, from the frame the figure states it', () => {
    // The armoured knight's look declares 0.504 m/s; a figure is made while its visitor already
    // steps, and states nothing until then.
    const stated: { pace: number | null } = { pace: null };
    const { crowd, at } = setup(stated);
    const timing = (nowMs: number) => ({ nowMs, intervalMs: 10_000 });
    const pace = catalogPace('knight');
    crowd.set(minute(1, []), [0, 0], timing(0));
    crowd.set(minute(2, [traveller('knight', [0, -6000])]), [0, 0], timing(1_000));
    crowd.setGates(new Map([['knight', [0, -8000]]]));
    crowd.update(1_200);
    expect(at('knight')).toEqual([0, -8]);
    // One second before its figure is made: the catalog person's pace for its id.
    crowd.update(2_200);
    expect(at('knight')![1]).toBeCloseTo(-8 + pace, 6);
    // Made: from here it steps at its look's own pace, slower than half of what it stepped at.
    stated.pace = KNIGHT_WALK;
    expect(KNIGHT_WALK).toBe(0.504);
    crowd.update(3_200);
    expect(at('knight')![1]).toBeCloseTo(-8 + pace + KNIGHT_WALK, 6);
    crowd.update(5_000);
    expect(at('knight')).toEqual([0, -6]);
    // Leaving, it walks the 2 m back into its gate at that pace: 3.97 s.
    crowd.set(minute(3, []), [0, 0], timing(5_000));
    crowd.update(6_000);
    expect(at('knight')![1]).toBeCloseTo(-6 - KNIGHT_WALK, 6);
    crowd.update(8_900);
    expect(crowd.isLeaving('knight')).toBe(true);
    expect(at('knight')![1]).toBeCloseTo(-6 - 3.9 * KNIGHT_WALK, 6);
    crowd.update(9_100);
    expect(crowd.isLeaving('knight')).toBe(false);
    expect(at('knight')).toBeNull();
  });
});
