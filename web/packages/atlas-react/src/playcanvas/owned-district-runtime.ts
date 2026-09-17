import type { NativeCharacterFrame } from './native-character-runtime.js';
import type {
  OwnedDistrict,
  DistrictInterpretation,
  DistrictSubject,
  OwnedDistrictBuilding,
} from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import { buildingRayDistance, pointInRing, surfaceTriangles } from './district-surfaces.js';
import { SocietyCrowd, type CrowdCounts } from './society/crowd.js';
import type { OwnedSocietyState } from './society/types.js';

export type { OwnedSocietyState } from './society/types.js';

export interface OwnedDistrictMetrics {
  readonly logicalBuildings: number;
  readonly logicalSidewalks: number;
  readonly drawCalls: number;
  readonly residentBytes: number;
  readonly visibleTiles: number;
}

/**
 * What the district draws where no record says what is there, in words a panel can show.
 *
 * No source record admitted for this district describes a surface material, and none describes
 * the ground. The renderer therefore draws what the records do carry, each footprint ring and its
 * roof height, as an outline with hatched faces, and draws the ground as the authored flat datum it
 * is. These sentences name that absence so the picture and the words cannot disagree.
 */
export interface OwnedDistrictUnavailableState {
  readonly buildingSurfaces: number;
  readonly sidewalkSurfaces: number;
  readonly surfaceReason: string;
  readonly groundReason: string;
}

export const OWNED_DISTRICT_SURFACE_UNAVAILABLE =
  'Surface material unavailable: no source record describes it. The outline and hatching show each recorded building footprint and roof height, and each recorded sidewalk footprint, only.';
export const OWNED_DISTRICT_GROUND_UNAVAILABLE =
  'Ground surface unavailable: the grid marks the authored flat walking datum, not a surveyed street.';

export interface OwnedAuthoredEnvironmentInstance {
  readonly instanceId: string;
  /** Supplied only after pinned source and destination-frame resolution by composition. */
  readonly providerFeatureId?: string;
  readonly coordinateFrame?: 'flatiron-local-mm';
  readonly transform: {
    readonly xMm: number;
    readonly yMm: number;
    readonly zMm: number;
    readonly yawMicroradians: number;
    readonly scaleMilli: number;
  };
  readonly origin: { readonly role: string };
  readonly removed: boolean;
  readonly availability: string;
}

interface Batch {
  readonly positions: number[];
  readonly normals: number[];
  readonly indices: number[];
}

interface HatchBatch extends Batch {
  readonly uvs: number[];
}

interface LineBatch {
  readonly positions: number[];
  readonly indices: number[];
}

const batch = (): Batch => ({ positions: [], normals: [], indices: [] });
const hatchBatch = (): HatchBatch => ({ positions: [], normals: [], indices: [], uvs: [] });
const lineBatch = (): LineBatch => ({ positions: [], indices: [] });

/** Metres per hatch repeat. Wide enough to read as a pattern, not as a facade rhythm. */
const HATCH_PERIOD_M = 2.4;
/** The one tone every unavailable mark shares, so no two buildings differ by an invented colour. */
const UNAVAILABLE_TONE = new pc.Color(0.34, 0.4, 0.43);
/** Metres between datum grid lines. */
const DATUM_SPACING_M = 10;
/** Sidewalks share the unavailable tone at a lower strength, so they read as ground under the buildings. */
const SIDEWALK_OPACITY = 0.55;

/**
 * The legend for authored instances: one tint per recorded role.
 *
 * The tint encodes the role the person chose for the instance, and nothing else. It is not a
 * material: the instance's surface is as unrecorded as every other surface here, so it draws with
 * the same outline and hatching. A role missing from this legend draws in the unavailable tone
 * rather than borrowing another role's tint.
 */
export const ROLE_TINT: Readonly<Record<string, pc.Color>> = Object.freeze({
  fictional: new pc.Color(0.1, 0.5, 0.6),
  personal: new pc.Color(0.66, 0.56, 0.4),
});

/**
 * The legend for the interpretation's generated civic markers (entrance and rest markers).
 *
 * The tint says "a generated recipe put this here", the same meaning the proof lens gives its
 * generated tier. It is not a material, and nothing about it was observed.
 */
