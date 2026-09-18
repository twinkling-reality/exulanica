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
 * builds the terrain grid, a street segment's carriageway and gutters (`streets.ts`), a building's
 * own walls, roofs and parapets (`massing.ts`), the face it shows a street with its ground band and
 * that band's panels (`facades.ts`), the solids of an object's parts (`form-parts.ts`) and the
 * ground a lot, a block or a tree pit states (`lots.ts`), and a curb's kerb and footway and the
 * carriageway that fills a junction (`streets.ts`), and in the navigation projection carves the
 * ground clear of what the grammar's navigation table says obstructs a walking capsule; everything
 * else states the rule it waits on (`NEEDS`).
 *
 * Two projections are materialised, each from the records by its own rules and each with its own
 * representation contract: `render_batch`, what is drawn, and `nav_envelope`, what a person is
 * supported by. Navigation is never read back out of the render mesh; Melbourne failed exactly
 * there. `collision_proxy` and `pick_geometry` wait for contracts of their own.
 */
import { GRAMMAR_TABLES, nestedShapeOf, recordShapeOf, TILE_RECORD_KIND } from './record-shapes.js';
import { add, subtract } from './integer-math.js';
import type { Plan, Space } from './integer-math.js';
import { backingPieces, facadePieces, faceCover, faceHeights, panelRoles } from './facades.js';
import type { BackingFields, FaceFrame, FacadeFields, GroundBayFields } from './facades.js';
import { massingPieces } from './massing.js';
import type { MassingFields } from './massing.js';
import { piecesOf, runOf, Surface } from './faces.js';
import type { FaceCover } from './faces.js';
import { alongEdge } from './faces.js';
import { expandFormParts, FormPartsRefusal } from './form-parts.js';
import { groundPieces } from './lots.js';
import type { FormObject, FormPart, FormShape, FormTriangle } from './form-parts.js';
import type { Piece, SurfaceExpansion } from './pieces.js';
import type { GrammarTable, ProjectionName } from './record-shapes.js';
import { ringClearance } from './ring-clearance.js';
import { curbSurfaces, junctionSurface, segmentSurfaces } from './streets.js';
import type { ApproachContext, CornerContext, CornerNeed, StreetFields, StreetLookup, StreetResult, StripNeed } from './streets.js';
import { hullKeepingEdges } from './piece-carve.js';
import { carveSupport } from './support-carve.js';
import type { ClearanceWalk, SupportTriangle } from './support-carve.js';
import { coveringsWithArea, metCells, yieldedCell } from './terrain-yield.js';
import type { CoveringTriangle, TerrainPatch } from './terrain-yield.js';

/**
 * Bumped whenever an expander, a statement, a contract or the materialised projection set
 * changes, because each changes the bytes a bake writes. The bake stage's parameters carry it.
 */
export const TESSELLATOR_SOURCE_VERSION = 18;

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
        'what obstructs by height: a record whose parts obstruct is read part by part, and only the parts '
          + 'standing below the capsule height its grammar measures take ground, so what stands over a '
          + 'person\'s head leaves the ground under it walkable',
      ],
      admissible_uses: ['sampling support height'],
      inadmissible_uses: [
        'drawing',
        'collision: clearance is not a solid',
        'deciding walkability: no record states a slope limit, so no slope is refused and the capsule is '
          + 'not checked against rising ground',
        'deciding that a plan point has no support: a record whose rule is not built draws no support at '
          + 'all, so unsupported ground here is as often a rule this version has yet to write as it is '
          + 'ground a person cannot stand on',
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
  /**
   * A facade's faces this version does not lay out. Its bays, its panels, its openings and the
   * returns into them are drawn; what waits here is the sill and head bands an opening grid states,
   * the string courses and the cornice, the awning, and the entrance, which is a record of its own.
   */
  facade_layout: 'facade_layout',
  /** A centreline or kerb line of more than one piece, or a kerb line not running with its centreline. */
  bent_street: 'bent_street',
  /** A segment's two curbs, carried by the tile, whose kerb lines leave its strip a length. */
  street_curbs: 'street_curbs',
  /** A junction leg whose segment, curbs or node the tile does not carry, so its mouth is unknown. */
  junction_legs: 'junction_legs',
  /** A corner that turns the other way, where the face wraps round it rather than being cut by it. */
  concave_corner: 'concave_corner',
  /** A crossing's band across its segment, from its line and width. */
  crossing_band: 'crossing_band',
  /** Road marking stripes, each a stated plan quad. */
  marking_stripes: 'marking_stripes',
  /** Object parts turned by their facing vector, with power-of-two chord bisection. */
  form_parts: 'form_parts',
} as const;
export type Need = (typeof NEEDS)[keyof typeof NEEDS];

