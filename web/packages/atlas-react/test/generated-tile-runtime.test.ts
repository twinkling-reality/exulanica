// @vitest-environment happy-dom
import { createHash, webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { beforeAll, describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { atlasVec3, parseTextureSetManifest, resolveGroundMovement, type TextureSetDigest } from '@exulanica/atlas-core';
import { routeObstructionRings } from '@exulanica/loom-tess/core';
import { GRAMMAR_TABLES, PROJECTION_DEFINITIONS, bakeTile, decodeOwd, type DecodedProjection, type GrammarTable } from '@exulanica/loom-tess/core';
import { applyTileEnvironment } from '../src/playcanvas/generated-tile/environment.js';
import { TILE_LOOK_V1 } from '../src/playcanvas/generated-tile/look.js';
import {
  GeneratedTileRefusal,
  MATERIAL_NONE_EXISTS_REASON,
  batchTileSurfaces,
  loadGeneratedTile,
  type GeneratedTileRange,
  type GeneratedTileSurface,
  type LoadedGeneratedTile,
  type SurfacePlacement,
} from '../src/playcanvas/generated-tile/tile-runtime.js';
import { surfaceUv, unavailableUv } from '../src/playcanvas/generated-tile/texture-materials.js';
import {
  SUPPORT_SAMPLE_SPACING_M,
  navEnvelopeSupport,
  rendererToTile,
  tileCapsule,
  tileNavigation,
  tileToRenderer,
  unsupportedFrame,
  type TileCapsule,
} from '../src/playcanvas/generated-tile/tile-navigation.js';

// Relative to web/, where the suite runs.
const FIXTURE = 'packages/loom-tess/test/fixtures/tile-conformance.json';
const manifest = parseTextureSetManifest(new Uint8Array(readFileSync('../assets/textures/manifest.json')));
const subtle = webcrypto.subtle as unknown as TextureSetDigest;
const sha256 = async (bytes: Uint8Array): Promise<string> => createHash('sha256').update(bytes).digest('hex');
const noSets = async (): Promise<Uint8Array> => { throw new Error('this test fetches no texture set'); };
/** The capsule city version 2 states, for the hand-built envelopes below. */
const CITY_V2_CAPSULE: TileCapsule = { radiusM: 0.34, heightM: 1.9, eyeHeightM: 1.62 };

let baked: Uint8Array;
let tile: LoadedGeneratedTile;

beforeAll(async () => {
  baked = (await bakeTile(new Uint8Array(readFileSync(FIXTURE)), sha256)).container;
  tile = await loadGeneratedTile({ name: 'tile-conformance', bytes: baked, manifest, fetchSet: noSets, digest: subtle });
  // Tess carves the navigation envelope exactly and draws the street's own surfaces, so a bake of
  // this fixture is seconds rather than the tenth of a second the default hook timeout assumes.
}, 60_000);

describe('loading a baked tile through tess\'s decoder', () => {
  it('draws only what the container draws, and states every record it does not', () => {
    const drawn = tile.ranges.filter((range) => range.state === 'drawn');
    const repeated = (kind: string, times: number): string[] => Array.from({ length: times }, () => kind);
    expect(drawn.map((range) => range.kind)).toEqual([
      'city.block',
      ...repeated('city.curb_edge', 6),
      ...repeated('city.facade', 9),
      ...repeated('city.interior_backing', 6),
      'city.junction',
      'city.massing',
      ...repeated('city.parcel', 2),
      ...repeated('city.rooftop_object', 2),
      ...repeated('city.street_furniture', 7),
      ...repeated('city.street_segment', 3),
      'city.street_tree',
      'city.terrain',
      ...repeated('city.vitrine', 6),
    ]);
    // The building draws what its faces do not: its own wall where no face covers it, and its roof
    // and parapet, each dressed by its own material record.
    expect(drawn[23]!.state === 'drawn' && drawn[23]!.surfaces.map((surface) => [surface.role, surface.orientation])).toEqual([
      ['wall', 'vertical'], ['roof', 'horizontal'], ['parapet', 'vertical'],
    ]);
    // And behind each face's glass, one plane in the wall role, which is what stops a person
    // looking through a first floor window and out of the far side of the building.
    expect(drawn[16]!.state === 'drawn' && drawn[16]!.surfaces.map((surface) => [surface.role, surface.orientation])).toEqual([
      ['wall', 'vertical'],
    ]);
    const terrain = drawn[39]!;
    // Exact terrain that no material record dresses is drawn, as one stated unavailable surface. It
    // is the patch less the carriageways and gutters the segments draw, so it follows their ranges.
    expect(terrain.state === 'drawn' && terrain.surfaces).toEqual([{
      role: 'terrain', orientation: 'horizontal', state: 'unavailable', textureSetId: null,
      reason: MATERIAL_NONE_EXISTS_REASON, firstVertex: 6961, vertexCount: 478, firstTriangle: 3235, triangleCount: 495,
    }]);
    expect(terrain.state === 'drawn' && terrain.triangleCount).toBe(495);
    expect(terrain.identity).toBe('2f14328d-39f8-5bee-a06a-f963b701ccf3');
    // A segment draws a carriageway and a gutter, each dressed by a texture set this test serves none of.
    const segment = drawn[36]!;
    expect(segment.state === 'drawn' && segment.surfaces.map((surface) => [surface.role, surface.orientation, surface.state])).toEqual([
      ['carriageway', 'horizontal', 'unavailable'],
      ['gutter', 'horizontal', 'unavailable'],
    ]);
    const decoded = decodeOwd(baked);
    const header = decoded.projections.find((projection) => projection.header.name === 'render_batch')!.header;
    const drawnEntry = header.entries.find((entry, index) => entry.state === 'drawn' && decoded.header.records[index]!.kind === 'city.terrain');
    expect(drawnEntry?.state === 'drawn' && drawnEntry.surfaces).toEqual([{
      role: 'terrain', material: { state: 'none-exists' }, orientation: 'horizontal',
      first_vertex: 6961, vertex_count: 478, first_triangle: 3235, triangle_count: 495,
    }]);
    // Halo records are context: the container lists them, and the runtime neither draws nor lists them.
    const halo = header.entries.filter((entry) => entry.state === 'halo').map((entry) => entry.record);
    expect(halo).toHaveLength(3);
    expect(halo.every((record) => decoded.header.records[record]!.membership === 'halo')).toBe(true);
    expect(tile.ranges.some((range) => halo.includes(range.record))).toBe(false);
    const listed = header.entries.filter((entry) => entry.state !== 'not_in_projection' && entry.state !== 'halo').length;
    expect(tile.ranges).toHaveLength(listed);
    expect(listed).toBe(55);
    for (const range of tile.ranges) {
      if (range.state === 'drawn') continue;
      expect(range.state).toBe('unavailable');
      expect(range.needs.length).toBeGreaterThan(0);
      expect(range.reason).toBe(`Not drawn yet: its geometry waits on ${range.needs.join(', ')}.`);
    }
    const massing = tile.ranges.find((range) => range.kind === 'city.massing')!;
    expect(massing.identity).toBe('5488228a-3210-54a7-9517-968a75f4624b');
    expect(massing.state).toBe('drawn');
    expect(tile.ranges.some((range) => range.kind === 'city.surface_material')).toBe(false);
  });

  it('maps every drawn triangle back to its record, and nothing else', () => {
    // Every triangle belongs to the record that drew it, in record order: the nine faces, the plane
    // behind each one's glass, the building, its rooftop objects, the street furniture, the three
    // segments, the terrain and the vitrines in the shopfronts.
    const runs: [string, number, number][] = [
      ['city.block', 0, 6],
      ['city.curb_edge', 6, 368],
      ['city.facade', 368, 2316],
      ['city.interior_backing', 2316, 2328],
      ['city.junction', 2328, 2404],
      ['city.massing', 2404, 2451],
      ['city.parcel', 2451, 2455],
      ['city.rooftop_object', 2455, 2665],
      ['city.street_furniture', 2665, 2957],
      ['city.street_segment', 2957, 2981],
      ['city.street_tree', 2981, 3235],
      ['city.terrain', 3235, 3730],
      ['city.vitrine', 3730, 4042],
    ];
    for (const [kind, from, to] of runs) {
      for (let triangle = from; triangle < to; triangle += 1) {
        expect(tile.rangeAtTriangle(triangle)?.kind).toBe(kind);
      }
    }
    expect(tile.rangeAtTriangle(4042)).toBeNull();
    expect(tile.rangeAtTriangle(-1)).toBeNull();
  });

  it('refuses a tile whose bytes are not what its records bake to', async () => {
    const sections = decodeOwd(baked).header.sections;
    const start = (name: string): number => sections.find((section) => section.name === name)!.byte_offset;
    // One float of the payload, one integer of the digested positions, and one index.
    for (const offset of [start('position') + 1, start('position_mm'), start('index')]) {
      const tampered = new Uint8Array(baked);
      tampered[offset] = tampered[offset]! ^ 1;
      await expect(loadGeneratedTile({ name: 'tampered', bytes: tampered, manifest, fetchSet: noSets, digest: subtle }))
        .rejects.toBeInstanceOf(GeneratedTileRefusal);
    }
    const truncated = baked.subarray(0, baked.byteLength - 4);
    await expect(loadGeneratedTile({ name: 'short', bytes: truncated, manifest, fetchSet: noSets, digest: subtle }))
      .rejects.toThrow(/refused/);
    // Four loads of a container whose navigation envelope is now carved, each digesting it whole.
  }, 30_000);

  it('refuses every tile on a page without crypto.subtle', async () => {
    await expect(loadGeneratedTile({ name: 'x', bytes: baked, manifest, fetchSet: noSets, digest: null }))
      .rejects.toThrow(/no crypto\.subtle/);
  });
});

describe('standing on the tile\'s own nav_envelope', () => {
  it('samples support from the envelope and opens standing on it, eye 1.62 m above it', () => {
    const navigation = tile.navigation;
    expect(navigation.support).toEqual({ state: 'nav_envelope', triangles: 5755 });
    expect(navigation.collisionState.state).toBe('unavailable');
    expect(navigation.viewpointOnly).toBe(false);
    const world = navigation.world;
    // The capsule is the one city version 2 states for the envelope's capsule clearance.
    expect(navigation.capsule).toEqual(CITY_V2_CAPSULE);
    expect(world.eyeHeight).toBe(1.62);
    expect(world.cameraRadius).toBe(0.34);
    expect(world.surfaceSampleSpacing).toBe(SUPPORT_SAMPLE_SPACING_M);
    // The terrain is the 128 m patch at the datum; the stance is the middle of the envelope's
    // southern edge.
    const [x, , z] = tileToRenderer(64000, 0, 0);
    expect(navigation.start.x).toBeCloseTo(x, 12);
    expect(navigation.start.z).toBeCloseTo(z, 12);
    expect(navigation.start.y).toBeCloseTo(1.62, 12);
    expect(world.surface.sample(x, z)?.height).toBe(0);
    // Off the tile there is nothing.
    const [ox, , oz] = tileToRenderer(130000, 1000, 0);
    expect(world.surface.sample(ox, oz)).toBeNull();
    // The middle of the tile is drawn and stood on, by two meshes neither of which is read for the
    // other: the render batch draws the ground there and the envelope supports a capsule on it. It
    // is a curb's footway now that curbs draw, where it was bare terrain before them.
    const [mx, , mz] = tileToRenderer(64000, 64000, 0);
    expect(tile.pick([mx, 5, mz], [0, -1, 0])?.range.kind).toBe('city.curb_edge');
    // And it stands above the carriageway rather than at the datum, because a footway rises from
    // the back of its kerb top by the crossfall its curb states.
    expect(world.surface.sample(mx, mz)?.height).toBeCloseTo(0.0676, 4);
    // Inside the building's base ring nothing supports anybody: the envelope keeps a capsule clear
    // of what the navigation table says obstructs, whether or not the building itself is drawn.
    const [bx, , bz] = tileToRenderer(47650, 55380, 0);
    expect(world.surface.sample(bx, bz)).toBeNull();
  });

  it('walks across the terrain at its sampled height', () => {
    const { world, start } = tile.navigation;
    const [, , north] = tileToRenderer(64000, 2000, 0);
    const resolution = resolveGroundMovement(world, {
      current: atlasVec3(start.x, start.y, start.z), desired: atlasVec3(start.x, start.y, north), lastSafe: atlasVec3(start.x, start.y, start.z),
    });
    expect(resolution.recovered).toBe(false);
    expect(resolution.position.y).toBeCloseTo(world.surface.sample(start.x, north)!.height + 1.62, 12);
  });
});

describe('the route obstruction rings a tile states', () => {
  // MEASURED 2026-09-18: the mapper sat on main for hours with nothing calling it, so a tile that
  // states rings served a page that carried none and a route rule had nothing to decide with. This
  // holds the wiring rather than the mapping: the rings a container states must reach the world.
  it('states them on the tile, named by record, for a route rule to read', () => {
    for (const obstacle of tile.routeObstructions.obstacles) {
      // `kind:identity`, so a run record can bind what a walk passed to the record that put it there.
      expect(obstacle.id).toMatch(/^[a-z_.]+:.+/);
      expect(obstacle.rings[0]!.length).toBeGreaterThanOrEqual(3);
    }
  });

  it('KEEPS THEM OUT OF THE NAVIGATION WORLD, because that field stops bodies', () => {
    // MEASURED 2026-09-18: carrying route rings in `polygonObstacles` made a bench stop a walker
    // 344 mm from its edge against a stated capsule radius of 340. The resolver collides against that
    // field by construction, with no flag and no opt-out, so the only way for a ring to stop nothing
    // is for it not to be there. This asserts the property the panel claims rather than the plumbing.
    expect(tile.navigation.world.polygonObstacles ?? []).toEqual([]);
  });

  it('proves that field really does block, so the emptiness above is load bearing', () => {
    // A ring square around a point half a metre north of the stance, in the renderer's frame.
    const from = tile.navigation.start;
    const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]] as const;
    const blocked = {
      ...tile.navigation.world,
      polygonObstacles: [{
        id: 'test:ring',
        rings: [corners.map(([dx, dz]) => atlasVec3(from.x + dx, 0, from.z - 0.5 + dz))],
      }],
    };
    const through = resolveGroundMovement(blocked, {
      current: atlasVec3(from.x, from.y, from.z),
      desired: atlasVec3(from.x, from.y, from.z - 0.5),
      lastSafe: null,
    });
    expect(through.collided || through.recovered).toBe(true);
  });

  it('states what it refused, so a smaller set is never silent', () => {
    for (const refusal of tile.routeObstructions.refused) {
      expect(refusal.reason).not.toBe('');
      expect(refusal.identity).toBeDefined();
    }
    // Every ring the container states is either carried or refused with a reason: none vanishes.
    expect(tile.routeObstructions.obstacles.length + tile.routeObstructions.refused.length)
      .toBe(routeObstructionRings(tile.header).length);
  });
});

