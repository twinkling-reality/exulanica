import * as pc from 'playcanvas';
import { resolveLookRole, stretchCoordinate, type AxisStretch, type LookFamily, type ResolvedStylePack } from '@exulanica/atlas-core';
import type { RenderShading } from '../generated-tile/look.js';
import type { LoadedPieceGroup, LoadedTexturedLevels, PackPieces } from './pieces.js';
import { drawInstancedPieces, type InstancePlacement, type InstancedDressing, type InstancedView } from './instanced-pieces.js';
import { swatchMaterial } from './swatch-material.js';

/**
 * Pack pieces placed in a world's slots, baked into one mesh per swatch.
 *
 * A slot is a box in city millimetres (east, north, up) with its base centre, its front (a unit
 * vector in plan) and its size: width along the front, depth, height. A piece is glTF metres, +Y up,
 * +Z front, pivot at its base centre. A piece stands in its slot by the rotation that turns its +Z
 * to the slot's front about the vertical, which takes glTF +X to the slot's right as a viewer facing
 * the front sees it; never a reflection. The family's fit (`fit` in the pack module) scales each
 * axis, or stretches a stated zone so a frame keeps its bars whatever the hole; a tiled family
 * repeats the piece along the width.
 *
 * Every slot's piece is moved into place here, once, and the triangles of every slot that share a
 * swatch become one mesh, so a town's six hundred windows are a draw per swatch. Normals follow each
 * triangle's own stretch. Positions are renderer metres (east, up, south) in the same frame as the
 * tiles' roots, so the caller parents the dressing where the tiles are parented.
 *
 * A textured piece (`pieces.ts`) is not baked: it is drawn instanced (`instanced-pieces.ts`) by the
 * matrix `placementMatrix` makes, the same transform the bake applies to each corner, so it stands
 * exactly where a palette piece would. It stands whole on its base: a draped slot's piece is not
 * bent to the land under each of its points, as a palette piece's is, and a stretch zone is not
 * drawn (the server refuses one on a textured piece; a slot asking for one is left undressed).
 *
 * A slot the pack does not dress, or that no variant fits, is returned by identity for the caller
 * to draw as it would without a pack. Nothing here changes what a slot is, what collides or where
 * anyone can walk.
 */

export interface PieceSlot {
  readonly identity: string;
  readonly lookRole: string;
  /** Base centre, city millimetres: east, north, up. */
  readonly positionMm: readonly [number, number, number];
  /** The slot's front in plan, a unit vector (east, north). */
  readonly front: readonly [number, number];
  /** Width along the front, depth, height. */
  readonly boxMm: readonly [number, number, number];
  /**
   * A slot of a site on land that follows the land: each point of its piece stands as far above
   * the land under it as the slot's base stands above the land under its base's centre.
   */
  readonly drape?: true;
}

export interface SlotDressing {
  /** Pieces placed. A tiled slot places one per copy. */
  readonly placed: number;
  readonly undressed: readonly string[];
  readonly triangles: number;
  readonly draws: number;
  /** The textured pieces drawn instanced, or none. */
  readonly instanced: InstancedDressing | null;
  dispose(): void;
}

/**
 * The column-major matrix that stands a piece (glTF metres) in its slot, in renderer metres (east,
 * up, south): scaled by `scale` on glTF x, y, z, moved `shift` metres along its own width (a tiled
 * copy), turned so +Z is the slot's `front` (east, north) and set at the slot's base centre
 * (`baseM`: east, north, up). Exactly the transform the bake applies to an unstretched corner.
 */
export function placementMatrix(
  front: readonly [number, number],
  baseM: readonly [number, number, number],
  scale: readonly [number, number, number],
  shift: number,
): Float32Array {
  const [fe, fn] = front;
  const [east, north, up] = baseM;
  const [sx, sy, sz] = scale;
  // glTF x to renderer: (-north, 0, -east) of the front; z: (east, 0, -north) of the front.
  return new Float32Array([
    -fn * sx, 0, -fe * sx, 0,
    0, sy, 0, 0,
    fe * sz, 0, -fn * sz, 0,
    east - shift * fn, up, -north - shift * fe, 1,
  ]);
}