export type Fields = { readonly [name: string]: unknown };

/** The surface roles this file names directly, each a closed value of the grammar's role fields. */
const LOT = 'lot';
const TREE_PIT = 'tree_pit';

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

/**
 * What a grammar's nav_envelope contract measures for a walking capsule: the radius it keeps clear
 * and the height below which a part of a record is in its way.
 */
export interface CapsuleClearance {
  readonly radiusMm: number;
  readonly heightMm: number;
}

/**
 * A region a standing capsule keeps its radius clear of, in plan, with the record it was read from.
 *
 * A ROUTE OBSTRUCTION RING, FROM THE NAVIGATION SIDE, AND NOT A COLLISION SOLID. It drops
 * everything standing above the capsule height by design, it is a plan region with NO HEIGHT, and
 * nothing in it stops a body: it says which way a walk can face, not what a walk can pass through.
 * A reader wanting solid occupancy wants `collision_proxy`, which has no contract yet; the
 * nav_envelope contract refuses collision in as many words, and a ring promoted quietly to a solid
 * would make a bench into a building.
 */
export interface ObstructionRegion {
  /** The record kind that obstructs, for the message when a ring is refused. */
  readonly kind: string;
  /**
   * The identity of the record it came from, so a reader can bind what a walk passed to the record
   * that put it there rather than to a shape with no name.
   */
  readonly identity: string;
  /** The ring itself, as the navigation table's obstruction axis names it. */
  readonly ring: readonly Plan[];
}

/** What an expander may read beyond its own record. */
export interface ExpandContext {
  /** The tile record's `tile_size_mm`. */
  readonly tileSizeMm: number;
  /**
   * Every region the navigation table says obstructs a walking capsule, from every record in the
   * document, owned or halo: a `base_ring` record's base ring, and one region for each part of a
   * `low_parts` record that stands below the capsule height.
   */
  readonly obstructions: readonly ObstructionRegion[];
  /**
   * The record's own stated plan extent, which its geometry must lie inside. A carve holds its
   * answer to this, since a hull round a carved face may otherwise reach a millimetre past it.
   */
  readonly extent: PlanBox | undefined;
  /**
   * The resolution the projection being expanded states in the record's grammar: how far a chord
   * may stand off the curve it stands for. A rule that cuts an arc reads it rather than choosing.
   */
  readonly resolutionMm: number;
  /**
   * The capsule radius the record's grammar measures for `nav_envelope`'s `capsule_clearance`, or
   * undefined when it measures none, which an expander claiming clearance refuses. Only the radius:
   * the carve is in plan, and the height has already chosen which of a record's parts obstruct.
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
  | {
      readonly state: 'drawn';
      readonly pieces: readonly Piece[];
      /**
       * The ground the record takes from terrain, when that is not the ground it draws. A support
       * surface is carved clear of what obstructs a capsule, and the holes that leaves are still
       * the record's ground: a footway with a tree standing in it is the footway's, and terrain
       * that drew under the tree would put a patch of hillside in the middle of a pavement. So a
       * carve reports what it covered as well as what it kept, and terrain yields to the first.
       */
      readonly covers?: readonly Piece[];
    }
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
  return { state: 'drawn', pieces: [pieceOf(kept)], covers: [pieceOf(surfaces)] };
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

/**
 * A curb's kerb face, kerb top and footway, by the street rules. The kerb line is digitised in its
 * segment's direction and every width is a field of the curb, so the rule needs the segment the
 * curb names and nothing else.
 */
