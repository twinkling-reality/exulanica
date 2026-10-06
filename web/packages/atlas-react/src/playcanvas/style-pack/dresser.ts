import * as pc from 'playcanvas';
import { resolveLookRole, stretchCoordinate, type AxisStretch, type LookFamily, type ResolvedStylePack } from '@exulanica/atlas-core';
import type { RenderShading } from '../generated-tile/look.js';
import type { LoadedPieceGroup, PackPieces } from './pieces.js';
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
}

export interface SlotDressing {
  /** Pieces placed. A tiled slot places one per copy. */
  readonly placed: number;
  readonly undressed: readonly string[];
  readonly triangles: number;
  readonly draws: number;
  dispose(): void;
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
): SlotDressing {
  const batches = new Map<string, SwatchBatch>();
  const undressed: string[] = [];
  let placed = 0;
  let device: pc.GraphicsDevice | null = null;
  const local = [0, 0, 0];
  const normal = [0, 0, 0];
  for (const slot of slots) {
    const dressing = resolveLookRole(pack, { identity: slot.identity, lookRole: slot.lookRole, positionMm: slot.positionMm, yawQuarterTurns: 0, boxMm: slot.boxMm }, families, 'module');
    const module = dressing?.kind === 'module' ? pack.modules[dressing.role] : undefined;
    const piece = dressing?.kind === 'module' && module !== undefined ? pieces.get(module, dressing.file) : undefined;
    if (dressing?.kind !== 'module' || module === undefined || piece === undefined) {
      undressed.push(slot.identity);
      continue;
    }
    const [w, d] = module.variants[dressing.variant]!.size_mm;
    const [bw, bd] = slot.boxMm;
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
        bake(group, axes, shift, toRenderer, batch, local, normal);
      }
      placed += 1;
    }
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

  let disposed = false;
  return {
    placed,
    undressed,
    triangles,
    draws: instances.length,
    dispose() {
      if (disposed) return;
      disposed = true;
      entity.destroy();
      for (const mesh of meshes) mesh.destroy();
      for (const material of materials) material.destroy();
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
