/**
 * THE FACADE RULE: THE FACE OF A BUILDING ON ONE TIER EDGE, IN INTEGERS.
 *
 * A facade states no line of its own. It states the TIER and the EDGE it is laid out on, so its
 * geometry is that edge of that tier of its building, and everything else it needs is a field:
 * positions are millimetres along the edge's run from its start vertex, and heights are millimetres
 * above the building's `base_elevation_mm` (`exulanica.grammar.grammars.city.facade`).
 *
 * WHAT THIS VERSION DRAWS:
 *
 *   1. THE FACE. The wall of the run, from the floor of its first storey to the ceiling of its
 *      last. Where the face includes storey 0 the ground band is not part of it: the band is
 *      `band_top_mm` tall and its bays draw it.
 *   2. THE GROUND BAND. Each ground bay tiles its own rectangle exactly with panels, each at its
 *      own recess and each taking the surface role the grammar gives its panel role. The part of
 *      the band no bay covers is the `ground_band` role, taken as intervals along the run.
 *   3. A PARTY WALL SCAR. Above `neighbour_top_mm` a party wall shows where the neighbour's profile
 *      met it, and that region takes the `party_wall_scar` role rather than `wall`.
 *
 *   4. THE PLANE BEHIND THE GLASS, for an interior backing record, which is laid out in this same
 *      frame and is a record of its own. See `backingPieces`.
 *
 * WHAT IT DOES NOT DRAW YET, each of which is additive and none of which this leaves a hole for:
 * openings with their reveals, sills and heads, which will be cut out of the face; string courses
 * and cornices, which are boxes projecting from it; awnings; and the entrance record, which is laid
 * out in this same frame and is a record of its own.
 *
 * THE FACE AND THE BUILDING'S OWN WALL ARE NEVER BOTH DRAWN. The massing rule draws a tier edge's
 * wall only where no facade of that building draws over it, taken as a rectangle in the edge's own
 * `(u, z)`: the facade's run by its storeys. So a facade replaces the wall it covers rather than
 * standing proud of it, which is what stops the two fighting for the same pixels.
 */
import { add, exact, GeometryError, subtract } from './integer-math.js';
import type { Plan } from './integer-math.js';
import { faceOn, piecesOf, Surface, VERTICAL } from './faces.js';
import type { FaceCover } from './faces.js';
import type { Piece } from './pieces.js';
import { storeyFloorMm } from './massing.js';
import type { MassingFields } from './massing.js';

/** The tier edge a facade is laid out on, and the heights its storeys sit at. */
export interface FaceFrame {
  readonly from: Plan;
  readonly to: Plan;
  readonly run: number;
  /** The building's `base_elevation_mm`: the datum every height on the face is above. */
  readonly datum: number;
  readonly base: number;
  readonly top: number;
}

/** A rectangular panel of a ground bay, in the face's frame. */
export interface GroundPanel {
  readonly role: string;
  readonly u_start_mm: number;
  readonly u_end_mm: number;
  readonly z_bottom_mm: number;
  readonly z_top_mm: number;
  readonly recess_mm: number;
}

/** What this rule reads of a ground bay record. */
export interface GroundBayFields {
  readonly facade_identity: string;
  readonly u_start_mm: number;
  readonly width_mm: number;
  readonly panels: readonly GroundPanel[];
}

/** What this rule reads of a facade record. */
export interface FacadeFields {
  readonly identity: string;
  readonly building_identity: string;
  readonly tier_ordinal: number;
  readonly edge_ordinal: number;
  readonly exposure: string;
  readonly run_length_mm: number;
  readonly first_storey: number;
  readonly last_storey: number;
  readonly band_top_mm: number;
  readonly neighbour_top_mm: number;
}

const WALL = 'wall';
const GROUND_BAND = 'ground_band';
const PARTY_WALL_SCAR = 'party_wall_scar';
const PARTY_WALL = 'party_wall';

/** What this rule reads of an interior backing record (`exulanica.grammar.grammars.city.vitrine`). */
export interface BackingFields {
  readonly identity: string;
  readonly facade_identity: string;
  readonly building_identity: string;
  readonly u_start_mm: number;
  readonly width_mm: number;
  readonly sill_mm: number;
  readonly height_mm: number;
  readonly depth_mm: number;
}

/**
 * THE PLANE BEHIND A FACE'S GLASS: one rectangle in the face's own frame, `depth_mm` back from the
 * face's outer plane, from `sill_mm` to `sill_mm + height_mm` above the BUILDING'S base, and
 * `width_mm` along the run from `u_start_mm`.
 *
 * One plane per face and not one per window, which is the grammar's decision and its reason: "the
 * rooms behind a face are a floor of rooms and not a box per opening", and "a plane a person can
 * never walk to needs no more detail than closing the view". It faces the way the face does, since
 * it is seen from the street through the glass, and it takes the `wall` role, which is the role the
 * grammar's material table gives an interior backing.
 *
 * It states `light_level_millionths` and this rule carries it nowhere. A container states no light,
 * so there is no field for it to reach; putting it somewhere would be a number appearing in
 * geometry that no record put there. When light belongs in a container it arrives as a stated field
 * with a version of its own.
 */
