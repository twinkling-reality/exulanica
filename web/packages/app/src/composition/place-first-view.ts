/**
 * Where a person first stands and looks in a place (a world made from a world kind), so the first look
 * is of the place, of its land's water where its land holds a sea, and never of a wall a few steps away.
 *
 * A place is served one arrival: on its first path just inside its south edge, facing north into it
 * (`exulanica/world/composers/site_plan.py`), whatever its land. On a coast the sea lies south of the
 * place, behind that arrival, and between a place's first two buildings, or between two yards graded above
 * its path, the arrival looks along a lane walled on both sides. The view here is judged by the towns'
 * figures (`TOWN_FIRST_VIEW`, version 7) and the place's own (`PLACE_FIRST_VIEW`,
 * `assets/catalogs/arrival/place-first-view.v1.json`), each stated with its reason:
 *
 * - **A view is clear** where nothing at eye height stands nearer than the centre floor across the
 *   frame's middle third, the place's buildings nearer than `nearFace.nearMm` show across at most
 *   `nearFace.shareMost` of its width and, being windowless, nearer than `wallNearMm` across at most
 *   `wallShareMost`, and nothing else at eye height stands nearer than `nearFace.postMm` anywhere in it.
 *   On land a bank or the side of a cut that rises above the eye stands in a view as a wall does.
 * - **Where the land holds a sea**, a clear view showing open water as a town's seafront view must, with
 *   at least `structuresLeast` of the place's buildings each met first by `structureLinesLeast` of its
 *   sight lines within `structureReachMm` inside the frame's middle `structureFrameShare` (a place of
 *   fewer buildings shows every one of them whole), is taken: the water with the place in it, never with
 *   the place behind. Of those, the one with the most buildings in view up to `structuresMostCounted`,
 *   then the most water, then from the spot nearest the arrival, then turned least from its way.
 * - **Otherwise** the clear view from the spot nearest the arrival that looks across the place, its
 *   middle within `acrossOffMost` of the frame's, turned least from that.
 * - Where no view is clear, the arrival as served.
 *
 * The spots tried are the arrival, steps of `backStepMm` back from it as far as `placed.outReachMm`, and
 * spots round the place's edge, `alongStepMm` inside it (the walk has no ground beyond a place), at least
 * twice that apart and at most `edgeSpotsMost` in all, each where a person can stand; the ways are every
 * `wayStep` round. Everything is in the place's plan frame, as its sight rings are (`siteSightRings`):
 * millimetres east and south of its south-west corner.
 */
import { nearFaceShare, nearestInWedge, openDistance, waterInView, type SeaSight, type SightBlocker } from './arrival-view.js';
import type { OpenViewRule } from '../town-first-view.js';
import catalogText from '../../../../../assets/catalogs/arrival/place-first-view.v1.json?raw';

/** The place's own first-view figures, as `place-first-view.v1.json` states them: angles in radians, lengths in millimetres. */
export interface PlaceViewRule {
  readonly wayStep: number;
  readonly edgeSpotsMost: number;
  readonly structuresLeast: number;
  readonly structureLinesLeast: number;
  readonly structureLineStep: number;
  readonly structureReachMm: number;
  readonly structureFrameShare: number;
  readonly structuresMostCounted: number;
  readonly wallNearMm: number;
  readonly wallShareMost: number;
  readonly acrossOffMost: number;
  readonly landColumn: number;
  readonly landStepMm: number;
}

const PROFILE = 'exulanica.place-first-view/v1';