export const GENERATED_MARKER_TINT = new pc.Color(0.85, 0.45, 0.1);

function hatchTexture(device: pc.GraphicsDevice): pc.Texture {
  const size = 32;
  const texture = new pc.Texture(device, {
    name: 'owned-district-unavailable-hatch',
    width: size,
    height: size,
    format: pc.PIXELFORMAT_RGBA8,
    mipmaps: true,
  });
  const pixels = texture.lock() as Uint8Array;
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      // A diagonal stroke over a faint wash: the wash keeps the recorded extent visible from
      // inside it, the stroke says that nothing about the surface is known.
      const alpha = (x + y) % 16 < 3 ? 165 : 22;
      pixels.set([255, 255, 255, alpha], (y * size + x) * 4);
    }
  }
  texture.unlock();
  texture.addressU = pc.ADDRESS_REPEAT;
  texture.addressV = pc.ADDRESS_REPEAT;
  return texture;
}

/** Hatched, unlit, and one tint: the whole of what an unrecorded surface may look like. */
function hatchedMaterial(hatch: pc.Texture, tint: pc.Color = UNAVAILABLE_TONE, opacity = 1): pc.StandardMaterial {
  const result = new pc.StandardMaterial();
  result.useLighting = false;
  result.useSkybox = false;
  result.diffuse = new pc.Color(0, 0, 0);
  result.emissive = tint.clone();
  result.opacity = opacity;
  result.emissiveMap = hatch;
  result.opacityMap = hatch;
  result.opacityMapChannel = 'a';
  result.blendType = pc.BLEND_NORMAL;
  result.depthWrite = false;
  result.cull = pc.CULLFACE_NONE;
  result.update();
  return result;
}

/** Unlit and one tint, for outlines, the datum grid and generated markers. */
function flatMaterial(opacity: number, tint: pc.Color = UNAVAILABLE_TONE): pc.StandardMaterial {
  const result = new pc.StandardMaterial();
  result.useLighting = false;
  result.useSkybox = false;
  result.diffuse = new pc.Color(0, 0, 0);
  result.emissive = tint.clone();
  result.cull = pc.CULLFACE_NONE;
  result.opacity = opacity;
  result.blendType = opacity < 1 ? pc.BLEND_NORMAL : pc.BLEND_NONE;
  result.update();
  return result;
}

function hatchQuad(
  target: HatchBatch,
  corners: readonly (readonly [number, number, number])[],
  uvs: readonly (readonly [number, number])[],
): void {
  const first = target.positions.length / 3;
  for (const corner of corners) target.positions.push(...corner);
  for (const uv of uvs) target.uvs.push(...uv);
  for (let index = 0; index < corners.length; index += 1) target.normals.push(0, 1, 0);
  target.indices.push(first, first + 1, first + 2, first, first + 2, first + 3);
}

function line(target: LineBatch, a: readonly [number, number, number], b: readonly [number, number, number]): void {
  const first = target.positions.length / 3;
  target.positions.push(...a, ...b);
  target.indices.push(first, first + 1);
}

/**
 * The recorded extent of one building: every ring at the ground and at its source roof height,
 * a vertical edge at every ring vertex, and hatched faces between them. Nothing here depends on a
 * material, a name or a batch id, so no building can look different from another for a reason the
 * source does not give.
 */
function addUnavailableBuilding(
  surfaces: HatchBatch,
  outlines: LineBatch,
  building: OwnedDistrictBuilding,
): void {
  const height = building.height_cm / 100;
  for (const polygon of building.polygons) {
    for (const ring of polygon) {
      let along = 0;
      for (let index = 1; index < ring.length; index += 1) {
        const [ax, az] = ring[index - 1]!.map((value) => value / 100) as [number, number];
        const [bx, bz] = ring[index]!.map((value) => value / 100) as [number, number];
        const length = Math.hypot(bx - ax, bz - az);
        if (length < 1e-8) continue;
        const u0 = along / HATCH_PERIOD_M;
        const u1 = (along + length) / HATCH_PERIOD_M;
        const v1 = height / HATCH_PERIOD_M;
        hatchQuad(surfaces,
          [[ax, 0, az], [bx, 0, bz], [bx, height, bz], [ax, height, az]],
          [[u0, 0], [u1, 0], [u1, v1], [u0, v1]]);
        line(outlines, [ax, 0.03, az], [bx, 0.03, bz]);
        line(outlines, [ax, 0.03, az], [ax, height, az]);
        along += length;
      }
    }
  }
  addUnavailableFlat(surfaces, outlines, building.polygons, height);
}

