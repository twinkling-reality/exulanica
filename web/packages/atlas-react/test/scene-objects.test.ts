import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type * as pc from 'playcanvas';
import { atlasVec3, placement, type IslandId } from '@exulanica/atlas-core';
import {
  AUTHORED_OBJECT_MEDIA_TYPE,
  MICRORADIANS_PER_RADIAN,
  SCALE_MILLI_UNIT,
  SceneObjectRuntime,
  createObjectContainerAsset,
  fetchVerifiedObjectAsset,
  nudgedPose,
  objectAssetBytesPath,
  placementPoseAtAtlasPoint,
  placementPoseBeforeVisitor,
  regionPointFromAtlas,
  safeObjectAssetPath,
  validateGlbContainer,
  yawMicroradiansOf,
  type AuthoredObjectAssetReference,
  type PlacedAuthoredObject,
  type RegionPose,
} from '../src/playcanvas/scene-objects.js';

/**
 * The authored-object boundary, from the outside.
 *
 * Every refusal here is a fetch `playcanvas@2.21.4` would otherwise make on its own account, out
 * of something written inside a container the caller did not author. Malformed containers are
 * built in this file because that is the only way to write those cases.
 *
 * The ACCEPTING cases are different, and deliberately so: they use the three real reviewed CC0
 * assets, checked against the digests in the published `world-objects.json`. A validator is only
 * worth having if it is run against the bytes it will actually meet, and the backend generates
 * these deterministically rather than committing them, so `web/` commits them here and the digest
 * assertion below is what fails if that generator ever moves.
 */

const ISLAND = 'region-a' as IslandId;
const FIXTURES = new URL('../../graph-client/test/fixtures/', import.meta.url);

const reviewedBytes = (key: string): ArrayBuffer => {
  const buffer = readFileSync(new URL(`${key}.glb`, FIXTURES));
  return Uint8Array.from(buffer).buffer;
};

const publishedVersion = JSON.parse(
  readFileSync(new URL('world-objects.json', FIXTURES), 'utf8'),
) as { objects: { asset: { asset_key: string; content_sha256: string; byte_size: number } }[] };

const sha = (bytes: ArrayBuffer): string =>
  createHash('sha256').update(new Uint8Array(bytes)).digest('hex');

function glb(gltf: Record<string, unknown>, binary: Uint8Array | null = null): ArrayBuffer {
  const json = new TextEncoder().encode(JSON.stringify(gltf));
  const jsonPadded = new Uint8Array(Math.ceil(json.length / 4) * 4).fill(0x20);
  jsonPadded.set(json);
  const binPadded = binary === null
    ? null
    : (() => {
        const padded = new Uint8Array(Math.ceil(binary.length / 4) * 4);
        padded.set(binary);
        return padded;
      })();
  const total = 12 + 8 + jsonPadded.length + (binPadded === null ? 0 : 8 + binPadded.length);
  const bytes = new Uint8Array(total);
  const view = new DataView(bytes.buffer);
  view.setUint32(0, 0x46546c67, true);
  view.setUint32(4, 2, true);
  view.setUint32(8, total, true);
  view.setUint32(12, jsonPadded.length, true);
  view.setUint32(16, 0x4e4f534a, true);
  bytes.set(jsonPadded, 20);
  if (binPadded !== null) {
    const at = 20 + jsonPadded.length;
    view.setUint32(at, binPadded.length, true);
    view.setUint32(at + 4, 0x004e4942, true);
    bytes.set(binPadded, at + 8);
  }
  return bytes.buffer;
}

const MINIMAL = {
  asset: { version: '2.0' },
  scenes: [{ nodes: [0] }],
  nodes: [{ mesh: 0 }],
  meshes: [{ primitives: [{ attributes: { POSITION: 0 } }] }],
  buffers: [{ byteLength: 12 }],
};

const container = (): ArrayBuffer => glb(MINIMAL, new Uint8Array(12));

function reference(
  bytes: ArrayBuffer,
  over: Partial<AuthoredObjectAssetReference> = {},
): AuthoredObjectAssetReference {
  return {
    assetKey: 'cc0.marker-cube',
    mediaType: AUTHORED_OBJECT_MEDIA_TYPE,
    contentSha256: sha(bytes),
    byteSize: bytes.byteLength,
    ...over,
  };
}