/** The figures a place first-view catalog file states; a file that states other or fewer is refused. */
export function placeViewRule(text: string): PlaceViewRule {
  const document = JSON.parse(text) as { profile?: unknown; entries?: unknown };
  if (document.profile !== PROFILE || !Array.isArray(document.entries)) throw new Error(`A place first-view catalog is ${PROFILE}.`);
  const stated = new Map<string, number>();
  for (const entry of document.entries as { key?: unknown; value?: unknown }[]) {
    if (typeof entry.key !== 'string' || typeof entry.value !== 'number' || !(entry.value > 0)) throw new Error('A place first-view figure is a key and a positive number.');
    stated.set(entry.key, entry.value);
  }
  const figure = (key: string): number => {
    const value = stated.get(key);
    if (value === undefined) throw new Error(`The place first-view catalog states no ${key}.`);
    return value;
  };
  const radians = (key: string): number => (figure(key) * Math.PI) / 180;
  const count = (key: string): number => {
    const value = figure(key);
    if (!Number.isInteger(value)) throw new Error(`The place first-view catalog's ${key} is a whole number.`);
    return value;
  };
  return Object.freeze({
    wayStep: radians('way_step_degrees'),
    edgeSpotsMost: count('edge_spots_most'),
    structuresLeast: count('structures_least'),
    structureLinesLeast: count('structure_lines_least'),
    structureLineStep: radians('structure_line_step_degrees'),
    structureReachMm: figure('structure_reach_mm'),
    structureFrameShare: figure('structure_frame_thousandths') / 1000,
    structuresMostCounted: count('structures_most_counted'),
    wallNearMm: figure('wall_near_mm'),
    wallShareMost: figure('wall_share_most_thousandths') / 1000,
    acrossOffMost: radians('across_off_most_degrees'),
    landColumn: radians('land_column_degrees'),
    landStepMm: figure('land_step_mm'),
  });
}

/** The figures the page opens a place by. */
export const PLACE_FIRST_VIEW: PlaceViewRule = placeViewRule(catalogText);

/** What a place's first view is chosen from, in the place's plan frame. */
export interface PlaceSight {
  /** The served arrival, millimetres east and south, and the unit plan direction it faces. */
  readonly arrivalMm: readonly [east: number, south: number];
  readonly facing: readonly [east: number, south: number];
  /** The place's extent: it spans east 0 to `widthMm` and south `-depthMm` to 0. */
  readonly widthMm: number;
  readonly depthMm: number;
  /** Each of the place's buildings by what of it stands at eye height, and everything else that does. */
  readonly buildings: readonly (readonly SightBlocker[])[];
  readonly posts: readonly SightBlocker[];
  /** Whether a person can stand at a spot: on drawn ground, out of every building and out of the water. */
  readonly standable: (eastMm: number, southMm: number) => boolean;
  /** The land's sea, where it holds one, by which open water in a view is read. */
  readonly sea?: SeaSight;
  /**
   * The land's height under a point and how far above it an eye stands, on land: a bank or the side of a
   * cut that rises above the eye stands in a view as a wall does. Absent on level ground.
   */
  readonly ground?: { readonly groundMm: (eastMm: number, southMm: number) => number; readonly eyeMm: number };
}

/** A place's first view: where to stand and the renderer's yaw (0 looks north), and what chose it. */
export interface PlaceView {
  readonly eastMm: number;
  readonly southMm: number;
  readonly yaw: number;
  readonly moved: boolean;
  readonly chosen: 'water' | 'across' | 'served';
}

type Plan = readonly [number, number];

const yawOf = (toward: Plan): number => Math.atan2(-toward[0], -toward[1]);
const turnBetween = (a: Plan, b: Plan): number => Math.acos(Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1])));
const turned = (toward: Plan, angle: number): Plan => [
  toward[0] * Math.cos(angle) - toward[1] * Math.sin(angle), toward[0] * Math.sin(angle) + toward[1] * Math.cos(angle),
] as const;

/** The spots a first view may stand at, the arrival first and the rest nearest it first. */
export function placeSpots(sight: PlaceSight, rule: OpenViewRule, place: PlaceViewRule = PLACE_FIRST_VIEW): Plan[] {
  const [east, south] = sight.arrivalMm;
  const spots: Plan[] = [];
  // Back from the arrival, out of a lane between the place's first buildings.
  const reach = rule.placed?.outReachMm ?? rule.backMaximumMm;
  if (rule.backStepMm > 0) {
    for (let back = rule.backStepMm; back <= reach; back += rule.backStepMm) {
      spots.push([east - sight.facing[0] * back, south - sight.facing[1] * back]);
    }
  }
  // Round the place's edge, a step inside it on its own ground (the walk has none beyond the place), so a view
  // may look across the place from any side.
  const inset = rule.alongStepMm;
  const every = Math.max(2 * rule.alongStepMm, (2 * (sight.widthMm + sight.depthMm)) / place.edgeSpotsMost);
  if (every > 0 && sight.widthMm > 2 * inset && sight.depthMm > 2 * inset) {
    const [west, eastEdge, north, southEdge] = [inset, sight.widthMm - inset, -sight.depthMm + inset, -inset];
    for (let x = west; x <= eastEdge; x += every) spots.push([x, north], [x, southEdge]);
    for (let y = north + every; y < southEdge; y += every) spots.push([west, y], [eastEdge, y]);
  }
  const from = (spot: Plan): number => Math.hypot(spot[0] - east, spot[1] - south);
  return [sight.arrivalMm, ...spots.filter((spot) => sight.standable(spot[0], spot[1])).sort((a, b) => from(a) - from(b))];
}