describe('where a resolved move puts the eye', () => {
  // MEASURED 2026-09-18 by two lanes from opposite sides of one container: a walk of 121.982 m
  // reported an eye at 1766 mm while the corridor lane's sampler said the line's support was 170,
  // which would have made the eye 1596 rather than the 1620 the grammar states. The sampler was
  // reading a triangle's highest corner rather than interpolating its plane, and the footway falls
  // 56 mm across its width to the gutter; corrected, support is 146 and 146 + 1620 is exactly 1766.
  // So the runtime and the container agree, and this holds the line they agree on: an eye is the
  // sampled support plus the capsule's stated eye height, and nothing else. If that ever stops being
  // true, every comparison between a trace and a container's support heights silently changes
  // meaning, and nothing in either lane's tools would notice.
  it('stands the eye exactly the stated eye height above the support it sampled, after a move', () => {
    const world = tile.navigation.world;
    const from = tile.navigation.start;
    // The stance is the middle of the envelope's SOUTHERN EDGE facing north, so the step that stays
    // on the envelope is northward, which is -z in the renderer's frame. A step the other way leaves
    // the envelope and is recovered, which is correct and is not what this test is about.
    const sample = world.surface.sample(from.x, from.z - 0.5);
    expect(sample, 'the envelope supports a point half a metre north').not.toBeNull();
    const resolved = resolveGroundMovement(world, {
      current: atlasVec3(from.x, from.y, from.z),
      desired: atlasVec3(from.x, from.y, from.z - 0.5),
      lastSafe: null,
    });
    expect(resolved.recovered).toBe(false);
    expect(resolved.position.y).toBeCloseTo(sample!.height + world.eyeHeight, 12);
    expect(resolved.position.y - sample!.height).toBeCloseTo(1.62, 12);
  });
});

