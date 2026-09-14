/** Shared abstract human skin. Disposable tessellation, never identity or world authority. */
export type V3 = readonly [number, number, number];
export interface SculptMesh {
  positions: Float32Array;
  normals: Float32Array;
  colors: Float32Array;
  indices: number[];
}
const clamp = (v: number) => Math.max(0, Math.min(1, v));
const smooth = (a: number, b: number, x: number) => {
  const t = clamp((x - a) / (b - a));
  return t * t * (3 - 2 * t);
};
const ellipsoid = (p: V3, c: V3, r: V3) =>
  (Math.hypot(
    (p[0] - c[0]) / r[0],
    (p[1] - c[1]) / r[1],
    (p[2] - c[2]) / r[2],
  ) -
    1) *
  Math.min(...r);
function limb(p: V3, a: V3, b: V3, r0: number, r1: number): number {
  const d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]],
    t = clamp(
      ((p[0] - a[0]) * d[0]! + (p[1] - a[1]) * d[1]! + (p[2] - a[2]) * d[2]!) /
        (d[0]! ** 2 + d[1]! ** 2 + d[2]! ** 2),
    );
  return (
    Math.hypot(
      p[0] - a[0] - d[0]! * t,
      p[1] - a[1] - d[1]! * t,
      p[2] - a[2] - d[2]! * t,
    ) -
    (r0 + (r1 - r0) * t)
  );
}
function blend(a: number, b: number, k = 0.035): number {
  const h = clamp(0.5 + (0.5 * (b - a)) / k);
  return b + (a - b) * h - k * h * (1 - h);
}
export function playerField(p: V3): number {
  let d = ellipsoid(p, [0, 0.88, 0.005], [0.158, 0.17, 0.115]);
  d = blend(d, ellipsoid(p, [0, 1.085, 0], [0.126, 0.215, 0.105]));
  d = blend(d, ellipsoid(p, [0, 1.3, 0], [0.197, 0.183, 0.125]), 0.055);
  d = blend(d, ellipsoid(p, [0, 1.465, 0.008], [0.065, 0.13, 0.067]), 0.045);
  d = blend(
    d,
    ellipsoid(
      p,
      [0, 1.675, 0.007],
      [0.108 * (0.87 + 0.13 * smooth(1.52, 1.7, p[1])), 0.157, 0.111],
    ),
    0.044,
  );
  for (const side of [-1, 1]) {
    const s = (x: number, y: number, z = 0): V3 => [side * x, y, z];
    d = blend(
      d,
      limb(p, s(0.045, 1.435), s(0.207, 1.375), 0.067, 0.075),
      0.055,
    );
    d = blend(d, limb(p, s(0.209, 1.367), s(0.274, 1.115), 0.063, 0.044), 0.04);
    d = blend(
      d,
      limb(p, s(0.274, 1.115), s(0.3, 0.902, -0.018), 0.044, 0.033),
      0.022,
    );
    d = blend(
      d,
      ellipsoid(p, s(0.302, 0.852, -0.022), [0.037, 0.063, 0.03]),
      0.027,
    );
    d = blend(
      d,
      limb(p, s(0.095, 0.86), s(0.108, 0.478, -0.065), 0.082, 0.049),
      0.037,
    );
    d = blend(
      d,
      limb(p, s(0.108, 0.478, -0.065), s(0.112, 0.105), 0.048, 0.032),
      0.023,
    );
    d = blend(
      d,
      ellipsoid(p, s(0.112, 0.307, -0.006), [0.051, 0.15, 0.052]),
      0.028,
    );
    d = blend(
      d,
      ellipsoid(p, s(0.112, 0.052, -0.05), [0.055, 0.052, 0.113]),
      0.02,
    );
  }
  return d;
}