export function backingPieces(backing: BackingFields, facade: FacadeFields, frame: FaceFrame, where: string): Piece[] {
  const end = add(backing.u_start_mm, backing.width_mm, where);
  if (end > facade.run_length_mm) {
    throw new GeometryError(`${where} reaches ${String(end)} mm along a face whose run is ${String(facade.run_length_mm)} mm`);
  }
  const base = add(frame.datum, backing.sill_mm, where);
  const surface = new Surface(WALL, VERTICAL);
  faceOn(
    surface,
    { from: frame.from, to: frame.to, run: frame.run },
    backing.u_start_mm,
    end,
    base,
    add(base, backing.height_mm, where),
    subtract(0, backing.depth_mm, where),
    frame.datum,
    where,
  );
  return piecesOf([surface]);
}

/**
 * What a ground panel's role is a surface of, which the grammar fixes
 * (`exulanica.grammar.grammars.city.facade.PANEL_SURFACE_ROLES`). A panel role this tessellator
 * has no surface role for is refused rather than dressed as something else.
 */
const PANEL_SURFACE_ROLES: ReadonlyMap<string, string> = new Map([
  ['stall_riser', 'stall_riser'],
  ['glazing', 'glazing'],
  ['transom', 'glazing'],
  ['fascia', 'fascia'],
  ['wall', GROUND_BAND],
  ['frame', 'shopfront_frame'],
  ['door', 'door'],
]);

/** The surface role a panel role is drawn as, or a refusal naming the role. */
export function panelSurfaceRole(role: string, where: string): string {
  const surface = PANEL_SURFACE_ROLES.get(role);
  if (surface === undefined) throw new RangeError(`${where}: a ground panel whose role ${role} this tessellator has no surface role for`);
  return surface;
}

/** Every panel role the grammar states, so a table that adds one is refused at load. */
export function panelRoles(): readonly string[] {
  return [...PANEL_SURFACE_ROLES.keys()];
}

/** The storeys of a face, as heights above the datum. */
export function faceHeights(facade: FacadeFields, massing: MassingFields, where: string): { base: number; top: number } {
  return {
    base: storeyFloorMm(massing, facade.first_storey, where),
    top: storeyFloorMm(massing, add(facade.last_storey, 1, where), where),
  };
}

/** The rectangle of its tier edge a facade covers, which the building's own wall gives up. */
export function faceCover(facade: FacadeFields, massing: MassingFields, where: string): FaceCover {
  const heights = faceHeights(facade, massing, where);
  return {
    tier: facade.tier_ordinal,
    edge: facade.edge_ordinal,
    low: 0,
    high: exact(facade.run_length_mm, where),
    base: heights.base,
    top: heights.top,
  };
}

/** The intervals of `[0, run]` that no bay covers, in order. */
function openAlong(run: number, bays: readonly GroundBayFields[], where: string): [number, number][] {
  const covered = bays
    .map((bay): [number, number] => [bay.u_start_mm, add(bay.u_start_mm, bay.width_mm, where)])
    .sort((first, second) => first[0] - second[0]);
  const open: [number, number][] = [];
  let at = 0;
  for (const [low, high] of covered) {
    if (low > at) open.push([at, low]);
    if (high > at) at = high;
  }
  if (at < run) open.push([at, run]);
  return open;
}

/**
 * A building's face on one tier edge, by the rule above. `frame` is that edge with the heights the
 * face's storeys sit at, and `bays` are the ground bay records that name this facade.
 */
export function facadePieces(
  facade: FacadeFields,
  frame: FaceFrame,
  bays: readonly GroundBayFields[],
  where: string,
): Piece[] {
  const edge = { from: frame.from, to: frame.to, run: frame.run };
  const wall = new Surface(WALL, VERTICAL);
  const band = new Surface(GROUND_BAND, VERTICAL);
  const scar = new Surface(PARTY_WALL_SCAR, VERTICAL);
  const panels = new Map<string, Surface>();
  const run = exact(facade.run_length_mm, where);
  // The ground band belongs to the bays; the face above it is the wall, up to the neighbour's top
  // on a party wall and in the scar's role above that.
  const banded = facade.first_storey === 0;
  const bandTop = banded ? add(frame.base, facade.band_top_mm, where) : frame.base;
  const party = facade.exposure === PARTY_WALL;
  const scarBase = party ? add(frame.datum, facade.neighbour_top_mm, where) : frame.top;
  const walled = scarBase < bandTop ? bandTop : scarBase;
  faceOn(wall, edge, 0, run, bandTop, walled > frame.top ? frame.top : walled, 0, frame.datum, where);
  if (party) faceOn(scar, edge, 0, run, walled, frame.top, 0, frame.datum, where);

  if (banded) {
    for (const [low, high] of openAlong(run, bays, where)) {
      faceOn(band, edge, low, high, frame.base, bandTop, 0, frame.datum, where);
    }
    for (const bay of bays) {
      for (const panel of bay.panels) {
        const role = panelSurfaceRole(panel.role, where);
        let surface = panels.get(role);
        if (surface === undefined) {
          surface = new Surface(role, VERTICAL);
          panels.set(role, surface);
        }
        faceOn(
          role === GROUND_BAND ? band : surface,
          edge,
          panel.u_start_mm,
          panel.u_end_mm,
          add(frame.base, panel.z_bottom_mm, where),
          add(frame.base, panel.z_top_mm, where),
          subtract(0, panel.recess_mm, where),
          frame.datum,
          where,
        );
      }
    }
  }
  const drawn = [wall, band, scar];
  for (const role of [...panels.keys()].sort()) {
    if (role === GROUND_BAND) continue;
    drawn.push(panels.get(role)!);
  }
  return piecesOf(drawn);
}
