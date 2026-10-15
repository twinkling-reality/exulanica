import * as pc from 'playcanvas';
import { PIECE_DRAWING_DEFAULTS, type PieceDrawing } from '@exulanica/atlas-core';
import type { LoadedTexturedPrimitive } from './pieces.js';

/**
 * Textured pieces drawn instanced, in cells, each cell at one level of detail.
 *
 * The dresser hands each placed textured piece over as a placement: the piece's levels (uploaded by
 * `pieces.ts`), the matrix that stands it in its slot (the same transform the bake applies to a
 * palette piece's corners) and its height as placed. Placements of one piece are gathered into
 * square cells of the ground (`cellSizeM`); a cell holds its placements' matrices and, for each level
 * and each primitive, one mesh instance drawing its own instance buffer of them, culled by the cell's
 * own bounds in the camera and in every shadow cascade.
 *
 * Each mesh instance has its own instance buffer, a copy of the cell's matrices (64 bytes a placement
 * for each primitive of each level), because the engine (PlayCanvas 2.21) keeps an instanced draw's
 * vertex array under a key that adds each vertex buffer's id to its format's number rather than
 * joining them. Two primitives uploaded one after the other with neighbouring formats, such as a made
 * tree's far bark and far leaves, sum alike; drawing one instance buffer, both draws took one key, and
 * the leaves drew the bark's vertices, which drew nothing. With an instance buffer of its own, no two
 * draws share the key's second part; a clash then needs two keys whose decimal parts split differently
 * (such as 22 and 1305 against 221 and 305), which only a fix in the engine removes.
 *
 * A cell draws its first level until the camera stands farther from it than `lod1BeyondPerMetre`
 * metres for each metre of its tallest placed piece, then its second level (where the piece has
 * one), and goes back only once the camera is `hysteresisPermille` nearer than that again. Only the
 * first level casts shadows, and only within `shadowReachM` of the camera. Choosing a level flips the
 * visibility and shadow flags of mesh instances made once; nothing is allocated or uploaded while the
 * camera moves.
 *
 * Positions are the parent's frame, renderer metres (east, up, south), as the bake's are.
 */

/** One textured piece standing in a slot: its levels, where it stands, and how tall it stands. */
export interface InstancePlacement {
  /** The piece, by the key the library holds it under: its cells are its own. */
  readonly key: string;
  readonly lod0: readonly LoadedTexturedPrimitive[];
  readonly lod1: readonly LoadedTexturedPrimitive[] | null;
  /** Column-major 4 by 4, the parent's frame: the piece's glTF metres to renderer metres. */
  readonly matrix: Float32Array;
  /** Its height as placed, metres. */
  readonly heightM: number;
}

/** Where the camera is, for choosing levels; none draws every cell at its first level. */
export interface InstancedView {
  readonly app: pc.AppBase;
  readonly camera: pc.Entity;
  readonly drawing?: PieceDrawing;
}

export interface InstancedDressing {
  readonly cells: number;
  readonly instances: number;
  /** Mesh instances drawn now at each level. */
  readonly drawsAtLevel: readonly [number, number];
  /** Triangles drawn now, counting every instance. */
  readonly triangles: number;
  /** Choose each cell's level for where the camera stands now. */
  update(): void;
  dispose(): void;
}

interface Cell {
  readonly entity: pc.Entity;
  readonly buffers: pc.VertexBuffer[];
  readonly count: number;
  readonly lod0: pc.MeshInstance[];
  readonly lod1: pc.MeshInstance[];
  readonly aabb: pc.BoundingBox;
  readonly tallestM: number;
  readonly triangles0: number;
  readonly triangles1: number;
  level: 0 | 1;
  casting: boolean;
}

const PREFIX = 'style-pack:instanced:';

/** The bounds of a level's positions, metres, glTF axes. */
function levelBounds(level: readonly LoadedTexturedPrimitive[]): [number, number, number, number, number, number] {
  const out: [number, number, number, number, number, number] = [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity];
  for (const primitive of level) {
    const p = primitive.positions;
    for (let i = 0; i < p.length; i += 3) {
      for (let k = 0; k < 3; k += 1) {
        out[k] = Math.min(out[k]!, p[i + k]!);
        out[k + 3] = Math.max(out[k + 3]!, p[i + k]!);
      }
    }
  }
  return out;
}

/** Grow `into` by the box `bounds` (glTF metres) carried by the column-major `matrix`. */
export function growByPlaced(into: { min: number[]; max: number[] }, bounds: readonly number[], matrix: Float32Array): void {
  for (let corner = 0; corner < 8; corner += 1) {
    const x = corner & 1 ? bounds[3]! : bounds[0]!;
    const y = corner & 2 ? bounds[4]! : bounds[1]!;
    const z = corner & 4 ? bounds[5]! : bounds[2]!;
    for (let k = 0; k < 3; k += 1) {
      const v = matrix[k]! * x + matrix[4 + k]! * y + matrix[8 + k]! * z + matrix[12 + k]!;
      into.min[k] = Math.min(into.min[k]!, v);
      into.max[k] = Math.max(into.max[k]!, v);
    }
  }
}