/** A textured piece's first-level triangles as `matrix` places them, as the bake would copy a seat's. */
function placedTriangles(levels: LoadedTexturedLevels, matrix: Float32Array, batch: { positions: number[]; normals: number[] }): void {
  const m = matrix;
  for (const primitive of levels.lod0) {
    const { positions, normals, indices } = primitive;
    for (const v of indices) {
      const x = positions[v * 3]!;
      const y = positions[v * 3 + 1]!;
      const z = positions[v * 3 + 2]!;
      for (let k = 0; k < 3; k += 1) batch.positions.push(Math.fround(m[k]! * x + m[4 + k]! * y + m[8 + k]! * z + m[12 + k]!));
      // A uniform scale and a turn: the normal turns with the piece, kept unit length.
      const nx = normals[v * 3]!;
      const ny = normals[v * 3 + 1]!;
      const nz = normals[v * 3 + 2]!;
      const tx = m[0]! * nx + m[4]! * ny + m[8]! * nz;
      const ty = m[1]! * nx + m[5]! * ny + m[9]! * nz;
      const tz = m[2]! * nx + m[6]! * ny + m[10]! * nz;
      const length = Math.hypot(tx, ty, tz);
      batch.normals.push(Math.fround(tx / length), Math.fround(ty / length), Math.fround(tz / length));
    }
  }
}

const PREFIX = 'style-pack:';

/** Where one axis of a piece lands: scaled about the pivot, or stretched from the low face. */
interface AxisPlacement {
  readonly scale: number;
  readonly stretch: AxisStretch | null;
  /** Millimetres from the pivot to the piece's low face on this axis (0 for height). */
  readonly lowMm: number;
  /** Millimetres from the pivot to the slot's low face on this axis. */
  readonly boxLowMm: number;
}

/** A coordinate in metres along one axis, placed. */
function placeAxis(axis: AxisPlacement, value: number): number {
  if (axis.stretch === null) return value * axis.scale;
  return (stretchCoordinate(axis.stretch, value * 1000 - axis.lowMm) + axis.boxLowMm) / 1000;
}

/** How much one axis is drawn out around a point, for turning its normals. */
function axisFactor(axis: AxisPlacement, value: number): number {
  if (axis.stretch === null) return axis.scale;
  const p = value * 1000 - axis.lowMm;
  return p > axis.stretch.low && p < axis.stretch.high ? axis.stretch.length / (axis.stretch.high - axis.stretch.low) : 1;
}

class SwatchBatch {
  readonly positions: number[] = [];
  readonly normals: number[] = [];
}

