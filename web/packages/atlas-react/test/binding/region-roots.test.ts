// @vitest-environment happy-dom
/**
 * Every region the binding draws has a root, whether or not anything in it was reconstructed.
 *
 * A world made from photographs has regions drawn only as photographs: no point map, so no entry
 * in `binding.islands`, which holds one visual per point map. Its declared floor and its people
 * still hang from that region's root. The browser check found both missing when they were hung
 * from `islands`; here the harness world holds a point map in its first region only.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { drawDeclaredFloors } from '../../src/playcanvas/declared-floor.js';
import { hostRegionSociety } from '../../src/playcanvas/society/region-society.js';
import { buildBinding } from './binding-harness.js';
import { FIRST_REGION, PERSONAL_SCENE, SECOND_REGION } from './world-kinds.js';

afterEach(() => {
  document.body.replaceChildren();
});

describe('a region drawn with no point map', () => {
  it('has a root, which its floor and its people hang from', async () => {
    const { binding } = await buildBinding('personal-regions');
    try {
      expect(binding.islands.map((visual) => visual.island.islandId)).toEqual([FIRST_REGION]);
      expect([...binding.regionRoots.keys()]).toEqual(PERSONAL_SCENE.islands.map((island) => island.islandId));
      const root = binding.regionRoots.get(SECOND_REGION)!;
      const floors = drawDeclaredFloors(binding, { halfExtentMm: 12_000, elevationMm: 0 });
      expect(floors.islandIds).toContain(SECOND_REGION);
      expect(root.children.some((child) => child.name === `declared-floor:${SECOND_REGION}`)).toBe(true);
      const society = hostRegionSociety(binding, SECOND_REGION);
      expect(society?.root.parent).toBe(root);
      floors.destroy();
    } finally {
      binding.destroy();
    }
  });
});
