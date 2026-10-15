import {readTerrainDressing, type TerrainDressing} from './terrain-dressing.js';
import { LAND_CHUNK_MM, readSupportNavigation, readHeightfieldGeometry, readHeightfieldContact, heightfieldAt, type HeightfieldContact, type HeightfieldPointContact, type LandWater, type SupportNavigation } from '@exulanica/atlas-core';
import { sha256Hex, canonicalJson } from '../character/digest.js';
/**
 * The drawing a site world's records make, in its level-floor or explicit-support profile.
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
export const SITE_DRAWING_SUPPORT_PROFILE = 'exulanica.site-drawing/v2';

export const SITE_DRAWING_TERRAIN_PROFILE = 'exulanica.site-drawing/v3';
export const SITE_DRAWING_DRESSED_TERRAIN_PROFILE = 'exulanica.site-drawing/v4';
/**
 * A site laid out on stated land (`docs/landform-contract.md`, sites on land): the version 1 slots,
 * each standing at the graded land's height under it, some marked `drape`, and a `land` section
 * naming the land's chunks and backdrop by digest, which the page reads before it draws the site.
 */
export const SITE_DRAWING_LAND_PROFILE = 'exulanica.site-drawing/v5';

export type SiteFit = 'contain' | 'fill' | 'tile' | 'surface';
export type SitePrimitive = 'box' | 'plane' | 'gable' | 'none';

export interface SiteUvFrame {
  readonly originMm: readonly [number, number, number];
  readonly uAxisMm: readonly [number, number, number];
  readonly vAxisMm: readonly [number, number, number];
}

export interface SiteSlot {
  /** Derived from a canonical support network, never inferred from a render mesh. */
  readonly supportSurfaceId?: string;
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
  /**
   * A slot of a site on land that follows the land: each point of it stands as far above the land
   * under it as its base stands above the land under its base's centre. Stated only on land.
   */
  readonly drape?: true;
  /**
   * The building a slot is a piece of, by its own slot's identity: its walls, lintels, doors and
   * roof, its rooms' floors and the fixtures in its rooms. A pack that dresses the building's own
   * slot with one piece hides the building's envelope (`site-dresser.ts`). Absent on everything else.
   */
  readonly structure?: string;
  /**
   * A building's own storey height, in millimetres, of which its height is a whole number: stated
   * only on a building's own slot (family `structure`), so what dresses its walls (a facade's rows
   * of windows) follows its storeys. Absent on every other slot, and in a drawing served before it
   * was stated.
   */
  readonly storeyHeightMm?: number;
  /**
   * A building's arcade: how many equal bays its front is divided into, an arch in each, and how
   * deep the covered walk behind the arches is, in millimetres. Stated together and only on a
   * building's own slot, so what dresses it draws its arches where people walk through them.
   * Absent on every building without an arcade, and in a drawing served before arcades.
   */
  readonly arcadeBays?: number;
  readonly loggiaDepthMm?: number;
}

/** What a site on land states of its land: each chunk's place and digest, the backdrop's and the water's. */
export interface SiteLandSection {
  readonly landSha256: string;
  readonly chunkMm: number;
  readonly chunks: readonly { readonly chunk: readonly [x: number, y: number]; readonly sha256: string }[];
  readonly backdropSha256: string;
  readonly water: readonly LandWater[];
}

export type SiteRectMm = readonly [x0: number, y0: number, x1: number, y1: number];

