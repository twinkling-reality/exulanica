/**
 * One character host per engine application: verified containers, shared materials and the
 * body variants each worn outfit needs, all reference-counted and released together.
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

interface ContainerEntry {
  references: number;
  readonly controller: AbortController;
  readonly promise: Promise<LoadedContainer>;
  loaded: LoadedContainer | null;
}

export interface LoadedContainer {
  readonly asset: pc.Asset;
  readonly resource: pc.ContainerResource & { readonly textures: pc.Asset[]; readonly renders: pc.Asset[]; readonly animations: pc.Asset[] };
  /** Parsed glTF document and binary chunk, retained only for base containers. */
  readonly document: GltfDocument | null;
  readonly binary: Uint8Array | null;
  readonly byteSize: number;
}

export interface GltfDocument {
  readonly accessors: readonly { bufferView?: number; byteOffset?: number; componentType: number; count: number; type: string }[];
  readonly bufferViews: readonly { byteOffset?: number; byteLength: number; byteStride?: number }[];
  readonly meshes: readonly { name?: string; primitives: readonly { attributes: Readonly<Record<string, number>>; indices?: number }[] }[];
  readonly skins?: readonly { joints: readonly number[] }[];
  readonly nodes: readonly { name?: string }[];
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

interface MaterialEntry {
  references: number;
  readonly promise: Promise<pc.StandardMaterial>;
  material: pc.StandardMaterial | null;
  lease: ContainerLease | null;
}

const HOSTS = new WeakMap<pc.AppBase, CharacterHost>();

export class CharacterHost {
  private readonly containers = new Map<string, ContainerEntry>();
  private readonly materials = new Map<string, MaterialEntry>();
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
    const canvas = device.canvas as HTMLCanvasElement | OffscreenCanvas;
    const id = 'id' in canvas ? canvas.id : '';
    const app = id ? pc.AppBase.getApplication(id) : undefined;
    if (!app || app.graphicsDevice !== device) {
      throw new Error('Characters need an application whose canvas has a unique id');
    }
    return CharacterHost.forApp(app, catalog);
  }

  get hasLoader(): boolean {
    return this.loader !== null;
  }

  get residentContainers(): number {
    return this.containers.size;
  }

  get residentEncodedBytes(): number {
    let bytes = 0;
    for (const entry of this.containers.values()) bytes += entry.loaded?.byteSize ?? 0;
    return bytes;
  }

  get residentGeometryBytes(): number {
    const meshes = new Set<pc.Mesh>();
    for (const entry of this.containers.values()) {
      for (const render of entry.loaded?.resource.renders ?? []) {
        for (const mesh of (render.resource as { meshes: pc.Mesh[] }).meshes) meshes.add(mesh);
      }
    }
    let bytes = 0;
    for (const mesh of meshes) bytes += (mesh.vertexBuffer?.numBytes ?? 0) + mesh.indexBuffer.reduce((n, b) => n + (b?.numBytes ?? 0), 0);
    for (const variant of this.variants.values()) bytes += variant.mesh.indexBuffer[0]?.numBytes ?? 0;
    return bytes;
  }

  get residentTextureBytes(): number {
    const textures = new Set<pc.Texture>();
    for (const entry of this.containers.values()) {
      for (const texture of entry.loaded?.resource.textures ?? []) textures.add(texture.resource as pc.Texture);
    }
    let bytes = 0;
    for (const texture of textures) bytes += texture.gpuSize;
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

  async acquire(ref: CatalogAssetRef, signal: AbortSignal, keepDocument = false): Promise<ContainerLease> {
    if (this.destroyed || signal.aborted) throw cancelled();
    const loader = this.loader;
    if (!loader) throw new Error('No character asset loader is registered');
    const key = ref.contentSha256;
    let entry = this.containers.get(key);
    if (!entry) {
      const pending: Omit<ContainerEntry, 'promise'> = { references: 0, controller: new AbortController(), loaded: null };
      const created: ContainerEntry = Object.assign(pending, { promise: this.load(pending, ref, loader, keepDocument) });
      entry = created;
      this.containers.set(key, entry);
      created.promise.catch(() => {
        if (this.containers.get(key) === created && created.references === 0) this.containers.delete(key);
      });
    }
    const held = entry;
    held.references += 1;
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      held.references -= 1;
      if (held.references > 0) return;
      if (this.containers.get(key) === held) this.containers.delete(key);
      held.controller.abort();
      if (held.loaded) this.dispose(held.loaded.asset);
      held.loaded = null;
    };
    const onAbort = () => release();
    signal.addEventListener('abort', onAbort, { once: true });
    try {
      const container = await Promise.race([
        held.promise,
        new Promise<never>((_, reject) => signal.addEventListener('abort', () => reject(cancelled()), { once: true })),
      ]);
      if (signal.aborted || this.destroyed) throw cancelled();
      return { container, release };
    } catch (error) {
      release();
      throw error;
    } finally {
      signal.removeEventListener('abort', onAbort);
    }
  }

