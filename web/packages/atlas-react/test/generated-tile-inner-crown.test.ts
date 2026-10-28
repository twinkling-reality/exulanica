import { describe, expect, it } from 'vitest';
import { INNER_CROWN_INSET_M, innerShells, shadedLeafColour } from '../src/playcanvas/generated-tile/inner-crown.js';

/** An octahedron of radius `r` about `centre`, its normals pointing out: a closed crown in small. */
function octahedron(centre: readonly [number, number, number], r: number) {
  const axes = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]] as const;
  const positions = axes.flatMap(([x, y, z]) => [centre[0] + x * r, centre[1] + y * r, centre[2] + z * r]);
  const normals = axes.flatMap((axis) => [...axis]);
  // Each face joins one end of each axis, wound outward.
  const indices = [0, 2, 4, 2, 1, 4, 1, 3, 4, 3, 0, 4, 2, 0, 5, 1, 2, 5, 3, 1, 5, 0, 3, 5];
  return { positions, normals, indices };
}

const distance = (positions: readonly number[], vertex: number, centre: readonly number[]) =>
  Math.hypot(positions[vertex * 3]! - centre[0]!, positions[vertex * 3 + 1]! - centre[1]!, positions[vertex * 3 + 2]! - centre[2]!);

describe('a tree crown drawn over its own inner crown', () => {
  it('draws every closed shell again, moved in along its normals by the inset, facing out as its leaves do', () => {
    const centre = [3, 5, -2] as const;
    const crown = octahedron(centre, 2);
    const shells = innerShells(crown.positions, crown.normals, crown.indices, INNER_CROWN_INSET_M)!;
    expect(shells.indices.length).toBe(crown.indices.length);
    expect(shells.positions.length).toBe(crown.positions.length);
    for (let vertex = 0; vertex < shells.positions.length / 3; vertex += 1) {
      expect(distance(shells.positions, vertex, centre)).toBeCloseTo(2 - INNER_CROWN_INSET_M, 9);
      const out = [0, 1, 2].map((axis) => shells.positions[vertex * 3 + axis]! - centre[axis]!);
      const normal = shells.normals.slice(vertex * 3, vertex * 3 + 3);
      expect(Math.hypot(...normal)).toBeCloseTo(1, 9);
      expect(normal.reduce((sum, n, axis) => sum + n * out[axis]!, 0)).toBeGreaterThan(0);
    }
    // Each triangle keeps its winding: its face normal still points out of the crown.
    for (let corner = 0; corner < shells.indices.length; corner += 3) {
      const [a, b, c] = [0, 1, 2].map((k) => shells.positions.slice(shells.indices[corner + k]! * 3, shells.indices[corner + k]! * 3 + 3));
      const u = [0, 1, 2].map((axis) => b![axis]! - a![axis]!);
      const v = [0, 1, 2].map((axis) => c![axis]! - a![axis]!);
      const face = [u[1]! * v[2]! - u[2]! * v[1]!, u[2]! * v[0]! - u[0]! * v[2]!, u[0]! * v[1]! - u[1]! * v[0]!];
      const middle = [0, 1, 2].map((axis) => (a![axis]! + b![axis]! + c![axis]!) / 3 - centre[axis]!);
      expect(face.reduce((sum, n, axis) => sum + n * middle[axis]!, 0)).toBeGreaterThan(0);
    }
  });

  it('leaves an open card with its holes, and draws only the shells that close among several', () => {
    const card = { positions: [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0], normals: [0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1], indices: [0, 1, 2, 0, 2, 3] };
    expect(innerShells(card.positions, card.normals, card.indices)).toBeNull();
    const crown = octahedron([10, 0, 0], 1.5);
    const offset = card.positions.length / 3;
    const both = innerShells(
      [...card.positions, ...crown.positions],
      [...card.normals, ...crown.normals],
      [...card.indices, ...crown.indices.map((index) => index + offset)],
    )!;
    expect(both.indices.length).toBe(crown.indices.length);
    expect(both.positions.length).toBe(crown.positions.length);
  });

  it('moves a seam whose vertices are split as one point, so the inner crown opens no crack', () => {
    const crown = octahedron([0, 0, 0], 2);
    // The +x vertex split in two for its last two faces, the copy's normal leaning away as a seam's does.
    const positions = [...crown.positions, 2, 0, 0];
    const normals = [...crown.normals, 0.8, 0.6, 0];
    const indices = crown.indices.map((index, at) => (index === 0 && at >= 18 ? 6 : index));
    const shells = innerShells(positions, normals, indices)!;
    const points = new Set<string>();
    for (let vertex = 0; vertex < shells.positions.length / 3; vertex += 1) {
      if (shells.positions[vertex * 3]! > 1) points.add(shells.positions.slice(vertex * 3, vertex * 3 + 3).map((v) => v.toFixed(9)).join(','));
    }
    expect(points.size).toBe(1);
  });

  it('draws it in the mean of the leaves that stand, in linear light, at the shade asked', () => {
    // Two texels of leaf at the cutoff and above, one empty texel of a colour no leaf has.
    const texels = new Uint8Array([60, 100, 40, 200, 90, 120, 50, 128, 255, 0, 255, 0]);
    const set = { classParameters: { materialClass: 'cutout', alphaCutoff: 128, coveragePermille: 600, doubleSided: true }, maps: { base_color_coverage: texels } } as const;
    const lin = (byte: number) => { const c = byte / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
    const srgb = (l: number) => (l <= 0.0031308 ? l * 12.92 : 1.055 * l ** (1 / 2.4) - 0.055);
    const expected = [[60, 90], [100, 120], [40, 50]].map(([a, b]) => srgb(((lin(a!) + lin(b!)) / 2) * 0.5));
    const got = shadedLeafColour(set, 0.5)!;
    got.forEach((value, channel) => expect(value).toBeCloseTo(expected[channel]!, 9));
    expect(shadedLeafColour({ classParameters: { materialClass: 'opaque' }, maps: {} })).toBeNull();
  });
});
