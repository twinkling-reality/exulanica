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
 * builds the terrain grid, a street segment's carriageway and gutters (`streets.ts`) and a
 * building's own walls, roofs and parapets (`massing.ts`), and in the navigation projection carves
 * the ground clear of what the grammar's navigation table says obstructs a walking capsule;
 * everything else states the rule it waits on (`NEEDS`).
 *
 * Two projections are materialised, each from the records by its own rules and each with its own
 * representation contract: `render_batch`, what is drawn, and `nav_envelope`, what a person is
 * supported by. Navigation is never read back out of the render mesh; Melbourne failed exactly
 * there. `collision_proxy` and `pick_geometry` wait for contracts of their own.
 */
import { GRAMMAR_TABLES, recordShapeOf, TILE_RECORD_KIND } from './record-shapes.js';
import type { Plan, Space } from './integer-math.js';
import { massingPieces } from './massing.js';
import type { MassingFields } from './massing.js';
import type { Piece, SurfaceExpansion } from './pieces.js';
import type { ProjectionName } from './record-shapes.js';
import { ringClearance } from './ring-clearance.js';
import { segmentSurfaces } from './streets.js';
import type { StreetFields } from './streets.js';
import { carveSupport } from './support-carve.js';
import type { ClearanceWalk, SupportTriangle } from './support-carve.js';
import { coveringsWithArea, metCells, yieldedCell } from './terrain-yield.js';
import type { CoveringTriangle, TerrainPatch } from './terrain-yield.js';

/**
 * Bumped whenever an expander, a statement, a contract or the materialised projection set
 * changes, because each changes the bytes a bake writes. The bake stage's parameters carry it.
 */
