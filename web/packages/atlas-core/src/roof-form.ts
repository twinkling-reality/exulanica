/**
 * Roof forms: how a made place's roof is shaped by the material its look role names.
 *
 * A site's drawing says of each roof only whether it is flat or pitched, and every pitched roof is
 * served as the same prism. The roof form catalog (`assets/catalogs/world-kinds/roof-form.v1.json`)
 * states, by surface material key, how each of those two is shaped: for a ridge its pitch, how far
 * it overhangs its walls, how thick it is laid, which way its ridge runs and whether its eaves stop
 * at the wall or run down to the ground (a tent); for a slab, the parapet that stands round it. The
 * drawing's flat or pitched still decides which of the two a roof is: an entry shapes that class
 * and never swaps one for the other. A material with no entry, and a class an entry leaves at
 * nothing, is drawn as it is served.
 *
 * A roof is drawn only: nothing here reaches the walk, a door or a seat.
 *
 * Pure: no DOM, no Node, no renderer. The catalog's text is passed in.
 */

export const ROOF_FORM_CATALOG_ID = 'roof-form';

/** Which way a ridge runs: as the drawing serves it, along the footprint's longer side, or along the way the structure's door faces. */
export type RidgeRuns = 'as_served' | 'long_side' | 'door_axis';

export interface RoofForm {
  /** The surface material this shapes a roof of. */
  readonly key: string;
  /** How a pitched roof of it is shaped; null leaves it as served. */
  readonly ridge: {
    /** Rise over run, in thousandths: 1000 is 45 degrees. */
    readonly pitchPermille: number;
    /** How far the roof reaches past its walls, level, in millimetres. */
    readonly overhangMm: number;
    /** How thick it is laid, in millimetres; 0 is a sheet. */
    readonly thicknessMm: number;
    readonly runs: RidgeRuns;
    /** Where its sides end: at the top of the wall, or at the ground. */
    readonly eaves: 'wall' | 'ground';
  } | null;
  /** The parapet round a flat roof of it; null leaves the slab as served. */
  readonly slab: { readonly parapetMm: number; readonly parapetThicknessMm: number } | null;
}

export interface RoofForms {
  readonly version: number;
  readonly byMaterial: ReadonlyMap<string, RoofForm>;
}

const KEY = /^[a-z][a-z0-9_]{0,39}$/;
const RUNS: readonly RidgeRuns[] = ['as_served', 'long_side', 'door_axis'];

function refuse(where: string, detail: string): never {
  throw new TypeError(`roof form catalog: ${where} ${detail}`);
}

function whole(value: unknown, where: string, max: number): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0 || value > max) return refuse(where, `must be a whole number from 0 to ${max}`);
  return value;
}

/** Read the catalog's text, or refuse it by naming the first entry that is not a roof form. */
export function readRoofForms(text: string): RoofForms {
  const document = JSON.parse(text) as { readonly catalog_id?: unknown; readonly catalog_version?: unknown; readonly entries?: unknown };
  if (document.catalog_id !== ROOF_FORM_CATALOG_ID || !Array.isArray(document.entries)) return refuse('the file', 'is not the roof form catalog');
  const version = whole(document.catalog_version, 'catalog_version', 1_000_000);
  const byMaterial = new Map<string, RoofForm>();
  for (const entry of document.entries as readonly Record<string, unknown>[]) {
    const key = entry?.['key'];
    if (typeof key !== 'string' || !KEY.test(key)) return refuse('an entry', `has the key ${JSON.stringify(key)}`);
    if (byMaterial.has(key)) return refuse(key, 'is stated twice');
    const reason = entry['reason'];
    if (typeof reason !== 'string' || reason.trim() === '') return refuse(key, 'gives no reason');
    const pitchPermille = whole(entry['ridge_pitch_permille'], `${key}.ridge_pitch_permille`, 4000);
    const overhangMm = whole(entry['ridge_overhang_mm'], `${key}.ridge_overhang_mm`, 3000);
    const thicknessMm = whole(entry['ridge_thickness_mm'], `${key}.ridge_thickness_mm`, 1000);
    const runs = entry['ridge_runs'];
    if (!RUNS.includes(runs as RidgeRuns)) return refuse(`${key}.ridge_runs`, `must be one of ${RUNS.join(', ')}`);
    const eaves = entry['ridge_eaves'];
    if (eaves !== 'wall' && eaves !== 'ground') return refuse(`${key}.ridge_eaves`, 'must be wall or ground');
    const parapetMm = whole(entry['slab_parapet_mm'], `${key}.slab_parapet_mm`, 3000);
    const parapetThicknessMm = whole(entry['slab_parapet_thickness_mm'], `${key}.slab_parapet_thickness_mm`, 1000);
    // A pitch of nothing shapes no ridge, and then nothing else of a ridge may be stated; a parapet needs a thickness.
    if (pitchPermille === 0 && (overhangMm !== 0 || thicknessMm !== 0 || runs !== 'as_served' || eaves !== 'wall')) return refuse(key, 'shapes a ridge with no pitch');
    if (eaves === 'ground' && overhangMm !== 0) return refuse(key, 'overhangs a roof that runs to the ground');
    if ((parapetMm === 0) !== (parapetThicknessMm === 0)) return refuse(key, 'states a parapet with no height or no thickness');
    if (pitchPermille === 0 && parapetMm === 0) return refuse(key, 'shapes nothing');
    byMaterial.set(key, Object.freeze({
      key,
      ridge: pitchPermille === 0 ? null : Object.freeze({ pitchPermille, overhangMm, thicknessMm, runs: runs as RidgeRuns, eaves }),
      slab: parapetMm === 0 ? null : Object.freeze({ parapetMm, parapetThicknessMm }),
    }));
  }
  return Object.freeze({ version, byMaterial });
}
