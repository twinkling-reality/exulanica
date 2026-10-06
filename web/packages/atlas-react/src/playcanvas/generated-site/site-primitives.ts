import * as pc from 'playcanvas';
import type { SiteDrawing, SiteSlot } from './site-drawing.js';

/**
 * A site world's slots drawn as the engine's own primitives, in the engine's own colours.
 *
 * Every slot of the drawing states its primitive: a `plane` for a ground, path, area or floor, a
 * `box` for a wall piece, a lintel, a flat roof's slab or a fixture, a `gable` for a pitched roof,
 * and `none` for a slot only a style pack fills (a door left open, a whole structure's module). A
 * plane lies at the slot's base, a box stands on it and a gable rises from it, each turned by the
 * slot's quarter turns counterclockwise seen from above: a slot facing north turns 0, west 1, south
 * 2 and east 3. The site's x east, y north and z up are the renderer's x, -z and y, so a quarter
 * turn is 90 degrees about the renderer's up axis.
 *
 * The colour is the fallback a pack replaces: one per look family, and for a ground or an area one
 * of a few materials its leaf names (soil, crops, gravel, paving, timber), so a field reads apart
 * from the yard round it. The colours decide nothing about a pack's look.
 */

const MILLIMETRES = 1000;
type Rgb = readonly [number, number, number];

/** One colour per look family, in sRGB, for a slot no pack dresses. */
const FAMILY_RGB: Readonly<Record<string, Rgb>> = Object.freeze({
  animal: [0.62, 0.52, 0.42],
  boundary: [0.55, 0.45, 0.33],
  character: [0.6, 0.6, 0.6],
  door: [0.45, 0.32, 0.22],
  fixture: [0.58, 0.44, 0.3],
  ground: [0.47, 0.56, 0.33],
  path: [0.68, 0.64, 0.56],
  plant: [0.3, 0.48, 0.25],
  prop: [0.7, 0.62, 0.4],
  road: [0.36, 0.36, 0.37],
  roof: [0.55, 0.3, 0.24],
  structure: [0.8, 0.76, 0.68],
  vehicle: [0.8, 0.62, 0.18],
  wall: [0.85, 0.82, 0.75],
  water: [0.24, 0.42, 0.55],
  window: [0.55, 0.68, 0.76],
});
/** A ground indoors is a floor. */
const INDOOR_GROUND_RGB: Rgb = [0.66, 0.55, 0.42];
/** Materials a ground's, a path's or a road's leaf may name, by a word in it, checked in order. */
const MATERIAL_WORDS: readonly (readonly [readonly string[], Rgb])[] = Object.freeze([
  [['soil', 'earth', 'dirt', 'mud', 'plough', 'tilled', 'bare'], [0.48, 0.37, 0.26]],
  [['wheat', 'barley', 'hay', 'straw', 'corn', 'grain', 'crop', 'stubble'], [0.8, 0.7, 0.4]],
  [['grass', 'lawn', 'meadow', 'pasture', 'paddock', 'green'], [0.44, 0.58, 0.3]],
  [['gravel', 'sand', 'aggregate', 'hardcore'], [0.74, 0.68, 0.55]],
  [['concrete', 'cement', 'slab', 'paving', 'paved', 'flag', 'tarmac', 'asphalt'], [0.64, 0.64, 0.62]],
  [['brick'], [0.62, 0.34, 0.26]],
  [['timber', 'wood', 'plank', 'board', 'deck', 'parquet'], [0.62, 0.48, 0.33]],
  [['tile', 'stone', 'terrazzo', 'marble'], [0.76, 0.74, 0.7]],
]);
const SURFACE_FAMILIES = new Set(['ground', 'path', 'road']);

/** The colour a slot is drawn in when no pack dresses it. */
export function slotColour(slot: SiteSlot, enclosure: SiteDrawing['extent']['enclosure']): Rgb {
  if (SURFACE_FAMILIES.has(slot.family)) {
    const words = slot.leaf.split('_');
    for (const [names, rgb] of MATERIAL_WORDS) {
      if (words.some((word) => names.includes(word))) return rgb;
    }
    if (slot.family === 'ground' && enclosure === 'indoor') return INDOOR_GROUND_RGB;
  }
  return FAMILY_RGB[slot.family] ?? FAMILY_RGB['prop']!;
}