/** Marching tetrahedra with shared edge vertices and gradient normals gives one smooth skin. */
const sculptCache = new Map<number, SculptMesh>();
export function buildPlayerSculpt(step = 0.025): SculptMesh {
  const existing = sculptCache.get(step);
  if (existing) return existing;
  const min: V3 = [-0.4, -0.028, -0.224],
    nx = Math.ceil(0.8 / step) + 1,
    ny = Math.ceil(1.9 / step) + 1,
    nz = Math.ceil(0.448 / step) + 1;
  const count = nx * ny * nz,
    values = new Float32Array(count);
  const at = (x: number, y: number, z: number) => x + nx * (y + ny * z);
  const pos = (id: number): V3 => [
    min[0] + (id % nx) * step,
    min[1] + (Math.floor(id / nx) % ny) * step,
    min[2] + Math.floor(id / (nx * ny)) * step,
  ];
  for (let i = 0; i < count; i++) values[i] = playerField(pos(i));
  const positions: number[] = [],
    normals: number[] = [],
    colors: number[] = [],
    indices: number[] = [],
    cache = new Map<string, number>();
  const vertex = (a: number, b: number) => {
    const key = a < b ? `${a}:${b}` : `${b}:${a}`;
    const held = cache.get(key);
    if (held !== undefined) return held;
    const pa = pos(a),
      pb = pos(b),
      t = values[a]! / (values[a]! - values[b]!);
    const p: V3 = [
      pa[0] + (pb[0] - pa[0]) * t,
      pa[1] + (pb[1] - pa[1]) * t,
      pa[2] + (pb[2] - pa[2]) * t,
    ];
    const e = 0.001,
      normal = [
        playerField([p[0] + e, p[1], p[2]]) -
          playerField([p[0] - e, p[1], p[2]]),
        playerField([p[0], p[1] + e, p[2]]) -
          playerField([p[0], p[1] - e, p[2]]),
        playerField([p[0], p[1], p[2] + e]) -
          playerField([p[0], p[1], p[2] - e]),
      ];
    const n = Math.hypot(...normal);
    positions.push(...p);
    normals.push(...normal.map((v) => v / n));
    const porcelain =
      smooth(1.495, 1.62, p[1]) *
      (0.65 + 0.35 * (1 - smooth(-0.045, 0.085, p[2])));
    colors.push(
      0.035 + porcelain * 0.76,
      0.105 + porcelain * 0.8,
      0.32 + porcelain * 0.64,
      1,
    );
    const index = positions.length / 3 - 1;
    cache.set(key, index);
    return index;
  };
  const face = (a: number, b: number, c: number) => {
    const ux = positions[b * 3]! - positions[a * 3]!,
      uy = positions[b * 3 + 1]! - positions[a * 3 + 1]!,
      uz = positions[b * 3 + 2]! - positions[a * 3 + 2]!;
    const vx = positions[c * 3]! - positions[a * 3]!,
      vy = positions[c * 3 + 1]! - positions[a * 3 + 1]!,
      vz = positions[c * 3 + 2]! - positions[a * 3 + 2]!;
    const dot =
      (uy * vz - uz * vy) * normals[a * 3]! +
      (uz * vx - ux * vz) * normals[a * 3 + 1]! +
      (ux * vy - uy * vx) * normals[a * 3 + 2]!;
    indices.push(a, ...(dot >= 0 ? [b, c] : [c, b]));
  };
  const tetra = [
    [0, 5, 1, 6],
    [0, 1, 2, 6],
    [0, 2, 3, 6],
    [0, 3, 7, 6],
    [0, 7, 4, 6],
    [0, 4, 5, 6],
  ];
  for (let z = 0; z < nz - 1; z++)
    for (let y = 0; y < ny - 1; y++)
      for (let x = 0; x < nx - 1; x++) {
        const corners = [
          at(x, y, z),
          at(x + 1, y, z),
          at(x + 1, y + 1, z),
          at(x, y + 1, z),
          at(x, y, z + 1),
          at(x + 1, y, z + 1),
          at(x + 1, y + 1, z + 1),
          at(x, y + 1, z + 1),
        ];
        for (const t of tetra) {
          const inside = t
              .map((i) => corners[i]!)
              .filter((i) => values[i]! < 0),
            outside = t.map((i) => corners[i]!).filter((i) => values[i]! >= 0);
          if (inside.length === 1 || inside.length === 3) {
            const one = inside.length === 1 ? inside : outside,
              other = inside.length === 1 ? outside : inside;
            face(
              vertex(one[0]!, other[0]!),
              vertex(one[0]!, other[1]!),
              vertex(one[0]!, other[2]!),
            );
          } else if (inside.length === 2) {
            const a = vertex(inside[0]!, outside[0]!),
              b = vertex(inside[0]!, outside[1]!),
              c = vertex(inside[1]!, outside[0]!),
              d = vertex(inside[1]!, outside[1]!);
            face(a, b, c);
            face(b, d, c);
          }
        }
      }
  const result = {
    positions: new Float32Array(positions),
    normals: new Float32Array(normals),
    colors: new Float32Array(colors),
    indices,
  };
  sculptCache.set(step, result);
  return result;
}