/** A recorded footprint at one height: hatched between its rings, and every ring outlined. */
function addUnavailableFlat(
  surfaces: HatchBatch,
  outlines: LineBatch,
  polygons: OwnedDistrictBuilding['polygons'],
  height: number,
): void {
  for (const polygon of polygons) {
    for (const ring of polygon) {
      for (let index = 1; index < ring.length; index += 1) {
        const [ax, az] = ring[index - 1]!;
        const [bx, bz] = ring[index]!;
        line(outlines, [ax / 100, height, az / 100], [bx / 100, height, bz / 100]);
      }
    }
    for (const triangle of surfaceTriangles(polygon)) {
      const first = surfaces.positions.length / 3;
      for (const [x, z] of triangle) {
        surfaces.positions.push(x / 100, height, z / 100);
        surfaces.uvs.push(x / 100 / HATCH_PERIOD_M, z / 100 / HATCH_PERIOD_M);
        surfaces.normals.push(0, 1, 0);
      }
      surfaces.indices.push(first, first + 1, first + 2);
    }
  }
}

function hatchedMesh(device: pc.GraphicsDevice, source: HatchBatch): pc.Mesh | null {
  if (source.indices.length === 0) return null;
  const result = new pc.Mesh(device);
  result.setPositions(source.positions);
  result.setNormals(source.normals);
  result.setUvs(0, source.uvs);
  result.setIndices(source.indices);
  result.update(pc.PRIMITIVE_TRIANGLES);
  return result;
}

function lineMesh(device: pc.GraphicsDevice, source: LineBatch): pc.Mesh | null {
  if (source.indices.length === 0) return null;
  const result = new pc.Mesh(device);
  result.setPositions(source.positions);
  result.setIndices(source.indices);
  result.update(pc.PRIMITIVE_LINES);
  return result;
}

/** The authored flat datum the district's navigation stands on, drawn as a grid, not a surface. */
function addGroundDatum(target: LineBatch, boundsCm: readonly [number, number, number, number]): void {
  const [west, north, east, south] = boundsCm.map((value) => value / 100) as [
    number, number, number, number,
  ];
  for (let x = Math.ceil(west / DATUM_SPACING_M) * DATUM_SPACING_M; x <= east; x += DATUM_SPACING_M) {
    line(target, [x, 0, north], [x, 0, south]);
  }
  for (let z = Math.ceil(north / DATUM_SPACING_M) * DATUM_SPACING_M; z <= south; z += DATUM_SPACING_M) {
    line(target, [west, 0, z], [east, 0, z]);
  }
  line(target, [west, 0, north], [east, 0, north]);
  line(target, [east, 0, north], [east, 0, south]);
  line(target, [east, 0, south], [west, 0, south]);
  line(target, [west, 0, south], [west, 0, north]);
}

function quad(
  target: Batch,
  a: readonly [number, number, number],
  b: readonly [number, number, number],
  c: readonly [number, number, number],
  d: readonly [number, number, number],
  normal: readonly [number, number, number],
): void {
  const first = target.positions.length / 3;
  target.positions.push(...a, ...b, ...c, ...d);
  for (let index = 0; index < 4; index += 1) target.normals.push(...normal);
  target.indices.push(first, first + 1, first + 2, first, first + 2, first + 3);
}

function addBox(
  target: Batch,
  centre: readonly [number, number, number],
  half: readonly [number, number, number],
): void {
  const [x, y, z] = centre;
  const [hx, hy, hz] = half;
  const l = x - hx;
  const r = x + hx;
  const b = y - hy;
  const t = y + hy;
  const n = z - hz;
  const f = z + hz;
  quad(target, [l, b, f], [r, b, f], [r, t, f], [l, t, f], [0, 0, 1]);
  quad(target, [r, b, n], [l, b, n], [l, t, n], [r, t, n], [0, 0, -1]);
  quad(target, [r, b, f], [r, b, n], [r, t, n], [r, t, f], [1, 0, 0]);
  quad(target, [l, b, n], [l, b, f], [l, t, f], [l, t, n], [-1, 0, 0]);
  quad(target, [l, t, f], [r, t, f], [r, t, n], [l, t, n], [0, 1, 0]);
  quad(target, [l, b, n], [r, b, n], [r, b, f], [l, b, f], [0, -1, 0]);
}

