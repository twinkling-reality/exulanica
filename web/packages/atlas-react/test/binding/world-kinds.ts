/**
 * The kinds of world the app can hand `AtlasBinding.create`, as option sets.
 *
 * Shared by the null-device suites (`binding-harness.ts`) and the GPU pixel scenes
 * (`gpu/binding-pixels.ts`), so both describe the same worlds. It imports no test runner and no
 * Node module: the decoded `.opm` pin a world needs is passed in, read from disk by the suites
 * and fetched by the browser page.
 *
 * A generated tile is represented by a mount that keeps its binding contract
 * (`generated-tile/binding-contract.ts`) and draws one named entity, because what is pinned here
 * is the binding's side of that contract, not a tile's geometry.
 */
import * as pc from 'playcanvas';
import {
  atlasVec3,
  buildNavigationWorld,
  islandId,
  localVec3,
  makeIsland,
  makeScene,
  placement,
  type AtlasScene,
  type Island,
} from '@exulanica/atlas-core';
import type { AtlasBindingOptions } from '../../src/playcanvas/atlas-binding.js';
import type { AuthoredRegion } from '../../src/playcanvas/world-kind.js';
import type { AuthoredPointMapPlacement } from '../../src/playcanvas/authored-point-maps.js';
import type { GeneratedTileMount } from '../../src/playcanvas/generated-tile/binding-contract.js';
import type { PointMap } from '../../src/playcanvas/opm.js';

export const STARTER_REGION = islandId('region:starter');
export const FIRST_REGION = islandId('region:first');
export const SECOND_REGION = islandId('region:second');

/** Every option combination the app hands the binding, named by what a person would call it. */
export const WORLD_KINDS = [
  'authored-endless',
  'authored-with-estimate',
  'authored-flat',
  'personal-regions',
  'owned-district',
  'generated-tile',
  'google-reference',
  'authored-and-google',
] as const;
export type WorldKind = (typeof WORLD_KINDS)[number];

export const ENDLESS_REGION: AuthoredRegion = Object.freeze({
  regionId: STARTER_REGION,
  module: Object.freeze({ key: 'region.authored-ground' as const, version: 2 as const }),
  ground: Object.freeze({ kind: 'endless' as const, elevationMm: 0 }),
  spawn: Object.freeze({ xMm: 0, yMm: 0, zMm: 4000, yawMicroradians: 0 }),
});

export const FLAT_REGION: AuthoredRegion = Object.freeze({
  regionId: STARTER_REGION,
  module: Object.freeze({ key: 'region.authored-ground' as const, version: 1 as const }),
  ground: Object.freeze({ kind: 'flat' as const, halfWidthMm: 12_000, halfDepthMm: 8_000, elevationMm: 0 }),
  spawn: Object.freeze({ xMm: 0, yMm: 0, zMm: 4000, yawMicroradians: 0 }),
});

function region(id: ReturnType<typeof islandId>, x: number, z: number, ordinal: number, anchors: number): Island {
  return makeIsland({
    islandId: id,
    creationOrdinal: ordinal,
    createdAt: ordinal,
    placement: placement(atlasVec3(x, 0, z), 0.4 * ordinal, 1),
    rung: 4,
    scaleIsMetric: false,
    footprintRadiusLocal: 6,
    viewpointLocal: localVec3(0, 1.6, 0),
    anchors: Array.from({ length: anchors }, (_, index) => Object.freeze({
      anchorId: `${id}/anchor-${index}` as never,
      islandId: id,
      occurrenceId: `occ/${id}/${index}` as never,
      // The first anchor of a region is a place, so the region draws a mote; the rest are people.
      kind: index === 0 ? 'place' as const : 'person' as const,
      local: localVec3(index - 1, 1, -2),
      focusRadiusLocal: 0.4,
      entityId: null,
      linkState: 'confirmed' as const,
      provenance: 'inference' as const,
      confidence: 'high' as const,
      occurrenceCount: 1,
      resolved: true,
      evidence: Object.freeze([]),
    })),
    layoutEntities: new Set(),
  });
}