describe('a tile whose nav_envelope is there but empty', () => {
  // MEASURED on the corridor lane's first baked street: its container carries a nav_envelope
  // projection with its own digest and no triangle, because the expanders that make walkable
  // geometry do not exist yet. The screen said "carries no nav_envelope", which was false about the
  // container, so the two cases now say which one happened.
  const extent = { min: [-4000, -4000, -200] as const, max: [8000, 8000, 640] as const };
  const empty = {
    header: { name: 'nav_envelope', triangle_count: 0, vertex_count: 0 },
  } as unknown as Parameters<typeof tileNavigation>[0];
  const navigation = tileNavigation(empty, extent, CITY_V2_CAPSULE);

  it('says the projection is there and holds no triangle, and still stands nobody on it', () => {
    expect(navigation.support).toEqual({
      state: 'unavailable',
      reason: "The tile's nav_envelope is empty, so there is nothing to stand on: the projection is there, with its own digest, and it holds no triangle.",
    });
    expect(navigation.viewpointOnly).toBe(true);
    expect(navigation.world.surface.sample(navigation.start.x, navigation.start.z)).toBeNull();
  });
});

describe('a tile with no nav_envelope', () => {
  const extent = { min: [-4000, -4000, -200] as const, max: [8000, 8000, 640] as const };
  const navigation = tileNavigation(undefined, extent, CITY_V2_CAPSULE);

  it('has no support anywhere, says so, and opens at a stated viewpoint outside the tile', () => {
    expect(navigation.support).toEqual({ state: 'unavailable', reason: 'The tile carries no nav_envelope projection, so there is nothing to stand on.' });
    expect(navigation.viewpointOnly).toBe(true);
    for (const [x, z] of [[0, 0], [2, -2], [navigation.start.x, navigation.start.z], [-3.9, 3.9]] as const) {
      expect(navigation.world.surface.sample(x, z)).toBeNull();
    }
    // The extent spans y from -4000 to 8000 mm; the viewpoint stands 6 m south of it, facing north.
    expect(navigation.start).toMatchObject({ y: 1.62, yaw: 0 });
    expect(rendererToTile(navigation.start.x, 0, navigation.start.z)[1]).toBeCloseTo(-10000, 6);
    expect(navigation.start.pitch).toBeLessThan(0);
  });

  it('keeps a blocked walker exactly where the viewpoint is, with the no-surface reason', () => {
    const { world, start } = navigation;
    const current = atlasVec3(start.x, start.y, start.z);
    const resolution = resolveGroundMovement(world, { current, desired: atlasVec3(start.x, start.y, start.z - 1), lastSafe: null });
    expect(resolution.recovered).toBe(true);
    expect(resolution.recoveryReason).toBe('no-surface');
    expect([resolution.position.x, resolution.position.y, resolution.position.z]).toEqual([start.x, start.y, start.z]);
  });
});