function curbPieces(fields: Fields, context: ExpandContext, where: string): StreetResult<'bent_street' | CornerNeed> {
  const segment = context.carried.get(fields.segment_identity as string);
  if (segment === undefined) throw new TessellationError(`${where} names a segment the tile does not carry`);
  if (segment.kind !== 'city.street_segment') throw new TessellationError(`${where} names ${segment.kind} as its segment`);
  return curbSurfaces(fields, segment.fields, cornersOf(fields, context, where), approachesOf(fields, context), where);
}

/**
 * The curbs whose corner ends at this one's start: the carried curbs that name it as their
 * follower. A curb's own strip gives way on a mitre its PREDECESSOR owns, so it has to find it.
 */
function approachesOf(fields: Fields, context: ExpandContext): ApproachContext[] {
  const identity = fields.identity as string;
  const owners: ApproachContext[] = [];
  for (const record of context.carried.values()) {
    if (record.kind !== 'city.curb_edge') continue;
    if (!(record.fields.next_curb_identity as readonly string[]).includes(identity)) continue;
    owners.push({ owner: record.fields });
  }
  return owners;
}

/**
 * The corner a curb owns for each curb it names as its follower, with the rings of the blocks it
 * names. A curb that names no follower turns no corner; one that names a follower the tile does
 * not carry is refused rather than drawn short, since the corner is its own geometry and half of a
 * record is not a record.
 */
function cornersOf(fields: Fields, context: ExpandContext, where: string): CornerContext[] {
  const blocks: Plan[][] = [];
  for (const identity of fields.block_identity as readonly string[]) {
    const block = context.carried.get(identity);
    if (block === undefined) continue;
    if (block.kind !== 'city.block') throw new TessellationError(`${where} names ${block.kind} as a block`);
    blocks.push(block.fields.boundary_mm as Plan[]);
  }
  return (fields.next_curb_identity as readonly string[]).map((identity) => {
    const follower = context.carried.get(identity);
    if (follower === undefined) throw new TessellationError(`${where} names a following curb the tile does not carry`);
    if (follower.kind !== 'city.curb_edge') throw new TessellationError(`${where} names ${follower.kind} as its following curb`);
    return { follower: follower.fields, blocks, resolutionMm: context.resolutionMm };
  });
}

/** How the street rules find the records a junction names: the tile's carried records only. */
function streetLookup(context: ExpandContext): StreetLookup {
  return {
    record: (identity: string): StreetFields | undefined => context.carried.get(identity)?.fields,
    curbs: (segment: string) => ({ left: curbOf(context, segment, 'left'), right: curbOf(context, segment, 'right') }),
  };
}

/** A junction's carriageway, filled between its legs' mouths and round each corner's fillet arc. */
function junctionPieces(fields: Fields, context: ExpandContext, where: string): StreetResult<StripNeed | 'junction_legs'> {
  return junctionSurface(fields, streetLookup(context), context.resolutionMm, where);
}

/** A junction as it is drawn: the carriageway that fills it. */
function renderJunction(fields: Fields, context: ExpandContext): Expansion {
  const where = `city.junction ${fields.identity as string}`;
  const result = junctionPieces(fields, context, where);
  if (result.state === 'waiting') return { state: 'unavailable', needs: [result.need] };
  return { state: 'drawn', pieces: result.pieces };
}

/** A junction's carriageway is ground a person walks on, carved clear of what obstructs. */
function supportJunction(fields: Fields, context: ExpandContext): Expansion {
  const where = `city.junction ${fields.identity as string}`;
  const result = junctionPieces(fields, context, where);
  if (result.state === 'waiting') return { state: 'unavailable', needs: [result.need] };
  const surfaces: SupportTriangle[] = [];
  for (const piece of result.pieces) {
    if (piece.surface?.orientation !== 'horizontal') continue;
    for (const triangle of spaceTriangles(piece.vertices, piece.triangles)) surfaces.push(triangle);
  }
  return carvedSupport(surfaces, context, where);
}

