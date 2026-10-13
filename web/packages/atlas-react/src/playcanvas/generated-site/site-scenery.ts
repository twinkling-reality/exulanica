import * as pc from 'playcanvas';
import {
  materialOfLeaf, sceneryBeyond,
  type SceneryPiece, type SiteScenery, type SiteSceneryCatalog, type SurfaceMaterials,
} from '@exulanica/atlas-core';
import type { StructuredSiteDrawing, SiteSlot } from './site-drawing.js';

/**
 * The scenery beyond a made place, drawn: trees and stones on the ground past the place's rectangle
 * (`site-scenery.ts` in atlas-core states what stands beyond which ground and where).
 *
 * IT IS SCENERY, LIKE THE HORIZON, AND NO PART OF THE WORLD. It is made here from the drawing's base
 * ground and the world's identity and is never a slot of the drawing: it is not listed, not walked
 * (the walk is the drawing's own), not picked (a click meets the world's things and people, never a
 * mesh), and it hides nobody (what hides a being is read from the drawing's slots). Taking it away
 * changes no fact of the place.
 *
 * Everything of one kind is one mesh, so a wood is a draw or two and not a draw a tree: all trunks,
 * all crowns, all stones. Each stands under an entity named as a slot's is (`<name>` holding
 * `<name>:shape`), so a look's dresser shades them as it shades any plain shape, or stands its own
 * tree piece at each tree and hides the plain ones.
 */

/** The entities the plain scenery is drawn under, by what stands. */
export const SCENERY_TREES = 'site-scenery:trees';
export const SCENERY_STONES = 'site-scenery:stones';

type Rgb = readonly [number, number, number];

/** A plain tree's trunk and crown and a stone, in the colours of these surface materials. */
const TRUNK_MATERIAL = 'timber';
const CROWN_MATERIAL = 'grass';
const STONE_MATERIAL = 'stone';
/** A crown's colour is its material's, darkened: leaves in a mass are darker than a lawn. */
const CROWN_SHADE = 0.72;
/** Where no catalog names the materials: the engine's own bark, leaf and stone. */
const PLAIN_RGB: Readonly<Record<'trunk' | 'crown' | 'stone', Rgb>> = { trunk: [0.42, 0.33, 0.25], crown: [0.27, 0.38, 0.2], stone: [0.58, 0.57, 0.54] };
/** A plain tree: its trunk's height and half width as shares of the tree's, and where its crown begins. */
const TRUNK_HEIGHT = 0.38;
const TRUNK_HALF_WIDTH = 0.045;
const CROWN_FROM = 0.3;
/** A stone lies a little in the ground: this share of its height is under it. */
const STONE_SUNK = 0.22;

export interface DrawnScenery {
  /** The pieces, nearest the place first, in site millimetres. */
  readonly pieces: readonly SceneryPiece[];
  /** What stands, and the material of the base ground it stands beyond. */
  readonly stands: SiteScenery['stands'];
  readonly material: string;
  /** Holds `SCENERY_TREES` or `SCENERY_STONES`, whichever is drawn. */
  readonly root: pc.Entity;
  readonly triangles: number;
  destroy(): void;
}

/**
 * The scenery a drawing's place has: what the catalog states for the material of its base ground
 * (`base`, the ground its drawing lays over its whole extent: `baseGroundSlot`), or null for an
 * indoor place, a place that lays no such ground, a ground whose leaf names no material, and a
 * material with no entry.
 */
export function sceneryOf(
  drawing: StructuredSiteDrawing, base: SiteSlot | null, catalog: SiteSceneryCatalog, materials: SurfaceMaterials,
): { readonly scenery: SiteScenery; readonly pieces: SceneryPiece[] } | null {
  if (drawing.extent.enclosure !== 'open') return null;
  const material = base === null ? null : materialOfLeaf(materials, base.family, base.leaf);
  const scenery = material === null ? undefined : catalog.byMaterial.get(material.key);
  if (scenery === undefined) return null;
  return { scenery, pieces: sceneryBeyond(drawing.worldId, drawing.extent, scenery) };
}

/** Triangles gathered into one mesh. */
class Gathered {
  readonly positions: number[] = [];
  readonly normals: number[] = [];
  readonly indices: number[] = [];

  /** A unit shape's triangles, each point scaled, turned about the vertical and moved. */
  add(shape: pc.Geometry, scale: readonly [number, number, number], quarterTurns: number, at: readonly [number, number, number]): void {
    const first = this.positions.length / 3;
    const cos = [1, 0, -1, 0][quarterTurns]!, sin = [0, 1, 0, -1][quarterTurns]!;
    const positions = shape.positions!, normals = shape.normals!;
    for (let i = 0; i < positions.length; i += 3) {
      const x = positions[i]! * scale[0], y = positions[i + 1]! * scale[1], z = positions[i + 2]! * scale[2];
      this.positions.push(at[0] + x * cos + z * sin, at[1] + y, at[2] - x * sin + z * cos);
      // A normal is carried by the inverse of the scale, then turned as the point is.
      const nx = normals[i]! / scale[0], ny = normals[i + 1]! / scale[1], nz = normals[i + 2]! / scale[2];
      const length = Math.hypot(nx, ny, nz) || 1;
      this.normals.push((nx * cos + nz * sin) / length, ny / length, (-nx * sin + nz * cos) / length);
    }
    for (const index of shape.indices!) this.indices.push(first + index);
  }

