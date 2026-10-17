import * as pc from 'playcanvas';
import {
  VOLUME_NORMAL_ONE, landscapeToSiteMm, readVolumeChunk, volumeDrawnCellMm,
  type HeightfieldDigest, type LandscapeDrawing, type PlacedVolume, type VolumeChunk, type VolumeChunkRef,
} from '@exulanica/atlas-core';
import type { SiteNearLand } from './site-land.js';

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
 *
 * A site on a placed volume's top (`exulanica.landscape-drawing/v2`) has a frame of its own in the
 * landscape: its south-west corner at the site frame's `atMm`, turned by its `yawMdeg`. The page's
 * frame stays the site's, so the landscape's root stands at the site frame's inverse
 * ({@link landscapePlacementM}) and every volume under it at its own place in the landscape's frame;
 * the landscape's own land below the island, its `ground`, is read as a site's land is
 * (`readLandscapeGround`) and drawn under the same root, so the island floats over that land or sea.
 */

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
  /**
   * The landscape's own land below a site on a volume's top, read and held to the digests its
   * `ground` names, in the landscape's frame; none for a landscape whose land is the site's.
   */
  readonly ground: SiteNearLand | null;
  /** The bytes the landscape drawing and its chunks were served as; the ground's are its own. */
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
 * A landscape that states the land below a site on a volume's top is read with that land
 * (`ground`, from `readLandscapeGround`), and one that states none with none.
 */
export function readSiteVolumes(
  drawing: LandscapeDrawing,
  bodies: ReadonlyMap<string, unknown>,
  digest: HeightfieldDigest,
  servedBytes: number,
  finestMm?: number,
  ground: SiteNearLand | null = null,
): SiteVolumes {
  if (ground === null ? drawing.ground !== null : ground.section !== drawing.ground) {
    throw new TypeError("The landscape's land below its site is read with it, and only the land it names.");
  }
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
  return Object.freeze({ drawing, volumes: Object.freeze(volumes), ground, servedBytes });
}

/**
 * Where a landscape's root stands in the page's frame, the site's: the renderer's position of the
 * landscape's origin, metres east, up and south, and its turn about up, degrees counterclockwise
 * seen from above. A landscape on a volume's top stands at its site frame's inverse, `R(-yaw)(p -
 * atMm)`, so the site's corner is the page's origin; one with no site frame is in the site's frame.
 */
export function landscapePlacementM(drawing: LandscapeDrawing): { readonly atM: readonly [number, number, number]; readonly yawDeg: number } {
  const frame = drawing.siteFrame;
  if (frame === null) return { atM: [0, 0, 0], yawDeg: 0 };
  const [x, y, z] = landscapeToSiteMm(frame, 0, 0, 0);
  return { atM: [x / 1000, z / 1000, -y / 1000], yawDeg: -frame.yawMdeg / 1000 };
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

/** How far from level a volume's face may lean and still be one of its upward faces: about 44 degrees, at {@link VOLUME_NORMAL_ONE}. */
export const VOLUME_UPWARD_NORMAL = Math.round(0.72 * VOLUME_NORMAL_ONE);

/**
 * A chunk's triangles whose three corners all pass `test` (a point of the volume's own frame,
 * millimetres east, north and up, and whether the surface faces up there), or, with `keep`, every
 * other triangle: the two halves of a chunk where something else draws the volume's top.
 */
export function trianglesWhere(
  chunk: VolumeChunk,
  test: (xMm: number, yMm: number, zMm: number, upward: boolean) => boolean,
  keep = false,
): Uint32Array {
  const p = chunk.positionsMm, n = chunk.normals, t = chunk.triangles;
  const held = (v: number): boolean => test(p[3 * v]!, p[3 * v + 1]!, p[3 * v + 2]!, n[3 * v + 2]! >= VOLUME_UPWARD_NORMAL);
  const picked: number[] = [];
  for (let i = 0; i < t.length; i += 3) {
    const a = t[i]!, b = t[i + 1]!, c = t[i + 2]!;
    if ((held(a) && held(b) && held(c)) !== keep) picked.push(a, b, c);
  }
  return Uint32Array.from(picked);
}

/**
 * Draw a landscape's volumes under a new root, standing where the landscape stands in the page's
 * frame ({@link landscapePlacementM}): one entity per placed volume at its origin and turn, one mesh
 * per chunk in `material`, each culled by its own bounds. Volumes cast shadows and receive them.
 * What else the landscape draws, the land below a site on a volume's top, goes under the same root.
 * `covered` names, for a volume by its id, the points of its own frame (and whether its surface faces
 * up there) where something else draws its top: a site's graded top drawn as land over its upward
 * faces, and the faces near that top drawn in the same ground. A triangle is left out only where
 * all three of its corners are covered, so the rock's own top never shows through the land drawn
 * over it, and the rock still meets that land at its edge. `under` gives, for a point of a volume's
 * own frame, the height it is drawn at (its own where nothing is drawn over it), so the rock kept
 * under that land stays under it.
 */
export function drawSiteVolumes(
  device: pc.GraphicsDevice,
  volumes: SiteVolumes,
  material: pc.Material,
  covered?: (volumeId: string, xMm: number, yMm: number, zMm: number, upward: boolean) => boolean,
  under?: (volumeId: string, xMm: number, yMm: number, zMm: number) => number,
): DrawnSiteVolumes {
  const root = new pc.Entity('site-volumes');
  if (volumes.drawing.siteFrame !== null) {
    const { atM, yawDeg } = landscapePlacementM(volumes.drawing);
    root.setLocalPosition(atM[0], atM[1], atM[2]);
    root.setLocalEulerAngles(0, yawDeg, 0);
  }
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
      const kept = covered === undefined ? chunk.triangles : trianglesWhere(chunk, (xMm, yMm, zMm, upward) => covered(volume.id, xMm, yMm, zMm, upward), true);
      if (kept.length === 0) continue;
      const { positions, normals } = volumeChunkVertices(chunk);
      if (under !== undefined) {
        const p = chunk.positionsMm;
        for (let v = 0; v < p.length / 3; v += 1) positions[3 * v + 1] = under(volume.id, p[3 * v]!, p[3 * v + 1]!, p[3 * v + 2]!) / 1000;
      }
      const mesh = new pc.Mesh(device);
      mesh.setPositions(positions);
      mesh.setNormals(normals);
      mesh.setIndices(kept);
      mesh.update(pc.PRIMITIVE_TRIANGLES);
      meshes.push(mesh);
      own.push(new pc.MeshInstance(mesh, material));
      triangles += kept.length / 3;
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