export const TESSELLATOR_SOURCE_VERSION = 6;

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
        'capsule clearance in plan: no support triangle enters the region within the capsule radius its '
          + 'grammar measures of what its navigation table says obstructs, at any height, so a capsule of '
          + 'that radius stood anywhere on support meets none of them',
      ],
      admissible_uses: ['sampling support height'],
      inadmissible_uses: [
        'drawing',
        'collision: clearance is not a solid',
        'deciding walkability: no record states a slope limit, so no slope is refused and the capsule is '
          + 'not checked against rising ground',
        'deciding that a plan point has no support: a record whose low parts obstruct takes the whole of '
          + 'its stated plan extent until this tessellator reads those parts, and a record whose rule is '
          + 'not built draws no support at all',
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
  /** Every part of the surface is ground another record takes, or a capsule clearance, so none is left. */
  ground_coverage: 'ground_coverage',
  /** Horizontal faces from a ring: a lot, a block, a tree pit. */
  ring_triangulation: 'ring_triangulation',
  /** A facade's faces: its bays, panels, openings, mouldings, awnings and entrances. */
  facade_layout: 'facade_layout',
  /** A centreline or kerb line of more than one piece, or a kerb line not running with its centreline. */
  bent_street: 'bent_street',
  /** A segment's two curbs, carried by the tile, whose kerb lines leave its strip a length. */
  street_curbs: 'street_curbs',
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

/** A record the document carries, owned or halo, as an expander may read it. */
export interface CarriedRecord {
  readonly kind: string;
  readonly fields: Fields;
}

/** A record's stated extent in plan, which a tessellation may test against but never draws. */
export interface PlanBox {
  readonly min_x: number;
  readonly min_y: number;
  readonly max_x: number;
  readonly max_y: number;
}

/** A region a standing capsule keeps its radius clear of, in plan, with what it was read from. */
export interface ObstructionRegion {
  /** The record kind that obstructs, for the message when a ring is refused. */
  readonly kind: string;
  /** The ring itself, as the navigation table's obstruction axis names it. */
  readonly ring: readonly Plan[];
}

/** What an expander may read beyond its own record. */
export interface ExpandContext {
  /** The tile record's `tile_size_mm`. */
  readonly tileSizeMm: number;
  /**
   * Every region the navigation table says obstructs a walking capsule, from every record in the
   * document, owned or halo: a `base_ring` record's base ring, and a `low_parts` record's stated
   * plan extent, which holds every part it has until this tessellator reads them one by one.
   */
  readonly obstructions: readonly ObstructionRegion[];
  /**
   * The record's own stated plan extent, which its geometry must lie inside. A carve holds its
   * answer to this, since a hull round a carved face may otherwise reach a millimetre past it.
   */
  readonly extent: PlanBox | undefined;
  /**
   * The capsule radius the record's grammar measures for `nav_envelope`'s `capsule_clearance`, or
   * undefined when it measures none, which an expander claiming clearance refuses. The height and
   * the eye are not read: the carve is in plan and ignores height, which only ever leaves out more.
   */
  readonly capsuleRadiusMm: number | undefined;
  /**
   * In plan, every triangle of the ground drawn records take by the navigation table, in this
   * projection. Empty while the records whose expanders read no coverings are expanded, and in a
   * projection that carries no surfaces.
   */
  readonly coverings: readonly CoveringTriangle[];
  /** Every record the document carries, owned or halo, that states an identity, by that identity. */
  readonly carried: ReadonlyMap<string, CarriedRecord>;
}

export type Expansion =
  | { readonly state: 'drawn'; readonly pieces: readonly Piece[] }
  | { readonly state: 'unavailable'; readonly needs: readonly Need[] };

export type Rule =
  | {
      readonly rule: 'expand';
      readonly expand: (fields: Fields, context: ExpandContext) => Expansion;
      /** Whether it reads `coverings`, so every record that covers the ground expands before it. */
      readonly readsCoverings: boolean;
    }
  | { readonly rule: 'needs'; readonly needs: readonly Need[] }
  | { readonly rule: 'not_in_projection' };

export class TessellationError extends Error {}

function safe(value: number, where: string): number {
  if (!Number.isSafeInteger(value)) {
    throw new TessellationError(`${where} is ${String(value)}, outside the integers a double holds`);
  }
  return value;
}

/** A terrain record's grid, checked against the facts it reads (`terrain_grid_matches_tile`). */
function patchOf(fields: Fields, context: ExpandContext): TerrainPatch {
  const side = fields.samples_per_side as number;
  const cell = fields.cell_mm as number;
  const heights = fields.height_mm as readonly number[];
  if (safe((side - 1) * cell, 'a terrain span') !== context.tileSizeMm) {
    throw new TessellationError('a terrain patch whose samples do not span its tile (terrain_grid_matches_tile)');
  }
  if (heights.length !== side * side) {
    throw new TessellationError('a terrain patch without one height per sample (terrain_grid_matches_tile)');
  }
  return {
    originX: safe((fields.tile_x as number) * context.tileSizeMm, 'a terrain origin'),
    originY: safe((fields.tile_y as number) * context.tileSizeMm, 'a terrain origin'),
    cell,
    side,
    heights,
  };
}

/**
 * A terrain patch, less every cell whose closed plan square meets one of `omit` and every cell
 * whose row-major index is in `skip`.
 *
 * The grammar's terrain rule: samples row-major from the tile's south-west corner, at
 * `tile * tile_size_mm + index * cell_mm` with the sample's own height, and each cell split along
 * the diagonal from its south-west sample to its north-east one (`triangulation` "sw_ne"). With x
 * east and y north, both triangles are counter-clockwise seen from +z. A vertex is emitted only
 * when a kept cell uses it, in row-major order.
 */
function terrainCells(
  patch: TerrainPatch,
  omit: readonly PlanBox[],
  skip: ReadonlySet<number>,
): { readonly vertices: number[]; readonly triangles: number[] } {
  const { side, cell, heights, originX, originY } = patch;
  const kept: [number, number][] = [];
  const used = new Array<boolean>(side * side).fill(false);
  for (let row = 0; row + 1 < side; row += 1) {
    const south = safe(originY + row * cell, 'a terrain y');
    const north = south + cell;
    for (let column = 0; column + 1 < side; column += 1) {
      const west = safe(originX + column * cell, 'a terrain x');
      const east = west + cell;
      if (skip.has(row * (side - 1) + column)) continue;
      const covered = omit.some((box) =>
        west <= box.max_x && box.min_x <= east && south <= box.max_y && box.min_y <= north);
      if (covered) continue;
      kept.push([row, column]);
      const low = row * side + column;
      for (const sample of [low, low + 1, low + side, low + side + 1]) used[sample] = true;
    }
  }
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
  return { vertices, triangles };
}

/**
 * THE GROUND PARTITION: a terrain patch less the ground drawn records take, by the terrain yield
 * rule (`terrain-yield.ts`). One partition, read by both projections: render draws it as the
 * terrain surface and navigation stands people on what is left of it, so the two never disagree
 * about where the ground is. A cell no covering meets is the grid's own two triangles.
 */
function groundPartition(patch: TerrainPatch, context: ExpandContext, where: string): { vertices: number[]; triangles: number[] } {
  const coverings = coveringsWithArea(context.coverings, where);
  const met = metCells(patch, coverings, where);
  const grid = terrainCells(patch, [], new Set(met.keys()));
  const vertices = [...grid.vertices];
  const triangles = [...grid.triangles];
  for (const key of [...met.keys()].sort((a, b) => a - b)) {
    const column = key % (patch.side - 1);
    const row = (key - column) / (patch.side - 1);
    const cell = yieldedCell(patch, row, column, met.get(key)!.map((index) => coverings[index]!), where);
    const first = vertices.length / 3;
    for (const vertex of cell.vertices) vertices.push(vertex[0], vertex[1], vertex[2]);
    for (const index of cell.triangles) triangles.push(first + index);
  }
  return { vertices, triangles };
}

/**
 * Drawn terrain is the ground partition, a horizontal surface in the plan frame, `s = x` and
 * `t = y`, in the terrain role. The grammar says terrain is not a surface where a street, a block
 * or a lot covers it; it yields exactly where their surfaces are drawn, and nowhere their records
 * only state an extent, which would draw holes nothing fills.
 */
function renderTerrain(fields: Fields, context: ExpandContext): Expansion {
  const where = `city.terrain ${fields.identity as string}`;
  const { vertices, triangles } = groundPartition(patchOf(fields, context), context, where);
  if (triangles.length === 0) return { state: 'unavailable', needs: [NEEDS.ground_coverage] };
  const coordinates: number[] = [];
  for (let vertex = 0; vertex < vertices.length; vertex += 3) {
    coordinates.push(vertices[vertex]!, vertices[vertex + 1]!);
  }
  const surface: SurfaceExpansion = { role: 'terrain', orientation: 'horizontal', coordinates };
  return { state: 'drawn', pieces: [{ vertices, triangles, surface }] };
}

/**
 * Everything a walking capsule keeps its radius clear of, as convex integer pieces: each region the
 * navigation table's obstruction axis names, covered by the ring clearance rule
 * (`ring-clearance.ts`) at the radius the record's grammar measures.
 */
function clearancesOf(context: ExpandContext, where: string): ClearanceWalk[] {
  const radius = context.capsuleRadiusMm;
  if (radius === undefined) {
    throw new TessellationError('a support surface whose grammar measures no capsule radius, so no clearance can be kept');
  }
  const walks: ClearanceWalk[] = [];
  for (const obstruction of context.obstructions) {
    for (const piece of ringClearance(obstruction.ring, radius, `${obstruction.kind} obstructing ${where}`)) {
      walks.push(piece);
    }
  }
  return walks;
}

/** The record's stated plan extent as a convex walk: the region its support is held inside. */
function statedWalk(context: ExpandContext, where: string): Plan[] {
  const extent = context.extent;
  if (extent === undefined) throw new TessellationError(`${where} draws support and states no extent`);
  return [
    [extent.min_x, extent.min_y],
    [extent.max_x, extent.min_y],
    [extent.max_x, extent.max_y],
    [extent.min_x, extent.max_y],
  ];
}

/** A mesh's triangles as space triangles, which the carve takes one at a time. */
function spaceTriangles(vertices: readonly number[], triangles: readonly number[]): SupportTriangle[] {
  const corner = (index: number): Space => [vertices[index * 3]!, vertices[index * 3 + 1]!, vertices[index * 3 + 2]!];
  const out: SupportTriangle[] = [];
  for (let at = 0; at + 2 < triangles.length; at += 3) {
    out.push([corner(triangles[at]!), corner(triangles[at + 1]!), corner(triangles[at + 2]!)]);
  }
  return out;
}

/** Space triangles as one piece, each vertex written once however many triangles hold it. */
function pieceOf(kept: readonly SupportTriangle[]): Piece {
  const vertices: number[] = [];
  const triangles: number[] = [];
  const at = new Map<string, number>();
  for (const triangle of kept) {
    for (const point of triangle) {
      const key = `${String(point[0])} ${String(point[1])} ${String(point[2])}`;
      const found = at.get(key);
      if (found === undefined) {
        at.set(key, vertices.length / 3);
        triangles.push(vertices.length / 3);
        vertices.push(point[0], point[1], point[2]);
        continue;
      }
      triangles.push(found);
    }
  }
  return { vertices, triangles };
}

/**
 * Support is the surfaces a record draws that a person may stand on, carved clear of everything the
 * navigation table says obstructs a capsule, by the support carve rule (`support-carve.ts`). The
 * carve is in plan and ignores height, which only ever leaves out more, and it holds its answer
 * inside the record's stated extent, which every drawn vertex must lie in.
 */
function carvedSupport(surfaces: readonly SupportTriangle[], context: ExpandContext, where: string): Expansion {
  const kept = carveSupport(surfaces, clearancesOf(context, where), statedWalk(context, where), where);
  if (kept.length === 0) return { state: 'unavailable', needs: [NEEDS.ground_coverage] };
  return { state: 'drawn', pieces: [pieceOf(kept)] };
}

/**
 * Terrain supports whoever stands on it where nothing covers it and a capsule fits: a heightfield
 * has one height over each plan point, which is what support sampling needs. It is the ground
 * partition render draws, carved.
 */
function supportTerrain(fields: Fields, context: ExpandContext): Expansion {
  const where = `city.terrain ${fields.identity as string}`;
  const { vertices, triangles } = groundPartition(patchOf(fields, context), context, where);
  return carvedSupport(spaceTriangles(vertices, triangles), context, where);
}

/** A street segment's curb on one side: the one carried curb that names the segment and the side. */
function curbOf(context: ExpandContext, segment: string, side: string): StreetFields | undefined {
  const found = [...context.carried.values()].filter((record) =>
    record.kind === 'city.curb_edge' && record.fields.segment_identity === segment && record.fields.side === side);
  if (found.length > 1) throw new TessellationError(`two curbs on the ${side} of segment ${segment}`);
  return found.length === 1 ? found[0]!.fields : undefined;
}

/**
 * A street segment's carriageway and gutters, by the segment rule, between the kerb lines of the
 * two curbs the tile carries for it.
 */
function renderSegment(fields: Fields, context: ExpandContext): Expansion {
  const identity = fields.identity as string;
  const result = segmentSurfaces(fields, curbOf(context, identity, 'left'), curbOf(context, identity, 'right'), `city.street_segment ${identity}`);
  if (result.state === 'waiting') return { state: 'unavailable', needs: [result.need] };
  return { state: 'drawn', pieces: result.pieces };
}

/** A building's own walls, roofs, terraces and parapets, by the massing rule (`massing.ts`). */
function renderMassing(fields: Fields): Expansion {
  const pieces = massingPieces(fields as unknown as MassingFields, `city.massing ${fields.identity as string}`);
  if (pieces.length === 0) throw new TessellationError('a massing with no tier, which its grammar refuses');
  return { state: 'drawn', pieces };
}

/**
 * A segment's carriageway and gutters are ground a person walks on, which is what the navigation
 * table's `support` says: the same surfaces the render path draws, the horizontal ones, carved.
 */
function supportSegment(fields: Fields, context: ExpandContext): Expansion {
  const identity = fields.identity as string;
  const where = `city.street_segment ${identity}`;
  const result = segmentSurfaces(fields, curbOf(context, identity, 'left'), curbOf(context, identity, 'right'), where);
  if (result.state === 'waiting') return { state: 'unavailable', needs: [result.need] };
  const surfaces: SupportTriangle[] = [];
  for (const piece of result.pieces) {
    if (piece.surface?.orientation !== 'horizontal') continue;
    for (const triangle of spaceTriangles(piece.vertices, piece.triangles)) surfaces.push(triangle);
  }
  return carvedSupport(surfaces, context, where);
}

const needs = (...list: Need[]): Rule => ({ rule: 'needs', needs: list });
const notInProjection: Rule = { rule: 'not_in_projection' };

interface KindRules {
  readonly render_batch: Rule;
  readonly nav_envelope: Rule;
}

/**
 * Per record kind. `nav_envelope` is `not_in_projection` for what supports nobody: a facade, a
 * marking, a sign, an occupancy, a relation, and every object, which is collision's concern.
 */
const KIND_RULES: ReadonlyMap<string, KindRules> = new Map<string, KindRules>([
  ['city.block', { render_batch: needs(NEEDS.ring_triangulation), nav_envelope: needs(NEEDS.ring_triangulation) }],
  ['city.crossing', { render_batch: needs(NEEDS.crossing_band), nav_envelope: needs(NEEDS.crossing_band) }],
  ['city.curb_edge', { render_batch: needs(NEEDS.kerb_offset), nav_envelope: needs(NEEDS.kerb_offset) }],
  ['city.district', { render_batch: notInProjection, nav_envelope: notInProjection }],
  ['city.entrance', { render_batch: needs(NEEDS.facade_layout), nav_envelope: needs(NEEDS.facade_layout) }],
  ['city.facade', { render_batch: needs(NEEDS.facade_layout), nav_envelope: notInProjection }],
  ['city.ground_bay', { render_batch: needs(NEEDS.facade_layout), nav_envelope: notInProjection }],
  ['city.junction', { render_batch: needs(NEEDS.junction_fill), nav_envelope: needs(NEEDS.junction_fill) }],
  // A room's near wall inside its building, behind its glazing: laid out on its facade, standing on
  // nothing, so it is no more a surface of the ground than the vitrine beside it.
  ['city.interior_backing', { render_batch: needs(NEEDS.facade_layout), nav_envelope: notInProjection }],
  ['city.junction_approach', { render_batch: notInProjection, nav_envelope: notInProjection }],
  // A lane is a path on its segment's carriageway, and draws as that carriageway.
  ['city.lane', { render_batch: notInProjection, nav_envelope: notInProjection }],
  ['city.lane_connection', { render_batch: notInProjection, nav_envelope: notInProjection }],
  // A building stands nobody on itself and covers the ground it stands on, which the navigation
  // table states as ground `cover`: it is no surface of the navigation projection at all.
  ['city.massing', {
    render_batch: { rule: 'expand', expand: (fields: Fields): Expansion => renderMassing(fields), readsCoverings: false },
    nav_envelope: notInProjection,
  }],
  ['city.parcel', { render_batch: needs(NEEDS.ring_triangulation), nav_envelope: needs(NEEDS.ring_triangulation) }],
  // A space on a carriageway or a footway draws as that surface; its bay lines are markings.
  ['city.parking_space', { render_batch: notInProjection, nav_envelope: notInProjection }],
  // An occupancy draws as its building's faces.
  ['city.premises', { render_batch: notInProjection, nav_envelope: notInProjection }],
  ['city.road_marking', { render_batch: needs(NEEDS.marking_stripes), nav_envelope: notInProjection }],
  ['city.rooftop_object', { render_batch: needs(NEEDS.form_parts), nav_envelope: notInProjection }],
  ['city.signal', { render_batch: notInProjection, nav_envelope: notInProjection }],
  // A named street draws as its segments.
  ['city.street', { render_batch: notInProjection, nav_envelope: notInProjection }],
  ['city.street_furniture', { render_batch: needs(NEEDS.form_parts), nav_envelope: notInProjection }],
  // A node draws as its junction or its segments' ends.
  ['city.street_node', { render_batch: notInProjection, nav_envelope: notInProjection }],
  ['city.street_segment', {
    render_batch: { rule: 'expand', expand: renderSegment, readsCoverings: false },
    nav_envelope: { rule: 'expand', expand: supportSegment, readsCoverings: false },
  }],
  // A tree's parts, and its pit, which is ground a person may stand on.
  ['city.street_tree', { render_batch: needs(NEEDS.form_parts, NEEDS.ring_triangulation), nav_envelope: needs(NEEDS.ring_triangulation) }],
  // A material is not a surface. A drawn range cites it; it draws nothing of its own.
  ['city.surface_material', { render_batch: notInProjection, nav_envelope: notInProjection }],
  ['city.terrain', {
    render_batch: { rule: 'expand', expand: renderTerrain, readsCoverings: true },
    nav_envelope: { rule: 'expand', expand: supportTerrain, readsCoverings: true },
  }],
  ['city.vitrine', { render_batch: needs(NEEDS.form_parts), nav_envelope: notInProjection }],
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

/**
 * How a kind whose navigation row covers its base ring states that ring: the ring the record stands
 * on, as its grammar states it. A building stands on its lowest tier's ring
 * (`exulanica.grammar.grammars.city.document` reads `tiers[0].ring_mm` as its footprint).
 */
const BASE_RINGS: ReadonlyMap<string, (fields: Fields) => readonly Plan[]> = new Map([
  ['city.massing', (fields: Fields): readonly Plan[] => (fields.tiers as readonly Fields[])[0]!.ring_mm as readonly Plan[]],
]);

/** The base ring of a record whose kind covers it. A kind with no stated way to read it is refused. */
export function baseRingOf(kind: string, fields: Fields): readonly Plan[] {
  const reader = BASE_RINGS.get(kind);
  if (reader === undefined) throw new TessellationError(`${kind} covers its base ring, and this tessellator reads no base ring for it`);
  return reader(fields);
}

/**
 * The region one record obstructs a walking capsule with, by the navigation table's obstruction
 * axis, or undefined when it obstructs nothing. A base ring is the ring itself. Low parts are each
 * part of the record below the capsule height, which this tessellator does not read one by one yet,
 * so it takes the stated plan extent, which holds every part the record has: it keeps a capsule
 * clear of more ground than the parts themselves would, never less.
 */
export function obstructionOf(
  kind: string,
  region: string,
  fields: Fields,
  extent: PlanBox | undefined,
): ObstructionRegion | undefined {
  if (region === 'none') return undefined;
  if (region === 'base_ring') return { kind, ring: baseRingOf(kind, fields) };
  if (region === 'low_parts') {
    if (extent === undefined) throw new TessellationError(`${kind} obstructs with its low parts and states no extent that holds them`);
    return {
      kind,
      ring: [
        [extent.min_x, extent.min_y],
        [extent.max_x, extent.min_y],
        [extent.max_x, extent.max_y],
        [extent.min_x, extent.max_y],
      ],
    };
  }
  throw new TessellationError(`${kind} obstructs with ${region}, a region this tessellator does not read`);
}

// Held at load, so a record kind added to a table without a rule cannot be baked at all, and every
// kind the navigation table gives a region states what that region is read from.
for (const table of GRAMMAR_TABLES) {
  const kinds = table.shapes.records
    .map((shape) => shape.kind)
    .filter((kind): kind is string => kind !== undefined && kind !== TILE_RECORD_KIND);
  for (const kind of [...KIND_RULES.keys()].sort()) {
    if (!kinds.includes(kind)) throw new TessellationError(`a rule for ${kind}, which no table declares`);
  }
  for (const row of table.navigation) {
    // A kind whose ground is covered stands nobody, and nobody may stand inside it either, so it
    // obstructs too: a table that covers the ground without obstructing it is refused, not guessed.
    if (row.ground === 'cover') {
      if (row.cover !== 'base_ring') throw new TessellationError(`${row.kind} covers ${row.cover}, a region this tessellator does not read`);
      if (!BASE_RINGS.has(row.kind)) throw new TessellationError(`${row.kind} covers its base ring, and this tessellator reads no base ring for it`);
      if (row.obstruction === 'none') throw new TessellationError(`${row.kind} covers the ground and obstructs nobody, so nothing would keep a capsule out of it`);
    }
    if (row.obstruction === 'none') continue;
    if (row.obstruction === 'base_ring' && !BASE_RINGS.has(row.kind)) {
      throw new TessellationError(`${row.kind} obstructs with its base ring, and this tessellator reads no base ring for it`);
    }
    if (row.obstruction === 'low_parts' && recordShapeOf(table, row.kind)!.extent_field === undefined) {
      throw new TessellationError(`${row.kind} obstructs with its low parts and states no extent that holds them`);
    }
    if (row.obstruction !== 'base_ring' && row.obstruction !== 'low_parts') {
      throw new TessellationError(`${row.kind} obstructs with ${row.obstruction}, a region this tessellator does not read`);
    }
  }
}
