/**
 * WHAT EACH RECORD KIND BECOMES IN EACH PROJECTION THIS TESSELLATOR MATERIALISES.
 *
 * An expander is a pure function from one record's fields to integer vertices and triangles. It
 * reads the record and the tile it is baked in, and nothing else: no catalog, no table of roles or
 * materials, no default. A record kind with no expander has a statement naming the rule it waits
 * on, and the entry it produces is `unavailable`, never a substituted mesh.
 *
 * MEASURED against city grammar version 2 (lane 20's records at 87865940), the records now carry
 * what every surface needs: footprints, tiers, elevations, facade layouts, kerb lines, crossing
 * widths, form parts with facing vectors and identities. What is missing is on this side: the
 * integer rules that expand them, each declared and versioned here as it is built. This version
 * builds one, the terrain grid, because it is exact with no new rule; everything else states the
 * rule it waits on (`NEEDS`).
 *
 * Two projections are materialised, each from the records by its own rules and each with its own
 * representation contract: `render_batch`, what is drawn, and `nav_envelope`, what a person is
 * supported by. Navigation is never read back out of the render mesh; Melbourne failed exactly
 * there. `collision_proxy` and `pick_geometry` wait for contracts of their own.
 */
import { GRAMMAR_TABLES, recordShapeOf, TILE_RECORD_KIND } from './record-shapes.js';
import type { ProjectionName } from './record-shapes.js';
import type { SurfaceOrientation } from './triangle-digest.js';

/**
 * Bumped whenever an expander, a statement, a contract or the materialised projection set
 * changes, because each changes the bytes a bake writes. The bake stage's parameters carry it.
 */
