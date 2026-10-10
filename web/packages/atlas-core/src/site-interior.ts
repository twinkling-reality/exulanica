/**
 * The inside of a made place whose extent is indoors: its ceiling and the light under it.
 *
 * A site's drawing says of its extent whether it is open to the sky or indoors, and draws walls and
 * a floor either way. The site interior catalog
 * (`assets/catalogs/world-kinds/site-interior.v1.json`) states what an indoor extent is drawn with
 * besides: a ceiling of a stated thickness, and the look's one sun turned to shine from above at a
 * stated share of its strength and in a stated colour. An open place has neither.
 *
 * The ceiling is drawn only: it is no slot of the drawing, and nothing here reaches the walk, a
 * click or what hides a being.
 *
 * Pure: no DOM, no Node, no renderer. The catalog's text is passed in.
 */

export const SITE_INTERIOR_CATALOG_ID = 'site-interior';

export interface SiteInterior {
  /** How thick the ceiling's slab is, in millimetres. */
  readonly ceilingThicknessMm: number;
  /** How far from straight down the light shines, and how far it is turned about the vertical, in degrees. */
  readonly lightTiltDegrees: number;
  readonly lightTurnDegrees: number;
  /** The light's strength as thousandths of the look's sun. */
  readonly lightSharePermille: number;
  /** The light's colour, sRGB bytes. */
  readonly lightSrgb8: readonly [number, number, number];
}

export interface SiteInteriorCatalog {
  readonly version: number;
  /** What an indoor extent is drawn with. */
  readonly indoor: SiteInterior;
}

function refuse(where: string, detail: string): never {
  throw new TypeError(`site interior catalog: ${where} ${detail}`);
}

function whole(value: unknown, where: string, min: number, max: number): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min || value > max) {
    return refuse(where, `must be a whole number from ${min} to ${max}`);
  }
  return value;
}

/** Read the catalog's text, or refuse it by naming what is not an interior. */
export function readSiteInterior(text: string): SiteInteriorCatalog {
  const document = JSON.parse(text) as { readonly catalog_id?: unknown; readonly catalog_version?: unknown; readonly entries?: unknown };
  if (document.catalog_id !== SITE_INTERIOR_CATALOG_ID || !Array.isArray(document.entries)) return refuse('the file', 'is not the site interior catalog');
  const version = whole(document.catalog_version, 'catalog_version', 1, 1_000_000);
  const entries = document.entries as readonly Record<string, unknown>[];
  if (entries.length !== 1 || entries[0]?.['key'] !== 'indoor') return refuse('the file', 'must state the one entry indoor');
  const entry = entries[0]!;
  const reason = entry['reason'];
  if (typeof reason !== 'string' || reason.trim() === '') return refuse('indoor', 'gives no reason');
  const colour = entry['light_srgb8'];
  if (!Array.isArray(colour) || colour.length !== 3) return refuse('indoor.light_srgb8', 'must be three bytes');
  return Object.freeze({
    version,
    indoor: Object.freeze({
      ceilingThicknessMm: whole(entry['ceiling_thickness_mm'], 'indoor.ceiling_thickness_mm', 1, 2000),
      // Straight down is 0; at 90 the light would lie along the ceiling and light no floor.
      lightTiltDegrees: whole(entry['light_tilt_degrees'], 'indoor.light_tilt_degrees', 0, 80),
      lightTurnDegrees: whole(entry['light_turn_degrees'], 'indoor.light_turn_degrees', 0, 359),
      lightSharePermille: whole(entry['light_share_permille'], 'indoor.light_share_permille', 1, 4000),
      lightSrgb8: Object.freeze(colour.map((byte, i) => whole(byte, `indoor.light_srgb8[${i}]`, 0, 255))) as unknown as readonly [number, number, number],
    }),
  });
}
