/**
 * What was drawn, measured from the renderer's own triangles.
 *
 * The harness reads every triangle the application submits in its world layer and hands them here
 * with the collision proxy the product navigates by. Nothing in this module knows what a triangle
 * is meant to be: a surface is a walking surface or a facade because of where it is and which way
 * it faces, never because of an entity name, which is what lets the same code score the shipped
 * district today and a generated corridor later.
 */

import {
  heightOnTriangle,
  pointInRing,
  pointTriangleDistance,
  rayCrossesTriangle,
  ringEdgeDistance,
  segmentIntersectsTriangle,
  triangleNormal,
  type Point2,
  type Vec3,
} from './geometry.js';
import { PlanarGrid } from './grid.js';
import { THRESHOLDS, millimetres } from './keys.js';

export type CullMode = 'none' | 'back' | 'front' | 'both';

/** One drawn mesh instance, already transformed into the frame the player navigates in. */
export interface DrawnMesh {
  /** The entity path, for reporting only. No decision reads it. */
  readonly id: string;
  /** Nine numbers per triangle, in submission order, metres. */
  readonly triangles: Float64Array;
  readonly cull: CullMode;
  readonly hasUv: boolean;
  /** Decoded bytes of every distinct texture its material binds. Zero when it binds none. */
  readonly decodedTextureBytes: number;
}

/** A building exterior ring from the collision proxy, with the vertical span it occupies. */
export interface ObstaclePrism {
  readonly id: string;
  readonly ring: readonly Point2[];
  readonly baseY: number;
  readonly topY: number;
}

/** The product's own navigation support, sampled by the harness at the points this asks for. */
export class SupportSamples {
  private readonly heights = new Map<string, number | null>();

  private static key(x: number, z: number): string {
    return `${Math.round(x * 1e6)}:${Math.round(z * 1e6)}`;
  }

  constructor(points: Float64Array, heights: readonly (number | null)[]) {
    if (points.length !== heights.length * 2) {
      throw new Error('support samples need one height per queried point');
    }
    for (let index = 0; index < heights.length; index += 1) {
      this.heights.set(SupportSamples.key(points[index * 2]!, points[index * 2 + 1]!), heights[index]!);
    }
  }

  at(x: number, z: number): number | null {
    const key = SupportSamples.key(x, z);
    if (!this.heights.has(key)) {
      throw new Error(`the product support was not sampled at ${x}, ${z}`);
    }
    return this.heights.get(key)!;
  }
}

const COS_WALKABLE = Math.cos((THRESHOLDS.walkableSlopeDegrees * Math.PI) / 180);
const SIN_WALKABLE = Math.sin((THRESHOLDS.walkableSlopeDegrees * Math.PI) / 180);
const STEP = THRESHOLDS.stepHeightMm / 1000;
const CONTACT = THRESHOLDS.contactToleranceMm / 1000;
const FACADE_BAND = THRESHOLDS.facadeBandMm / 1000;
const TRIANGLE_CELL = 4;

/** Every drawn triangle in one table, with the per-triangle facts every measurement reads. */
export class TriangleTable {
  readonly count: number;
  readonly positions: Float64Array;
  readonly meshOf: Uint32Array;
  readonly normals: Float64Array;
  readonly centroids: Float64Array;
  readonly bounds: Float64Array;
  readonly grid: PlanarGrid;