/** A curb as it is drawn: its face, its top and its footway. */
function renderCurb(fields: Fields, context: ExpandContext): Expansion {
  const where = `city.curb_edge ${fields.identity as string}`;
  const result = curbPieces(fields, context, where);
  if (result.state === 'waiting') return { state: 'unavailable', needs: [result.need] };
  return { state: 'drawn', pieces: result.pieces };
}

/** A curb's kerb top and footway are ground a person walks on, carved clear of what obstructs. */
function supportCurb(fields: Fields, context: ExpandContext): Expansion {
  const where = `city.curb_edge ${fields.identity as string}`;
  const result = curbPieces(fields, context, where);
  if (result.state === 'waiting') return { state: 'unavailable', needs: [result.need] };
  const surfaces: SupportTriangle[] = [];
  for (const piece of result.pieces) {
    if (piece.surface?.orientation !== 'horizontal') continue;
    for (const triangle of spaceTriangles(piece.vertices, piece.triangles)) surfaces.push(triangle);
  }
  return carvedSupport(surfaces, context, where);
}

/** Every record of a kind the tile carries whose named field holds an identity. */
function carriedWhere(context: ExpandContext, kind: string, field: string, identity: string): Fields[] {
  const found: Fields[] = [];
  for (const record of context.carried.values()) {
    if (record.kind !== kind) continue;
    if (record.fields[field] !== identity) continue;
    found.push(record.fields);
  }
  return found;
}

/**
 * A building's own walls, roofs, terraces and parapets, by the massing rule (`massing.ts`), less
 * every part of a tier edge a facade of this building draws over.
 */
function renderMassing(fields: Fields, context: ExpandContext): Expansion {
  const massing = fields as unknown as MassingFields;
  const where = `city.massing ${fields.identity as string}`;
  const covers: FaceCover[] = carriedWhere(context, 'city.facade', 'building_identity', fields.identity as string)
    .map((facade) => faceCover(facade as unknown as FacadeFields, massing, where));
  const pieces = massingPieces(massing, covers, where);
  if (pieces.length === 0) return { state: 'unavailable', needs: [NEEDS.ground_coverage] };
  return { state: 'drawn', pieces };
}

/**
 * Where an object stands and which way it faces. A street tree states no facing vector, so its
 * local frame faces east, which is how `exulanica.world.society_city_place` reads the same parts.
 */
function objectFrame(fields: Fields): Omit<FormObject, 'parts'> {
  const stated = fields.facing_dx_mm;
  return {
    xMm: fields.x_mm as number,
    yMm: fields.y_mm as number,
    zMm: fields.z_mm as number,
    facingDxMm: stated === undefined ? 1 : stated as number,
    facingDyMm: stated === undefined ? 0 : fields.facing_dy_mm as number,
  };
}

/** An object's parts as the form parts rule takes them, field for field. */
function formParts(fields: Fields): FormPart[] {
  return (fields.parts as readonly Fields[]).map((part) => ({
    shape: part.shape as FormShape,
    surfaceRole: part.surface_role as string,
    offsetXMm: part.offset_x_mm as number,
    offsetYMm: part.offset_y_mm as number,
    offsetZMm: part.offset_z_mm as number,
    sizeXMm: part.size_x_mm as number,
    sizeYMm: part.size_y_mm as number,
    sizeZMm: part.size_z_mm as number,
    topScaleMillionths: part.top_scale_millionths as number,
    segments: part.segments as number,
    rings: part.rings as number,
  }));
}

/** An object's triangles by the form parts rule, with its refusal said in this tessellator's terms. */
function formTriangles(object: FormObject, where: string): readonly FormTriangle[] {
  try {
    return expandFormParts(object);
  } catch (refusal) {
    if (refusal instanceof FormPartsRefusal) throw new TessellationError(`${where}: ${refusal.message}`);
    throw refusal;
  }
}

