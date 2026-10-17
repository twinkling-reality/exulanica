import * as pc from 'playcanvas';
import {
  LAND_CELL_MM, LAND_CHUNK_MM, backdropMeshData, chunkHeightMm, landBackdropColour, readLandBackdrop, readLandChunk, readSiteTop,
  siteTopCellHeld, siteTopHeightMm, valueNoise,
  type HeightfieldDigest, type LandBackdrop, type LandChunk, type LandscapeDrawing, type LandSurfaces, type LandWater, type SiteTop,
  type SiteTopRun,
} from '@exulanica/atlas-core';
import type { GeneratedTileHost } from '../generated-tile/binding-contract.js';
import { buildSurfaceMesh, type SurfaceBatch } from '../generated-tile/surface-mesh.js';
import { landSurfaceMaterial } from './land-slope.js';
import type { SiteLandSection, SiteLandWall, SiteSlot, SiteTopSection, StructuredSiteDrawing } from './site-drawing.js';
import type { DrawnSiteSlots } from './site-primitives.js';

/**
 * A site world's land, read and drawn: the near land a person walks in chunks, the backdrop to the
 * horizon, the water over them, and the slots that follow the land (`docs/landform-contract.md`,
 * sites on land).
 *
 * The drawing names each chunk and the backdrop by the SHA-256 of its canonical JSON; the page
 * fetches them by those digests and `readSiteLand` holds each to its digest, so the land drawn is
 * the land the drawing was made on, or nothing is drawn. Heights are millimetres above the land's
 * datum, the sea's level, in the site's own frame (x east, y north from its south-west corner); the
 * renderer's frame is east, up and south in metres, so a site point (x, y) is the renderer's
 * (x / 1000, -y / 1000).
 *
 * A site on a placed volume's top, a floating island's, stands on the volume's graded top instead
 * (`exulanica.site-top/v1`, read by `readSiteTopLand`): the same kind of land to every reader that
 * asks its height, where it is dry and its water, but with no chunks and no backdrop. Its heights
 * are above the volume's level 0, the site frame's own; the landscape's land below it is drawn
 * with the volumes (`site-volumes.ts`). Only the cells of its lattice with rock under them are
 * drawn as land, a few millimetres over the volume's own top faces; the volume's rock draws the
 * rest of the top.
 *
 * A site on level ground has no land: none of this is read, made or asked, and every reader that
 * takes a ground function is handed none.
 */

/** The ground land wears where nothing it stands for is drawn: a site's with no base ground, and a town's. */
export const LAND_GROUND_RGB = [0.47, 0.56, 0.33] as const;
/**
 * The rock a volume is drawn in where nothing dresses it (`site-volumes.ts`): the engine's own, as
 * the land's ground has. The land's retaining walls wear it where the land's surfaces hand no rock.
 */
export const VOLUME_ROCK_RGB: readonly [number, number, number] = [0.47, 0.455, 0.431];
/** Plain water where the drawing's own water material is not handed over. */
const PLAIN_WATER: readonly [number, number, number] = [0.24, 0.42, 0.55];
/** Scenery stands only on land at least this far above the sea's level. */
const DRY_ABOVE_SEA_MM = 300;
/** How far past the backdrop's reach the camera's far plane stands, as a share of it. */
const FAR_MARGIN = 1.15;
/** How far a retaining wall's coping stands above the upper level it holds. */
const WALL_COPING_MM = 100;
/**
 * How far over the volume's own top faces a graded top's cells are drawn, so the top is the one
 * seen where both lie: half of the drawing's layer step (6 mm), so a ground draped a layer over the
 * land still lies over it.
 */
const TOP_LIFT_MM = 3;

/** What every land a site stands on answers, whatever it is read from. */
interface SiteGround {
  /** The land's height under a site point, millimetres east and north; the near land's edge beyond it. */
  readonly groundMm: (eastMm: number, northMm: number) => number;
  /** The land's height under a renderer point, metres east and south: the scene's and the society's frame. */
  readonly groundM: (eastM: number, southM: number) => number;
  /** Whether scenery may stand at a site point: on the near land, above the sea and out of every lake and pond. */
  readonly dryAt: (eastMm: number, northMm: number) => boolean;
  /** The bytes its documents were served as. */
  readonly servedBytes: number;
}

/** The land a site on land stands on, read and held to the digests its drawing names: its chunks and backdrop. */
export interface SiteNearLand extends SiteGround {
  readonly section: SiteLandSection;
  readonly chunks: readonly LandChunk[];
  readonly backdrop: LandBackdrop;
  readonly top: null;
}

/**
 * The graded top a site on a placed volume's top stands on, read and held to the digest its drawing
 * names. Heights are above the volume's level 0, and beyond the top's lattice its nearest edge's. It
 * has no chunks (land cover, which grows over chunks, grows none on it) and no backdrop.
 */
export interface SiteTopLand extends SiteGround {
  readonly section: SiteTopSection;
  readonly chunks: readonly LandChunk[];
  readonly backdrop: null;
  readonly top: SiteTop;
}

/** The land a site on land, or on a volume's top, stands on, read and held to the digests its drawing names. */
export type SiteLand = SiteNearLand | SiteTopLand;

/** A chunk's place as one number, so a lookup makes no text. */
const placeKey = (chunkX: number, chunkY: number): number => (chunkX + 4096) * 8193 + (chunkY + 4096);

/**
 * The near land's height at any point, allocating nothing: a person's feet are asked for on every
 * frame. A point beyond the chunks is asked at the nearest point of their bounds.
 */
class GroundSampler {
  readonly #byPlace = new Map<number, LandChunk>();
  readonly #east: readonly [number, number];
  readonly #north: readonly [number, number];

