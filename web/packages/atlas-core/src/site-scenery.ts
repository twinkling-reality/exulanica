/**
 * Scenery beyond a made place: what stands on the ground past the place's rectangle.
 *
 * A place's ground runs out to the horizon in the material of its own base ground. The site scenery
 * catalog (`assets/catalogs/world-kinds/site-scenery.v1.json`) states, by that material's key, what
 * stands on it out there: trees beyond a forest's floor, a stone here and there beyond sand, a tree
 * here and there beyond grass. A material with no entry has none.
 *
 * It is scenery, like the horizon: not a part of the world. It is not in the place's drawing, not
 * listed, not walked, not picked, and it hides nobody; a creator's world document states none of
 * it. The page makes it from the base ground's material and the world's own identity, so the same
 * world has the same trees every time it is opened, on any machine.
 *
 * Placement is whole numbers throughout: the world's identity is hashed to 32 bits, each square of
 * a grid over the ground is hashed from that and its own column and row, and every position, size
 * and choice is taken from those bits by integer arithmetic. One square root is taken, of a whole
 * number, to say how far beyond the rectangle a point lies; a square root is the same on every
 * machine. Nothing here depends on how a machine rounds a product of fractions.
 *
 * The count of pieces is a rendering budget (`most`), stated with its reason in the catalog and no
 * fact of any world: where the ground holds more, the nearest to the place are kept.
 *
 * Pure: no DOM, no Node, no renderer. The catalog's text is passed in.
 */

export const SITE_SCENERY_CATALOG_ID = 'site-scenery';

/** What stands: a tree (a pack's own tree piece, or a plain trunk and crown) or a low stone. */
export type SceneryStands = 'tree' | 'stone';
export const SCENERY_STANDS: readonly SceneryStands[] = ['tree', 'stone'];

export interface SiteScenery {
  /** The surface material of the base ground this stands beyond. */
  readonly key: string;
  readonly stands: SceneryStands;
  /** The side of the squares the ground beyond is cut into; a square holds one piece or none. */
  readonly spacingMm: number;
  /** How far beyond the rectangle the nearest piece may stand, and the farthest. */
  readonly fromMm: number;
  readonly toMm: number;
  /** Over this far from `fromMm` outward the share of squares that hold a piece rises from none. */
  readonly edgeThinMm: number;
  /** The share of squares that hold a piece near the place and at `toMm`, in thousandths. */
  readonly nearKeepPermille: number;
  readonly farKeepPermille: number;
  /** How tall a piece stands, least and most. */
  readonly heightMm: readonly [number, number];
  /** Its width as thousandths of its height. */
  readonly widthPermille: number;
  /** The rendering budget: at most this many pieces, the nearest first. */
  readonly most: number;
}

export interface SiteSceneryCatalog {
  readonly version: number;
  readonly byMaterial: ReadonlyMap<string, SiteScenery>;
}

/** One piece of scenery: where it stands in site millimetres (x east, y north), and its size. */
export interface SceneryPiece {
  /** Its square's column and row, which with the world's identity is what it is. */
  readonly identity: string;
  readonly stands: SceneryStands;
  readonly xMm: number;
  readonly yMm: number;
  /** How far beyond the place's rectangle it stands. */
  readonly beyondMm: number;
  readonly heightMm: number;
  readonly widthMm: number;
  /** Which of four ways it is turned. */
  readonly quarterTurns: 0 | 1 | 2 | 3;
}

const KEY = /^[a-z][a-z0-9_]{0,39}$/;

function refuse(where: string, detail: string): never {
  throw new TypeError(`site scenery catalog: ${where} ${detail}`);
}

function whole(value: unknown, where: string, min: number, max: number): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min || value > max) {
    return refuse(where, `must be a whole number from ${min} to ${max}`);
  }
  return value;
}

