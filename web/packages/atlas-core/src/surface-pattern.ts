/**
 * Surface patterns: what keeps a made place's surface from being one flat colour.
 *
 * The surface pattern catalog (`assets/catalogs/world-kinds/surface-pattern.v1.json`) states, by
 * surface material key, a pattern at physical scale: its kind, one or two periods in millimetres
 * and how strongly it darkens the material's colour. The kinds are few and each is worked from a
 * surface's own place in the world, so no texture image and no UV is needed:
 *
 * - `courses`: rows `period_b` high of blocks `period_a` long, each row's joints broken against the
 *   last (stone, brick, slates, paving, tiles, cobbles);
 * - `boards`: boards `period_a` wide, each a little its own tone, with a joint between (timber, a
 *   plain floor, a drilled crop);
 * - `strokes`: fine streaks `period_a` wide running down the surface, with a line every `period_b`
 *   (thatch);
 * - `seams`: a thin line every `period_a` (canvas, sheet metal, cast concrete);
 * - `ripples`: soft bands about `period_a` apart that wander (water, ice);
 * - `grain`: a soft mottle about `period_a` across with a finer one inside it (grass, sand, earth).
 *
 * It is colour only: nothing is raised or sunk, and nothing here reaches a slot, the walk or a seat.
 *
 * Pure: no DOM, no Node, no renderer. The catalog's text is passed in.
 */

export const SURFACE_PATTERN_CATALOG_ID = 'surface-pattern';
export const SURFACE_PATTERN_KINDS = ['courses', 'boards', 'strokes', 'seams', 'ripples', 'grain'] as const;
export type SurfacePatternKind = (typeof SURFACE_PATTERN_KINDS)[number];

export interface SurfacePattern {
  /** The surface material it patterns. */
  readonly key: string;
  readonly kind: SurfacePatternKind;
  /** The pattern's period across the surface, in millimetres. */
  readonly periodAMm: number;
  /** Its period up the surface, for the kinds that have one (`courses`, `strokes`); else 0. */
  readonly periodBMm: number;
  /** How far the pattern darkens the colour at its strongest, in thousandths. */
  readonly strengthPermille: number;
}

export interface SurfacePatterns {
  readonly version: number;
  readonly byMaterial: ReadonlyMap<string, SurfacePattern>;
}

const KEY = /^[a-z][a-z0-9_]{0,39}$/;
/** The kinds that are worked from two periods. */
const TWO_PERIODS: ReadonlySet<SurfacePatternKind> = new Set(['courses', 'strokes']);

function refuse(where: string, detail: string): never {
  throw new TypeError(`surface pattern catalog: ${where} ${detail}`);
}

function whole(value: unknown, where: string, min: number, max: number): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min || value > max) return refuse(where, `must be a whole number from ${min} to ${max}`);
  return value;
}

/** Read the catalog's text, or refuse it by naming the first entry that is not a pattern. */
export function readSurfacePatterns(text: string): SurfacePatterns {
  const document = JSON.parse(text) as { readonly catalog_id?: unknown; readonly catalog_version?: unknown; readonly entries?: unknown };
  if (document.catalog_id !== SURFACE_PATTERN_CATALOG_ID || !Array.isArray(document.entries)) return refuse('the file', 'is not the surface pattern catalog');
  const version = whole(document.catalog_version, 'catalog_version', 1, 1_000_000);
  const byMaterial = new Map<string, SurfacePattern>();
  for (const entry of document.entries as readonly Record<string, unknown>[]) {
    const key = entry?.['key'];
    if (typeof key !== 'string' || !KEY.test(key)) return refuse('an entry', `has the key ${JSON.stringify(key)}`);
    if (byMaterial.has(key)) return refuse(key, 'is stated twice');
    const reason = entry['reason'];
    if (typeof reason !== 'string' || reason.trim() === '') return refuse(key, 'gives no reason');
    const kind = entry['kind'];
    if (!SURFACE_PATTERN_KINDS.includes(kind as SurfacePatternKind)) return refuse(`${key}.kind`, `must be one of ${SURFACE_PATTERN_KINDS.join(', ')}`);
    const periodAMm = whole(entry['period_a_mm'], `${key}.period_a_mm`, 20, 20_000);
    const periodBMm = whole(entry['period_b_mm'], `${key}.period_b_mm`, 0, 20_000);
    if (TWO_PERIODS.has(kind as SurfacePatternKind) !== (periodBMm !== 0)) return refuse(key, 'states a second period exactly where its kind has one');
    if (periodBMm !== 0 && periodBMm < 20) return refuse(`${key}.period_b_mm`, 'must be 0 or at least 20');
    byMaterial.set(key, Object.freeze({
      key, kind: kind as SurfacePatternKind, periodAMm, periodBMm,
      strengthPermille: whole(entry['strength_permille'], `${key}.strength_permille`, 1, 600),
    }));
  }
  return Object.freeze({ version, byMaterial });
}