function mesh(device: pc.GraphicsDevice, source: Batch): pc.Mesh | null {
  if (source.indices.length === 0) return null;
  const result = new pc.Mesh(device);
  result.setPositions(source.positions);
  result.setNormals(source.normals);
  result.setIndices(source.indices);
  result.update(pc.PRIMITIVE_TRIANGLES);
  return result;
}

function rayBox(
  origin: readonly [number, number, number],
  direction: readonly [number, number, number],
  minimum: readonly [number, number, number],
  maximum: readonly [number, number, number],
): number | null {
  let near = 0;
  let far = Number.POSITIVE_INFINITY;
  for (let axis = 0; axis < 3; axis += 1) {
    if (Math.abs(direction[axis]!) < 1e-9) {
      if (origin[axis]! < minimum[axis]! || origin[axis]! > maximum[axis]!) return null;
      continue;
    }
    const first = (minimum[axis]! - origin[axis]!) / direction[axis]!;
    const second = (maximum[axis]! - origin[axis]!) / direction[axis]!;
    near = Math.max(near, Math.min(first, second));
    far = Math.min(far, Math.max(first, second));
    if (near > far) return null;
  }
  return far >= 0 ? near : null;
}

/** PlayCanvas representation only. The document remains the world authority. */
export class OwnedDistrictRuntime {
  readonly root = new pc.Entity('owned-district');
  readonly authoredRoot = new pc.Entity('owned-district-authored-instances');
  readonly societyRoot = new pc.Entity('owned-district-society');
  readonly metrics: OwnedDistrictMetrics;
  readonly unavailable: OwnedDistrictUnavailableState;
  private readonly meshes: pc.Mesh[] = [];
  private readonly materials: pc.Material[] = [];
  private readonly textures: pc.Texture[] = [];
  private readonly hatch: pc.Texture;
  private authoredMeshes: pc.Mesh[] = [];
  private authoredMaterials: pc.Material[] = [];
  /** The whole synthetic population, drawn by distance; see `society/crowd.ts`. */
  private readonly crowd: SocietyCrowd;
  private destroyed = false;

