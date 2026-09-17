import * as pc from 'playcanvas';
import {
  DATA_VIEW_STYLE,
  REPRESENTATION_POINTS_PER_SUBJECT,
  representationSampleIndices,
  type DataViewStyle,
  type RepresentationBounds,
  type RepresentationSubject,
} from '@exulanica/atlas-core';
import { createDataViewPoints } from './data-view/points.js';
import type { RepresentationDraw, RepresentationPointAllocation } from './representation-runtime.js';

/** Triangle sampling reads the whole mesh on the CPU, so it stays bounded by source size. */
const MAX_SOURCE_VERTICES = 250_000;
/** Address sampling only selects existing points, so a retained buffer may be much larger. */
export const MAX_RETAINED_POINTS = 16_777_216;

/** Hierarchy visibility is borrowed authority, never replaced by the representation preference. */
export function representationParentVisible(node: pc.GraphNode): boolean {
  for (let current: pc.GraphNode | null = node; current !== null; current = current.parent) {
    if (!current.enabled) return false;
  }
  return true;
}

/** The layers a borrowed node draws in, for a presentation draw parented beneath it. */
function layersOf(node: pc.GraphNode): readonly number[] | undefined {
  return node instanceof pc.Entity ? node.render?.layers ?? node.gsplat?.layers : undefined;
}

/** Static triangle draws only. Generated surface samples are presentation, not measurements. */
export function staticMeshRepresentation(
  device: pc.GraphicsDevice,
  instance: pc.MeshInstance,
  currentSubject: () => RepresentationSubject,
  parentVisible: () => boolean = () => representationParentVisible(instance.node),
  style: DataViewStyle = DATA_VIEW_STYLE,
): RepresentationDraw | null {
  if (!(instance.material instanceof pc.StandardMaterial) || instance.skinInstance != null
    || instance.morphInstance != null || !instance.visible
    || instance.mesh.vertexBuffer === null || instance.mesh.vertexBuffer.numVertices > MAX_SOURCE_VERTICES
    || instance.mesh.primitive[0]?.type !== pc.PRIMITIVE_TRIANGLES) return null;
  const original = instance.material;
  const originalVisible = instance.visible;
  let clone: pc.StandardMaterial | null = null;
  let lastWeight: number | null = null;
  let refresh = true;
  let surface: { positions: number[]; indices: number[]; area: number } | null | undefined;
  const readSurface = () => {
    if (surface !== undefined) return surface;
    const positions: number[] = [];
    instance.mesh.getPositions(positions);
    const indices: number[] = [];
    instance.mesh.getIndices(indices);
    const area = positions.length >= 9 ? meshSurfaceArea(positions, indices) : 0;
    surface = Number.isFinite(area) && area > 0 ? { positions, indices, area } : null;
    return surface;
  };
  return {
    currentSubject,
    parentVisible,
    setRenderedWeight(weight) {
      if (!refresh && weight === lastWeight) return;
      refresh = false;
      lastWeight = weight;
      instance.visible = originalVisible;
      if (weight < 1) {
        clone ??= original.clone();
        // Retain an alpha-zero original draw for its stable pick subject at the point endpoint.
        // Theme/material changes affect the borrowed original; copy them before presentation alpha.
        // The fade is a dither, not a blend: the surface stays an opaque, depth-writing draw that
        // loses pixels as it fades, so overlapping batches never sort against each other, and the
        // pixels it gives up show the data view's dark ground and the points behind.
        clone.copy(original); clone.opacity = original.opacity * weight;
        clone.opacityDither = pc.DITHER_IGNNOISE; clone.opacityShadowDither = pc.DITHER_IGNNOISE;
        clone.update();
        instance.material = clone;
      } else instance.material = original;
    },
    refresh() { refresh = true; },
    pointDemand() {
      const read = readSurface();
      return read === null ? 0 : read.area * style.points.densityPerSquareMetre;
    },
    createPoints(limit): RepresentationPointAllocation | null {
      const read = readSurface();
      if (read === null) return null;
      const count = read.positions.length / 3;
      if (!Number.isSafeInteger(count) || count < 1 || count > MAX_SOURCE_VERTICES) return null;
      const samples = sampledMeshSurfacePositions(read.positions, read.indices, limit);
      if (samples === null) return null;
      const layers = layersOf(instance.node);
      return createDataViewPoints({
        device, node: instance.node, positions: samples, style,
        subjectId: currentSubject().subjectId, ...(layers ? { layers } : {}),
      });
    },
    restore() {
      instance.material = original; instance.visible = originalVisible;
      clone?.destroy(); clone = null;
    },
  };
}