  private async load(
    entry: { readonly references: number; readonly controller: AbortController; loaded: LoadedContainer | null },
    ref: CatalogAssetRef,
    loader: CharacterAssetLoader,
    keepDocument: boolean,
  ): Promise<LoadedContainer> {
    const { signal } = entry.controller;
    const bytes = await loader(ref, signal);
    if (bytes.byteLength !== ref.byteSize) throw new Error(`Character asset ${ref.assetKey} has the wrong length`);
    if ((await containerSha256(bytes)) !== ref.contentSha256) throw new Error(`Character asset ${ref.assetKey} failed its digest`);
    if (signal.aborted) throw cancelled();
    const parsed = keepDocument ? parseGlb(bytes) : null;
    const asset = await createObjectContainerAsset(this.app, `character-${ref.contentSha256}`, keepDocument ? bytes.slice(0) : bytes);
    if (entry.references === 0 || signal.aborted || this.destroyed) {
      this.dispose(asset);
      throw cancelled();
    }
    entry.loaded = {
      asset,
      resource: asset.resource as LoadedContainer['resource'],
      document: parsed?.document ?? null,
      binary: parsed?.binary ?? null,
      byteSize: ref.byteSize,
    };
    return entry.loaded;
  }

  /** A shared material built from a reviewed pack, optionally tinted. */
  async material(material: CatalogMaterial, tint: string | null, signal: AbortSignal): Promise<{ material: pc.StandardMaterial; release(): void }> {
    const key = `${material.asset.contentSha256}:${tint ?? ''}`;
    let entry = this.materials.get(key);
    if (!entry) {
      const pending: Omit<MaterialEntry, 'promise'> = { references: 0, material: null, lease: null };
      const created: MaterialEntry = Object.assign(pending, { promise: this.buildMaterial(pending, material, tint) });
      created.promise.catch(() => {
        created.lease?.release();
        if (this.materials.get(key) === created) this.materials.delete(key);
      });
      entry = created;
      this.materials.set(key, entry);
    }
    const held = entry;
    held.references += 1;
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      held.references -= 1;
      if (held.references > 0) return;
      if (this.materials.get(key) === held) this.materials.delete(key);
      held.material?.destroy();
      held.material = null;
      held.lease?.release();
      held.lease = null;
    };
    try {
      const built = await held.promise;
      if (signal.aborted || this.destroyed) throw cancelled();
      return { material: built, release };
    } catch (error) {
      release();
      throw error;
    }
  }

  private async buildMaterial(entry: Omit<MaterialEntry, 'promise'>, material: CatalogMaterial, tint: string | null): Promise<pc.StandardMaterial> {
    const lease = await this.acquire(material.asset, new AbortController().signal);
    if (entry.references === 0 || this.destroyed) {
      // Everyone who asked has gone while the pack loaded.
      lease.release();
      throw cancelled();
    }
    entry.lease = lease;
    const textures = lease.container.resource.textures.map((asset) => asset.resource as pc.Texture);
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
    built.useMetalness = true;
    built.metalness = 0;
    built.gloss = 1 - material.roughnessMilli / 1000;
    built.update();
    entry.material = built;
    return built;
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

  private dispose(asset: pc.Asset): void {
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
    for (const entry of this.materials.values()) entry.material?.destroy();
    this.materials.clear();
    for (const variant of this.variants.values()) variant.destroy();
    this.variants.clear();
    for (const entry of this.containers.values()) {
      entry.controller.abort();
      if (entry.loaded) {
        entry.loaded.asset.unload();
        this.app.assets.remove(entry.loaded.asset);
      }
    }
    this.containers.clear();
    if (HOSTS.get(this.app) === this) HOSTS.delete(this.app);
  }
}