describe('drawing per surface', () => {
  // A hand-built render_batch in the payload's metres from its origin (tile frame, z up): a kerb whose
  // vertical face (vertices 0 to 3) and horizontal top (4 to 7) are two surfaces of one record, and a
  // footway (8 to 11) that is another record's only surface.
  const quad = (a: readonly number[], b: readonly number[], c: readonly number[], d: readonly number[]) => [...a, ...b, ...c, ...d];
  const position = new Float32Array([
    ...quad([0, 0, 0], [1, 0, 0], [1, 0, 0.15], [0, 0, 0.15]),
    ...quad([0, 0, 0.15], [1, 0, 0.15], [1, 0.3, 0.15], [0, 0.3, 0.15]),
    ...quad([0, 0.3, 0.15], [1, 0.3, 0.15], [1, 2, 0.15], [0, 2, 0.15]),
  ]);
  const index = new Uint32Array([0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7, 8, 9, 10, 8, 10, 11]);
  const surfaceMm = new Float64Array([
    0, 150, 1000, 150, 1000, 0, 0, 0,
    0, 0, 1000, 0, 1000, 300, 0, 300,
    0, 300, 1000, 300, 1000, 2000, 0, 2000,
  ]);
  const surface = (role: string, orientation: 'vertical' | 'horizontal', first: number, textured: boolean): GeneratedTileSurface => ({
    role, orientation, state: textured ? 'textured' : 'unavailable', textureSetId: textured ? 'cc0.kerb-stone' : null,
    reason: textured ? null : MATERIAL_NONE_EXISTS_REASON, firstVertex: first * 2, vertexCount: 4, firstTriangle: first, triangleCount: 2,
  });
  const face = surface('kerb_face', 'vertical', 0, false);
  const top = surface('kerb_top', 'horizontal', 2, true);
  const footway = surface('footway', 'horizontal', 4, false);
  const extentMm = { min: [0, 0, 0] as const, max: [1000, 2000, 150] as const };
  const ranges: GeneratedTileRange[] = [
    { record: 0, kind: 'city.curb_edge', identity: null, state: 'drawn', firstTriangle: 0, triangleCount: 4, extentMm, surfaces: [face, top] },
    { record: 1, kind: 'city.footway', identity: null, state: 'drawn', firstTriangle: 4, triangleCount: 2, extentMm, surfaces: [footway] },
  ];
  const kerbStone = manifest.byId.get('cc0.kerb-stone')!;
  const placement: SurfacePlacement = {
    reference: { textureSetId: 'cc0.kerb-stone', repeatSizeMillionths: 2_000_000, rotationUrad: 0, offsetUMm: 100, offsetVMm: 0 },
    entry: kerbStone,
  };
  const placements = new Map([[top, placement]]);

  it('batches surfaces by what they are drawn with, not by record, and places each by its own material and orientation', () => {
    const batches = batchTileSurfaces({ position, index }, surfaceMm, ranges, placements, TILE_LOOK_V1);
    expect(batches.map((batch) => [batch.key, batch.triangles, batch.positions.length / 3, batch.indices.length])).toEqual([
      ['', 4, 8, 12],
      ['cc0.kerb-stone', 2, 4, 6],
    ]);
    const [unavailable, textured] = batches as [typeof batches[0], typeof batches[0]];
    // The kerb's face and the footway share the unavailable draw, each with its own orientation's pattern.
    expect(unavailable.uvs.slice(0, 2)).toEqual([...unavailableUv(0, 150, TILE_LOOK_V1, 'vertical')]);
    expect(unavailable.uvs.slice(8, 10)).toEqual([...unavailableUv(0, 300, TILE_LOOK_V1, 'horizontal')]);
    expect(textured.uvs.slice(2, 4)).toEqual([...surfaceUv(1000, 0, placement.reference, kerbStone)]);
    // Positions are rotated into the renderer frame, (x, z, -y), and indices point into their own batch.
    expect(textured.positions.slice(6, 9).map((value) => Math.fround(value) + 0)).toEqual([1, Math.fround(0.15), Math.fround(-0.3)]);
    expect(Math.max(...unavailable.indices)).toBe(7);
    // Normals are per surface: the face points horizontally, the top and the footway straight up.
    for (let vertex = 0; vertex < 4; vertex += 1) {
      const [x, y, z] = unavailable.normals.slice(vertex * 3, vertex * 3 + 3) as [number, number, number];
      expect([Math.abs(x) + Math.abs(y), Math.abs(z)]).toEqual([0, 1]);
      expect(textured.normals.slice(vertex * 3, vertex * 3 + 3).map((value) => value + 0)).toEqual([0, 1, 0]);
      expect(unavailable.normals.slice((vertex + 4) * 3, (vertex + 4) * 3 + 3).map((value) => value + 0)).toEqual([0, 1, 0]);
    }
  });

  it('refuses a surface triangle that reaches outside its surface, and a textured surface with no placement', () => {
    const stray = new Uint32Array(index);
    stray[2] = 4;
    expect(() => batchTileSurfaces({ position, index: stray }, surfaceMm, ranges, placements, TILE_LOOK_V1))
      .toThrow(/kerb_face surface of record 0 uses a vertex outside the surface/);
    expect(() => batchTileSurfaces({ position, index }, surfaceMm, ranges, new Map(), TILE_LOOK_V1))
      .toThrow(/kerb_top surface of record 0 is textured and has no placement/);
  });
});