const respond = (bytes: ArrayBuffer, status = 200) => vi.fn(async () =>
  new Response(status === 200 ? bytes : null, { status }));

const options = (fetchImpl: typeof globalThis.fetch) =>
  ({ baseUrl: 'https://exulanica.test', token: 'token', fetch: fetchImpl });

describe('the reviewed assets this build will actually meet', () => {
  it('accepts all three, and their bytes are the ones the published version names', () => {
    const published = new Map(publishedVersion.objects.map((object) =>
      [object.asset.asset_key, object.asset]));
    for (const key of ['cc0.marker-cube', 'cc0.marker-pillar', 'cc0.marker-plate']) {
      const bytes = reviewedBytes(key);
      const summary = validateGlbContainer(bytes);
      expect(summary.meshCount).toBeGreaterThan(0);
      // No textures at all, so nothing in them can reach for an image.
      expect(summary.imageCount).toBe(0);
      const row = published.get(key);
      if (row !== undefined) {
        expect(sha(bytes)).toBe(row.content_sha256);
        expect(bytes.byteLength).toBe(row.byte_size);
      }
    }
  });
});

describe('a container the glTF parser would complete over the network is refused first', () => {
  it('refuses an external buffer, which loadBuffers would fetch', () => {
    expect(() => validateGlbContainer(glb({
      ...MINIMAL, buffers: [{ uri: 'https://elsewhere.test/model.bin', byteLength: 12 }],
    }, new Uint8Array(12)))).toThrow(/references an external buffer/);
  });

  it('refuses an external image, which createImages would fetch cross-origin', () => {
    expect(() => validateGlbContainer(glb({
      ...MINIMAL, images: [{ uri: 'texture.png' }],
    }, new Uint8Array(12)))).toThrow(/references an external image/);
  });

  it('refuses a data-URI buffer as well, so the registry byte count still bounds the decode', () => {
    expect(() => validateGlbContainer(glb({
      ...MINIMAL, buffers: [{ uri: 'data:application/octet-stream;base64,AAAA', byteLength: 3 }],
    }, new Uint8Array(12)))).toThrow(/references an external buffer/);
  });

  it('refuses a compressed container, whose decoder would be fetched and run', () => {
    for (const extension of [
      'KHR_draco_mesh_compression', 'EXT_meshopt_compression', 'KHR_texture_basisu',
    ]) {
      expect(() => validateGlbContainer(glb({
        ...MINIMAL, extensionsUsed: [extension],
      }, new Uint8Array(12)))).toThrow(/decoder this build has not verified/);
    }
  });

  it('refuses any other required extension rather than letting the parser drop what it cannot read', () => {
    expect(() => validateGlbContainer(glb({
      ...MINIMAL, extensionsRequired: ['VENDOR_secret_sauce'],
    }, new Uint8Array(12)))).toThrow(/unreviewed glTF extensions: VENDOR_secret_sauce/);
  });

  it('tolerates an ignorable extension that is only listed as used', () => {
    expect(() => validateGlbContainer(glb({
      ...MINIMAL, extensionsUsed: ['KHR_materials_emissive_strength'],
    }, new Uint8Array(12)))).not.toThrow();
  });

  it('refuses an image that resolves to neither a buffer view nor a URI', () => {
    expect(() => validateGlbContainer(glb({
      ...MINIMAL, images: [{ mimeType: 'image/png' }],
    }, new Uint8Array(12)))).toThrow(/neither a buffer view nor bytes/);
  });

  it('refuses a header that lies about its own length, which the parser ignores', () => {
    const bytes = container();
    new DataView(bytes).setUint32(8, bytes.byteLength - 4, true);
    expect(() => validateGlbContainer(bytes)).toThrow(/header length disagrees/);
  });

  it('refuses the chunk length the parser reads past without returning', () => {
    const bytes = container();
    new DataView(bytes).setUint32(12, 0xfffffffc, true);
    expect(() => validateGlbContainer(bytes)).toThrow(/runs past the end/);
  });

  it('refuses the wrong magic, the wrong version and the wrong chunk order', () => {
    const wrongMagic = container();
    new DataView(wrongMagic).setUint32(0, 0x12345678, true);
    expect(() => validateGlbContainer(wrongMagic)).toThrow(/not a GLB container/);

    const wrongVersion = container();
    new DataView(wrongVersion).setUint32(4, 1, true);
    expect(() => validateGlbContainer(wrongVersion)).toThrow(/glTF binary version 2/);

    const wrongChunk = container();
    new DataView(wrongChunk).setUint32(16, 0x004e4942, true);
    expect(() => validateGlbContainer(wrongChunk)).toThrow(/first GLB chunk must be the JSON chunk/);
  });

  it('refuses a truncated container, a non-JSON chunk and a non-2.0 asset version', () => {
    expect(() => validateGlbContainer(container().slice(0, 16))).toThrow();
    expect(() => validateGlbContainer(glb({ ...MINIMAL, asset: { version: '1.0' } })))
      .toThrow(/glTF 2.0 asset version/);
    const notJson = new Uint8Array(container());
    notJson[20] = 0x00;
    expect(() => validateGlbContainer(notJson.buffer)).toThrow(/not a valid glTF document/);
  });

  it('refuses a buffer larger than the BIN chunk that must hold it', () => {
    expect(() => validateGlbContainer(glb({ ...MINIMAL, buffers: [{ byteLength: 4096 }] },
      new Uint8Array(12)))).toThrow(/a length its BIN chunk cannot hold/);
    expect(() => validateGlbContainer(glb(MINIMAL))).toThrow(/declares buffers and carries no BIN chunk/);
  });
});

