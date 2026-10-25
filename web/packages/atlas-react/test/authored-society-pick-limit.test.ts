// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { AuthoredRegionSociety } from '../src/playcanvas/society/authored-society.js';
import type { OwnedSocietyState } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';

/*
 * Something drawn in front of a person (a placed thing) is picked instead of them: the person is
 * picked only when they stand nearer along the ray than the limit the caller states. The region is
 * scaled, so the limit is a world distance carried into the region's frame.
 */

function setup(scale: number) {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  serveFixturePeople(app);
  const region = new pc.Entity('region');
  region.setLocalScale(scale, scale, scale);
  app.root.addChild(region);
  return new AuthoredRegionSociety(device, region);
}

// One person 5 m in front of the origin along +Z, in the region's own metres.
const state: OwnedSocietyState = {
  profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'branch', tick: 1,
  inhabitants: [{ id: 'person-0', synthetic: true, position_mm: [0, 5000], motion_path_mm: [[0, 5000]] }],
};

describe('picking a person behind something nearer', () => {
  it('picks them only within the stated world distance, in a region of any scale', () => {
    for (const scale of [1, 2]) {
      const society = setup(scale);
      society.setSociety(state, [0, 0]);
      // The person's box starts about (5 - 0.34) region metres along the ray: that times the scale in the world.
      const front = (5 - 0.34) * scale;
      expect(society.pickInhabitant([0, 1, 0], [0, 0, 1])).toBe('person-0');
      expect(society.pickInhabitant([0, 1, 0], [0, 0, 1], front + 0.05)).toBe('person-0');
      expect(society.pickInhabitant([0, 1, 0], [0, 0, 1], front - 0.05)).toBeNull();
      society.destroy();
    }
  });
});

// A ray along +Z from 1 m up: a nearer person 3 m out and a farther one 6 m out, each offset sideways as stated, and
// the one chosen, if any.
const pick = (nearSide: number, farSide: number | null, chosen: string | null = null) => {
  const society = setup(1);
  const person = (id: string, side: number, along: number): OwnedSocietyState['inhabitants'][number] =>
    ({ id, synthetic: true, position_mm: [side, along], motion_path_mm: [[side, along]] });
  const inhabitants = [person('near', nearSide, 3000), ...(farSide === null ? [] : [person('far', farSide, 6000)])];
  society.setSociety({ ...state, inhabitants }, [0, 0]);
  const picked = society.pickInhabitant([0, 1, 0], [0, 0, 1], Number.POSITIVE_INFINITY, chosen);
  society.destroy();
  return picked;
};

describe('picking the person under the pointer, not a passer-by beside the line (P1)', () => {

  it('chooses the farther one the ray passes through the middle of over a nearer one it only grazes', () => {
    // 0.25 m beside the ray: inside the nearer one's 0.34 m box, outside half of it.
    expect(pick(250, 0)).toBe('far');
  });

  it('chooses the nearer one when the ray passes through the middle of both, and a grazed one when it meets no other', () => {
    expect(pick(50, 0)).toBe('near');
    expect(pick(250, null)).toBe('near');
    // Nobody grazed or met: 0.5 m beside the ray is outside the box.
    expect(pick(500, null)).toBeNull();
  });
});

describe('the look stopping at the one chosen, never labelling someone behind them', () => {
  // P1's layout, the nearer person chosen: the ray meets them 0.25 m beside their middle, and passes through the middle
  // of someone 3 m behind them.
  it('stops at the chosen one when it meets them, however squarely it would meet someone behind', () => {
    expect(pick(250, 0, 'near')).toBe('near');
  });

  it('keeps P1 up to the chosen one and leaves a ray that misses them as it was', () => {
    // The farther one chosen: the nearer one the ray passes through the middle of still stands in front.
    expect(pick(50, 0, 'far')).toBe('near');
    // The farther one chosen and squarely met, the nearer one only grazed: the middle still wins.
    expect(pick(250, 0, 'far')).toBe('far');
    // The chosen one beside the ray, unmet: the pick is the one without anyone chosen.
    expect(pick(500, 0, 'near')).toBe('far');
    expect(pick(250, 0, null)).toBe('far');
  });
});
