import * as pc from 'playcanvas';
import {
  VOLUME_NORMAL_ONE, readVolumeChunk, volumeDrawnCellMm,
  type HeightfieldDigest, type LandscapeDrawing, type PlacedVolume, type VolumeChunk, type VolumeChunkRef,
} from '@exulanica/atlas-core';

/**
 * The volumes a site on a landscape places round it (`docs/landscape-contract.md`), read and
 * drawn: sea stacks, arches, floating islands, each a placed volume whose surface the server
 * meshed in chunks.
 *
 * The landscape drawing names every chunk by the SHA-256 of its canonical JSON; the page fetches
 * the chunks of the level it draws each volume at ({@link siteVolumeChunks}) and
 * {@link readSiteVolumes} holds each to its digest and to its volume, so what is drawn is what
 * the server realized, or nothing is drawn. A chunk is in its volume's own frame (millimetres east,
 * north and up); its volume stands at `atMm` turned by `yawMdeg` counterclockwise seen from above.
 * The renderer's frame is east, up and south in metres, so a volume point (x, y, z) is the
 * renderer's (x, z, -y) / 1000, and the turn is about the renderer's up axis. The server turns
 * every triangle from solid toward air, which this frame keeps, so faces cull as drawn.
 *
 * Volumes stand off the site and are seen, not walked: nothing here is read by the site's walk,
 * its society or its seats. Each is worn in its own look ({@link DrawnSiteVolumes.wearEach}), so a
 * floating island's upward faces can be its grass while a sea stack is rock throughout.
 */

/** The rock a volume is drawn in where nothing dresses it: the engine's own, as the land's ground has. */
export const VOLUME_ROCK_RGB: readonly [number, number, number] = [0.47, 0.455, 0.431];

export interface SiteVolume {
  readonly volume: PlacedVolume;
  /** The cell its chunks are drawn at. */
  readonly cellMm: number;
  readonly chunks: readonly VolumeChunk[];
}

/** A site's landscape, read and held to the digests its drawing names. */
export interface SiteVolumes {
  readonly drawing: LandscapeDrawing;
  readonly volumes: readonly SiteVolume[];
  /** The bytes the landscape drawing and its chunks were served as. */
  readonly servedBytes: number;
}

/** Every chunk a page fetches for a landscape: each placed volume's chunks at the cell it is drawn at. */
export function siteVolumeChunks(drawing: LandscapeDrawing, finestMm?: number): readonly VolumeChunkRef[] {
  return drawing.volumes.flatMap((volume) => {
    const cell = volumeDrawnCellMm(volume, finestMm);
    return cell === null ? [] : volume.chunks.filter((chunk) => chunk.cellMm === cell);
  });
}

/**
 * Read a landscape's chunks (`bodies`, by the digest each was fetched by), each held to the digest
 * its drawing names, to its volume and its input, and to its place; refused as a whole otherwise.
 */
export function readSiteVolumes(
  drawing: LandscapeDrawing,
  bodies: ReadonlyMap<string, unknown>,
  digest: HeightfieldDigest,
  servedBytes: number,
  finestMm?: number,
): SiteVolumes {
  const volumes = drawing.volumes.map((volume): SiteVolume => {
    const cellMm = volumeDrawnCellMm(volume, finestMm);
    const named = cellMm === null ? [] : volume.chunks.filter((chunk) => chunk.cellMm === cellMm);
    const chunks = named.map((ref) => {
      const body = bodies.get(ref.sha256);
      if (body === undefined) throw new TypeError(`The landscape's chunk ${ref.sha256} of ${volume.id} was not fetched.`);
      const chunk = readVolumeChunk(body, digest, ref.sha256);
      const placed = chunk.chunk.every((index, axis) => index === ref.chunk[axis]) && chunk.cellMm === ref.cellMm;
      if (!placed || chunk.volumeSha256 !== volume.volumeSha256 || chunk.inputSha256 !== volume.inputSha256) {
        throw new TypeError(`The landscape's chunk ${ref.sha256} is not the chunk of ${volume.id} its drawing names.`);
      }
      return chunk;
    });
    return Object.freeze({ volume, cellMm: cellMm ?? 0, chunks: Object.freeze(chunks) });
  });
  return Object.freeze({ drawing, volumes: Object.freeze(volumes), servedBytes });
}