/** The triangles of an object's parts, gathered into one surface per role and orientation. */
function objectPieces(object: FormObject, where: string): Piece[] {
  const triangles = formTriangles(object, where);
  const surfaces = new Map<string, Surface>();
  for (const triangle of triangles) {
    const key = `${triangle.surfaceRole} ${triangle.orientation}`;
    let surface = surfaces.get(key);
    if (surface === undefined) {
      surface = new Surface(triangle.surfaceRole, triangle.orientation);
      surfaces.set(key, surface);
    }
    const held = surface;
    held.face(...triangle.vertices.map((vertex) => held.corner([vertex.xMm, vertex.yMm], vertex.zMm, vertex.sMm, vertex.tMm)));
  }
  return piecesOf([...surfaces.values()]);
}

/** An object that states where it stands and which way it faces: furniture, a rooftop object. */
function renderObject(fields: Fields, kind: string): Expansion {
  const where = `${kind} ${fields.identity as string}`;
  const pieces = objectPieces({ ...objectFrame(fields), parts: formParts(fields) }, where);
  if (pieces.length === 0) return { state: 'unavailable', needs: [NEEDS.form_parts] };
  return { state: 'drawn', pieces };
}

/**
 * A vitrine's fitout. A vitrine states no point and no facing: its frame is the facade it sits in,
 * `x` along the run, `y` into the building and `z` up from the sill (`city.vitrine`). The run
 * direction is the facing, and no negation is needed for the rule's "+y is to the left": a ring is
 * counter-clockwise, which `exulanica.grammar.geometry` refuses a ring for not being, so walking a
 * tier edge in its stated order keeps the building's interior on the left.
 */
function renderVitrine(fields: Fields, context: ExpandContext): Expansion {
  const where = `city.vitrine ${fields.identity as string}`;
  const facade = facadeOf(fields.facade_identity as string, context, where);
  const { frame } = faceFrameOf(facade, context, where);
  const at = alongEdge(frame.from, frame.to, fields.u_start_mm as number, frame.run, where);
  const pieces = objectPieces({
    xMm: at[0],
    yMm: at[1],
    zMm: add(frame.datum, fields.sill_mm as number, where),
    facingDxMm: subtract(frame.to[0], frame.from[0], where),
    facingDyMm: subtract(frame.to[1], frame.from[1], where),
    parts: formParts(fields),
  }, where);
  if (pieces.length === 0) return { state: 'unavailable', needs: [NEEDS.form_parts] };
  return { state: 'drawn', pieces };
}

/** A lot: a parcel's boundary at the grade it states, as one horizontal surface. */
function renderParcel(fields: Fields): Expansion {
  const where = `city.parcel ${fields.identity as string}`;
  const pieces = groundPieces(fields.boundary_mm as readonly Plan[], fields.grade_elevation_mm as number, LOT, [], where);
  if (pieces.length === 0) return { state: 'unavailable', needs: [NEEDS.ground_coverage] };
  return { state: 'drawn', pieces };
}

/**
 * A block's own ground, less the parcels that name it. A parcel always draws the boundary it
 * states, since its rule refuses rather than waits, so a parcel the tile carries is a parcel that
 * is drawn and this yields to drawn ground rather than to a stated extent.
 */
function renderBlock(fields: Fields, context: ExpandContext): Expansion {
  const where = `city.block ${fields.identity as string}`;
  const parcels = carriedWhere(context, 'city.parcel', 'block_identity', fields.identity as string)
    .map((parcel) => parcel.boundary_mm as readonly Plan[]);
  const pieces = groundPieces(fields.boundary_mm as readonly Plan[], fields.grade_elevation_mm as number, LOT, parcels, where);
  if (pieces.length === 0) return { state: 'unavailable', needs: [NEEDS.ground_coverage] };
  return { state: 'drawn', pieces };
}

/**
 * A street tree: the pit it stands in, and its own parts. It states no facing vector, so its local
 * frame faces east, which is how `exulanica.world.society_city_place` reads the same parts.
 */
function renderTree(fields: Fields): Expansion {
  const where = `city.street_tree ${fields.identity as string}`;
  const pit = groundPieces(fields.pit_mm as readonly Plan[], fields.z_mm as number, TREE_PIT, [], where);
  const parts = objectPieces({ ...objectFrame(fields), parts: formParts(fields) }, where);
  const pieces = [...pit, ...parts];
  if (pieces.length === 0) return { state: 'unavailable', needs: [NEEDS.ring_triangulation, NEEDS.form_parts] };
  return { state: 'drawn', pieces };
}

