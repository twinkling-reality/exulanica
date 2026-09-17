/**
 * WHAT EACH RECORD KIND BECOMES IN EACH PROJECTION THIS TESSELLATOR MATERIALISES.
 *
 * An expander is a pure function from one record's fields to integer vertices and triangles. It
 * reads the record and nothing else: no catalog, no table of roles or materials, no default. A
 * record kind whose fields do not determine its geometry has no expander. It has a statement
 * naming what it lacks, and the entry it produces is `unavailable`, never a substituted mesh.
 *
 * MEASURED against the grammar's record shapes at main 42f296bf (city stages version 1), only the
 * terrain grid is fully determined. Everything else waits on a record field the grammar does not
 * carry yet; the list below is the requirement sent to the city vocabulary lane (lane 20).
 *
 * Two projections are materialised, each from the records by its own rules and each with its own
 * representation contract: `render_batch`, what is drawn, and `nav_envelope`, what a person is
 * supported by. Navigation is never read back out of the render mesh; Melbourne failed exactly
 * there. `collision_proxy` and `pick_geometry` wait for contracts of their own.
 */
import { RECORD_SHAPES } from './record-shapes.js';
import type { ProjectionName } from './record-shapes.js';
import type { SurfaceOrientation } from './triangle-digest.js';

/**
 * Bumped whenever an expander, a statement or the materialised projection set changes, because
 * each changes the bytes a bake writes. The bake stage's parameters carry it.
 */
export const TESSELLATOR_SOURCE_VERSION = 1;

/**
 * What each materialised projection preserves and what it may be used for, as separate rows, the
 * target architecture's representation contract. The header of every container carries these, and
 * `TESSELLATOR_SOURCE_VERSION` versions them.
 */
export interface ProjectionDefinition {
  readonly name: ProjectionName;
  /** Whether drawn ranges carry a material reference, an orientation and surface coordinates. */
  readonly surfaces: boolean;
  readonly contract: {
    readonly preserves: readonly string[];
    readonly admissible_uses: readonly string[];
    readonly inadmissible_uses: readonly string[];
  };
}

export const PROJECTION_DEFINITIONS: readonly ProjectionDefinition[] = [
  {
    name: 'render_batch',
    surfaces: true,
    contract: {
      preserves: [
        'the integer vertex positions of every drawn record',
        'the record, stated identity and material reference of every triangle',
        'surface coordinates in millimetres, for texture scale from physical extent',
      ],
      admissible_uses: ['drawing'],
      inadmissible_uses: ['support height', 'collision', 'measurement'],
    },
  },
  {
    name: 'nav_envelope',
    surfaces: false,
    contract: {
      preserves: [
        'the integer vertex positions of every surface a person may be supported by',
        'support height at a plan point inside a triangle, by linear interpolation over them',
      ],
      admissible_uses: ['sampling support height'],
      inadmissible_uses: [
        'drawing',
        'collision: obstacles are not carved out of the envelope',
        'deciding walkability: no record states a slope limit, so no slope is refused',
      ],
    },
  },
];

export const MATERIALISED_PROJECTIONS: readonly ProjectionName[] = PROJECTION_DEFINITIONS.map(
  (definition) => definition.name,
);

/**
 * The only level of detail this version draws. Nothing here varies with a level of detail yet, so
 * a tile at any other level is refused rather than drawn at this one and labelled as the other.
 */
export const MATERIALISED_LOD = 0;

/**
 * What a record kind can lack, each named for the value a record would have to carry. These are
 * requirements on the grammar, not parameters of this package.
 */