  constructor(readonly meshes: readonly DrawnMesh[]) {
    let count = 0;
    for (const mesh of meshes) {
      if (mesh.triangles.length % 9 !== 0) throw new Error(`${mesh.id}: triangles are not in nines`);
      count += mesh.triangles.length / 9;
    }
    this.count = count;
    this.positions = new Float64Array(count * 9);
    this.meshOf = new Uint32Array(count);
    this.normals = new Float64Array(count * 3);
    this.centroids = new Float64Array(count * 3);
    this.bounds = new Float64Array(count * 6);
    this.grid = new PlanarGrid(TRIANGLE_CELL, count);
    let t = 0;
    meshes.forEach((mesh, meshIndex) => {
      for (let offset = 0; offset < mesh.triangles.length; offset += 9, t += 1) {
        for (let k = 0; k < 9; k += 1) {
          const value = mesh.triangles[offset + k]!;
          if (!Number.isFinite(value)) throw new Error(`${mesh.id}: non-finite vertex`);
          this.positions[t * 9 + k] = value;
        }
        this.meshOf[t] = meshIndex;
        const [a, b, c] = [this.vertex(t, 0), this.vertex(t, 1), this.vertex(t, 2)];
        const n = triangleNormal(a, b, c) ?? [0, 0, 0];
        this.normals.set(n, t * 3);
        this.centroids.set(
          [(a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3, (a[2] + b[2] + c[2]) / 3],
          t * 3,
        );
        const box = [
          Math.min(a[0], b[0], c[0]), Math.min(a[1], b[1], c[1]), Math.min(a[2], b[2], c[2]),
          Math.max(a[0], b[0], c[0]), Math.max(a[1], b[1], c[1]), Math.max(a[2], b[2], c[2]),
        ];
        this.bounds.set(box, t * 6);
        this.grid.insert(t, box[0]!, box[2]!, box[3]!, box[5]!);
      }
    });
  }

  vertex(t: number, corner: number): Vec3 {
    const o = t * 9 + corner * 3;
    return [this.positions[o]!, this.positions[o + 1]!, this.positions[o + 2]!];
  }

  centroid(t: number): Vec3 {
    return [this.centroids[t * 3]!, this.centroids[t * 3 + 1]!, this.centroids[t * 3 + 2]!];
  }

  normalY(t: number): number {
    return this.normals[t * 3 + 1]!;
  }

  minY(t: number): number {
    return this.bounds[t * 6 + 1]!;
  }

  maxY(t: number): number {
    return this.bounds[t * 6 + 4]!;
  }

  /** Whether the triangle is a front face seen from above, under its mesh's cull mode. */
  seenFromAboveAsFloor(t: number): boolean {
    const ny = this.normalY(t);
    switch (this.meshes[this.meshOf[t]!]!.cull) {
      case 'none': return Math.abs(ny) >= COS_WALKABLE;
      case 'back': return ny >= COS_WALKABLE;
      case 'front': return -ny >= COS_WALKABLE;
      case 'both': return false;
    }
  }

  textured(t: number): boolean {
    const mesh = this.meshes[this.meshOf[t]!]!;
    return mesh.hasUv && mesh.decodedTextureBytes > 0;
  }

  /** Every point whose product support the measurements below need, before any is measured. */
  centroidQueryPoints(): Float64Array {
    const points = new Float64Array(this.count * 2);
    for (let t = 0; t < this.count; t += 1) {
      points[t * 2] = this.centroids[t * 3]!;
      points[t * 2 + 1] = this.centroids[t * 3 + 2]!;
    }
    return points;
  }
}

/** Which triangles are walking surface, and which are facade. Disjoint by construction. */
export interface Classification {
  readonly walking: Uint8Array;
  readonly facade: Uint8Array;
  readonly walkingTriangles: number;
  readonly facadeTriangles: number;
  readonly untexturedWalkingTriangles: number;
  readonly untexturedFacadeTriangles: number;
  /** Per mesh id, for reporting: walking-surface and facade triangles each mesh contributed. */
  readonly byMesh: Readonly<Record<string, { readonly walking: number; readonly facade: number; readonly drawn: number }>>;
}

class PrismIndex {
  readonly grid: PlanarGrid;
  readonly edgeGrid: PlanarGrid;
  readonly edges: { prism: number; a: Point2; b: Point2 }[] = [];

  constructor(readonly prisms: readonly ObstaclePrism[]) {
    this.grid = new PlanarGrid(16, Math.max(1, prisms.length));
    prisms.forEach((prism, index) => {
      let minX = Number.POSITIVE_INFINITY;
      let minZ = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let maxZ = Number.NEGATIVE_INFINITY;
      for (const [x, z] of prism.ring) {
        minX = Math.min(minX, x);
        minZ = Math.min(minZ, z);
        maxX = Math.max(maxX, x);
        maxZ = Math.max(maxZ, z);
      }
      this.grid.insert(index, minX, minZ, maxX, maxZ);
      for (let k = 1; k < prism.ring.length; k += 1) {
        const a = prism.ring[k - 1]!;
        const b = prism.ring[k]!;
        if (Math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-9) continue;
        this.edges.push({ prism: index, a, b });
      }
    });
    this.edgeGrid = new PlanarGrid(4, Math.max(1, this.edges.length));
    this.edges.forEach((edge, index) => {
      this.edgeGrid.insert(
        index,
        Math.min(edge.a[0], edge.b[0]),
        Math.min(edge.a[1], edge.b[1]),
        Math.max(edge.a[0], edge.b[0]),
        Math.max(edge.a[1], edge.b[1]),
      );
    });
  }