export function dressSlots(
  parent: pc.Entity,
  slots: readonly PieceSlot[],
  pack: ResolvedStylePack,
  families: ReadonlyMap<string, LookFamily>,
  pieces: PackPieces,
  shading: RenderShading,
  /** Opt-in copy of a selected slot's exact baked triangles, in the parent's frame. */
  capture?: { readonly identities: ReadonlySet<string>; readonly maximumVertices: number; readonly triangles: (identity: string, positions: readonly number[], normals: readonly number[]) => void },
  /** The land's height under a point of the parent's frame (east, south, metres), for draped slots; none on level ground. */
  ground?: (east: number, south: number) => number,
  /** The camera textured pieces choose their level of detail by; none draws every one at its first. */
  view?: InstancedView,
): SlotDressing {
  const batches = new Map<string, SwatchBatch>();
  const placements: InstancePlacement[] = [];
  const undressed: string[] = [];
  let placed = 0;
  let capturedVertices = 0;
  const captureLimit = capture !== undefined && Number.isSafeInteger(capture.maximumVertices) && capture.maximumVertices >= 0 ? capture.maximumVertices : 0;
  let device: pc.GraphicsDevice | null = null;
  const local = [0, 0, 0];
  const normal = [0, 0, 0];
  for (const slot of slots) {
    const captured = capture?.identities.has(slot.identity) ? new SwatchBatch() : null;
    let captureRefused = false;
    const dressing = resolveLookRole(pack, { identity: slot.identity, lookRole: slot.lookRole, positionMm: slot.positionMm, yawQuarterTurns: 0, boxMm: slot.boxMm }, families, 'module');
    const module = dressing?.kind === 'module' ? pack.modules[dressing.role] : undefined;
    const piece = dressing?.kind === 'module' && module !== undefined ? pieces.get(module, dressing.file) : undefined;
    if (dressing?.kind !== 'module' || module === undefined || piece === undefined) {
      undressed.push(slot.identity);
      continue;
    }
    const [w, d] = module.variants[dressing.variant]!.size_mm;
    const [bw, bd] = slot.boxMm;
    if (piece.textured !== undefined) {
      // Drawn instanced, never stretched: a slot that asks a textured piece to stretch keeps its primitive.
      if (dressing.stretch.some((axis) => axis !== null)) {
        undressed.push(slot.identity);
        continue;
      }
      const base = slot.positionMm.map((value) => value / 1000) as [number, number, number];
      for (let copy = 0; copy < dressing.copies; copy += 1) {
        const shift = (copy + 0.5 - dressing.copies / 2) * (w / 1000) * dressing.scale[0];
        const matrix = placementMatrix(slot.front, base, dressing.scale, shift);
        placements.push({
          key: `${String(module.stated)}:${dressing.file.sha256}`,
          lod0: piece.textured.lod0,
          lod1: piece.textured.lod1,
          matrix,
          heightM: piece.bounds[4] * dressing.scale[1],
        });
        if (captured !== null && !captureRefused) {
          const from = captured.positions.length;
          placedTriangles(piece.textured, matrix, captured);
          const count = (captured.positions.length - from) / 3;
          if (capturedVertices + count > captureLimit) {
            captured.positions.length = 0;
            captured.normals.length = 0;
            captureRefused = true;
          } else {
            capturedVertices += count;
          }
        }
        placed += 1;
      }
      if (captured !== null) capture!.triangles(slot.identity, captured.positions, captured.normals);
      continue;
    }
    // glTF axes x (width), y (height), z (depth); height's low face is the pivot itself.
    const axes: AxisPlacement[] = [
      { scale: dressing.scale[0], stretch: dressing.stretch[0], lowMm: -w / 2, boxLowMm: -bw / 2 },
      { scale: dressing.scale[1], stretch: dressing.stretch[1], lowMm: 0, boxLowMm: 0 },
      { scale: dressing.scale[2], stretch: dressing.stretch[2], lowMm: -d / 2, boxLowMm: -bd / 2 },
    ];
    // The slot's front (east, north) is the piece's +Z, and the piece's +X is (-north, east): the
    // right of a viewer facing the front.
    const [frontEast, frontNorth] = slot.front;
    const [east, north, up] = slot.positionMm.map((value) => value / 1000) as [number, number, number];
    // A draped slot's piece rises and falls with the land under each of its points.
    const under = ground === undefined || slot.drape !== true ? 0 : ground(east, -north);
    const lift = ground === undefined || slot.drape !== true ? null : (x: number, z: number): number => ground(x, z) - under;
    // Renderer metres: east, up, south.
    const toRenderer = (x: number, y: number, z: number, out: number[], offset: boolean): void => {
      const e = -x * frontNorth + z * frontEast;
      const n = x * frontEast + z * frontNorth;
      out[0] = e + (offset ? east : 0);
      out[1] = y + (offset ? up : 0);
      out[2] = -n - (offset ? north : 0);
    };
    for (let copy = 0; copy < dressing.copies; copy += 1) {
      const shift = (copy + 0.5 - dressing.copies / 2) * (w / 1000) * dressing.scale[0];
      for (const group of piece.groups) {
        device ??= group.mesh.device;
        let batch = batches.get(group.swatch);
        if (batch === undefined) {
          batch = new SwatchBatch();
          batches.set(group.swatch, batch);
        }
        const from = batch.positions.length;
        bake(group, axes, shift, toRenderer, batch, local, normal, lift);
        if (captured !== null && !captureRefused) {
          const count = (batch.positions.length - from) / 3;
          if (capturedVertices + count > captureLimit) {
            captured.positions.length = 0;
            captured.normals.length = 0;
            captureRefused = true;
            continue;
          }
          capturedVertices += count;
          for (let i = from; i < batch.positions.length; i += 1) {
            // Match the Float32 upload that the batch mesh actually draws.
            captured.positions.push(Math.fround(batch.positions[i]!));
            captured.normals.push(Math.fround(batch.normals[i]!));
          }
        }
      }
      placed += 1;
    }
    if (captured !== null) capture!.triangles(slot.identity, captured.positions, captured.normals);
  }

  const entity = new pc.Entity(`${PREFIX}pieces`);
  const materials: pc.StandardMaterial[] = [];
  const meshes: pc.Mesh[] = [];
  const instances: pc.MeshInstance[] = [];
  let triangles = 0;
  for (const [key, batch] of batches) {
    const mesh = new pc.Mesh(device!);
    mesh.setPositions(batch.positions);
    mesh.setNormals(batch.normals);
    const count = batch.positions.length / 3;
    mesh.setIndices(count > 65_535 ? Uint32Array.from({ length: count }, (_, i) => i) : Uint16Array.from({ length: count }, (_, i) => i));
    mesh.update(pc.PRIMITIVE_TRIANGLES);
    meshes.push(mesh);
    triangles += count / 3;
    const material = swatchMaterial(pack.swatches.get(key)!, null, shading, `${PREFIX}swatch:${key}`);
    materials.push(material);
    instances.push(new pc.MeshInstance(mesh, material));
  }
  if (instances.length > 0) {
    entity.addComponent('render', { meshInstances: instances, castShadows: true, receiveShadows: true });
    parent.addChild(entity);
  }

  const instanced = placements.length === 0 ? null : drawInstancedPieces(parent, placements, view ?? null);

  let disposed = false;
  return {
    placed,
    undressed,
    triangles,
    draws: instances.length,
    instanced,
    dispose() {
      if (disposed) return;
      disposed = true;
      entity.destroy();
      for (const mesh of meshes) mesh.destroy();
      for (const material of materials) material.destroy();
      instanced?.dispose();
    },
  };
}

