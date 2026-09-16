import type { DrawnMesh, ObstaclePrism } from '../src/index.js';

type V = readonly [number, number, number];

/** Two counter-clockwise triangles for a quad a, b, c, d. */
export function quad(out: number[], a: V, b: V, c: V, d: V): void {
  out.push(...a, ...b, ...c, ...a, ...c, ...d);
}

/** A closed axis-aligned box with outward, counter-clockwise faces. */
export function box(out: number[], min: V, max: V): void {
  const [l, b, n] = min;
  const [r, t, f] = max;
  quad(out, [l, b, f], [r, b, f], [r, t, f], [l, t, f]);
  quad(out, [r, b, n], [l, b, n], [l, t, n], [r, t, n]);
  quad(out, [r, b, f], [r, b, n], [r, t, n], [r, t, f]);
  quad(out, [l, b, n], [l, b, f], [l, t, f], [l, t, n]);
  quad(out, [l, t, f], [r, t, f], [r, t, n], [l, t, n]);
  quad(out, [l, b, n], [r, b, n], [r, b, f], [l, b, f]);
}

/**
 * Walls of a prism, wound as the product's `addBuilding` winds them: a, b along the ground and
 * c, d above, so the geometric normal is (-dz, 0, dx). For `rectangle` rings that is outward.
 */
export function walls(out: number[], ring: readonly (readonly [number, number])[], height: number): void {
  for (let k = 1; k < ring.length; k += 1) {
    const [ax, az] = ring[k - 1]!;
    const [bx, bz] = ring[k]!;
    quad(out, [ax, 0, az], [bx, 0, bz], [bx, height, bz], [ax, height, az]);
  }
}

export function mesh(id: string, triangles: number[], textured = false): DrawnMesh {
  return {
    id,
    triangles: Float64Array.from(triangles),
    cull: 'back',
    hasUv: textured,
    decodedTextureBytes: textured ? 4096 : 0,
  };
}

export function rectangle(west: number, north: number, east: number, south: number): [number, number][] {
  return [[west, north], [west, south], [east, south], [east, north], [west, north]];
}

/**
 * A 200 m street along x, 20 m wide, with a row of buildings on each side, and ground under all
 * of it. The street centreline is z = 0; buildings stand from z = -30 to -10 and 10 to 30.
 */
export function street(options: {
  readonly textured?: boolean;
  readonly floatingDecal?: boolean;
  readonly treeInsideBuilding?: boolean;
  readonly poleOnRoute?: boolean;
  readonly groundHole?: boolean;
} = {}): { meshes: DrawnMesh[]; prisms: ObstaclePrism[] } {
  const textured = options.textured ?? false;
  const ground: number[] = [];
  if (options.groundHole === true) {
    quad(ground, [-50, 0, -60], [-50, 0, 60], [40, 0, 60], [40, 0, -60]);
    quad(ground, [45, 0, -60], [45, 0, 60], [250, 0, 60], [250, 0, -60]);
  } else {
    quad(ground, [-50, 0, -60], [-50, 0, 60], [250, 0, 60], [250, 0, -60]);
  }
  const prisms: ObstaclePrism[] = [];
  const wallTriangles: number[] = [];
  for (let i = 0; i < 10; i += 1) {
    const west = i * 20;
    for (const [north, south] of [[-30, -10], [10, 30]] as const) {
      const ring = rectangle(west, north, west + 20, south);
      prisms.push({ id: `b${i}${north < 0 ? 'n' : 's'}`, ring, baseY: 0, topY: 18 });
      walls(wallTriangles, ring, 18);
    }
  }
  const meshes = [mesh('ground', ground, textured), mesh('walls', wallTriangles, textured)];
  if (options.floatingDecal === true) {
    const decal: number[] = [];
    // 0.2 m in front of the north row's street face (z = -10), 3 m up.
    quad(decal, [30, 3, -9.8], [32, 3, -9.8], [32, 4.5, -9.8], [30, 4.5, -9.8]);
    meshes.push(mesh('decal', decal, textured));
  }
  if (options.treeInsideBuilding === true) {
    const tree: number[] = [];
    box(tree, [49, 0, -21], [51, 3, -19]);
    meshes.push(mesh('tree', tree, textured));
  }
  if (options.poleOnRoute === true) {
    const pole: number[] = [];
    box(pole, [99.9, 0, -0.1], [100.1, 3, 0.1]);
    meshes.push(mesh('pole', pole, textured));
  }
  return { meshes, prisms };
}

/** The product support for the fixture: flat ground over the field, none outside it. */
export async function flatSupport(points: Float64Array): Promise<(number | null)[]> {
  const heights: (number | null)[] = [];
  for (let i = 0; i < points.length; i += 2) {
    const x = points[i]!;
    const z = points[i + 1]!;
    heights.push(x < -50 || x > 250 || z < -60 || z > 60 ? null : 0);
  }
  return heights;
}
