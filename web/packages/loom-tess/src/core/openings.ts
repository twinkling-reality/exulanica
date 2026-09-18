/**
 * THE OPENING RULE: WHERE A FACE IS NOT THERE, AND HOW DEEP THE WALL IS AROUND IT.
 *
 * A facade states its openings as ONE GRID PER FACE rather than one record per window
 * (`exulanica.grammar.grammars.city.facade.OpeningGrid`), and the grid is a rule for repeating one
 * shape: in every bay of the face, at every storey the grid lists, an opening starts
 * `u_offset_mm` after that bay's start and is `width_mm` wide, its sill sits `sill_height_mm` above
 * that storey's floor, and it is `height_mm` tall to its head. So a face with five bays and two
 * storeys listed states TEN openings, and the count this rule draws is the bays times the storeys,
 * never the grids.
 *
 * WHAT IT PRODUCES, and both halves are needed for either to read as a hole:
 *
 *   1. AN OUTLINE, in the face's own `(u, z)` plane, turning counter-clockwise. The face is carved
 *      by these (`piece-carve.openRegions`), so the wall is what is left of it rather than a
 *      rectangle with something drawn over the part that should be missing. Where the grid states a
 *      rise the head is an arch through three points (`segmental-arch.ts`); where it states none the
 *      head is flat and the outline is four corners.
 *   2. A RETURN, `reveal_depth_mm` back into the wall all the way round that outline
 *      (`faces.revealOn`). Without it the wall has no thickness at the hole and a person sees the
 *      building's inside through an edge with nothing on it. The return takes the `trim` role, which
 *      is the role the grammar gives a facade's dressed edges and the one its material records
 *      already dress.
 *
 * THE OPENING IS CUT FROM THE WALL AND NOTHING ELSE, AND THE GRAMMAR DOES NOT GUARANTEE IT. The
 * grammar holds an opening inside its own bay and onto the face's upper storeys, which keeps it
 * clear of the ground band in `u` and in which storeys it sits on. It states NO rule that a sill
 * clears the top of the ground band, and none that a head and its rise stay under the storey's
 * ceiling: a band taller than the ground storey, or a window taller than the storey above it, passes
 * every check the grammar makes. So this rule refuses an opening that falls outside the rectangle of
 * wall the face draws, naming both heights, rather than letting the carve clip it quietly, because a
 * clipped opening is a smaller hole that looks deliberate. That refusal is vacuous over the corridor
 * city as it stands, which is a measurement of one corpus on one day and is recorded as one in this
 * package's evidence rather than asserted here.
 */
import { add, exact, GeometryError, multiply, subtract } from './integer-math.js';
import type { Plan } from './integer-math.js';
import { storeyFloorMm } from './massing.js';
import type { MassingFields } from './massing.js';
import { archHead } from './segmental-arch.js';

/** What this rule reads of one of a facade's opening grids. */
export interface OpeningGridFields {
  readonly storeys: readonly number[];
  readonly u_offset_mm: number;
  readonly width_mm: number;
  readonly height_mm: number;
  readonly sill_height_mm: number;
  readonly reveal_depth_mm: number;
  readonly head_rise_mm: number;
}

/** What this rule reads of a facade's bay layout. */
export interface BayLayoutFields {
  readonly count: number;
  readonly pitch_mm: number;
  readonly margin_start_mm: number;
}

/** One opening cut into a face: its outline in the face's `(u, z)` plane, and how deep it returns. */
export interface Opening {
  readonly outline: readonly Plan[];
  readonly revealDepthMm: number;
}

/** The rectangle of a face that openings are cut from: the wall, between the band and the top. */
export interface WallRegion {
  readonly run: number;
  readonly base: number;
  readonly top: number;
}

/**
 * One opening's outline in the face's `(u, z)` plane, counter-clockwise from its lower left corner:
 * the two sill corners, then the head, which is an arch from the right springing to the left where
 * the grid states a rise and the two head corners where it states none.
 */
export function openingOutline(
  uLeft: number,
  uRight: number,
  sillZ: number,
  headZ: number,
  rise: number,
  resolutionMm: number,
  where: string,
): Plan[] {
  if (uRight <= uLeft) throw new GeometryError(`${where} is ${String(subtract(uRight, uLeft, where))} mm wide`);
  if (headZ <= sillZ) throw new GeometryError(`${where} is ${String(subtract(headZ, sillZ, where))} mm tall`);
  const sill: Plan[] = [[uLeft, sillZ], [uRight, sillZ]];
  if (exact(rise, where) === 0) return [...sill, [uRight, headZ], [uLeft, headZ]];
  return [...sill, ...archHead(uLeft, uRight, headZ, rise, resolutionMm, where)];
}

/**
 * Every opening one grid states on one face, in the face's `(u, z)` plane: one per bay per storey,
 * by the rule above. `region` is the wall they are cut from, and an opening outside it is refused.
 */
export function gridOpenings(
  grid: OpeningGridFields,
  bays: BayLayoutFields,
  massing: MassingFields,
  region: WallRegion,
  resolutionMm: number,
  where: string,
): Opening[] {
  if (bays.count < 1) throw new GeometryError(`${where} states openings on a face with no bays`);
  const openings: Opening[] = [];
  for (const storey of grid.storeys) {
    const floor = storeyFloorMm(massing, storey, where);
    const sillZ = add(floor, grid.sill_height_mm, where);
    const headZ = add(sillZ, grid.height_mm, where);
    const crownZ = add(headZ, grid.head_rise_mm, where);
    if (sillZ < region.base) {
      throw new GeometryError(`${where} sits at ${String(sillZ)} mm on storey ${String(storey)}, below the ${String(region.base)} mm its face's wall starts at`);
    }
    if (crownZ > region.top) {
      throw new GeometryError(`${where} reaches ${String(crownZ)} mm on storey ${String(storey)}, above the ${String(region.top)} mm its face's wall ends at`);
    }
    for (let bay = 0; bay < bays.count; bay += 1) {
      const start = add(bays.margin_start_mm, multiply(bay, bays.pitch_mm, where), where);
      const uLeft = add(start, grid.u_offset_mm, where);
      const uRight = add(uLeft, grid.width_mm, where);
      if (uLeft < 0) {
        throw new GeometryError(`${where} starts at ${String(uLeft)} mm in bay ${String(bay)}, before its face's run begins`);
      }
      if (uRight > region.run) {
        throw new GeometryError(`${where} reaches ${String(uRight)} mm in bay ${String(bay)}, past the face's ${String(region.run)} mm run`);
      }
      const at = `${where} bay ${String(bay)} storey ${String(storey)}`;
      openings.push({
        outline: openingOutline(uLeft, uRight, sillZ, headZ, grid.head_rise_mm, resolutionMm, at),
        revealDepthMm: grid.reveal_depth_mm,
      });
    }
  }
  return openings;
}