describe('bytes reach the decoder only authenticated, hashed and counted', () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
  afterEach(() => {
    if (original !== undefined) Object.defineProperty(globalThis, 'crypto', original);
  });

  it('reads the reviewed bytes from the asset key and sends the bearer', async () => {
    const bytes = reviewedBytes('cc0.marker-cube');
    const fetchImpl = respond(bytes);
    const got = await fetchVerifiedObjectAsset(
      ISLAND, reference(bytes), new AbortController().signal, options(fetchImpl as never),
    );
    expect(new Uint8Array(got)).toEqual(new Uint8Array(bytes));
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://exulanica.test/world/assets/cc0.marker-cube/bytes');
    expect((init.headers as Record<string, string>)['authorization']).toBe('Bearer token');
  });

  it('escapes an asset key into the path rather than interpolating it raw', () => {
    expect(objectAssetBytesPath('cc0.marker-cube')).toBe('/world/assets/cc0.marker-cube/bytes');
    expect(objectAssetBytesPath('a/../b')).toBe('/world/assets/a%2F..%2Fb/bytes');
    expect(safeObjectAssetPath('/world/assets/a/bytes')).toBe(true);
    expect(safeObjectAssetPath('/world/assets/a#b')).toBe(false);
    expect(safeObjectAssetPath('/world-objects/assets/a/bytes')).toBe(false);
  });

  it('refuses a registry row with no digest rather than loading an unchecked container', async () => {
    const bytes = container();
    await expect(fetchVerifiedObjectAsset(
      ISLAND, reference(bytes, { contentSha256: '' }), new AbortController().signal,
      options(respond(bytes) as never),
    )).rejects.toThrow(/needs a SHA-256 in the registry/);
  });

  it('refuses a registry row with no byte count', async () => {
    const bytes = container();
    await expect(fetchVerifiedObjectAsset(
      ISLAND, reference(bytes, { byteSize: 0 }), new AbortController().signal,
      options(respond(bytes) as never),
    )).rejects.toThrow(/needs a byte count in the registry/);
  });

  it('refuses bytes whose hash is not the one the registry named', async () => {
    const bytes = container();
    await expect(fetchVerifiedObjectAsset(
      ISLAND, reference(bytes, { contentSha256: 'a'.repeat(64) }), new AbortController().signal,
      options(respond(bytes) as never),
    )).rejects.toThrow(/SHA-256 does not match/);
  });

  it('refuses a body whose length is not the one the registry named', async () => {
    const bytes = container();
    await expect(fetchVerifiedObjectAsset(
      ISLAND, reference(bytes, { byteSize: bytes.byteLength + 4 }), new AbortController().signal,
      options(respond(bytes) as never),
    )).rejects.toThrow(/bytes and .* arrived/);
  });

  it('refuses a media type it cannot open', async () => {
    const bytes = container();
    await expect(fetchVerifiedObjectAsset(
      ISLAND, reference(bytes, { mediaType: 'model/vnd.usdz+zip' }), new AbortController().signal,
      options(respond(bytes) as never),
    )).rejects.toThrow(/not a container this build can open/);
  });

  it('refuses everything when the page cannot compute a hash at all', async () => {
    const bytes = container();
    Object.defineProperty(globalThis, 'crypto', { value: undefined, configurable: true });
    const fetchImpl = respond(bytes);
    await expect(fetchVerifiedObjectAsset(
      ISLAND, reference(bytes), new AbortController().signal, options(fetchImpl as never),
    )).rejects.toThrow(/cannot verify content hashes/);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('refuses a container that fails validation even when its hash is right', async () => {
    const bytes = glb({ ...MINIMAL, images: [{ uri: 'texture.png' }] }, new Uint8Array(12));
    await expect(fetchVerifiedObjectAsset(
      ISLAND, reference(bytes), new AbortController().signal, options(respond(bytes) as never),
    )).rejects.toThrow(/references an external image/);
  });

  it('propagates an unauthenticated response as a failure', async () => {
    const bytes = container();
    await expect(fetchVerifiedObjectAsset(
      ISLAND, reference(bytes), new AbortController().signal,
      options(respond(bytes, 401) as never),
    )).rejects.toThrow(/HTTP 401/);
  });
});

describe('the container reaches the native handler as bytes, never as a URL', () => {
  it('supplies verified bytes in memory and keeps them owned until disposal', async () => {
    const bytes = reviewedBytes('cc0.marker-plate');
    const assets = {
      add: vi.fn(),
      remove: vi.fn(),
      load: vi.fn((asset: pc.Asset) => {
        expect(asset.type).toBe('container');
        const file = asset.file as unknown as { contents: ArrayBuffer; url: string };
        expect(file.contents).toBe(bytes);
        expect(file.url).toBe('verified-object/cc0.marker-plate.glb');
        asset.resource = { destroy: vi.fn() } as never;
        asset.fire('load', asset);
      }),
    };
    const asset = await createObjectContainerAsset(
      { assets } as unknown as pc.AppBase, 'cc0.marker-plate', bytes,
    );
    expect(assets.add).toHaveBeenCalledWith(asset);
  });

  it('turns the registry’s bare-string error into a message a status line can show', async () => {
    const bytes = container();
    const assets = {
      add: vi.fn(),
      remove: vi.fn(),
      load: vi.fn((asset: pc.Asset) => {
        asset.fire('error', "No resource handler for asset type: 'container'");
      }),
    };
    await expect(createObjectContainerAsset({ assets } as unknown as pc.AppBase, 'a', bytes))
      .rejects.toThrow(/No resource handler for asset type/);
    expect(assets.remove).toHaveBeenCalled();
  });
});

describe('placement is region-local fixed point', () => {
  const region = placement(atlasVec3(0, 0, 0), 0, 1);

  it('converts an atlas point into region millimetres, which atlas-core refuses to do', () => {
    const turned = placement(atlasVec3(10, 0, -4), Math.PI / 2, 2);
    // One metre along local +X: yaw 90 degrees sends +X to -Z, scale 2, offset.
    const local = regionPointFromAtlas(turned, [10, 0, -6]);
    expect(local[0]).toBeCloseTo(1000, 6);
    expect(local[1]).toBeCloseTo(0, 6);
    expect(local[2]).toBeCloseTo(0, 6);
  });

  it('produces whole millimetres, microradians and thousandths', () => {
    const pose = placementPoseBeforeVisitor(
      region,
      { position: atlasVec3(0, 1.6, 0), forward: atlasVec3(0, -0.2, -1) },
      3000,
    );
    for (const value of [pose.xMm, pose.yMm, pose.zMm, pose.yawMicroradians, pose.scaleMilli]) {
      expect(Number.isSafeInteger(value)).toBe(true);
    }
    expect(pose.zMm).toBeCloseTo(-3000, 0);
    expect(pose.yMm).toBe(0);
    expect(pose.scaleMilli).toBe(SCALE_MILLI_UNIT);
  });

  it('keeps yaw non-negative and inside one turn, as the transform bound requires', () => {
    expect(yawMicroradiansOf(0)).toBe(0);
    expect(yawMicroradiansOf(Number.NaN)).toBe(0);
    expect(yawMicroradiansOf(-Math.PI / 2))
      .toBe(Math.round(1.5 * Math.PI * MICRORADIANS_PER_RADIAN));
    expect(yawMicroradiansOf(3 * Math.PI)).toBe(Math.round(Math.PI * MICRORADIANS_PER_RADIAN));
    for (const radians of [-100, -1, 0, 1, 100]) {
      const yaw = yawMicroradiansOf(radians);
      expect(yaw).toBeGreaterThanOrEqual(0);
      expect(yaw).toBeLessThanOrEqual(6_283_185);
    }
  });

  it('stands at a caller-supplied ground when the frame did not measure one', () => {
    const pose = { position: atlasVec3(0, 1.6, 0), forward: atlasVec3(0, 0, -1) };
    expect(placementPoseBeforeVisitor(region, pose, 3000, -1600).yMm).toBe(-1600);
    expect(placementPoseAtAtlasPoint(region, [1, 9, 1], pose, -1600).yMm).toBe(-1600);
    expect(placementPoseBeforeVisitor(region, pose, 3000).yMm).toBe(0);
    expect(placementPoseAtAtlasPoint(region, [1, 9, 1], pose).yMm).toBe(0);
  });

  it('faces region -Z when the visitor is looking straight down', () => {
    const pose = placementPoseBeforeVisitor(
      region, { position: atlasVec3(0, 1.6, 0), forward: atlasVec3(0, -1, 0) }, 2000,
    );
    expect(pose.zMm).toBeCloseTo(-2000, 0);
    expect(Number.isSafeInteger(pose.yawMicroradians)).toBe(true);
  });

  it('stands an anchored placement at the anchor’s foot, facing the visitor', () => {
    const pose = placementPoseAtAtlasPoint(
      region, [4, 2.2, 0], { position: atlasVec3(0, 1.6, 0), forward: atlasVec3(1, 0, 0) },
    );
    expect(pose.xMm).toBe(4000);
    expect(pose.yMm).toBe(0);
    // Facing back towards the visitor, wrapped into the non-negative range.
    expect(pose.yawMicroradians).toBe(Math.round(1.5 * Math.PI * MICRORADIANS_PER_RADIAN));
  });

  it('nudges by whole millimetres and keeps every field an integer', () => {
    const start: RegionPose = {
      xMm: 1200, yMm: 0, zMm: -450, yawMicroradians: 785_398, scaleMilli: 1000,
    };
    const moved = nudgedPose(start, { xMm: -250, yMm: 250.4, yaw: Math.PI });
    expect(moved.xMm).toBe(950);
    expect(moved.yMm).toBe(250);
    expect(moved.zMm).toBe(-450);
    expect(Number.isSafeInteger(moved.yawMicroradians)).toBe(true);
    expect(moved.yawMicroradians).toBeGreaterThanOrEqual(0);
    expect(nudgedPose(start, {})).toEqual(start);
  });
});

// -- the runtime, with the engine stood in for --------------------------------------------------

interface FakeEntity {
  name: string;
  enabled: boolean;
  readonly position: number[];
  readonly scale: number[];
  readonly euler: number[];
  destroy: () => void;
  setLocalPosition: (x: number, y: number, z: number) => void;
  setLocalEulerAngles: (x: number, y: number, z: number) => void;
  setLocalScale: (x: number, y: number, z: number) => void;
  addChild: (child: unknown) => void;
}

function fakeEntity(): FakeEntity {
  const entity: FakeEntity = {
    name: '',
    enabled: true,
    position: [0, 0, 0],
    scale: [1, 1, 1],
    euler: [0, 0, 0],
    destroy: vi.fn(),
    setLocalPosition: (x, y, z) => { entity.position[0] = x; entity.position[1] = y; entity.position[2] = z; },
    setLocalEulerAngles: (x, y, z) => { entity.euler[0] = x; entity.euler[1] = y; entity.euler[2] = z; },
    setLocalScale: (x, y, z) => { entity.scale[0] = x; entity.scale[1] = y; entity.scale[2] = z; },
    addChild: vi.fn(),
  };
  return entity;
}

function harness() {
  const drawn = fakeEntity();
  const root = fakeEntity();
  const registry = { fire: vi.fn(), _loader: { clearCache: vi.fn() } };
  const assets = {
    add: vi.fn((asset: pc.Asset) => { (asset as { registry: unknown }).registry = registry; }),
    remove: vi.fn(),
    load: vi.fn((asset: pc.Asset) => {
      asset.resource = { instantiateRenderEntity: () => drawn, destroy: vi.fn() } as never;
      asset.fire('load', asset);
    }),
  };
  const roots = new Map<IslandId, pc.Entity>([[ISLAND, root as unknown as pc.Entity]]);
  const runtime = new SceneObjectRuntime({ assets } as unknown as pc.AppBase, roots);
  return { runtime, drawn, root, assets };
}

const POSE: RegionPose = Object.freeze({
  xMm: 1200, yMm: 0, zMm: -450, yawMicroradians: 0, scaleMilli: 1000,
});

const placed = (behaviour: PlacedAuthoredObject['behaviour']): PlacedAuthoredObject => ({
  objectId: 'object:lantern',
  islandId: ISLAND,
  asset: reference(reviewedBytes('cc0.marker-cube')),
  transform: POSE,
  behaviour,
});

const boundedPath = (over: Record<string, unknown> = {}) => ({
  behaviourKey: 'motion.bounded-path',
  behaviourVersion: 1,
  parameters: { axis: 'y', easing: 'smooth', travel_mm: 1000, period_milliseconds: 4000, ...over },
});

describe('the runtime places, moves and animates what a surface already committed', () => {
  it('places an object under its region, converting fixed point to metres', async () => {
    const { runtime, drawn, root } = harness();
    const outcome = await runtime.place(placed(boundedPath()), reviewedBytes('cc0.marker-cube'));
    expect(outcome).toEqual({ objectId: 'object:lantern', motion: 'attached', notices: [] });
    expect(root.addChild).toHaveBeenCalledWith(drawn);
    expect(drawn.name).toBe('authored-object:object:lantern');
    expect(drawn.position).toEqual([1.2, 0, -0.45]);
    expect(drawn.scale).toEqual([1, 1, 1]);
    expect(runtime.motionStateOf('object:lantern')).toBe('at-rest');
  });

  it('applies yaw and scale from the fixed-point fields', async () => {
    const { runtime, drawn } = harness();
    await runtime.place({
      ...placed(null),
      transform: { xMm: 0, yMm: 0, zMm: 0, yawMicroradians: 1_570_796, scaleMilli: 2000 },
    }, reviewedBytes('cc0.marker-cube'));
    expect(drawn.euler[1]).toBeCloseTo(90, 3);
    expect(drawn.scale).toEqual([2, 2, 2]);
  });

  it('still places the object when its behaviour is one this build cannot run, and says why', async () => {
    const { runtime, root } = harness();
    const outcome = await runtime.place(
      placed({ behaviourKey: 'motion.orbit', behaviourVersion: 1, parameters: {} }),
      reviewedBytes('cc0.marker-cube'),
    );
    expect(outcome.motion).toBe('none');
    expect(outcome.notices[0]).toContain('motion.orbit@1');
    expect(outcome.notices[0]).toContain('motion.bounded-path@1');
    expect(root.addChild).toHaveBeenCalled();
    expect(runtime.motionStateOf('object:lantern')).toBe('none');
  });

  it('refuses a behaviour at an unreviewed version the same way', async () => {
    const { runtime } = harness();
    const outcome = await runtime.place(
      placed({ ...boundedPath(), behaviourVersion: 2 }), reviewedBytes('cc0.marker-cube'),
    );
    expect(outcome.motion).toBe('none');
    expect(outcome.notices[0]).toContain('motion.bounded-path@2');
  });

  it('reports a clamped parameter rather than travelling further than declared', async () => {
    const { runtime } = harness();
    const outcome = await runtime.place(
      placed(boundedPath({ travel_mm: 99_999 })), reviewedBytes('cc0.marker-cube'),
    );
    expect(outcome.motion).toBe('attached');
    expect(outcome.notices[0]).toContain('travel_mm');
  });

  it('refuses a region this world does not draw instead of dropping the object silently', async () => {
    const { runtime } = harness();
    await expect(runtime.place(
      { ...placed(null), islandId: 'elsewhere' as IslandId }, reviewedBytes('cc0.marker-cube'),
    )).rejects.toThrow(/not drawn in this world/);
  });

  it('runs on the frame clock in seconds, holds, and resets exactly', async () => {
    const { runtime, drawn } = harness();
    await runtime.place(placed(boundedPath()), reviewedBytes('cc0.marker-cube'));
    const authored = [...drawn.position];

    expect(runtime.control('object:lantern', 'trigger')).toEqual({ ok: true });
    // Two seconds is half of a four-second period, which is the far end of the travel. The frame
    // clock is seconds and the behaviour's is milliseconds; getting that wrong runs it 1000x slow.
    runtime.update(2);
    expect(drawn.position[1]).toBeCloseTo(authored[1]! + 1, 6);

    runtime.control('object:lantern', 'stop');
    const held = [...drawn.position];
    runtime.update(1);
    expect(drawn.position).toEqual(held);

    runtime.control('object:lantern', 'reset');
    expect(drawn.position).toEqual(authored);
    expect(runtime.motionStateOf('object:lantern')).toBe('at-rest');
  });

  it('refuses a control on an object with no runnable motion, in words', async () => {
    const { runtime } = harness();
    await runtime.place(placed(null), reviewedBytes('cc0.marker-cube'));
    expect(runtime.control('object:lantern', 'trigger'))
      .toEqual({ ok: false, reason: expect.stringContaining('no motion this build can run') });
    expect(runtime.control('object:nine', 'trigger'))
      .toEqual({ ok: false, reason: expect.stringContaining('not in this world') });
  });

  it('moves an object to a new authored pose and returns its motion to rest', async () => {
    const { runtime, drawn } = harness();
    await runtime.place(placed(boundedPath()), reviewedBytes('cc0.marker-cube'));
    runtime.control('object:lantern', 'trigger');
    runtime.update(1);
    expect(runtime.setTransform('object:lantern', {
      xMm: 5000, yMm: 0, zMm: 5000, yawMicroradians: 0, scaleMilli: 1000,
    })).toBe(true);
    expect(drawn.position).toEqual([5, 0, 5]);
    expect(runtime.motionStateOf('object:lantern')).toBe('at-rest');
    expect(runtime.setTransform('object:nine', POSE)).toBe(false);
  });

  it('draws an object only where its region’s body is drawn', async () => {
    const { runtime, drawn } = harness();
    await runtime.place(placed(null), reviewedBytes('cc0.marker-cube'));
    runtime.setResidency(new Map([[ISLAND, 'full']]), false);
    expect(drawn.enabled).toBe(true);
    runtime.setResidency(new Map([[ISLAND, 'stub']]), false);
    expect(drawn.enabled).toBe(false);
    runtime.setResidency(new Map([[ISLAND, 'full']]), true);
    expect(drawn.enabled).toBe(false);
  });

  it('unloads the asset and destroys the entity on remove and on teardown', async () => {
    const { runtime, drawn, assets } = harness();
    await runtime.place(placed(null), reviewedBytes('cc0.marker-cube'));
    expect(runtime.remove('object:lantern')).toBe(true);
    expect(drawn.destroy).toHaveBeenCalled();
    expect(assets.remove).toHaveBeenCalled();
    expect(runtime.remove('object:lantern')).toBe(false);

    await runtime.place(placed(null), reviewedBytes('cc0.marker-cube'));
    runtime.destroy();
    expect(runtime.objectIds).toEqual([]);
    await expect(runtime.place(placed(null), reviewedBytes('cc0.marker-cube')))
      .rejects.toThrow(/destroyed/);
  });

  it('replaces an object placed twice under the same id rather than stacking two', async () => {
    const { runtime, root } = harness();
    await runtime.place(placed(null), reviewedBytes('cc0.marker-cube'));
    await runtime.place(placed(null), reviewedBytes('cc0.marker-cube'));
    expect(runtime.objectIds).toEqual(['object:lantern']);
    expect(root.addChild).toHaveBeenCalledTimes(2);
  });
});