/** Read the catalog's text, or refuse it by naming the first entry that is not scenery. */
export function readSiteScenery(text: string): SiteSceneryCatalog {
  const document = JSON.parse(text) as { readonly catalog_id?: unknown; readonly catalog_version?: unknown; readonly entries?: unknown };
  if (document.catalog_id !== SITE_SCENERY_CATALOG_ID || !Array.isArray(document.entries)) return refuse('the file', 'is not the site scenery catalog');
  const version = whole(document.catalog_version, 'catalog_version', 1, 1_000_000);
  const byMaterial = new Map<string, SiteScenery>();
  for (const entry of document.entries as readonly Record<string, unknown>[]) {
    const key = entry?.['key'];
    if (typeof key !== 'string' || !KEY.test(key)) return refuse('an entry', `has the key ${JSON.stringify(key)}`);
    if (byMaterial.has(key)) return refuse(key, 'is stated twice');
    const reason = entry['reason'];
    if (typeof reason !== 'string' || reason.trim() === '') return refuse(key, 'gives no reason');
    const stands = entry['stands'];
    if (!SCENERY_STANDS.includes(stands as SceneryStands)) return refuse(`${key}.stands`, `must be one of ${SCENERY_STANDS.join(', ')}`);
    const height = entry['height_mm'];
    if (!Array.isArray(height) || height.length !== 2) return refuse(`${key}.height_mm`, 'must be a least and a most');
    const scenery: SiteScenery = {
      key,
      stands: stands as SceneryStands,
      spacingMm: whole(entry['spacing_mm'], `${key}.spacing_mm`, 500, 1_000_000),
      fromMm: whole(entry['from_mm'], `${key}.from_mm`, 0, 1_000_000),
      toMm: whole(entry['to_mm'], `${key}.to_mm`, 1, 8_000_000),
      edgeThinMm: whole(entry['edge_thin_mm'], `${key}.edge_thin_mm`, 0, 8_000_000),
      nearKeepPermille: whole(entry['near_keep_permille'], `${key}.near_keep_permille`, 1, 1000),
      farKeepPermille: whole(entry['far_keep_permille'], `${key}.far_keep_permille`, 0, 1000),
      heightMm: [whole(height[0], `${key}.height_mm`, 10, 100_000), whole(height[1], `${key}.height_mm`, 10, 100_000)],
      widthPermille: whole(entry['width_permille'], `${key}.width_permille`, 10, 100_000),
      most: whole(entry['most'], `${key}.most`, 1, 100_000),
    };
    if (scenery.toMm <= scenery.fromMm) return refuse(key, 'ends no farther out than it begins');
    if (scenery.fromMm + scenery.edgeThinMm > scenery.toMm) return refuse(key, 'thins toward the place over more ground than it stands on');
    if (scenery.heightMm[1] < scenery.heightMm[0]) return refuse(`${key}.height_mm`, 'states a most under its least');
    byMaterial.set(key, Object.freeze({ ...scenery, heightMm: Object.freeze(scenery.heightMm) as readonly [number, number] }));
  }
  return Object.freeze({ version, byMaterial });
}

/** A string's 32 bits (FNV-1a over its UTF-16 code units), as a whole number from 0. */
function bitsOf(text: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** 32 well mixed bits from a seed and three whole numbers. */
function mixed(seed: number, a: number, b: number, c: number): number {
  let h = seed ^ Math.imul(a | 0, 0x9e3779b1) ^ Math.imul(b | 0, 0x85ebca6b) ^ Math.imul(c | 0, 0xc2b2ae35);
  h ^= h >>> 16;
  h = Math.imul(h, 0x7feb352d);
  h ^= h >>> 15;
  h = Math.imul(h, 0x846ca68b);
  h ^= h >>> 16;
  return h >>> 0;
}

/**
 * The scenery that stands beyond one place: `worldId` is the world's own identity, the rectangle
 * is the place's extent from its origin (x east, y north, millimetres). In order, nearest the place
 * first, and where two stand equally near, by column then row.
 */
export function sceneryBeyond(
  worldId: string, extent: { readonly widthMm: number; readonly depthMm: number }, scenery: SiteScenery,
): SceneryPiece[] {
  const { spacingMm: s, fromMm, toMm } = scenery;
  const { widthMm, depthMm } = extent;
  if (!(Number.isInteger(widthMm) && Number.isInteger(depthMm) && widthMm > 0 && depthMm > 0)) return [];
  const seed = bitsOf(worldId);
  const pieces: SceneryPiece[] = [];
  const firstColumn = Math.floor(-toMm / s), lastColumn = Math.floor((widthMm + toMm) / s);
  const firstRow = Math.floor(-toMm / s), lastRow = Math.floor((depthMm + toMm) / s);
  for (let column = firstColumn; column <= lastColumn; column += 1) {
    for (let row = firstRow; row <= lastRow; row += 1) {
      // A point of the square, not its middle: a grid's rows must not show.
      const xMm = column * s + mixed(seed, column, row, 1) % s;
      const yMm = row * s + mixed(seed, column, row, 2) % s;
      const dx = xMm < 0 ? -xMm : xMm > widthMm ? xMm - widthMm : 0;
      const dy = yMm < 0 ? -yMm : yMm > depthMm ? yMm - depthMm : 0;
      if (dx === 0 && dy === 0) continue;
      const beyondMm = Math.round(Math.sqrt(dx * dx + dy * dy));
      if (beyondMm < fromMm || beyondMm > toMm) continue;
      // The share of squares that hold a piece: none at the inner edge rising over the thinning
      // ground to the near share, then from there to the far share at the outer edge.
      const inward = beyondMm - fromMm;
      const keep = inward < scenery.edgeThinMm
        ? Math.floor(scenery.nearKeepPermille * inward / scenery.edgeThinMm)
        : scenery.nearKeepPermille + Math.floor((scenery.farKeepPermille - scenery.nearKeepPermille)
          * (inward - scenery.edgeThinMm) / (toMm - fromMm - scenery.edgeThinMm || 1));
      if (mixed(seed, column, row, 3) % 1000 >= keep) continue;
      const [least, most] = scenery.heightMm;
      const heightMm = least + mixed(seed, column, row, 4) % (most - least + 1);
      pieces.push({
        identity: `${column}:${row}`,
        stands: scenery.stands,
        xMm,
        yMm,
        beyondMm,
        heightMm,
        widthMm: Math.floor(heightMm * scenery.widthPermille / 1000),
        quarterTurns: (mixed(seed, column, row, 5) % 4) as 0 | 1 | 2 | 3,
      });
    }
  }
  pieces.sort((a, b) => a.beyondMm - b.beyondMm || a.xMm - b.xMm || a.yMm - b.yMm);
  return pieces.slice(0, scenery.most);
}
