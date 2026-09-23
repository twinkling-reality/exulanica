/**
 * One character host per engine application: verified containers, material packs, shared
 * materials and the body variants each worn outfit needs, all reference-counted and released
 * together.
 *
 * Bytes arrive only through a loader the application registers, so authority over what may be
 * fetched stays with the composition that knows the session. Until a loader is registered a
 * renderable shows its simple form and upgrades itself when one arrives.
 */
import * as pc from 'playcanvas';
import { createObjectContainerAsset, validateGlbContainer } from '../scene-objects.js';
import type { CatalogAssetRef, CatalogMaterial, CharacterCatalog } from './catalog.js';
import { hex, sha256Hex } from './digest.js';

export type CharacterAssetLoader = (asset: CatalogAssetRef, signal: AbortSignal) => Promise<ArrayBuffer>;

export interface LoadedContainer {
  readonly asset: pc.Asset;
  readonly resource: pc.ContainerResource & { readonly textures: pc.Asset[]; readonly renders: pc.Asset[]; readonly animations: pc.Asset[] };
  /** Parsed glTF document and binary chunk, retained only for base containers. */
  readonly document: GltfDocument | null;
  readonly binary: Uint8Array | null;
  readonly byteSize: number;
}

/** A material pack's textures, indexed as its glTF `textures` list is. */
export interface LoadedPack {
  readonly textures: readonly pc.Texture[];
  readonly byteSize: number;
}

export interface GltfDocument {
  readonly accessors: readonly { bufferView?: number; byteOffset?: number; componentType: number; count: number; type: string }[];
  readonly bufferViews: readonly { byteOffset?: number; byteLength: number; byteStride?: number }[];
  readonly meshes: readonly { name?: string; primitives: readonly { attributes: Readonly<Record<string, number>>; indices?: number }[] }[];
  readonly skins?: readonly { joints: readonly number[] }[];
  readonly nodes: readonly { name?: string }[];
}

interface PackDocument {
  readonly bufferViews: readonly { byteOffset?: number; byteLength: number }[];
  readonly images: readonly { bufferView: number; mimeType: string }[];
  readonly textures: readonly { source: number; sampler?: number }[];
  readonly samplers?: readonly { wrapS?: number; wrapT?: number }[];
}

export interface ContainerLease {
  readonly container: LoadedContainer;
  release(): void;
}

function cancelled(): DOMException {
  return new DOMException('Character request cancelled', 'AbortError');
}

/** Containers are megabytes: hash them natively off the frame where the platform allows. */
async function containerSha256(bytes: ArrayBuffer): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) return sha256Hex(new Uint8Array(bytes));
  return hex(new Uint8Array(await subtle.digest('SHA-256', bytes)));
}

export function parseGlb(bytes: ArrayBuffer): { document: GltfDocument; binary: Uint8Array } {
  validateGlbContainer(bytes);
  const view = new DataView(bytes);
  const jsonLength = view.getUint32(12, true);
  const document = JSON.parse(new TextDecoder().decode(new Uint8Array(bytes, 20, jsonLength))) as GltfDocument;
  const binaryStart = 20 + jsonLength;
  const binary = binaryStart < bytes.byteLength ? new Uint8Array(bytes, binaryStart + 8, view.getUint32(binaryStart, true)) : new Uint8Array(0);
  return { document, binary };
}

const COMPONENT_BYTES: Readonly<Record<number, number>> = { 5121: 1, 5123: 2, 5125: 4, 5126: 4 };
const TYPE_WIDTH: Readonly<Record<string, number>> = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 };
const WRAP: Readonly<Record<number, number>> = { 33071: pc.ADDRESS_CLAMP_TO_EDGE, 33648: pc.ADDRESS_MIRRORED_REPEAT, 10497: pc.ADDRESS_REPEAT };