  constructor(chunks: readonly LandChunk[]) {
    for (const chunk of chunks) this.#byPlace.set(placeKey(chunk.chunkX, chunk.chunkY), chunk);
    const xs = chunks.map((chunk) => chunk.chunkX), ys = chunks.map((chunk) => chunk.chunkY);
    this.#east = [Math.min(...xs) * LAND_CHUNK_MM, (Math.max(...xs) + 1) * LAND_CHUNK_MM];
    this.#north = [Math.min(...ys) * LAND_CHUNK_MM, (Math.max(...ys) + 1) * LAND_CHUNK_MM];
  }

  #in(chunkX: number, chunkY: number, eastMm: number, northMm: number): number | null {
    const chunk = this.#byPlace.get(placeKey(chunkX, chunkY));
    return chunk === undefined ? null : chunkHeightMm(chunk, eastMm, northMm);
  }

  heightMm(eastMm: number, northMm: number): number {
    const x = Math.min(this.#east[1], Math.max(this.#east[0], eastMm));
    const y = Math.min(this.#north[1], Math.max(this.#north[0], northMm));
    const cx = Math.floor(x / LAND_CHUNK_MM), cy = Math.floor(y / LAND_CHUNK_MM);
    // A point on a chunk's west or south edge is its neighbour's too, which holds the same samples.
    const west = x === cx * LAND_CHUNK_MM, south = y === cy * LAND_CHUNK_MM;
    return this.#in(cx, cy, x, y)
      ?? (west ? this.#in(cx - 1, cy, x, y) : null)
      ?? (south ? this.#in(cx, cy - 1, x, y) : null)
      ?? (west && south ? this.#in(cx - 1, cy - 1, x, y) : null)
      ?? 0;
  }
}

/** Whether a site point lies under a body of water the land states. */
function underWater(water: readonly LandWater[], eastMm: number, northMm: number, groundMm: number): boolean {
  for (const body of water) {
    if (body.kind === 'sea' && groundMm < body.levelMm + DRY_ABOVE_SEA_MM) return true;
    if (body.kind === 'lake' && Math.hypot(eastMm - body.centreMm[0], northMm - body.centreMm[1]) <= body.radiusMm) return true;
    if ((body.kind === 'pond' || body.kind === 'pool') && eastMm >= body.rectMm[0] && eastMm <= body.rectMm[2] && northMm >= body.rectMm[1] && northMm <= body.rectMm[3]) return true;
  }
  return false;
}

/**
 * Read a site's land from the documents served for it: every chunk its drawing names, by place,
 * and its backdrop, each held to the digest the drawing names. Refuses (throws) a drawing with no
 * land, a chunk missing or not the one named, and a backdrop not the one named.
 */
export function readSiteLand(
  drawing: StructuredSiteDrawing,
  chunks: ReadonlyMap<string, unknown>,
  backdrop: unknown,
  digest: HeightfieldDigest,
  servedBytes = 0,
): SiteNearLand {
  const section = drawing.land;
  if (section === undefined) throw new Error('The site drawing states no land.');
  return readLandSection(section, chunks, backdrop, digest, servedBytes);
}

/**
 * Read land from the documents served for its section, a site's drawing's or a town's own: every
 * chunk it names, by place, and its backdrop, each held to the digest the section names. Refuses
 * (throws) a chunk missing or not the one named, and a backdrop not the one named.
 */
export function readLandSection(
  section: SiteLandSection,
  chunks: ReadonlyMap<string, unknown>,
  backdrop: unknown,
  digest: HeightfieldDigest,
  servedBytes = 0,
): SiteNearLand {
  const read = section.chunks.map(({ chunk: [x, y], sha256 }) => {
    const raw = chunks.get(`${x},${y}`);
    if (raw === undefined) throw new Error(`The land chunk (${x}, ${y}) its land section names was not served.`);
    const one = readLandChunk(raw, digest, sha256);
    if (one.chunkX !== x || one.chunkY !== y) throw new Error(`The land chunk served for (${x}, ${y}) states another place.`);
    return one;
  });
  const far = readLandBackdrop(backdrop, digest, section.backdropSha256);
  const sampler = new GroundSampler(read);
  const groundMm = (eastMm: number, northMm: number): number => sampler.heightMm(eastMm, northMm);
  return Object.freeze({
    section,
    chunks: Object.freeze(read),
    backdrop: far,
    groundMm,
    groundM: (eastM: number, southM: number): number => sampler.heightMm(eastM * 1000, -southM * 1000) / 1000,
    dryAt: (eastMm: number, northMm: number): boolean => !underWater(section.water, eastMm, northMm, groundMm(eastMm, northMm)),
    servedBytes,
    top: null,
  });
}

/**
 * Read the graded top a site on a placed volume's top stands on, from the document served for it
 * (`land/top`), held to the digest its drawing names; every cell its drawing draws as land must lie
 * on the top's lattice. Refuses (throws) a drawing on no top, a top that is not the one named and a
 * cell off its lattice.
 */
export function readSiteTopLand(drawing: StructuredSiteDrawing, raw: unknown, digest: HeightfieldDigest, servedBytes = 0): SiteTopLand {
  const section = drawing.top;
  if (section === undefined) throw new Error("The site drawing stands on no volume's top.");
  const top = readSiteTop(raw, digest, section.topSha256);
  for (const [row, , last] of section.rockCells) {
    if (row >= top.rows - 1 || last >= top.columns - 1) throw new Error(`The site drawing draws a cell of its top's row ${row} off the top's lattice.`);
  }
  const groundMm = (eastMm: number, northMm: number): number => siteTopHeightMm(top, eastMm, northMm);
  return Object.freeze({
    section,
    chunks: Object.freeze([]),
    backdrop: null,
    top,
    groundMm,
    groundM: (eastM: number, southM: number): number => siteTopHeightMm(top, eastM * 1000, -southM * 1000) / 1000,
    dryAt: (eastMm: number, northMm: number): boolean => !underWater(section.water, eastMm, northMm, groundMm(eastMm, northMm)),
    servedBytes,
  });
}

/**
 * Read the land below a site on a volume's top from the documents served for its landscape's
 * ground (`landscape/ground?sha256=`): every chunk the ground names, by place, and its backdrop,
 * each held to the digest the ground names, as `readLandSection` reads a site's land. Its heights
 * and places are the landscape's own, above the sea, never the site's: it is drawn under the
 * landscape's root, which stands the landscape where the site's frame puts it (`site-volumes.ts`).
 * Refuses (throws) a landscape with no ground, and whatever `readLandSection` refuses.
 */
export function readLandscapeGround(
  landscape: LandscapeDrawing,
  chunks: ReadonlyMap<string, unknown>,
  backdrop: unknown,
  digest: HeightfieldDigest,
  servedBytes = 0,
): SiteNearLand {
  if (landscape.ground === null) throw new Error('The landscape states no land below its site.');
  return readLandSection(landscape.ground, chunks, backdrop, digest, servedBytes);
}

/** A site rectangle's extent of a slot in plan: east and north half sides, its quarter turns applied. */
function halfSides(slot: SiteSlot): readonly [number, number] {
  const turned = slot.yawQuarterTurns % 2 !== 0;
  return [(turned ? slot.boxMm[1] : slot.boxMm[0]) / 2, (turned ? slot.boxMm[0] : slot.boxMm[1]) / 2];
}

/** The lattice lines a span crosses, with its two ends: where the land's height may bend. */
function stations(low: number, high: number): number[] {
  const out = [low];
  for (let at = Math.floor(low / LAND_CELL_MM) * LAND_CELL_MM + LAND_CELL_MM; at < high; at += LAND_CELL_MM) out.push(at);
  out.push(high);
  return out;
}

/** What draping a site's slots changed, so it can be put back. */
export interface DrapedSlots {
  /** Slots whose shape follows the land now. */
  readonly draped: number;
  /** Puts back every shape as the slots drew it; the draped meshes stay until `destroy`. */
  undrape(): void;
  destroy(): void;
}

/**
 * Lay every slot a site on land marks `drape` on the land: a plane becomes a mesh over its
 * rectangle that bends where the land bends, and a box's corners rise and fall with the land under
 * them, each point as far above the land as the slot's base stands above the land under its base's
 * centre. The slot's entity and its material are kept; only its shape's mesh and its shape's own
 * placing change, and `undrape` puts both back.
 */
export function drapeSiteSlots(device: pc.GraphicsDevice, drawing: StructuredSiteDrawing, drawn: DrawnSiteSlots, land: SiteLand): DrapedSlots {
  const restore: (() => void)[] = [];
  const meshes: pc.Mesh[] = [];
  const point = new pc.Vec3();
  for (const slot of drawing.slots) {
    if (slot.drape !== true || (slot.primitive !== 'plane' && slot.primitive !== 'box')) continue;
    const entity = drawn.entities.get(slot.identity);
    const shape = entity?.findByName(`${slot.identity}:shape`) as pc.Entity | null | undefined;
    const instance = shape?.render?.meshInstances[0];
    if (entity === undefined || shape == null || instance === undefined) continue;
    const [cx, cy, cz] = slot.positionMm;
    const layerMm = Math.round(cz - land.groundMm(cx, cy));
    const toLocal = entity.getLocalTransform().clone().invert();
    const toRoot = entity.getLocalTransform().clone();
    const positions: number[] = [], surfaceMm: number[] = [], indices: number[] = [];
    const [width, depth, height] = slot.boxMm;
    if (slot.primitive === 'plane') {
      const [east, north] = halfSides(slot);
      const xs = stations(cx - east, cx + east), ys = stations(cy - north, cy + north);
      for (const y of ys) for (const x of xs) {
        toLocal.transformPoint(point.set(x / 1000, (land.groundMm(x, y) + layerMm) / 1000, -y / 1000), point);
        positions.push(point.x, point.y, point.z);
        surfaceMm.push(point.x * 1000, point.z * 1000);
      }
      const w = xs.length;
      for (let j = 0; j + 1 < ys.length; j += 1) for (let i = 0; i + 1 < w; i += 1) {
        const sw = j * w + i, se = sw + 1, nw = sw + w, ne = nw + 1;
        indices.push(sw, se, ne, sw, ne, nw);
      }
    } else {
      // A box from its base up, its corners carried into the site's frame, lifted by the land
      // under each and carried back.
      const corner = (ix: number, iy: number, iz: number): readonly [number, number, number] => {
        toRoot.transformPoint(point.set((ix - 0.5) * width / 1000, iy * height / 1000, (iz - 0.5) * depth / 1000), point);
        const lift = land.groundMm(point.x * 1000, -point.z * 1000) - land.groundMm(cx, cy);
        toLocal.transformPoint(point.set(point.x, point.y + lift / 1000, point.z), point);
        return [point.x, point.y, point.z];
      };
      const faces: readonly (readonly (readonly [number, number, number])[])[] = [
        [[1, 0, 0], [1, 0, 1], [1, 1, 1], [1, 1, 0]], [[0, 0, 1], [0, 0, 0], [0, 1, 0], [0, 1, 1]],
        [[0, 1, 0], [1, 1, 0], [1, 1, 1], [0, 1, 1]], [[0, 0, 1], [1, 0, 1], [1, 0, 0], [0, 0, 0]],
        [[0, 0, 1], [0, 1, 1], [1, 1, 1], [1, 0, 1]], [[1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 0]],
      ];
      for (const listed of faces) {
        // Wound counterclockwise seen from outside, the renderer's front: (b - a) x (c - a) points out.
        const [a, b, c] = listed as readonly (readonly [number, number, number])[];
        const out = [0, 1, 2].map((k) => (a![k]! + b![k]! + c![k]! + listed[3]![k]!) / 4 - 0.5);
        const u = [0, 1, 2].map((k) => b![k]! - a![k]!), v = [0, 1, 2].map((k) => c![k]! - a![k]!);
        const facing = (u[1]! * v[2]! - u[2]! * v[1]!) * out[0]! + (u[2]! * v[0]! - u[0]! * v[2]!) * out[1]! + (u[0]! * v[1]! - u[1]! * v[0]!) * out[2]!;
        const face = facing > 0 ? listed : [...listed].reverse();
        const base = positions.length / 3;
        face.forEach(([ix, iy, iz], k) => {
          positions.push(...corner(ix, iy, iz));
          surfaceMm.push(k === 1 || k === 2 ? width : 0, k >= 2 ? height : 0);
        });
        indices.push(base, base + 1, base + 2, base, base + 2, base + 3);
      }
    }
    const normals = pc.calculateNormals(positions, indices);
    const mesh = buildSurfaceMesh(device, { positions, normals, surfaceMm, indices }, slot.primitive === 'plane'
      ? (s, t) => [s / width + 0.5, t / depth + 0.5]
      : (s, t) => [s / Math.max(width, 1), t / Math.max(height, 1)]);
    meshes.push(mesh);
    const original = instance.mesh;
    const at = shape.getLocalPosition().clone(), scale = shape.getLocalScale().clone();
    instance.mesh = mesh;
    shape.setLocalPosition(0, 0, 0);
    shape.setLocalScale(1, 1, 1);
    restore.push(() => {
      if (instance.mesh === mesh) instance.mesh = original;
      shape.setLocalPosition(at);
      shape.setLocalScale(scale);
    });
  }
  let undone = false;
  return {
    draped: meshes.length,
    undrape(): void {
      if (undone) return;
      undone = true;
      for (const one of restore.splice(0).reverse()) one();
    },
    destroy(): void {
      this.undrape();
      for (const mesh of meshes.splice(0)) mesh.destroy();
    },
  };
}

/**
 * Where a body of the land's water is drawn, as a plane: its middle (metres, the scene's frame),
 * its half extents along the plane's own two axes, and the turn that stands a fall upright. The
 * sea is as wide as the backdrop reaches; a lake is the square round its basin; a cascade's pool is
 * its rectangle; a fall is a sheet across its channel from its top down to its bottom, facing the
 * side it falls toward, so it is seen from below.
 */
export function waterPlane(body: LandWater, reachM: number): {
  readonly at: readonly [number, number, number]; readonly half: readonly [number, number];
  readonly turn: readonly [number, number, number];
} {
  if (body.kind === 'sea') return { at: [0, body.levelMm / 1000, 0], half: [reachM, reachM], turn: [0, 0, 0] };
  if (body.kind === 'lake') {
    const r = body.radiusMm / 1000;
    return { at: [body.centreMm[0] / 1000, body.levelMm / 1000, -body.centreMm[1] / 1000], half: [r, r], turn: [0, 0, 0] };
  }
  const [x0, y0, x1, y1] = body.rectMm;
  const middle: readonly [number, number] = [(x0 + x1) / 2000, -(y0 + y1) / 2000];
  if (body.kind !== 'fall') {
    return { at: [middle[0], body.levelMm / 1000, middle[1]], half: [(x1 - x0) / 2000, (y1 - y0) / 2000], turn: [0, 0, 0] };
  }
  const halfHeight = (body.levelMm - body.bottomMm) / 2000;
  const height = (body.levelMm + body.bottomMm) / 2000;
  // The plane faces up (+y); a fall's face turns toward its side: south is +z, north -z, east +x.
  const across = y0 === y1;
  const turn: readonly [number, number, number] = body.side === 'south' ? [90, 0, 0] : body.side === 'north' ? [-90, 0, 0]
    : body.side === 'east' ? [0, 0, -90] : [0, 0, 90];
  const half: readonly [number, number] = across ? [(x1 - x0) / 2000, halfHeight] : [halfHeight, (y1 - y0) / 2000];
  return { at: [middle[0], height, middle[1]], half, turn };
}

/** What drawing a site's land put in the scene, and how to dress it and take it away. */
export interface DrawnSiteLand {
  readonly root: pc.Entity;
  /**
   * One per chunk, or on a volume's top the one mesh of its cells drawn as land: the land a person
   * walks, worn in the site's base ground once that is dressed.
   */
  readonly ground: readonly pc.MeshInstance[];
  readonly triangles: number;
  readonly draws: number;
  /** How far from the site's origin the backdrop (or a volume's top) reaches, metres: where the far plane must stand. */
  readonly reachM: number;
  /**
   * Wear the site's base ground on the near land, as it is dressed, and the land's own surfaces
   * over it (`land-slope.ts`). After a pack's texture is set on the near land (which replaces what
   * it wears), `surfaces` lays the land's surfaces over that too.
   */
  wear(material: pc.Material): void;
  surfaces(): void;
  /** The sea, the lakes and a cascade's pools and falls as drawn, each with its body; a pond is a
   * site slot, not here. */
  readonly water: readonly { readonly instance: pc.MeshInstance; readonly body: LandWater }[];
  /**
   * Wear each sea, lake, pool and fall in the material the callback gives for its body (the look's
   * water, as a dresser makes it), or keep plain water where it gives none. The materials stay the
   * caller's.
   */
  wearWater(material: (body: LandWater) => pc.Material | null): void;
  /**
   * Colour the backdrop over `ground`, linear RGB: the colour the near land wears once a pack
   * dresses it, with the land's surfaces over it as before. Null colours it over the ground it was
   * drawn over.
   */
  colourBackdrop(ground: Rgb | null): void;
  /**
   * Wear the land's retaining walls in `material` (the site's boundary wall, where the mount holds
   * one), or in the plain rock they were drawn in again with null. The material stays the caller's.
   * Nothing where the land states no walls.
   */
  wearWalls(material: pc.Material | null): void;
  destroy(): void;
}

type Rgb = readonly [number, number, number];
const linear = (c: number): number => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const gamma = (c: number): number => (c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055);

/** One step of a main side over the site's lattice, in site millimetres east and north. */
const SIDE_STEP: Readonly<Record<SiteLandWall['high'], readonly [number, number]>> = {
  north: [0, LAND_CELL_MM], east: [LAND_CELL_MM, 0], south: [0, -LAND_CELL_MM], west: [-LAND_CELL_MM, 0],
};

/**
 * The faces of a land's retaining walls, in the scene's frame. For each metre of a run: a vertical
 * face on the low line from the land there up to the land one cell toward the high side and the
 * coping over it, the top over that cell strip at that height, and the coping's back down to the
 * upper land; at each end of a run, a face across the strip from the land up to the top. Every
 * height is the land's at a lattice point, and the land between two lattice points on a cell's edge
 * is straight, so each face's foot lies on the land. Each face is wound to face out of the wall.
 */
function wallFaces(walls: readonly SiteLandWall[], groundMm: (eastMm: number, northMm: number) => number): {
  readonly positions: number[]; readonly normals: number[]; readonly surfaceMm: number[]; readonly indices: number[];
} {
  const positions: number[] = [], normals: number[] = [], surfaceMm: number[] = [], indices: number[] = [];
  type Corner = readonly [eastMm: number, northMm: number, heightMm: number];
  // Four corners of a plane face, in site millimetres, with their surface coordinates, and the way
  // out of the wall in the scene's frame.
  const face = (corners: readonly Corner[], surface: readonly (readonly [number, number])[], out: readonly [number, number, number]): void => {
    const at = corners.map(([x, y, h]) => [x / 1000, h / 1000, -y / 1000] as const);
    const u = [0, 1, 2].map((k) => at[1]![k]! - at[0]![k]!), v = [0, 1, 2].map((k) => at[2]![k]! - at[0]![k]!);
    let n = [u[1]! * v[2]! - u[2]! * v[1]!, u[2]! * v[0]! - u[0]! * v[2]!, u[0]! * v[1]! - u[1]! * v[0]!];
    // Wound counterclockwise seen from outside, the renderer's front: (b - a) x (c - a) points out.
    const order = n[0]! * out[0] + n[1]! * out[1] + n[2]! * out[2] >= 0 ? [0, 1, 2, 3] : [3, 2, 1, 0];
    if (order[0] === 3) n = n.map((c) => -c);
    const length = Math.hypot(n[0]!, n[1]!, n[2]!) || 1;
    const base = positions.length / 3;
    for (const k of order) {
      positions.push(...at[k]!);
      normals.push(n[0]! / length, n[1]! / length, n[2]! / length);
      surfaceMm.push(...surface[k]!);
    }
    indices.push(base, base + 1, base + 2, base, base + 2, base + 3);
  };
  for (const wall of walls) {
    const [x0, y0] = wall.fromMm, [x1, y1] = wall.toMm;
    const metres = (Math.abs(x1 - x0) + Math.abs(y1 - y0)) / LAND_CELL_MM;
    const [sx, sy] = [Math.sign(x1 - x0) * LAND_CELL_MM, Math.sign(y1 - y0) * LAND_CELL_MM];
    const [hx, hy] = SIDE_STEP[wall.high];
    const away: readonly [number, number, number] = [-hx / LAND_CELL_MM, 0, hy / LAND_CELL_MM];
    const toward: readonly [number, number, number] = [hx / LAND_CELL_MM, 0, -hy / LAND_CELL_MM];
    const along: readonly [number, number, number] = [sx / LAND_CELL_MM, 0, -sy / LAND_CELL_MM];
    // A point of the run, `k` metres from its start, on the low line or one cell toward the high side.
    const low = (k: number): Corner => {
      const x = x0 + k * sx, y = y0 + k * sy;
      return [x, y, groundMm(x, y)];
    };
    const high = (k: number): Corner => {
      const x = x0 + k * sx + hx, y = y0 + k * sy + hy;
      return [x, y, groundMm(x, y)];
    };
    const top = (corner: Corner, k: number): Corner => [corner[0], corner[1], high(k)[2] + WALL_COPING_MM];
    for (let k = 0; k < metres; k += 1) {
      const a = low(k), b = low(k + 1), c = high(k), d = high(k + 1);
      const s0 = k * LAND_CELL_MM, s1 = s0 + LAND_CELL_MM;
      face([a, b, top(b, k + 1), top(a, k)], [[s0, a[2]], [s1, b[2]], [s1, d[2] + WALL_COPING_MM], [s0, c[2] + WALL_COPING_MM]], away);
      face([top(a, k), top(b, k + 1), top(d, k + 1), top(c, k)], [[s0, 0], [s1, 0], [s1, LAND_CELL_MM], [s0, LAND_CELL_MM]], [0, 1, 0]);
      face([c, d, top(d, k + 1), top(c, k)], [[s0, c[2]], [s1, d[2]], [s1, d[2] + WALL_COPING_MM], [s0, c[2] + WALL_COPING_MM]], toward);
    }
    const ends: readonly (readonly [number, readonly [number, number, number]])[] = [[0, [-along[0], 0, -along[2]]], [metres, along]];
    for (const [k, out] of ends) {
      const a = low(k), c = high(k);
      face([a, c, top(c, k), top(a, k)], [[0, a[2]], [LAND_CELL_MM, c[2]], [LAND_CELL_MM, c[2] + WALL_COPING_MM], [0, c[2] + WALL_COPING_MM]], out);
    }
  }
  return { positions, normals, surfaceMm, indices };
}

/**
 * A graded top's mesh in the scene's frame: every point of its lattice, lifted `TOP_LIFT_MM`, with
 * the normals of the whole lattice, and triangles for the cells in `runs`, each split as a near
 * chunk's cells are (and as the height rule splits them), from its south-west corner to its
 * north-east. Its rim follows the rock, not the grid: a cell outside the runs draws the part of it
 * round its corners on rock (corners of a cell in the runs) out to the middles of its edges that
 * lead off the rock, as marching squares do, so the top's edge runs through the cells' half points
 * and never takes a square bite; a cell with only two opposite corners on rock draws a corner at
 * each. A middle stands at the height the rule gives it, its two ends' mean floored. None where
 * the runs hold no cell.
 */
function topMesh(top: SiteTop, runs: readonly SiteTopRun[]): {
  readonly positions: number[]; readonly normals: number[]; readonly surfaceMm: number[]; readonly indices: number[]; readonly reachM: number;
} | null {
  const { columns, rows, heightMm } = top;
  const [x0, y0] = top.originMm;
  const positions: number[] = [], surfaceMm: number[] = [];
  let reach = 0;
  for (let j = 0; j < rows; j += 1) for (let i = 0; i < columns; i += 1) {
    const east = x0 + i * LAND_CELL_MM, north = y0 + j * LAND_CELL_MM;
    positions.push(east / 1000, (heightMm[j * columns + i]! + TOP_LIFT_MM) / 1000, -north / 1000);
    surfaceMm.push(east, -north);
    reach = Math.max(reach, Math.hypot(east, north) / 1000);
  }
  const all: number[] = [], indices: number[] = [];
  const rock = new Set<number>();
  for (const [row, first, last] of runs) {
    for (let i = first; i <= last; i += 1) for (const at of [row * columns + i, row * columns + i + 1, (row + 1) * columns + i, (row + 1) * columns + i + 1]) rock.add(at);
  }
  // Each edge's middle, made once and shared by the two cells that edge bounds.
  const lattice = positions.length / 3;
  const middles = new Map<number, readonly [number, number]>();
  const middle = (a: number, b: number): number => {
    const key = Math.min(a, b) * lattice + Math.max(a, b);
    const known = middles.get(key);
    if (known !== undefined) return known[0];
    const at = positions.length / 3;
    // The height rule's own value there: its two ends' mean, floored, as the server's place stands it.
    const height = Math.floor((heightMm[a]! + heightMm[b]!) / 2);
    positions.push((positions[3 * a]! + positions[3 * b]!) / 2, (height + TOP_LIFT_MM) / 1000, (positions[3 * a + 2]! + positions[3 * b + 2]!) / 2);
    surfaceMm.push((surfaceMm[2 * a]! + surfaceMm[2 * b]!) / 2, (surfaceMm[2 * a + 1]! + surfaceMm[2 * b + 1]!) / 2);
    middles.set(key, [at, a * lattice + b]);
    return at;
  };
  for (let j = 0; j + 1 < rows; j += 1) for (let i = 0; i + 1 < columns; i += 1) {
    const sw = j * columns + i, se = sw + 1, nw = sw + columns, ne = nw + 1;
    all.push(sw, se, ne, sw, ne, nw);
    if (siteTopCellHeld(runs, j, i)) {
      indices.push(sw, se, ne, sw, ne, nw);
      continue;
    }
    // Round the cell counterclockwise from its south-west corner, as its own halves turn.
    const corners = [sw, se, ne, nw];
    const on = corners.map((corner) => rock.has(corner));
    const count = on.filter(Boolean).length;
    if (count === 0) continue;
    if (count === 2 && on[0] === on[2]) {
      // Two opposite corners: a corner of the cell at each, never a bridge across it.
      for (let k = 0; k < 4; k += 1) {
        if (!on[k]) continue;
        const before = corners[(k + 3) % 4]!, after = corners[(k + 1) % 4]!;
        indices.push(corners[k]!, middle(corners[k]!, after), middle(before, corners[k]!));
      }
      continue;
    }
    const outline: number[] = [];
    for (let k = 0; k < 4; k += 1) {
      const next = (k + 1) % 4;
      if (on[k]) outline.push(corners[k]!);
      if (on[k] !== on[next]) outline.push(middle(corners[k]!, corners[next]!));
    }
    for (let k = 1; k + 1 < outline.length; k += 1) indices.push(outline[0]!, outline[k]!, outline[k + 1]!);
  }
  if (indices.length === 0) return null;
  const latticeNormals = pc.calculateNormals(positions.slice(0, lattice * 3), all);
  const normals = [...latticeNormals];
  for (const [, pair] of [...middles.entries()].sort((one, two) => one[1][0] - two[1][0])) {
    const a = Math.floor(pair[1] / lattice), b = pair[1] % lattice;
    const n = [0, 1, 2].map((k) => latticeNormals[3 * a + k]! + latticeNormals[3 * b + k]!);
    const length = Math.hypot(n[0]!, n[1]!, n[2]!) || 1;
    normals.push(n[0]! / length, n[1]! / length, n[2]! / length);
  }
  return { positions, normals, surfaceMm, indices, reachM: reach };
}

/**
 * A land material's shine taken off: no metal and fully rough, its textures' own roughness and
 * metalness left unread, so grass never glosses in the sun.
 */
function matteOver(material: pc.StandardMaterial): void {
  material.useMetalness = true;
  material.metalness = 0;
  material.metalnessMap = null;
  material.glossMap = null;
  material.glossInvert = false;
  material.gloss = 0;
  material.update();
}

function plainMaterial(name: string, rgb: Rgb, gloss: number): pc.StandardMaterial {
  const material = new pc.StandardMaterial();
  material.name = name;
  material.diffuse = new pc.Color(rgb[0], rgb[1], rgb[2]);
  material.gloss = gloss;
  material.useMetalness = true;
  material.metalness = 0;
  material.update();
  return material;
}

/**
 * Draw a site's land under a new root: each near chunk as one mesh in `groundMaterial` (the site's
 * base ground as drawn) with the land's own surfaces laid over it, the backdrop in blocks a
 * renderer can cull, coloured by the same surfaces over `groundRgb`, and the sea and lakes at their
 * levels. With no `surfaces` the land wears its ground alone. A near chunk `leaveOut` names is not
 * drawn: a town's tiles draw the land under them. Nothing here casts a shadow; the near land
 * receives them.
 *
 * A volume's graded top is drawn as one mesh of the cells its drawing draws as land, in the same
 * way, with no backdrop. `datumMm` is how far above the sea the frame the land is drawn in has its
 * level 0, so the surfaces' heights stay above the sea: a floating island's level, for its top and
 * for the landscape's land drawn under a root that stands the island at the page's level 0. With
 * `matte`, every material the land wears is a matte copy, without its shine. `rim` is more of the
 * top in the page's frame, the volume's own upward faces near it beyond the cells its drawing
 * draws (surface coordinates east and south, as the top's): drawn with the top, in its ground, so
 * the top reads as one ground to the rock's edge.
 */
export function drawSiteLand(
  device: pc.GraphicsDevice,
  land: SiteLand,
  groundMaterial: pc.Material,
  groundRgb: Rgb,
  surfaces: LandSurfaces | null = null,
  options: { readonly leaveOut?: (chunkX: number, chunkY: number) => boolean; readonly datumMm?: number; readonly matte?: boolean; readonly rim?: SurfaceBatch } = {},
): DrawnSiteLand {
  const root = new pc.Entity('site-land');
  const meshes: pc.Mesh[] = [];
  const made: pc.StandardMaterial[] = [];
  const ground: pc.MeshInstance[] = [];
  let triangles = 0;
  let draws = 0;
  const sea = land.section.water.some((body) => body.kind === 'sea');
  // Each material the near land wears, with the land's surfaces over it, made once.
  const surfaced = new Map<pc.Material, pc.Material>();
  const worn = new Set<pc.Material>();
  const matte = options.matte === true;
  const overlaid = (material: pc.Material): pc.Material => {
    if ((surfaces === null && !matte) || worn.has(material)) return material;
    let copy = surfaced.get(material);
    if (copy === undefined) {
      const fresh = surfaces === null
        ? (material instanceof pc.StandardMaterial ? material.clone() : null)
        : landSurfaceMaterial(device, material, surfaces, sea, options.datumMm ?? 0);
      if (fresh !== null && matte) matteOver(fresh);
      copy = fresh ?? material;
      if (fresh !== null) { made.push(fresh); worn.add(fresh); }
      surfaced.set(material, copy);
    }
    return copy;
  };
  const add = (name: string, instances: readonly pc.MeshInstance[], receive: boolean): void => {
    const entity = new pc.Entity(name);
    entity.addComponent('render', { meshInstances: [...instances], castShadows: false, receiveShadows: receive });
    root.addChild(entity);
    draws += instances.length;
  };
  for (const chunk of land.chunks) {
    if (options.leaveOut?.(chunk.chunkX, chunk.chunkY) === true) continue;
    const n = chunk.samplesPerSide, positions: number[] = [], surfaceMm: number[] = [];
    for (let j = 0; j < n; j += 1) for (let i = 0; i < n; i += 1) {
      const east = chunk.chunkX * LAND_CHUNK_MM + i * chunk.cellMm, north = chunk.chunkY * LAND_CHUNK_MM + j * chunk.cellMm;
      positions.push(east / 1000, chunk.heightMm[j * n + i]! / 1000, -north / 1000);
      surfaceMm.push(east, -north);
    }
    const all: number[] = [];
    for (let j = 0; j + 1 < n; j += 1) for (let i = 0; i + 1 < n; i += 1) {
      const sw = j * n + i, se = sw + 1, nw = sw + n, ne = nw + 1;
      all.push(sw, se, ne, sw, ne, nw);
    }
    const normals = pc.calculateNormals(positions, all);
    const mesh = buildSurfaceMesh(device, { positions, normals, surfaceMm, indices: all }, (s, t) => [s / 1000, t / 1000]);
    meshes.push(mesh);
    const near = new pc.MeshInstance(mesh, overlaid(groundMaterial));
    ground.push(near);
    triangles += all.length / 3;
    add(`site-land:chunk:${chunk.chunkX}:${chunk.chunkY}`, [near], true);
  }
  // A volume's top: the cells with rock under them as one mesh, over the volume's own top faces.
  const top = land.top === null ? null : topMesh(land.top, land.section.rockCells);
  if (top !== null) {
    const drawn: pc.MeshInstance[] = [];
    for (const batch of options.rim === undefined || options.rim.indices.length === 0 ? [top] : [top, options.rim]) {
      const mesh = buildSurfaceMesh(device, batch, (s, t) => [s / 1000, t / 1000]);
      meshes.push(mesh);
      const near = new pc.MeshInstance(mesh, overlaid(groundMaterial));
      ground.push(near);
      drawn.push(near);
      triangles += batch.indices.length / 3;
    }
    add('site-land:top', drawn, true);
  }
  // The backdrop: coloured by vertex, linear, by the land's surfaces over its ground, since it is
  // drawn only and never dressed; a dresser hands it the colour the near land wears instead.
  const groundLinear = [linear(groundRgb[0]), linear(groundRgb[1]), linear(groundRgb[2])] as const;
  const colouredOver = (ground: Rgb, positions: readonly number[], normals: readonly number[]): number[] => {
    const colours: number[] = [];
    for (let v = 0; v < positions.length; v += 3) {
      if (surfaces === null) { colours.push(...ground, 1); continue; }
      const x = positions[v]!, z = positions[v + 2]!;
      const up = Math.min(1, Math.max(0.02, Math.abs(normals[v + 1]!)));
      const slopePermille = Math.sqrt(Math.max(0, 1 - up * up)) / up * 1000;
      const { broadM, fineM, fineShare } = surfaces.noise;
      const shift = (2 * valueNoise(x / broadM, z / broadM) - 1) * (1 - fineShare) + (2 * valueNoise(x / fineM + 17, z / fineM + 3) - 1) * fineShare;
      colours.push(...landBackdropColour(surfaces, ground, slopePermille, positions[v + 1]! * 1000, shift, sea), 1);
    }
    return colours;
  };
  const far = new pc.StandardMaterial();
  far.name = 'site-land:backdrop';
  far.diffuse = new pc.Color(1, 1, 1);
  far.diffuseVertexColor = true;
  far.gloss = 0.1;
  far.useMetalness = true;
  far.metalness = 0;
  far.update();
  made.push(far);
  let reach = top?.reachM ?? 0;
  const blocks: pc.MeshInstance[] = [];
  const backdrop: { readonly mesh: pc.Mesh; readonly positions: number[]; readonly normals: number[] }[] = [];
  for (const block of land.backdrop === null ? [] : backdropMeshData(land.backdrop, { blocks: 4 })) {
    const positions = Array.from(block.positions), indices = Array.from(block.indices);
    const normals = pc.calculateNormals(positions, indices);
    for (let v = 0; v < positions.length; v += 3) reach = Math.max(reach, Math.hypot(positions[v]!, positions[v + 2]!));
    const mesh = new pc.Mesh(device);
    mesh.setPositions(positions);
    mesh.setNormals(normals);
    mesh.setColors(colouredOver(groundLinear, positions, normals));
    mesh.setIndices(indices);
    mesh.update(pc.PRIMITIVE_TRIANGLES);
    meshes.push(mesh);
    backdrop.push({ mesh, positions, normals });
    blocks.push(new pc.MeshInstance(mesh, far));
    triangles += indices.length / 3;
  }
  if (land.backdrop !== null) add('site-land:backdrop', blocks, true);
  // The sea and the lakes, level at their own heights, wide enough to meet the backdrop's edge.
  const water = plainMaterial('site-land:water', PLAIN_WATER, 0.85);
  made.push(water);
  const waters: { readonly instance: pc.MeshInstance; readonly body: LandWater }[] = [];
  for (const body of land.section.water) {
    if (body.kind === 'pond') continue;
    const placed = waterPlane(body, reach);
    const mesh = pc.Mesh.fromGeometry(device, new pc.PlaneGeometry({ halfExtents: new pc.Vec2(placed.half[0], placed.half[1]) }));
    meshes.push(mesh);
    const surface = new pc.MeshInstance(mesh, water);
    waters.push({ instance: surface, body });
    const entity = new pc.Entity(`site-land:water:${body.id}`);
    entity.setLocalPosition(placed.at[0], placed.at[1], placed.at[2]);
    entity.setLocalEulerAngles(placed.turn[0], placed.turn[1], placed.turn[2]);
    entity.addComponent('render', { meshInstances: [surface], castShadows: false, receiveShadows: true });
    root.addChild(entity);
    draws += 1;
    triangles += mesh.primitive[0]!.count / 3;
  }
  // The retaining walls where the land's levels meet: one mesh in one plain material, the surfaces'
  // rock where they are handed, the engine's rock where they are not. Seen, never walked.
  const walls = (land.top === null ? land.section.walls : undefined) ?? [];
  const rock = surfaces?.bands.find((band) => band.key === 'rock')?.linear;
  const stone = walls.length === 0 ? null
    : plainMaterial('site-land:walls', rock === undefined ? VOLUME_ROCK_RGB : [gamma(rock[0]), gamma(rock[1]), gamma(rock[2])], 0.1);
  let walled: pc.MeshInstance | null = null;
  if (stone !== null) {
    made.push(stone);
    const mesh = buildSurfaceMesh(device, wallFaces(walls, land.groundMm), (s, t) => [s / 1000, t / 1000]);
    meshes.push(mesh);
    walled = new pc.MeshInstance(mesh, stone);
    add('site-land:walls', [walled], true);
    triangles += mesh.primitive[0]!.count / 3;
  }
  let destroyed = false;
  return {
    root,
    ground,
    triangles,
    draws,
    reachM: reach * FAR_MARGIN,
    wear(material: pc.Material): void {
      for (const instance of ground) instance.material = overlaid(material);
    },
    surfaces(): void {
      for (const instance of ground) instance.material = overlaid(instance.material);
    },
    water: waters,
    wearWater(material: (body: LandWater) => pc.Material | null): void {
      for (const one of waters) one.instance.material = material(one.body) ?? water;
    },
    colourBackdrop(over: Rgb | null): void {
      if (destroyed) return;
      for (const block of backdrop) {
        block.mesh.setColors(colouredOver(over ?? groundLinear, block.positions, block.normals));
        block.mesh.update(pc.PRIMITIVE_TRIANGLES);
      }
    },
    wearWalls(material: pc.Material | null): void {
      if (walled !== null) walled.material = material ?? stone!;
    },
    destroy(): void {
      if (destroyed) return;
      destroyed = true;
      root.destroy();
      for (const mesh of meshes) mesh.destroy();
      for (const material of made) material.destroy();
    },
  };
}

/**
 * Draw the land round a town made on its land, under the host's environment root: every near chunk
 * its tiles do not cover (`covered` names those they do) in the land's plain ground with its
 * surfaces over it, the backdrop and the water, with the camera seeing as far as the backdrop
 * reaches. Disposing takes it all away and gives the camera back its far plane.
 */
export function attachLandRound(
  host: GeneratedTileHost,
  land: SiteLand,
  covered: (chunkX: number, chunkY: number) => boolean,
  surfaces: LandSurfaces | null,
): { readonly drawn: DrawnSiteLand; dispose(): void } {
  const plain = new pc.StandardMaterial();
  plain.name = 'town-land:ground';
  plain.diffuse = new pc.Color(...LAND_GROUND_RGB);
  plain.update();
  const drawn = drawSiteLand(host.app.graphicsDevice, land, plain, LAND_GROUND_RGB, surfaces, { leaveOut: covered });
  host.environmentRoot.addChild(drawn.root);
  const camera = host.camera.camera;
  const far = camera?.farClip;
  if (camera != null) camera.farClip = Math.max(camera.farClip, drawn.reachM);
  let disposed = false;
  return {
    drawn,
    dispose(): void {
      if (disposed) return;
      disposed = true;
      drawn.destroy();
      plain.destroy();
      if (camera != null && far !== undefined) camera.farClip = far;
    },
  };
}