export const TESSELLATOR_SOURCE_VERSION = 2;

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
        'the record, stated identity and dressing material record of every triangle',
        'surface coordinates in millimetres, in the surface frame the grammar fixes',
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
        'the integer vertex positions of every surface this version draws that a person may be supported by',
        'support height at a plan point inside a triangle, by linear interpolation over them',
      ],
      admissible_uses: ['sampling support height'],
      inadmissible_uses: [
        'drawing',
        'collision: obstacles are not carved out of the envelope',
        'capsule clearance: no clearance is carved or checked',
        'deciding walkability: no record states a slope limit, so no slope is refused',
        'deciding that a plan point has no support: a terrain cell whose closed plan square meets the '
          + 'stated extent of a record that covers the ground is left out until that record is drawn',
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
 * Why an entry is unavailable, each named for what would have to exist. The first is a fact about
 * a tile's records; the rest are integer rules this package has not built yet, which the records
 * already carry enough for.
 */
export const NEEDS = {
  /** No surface material record dresses the surface. The grammar states which roles no set dresses. */
  surface_material: 'surface_material',
  /** Every cell of a terrain patch meets the stated extent of a record that covers the ground. */
  ground_coverage: 'ground_coverage',
  /** Horizontal faces from a ring: a lot, a block, a tree pit. */
  ring_triangulation: 'ring_triangulation',
  /** A building's own faces: roofs from tier rings with light wells as holes, parapets, well walls, gables. */
  massing_faces: 'massing_faces',
  /** A facade's faces: its bays, panels, openings, mouldings, awnings and entrances. */
  facade_layout: 'facade_layout',
  /** A segment's carriageway and gutters, between its curbs' kerb lines. */
  segment_surface: 'segment_surface',
  /** Kerb faces, kerb tops and footways, offset from a kerb line by the floor square root normal, with fillet arcs. */
  kerb_offset: 'kerb_offset',
  /** A junction's carriageway, filled between its legs with fillet arcs. */
  junction_fill: 'junction_fill',
  /** A crossing's band across its segment, from its line and width. */
  crossing_band: 'crossing_band',
  /** Road marking stripes, each a stated plan quad. */
  marking_stripes: 'marking_stripes',
  /** Object parts turned by their facing vector, with power-of-two chord bisection. */
  form_parts: 'form_parts',
} as const;
export type Need = (typeof NEEDS)[keyof typeof NEEDS];

export type Fields = { readonly [name: string]: unknown };

/** A record's stated extent in plan, which a tessellation may test against but never draws. */
export interface PlanBox {
  readonly min_x: number;
  readonly min_y: number;
  readonly max_x: number;
  readonly max_y: number;
}

/** What an expander may read beyond its own record. */
export interface ExpandContext {
  /** The tile record's `tile_size_mm`. */
  readonly tileSizeMm: number;
  /** The stated plan extent of every record in the document, owned or halo, that covers the ground. */
  readonly groundCover: readonly PlanBox[];
}

export interface SurfaceExpansion {
  /** The surface role the range draws; the material record dressing that role binds to it. */
  readonly role: string;
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
  | { readonly rule: 'expand'; readonly expand: (fields: Fields, context: ExpandContext) => Expansion }
  | { readonly rule: 'needs'; readonly needs: readonly Need[] }
  | { readonly rule: 'not_in_projection' };

export class TessellationError extends Error {}

function safe(value: number, where: string): number {
  if (!Number.isSafeInteger(value)) {
    throw new TessellationError(`${where} is ${String(value)}, outside the integers a double holds`);
  }
  return value;
}

/**
 * A terrain patch, less every cell that something else covers.
 *
 * The grammar's terrain rule: samples row-major from the tile's south-west corner, at
 * `tile * tile_size_mm + index * cell_mm` with the sample's own height, and each cell split along
 * the diagonal from its south-west sample to its north-east one (`triangulation` "sw_ne"). With x
 * east and y north, both triangles are counter-clockwise seen from +z.
 *
 * The grammar also says terrain is not a surface where a street, a block or a lot covers it. This
 * version cannot yet draw those surfaces, so it cannot draw their edges either, and it takes the
 * exact conservative reading: a cell whose closed plan square meets the stated extent of any
 * record that covers the ground is left out. An extent contains everything its record generates,
 * so a cell kept is a cell nothing covers. A vertex is emitted only when a kept cell uses it, in
 * row-major order. That rule is fixed by `TESSELLATOR_SOURCE_VERSION`.
 *
 * It depends on the grammar's `terrain_grid_matches_tile`, and checks the facts it reads.
 */
function terrainCells(fields: Fields, context: ExpandContext): Expansion {
  const side = fields.samples_per_side as number;
  const cell = fields.cell_mm as number;
  const heights = fields.height_mm as readonly number[];
  if (safe((side - 1) * cell, 'a terrain span') !== context.tileSizeMm) {
    throw new TessellationError('a terrain patch whose samples do not span its tile (terrain_grid_matches_tile)');
  }
  if (heights.length !== side * side) {
    throw new TessellationError('a terrain patch without one height per sample (terrain_grid_matches_tile)');
  }
  const originX = safe((fields.tile_x as number) * context.tileSizeMm, 'a terrain origin');
  const originY = safe((fields.tile_y as number) * context.tileSizeMm, 'a terrain origin');
  const kept: [number, number][] = [];
  const used = new Array<boolean>(side * side).fill(false);
  for (let row = 0; row + 1 < side; row += 1) {
    const south = safe(originY + row * cell, 'a terrain y');
    const north = south + cell;
    for (let column = 0; column + 1 < side; column += 1) {
      const west = safe(originX + column * cell, 'a terrain x');
      const east = west + cell;
      const covered = context.groundCover.some((box) =>
        west <= box.max_x && box.min_x <= east && south <= box.max_y && box.min_y <= north);
      if (covered) continue;
      kept.push([row, column]);
      const low = row * side + column;
      for (const sample of [low, low + 1, low + side, low + side + 1]) used[sample] = true;
    }
  }
  if (kept.length === 0) return { state: 'unavailable', needs: [NEEDS.ground_coverage] };
  const vertexOf = new Array<number>(side * side);
  const vertices: number[] = [];
  used.forEach((isUsed, sample) => {
    if (!isUsed) return;
    vertexOf[sample] = vertices.length / 3;
    const column = sample % side;
    const row = (sample - column) / side;
    vertices.push(originX + column * cell, originY + row * cell, heights[sample]!);
  });
  const triangles: number[] = [];
  for (const [row, column] of kept) {
    const low = vertexOf[row * side + column]!;
    const right = vertexOf[row * side + column + 1]!;
    const high = vertexOf[(row + 1) * side + column + 1]!;
    const up = vertexOf[(row + 1) * side + column]!;
    triangles.push(low, right, high, low, high, up);
  }
  return { state: 'drawn', vertices, triangles };
}

/** Drawn terrain is a horizontal surface in the plan frame, `s = x` and `t = y`, dressed as terrain. */
function renderTerrain(fields: Fields, context: ExpandContext): Expansion {
  const grid = terrainCells(fields, context);
  if (grid.state === 'unavailable') return grid;
  const coordinates: number[] = [];
  for (let vertex = 0; vertex < grid.vertices.length; vertex += 3) {
    coordinates.push(grid.vertices[vertex]!, grid.vertices[vertex + 1]!);
  }
  return { ...grid, surface: { role: 'terrain', orientation: 'horizontal', coordinates } };
}

/**
 * Terrain supports whoever stands on it where nothing covers it: a heightfield has one height over
 * each plan point, which is what support sampling needs. Its own rule rather than the render rule,
 * so the two projections part: exposed terrain has no material, so it is unavailable to draw and
 * still supports.
 */
function supportTerrain(fields: Fields, context: ExpandContext): Expansion {
  return terrainCells(fields, context);
}

const needs = (...list: Need[]): Rule => ({ rule: 'needs', needs: list });
const notInProjection: Rule = { rule: 'not_in_projection' };

interface KindRules {
  readonly render_batch: Rule;
  readonly nav_envelope: Rule;
  /**
   * Whether the record's stated extent covers the ground in plan, so terrain under it is not a
   * surface. Everything a street, a block or a lot holds does; a district is a region, not a cover.
   */
  readonly covers_ground: boolean;
}

/**
 * Per record kind. `nav_envelope` is `not_in_projection` for what supports nobody: a facade, a
 * marking, a sign, an occupancy, a relation, and every object, which is collision's concern.
 */
const KIND_RULES: ReadonlyMap<string, KindRules> = new Map<string, KindRules>([
  ['city.block', { render_batch: needs(NEEDS.ring_triangulation), nav_envelope: needs(NEEDS.ring_triangulation), covers_ground: true }],
  ['city.crossing', { render_batch: needs(NEEDS.crossing_band), nav_envelope: needs(NEEDS.crossing_band), covers_ground: true }],
  ['city.curb_edge', { render_batch: needs(NEEDS.kerb_offset), nav_envelope: needs(NEEDS.kerb_offset), covers_ground: true }],
  ['city.district', { render_batch: notInProjection, nav_envelope: notInProjection, covers_ground: false }],
  ['city.entrance', { render_batch: needs(NEEDS.facade_layout), nav_envelope: needs(NEEDS.facade_layout), covers_ground: true }],
  ['city.facade', { render_batch: needs(NEEDS.facade_layout), nav_envelope: notInProjection, covers_ground: true }],
  ['city.ground_bay', { render_batch: needs(NEEDS.facade_layout), nav_envelope: notInProjection, covers_ground: true }],
  ['city.junction', { render_batch: needs(NEEDS.junction_fill), nav_envelope: needs(NEEDS.junction_fill), covers_ground: true }],
  ['city.junction_approach', { render_batch: notInProjection, nav_envelope: notInProjection, covers_ground: false }],
  // A lane is a path on its segment's carriageway, and draws as that carriageway.
  ['city.lane', { render_batch: notInProjection, nav_envelope: notInProjection, covers_ground: true }],
  ['city.lane_connection', { render_batch: notInProjection, nav_envelope: notInProjection, covers_ground: true }],
  ['city.massing', { render_batch: needs(NEEDS.massing_faces), nav_envelope: needs(NEEDS.massing_faces), covers_ground: true }],
  ['city.parcel', { render_batch: needs(NEEDS.ring_triangulation), nav_envelope: needs(NEEDS.ring_triangulation), covers_ground: true }],
  // A space on a carriageway or a footway draws as that surface; its bay lines are markings.
  ['city.parking_space', { render_batch: notInProjection, nav_envelope: notInProjection, covers_ground: true }],
  // An occupancy draws as its building's faces.
  ['city.premises', { render_batch: notInProjection, nav_envelope: notInProjection, covers_ground: true }],
  ['city.road_marking', { render_batch: needs(NEEDS.marking_stripes), nav_envelope: notInProjection, covers_ground: true }],
  ['city.rooftop_object', { render_batch: needs(NEEDS.form_parts), nav_envelope: notInProjection, covers_ground: true }],
  ['city.signal', { render_batch: notInProjection, nav_envelope: notInProjection, covers_ground: false }],
  // A named street draws as its segments.
  ['city.street', { render_batch: notInProjection, nav_envelope: notInProjection, covers_ground: true }],
  ['city.street_furniture', { render_batch: needs(NEEDS.form_parts), nav_envelope: notInProjection, covers_ground: true }],
  // A node draws as its junction or its segments' ends.
  ['city.street_node', { render_batch: notInProjection, nav_envelope: notInProjection, covers_ground: true }],
  ['city.street_segment', { render_batch: needs(NEEDS.segment_surface), nav_envelope: needs(NEEDS.segment_surface), covers_ground: true }],
  // A tree's parts, and its pit, which is ground a person may stand on.
  ['city.street_tree', { render_batch: needs(NEEDS.form_parts, NEEDS.ring_triangulation), nav_envelope: needs(NEEDS.ring_triangulation), covers_ground: true }],
  // A material is not a surface. A drawn range cites it; it draws nothing of its own.
  ['city.surface_material', { render_batch: notInProjection, nav_envelope: notInProjection, covers_ground: false }],
  ['city.terrain', {
    render_batch: { rule: 'expand', expand: renderTerrain },
    nav_envelope: { rule: 'expand', expand: supportTerrain },
    covers_ground: false,
  }],
  ['city.vitrine', { render_batch: needs(NEEDS.form_parts), nav_envelope: notInProjection, covers_ground: true }],
]);

function rulesOf(kind: string): KindRules {
  const rules = KIND_RULES.get(kind);
  if (rules === undefined) throw new TessellationError(`no rule for ${kind}`);
  return rules;
}

/** The rule for one record kind in one materialised projection. */
export function ruleFor(projection: ProjectionName, kind: string): Rule {
  const rules = rulesOf(kind);
  if (projection === 'render_batch') return rules.render_batch;
  if (projection === 'nav_envelope') return rules.nav_envelope;
  throw new TessellationError(`${projection} is not materialised`);
}

/** Whether a record kind's stated extent covers the ground terrain would otherwise draw. */
export function coversGround(kind: string): boolean {
  return rulesOf(kind).covers_ground;
}

// Held at load, so a record kind added to a table without a rule cannot be baked at all, and a kind
// said to cover the ground states an extent to cover it with.
for (const table of GRAMMAR_TABLES) {
  const kinds = table.shapes.records
    .map((shape) => shape.kind)
    .filter((kind): kind is string => kind !== undefined && kind !== TILE_RECORD_KIND);
  for (const kind of kinds) {
    if (coversGround(kind)) {
      if (recordShapeOf(table, kind)!.extent_field === undefined) {
        throw new TessellationError(`${kind} covers the ground and states no extent`);
      }
    }
  }
  for (const kind of [...KIND_RULES.keys()].sort()) {
    if (!kinds.includes(kind)) throw new TessellationError(`a rule for ${kind}, which no table declares`);
  }
}