/** Read a dense integer accessor (indices or the `_HIDE` bitmask). */
export function integerAccessor(document: GltfDocument, binary: Uint8Array, index: number): Uint32Array {
  const accessor = document.accessors[index];
  if (!accessor || accessor.bufferView === undefined) throw new TypeError('Dense accessor required');
  const size = COMPONENT_BYTES[accessor.componentType];
  const width = TYPE_WIDTH[accessor.type];
  if (!size || !width || accessor.componentType === 5126) throw new TypeError('Integer accessor required');
  const view = document.bufferViews[accessor.bufferView]!;
  const stride = view.byteStride ?? size * width;
  const start = binary.byteOffset + (view.byteOffset ?? 0) + (accessor.byteOffset ?? 0);
  const data = new DataView(binary.buffer, start, stride * (accessor.count - 1) + size * width);
  const out = new Uint32Array(accessor.count * width);
  for (let i = 0; i < accessor.count; i++) {
    for (let c = 0; c < width; c++) {
      const at = i * stride + c * size;
      out[i * width + c] = size === 1 ? data.getUint8(at) : size === 2 ? data.getUint16(at, true) : data.getUint32(at, true);
    }
  }
  return out;
}

class BodyVariant {
  references = 0;
  constructor(readonly mesh: pc.Mesh, private readonly owned: pc.IndexBuffer) {}
  destroy(): void {
    const mesh = this.mesh;
    // The vertex buffer, morph and skin belong to the source body mesh.
    mesh.vertexBuffer = null as unknown as pc.VertexBuffer;
    mesh.morph = null;
    mesh.skin = null;
    mesh.indexBuffer[0] = null as unknown as pc.IndexBuffer;
    mesh.decRefCount();
    this.owned.destroy();
    mesh.destroy();
  }
}

interface SharedEntry<T> {
  references: number;
  readonly controller: AbortController;
  promise: Promise<T>;
  value: T | null;
}

/**
 * Reference-counted resources that load once however many people ask. A resource whose every
 * requester has gone while it loaded is disposed the moment it arrives.
 */
class SharedResources<T> {
  private readonly entries = new Map<string, SharedEntry<T>>();
  constructor(private readonly dispose: (value: T) => void) {}

  get size(): number {
    return this.entries.size;
  }

  *loaded(): IterableIterator<T> {
    for (const entry of this.entries.values()) if (entry.value !== null) yield entry.value;
  }

  async lease(key: string, create: (signal: AbortSignal) => Promise<T>, signal: AbortSignal): Promise<{ value: T; release(): void }> {
    if (signal.aborted) throw cancelled();
    let entry = this.entries.get(key);
    if (!entry) {
      const created: SharedEntry<T> = { references: 0, controller: new AbortController(), value: null, promise: Promise.resolve(null as T) };
      created.promise = create(created.controller.signal).then((value) => {
        if (created.references === 0 || created.controller.signal.aborted) {
          this.dispose(value);
          throw cancelled();
        }
        created.value = value;
        return value;
      });
      created.promise.catch(() => {
        if (this.entries.get(key) === created && created.references === 0) this.entries.delete(key);
      });
      entry = created;
      this.entries.set(key, created);
    }
    const held = entry;
    held.references += 1;
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      held.references -= 1;
      if (held.references > 0) return;
      if (this.entries.get(key) === held) this.entries.delete(key);
      held.controller.abort();
      if (held.value !== null) this.dispose(held.value);
      held.value = null;
    };
    const onAbort = () => release();
    signal.addEventListener('abort', onAbort, { once: true });
    try {
      const value = await Promise.race([
        held.promise,
        new Promise<never>((_, reject) => signal.addEventListener('abort', () => reject(cancelled()), { once: true })),
      ]);
      if (signal.aborted) throw cancelled();
      return { value, release };
    } catch (error) {
      release();
      throw error;
    } finally {
      signal.removeEventListener('abort', onAbort);
    }
  }

  clear(): void {
    for (const entry of this.entries.values()) {
      entry.controller.abort();
      if (entry.value !== null) this.dispose(entry.value);
      entry.value = null;
    }
    this.entries.clear();
  }
}

interface BuiltMaterial {
  readonly material: pc.StandardMaterial;
  readonly pack: { release(): void };
}

const HOSTS = new WeakMap<pc.AppBase, CharacterHost>();

/**
 * The application that owns `device`, or null.
 *
 * Found by its canvas identity; a canvas without an id can only be matched to the current
 * application, and only when that application draws with this very device. Every application the
 * product mounts names its canvas, so the second rule serves pages with one application, such as a
 * test's, and never picks between two.
 */
export function applicationOf(device: pc.GraphicsDevice): pc.AppBase | null {
  const canvas = device.canvas as HTMLCanvasElement | OffscreenCanvas;
  const id = 'id' in canvas ? canvas.id : '';
  const app = id ? pc.AppBase.getApplication(id) : pc.AppBase.getApplication();
  return app && app.graphicsDevice === device ? app : null;
}