export interface StructuredSiteDrawing {
  readonly profile?: typeof SITE_DRAWING_PROFILE | typeof SITE_DRAWING_SUPPORT_PROFILE | typeof SITE_DRAWING_LAND_PROFILE;
  readonly support?: SupportNavigation;
  /** The land a site on land stands on, by digest; none for a site on level ground. */
  readonly land?: SiteLandSection;
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

/** Terrain has its own region frame and exact contact, with no structured-site slots. */
interface TerrainDrawingBase {
  readonly worldId: string;
  readonly regionId: 'region:generated';
  readonly receiptSha256: string;
  readonly boundsMm: { readonly east: readonly [number, number]; readonly south: readonly [number, number] };
  readonly terrain: HeightfieldContact;
  readonly arrival: {
    readonly positionMm: readonly [number, number, number];
    readonly facingMm: readonly [number, number];
    readonly contact: HeightfieldPointContact;
  };
}
export interface PlainTerrainSiteDrawing extends TerrainDrawingBase {readonly profile: typeof SITE_DRAWING_TERRAIN_PROFILE;}
export interface DressedTerrainSiteDrawing extends TerrainDrawingBase {
  readonly profile: typeof SITE_DRAWING_DRESSED_TERRAIN_PROFILE;
  readonly dressing: TerrainDressing;
  readonly dressingSha256: string;
}
export type TerrainSiteDrawing = PlainTerrainSiteDrawing | DressedTerrainSiteDrawing;
export type SiteDrawing = StructuredSiteDrawing | TerrainSiteDrawing;
export function isTerrainSiteDrawing(drawing: SiteDrawing): drawing is TerrainSiteDrawing {
  return drawing.profile === SITE_DRAWING_TERRAIN_PROFILE || drawing.profile === SITE_DRAWING_DRESSED_TERRAIN_PROFILE;
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

function slot(value: unknown, index: number, onLand: boolean): SiteSlot {
  const row = object(value, `slot ${index}`);
  const drape = row['drape'];
  if (drape !== undefined && (drape !== true || !onLand)) fail(`The site drawing's slot ${index} drapes only on land, and only as true.`);
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
  const structure = row['structure'] === undefined ? undefined : text(row['structure'], `slot ${index} structure`);
  const storeyHeight = row['storeyHeightMm'] === undefined ? undefined : integer(row['storeyHeightMm'], `slot ${index} storey height`);
  if (storeyHeight !== undefined) {
    if (parts[1] !== 'structure') fail(`The site drawing's slot ${index} states a storey height, and only a building's own slot does.`);
    if (storeyHeight <= 0 || box[2] % storeyHeight !== 0) fail(`The site drawing's slot ${index} storey height does not divide its ${box[2]} mm height.`);
  }
  const bays = row['arcadeBays'] === undefined ? undefined : integer(row['arcadeBays'], `slot ${index} arcade bays`);
  const loggia = row['loggiaDepthMm'] === undefined ? undefined : integer(row['loggiaDepthMm'], `slot ${index} covered walk depth`);
  if ((bays === undefined) !== (loggia === undefined)) fail(`The site drawing's slot ${index} states an arcade's bays and its covered walk's depth together.`);
  if (bays !== undefined && loggia !== undefined) {
    if (parts[1] !== 'structure') fail(`The site drawing's slot ${index} states an arcade, and only a building's own slot does.`);
    if (bays < 1) fail(`The site drawing's slot ${index} arcade has no bay.`);
    if (loggia <= 0 || loggia >= box[1]) fail(`The site drawing's slot ${index} covered walk is not inside its ${box[1]} mm depth.`);
  }
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
    ...(drape === true ? { drape: true as const } : {}),
    ...(structure === undefined ? {} : { structure }),
    ...(storeyHeight === undefined ? {} : { storeyHeightMm: storeyHeight }),
    ...(bays === undefined || loggia === undefined ? {} : { arcadeBays: bays, loggiaDepthMm: loggia }),
  });
}

/** Two whole numbers, as far from the site as its land reaches. */
function point(value: unknown, what: string): readonly [number, number] {
  if (!Array.isArray(value) || value.length !== 2) fail(`The site drawing's ${what} is not two figures.`);
  return Object.freeze([integer(value[0], what), integer(value[1], what)] as const);
}

const WATER_FIELDS: Readonly<Record<string, string>> = {
  sea: 'id kind level_mm side', lake: 'id kind level_mm centre_mm radius_mm', pond: 'id kind level_mm rect_mm',
  pool: 'id kind level_mm rect_mm', fall: 'id kind level_mm bottom_mm rect_mm side',
};
/** The sides a cascade's fall may fall toward. */
const FALL_SIDES: readonly string[] = ['north', 'east', 'south', 'west'];

