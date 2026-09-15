import { describe, expect, it } from 'vitest';
import {
  atlasVec3,
  navigationRegionForIsland,
  ownedDistrictNavigation,
  parseOwnedDistrict,
  resolveGroundMovement,
} from '../src/index.js';
import { island } from './fixture.js';

const fixture = {
  profile: 'exulanica.owned-district/v1',
  district_id: 'district',
  name: 'Test district',
  seed: 7,
  bounds_cm: [-1000, -1000, 1000, 1000],
  materials: [],
  sidewalks: [],
  source_records: [{
    dataset_id: 'open',
    provider_revision: 'v1',
    sha256: 'a'.repeat(64),
    attribution: 'Open source',
    operation_rights: { display: true, persist: true, modify: true },
  }],
  buildings: [{
    id: 'doitt_id:1',
    bin: null,
    name: 'Building',
    construction_year: null,
    height_cm: 1000,
    material: 0,
    render_batch_id: 0,
    bbox_cm: [-100, -300, 100, 300],
    polygons: [[[[-100, -300], [100, -300], [100, 300], [-100, 300], [-100, -300]]]],
  }],
};

describe('owned district contract', () => {
  it('builds bounded visible support and exact footprint collision', () => {
    const district = parseOwnedDistrict(fixture);
    const world = ownedDistrictNavigation(district);
    const collision = resolveGroundMovement(world, {
      current: atlasVec3(-5, world.eyeHeight, 0),
      desired: atlasVec3(5, world.eyeHeight, 0),
      lastSafe: atlasVec3(-5, world.eyeHeight, 0),
    });
    expect(collision.collided).toBe(true);
    expect(collision.position.x).toBeLessThan(-1.3);

    const edge = resolveGroundMovement(world, {
      current: atlasVec3(9, world.eyeHeight, 9),
      desired: atlasVec3(12, world.eyeHeight, 9),
      lastSafe: atlasVec3(9, world.eyeHeight, 9),
    });
    expect(edge.recovered).toBe(true);
    expect(edge.recoveryReason).toBe('no-surface');
  });

  /*
   * The district used to hand back `regions: []`, and because `resolveDirectNavigation` looks its
   * target up in that array first, every region in an owned district answered
   * `outside-resident-field`. Nothing about the memories had changed; they were simply not
   * declared, so travel to any of them was refused.
   */
  it('declares the memories standing on its ground and omits the ones beyond it', () => {
    const district = parseOwnedDistrict(fixture);
    const inside = island({ key: 'inside', createdAt: 1, anchors: [], position: [4, 0, -3] });
    const beyond = island({ key: 'beyond', createdAt: 2, anchors: [], position: [40, 0, 0] });
    const world = ownedDistrictNavigation(
      district,
      [inside, beyond].map(navigationRegionForIsland),
    );
    expect(world.regions.map((region) => region.islandId)).toEqual([inside.islandId]);
    // Not a radius test. The surface is the district rectangle, so the question a declared region
    // has to answer is whether this district has ground under it, not how far out it sits.
    expect(world.surface.sample(beyond.placement.position.x, beyond.placement.position.z)).toBeNull();
  });

  it('rejects an unadmitted source before rendering', () => {
    expect(() => parseOwnedDistrict({
      ...fixture,
      source_records: [{ ...fixture.source_records[0], operation_rights: { display: true } }],
    })).toThrow(/not admitted/);
  });
});
