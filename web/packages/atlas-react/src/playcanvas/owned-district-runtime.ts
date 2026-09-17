import type { NativeCharacterFrame } from './native-character-runtime.js';
import type {
  OwnedDistrict,
  DistrictInterpretation,
  DistrictSubject,
  OwnedDistrictBuilding,
} from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import { buildingRayDistance, pointInRing, ringArea, surfaceTriangles } from './district-surfaces.js';
import { sampleMotionPath } from './society-presentation.js';
import { PlayerAvatar } from './player-avatar.js';
import { abstractCharacter, syntheticCharacterStyle } from './character-shape.js';

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
  readonly surfaceReason: string;
  readonly groundReason: string;
}

export const OWNED_DISTRICT_SURFACE_UNAVAILABLE =
  'Surface material unavailable: no source record describes it. The outline and hatching show the recorded footprint and roof height only.';
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

export interface OwnedSocietyState {
  readonly profile?: 'exulanica-society/v1' | 'exulanica-society/v2';
  readonly society_id?: string;
  readonly branch_id?: string;
  readonly input_seq?: number;
  readonly input_sha256?: string;
  readonly tick: number;
  readonly inhabitants: readonly {
    readonly id: string;
    readonly synthetic: true;
    readonly display_name?: string;
    readonly role?: string;
    readonly position_mm: readonly [number, number];
    readonly goal?: null | { readonly kind: 'visit' | 'rest'; readonly target_id: string; readonly reason: string };
    readonly action?: { readonly kind: 'idle' | 'move' | 'visit' | 'rest'; readonly status: 'active' | 'completed' | 'blocked'; readonly target_id: string | null; readonly remaining_ticks: number; readonly reason: string };
    readonly route?: null | { readonly node_ids: readonly string[]; readonly edge_index: number; readonly edge_progress_mm: number; readonly destination_node_id: string; readonly input_sha256: string };
    readonly motion_path_mm?: readonly (readonly [number, number])[];
    readonly explanation?: { readonly summary: string; readonly event_ids: readonly string[] };
  }[];
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

interface SocietyAnimation {
  readonly startedAtMs: number;
  readonly durationMs: number;
  readonly inhabitants: readonly {
    readonly id: string;
    readonly role: string;
    readonly ordinal: number;
    readonly from: readonly [number, number];
    readonly to: readonly [number, number];
    readonly path: readonly (readonly [number, number])[];
  }[];
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

function unavailableSurfaceMaterial(hatch: pc.Texture): pc.StandardMaterial {
  const result = new pc.StandardMaterial();
  result.useLighting = false;
  result.useSkybox = false;
  result.diffuse = new pc.Color(0, 0, 0);
  result.emissive = UNAVAILABLE_TONE.clone();
  result.emissiveMap = hatch;
  result.opacityMap = hatch;
  result.opacityMapChannel = 'a';
  result.blendType = pc.BLEND_NORMAL;
  result.depthWrite = false;
  result.cull = pc.CULLFACE_NONE;
  result.update();
  return result;
}

function unavailableLineMaterial(opacity: number): pc.StandardMaterial {
  const result = new pc.StandardMaterial();
  result.useLighting = false;
  result.useSkybox = false;
  result.diffuse = new pc.Color(0, 0, 0);
  result.emissive = UNAVAILABLE_TONE.clone();
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
        line(outlines, [ax, height, az], [bx, height, bz]);
        line(outlines, [ax, 0.03, az], [ax, height, az]);
        along += length;
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

function addBuilding(target: Batch, building: OwnedDistrictBuilding): void {
  const height = building.height_cm / 100;
  for (const polygon of building.polygons) {
    polygon.forEach((sourceRing, ringIndex) => {
      // Consistent outward faces regardless of provider winding, including holes.
      const wantPositive = ringIndex === 0;
      const ring = (ringArea(sourceRing) > 0) === wantPositive ? sourceRing : [...sourceRing].reverse();
      for (let index = 1; index < ring.length; index++) {
        const [ax, az] = ring[index - 1]!, [bx, bz] = ring[index]!;
        const dx = (bx - ax) / 100, dz = (bz - az) / 100;
        const length = Math.hypot(dx, dz);
        if (length < 1e-8) continue;
        quad(target, [bx / 100, 0, bz / 100], [ax / 100, 0, az / 100],
          [ax / 100, height, az / 100], [bx / 100, height, bz / 100],
          [dz / length, 0, -dx / length]);
      }
    });
  }
  addFlatPolygon(target, building.polygons, height);
}

function addFlatPolygon(
  target: Batch,
  polygons: OwnedDistrictBuilding['polygons'],
  height: number,
): void {
  for (const polygon of polygons) {
    for (const triangle of surfaceTriangles(polygon)) {
      const first = target.positions.length / 3;
      for (const [x, z] of triangle) {
        target.positions.push(x / 100, height, z / 100);
        target.normals.push(0, 1, 0);
      }
      target.indices.push(first, first + 1, first + 2);
    }
  }
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
  private authoredMeshes: pc.Mesh[] = [];
  private authoredMaterials: pc.Material[] = [];
  private societyMeshes: pc.Mesh[] = [];
  private societyMaterials: pc.Material[] = [];
  private readonly societyCharacters = new Map<string, PlayerAvatar>();
  private lastSocietyFrameMs=0;
  private nativeSocietyDiscontinuity=true;
  private settleSocietyUntilMs=0;
  private promotedInhabitant:string|null=null;
  private readonly societyPositions = new Map<string, readonly [number, number]>();
  private latestSociety: OwnedSocietyState | null = null;
  private lastObserver: readonly [number, number] | null = null;
  private societyScope = '';
  private societyTick = -1;
  private societyAnimation: SocietyAnimation | null = null;
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
    const sidewalkBatch = batch();
    for (const sidewalk of district.sidewalks) {
      addFlatPolygon(sidewalkBatch, sidewalk.polygons, 0.025);
    }
    const sidewalkMesh = mesh(device, sidewalkBatch);
    if (sidewalkMesh !== null) {
      const sidewalkMaterial = new pc.StandardMaterial();
      sidewalkMaterial.diffuse = new pc.Color(0.76, 0.76, 0.71);
      sidewalkMaterial.emissive = new pc.Color(0.025, 0.023, 0.019);
      sidewalkMaterial.emissiveIntensity = 0.15;
      sidewalkMaterial.gloss = 0.1;
      sidewalkMaterial.update();
      const sidewalks = new pc.Entity('owned-sidewalks');
      sidewalks.addComponent('render', {
        meshInstances: [new pc.MeshInstance(sidewalkMesh, sidewalkMaterial, sidewalks)],
        castShadows: false,
        receiveShadows: true,
      });
      this.meshes.push(sidewalkMesh);
      this.materials.push(sidewalkMaterial);
      this.root.addChild(sidewalks);
    }

    let drawCalls = sidewalkMesh === null ? 0 : 1;

    // No record gives the ground a surface. The grid is the authored walking datum and says so.
    const datum = lineBatch();
    addGroundDatum(datum, district.bounds_cm);
    drawCalls += this.addLines(datum, 'owned-district-ground-datum-unavailable', 0.35);

    // No record gives any building a material. Every building draws the same way: its recorded
    // footprint and roof height as an outline, hatched between the edges. The interpretation's
    // facade grids and parapets are generated recipes with nothing observed behind them, so they
    // are not drawn either.
    const hatch = hatchTexture(device);
    this.textures.push(hatch);
    const surfaces = hatchBatch();
    const outlines = lineBatch();
    for (const building of district.buildings) addUnavailableBuilding(surfaces, outlines, building);
    if (surfaces.indices.length > 0) {
      const geometry = new pc.Mesh(device);
      geometry.setPositions(surfaces.positions);
      geometry.setNormals(surfaces.normals);
      geometry.setUvs(0, surfaces.uvs);
      geometry.setIndices(surfaces.indices);
      geometry.update(pc.PRIMITIVE_TRIANGLES);
      const surface = unavailableSurfaceMaterial(hatch);
      const entity = new pc.Entity('owned-building-surface-unavailable');
      entity.addComponent('render', {
        meshInstances: [new pc.MeshInstance(geometry, surface, entity)],
        castShadows: false,
        receiveShadows: false,
      });
      this.meshes.push(geometry);
      this.materials.push(surface);
      this.root.addChild(entity);
      drawCalls += 1;
    }
    drawCalls += this.addLines(outlines, 'owned-building-recorded-extent', 1);
    this.unavailable = Object.freeze({
      buildingSurfaces: district.buildings.length,
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
        const mat = new pc.StandardMaterial(); mat.diffuse = new pc.Color(.22, .54, .58); mat.emissive = new pc.Color(.07, .16, .17); mat.cull = pc.CULLFACE_NONE; mat.update();
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

  private addLines(source: LineBatch, name: string, opacity: number): number {
    if (source.indices.length === 0) return 0;
    const geometry = new pc.Mesh(this.device);
    geometry.setPositions(source.positions);
    geometry.setIndices(source.indices);
    geometry.update(pc.PRIMITIVE_LINES);
    const surface = unavailableLineMaterial(opacity);
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
      const source = batch();
      addBuilding(source, local);
      const geometry = mesh(this.device, source);
      if (geometry === null) continue;
      const surface = new pc.StandardMaterial();
      surface.diffuse = instance.origin.role === 'fictional'
        ? new pc.Color(0.12, 0.34, 0.4)
        : new pc.Color(0.74, 0.66, 0.55);
      surface.emissive = instance.origin.role === 'fictional'
        ? new pc.Color(0.05, 0.58, 0.68)
        : new pc.Color(0.08, 0.04, 0.02);
      surface.emissiveIntensity = instance.origin.role === 'fictional' ? 0.55 : 0.12;
      surface.metalness = 0.22;
      surface.gloss = 0.72;
      surface.useMetalness = true;
      surface.update();
      const entity = new pc.Entity(`authored-${instance.instanceId}`);
      entity.addComponent('render', {
        meshInstances: [new pc.MeshInstance(geometry, surface, entity)],
        castShadows: true,
        receiveShadows: true,
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
      this.authoredMeshes.push(geometry);
      this.authoredMaterials.push(surface);
      this.authoredRoot.addChild(entity);
    }
  }

  /** Release the unavailable population without inventing an authoritative snapshot. */
  clearSociety(): void {
    this.latestSociety = null;
    this.societyAnimation = null;
    this.settleSocietyUntilMs = 0;
    this.lastObserver = null;
    this.promotedInhabitant = null;
    this.societyScope = '';
    this.societyTick = -1;
    this.nativeSocietyDiscontinuity = true;
    this.societyPositions.clear();
    for (const character of this.societyCharacters.values()) character.destroy();
    this.societyCharacters.clear();
    for (const value of this.societyMeshes) value.destroy();
    for (const value of this.societyMaterials) value.destroy();
    this.societyMeshes = [];
    this.societyMaterials = [];
  }

  setSociety(
    state: OwnedSocietyState,
    visibleCap = 24,
    observer?: readonly [number, number],
  ): number {
    this.latestSociety = state;
    this.lastObserver = observer ?? null;
    const scope = `${state.society_id ?? 'preview'}:${state.branch_id ?? ''}`;
    if(scope!==this.societyScope){for(const character of this.societyCharacters.values())character.destroy();this.societyCharacters.clear();}
    const consecutive = scope === this.societyScope && state.tick === this.societyTick + 1;
    this.nativeSocietyDiscontinuity ||= !consecutive;
    this.societyScope = scope;
    this.societyTick = state.tick;
    // Picking follows only currently visible display positions, never a stale capped subset.
    this.societyPositions.clear();
    const visible = [...state.inhabitants]
      .filter((inhabitant) => inhabitant.synthetic === true)
      .sort((a, b) => observer === undefined ? 0 :
        Math.hypot(a.position_mm[0] / 1000 - observer[0], a.position_mm[1] / 1000 - observer[1]) -
        Math.hypot(b.position_mm[0] / 1000 - observer[0], b.position_mm[1] / 1000 - observer[1]))
      .slice(0, Math.max(0, Math.min(visibleCap, 24)));
    const visibleIds=new Set(visible.map(person=>person.id));
    for(const [id,character] of this.societyCharacters)if(!visibleIds.has(id)){character.destroy();this.societyCharacters.delete(id);}
    const animated = visible.map((inhabitant, ordinal) => {
      const role=inhabitant.role??'inhabitant';
      let character=this.societyCharacters.get(inhabitant.id);
      if(!character){character=new PlayerAvatar(this.device,this.societyRoot,{name:`synthetic:${inhabitant.id}`,detail:'mid',representation:abstractCharacter({kind:'synthetic-inhabitant',societyId:state.society_id??'preview',branchId:state.branch_id??'preview',inhabitantId:inhabitant.id},'mid',syntheticCharacterStyle(inhabitant.id))});this.societyCharacters.set(inhabitant.id,character);}
      const to = [
        inhabitant.position_mm[0] / 1000,
        inhabitant.position_mm[1] / 1000,
      ] as const;
      const candidatePath = inhabitant.motion_path_mm?.map(([x, z]) => [x / 1000, z / 1000] as const);
      // Legacy snapshots have no supported path. Do not fabricate travel between endpoints.
      const path = state.profile === 'exulanica-society/v2' && consecutive && candidatePath?.length
        ? candidatePath : [to];
      const from = path[0]!;
      this.societyPositions.set(inhabitant.id, from);
      character.update({x:from[0],y:character.body.heightMm/1000*.89,z:from[1],yaw:0,pitch:0},0,0,1/60,true,true,0);
      return { id: inhabitant.id, role, ordinal, from, to, path };
    });
    this.societyAnimation = animated.some(person=>person.path.length>1) ? {
      startedAtMs: performance.now(),
      durationMs: 1_850,
      inhabitants: animated,
    } : null;
    this.applyCoincidentVisibility();
    this.lastSocietyFrameMs=performance.now();
    return visible.length;
  }

  /** Interpolate display meshes only; authoritative endpoints remain the society snapshots. */
  tickSociety(nowMs: number): void {
    const animation = this.societyAnimation;
    if (animation === null) {
      if(nowMs<this.settleSocietyUntilMs){
        const dt=Math.max(.001,Math.min(.05,(nowMs-this.lastSocietyFrameMs)/1000));this.lastSocietyFrameMs=nowMs;
        for(const [id,character] of this.societyCharacters){const p=this.societyPositions.get(id)!;character.update({x:p[0],y:character.body.heightMm/1000*.89,z:p[1],yaw:0,pitch:0},0,0,dt,true,false,0);}
        this.applyCoincidentVisibility();
      }else this.settleSocietyUntilMs=0;
      return;
    }
    const linear = Math.max(0, Math.min(1, (nowMs - animation.startedAtMs) / animation.durationMs));
    const progress = linear * linear * (3 - 2 * linear);
    const dt=Math.max(.001,Math.min(.05,(nowMs-this.lastSocietyFrameMs)/1000));
    this.lastSocietyFrameMs=nowMs;
    for (const inhabitant of animation.inhabitants) {
      const position = sampleMotionPath(inhabitant.path, progress);
      const previous=this.societyPositions.get(inhabitant.id)??position;
      this.societyPositions.set(inhabitant.id, position);
      const character=this.societyCharacters.get(inhabitant.id);
      character?.update({x:position[0],y:character.body.heightMm/1000*.89,z:position[1],yaw:0,pitch:0},position[0]-previous[0],position[1]-previous[1],dt,true,nowMs===Number.MAX_SAFE_INTEGER,0);
    }
    this.applyCoincidentVisibility();
    if (linear >= 1) {this.societyAnimation = null;this.settleSocietyUntilMs=nowMs===Number.MAX_SAFE_INTEGER?0:nowMs+600;}
  }

  refreshNearby(observer: readonly [number, number]): void {
    if (this.societyAnimation || !this.latestSociety || (this.lastObserver && Math.hypot(observer[0] - this.lastObserver[0], observer[1] - this.lastObserver[1]) < 4)) return;
    this.setSociety(this.latestSociety, 24, observer);
  }

  /** GPU buffer residency, separate from the serialized source document byte count. */
  get characterTextureBytes():number{return [...this.societyCharacters.values()].reduce((bytes,character)=>bytes+character.textureResidentBytes,0);}
  get geometryResidentBytes(): number {
    return [...this.societyCharacters.values()].reduce((sum,character)=>sum+character.residentBytes,0)+[...this.meshes, ...this.authoredMeshes, ...this.societyMeshes].reduce((sum, mesh) => sum + (mesh.vertexBuffer?.numBytes ?? 0) + mesh.indexBuffer.reduce((bytes, buffer) => bytes + (buffer?.numBytes ?? 0), 0), 0);
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

  get societyAnimating(): boolean { return this.societyAnimation !== null || this.settleSocietyUntilMs>0; }

  private applyCoincidentVisibility():void {
    const groups=new Map<string,string[]>();
    for(const [id,p] of this.societyPositions){const key=p.map(n=>n.toFixed(3)).join(':');const ids=groups.get(key)??[];ids.push(id);groups.set(key,ids);}
    for(const ids of groups.values()){
      const shown=ids.includes(this.promotedInhabitant??'')?this.promotedInhabitant:ids.slice().sort()[0];
      for(const id of ids){const character=this.societyCharacters.get(id);if(character)character.root.enabled=id===shown;}
    }
  }
  revealInhabitant(id:string):void {if(!this.societyPositions.has(id))return;this.promotedInhabitant=id;this.applyCoincidentVisibility();}
  get drawnInhabitantCount():number{return [...this.societyCharacters.values()].filter(character=>character.root.enabled&&!character.root.tags.has('native-character-hidden')).length;}
  coincidentInhabitants(id:string):readonly string[]{const p=this.societyPositions.get(id);return p?[...this.societyPositions].filter(([,q])=>Math.hypot(p[0]-q[0],p[1]-q[1])<.001).map(([key])=>key):[];}
  inhabitantRepresentation(id:string){return this.societyCharacters.get(id)?.representation??null;}

  nativeCharacterFrames(deltaSeconds:number,reducedMotion:boolean):readonly NativeCharacterFrame[]{
    const discontinuity=this.nativeSocietyDiscontinuity;this.nativeSocietyDiscontinuity=false;
    return [...this.societyCharacters.values()].map(character=>{
      const p=character.root.getLocalPosition();
      return {subject:character.representation.subject,parent:this.societyRoot,fallback:character.root,visible:character.root.enabled,position:[p.x,p.y,p.z],yaw:character.facing,deltaSeconds,reducedMotion,discontinuity};
    });
  }

  get visibleInhabitantIds(): readonly string[] { return [...this.societyPositions.keys()]; }

  /** Stable subject selection against the displayed avatar, with building occlusion. */
  pickInhabitant(origin: readonly [number, number, number], direction: readonly [number, number, number]): string | null {
    let nearest = Infinity;
    for (const building of this.district.buildings) nearest = Math.min(nearest, buildingRayDistance(building, origin, direction) ?? Infinity);
    let selected: string | null = null;
    for (const [id, [x, z]] of this.societyPositions) {
      if(!this.societyCharacters.get(id)?.root.enabled||this.societyCharacters.get(id)?.root.tags.has('native-character-hidden'))continue;
      const height=(this.societyCharacters.get(id)?.body.heightMm??1820)/1000;
      const distance = rayBox(origin, direction, [x - .34, 0, z - .34], [x + .34, height, z + .34]);
      if (distance !== null && distance < nearest) { nearest = distance; selected = id; }
    }
    return selected;
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
    this.clearSociety();
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