/** The land section of a site on land: its chunks and backdrop by digest, and its water. */
function landSection(value: unknown): SiteLandSection {
  const row = closed(value, 'land_sha256 chunk_mm chunks backdrop_sha256 water', 'land');
  if (row['chunk_mm'] !== LAND_CHUNK_MM) fail(`The site drawing's land chunks are not ${LAND_CHUNK_MM} mm.`);
  const chunks = row['chunks'], water = row['water'];
  if (!Array.isArray(chunks) || chunks.length === 0 || !Array.isArray(water)) fail("The site drawing's land states no chunks or no water list.");
  const read = chunks.map((one, index) => {
    const chunk = closed(one, 'chunk sha256', `land chunk ${index}`);
    return Object.freeze({ chunk: pair(chunk['chunk'], `land chunk ${index} place`), sha256: digest(chunk['sha256'], `land chunk ${index} digest`) });
  });
  if (new Set(read.map((one) => one.chunk.join(','))).size !== read.length) fail("The site drawing's land states a chunk twice.");
  return Object.freeze({
    landSha256: digest(row['land_sha256'], 'land digest'),
    chunkMm: LAND_CHUNK_MM,
    chunks: Object.freeze(read),
    backdropSha256: digest(row['backdrop_sha256'], 'backdrop digest'),
    water: Object.freeze(water.map((one, index): LandWater => {
      const kind = object(one, `land water ${index}`)['kind'];
      const fields = typeof kind === 'string' ? WATER_FIELDS[kind] : undefined;
      if (fields === undefined) fail(`The site drawing's land water ${index} is not sea, lake, pond, pool or fall.`);
      const body = closed(one, fields, `land water ${index}`);
      const id = text(body['id'], `land water ${index} id`), levelMm = integer(body['level_mm'], `land water ${index} level`);
      if (kind === 'sea') return Object.freeze({ id, kind, levelMm, side: text(body['side'], `land water ${index} side`) });
      if (kind === 'lake') return Object.freeze({ id, kind, levelMm, centreMm: point(body['centre_mm'], `land water ${index} centre`), radiusMm: integer(body['radius_mm'], `land water ${index} radius`) });
      if (kind !== 'fall') {
        const [x0, y0, x1, y1] = rect(body['rect_mm'], `land water ${index} rectangle`);
        return Object.freeze({ id, kind: kind as 'pond' | 'pool', levelMm, rectMm: Object.freeze([x0, y0, x1, y1] as const) });
      }
      const line = body['rect_mm'];
      if (!Array.isArray(line) || line.length !== 4) fail(`The site drawing's land water ${index} line is not four numbers.`);
      const [x0, y0, x1, y1] = line.map((v) => integer(v, `land water ${index} line`)) as [number, number, number, number];
      if (!((x0 === x1 && y0 < y1) || (y0 === y1 && x0 < x1))) fail(`The site drawing's land water ${index} is a fall that is not a line across its channel.`);
      const rectMm = Object.freeze([x0, y0, x1, y1] as const);
      const bottomMm = integer(body['bottom_mm'], `land water ${index} bottom`);
      if (bottomMm >= levelMm) fail(`The site drawing's land water ${index} is a fall that does not fall.`);
      const side = text(body['side'], `land water ${index} side`);
      if (!FALL_SIDES.includes(side)) fail(`The site drawing's land water ${index} falls toward ${side}, not north, east, south or west.`);
      return Object.freeze({ id, kind: 'fall' as const, levelMm, bottomMm, rectMm, side: side as 'north' | 'east' | 'south' | 'west' });
    })),
  });
}

