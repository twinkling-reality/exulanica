/**
 * How the first view of a generated town is chosen where nothing is placed in it, read from the one
 * data file that states each value with its reason,
 * `assets/catalogs/arrival/town-first-view.v1.json`. Presentation only.
 */
import catalogText from '../../../../assets/catalogs/arrival/town-first-view.v1.json?raw';

/**
 * How the first view is chosen where nothing is placed, as the town first-view catalog states it
 * (`assets/catalogs/arrival/town-first-view.v1.json`, read below): angles in
 * radians, lengths in millimetres.
 */
export interface OpenViewRule {
  /** How far the view is turned from straight across the road toward each way along it. */
  readonly slant: number;
  /** Half the fan of sight lines a view is judged by, and how many lines. */
  readonly fanHalf: number;
  readonly sightLines: number;
  /** How far a sight line is followed: farther is as good as this. */
  readonly reachMm: number;
  /** Something nearer than this dead ahead fills the frame. */
  readonly faceMm: number;
  /** The step back from the kerb, off the line people walk, and the farthest back. */
  readonly backStepMm: number;
  readonly backMaximumMm: number;
  /** The step along the footway, and the farthest along. */
  readonly alongStepMm: number;
  readonly alongMaximumMm: number;
  /** Views whose openness differs by less than this are equally open; the nearer spot is taken. */
  readonly tie: number;
}

interface FirstViewEntry {
  readonly key: string;
  readonly value: number;
  readonly unit: string;
  readonly reason: string;
}

function readCatalog(text: string): ReadonlyMap<string, FirstViewEntry> {
  const document = JSON.parse(text) as { readonly profile?: unknown; readonly entries?: readonly FirstViewEntry[] };
  if (document.profile !== 'exulanica.town-first-view/v1' || !Array.isArray(document.entries)) {
    throw new Error('not the town first-view catalog');
  }
  const entries = new Map<string, FirstViewEntry>();
  for (const entry of document.entries) {
    if (typeof entry.key !== 'string' || !Number.isFinite(entry.value) || entry.value < 0 || !entry.reason || entries.has(entry.key)) {
      throw new Error(`town first-view entry ${String(entry.key)} is malformed`);
    }
    entries.set(entry.key, entry);
  }
  return entries;
}

const ENTRIES = readCatalog(catalogText);

function stated(key: string, unit: string): number {
  const entry = ENTRIES.get(key);
  if (entry === undefined || entry.unit !== unit) throw new Error(`the town first-view catalog states no ${key} in ${unit}s`);
  return entry.value;
}

const radians = (key: string): number => (stated(key, 'degree') * Math.PI) / 180;

/** The rule the first view of a town with nothing placed is chosen by. */
export const TOWN_FIRST_VIEW: OpenViewRule = Object.freeze({
  slant: radians('slant_degrees'),
  fanHalf: radians('fan_half_degrees'),
  sightLines: stated('sight_lines', 'count'),
  reachMm: stated('reach_mm', 'millimetre'),
  faceMm: stated('face_mm', 'millimetre'),
  backStepMm: stated('back_step_mm', 'millimetre'),
  backMaximumMm: stated('back_maximum_mm', 'millimetre'),
  alongStepMm: stated('along_step_mm', 'millimetre'),
  alongMaximumMm: stated('along_maximum_mm', 'millimetre'),
  tie: stated('tie_milli', 'thousandth') / 1000,
});