/** The renderer's position for a volume's origin, metres east, up and south. */
export function volumeOriginM(volume: PlacedVolume): readonly [number, number, number] {
  return [volume.atMm[0] / 1000, volume.atMm[2] / 1000, -volume.atMm[1] / 1000];
}

/** A chunk's vertices in the renderer's frame relative to its volume's origin: positions in metres, unit normals. */
export function volumeChunkVertices(chunk: VolumeChunk): { readonly positions: Float32Array; readonly normals: Float32Array } {
  const count = chunk.positionsMm.length / 3;
  const positions = new Float32Array(count * 3);
  const normals = new Float32Array(count * 3);
  for (let v = 0; v < count; v += 1) {
    const x = chunk.positionsMm[3 * v]!, y = chunk.positionsMm[3 * v + 1]!, z = chunk.positionsMm[3 * v + 2]!;
    positions[3 * v] = x / 1000;
    positions[3 * v + 1] = z / 1000;
    positions[3 * v + 2] = -y / 1000;
    normals[3 * v] = chunk.normals[3 * v]! / VOLUME_NORMAL_ONE;
    normals[3 * v + 1] = chunk.normals[3 * v + 2]! / VOLUME_NORMAL_ONE;
    normals[3 * v + 2] = -chunk.normals[3 * v + 1]! / VOLUME_NORMAL_ONE;
  }
  return { positions, normals };
}

export interface DrawnSiteVolumes {
  readonly root: pc.Entity;
  readonly instances: readonly pc.MeshInstance[];
  readonly triangles: number;
  readonly draws: number;
  /** Draw every volume in `material`, as the site's dressing makes it. */
  wear(material: pc.Material): void;
  /** Draw each volume in the material `lookOf` gives it, one it gives none keeping what it wears; how many it dressed. */
  wearEach(lookOf: (volume: PlacedVolume) => pc.Material | null): number;
  destroy(): void;
}

/**
 * Draw a landscape's volumes under a new root: one entity per placed volume at its origin and turn,
 * one mesh per chunk in `material`, each culled by its own bounds. Volumes cast shadows and
 * receive them.
 */
export function drawSiteVolumes(device: pc.GraphicsDevice, volumes: SiteVolumes, material: pc.Material): DrawnSiteVolumes {
  const root = new pc.Entity('site-volumes');
  const meshes: pc.Mesh[] = [];
  const instances: pc.MeshInstance[] = [];
  const worn: { readonly volume: PlacedVolume; readonly instances: readonly pc.MeshInstance[] }[] = [];
  let triangles = 0;
  for (const { volume, chunks } of volumes.volumes) {
    const placed = new pc.Entity(`site-volumes:${volume.id}`);
    const [x, y, z] = volumeOriginM(volume);
    placed.setLocalPosition(x, y, z);
    placed.setLocalEulerAngles(0, volume.yawMdeg / 1000, 0);
    const own: pc.MeshInstance[] = [];
    for (const chunk of chunks) {
      if (chunk.triangles.length === 0) continue;
      const { positions, normals } = volumeChunkVertices(chunk);
      const mesh = new pc.Mesh(device);
      mesh.setPositions(positions);
      mesh.setNormals(normals);
      mesh.setIndices(chunk.triangles);
      mesh.update(pc.PRIMITIVE_TRIANGLES);
      meshes.push(mesh);
      own.push(new pc.MeshInstance(mesh, material));
      triangles += chunk.triangles.length / 3;
    }
    if (own.length > 0) placed.addComponent('render', { meshInstances: own, castShadows: true, receiveShadows: true });
    instances.push(...own);
    worn.push({ volume, instances: own });
    root.addChild(placed);
  }
  let destroyed = false;
  return {
    root,
    instances,
    triangles,
    draws: instances.length,
    wear(material: pc.Material): void {
      for (const instance of instances) instance.material = material;
    },
    wearEach(lookOf: (volume: PlacedVolume) => pc.Material | null): number {
      let dressed = 0;
      for (const { volume, instances: own } of worn) {
        const material = lookOf(volume);
        if (material === null) continue;
        for (const instance of own) instance.material = material;
        dressed += 1;
      }
      return dressed;
    },
    destroy(): void {
      if (destroyed) return;
      destroyed = true;
      root.destroy();
      for (const mesh of meshes) mesh.destroy();
    },
  };
}