  constructor(
    private readonly device: pc.GraphicsDevice,
    parent: pc.Entity,
    readonly district: OwnedDistrict,
    sourceBytes: number,
    readonly interpretation?: DistrictInterpretation,
  ) {
    if (interpretation && interpretation.district_id !== district.district_id) throw new Error('District interpretation binding mismatch');
    parent.addChild(this.root);
    parent.addChild(this.authoredRoot);
    parent.addChild(this.societyRoot);
    this.hatch = hatchTexture(device);
    this.textures.push(this.hatch);
    this.crowd = new SocietyCrowd(device, this.societyRoot);

    // Sidewalk footprints are recorded; what they are paved with is not. They draw like the
    // buildings, hatched and outlined, at a lower strength so they still read as ground.
    const sidewalkSurfaces = hatchBatch();
    const sidewalkOutlines = lineBatch();
    for (const sidewalk of district.sidewalks) {
      addUnavailableFlat(sidewalkSurfaces, sidewalkOutlines, sidewalk.polygons, 0.025);
    }
    let drawCalls = this.addHatched(sidewalkSurfaces, 'owned-sidewalk-surface-unavailable', SIDEWALK_OPACITY);
    drawCalls += this.addLines(sidewalkOutlines, 'owned-sidewalk-recorded-extent', SIDEWALK_OPACITY);

    // No record gives the ground a surface. The grid is the authored walking datum and says so.
    const datum = lineBatch();
    addGroundDatum(datum, district.bounds_cm);
    drawCalls += this.addLines(datum, 'owned-district-ground-datum-unavailable', 0.35);

    // No record gives any building a material. Every building draws the same way: its recorded
    // footprint and roof height as an outline, hatched between the edges. The interpretation's
    // facade grids and parapets are generated recipes with nothing observed behind them, so they
    // are not drawn either.
    const surfaces = hatchBatch();
    const outlines = lineBatch();
    for (const building of district.buildings) addUnavailableBuilding(surfaces, outlines, building);
    drawCalls += this.addHatched(surfaces, 'owned-building-surface-unavailable', 1);
    drawCalls += this.addLines(outlines, 'owned-building-recorded-extent', 1);
    this.unavailable = Object.freeze({
      buildingSurfaces: district.buildings.length,
      sidewalkSurfaces: district.sidewalks.length,
      surfaceReason: OWNED_DISTRICT_SURFACE_UNAVAILABLE,
      groundReason: OWNED_DISTRICT_GROUND_UNAVAILABLE,
    });
    if (interpretation) {
      const civic = batch();
      for (const subject of interpretation.subjects) {
        if (!subject.permitted_uses.includes('render')) continue;
        const recipe = subject.recipe;
        if (recipe.kind === 'rest-pad') {
          const [x, z] = recipe.position_mm.map(v => v / 1000);
          const radius = recipe.radius_mm / 1000;
          for (let i = 0; i < 24; i++) {
            const a = i * Math.PI / 12, b = (i + 1) * Math.PI / 12;
            quad(civic, [x! + Math.cos(a) * radius, .008, z! + Math.sin(a) * radius],
              [x! + Math.cos(b) * radius, .008, z! + Math.sin(b) * radius],
              [x! + Math.cos(b) * radius * .75, .008, z! + Math.sin(b) * radius * .75],
              [x! + Math.cos(a) * radius * .75, .008, z! + Math.sin(a) * radius * .75], [0, 1, 0]);
          }
        } else if (recipe.kind === 'entrance-marker') {
          const [x, z] = recipe.position_mm.map(v => v / 1000);
          // A thin upright arrival marker, not a door or supported interior.
          addBox(civic, [x!, recipe.height_mm / 2000, z!], [recipe.width_mm / 2000, recipe.height_mm / 2000, .025]);
        }
      }
      const civicMesh = mesh(device, civic);
      if (civicMesh) {
        // Generated recipes, drawn in the generated-marker tint rather than a surface of their own.
        const mat = flatMaterial(1, GENERATED_MARKER_TINT);
        const entity = new pc.Entity('interpreted-civic-markers');
        entity.addComponent('render', {meshInstances:[new pc.MeshInstance(civicMesh, mat, entity)],castShadows:false,receiveShadows:true});
        this.root.addChild(entity); this.meshes.push(civicMesh); this.materials.push(mat); drawCalls++;
      }
    }
    this.metrics = Object.freeze({
      logicalBuildings: district.buildings.length,
      logicalSidewalks: district.sidewalks.length,
      drawCalls,
      residentBytes: sourceBytes,
      visibleTiles: 1,
    });
  }

  private addHatched(source: HatchBatch, name: string, opacity: number): number {
    const geometry = hatchedMesh(this.device, source);
    if (geometry === null) return 0;
    const surface = hatchedMaterial(this.hatch, UNAVAILABLE_TONE, opacity);
    const entity = new pc.Entity(name);
    entity.addComponent('render', {
      meshInstances: [new pc.MeshInstance(geometry, surface, entity)],
      castShadows: false,
      receiveShadows: false,
    });
    this.meshes.push(geometry);
    this.materials.push(surface);
    this.root.addChild(entity);
    return 1;
  }

  private addLines(source: LineBatch, name: string, opacity: number): number {
    const geometry = lineMesh(this.device, source);
    if (geometry === null) return 0;
    const surface = flatMaterial(opacity);
    const entity = new pc.Entity(name);
    entity.addComponent('render', {
      meshInstances: [new pc.MeshInstance(geometry, surface, entity)],
      castShadows: false,
      receiveShadows: false,
    });
    this.meshes.push(geometry);
    this.materials.push(surface);
    this.root.addChild(entity);
    return 1;
  }

