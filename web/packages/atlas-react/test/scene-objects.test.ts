import { createHash } from 'node:crypto';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type * as pc from 'playcanvas';
import { identityDisplayFrame, sceneDisplayFrame, type IslandId } from '@exulanica/atlas-core';
import {
  AUTHORED_OBJECT_CONTAINER,
  SceneObjectRuntime,
  createObjectContainerAsset,
  displayPointFromAtlas,
  displayPoseOfObject,
  fetchVerifiedObjectAsset,
  invertSimilarity,
  objectTransformForDisplayPose,
  placementPoseAtAtlasPoint,
  placementPoseBeforeVisitor,
  safeObjectAssetPath,
  validateGlbContainer,
  type AuthoredObjectAssetReference,
  type PlacedAuthoredObject,
} from '../src/playcanvas/scene-objects.js';

/**
 * The authored-object boundary, from the outside.
 *
 * Every refusal here is a fetch `playcanvas@2.21.4` would otherwise make on its own account, out
 * of something written inside a container the caller did not author. The container is built in
 * this file rather than read from disk for the same reason the SOG fixture is not: what is under
 * test is that a real GLB, checked against a real digest, reaches a decoder that was given no
 * help, and a hand-built container is the only way to write the malformed cases.
 */

const ISLAND = 'island-1' as IslandId;

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

const sha = (bytes: ArrayBuffer): string =>
  createHash('sha256').update(new Uint8Array(bytes)).digest('hex');

function reference(bytes: ArrayBuffer, over: Partial<AuthoredObjectAssetReference> = {}) {
  return {
    assetId: 'lantern',
    container: AUTHORED_OBJECT_CONTAINER,
    path: '/world-objects/assets/lantern/bytes',
    contentSha256: sha(bytes),
    byteSize: bytes.byteLength,
    ...over,
  } as AuthoredObjectAssetReference;
}

const respond = (bytes: ArrayBuffer, status = 200) => vi.fn(async () =>
  new Response(status === 200 ? bytes : null, { status }));

const options = (fetchImpl: typeof globalThis.fetch) =>
  ({ baseUrl: 'https://exulanica.test', token: 'token', fetch: fetchImpl });