/**
 * The share of the frame `half` either side of `toward`, by the width each column takes in it, in which the
 * land rises above the eye within `reachMm`, leaving out the columns `covered` says something else already
 * fills. Columns `place.landColumn` apart, each read `place.landStepMm` at a time.
 */
export function landShare(
  spot: Plan, toward: Plan, ground: NonNullable<PlaceSight['ground']>, half: number, reachMm: number,
  covered: (way: Plan) => boolean = () => false, place: PlaceViewRule = PLACE_FIRST_VIEW,
): number {
  const eye = ground.groundMm(spot[0], spot[1]) + ground.eyeMm;
  const columns = Math.max(1, Math.ceil((2 * half) / place.landColumn - 1e-9));
  let risen = 0;
  let whole = 0;
  for (let column = 0; column < columns; column += 1) {
    const lo = -half + column * place.landColumn;
    const hi = Math.min(half, lo + place.landColumn);
    const width = Math.tan(hi) - Math.tan(lo);
    whole += width;
    const way = turned(toward, (lo + hi) / 2);
    if (covered(way)) continue;
    for (let distance = place.landStepMm; distance <= reachMm; distance += place.landStepMm) {
      if (ground.groundMm(spot[0] + way[0] * distance, spot[1] + way[1] * distance) > eye) {
        risen += width;
        break;
      }
    }
  }
  return whole > 0 ? risen / whole : 0;
}

/**
 * How many of `buildings` a view shows: each met before anything else of `rings` by at least `least` of its
 * sight lines, `step` apart across `half` either side of `toward`, within `reachMm`.
 */
export function buildingsSeen(
  spot: Plan, toward: Plan, buildings: readonly (readonly SightBlocker[])[], rings: readonly SightBlocker[],
  half: number, step: number, reachMm: number, least: number,
): number {
  const met = new Map<number, number>();
  const lines = Math.floor(half / step);
  for (let line = -lines; line <= lines; line += 1) {
    const way = turned(toward, line * step);
    const nearest = openDistance(spot, way, rings, reachMm);
    if (nearest >= reachMm) continue;
    // The building whose own wall the line meets at the nearest distance is the one it shows.
    const shown = buildings.findIndex((own) => openDistance(spot, way, own, reachMm) <= nearest);
    if (shown >= 0) met.set(shown, (met.get(shown) ?? 0) + 1);
  }
  return [...met.values()].filter((count) => count >= least).length;
}

/** Whether every point of a building's rings stands ahead within `half` either side of `toward`: it shows whole. */
export function showsWhole(spot: Plan, toward: Plan, rings: readonly SightBlocker[], half: number): boolean {
  return rings.every((ring) => ring.every((point) => {
    const away = [point[0] - spot[0], point[1] - spot[1]] as const;
    const length = Math.hypot(away[0], away[1]);
    return length > 0 && turnBetween(toward, [away[0] / length, away[1] / length]) <= half;
  }));
}

