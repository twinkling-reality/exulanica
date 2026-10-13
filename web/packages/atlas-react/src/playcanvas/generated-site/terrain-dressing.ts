import * as pc from 'playcanvas';
import { canonicalJson, sha256Hex } from '../character/digest.js';
import { createObjectContainerAsset, validateGlbContainer } from '../scene-objects.js';
import { StaticMeshPicker } from '../mesh-picking.js';

export const DRESSING_LIMITS = Object.freeze({instances: 8, files: 8, bytes: 32 * 1024 * 1024,
  vertices: 1048576, triangles: 1048576, draws: 512, texels: 16777216});
export interface TerrainDressingInstance {
  readonly instance_id: string;
  readonly source: {readonly kind: 'reviewed_component'; readonly asset_key: string; readonly content_sha256: string};
  readonly position_mm: readonly [number, number, number];
  readonly quarter_turns: number;
  readonly scale_per_mille: number;
}
export interface TerrainDressing {
  readonly profile: 'exulanica.terrain-dressing/v1';
  readonly frame: 'region-local-east-up-south-mm';
  readonly collision: 'all-mesh-instance-aabb/v1';
  readonly instances: readonly TerrainDressingInstance[];
}
const require = (okay: boolean, detail: string): void => {if (!okay) throw new TypeError(`Terrain dressing: ${detail}`);};
const object = (value: unknown): Record<string, unknown> => {
  require(value !== null && typeof value === 'object' && !Array.isArray(value), 'expected an object'); return value as Record<string, unknown>;
};
const closed = (value: unknown, keys: string): Record<string, unknown> => {
  const row = object(value); require(Object.keys(row).sort().join(' ') === keys.split(' ').sort().join(' '), 'unexpected fields'); return row;
};
const integer = (value: unknown, low: number, high: number): number => {
  require(typeof value === 'number' && Number.isSafeInteger(value) && value >= low && value <= high, 'invalid bounded integer'); return value as number;
};
const identity = (value: unknown, maximum = 64): string => {
  require(typeof value === 'string' && value.length <= maximum && /^[a-z][a-z0-9.-]*$/.test(value), 'invalid identity'); return value as string;
};
const digest = (value: unknown): string => {
  require(typeof value === 'string' && /^[0-9a-f]{64}$/.test(value), 'invalid content digest'); return value as string;
};
export function readTerrainDressing(value: unknown, expectedSha256: string): TerrainDressing {
  const row = closed(value, 'profile frame collision instances');
  require(row['profile'] === 'exulanica.terrain-dressing/v1' && row['frame'] === 'region-local-east-up-south-mm'
    && row['collision'] === 'all-mesh-instance-aabb/v1', 'unsupported profile, frame or collision');
  require(Array.isArray(row['instances']) && row['instances'].length > 0 && row['instances'].length <= DRESSING_LIMITS.instances, 'instance limit');
  const keys = new Map<string, string>(); let previous = '';
  const instances = (row['instances'] as unknown[]).map(value => {
    const item = closed(value, 'instance_id source position_mm quarter_turns scale_per_mille');
    const id = identity(item['instance_id']); require(id > previous, 'instances must be unique and sorted'); previous = id;
    const source = closed(item['source'], 'kind asset_key content_sha256');
    require(source['kind'] === 'reviewed_component', 'only reviewed components can dress terrain');
    const key = identity(source['asset_key'], 200), sha = digest(source['content_sha256']);
    require(!keys.has(key) || keys.get(key) === sha, 'one asset key cannot name different contents'); keys.set(key, sha);
    require(Array.isArray(item['position_mm']) && item['position_mm'].length === 3, 'position needs three coordinates');
    const position = (item['position_mm'] as unknown[]).map(v => integer(v, -512000, 512000));
    return Object.freeze({instance_id: id, source: Object.freeze({kind: 'reviewed_component' as const, asset_key: key, content_sha256: sha}),
      position_mm: Object.freeze(position) as unknown as readonly [number, number, number],
      quarter_turns: integer(item['quarter_turns'], 0, 3), scale_per_mille: integer(item['scale_per_mille'], 100, 4000)});
  });
  const result: TerrainDressing = Object.freeze({profile: 'exulanica.terrain-dressing/v1', frame: 'region-local-east-up-south-mm',
    collision: 'all-mesh-instance-aabb/v1', instances: Object.freeze(instances)});
  require(keys.size <= DRESSING_LIMITS.files && sha256Hex(new TextEncoder().encode(canonicalJson(result))) === digest(expectedSha256), 'dressing digest or file budget differs');
  return result;
}
interface GlbFacts {
  readonly document: Record<string, any>;
  readonly activeNodes: readonly number[];
  readonly vertices: number;
  readonly triangles: number;
  readonly draws: number;
  readonly texels: number;
}
/** Bounded headers before decoding; full source geometry admission remains the server's strict static GLB contract. */
export function dressingGlbFacts(bytes: ArrayBuffer): GlbFacts {
  validateGlbContainer(bytes);
  const view = new DataView(bytes), jsonBytes = view.getUint32(12, true);
  const document = JSON.parse(new TextDecoder().decode(new Uint8Array(bytes, 20, jsonBytes))) as Record<string, any>;
  require(Array.isArray(document['scenes']) && document['scenes'].length === 1 && (document['scene'] ?? 0) === 0, 'requires the admitted single static scene');
  require(!(document['skins']?.length || document['animations']?.length), 'moving or deforming components are unavailable');
  const nodes = document['nodes'] ?? [], meshes = document['meshes'] ?? [], accessors = document['accessors'] ?? [];
  require(nodes.length <= 65536 && meshes.length <= 65536 && accessors.length <= 65536, 'document resource limit');
  const activeNodes: number[] = [], seen = new Set<number>(); let vertices = 0, triangles = 0, draws = 0;
  const todo = [...(document['scenes'][0].nodes ?? [])];
  while (todo.length) {
    const index = integer(todo.pop(), 0, nodes.length - 1); require(!seen.has(index), 'repeated or cyclic active node'); seen.add(index); activeNodes.push(index);
    const node = nodes[index]; require(node.skin === undefined && node.extensions === undefined && node.matrix === undefined, 'unsupported static node; dressing requires TRS');
    if (node.mesh !== undefined) {
      const mesh = meshes[integer(node.mesh, 0, meshes.length - 1)];
      for (const primitive of mesh.primitives ?? []) {
        require((primitive.mode ?? 4) === 4 && primitive.targets === undefined, 'requires static triangles');
        const position = accessors[integer(primitive.attributes?.POSITION, 0, accessors.length - 1)];
        const count = integer(position.count, 1, DRESSING_LIMITS.vertices);
        const indices = primitive.indices === undefined ? count : integer(accessors[integer(primitive.indices, 0, accessors.length - 1)].count, 1, DRESSING_LIMITS.triangles * 3);
        require(indices % 3 === 0, 'incomplete triangle'); vertices += count; triangles += indices / 3; draws++;
      }
    }
    todo.push(...(node.children ?? []));
    require(vertices <= DRESSING_LIMITS.vertices && triangles <= DRESSING_LIMITS.triangles && draws <= DRESSING_LIMITS.draws, 'rendered geometry budget');
  }
  const binaryAt = 20 + jsonBytes + 8, bufferViews = document['bufferViews'] ?? [];
  let texels = 0;
  for (const image of document['images'] ?? []) {
    const buffer = bufferViews[integer(image.bufferView, 0, bufferViews.length - 1)];
    const start = integer(buffer.byteOffset ?? 0, 0, bytes.byteLength), size = integer(buffer.byteLength, 1, bytes.byteLength);
    require(binaryAt + start + size <= bytes.byteLength, 'image runs outside bytes');
    const data = new Uint8Array(bytes, binaryAt + start, size);
    let width = 0, height = 0;
    if (image.mimeType === 'image/png') {
      require(size >= 24 && data[0] === 137 && data[1] === 80 && data[2] === 78 && data[3] === 71, 'invalid embedded PNG');
      const png = new DataView(bytes, binaryAt + start, size); width = png.getUint32(16); height = png.getUint32(20);
    } else {
      require(image.mimeType === 'image/jpeg' && data[0] === 255 && data[1] === 216, 'invalid embedded JPEG');
      let at = 2;
      while (at + 4 <= size) {
        require(data[at] === 255, 'invalid JPEG marker'); while (data[at] === 255) at++;
        const marker = data[at++]!; if (marker === 217 || marker === 218) break;
        if (marker === 1 || (marker >= 208 && marker <= 215)) continue;
        const length = data[at]! * 256 + data[at + 1]!; require(length >= 2 && at + length <= size, 'invalid JPEG segment');
        if ([192, 193, 194, 195, 197, 198, 199, 201, 202, 203, 205, 206, 207].includes(marker)) {
          require(length >= 8, 'invalid JPEG frame'); height = data[at + 3]! * 256 + data[at + 4]!; width = data[at + 5]! * 256 + data[at + 6]!; break;
        }
        at += length;
      }
    }
    require(width > 0 && height > 0 && Number.isSafeInteger(width * height), 'invalid decoded image size');
    texels += width * height; require(texels <= DRESSING_LIMITS.texels, 'decoded image budget');
  }
  require(draws > 0, 'empty active scene');
  return Object.freeze({document, activeNodes: Object.freeze(activeNodes.sort((a, b) => a - b)), vertices, triangles, draws, texels});
}
export interface PreparedDressing {
  readonly dressing: TerrainDressing;
  readonly transferredBytes: number;
  readonly texels: number;
  readonly draws: number;
  readonly triangles: number;
  readonly files: ReadonlyMap<string, {readonly bytes: ArrayBuffer; readonly facts: GlbFacts}>;
}
export async function prepareTerrainDressing(dressing: TerrainDressing,
  read: (source: TerrainDressingInstance['source'], signal: AbortSignal) => Promise<ArrayBuffer>, signal: AbortSignal): Promise<PreparedDressing> {
  const files = new Map<string, {bytes: ArrayBuffer; facts: GlbFacts}>(); const checkedKeys = new Set<string>(); let transferredBytes = 0, texels = 0, vertices = 0, triangles = 0, draws = 0;
  for (const instance of dressing.instances) {
    const {source} = instance; let file = files.get(source.content_sha256);
    let fetched: ArrayBuffer | undefined;
    if (!checkedKeys.has(source.asset_key)) {
      fetched = await read(source, signal); require(!signal.aborted, 'loading was cancelled');
      require(sha256Hex(new Uint8Array(fetched)) === source.content_sha256, 'component content digest differs');
      checkedKeys.add(source.asset_key);
    }
    if (file === undefined) {
      const bytes = fetched!;
      transferredBytes += bytes.byteLength; require(transferredBytes <= DRESSING_LIMITS.bytes, 'aggregate content budget');
      require(sha256Hex(new Uint8Array(bytes)) === source.content_sha256, 'component content digest differs');
      const facts = dressingGlbFacts(bytes); texels += facts.texels; require(texels <= DRESSING_LIMITS.texels, 'aggregate decoded image budget');
      file = {bytes, facts}; files.set(source.content_sha256, file);
    }
    vertices += file.facts.vertices; triangles += file.facts.triangles; draws += file.facts.draws;
    require(vertices <= DRESSING_LIMITS.vertices && triangles <= DRESSING_LIMITS.triangles && draws <= DRESSING_LIMITS.draws, 'aggregate instance geometry budget');
  }
  return Object.freeze({dressing, files, transferredBytes, texels, draws, triangles});
}
export interface DressingSurface {
  readonly instanceId: string;
  readonly assetKey: string;
  readonly contentSha256: string;
  readonly nodeIndex: number;
  readonly meshIndex: number;
  readonly primitiveIndex: number;
  readonly meshInstance: pc.MeshInstance;
}
export interface TerrainDressingAttachment {
  readonly ready: Promise<void>;
  readonly surfaces: readonly DressingSurface[];
  readonly decodedTextureBytes: number;
  pick(origin: readonly [number, number, number], direction: readonly [number, number, number]): {readonly surface: DressingSurface; readonly distance: number} | null;
  current(): boolean;
  update(): void;
  dispose(): void;
}
/** Decode the pinned full active scene; parent transforms and embedded materials remain source-owned. */
export function attachTerrainDressing(app: pc.AppBase, parent: pc.Entity, prepared: PreparedDressing,
  current: () => boolean, decode = createObjectContainerAsset): TerrainDressingAttachment {
  const assets = new Map<string, pc.Asset>(), roots: pc.Entity[] = [], surfaces: DressingSurface[] = [];
  const frames: {node: pc.GraphNode; parent: pc.GraphNode | null; matrix: readonly number[]}[] = [];
  const pin = (node: pc.GraphNode): void => {frames.push({node, parent: node.parent, matrix: [...node.getLocalTransform().data]});};
  const picker = new StaticMeshPicker(); let disposed = false, complete = false, decodedTextureBytes = 0;
  const valid = (): boolean => !disposed && current() && frames.every(({node, parent, matrix}) =>
    node.parent === parent && matrix.every((value, index) => node.getLocalTransform().data[index] === value));
  const dispose = (): void => {
    if (disposed) return; disposed = true; complete = false;
    for (const root of roots) root.destroy(); roots.length = 0; surfaces.length = 0;
    for (const asset of assets.values()) {asset.unload(); app.assets.remove(asset);} assets.clear();
  };
  const ready = (async () => {
    try {
      for (const [sha, file] of prepared.files) {
        require(valid() && sha256Hex(new Uint8Array(file.bytes)) === sha, 'stale or modified prepared component');
        const asset = await decode(app, `terrain:${sha}`, file.bytes);
        if (!valid()) {asset.unload(); app.assets.remove(asset); throw new Error('Terrain dressing was superseded during decoding');}
        assets.set(sha, asset);
        for (const texture of (asset.resource as pc.ContainerResource & {textures: pc.Asset[]}).textures ?? []) {
          const resource = texture.resource as pc.Texture; decodedTextureBytes += resource.width * resource.height * 4;
        }
      }
      for (const instance of prepared.dressing.instances) {
        require(valid(), 'source unavailable during attachment');
        const resource = assets.get(instance.source.content_sha256)!.resource as pc.ContainerResource & {data: {nodes: pc.GraphNode[]; scenes: pc.GraphNode[]}};
        const file = prepared.files.get(instance.source.content_sha256)!;
        require(resource.data.scenes.length === 1, 'decoded scene count differs');
        const entity = resource.instantiateRenderEntity({castShadows: true, receiveShadows: true});
        const outer = new pc.Entity(`dressing:${instance.instance_id}`); roots.push(outer); outer.enabled = false; outer.addChild(entity);
        const seen = new Set<number>();
        const visit = (template: pc.GraphNode, node: pc.Entity): void => {
          const index = resource.data.nodes.indexOf(template);
          if (index >= 0) seen.add(index);
          pin(node);
          const mesh = index < 0 ? undefined : file.facts.document['nodes'][index].mesh;
          if (node.render !== undefined && node.render !== null) {
            require(mesh !== undefined, 'decoded renderer lost node identity');
            for (const [primitiveIndex, meshInstance] of node.render.meshInstances.entries()) {
              picker.prepare(meshInstance); surfaces.push(Object.freeze({instanceId: instance.instance_id, assetKey: instance.source.asset_key,
                contentSha256: instance.source.content_sha256, nodeIndex: index, meshIndex: mesh, primitiveIndex, meshInstance}));
            }
          }
          require(template.children.length === node.children.length, 'decoded node hierarchy differs');
          for (let i = 0; i < template.children.length; i++) visit(template.children[i]!, node.children[i] as pc.Entity);
        };
        visit(resource.data.scenes[0]!, entity);
        require(file.facts.activeNodes.length === seen.size && file.facts.activeNodes.every(id => seen.has(id)), 'decoded active scene differs');
        outer.setLocalPosition(...instance.position_mm.map(v => v / 1000) as [number, number, number]);
        outer.setLocalEulerAngles(0, instance.quarter_turns * 90, 0);
        const scale = instance.scale_per_mille / 1000; outer.setLocalScale(scale, scale, scale); parent.addChild(outer); pin(outer);
      }
      require(valid() && surfaces.length === prepared.draws, 'decoded draw coverage differs');
      complete = true; for (const root of roots) root.enabled = true;
    } catch (error) {dispose(); throw error;}
  })();
  return {ready, get surfaces() {return surfaces;}, get decodedTextureBytes() {return decodedTextureBytes;},
    pick(origin, direction) {
      if (!complete || !valid()) return null;
      let best: {surface: DressingSurface; distance: number} | null = null;
      for (const surface of surfaces) {
        const distance = picker.pick(surface.meshInstance, origin, direction, best?.distance ?? Infinity);
        if (distance !== null && (best === null || distance < best.distance)) best = {surface, distance};
      }
      return best;
    }, current: valid, update() {if (!valid()) dispose();}, dispose};
}

/** Dressing bounds include only a translated source frame inside the declared numeric envelope. */
export function terrainDressingFrameAvailable(parent: pc.GraphNode): boolean {
  const m = parent.getWorldTransform().data;
  const identity = [1,0,0,0,0,1,0,0,0,0,1,0];
  return identity.every((value, index) => m[index] === value) && m[15] === 1
    && [m[12],m[13],m[14]].every(value => Number.isFinite(value) && Math.abs(value!) <= 1024);
}

/** Shared across lighting replacements, but each attachment receives a unique revocable generation. */
export function createDressingReadiness() {
  let generation = 0, ready = false, valid = () => true;
  return {read() {if (ready && !valid()) {generation++; ready = false;} return ready;}, begin(current: () => boolean = () => true) {
    const own = ++generation; ready = false; valid = current;
    return {current: () => own === generation, ready() {if (own === generation && current()) ready = true;},
      dispose() {if (own === generation) {generation++; ready = false;}}};
  }};
}
