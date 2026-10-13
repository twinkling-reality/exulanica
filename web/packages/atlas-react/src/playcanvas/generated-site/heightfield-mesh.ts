import * as pc from 'playcanvas';
import type { HeightfieldGeometry, HeightfieldGeometryDocument, HeightfieldTriangleSelector } from '@exulanica/atlas-core';
import { buildSurfaceMesh } from '../generated-tile/surface-mesh.js';

export interface HeightfieldMeshPart {
  readonly geometrySha256: string;
  readonly componentId: string;
  /** Numeric source selector, never an entity inferred from a mesh face. */
  readonly triangle: HeightfieldTriangleSelector;
  readonly provenance: HeightfieldGeometryDocument['provenance'];
}

/**
 * Disposable renderer buffers for the exact retained realization. Mutation here cannot change
 * admitted geometry. Picking ordinals remain meaningful only while the original topology is kept.
 * Normals and UVs are presentation data, never contact or source-authorization evidence.
 */
export interface HeightfieldMeshData {
  readonly geometrySha256: string;
  readonly componentId: string;
  readonly provenance: HeightfieldGeometryDocument['provenance'];
  readonly positions: Float32Array;
  readonly normals: Float32Array;
  readonly indices: Uint32Array;
  /** Planar east/south millimetres, retained for the existing physical texture-set dresser. */
  readonly surfaceMm: Float64Array;
  readonly uvs: Float32Array;
}

const DEFAULT_REPEAT_MM = [1000, 1000] as const;
function repeatExtents(repeatMm: readonly [number, number]): readonly [number, number] {
  if (repeatMm.length !== 2 || repeatMm.some(value => !Number.isSafeInteger(value) || value < 1 || value > 512000)) {
    throw new RangeError('Heightfield texture repeats need two positive bounded millimetre extents.');
  }
  return repeatMm;
}

/** Region east/up/south mm become renderer east/up/south metres exactly once, then Float32. */
export function heightfieldMeshData(geometry: HeightfieldGeometry, repeatMm: readonly [number, number] = DEFAULT_REPEAT_MM): HeightfieldMeshData {
  const [repeatU, repeatV] = repeatExtents(repeatMm);
  const { east_mm: east, south_mm: south, height_mm: heights } = geometry.data;
  const width = east.length, vertices = heights.length;
  const positions = new Float32Array(vertices * 3), surfaceMm = new Float64Array(vertices * 2), uvs = new Float32Array(vertices * 2);
  for (let row = 0; row < south.length; row++) for (let column = 0; column < width; column++) {
    const vertex = row * width + column;
    positions[vertex * 3] = east[column]! / 1000;
    positions[vertex * 3 + 1] = heights[vertex]! / 1000;
    positions[vertex * 3 + 2] = south[row]! / 1000;
    surfaceMm[vertex * 2] = east[column]!;
    surfaceMm[vertex * 2 + 1] = south[row]!;
    uvs[vertex * 2] = east[column]! / repeatU;
    uvs[vertex * 2 + 1] = south[row]! / repeatV;
  }
  const indices = new Uint32Array((width - 1) * (south.length - 1) * 6);
  for (let row = 0; row < south.length - 1; row++) for (let column = 0; column < width - 1; column++) {
    const a = row * width + column, b = a + 1, c = a + width, d = c + 1;
    indices.set([a, c, b, b, c, d], (row * (width - 1) + column) * 6);
  }
  // Shared vertices keep a smooth display normal. Exact contact retains each triangle plane.
  const normals = Float32Array.from(pc.calculateNormals(Array.from(positions), Array.from(indices)));
  return Object.freeze({ geometrySha256: geometry.sha256, componentId: geometry.data.component_id, provenance: geometry.data.provenance, positions, normals, indices, surfaceMm, uvs });
}

/** Resolve an original triangle ordinal from the mesh or static picker to its source component. */
export function heightfieldMeshPart(geometry: HeightfieldGeometry, originalTriangleIndex: number): HeightfieldMeshPart {
  const columns = geometry.data.east_mm.length - 1, rows = geometry.data.south_mm.length - 1;
  if (!Number.isSafeInteger(originalTriangleIndex) || originalTriangleIndex < 0 || originalTriangleIndex >= rows * columns * 2) {
    throw new RangeError('Heightfield picking needs an original triangle ordinal in this realization.');
  }
  const cell = Math.floor(originalTriangleIndex / 2);
  const triangle = Object.freeze([Math.floor(cell / columns), cell % columns, originalTriangleIndex % 2]) as HeightfieldTriangleSelector;
  return Object.freeze({ geometrySha256: geometry.sha256, componentId: geometry.data.component_id, triangle, provenance: geometry.data.provenance });
}

/** Reuse ordinary mesh/tangent construction. Caller owns the mesh and its eventual destruction. */
export function createHeightfieldMesh(device: pc.GraphicsDevice, geometry: HeightfieldGeometry, repeatMm: readonly [number, number] = DEFAULT_REPEAT_MM): pc.Mesh {
  const [repeatU, repeatV] = repeatExtents(repeatMm);
  const data = heightfieldMeshData(geometry, repeatMm);
  return buildSurfaceMesh(device, data, (east, south) => [east / repeatU, south / repeatV]);
}
