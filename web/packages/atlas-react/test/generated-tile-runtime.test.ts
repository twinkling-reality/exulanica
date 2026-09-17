// @vitest-environment happy-dom
import { createHash, webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { beforeAll, describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { atlasVec3, parseTextureSetManifest, resolveGroundMovement, type TextureSetDigest } from '@exulanica/atlas-core';
import { GRAMMAR_TABLES, PROJECTION_DEFINITIONS, bakeTile, decodeOwd, type DecodedProjection, type GrammarTable } from '@exulanica/loom-tess/core';
import {
  GeneratedTileRefusal,
  MATERIAL_NONE_EXISTS_REASON,
  loadGeneratedTile,
  type LoadedGeneratedTile,
} from '../src/playcanvas/generated-tile/tile-runtime.js';
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
});

describe('loading a baked tile through tess\'s decoder', () => {
  it('draws only what the container draws, and states every record it does not', () => {
    const drawn = tile.ranges.filter((range) => range.state === 'drawn');
    expect(drawn.map((range) => range.kind)).toEqual(['city.terrain']);
    const terrain = drawn[0]!;
    // Exact terrain that no material record dresses is drawn, as the stated unavailable surface.
    expect(terrain.state === 'drawn' && terrain.surface).toBe('unavailable');
    expect(terrain.state === 'drawn' && terrain.reason).toBe(MATERIAL_NONE_EXISTS_REASON);
    expect(terrain.state === 'drawn' && terrain.triangleCount).toBe(512);
    expect(terrain.identity).toBe('2f14328d-39f8-5bee-a06a-f963b701ccf3');
    const decoded = decodeOwd(baked);
    const header = decoded.projections.find((projection) => projection.header.name === 'render_batch')!.header;
    const drawnEntry = header.entries.find((entry) => entry.state === 'drawn');
    expect(drawnEntry?.state === 'drawn' && drawnEntry.material).toEqual({ state: 'none-exists' });
    // Halo records are context: the container lists them, and the runtime neither draws nor lists them.
    const halo = header.entries.filter((entry) => entry.state === 'halo').map((entry) => entry.record);
    expect(halo).toHaveLength(3);
    expect(halo.every((record) => decoded.header.records[record]!.membership === 'halo')).toBe(true);
    expect(tile.ranges.some((range) => halo.includes(range.record))).toBe(false);
    const listed = header.entries.filter((entry) => entry.state !== 'not_in_projection' && entry.state !== 'halo').length;
    expect(tile.ranges).toHaveLength(listed);
    expect(listed).toBe(62);
    for (const range of tile.ranges) {
      if (range.state === 'drawn') continue;
      expect(range.state).toBe('unavailable');
      expect(range.needs.length).toBeGreaterThan(0);
      expect(range.reason).toBe(`Not drawn yet: its geometry waits on ${range.needs.join(', ')}.`);
    }
    const massing = tile.ranges.find((range) => range.kind === 'city.massing')!;
    expect(massing.identity).toBe('5488228a-3210-54a7-9517-968a75f4624b');
    expect(massing.state === 'unavailable' && massing.needs).toEqual(['massing_faces']);
    expect(tile.ranges.some((range) => range.kind === 'city.surface_material')).toBe(false);
  });

  it('maps every drawn triangle back to its record, and nothing else', () => {
    for (let triangle = 0; triangle < 512; triangle += 1) {
      expect(tile.rangeAtTriangle(triangle)?.kind).toBe('city.terrain');
    }
    expect(tile.rangeAtTriangle(512)).toBeNull();
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
  });

  it('refuses every tile on a page without crypto.subtle', async () => {
    await expect(loadGeneratedTile({ name: 'x', bytes: baked, manifest, fetchSet: noSets, digest: null }))
      .rejects.toThrow(/no crypto\.subtle/);
  });
});

describe('standing on the tile\'s own nav_envelope', () => {
  it('samples support from the envelope and opens standing on it, eye 1.62 m above it', () => {
    const navigation = tile.navigation;
    expect(navigation.support).toEqual({ state: 'nav_envelope', triangles: 368 });
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
    // The middle of the tile is drawn, but the envelope carves capsule clearance around the records
    // there, so it supports nothing: support is never read from what is drawn.
    const [mx, , mz] = tileToRenderer(64000, 64000, 0);
    expect(tile.pick([mx, 5, mz], [0, -1, 0])?.range.kind).toBe('city.terrain');
    expect(world.surface.sample(mx, mz)).toBeNull();
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

describe('a tile with no nav_envelope', () => {
  const extent = { min: [-4000, -4000, -200] as const, max: [8000, 8000, 640] as const };
  const navigation = tileNavigation(undefined, extent, CITY_V2_CAPSULE);

  it('has no support anywhere, says so, and opens at a stated viewpoint outside the tile', () => {
    expect(navigation.support).toEqual({ state: 'unavailable', reason: 'The tile carries no nav_envelope, so there is nothing to stand on.' });
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
    expect(attachment.metrics).toMatchObject({ tileName: 'tile-conformance', triangles: 512, drawBatches: 1, unavailableSurfaces: 1, decodedTextureBytes: 0 });
    const root = environmentRoot.findByName('generated-tile:tile-conformance') as pc.Entity;
    const renders = root.findComponents('render') as pc.RenderComponent[];
    expect(renders).toHaveLength(1);
    const mesh = renders[0]!.meshInstances[0]!.mesh;
    expect(mesh.vertexBuffer?.numVertices).toBe(289);
    const decoded = decodeOwd(baked).projections[0]!;
    const drawn: number[] = [];
    mesh.getPositions(drawn);
    // The same 289 vertices, rotated into the renderer frame, and no other: the mesh keeps
    // first-use order, so compare them as sorted triples.
    const triples = (values: ArrayLike<number>): string[] => {
      const out: string[] = [];
      for (let vertex = 0; vertex < values.length / 3; vertex += 1) {
        out.push([values[vertex * 3]!, values[vertex * 3 + 1]!, values[vertex * 3 + 2]!].map((value) => Math.fround(value) + 0).join(','));
      }
      return out.sort();
    };
    const expected: number[] = [];
    for (let vertex = 0; vertex < 289; vertex += 1) {
      expected.push(decoded.position[vertex * 3]!, decoded.position[vertex * 3 + 2]!, -decoded.position[vertex * 3 + 1]!);
    }
    expect(triples(drawn)).toEqual(triples(expected));
    expect(renders[0]!.meshInstances[0]!.mesh.indexBuffer[0]?.numIndices).toBe(512 * 3);
    expect(app.scene.fog.start).toBe(tile.look.fog.startM);
    attachment.dispose();
    expect(environmentRoot.findByName('generated-tile:tile-conformance')).toBeNull();
    expect(app.scene.fog.start).toBe(fogBefore);
  });
});
