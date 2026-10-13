/** Static mesh-local triangle queries. No renderer, world authority or semantic identity is inferred. */
export type TriangleQueryPoint = readonly [number, number, number];

export interface TriangleQueryGeometry {
  readonly positions: ArrayLike<number>;
  readonly indices?: ArrayLike<number>;
  /** Offset/count in indices, or vertices for a nonindexed triangle list. */
  readonly base?: number;
  readonly count?: number;
}

export interface TriangleQueryHit {
  /** Ray parameter, not Euclidean distance unless direction has unit length. */
  readonly distance: number;
  /** Original triangle ordinal within this primitive, independent of tree order. */
  readonly triangleIndex: number;
  /** Original first index/vertex offset, including the primitive's base. */
  readonly primitiveOffset: number;
  readonly vertexIndices: readonly [number, number, number];
}

export interface TriangleQueryWork {
  boxes: number;
  triangles: number;
}

/** Accelerator limits, not asset admission rules. A caller can retain its linear fallback. */
export const TRIANGLE_QUERY_LIMITS = Object.freeze({
  triangles: 1_048_576,
  vertices: 1_048_576,
  sourceComponents: 8_388_608,
  depth: 32,
  leafTriangles: 8,
});

type Node = {
  readonly bounds: readonly [number, number, number, number, number, number];
  readonly start: number;
  readonly end: number;
  left: number;
  right: number;
};

function integer(value: number, maximum: number): boolean {
  return Number.isSafeInteger(value) && value >= 0 && value <= maximum;
}

/**
 * Immutable copied geometry with a bounded midpoint BVH. Rebuild when positions or topology
 * change; a live affine node transform only requires inverse-transforming the query ray.
 * Keep that direction unnormalized to preserve the caller's ray parameter through scale.
 * Skinning, morphs, moving vertices and per-instance visibility remain the caller's concern.
 */
export class TriangleQuery {
  readonly #positions: Float64Array;
  readonly #vertices: Uint32Array;
  readonly #order: Uint32Array;
  readonly #nodes: Node[] = [];
  readonly #base: number;
  readonly triangleCount: number;

  constructor(geometry: TriangleQueryGeometry) {
    const size = geometry.positions.length;
    const indexSize = geometry.indices?.length ?? 0;
    const available = geometry.indices === undefined ? size / 3 : indexSize;
    const base = geometry.base ?? 0;
    const count = geometry.count ?? available - base;
    if (!integer(size, TRIANGLE_QUERY_LIMITS.vertices * 3) || size % 3 !== 0
      || !integer(indexSize, TRIANGLE_QUERY_LIMITS.sourceComponents)
      || size + indexSize > TRIANGLE_QUERY_LIMITS.sourceComponents
      || !integer(base, available) || !integer(count, available - base) || count % 3 !== 0
      || count / 3 > TRIANGLE_QUERY_LIMITS.triangles) {
      throw new RangeError('Triangle query geometry exceeds its bounded triangle-list layout.');
    }
    this.#base = base;
    this.triangleCount = count / 3;
    this.#positions = new Float64Array(size);
    for (let i = 0; i < size; i++) {
      const value = geometry.positions[i]!;
      // Bounds, centroids and ray products stay finite for ordinary renderer-local coordinates.
      if (!Number.isFinite(value) || Math.abs(value) > 1e15) throw new RangeError('Invalid triangle query coordinate.');
      this.#positions[i] = value;
    }
    this.#vertices = new Uint32Array(count);
    for (let i = 0; i < count; i++) {
      const vertex = geometry.indices === undefined ? base + i : geometry.indices[base + i]!;
      if (!integer(vertex, size / 3 - 1)) throw new RangeError('Invalid triangle query vertex index.');
      this.#vertices[i] = vertex;
    }
    this.#order = Uint32Array.from({ length: this.triangleCount }, (_, i) => i);
    if (count > 0) this.#build(0, this.triangleCount, 0);
  }

