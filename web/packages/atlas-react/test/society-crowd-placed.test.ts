// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd, type CrowdFigures } from '../src/playcanvas/society/crowd.js';
import type { OwnedSocietyState, SocietyInhabitantSnapshot } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';

/*
 * A being its author placed is taken in by the society at the open node nearest where it was put down, which may be
 * metres away when somebody was on the way to the nearer one. Drawn for the first time in a later minute, it walks
 * from where it was put down to that node at its own pace, so it never jumps there. One drawn on the page's first read
 * of the world, or taken in where it was put down, is drawn where it stands. Points are the society's own frame (the
 * crowd's root is not moved here), in metres; times are the caller's clock.
 */

const PIP = { kind: 'pip', version: 1, sha256: 'c'.repeat(64) };
/** The pace each being's figure states, metres a second. */
const PACE = 0.5;

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
  const figures: CrowdFigures = {
    figureFor(person) {
      if (person.kind?.kind !== 'pip') return null;
      return {
        key: 'pip',
        factory: (_device, parent, identity) => {
          const entity = new pc.Entity(`thing:${identity.inhabitantId}`);
          parent.addChild(entity);
          drawn.set(identity.inhabitantId, entity);
          return {
            root: entity, subject: { kind: 'synthetic-inhabitant', ...identity }, standingHeight: 0.4, facing: 0, walkSpeed: PACE,
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
  /** Where a being is drawn now, plan metres east and south, or null when it is not drawn. */
  const at = (id: string): [number, number] | null => {
    const entity = drawn.get(id);
    if (entity === undefined || !entity.enabled) return null;
    const p = entity.getLocalPosition();
    return [Number(p.x.toFixed(6)), Number(p.z.toFixed(6))];
  };
  return { crowd, at };
}

const being = (id: string, at: readonly [number, number], cameBy: 'placed' | 'populated', putAt: readonly [number, number] | null): SocietyInhabitantSnapshot =>
  ({ id, synthetic: true, kind: PIP, position_mm: at, motion_path_mm: [at], came_by: cameBy, placed_at_mm: putAt } as SocietyInhabitantSnapshot);

const minute = (tick: number, people: SocietyInhabitantSnapshot[]): OwnedSocietyState => ({
  profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'branch', tick, inhabitants: people,
  movement_budget_mm_per_tick: 60_000,
} as OwnedSocietyState);

const timing = (nowMs: number) => ({ nowMs, intervalMs: 10_000 });

describe('a being just placed', () => {
  it('walks from where it was put down to the node the society took it in at, at its own pace', () => {
    const { crowd, at } = setup();
    crowd.set(minute(1, []), [0, 0], timing(0));
    // Put down at the stand's node, taken in 2.5 m away at a door: drawn first where it was put down.
    const put = [128_000, -56_100] as const, node = [126_362, -54_150] as const;
    crowd.set(minute(2, [being('placed', node, 'placed', put)]), [0, 0], timing(1_000));
    expect(at('placed')).toEqual([128, -56.1]);
    const metres = Math.hypot(1.638, 1.95);
    crowd.update(2_000);
    const one = at('placed')!;
    expect(Math.hypot(one[0] - 128, one[1] + 56.1)).toBeCloseTo(PACE, 6);
    // On the line between the two points: it walks there, never jumps.
    expect((one[0] - 128) / -1.638).toBeCloseTo((one[1] + 56.1) / 1.95, 6);
    crowd.update(1_000 + Math.ceil((metres / PACE) * 1000) + 100);
    expect(at('placed')).toEqual([126.362, -54.15]);
  });

  it('stands where it was put down when the society took it in there', () => {
    const { crowd, at } = setup();
    crowd.set(minute(1, []), [0, 0], timing(0));
    crowd.set(minute(2, [being('placed', [4_000, -2_000], 'placed', [4_000, -2_000])]), [0, 0], timing(1_000));
    expect(at('placed')).toEqual([4, -2]);
    crowd.update(2_000);
    expect(at('placed')).toEqual([4, -2]);
  });

  it('stands where it is on the first read of the world, and so does anyone who was not placed', () => {
    const { crowd, at } = setup();
    crowd.set(minute(5, [being('placed', [126_362, -54_150], 'placed', [128_000, -56_100])]), [0, 0], timing(0));
    expect(at('placed')).toEqual([126.362, -54.15]);
    crowd.set(minute(6, [being('placed', [126_362, -54_150], 'placed', [128_000, -56_100]), being('populated', [3_000, 0], 'populated', null)]), [0, 0], timing(1_000));
    expect(at('populated')).toEqual([3, 0]);
    crowd.update(2_000);
    expect(at('placed')).toEqual([126.362, -54.15]);
  });
});