export class CharacterHost {
  private readonly containers = new SharedResources<LoadedContainer>((container) => this.disposeContainer(container));
  private readonly packs = new SharedResources<LoadedPack>((pack) => { for (const texture of pack.textures) texture.destroy(); });
  private readonly materials = new SharedResources<BuiltMaterial>((built) => { built.material.destroy(); built.pack.release(); });
  private readonly variants = new Map<string, BodyVariant>();
  private readonly loaderListeners = new Set<() => void>();
  private loader: CharacterAssetLoader | null = null;
  private destroyed = false;

  private constructor(readonly app: pc.AppBase, readonly catalog: CharacterCatalog) {}

  static forApp(app: pc.AppBase, catalog: CharacterCatalog): CharacterHost {
    let host = HOSTS.get(app);
    if (!host || host.destroyed) {
      host = new CharacterHost(app, catalog);
      HOSTS.set(app, host);
      app.once('destroy', () => host!.destroy());
    }
    return host;
  }

  /** The host of the application that owns `device`, found by its canvas identity. */
  static forDevice(device: pc.GraphicsDevice, catalog: CharacterCatalog): CharacterHost {
    const app = applicationOf(device);
    if (!app) throw new Error('Characters need an application whose canvas has a unique id');
    return CharacterHost.forApp(app, catalog);
  }

  /**
   * What a shared host already holds for this device, and nothing when no character has been drawn.
   *
   * Read by anyone accounting for character memory: containers, packs and materials are shared
   * between people, so they belong to the host and are counted once, never once per person.
   */
  static residentFor(device: pc.GraphicsDevice): { readonly geometryBytes: number; readonly textureBytes: number } {
    const app = applicationOf(device);
    const host = app ? HOSTS.get(app) : undefined;
    return host && !host.destroyed
      ? { geometryBytes: host.residentGeometryBytes, textureBytes: host.residentTextureBytes }
      : { geometryBytes: 0, textureBytes: 0 };
  }

  get hasLoader(): boolean {
    return this.loader !== null;
  }

  get residentContainers(): number {
    return this.containers.size + this.packs.size;
  }

  get residentEncodedBytes(): number {
    let bytes = 0;
    for (const container of this.containers.loaded()) bytes += container.byteSize;
    for (const pack of this.packs.loaded()) bytes += pack.byteSize;
    return bytes;
  }

  get residentGeometryBytes(): number {
    const meshes = new Set<pc.Mesh>();
    for (const container of this.containers.loaded()) {
      for (const render of container.resource.renders) {
        for (const mesh of (render.resource as { meshes: pc.Mesh[] }).meshes) meshes.add(mesh);
      }
    }
    let bytes = 0;
    for (const mesh of meshes) bytes += (mesh.vertexBuffer?.numBytes ?? 0) + mesh.indexBuffer.reduce((n, b) => n + (b?.numBytes ?? 0), 0);
    for (const variant of this.variants.values()) bytes += variant.mesh.indexBuffer[0]?.numBytes ?? 0;
    return bytes;
  }

  get residentTextureBytes(): number {
    let bytes = 0;
    for (const pack of this.packs.loaded()) for (const texture of pack.textures) bytes += texture.gpuSize;
    return bytes;
  }

  /** Register the byte loader; renderables waiting for one upgrade immediately. */
  setLoader(loader: CharacterAssetLoader): void {
    if (this.destroyed) return;
    this.loader = loader;
    for (const listener of [...this.loaderListeners]) listener();
  }

  onLoader(listener: () => void): () => void {
    this.loaderListeners.add(listener);
    return () => this.loaderListeners.delete(listener);
  }

  private async verifiedBytes(ref: CatalogAssetRef, signal: AbortSignal): Promise<ArrayBuffer> {
    const loader = this.loader;
    if (!loader) throw new Error('No character asset loader is registered');
    const bytes = await loader(ref, signal);
    if (bytes.byteLength !== ref.byteSize) throw new Error(`Character asset ${ref.assetKey} has the wrong length`);
    if ((await containerSha256(bytes)) !== ref.contentSha256) throw new Error(`Character asset ${ref.assetKey} failed its digest`);
    if (signal.aborted || this.destroyed) throw cancelled();
    return bytes;
  }