/** A triangular prism under a gable: its ridge along the slot's width, its span its depth. */
function gableMesh(device: pc.GraphicsDevice): pc.Mesh {
  // Unit prism: x from -0.5 to 0.5, z (depth) from -0.5 to 0.5, ridge at y = 1 over z = 0.
  const positions: number[] = [];
  const normals: number[] = [];
  const indices: number[] = [];
  const face = (corners: readonly (readonly [number, number, number])[], normal: readonly [number, number, number]) => {
    const base = positions.length / 3;
    for (const corner of corners) {
      positions.push(...corner);
      normals.push(...normal);
    }
    for (let i = 1; i + 1 < corners.length; i += 1) indices.push(base, base + i, base + i + 1);
  };
  const slope = Math.hypot(0.5, 1);
  face([[-0.5, 0, 0.5], [0.5, 0, 0.5], [0.5, 1, 0], [-0.5, 1, 0]], [0, 0.5 / slope, 1 / slope]);
  face([[0.5, 0, -0.5], [-0.5, 0, -0.5], [-0.5, 1, 0], [0.5, 1, 0]], [0, 0.5 / slope, -1 / slope]);
  face([[-0.5, 0, -0.5], [-0.5, 0, 0.5], [-0.5, 1, 0]], [-1, 0, 0]);
  face([[0.5, 0, 0.5], [0.5, 0, -0.5], [0.5, 1, 0]], [1, 0, 0]);
  face([[-0.5, 0, -0.5], [0.5, 0, -0.5], [0.5, 0, 0.5], [-0.5, 0, 0.5]], [0, -1, 0]);
  const mesh = new pc.Mesh(device);
  mesh.setPositions(positions);
  mesh.setNormals(normals);
  mesh.setIndices(indices);
  mesh.update();
  return mesh;
}

/** What drawing a site's slots put in the scene: their root, counts and how to take them away. */
export interface DrawnSiteSlots {
  readonly root: pc.Entity;
  /**
   * Each drawn slot's entity by the slot's identity: the entity at the slot's base, turned by its
   * quarter turns, whose one child (`<identity>:shape`) holds the primitive. A `none` slot has
   * none. The drawing owns these entities; a dresser may disable one or give its shape another
   * material instance, and puts back what it changed when its disposer runs.
   */
  readonly entities: ReadonlyMap<string, pc.Entity>;
  /** Slots drawn as an entity; a `none` slot draws nothing and is not counted. */
  readonly drawn: number;
  readonly triangles: number;
  destroy(): void;
}

/** Draw every slot of a site under a new root, at the site's origin in the renderer's frame. */
export function drawSiteSlots(device: pc.GraphicsDevice, drawing: SiteDrawing): DrawnSiteSlots {
  const root = new pc.Entity(`generated-site:${drawing.worldId}`);
  const materials = new Map<string, pc.StandardMaterial>();
  const material = (rgb: Rgb): pc.StandardMaterial => {
    const key = rgb.join(',');
    const held = materials.get(key);
    if (held !== undefined) return held;
    const made = new pc.StandardMaterial();
    made.name = `generated-site-colour:${key}`;
    made.diffuse = new pc.Color(rgb[0], rgb[1], rgb[2]);
    made.gloss = 0.2;
    made.useMetalness = true;
    made.metalness = 0;
    made.update();
    materials.set(key, made);
    return made;
  };
  let gable: pc.Mesh | null = null;
  const entities = new Map<string, pc.Entity>();
  let drawn = 0;
  let triangles = 0;
  for (const slot of drawing.slots) {
    if (slot.primitive === 'none') continue;
    const [x, y, z] = slot.positionMm;
    const [width, depth, height] = slot.boxMm.map((v) => v / MILLIMETRES) as unknown as [number, number, number];
    const entity = new pc.Entity(slot.identity);
    entity.setLocalPosition(x / MILLIMETRES, z / MILLIMETRES, -y / MILLIMETRES);
    entity.setLocalEulerAngles(0, 90 * slot.yawQuarterTurns, 0);
    const shape = new pc.Entity(`${slot.identity}:shape`);
    const colour = material(slotColour(slot, drawing.extent.enclosure));
    if (slot.primitive === 'plane') {
      shape.addComponent('render', { type: 'plane', material: colour, castShadows: false });
      shape.setLocalScale(width, 1, depth);
      triangles += 2;
    } else if (slot.primitive === 'box') {
      shape.addComponent('render', { type: 'box', material: colour, castShadows: true });
      shape.setLocalPosition(0, height / 2, 0);
      shape.setLocalScale(width, height, depth);
      triangles += 12;
    } else {
      gable ??= gableMesh(device);
      const instance = new pc.MeshInstance(gable, colour);
      shape.addComponent('render', { meshInstances: [instance], castShadows: true });
      shape.setLocalScale(width, height, depth);
      triangles += 8;
    }
    entity.addChild(shape);
    root.addChild(entity);
    entities.set(slot.identity, entity);
    drawn += 1;
  }
  let destroyed = false;
  return {
    root,
    entities,
    drawn,
    triangles,
    destroy(): void {
      if (destroyed) return;
      destroyed = true;
      root.destroy();
      for (const made of materials.values()) made.destroy();
      gable?.destroy();
    },
  };
}