describe('the frame and the capsule a tile\'s grammar states', () => {
  const city = GRAMMAR_TABLES.find((table) => table.grammar_id === 'city' && table.grammar_version === 2)!;
  const named = { grammar_id: 'city', grammar_version: 2 };

  it('builds the person to the grammar\'s own capsule clearance measures, and to no other numbers', () => {
    expect(tileCapsule([named])).toEqual(CITY_V2_CAPSULE);
    const wider: GrammarTable = {
      ...city,
      measures: { nav_envelope: { capsule_clearance: { eye_height_mm: 1500, height_mm: 1800, radius_mm: 400 } } },
    };
    expect(tileCapsule([named], [wider])).toEqual({ radiusM: 0.4, heightM: 1.8, eyeHeightM: 1.5 });
    const loaded = tileNavigation(undefined, { min: [0, 0, 0], max: [1000, 1000, 0] }, { radiusM: 0.4, heightM: 1.8, eyeHeightM: 1.5 });
    expect([loaded.world.eyeHeight, loaded.world.cameraRadius, loaded.start.y]).toEqual([1.5, 0.4, 1.5]);
  });

  it('refuses to guess a capsule the grammar does not state, or two that disagree', () => {
    expect(tileCapsule([{ grammar_id: 'city', grammar_version: 9 }])).toMatch(/has no grammar table/);
    expect(tileCapsule([named], [{ ...city, measures: {} }])).toMatch(/states no nav_envelope capsule_clearance/);
    const other: GrammarTable = {
      ...city, grammar_id: 'other',
      measures: { nav_envelope: { capsule_clearance: { eye_height_mm: 1620, height_mm: 1900, radius_mm: 300 } } },
    };
    expect(tileCapsule([named, { grammar_id: 'other', grammar_version: 2 }], [city, other])).toMatch(/different capsule clearance/);
    expect(tileCapsule([])).toMatch(/names no grammar/);
  });

  it('places only city_local millimetres with x east, y north and z up', () => {
    const header = decodeOwd(baked).header;
    expect(unsupportedFrame(header.grammars)).toBeNull();
    const frame = header.grammars[0]!.frame;
    for (const changed of [{ ...frame, name: 'wgs84' }, { ...frame, units: 'm' }, { ...frame, axes: 'x_north_y_east_z_up' }]) {
      expect(unsupportedFrame([{ ...header.grammars[0]!, frame: changed }])).toMatch(/this runtime places only city_local/);
    }
  });
});