/** One piece group's triangles, placed: each corner moved, each normal turned by its triangle's stretch. */
function bake(
  group: LoadedPieceGroup,
  axes: readonly AxisPlacement[],
  shift: number,
  toRenderer: (x: number, y: number, z: number, out: number[], offset: boolean) => void,
  batch: SwatchBatch,
  local: number[],
  normal: number[],
  lift: ((x: number, z: number) => number) | null,
): void {
  const { positions, normals, indices } = group;
  for (let t = 0; t < indices.length; t += 3) {
    // The stretch a triangle takes is the one at its centroid, so a triangle inside a zone turns its
    // normals by the zone's draw-out and one outside keeps them.
    let cx = 0;
    let cy = 0;
    let cz = 0;
    for (let k = 0; k < 3; k += 1) {
      const v = indices[t + k]!;
      cx += positions[v * 3]! / 3;
      cy += positions[v * 3 + 1]! / 3;
      cz += positions[v * 3 + 2]! / 3;
    }
    const fx = axisFactor(axes[0]!, cx);
    const fy = axisFactor(axes[1]!, cy);
    const fz = axisFactor(axes[2]!, cz);
    for (let k = 0; k < 3; k += 1) {
      const v = indices[t + k]!;
      local[0] = placeAxis(axes[0]!, positions[v * 3]!) + shift;
      local[1] = placeAxis(axes[1]!, positions[v * 3 + 1]!);
      local[2] = placeAxis(axes[2]!, positions[v * 3 + 2]!);
      toRenderer(local[0]!, local[1]!, local[2]!, normal, true);
      if (lift !== null) normal[1] = normal[1]! + lift(normal[0]!, normal[2]!);
      batch.positions.push(normal[0]!, normal[1]!, normal[2]!);
      // A normal under a stretch turns by the inverse of the draw-out on each axis.
      const nx = normals[v * 3]! / fx;
      const ny = normals[v * 3 + 1]! / fy;
      const nz = normals[v * 3 + 2]! / fz;
      const length = Math.hypot(nx, ny, nz);
      toRenderer(nx / length, ny / length, nz / length, normal, false);
      batch.normals.push(normal[0]!, normal[1]!, normal[2]!);
    }
  }
}