  /** Prisms whose ring contains (x, z), in index order. */
  containing(x: number, z: number): number[] {
    const found: number[] = [];
    this.grid.query(x, z, x, z, (index) => {
      if (pointInRing(x, z, this.prisms[index]!.ring)) found.push(index);
    });
    return found.sort((p, q) => p - q);
  }
}

export function classify(
  table: TriangleTable,
  prisms: readonly ObstaclePrism[],
  support: SupportSamples,
): Classification {
  const index = new PrismIndex(prisms);
  const walking = new Uint8Array(table.count);
  const facade = new Uint8Array(table.count);
  let walkingTriangles = 0;
  let facadeTriangles = 0;
  let untexturedWalkingTriangles = 0;
  let untexturedFacadeTriangles = 0;
  const byMesh: Record<string, { walking: number; facade: number; drawn: number }> = {};
  for (const mesh of table.meshes) byMesh[mesh.id] = { walking: 0, facade: 0, drawn: mesh.triangles.length / 9 };
  for (let t = 0; t < table.count; t += 1) {
    const [cx, cy, cz] = table.centroid(t);
    const tally = byMesh[table.meshes[table.meshOf[t]!]!.id]!;
    if (table.seenFromAboveAsFloor(t)) {
      const height = support.at(cx, cz);
      if (height !== null && Math.abs(cy - height) <= STEP) {
        walking[t] = 1;
        walkingTriangles += 1;
        tally.walking += 1;
        if (!table.textured(t)) untexturedWalkingTriangles += 1;
      }
      continue;
    }
    if (Math.abs(table.normalY(t)) > SIN_WALKABLE) continue;
    let near = false;
    index.edgeGrid.query(cx - FACADE_BAND, cz - FACADE_BAND, cx + FACADE_BAND, cz + FACADE_BAND, (e) => {
      if (near) return;
      const edge = index.edges[e]!;
      const prism = prisms[edge.prism]!;
      if (cy < prism.baseY - CONTACT || cy > prism.topY + CONTACT) return;
      if (ringEdgeDistance(cx, cz, [edge.a, edge.b]) <= FACADE_BAND) near = true;
    });
    if (near) {
      facade[t] = 1;
      facadeTriangles += 1;
      tally.facade += 1;
      if (!table.textured(t)) untexturedFacadeTriangles += 1;
    }
  }
  return {
    walking,
    facade,
    walkingTriangles,
    facadeTriangles,
    untexturedWalkingTriangles,
    untexturedFacadeTriangles,
    byMesh,
  };
}

/**
 * The highest walking-surface triangle directly beneath (x, z) and at or below `ceiling`.
 *
 * This is the "drawn support": the surface a person standing there would see under their feet.
 */
export function drawnSupport(
  table: TriangleTable,
  classification: Classification,
  x: number,
  z: number,
  ceiling: number,
): number | null {
  let best: number | null = null;
  table.grid.query(x, z, x, z, (t) => {
    if (classification.walking[t] !== 1) return;
    const o = t * 6;
    if (x < table.bounds[o]! - 1e-9 || x > table.bounds[o + 3]! + 1e-9) return;
    if (z < table.bounds[o + 2]! - 1e-9 || z > table.bounds[o + 5]! + 1e-9) return;
    const height = heightOnTriangle(x, z, table.vertex(t, 0), table.vertex(t, 1), table.vertex(t, 2));
    if (height === null || height > ceiling + 1e-9) return;
    if (best === null || height > best) best = height;
  });
  return best;
}

/** A connected set of drawn triangles, joined where vertices coincide to the millimetre. */
export interface Component {
  readonly index: number;
  readonly triangles: readonly number[];
  readonly vertices: readonly Vec3[];
  readonly bounds: readonly [number, number, number, number, number, number];
  readonly closed: boolean;
  readonly lowest: Vec3;
  readonly meshIds: readonly string[];
}

function find(parent: Int32Array, item: number): number {
  let root = item;
  while (parent[root] !== root) root = parent[root]!;
  let walk = item;
  while (parent[walk] !== root) {
    const next = parent[walk]!;
    parent[walk] = root;
    walk = next;
  }
  return root;
}

export function components(table: TriangleTable): { list: Component[]; of: Int32Array } {
  const ids = new Map<string, number>();
  const corner = new Int32Array(table.count * 3);
  const coordinates: Vec3[] = [];
  for (let t = 0; t < table.count; t += 1) {
    for (let k = 0; k < 3; k += 1) {
      const v = table.vertex(t, k);
      const key = `${Math.round(v[0] * 1000)},${Math.round(v[1] * 1000)},${Math.round(v[2] * 1000)}`;
      let id = ids.get(key);
      if (id === undefined) {
        id = coordinates.length;
        ids.set(key, id);
        coordinates.push(v);
      }
      corner[t * 3 + k] = id;
    }
  }
  const parent = new Int32Array(coordinates.length);
  for (let i = 0; i < parent.length; i += 1) parent[i] = i;
  const union = (a: number, b: number): void => {
    const ra = find(parent, a);
    const rb = find(parent, b);
    if (ra !== rb) parent[Math.max(ra, rb)] = Math.min(ra, rb);
  };
  for (let t = 0; t < table.count; t += 1) {
    union(corner[t * 3]!, corner[t * 3 + 1]!);
    union(corner[t * 3]!, corner[t * 3 + 2]!);
  }
  const order = new Map<number, number>();
  const of = new Int32Array(table.count);
  const grouped: number[][] = [];
  for (let t = 0; t < table.count; t += 1) {
    const root = find(parent, corner[t * 3]!);
    let index = order.get(root);
    if (index === undefined) {
      index = grouped.length;
      order.set(root, index);
      grouped.push([]);
    }
    grouped[index]!.push(t);
    of[t] = index;
  }
  const list = grouped.map((triangles, index): Component => {
    const seen = new Set<number>();
    const vertices: Vec3[] = [];
    const edges = new Map<string, number>();
    const meshIds = new Set<string>();
    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let minZ = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    let maxZ = Number.NEGATIVE_INFINITY;
    let lowest: Vec3 | null = null;
    for (const t of triangles) {
      meshIds.add(table.meshes[table.meshOf[t]!]!.id);
      const o = t * 6;
      minX = Math.min(minX, table.bounds[o]!);
      minY = Math.min(minY, table.bounds[o + 1]!);
      minZ = Math.min(minZ, table.bounds[o + 2]!);
      maxX = Math.max(maxX, table.bounds[o + 3]!);
      maxY = Math.max(maxY, table.bounds[o + 4]!);
      maxZ = Math.max(maxZ, table.bounds[o + 5]!);
      for (let k = 0; k < 3; k += 1) {
        const id = corner[t * 3 + k]!;
        if (!seen.has(id)) {
          seen.add(id);
          const v = coordinates[id]!;
          vertices.push(v);
          if (lowest === null || v[1] < lowest[1]) lowest = v;
        }
        const next = corner[t * 3 + ((k + 1) % 3)]!;
        const edge = id < next ? `${id}:${next}` : `${next}:${id}`;
        edges.set(edge, (edges.get(edge) ?? 0) + 1);
      }
    }
    const closed = edges.size > 0 && [...edges.values()].every((uses) => uses === 2);
    return {
      index,
      triangles,
      vertices,
      bounds: [minX, minY, minZ, maxX, maxY, maxZ],
      closed,
      lowest: lowest!,
      meshIds: [...meshIds].sort(),
    };
  });
  return { list, of };
}

/** The lowest point of every component, for the harness to sample the product support at. */
export function componentQueryPoints(list: readonly Component[]): Float64Array {
  const points = new Float64Array(list.length * 2);
  list.forEach((component, index) => {
    points[index * 2] = component.lowest[0];
    points[index * 2 + 1] = component.lowest[2];
  });
  return points;
}

export interface IntegrityMeasurement {
  readonly components: number;
  readonly supportComponents: number;
  readonly componentsDetachedFromSupport: number;
  readonly detachedTriangles: number;
  readonly detachedByMesh: Readonly<Record<string, number>>;
  readonly detachedExamples: readonly {
    readonly meshIds: readonly string[];
    readonly triangles: number;
    readonly lowestMm: readonly [number, number, number];
  }[];
  readonly trianglesInsideBuildings: number;
  readonly componentsInsideBuildings: number;
  readonly insideByMesh: Readonly<Record<string, number>>;
  readonly buildingsWithDrawnGeometryInside: readonly string[];
  readonly ringEdges: number;
  readonly ringEdgesWithoutDrawnFacade: number;
  readonly ringEdgeExamples: readonly { readonly prism: string; readonly midpointMm: readonly [number, number] }[];
}

function overlaps(
  box: ArrayLike<number>,
  x: number, y: number, z: number, pad: number,
): boolean {
  return x >= box[0]! - pad && x <= box[3]! + pad &&
    y >= box[1]! - pad && y <= box[4]! + pad &&
    z >= box[2]! - pad && z <= box[5]! + pad;
}

function contains(component: Component, table: TriangleTable, point: Vec3): boolean {
  if (!component.closed || !overlaps(component.bounds, point[0], point[1], point[2], 0)) return false;
  let crossings = 0;
  for (const t of component.triangles) {
    if (rayCrossesTriangle(point, table.vertex(t, 0), table.vertex(t, 1), table.vertex(t, 2))) {
      crossings += 1;
    }
  }
  return crossings % 2 === 1;
}

/**
 * Integrity of the drawn geometry: what floats, what lies inside a building, which walls are open.
 *
 * `support` must hold the product support at every component's lowest point.
 */
export function integrity(
  table: TriangleTable,
  classification: Classification,
  prisms: readonly ObstaclePrism[],
  parts: { list: readonly Component[]; of: Int32Array },
  support: SupportSamples,
): IntegrityMeasurement {
  const { list, of } = parts;
  const mm = millimetres;
  // Support roots: components with a walking-surface triangle that rest on the product support.
  const root = new Uint8Array(list.length);
  for (let t = 0; t < table.count; t += 1) {
    if (classification.walking[t] !== 1) continue;
    const component = list[of[t]!]!;
    const height = support.at(component.lowest[0], component.lowest[2]);
    if (height !== null && Math.abs(component.lowest[1] - height) <= CONTACT) root[component.index] = 1;
  }

  // Contacts, as an adjacency list built in component order.
  const adjacent: Set<number>[] = list.map(() => new Set<number>());
  const link = (a: number, b: number): void => {
    if (a === b) return;
    adjacent[a]!.add(b);
    adjacent[b]!.add(a);
  };
  const closedGrid = new PlanarGrid(8, Math.max(1, list.length));
  for (const component of list) {
    if (!component.closed) continue;
    closedGrid.insert(component.index, component.bounds[0], component.bounds[2], component.bounds[3], component.bounds[5]);
  }
  // 1. A vertex within the contact tolerance of another component's triangle.
  for (const component of list) {
    for (const v of component.vertices) {
      table.grid.query(v[0] - CONTACT, v[2] - CONTACT, v[0] + CONTACT, v[2] + CONTACT, (t) => {
        const other = of[t]!;
        if (other === component.index || adjacent[component.index]!.has(other)) return;
        if (!overlaps(table.bounds.subarray(t * 6, t * 6 + 6), v[0], v[1], v[2], CONTACT)) return;
        if (pointTriangleDistance(v, table.vertex(t, 0), table.vertex(t, 1), table.vertex(t, 2)) <= CONTACT) {
          link(component.index, other);
        }
      });
    }
  }
  // 2. A vertex inside another closed component.
  for (const component of list) {
    for (const v of component.vertices) {
      const candidates: number[] = [];
      closedGrid.query(v[0], v[2], v[0], v[2], (other) => {
        if (other !== component.index && !adjacent[component.index]!.has(other)) candidates.push(other);
      });
      for (const other of candidates) {
        if (contains(list[other]!, table, v)) link(component.index, other);
      }
    }
  }
  // Reachability from the support roots, breadth first in component order.
  const reachability = (): Uint8Array => {
    const reached = new Uint8Array(list.length);
    const queue: number[] = [];
    for (let c = 0; c < list.length; c += 1) {
      if (root[c] === 1) {
        reached[c] = 1;
        queue.push(c);
      }
    }
    for (let head = 0; head < queue.length; head += 1) {
      const sorted = [...adjacent[queue[head]!]!].sort((a, b) => a - b);
      for (const next of sorted) {
        if (reached[next] === 1) continue;
        reached[next] = 1;
        queue.push(next);
      }
    }
    return reached;
  };
  // 3. An edge of one triangle crossing another, tested only where it can change the answer:
  // between a component not yet reached and anything near it. Every such pair is tested in both
  // directions, so a chain of crossings back to the support is found in one pass.
  const crosses = (t: number, u: number): boolean => {
    for (const [s, w] of [[t, u], [u, t]] as const) {
      const a = table.vertex(w, 0);
      const b = table.vertex(w, 1);
      const c = table.vertex(w, 2);
      for (let k = 0; k < 3; k += 1) {
        if (segmentIntersectsTriangle(table.vertex(s, k), table.vertex(s, (k + 1) % 3), a, b, c)) {
          return true;
        }
      }
    }
    return false;
  };
  const beforeCrossings = reachability();
  for (const component of list) {
    if (beforeCrossings[component.index] === 1) continue;
    for (const t of component.triangles) {
      const box = table.bounds.subarray(t * 6, t * 6 + 6);
      table.grid.query(box[0]!, box[2]!, box[3]!, box[5]!, (u) => {
        const other = of[u]!;
        if (other === component.index || adjacent[component.index]!.has(other)) return;
        const near = table.bounds.subarray(u * 6, u * 6 + 6);
        if (
          near[0]! > box[3]! || near[3]! < box[0]! ||
          near[1]! > box[4]! || near[4]! < box[1]! ||
          near[2]! > box[5]! || near[5]! < box[2]!
        ) return;
        if (crosses(t, u)) link(component.index, other);
      });
    }
  }
  const reached = reachability();
  const detachedByMesh: Record<string, number> = {};
  const detachedExamples: IntegrityMeasurement['detachedExamples'][number][] = [];
  let componentsDetachedFromSupport = 0;
  let detachedTriangles = 0;
  for (const component of list) {
    if (reached[component.index] === 1) continue;
    componentsDetachedFromSupport += 1;
    detachedTriangles += component.triangles.length;
    for (const id of component.meshIds) detachedByMesh[id] = (detachedByMesh[id] ?? 0) + 1;
    if (detachedExamples.length < 12) {
      detachedExamples.push({
        meshIds: component.meshIds,
        triangles: component.triangles.length,
        lowestMm: [mm(component.lowest[0]), mm(component.lowest[1]), mm(component.lowest[2])],
      });
    }
  }

  // Drawn triangles inside a building volume shrunk by the contact tolerance.
  const index = new PrismIndex(prisms);
  const insideByMesh: Record<string, number> = {};
  const insideComponents = new Set<number>();
  const insideBuildings = new Set<string>();
  let trianglesInsideBuildings = 0;
  for (let t = 0; t < table.count; t += 1) {
    const [cx, cy, cz] = table.centroid(t);
    for (const p of index.containing(cx, cz)) {
      const prism = prisms[p]!;
      if (cy <= prism.baseY + CONTACT || cy >= prism.topY - CONTACT) continue;
      if (ringEdgeDistance(cx, cz, prism.ring) <= CONTACT) continue;
      trianglesInsideBuildings += 1;
      const id = table.meshes[table.meshOf[t]!]!.id;
      insideByMesh[id] = (insideByMesh[id] ?? 0) + 1;
      insideComponents.add(of[t]!);
      insideBuildings.add(prism.id);
      break;
    }
  }

  // Every collision edge must have drawn geometry at its midpoint in the eye-level band.
  const probeHeight = THRESHOLDS.facadeProbeHeightMm / 1000;
  let ringEdgesWithoutDrawnFacade = 0;
  const ringEdgeExamples: { prism: string; midpointMm: readonly [number, number] }[] = [];
  for (const edge of index.edges) {
    const prism = prisms[edge.prism]!;
    const mx = (edge.a[0] + edge.b[0]) / 2;
    const mz = (edge.a[1] + edge.b[1]) / 2;
    const my = prism.baseY + Math.min(probeHeight, (prism.topY - prism.baseY) / 2);
    const probe: Vec3 = [mx, my, mz];
    let covered = false;
    table.grid.query(mx - CONTACT, mz - CONTACT, mx + CONTACT, mz + CONTACT, (t) => {
      if (covered) return;
      if (!overlaps(table.bounds.subarray(t * 6, t * 6 + 6), mx, my, mz, CONTACT)) return;
      if (pointTriangleDistance(probe, table.vertex(t, 0), table.vertex(t, 1), table.vertex(t, 2)) <= CONTACT) {
        covered = true;
      }
    });
    if (!covered) {
      ringEdgesWithoutDrawnFacade += 1;
      if (ringEdgeExamples.length < 12) ringEdgeExamples.push({ prism: prism.id, midpointMm: [mm(mx), mm(mz)] });
    }
  }

  return {
    components: list.length,
    supportComponents: root.reduce((total, value) => total + value, 0),
    componentsDetachedFromSupport,
    detachedTriangles,
    detachedByMesh,
    detachedExamples,
    trianglesInsideBuildings,
    componentsInsideBuildings: insideComponents.size,
    insideByMesh,
    buildingsWithDrawnGeometryInside: [...insideBuildings].sort(),
    ringEdges: index.edges.length,
    ringEdgesWithoutDrawnFacade,
    ringEdgeExamples,
  };
}