describe('picking a tile', () => {
  it('finds the drawn triangle under a ray, its record and the distance along a unit ray', () => {
    const [x, , z] = tileToRenderer(1000, 1000, 0);
    const hit = tile.pick([x, 5, z], [0, -1, 0]);
    expect(hit?.range.kind).toBe('city.terrain');
    expect(tile.rangeAtTriangle(hit!.triangle)).toBe(hit!.range);
    expect(hit!.distance).toBeCloseTo(5 - tile.navigation.world.surface.sample(x, z)!.height, 9);
    expect(tile.pick([x, 5, z], [0, 1, 0])).toBeNull();
    const [fx, , fz] = tileToRenderer(130000, 130000, 0);
    expect(tile.pick([fx, 5, fz], [0, -1, 0])).toBeNull();
  });
});

/** A hand-built nav_envelope: a 4 m footway 150 mm up, a 4 m carriageway at 0, and a ramp. */
function envelope(step: number): DecodedProjection {
  const vertices = [
    // footway, y 0 to 4000
    0, 0, step, 4000, 0, step, 4000, 4000, step, 0, 4000, step,
    // carriageway, y -4000 to 0
    0, -4000, 0, 4000, -4000, 0, 4000, 0, 0, 0, 0, 0,
    // a ramp to the east, rising 400 mm over 4 m, above the footway's height range
    4000, 0, step, 8000, 0, step + 400, 8000, 4000, step + 400, 4000, 4000, step,
  ];
  const indices = [0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7, 8, 9, 10, 8, 10, 11];
  const origin = [0, -4000, 0] as const;
  const positionMm = new Int32Array(vertices.map((value, index) => value - origin[index % 3]!));
  return {
    header: {
      name: 'nav_envelope', contract: PROJECTION_DEFINITIONS.find((definition) => definition.name === 'nav_envelope')!.contract,
      triangle_digest: '0'.repeat(64), origin_mm: origin,
      vertex_count: vertices.length / 3, triangle_count: indices.length / 3, entries: [],
    },
    positionMm,
    position: new Float32Array(positionMm.length),
    index: new Uint32Array(indices),
  };
}

