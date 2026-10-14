import * as pc from 'playcanvas';
import {
  LAND_CELL_MM, LAND_CHUNK_MM, backdropMeshData, chunkHeightMm, landBackdropColour, readLandBackdrop, readLandChunk,
  type HeightfieldDigest, type LandBackdrop, type LandChunk, type LandSurfaces, type LandWater,
} from '@exulanica/atlas-core';
import { buildSurfaceMesh } from '../generated-tile/surface-mesh.js';
import { landSurfaceMaterial } from './land-slope.js';
import type { SiteLandSection, SiteSlot, StructuredSiteDrawing } from './site-drawing.js';
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
 * A site on level ground has no land: none of this is read, made or asked, and every reader that
 * takes a ground function is handed none.
 */

/** Plain water where the drawing's own water material is not handed over. */
const PLAIN_WATER: readonly [number, number, number] = [0.24, 0.42, 0.55];
/** Scenery stands only on land at least this far above the sea's level. */
const DRY_ABOVE_SEA_MM = 300;
/** How far past the backdrop's reach the camera's far plane stands, as a share of it. */
const FAR_MARGIN = 1.15;

/** The land a site on land stands on, read and held to the digests its drawing names. */
export interface SiteLand {
  readonly section: SiteLandSection;
  readonly chunks: readonly LandChunk[];
  readonly backdrop: LandBackdrop;
  /** The land's height under a site point, millimetres east and north; the near land's edge beyond it. */
  readonly groundMm: (eastMm: number, northMm: number) => number;
  /** The land's height under a renderer point, metres east and south: the scene's and the society's frame. */
  readonly groundM: (eastM: number, southM: number) => number;
  /** Whether scenery may stand at a site point: on the near land, above the sea and out of every lake and pond. */
  readonly dryAt: (eastMm: number, northMm: number) => boolean;
  /** The bytes the chunks and the backdrop were served as. */
  readonly servedBytes: number;
}

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
    if (body.kind === 'pond' && eastMm >= body.rectMm[0] && eastMm <= body.rectMm[2] && northMm >= body.rectMm[1] && northMm <= body.rectMm[3]) return true;
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
): SiteLand {
  const section = drawing.land;
  if (section === undefined) throw new Error('The site drawing states no land.');
  const read = section.chunks.map(({ chunk: [x, y], sha256 }) => {
    const raw = chunks.get(`${x},${y}`);
    if (raw === undefined) throw new Error(`The land chunk (${x}, ${y}) its drawing names was not served.`);
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
  });
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

/** What drawing a site's land put in the scene, and how to dress it and take it away. */
export interface DrawnSiteLand {
  readonly root: pc.Entity;
  /** One per chunk: the land a person walks, worn in the site's base ground once that is dressed. */
  readonly ground: readonly pc.MeshInstance[];
  readonly triangles: number;
  readonly draws: number;
  /** How far from the site's origin the backdrop reaches, metres: where the far plane must stand. */
  readonly reachM: number;
  /**
   * Wear the site's base ground on the near land, as it is dressed, and the land's own surfaces
   * over it (`land-slope.ts`). After a pack's texture is set on the near land (which replaces what
   * it wears), `surfaces` lays the land's surfaces over that too.
   */
  wear(material: pc.Material): void;
  surfaces(): void;
  /** The sea and the lakes as drawn, each with its body; a pond is a site slot, not here. */
  readonly water: readonly { readonly instance: pc.MeshInstance; readonly body: LandWater }[];
  /**
   * Wear each sea and lake in the material the callback gives for its body (the look's water, as a
   * dresser makes it), or keep plain water where it gives none. The materials stay the caller's.
   */
  wearWater(material: (body: LandWater) => pc.Material | null): void;
  destroy(): void;
}

type Rgb = readonly [number, number, number];
const linear = (c: number): number => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);

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

/** Value noise in the world's metres, 0 to 1: the backdrop's own, as the near land's shader states it. */
function valueNoise(x: number, z: number): number {
  const hash = (a: number, b: number): number => { const v = Math.sin(a * 127.1 + b * 311.7) * 43758.5453; return v - Math.floor(v); };
  const i = Math.floor(x), j = Math.floor(z), tx = x - i, tz = z - j;
  const sx = tx * tx * (3 - 2 * tx), sz = tz * tz * (3 - 2 * tz);
  const a = hash(i, j) + (hash(i + 1, j) - hash(i, j)) * sx;
  const b = hash(i, j + 1) + (hash(i + 1, j + 1) - hash(i, j + 1)) * sx;
  return a + (b - a) * sz;
}