  setAuthoredInstances(instances: readonly OwnedAuthoredEnvironmentInstance[]): void {
    for (const child of [...this.authoredRoot.children]) child.destroy();
    for (const held of this.authoredMeshes) held.destroy();
    for (const held of this.authoredMaterials) held.destroy();
    this.authoredMeshes = [];
    this.authoredMaterials = [];
    for (const instance of instances) {
      if (instance.removed || instance.availability !== 'available') continue;
      if (instance.coordinateFrame !== 'flatiron-local-mm' || instance.providerFeatureId === undefined) continue;
      const building = this.district.buildings.find(
        (candidate) => candidate.id === instance.providerFeatureId,
      );
      if (building === undefined) continue;
      const [west, north, east, south] = building.bbox_cm;
      const cx = (west + east) / 2;
      const cz = (north + south) / 2;
      const local: OwnedDistrictBuilding = {
        ...building,
        polygons: building.polygons.map((polygon) => polygon.map((ring) => ring.map(
          ([x, z]) => [x - cx, z - cz] as const,
        ))),
      };
      const surfaces = hatchBatch();
      const outlines = lineBatch();
      addUnavailableBuilding(surfaces, outlines, local);
      const geometry = hatchedMesh(this.device, surfaces);
      const edges = lineMesh(this.device, outlines);
      if (geometry === null || edges === null) continue;
      // The recorded role is the only thing that tells two instances apart.
      const tint = Object.hasOwn(ROLE_TINT, instance.origin.role)
        ? ROLE_TINT[instance.origin.role]!
        : UNAVAILABLE_TONE;
      const surface = hatchedMaterial(this.hatch, tint);
      const edge = flatMaterial(1, tint);
      const entity = new pc.Entity(`authored-${instance.instanceId}`);
      entity.addComponent('render', {
        meshInstances: [
          new pc.MeshInstance(geometry, surface, entity),
          new pc.MeshInstance(edges, edge, entity),
        ],
        castShadows: false,
        receiveShadows: false,
      });
      entity.setLocalPosition(
        instance.transform.xMm / 1000,
        instance.transform.yMm / 1000,
        instance.transform.zMm / 1000,
      );
      entity.setEulerAngles(0, instance.transform.yawMicroradians * 180 / Math.PI / 1_000_000, 0);
      entity.setLocalScale(
        instance.transform.scaleMilli / 1000,
        instance.transform.scaleMilli / 1000,
        instance.transform.scaleMilli / 1000,
      );
      this.authoredMeshes.push(geometry, edges);
      this.authoredMaterials.push(surface, edge);
      this.authoredRoot.addChild(entity);
    }
  }

  /** Release the unavailable population without inventing an authoritative snapshot. */
  clearSociety(): void {
    this.crowd.clear();
  }

  /**
   * Present one canonical snapshot. The whole population is kept and drawn by distance, and the
   * return value is how many inhabitants are drawn. `intervalMs` is the time until the next
   * snapshot is expected, over which recorded motion is shown.
   */
  setSociety(
    state: OwnedSocietyState,
    observer?: readonly [number, number],
    options?: { readonly intervalMs?: number },
  ): number {
    return this.crowd.set(state, observer, options).drawn;
  }

  /** Interpolate display only; authoritative endpoints remain the society snapshots. */
  tickSociety(nowMs: number): void {
    this.crowd.update(nowMs);
  }

  refreshNearby(observer: readonly [number, number]): void {
    this.crowd.refresh(observer);
  }

  /** Population, indoor, near-character and far-figure counts for inspection surfaces. */
  get societyCounts(): CrowdCounts {
    return this.crowd.counts;
  }

  /** GPU buffer residency, separate from the serialized source document byte count. */
  get characterTextureBytes(): number {
    return this.crowd.textureResidentBytes;
  }
  get geometryResidentBytes(): number {
    return this.crowd.residentBytes+[...this.meshes, ...this.authoredMeshes].reduce((sum, mesh) => sum + (mesh.vertexBuffer?.numBytes ?? 0) + mesh.indexBuffer.reduce((bytes, buffer) => bytes + (buffer?.numBytes ?? 0), 0), 0);
  }

