// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import type { CrowdFigures } from '../src/playcanvas/society/crowd.js';
import { AuthoredRegionSociety } from '../src/playcanvas/society/authored-society.js';
import type { OwnedSocietyState, SocietyInhabitantSnapshot } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';

/*
 * How near someone is, measured to their body: the point of the box they are drawn and picked by
 * that lies nearest a viewer. Beside a creature 16 m long, 12 m wide and 8 m tall the viewer is as
 * near as its side, and under it they are at it, where a point inside its body would stay metres
 * away. The region is moved and turned here, so the expected points are worked by hand from that
 * turn: a quarter turn about +Y carries the region's (x, y, z) to (z, y, -x), then (10, 0, 5) is added.
 */

const STRIDER = { kind: 'strider', version: 1, sha256: 'a'.repeat(64) };
const KNIGHT = { kind: 'knight', version: 1, sha256: 'b'.repeat(64) };

function setup(scale = 1) {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  serveFixturePeople(app);
  const region = new pc.Entity('region');
  region.setLocalPosition(10, 0, 5);
  region.setLocalEulerAngles(0, 90, 0);
  region.setLocalScale(scale, scale, scale);
  app.root.addChild(region);
  return new AuthoredRegionSociety(device, region);
}

/** The strider's body covers 12 m across and 16 m along the way it faces, 8 m up; the knight states no size. */
function figures(turn: { facing: number }): CrowdFigures {
  return {
    figureFor(person) {
      const strider = person.kind?.kind === 'strider';
      if (!strider && person.kind?.kind !== 'knight') return null;
      return {
        key: person.kind!.kind,
        factory: (_device, parent, identity) => {
          const root = new pc.Entity(`thing:${identity.inhabitantId}`);
          parent.addChild(root);
          return {
            root, subject: { kind: 'synthetic-inhabitant', ...identity },
            standingHeight: strider ? 8 : 1.8,
            get facing() { return strider ? turn.facing : 0; },
            footprint: strider ? { halfAcross: 6, halfAlong: 8 } : null,
            pose: (pose) => root.setLocalPosition(...pose.position),
            setVisible: (visible) => { root.enabled = visible; },
            destroy: () => root.destroy(),
          };
        },
      };
    },
  };
}

const person = (id: string, at: readonly [number, number], extra: Partial<SocietyInhabitantSnapshot> = {}): SocietyInhabitantSnapshot =>
  ({ id, synthetic: true, position_mm: at, motion_path_mm: [at], ...extra });

const state = (people: SocietyInhabitantSnapshot[]): OwnedSocietyState => ({
  profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'branch', tick: 1, inhabitants: people,
});

/** The strider at the region's origin, the knight 20 m east of it in the region, someone indoors. */
function drawn(scale = 1, turn = { facing: 0 }) {
  const society = setup(scale);
  society.setFigures(figures(turn));
  society.setSociety(state([
    person('strider-1', [0, 0], { kind: STRIDER }),
    person('knight-1', [20_000, 0], { kind: KNIGHT }),
    person('indoors-1', [1000, 0], { indoors: true }),
  ]), [10, 5]);
  return society;
}

const expectPoint = (out: pc.Vec3, x: number, y: number, z: number): void => {
  expect(out.x).toBeCloseTo(x, 9);
  expect(out.y).toBeCloseTo(y, 9);
  expect(out.z).toBeCloseTo(z, 9);
};

describe('how near someone is, measured to their body', () => {
  it('is the near side of a body bigger than the reach, and the viewer themselves under it', () => {
    const society = drawn();
    const out = new pc.Vec3();
    // Facing +z in the region, the body spans the region's x -6..6, y 0..8, z -8..8: in the world,
    // x 2..18, y 0..8, z -1..11. Two metres east of its east side, at eye height:
    const beside = new pc.Vec3(20, 1.6, 5);
    expect(society.nearestPointOf('strider-1', beside, out)).toBe(true);
    expectPoint(out, 18, 1.6, 5);
    expect(beside.distance(out)).toBeCloseTo(2, 9);
    // Standing under its body: the viewer is at it.
    const under = new pc.Vec3(12, 1.6, 4);
    expect(society.nearestPointOf('strider-1', under, out)).toBe(true);
    expectPoint(out, 12, 1.6, 4);
    // Above and beyond a corner: the corner itself.
    expect(society.nearestPointOf('strider-1', new pc.Vec3(0, 10, -3), out)).toBe(true);
    expectPoint(out, 2, 8, -1);
    society.destroy();
  });

  it('turns with the body as it is drawn', () => {
    const turn = { facing: Math.PI / 2 };
    const society = drawn(1, turn);
    const out = new pc.Vec3();
    // Turned a quarter, its 16 m length lies along the region's x, its 12 m width along z: in the
    // world it now reaches only 6 m east of its middle.
    expect(society.nearestPointOf('strider-1', new pc.Vec3(20, 1.6, 5), out)).toBe(true);
    expectPoint(out, 16, 1.6, 5);
    turn.facing = 0;
    expect(society.nearestPointOf('strider-1', new pc.Vec3(20, 1.6, 5), out)).toBe(true);
    expectPoint(out, 18, 1.6, 5);
    society.destroy();
  });

  it('is a person\'s box for one that states no size, and nothing for anyone not drawn outdoors', () => {
    const society = drawn();
    const out = new pc.Vec3();
    // The knight stands at the region's (20, 0, 0), the world's (10, 0, -15), boxed 0.34 m about
    // its middle and 1.8 m up. From 3 m south of its middle the box's south face is 2.66 m away.
    expect(society.nearestPointOf('knight-1', new pc.Vec3(10, 1.6, -12), out)).toBe(true);
    expectPoint(out, 10, 1.6, -14.66);
    expect(society.nearestPointOf('indoors-1', new pc.Vec3(10, 1.6, -12), out)).toBe(false);
    expect(society.nearestPointOf('nobody', new pc.Vec3(10, 1.6, -12), out)).toBe(false);
    society.destroy();
  });

  it('is where a pick from the viewer meets the body, in a region of any scale', () => {
    for (const scale of [1, 2]) {
      const society = drawn(scale);
      const out = new pc.Vec3();
      // Ten region metres east of its middle: two region metres from its east side, in world metres times the scale.
      const viewer = new pc.Vec3(10 + 10 * scale, 1.6, 5);
      expect(society.nearestPointOf('strider-1', viewer, out)).toBe(true);
      expectPoint(out, 10 + 8 * scale, 1.6, 5);
      const distance = viewer.distance(out);
      expect(distance).toBeCloseTo(2 * scale, 9);
      // The pick meets the same box there: within that distance along the way to it, and not short of it.
      const along = out.clone().sub(viewer).normalize();
      const ray = [viewer.x, viewer.y, viewer.z] as const, direction = [along.x, along.y, along.z] as const;
      expect(society.pickInhabitant(ray, direction, distance + 0.05)).toBe('strider-1');
      expect(society.pickInhabitant(ray, direction, distance - 0.05)).toBeNull();
      society.destroy();
    }
  });
});
