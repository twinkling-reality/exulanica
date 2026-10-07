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
