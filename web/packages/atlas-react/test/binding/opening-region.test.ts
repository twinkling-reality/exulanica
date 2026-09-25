// @vitest-environment happy-dom
/**
 * The binding opens a world of scene regions where the person's placements are, from its first
 * frame, and moves no region to do it.
 *
 * `create-world-kinds.test.ts` pins the two-region world with no placement; that pin must not move.
 * Here the same world is built with the person's placements in its second region.
 */
import { afterEach, describe, expect, it } from 'vitest';
import type { AtlasBinding } from '../../src/playcanvas/atlas-binding.js';
import { initialAtlasCameraState } from '../../src/playcanvas/camera-views.js';
import { buildBinding, describeBuiltWorld } from './binding-harness.js';
import { FIRST_REGION, PERSONAL_SCENE, SECOND_REGION } from './world-kinds.js';

afterEach(() => {
  document.body.replaceChildren();
});

function pose(binding: AtlasBinding) {
  const { x, y, z, yaw, pitch } = binding.controls.state;
  return { x, y, z, yaw, pitch };
}

/** Every region the binding drew, in its order, with where it stands. */
function regions(binding: AtlasBinding) {
  return binding.islands.map((visual) => ({
    id: visual.island.islandId,
    ordinal: visual.island.creationOrdinal,
    placement: visual.island.placement,
  }));
}

async function built(placementRegionIds?: readonly string[]) {
  const { binding } = await buildBinding(
    'personal-regions',
    placementRegionIds === undefined ? {} : { placementRegionIds },
  );
  try {
    return {
      start: pose(binding),
      described: describeBuiltWorld(binding),
      regions: regions(binding),
      navigation: binding.navigationWorld,
    };
  } finally {
    binding.destroy();
  }
}

describe('the first view of a world of scene regions', () => {
  it('stands in the region holding the person’s placements, from the binding’s first pose', async () => {
    const plain = await built();
    const placed = await built([SECOND_REGION, SECOND_REGION, FIRST_REGION]);

    expect(PERSONAL_SCENE.islands[0]!.islandId).toBe(FIRST_REGION);
    expect(placed.start).toEqual(initialAtlasCameraState(
      { ...PERSONAL_SCENE, islands: [PERSONAL_SCENE.islands[1]!] }, placed.navigation,
    ));
    expect(placed.start).not.toEqual(plain.start);
  });

  it('moves no region: order, ordinals and placements are those of the world with no placement', async () => {
    const plain = await built();
    const placed = await built([SECOND_REGION]);

    expect(placed.regions).toEqual(plain.regions);
    const { start: _placedStart, ...placedRest } = placed.described;
    const { start: _plainStart, ...plainRest } = plain.described;
    expect(placedRest).toEqual(plainRest);
  });

  it('builds exactly the pinned world when the placements are in the first region', async () => {
    const plain = await built();
    const placed = await built([FIRST_REGION]);

    expect(placed.described).toEqual(plain.described);
  });
});
