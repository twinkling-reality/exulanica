/**
 * Flat per-face normals for an authored object mesh whose own normals light nothing.
 *
 * A reviewed container may carry no normals at all: the marker assets migration 0042 pinned are
 * positions and indices only (`exulanica/world/assets.py`). `playcanvas@2.21.4` then averages face
 * normals over shared vertices. That is a lighting direction for a closed box, but the marker
 * plate shares its four vertices between an upward and a downward winding, so every average is a
 * zero vector, and normalising it yields NaN. A lit material has nothing to shade such a surface
 * with, and the plate draws as a dark hole or not at all.
 *
 * The bytes are pinned, so the renderer answers instead: a mesh with any vertex normal that names
 * no direction is rebuilt with each triangle on its own three vertices and that triangle's own
 * normal, which is what glTF 2.0 asks of a client given no normals. Its winding decides which way
 * each face points, so a plate wound both ways gets a face lit from above and one from below, and
 * back-face culling keeps whichever faces the camera. A mesh whose normals are all directions is
 * left exactly as it arrived.
 */

import * as pc from 'playcanvas';

/**
 * The shortest normal that still names a direction.
 *
 * Normals are unit vectors, and a float32 unit vector is within about 1e-7 of length 1. Half is a
 * margin, not a measurement: the defect it separates is a zero or NaN vector, whose length is 0
 * or not a number at all.
 */
export const MIN_NORMAL_LENGTH = 0.5;

/** True when every one of `vertexCount` normals is a finite vector at least `MIN_NORMAL_LENGTH` long. */
export function normalsUsable(normals: ArrayLike<number>, vertexCount: number): boolean {
  if (normals.length < vertexCount * 3) return false;
  for (let vertex = 0; vertex < vertexCount; vertex += 1) {
    const x = normals[vertex * 3]!;
    const y = normals[vertex * 3 + 1]!;
    const z = normals[vertex * 3 + 2]!;
    const length = Math.hypot(x, y, z);
    if (!Number.isFinite(length) || length < MIN_NORMAL_LENGTH) return false;
  }
  return true;
}

export interface FlatGeometry {
  readonly positions: Float32Array;
  readonly normals: Float32Array;
  /** Present exactly when the source had a first texture channel. */
  readonly uvs: Float32Array | null;
  readonly indices: Uint32Array;
}

/**
 * The same triangles, each on its own three vertices with its own face normal.
 *
 * A triangle with no area has no normal; it is kept with a zero normal, as it covers no pixel.
 */
export function flatNormalGeometry(
  positions: ArrayLike<number>,
  indices: ArrayLike<number>,
  uvs: ArrayLike<number> | null = null,
): FlatGeometry {
  if (indices.length % 3 !== 0) throw new TypeError('A triangle list holds a multiple of three indices');
  const count = indices.length;
  const outPositions = new Float32Array(count * 3);
  const outNormals = new Float32Array(count * 3);
  const outUvs = uvs === null ? null : new Float32Array(count * 2);
  for (let corner = 0; corner < count; corner += 3) {
    const a = indices[corner]!;
    const b = indices[corner + 1]!;
    const c = indices[corner + 2]!;
    const ax = positions[a * 3]!, ay = positions[a * 3 + 1]!, az = positions[a * 3 + 2]!;
    const e1x = positions[b * 3]! - ax, e1y = positions[b * 3 + 1]! - ay, e1z = positions[b * 3 + 2]! - az;
    const e2x = positions[c * 3]! - ax, e2y = positions[c * 3 + 1]! - ay, e2z = positions[c * 3 + 2]! - az;
    let nx = e1y * e2z - e1z * e2y;
    let ny = e1z * e2x - e1x * e2z;
    let nz = e1x * e2y - e1y * e2x;
    const length = Math.hypot(nx, ny, nz);
    if (length > 0) {
      nx /= length; ny /= length; nz /= length;
    }
    for (const [offset, source] of [[0, a], [1, b], [2, c]] as const) {
      const target = corner + offset;
      outPositions.set([positions[source * 3]!, positions[source * 3 + 1]!, positions[source * 3 + 2]!], target * 3);
      outNormals.set([nx, ny, nz], target * 3);
      if (outUvs !== null) outUvs.set([uvs![source * 2]!, uvs![source * 2 + 1]!], target * 2);
    }
  }
  const outIndices = new Uint32Array(count);
  for (let index = 0; index < count; index += 1) outIndices[index] = index;
  return Object.freeze({ positions: outPositions, normals: outNormals, uvs: outUvs, indices: outIndices });
}

/** What {@link giveFlatNormalsWhereUnusable} did to an entity's meshes. */
export interface NormalRepair {
  /** Meshes rebuilt with flat normals. */
  readonly rebuilt: number;
  /** Meshes whose normals light nothing but which this cannot rebuild: skinned, morphed, or not triangles. */
  readonly unrepairable: number;
}

/**
 * Rebuild every mesh under `entity` whose normals are unusable, in place on its mesh instances.
 *
 * A rebuilt mesh belongs to this entity alone, so the container's own mesh is never changed for
 * another placement of the same asset.
 */
export function giveFlatNormalsWhereUnusable(device: pc.GraphicsDevice, entity: pc.Entity): NormalRepair {
  const rebuiltBySource = new Map<pc.Mesh, pc.Mesh>();
  let unrepairable = 0;
  for (const render of entity.findComponents('render') as pc.RenderComponent[]) {
    for (const instance of render.meshInstances) {
      const source = instance.mesh;
      const known = rebuiltBySource.get(source);
      if (known !== undefined) {
        instance.mesh = known;
        continue;
      }
      const positions: number[] = [];
      const vertexCount = source.getPositions(positions);
      const normals: number[] = [];
      source.getNormals(normals);
      if (normalsUsable(normals, vertexCount)) continue;
      if (instance.skinInstance !== null || instance.morphInstance !== null
        || source.primitive[0]?.type !== pc.PRIMITIVE_TRIANGLES) {
        unrepairable += 1;
        continue;
      }
      const indices: number[] = [];
      if (source.getIndices(indices) === 0) {
        for (let vertex = 0; vertex < vertexCount; vertex += 1) indices.push(vertex);
      }
      const uvs: number[] = [];
      const hasUvs = source.getUvs(0, uvs) > 0;
      const flat = flatNormalGeometry(positions, indices, hasUvs ? uvs : null);
      const rebuilt = new pc.Mesh(device);
      rebuilt.setPositions(flat.positions);
      rebuilt.setNormals(flat.normals);
      if (flat.uvs !== null) rebuilt.setUvs(0, flat.uvs);
      rebuilt.setIndices(flat.indices);
      rebuilt.update(pc.PRIMITIVE_TRIANGLES);
      rebuiltBySource.set(source, rebuilt);
      instance.mesh = rebuilt;
    }
  }
  return Object.freeze({ rebuilt: rebuiltBySource.size, unrepairable });
}