/**
 * Draw a site's land under a new root: each near chunk as one mesh in `groundMaterial` (the site's
 * base ground as drawn) with the land's own surfaces laid over it, the backdrop in blocks a
 * renderer can cull, coloured by the same surfaces over `groundRgb`, and the sea and lakes at their
 * levels. With no `surfaces` the land wears its ground alone. Nothing here casts a shadow; the near
 * land receives them.
 */
export function drawSiteLand(
  device: pc.GraphicsDevice,
  land: SiteLand,
  groundMaterial: pc.Material,
  groundRgb: Rgb,
  surfaces: LandSurfaces | null = null,
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
  const overlaid = (material: pc.Material): pc.Material => {
    if (surfaces === null || worn.has(material)) return material;
    let copy = surfaced.get(material);
    if (copy === undefined) {
      const fresh = landSurfaceMaterial(device, material, surfaces, sea);
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
  // The backdrop: coloured by vertex, linear, by the land's surfaces over its ground, since it is
  // drawn only and never dressed.
  const groundLinear = [linear(groundRgb[0]), linear(groundRgb[1]), linear(groundRgb[2])] as const;
  const far = new pc.StandardMaterial();
  far.name = 'site-land:backdrop';
  far.diffuse = new pc.Color(1, 1, 1);
  far.diffuseVertexColor = true;
  far.gloss = 0.1;
  far.useMetalness = true;
  far.metalness = 0;
  far.update();
  made.push(far);
  let reach = 0;
  const blocks: pc.MeshInstance[] = [];
  for (const block of backdropMeshData(land.backdrop, { blocks: 4 })) {
    const positions = Array.from(block.positions), indices = Array.from(block.indices);
    const normals = pc.calculateNormals(positions, indices);
    const colours: number[] = [];
    for (let v = 0; v < positions.length; v += 3) {
      const x = positions[v]!, z = positions[v + 2]!;
      reach = Math.max(reach, Math.hypot(x, z));
      if (surfaces === null) { colours.push(...groundLinear, 1); continue; }
      const up = Math.min(1, Math.max(0.02, Math.abs(normals[v + 1]!)));
      const slopePermille = Math.sqrt(Math.max(0, 1 - up * up)) / up * 1000;
      const { broadM, fineM, fineShare } = surfaces.noise;
      const shift = (2 * valueNoise(x / broadM, z / broadM) - 1) * (1 - fineShare) + (2 * valueNoise(x / fineM + 17, z / fineM + 3) - 1) * fineShare;
      colours.push(...landBackdropColour(surfaces, groundLinear, slopePermille, positions[v + 1]! * 1000, shift, sea), 1);
    }
    const mesh = new pc.Mesh(device);
    mesh.setPositions(positions);
    mesh.setNormals(normals);
    mesh.setColors(colours);
    mesh.setIndices(indices);
    mesh.update(pc.PRIMITIVE_TRIANGLES);
    meshes.push(mesh);
    blocks.push(new pc.MeshInstance(mesh, far));
    triangles += indices.length / 3;
  }
  add('site-land:backdrop', blocks, true);
  // The sea and the lakes, level at their own heights, wide enough to meet the backdrop's edge.
  const water = plainMaterial('site-land:water', PLAIN_WATER, 0.85);
  made.push(water);
  const waters: { readonly instance: pc.MeshInstance; readonly body: LandWater }[] = [];
  for (const body of land.section.water) {
    if (body.kind === 'pond') continue;
    const [x, z, half] = body.kind === 'sea' ? [0, 0, reach] : [body.centreMm[0] / 1000, -body.centreMm[1] / 1000, body.radiusMm / 1000];
    const mesh = pc.Mesh.fromGeometry(device, new pc.PlaneGeometry({ halfExtents: new pc.Vec2(half, half) }));
    meshes.push(mesh);
    const surface = new pc.MeshInstance(mesh, water);
    waters.push({ instance: surface, body });
    const entity = new pc.Entity(`site-land:water:${body.id}`);
    entity.setLocalPosition(x, body.levelMm / 1000, z);
    entity.addComponent('render', { meshInstances: [surface], castShadows: false, receiveShadows: true });
    root.addChild(entity);
    draws += 1;
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
    destroy(): void {
      if (destroyed) return;
      destroyed = true;
      root.destroy();
      for (const mesh of meshes) mesh.destroy();
      for (const material of made) material.destroy();
    },
  };
}
