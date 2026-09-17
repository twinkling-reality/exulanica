/**
 * WHAT EACH RECORD KIND BECOMES IN EACH PROJECTION THIS TESSELLATOR MATERIALISES.
 *
 * An expander is a pure function from one record's fields to integer vertices and triangles. It
 * reads the record and the tile it is baked in, and nothing else: no catalog, no table of roles or
 * materials, no default. A record kind with no expander has a statement naming the rule it waits
 * on, and the entry it produces is `unavailable`, never a substituted mesh. Geometry an expander
 * produces exactly is drawn whether or not a material record dresses it: a range nothing dresses
 * says that none exists, as the grammar's render_batch contract requires, and is not withheld.
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
export const TESSELLATOR_SOURCE_VERSION = 3;

/**
 * What each materialised projection preserves and what it may be used for, as separate rows, the
 * target architecture's representation contract. The header of every container carries these, and
 * `TESSELLATOR_SOURCE_VERSION` versions them.
 */
export interface ProjectionDefinition {
  readonly name: ProjectionName;
  /**
   * Whether a drawn entry is made of surfaces, each with the grammar's surface role, the material
   * record for its record and role (or the statement that none exists), an orientation and surface
   * coordinates.
   */
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
        'the record and stated identity of every triangle',
        'the surfaces of every drawn record, each with its role, which is a surface role its grammar states, '
          + 'its orientation, and the surface material record for that record and role, or the statement '
          + 'that none exists; no role is inferred from geometry',
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
        'capsule clearance in plan: every support triangle lies more than the capsule radius its grammar '
          + 'measures from the stated plan extent of every other record the tile carries that covers or stands '
          + 'on the ground, at any height, so a capsule of that radius stood anywhere on it meets none of them',
      ],
      admissible_uses: ['sampling support height'],
      inadmissible_uses: [
        'drawing',
        'collision: clearance is not a solid',
        'deciding walkability: no record states a slope limit, so no slope is refused and the capsule is '
          + 'not checked against rising ground',
        'deciding that a plan point has no support: a terrain cell whose closed plan square meets such an '
          + 'extent grown by the capsule radius is left out until that record is drawn',
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
 * already carry enough for. A missing material is not among them: geometry nothing dresses is
 * drawn, and says so.
 */
export const NEEDS = {
  /** Every cell of a terrain patch meets a record that covers the ground, or its capsule clearance. */
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
  /**
   * The stated plan extent of every record in the document, owned or halo, that covers or stands on
   * the ground.
   */
  readonly groundCover: readonly PlanBox[];
  /**
   * The capsule radius the record's grammar measures for `nav_envelope`'s `capsule_clearance`, or
   * undefined when it measures none, which an expander claiming clearance refuses. The height and
   * the eye are not read: the carve is in plan and ignores height, which only ever leaves out more.
   */
  readonly capsuleRadiusMm: number | undefined;
}

export interface SurfaceExpansion {
  /** The grammar's surface role the piece draws; the material record for (record, role) dresses it. */
  readonly role: string;
  readonly orientation: SurfaceOrientation;
  /** Absolute surface coordinates in millimetres, two per vertex of the piece. */
  readonly coordinates: readonly number[];
}

/**
 * One group of faces an expander draws, with vertices of its own. In a projection that carries
 * surfaces every piece is one surface, and an entry may repeat a role only on another orientation.
 * In any other projection the pieces are joined into one range and carry no surface.
 */
export interface Piece {
  /** Absolute integer vertices in the records' unit, three per vertex. */
  readonly vertices: readonly number[];
  /** Indices into this piece's `vertices`, three per triangle, counter-clockwise seen from outside. */
  readonly triangles: readonly number[];
  /** Present exactly when the projection carries surfaces. */
  readonly surface?: SurfaceExpansion;
}

export type Expansion =
  | { readonly state: 'drawn'; readonly pieces: readonly Piece[] }
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
 * A terrain patch, less every cell whose closed plan square meets one of `omit`.
 *
 * The grammar's terrain rule: samples row-major from the tile's south-west corner, at
 * `tile * tile_size_mm + index * cell_mm` with the sample's own height, and each cell split along
 * the diagonal from its south-west sample to its north-east one (`triangulation` "sw_ne"). With x
 * east and y north, both triangles are counter-clockwise seen from +z. A vertex is emitted only
 * when a kept cell uses it, in row-major order.
 *
 * It depends on the grammar's `terrain_grid_matches_tile`, and checks the facts it reads.
 */
function terrainCells(
  fields: Fields,
  context: ExpandContext,
  omit: readonly PlanBox[],
): { readonly state: 'drawn'; readonly vertices: number[]; readonly triangles: number[] } | Extract<Expansion, { state: 'unavailable' }> {
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
      const covered = omit.some((box) =>
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

/**
 * Drawn terrain is the whole patch, a horizontal surface in the plan frame, `s = x` and `t = y`, in
 * the terrain role. The grammar says terrain is not a surface where a street, a block or a lot
 * covers it; how it yields to them is exact coverage, and comes with their expanders. Leaving cells
 * out here instead would draw holes in the ground that read as cuts.
 */
function renderTerrain(fields: Fields, context: ExpandContext): Expansion {
  const grid = terrainCells(fields, context, []);
  if (grid.state === 'unavailable') return grid;
  const coordinates: number[] = [];
  for (let vertex = 0; vertex < grid.vertices.length; vertex += 3) {
    coordinates.push(grid.vertices[vertex]!, grid.vertices[vertex + 1]!);
  }
  const surface: SurfaceExpansion = { role: 'terrain', orientation: 'horizontal', coordinates };
  return { state: 'drawn', pieces: [{ vertices: grid.vertices, triangles: grid.triangles, surface }] };
}

/**
 * Terrain supports whoever stands on it where nothing covers it and a capsule fits: a heightfield
 * has one height over each plan point, which is what support sampling needs.
 *
 * This version cannot draw the surfaces that cover terrain, so it takes the exact conservative
 * reading, in integers: a cell is left out when its closed plan square meets the stated extent of
 * any record that covers or stands on the ground, grown on every side by the capsule radius the
 * terrain's grammar measures (`capsule_clearance`, `radius_mm`, in its nav_envelope contract). An
 * extent contains everything its record generates, so a kept cell is a cell nothing covers, and a
 * point outside a box grown by the radius on each axis is more than the radius from the box, so a
 * capsule stood anywhere on a kept cell meets no such record in plan, at any height. Support never
 * claims ground that is not there, or room that is not there; render draws the whole patch. Both
 * rules are fixed by `TESSELLATOR_SOURCE_VERSION`.
 */
function supportTerrain(fields: Fields, context: ExpandContext): Expansion {
  const radius = context.capsuleRadiusMm;
  if (radius === undefined) {
    throw new TessellationError('a support surface whose grammar measures no capsule radius, so no clearance can be kept');
  }
  const clear = context.groundCover.map((box) => ({
    min_x: safe(box.min_x - radius, 'a clearance extent'),
    min_y: safe(box.min_y - radius, 'a clearance extent'),
    max_x: safe(box.max_x + radius, 'a clearance extent'),
    max_y: safe(box.max_y + radius, 'a clearance extent'),
  }));
  const grid = terrainCells(fields, context, clear);
  if (grid.state === 'unavailable') return grid;
  return { state: 'drawn', pieces: [{ vertices: grid.vertices, triangles: grid.triangles }] };
}

const needs = (...list: Need[]): Rule => ({ rule: 'needs', needs: list });
const notInProjection: Rule = { rule: 'not_in_projection' };

interface KindRules {
  readonly render_batch: Rule;
  readonly nav_envelope: Rule;
  /**
   * Whether the record's stated extent covers or stands on the ground in plan, so terrain under it
   * is not a surface and a capsule keeps clear of it. Everything a street, a block or a lot holds
   * does; a district is a region, and a terrain patch is the ground itself.
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
