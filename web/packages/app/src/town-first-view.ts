/**
 * How the first view of a generated town is chosen where nothing is placed in it, read from the
 * data files that state each value with its reason, `assets/catalogs/arrival/town-first-view.v2.json`
 * and the version before it. Presentation only.
 *
 * Version 1 chooses the most open view. Version 2 chooses by what of the town's life lies in view
 * (its seats and doors), with openness to break a tie and nothing at eye height dead ahead; it is
 * the version the page opens a town by. Both stay readable: `firstViewRule` reads either file.
 */
import catalogText from '../../../../assets/catalogs/arrival/town-first-view.v2.json?raw';

/**
 * How a view is judged by the town's life, as version 2 of the catalog states it: angles in
 * radians, lengths in millimetres.
 */
export interface LifeViewRule {
  /** A seat or a door in view counts whole up to `nearMm`, then less, down to nothing at `farMm`. */
  readonly nearMm: number;
  readonly farMm: number;
  /** How many doors one seat in view is worth. */
  readonly seatWeight: number;
  /** Views whose life differs by less than this are equally alive; the more open is taken. */
  readonly tie: number;
  /** Something in a sight line this near its end is the seat or door itself, and does not hide it. */
  readonly sightMarginMm: number;
  /** Dead ahead: this far either side of where the view looks, and how near nothing may stand in it. */
  readonly centreHalf: number;
  readonly centreFloorMm: number;
  /** A part of street furniture is a seat by its shape: its top's height, and its least plan span. */
  readonly seatTopMinimumMm: number;
  readonly seatTopMaximumMm: number;
  readonly seatSpanMinimumMm: number;
}

/**
 * How the first view is chosen where nothing is placed, as a town first-view catalog states it:
 * angles in radians, lengths in millimetres.
 */
export interface OpenViewRule {
  /** How far the view is turned from straight across the road toward each way along it. */
  readonly slant: number;
  /** Half the fan a view is judged over, and how many sight lines openness is the mean of. */
  readonly fanHalf: number;
  readonly sightLines: number;
  /** How far a sight line is followed: farther is as good as this. */
  readonly reachMm: number;
  /** Version 1: something nearer than this on the middle sight lines fills the frame. 0 in version 2. */
  readonly faceMm: number;
  /** The step back from the kerb, off the line people walk, and the farthest back. */
  readonly backStepMm: number;
  readonly backMaximumMm: number;
  /** The step along the footway, and the farthest along. */
  readonly alongStepMm: number;
  readonly alongMaximumMm: number;
  /** Views whose openness differs by less than this are equally open; the nearer spot is taken. */
  readonly tie: number;
  /** Version 2: the view is chosen by the town's life first. Absent in version 1. */
  readonly life?: LifeViewRule;
}

interface FirstViewEntry {
  readonly key: string;
  readonly value: number;
  readonly unit: string;
  readonly reason: string;
}

const PROFILES: ReadonlyMap<unknown, 1 | 2> = new Map([
  ['exulanica.town-first-view/v1', 1], ['exulanica.town-first-view/v2', 2],
]);

/** The rule a town first-view catalog file states, of either version; a file that is neither is refused. */
export function firstViewRule(text: string): OpenViewRule {
  const document = JSON.parse(text) as { readonly profile?: unknown; readonly entries?: readonly FirstViewEntry[] };
  const version = PROFILES.get(document.profile);
  if (version === undefined || !Array.isArray(document.entries)) {
    throw new Error('not a town first-view catalog');
  }
  const entries = new Map<string, FirstViewEntry>();
  for (const entry of document.entries) {
    if (typeof entry.key !== 'string' || !Number.isFinite(entry.value) || entry.value < 0 || !entry.reason || entries.has(entry.key)) {
      throw new Error(`town first-view entry ${String(entry.key)} is malformed`);
    }
    entries.set(entry.key, entry);
  }
  const stated = (key: string, unit: string): number => {
    const entry = entries.get(key);
    if (entry === undefined || entry.unit !== unit) throw new Error(`the town first-view catalog states no ${key} in ${unit}s`);
    return entry.value;
  };
  const radians = (key: string): number => (stated(key, 'degree') * Math.PI) / 180;
  const millimetres = (key: string): number => stated(key, 'millimetre');
  const thousandths = (key: string): number => stated(key, 'thousandth') / 1000;
  const rule = {
    slant: radians('slant_degrees'),
    fanHalf: radians('fan_half_degrees'),
    sightLines: stated('sight_lines', 'count'),
    reachMm: millimetres('reach_mm'),
    faceMm: version === 1 ? millimetres('face_mm') : 0,
    backStepMm: millimetres('back_step_mm'),
    backMaximumMm: millimetres('back_maximum_mm'),
    alongStepMm: millimetres('along_step_mm'),
    alongMaximumMm: millimetres('along_maximum_mm'),
    tie: thousandths('tie_milli'),
  };
  if (version === 1) return Object.freeze(rule);
  const life: LifeViewRule = Object.freeze({
    nearMm: millimetres('life_near_mm'),
    farMm: millimetres('life_far_mm'),
    seatWeight: thousandths('seat_weight_milli'),
    tie: thousandths('life_tie_milli'),
    sightMarginMm: millimetres('sight_margin_mm'),
    centreHalf: radians('centre_half_degrees'),
    centreFloorMm: millimetres('centre_floor_mm'),
    seatTopMinimumMm: millimetres('seat_top_minimum_mm'),
    seatTopMaximumMm: millimetres('seat_top_maximum_mm'),
    seatSpanMinimumMm: millimetres('seat_span_minimum_mm'),
  });
  if (!(life.farMm > life.nearMm) || !(life.seatTopMaximumMm >= life.seatTopMinimumMm) || !(life.centreHalf < Math.PI / 2)) {
    throw new Error('the town first-view catalog states distances or an angle that cannot be held together');
  }
  return Object.freeze({ ...rule, life });
}

/** The rule the first view of a town with nothing placed is chosen by. */
export const TOWN_FIRST_VIEW: OpenViewRule = firstViewRule(catalogText);
