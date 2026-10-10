/**
 * How the page shows who decides for a being, over the being, read from the data file that states
 * each value with its class and reason, `assets/catalogs/thing-presentation/decider-marks.v2.json`,
 * and the version before it. Presentation only: nothing a society records is changed by it, and no
 * value is a count of beings.
 *
 * Version 2 is version 1 with the height under which a mark is a dot; it is the version the page
 * draws by. Version 1 states no such height and is read as it was: no mark is a dot.
 */
import type { DeciderMarkRule } from '@exulanica/atlas-react/things';
import catalogText from '../../../../assets/catalogs/thing-presentation/decider-marks.v2.json?raw';

interface MarkEntry {
  readonly key: string;
  readonly value: number;
  readonly unit: string;
  readonly class: string;
  readonly reason: string;
}

const CLASSES = new Set(['chosen_default', 'chosen_budget', 'measured_cost']);

const PROFILES: ReadonlyMap<unknown, 1 | 2> = new Map([['exulanica.decider-marks/v1', 1], ['exulanica.decider-marks/v2', 2]]);

/** The rule a decider-marks catalog file states, of either version; a file that is not one, or states less, is refused. */
export function deciderMarkRule(text: string): DeciderMarkRule {
  const document = JSON.parse(text) as { readonly profile?: unknown; readonly entries?: readonly MarkEntry[] };
  const version = PROFILES.get(document.profile);
  if (version === undefined || !Array.isArray(document.entries)) {
    throw new Error('not the decider marks catalog');
  }
  const entries = new Map<string, MarkEntry>();
  for (const entry of document.entries) {
    if (typeof entry.key !== 'string' || !Number.isFinite(entry.value) || entry.value <= 0 || !entry.reason
      || !CLASSES.has(entry.class) || entries.has(entry.key)) {
      throw new Error(`decider marks entry ${String(entry.key)} is malformed`);
    }
    entries.set(entry.key, entry);
  }
  const stated = (key: string, unit: string): number => {
    const entry = entries.get(key);
    if (entry === undefined || entry.unit !== unit) throw new Error(`the decider marks catalog states no ${key} in ${unit}s`);
    return entry.value;
  };
  const rule: DeciderMarkRule = {
    nameLeastPx: stated('name_least_px', 'css_pixel'),
    beingLeastPx: stated('being_least_px', 'css_pixel'),
    dotUnderPx: version === 1 ? 0 : stated('dot_under_px', 'css_pixel'),
    screenShare: stated('screen_share_milli', 'thousandth') / 1000,
    linesAtOnce: stated('lines_at_once', 'count'),
    lineBaseMs: stated('line_base_ms', 'millisecond'),
    linePerCharacterMs: stated('line_per_character_ms', 'millisecond'),
    lineMostMs: stated('line_most_ms', 'millisecond'),
  };
  if (rule.screenShare > 1 || rule.lineMostMs < rule.lineBaseMs || !Number.isInteger(rule.linesAtOnce)) {
    throw new Error('the decider marks catalog states a share, a time or a count that cannot be held');
  }
  return Object.freeze(rule);
}

/** The rule the marks over a world are drawn by. */
export const DECIDER_MARKS: DeciderMarkRule = deciderMarkRule(catalogText);