/** Read a served site drawing, or refuse it by name. */
export function parseSiteDrawing(value: unknown): SiteDrawing {
  const body = object(value, 'document');
  if ((body['profile'] === SITE_DRAWING_TERRAIN_PROFILE || body['profile'] === SITE_DRAWING_DRESSED_TERRAIN_PROFILE)) return parseTerrainDrawing(body);
  const profile = body['profile'];
  if (profile !== SITE_DRAWING_PROFILE && profile !== SITE_DRAWING_SUPPORT_PROFILE && profile !== SITE_DRAWING_LAND_PROFILE) fail(`The site drawing is not ${SITE_DRAWING_PROFILE}, ${SITE_DRAWING_SUPPORT_PROFILE} or ${SITE_DRAWING_LAND_PROFILE}.`);
  const onLand = profile === SITE_DRAWING_LAND_PROFILE;
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
  const supportRaw = body['profile'] === SITE_DRAWING_SUPPORT_PROFILE ? object(body['support'], 'support adapter') : null;
  let support: SupportNavigation | undefined;
  if (supportRaw !== null) {
    if (supportRaw['profile'] !== 'exulanica.support-adapter/v1') fail('The site support adapter has an unknown profile.');
    const entrySurface = text(supportRaw['entry_surface_id'], 'entry surface');
    support = readSupportNavigation(supportRaw['network'], text(body['world_id'], 'world'), entrySurface, sha256Hex);
    if (support.document.frame.name !== 'region:generated' || support.document.frame.datum !== 'region-origin') fail('The site support network uses another region frame.');
    const binding = object(supportRaw['node_surfaces'], 'node surface bindings');
    for (const [key, value] of Object.entries(binding)) {
      if (!/^support-node:[0-9a-f]{64}$/.test(key) || typeof value !== 'string' || !support.surfaces.has(value)) fail('The site support node binding is not a qualified admitted surface.');
    }
    if (!/^[0-9a-f]{64}$/.test(text(supportRaw['place_sha256'], 'support place digest'))
        || binding[text(supportRaw['entry_node_id'], 'support entry node')] !== entrySurface) fail('The site support entry/place binding is invalid.');
  }
  const read = slots.map((one, index) => slot(one, index, onLand));
  const land = onLand ? landSection(body['land']) : undefined;
  // Network supports are canonical walking geometry. Draw their exact top planes in the same dresser.
  if (support !== undefined) for (const surface of support.document.surfaces) {
    if (surface.surface_id === support.entry.surfaceId) continue;
    const [east0, south0, east1, south1] = surface.rect_mm;
    read.push(Object.freeze({ identity: `support-plane:${support.document.document_sha256}:${surface.surface_id}`,
      supportSurfaceId: surface.surface_id, part: 'walking_support', label: surface.surface_id, lookRole: 'ground.paving', family: 'ground', leaf: 'paving',
      positionMm: Object.freeze([(east0 + east1) / 2, -(south0 + south1) / 2, surface.support_z_mm]) as readonly [number, number, number],
      yawQuarterTurns: 0, boxMm: Object.freeze([east1-east0, south1-south0, 0]) as readonly [number, number, number],
      front: '+y', fit: 'surface', primitive: 'plane' }));
  }
  const identities = new Set(read.map((one) => one.identity));
  if (identities.size !== read.length) fail('Two slots of the site drawing share an identity.');
  // A piece of a building names the building's own slot, which is a slot of the drawing and itself
  // the piece of no building.
  const owners = new Set(read.flatMap((one) => (one.structure === undefined ? [] : [one.structure])));
  for (const one of read) {
    if (one.structure !== undefined && !identities.has(one.structure)) fail(`The site drawing's slot ${one.identity} is a piece of ${one.structure}, which is no slot of the drawing.`);
    if (one.structure !== undefined && owners.has(one.identity)) fail(`The site drawing's slot ${one.identity} is a building's own slot and a piece of another.`);
  }
  return Object.freeze({
    profile,
    ...(support === undefined ? {} : { support }),
    ...(land === undefined ? {} : { land }),
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

/** Require a structured site before using a dresser or a flat-site projection. */
export function parseStructuredSiteDrawing(value: unknown): StructuredSiteDrawing {
  const drawing = parseSiteDrawing(value);
  if (isTerrainSiteDrawing(drawing)) fail('The drawing is terrain, not a structured site.');
  return drawing;
}

function closed(value: unknown, fields: string, what: string): Record<string, unknown> {
  const row = object(value, what);
  if (Object.keys(row).sort().join(' ') !== fields.split(' ').sort().join(' ')) fail(`The site drawing's ${what} has unexpected or missing fields.`);
  return row;
}
function pair(value: unknown, what: string): readonly [number, number] {
  if (!Array.isArray(value) || value.length !== 2) fail(`The site drawing's ${what} is not two figures.`);
  const result = value.map(v => integer(v, what));
  if (result.some(v => Math.abs(v) > 512000)) fail(`The site drawing's ${what} is outside the bounded frame.`);
  return Object.freeze([result[0]!, result[1]!]);
}
function digest(value: unknown, what: string): string {
  const result = text(value, what);
  if (!/^[0-9a-f]{64}$/.test(result)) fail(`The site drawing's ${what} is not a SHA-256 digest.`);
  return result;
}
function parseTerrainDrawing(body: Record<string, unknown>): TerrainSiteDrawing {
  closed(body, 'profile world_id region_id receipt_sha256 composer frame bounds_mm terrain arrival capabilities', 'terrain document');
  const dressed = body['profile'] === SITE_DRAWING_DRESSED_TERRAIN_PROFILE;
  const composer = closed(body['composer'], 'key version', 'composer');
  if (composer['key'] !== 'site-plan' || composer['version'] !== (dressed ? 4 : 3)) fail('The terrain drawing does not bind its site-plan composer.');
  if (body['region_id'] !== 'region:generated' || body['frame'] !== 'region-local-east-up-south-mm') fail('The terrain drawing uses another region frame.');
  const capabilities = closed(body['capabilities'], 'person_navigation passive_flat_patch society_projection', 'capabilities');
  if (capabilities['person_navigation'] !== true || capabilities['passive_flat_patch'] !== true || capabilities['society_projection'] !== 'unavailable') fail('The terrain drawing declares unsupported capabilities.');
  const raw = closed(body['terrain'], 'geometry geometry_sha256 contact contact_sha256' + (dressed ? ' dressing dressing_sha256' : ''), 'terrain');
  const geometry = readHeightfieldGeometry(raw['geometry'], sha256Hex, digest(raw['geometry_sha256'], 'geometry digest'));
  const terrain = readHeightfieldContact(raw['contact'], geometry, sha256Hex, digest(raw['contact_sha256'], 'contact digest'));
  const bounds = closed(body['bounds_mm'], 'east south', 'bounds');
  const east = pair(bounds['east'], 'east bounds'), south = pair(bounds['south'], 'south bounds');
  if (east[0] !== 0 || south[1] !== 0 || east[0] !== geometry.data.east_mm[0] || east[1] !== geometry.data.east_mm.at(-1)
      || south[0] !== geometry.data.south_mm[0] || south[1] !== geometry.data.south_mm.at(-1)) fail('The terrain bounds differ from its admitted geometry.');
  const arrival = closed(body['arrival'], 'position_mm facing_mm contact', 'terrain arrival');
  const position = triple(arrival['position_mm'], 'terrain arrival'), facing = pair(arrival['facing_mm'], 'terrain facing');
  if (facing[0] === 0 && facing[1] === 0) fail('The terrain arrival faces no way.');
  const result = heightfieldAt(terrain, [position[0], position[2]]);
  if (result.status !== 'clear' || result.contact === null) fail('The terrain arrival has no complete person clearance.');
  if (canonicalJson(arrival['contact']) !== canonicalJson(result.contact)) fail('The terrain arrival contact differs from its admitted geometry.');
  const n = BigInt(result.contact.height_mm.numerator), d = BigInt(result.contact.height_mm.denominator), abs = n < 0n ? -n : n;
  const rounded = (abs / d + (2n * (abs % d) > d ? 1n : 0n)) * (n < 0n ? -1n : 1n);
  if (position[1] !== Number(rounded)) fail('The terrain arrival height differs from canonical rounding.');
  const dressingSha256 = dressed ? digest(raw['dressing_sha256'], 'dressing digest') : null;
  const dressing = dressingSha256 === null ? null : readTerrainDressing(raw['dressing'], dressingSha256);
  return Object.freeze({... (dressing === null ? {profile: SITE_DRAWING_TERRAIN_PROFILE} as const
    : {profile: SITE_DRAWING_DRESSED_TERRAIN_PROFILE, dressing, dressingSha256: dressingSha256!} as const), worldId: text(body['world_id'], 'world'), regionId: 'region:generated',
    receiptSha256: digest(body['receipt_sha256'], 'receipt'), boundsMm: Object.freeze({east, south}), terrain,
    arrival: Object.freeze({positionMm: position, facingMm: facing, contact: result.contact})});
}