  mesh(device: pc.GraphicsDevice): pc.Mesh {
    const geometry = new pc.Geometry();
    geometry.positions = this.positions;
    geometry.normals = this.normals;
    geometry.indices = this.indices;
    return pc.Mesh.fromGeometry(device, geometry);
  }
}

/**
 * Draw scenery as plain shapes under a new root, in the renderer's frame (east, up, south; a site's
 * y is north). `materials` names the colours; with none, the engine's own.
 */
export function drawSiteScenery(
  device: pc.GraphicsDevice, drawn: { readonly scenery: SiteScenery; readonly pieces: readonly SceneryPiece[] },
  materials: SurfaceMaterials | null,
): DrawnScenery {
  const { scenery, pieces } = drawn;
  const root = new pc.Entity('site-scenery');
  const made: pc.StandardMaterial[] = [];
  const meshes: pc.Mesh[] = [];
  const colourOf = (key: string, fallback: Rgb, shade = 1): Rgb => {
    const stated = materials?.materials.find((material) => material.key === key)?.swatch.srgb8;
    const [r, g, b] = stated === undefined ? fallback : [stated[0] / 255, stated[1] / 255, stated[2] / 255];
    return [r * shade, g * shade, b * shade];
  };
  const material = (name: string, rgb: Rgb): pc.StandardMaterial => {
    const one = new pc.StandardMaterial();
    one.name = `site-scenery-colour:${name}`;
    one.diffuse = new pc.Color(rgb[0], rgb[1], rgb[2]);
    one.gloss = 0.2;
    one.useMetalness = true;
    one.metalness = 0;
    one.update();
    made.push(one);
    return one;
  };
  let triangles = 0;
  const shaped = (name: string, parts: readonly (readonly [Gathered, pc.StandardMaterial])[]): void => {
    const entity = new pc.Entity(name);
    const shape = new pc.Entity(`${name}:shape`);
    const instances = parts.map(([gathered, colour]) => {
      const mesh = gathered.mesh(device);
      meshes.push(mesh);
      triangles += gathered.indices.length / 3;
      return new pc.MeshInstance(mesh, colour);
    });
    shape.addComponent('render', { meshInstances: instances, castShadows: true, receiveShadows: true });
    entity.addChild(shape);
    root.addChild(entity);
  };
  if (scenery.stands === 'tree') {
    // A unit trunk (a six sided post one high about the vertical) and a unit crown (a cone one high).
    const post = new pc.CylinderGeometry({ radius: 1, height: 1, heightSegments: 1, capSegments: 6 });
    const cone = new pc.ConeGeometry({ baseRadius: 1, peakRadius: 0, height: 1, heightSegments: 1, capSegments: 7 });
    const trunks = new Gathered(), crowns = new Gathered();
    for (const piece of pieces) {
      const x = piece.xMm / 1000, z = -piece.yMm / 1000, tall = piece.heightMm / 1000, wide = piece.widthMm / 1000;
      const trunk = tall * TRUNK_HEIGHT, crown = tall * (1 - CROWN_FROM);
      // Both unit shapes stand about their own middle.
      trunks.add(post, [tall * TRUNK_HALF_WIDTH, trunk, tall * TRUNK_HALF_WIDTH], piece.quarterTurns, [x, trunk / 2, z]);
      crowns.add(cone, [wide / 2, crown, wide / 2], piece.quarterTurns, [x, tall * CROWN_FROM + crown / 2, z]);
    }
    shaped(SCENERY_TREES, [
      [trunks, material('trunk', colourOf(TRUNK_MATERIAL, PLAIN_RGB.trunk))],
      [crowns, material('crown', colourOf(CROWN_MATERIAL, PLAIN_RGB.crown, CROWN_SHADE))],
    ]);
  } else {
    // A unit stone: a ball of few faces, squashed to the piece's width and height and sunk a little.
    const ball = new pc.SphereGeometry({ radius: 0.5, latitudeBands: 4, longitudeBands: 7 });
    const stones = new Gathered();
    for (const piece of pieces) {
      const tall = piece.heightMm / 1000 / (1 - STONE_SUNK), wide = piece.widthMm / 1000;
      // Every other stone is narrower one way, so no two read as the same ball.
      const narrow = piece.quarterTurns % 2 === 0 ? 0.7 : 1;
      stones.add(ball, [wide, tall, wide * narrow], piece.quarterTurns, [piece.xMm / 1000, tall * (0.5 - STONE_SUNK), -piece.yMm / 1000]);
    }
    shaped(SCENERY_STONES, [[stones, material('stone', colourOf(STONE_MATERIAL, PLAIN_RGB.stone))]]);
  }
  return {
    pieces, stands: scenery.stands, material: scenery.key, root, triangles,
    destroy(): void {
      root.destroy();
      for (const mesh of meshes) mesh.destroy();
      for (const one of made) one.destroy();
    },
  };
}
