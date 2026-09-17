// @vitest-environment happy-dom
import { createHash, webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { beforeAll, describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { atlasVec3, parseTextureSetManifest, resolveGroundMovement, type TextureSetDigest } from '@exulanica/atlas-core';
import { bakeTile, decodeOwd, type DecodedProjection } from '@exulanica/loom-tess/core';
import {
  GeneratedTileRefusal,
  MATERIAL_NOT_CITED,
  loadGeneratedTile,
  type LoadedGeneratedTile,
} from '../src/playcanvas/generated-tile/tile-runtime.js';
import {
  SUPPORT_SAMPLE_SPACING_M,
  navEnvelopeSupport,
  rendererToTile,
  tileNavigation,
  tileToRenderer,
} from '../src/playcanvas/generated-tile/tile-navigation.js';

// Relative to web/, where the suite runs.
const FIXTURE = 'packages/loom-tess/test/fixtures/tile-conformance.json';
const manifest = parseTextureSetManifest(new Uint8Array(readFileSync('../assets/textures/manifest.json')));
const subtle = webcrypto.subtle as unknown as TextureSetDigest;
const sha256 = async (bytes: Uint8Array): Promise<string> => createHash('sha256').update(bytes).digest('hex');
const noSets = async (): Promise<Uint8Array> => { throw new Error('this test fetches no texture set'); };

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
    expect(terrain.state === 'drawn' && terrain.surface).toBe('unavailable');
    expect(terrain.state === 'drawn' && terrain.reason).toBe(MATERIAL_NOT_CITED);
    expect(terrain.state === 'drawn' && terrain.triangleCount).toBe(18);
    expect(terrain.identity).toBeNull();
    const header = decodeOwd(baked).projections.find((projection) => projection.header.name === 'render_batch')!.header;
    const listed = header.entries.filter((entry) => entry.state !== 'not_a_surface').length;
    expect(tile.ranges).toHaveLength(listed);
    for (const range of tile.ranges) {
      if (range.state === 'drawn') continue;
      expect(range.state).toBe('unavailable');
      expect(range.needs.length).toBeGreaterThan(0);
      expect(range.reason).toBe(`Not drawn: the record lacks ${range.needs.join(', ')}.`);
    }
    const massing = tile.ranges.find((range) => range.kind === 'city.massing')!;
    expect(massing.identity).toBe('3b982423-5f54-5932-98b4-0a7de4a190e9');
    expect(tile.ranges.some((range) => range.kind === 'city.surface_material')).toBe(false);
  });

  it('maps every drawn triangle back to its record, and nothing else', () => {
    for (let triangle = 0; triangle < 18; triangle += 1) {
      expect(tile.rangeAtTriangle(triangle)?.kind).toBe('city.terrain');
    }
    expect(tile.rangeAtTriangle(18)).toBeNull();
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

describe('standing on a tile with no nav_envelope', () => {
  it('has no support anywhere, says so, and opens at a stated viewpoint outside the tile', () => {
    const navigation = tile.navigation;
    expect(navigation.support).toEqual({ state: 'unavailable', reason: 'The tile carries no nav_envelope, so there is nothing to stand on.' });
    expect(navigation.collisionState.state).toBe('unavailable');
    expect(navigation.viewpointOnly).toBe(true);
    const world = navigation.world;
    for (const [x, z] of [[0, 0], [2, -2], [navigation.start.x, navigation.start.z], [-3.9, 3.9]] as const) {
      expect(world.surface.sample(x, z)).toBeNull();
    }
    expect(world.eyeHeight).toBe(1.62);
    expect(world.cameraRadius).toBe(0.34);
    expect(world.surfaceSampleSpacing).toBe(SUPPORT_SAMPLE_SPACING_M);
    // The terrain spans y from -4000 to 8000 mm; the viewpoint stands 6 m south of it, facing north.
    expect(navigation.start).toMatchObject({ y: 1.62, yaw: 0 });
    expect(rendererToTile(navigation.start.x, 0, navigation.start.z)[1]).toBeCloseTo(-10000, 6);
    expect(navigation.start.pitch).toBeLessThan(0);
  });

  it('keeps a blocked walker exactly where the viewpoint is, with the no-surface reason', () => {
    const { world, start } = tile.navigation;
    const current = atlasVec3(start.x, start.y, start.z);
    const resolution = resolveGroundMovement(world, { current, desired: atlasVec3(start.x, start.y, start.z - 1), lastSafe: null });
    expect(resolution.recovered).toBe(true);
    expect(resolution.recoveryReason).toBe('no-surface');
    expect([resolution.position.x, resolution.position.y, resolution.position.z]).toEqual([start.x, start.y, start.z]);
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
      name: 'nav_envelope', triangle_digest: '0'.repeat(64), origin_mm: origin,
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
    const kerb = tileNavigation(envelope(150), extent);
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
    const wall = walk(tileNavigation(envelope(200), extent));
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
    expect(attachment.metrics).toMatchObject({ tileName: 'tile-conformance', triangles: 18, drawBatches: 1, unavailableSurfaces: 1, decodedTextureBytes: 0 });
    const root = environmentRoot.findByName('generated-tile:tile-conformance') as pc.Entity;
    const renders = root.findComponents('render') as pc.RenderComponent[];
    expect(renders).toHaveLength(1);
    const mesh = renders[0]!.meshInstances[0]!.mesh;
    expect(mesh.vertexBuffer?.numVertices).toBe(16);
    const decoded = decodeOwd(baked).projections[0]!;
    const drawn: number[] = [];
    mesh.getPositions(drawn);
    // The same sixteen vertices, rotated into the renderer frame, and no other: the mesh keeps
    // first-use order, so compare them as sorted triples.
    const triples = (values: ArrayLike<number>): string[] => {
      const out: string[] = [];
      for (let vertex = 0; vertex < values.length / 3; vertex += 1) {
        out.push([values[vertex * 3]!, values[vertex * 3 + 1]!, values[vertex * 3 + 2]!].map((value) => Math.fround(value) + 0).join(','));
      }
      return out.sort();
    };
    const expected: number[] = [];
    for (let vertex = 0; vertex < 16; vertex += 1) {
      expected.push(decoded.position[vertex * 3]!, decoded.position[vertex * 3 + 2]!, -decoded.position[vertex * 3 + 1]!);
    }
    expect(triples(drawn)).toEqual(triples(expected));
    expect(renders[0]!.meshInstances[0]!.mesh.indexBuffer[0]?.numIndices).toBe(18 * 3);
    expect(app.scene.fog.start).toBe(tile.look.fog.startM);
    attachment.dispose();
    expect(environmentRoot.findByName('generated-tile:tile-conformance')).toBeNull();
    expect(app.scene.fog.start).toBe(fogBefore);
  });
});