describe('support from a nav_envelope', () => {
  const extent = { min: [0, -4000, 0] as const, max: [8000, 4000, 550] as const };

  it('samples the envelope\'s own height, exactly, and nothing off it', () => {
    const { surface, triangles } = navEnvelopeSupport(envelope(150));
    expect(triangles).toBe(6);
    const at = (x: number, y: number) => {
      const [rx, , rz] = tileToRenderer(x, y, 0);
      return surface.sample(rx, rz);
    };
    expect(at(1000, 1000)?.height).toBeCloseTo(0.15, 12);
    expect(at(1000, -1000)?.height).toBe(0);
    expect(at(6000, 2000)?.height).toBeCloseTo(0.35, 12);
    const flat = at(1000, 1000)!.normal;
    expect([flat.x + 0, flat.y, flat.z + 0]).toEqual([0, 1, 0]);
    const ramp = at(6000, 2000)!.normal;
    expect(ramp.y).toBeCloseTo(4000 / Math.hypot(4000, 400), 12);
    expect(ramp.x).toBeLessThan(0);
    expect(at(-1, 1000)).toBeNull();
    expect(at(1000, 4001)).toBeNull();
    expect(at(9000, 0)).toBeNull();
  });

  it('stands the capsule on it and lets a 150 mm kerb be climbed but not a 200 mm step', () => {
    const kerb = tileNavigation(envelope(150), extent, CITY_V2_CAPSULE);
    expect(kerb.viewpointOnly).toBe(false);
    expect(kerb.support).toEqual({ state: 'nav_envelope', triangles: 6 });
    expect(kerb.start.y).toBeCloseTo(1.62, 12);
    const [x, , z] = tileToRenderer(1000, -500, 0);
    const [, , zUp] = tileToRenderer(1000, 500, 0);
    const walk = (navigation: typeof kerb) => resolveGroundMovement(navigation.world, {
      current: atlasVec3(x, 1.62, z), desired: atlasVec3(x, 1.62, zUp), lastSafe: atlasVec3(x, 1.62, z),
    });
    const climbed = walk(kerb);
    expect(climbed.recovered).toBe(false);
    expect(climbed.position.y).toBeCloseTo(0.15 + 1.62, 12);
    const wall = walk(tileNavigation(envelope(200), extent, CITY_V2_CAPSULE));
    expect(wall.recovered).toBe(true);
    expect(wall.recoveryReason).toBe('unsafe-surface');
  });

  it('refuses an envelope with nothing walkable in it', () => {
    const flat = envelope(150);
    const vertical: DecodedProjection = { ...flat, index: new Uint32Array([0, 1, 1]) };
    expect(() => navEnvelopeSupport(vertical)).toThrow(/no walkable triangle/);
  });
});

