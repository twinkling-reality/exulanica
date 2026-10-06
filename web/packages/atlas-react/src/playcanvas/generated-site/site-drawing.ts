/**
 * The drawing a site world's records make, as the server serves it (`exulanica.site-drawing/v1`).
 *
 * A world made from a world kind is not baked. Its version serves one document: every drawn piece
 * as a slot a style pack dresses (its stable identity, its look role `family.leaf`, the base centre
 * of its box, its quarter turns, its box, its family's fit and the engine's own primitive), the
 * floor a person walks and the boxes they keep out of, and where a person arrives. Everything is in
 * the site's own frame: x east, y north, z up, integer millimetres from the site's south-west
 * corner. The region's east is x and its south is minus y.
 *
 * This module reads the document and refuses anything else by name. It decides no look.
 */

export const SITE_DRAWING_PROFILE = 'exulanica.site-drawing/v1';

export type SiteFit = 'contain' | 'fill' | 'tile' | 'surface';
export type SitePrimitive = 'box' | 'plane' | 'gable' | 'none';

export interface SiteUvFrame {
  readonly originMm: readonly [number, number, number];
  readonly uAxisMm: readonly [number, number, number];
  readonly vAxisMm: readonly [number, number, number];
}

export interface SiteSlot {
  readonly identity: string;
  readonly part: string;
  readonly label: string;
  /** The look role a style pack dresses: `family.leaf`. */
  readonly lookRole: string;
  readonly family: string;
  readonly leaf: string;
  /** The base centre of the slot's box, in site millimetres. */
  readonly positionMm: readonly [x: number, y: number, z: number];
  readonly yawQuarterTurns: 0 | 1 | 2 | 3;
  /** Width along the slot's front, depth, height, in millimetres. */
  readonly boxMm: readonly [width: number, depth: number, height: number];
  readonly front: '+y';
  readonly fit: SiteFit;
  readonly primitive: SitePrimitive;
  readonly uvFrame?: SiteUvFrame;
}

export type SiteRectMm = readonly [x0: number, y0: number, x1: number, y1: number];

export interface SiteDrawing {
  readonly worldId: string;
  readonly receiptSha256: string;
  readonly kind: { readonly kind: string; readonly version: number; readonly label: string };
  readonly extent: { readonly widthMm: number; readonly depthMm: number; readonly enclosure: 'open' | 'indoor' };
  readonly arrival: {
    readonly positionMm: readonly [number, number, number];
    readonly facingMm: readonly [number, number];
  };
  readonly slots: readonly SiteSlot[];
  readonly walk: {
    readonly floorMm: SiteRectMm;
    readonly blockersMm: readonly SiteRectMm[];
    readonly keepOutMm: readonly SiteRectMm[];
  };
  readonly seats: readonly { readonly identity: string; readonly seatHeightMm: number }[];
}

export class SiteDrawingError extends Error {
  override readonly name = 'SiteDrawingError';
}

function fail(message: string): never {
  throw new SiteDrawingError(message);
}

function object(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) fail(`The site drawing's ${what} is not an object.`);
  return value as Record<string, unknown>;
}

function integer(value: unknown, what: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) fail(`The site drawing's ${what} is not a whole number.`);
  return value;
}

function text(value: unknown, what: string): string {
  if (typeof value !== 'string') fail(`The site drawing's ${what} is not text.`);
  return value;
}

function triple(value: unknown, what: string): readonly [number, number, number] {
  if (!Array.isArray(value) || value.length !== 3) fail(`The site drawing's ${what} is not three figures.`);
  return Object.freeze([integer(value[0], what), integer(value[1], what), integer(value[2], what)]);
}

function rect(value: unknown, what: string): SiteRectMm {
  if (!Array.isArray(value) || value.length !== 4) fail(`The site drawing's ${what} is not a rectangle.`);
  const [x0, y0, x1, y1] = value.map((v) => integer(v, what));
  if (!(x0! < x1! && y0! < y1!)) fail(`The site drawing's ${what} is not a rectangle from its least corner.`);
  return Object.freeze([x0!, y0!, x1!, y1!]);
}

const FITS: readonly SiteFit[] = ['contain', 'fill', 'tile', 'surface'];
const PRIMITIVES: readonly SitePrimitive[] = ['box', 'plane', 'gable', 'none'];
const LOOK = /^([a-z]+)\.([a-z][a-z0-9_]{0,47})$/u;