/** A place's first view, as the module comment says: the water with the place in it, else across the place, else as served. */
export function placeFirstView(sight: PlaceSight, rule: OpenViewRule, place: PlaceViewRule = PLACE_FIRST_VIEW): PlaceView {
  const served: PlaceView = {
    eastMm: sight.arrivalMm[0], southMm: sight.arrivalMm[1], yaw: yawOf(sight.facing), moved: false, chosen: 'served',
  };
  const near = rule.nearFace;
  const life = rule.life;
  const middle = rule.middleThirdHalf;
  if (near === undefined || life === undefined || middle === undefined) return served;
  const walls = sight.buildings.flat();
  const rings = [...walls, ...sight.posts];
  const ground = sight.ground;
  // A view is clear at 1 or more: each of its tests as a share of what the rule allows. On land a bank or a
  // cut's side rising above the eye counts as a wall: across the middle third nearer than the centre floor,
  // and in the frame's columns no wall already fills nearer than the near distance.
  const room = (spot: Plan, toward: Plan): number => {
    const standing = Math.min(
      nearestInWedge(spot, toward, middle, rings) / life.centreFloorMm,
      nearestInWedge(spot, toward, near.frameHalf, sight.posts) / near.postMm,
    );
    if (standing < 1) return standing;
    const walled = (way: Plan): boolean => openDistance(spot, way, walls, near.nearMm) < near.nearMm;
    const share = nearFaceShare(spot, toward, walls, near.frameHalf, near.nearMm)
      + (ground === undefined ? 0 : landShare(spot, toward, ground, near.frameHalf, near.nearMm, walled, place));
    const blank = nearFaceShare(spot, toward, walls, near.frameHalf, place.wallNearMm);
    const centre = ground !== undefined && landShare(spot, toward, ground, middle, life.centreFloorMm, undefined, place) > 0
      ? 0 : Number.POSITIVE_INFINITY;
    return Math.min(
      standing, centre,
      share === 0 ? Number.POSITIVE_INFINITY : near.shareMost / share,
      blank === 0 ? Number.POSITIVE_INFINITY : place.wallShareMost / blank,
    );
  };
  const spots = placeSpots(sight, rule, place);
  const ways: Plan[] = Array.from({ length: Math.round((2 * Math.PI) / place.wayStep) }, (_, index) => [
    Math.cos(index * place.wayStep), Math.sin(index * place.wayStep),
  ] as const);
  const view = (spot: Plan, toward: Plan, chosen: PlaceView['chosen']): PlaceView => ({
    eastMm: spot[0], southMm: spot[1], yaw: yawOf(toward), moved: spot !== sight.arrivalMm, chosen,
  });
  const water = rule.seafront?.water;
  const least = Math.min(place.structuresLeast, sight.buildings.length);
  if (sight.sea !== undefined && water !== undefined && rule.seafront !== undefined && least > 0) {
    const lines = near.frameHalf * place.structureFrameShare;
    const whole = sight.buildings.length < place.structuresLeast;
    const from = (spot: Plan): number => Math.hypot(spot[0] - sight.arrivalMm[0], spot[1] - sight.arrivalMm[1]);
    let best: { spot: Plan; toward: Plan; seen: number; shown: number; away: number; turn: number } | null = null;
    for (const spot of spots) {
      for (const toward of ways) {
        const counted = buildingsSeen(spot, toward, sight.buildings, rings, lines, place.structureLineStep, place.structureReachMm, place.structureLinesLeast);
        if (counted < least || (whole && !sight.buildings.every((own) => showsWhole(spot, toward, own, near.frameHalf)))) continue;
        if (room(spot, toward) < 1) continue;
        const shown = waterInView(spot, toward, sight.sea, rings, near.frameHalf, rule.seafront.frontStep, water);
        if (shown < water.share) continue;
        const seen = Math.min(counted, place.structuresMostCounted);
        const away = from(spot);
        const turn = turnBetween(toward, sight.facing);
        const better = best === null || seen > best.seen || (seen === best.seen && (shown > best.shown
          || (shown === best.shown && (away < best.away || (away === best.away && turn < best.turn)))));
        if (better) best = { spot, toward, seen, shown, away, turn };
      }
    }
    if (best !== null) return view(best.spot, best.toward, 'water');
  }
  const centre = [sight.widthMm / 2, -sight.depthMm / 2] as const;
  for (const spot of spots) {
    const away = [centre[0] - spot[0], centre[1] - spot[1]] as const;
    const length = Math.hypot(away[0], away[1]);
    const across: Plan = length === 0 ? sight.facing : [away[0] / length, away[1] / length];
    let best: { toward: Plan; off: number } | null = null;
    for (const toward of ways) {
      const off = turnBetween(toward, across);
      if (off > place.acrossOffMost || room(spot, toward) < 1) continue;
      if (best === null || off < best.off) best = { toward, off };
    }
    if (best !== null) return view(spot, best.toward, 'across');
  }
  return served;
}