/** The summed area of a triangle list, in the mesh's own squared units. */
export function meshSurfaceArea(positions: ArrayLike<number>, suppliedIndices: ArrayLike<number>): number {
  const vertexCount = positions.length / 3;
  const indexCount = suppliedIndices.length === 0 ? vertexCount : suppliedIndices.length;
  let area = 0;
  for (let offset = 0; offset + 2 < indexCount; offset += 3) {
    const a = suppliedIndices.length === 0 ? offset : suppliedIndices[offset]!;
    const b = suppliedIndices.length === 0 ? offset + 1 : suppliedIndices[offset + 1]!;
    const c = suppliedIndices.length === 0 ? offset + 2 : suppliedIndices[offset + 2]!;
    if (!(a >= 0 && b >= 0 && c >= 0 && a < vertexCount && b < vertexCount && c < vertexCount)) return Number.NaN;
    const abx = positions[b * 3]! - positions[a * 3]!;
    const aby = positions[b * 3 + 1]! - positions[a * 3 + 1]!;
    const abz = positions[b * 3 + 2]! - positions[a * 3 + 2]!;
    const acx = positions[c * 3]! - positions[a * 3]!;
    const acy = positions[c * 3 + 1]! - positions[a * 3 + 1]!;
    const acz = positions[c * 3 + 2]! - positions[a * 3 + 2]!;
    area += Math.hypot(aby * acz - abz * acy, abz * acx - abx * acz, abx * acy - aby * acx) / 2;
  }
  return area;
}

/** The mesh's own local extent, for a generated batch's `generated-extent` bounds. */
export function meshLocalExtent(mesh: pc.Mesh): {
  readonly min: readonly [number, number, number];
  readonly max: readonly [number, number, number];
} | null {
  const { center, halfExtents } = mesh.aabb;
  const min = [center.x - halfExtents.x, center.y - halfExtents.y, center.z - halfExtents.z] as const;
  const max = [center.x + halfExtents.x, center.y + halfExtents.y, center.z + halfExtents.z] as const;
  return [...min, ...max].every(Number.isFinite) ? { min, max } : null;
}

function radicalInverse(index: number, base: number): number {
  let value = 0;
  let fraction = 1 / base;
  for (let held = index; held > 0; held = Math.floor(held / base)) {
    value += (held % base) * fraction;
    fraction /= base;
  }
  return value;
}

/** Deterministic area-weighted samples of the renderer's triangles, never inferred geometry. */
export function sampledMeshSurfacePositions(
  positions: ArrayLike<number>,
  suppliedIndices: ArrayLike<number>,
  limit: number,
): Float32Array | null {
  const vertexCount = positions.length / 3;
  if (!Number.isSafeInteger(vertexCount) || vertexCount < 3 || vertexCount > MAX_SOURCE_VERTICES
    || !Number.isSafeInteger(limit) || limit < 1 || limit > REPRESENTATION_POINTS_PER_SUBJECT) return null;
  for (let i = 0; i < positions.length; i += 1) if (!Number.isFinite(positions[i]!)) return null;
  const indexCount = suppliedIndices.length === 0 ? vertexCount : suppliedIndices.length;
  if (indexCount < 3) return null;
  const index = (offset: number): number => (suppliedIndices.length === 0 ? offset : suppliedIndices[offset]!);
  for (let offset = 0; offset < indexCount; offset += 1) {
    const value = index(offset);
    if (!Number.isSafeInteger(value) || value < 0 || value >= vertexCount) return null;
  }
  const triangleCount = Math.floor(indexCount / 3);
  const corners = new Uint32Array(triangleCount * 3);
  const ends = new Float64Array(triangleCount);
  let kept = 0;
  let area = 0;
  for (let offset = 0; offset + 2 < indexCount; offset += 3) {
    const a = index(offset); const b = index(offset + 1); const c = index(offset + 2);
    const abx = positions[b * 3]! - positions[a * 3]!;
    const aby = positions[b * 3 + 1]! - positions[a * 3 + 1]!;
    const abz = positions[b * 3 + 2]! - positions[a * 3 + 2]!;
    const acx = positions[c * 3]! - positions[a * 3]!;
    const acy = positions[c * 3 + 1]! - positions[a * 3 + 1]!;
    const acz = positions[c * 3 + 2]! - positions[a * 3 + 2]!;
    const x = aby * acz - abz * acy;
    const y = abz * acx - abx * acz;
    const z = abx * acy - aby * acx;
    const triangleArea = Math.hypot(x, y, z) / 2;
    if (!(triangleArea > 0)) continue;
    area += triangleArea;
    corners[kept * 3] = a; corners[kept * 3 + 1] = b; corners[kept * 3 + 2] = c;
    ends[kept] = area;
    kept += 1;
  }
  if (kept === 0 || !Number.isFinite(area)) return null;
  const samples = new Float32Array(limit * 3);
  let triangle = 0;
  for (let sample = 0; sample < limit; sample += 1) {
    const target = (sample + 0.5) * area / limit;
    while (triangle < kept - 1 && ends[triangle]! < target) triangle += 1;
    const a = corners[triangle * 3]!; const b = corners[triangle * 3 + 1]!; const c = corners[triangle * 3 + 2]!;
    const root = Math.sqrt(radicalInverse(sample + 1, 2));
    const v = radicalInverse(sample + 1, 3);
    const wa = 1 - root; const wb = root * (1 - v); const wc = root * v;
    for (let axis = 0; axis < 3; axis += 1) {
      samples[sample * 3 + axis] = positions[a * 3 + axis]! * wa
        + positions[b * 3 + axis]! * wb
        + positions[c * 3 + axis]! * wc;
    }
  }
  return samples;
}