/** Distance from a point to a box, 0 inside it. */
function distanceToBox(aabb: pc.BoundingBox, x: number, y: number, z: number): number {
  const min = aabb.getMin();
  const max = aabb.getMax();
  const dx = Math.max(min.x - x, 0, x - max.x);
  const dy = Math.max(min.y - y, 0, y - max.y);
  const dz = Math.max(min.z - z, 0, z - max.z);
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

const triangleCount = (level: readonly LoadedTexturedPrimitive[]): number => level.reduce((sum, primitive) => sum + primitive.indices.length / 3, 0);

/** Draw `placements` under `parent`, in cells, choosing levels from `view`'s camera. */
export function drawInstancedPieces(parent: pc.Entity, placements: readonly InstancePlacement[], view: InstancedView | null): InstancedDressing {
  const drawing = view?.drawing ?? PIECE_DRAWING_DEFAULTS;
  const groups = new Map<string, InstancePlacement[]>();
  for (const placement of placements) {
    const x = placement.matrix[12]!;
    const z = placement.matrix[14]!;
    const key = `${placement.key}|${String(Math.floor(x / drawing.cellSizeM))}|${String(Math.floor(z / drawing.cellSizeM))}`;
    let group = groups.get(key);
    if (group === undefined) {
      group = [];
      groups.set(key, group);
    }
    group.push(placement);
  }
  const root = new pc.Entity(`${PREFIX}pieces`);
  const cells: Cell[] = [];
  for (const [key, group] of groups) {
    const first = group[0]!;
    const owner = first.lod0[0]!.mesh.device;
    const format = pc.VertexFormat.getDefaultInstancingFormat(owner);
    const data = new Float32Array(group.length * 16);
    group.forEach((placement, index) => data.set(placement.matrix, index * 16));
    const buffers: pc.VertexBuffer[] = [];
    const box = { min: [Infinity, Infinity, Infinity], max: [-Infinity, -Infinity, -Infinity] };
    const bounds0 = levelBounds(first.lod0);
    const bounds1 = first.lod1 === null ? null : levelBounds(first.lod1);
    for (const placement of group) {
      growByPlaced(box, bounds0, placement.matrix);
      if (bounds1 !== null) growByPlaced(box, bounds1, placement.matrix);
    }
    const aabb = new pc.BoundingBox();
    aabb.setMinMax(new pc.Vec3(box.min[0], box.min[1], box.min[2]), new pc.Vec3(box.max[0], box.max[1], box.max[2]));
    const instances = (level: readonly LoadedTexturedPrimitive[] | null): pc.MeshInstance[] => (level ?? []).map((primitive) => {
      const buffer = new pc.VertexBuffer(owner, format, group.length, { data: data.slice().buffer });
      buffers.push(buffer);
      const instance = new pc.MeshInstance(primitive.mesh, primitive.material);
      instance.setInstancing(buffer, true);
      return instance;
    });
    const lod0 = instances(first.lod0);
    const lod1 = instances(first.lod1);
    const entity = new pc.Entity(`${PREFIX}${key}`);
    // Every mesh instance joins the layer's shadow casters once; the flags below then say which cast.
    entity.addComponent('render', { meshInstances: [...lod0, ...lod1], castShadows: true, receiveShadows: true });
    // The cell's bounds, set on the component: it gives them to each of its mesh instances, and would
    // clear any one of them set alone.
    entity.render!.customAabb = aabb;
    for (const instance of lod1) {
      instance.visible = false;
      instance.castShadow = false;
    }
    root.addChild(entity);
    cells.push({
      entity, buffers, count: group.length, lod0, lod1, aabb,
      tallestM: Math.max(...group.map((placement) => placement.heightM)),
      triangles0: triangleCount(first.lod0) * group.length,
      triangles1: first.lod1 === null ? 0 : triangleCount(first.lod1) * group.length,
      level: 0, casting: true,
    });
  }
  parent.addChild(root);

  const inverse = new pc.Mat4();
  const at = new pc.Vec3();
  const update = (): void => {
    if (view === null) return;
    inverse.copy(parent.getWorldTransform()).invert();
    inverse.transformPoint(view.camera.getPosition(), at);
    const back = 1 - drawing.hysteresisPermille / 1000;
    for (const cell of cells) {
      const distance = distanceToBox(cell.aabb, at.x, at.y, at.z);
      const beyond = drawing.lod1BeyondPerMetre * cell.tallestM;
      const level: 0 | 1 = cell.lod1.length === 0 ? 0 : cell.level === 0 ? (distance > beyond ? 1 : 0) : distance < beyond * back ? 0 : 1;
      const casting = level === 0 && distance <= drawing.shadowReachM;
      if (level !== cell.level) {
        for (const instance of cell.lod0) instance.visible = level === 0;
        for (const instance of cell.lod1) instance.visible = level === 1;
        cell.level = level;
      }
      if (casting !== cell.casting) {
        for (const instance of cell.lod0) instance.castShadow = casting;
        if (casting) {
          // A caster that left the layer's list while it did not cast (its entity hidden meanwhile) joins again.
          for (const layer of cell.entity.render!.layers) view.app.scene.layers.getLayerById(layer)?.addShadowCasters(cell.lod0);
        }
        cell.casting = casting;
      }
    }
  };
  view?.app.on('update', update);
  update();

  let disposed = false;
  return {
    cells: cells.length,
    instances: placements.length,
    get drawsAtLevel(): readonly [number, number] {
      let zero = 0;
      let one = 0;
      for (const cell of cells) {
        if (cell.level === 0) zero += cell.lod0.length;
        else one += cell.lod1.length;
      }
      return [zero, one];
    },
    get triangles() {
      return cells.reduce((sum, cell) => sum + (cell.level === 0 ? cell.triangles0 : cell.triangles1), 0);
    },
    update,
    dispose() {
      if (disposed) return;
      disposed = true;
      view?.app.off('update', update);
      // Destroying the entities destroys their mesh instances; the meshes are the library's.
      root.destroy();
      for (const cell of cells) for (const buffer of cell.buffers) buffer.destroy();
      cells.length = 0;
    },
  };
}