/** A building's face on one tier edge, by the facade rule (`facades.ts`). */
/**
 * The tier edge a face is laid out on, and the heights it sits at. Derived ONCE and read by the
 * facade itself and by every record laid out in its frame, because two derivations of one frame is
 * a disagreement waiting to happen: a vitrine, a backing and the face must all take the same edge.
 */
function faceFrameOf(facade: FacadeFields, context: ExpandContext, where: string): { massing: MassingFields; frame: FaceFrame } {
  const building = context.carried.get(facade.building_identity);
  if (building === undefined) throw new TessellationError(`${where} names a building the tile does not carry`);
  if (building.kind !== 'city.massing') throw new TessellationError(`${where} names ${building.kind} as its building`);
  const massing = building.fields as unknown as MassingFields;
  const tier = massing.tiers[facade.tier_ordinal];
  if (tier === undefined) throw new TessellationError(`${where} is laid out on a tier its building does not have`);
  const ring = tier.ring_mm;
  const from = ring[facade.edge_ordinal];
  if (from === undefined) throw new TessellationError(`${where} is laid out on an edge its tier does not have`);
  const to = ring[(facade.edge_ordinal + 1) % ring.length]!;
  const heights = faceHeights(facade, massing, where);
  return {
    massing,
    frame: { from, to, run: runOf(from, to, where), datum: massing.base_elevation_mm, base: heights.base, top: heights.top },
  };
}

/** The facade a record laid out on a face names, which the tile must carry for it to be drawn. */
function facadeOf(identity: string, context: ExpandContext, where: string): FacadeFields {
  const carried = context.carried.get(identity);
  if (carried === undefined) throw new TessellationError(`${where} names a facade the tile does not carry`);
  if (carried.kind !== 'city.facade') throw new TessellationError(`${where} names ${carried.kind} as its facade`);
  return carried.fields as unknown as FacadeFields;
}

function renderFacade(fields: Fields, context: ExpandContext): Expansion {
  const facade = fields as unknown as FacadeFields;
  const where = `city.facade ${facade.identity}`;
  const { massing, frame } = faceFrameOf(facade, context, where);
  const bays = carriedWhere(context, 'city.ground_bay', 'facade_identity', facade.identity) as unknown as GroundBayFields[];
  const pieces = facadePieces(facade, massing, frame, bays, context.resolutionMm, where);
  if (pieces.length === 0) throw new TessellationError(`${where} draws no face, which its run and storeys should not allow`);
  return { state: 'drawn', pieces };
}

/**
 * The plane behind one face's glass, by the backing rule (`facades.ts`). Without it a building is
 * see-through: upper glazing has nothing behind it and a person looks through a first floor window
 * and out of the far side of the terrace.
 */