/**
 * A retained buffer's own points, drawn by the data view: even addresses into the existing
 * positions, never interpolated. Point maps and trained Gaussian centres use this.
 */
export function retainedPointAllocation(
  device: pc.GraphicsDevice, node: pc.GraphNode, positions: ArrayLike<number>, limit: number,
  subjectId: string, style: DataViewStyle = DATA_VIEW_STYLE,
): RepresentationPointAllocation | null {
  const selected = sampledMeshPositions(positions, limit);
  if (selected === null) return null;
  const layers = layersOf(node);
  return createDataViewPoints({
    device, node, positions: selected, style, subjectId, ...(layers ? { layers } : {}),
  });
}

/** Coordinates remain in their borrowed mesh frame; only source vertex addresses are selected. */
export function sampledMeshPositions(
  positions: ArrayLike<number>,
  limit: number,
): Float32Array | null {
  const count = positions.length / 3;
  if (!Number.isSafeInteger(count) || count < 1 || count > MAX_RETAINED_POINTS) return null;
  const indices = representationSampleIndices(count, limit);
  if (indices.length === 0) return null;
  const selected = new Float32Array(indices.length * 3);
  for (let i = 0; i < indices.length; i += 1) {
    for (let axis = 0; axis < 3; axis += 1) {
      const value = positions[indices[i]! * 3 + axis]!;
      if (!Number.isFinite(value)) return null;
      selected[i * 3 + axis] = value;
    }
  }
  return selected;
}

/** Eight display-world corners through the exact borrowed renderer frame, for non-pickable UI. */
export function representationWorldBounds(
  bounds: RepresentationBounds,
  node: pc.GraphNode,
): readonly (readonly [number, number, number])[] {
  if (!['metres', 'scene-units'].includes(bounds.units)) {
    throw new TypeError('Bounds units must already agree with the borrowed renderer frame');
  }
  if (bounds.min.length !== 3 || bounds.max.length !== 3
    || ![...bounds.min, ...bounds.max].every(Number.isFinite)
    || bounds.min.some((value, axis) => value > bounds.max[axis]!)) {
    throw new TypeError('Bounds must be a finite ordered three-dimensional box');
  }
  const matrix = node.getWorldTransform();
  const point = new pc.Vec3();
  const world = new pc.Vec3();
  const corners: (readonly [number, number, number])[] = [];
  for (const x of [bounds.min[0], bounds.max[0]]) {
    for (const y of [bounds.min[1], bounds.max[1]]) {
      for (const z of [bounds.min[2], bounds.max[2]]) {
        matrix.transformPoint(point.set(x, y, z), world);
        corners.push(Object.freeze([world.x, world.y, world.z]));
      }
    }
  }
  return Object.freeze(corners);
}
