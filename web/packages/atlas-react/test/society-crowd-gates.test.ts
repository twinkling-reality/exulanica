// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd, type CrowdFigures } from '../src/playcanvas/society/crowd.js';
import type { OwnedSocietyState, SocietyInhabitantSnapshot } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';

/*
 * A visitor who crossed in through a gate, standing within 5 m of it, is drawn stepping out of the
 * gate at the state that first holds it and back into it at the state that no longer does, at a walk
 * (1.4 m a second), as lanes DRAW and ROOT agreed for the sword going home; the state records neither
 * step. One farther from its gate goes where it stands, as before. Points are the society's own frame
 * (the crowd's root is not moved here), in metres; times are the caller's clock.
 */

const TRAVELLER = { kind: 'traveller', version: 1, sha256: 'b'.repeat(64) };

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
    // Out of its gate at 1.4 m a second.
    crowd.update(2_200);
    expect(at('near-gate')).toEqual([0, -6.6]);
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
    expect(at('near-gate')).toEqual([0, -7.4]);
    crowd.update(7_000);
    expect(crowd.isLeaving('near-gate')).toBe(false);
    expect(at('near-gate')).toBeNull();
  });
});