function renderBacking(fields: Fields, context: ExpandContext): Expansion {
  const backing = fields as unknown as BackingFields;
  const where = `city.interior_backing ${backing.identity}`;
  const facade = facadeOf(backing.facade_identity, context, where);
  if (facade.building_identity !== backing.building_identity) {
    throw new TessellationError(`${where} names one building and its facade names another`);
  }
  const { frame } = faceFrameOf(facade, context, where);
  const pieces = backingPieces(backing, facade, frame, where);
  if (pieces.length === 0) throw new TessellationError(`${where} draws no plane, which its width and height should not allow`);
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
  ['city.block', {
    render_batch: { rule: 'expand', expand: renderBlock, readsCoverings: false },
    nav_envelope: needs(NEEDS.ring_triangulation),
  }],
  ['city.crossing', { render_batch: needs(NEEDS.crossing_band), nav_envelope: needs(NEEDS.crossing_band) }],
  ['city.curb_edge', {
    render_batch: { rule: 'expand', expand: renderCurb, readsCoverings: false },
    nav_envelope: { rule: 'expand', expand: supportCurb, readsCoverings: false },
  }],
  ['city.district', { render_batch: notInProjection, nav_envelope: notInProjection }],
  ['city.entrance', { render_batch: needs(NEEDS.facade_layout), nav_envelope: needs(NEEDS.facade_layout) }],
  ['city.facade', {
    render_batch: { rule: 'expand', expand: renderFacade, readsCoverings: false },
    nav_envelope: notInProjection,
  }],
  // A ground bay draws as part of its facade's ground band, in the facade's own entry, because the
  // material records that dress its panels name the facade and the panel's surface role.
  ['city.ground_bay', { render_batch: notInProjection, nav_envelope: notInProjection }],
  ['city.junction', {
    render_batch: { rule: 'expand', expand: renderJunction, readsCoverings: false },
    nav_envelope: { rule: 'expand', expand: supportJunction, readsCoverings: false },
  }],
  // A room's near wall inside its building, behind its glazing: laid out on its facade, standing on
  // nothing, so it is no more a surface of the ground than the vitrine beside it.
  ['city.interior_backing', {
    render_batch: { rule: 'expand', expand: renderBacking, readsCoverings: false },
    nav_envelope: notInProjection,
  }],
  ['city.junction_approach', { render_batch: notInProjection, nav_envelope: notInProjection }],
  // A lane is a path on its segment's carriageway, and draws as that carriageway.
  ['city.lane', { render_batch: notInProjection, nav_envelope: notInProjection }],
  ['city.lane_connection', { render_batch: notInProjection, nav_envelope: notInProjection }],
  // A building stands nobody on itself and covers the ground it stands on, which the navigation
  // table states as ground `cover`: it is no surface of the navigation projection at all.
  ['city.massing', {
    render_batch: { rule: 'expand', expand: renderMassing, readsCoverings: false },
    nav_envelope: notInProjection,
  }],
  ['city.parcel', {
    render_batch: { rule: 'expand', expand: renderParcel, readsCoverings: false },
    nav_envelope: needs(NEEDS.ring_triangulation),
  }],
  // A space on a carriageway or a footway draws as that surface; its bay lines are markings.
  ['city.parking_space', { render_batch: notInProjection, nav_envelope: notInProjection }],
  // An occupancy draws as its building's faces.
  ['city.premises', { render_batch: notInProjection, nav_envelope: notInProjection }],
  ['city.road_marking', { render_batch: needs(NEEDS.marking_stripes), nav_envelope: notInProjection }],
  ['city.rooftop_object', {
    render_batch: { rule: 'expand', expand: (fields: Fields): Expansion => renderObject(fields, 'city.rooftop_object'), readsCoverings: false },
    nav_envelope: notInProjection,
  }],
  ['city.signal', { render_batch: notInProjection, nav_envelope: notInProjection }],
  // A named street draws as its segments.
  ['city.street', { render_batch: notInProjection, nav_envelope: notInProjection }],
  ['city.street_furniture', {
    render_batch: { rule: 'expand', expand: (fields: Fields): Expansion => renderObject(fields, 'city.street_furniture'), readsCoverings: false },
    nav_envelope: notInProjection,
  }],
  // A node draws as its junction or its segments' ends.
  ['city.street_node', { render_batch: notInProjection, nav_envelope: notInProjection }],
  ['city.street_segment', {
    render_batch: { rule: 'expand', expand: renderSegment, readsCoverings: false },
    nav_envelope: { rule: 'expand', expand: supportSegment, readsCoverings: false },
  }],
  // A tree's parts, and its pit, which is ground a person may stand on.
  ['city.street_tree', {
    render_batch: { rule: 'expand', expand: (fields: Fields): Expansion => renderTree(fields), readsCoverings: false },
    nav_envelope: needs(NEEDS.ring_triangulation),
  }],
  // A material is not a surface. A drawn range cites it; it draws nothing of its own.
  ['city.surface_material', { render_batch: notInProjection, nav_envelope: notInProjection }],
  ['city.terrain', {
    render_batch: { rule: 'expand', expand: renderTerrain, readsCoverings: true },
    nav_envelope: { rule: 'expand', expand: supportTerrain, readsCoverings: true },
  }],
  ['city.vitrine', {
    render_batch: { rule: 'expand', expand: renderVitrine, readsCoverings: false },
    nav_envelope: notInProjection,
  }],
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
 * What a grammar measures for the walking capsule of `nav_envelope`'s `capsule_clearance`: the
 * radius a support surface is carved clear by, and the height below which a record's part stands in
 * a person's way rather than over their head. Undefined when the grammar measures neither.
 */
export function capsuleOf(table: GrammarTable): CapsuleClearance | undefined {
  const clearance = table.measures.nav_envelope?.capsule_clearance;
  if (clearance === undefined) return undefined;
  const radiusMm = clearance.radius_mm;
  const heightMm = clearance.height_mm;
  if (radiusMm === undefined) throw new TessellationError(`${table.grammar_id} measures a capsule clearance with no radius`);
  if (heightMm === undefined) throw new TessellationError(`${table.grammar_id} measures a capsule clearance with no height`);
  return { radiusMm, heightMm };
}

/**
 * The regions one record obstructs a walking capsule with, by the navigation table's obstruction
 * axis, and none when it obstructs nothing. A base ring is the ring itself, one region. Low parts
 * are one region each: every part of the record whose bottom stands below the capsule height, in
 * its own place, so what a person walks round is the part and not the record.
 */
export function obstructionsOf(
  kind: string,
  region: string,
  fields: Fields,
  capsule: CapsuleClearance | undefined,
  where: string,
): ObstructionRegion[] {
  const identity = fields.identity as string;
  if (region === 'none') return [];
  if (region === 'base_ring') return [{ kind, identity, ring: baseRingOf(kind, fields) }];
  if (region === 'low_parts') {
    if (capsule === undefined) {
      throw new TessellationError(`${kind} obstructs with its low parts and its grammar measures no capsule to call them low by`);
    }
    // A LOW PART, not the record's extent. The grammar says which: each part whose bottom lies
    // below the capsule height above the record's base point. A street tree's trunk is one; its
    // canopy is not, since the grammar holds a canopy a capsule height above what it overhangs, and
    // taking the extent instead took the canopy's whole width of footway away from the person
    // underneath it. Each part's own plan region is the hull of the triangles the form parts rule
    // makes of it, so the frame that turns a part is derived once and drawn and carved from alike.
    const regions: ObstructionRegion[] = [];
    formParts(fields).forEach((part, ordinal) => {
      if (part.offsetZMm >= capsule.heightMm) return;
      const points: Plan[] = [];
      for (const triangle of formTriangles({ ...objectFrame(fields), parts: [part] }, where)) {
        for (const vertex of triangle.vertices) points.push([vertex.xMm, vertex.yMm]);
      }
      const ring = hullKeepingEdges(points, where);
      // A part standing in a person's way whose plan region has no area would be walked through,
      // so it is refused rather than passed over: every part this rule reads takes ground.
      if (ring.length < 3) throw new TessellationError(`${where}: part ${ordinal} stands below head height and covers no ground in plan`);
      regions.push({ kind, identity, ring });
    });
    return regions;
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
  // Every ground panel role the table states is a role this tessellator draws as some surface.
  for (const field of nestedShapeOf(table, 'GroundPanel').fields) {
    if (field.name !== 'role') continue;
    const values = field.values;
    if (values === undefined) continue;
    for (const role of values) {
      if (!panelRoles().includes(role)) throw new TessellationError(`a ground panel role ${role} this tessellator has no surface role for`);
    }
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
    if (row.obstruction === 'low_parts' && !recordShapeOf(table, row.kind)!.fields.some((field) => field.name === 'parts')) {
      throw new TessellationError(`${row.kind} obstructs with its low parts and states no parts to read them from`);
    }
    if (row.obstruction !== 'base_ring' && row.obstruction !== 'low_parts') {
      throw new TessellationError(`${row.kind} obstructs with ${row.obstruction}, a region this tessellator does not read`);
    }
  }
}
