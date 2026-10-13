import * as pc from 'playcanvas';
import { TriangleQuery } from '@exulanica/atlas-core';
import { representationParentVisible } from './representation-binding.js';

type Vec3 = readonly [number, number, number];

/** Two-sided triangle intersection. Distance uses the units of the supplied ray. */
export function rayTriangle(origin: Vec3, direction: Vec3, a: Vec3, b: Vec3, c: Vec3): number | null {
  const e1 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const e2 = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
  const p = [direction[1] * e2[2]! - direction[2] * e2[1]!, direction[2] * e2[0]! - direction[0] * e2[2]!, direction[0] * e2[1]! - direction[1] * e2[0]!];
  const det = e1[0]! * p[0]! + e1[1]! * p[1]! + e1[2]! * p[2]!;
  if (det === 0) return null;
  const t = [origin[0] - a[0], origin[1] - a[1], origin[2] - a[2]];
  const u = (t[0]! * p[0]! + t[1]! * p[1]! + t[2]! * p[2]!) / det;
  if (u < 0 || u > 1) return null;
  const q = [t[1]! * e1[2]! - t[2]! * e1[1]!, t[2]! * e1[0]! - t[0]! * e1[2]!, t[0]! * e1[1]! - t[1]! * e1[0]!];
  const v = (direction[0] * q[0]! + direction[1] * q[1]! + direction[2] * q[2]!) / det;
  if (v < 0 || u + v > 1) return null;
  const distance = (e2[0]! * q[0]! + e2[1]! * q[1]! + e2[2]! * q[2]!) / det;
  return distance >= 0 ? distance : null;
}

/** Invert an affine frame in double precision without changing the ray parameter. */
function localRay(frame: pc.Mat4, origin: Vec3, direction: Vec3): readonly [Vec3, Vec3] | null {
  const m = frame.data;
  const a = m[0]!, b = m[4]!, c = m[8]!;
  const d = m[1]!, e = m[5]!, f = m[9]!;
  const g = m[2]!, h = m[6]!, i = m[10]!;
  const row0 = [e * i - f * h, c * h - b * i, b * f - c * e];
  const row1 = [f * g - d * i, a * i - c * g, c * d - a * f];
  const row2 = [d * h - e * g, b * g - a * h, a * e - b * d];
  const determinant = a * row0[0]! + b * row1[0]! + c * row2[0]!;
  if (determinant === 0 || !Number.isFinite(determinant)) return null;
  const transform = (v: Vec3): Vec3 => [row0, row1, row2].map(
    row => (row[0]! * v[0] + row[1]! * v[1] + row[2]! * v[2]) / determinant,
  ) as unknown as Vec3;
  const localOrigin = transform([origin[0] - m[12]!, origin[1] - m[13]!, origin[2] - m[14]!]);
  // Do not normalize: t must still measure distance along the supplied world ray.
  const localDirection = transform(direction);
  return [...localOrigin, ...localDirection].every(Number.isFinite) ? [localOrigin, localDirection] : null;
}

interface StaticSurface {
  readonly positions: number[];
  readonly indices: number[];
  primitiveKey: string;
  query: TriangleQuery | null;
}

/** Reads immutable static renderer triangles once, and their live node frame on every pick. */
export class StaticMeshPicker {
  readonly #surfaces = new WeakMap<pc.Mesh, StaticSurface>();
  readonly #a = new pc.Vec3();
  readonly #b = new pc.Vec3();
  readonly #c = new pc.Vec3();

  /** Prepare static topology during asset loading, before its first pointer interaction. */
  prepare(instance: pc.MeshInstance): void {
    this.#surface(instance);
  }

  #surface(instance: pc.MeshInstance): StaticSurface | null {
    const primitive = instance.mesh.primitive[0];
    if (instance.skinInstance != null || instance.morphInstance != null
      || primitive?.type !== pc.PRIMITIVE_TRIANGLES) return null;
    let surface = this.#surfaces.get(instance.mesh);
    if (surface === undefined) {
      const positions: number[] = []; const indices: number[] = [];
      instance.mesh.getPositions(positions); instance.mesh.getIndices(indices);
      surface = { positions, indices, primitiveKey: '', query: null }; this.#surfaces.set(instance.mesh, surface);
    }
    const { positions, indices } = surface;
    const indexed = primitive.indexed;
    const count = Math.min(primitive.count, indexed ? indices.length - primitive.base : positions.length / 3 - primitive.base);
    const key = `${indexed}:${primitive.base}:${count}`;
    if (surface.primitiveKey !== key) {
      surface.primitiveKey = key;
      try {
        surface.query = new TriangleQuery({ positions, ...(indexed ? { indices } : {}),
          base: primitive.base, count: Math.max(0, Math.floor(count / 3) * 3) });
      } catch (error) {
        if (!(error instanceof RangeError)) throw error;
        // Oversized renderer geometry retains the existing exact path; never pick its bounds.
        surface.query = null;
      }
    }
    return surface;
  }

  /** A unit renderer-world ray, limited by the first surface already met. */
  pick(instance: pc.MeshInstance, origin: Vec3, direction: Vec3, maximum: number): number | null {
    if (!instance.visible || !representationParentVisible(instance.node)) return null;
    if (!instance.aabb.intersectsRay(new pc.Ray(new pc.Vec3(...origin), new pc.Vec3(...direction)))) return null;
    const surface = this.#surface(instance);
    if (surface === null) return null;
    const primitive = instance.mesh.primitive[0]!;
    const { positions, indices } = surface;
    const indexed = primitive.indexed;
    const count = Math.min(primitive.count, indexed ? indices.length - primitive.base : positions.length / 3 - primitive.base);
    const frame = instance.node.getWorldTransform();
    const ray = surface.query === null ? null : localRay(frame, origin, direction);
    if (ray !== null) return surface.query!.nearest(ray[0], ray[1], maximum)?.distance ?? null;
    // A singular frame can still leave a visible triangle. Preserve world-space intersection.
    let best: number | null = null;
    const point = (at: number, target: pc.Vec3): Vec3 => {
      const vertex = indexed ? indices[at]! : at;
      frame.transformPoint(target.set(positions[vertex * 3]!, positions[vertex * 3 + 1]!, positions[vertex * 3 + 2]!), target);
      return [target.x, target.y, target.z];
    };
    for (let offset = 0; offset + 2 < count; offset += 3) {
      const at = primitive.base + offset;
      const hit = rayTriangle(origin, direction, point(at, this.#a), point(at + 1, this.#b), point(at + 2, this.#c));
      if (hit !== null && hit <= maximum && (best === null || hit < best)) best = hit;
    }
    return best;
  }
}