  /** Exact owned typed-buffer bytes; excludes JS nodes, input arrays and build/runtime overhead. */
  get bufferBytes(): number { return this.#positions.byteLength + this.#vertices.byteLength + this.#order.byteLength; }
  get nodeCount(): number { return this.#nodes.length; }

  #build(start: number, end: number, depth: number): number {
    const bounds: [number, number, number, number, number, number] = [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity];
    const p = this.#positions;
    for (let at = start; at < end; at++) {
      const triangle = this.#order[at]! * 3;
      for (let corner = 0; corner < 3; corner++) {
        const vertex = this.#vertices[triangle + corner]! * 3;
        for (let axis = 0; axis < 3; axis++) {
          const value = p[vertex + axis]!;
          bounds[axis] = Math.min(bounds[axis]!, value);
          bounds[axis + 3] = Math.max(bounds[axis + 3]!, value);
        }
      }
    }
    const index = this.#nodes.length;
    const node: Node = { bounds, start, end, left: -1, right: -1 };
    this.#nodes.push(node);
    if (end - start <= TRIANGLE_QUERY_LIMITS.leafTriangles || depth >= TRIANGLE_QUERY_LIMITS.depth) return index;
    let axis = 0;
    for (let i = 1; i < 3; i++) if (bounds[i + 3]! - bounds[i]! > bounds[axis + 3]! - bounds[axis]!) axis = i;
    const middle = (bounds[axis]! + bounds[axis + 3]!) / 2;
    let split = start;
    for (let at = start; at < end; at++) {
      const triangle = this.#order[at]! * 3;
      const centre = (p[this.#vertices[triangle]! * 3 + axis]! + p[this.#vertices[triangle + 1]! * 3 + axis]! + p[this.#vertices[triangle + 2]! * 3 + axis]!) / 3;
      if (centre < middle) {
        const swap = this.#order[split]!; this.#order[split++] = this.#order[at]!; this.#order[at] = swap;
      }
    }
    // An empty midpoint split makes no progress. Keep a bounded linear leaf instead of
    // spending more build work on the same partition, particularly for coincident geometry.
    if (split === start || split === end) return index;
    node.left = this.#build(start, split, depth + 1);
    node.right = this.#build(split, end, depth + 1);
    return index;
  }

  #box(node: Node, origin: TriangleQueryPoint, direction: TriangleQueryPoint, maximum: number): number | null {
    let near = 0; let far = maximum;
    for (let axis = 0; axis < 3; axis++) {
      const low = node.bounds[axis]!; const high = node.bounds[axis + 3]!;
      // Conservative rounding margin: bounds may add candidates, never change triangle hits.
      const margin = Number.EPSILON * 8 * Math.max(1, Math.abs(low), Math.abs(high), Math.abs(origin[axis]!));
      const d = direction[axis]!; const o = origin[axis]!;
      if (d === 0) { if (o < low - margin || o > high + margin) return null; continue; }
      const a = (low - margin - o) / d; const b = (high + margin - o) / d;
      near = Math.max(near, Math.min(a, b)); far = Math.min(far, Math.max(a, b));
      if (near > far) return null;
    }
    return near;
  }

  #triangle(triangle: number, origin: TriangleQueryPoint, direction: TriangleQueryPoint): number | null {
    const p = this.#positions; const ids = this.#vertices; const at = triangle * 3;
    const a = ids[at]! * 3; const b = ids[at + 1]! * 3; const c = ids[at + 2]! * 3;
    const ex = p[b]! - p[a]!; const ey = p[b + 1]! - p[a + 1]!; const ez = p[b + 2]! - p[a + 2]!;
    const fx = p[c]! - p[a]!; const fy = p[c + 1]! - p[a + 1]!; const fz = p[c + 2]! - p[a + 2]!;
    const px = direction[1] * fz - direction[2] * fy;
    const py = direction[2] * fx - direction[0] * fz;
    const pz = direction[0] * fy - direction[1] * fx;
    const determinant = ex * px + ey * py + ez * pz;
    if (determinant === 0) return null;
    const tx = origin[0] - p[a]!; const ty = origin[1] - p[a + 1]!; const tz = origin[2] - p[a + 2]!;
    const u = (tx * px + ty * py + tz * pz) / determinant;
    if (u < 0 || u > 1) return null;
    const qx = ty * ez - tz * ey; const qy = tz * ex - tx * ez; const qz = tx * ey - ty * ex;
    const v = (direction[0] * qx + direction[1] * qy + direction[2] * qz) / determinant;
    if (v < 0 || u + v > 1) return null;
    const distance = (fx * qx + fy * qy + fz * qz) / determinant;
    return Number.isFinite(distance) && distance >= 0 ? distance : null;
  }

  /** Nearest two-sided hit, inclusive maximum. Equal hits retain original primitive order. */
  nearest(origin: TriangleQueryPoint, direction: TriangleQueryPoint, maximum = Infinity, work?: TriangleQueryWork): TriangleQueryHit | null {
    if (!origin.every(Number.isFinite) || !direction.every(Number.isFinite)
      || direction.every((value) => value === 0) || !(maximum >= 0)) throw new RangeError('Invalid triangle query ray.');
    if (work !== undefined) { work.boxes = 0; work.triangles = 0; }
    const root = this.#nodes[0];
    if (root === undefined) return null;
    if (work !== undefined) work.boxes++;
    const rootNear = this.#box(root, origin, direction, maximum);
    if (rootNear === null) return null;
    const pending: number[] = [0, rootNear];
    let best = maximum; let hit = -1;
    while (pending.length > 0) {
      const near = pending.pop()!; const node = this.#nodes[pending.pop()!]!;
      if (near > best) continue;
      if (node.left < 0) {
        for (let at = node.start; at < node.end; at++) {
          const triangle = this.#order[at]!;
          if (work !== undefined) work.triangles++;
          const distance = this.#triangle(triangle, origin, direction);
          if (distance !== null && distance <= best && (hit < 0 || distance < best || triangle < hit)) { best = distance; hit = triangle; }
        }
      } else {
        if (work !== undefined) work.boxes += 2;
        const left = this.#box(this.#nodes[node.left]!, origin, direction, best);
        const right = this.#box(this.#nodes[node.right]!, origin, direction, best);
        if (left !== null && right !== null) {
          if (left <= right) pending.push(node.right, right, node.left, left);
          else pending.push(node.left, left, node.right, right);
        } else if (left !== null) pending.push(node.left, left);
        else if (right !== null) pending.push(node.right, right);
      }
    }
    if (hit < 0) return null;
    const at = hit * 3;
    return { distance: best, triangleIndex: hit, primitiveOffset: this.#base + at,
      vertexIndices: [this.#vertices[at]!, this.#vertices[at + 1]!, this.#vertices[at + 2]!] };
  }
}