  /** A body or worn part: a skinned glTF container. Bases keep their document for body variants. */
  async acquire(ref: CatalogAssetRef, signal: AbortSignal, keepDocument = false): Promise<ContainerLease> {
    if (this.destroyed) throw cancelled();
    const { value, release } = await this.containers.lease(ref.contentSha256, async (own) => {
      const bytes = await this.verifiedBytes(ref, own);
      const parsed = keepDocument ? parseGlb(bytes) : null;
      const asset = await createObjectContainerAsset(this.app, `character-${ref.contentSha256}`, keepDocument ? bytes.slice(0) : bytes);
      return {
        asset,
        resource: asset.resource as LoadedContainer['resource'],
        document: parsed?.document ?? null,
        binary: parsed?.binary ?? null,
        byteSize: ref.byteSize,
      };
    }, signal);
    return { container: value, release };
  }

  /**
   * A material pack's images as textures. Colour images decode as sRGB, and normal and opacity
   * images stay linear, as the catalog material's roles say; nothing depends on how a general
   * glTF loader guesses a colour space.
   */
  private async acquirePack(material: CatalogMaterial, signal: AbortSignal): Promise<{ value: LoadedPack; release(): void }> {
    const ref = material.asset;
    return this.packs.lease(ref.contentSha256, async (own) => {
      const bytes = await this.verifiedBytes(ref, own);
      const { document, binary } = parseGlb(bytes) as unknown as { document: PackDocument; binary: Uint8Array };
      const device = this.app.graphicsDevice;
      const created: pc.Texture[] = [];
      try {
        const bitmaps = await Promise.all(document.textures.map((texture) => {
          const image = document.images[texture.source]!;
          const view = document.bufferViews[image.bufferView]!;
          const start = view.byteOffset ?? 0;
          const blob = new Blob([binary.slice(start, start + view.byteLength)], { type: image.mimeType });
          return createImageBitmap(blob, { premultiplyAlpha: 'none', colorSpaceConversion: 'none' });
        }));
        if (own.aborted || this.destroyed) throw cancelled();
        bitmaps.forEach((bitmap, index) => {
          const sampler = document.samplers?.[document.textures[index]!.sampler ?? -1];
          const texture = new pc.Texture(device, {
            name: `character:${ref.assetKey}:${index}`,
            width: bitmap.width,
            height: bitmap.height,
            // Colour decodes as sRGB; an opacity-only image needs one channel, a quarter of RGBA.
            format: index === material.roles.baseColor ? pc.PIXELFORMAT_SRGBA8
              : index === material.roles.opacity ? pc.PIXELFORMAT_R8 : pc.PIXELFORMAT_RGBA8,
            mipmaps: true,
            minFilter: pc.FILTER_LINEAR_MIPMAP_LINEAR,
            magFilter: pc.FILTER_LINEAR,
            addressU: WRAP[sampler?.wrapS ?? 10497] ?? pc.ADDRESS_REPEAT,
            addressV: WRAP[sampler?.wrapT ?? 10497] ?? pc.ADDRESS_REPEAT,
            anisotropy: Math.min(8, device.maxAnisotropy),
          });
          texture.setSource(bitmap as unknown as HTMLImageElement);
          created.push(texture);
        });
        return { textures: created, byteSize: ref.byteSize };
      } catch (error) {
        for (const texture of created) texture.destroy();
        throw error;
      }
    }, signal);
  }

