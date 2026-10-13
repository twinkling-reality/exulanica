// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { pointContact, readHeightfieldGeometry, TriangleQuery } from '@exulanica/atlas-core';
import { createHeightfieldMesh, heightfieldMeshData, heightfieldMeshPart } from '../src/playcanvas/generated-site/heightfield-mesh.js';

const digest = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
function fixture(east = [-1997, -997, 253, 2253], south = [-1503, -253, 1747]) {
  return readHeightfieldGeometry({
    profile: 'exulanica.heightfield-geometry/v1', component_id: 'terrain:uneven', frame: 'region-local-east-up-south-mm',
    east_mm: east, south_mm: south, height_mm: south.flatMap((_, row) => east.map((_, column) => 1200 + row * 100 + column * 100)),
    diagonal: 'a-c-b,b-c-d', provenance: { kind: 'authored', source_sha256: 'a'.repeat(64), generator_id: 'fixture:uneven', generator_version: 1, input_sha256: 'b'.repeat(64) },
  }, digest);
}

describe('admitted heightfield renderer bridge', () => {
  it('converts original nonuniform coordinates once and preserves fixed upward topology', () => {
    const geometry = fixture(), before = geometry.document(), data = heightfieldMeshData(geometry);
    const width = geometry.data.east_mm.length;
    for (let row = 0; row < geometry.data.south_mm.length; row++) for (let column = 0; column < width; column++) {
      const vertex = row * width + column;
      const expected = [geometry.data.east_mm[column]!, geometry.data.height_mm[vertex]!, geometry.data.south_mm[row]!];
      expected.forEach((mm, axis) => {
        expect(data.positions[vertex * 3 + axis]).toBe(Math.fround(mm / 1000));
        expect(Math.abs(data.positions[vertex * 3 + axis]! * 1000 - mm)).toBeLessThan(0.02);
      });
      const normal = Array.from(data.normals.slice(vertex * 3, vertex * 3 + 3));
      expect(normal[1]).toBeGreaterThan(0);
      expect(Math.hypot(...normal)).toBeCloseTo(1, 6);
    }
    expect(Array.from(data.indices.slice(0, 12))).toEqual([0, 4, 1, 1, 4, 5, 1, 5, 2, 2, 5, 6]);
    for (let ordinal = 0; ordinal < data.indices.length / 3; ordinal++) {
      const [a, b, c] = Array.from(data.indices.slice(ordinal * 3, ordinal * 3 + 3));
      const ax = data.positions[a! * 3]!, az = data.positions[a! * 3 + 2]!;
      const bx = data.positions[b! * 3]!, bz = data.positions[b! * 3 + 2]!;
      const cx = data.positions[c! * 3]!, cz = data.positions[c! * 3 + 2]!;
      expect((bz - az) * (cx - ax) - (bx - ax) * (cz - az)).toBeGreaterThan(0);
    }
    data.positions[0] = 500;
    expect(geometry.document()).toEqual(before);
  });
  it('uses physical planar UV repeats independent of nonuniform cell spacing', () => {
    const geometry = fixture(), data = heightfieldMeshData(geometry, [500, 2000]);
    for (let vertex = 0; vertex < data.uvs.length / 2; vertex++) {
      expect(data.uvs[vertex * 2]).toBe(Math.fround(data.surfaceMm[vertex * 2]! / 500));
      expect(data.uvs[vertex * 2 + 1]).toBe(Math.fround(data.surfaceMm[vertex * 2 + 1]! / 2000));
    }
    const redressed = heightfieldMeshData(geometry, [2500, 1000]);
    expect(redressed.positions).toEqual(data.positions);
    expect(redressed.indices).toEqual(data.indices);
    expect(redressed.geometrySha256).toBe(data.geometrySha256);
    expect(redressed.uvs).not.toEqual(data.uvs);
    expect(() => heightfieldMeshData(geometry, [0, 1000])).toThrow();
    expect(() => heightfieldMeshData(geometry, [NaN, 1000])).toThrow();
  });
  it('maps original static-picker triangles to the same exact component and contact', () => {
    const geometry = fixture(), data = heightfieldMeshData(geometry), picker = new TriangleQuery(data);
    for (const position of [[-750, -750], [-1800, 1500], [1900, 300]] as const) {
      const expected = pointContact(geometry, position)!;
      const hit = picker.nearest([position[0] / 1000, 100, position[1] / 1000], [0, -1, 0]);
      expect(hit).not.toBeNull();
      const part = heightfieldMeshPart(geometry, hit!.triangleIndex);
      expect(part).toEqual({ geometrySha256: geometry.sha256, componentId: geometry.data.component_id, triangle: expected.triangle, provenance: geometry.data.provenance });
      const exactHeight = Number(expected.height_mm.numerator) / Number(expected.height_mm.denominator);
      expect(Math.abs((100 - hit!.distance) * 1000 - exactHeight)).toBeLessThan(0.1);
      expect(Object.isFrozen(part)).toBe(true);
      expect(Object.isFrozen(part.provenance)).toBe(true);
    }
    for (const invalid of [-1, 0.5, NaN, Infinity, data.indices.length / 3]) expect(() => heightfieldMeshPart(geometry, invalid)).toThrow();
  });
  it('keeps 32-bit indices at the full admitted grid and numeric selectors at its last cell', () => {
    const axis = Array.from({ length: 257 }, (_, index) => -256000 + index * 2000);
    const geometry = fixture(axis, axis), data = heightfieldMeshData(geometry);
    expect(data.positions.length / 3).toBe(66049);
    expect(data.indices).toBeInstanceOf(Uint32Array);
    expect(data.indices[data.indices.length - 1]).toBe(66048);
    expect(heightfieldMeshPart(geometry, data.indices.length / 3 - 1).triangle).toEqual([255, 255, 1]);
    expect(Math.abs(data.positions[data.positions.length - 1]! * 1000 - 256000)).toBeLessThan(0.02);
  });
  it('builds an ordinary PlayCanvas mesh with the same geometry, UVs and texture tangents', () => {
    const geometry = fixture(), data = heightfieldMeshData(geometry, [500, 2000]);
    const device = new pc.NullGraphicsDevice(document.createElement('canvas'));
    const mesh = createHeightfieldMesh(device, geometry, [500, 2000]);
    try {
      const positions: number[] = [], normals: number[] = [], indices: number[] = [], uvs: number[] = [], tangents: number[] = [];
      mesh.getPositions(positions); mesh.getNormals(normals); mesh.getIndices(indices); mesh.getUvs(0, uvs); mesh.getVertexStream(pc.SEMANTIC_TANGENT, tangents);
      expect(positions).toEqual(Array.from(data.positions));
      expect(normals).toEqual(Array.from(data.normals));
      expect(indices).toEqual(Array.from(data.indices));
      expect(uvs).toEqual(Array.from(data.uvs));
      expect(tangents.length).toBe(data.positions.length / 3 * 4);
      expect(tangents.every(Number.isFinite)).toBe(true);
    } finally { mesh.destroy(); device.destroy(); }
  });
});
