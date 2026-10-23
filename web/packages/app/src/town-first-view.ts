/**
 * How the first view of a generated town is chosen, read from the data files that state each value
 * with its reason, `assets/catalogs/arrival/town-first-view.v5.json` and the versions before it.
 * Presentation only.
 *
 * Version 1 chooses the most open view. Version 2 chooses by what of the town's life lies in view
 * (its seats and doors), with openness to break a tie and nothing at eye height dead ahead. Version
 * 3 is version 2 with a least distance under which a seat or a door does not count, so the view
 * does not walk up to a bench to stand behind it. Version 4 is version 3 with the figures the view
 * of placed things and the preference for standing off the walking line were chosen by; it is the
 * version 4 with a seafront view: where a town's entry names a direction its first view looks toward
 * (the sea of a town on land that holds one) and its arrival faces away from it, across the shore
 * street from its seaward footway, the view turns along the shore, the fronts on the land side and the
 * open view on the other, with nothing near across its middle third; it is the version the page
 * opens a town by. All stay readable:
 * `firstViewRule` reads any of the five files, and an earlier one with the figures version 4 states
 * as `FIRST_VIEW_DEFAULTS` states them.
 */
import catalogText from '../../../../assets/catalogs/arrival/town-first-view.v5.json?raw';

/**
 * How a view is judged by the town's life, as version 2 of the catalog states it: angles in
 * radians, lengths in millimetres.
 */
export interface LifeViewRule {
  /** A seat or a door in view counts whole up to `nearMm`, then less, down to nothing at `farMm`. */
  readonly nearMm: number;
  readonly farMm: number;
  /** Nearer than this a seat or a door is at the viewer's feet and does not count. 0 in version 2. */
  readonly leastMm: number;
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
 * How the first view of a town with things placed in it steps to a spot that sees them, as version 4
 * of the catalog states it, in millimetres.
 */
export interface PlacedViewRule {
  /** The step between the spots tried, along the footway, back from the kerb and out toward the street. */
  readonly stepMm: number;
  /** How many steps along the footway either way, and back from the kerb. */
  readonly stepsAlong: number;
  readonly stepsBack: number;
  /** How far out toward and across the street, where no spot near the footway sees them. */
  readonly outReachMm: number;
  /** Room kept round a parked vehicle's footprint. */
  readonly parkedClearanceMm: number;
  /** How much farther a spot's nearest vehicle in the way must be for that spot to be taken instead. */
  readonly parkedFartherMm: number;
}

/**
 * How the first view is chosen, as a town first-view catalog states it: angles in radians, lengths
 * in millimetres.
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
  /** What standing back from the kerb, off the line people walk, adds to a view's openness. */
  readonly offLineBonus?: number;
  /** How a view of placed things steps to a spot that sees them. */
  readonly placed?: PlacedViewRule;
  /**
   * Version 5: how far either side of where a first view looks nothing at eye height may stand nearer
   * than the centre floor: its middle third, where earlier versions test dead ahead alone (the life
   * rule's `centreHalf`). Absent before version 5.
   */
  readonly middleThirdHalf?: number;
  /**
   * Version 5: a seafront view, where an entry names a direction to look toward and the arrival faces
   * away from it within `facingMost`: the view turns `slant` from straight across instead of the rule's slant,
   * from the spot and the way with the most buildings' fronts in view, counted by sight lines `frontStep`
   * apart across `frontHalf` either side, a front once `frontLinesLeast` of them meet it, up to
   * `frontsLeast`, stepping up to `alongMaximumMm` along the footway, then the most doors. Absent before
   * version 5.
   */
  readonly seafront?: {
    readonly facingMost: number; readonly slant: number; readonly frontHalf: number;
    readonly frontStep: number; readonly frontLinesLeast: number; readonly frontsLeast: number; readonly alongMaximumMm: number;
  };
}

/**
 * The figures versions 1 to 3 of the catalog do not state, as the page chose by them before version 4
 * stated them, and as a caller that hands no rule is answered by. `aimAheadMm` is where a town with
 * nothing placed is looked at when no rule is handed at all: that far ahead the way its entry says.
 */
export const FIRST_VIEW_DEFAULTS = Object.freeze({
  offLineBonus: 0.05,
  placed: Object.freeze({
    stepMm: 1_500, stepsAlong: 8, stepsBack: 3, outReachMm: 12_000, parkedClearanceMm: 300, parkedFartherMm: 500,
  } satisfies PlacedViewRule),
  aimAheadMm: 10_000,
});