  /** A shared material built from a reviewed pack, optionally tinted. */
  async material(material: CatalogMaterial, tint: string | null, signal: AbortSignal): Promise<{ material: pc.StandardMaterial; release(): void }> {
    if (this.destroyed) throw cancelled();
    const key = `${material.asset.contentSha256}:${tint ?? ''}`;
    const { value, release } = await this.materials.lease(key, async (own) => {
      const pack = await this.acquirePack(material, own);
      try {
        const textures = pack.value.textures;
        const built = new pc.StandardMaterial();
        built.name = `character:${material.materialId}`;
        built.diffuseMap = textures[material.roles.baseColor]!;
        if (tint) built.diffuse.fromString(tint);
        if (material.roles.normal !== undefined) built.normalMap = textures[material.roles.normal]!;
        if (material.alphaMode === 'MASK') {
          built.opacityMap = textures[material.roles.opacity ?? material.roles.baseColor]!;
          built.opacityMapChannel = material.roles.opacity === undefined ? 'a' : 'r';
          built.alphaTest = (material.alphaCutoffMilli ?? 500) / 1000;
          built.alphaToCoverage = this.app.graphicsDevice.samples > 1;
        }
        built.cull = material.doubleSided ? pc.CULLFACE_NONE : pc.CULLFACE_BACK;
        // A shell seen from inside (hair, brows, lashes) is lit from its own side, not the far one.
        built.twoSidedLighting = material.doubleSided;
        if (material.vertexOcclusion) {
          // Baked ambient occlusion rides in every channel of the vertex colour; it shades ambient
          // light and, by the engine's default, specular.
          built.aoVertexColor = true;
          built.aoVertexColorChannel = 'r';
        }
        built.useMetalness = true;
        built.metalness = 0;
        built.gloss = 1 - material.roughnessMilli / 1000;
        built.update();
        return { material: built, pack };
      } catch (error) {
        pack.release();
        throw error;
      }
    }, signal);
    return { material: value.material, release };
  }

  /**
   * The body mesh with every triangle a worn part covers removed. Shares the source body's
   * vertices, morph targets and skin; only the index list is new, and it is cached per mask.
   */
  bodyVariant(base: LoadedContainer, body: pc.Mesh, bodyMeshIndex: number, mask: number): { mesh: pc.Mesh; release(): void } {
    const key = `${base.asset.id}:${bodyMeshIndex}:${mask}`;
    let variant = this.variants.get(key);
    if (!variant) {
      if (!base.document || !base.binary) throw new Error('Base container was loaded without its document');
      const primitive = base.document.meshes[bodyMeshIndex]!.primitives[0]!;
      const hideIndex = primitive.attributes['_HIDE'];
      if (hideIndex === undefined || primitive.indices === undefined) throw new Error('Base body has no hide attribute');
      const hide = integerAccessor(base.document, base.binary, hideIndex);
      const indices = integerAccessor(base.document, base.binary, primitive.indices);
      if (body.vertexBuffer.numVertices !== hide.length) throw new Error('Body vertex order differs from its container');
      const kept: number[] = [];
      for (let t = 0; t < indices.length; t += 3) {
        const a = indices[t]!, b = indices[t + 1]!, c = indices[t + 2]!;
        if (((hide[a]! | hide[b]! | hide[c]!) & mask) === 0) kept.push(a, b, c);
      }
      const format = body.vertexBuffer.numVertices > 0xffff ? pc.INDEXFORMAT_UINT32 : pc.INDEXFORMAT_UINT16;
      const data = format === pc.INDEXFORMAT_UINT32 ? new Uint32Array(kept) : new Uint16Array(kept);
      const indexBuffer = new pc.IndexBuffer(this.app.graphicsDevice, format, kept.length, pc.BUFFER_STATIC, data.buffer);
      const mesh = new pc.Mesh(this.app.graphicsDevice);
      mesh.vertexBuffer = body.vertexBuffer;
      mesh.indexBuffer[0] = indexBuffer;
      mesh.primitive[0] = { type: pc.PRIMITIVE_TRIANGLES, base: 0, baseVertex: 0, count: kept.length, indexed: true };
      mesh.skin = body.skin;
      mesh.morph = body.morph;
      mesh.aabb = body.aabb;
      mesh.boneAabb = body.boneAabb;
      mesh.incRefCount();
      variant = new BodyVariant(mesh, indexBuffer);
      this.variants.set(key, variant);
    }
    const held = variant;
    held.references += 1;
    let released = false;
    return {
      mesh: held.mesh,
      release: () => {
        if (released) return;
        released = true;
        held.references -= 1;
        if (held.references > 0) return;
        if (this.variants.get(key) === held) this.variants.delete(key);
        held.destroy();
      },
    };
  }

  private disposeContainer(container: LoadedContainer): void {
    const asset = container.asset;
    for (const [key, variant] of this.variants) {
      if (key.startsWith(`${asset.id}:`)) {
        variant.destroy();
        this.variants.delete(key);
      }
    }
    asset.unload();
    this.app.assets.remove(asset);
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.loaderListeners.clear();
    this.materials.clear();
    this.packs.clear();
    for (const variant of this.variants.values()) variant.destroy();
    this.variants.clear();
    this.containers.clear();
    if (HOSTS.get(this.app) === this) HOSTS.delete(this.app);
  }
}
