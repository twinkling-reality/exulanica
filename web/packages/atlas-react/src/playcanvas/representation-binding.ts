import * as pc from 'playcanvas';
import {
  representationSampleIndices,
  type RepresentationBounds,
  type RepresentationSubject,
} from '@exulanica/atlas-core';
import type { RepresentationDraw, RepresentationPointAllocation } from './representation-runtime.js';

const MAX_SOURCE_VERTICES = 250_000;

/** Hierarchy visibility is borrowed authority, never replaced by the representation preference. */
export function representationParentVisible(node: pc.GraphNode): boolean {
  for (let current: pc.GraphNode | null = node; current !== null; current = current.parent) {
    if (!current.enabled) return false;
  }
  return true;
}

/** Static triangle draws only. Generated surface samples are presentation, not measurements. */
export function staticMeshRepresentation(
  device: pc.GraphicsDevice,
  instance: pc.MeshInstance,
  currentSubject: () => RepresentationSubject,
  parentVisible: () => boolean = () => representationParentVisible(instance.node),
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
        clone.copy(original); clone.opacity = original.opacity * weight;
        clone.blendType = pc.BLEND_NORMAL; clone.depthWrite = false; clone.update();
        instance.material = clone;
      } else instance.material = original;
    },
    refresh() { refresh = true; },
    createPoints(limit): RepresentationPointAllocation | null {
      const positions: number[] = [];
      instance.mesh.getPositions(positions);
      const count = positions.length / 3;
      if (!Number.isSafeInteger(count) || count < 1 || count > MAX_SOURCE_VERTICES) return null;
      const indices: number[] = [];
      instance.mesh.getIndices(indices);
      const samples = sampledMeshSurfacePositions(positions, indices, limit);
      if (samples === null) return null;
      return sampledPointAllocation(
        device,
        instance.node,
        samples,
        samples.length / 3,
        original.diffuse,
        currentSubject().subjectId,
      );
    },
    restore() {
      instance.material = original; instance.visible = originalVisible;
      clone?.destroy(); clone = null;
    },
  };
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
    || !Number.isSafeInteger(limit) || limit < 1 || limit > 65_536
    || Array.from(positions).some(value => !Number.isFinite(value))) return null;
  const indices = suppliedIndices.length === 0
    ? Array.from({ length: vertexCount }, (_, index) => index)
    : Array.from(suppliedIndices);
  if (indices.length < 3 || indices.some(index => !Number.isSafeInteger(index)
    || index < 0 || index >= vertexCount)) return null;
  const triangles: { readonly indices: readonly [number, number, number]; readonly end: number }[] = [];
  let area = 0;
  for (let offset = 0; offset + 2 < indices.length; offset += 3) {
    const a = indices[offset]!; const b = indices[offset + 1]!; const c = indices[offset + 2]!;
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
    triangles.push({ indices: [a, b, c], end: area });
  }
  if (triangles.length === 0 || !Number.isFinite(area)) return null;
  const samples = new Float32Array(limit * 3);
  let triangleIndex = 0;
  for (let sample = 0; sample < limit; sample += 1) {
    const target = (sample + 0.5) * area / limit;
    while (triangles[triangleIndex]!.end < target) triangleIndex += 1;
    const [a, b, c] = triangles[triangleIndex]!.indices;
    const root = Math.sqrt(radicalInverse(sample + 1, 2));
    const barycentric = [1 - root, root * (1 - radicalInverse(sample + 1, 3)),
      root * radicalInverse(sample + 1, 3)];
    for (let axis = 0; axis < 3; axis += 1) {
      samples[sample * 3 + axis] = positions[a * 3 + axis]! * barycentric[0]!
        + positions[b * 3 + axis]! * barycentric[1]!
        + positions[c * 3 + axis]! * barycentric[2]!;
    }
  }
  return samples;
}

export function sampledPointAllocation(
  device: pc.GraphicsDevice, node: pc.GraphNode, positions: ArrayLike<number>, limit: number,
  color: pc.Color, subjectId: string,
): RepresentationPointAllocation | null {
  const selected = sampledMeshPositions(positions, limit);
  if (selected === null) return null;
  const pointCount = selected.length / 3;
  const mesh = new pc.Mesh(device);
  // Recompute bounds: these allocations are created after the source entity and otherwise keep
  // an empty origin AABB, which lets the renderer cull a valid point display off-camera.
  mesh.setPositions(selected); mesh.update(pc.PRIMITIVE_POINTS);
  const material = new pc.StandardMaterial();
  material.useLighting = false;
  material.useFog = false;
  // The district sky is deliberately pale, so preserve source hue while enforcing enough
  // contrast for one-pixel WebGL/WebGPU points to remain legible at the endpoint.
  const displayColor = new pc.Color(
    0.08 + color.r * 0.18,
    0.12 + color.g * 0.2,
    0.28 + color.b * 0.24,
  );
  material.emissive.copy(displayColor); material.diffuse.copy(displayColor); material.update();
  const entity = new pc.Entity(`representation-points:${subjectId}`);
  node.addChild(entity);
  const points = new pc.MeshInstance(mesh, material, entity);
  points.pick = false; points.castShadow = false; points.receiveShadow = false;
  const layers = node instanceof pc.Entity ? node.render?.layers : undefined;
  entity.addComponent('render', {
    meshInstances: [points],
    ...(layers ? { layers: [...layers] } : {}),
  });
  let destroyed = false;
  let lastWeight: number | null = null;
  return {
    pointCount,
    // CPU vertex storage plus GPU position payload; engine/material overhead is separately bounded
    // by registry size, and no retained source buffer ownership is included in this allocation.
    byteLength: selected.byteLength * 2,
    setWeight(weight) {
      if (destroyed || weight === lastWeight) return;
      lastWeight = weight;
      points.visible = weight > 0;
      material.opacity = weight;
      material.blendType = weight < 1 ? pc.BLEND_NORMAL : pc.BLEND_NONE;
      material.depthWrite = weight === 1; material.update();
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      entity.destroy(); mesh.destroy(); material.destroy();
    },
  };
}

/** Coordinates remain in their borrowed mesh frame; only source vertex addresses are selected. */
export function sampledMeshPositions(
  positions: ArrayLike<number>,
  limit: number,
): Float32Array | null {
  const count = positions.length / 3;
  if (!Number.isSafeInteger(count) || count < 1 || count > MAX_SOURCE_VERTICES) return null;
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