interface FirstViewEntry {
  readonly key: string;
  readonly value: number;
  readonly unit: string;
  readonly reason: string;
}

const PROFILES: ReadonlyMap<unknown, 1 | 2 | 3 | 4 | 5> = new Map([
  ['exulanica.town-first-view/v1', 1], ['exulanica.town-first-view/v2', 2], ['exulanica.town-first-view/v3', 3],
  ['exulanica.town-first-view/v4', 4], ['exulanica.town-first-view/v5', 5],
]);

/** The figures of version 4 an earlier version is read with. */
const FIRST_VIEW_DEFAULTS_STATED = Object.freeze({ offLineBonus: FIRST_VIEW_DEFAULTS.offLineBonus, placed: FIRST_VIEW_DEFAULTS.placed });

/** Version 4's figures for the view of placed things, refused where they cannot be stepped by. */
function statedPlaced(
  stated: (key: string, unit: string) => number, millimetres: (key: string) => number, thousandths: (key: string) => number,
): { readonly offLineBonus: number; readonly placed: PlacedViewRule } {
  const placed: PlacedViewRule = Object.freeze({
    stepMm: millimetres('placed_step_mm'),
    stepsAlong: stated('placed_steps_along', 'count'),
    stepsBack: stated('placed_steps_back', 'count'),
    outReachMm: millimetres('placed_out_reach_mm'),
    parkedClearanceMm: millimetres('parked_clearance_mm'),
    parkedFartherMm: millimetres('parked_farther_mm'),
  });
  if (!(placed.stepMm > 0) || !Number.isInteger(placed.stepsAlong) || !Number.isInteger(placed.stepsBack)) {
    throw new Error('the town first-view catalog states a step of nothing, or a part of a step');
  }
  return { offLineBonus: thousandths('off_line_bonus_milli'), placed };
}

/** The rule a town first-view catalog file states, of any version; a file of none of them is refused. */
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
    ...(version < 4 ? FIRST_VIEW_DEFAULTS_STATED : statedPlaced(stated, millimetres, thousandths)),
    ...(version < 5 ? {} : {
      middleThirdHalf: radians('middle_third_half_degrees'),
      seafront: Object.freeze({
        facingMost: radians('seafront_facing_most_degrees'),
        slant: radians('seafront_slant_degrees'),
        frontHalf: radians('seafront_front_half_degrees'),
        frontStep: radians('seafront_front_step_degrees'),
        frontLinesLeast: stated('seafront_front_lines_least', 'count'),
        frontsLeast: stated('seafront_fronts_least', 'count'),
        alongMaximumMm: millimetres('seafront_along_maximum_mm'),
      }),
    }),
  };
  if (version === 1) return Object.freeze(rule);
  const life: LifeViewRule = Object.freeze({
    nearMm: millimetres('life_near_mm'),
    farMm: millimetres('life_far_mm'),
    leastMm: version === 2 ? 0 : millimetres('life_least_mm'),
    seatWeight: thousandths('seat_weight_milli'),
    tie: thousandths('life_tie_milli'),
    sightMarginMm: millimetres('sight_margin_mm'),
    centreHalf: radians('centre_half_degrees'),
    centreFloorMm: millimetres('centre_floor_mm'),
    seatTopMinimumMm: millimetres('seat_top_minimum_mm'),
    seatTopMaximumMm: millimetres('seat_top_maximum_mm'),
    seatSpanMinimumMm: millimetres('seat_span_minimum_mm'),
  });
  if (!(life.farMm > life.nearMm) || !(life.nearMm > life.leastMm) || !(life.seatTopMaximumMm >= life.seatTopMinimumMm)
    || !(life.centreHalf < Math.PI / 2)
    || (rule.middleThirdHalf !== undefined && !(rule.middleThirdHalf >= life.centreHalf && rule.middleThirdHalf < Math.PI / 2))
    || (rule.seafront !== undefined && (!(rule.seafront.frontStep > 0)
      || !(rule.seafront.frontHalf > 0 && rule.seafront.frontHalf < Math.PI / 2)
      || !Number.isInteger(rule.seafront.frontsLeast) || rule.seafront.frontsLeast < 1
      || !Number.isInteger(rule.seafront.frontLinesLeast) || rule.seafront.frontLinesLeast < 1))) {
    throw new Error('the town first-view catalog states distances or an angle that cannot be held together');
  }
  return Object.freeze({ ...rule, life });
}

/** The rule the first view of a town with nothing placed is chosen by. */
export const TOWN_FIRST_VIEW: OpenViewRule = firstViewRule(catalogText);