export const NEEDS = {
  /** No record carries a building's footprint ring. `edge_ordinal` names edges of nothing. */
  footprint_ring: 'footprint_ring',
  /** No record says where a street, lot, building or object sits against the terrain. */
  base_elevation: 'base_elevation',
  /** The city parameter schema is empty, so a facade record carries no bay or opening layout. */
  facade_layout_parameters: 'facade_layout_parameters',
  /** A vitrine names a bay and a depth, and no record says where the bay is or how wide. */
  bay_geometry: 'bay_geometry',
  /** A street segment places crossings along its centreline and states no crossing width. */
  crossing_width: 'crossing_width',
  /** Street furniture has a position and a class key, and no extent or asset reference. */
  furniture_extent: 'furniture_extent',
  /** A terrain grid with one sample on an axis is a line, which has no surface to draw. */
  grid_with_area: 'grid_with_area',
} as const;
export type Need = (typeof NEEDS)[keyof typeof NEEDS];

export type Fields = { readonly [name: string]: unknown };

export interface SurfaceExpansion {
  /** The record kind has no material record shape, so the range binds none. */
  readonly material: 'not-carried';
  readonly orientation: SurfaceOrientation;
  /** Absolute surface coordinates in millimetres, two per vertex. */
  readonly coordinates: readonly number[];
}

export type Expansion =
  | {
      readonly state: 'drawn';
      /** Absolute integer vertices in the records' unit, three per vertex. */
      readonly vertices: readonly number[];
      /** Indices into `vertices`, three per triangle, counter-clockwise seen from +z. */
      readonly triangles: readonly number[];
      /** Present exactly when the projection carries surfaces. */
      readonly surface?: SurfaceExpansion;
    }
  | { readonly state: 'unavailable'; readonly needs: readonly Need[] };

export type Rule =
  | { readonly rule: 'expand'; readonly expand: (fields: Fields) => Expansion }
  | { readonly rule: 'needs'; readonly needs: readonly Need[] }
  | { readonly rule: 'not_in_projection' };

export class TessellationError extends Error {}

function safe(value: number, where: string): number {
  if (!Number.isSafeInteger(value)) {
    throw new TessellationError(`${where} is ${String(value)}, outside the integers a double holds`);
  }
  return value;
}

/** The smallest grid that encloses any area: two samples on each axis. */
const SAMPLES_FOR_AN_EDGE = 2;

/**
 * A terrain grid: one vertex per sample, row-major, at `origin + index * cell_mm` with the
 * sample's own height; two triangles per cell, split on the diagonal from the cell's lowest
 * corner to its highest. With x to the right and y up, both are counter-clockwise seen from +z.
 * The diagonal is a tessellation choice and is fixed by `TESSELLATOR_SOURCE_VERSION`.
 */
function terrainGrid(fields: Fields): Expansion {
  const originX = fields.origin_x_mm as number;
  const originY = fields.origin_y_mm as number;
  const cell = fields.cell_mm as number;
  const columns = fields.columns as number;
  const rows = fields.rows as number;
  const heights = fields.height_mm as readonly number[];
  if (columns < SAMPLES_FOR_AN_EDGE) return { state: 'unavailable', needs: [NEEDS.grid_with_area] };
  if (rows < SAMPLES_FOR_AN_EDGE) return { state: 'unavailable', needs: [NEEDS.grid_with_area] };
  const vertices: number[] = [];
  for (let row = 0; row < rows; row += 1) {
    const y = safe(originY + safe(row * cell, 'a terrain row offset'), 'a terrain y');
    for (let column = 0; column < columns; column += 1) {
      const x = safe(originX + safe(column * cell, 'a terrain column offset'), 'a terrain x');
      vertices.push(x, y, heights[row * columns + column]!);
    }
  }
  const triangles: number[] = [];
  for (let row = 0; row + 1 < rows; row += 1) {
    for (let column = 0; column + 1 < columns; column += 1) {
      const low = row * columns + column;
      const right = low + 1;
      const high = low + columns + 1;
      const up = low + columns;
      triangles.push(low, right, high, low, high, up);
    }
  }
  return { state: 'drawn', vertices, triangles };
}