function slot(value: unknown, index: number): SiteSlot {
  const row = object(value, `slot ${index}`);
  const look = text(row['lookRole'], `slot ${index} look role`);
  const parts = LOOK.exec(look);
  if (parts === null) fail(`The site drawing's slot ${index} names no look role family.leaf.`);
  const yaw = integer(row['yawQuarterTurns'], `slot ${index} quarter turns`);
  if (yaw < 0 || yaw > 3) fail(`The site drawing's slot ${index} turns by 0 to 3 quarter turns.`);
  const fit = text(row['fit'], `slot ${index} fit`) as SiteFit;
  if (!FITS.includes(fit)) fail(`The site drawing's slot ${index} names no fit.`);
  const primitive = text(row['primitive'], `slot ${index} primitive`) as SitePrimitive;
  if (!PRIMITIVES.includes(primitive)) fail(`The site drawing's slot ${index} names no primitive.`);
  if (row['front'] !== '+y') fail(`The site drawing's slot ${index} faces its +y.`);
  const box = triple(row['boxMm'], `slot ${index} box`);
  if (box.some((side) => side < 0)) fail(`The site drawing's slot ${index} has a negative side.`);
  const uv = row['uvFrame'];
  const frame = uv === undefined ? undefined : object(uv, `slot ${index} uv frame`);
  return Object.freeze({
    identity: text(row['identity'], `slot ${index} identity`),
    part: text(row['part'], `slot ${index} part`),
    label: text(row['label'], `slot ${index} label`),
    lookRole: look,
    family: parts[1]!,
    leaf: parts[2]!,
    positionMm: triple(row['positionMm'], `slot ${index} position`),
    yawQuarterTurns: yaw as 0 | 1 | 2 | 3,
    boxMm: box,
    front: '+y',
    fit,
    primitive,
    ...(frame === undefined
      ? {}
      : {
        uvFrame: Object.freeze({
          originMm: triple(frame['originMm'], `slot ${index} uv origin`),
          uAxisMm: triple(frame['uAxisMm'], `slot ${index} uv u axis`),
          vAxisMm: triple(frame['vAxisMm'], `slot ${index} uv v axis`),
        }),
      }),
  });
}

/** Read a served site drawing, or refuse it by name. */
export function parseSiteDrawing(value: unknown): SiteDrawing {
  const body = object(value, 'document');
  if (body['profile'] !== SITE_DRAWING_PROFILE) fail(`The site drawing is not ${SITE_DRAWING_PROFILE}.`);
  const kind = object(body['kind'], 'kind');
  const extent = object(body['extent'], 'extent');
  const enclosure = extent['enclosure'];
  if (enclosure !== 'open' && enclosure !== 'indoor') fail('The site drawing names no enclosure.');
  const arrival = object(body['arrival'], 'arrival');
  const facing = arrival['facingMm'];
  if (!Array.isArray(facing) || facing.length !== 2) fail("The site drawing's arrival faces no way.");
  const walk = object(body['walk'], 'walk');
  const slots = body['slots'];
  if (!Array.isArray(slots)) fail("The site drawing's slots are not a list.");
  const blockers = walk['blockersMm'];
  const keepOut = walk['keepOutMm'];
  const seats = body['seats'];
  if (!Array.isArray(blockers) || !Array.isArray(keepOut) || !Array.isArray(seats)) {
    fail("The site drawing's walk or seats are not lists.");
  }
  const read = slots.map(slot);
  const identities = new Set(read.map((one) => one.identity));
  if (identities.size !== read.length) fail('Two slots of the site drawing share an identity.');
  return Object.freeze({
    worldId: text(body['world_id'], 'world'),
    receiptSha256: text(body['receipt_sha256'], 'receipt'),
    kind: Object.freeze({
      kind: text(kind['kind'], 'kind key'),
      version: integer(kind['version'], 'kind version'),
      label: text(kind['label'], 'kind label'),
    }),
    extent: Object.freeze({
      widthMm: integer(extent['widthMm'], 'width'),
      depthMm: integer(extent['depthMm'], 'depth'),
      enclosure,
    }),
    arrival: Object.freeze({
      positionMm: triple(arrival['positionMm'], 'arrival'),
      facingMm: Object.freeze([integer(facing[0], 'facing'), integer(facing[1], 'facing')]) as readonly [number, number],
    }),
    slots: Object.freeze(read),
    walk: Object.freeze({
      floorMm: rect(walk['floorMm'], 'floor'),
      blockersMm: Object.freeze(blockers.map((one, index) => rect(one, `blocker ${index}`))),
      keepOutMm: Object.freeze(keepOut.map((one, index) => rect(one, `keep-out ${index}`))),
    }),
    seats: Object.freeze(seats.map((one, index) => {
      const row = object(one, `seat ${index}`);
      return Object.freeze({
        identity: text(row['identity'], `seat ${index}`),
        seatHeightMm: integer(row['seatHeightMm'], `seat ${index} height`),
      });
    })),
  });
}