describe('drawing a tile into the Atlas scene', () => {
  it('adds exactly the drawn triangles under the environment root, and removes them again', () => {
    const canvas = document.createElement('canvas');
    const device = new pc.NullGraphicsDevice(canvas);
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
    app.init(options);
    const camera = new pc.Entity('camera');
    camera.addComponent('camera');
    app.root.addChild(camera);
    const environmentRoot = new pc.Entity('geographic-environment');
    app.root.addChild(environmentRoot);
    const fogBefore = app.scene.fog.start;
    const attachment = tile.attach({ app, environmentRoot, camera });
    // Every surface is unavailable here: the terrain has no material, and this test serves no set
    // for the segments' carriageways and gutters, the building's walls, roofs and parapets, or the
    // plane behind each face's glass.
    expect(attachment.metrics).toMatchObject({ tileName: 'tile-conformance', triangles: 4042, drawBatches: 1, unavailableSurfaces: 124, decodedTextureBytes: 0 });
    const root = environmentRoot.findByName('generated-tile:tile-conformance') as pc.Entity;
    const renders = root.findComponents('render') as pc.RenderComponent[];
    expect(renders).toHaveLength(1);
    const mesh = renders[0]!.meshInstances[0]!.mesh;
    expect(mesh.vertexBuffer?.numVertices).toBe(8375);
    const decoded = decodeOwd(baked).projections[0]!;
    const drawn: number[] = [];
    mesh.getPositions(drawn);
    // The same 4,833 vertices, rotated into the renderer frame, and no other: the mesh keeps
    // first-use order, so compare them as sorted triples.
    const triples = (values: ArrayLike<number>): string[] => {
      const out: string[] = [];
      for (let vertex = 0; vertex < values.length / 3; vertex += 1) {
        out.push([values[vertex * 3]!, values[vertex * 3 + 1]!, values[vertex * 3 + 2]!].map((value) => Math.fround(value) + 0).join(','));
      }
      return out.sort();
    };
    const expected: number[] = [];
    for (let vertex = 0; vertex < 8375; vertex += 1) {
      expected.push(decoded.position[vertex * 3]!, decoded.position[vertex * 3 + 2]!, -decoded.position[vertex * 3 + 1]!);
    }
    expect(triples(drawn)).toEqual(triples(expected));
    expect(renders[0]!.meshInstances[0]!.mesh.indexBuffer[0]?.numIndices).toBe(4042 * 3);
    expect(app.scene.fog.start).toBe(tile.look.fog.startM);
    attachment.dispose();
    expect(environmentRoot.findByName('generated-tile:tile-conformance')).toBeNull();
    expect(app.scene.fog.start).toBe(fogBefore);
  });
});

describe('the camera frame waits for a canvas with a size', () => {
  it('builds no render targets at 0 by 0, builds them once on the first resize, and removes them on dispose', () => {
    const canvas = document.createElement('canvas');
    canvas.width = 0;
    canvas.height = 0;
    const device = new pc.NullGraphicsDevice(canvas);
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
    app.init(options);
    const camera = new pc.Entity('camera');
    camera.addComponent('camera');
    app.root.addChild(camera);
    expect([device.width, device.height]).toEqual([0, 0]);

    const environment = applyTileEnvironment(app, camera, TILE_LOOK_V1);
    // A frame created now would build its targets at 0 by 0: incomplete framebuffers.
    expect(environment.frame).toBeNull();
    expect(camera.camera!.framePasses).toEqual([]);

    device.setResolution(640, 480);
    const frame = environment.frame;
    expect(frame).not.toBeNull();
    expect(camera.camera!.framePasses).toHaveLength(1);
    expect(frame!.ssao.radius).toBe(TILE_LOOK_V1.contactShadow.radiusM);
    device.setResolution(800, 600);
    expect(environment.frame).toBe(frame);

    environment.dispose();
    expect(environment.frame).toBeNull();
    expect(camera.camera!.framePasses).toEqual([]);
    device.setResolution(320, 240);
    expect(environment.frame).toBeNull();
    expect(camera.camera!.framePasses).toEqual([]);
  });

  it('builds the frame at once when the canvas already has a size', () => {
    const canvas = document.createElement('canvas');
    canvas.width = 320;
    canvas.height = 200;
    const device = new pc.NullGraphicsDevice(canvas);
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
    app.init(options);
    const camera = new pc.Entity('camera');
    camera.addComponent('camera');
    app.root.addChild(camera);
    const environment = applyTileEnvironment(app, camera, TILE_LOOK_V1);
    expect(environment.frame).not.toBeNull();
    expect(camera.camera!.framePasses).toHaveLength(1);
    environment.dispose();
    expect(camera.camera!.framePasses).toEqual([]);
  });
});