/** Drawn terrain is a horizontal surface in the plan frame: `s = x` and `t = y`, left of `s`. */
function renderTerrain(fields: Fields): Expansion {
  const grid = terrainGrid(fields);
  if (grid.state === 'unavailable') return grid;
  const coordinates: number[] = [];
  for (let vertex = 0; vertex < grid.vertices.length; vertex += 3) {
    coordinates.push(grid.vertices[vertex]!, grid.vertices[vertex + 1]!);
  }
  return { ...grid, surface: { material: 'not-carried', orientation: 'horizontal', coordinates } };
}

/**
 * A terrain grid supports whoever stands on it, everywhere: a heightfield has one height over each
 * plan point, which is what support sampling needs. Its own rule rather than the render rule, so
 * the two projections can part when the grammar says where a surface is not walkable.
 */
function supportTerrain(fields: Fields): Expansion {
  return terrainGrid(fields);
}

const needs = (...list: Need[]): Rule => ({ rule: 'needs', needs: list });
const notInProjection: Rule = { rule: 'not_in_projection' };

/** `render_batch`, per record kind. Every kind in `RECORD_SHAPES` has exactly one rule. */
const RENDER_BATCH: ReadonlyMap<string, Rule> = new Map<string, Rule>([
  ['city.curb_edge', needs(NEEDS.base_elevation)],
  ['city.facade', needs(NEEDS.footprint_ring, NEEDS.base_elevation, NEEDS.facade_layout_parameters)],
  ['city.massing', needs(NEEDS.footprint_ring, NEEDS.base_elevation)],
  ['city.parcel', needs(NEEDS.base_elevation)],
  ['city.premises', needs(NEEDS.footprint_ring, NEEDS.base_elevation, NEEDS.facade_layout_parameters)],
  ['city.street_furniture', needs(NEEDS.base_elevation, NEEDS.furniture_extent)],
  ['city.street_node', needs(NEEDS.base_elevation)],
  ['city.street_segment', needs(NEEDS.base_elevation, NEEDS.crossing_width)],
  // A material is not a surface. A drawn range cites it; it draws nothing of its own.
  ['city.surface_material', notInProjection],
  ['city.terrain', { rule: 'expand', expand: renderTerrain }],
  ['city.vitrine', needs(NEEDS.footprint_ring, NEEDS.base_elevation, NEEDS.bay_geometry)],
]);

/**
 * `nav_envelope`, per record kind. A facade, a vitrine behind glass, a sign and a material support
 * nobody. Street furniture is an obstacle, which is collision's concern, not support's.
 */
const NAV_ENVELOPE: ReadonlyMap<string, Rule> = new Map<string, Rule>([
  ['city.curb_edge', needs(NEEDS.base_elevation)],
  ['city.facade', notInProjection],
  ['city.massing', needs(NEEDS.footprint_ring, NEEDS.base_elevation)],
  ['city.parcel', needs(NEEDS.base_elevation)],
  ['city.premises', notInProjection],
  ['city.street_furniture', notInProjection],
  ['city.street_node', needs(NEEDS.base_elevation)],
  ['city.street_segment', needs(NEEDS.base_elevation, NEEDS.crossing_width)],
  ['city.surface_material', notInProjection],
  ['city.terrain', { rule: 'expand', expand: supportTerrain }],
  ['city.vitrine', notInProjection],
]);

const RULES: ReadonlyMap<ProjectionName, ReadonlyMap<string, Rule>> = new Map([
  ['render_batch', RENDER_BATCH],
  ['nav_envelope', NAV_ENVELOPE],
]);

/** The rule for one record kind in one materialised projection. */
export function ruleFor(projection: ProjectionName, kind: string): Rule {
  const table = RULES.get(projection);
  if (table === undefined) throw new TessellationError(`${projection} is not materialised`);
  const rule = table.get(kind);
  if (rule === undefined) throw new TessellationError(`${projection} has no rule for ${kind}`);
  return rule;
}

// Held at load, so a record kind added to the shapes without a rule cannot be baked at all.
for (const projection of MATERIALISED_PROJECTIONS) {
  for (const shape of RECORD_SHAPES) ruleFor(projection, shape.kind);
}