/** Two regions far enough from the origin that the render origin rebases on the first frame. */
export const PERSONAL_SCENE: AtlasScene = makeScene([
  region(FIRST_REGION, 120, -80, 1, 2),
  region(SECOND_REGION, 150, -60, 2, 1),
], 1, 1);

export const DISTRICT_DOCUMENT = Object.freeze({
  profile: 'exulanica.owned-district/v1', district_id: 'harness', name: 'Harness', seed: 1,
  bounds_cm: [-1000, -1000, 1000, 1000],
  materials: [{ name: 'stone', base: '#778899', roughness_milli: 800, metalness_milli: 0 }],
  buildings: [], sidewalks: [], source_records: [],
});

/** A mount that keeps the generated tile's binding contract and draws one named entity. */
export function stubTileMount(): GeneratedTileMount & { readonly disposed: () => boolean } {
  let disposed = false;
  return {
    navigationWorld: buildNavigationWorld(makeScene([], 1, 1), Object.freeze({
      sample: (x: number, z: number) => (Math.abs(x) <= 64 && Math.abs(z) <= 64
        ? Object.freeze({ height: 0.095, normal: Object.freeze({ x: 0, y: 1, z: 0 }) })
        : null),
    })),
    start: Object.freeze({ x: 0, y: 1.715, z: 60, yaw: 0, pitch: 0 }) as never,
    attach: ({ environmentRoot }) => {
      const drawn = new pc.Entity('generated-tile:harness');
      environmentRoot.addChild(drawn);
      return {
        metrics: Object.freeze({
          tileName: 'harness', triangles: 0, drawBatches: 0, transferredBytes: 0,
          decodedTextureBytes: 0, unavailableSurfaces: 0, neighbours: Object.freeze([]),
          lookId: 'harness', lookVersion: 1,
        }),
        dispose: () => { disposed = true; drawn.destroy(); },
      };
    },
    disposed: () => disposed,
  };
}

/** A Google configuration that is switched on. The suites refuse its network; the GPU page never builds it. */
export const GOOGLE_ON = Object.freeze({
  enabled: true, apiKey: 'harness-key', longitude: -73.99, latitude: 40.74, altitude: 10,
});

/** One placed depth estimate standing 1.5 m east and 3 m north of the starter origin. */
export function estimateOf(map: PointMap): AuthoredPointMapPlacement {
  return Object.freeze({
    instanceId: 'estimate:harness',
    map,
    transform: Object.freeze({ xMm: 1500, yMm: 1620, zMm: -3000, yawMicroradians: 0, scaleMilli: 1000 }),
  });
}

/** The options one world kind adds to the base, given the decoded `.opm` pin. */
export function worldOptions(kind: WorldKind, opm: PointMap): Partial<AtlasBindingOptions> {
  switch (kind) {
    case 'authored-endless': return { authoredRegion: ENDLESS_REGION };
    case 'authored-with-estimate': return { authoredRegion: ENDLESS_REGION, authoredPointMaps: [estimateOf(opm)] };
    case 'authored-flat': return { authoredRegion: FLAT_REGION };
    // The first region has a point map, so it draws a cloud and a relief; the second does not.
    case 'personal-regions': return { scene: PERSONAL_SCENE, pointMaps: new Map([[FIRST_REGION, opm]]) };
    case 'owned-district': return { ownedDistrict: { document: DISTRICT_DOCUMENT as never, residentBytes: 100 } };
    case 'generated-tile': return { generatedTile: stubTileMount() };
    case 'google-reference': return { googleTiles: GOOGLE_ON };
    case 'authored-and-google': return { authoredRegion: ENDLESS_REGION, googleTiles: GOOGLE_ON };
  }
}
