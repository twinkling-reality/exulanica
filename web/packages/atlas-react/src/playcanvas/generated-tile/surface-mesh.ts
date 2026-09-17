import * as pc from 'playcanvas';
import { setTangents } from './texture-materials.js';

/**
 * One draw's worth of triangles, as the tile hands them over: positions and normals for the
 * renderer, and each vertex's surface coordinate in millimetres for the texture.
 *
 * The builder adds nothing. It does not weld, split, reorder, close or fill; it turns the given
 * triangles into a mesh with UVs from `uvOf` and tangents in the texture sets' convention. A surface
 * the tile does not state is a surface this function never sees.
 */
export interface SurfaceBatch {
  /** Metres, x y z per vertex, +Y up. */
  readonly positions: ArrayLike<number>;
  /** Unit normals, x y z per vertex. */
  readonly normals: ArrayLike<number>;
  /** Millimetres on the surface, s t per vertex, in the placement convention of the set. */
  readonly surfaceMm: ArrayLike<number>;
  readonly indices: ArrayLike<number>;
}

export function validateSurfaceBatch(batch: SurfaceBatch): number {
  const vertices = batch.positions.length / 3;
  if (!Number.isInteger(vertices) || vertices === 0) throw new Error('A surface batch needs whole vertices');
  if (batch.normals.length !== vertices * 3) throw new Error('A surface batch needs one normal per vertex');
  if (batch.surfaceMm.length !== vertices * 2) throw new Error('A surface batch needs one surface coordinate per vertex');
  if (batch.indices.length === 0 || batch.indices.length % 3 !== 0) throw new Error('A surface batch needs whole triangles');
  for (let index = 0; index < batch.indices.length; index += 1) {
    const vertex = batch.indices[index]!;
    if (!Number.isInteger(vertex) || vertex < 0 || vertex >= vertices) throw new Error('A surface batch index is out of range');
  }
  for (const values of [batch.positions, batch.normals, batch.surfaceMm]) {
    for (let index = 0; index < values.length; index += 1) {
      if (!Number.isFinite(values[index]!)) throw new Error('A surface batch holds a value that is not finite');
    }
  }
  return vertices;
}

export function buildSurfaceMesh(
  device: pc.GraphicsDevice,
  batch: SurfaceBatch,
  uvOf: (sMm: number, tMm: number) => readonly [number, number],
): pc.Mesh {
  const vertices = validateSurfaceBatch(batch);
  const positions = Array.from(batch.positions);
  const normals = Array.from(batch.normals);
  const indices = Array.from(batch.indices);
  const uvs = new Array<number>(vertices * 2);
  for (let vertex = 0; vertex < vertices; vertex += 1) {
    const [u, v] = uvOf(batch.surfaceMm[vertex * 2]!, batch.surfaceMm[vertex * 2 + 1]!);
    uvs[vertex * 2] = u;
    uvs[vertex * 2 + 1] = v;
  }
  const mesh = new pc.Mesh(device);
  mesh.setPositions(positions);
  mesh.setNormals(normals);
  mesh.setUvs(0, uvs);
  mesh.setVertexStream(pc.SEMANTIC_TANGENT, setTangents(positions, normals, uvs, indices), 4);
  mesh.setIndices(indices);
  mesh.update(pc.PRIMITIVE_TRIANGLES);
  return mesh;
}
