// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd } from '../src/playcanvas/society/crowd.js';
import type { CrowdRenderableFactory, OwnedSocietyState } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';

/*
 * A living state records where a person is when its minute ends. Someone who walks to a door in a
 * minute ends it indoors, and is still on the street for as long as that walk takes. The times here
 * are worked by hand from the state alone: a person recorded at 60 m a minute, shown a minute in
 * 60 s, covers a metre a second, so a 30 m walk to a door lasts 30 s and a 20 m one 20 s.
 */
const SPEED_MM_PER_TICK = 60_000;
const INTERVAL_MS = 60_000;

function setup(nearLimit?: number) {
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
  const shown = new Map<string, pc.Entity>();
  const factory: CrowdRenderableFactory = (_device, parent, identity) => {
    const entity = new pc.Entity(identity.inhabitantId);
    parent.addChild(entity);
    shown.set(identity.inhabitantId, entity);
    return {
      root: entity, subject: { kind: 'synthetic-inhabitant', ...identity }, standingHeight: 1.8, facing: 0,
      pose: (pose) => entity.setLocalPosition(pose.position[0], pose.position[1], pose.position[2]),
      setVisible: (visible) => { entity.enabled = visible; },
      destroy: () => { shown.delete(identity.inhabitantId); entity.destroy(); },
    };
  };
  const crowd = new SocietyCrowd(device, root, { factory, ...(nearLimit === undefined ? {} : { nearLimit }) });
  return { crowd, shown, done: () => { crowd.destroy(); app.destroy(); } };
}

/** One person's living state at a tick: the path the minute recorded, in metres, and where it ends. */
const minute = (tick: number, path: readonly (readonly [number, number])[], indoors: boolean): OwnedSocietyState => ({
  profile: 'exulanica-society/v4',
  society_id: 'society',
  branch_id: 'branch',
  tick,
  inhabitants: [{
    id: 'resident',
    synthetic: true,
    position_mm: [path.at(-1)![0] * 1000, path.at(-1)![1] * 1000],
    motion_path_mm: path.map(([x, z]) => [x * 1000, z * 1000] as const),
    walk_speed_mm_per_tick: SPEED_MM_PER_TICK,
    indoors,
  }],
});

describe('a walk to a door', () => {
  it('is drawn until the person reaches the door, and not after', () => {
    const { crowd, shown, done } = setup();
    const standing = crowd.set(minute(0, [[0, 0]], false), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    // Standing in the street with nowhere to walk, they are outdoors and stay drawn.
    expect(standing).toEqual({ population: 1, outdoors: 1, indoors: 0, near: 1, far: 0, drawn: 1 });
    // The next minute ends with them indoors, 30 m along the street.
    const counts = crowd.set(minute(1, [[0, 0], [30, 0]], true), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    expect(counts).toEqual({ population: 1, outdoors: 1, indoors: 0, near: 1, far: 0, drawn: 1 });
    expect(crowd.detailOf('resident')).toBe('near');

    crowd.update(15_000);
    expect(crowd.positionOf('resident')![0]).toBeCloseTo(15, 6);
    expect(crowd.detailOf('resident')).toBe('near');
    expect(shown.get('resident')!.enabled).toBe(true);
    expect(shown.get('resident')!.getLocalPosition().x).toBeCloseTo(15, 6);
    expect(crowd.anchorOf('resident', new pc.Vec3())).toBe(true);

    crowd.update(29_000);
    expect(crowd.detailOf('resident')).toBe('near');
    expect(crowd.counts.indoors).toBe(0);

    // The walk lasts 30 s: a second later they are inside.
    crowd.update(31_000);
    expect(crowd.positionOf('resident')).toEqual([30, 0]);
    expect(crowd.detailOf('resident')).toBe('indoors');
    expect(crowd.counts).toEqual({ population: 1, outdoors: 0, indoors: 1, near: 0, far: 0, drawn: 0 });
    expect(crowd.drawnIds).toEqual([]);
    expect(shown.has('resident')).toBe(false);
    expect(crowd.anchorOf('resident', new pc.Vec3())).toBe(false);
    done();
  });

  it('is drawn from one door to the other when the minute starts and ends indoors', () => {
    const { crowd, shown, done } = setup();
    const before = crowd.set(minute(0, [[0, 0]], true), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    expect(before).toEqual({ population: 1, outdoors: 0, indoors: 1, near: 0, far: 0, drawn: 0 });
    // Out of one door and in at another 20 m away, all within the minute.
    crowd.set(minute(1, [[0, 0], [20, 0]], true), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    crowd.update(10_000);
    expect(crowd.detailOf('resident')).toBe('near');
    expect(shown.get('resident')!.getLocalPosition().x).toBeCloseTo(10, 6);
    crowd.update(21_000);
    expect(crowd.detailOf('resident')).toBe('indoors');
    expect(crowd.drawnIds).toEqual([]);
    done();
  });

  it('is drawn in the far form too, and leaves it at the door', () => {
    // No full places: everyone outdoors within range is a far figure.
    const { crowd, done } = setup(0);
    crowd.set(minute(0, [[0, 0]], false), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    crowd.set(minute(1, [[0, 0], [30, 0]], true), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    crowd.update(15_000);
    expect(crowd.detailOf('resident')).toBe('far');
    expect(crowd.counts).toEqual({ population: 1, outdoors: 1, indoors: 0, near: 0, far: 1, drawn: 1 });
    crowd.update(31_000);
    expect(crowd.detailOf('resident')).toBe('indoors');
    expect(crowd.counts).toEqual({ population: 1, outdoors: 0, indoors: 1, near: 0, far: 0, drawn: 0 });
    done();
  });

  it('keeps someone who stays indoors undrawn, and shows nobody on the way under reduced motion', () => {
    const { crowd, shown, done } = setup();
    crowd.set(minute(0, [[0, 0]], true), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    crowd.set(minute(1, [[0, 0]], true), [0, 0], { nowMs: 0, intervalMs: INTERVAL_MS });
    crowd.update(30_000);
    expect(crowd.detailOf('resident')).toBe('indoors');
    expect(shown.size).toBe(0);
    // Reduced motion shows every recorded end at once: the end of this walk is indoors.
    crowd.set(minute(2, [[0, 0], [30, 0]], true), [0, 0], { nowMs: 60_000, intervalMs: INTERVAL_MS });
    crowd.update(Number.MAX_SAFE_INTEGER);
    expect(crowd.positionOf('resident')).toEqual([30, 0]);
    expect(crowd.detailOf('resident')).toBe('indoors');
    expect(crowd.drawnIds).toEqual([]);
    done();
  });
});