describe('a container the glTF parser would complete over the network is refused first', () => {
  it('accepts a self-contained container and reports what is in it', () => {
    const summary = validateGlbContainer(container());
    expect(summary).toEqual({
      jsonBytes: expect.any(Number), binaryBytes: 12, meshCount: 1, nodeCount: 1, imageCount: 0,
    });
  });

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

  it('refuses a data-URI buffer as well, so the descriptor byte count still bounds the decode', () => {
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

  it('accepts an image carried in the container itself', () => {
    expect(validateGlbContainer(glb({
      ...MINIMAL, images: [{ bufferView: 0, mimeType: 'image/png' }],
    }, new Uint8Array(12))).imageCount).toBe(1);
  });

  it('refuses a header that lies about its own length, which the parser ignores', () => {
    const bytes = container();
    new DataView(bytes).setUint32(8, bytes.byteLength - 4, true);
    expect(() => validateGlbContainer(bytes)).toThrow(/header length disagrees/);
  });

  it('refuses the chunk length the parser reads past without returning', () => {
    const bytes = container();
    // parseGlb reports this and then keeps going, so the malformed case must never reach it.
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

  it('sends the bearer to the declared path and returns verified bytes', async () => {
    const bytes = container();
    const fetchImpl = respond(bytes);
    const got = await fetchVerifiedObjectAsset(
      ISLAND, reference(bytes), new AbortController().signal, options(fetchImpl as never),
    );
    expect(new Uint8Array(got)).toEqual(new Uint8Array(bytes));
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://exulanica.test/world-objects/assets/lantern/bytes');
    expect((init.headers as Record<string, string>)['authorization']).toBe('Bearer token');
  });

  it('refuses a descriptor with no digest rather than loading an unchecked container', async () => {
    const bytes = container();
    await expect(fetchVerifiedObjectAsset(
      ISLAND, reference(bytes, { contentSha256: '' }), new AbortController().signal,
      options(respond(bytes) as never),
    )).rejects.toThrow(/needs a SHA-256 in the descriptor/);
  });

  it('refuses a descriptor with no byte count', async () => {
    const bytes = container();
    await expect(fetchVerifiedObjectAsset(
      ISLAND, reference(bytes, { byteSize: 0 }), new AbortController().signal,
      options(respond(bytes) as never),
    )).rejects.toThrow(/needs a byte count in the descriptor/);
  });

  it('refuses bytes whose hash is not the one the descriptor named', async () => {
    const bytes = container();
    await expect(fetchVerifiedObjectAsset(
      ISLAND, reference(bytes, { contentSha256: 'a'.repeat(64) }), new AbortController().signal,
      options(respond(bytes) as never),
    )).rejects.toThrow(/SHA-256 does not match/);
  });

  it('refuses a body whose length is not the one the descriptor named', async () => {
    const bytes = container();
    await expect(fetchVerifiedObjectAsset(
      ISLAND, reference(bytes, { byteSize: bytes.byteLength + 4 }), new AbortController().signal,
      options(respond(bytes) as never),
    )).rejects.toThrow(/is 208 bytes and 204 arrived/);
  });

  it('refuses a remote or query-bearing path, and a container it cannot open', async () => {
    const bytes = container();
    for (const path of [
      'https://elsewhere.test/model.glb',
      '/world-objects/assets/lantern/bytes?token=secret',
      '/geometry/artifacts/lantern/bytes',
    ]) {
      await expect(fetchVerifiedObjectAsset(
        ISLAND, reference(bytes, { path }), new AbortController().signal,
        options(respond(bytes) as never),
      )).rejects.toThrow(/local authenticated path|container this build can open/);
    }
    await expect(fetchVerifiedObjectAsset(
      ISLAND, reference(bytes, { container: 'sog/1' as never }), new AbortController().signal,
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
    // And it refused before it asked for the bytes.
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

  it('names the path shape it accepts', () => {
    expect(safeObjectAssetPath('/world-objects/assets/a/bytes')).toBe(true);
    expect(safeObjectAssetPath('/world-objects/a#b')).toBe(false);
    expect(safeObjectAssetPath('/geometry/a')).toBe(false);
  });
});

describe('the container reaches the native handler as bytes, never as a URL', () => {
  it('supplies verified bytes in memory and keeps them owned until disposal', async () => {
    const bytes = container();
    const assets = {
      add: vi.fn(),
      remove: vi.fn(),
      load: vi.fn((asset: pc.Asset) => {
        expect(asset.type).toBe('container');
        const file = asset.file as unknown as { contents: ArrayBuffer; url: string };
        expect(file.contents).toBe(bytes);
        expect(file.url).toBe('verified-object/lantern.glb');
        asset.resource = { destroy: vi.fn() } as never;
        asset.fire('load', asset);
      }),
    };
    const asset = await createObjectContainerAsset(
      { assets } as unknown as pc.AppBase, 'lantern', bytes,
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
    await expect(createObjectContainerAsset({ assets } as unknown as pc.AppBase, 'lantern', bytes))
      .rejects.toThrow(/No resource handler for asset type/);
    expect(assets.remove).toHaveBeenCalled();
  });
});

describe('placement is region-local, composed with the region’s display frame', () => {
  const frame = sceneDisplayFrame(
    [
      { position: [3, 0, 0], forward: [-1, 0, 0], up: [0, 0, 1] },
      { position: [-3, 0, 0], forward: [1, 0, 0], up: [0, 0, 1] },
      { position: [0, 0, 3], forward: [0, 0, -1], up: [0, 0, 1] },
    ],
    [[-4, -4, -4], [4, 4, 4]],
  );

  it('round-trips a display pose through the persisted region-local transform', () => {
    const pose = { x: 1.5, y: 0, z: -2.25, yaw: 0.7 };
    const sceneFromObject = objectTransformForDisplayPose(frame, pose);
    const read = displayPoseOfObject(frame, sceneFromObject);
    expect(read.x).toBeCloseTo(pose.x, 9);
    expect(read.y).toBeCloseTo(pose.y, 9);
    expect(read.z).toBeCloseTo(pose.z, 9);
    expect(read.yaw).toBeCloseTo(pose.yaw, 9);
  });

  it('is not the identity, so the frame is genuinely doing the work', () => {
    expect(frame.scale).not.toBe(1);
    const sceneFromObject = objectTransformForDisplayPose(frame, { x: 1, y: 0, z: 0, yaw: 0 });
    expect(sceneFromObject[3]).not.toBeCloseTo(1, 3);
  });

  it('inverts a similarity and refuses a matrix that is not one', () => {
    const identity = invertSimilarity(identityDisplayFrame().displayFromSceneRowMajor);
    expect([...identity].map((value) => value + 0))
      .toEqual([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
    expect(() => invertSimilarity(new Array(16).fill(0))).toThrow(/invertible similarity/);
  });

  it('undoes a region placement, which atlas-core deliberately refuses to do', () => {
    const placement = { position: { x: 10, y: 0, z: -4 } as never, yaw: Math.PI / 2, scale: 2 };
    // A point one unit along local +X, placed: yaw 90 degrees sends +X to -Z, scale 2, offset.
    const local = displayPointFromAtlas(placement, [10, 0, -6]);
    expect(local[0]).toBeCloseTo(1, 9);
    expect(local[1]).toBeCloseTo(0, 9);
    expect(local[2]).toBeCloseTo(0, 9);
  });

  it('puts a placement a step in front of the visitor, on the ground', () => {
    const placement = { position: { x: 0, y: 0, z: 0 } as never, yaw: 0, scale: 1 };
    const pose = placementPoseBeforeVisitor(
      placement,
      { position: { x: 0, y: 1.6, z: 0 } as never, forward: { x: 0, y: -0.2, z: -1 } as never },
      3,
    );
    expect(pose.y).toBe(0);
    expect(pose.z).toBeCloseTo(-3, 6);
    expect(pose.x).toBeCloseTo(0, 6);
  });

  it('stands at a caller-supplied ground when the frame did not measure one', () => {
    const placement = { position: { x: 0, y: 0, z: 0 } as never, yaw: 0, scale: 1 };
    const pose = { position: { x: 0, y: 1.6, z: 0 } as never, forward: { x: 0, y: 0, z: -1 } as never };
    // The identity frame's y = 0 is the scene's own origin, not a floor. A caller that knows this
    // supplies the height instead, and both placement kinds have to honour it.
    expect(placementPoseBeforeVisitor(placement, pose, 3, -4.25).y).toBe(-4.25);
    expect(placementPoseAtAtlasPoint(placement, [1, 9, 1], pose, -4.25).y).toBe(-4.25);
    // And the default stays the measured ground, so nothing that had a real frame changes.
    expect(placementPoseBeforeVisitor(placement, pose, 3).y).toBe(0);
    expect(placementPoseAtAtlasPoint(placement, [1, 9, 1], pose).y).toBe(0);
  });

  it('faces display -Z when the visitor is looking straight down', () => {
    const placement = { position: { x: 0, y: 0, z: 0 } as never, yaw: 0, scale: 1 };
    const pose = placementPoseBeforeVisitor(
      placement,
      { position: { x: 0, y: 1.6, z: 0 } as never, forward: { x: 0, y: -1, z: 0 } as never },
      2,
    );
    expect(pose.z).toBeCloseTo(-2, 6);
    expect(Number.isFinite(pose.yaw)).toBe(true);
  });

  it('stands an anchored placement at the anchor’s foot, facing the visitor', () => {
    const placement = { position: { x: 0, y: 0, z: 0 } as never, yaw: 0, scale: 1 };
    const pose = placementPoseAtAtlasPoint(
      placement,
      [4, 2.2, 0],
      { position: { x: 0, y: 1.6, z: 0 } as never, forward: { x: 1, y: 0, z: 0 } as never },
    );
    expect(pose.x).toBeCloseTo(4, 9);
    expect(pose.y).toBe(0);
    expect(pose.yaw).toBeCloseTo(-Math.PI / 2, 6);
  });
});

// -- the runtime, with the engine stood in for --------------------------------------------------

interface FakeEntity {
  name: string;
  enabled: boolean;
  readonly position: number[];
  readonly scale: number[];
  destroy: () => void;
  setLocalPosition: (x: number, y: number, z: number) => void;
  setLocalRotation: (q: unknown) => void;
  setLocalScale: (x: number, y: number, z: number) => void;
  addChild: (child: unknown) => void;
}

function fakeEntity(): FakeEntity {
  const entity: FakeEntity = {
    name: '',
    enabled: true,
    position: [0, 0, 0],
    scale: [1, 1, 1],
    destroy: vi.fn(),
    setLocalPosition: (x, y, z) => { entity.position[0] = x; entity.position[1] = y; entity.position[2] = z; },
    setLocalRotation: () => undefined,
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

const placed = (behaviour: PlacedAuthoredObject['behaviour']): PlacedAuthoredObject => ({
  objectId: 'object-1',
  islandId: ISLAND,
  sceneId: 'scene-1',
  asset: reference(container()),
  sceneFromObjectRowMajor: [1, 0, 0, 2, 0, 1, 0, 0.25, 0, 0, 1, -3, 0, 0, 0, 1],
  behaviour,
});

describe('the runtime places, moves and animates what a surface already committed', () => {
  const frame = identityDisplayFrame();

  it('places an object under its region and attaches a supported behaviour', async () => {
    const { runtime, drawn, root } = harness();
    const outcome = await runtime.place(
      placed({ behaviourId: 'motion.bounded', parameters: { axis: 'y', amplitude: 1, period: 4 } }),
      container(), frame,
    );
    expect(outcome).toEqual({ objectId: 'object-1', motion: 'attached', notices: [] });
    expect(root.addChild).toHaveBeenCalledWith(drawn);
    expect(drawn.name).toBe('authored-object:object-1');
    expect(drawn.position).toEqual([2, 0.25, -3]);
    expect(runtime.motionStateOf('object-1')).toBe('at-rest');
  });

  it('still places the object when its behaviour id is not supported, and says why', async () => {
    const { runtime, root } = harness();
    const outcome = await runtime.place(
      placed({ behaviourId: 'motion.orbit', parameters: {} }), container(), frame,
    );
    expect(outcome.motion).toBe('none');
    expect(outcome.notices).toHaveLength(1);
    expect(outcome.notices[0]).toContain('motion.orbit');
    expect(outcome.notices[0]).toContain('motion.bounded');
    // The refusal is about the motion. The object itself is real and is drawn.
    expect(root.addChild).toHaveBeenCalled();
    expect(runtime.motionStateOf('object-1')).toBe('none');
  });

  it('reports a clamped parameter rather than moving further than declared', async () => {
    const { runtime } = harness();
    const outcome = await runtime.place(
      placed({ behaviourId: 'motion.bounded', parameters: { axis: 'y', amplitude: 99, period: 4 } }),
      container(), frame,
    );
    expect(outcome.motion).toBe('attached');
    expect(outcome.notices[0]).toContain('amplitude');
  });

  it('refuses a region this world does not draw instead of dropping the object silently', async () => {
    const { runtime } = harness();
    await expect(runtime.place(
      { ...placed(null), islandId: 'elsewhere' as IslandId }, container(), frame,
    )).rejects.toThrow(/not drawn in this world/);
  });

  it('runs, holds and resets, returning the authored transform exactly', async () => {
    const { runtime, drawn } = harness();
    await runtime.place(
      placed({ behaviourId: 'motion.bounded', parameters: { axis: 'y', amplitude: 1, period: 4 } }),
      container(), frame,
    );
    const authored = [...drawn.position];

    expect(runtime.control('object-1', 'trigger')).toEqual({ ok: true });
    runtime.update(1);
    expect(drawn.position[1]).toBeCloseTo(authored[1]! + 1, 9);

    runtime.control('object-1', 'stop');
    const held = [...drawn.position];
    runtime.update(1);
    expect(drawn.position).toEqual(held);

    runtime.control('object-1', 'reset');
    expect(drawn.position).toEqual(authored);
    expect(runtime.motionStateOf('object-1')).toBe('at-rest');
  });

  it('refuses a control on an object with no motion, in words', async () => {
    const { runtime } = harness();
    await runtime.place(placed(null), container(), frame);
    expect(runtime.control('object-1', 'trigger'))
      .toEqual({ ok: false, reason: expect.stringContaining('no supported motion') });
    expect(runtime.control('object-9', 'trigger'))
      .toEqual({ ok: false, reason: expect.stringContaining('not in this world') });
  });

  it('moves an object to a new authored transform and returns its motion to rest', async () => {
    const { runtime, drawn } = harness();
    await runtime.place(
      placed({ behaviourId: 'motion.bounded', parameters: { axis: 'y', amplitude: 1, period: 4 } }),
      container(), frame,
    );
    runtime.control('object-1', 'trigger');
    runtime.update(1);
    expect(runtime.setTransform(
      'object-1', [1, 0, 0, 5, 0, 1, 0, 0, 0, 0, 1, 5, 0, 0, 0, 1], frame,
    )).toBe(true);
    expect(drawn.position).toEqual([5, 0, 5]);
    expect(runtime.motionStateOf('object-1')).toBe('at-rest');
    expect(runtime.setTransform('object-9', [], frame)).toBe(false);
  });

  it('draws an object only where its region’s body is drawn', async () => {
    const { runtime, drawn } = harness();
    await runtime.place(placed(null), container(), frame);
    runtime.setResidency(new Map([[ISLAND, 'full']]), false);
    expect(drawn.enabled).toBe(true);
    runtime.setResidency(new Map([[ISLAND, 'stub']]), false);
    expect(drawn.enabled).toBe(false);
    runtime.setResidency(new Map([[ISLAND, 'full']]), true);
    expect(drawn.enabled).toBe(false);
  });

  it('unloads the asset and destroys the entity on remove and on teardown', async () => {
    const { runtime, drawn, assets } = harness();
    await runtime.place(placed(null), container(), frame);
    expect(runtime.remove('object-1')).toBe(true);
    expect(drawn.destroy).toHaveBeenCalled();
    expect(assets.remove).toHaveBeenCalled();
    expect(runtime.remove('object-1')).toBe(false);

    await runtime.place(placed(null), container(), frame);
    runtime.destroy();
    expect(runtime.objectIds).toEqual([]);
    await expect(runtime.place(placed(null), container(), frame)).rejects.toThrow(/destroyed/);
  });

  it('replaces an object placed twice under the same id rather than stacking two', async () => {
    const { runtime, root } = harness();
    await runtime.place(placed(null), container(), frame);
    await runtime.place(placed(null), container(), frame);
    expect(runtime.objectIds).toEqual(['object-1']);
    expect(root.addChild).toHaveBeenCalledTimes(2);
  });
});