  /** Resolves shared subjects, independent of renderer batch IDs. */
  pickSubject(origin: readonly [number, number, number], direction: readonly [number, number, number]): DistrictSubject | null {
    if (!this.interpretation) return null;
    const building = this.pickBuilding(origin, direction);
    let nearest = building ? buildingRayDistance(building, origin, direction) ?? Infinity : Infinity;
    let selected = building ? this.interpretation.subjects.find(s => s.subject_id === building.id) ?? null : null;
    for (const subject of this.interpretation.subjects) {
      if (!subject.permitted_uses.includes('select')) continue;
      const recipe = subject.recipe;
      let distance: number | null = null;
      if (recipe.kind === 'entrance-marker') {
        const [x,z] = recipe.position_mm.map(v => v / 1000), half = recipe.width_mm / 2000;
        distance = rayBox(origin, direction, [x! - half, 0, z! - .025], [x! + half, recipe.height_mm / 1000, z! + .025]);
      } else if (recipe.kind === 'rest-pad' && Math.abs(direction[1]) > 1e-8) {
        const t = (.008 - origin[1]) / direction[1];
        const dx = origin[0] + direction[0] * t - recipe.position_mm[0] / 1000;
        const dz = origin[2] + direction[2] * t - recipe.position_mm[1] / 1000;
        if (t >= 0 && Math.hypot(dx,dz) <= recipe.radius_mm / 1000) distance = t;
      } else if (recipe.kind === 'source-footprint' && subject.kind === 'sidewalk' && Math.abs(direction[1]) > 1e-8) {
        const t = (.025 - origin[1]) / direction[1];
        const point = [(origin[0] + direction[0] * t) * 100, (origin[2] + direction[2] * t) * 100] as const;
        const sidewalk = this.district.sidewalks.find(s => s.id === recipe.feature_id);
        if (t >= 0 && sidewalk?.polygons.some(p => p[0] && pointInRing(point,p[0]) && !p.slice(1).some(r => pointInRing(point,r)))) distance = t;
      }
      if (distance !== null && distance < nearest) { nearest = distance; selected = subject; }
    }
    return selected;
  }

  get societyAnimating(): boolean {
    return this.crowd.animating;
  }

  /** Selecting an inhabitant keeps it a full character; it never moves anyone. */
  revealInhabitant(id: string): void {
    this.crowd.select(id);
  }

  get drawnInhabitantCount(): number {
    return this.crowd.counts.drawn;
  }

  /** Every inhabitant presented at this inhabitant's point, itself included. */
  coincidentInhabitants(id: string): readonly string[] {
    return this.crowd.sharing(id);
  }

  inhabitantRepresentation(id: string) {
    return this.crowd.representation(id);
  }

  /** How an inhabitant is currently shown: a full character, a far figure, indoors or not drawn. */
  inhabitantDetail(id: string): 'near' | 'far' | 'indoors' | 'not-drawn' {
    return this.crowd.detailOf(id);
  }

  nativeCharacterFrames(deltaSeconds: number, reducedMotion: boolean): readonly NativeCharacterFrame[] {
    return this.crowd.nativeFrames(deltaSeconds, reducedMotion);
  }

  /** Every drawn inhabitant, full characters first, then far figures by distance. */
  get visibleInhabitantIds(): readonly string[] {
    return this.crowd.drawnIds;
  }

  /** Stable subject selection against the drawn figure, with building occlusion. */
  pickInhabitant(origin: readonly [number, number, number], direction: readonly [number, number, number]): string | null {
    let nearest = Infinity;
    for (const building of this.district.buildings) nearest = Math.min(nearest, buildingRayDistance(building, origin, direction) ?? Infinity);
    return this.crowd.pick(nearest, (minimum, maximum) => rayBox(origin, direction, minimum, maximum));
  }

  /** Exact semantic hit against admitted extruded footprints, independent of mesh names. */
  pickBuilding(
    origin: readonly [number, number, number],
    direction: readonly [number, number, number],
  ): OwnedDistrictBuilding | null {
    let selected: { building: OwnedDistrictBuilding; distance: number } | null = null;
    for (const building of this.district.buildings) {
      const distance = buildingRayDistance(building, origin, direction);
      if (distance !== null && (selected === null || distance < selected.distance)) selected = { building, distance };
    }
    return selected?.building ?? null;
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.crowd.destroy();
    this.root.destroy();
    this.authoredRoot.destroy();
    this.societyRoot.destroy();
    for (const value of this.authoredMeshes) value.destroy();
    for (const value of this.authoredMaterials) value.destroy();
    for (const value of this.meshes) value.destroy();
    for (const value of this.materials) value.destroy();
    for (const value of this.textures) value.destroy();
  }
}
