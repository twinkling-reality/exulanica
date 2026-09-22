import { NativeCharacterRuntime } from './native-character-runtime.js';
import type { CharacterByteLoader } from './native-character-pool.js';
import * as pc from 'playcanvas';
import type {
  AnchorTable,
  AnchorId,
  AtlasScene,
  CameraPose,
  DirectNavigationResolution,
  DirectNavigationTarget,
  DirectNavigationTransition,
  EmphasisBuffers,
  FocusState,
  Island,
  LocalVec3,
  IslandId,
  MapPresentationState,
  NavigationSurface,
  NavigationWorld,
  NeighborhoodId,
  NeighborhoodIndex,
  NavigationPose,
  OwnedDistrict,
  ResidencyAction,
  ResidencyAsset,
  ResidencyCost,
  ResidencyStage,
  ResidencyState,
  ResidencyView,
  RepresentationPressureState,
  RepresentationIntent,
  RepresentationBounds,
  RepresentationSubject,
  RenderOriginState,
  SpatialClassification,
  TierState,
  ViewManifest,
  WorldTopologySnapshot,
  WorldPreviewSession,
  WorldProposalOrigin,
  WorldStyleVersion,
} from '@exulanica/atlas-core';
import { shouldDrawFrame } from './frame-policy.js';
import {
  DISSOLVE_BAND_FRACTION,
  EMPTY_RESIDENCY_STATE,
  EMPTY_TIER_STATE,
  INITIAL_FOCUS_STATE,
  applyViewManifestInto,
  atlasMapPose,
  atlasVec3,
  buildAnchorTable,
  RECOVERY_MARGIN_AU,
  buildNeighborhoodIndex,
  buildNavigationWorld,
  navigationRegionForIsland,
  ownedDistrictNavigation,
  classifySpatialPhase,
  enterAtlasMap,
  exitAtlasMap,
  focusDirectly,
  isNavigationLineVisible,
  isNavigationPositionClear,
  latchFocus,
  localDirectionToAtlas,
  localToAtlas,
  localVec3,
  mapTierState,
  neutralEmphasis,
  occurrenceNormalizer,
  resolveFocus,
  releaseFocus,
  resolveDirectNavigation,
  resolveTiers,
  planDirectNavigationTransition,
  planResidency,
  residencyDemandsForView,
  sampleDirectNavigationTransition,
  completeResidencyRequest,
  composeAtlasWorld,
  WorldCustomizationController,
  RepresentationPressureController,
  INITIAL_RENDER_ORIGIN,
  renderOriginForNeighborhood,
  frameFraction,
  districtRepresentationSubjects,
  validateRepresentationSubject,
  DEFAULT_FOCUS_CONFIG,
} from '@exulanica/atlas-core';
import { OwnedDistrictRuntime } from './owned-district-runtime.js';
import type { GeneratedTileAttachment, GeneratedTileMount } from './generated-tile/binding-contract.js';
import { PlayerAvatar } from './player-avatar.js';
import { FollowCamera, playerCameraAimHeight, type PlayerCameraMode } from './player-camera.js';
import {
  DAWN_THEME,
  DEFAULT_WORLD_ART_PROFILE,
  WORLD_STYLE_CATALOG,
  unitRgb,
  worldArtProfile,
  type PresentationTheme,
  type WorldArtProfile,
  type WorldStyleParameters,
} from '@exulanica/presentation';
import { AnchorOverlay } from './anchor-overlay.js';
import { MapRegionOverlay } from './map-region-overlay.js';
import type { AnchorMotes } from './anchor-motes.js';
import { createAnchorMotes } from './anchor-motes.js';
import {
  DEFAULT_CONTROLS,
  FirstPersonControls,
  type CameraState,
  type InputMode,
} from './controls.js';
import type { GoogleTilesConfig } from './google-tiles-config.js';
import {
  createGoogleTilesEnvironment,
  type GoogleTilesEnvironment,
} from './google-tiles-environment.js';
import type { SourceMediaCatalog } from './source-media.js';
import { sourceMediaForIsland } from './source-media.js';
import { createWorldField, type WorldField } from './world-field.js';
import { createComposedWorld, type ComposedWorld } from './composed-world.js';
import { createRegionMass, type RegionMass } from './region-mass.js';
import { createRegionRelief, type RegionRelief } from './region-relief.js';
import type { PointMap } from './opm.js';
import type { PointCloud } from './point-cloud.js';
import {
  SINGLE_VIEW_EDGE_MARGIN,
  createPointCloud,
  singleViewDepths,
} from './point-cloud.js';
import { defaultSemanticsFor } from './semantics.js';
// `reliefFor` moved to point-cloud.ts beside RELIEF_PARALLAX_DEG, the constant it reads, so the
// authored point-map runtime can use it without importing this module back. Re-exported here
// because this is where every existing caller imports it from.
export { reliefFor } from './point-cloud.js';
import { reliefFor } from './point-cloud.js';
import {
  createAuthoredPointMaps,
  type AuthoredPointMapPlacement,
  type AuthoredPointMaps,
} from './authored-point-maps.js';
import { sceneInspectionViews, calibratedCameraFrustum, type SceneInspectionView, type RecoveredSceneCamera } from './scene-inspection.js';
import { PROOF_LENS_SPLAT_MODIFIER, createSceneSplatAsset, type TrainedSceneGeometry } from './scene-splats.js';
import {
  SceneObjectRuntime,
  type ObjectRepresentationRegistration,
  type PlacedAuthoredObject,
} from './scene-objects.js';
import {
  opmPointInScene,
  type PlacedScenePointMap,
  validateScenePointMapPlacement,
  scenePointMapViewpoint,
} from './scene-point-maps.js';
import {
  RepresentationRuntime,
  type RepresentationDraw,
  type RepresentationMetadata,
  type RepresentationReport,
} from './representation-runtime.js';
import {
  MAX_STATIC_MESHES_PER_REPRESENTATION,
  meshLocalExtent,
  type ExternalRepresentationEntry,
  representationParentVisible,
  representationWorldBounds,
  retainedPointAllocation,
  staticMeshGroupRepresentation,
  staticMeshRepresentation,
} from './representation-binding.js';
import { DataViewOverlay } from './data-view/overlay.js';
import type { DataViewOverlayPlan } from './data-view/overlay-plan.js';

export type RepresentationSelectionReason = 'explicit' | 'unavailable' | 'unregistered';

/**
 * The PlayCanvas binding for the Atlas.
 *
 * ONE SCENE, FOR THE WHOLE SESSION. The `AtlasScene` handed in here is never replaced. Tier
 * changes, view manifests and camera moves are all transformations over it. There is no "enter
 * scene" and no "return to Atlas" in this file, and there must never be one.
 *
 * WHAT THIS FILE DOES NOT OWN. Every rule about what the world should look like lives in
 * atlas-core: which tier an island is at, which anchor has focus, what emphasis each anchor
 * carries, where an island sits. This module converts those answers into PlayCanvas objects and
 * nothing more. That split is what makes ADR-0003 a two-package decision rather than a front-end
 * rewrite, and it is worth being strict about: if a rule is decided here, it is in the wrong
 * package.
 */

export interface IslandVisual {
  readonly island: Island;
  readonly entity: pc.Entity;
  readonly cloud: PointCloud;
  readonly pointMap: PlacedScenePointMap;
  /** Reused so the per-frame uniform write allocates nothing. */
  readonly uIsland: Float32Array;
  readonly uPoint: Float32Array;
  /**
   * The photograph's camera in the map's local frame, for a map drawn as one photograph's own
   * view (an unmeasured arrangement). Null for every other map. The frame loop hands its world
   * position to the shader, which flattens the relief as the visitor leaves the camera.
   */
  readonly singleViewLocal: pc.Vec3 | null;
  /** Where the print stands in the map's local frame: the camera, moved out by the print depth. */
  readonly printLocal: pc.Vec3 | null;
  /** Radians of parallax per world unit the visitor stands from the camera, at full relief. */
  readonly parallaxPerUnit: number;
  /**
   * The proof lens for this island: an already-resolved RGB triple and a tint strength.
   *
   * Four zeros is the lens off, which is what every island holds until a caller supplies a value.
   * NOTHING IN THIS PACKAGE MAY DECIDE WHAT GOES IN HERE. Which tier an island is showing and
   * which colour that tier wears are both `@exulanica/presentation`'s (`proof-lens.ts`), and the
   * app resolves them before they cross; the binding's whole job is to get four floats to a
   * uniform. That is the same split `uPalette` already keeps for provenance colour, and it is
   * what `pnpm boundaries` and the module header above are protecting.
   */
  readonly uLens: Float32Array;
}

/** One island's proof-lens colour, resolved by the caller: red, green, blue, tint strength. */
export type ProofLensColor = readonly [number, number, number, number];

/** The photograph the visitor is looking into, when it is drawn in an unmeasured arrangement. */
export interface CentredPhotograph {
  readonly sceneId: string;
  readonly captureId: string;
  readonly islandId: IslandId;
}

/** Reused by the frame loop so handing a camera to the shader allocates nothing. */
const SINGLE_VIEW_SCRATCH = new pc.Vec3();
const SINGLE_VIEW_PRINT = new pc.Vec3();

/**
 * How flat one photograph's relief should be for a visitor at `viewer`, and whether they are behind
 * its print.
 *
 * The relief is right only from the camera. A visitor a distance D from it sees two samples on one
 * camera ray, at depths near and far, part by at most D (1/near - 1/far) radians, and that parting
 * is every gap and stretched edge a relief can show. Flattening in inverse depth scales it by
 * (1 - flatten), so this keeps the relief whole while the parting stays within
 * `RELIEF_PARALLAX_DEG` and beyond that flattens just enough to hold it there. `parallaxPerUnit` is
 * (1/near - 1/far) in world units. Far away, or well to the side, the relief is a flat print.
 */
/**
 * The deepest, up to `wanted`, a photograph's print can stand without its lower edge going under
 * the walking ground. MEASURED 2026-09-11 on the first personal place: a print at the median depth
 * of the widest photograph, 5.3 m with a 77.5 degree vertical field, had the lower quarter of its
 * frame under the ground, because a frame that tall reaches the ground well before 5.3 m.
 */
function printDepthAboveGround(
  entity: pc.Entity,
  island: Island,
  navigationWorld: NavigationWorld,
  map: PlacedScenePointMap['map'],
  wanted: number,
): number {
  const { position: eye, fovYDeg, aspect } = map.header.viewpoint;
  const tanY = Math.tan((fovYDeg * Math.PI) / 360);
  const tanX = tanY * aspect;
  if (!(tanY > 0) || !(tanX > 0) || !Number.isFinite(tanX)) return wanted;
  const local = entity.getLocalTransform();
  const corner = new pc.Vec3();
  const STEPS = 100;
  for (let step = 0; step < STEPS; step += 1) {
    const depth = wanted * (1 - step / STEPS);
    const clear = [-1, 0, 1].every((across) => {
      local.transformPoint(corner.set(eye[0] + across * depth * tanX, eye[1] - depth * tanY, eye[2] - depth), corner);
      const at = localToAtlas(island.placement, localVec3(corner.x, corner.y, corner.z));
      const ground = navigationWorld.surface.sample(at.x, at.z);
      return ground === null || at.y >= ground.height;
    });
    if (clear) return depth;
  }
  return wanted / STEPS;
}

/** The lens off. A value rather than an absence, so an unlit island is written, not skipped. */
const PROOF_LENS_OFF: ProofLensColor = Object.freeze([0, 0, 0, 0]);

/**
 * Seconds a trained scene's work buffer stays open for after the lens changes.
 *
 * MEASURED, and the first two values were both too small. `WORKBUFFER_UPDATE_ONCE` asks for one
 * refill on the next frame and the tint took several seconds to appear; eight drawn frames, about
 * a seventh of a second, did not help either. What the wait is actually for is the work-buffer
 * shader: installing the modifier rebuilds it, the link is deferred until first use, and until it
 * lands the refills run through the shader that has no lens in it. Nothing asks for another refill
 * when the replacement shader is ready, so the window has to outlast the compile.
 *
 * 2.5 s covers it on the real trained bowl on ANGLE Metal on 2026-09-06, where the tint was absent
 * at 1.8 s and present at 2.5 s. It is a bounded window per press of a button, and it costs
 * nothing once closed: getting it wrong is not a visible error but a silent one, a lens that says
 * nothing while the panel says the tier out loud.
 */
const PROOF_LENS_SETTLE_SECONDS = 2.5;
/** Authored triangle samples retain object structure without changing district sampling density. */
const AUTHORED_MESH_SAMPLE_DENSITY_SCALE = 8;

/**
 * A trained region is all or nothing: one gsplat asset, identical at every drawn stage. The flat
 * 24 is why the pressure controller's level-3 budget (96 * 0.22 = 21.12) cannot afford it, and
 * why the occupied-region exemption in `planResidency` has to clear the budget as well as the
 * stage ceiling.
 */
export const TRAINED_REGION_RESIDENCY_COST: ResidencyCost = Object.freeze({
  stub: 0, proxy: 24, coarse: 24, full: 24,
});

/**
 * The residency inputs for one frame, and the signature that decides whether to replan.
 *
 * `occupied` is the region the visitor is standing in. It belongs in the signature as well as the
 * view: crossing a region boundary inside one neighborhood at unchanged tiers changes nothing
 * else, so without it the plan that stubbed the region under the visitor would never be revisited.
 */
export function residencyFrameInputs(input: {
  readonly map: boolean;
  readonly activeNeighborhood: NeighborhoodId | null;
  readonly tier: TierState;
  readonly target: IslandId | null;
  readonly occupied: IslandId | null;
}): { readonly view: ResidencyView; readonly signature: string } {
  return {
    view: {
      map: input.map,
      activeNeighborhood: input.activeNeighborhood,
      tier: input.tier,
      target: input.target,
      occupied: input.occupied,
    },
    signature: [
      input.map ? 'map' : 'ground',
      input.activeNeighborhood ?? '',
      input.target ?? '',
      input.occupied ?? '',
      ...[...input.tier.tier.entries()].map(([id, tier]) => `${id}:${tier}`),
    ].join('|'),
  };
}

/**
 * The representation subject for one object placed from the reviewed catalog.
 *
 * What exists for it is a display record and the reviewed asset's identity: its key as the label
 * and its content digest as the one reference. It has no structured source records, so it claims
 * none. `extent` is the object root's local bounds, before authored placement is applied.
 */
export function placedCatalogObjectSubject(
  object: PlacedAuthoredObject,
  extent: {
    readonly min: readonly [number, number, number];
    readonly max: readonly [number, number, number];
  },
): RepresentationSubject {
  const frameId = `authored-object:${object.objectId}:object-local`;
  return Object.freeze({
    subjectId: object.objectId,
    subjectKind: 'object',
    sceneId: null,
    frameId,
    origin: 'authored',
    sourceRefs: Object.freeze([object.asset.contentSha256]),
    availability: 'available',
    rendered: true,
    // These are deterministic presentation samples of the authored triangles, not measurements.
    points: 'mesh-surface-samples',
    compatibleBlend: true,
    bounds: Object.freeze({
      frameId,
      units: 'scene-units',
      origin: 'authored',
      basis: 'authored-bounds',
      min: extent.min,
      max: extent.max,
    }),
    label: object.asset.assetKey,
    dataAvailable: false,
    unavailableReason: 'Generated whole-object surface samples from static renderer triangles; not observed measurements, semantic parts or segmentation.',
  });
}

export interface AtlasBindingOptions {
  readonly canvas: HTMLCanvasElement;
  readonly overlayParent: HTMLElement;
  readonly scene: AtlasScene;
  /** Source-independent authored ground. It is a region, never a capture-backed Atlas island. */
  readonly authoredRegion?: AuthoredRegion;
  /**
   * Depth estimates from the account holder's own photographs, placed by them in that region.
   *
   * Only the ones the server said are available; an instance in any other state is not passed
   * here and nothing is drawn where it was. Requires ``authoredRegion``: the placements are in
   * that region's frame, and there is no other root they could hang from.
   */
  readonly authoredPointMaps?: readonly AuthoredPointMapPlacement[];
  /** Legacy unposed point maps, one per island. Islands with no map render as anchors only. */
  readonly pointMaps: ReadonlyMap<IslandId, PointMap>;
  /** Every map in a posed reconstruction scene. Supersedes pointMaps when supplied. */
  readonly placedPointMaps?: readonly PlacedScenePointMap[];
  readonly trainedGeometry?: readonly TrainedSceneGeometry[];
  readonly recoveredCameras?: readonly RecoveredSceneCamera[];
  /** Caller-authorized media presentation keyed by the scene's evidence handles. */
  readonly sourceMedia?: SourceMediaCatalog;
  /** Keep original photographs in the authorized inspector instead of placing optical sheets in the world. */
  /**
   * Which arrangement of the composed world to build.
   *
   * The catalog offers substitutable modules per recipe slot; the seed decides which one each
   * element gets, stably per element, so the same seed always rebuilds the same world and a
   * different one rebuilds a different world from the same memories. Omitted means the composer's
   * own default, which is what a world with no persisted arrangement should keep getting.
   */
  readonly worldSeed?: string;
  readonly deviceTypes?: readonly string[];
  readonly blend?: boolean;
  readonly sizeGain?: number;
  readonly maxSizePx?: number;
  readonly fov?: number;
  readonly sensitivityMultiplier?: number;
  readonly overlay?: boolean;
  readonly theme?: PresentationTheme;
  /** Appearance-only realization. Topology, navigation, collision, and evidence stay protected. */
  readonly artProfile?: WorldArtProfile;
  readonly artProfileParameters?: WorldStyleParameters;
  /** Access preference outranks a style's authored or personalized ambient tempo. */
  readonly reducedMotion?: boolean;
  /** Abstract renderer residency units. Point-map full detail costs 24 by default. */
  readonly residencyBudget?: number;
  /** Ceiling on the backing-store pixel ratio. Never raises a display above its own ratio. */
  readonly maxPixelRatio?: number;
  /** Optional visualization-only Google reference. It never participates in Atlas interaction. */
  readonly googleTiles?: GoogleTilesConfig;
  /** Admitted owned geography. One semantic document drives rendering and collision. */
  readonly ownedDistrict?: {
    readonly document: OwnedDistrict;
    readonly residentBytes: number;
    readonly interpretation?: import('@exulanica/atlas-core').DistrictInterpretation;
  };
  /**
   * Development evaluation of one baked generated tile, reachable only from the preview route.
   * Replaces the owned district: the tile supplies the ground, the collision and the opening
   * stance, and draws itself into the environment root.
   */
  readonly generatedTile?: GeneratedTileMount;
  /** Optional current rights/record refinements for known renderer subjects. */
  readonly representationSubjects?: readonly RepresentationSubject[];
}

/**
 * How far this renderer carries a person across a ground that states no extent.
 *
 * MEASURED, not chosen. A position reaches the GPU as a 32-bit float, and the render origin only
 * moves when the active neighborhood changes, which in a world whose scene holds no regions never
 * happens. So the whole walk is drawn at its true distance from the world origin, and the smallest
 * position change the pipeline can represent is the float32 step at that distance: 0.12 mm at
 * 2 km, 0.98 mm at 8.192 km, 1.95 mm at 16.4 km. 8192 metres is the farthest distance at which the
 * drawn position still resolves the millimetre, which is the unit every stored coordinate in this
 * product is written in, so it is the farthest distance at which the renderer can still put a
 * person exactly where the world says they are.
 *
 * It is a property of this renderer and not of the world. A descriptor states that its ground has
 * no edge; this states how much of that ground the current pipeline can honestly draw, and it
 * moves when the pipeline does, with no stored world changing and nothing to migrate.
 */
export const AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M = 8192;

/**
 * The ground an authored region states.
 *
 * `flat` describes a surface whose perimeter is a real edge, such as a place rebuilt from
 * photographs. `endless` states there is no perimeter, so it carries no extent to read.
 */
export type AuthoredGround =
  | {
      readonly kind: 'flat';
      readonly halfWidthMm: number;
      readonly halfDepthMm: number;
      readonly elevationMm: number;
    }
  | {
      readonly kind: 'endless';
      readonly elevationMm: number;
    };

export interface AuthoredRegion {
  readonly regionId: IslandId;
  readonly module: {
    readonly key: 'region.authored-ground';
    readonly version: 1 | 2;
  };
  readonly ground: AuthoredGround;
  /** Ground-contact pose in the authored region frame, in fixed-point wire units. */
  readonly spawn: {
    readonly xMm: number;
    readonly yMm: number;
    readonly zMm: number;
    readonly yawMicroradians: number;
  };
}

/** Where an authored ground has a walking surface, in metres, for the navigation contract. */
export function authoredGroundSurface(ground: AuthoredGround): NavigationSurface {
  const elevation = ground.elevationMm / 1000;
  const sample = Object.freeze({
    height: elevation,
    normal: Object.freeze({ x: 0, y: 1, z: 0 }),
  });
  if (ground.kind === 'endless') {
    const radius = AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M;
    return Object.freeze({
      sample: (x: number, z: number) => (Math.hypot(x, z) <= radius ? sample : null),
    });
  }
  const halfWidth = ground.halfWidthMm / 1000;
  const halfDepth = ground.halfDepthMm / 1000;
  return Object.freeze({
    sample: (x: number, z: number) =>
      Math.abs(x) <= halfWidth && Math.abs(z) <= halfDepth ? sample : null,
  });
}

/**
 * The walkable field an endless authored ground admits.
 *
 * `buildNavigationWorld` sizes its field from the scene's regions, and a starter world has none,
 * so it lands on its 90 metre floor. That floor was the second wall standing behind the first: a
 * sampler with no rectangle still leaves a person compressed at 90 metres and returned at 138.
 *
 * Both radii sit INSIDE the distance the surface answers for, by the same margin the resident
 * field already puts between its soft band and its hard envelope. A walk is therefore returned
 * while there is still described ground underneath it, which is what makes the refusal honest:
 * the field this renderer can carry ran out, not the ground. Every position movement can reach,
 * including the compressed overshoot, is a position the surface answers.
 */
export function endlessAuthoredNavigation(world: NavigationWorld): NavigationWorld {
  const recoveryRadius = AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M - RECOVERY_MARGIN_AU;
  return Object.freeze({
    ...world,
    fieldRadius: recoveryRadius - RECOVERY_MARGIN_AU,
    recoveryRadius,
  });
}

export interface FrameReport {
  readonly dt: number;
  readonly mode: InputMode;
  readonly tier: TierState;
  readonly focusedIndex: number | null;
  readonly moving: boolean;
  readonly spatial: SpatialClassification;
  readonly residency: ResidencyState;
  readonly activeNeighborhood: NeighborhoodId | null;
  readonly navigating: boolean;
  readonly recoveryReason: 'outside-field' | 'no-surface' | 'unsafe-surface' | null;
  readonly representationPressure: RepresentationPressureState;
  readonly renderOrigin: RenderOriginState;
}

/** A tiny structural check that the presentation transform survived the trip into the engine. */
export interface PlacementCheck {
  readonly islandId: IslandId;
  readonly maxErrorMetres: number;
}

export class AtlasBinding {
  readonly app: pc.AppBase;
  readonly device: pc.GraphicsDevice;
  readonly camera: pc.Entity;
  readonly controls: FirstPersonControls;
  readonly overlay: AnchorOverlay | null;
  readonly mapOverlay: MapRegionOverlay | null;
  /**
   * One mote per non-person anchor, in atlas space.
   *
   * This is what a region with no reconstructed geometry looks like, and it is not optional:
   * a point cloud exists only where a point map was supplied, so without this a rung 4 island
   * renders as nothing at all. Rung 4 is a real rung with a movement model, not an absence.
   */
  readonly motes: AnchorMotes;
  /**
   * Placed depth estimates on the authored region, or null when the world has none to draw.
   *
   * Attached after construction rather than threaded through the constructor, as the generated
   * tile is: it hangs off a root the factory built and needs nothing else the binding holds.
   */
  authoredPointMaps: AuthoredPointMaps | null = null;
  readonly table: AnchorTable;
  readonly emphasis: EmphasisBuffers;
  readonly islands: readonly IslandVisual[];
  readonly trainedScenes: readonly {
    readonly island: Island;
    readonly entity: pc.Entity;
    readonly asset: pc.Asset;
    readonly geometry: TrainedSceneGeometry;
  }[];
  readonly trainedSceneFailures: readonly { readonly sceneId: string; readonly reason: string }[];
  readonly scene: AtlasScene;
  readonly navigationWorld: NavigationWorld;
  readonly field: WorldField;
  readonly topology: WorldTopologySnapshot;
  readonly composedWorld: ComposedWorld;
  readonly regionMass: RegionMass;
  readonly regionRelief: RegionRelief;
  readonly customization: WorldCustomizationController;
  /** Authored objects. Empty until a surface places one; see `scene-objects.ts`. */
  readonly objects: SceneObjectRuntime;
  private districtObjectFrame: { readonly regionId: IslandId; readonly key: string; readonly root: pc.Entity } | null = null;

  /** Install only a currently authorized region-to-district translation from the host. */
  setDistrictObjectFrame(binding: { readonly regionId: string; readonly translationMm: readonly [number, number, number] } | null): void {
    if (binding !== null && (this.ownedDistrict === null ||
        !binding.translationMm.every(Number.isSafeInteger) ||
        !this.scene.islands.some(island => String(island.islandId) === binding.regionId))) {
      throw new TypeError('District object frame requires a known region and integer translation');
    }
    const key = binding === null ? null : JSON.stringify(binding);
    if (key === (this.districtObjectFrame?.key ?? null)) return;
    if (this.districtObjectFrame !== null) {
      this.objects.setRegionOverride(this.districtObjectFrame.regionId, null);
      this.districtObjectFrame.root.destroy();
      this.districtObjectFrame = null;
    }
    if (binding !== null) {
      const regionId = this.scene.islands.find(island => String(island.islandId) === binding.regionId)!.islandId;
      const root = new pc.Entity(`district-objects:${regionId}`);
      root.setLocalPosition(...binding.translationMm.map(value => value / 1000) as [number, number, number]);
      this.environmentRoot.addChild(root);
      this.objects.setRegionOverride(regionId, root);
      this.districtObjectFrame = { regionId, key: key!, root };
    }
    this.applyResidencyPresentation();
    this.invalidate();
  }
  /** Scene segments, one region at a time. Installs nothing until a surface applies one. */
  readonly segmentOverlay: SegmentOverlayRuntime;
  readonly neighborhoodIndex: NeighborhoodIndex;
  /** Geographic display layers use their own root and never inherit Atlas origin rebasing. */
  readonly environmentRoot: pc.Entity;
  readonly renderRoot: pc.Entity;
  /** Null unless explicitly feature-flagged with a key by the application. */
  googleTiles: GoogleTilesEnvironment<unknown> | null = null;
  readonly ownedDistrict: OwnedDistrictRuntime | null;
  /** The mounted evaluation tile, if the preview route asked for one. */
  generatedTile: GeneratedTileAttachment | null = null;
  private representationController: RepresentationRuntime | null = null;
  get representation(): RepresentationRuntime {
    return this.representationController ??= new RepresentationRuntime();
  }
  /** Boxes, tags, links and the dark ground. Created with the registry; draws only when asked. */
  private representationOverlay: DataViewOverlay | null = null;
  private readonly representationDefaults = new Map<string, RepresentationSubject>();
  private readonly representationOverrides = new Map<string, RepresentationSubject>();
  private readonly representationFrames = new Map<string, pc.GraphNode>();
  private readonly representationSelectionObservers = new Set<(
    subjectId: string | null,
    reason: RepresentationSelectionReason,
  ) => void>();

  private tierState: TierState = EMPTY_TIER_STATE;
  private focusState: FocusState = INITIAL_FOCUS_STATE;
  private centred: CentredPhotograph | null = null;
  private occupied: IslandId | null = null;
  private readonly centredInverse = new pc.Mat4();
  private readonly centredCapture = new pc.Vec3();
  private readonly centredDirection = new pc.Vec3();
  private readonly normalizer: number;
  private readonly pose: { position: pc.Vec3; rotation: pc.Quat } = {
    position: new pc.Vec3(),
    rotation: new pc.Quat(),
  };
  private readonly qYaw = new pc.Quat();
  private readonly qPitch = new pc.Quat();
  private elapsed = 0;
  private mapState: MapPresentationState | null = null;
  private readonly residencyCatalog: readonly ResidencyAsset[];
  private readonly residencyBudget: number;
  private residencyState: ResidencyState = EMPTY_RESIDENCY_STATE;
  private residencyAllocated: ReadonlyMap<IslandId, ResidencyStage> = new Map();
  /**
   * Islands whose source body is actually drawn right now. The overlay needs this because an
   * interaction prompt has to belong to something visible: an anchor on a stubbed island would
   * otherwise put a marker on apparently empty ground.
   */
  private readonly presentIslands = new Set<IslandId>();
  private residencySignature = '';
  private readonly representationPressure = new RepresentationPressureController();
  private renderOriginState: RenderOriginState = INITIAL_RENDER_ORIGIN;
  private activeNeighborhood: NeighborhoodId | null = null;
  private navigationTransition: DirectNavigationTransition | null = null;
  private navigationElapsedMs = 0;
  private navigationTargetIsland: IslandId | null = null;
  private readonly recoveredCameras: readonly RecoveredSceneCamera[];
  private inspection: {
    readonly returnPose: NavigationPose;
    readonly returnFov: number;
    readonly returnProjection: pc.CameraComponent['calculateProjection'];
    view: SceneInspectionView;
  } | null = null;
  private readonly inspectionMatrix = new pc.Mat4();
  private readonly inspectionTarget = new pc.Vec3();
  private readonly inspectionUp = new pc.Vec3();
  private applicationControlsEnabled = true;
  /** Trained scenes whose work-buffer modifier is installed. See `setProofLens`. */
  private readonly proofLensSplatsPrepared = new Set<pc.Entity>();
  /** When the lens settle window closes, on the binding's own clock. Negative means closed. */
  private proofLensSettleUntil = -1;
  private styleProposalSequence = 0;
  private readonly skyClearColor = new pc.Color();
  private readonly mapClearColor = new pc.Color();

  onFrame: ((report: FrameReport) => void) | null = null;
  onResidencyActions: ((actions: readonly ResidencyAction[]) => void) | null = null;
  onNavigationArrive: ((target: DirectNavigationTarget) => void) | null = null;
  onMapTarget: ((islandId: IslandId) => void) | null = null;
  onInspectionChange: ((view: SceneInspectionView | null) => void) | null = null;
  /** Fires whenever the memory layer is switched, including when travel switches it on. */
  onMemoryLayerChange: ((visible: boolean) => void) | null = null;
  onRepresentationChange: ((report: RepresentationReport) => void) | null = null;

  private publishRepresentationReport(
    selected: string | null,
    report: RepresentationReport,
  ): RepresentationReport {
    if (report.selection !== selected) {
      const reason = selected !== null && report.subjects.some(entry =>
        entry.subject.subjectId === selected && entry.subject.availability !== 'available')
        ? 'unavailable' : 'unregistered';
      this.publishRepresentationSelection(report.selection, reason);
    }
    this.onRepresentationChange?.(report);
    return report;
  }

  private publishRepresentation(): RepresentationReport {
    const selected = this.representation.report.selection;
    return this.publishRepresentationReport(selected, this.representation.update());
  }

  private publishRepresentationSelection(
    subjectId: string | null,
    reason: RepresentationSelectionReason,
  ): void {
    for (const observer of this.representationSelectionObservers) observer(subjectId, reason);
  }

  /** Observe explicit selection and authority-driven clearing without owning the data-view panel. */
  observeRepresentationSelection(observer: (
    subjectId: string | null,
    reason: RepresentationSelectionReason,
  ) => void): () => void {
    this.representationSelectionObservers.add(observer);
    return () => { this.representationSelectionObservers.delete(observer); };
  }

  /** Called by the physical residency executor after its checked publish or terminal fallback. */
  settleResidencyRequest(requestId: string, ok: boolean): void {
    this.residencyState = completeResidencyRequest(this.residencyState, requestId, ok);
    this.residencyAllocated = new Map(
      [...this.residencyState.entries].map(([id, entry]) => [id, entry.current]),
    );
    this.applyResidencyPresentation();
  }

  private applyResidencyPresentation(): void {
    this.objects.setResidency(this.residencyAllocated, this.mapState !== null);
    for (const visual of this.islands) {
      const inspecting = visual.island.islandId === this.inspection?.view.islandId;
      visual.entity.enabled = !this.trainedScenes.some((splat) => splat.geometry.sceneId === visual.pointMap.sceneId)
        && (inspecting || this.residencyAllocated.get(visual.island.islandId) !== 'stub');
      visual.cloud.setInspection(inspecting);
      visual.uIsland[2] = inspecting ? visual.uIsland[1]!
        : visual.uIsland[1]! * (1 - DISSOLVE_BAND_FRACTION);
    }
    for (const visual of this.trainedScenes) {
      visual.entity.enabled = visual.island.islandId === this.inspection?.view.islandId
        || this.residencyAllocated.get(visual.island.islandId) !== 'stub';
    }
    this.publishRepresentation();
  }

  private constructor(
    app: pc.AppBase,
    camera: pc.Entity,
    controls: FirstPersonControls,
    overlay: AnchorOverlay | null,
    mapOverlay: MapRegionOverlay | null,
    motes: AnchorMotes,
    scene: AtlasScene,
    table: AnchorTable,
    islands: readonly IslandVisual[],
    trainedScenes: AtlasBinding['trainedScenes'],
    trainedSceneFailures: AtlasBinding['trainedSceneFailures'],
    recoveredCameras: readonly RecoveredSceneCamera[],
    navigationWorld: NavigationWorld,
    field: WorldField,
    topology: WorldTopologySnapshot,
    composedWorld: ComposedWorld,
    regionMass: RegionMass,
    regionRelief: RegionRelief,
    customization: WorldCustomizationController,
    neighborhoodIndex: NeighborhoodIndex,
    environmentRoot: pc.Entity,
    renderRoot: pc.Entity,
    initialProfile: WorldArtProfile,
    residencyCatalog: readonly ResidencyAsset[],
    residencyBudget: number,
    objectRoots: ReadonlyMap<IslandId, pc.Entity>,
    ownedDistrict: OwnedDistrictRuntime | null,
  ) {
    this.app = app;
    this.device = app.graphicsDevice;
    this.camera = camera;
    this.controls = controls;
    this.overlay = overlay;
    this.mapOverlay = mapOverlay;
    if (this.mapOverlay !== null) {
      this.mapOverlay.onSelect = (islandId) => this.onMapTarget?.(islandId);
    }
    this.motes = motes;
    this.scene = scene;
    this.table = table;
    this.islands = islands;
    this.trainedScenes = trainedScenes;
    this.trainedSceneFailures = trainedSceneFailures;
    this.recoveredCameras = recoveredCameras;
    this.navigationWorld = navigationWorld;
    this.field = field;
    this.objects = new SceneObjectRuntime(app, objectRoots, {
      registerRepresentation: (object, entity) =>
        this.registerAuthoredObjectRepresentation(object, entity),
      invalidate: () => this.invalidate(),
      artProfile: initialProfile,
    });
    this.segmentOverlay = new SegmentOverlayRuntime(islands, trainedScenes, () => playcanvasSegmentEngine(app), {
      lensPrepared: (entity) => this.proofLensSplatsPrepared.has(entity),
      // The same window the lens holds, on the same clock, closed by the same `settleProofLens`.
      settle: () => { this.proofLensSettleUntil = this.elapsed + PROOF_LENS_SETTLE_SECONDS; },
      invalidate: () => this.invalidate(),
    });
    this.topology = topology;
    this.composedWorld = composedWorld;
    this.regionMass = regionMass;
    this.regionRelief = regionRelief;
    this.customization = customization;
    this.neighborhoodIndex = neighborhoodIndex;
    this.environmentRoot = environmentRoot;
    this.renderRoot = renderRoot;
    this.ownedDistrict = ownedDistrict;
    this.setClearColours(initialProfile);
    this.residencyCatalog = residencyCatalog;
    this.residencyBudget = residencyBudget;
    this.emphasis = neutralEmphasis(table);
    this.normalizer = occurrenceNormalizer(table.anchors);
  }

  private dirty = true;
  private reducedMotion = false;
  private playerAvatar: PlayerAvatar | null = null;
  nativeCharacters:NativeCharacterRuntime|null=null;
  private nativePlayerDiscontinuity=true;
  /** Loader must resolve a permitted pinned reference through the current authenticated asset path. */
  enableNativeCharacters(loadBytes:CharacterByteLoader):NativeCharacterRuntime{
    this.nativeCharacters??=new NativeCharacterRuntime(this.app,loadBytes);
    if(this.ownedDistrict)this.playerAvatar??=new PlayerAvatar(this.device,this.environmentRoot);
    this.syncNativeCharacterFrames(0,true);
    return this.nativeCharacters;
  }
  private playerCameraMode: PlayerCameraMode = 'first-person';
  private playerCameraDistance=3.8;
  private readonly followCamera=new FollowCamera();

  /**
   * Third person shows the player unless the boom has been driven into them.
   *
   * A facade behind the player shortens the boom past the body, and drawing the avatar then fills
   * the screen with the inside of its own head. Reads last frame's boom length, because the camera
   * is solved after the characters are posed.
   */
  private get playerDrawn():boolean{
    return this.playerCameraMode==='third-person'&&this.inspection===null
      &&!this.followCamera.occludesPlayer();
  }
  private nearbySignature='';
  private lastPlayerPosition: readonly [number, number] | null = null;
  private lastRenderMs = -1;
  private readonly renderedPose = { x: NaN, y: NaN, z: NaN, yaw: NaN, pitch: NaN };

  static async create(options: AtlasBindingOptions): Promise<AtlasBinding> {
    const theme = options.theme ?? DAWN_THEME;
    const initialArtProfile = options.artProfile ?? DEFAULT_WORLD_ART_PROFILE;
    if (options.ownedDistrict !== undefined && options.generatedTile !== undefined) {
      throw new TypeError('A generated tile replaces the owned district; pass one or the other');
    }
    if (options.authoredRegion !== undefined &&
        (options.ownedDistrict !== undefined || options.generatedTile !== undefined)) {
      throw new TypeError('An authored starter region cannot replace geographic ground');
    }
    const cityActive = options.ownedDistrict !== undefined || options.generatedTile !== undefined ||
      (options.googleTiles?.enabled === true && options.googleTiles.apiKey.length > 0);
    const device = await pc.createGraphicsDevice(options.canvas, {
      deviceTypes: [...(options.deviceTypes ?? ['webgl2'])],
      antialias: true,
      depth: true,
      stencil: false,
      powerPreference: 'high-performance',
    });

    const app = new pc.AppBase(options.canvas);
    const appOptions = new pc.AppOptions();
    appOptions.graphicsDevice = device;
    appOptions.componentSystems = [
      pc.RenderComponentSystem,
      pc.AnimComponentSystem,
      pc.CameraComponentSystem,
      pc.LightComponentSystem,
      pc.GSplatComponentSystem,
    ];
    // `ContainerHandler` is what decodes an authored object's GLB, and `TextureHandler` is what
    // its embedded images become. The container's own sub-assets (render, material, animation)
    // are constructed already loaded by `GlbContainerResource` and never reach the loader, so
    // they need no handler; a missing one here is reported as a bare string rather than an
    // Error, which is why `scene-objects.ts` converts it before a status line sees it.
    appOptions.resourceHandlers = [pc.TextureHandler, pc.GSplatHandler, pc.ContainerHandler];
    app.init(appOptions);
    app.setCanvasFillMode(pc.FILLMODE_NONE);
    app.setCanvasResolution(pc.RESOLUTION_AUTO);
    /*
     * Cap the backing-store resolution.
     *
     * This scene is fragment-bound, not vertex-bound: a full-screen sky shader plus a ground
     * shader that loops over regions and traces for every pixel. Cost therefore scales with the
     * PIXEL COUNT, and on a 2x display an uncapped ratio quadruples that against a 1x panel for
     * detail that the atmosphere is deliberately diffusing away. The cap is a ceiling, not a
     * fixed value, so a 1x display is untouched.
     */
    device.maxPixelRatio = Math.min(globalThis.devicePixelRatio ?? 1, options.maxPixelRatio ?? 1.5);

    const camera = new pc.Entity('atlas-camera');
    const [skyR, skyG, skyB] = unitRgb(initialArtProfile.palette.sky);
    camera.addComponent('camera', {
      fov: options.fov ?? 70,
      nearClip: 0.08,
      farClip: cityActive ? 15_000 : 1200,
      clearColor: cityActive
        ? new pc.Color(0.79, 0.85, 0.88, 1)
        : new pc.Color(skyR, skyG, skyB, 1),
    });
    if (camera.camera !== undefined && camera.camera !== null) {
      camera.camera.toneMapping = pc.TONEMAP_ACES;
    }
    app.root.addChild(camera);

    const [hazeR, hazeG, hazeB] = unitRgb(initialArtProfile.palette.haze);
    app.scene.ambientLight = cityActive
      ? new pc.Color(0.64, 0.69, 0.74)
      : new pc.Color(hazeR * 0.58, hazeG * 0.58, hazeB * 0.58);
    app.scene.exposure = cityActive ? 1.12 : 1.06;
    app.scene.fog.type = pc.FOG_LINEAR;
    app.scene.fog.color.set(
      cityActive ? 0.83 : hazeR,
      cityActive ? 0.86 : hazeG,
      cityActive ? 0.89 : hazeB,
    );
    app.scene.fog.start = cityActive ? 110 : 46;
    app.scene.fog.end = cityActive ? 820 : 220;

    const worldLight = new pc.Entity('atlas-directional-light');
    const [lr, lg, lb] = unitRgb(initialArtProfile.palette.sun);
    worldLight.addComponent('light', {
      type: 'directional',
      color: new pc.Color(lr, lg, lb),
      intensity: cityActive ? 1.1 : 1.65,
      castShadows: true,
      shadowDistance: cityActive ? 120 : 72,
      normalOffsetBias: cityActive ? 0.25 : 0,
      shadowBias: cityActive ? 0.2 : 0.05,
      shadowResolution: 2048,
    });
    worldLight.setEulerAngles(52, -38, 0);
    app.root.addChild(worldLight);
    if(cityActive){
      const skyFill=new pc.Entity('district-sky-fill');
      skyFill.addComponent('light',{type:'directional',color:new pc.Color(.70,.82,1),intensity:.72,castShadows:false});
      skyFill.setEulerAngles(28,145,0);app.root.addChild(skyFill);
    }

    const table = buildAnchorTable(options.scene);
    const environmentRoot = new pc.Entity('geographic-environment');
    app.root.addChild(environmentRoot);
    const renderRoot = new pc.Entity('atlas-render-origin');
    app.root.addChild(renderRoot);
    const authoredGround = options.authoredRegion?.ground;
    const authoredSurface = authoredGround === undefined
      ? undefined
      : authoredGroundSurface(authoredGround);
    const navigationWorld = options.generatedTile !== undefined
      ? options.generatedTile.navigationWorld
      : options.ownedDistrict === undefined
      ? authoredGround?.kind === 'endless'
        ? endlessAuthoredNavigation(buildNavigationWorld(options.scene, authoredSurface))
        : buildNavigationWorld(options.scene, authoredSurface)
      // The district owns the ground and the blockers; the scene owns where the memories are. Both
      // are already drawn in the same coordinate space, so withholding the regions from the
      // navigation world did not keep them apart, it only made them unreachable.
      : ownedDistrictNavigation(
        options.ownedDistrict.document,
        options.scene.islands.map(navigationRegionForIsland),
      );
    const ownedDistrict = options.ownedDistrict === undefined
      ? null
      : new OwnedDistrictRuntime(
        device,
        environmentRoot,
        options.ownedDistrict.document,
        options.ownedDistrict.residentBytes,
        options.ownedDistrict.interpretation,
      );
    const neighborhoodIndex = buildNeighborhoodIndex(options.scene);
    const explicitPointMaps = options.placedPointMaps ?? [];
    const explicitlyPlacedIslands = new Set(explicitPointMaps.map((value) => value.islandId));
    const placedPointMaps = [
      ...explicitPointMaps,
      ...[...options.pointMaps]
        .filter(([islandId]) => !explicitlyPlacedIslands.has(islandId))
        .map(
          ([islandId, map], index): PlacedScenePointMap => ({
            sceneId: `legacy:${islandId}`,
            artifactId: `legacy:${islandId}:${index}`,
            islandId,
            map,
            sceneFromOpmRowMajor: [
              1, 0, 0, 0,
              0, 1, 0, 0,
              0, 0, 1, 0,
              0, 0, 0, 1,
            ],
            localUnitsToSceneUnits: 1,
          }),
        ),
    ];
    for (const value of placedPointMaps) validateScenePointMapPlacement(value);
    const pointMapsByIsland = new Map<IslandId, PlacedScenePointMap[]>();
    for (const value of placedPointMaps) {
      const held = pointMapsByIsland.get(value.islandId);
      if (held === undefined) pointMapsByIsland.set(value.islandId, [value]);
      else held.push(value);
    }
    const trainedAssets = new Map<TrainedSceneGeometry, { asset: pc.Asset; entity: pc.Entity }>();
    const trainedSceneFailures: Array<AtlasBinding['trainedSceneFailures'][number]> = [];
    for (const geometry of options.trainedGeometry ?? []) {
      if (!options.scene.islands.some((island) => island.islandId === geometry.islandId)) continue;
      let asset: pc.Asset | undefined;
      let entity: pc.Entity | undefined;
      try {
        asset = await createSceneSplatAsset(app, geometry);
        entity = new pc.Entity(`trained-scene:${geometry.artifactId}`);
        const m = geometry.sceneFromAssetRowMajor;
        applySceneTransform(entity, m, Math.hypot(m[0]!, m[4]!, m[8]!));
        entity.addComponent('gsplat', { asset });
        trainedAssets.set(geometry, { asset, entity });
      }
      catch (error) {
        entity?.destroy();
        if (asset !== undefined) { asset.unload(); app.assets.remove(asset); }
        trainedSceneFailures.push({ sceneId: geometry.sceneId,
          reason: error instanceof Error ? error.message : 'The trained scene decoder failed.' });
      }
    }
    const trainedIslandIds = new Set([...trainedAssets.keys()].map((geometry) => geometry.islandId));
    const availableReconstruction = new Set([...pointMapsByIsland.keys(), ...trainedIslandIds]);
    const residencyBudget = options.residencyBudget ?? 96;
    const residencyCatalog: ResidencyAsset[] = options.scene.islands.map((island) => ({
      islandId: island.islandId,
      cost: trainedIslandIds.has(island.islandId)
        ? TRAINED_REGION_RESIDENCY_COST
        : pointMapsByIsland.has(island.islandId)
        ? pointMapResidencyCost(pointMapsByIsland.get(island.islandId)!.length, residencyBudget)
        : Object.freeze({ stub: 0, proxy: 2, coarse: 2, full: 2 }),
    }));
    const field = createWorldField(
      device,
      navigationWorld,
      initialArtProfile,
      theme,
      options.reducedMotion ?? false,
      /*
       * The world field draws an authored ground from an exact rectangle, and a ground with no
       * extent has none to give it. Rather than invent one, an endless ground takes the field's
       * own continuous surface, which is built by sampling the navigation surface above and so
       * runs flat and unbroken to well past the distance this renderer supports. Giving that
       * ground its own appearance is the world field's own work.
       */
      authoredGround === undefined || authoredGround.kind === 'endless'
        ? undefined
        : Object.freeze({
            halfWidth: authoredGround.halfWidthMm / 1000,
            halfDepth: authoredGround.halfDepthMm / 1000,
            elevation: authoredGround.elevationMm / 1000,
          }),
    );
    if (options.ownedDistrict !== undefined || options.generatedTile !== undefined) field.entity.enabled = false;
    renderRoot.addChild(field.entity);
    const topology = composeAtlasWorld(options.scene, {
      availableReconstruction,
      ...(options.worldSeed === undefined ? {} : { seed: options.worldSeed }),
    });
    const composedWorld = createComposedWorld(
      device,
      topology,
      initialArtProfile,
      theme,
    );
    // What the Map looks down on. Built from the same anchors the ground view already draws, so
    // it cannot drift from what the world actually holds, and enabled only at the Map vantage.
    // Relief first: it decides which regions have a measured surface, and the mass draws marks
    // for the ones that do not. A region cannot be both without saying its own extent twice.
    const regionRelief = createRegionRelief(
      device,
      options.scene,
      new Map(
        [...pointMapsByIsland].map(([islandId, maps]) => [islandId, maps[0]!.map] as const),
      ),
      initialArtProfile,
    );
    renderRoot.addChild(regionRelief.entity);
    const regionMass = createRegionMass(
      device,
      options.scene,
      initialArtProfile,
      regionRelief.reconstructed,
    );
    renderRoot.addChild(regionMass.entity);
    const customization = new WorldCustomizationController({
      topologyDigest: topology.topologyDigest,
      regionIds: new Set(options.scene.islands.map((island) => island.islandId)),
      catalog: WORLD_STYLE_CATALOG,
      initial: Object.freeze({
        versionId: 'world-style:0',
        revision: 0,
        parentVersionId: null,
        global: Object.freeze({
          profileId: initialArtProfile.profileId,
          profileVersion: initialArtProfile.profileVersion,
          ...(options.artProfileParameters === undefined
            ? {}
            : { parameters: options.artProfileParameters }),
        }),
        regions: Object.freeze([]),
        appliedFromProposalId: null,
      }),
    });
    renderRoot.addChild(composedWorld.entity);
    const visuals: IslandVisual[] = [];
    const trainedScenes: Array<AtlasBinding['trainedScenes'][number]> = [];

    const objectRoots = new Map<IslandId, pc.Entity>();
    let authoredPointMaps: AuthoredPointMaps | null = null;
    if (options.authoredRegion !== undefined) {
      const root = new pc.Entity(`authored-region:${options.authoredRegion.regionId}`);
      root.setLocalPosition(0, options.authoredRegion.ground.elevationMm / 1000, 0);
      renderRoot.addChild(root);
      objectRoots.set(options.authoredRegion.regionId, root);
      if (options.authoredPointMaps !== undefined && options.authoredPointMaps.length > 0) {
        // Built after the root is in the graph, because each print's world-space camera is read
        // once here rather than recomputed every frame.
        authoredPointMaps = createAuthoredPointMaps({
          device,
          root,
          placements: options.authoredPointMaps,
          ...(options.sizeGain === undefined ? {} : { sizeGain: options.sizeGain }),
          ...(options.maxSizePx === undefined ? {} : { maxSizePx: options.maxSizePx }),
          theme,
        });
      }
    }
    for (const island of options.scene.islands) {
      const islandEntity = new pc.Entity(`island:${island.islandId}`);
      applyPlacement(islandEntity, island);
      renderRoot.addChild(islandEntity);
      objectRoots.set(island.islandId, islandEntity);
      for (const [geometry, { asset, entity }] of trainedAssets) {
        if (geometry.islandId !== island.islandId) continue;
        islandEntity.addChild(entity);
        trainedScenes.push({ island, entity, asset, geometry });
      }

      for (const pointMap of pointMapsByIsland.get(island.islandId) ?? []) {
        const entity = new pc.Entity(`point-map:${pointMap.artifactId}`);
        applyScenePointMapPlacement(entity, pointMap);
        if (pointMap.arrangement === 'unmeasured-fan') standOnTheGround(entity, pointMap, island, navigationWorld);
        const map = pointMap.map;
        const cloud = createPointCloud({
          device,
          map,
          semantics: defaultSemanticsFor(map.header),
          ...(options.sizeGain === undefined ? {} : { sizeGain: options.sizeGain }),
          ...(options.maxSizePx === undefined ? {} : { maxSizePx: options.maxSizePx }),
          ...(options.blend === undefined ? {} : { blend: options.blend }),
          // One photograph's own view reads as its surface, not as dots. Posed maps overlap one
          // another from many cameras, so they stay points.
          surface: pointMap.arrangement === 'unmeasured-fan',
          ...(pointMap.photograph === undefined ? {} : { photograph: pointMap.photograph }),
          theme,
        });
        const instance = new pc.MeshInstance(cloud.mesh, cloud.material, entity);
        entity.addComponent('render', { meshInstances: [instance] });
        islandEntity.addChild(entity);
        const depths = pointMap.arrangement === 'unmeasured-fan' ? singleViewDepths(map) : null;
        const printDepth = depths === null ? 0
          : printDepthAboveGround(entity, island, navigationWorld, map, depths.median);
        const eye = depths === null ? null : cloud.enableSingleView(printDepth);
        const worldScale = entity.getLocalScale().x * island.placement.scale;

        visuals.push({
          island,
          entity,
          cloud,
          pointMap,
          singleViewLocal: eye === null ? null : new pc.Vec3(eye[0], eye[1], eye[2]),
          printLocal: eye === null ? null : new pc.Vec3(eye[0], eye[1], eye[2] - printDepth),
          parallaxPerUnit: depths === null ? 0 : (1 / depths.nearest - 1 / depths.furthest) / worldScale,
          uIsland: new Float32Array([
            1,
            cloud.footprintRadiusLocal,
            cloud.footprintRadiusLocal * (1 - DISSOLVE_BAND_FRACTION),
            island.placement.scale * pointMap.localUnitsToSceneUnits,
          ]),
          uPoint: new Float32Array([
            options.sizeGain ?? cloud.defaultSizeGain,
            options.maxSizePx ?? cloud.defaultMaxSizePx,
            900,
            0,
          ]),
          // Four zeros: the proof lens off. See `setProofLens`.
          uLens: new Float32Array(4),
        });
      }
    }

    const start = options.generatedTile !== undefined
      ? { ...options.generatedTile.start }
      : options.ownedDistrict !== undefined
      ? ownedDistrictCameraState(navigationWorld, options.ownedDistrict.document)
      : options.authoredRegion !== undefined
        ? {
            x: options.authoredRegion.spawn.xMm / 1000,
            y: options.authoredRegion.spawn.yMm / 1000 + navigationWorld.eyeHeight,
            z: options.authoredRegion.spawn.zMm / 1000,
            yaw: options.authoredRegion.spawn.yawMicroradians / 1_000_000,
            pitch: 0,
          }
      : cityActive
        ? cityCameraState('overview')
        : initialAtlasCameraState(options.scene, navigationWorld);

    // The Google-tiles entry is an aerial overview, not a stance. Everything else starts on foot.
    const aerialStart = options.ownedDistrict === undefined && options.generatedTile === undefined && cityActive;
    const controls = new FirstPersonControls(
      options.canvas,
      start,
      cityActive ? { ...DEFAULT_CONTROLS, moveSpeed: 1.65, sprintMultiplier: 2.7, accelTime: .16 } : DEFAULT_CONTROLS,
      navigationWorld,
      { groundStart: !aerialStart },
    );
    controls.onCameraToggle = () => { binding.setCameraMode(binding.cameraMode === 'first-person' ? 'third-person' : 'first-person'); };
    controls.setSensitivityMultiplier(options.sensitivityMultiplier ?? 1);
    const overlay =
      options.overlay === false ? null : new AnchorOverlay(options.overlayParent);
    const mapOverlay =
      options.overlay === false
        ? null
        : new MapRegionOverlay(
            options.overlayParent,
            options.scene,
            new Map(options.scene.islands.map((island) => [
              island.islandId,
              sourceMediaForIsland(island, options.sourceMedia ?? new Map())[0]?.title,
            ])),
          );

    // Parented to the ROOT and not to an island entity. `table.atlasPositions` already has the
    // presentation transform applied, so hanging the cloud under an island would apply the
    // placement a second time and put every anchor somewhere no anchor is.
    const motes = createAnchorMotes({ device, table, theme });
    if (motes.count > 0) {
      const moteEntity = new pc.Entity('atlas-anchors');
      moteEntity.addComponent('render', {
        meshInstances: [new pc.MeshInstance(motes.mesh, motes.material, moteEntity)],
      });
      renderRoot.addChild(moteEntity);
    }

    const binding = new AtlasBinding(
      app,
      camera,
      controls,
      overlay,
      mapOverlay,
      motes,
      options.scene,
      table,
      visuals,
      Object.freeze(trainedScenes),
      Object.freeze(trainedSceneFailures),
      options.recoveredCameras ?? [],
      navigationWorld,
      field,
      topology,
      composedWorld,
      regionMass,
      regionRelief,
      customization,
      neighborhoodIndex,
      environmentRoot,
      renderRoot,
      initialArtProfile,
      Object.freeze(residencyCatalog),
      residencyBudget,
      objectRoots,
      ownedDistrict,
    );
    binding.authoredPointMaps = authoredPointMaps;
    if (options.ownedDistrict !== undefined) binding.renderRoot.enabled = false;
    if (options.generatedTile !== undefined) {
      binding.renderRoot.enabled = false;
      binding.generatedTile = options.generatedTile.attach({ app, environmentRoot, camera });
    }
    if (options.googleTiles?.enabled === true && options.googleTiles.apiKey.length > 0) {
      binding.renderRoot.enabled = false;
      binding.googleTiles = createGoogleTilesEnvironment(
        app,
        environmentRoot,
        options.overlayParent,
        options.googleTiles,
        {
          invalidate: () => binding.invalidate(),
          unavailable: () => binding.invalidate(),
        },
      ) as GoogleTilesEnvironment<unknown>;
      void binding.googleTiles.attach();
    }
    binding.initializeRepresentation(options.representationSubjects ?? []);
    return binding;
  }

  private representationSubject(fallback: RepresentationSubject): RepresentationSubject {
    return this.representationOverrides.get(fallback.subjectId) ?? fallback;
  }

  /**
   * Borrow one authored object's whole renderer draw without inventing submesh ownership.
   *
   * A bounded static hierarchy stays one authored subject. Its renderer nodes retain their own
   * transforms, while the object-root frame owns aggregate bounds. Skinned and morphing draws stay
   * unsupported because generated static samples would stop agreeing with the visible surface.
   * The ordinary authored object remains drawn in every refusal case.
   */
  private registerAuthoredObjectRepresentation(
    object: PlacedAuthoredObject,
    entity: pc.Entity,
  ): ObjectRepresentationRegistration {
    const instances = (entity.findComponents('render') as pc.RenderComponent[])
      .flatMap(render => render.meshInstances);
    if (instances.length === 0) {
      return Object.freeze({
        ok: false as const,
        reason: 'World to data is unavailable for this object because its reviewed asset has no supported renderer mesh.',
      });
    }
    if (instances.length > MAX_STATIC_MESHES_PER_REPRESENTATION) {
      return Object.freeze({
        ok: false as const,
        reason: `World to data is unavailable for this object because its reviewed asset has ${instances.length} renderer meshes; the bounded whole-object limit is ${MAX_STATIC_MESHES_PER_REPRESENTATION}.`,
      });
    }
    if (instances.some(instance => instance.skinInstance != null || instance.morphInstance != null)) {
      return Object.freeze({
        ok: false as const,
        reason: 'World to data is unavailable for this object because skinned or morphing meshes do not have a supported static surface sample.',
      });
    }
    let subject: RepresentationSubject;
    const current = () => this.representationSubject(subject);
    const representationStyle = this.representation.style;
    const authoredMeshStyle = Object.freeze({
      ...representationStyle,
      points: Object.freeze({
        ...representationStyle.points,
        densityPerSquareMetre:
          representationStyle.points.densityPerSquareMetre * AUTHORED_MESH_SAMPLE_DENSITY_SCALE,
      }),
    });
    const group = staticMeshGroupRepresentation(
      this.device, entity, instances, current, authoredMeshStyle,
    );
    if (group === null) {
      return Object.freeze({
        ok: false as const,
        reason: 'World to data is unavailable for this object because its static triangle hierarchy exceeds the bounded source size or has no finite surface and extent.',
      });
    }
    subject = placedCatalogObjectSubject(object, group.extent);
    try {
      return Object.freeze({
        ok: true as const,
        release: this.registerRepresentationSubjects(entity, [{ subject, draw: group.draw }]),
      });
    } catch (error) {
      return Object.freeze({
        ok: false as const,
        reason: error instanceof Error
          ? `World to data is unavailable for this object: ${error.message}`
          : 'World to data is unavailable for this object because its mesh is not supported.',
      });
    }
  }

  private rememberRepresentationSubject(subject: RepresentationSubject): () => RepresentationSubject {
    if (this.representationDefaults.has(subject.subjectId)) {
      throw new TypeError(`Duplicate representation subject ${subject.subjectId}`);
    }
    this.representationDefaults.set(subject.subjectId, Object.freeze(subject));
    return () => this.representationSubject(subject);
  }

  private registerOwnedDistrictMetadata(sourceDisplayAllowed: boolean): void {
    if (this.ownedDistrict === null) return;
    const root = this.ownedDistrict.root;
    for (const subject of districtRepresentationSubjects(
      this.ownedDistrict.district,
      sourceDisplayAllowed ? 'available' : 'unavailable',
    )) {
      const current = this.rememberRepresentationSubject(subject);
      this.representationFrames.set(subject.subjectId, root);
      const metadata: RepresentationMetadata = {
        currentSubject: current,
        parentVisible: () => representationParentVisible(root),
      };
      this.representation.registerMetadata(metadata);
    }
  }

  private initializeRepresentation(subjects: readonly RepresentationSubject[]): void {
    const remember = (subject: RepresentationSubject): (() => RepresentationSubject) =>
      this.rememberRepresentationSubject(subject);

    for (const visual of this.islands) {
      const { min, max } = visual.pointMap.map.header.bounds;
      const source = visual.pointMap.artifactId;
      const surface = visual.cloud.surface;
      // The map's own look (points or a surface) is its rendered form; the data view draws the
      // same retained samples in its own look. Neither can fade the other, so the data look
      // grows over the map's own look and replaces it only at the points end.
      const current = remember({
        subjectId: source,
        subjectKind: 'scene',
        sceneId: visual.pointMap.sceneId,
        frameId: `artifact:${source}:opm-local`,
        origin: 'inferred',
        sourceRefs: Object.freeze([source]),
        availability: 'available',
        rendered: true,
        points: 'retained-points',
        compatibleBlend: true,
        blend: 'overlay',
        bounds: Object.freeze({
          frameId: `artifact:${source}:opm-local`,
          units: 'metres',
          origin: 'inferred',
          basis: 'source-bounds',
          min: Object.freeze([...min]) as readonly [number, number, number],
          max: Object.freeze([...max]) as readonly [number, number, number],
        }),
        label: null,
        dataAvailable: visual.pointMap.captureId !== undefined,
        unavailableReason: surface
          ? 'The point-map surface keeps its own look until the points end; its retained samples fade in over it.'
          : 'The point map keeps its own look until the points end; the same retained samples fade in over it.',
      });
      this.representationFrames.set(source, visual.entity);
      const render = visual.entity.render;
      if (render === undefined || render === null) continue;
      const originallyEnabled = render.enabled;
      this.representation.register({
        currentSubject: current,
        parentVisible: () => visual.entity.parent !== null
          && representationParentVisible(visual.entity.parent),
        setRenderedWeight: weight => { render.enabled = originallyEnabled && weight > 0; },
        pointDemand: () => visual.pointMap.map.header.pointCount,
        createPoints: limit => retainedPointAllocation(
          this.device,
          visual.entity,
          visual.pointMap.map.position,
          limit,
          source,
          this.representation.style,
        ),
        restore: () => { render.enabled = originallyEnabled; },
      });
    }

    for (const visual of this.trainedScenes) {
      const source = visual.geometry.artifactId;
      const centres = splatCentres(visual);
      const current = remember({
        subjectId: source,
        subjectKind: 'scene',
        sceneId: visual.geometry.sceneId,
        frameId: `artifact:${source}:asset-local`,
        origin: 'generated',
        sourceRefs: Object.freeze([source]),
        availability: 'available',
        rendered: true,
        points: centres === null ? null : 'gaussian-centres',
        // The splat renderer exposes no fade this view owns, so the splat stays whole while its
        // own centres fade in over it, and leaves at the points end.
        compatibleBlend: centres !== null,
        ...(centres === null ? {} : { blend: 'overlay' as const }),
        bounds: Object.freeze({
          frameId: `artifact:${source}:asset-local`,
          units: 'scene-units',
          origin: 'generated',
          basis: 'source-bounds',
          min: Object.freeze([...visual.geometry.bounds.min]) as readonly [number, number, number],
          max: Object.freeze([...visual.geometry.bounds.max]) as readonly [number, number, number],
        }),
        label: null,
        dataAvailable: false,
        unavailableReason: centres === null
          ? 'The engine retained no CPU Gaussian-centre buffer.'
          : 'The trained splat cannot fade here, so its Gaussian centres fade in over it and it leaves at the points end.',
      });
      this.representationFrames.set(source, visual.entity);
      const component = visual.entity.gsplat;
      if (component === undefined || component === null) continue;
      const originallyEnabled = component.enabled;
      this.representation.register({
        currentSubject: current,
        parentVisible: () => visual.entity.parent !== null
          && representationParentVisible(visual.entity.parent),
        setRenderedWeight: weight => { component.enabled = originallyEnabled && weight > 0; },
        pointDemand: () => (centres === null ? 0 : centres.length / 3),
        createPoints: limit => centres === null ? null : retainedPointAllocation(
          this.device,
          visual.entity,
          centres,
          limit,
          source,
          this.representation.style,
        ),
        restore: () => { component.enabled = originallyEnabled; },
      });
    }

    if (this.ownedDistrict !== null) {
      const district = this.ownedDistrict.district;
      const sourceRefs = Object.freeze(district.source_records.map(source => source.sha256));
      const sourceDisplayAllowed = district.source_records.length > 0
        && district.source_records.every(source => source.operation_rights.display === true);
      let ordinal = 0;
      const districtFrame = `${district.frame?.name ?? district.district_id}:render-metres`;
      const rootWorld = this.ownedDistrict.root.getWorldTransform().data;
      this.registerOwnedDistrictMetadata(sourceDisplayAllowed);
      for (const render of this.ownedDistrict.root.findComponents('render') as pc.RenderComponent[]) {
        for (const instance of render.meshInstances) {
          const subjectId = `${district.district_id}:render-group:${render.entity.name}:${ordinal}`;
          ordinal += 1;
          // A batch's extent is its own mesh's, and it is stated in the district frame only when
          // the batch draws in that frame. It is the extent of a group, never of one building.
          const nodeWorld = instance.node.getWorldTransform().data;
          const extent = nodeWorld.every((value, index) => value === rootWorld[index])
            ? meshLocalExtent(instance.mesh) : null;
          const current = remember({
            subjectId,
            subjectKind: 'geometry-group',
            sceneId: null,
            frameId: districtFrame,
            // This is renderer tessellation derived from retained source and interpretation
            // records. Sampling its vertices must never relabel them as observed measurements.
            origin: 'generated',
            sourceRefs,
            availability: sourceDisplayAllowed ? 'available' : 'unavailable',
            rendered: true,
            points: 'mesh-surface-samples',
            compatibleBlend: true,
            bounds: extent === null ? null : Object.freeze({
              frameId: districtFrame,
              units: 'metres' as const,
              origin: 'generated' as const,
              basis: 'generated-extent' as const,
              min: Object.freeze([...extent.min]) as readonly [number, number, number],
              max: Object.freeze([...extent.max]) as readonly [number, number, number],
            }),
            label: render.entity.name,
            dataAvailable: sourceDisplayAllowed,
            unavailableReason: sourceDisplayAllowed
              ? 'Sampled points are generated aggregate mesh vertices, not measurements or per-feature segmentation.'
              : 'A retained district source is unavailable for display.',
          });
          this.representationFrames.set(subjectId, instance.node);
          const draw = staticMeshRepresentation(
            this.device, instance, current, undefined, this.representation.style);
          if (draw !== null) this.representation.register(draw);
        }
      }
    }
    this.representationOverlay = new DataViewOverlay({
      device: this.device,
      app: this.app,
      camera: this.camera,
      report: () => this.representation.report,
      worldBounds: subject => this.representationBounds(subject),
      reducedMotion: () => this.reducedMotion,
      invalidate: () => this.invalidate(),
    }, this.representation.style);
    // Points are prepared a bounded amount per update; keep publishing until every request is met.
    this.app.on('update', () => {
      if (this.representationController !== null && this.representation.report.pendingSubjects > 0) {
        this.publishRepresentation();
        this.invalidate();
      }
    });
    this.setRepresentationSubjects(subjects);
  }

  /**
   * Register subjects whose geometry the caller draws (a baked tile, for example) against the node
   * their frame and bounds are stated in. Each one passes the same validation, budget, blend and
   * overlay rules as the binding's own subjects, and later rights changes arrive through
   * `setRepresentationSubjects` as usual. Give each subject either the static triangle draw it
   * stands for, which the data view borrows exactly as it borrows a district batch, or a draw of
   * the caller's own. Nothing is registered unless every entry is accepted.
   *
   * Returns the handle that unregisters all of them and restores every borrowed draw. Call it when
   * the geometry unloads; it also runs by itself if the node is destroyed first. Idempotent.
   */
  registerRepresentationSubjects(
    node: pc.GraphNode,
    entries: readonly ExternalRepresentationEntry[],
  ): () => void {
    const seen = new Set<string>();
    for (const entry of entries) {
      validateRepresentationSubject(entry.subject);
      this.representation.assertStyleAccepts(entry.subject);
      const id = entry.subject.subjectId;
      if (seen.has(id) || this.representationDefaults.has(id)) {
        throw new TypeError(`Duplicate representation subject ${id}`);
      }
      if ((entry.instance === undefined) === (entry.draw === undefined)) {
        throw new TypeError(`Representation subject ${id} needs exactly one of a mesh instance or a draw`);
      }
      seen.add(id);
    }
    const registered: string[] = [];
    const release = (): void => {
      for (const id of registered.splice(0)) {
        this.representation.unregister(id);
        this.representationDefaults.delete(id);
        this.representationOverrides.delete(id);
        this.representationFrames.delete(id);
      }
    };
    try {
      for (const entry of entries) {
        const fixed = Object.freeze({
          ...entry.subject,
          sourceRefs: Object.freeze([...entry.subject.sourceRefs]),
          bounds: entry.subject.bounds === null ? null : Object.freeze({
            ...entry.subject.bounds,
            min: Object.freeze([...entry.subject.bounds.min]) as readonly [number, number, number],
            max: Object.freeze([...entry.subject.bounds.max]) as readonly [number, number, number],
          }),
        });
        const id = fixed.subjectId;
        const current = () => this.representationSubject(fixed);
        const own = entry.draw;
        const draw: RepresentationDraw | null = own === undefined
          ? staticMeshRepresentation(this.device, entry.instance!, current, undefined, this.representation.style)
          : {
            currentSubject: current,
            parentVisible: () => own.parentVisible(),
            setRenderedWeight: weight => own.setRenderedWeight(weight),
            createPoints: limit => own.createPoints(limit),
            restore: () => own.restore(),
            ...(own.pointDemand === undefined ? {} : { pointDemand: () => own.pointDemand!() }),
            ...(own.setExistingPointWeight === undefined
              ? {} : { setExistingPointWeight: (weight: number) => own.setExistingPointWeight!(weight) }),
            ...(own.refresh === undefined ? {} : { refresh: () => own.refresh!() }),
          };
        if (draw === null) {
          throw new TypeError(`Representation subject ${id} is not a static triangle draw the data view can borrow`);
        }
        this.representationDefaults.set(id, fixed);
        this.representationFrames.set(id, node);
        registered.push(id);
        this.representation.register(draw);
      }
    } catch (error) {
      release();
      throw error;
    }
    let active = true;
    const handle = (): void => {
      if (!active) return;
      active = false;
      node.off('destroy', handle);
      release();
      if (this.representationController !== null) this.publishRepresentation();
      this.invalidate();
    };
    node.once('destroy', handle);
    this.publishRepresentation();
    this.invalidate();
    return handle;
  }

  /** Update current rights and records for known geometry without replacing world identity. */
  setRepresentationSubjects(subjects: readonly RepresentationSubject[]): RepresentationReport {
    const seen = new Set<string>();
    for (const subject of subjects) {
      validateRepresentationSubject(subject);
      if (seen.has(subject.subjectId)) throw new TypeError('Representation subjects must be unique');
      seen.add(subject.subjectId);
      const fixed = this.representationDefaults.get(subject.subjectId);
      if (fixed === undefined) throw new TypeError(`Unknown representation subject ${subject.subjectId}`);
      for (const key of [
        'subjectKind', 'sceneId', 'frameId', 'origin', 'rendered', 'points', 'compatibleBlend', 'blend',
      ] as const) {
        if (subject[key] !== fixed[key]) {
          throw new TypeError(`Representation subject ${subject.subjectId} changed ${key}`);
        }
      }
      if (JSON.stringify(subject.record ?? null) !== JSON.stringify(fixed.record ?? null)) {
        throw new TypeError(`Representation subject ${subject.subjectId} changed record`);
      }
    }
    // Commit only after every record passes. Copy caller-owned arrays so later mutation cannot
    // silently change current rights, references or display bounds.
    for (const subject of subjects) {
      const bounds = subject.bounds === null ? null : Object.freeze({
        ...subject.bounds,
        min: Object.freeze([...subject.bounds.min]) as readonly [number, number, number],
        max: Object.freeze([...subject.bounds.max]) as readonly [number, number, number],
      });
      this.representationOverrides.set(subject.subjectId, Object.freeze({
        ...subject,
        sourceRefs: Object.freeze([...subject.sourceRefs]),
        bounds,
      }));
    }
    const report = this.publishRepresentation();
    this.invalidate();
    return report;
  }

  /** Presentation-only. Camera, inspection, picking, clocks, collision and navigation are untouched. */
  setRepresentationIntent(intent: RepresentationIntent): RepresentationReport {
    const selected = this.representation.report.selection;
    const report = this.publishRepresentationReport(selected, this.representation.setIntent(intent));
    this.invalidate();
    return report;
  }

  get representationReport(): RepresentationReport { return this.representation.report; }

  /** Highlight one subject in the data view, or none. The world selection and camera stay put. */
  setRepresentationSelection(subjectId: string | null): RepresentationReport {
    const selected = this.representation.report.selection;
    const report = this.representation.setSelection(subjectId);
    if (report.selection !== selected) this.publishRepresentationSelection(report.selection, 'explicit');
    this.onRepresentationChange?.(report);
    this.invalidate();
    return report;
  }

  /** What the overlay drew on the last drawn frame, with every refusal it made. */
  get representationOverlayPlan(): DataViewOverlayPlan | null {
    return this.representationOverlay?.plan ?? null;
  }

  /** Display-world corners for UI projection. This creates no draw or pick target. */
  representationBounds(subject: RepresentationSubject): readonly (readonly [number, number, number])[] | null {
    validateRepresentationSubject(subject);
    const known = this.representationFrames.get(subject.subjectId);
    const registered = this.representationDefaults.get(subject.subjectId);
    if (registered !== undefined && subject.frameId !== registered.frameId) return null;
    const effective = registered === undefined ? subject : this.representationSubject(registered);
    if (effective.availability !== 'available') return null;
    const districtFrame = this.ownedDistrict === null
      ? null
      : `${this.ownedDistrict.district.frame?.name ?? this.ownedDistrict.district.district_id}:render-metres`;
    const frame = known ?? (effective.subjectKind === 'object' && effective.frameId === districtFrame
      ? this.ownedDistrict!.root
      : null);
    if (effective.bounds === null || frame === null || effective.bounds.frameId !== effective.frameId) {
      return null;
    }
    return representationWorldBounds(effective.bounds as RepresentationBounds, frame);
  }

  setMemoryLayerVisible(visible: boolean): void {
    const changed = this.renderRoot.enabled !== visible;
    this.renderRoot.enabled = visible;
    if (!visible) { this.focusState = INITIAL_FOCUS_STATE; this.centred = null; }
    this.publishRepresentation();
    this.invalidate();
    // The control that owns this switch read the binding once, when it was built. Anything that
    // changed the layer afterwards left a checkbox saying the opposite of what the world showed.
    if (changed) this.onMemoryLayerChange?.(visible);
  }

  get memoryLayerVisible(): boolean {
    return this.renderRoot.enabled;
  }

  setWalkAssist(mode:'off'|'walk'|'run'):void {this.controls.setWalkAssist(mode);this.invalidate();}
  setCameraFraming(distance:number):void {this.playerCameraDistance=Math.max(.65,Math.min(6,distance));this.followCamera.reset();this.invalidate();}
  turnCamera(radians:number):void {if(!Number.isFinite(radians))return;this.controls.state.yaw+=radians;this.invalidate();}
  get cameraMode(): PlayerCameraMode { return this.playerCameraMode; }

  setCameraMode(mode: PlayerCameraMode): void {
    if (this.ownedDistrict === null) return;
    this.playerCameraMode = mode;
    this.followCamera.reset();
    this.playerAvatar ??= new PlayerAvatar(this.device, this.environmentRoot);
    const canvas = this.app.graphicsDevice.canvas;
    if (canvas instanceof HTMLCanvasElement) { canvas.dataset.cameraMode = mode; canvas.dispatchEvent(new Event('camera-mode-change')); }
    this.invalidate();
  }

  /** Reticle origin is the displayed camera; reach remains a separate player-space check. */
  interactionRay(): { origin: readonly [number, number, number]; direction: readonly [number, number, number] } {
    const position = this.camera.getPosition();
    const forward = this.camera.forward;
    return { origin: [position.x + this.renderOriginState.origin.x, position.y + this.renderOriginState.origin.y, position.z + this.renderOriginState.origin.z], direction: [forward.x, forward.y, forward.z] };
  }

  setCityView(view: 'overview' | 'street'): void {
    this.nativePlayerDiscontinuity=true;
    if (this.googleTiles === null && this.ownedDistrict === null) return;
    Object.assign(
      this.controls.state,
      this.ownedDistrict === null
        ? cityCameraState(view)
        : view === 'overview'
          ? ownedDistrictOverviewCameraState(this.ownedDistrict.district)
          : ownedDistrictCameraState(this.navigationWorld, this.ownedDistrict.district),
    );
    this.invalidate();
  }

  setTheme(theme: PresentationTheme): void {
    this.invalidate();
    this.motes.setTheme(theme);
    this.field.setTheme(theme);
    this.composedWorld.setTheme(theme);
    for (const visual of this.islands) visual.cloud.setTheme(theme);
    const selected = this.representation.report.selection;
    this.publishRepresentationReport(selected, this.representation.refresh());
  }

  setReducedMotion(reduced: boolean): void {
    this.reducedMotion = reduced;
    this.field.setReducedMotion(reduced);
    this.invalidate();
  }

  /**
   * Mark the next frame as needing to be drawn.
   *
   * Anything that changes what the world LOOKS like without moving the camera calls this: a
   * profile swap, a theme change, entering Map. Movement and travel are detected from the pose
   * itself, so they never need announcing.
   */
  invalidate(): void {
    this.dirty = true;
  }

  /** Whether this frame has to be drawn at all. The rule itself lives in `frame-policy`. */
  wantsFrame(nowMs: number): boolean {
    const s = this.controls.state;
    const r = this.renderedPose;
    return shouldDrawFrame({
      dirty: this.dirty || this.objects.animating || (this.ownedDistrict?.societyAnimating ?? false) || (this.playerCameraMode==='third-person' && !this.reducedMotion),
      navigating: this.navigationTransition !== null,
      poseChanged:
        s.x !== r.x || s.y !== r.y || s.z !== r.z ||
        s.yaw !== r.yaw || s.pitch !== r.pitch,
      reducedMotion: this.reducedMotion,
      sinceLastRenderMs: this.lastRenderMs < 0 ? -1 : nowMs - this.lastRenderMs,
    });
  }

  /** Called by the host immediately after it has drawn, to record what the screen now shows. */
  markRendered(nowMs: number): void {
    const s = this.controls.state;
    this.renderedPose.x = s.x;
    this.renderedPose.y = s.y;
    this.renderedPose.z = s.z;
    this.renderedPose.yaw = s.yaw;
    this.renderedPose.pitch = s.pitch;
    this.lastRenderMs = nowMs;
    this.dirty = false;
  }

  private setClearColours(profile: WorldArtProfile): void {
    const [skyR, skyG, skyB] = unitRgb(profile.palette.sky);
    this.skyClearColor.set(skyR, skyG, skyB, 1);
    const [groundR, groundG, groundB] = unitRgb(profile.palette.terrain);
    const [surfaceR, surfaceG, surfaceB] = unitRgb(profile.palette.terrainLift);
    this.mapClearColor.set(
      groundR * 0.72 + surfaceR * 0.28,
      groundG * 0.72 + surfaceG * 0.28,
      groundB * 0.72 + surfaceB * 0.28,
      1,
    );
  }

  private setProfileVisuals(profile: WorldArtProfile): void {
    this.invalidate();
    this.composedWorld.setProfile(profile);
    this.regionMass.applyProfile(profile);
    this.regionRelief.applyProfile(profile);
    this.field.setProfile(profile);
    this.objects.setProfile(profile);
    this.setClearColours(profile);
    if (this.camera.camera !== undefined && this.camera.camera !== null) {
      this.camera.camera.clearColor.copy(
        this.mapState === null ? this.skyClearColor : this.mapClearColor,
      );
    }
    const [hazeR, hazeG, hazeB] = unitRgb(profile.palette.haze);
    this.app.scene.ambientLight.set(hazeR * 0.58, hazeG * 0.58, hazeB * 0.58);
    this.app.scene.fog.color.set(hazeR, hazeG, hazeB);
    const [sunR, sunG, sunB] = unitRgb(profile.palette.sun);
    const light = (this.app.root.findByName('atlas-directional-light') as pc.Entity | null)?.light;
    if (light !== undefined && light !== null) light.color.set(sunR, sunG, sunB);
  }

  previewArtProfile(
    profile: WorldArtProfile,
    origin: WorldProposalOrigin,
    parameters?: WorldStyleParameters,
  ): WorldPreviewSession {
    this.styleProposalSequence += 1;
    const current = this.customization.current();
    const preview = this.customization.preview({
      proposalId: `${origin}-${this.styleProposalSequence}-${profile.profileId}`,
      origin,
      kind: 'appearance',
      scope: { kind: 'global' },
      baseStyleVersionId: current.versionId,
      baseTopologyDigest: this.topology.topologyDigest,
      profile: {
        profileId: profile.profileId,
        profileVersion: profile.profileVersion,
        ...(parameters === undefined ? {} : { parameters }),
      },
    });
    if (preview.validation.ok) this.setProfileVisuals(profile);
    return preview;
  }

  applyArtProfilePreview(sessionId: string): WorldStyleVersion {
    const applied = this.customization.apply(sessionId);
    this.setProfileVisuals(worldArtProfile(
      applied.global.profileId,
      applied.global.profileVersion,
      applied.global.parameters,
    ));
    const canvas = this.device.canvas;
    if (canvas instanceof HTMLCanvasElement) canvas.dataset.worldProfile = this.composedWorld.profileId;
    return applied;
  }

  discardArtProfilePreview(sessionId: string): void {
    this.customization.discard(sessionId);
    const current = this.customization.current();
    this.setProfileVisuals(worldArtProfile(
      current.global.profileId,
      current.global.profileVersion,
      current.global.parameters,
    ));
  }

  /** Settings convenience; Companion can hold the preview open and call apply/discard explicitly. */
  setArtProfile(
    profile: WorldArtProfile,
    origin: WorldProposalOrigin = 'settings',
    parameters?: WorldStyleParameters,
  ): WorldStyleVersion {
    const current = this.customization.current();
    const currentParameters = current.global.parameters ?? {};
    // Omitting parameters means "keep the current treatment" when the caller is already on this
    // profile. This preserves the pre-parameter API without manufacturing a duplicate version.
    const requestedParameters = parameters ?? (
      current.global.profileId === profile.profileId &&
      current.global.profileVersion === profile.profileVersion
        ? currentParameters
        : {}
    );
    const parameterKeys = new Set([...Object.keys(currentParameters), ...Object.keys(requestedParameters)]);
    const sameParameters = [...parameterKeys].every(
      (key) => currentParameters[key] === requestedParameters[key],
    );
    if (
      current.global.profileId === profile.profileId &&
      current.global.profileVersion === profile.profileVersion &&
      sameParameters
    ) return current;
    return this.applyArtProfilePreview(
      this.previewArtProfile(profile, origin, requestedParameters).sessionId,
    );
  }

  setFieldOfView(degrees: number): void {
    if (!Number.isFinite(degrees)) return;
    if (this.camera.camera !== undefined && this.camera.camera !== null) {
      this.camera.camera.fov = Math.max(60, Math.min(90, degrees));
    }
  }

  setSensitivityMultiplier(multiplier: number): void {
    this.controls.setSensitivityMultiplier(multiplier);
  }

  /**
   * The proof lens: colour each region by what produced the surface a visitor is looking at.
   *
   * `null` switches it off. Otherwise the map carries one already-resolved RGBA per island, and an
   * island the map omits is left uncoloured rather than being given a default, because a default
   * would be this package inventing an answer about provenance.
   *
   * THIS METHOD RESOLVES NOTHING AND DECIDES NOTHING. It writes four floats per island into a
   * uniform. The tier, the palette and the words that name each tier all live in
   * `@exulanica/presentation`, which is why the legend in the status panel and the colour in the
   * world cannot drift apart: they are the same four numbers read twice.
   *
   * IT ALSO CHANGES NOTHING ELSE. No scene is replaced, no residency plan is recomputed, no tier
   * or rung is touched, and no receipt is read: the only state this writes is `IslandVisual.uLens`
   * and the equivalent parameter on a trained scene. Switching the lens on and off is meant to be
   * exactly as consequential as looking at something differently, and this is where that is true.
   */
  setProofLens(colors: ReadonlyMap<IslandId, ProofLensColor> | null): void {
    for (const visual of this.islands) {
      const color = colors?.get(visual.island.islandId);
      visual.uLens.set(color ?? PROOF_LENS_OFF);
    }
    for (const visual of this.trainedScenes) {
      const color = colors?.get(visual.island.islandId) ?? PROOF_LENS_OFF;
      const gsplat = visual.entity.gsplat;
      if (gsplat === undefined || gsplat === null) continue;
      if (!this.proofLensSplatsPrepared.has(visual.entity)) {
        // Installed on the first use and never removed. Installing it at construction would put a
        // modified shader on the default path, where a compile failure would cost the trained
        // scene itself rather than only the lens; installing and removing it per toggle would
        // rebuild the shader twice for a value that is a uniform.
        //
        // A scene the segment overlay covers already carries a modifier with the lens inside it,
        // and replacing that would drop the segments. The overlay restores the lens's own modifier
        // when it leaves, because this set now says the lens was here.
        if (!this.segmentOverlay.covers(visual.entity)) gsplat.setWorkBufferModifier(PROOF_LENS_SPLAT_MODIFIER);
        this.proofLensSplatsPrepared.add(visual.entity);
      }
      gsplat.setParameter('uProofLens', [...color]);
      /*
       * THE WORK BUFFER IS HELD OPEN FOR A FEW FRAMES, NOT FOR ONE, AND MEASURED IS WHY.
       *
       * `WORKBUFFER_UPDATE_ONCE` asks for exactly one refill on the next frame, which is what this
       * did first. On the real trained bowl on 2026-09-06 the tint then took several seconds to
       * appear and sometimes did not appear at all before something else moved: this application
       * runs with `autoRender` off and draws only the frames `wantsFrame` asks for, so a single
       * requested refill can land on a frame the host never renders and is simply lost.
       *
       * ALWAYS for a bounded settle and then back to AUTO. The cost is a handful of work-buffer
       * renders per press of a button rather than one per frame for as long as the lens is open,
       * and the lens is visible in the frame after the press rather than whenever the scene next
       * happens to move.
       */
      gsplat.workBufferUpdate = pc.WORKBUFFER_UPDATE_ALWAYS;
    }
    this.proofLensSettleUntil = this.elapsed + PROOF_LENS_SETTLE_SECONDS;
    this.invalidate();
  }

  /** Close the settle window opened by `setProofLens`, once the tint is in the work buffer. */
  private settleProofLens(): void {
    if (this.proofLensSettleUntil < 0) return;
    if (this.elapsed < this.proofLensSettleUntil) {
      // Every settle frame has to be a DRAWN frame, or the window would run out against frames the
      // host skipped and the work buffer would never be refilled at all.
      this.invalidate();
      return;
    }
    this.proofLensSettleUntil = -1;
    for (const visual of this.trainedScenes) {
      const gsplat = visual.entity.gsplat;
      if (gsplat === undefined || gsplat === null) continue;
      gsplat.workBufferUpdate = pc.WORKBUFFER_UPDATE_AUTO;
    }
    this.invalidate();
  }

  /** Compose application surfaces with Map and travel locks so one cannot re-enable another. */
  setControlsEnabled(enabled: boolean): void {
    this.applicationControlsEnabled = enabled;
    this.refreshControlsEnabled();
  }

  /**
   * Keep walking available while a surface owns the cursor and pointer lock is suspended.
   *
   * Any surface that needs a free cursor releases the lock, and releasing the lock used to end
   * movement as a side effect: opening a panel parked you. Walking and pointing are separable,
   * so a surface that takes the cursor opts back into movement here rather than stranding it.
   * Look still requires the lock, because look IS the lock.
   */
  setFreeCursorActive(active: boolean): void {
    this.controls.setConversationActive(active);
  }

  private refreshControlsEnabled(): void {
    this.controls.setEnabled(
      this.applicationControlsEnabled &&
      this.mapState === null &&
      this.navigationTransition === null &&
      this.inspection === null,
    );
  }

  /** Repeatable photographed and interpolated cameras over verified, currently resident inputs. */
  inspectionViews(sceneId: string): readonly SceneInspectionView[] {
    const maps = this.islands.filter((visual) => visual.pointMap.sceneId === sceneId);
    const island = maps[0]?.island ?? this.trainedScenes.find((visual) => visual.geometry.sceneId === sceneId)?.island;
    return island === undefined ? [] : sceneInspectionViews(island, maps.map((visual) => visual.pointMap),
      this.recoveredCameras.filter((camera) => camera.sceneId === sceneId));
  }

  get inspectionView(): SceneInspectionView | null { return this.inspection?.view ?? null; }

  inspectSceneView(sceneId: string, viewId: string): boolean {
    const view = this.inspectionViews(sceneId).find((candidate) => candidate.id === viewId);
    if (view === undefined) return false;
    this.cancelDirectNavigation();
    if (this.mapState !== null) this.setMapMode(false);
    if (this.inspection === null) {
      this.inspection = { returnPose: this.navigationPose(), returnFov: this.camera.camera?.fov ?? 70,
        returnProjection: this.camera.camera!.calculateProjection, view };
    } else this.inspection.view = view;
    if (document.pointerLockElement === this.device.canvas) document.exitPointerLock();
    const [x, y, z] = view.position;
    const [fx, fy, fz] = view.forward;
    Object.assign(this.controls.state, {
      x, y, z,
      yaw: Math.atan2(-fx, -fz),
      pitch: Math.atan2(fy, Math.hypot(fx, fz)),
    });
    if (this.camera.camera !== undefined && this.camera.camera !== null) {
      const camera = this.camera.camera;
      camera.fov = view.fovYDeg;
      const calibration = view.calibration;
      camera.calculateProjection = (matrix: pc.Mat4) => {
        if (calibration === null) {
          matrix.setPerspective(camera.fov, camera.aspectRatio, camera.nearClip, camera.farClip, camera.horizontalFov);
          return;
        }
        const frustum = calibratedCameraFrustum(calibration, camera.aspectRatio, camera.nearClip);
        matrix.setFrustum(frustum.left, frustum.right, frustum.bottom, frustum.top, camera.nearClip, camera.farClip);
      };
    }
    this.navigationTargetIsland = view.islandId;
    this.refreshControlsEnabled();
    this.applyResidencyPresentation();
    this.invalidate();
    this.onInspectionChange?.(view);
    return true;
  }

  /** Restore the complete ground pose; inspection never validates or changes walking geometry. */
  endSceneInspection(): void {
    const held = this.inspection;
    if (held === null) return;
    this.inspection = null;
    this.applyNavigationPose(held.returnPose);
    if (this.camera.camera !== undefined && this.camera.camera !== null) {
      this.camera.camera.fov = held.returnFov;
      this.camera.camera.calculateProjection = held.returnProjection;
    }
    this.navigationTargetIsland = null;
    this.refreshControlsEnabled();
    this.applyResidencyPresentation();
    this.invalidate();
    this.onInspectionChange?.(null);
  }

  /** The map is the same live scene from a high camera pose; no scene is loaded or replaced. */
  setMapMode(active: boolean): void {
    if (active) this.endSceneInspection();
    this.invalidate();
    if (active === (this.mapState !== null)) return;
    this.composedWorld.setMapActive(active);
    this.regionMass.setMapActive(active);
    this.regionRelief.setMapActive(active);
    if (this.camera.camera !== undefined && this.camera.camera !== null) {
      this.camera.camera.clearColor.copy(active ? this.mapClearColor : this.skyClearColor);
    }
    if (active) {
      this.cancelDirectNavigation();
      const s = this.controls.state;
      this.mapState = enterAtlasMap(this.scene, {
        position: atlasVec3(s.x, s.y, s.z),
        yaw: s.yaw,
        pitch: s.pitch,
      });
      const activePose = this.mapState.active;
      Object.assign(this.controls.state, {
        x: activePose.position.x,
        y: activePose.position.y,
        z: activePose.position.z,
        yaw: activePose.yaw,
        pitch: activePose.pitch,
      });
      this.field.setMapGroundPose(this.mapState.ground);
      if (this.overlay !== null) this.overlay.root.hidden = true;
      this.mapOverlay?.setActive(true);
      this.refreshPresentIslands(true);
      this.refreshControlsEnabled();
      return;
    }
    if (this.mapState !== null) {
      const ground = exitAtlasMap(this.mapState);
      Object.assign(this.controls.state, {
        x: ground.position.x,
        y: ground.position.y,
        z: ground.position.z,
        yaw: ground.yaw,
        pitch: ground.pitch,
      });
    }
    this.mapState = null;
    this.field.setMapGroundPose(null);
    if (this.overlay !== null) this.overlay.root.hidden = false;
    this.mapOverlay?.setActive(false);
      this.refreshPresentIslands(false);
    this.refreshControlsEnabled();
  }

  /** Resolve and begin one safe direct-navigation transition. No target means no camera change. */
  navigate(
    target: DirectNavigationTarget,
    reducedMotion = false,
  ): DirectNavigationResolution {
    const state = this.inspection?.returnPose ?? this.mapState?.ground ?? this.navigationPose();
    const resolution = resolveDirectNavigation(
      this.scene,
      this.navigationWorld,
      target,
      state.position,
    );
    if (!resolution.ok) return resolution;
    this.endSceneInspection();
    // Travelling to a memory is a request to see it. Over an owned district the memory layer starts
    // off, so without this the whole journey ends standing in the street facing geometry that is
    // switched off, which reads as travel being broken rather than as a layer being hidden.
    // `setMemoryLayerVisible` announces the change so the control that owns the switch follows it.
    if (!this.memoryLayerVisible) this.setMemoryLayerVisible(true);
    if (this.mapState !== null) this.setMapMode(false);
    const planned = planDirectNavigationTransition(resolution, state, reducedMotion);
    // atlas-core already aims the arrival at the region itself. The previous override tilted the
    // camera up at the source veil hanging above it; with no body in the air there is nothing to
    // look up at, and the region's own landmark is what the arrival should face.
    this.navigationTransition = planned;
    this.navigationElapsedMs = 0;
    this.navigationTargetIsland = resolution.islandId;
    this.refreshControlsEnabled();
    if (this.navigationTransition.durationMs === 0) this.advanceDirectNavigation(0);
    return resolution;
  }

  navigateToAnchor(anchorId: AnchorId, reducedMotion = false): DirectNavigationResolution {
    return this.navigate({ kind: 'anchor', anchorId }, reducedMotion);
  }

  navigateToIsland(islandId: IslandId, reducedMotion = false): DirectNavigationResolution {
    return this.navigate({ kind: 'island', islandId }, reducedMotion);
  }

  cancelDirectNavigation(): void {
    if (this.navigationTransition === null) return;
    this.navigationTransition = null;
    this.navigationTargetIsland = null;
    this.navigationElapsedMs = 0;
    this.refreshControlsEnabled();
  }

  /**
   * Verify that the engine's world transform reproduces atlas-core's `localToAtlas` exactly.
   *
   * Worth doing once at startup rather than trusting a convention comment. An island turned the
   * wrong way is a hole, because a 2.5D shell has observed surfaces on one side only, and a sign
   * error in a yaw is not visible until someone walks round the back.
   */
  verifyPlacements(): PlacementCheck[] {
    const probes = [
      localVec3(1, 0, 0),
      localVec3(0, 0, -1),
      localVec3(3.5, 1.2, -7.25),
    ];
    const out: PlacementCheck[] = [];
    const v = new pc.Vec3();
    for (const visual of this.islands) {
      let worst = 0;
      for (const probe of probes) {
        const scenePoint = opmPointInScene(
          visual.pointMap,
          [probe.x, probe.y, probe.z],
        );
        const expected = localToAtlas(
          visual.island.placement,
          localVec3(scenePoint[0], scenePoint[1], scenePoint[2]),
        );
        v.set(probe.x, probe.y, probe.z);
        visual.entity.getWorldTransform().transformPoint(v, v);
        worst = Math.max(worst, Math.hypot(
          v.x + this.renderOriginState.origin.x - expected.x,
          v.y + this.renderOriginState.origin.y - expected.y,
          v.z + this.renderOriginState.origin.z - expected.z,
        ));
      }
      out.push({ islandId: visual.island.islandId, maxErrorMetres: worst });
    }
    return out;
  }

  /** Apply a view manifest. One tight numeric loop, no scene-graph mutation, safe on every hover. */
  applyManifest(manifest: ViewManifest): void {
    applyViewManifestInto(this.table, manifest, this.emphasis, this.scene.stateVersion);
  }

  /** Reset to the neutral frame: nothing emphasised, nothing muted. */
  clearManifest(): void {
    const neutral = neutralEmphasis(this.table);
    this.emphasis.anchorEmphasis.set(neutral.anchorEmphasis);
    this.emphasis.anchorLevel.set(neutral.anchorLevel);
    this.emphasis.anchorInteractable.set(neutral.anchorInteractable);
    this.emphasis.anchorLabelable.set(neutral.anchorLabelable);
    this.emphasis.islandEmphasis.set(neutral.islandEmphasis);
    this.emphasis.islandLevel.set(neutral.islandLevel);
  }

  /**
   * Put focus on one anchor, because something outside the world pointed at it.
   *
   * interaction-model.md 5.2: "Clicking an evidence chip does not leave the Atlas. It opens the
   * source image inline, docked to the panel, AND SIMULTANEOUSLY THE CORRESPONDING ANCHOR IN THE
   * WORLD PULSES. The written claim and the spatial world point at the same evidence at the same
   * time. That simultaneity is the product's central promise made visible in one gesture."
   *
   * The aim solver cannot express that, because the camera is not aiming at anything: the user
   * clicked a citation in a panel. So this is a direct set through atlas-core's `focusDirectly`
   * rather than a second focus rule written here. It is deliberately NOT a latch: the next frame
   * of aim resolution takes focus back, which is correct, because the pulse marks a moment and
   * does not seize the user's attention until they dismiss it.
   *
   * An index outside the table is ignored rather than throwing. The caller is translating an
   * anchor id it received from the graph, and an id the current scene does not contain means the
   * graph moved under the panel, which is a stale view rather than a fault.
   */
  focusAnchor(index: number, nowMs: number = performance.now()): void {
    if (!Number.isInteger(index) || index < 0 || index >= this.table.count) return;
    this.focusState = focusDirectly(this.focusState, index, nowMs);
  }

  /**
   * The photograph whose print the reticle is on, for a map drawn in an unmeasured arrangement, or
   * null. The reticle's ray is met with the print's plane, from in front of it and within the same
   * interaction radius an anchor has; seen from its camera that is exactly the photograph's own
   * pixel, and from anywhere else it is the print the relief flattens into.
   */
  get centredPhotograph(): CentredPhotograph | null {
    return this.centred;
  }

  private findCentredPhotograph(): CentredPhotograph | null {
    const eye = this.camera.getPosition();
    const forward = this.camera.forward;
    let best: CentredPhotograph | null = null;
    let bestScore = 1 - SINGLE_VIEW_EDGE_MARGIN;
    for (const visual of this.islands) {
      const camera = visual.singleViewLocal;
      const print = visual.printLocal;
      const captureId = visual.pointMap.captureId;
      if (camera === null || print === null || captureId === undefined || !visual.entity.enabled) continue;
      const world = visual.entity.getWorldTransform();
      this.centredInverse.copy(world).invert();
      this.centredInverse.transformPoint(eye, this.centredCapture);
      this.centredInverse.transformVector(forward, this.centredDirection).normalize();
      // The print's plane is z = print.z in the camera's own frame, and the camera looks along -z.
      if (this.centredCapture.z <= print.z || this.centredDirection.z >= 0) continue;
      const along = (print.z - this.centredCapture.z) / this.centredDirection.z;
      const hitX = this.centredCapture.x + this.centredDirection.x * along - camera.x;
      const hitY = this.centredCapture.y + this.centredDirection.y * along - camera.y;
      const hitZ = print.z - camera.z;
      // Reachable from where the visitor stands, by the same radius that decides an anchor.
      world.transformPoint(SINGLE_VIEW_SCRATCH.set(hitX + camera.x, hitY + camera.y, print.z), SINGLE_VIEW_PRINT);
      if (SINGLE_VIEW_PRINT.distance(eye) > DEFAULT_FOCUS_CONFIG.interactRadius) continue;
      const score = frameFraction([hitX, hitY, hitZ], visual.pointMap.map.header.viewpoint);
      if (score !== null && score < bestScore) {
        bestScore = score;
        best = { sceneId: visual.pointMap.sceneId, captureId, islandId: visual.island.islandId };
      }
    }
    return best;
  }

  /**
   * The region the visitor is standing inside, or null.
   *
   * The landmark is what marks a memory in the world now that nothing else does, and a landmark is
   * geometry with no identity of its own: it carries no anchor, so the reticle cannot settle on it
   * the way it settles on an occurrence. Spatial phase already knows which region holds the camera,
   * and that is the same answer without inventing a picking surface for a beacon.
   */
  get occupiedRegion(): IslandId | null {
    return this.occupied;
  }

  /** Engage exactly the one settled reticle target. The application decides which panel opens. */
  engageFocusedAnchor(): number | null {
    if (!this.memoryLayerVisible || this.controls.mode !== 'traverse' || this.focusState.focusedIndex === null) return null;
    const index = this.focusState.focusedIndex;
    this.focusState = latchFocus(this.focusState);
    return index;
  }

  /** Mirror of what source-first-grove and the island visuals were just told to draw. */
  private refreshPresentIslands(map: boolean): void {
    this.presentIslands.clear();
    if (map) return;
    for (const [islandId, stage] of this.residencyAllocated) {
      if (stage !== 'stub') this.presentIslands.add(islandId);
    }
  }

  /** Called when the evidence surface gives control back to traversal. */
  releaseFocusedAnchor(): void {
    this.focusState = releaseFocus(this.focusState);
  }

  playerPose(): CameraPose {
    const s = this.controls.state;
    return { position: atlasVec3(s.x, s.y, s.z), forward: this.controls.forward() };
  }

  cameraPose(): CameraPose {
    const ray = this.interactionRay();
    return { position: atlasVec3(...ray.origin), forward: atlasVec3(...ray.direction) };
  }

  private navigationPose(): NavigationPose {
    const s = this.controls.state;
    return Object.freeze({ position: atlasVec3(s.x, s.y, s.z), yaw: s.yaw, pitch: s.pitch });
  }

  private applyNavigationPose(pose: NavigationPose): void {
    Object.assign(this.controls.state, {
      x: pose.position.x,
      y: pose.position.y,
      z: pose.position.z,
      yaw: pose.yaw,
      pitch: pose.pitch,
    });
  }

  private advanceDirectNavigation(dtMs: number): void {
    const transition = this.navigationTransition;
    if (transition === null) return;
    this.navigationElapsedMs += dtMs;
    this.applyNavigationPose(sampleDirectNavigationTransition(transition, this.navigationElapsedMs));
    if (this.navigationElapsedMs < transition.durationMs) return;
    this.applyNavigationPose(transition.to);
    this.navigationTransition = null;
    this.navigationTargetIsland = null;
    this.navigationElapsedMs = 0;
    this.refreshControlsEnabled();
    this.onNavigationArrive?.(transition.target);
  }

  private syncNativeCharacterFrames(dt:number,navigating=false):void{
    if(!this.nativeCharacters)return;
    const frames=[...(this.ownedDistrict?.nativeCharacterFrames(dt,this.reducedMotion)??[])];
    if(this.playerAvatar){
      const avatar=this.playerAvatar,s=this.controls.state;
      frames.push({subject:avatar.representation.subject,parent:this.environmentRoot,fallback:avatar.root,
        visible:this.playerDrawn&&avatar.representation.availability!=='hidden',
        position:[s.x,s.y-this.navigationWorld.eyeHeight,s.z],yaw:avatar.facing,
        deltaSeconds:dt,reducedMotion:this.reducedMotion,discontinuity:this.nativePlayerDiscontinuity||navigating});
    }
    this.nativeCharacters.syncFrames(frames);this.nativePlayerDiscontinuity=false;
  }

  /**
   * One frame of Atlas logic. Called from the engine's update, before it renders.
   *
   * The order matters and is the same order the interaction model describes: move, decide
   * representation density, decide attention, then draw the overlay from those decisions. The
   * overlay never decides anything.
   */
  update(dt: number, nowMs: number): void {
    this.elapsed += dt;
    if (document.visibilityState !== 'hidden' && Number.isFinite(dt) && dt > 0) {
      const pressure = this.representationPressure.record({ frameTimeMs: dt * 1000 });
      if (pressure.changed) this.residencySignature = '';
    }
    const navigating = this.navigationTransition !== null;
    if (navigating) this.advanceDirectNavigation(dt * 1000);
    else if (this.inspection === null) this.controls.update(dt);
    this.ownedDistrict?.refreshNearby([this.controls.state.x, this.controls.state.z]);
    this.ownedDistrict?.tickSociety(this.reducedMotion ? Number.MAX_SAFE_INTEGER : nowMs);
    if (this.ownedDistrict && Math.floor(nowMs / 1000) !== Math.floor((nowMs - dt * 1000) / 1000)) {
      const canvas = this.device.canvas;
      if (canvas instanceof HTMLCanvasElement) {
        canvas.dataset.ownedGeometryBytes = String(this.ownedDistrict.geometryResidentBytes+(this.playerAvatar?.residentBytes??0));
        canvas.dataset.characterTextureBytes=String(this.ownedDistrict.characterTextureBytes+(this.playerAvatar?.textureResidentBytes??0));
        canvas.dataset.actualDrawCalls = String(this.app.stats.drawCalls.total);
        canvas.dataset.playerPosition = JSON.stringify([this.controls.state.x, this.controls.state.y, this.controls.state.z]);
        canvas.dataset.displayCameraPosition = JSON.stringify(this.camera.getPosition().toArray());
        canvas.dataset.societyRendered = String(this.ownedDistrict.drawnInhabitantCount);
        canvas.dataset.societyNearby=String(this.ownedDistrict.visibleInhabitantIds.length);
        const signature=this.ownedDistrict.visibleInhabitantIds.join('|');
        if(signature!==this.nearbySignature){this.nearbySignature=signature;canvas.dispatchEvent(new Event('society-nearby-change'));}
      }
    }

    const s = this.controls.state;
    const previous = this.lastPlayerPosition ?? [s.x, s.z];
    this.playerAvatar?.update(s, s.x - previous[0]!, s.z - previous[1]!, dt,
      this.playerDrawn, this.reducedMotion,
      s.y - this.navigationWorld.eyeHeight, this.controls.movementHeading);
    this.lastPlayerPosition = [s.x, s.z];
    this.syncNativeCharacterFrames(dt,navigating);
    // Look at the body that is actually drawn, not at a fixed offset from the eye line.
    const groundY = s.y - this.navigationWorld.eyeHeight;
    const standingHeight = (this.playerAvatar?.body.heightMm ?? 1820) / 1000;
    const cameraPosition = this.inspection === null
      ? this.followCamera.solve(s, this.playerCameraMode, {
        ...(this.ownedDistrict?.district === undefined ? {} : { district: this.ownedDistrict.district }),
        requestedDistance: this.playerCameraDistance,
        aimHeight: playerCameraAimHeight(groundY, standingHeight, this.playerCameraDistance),
        dt,
        reducedMotion: this.reducedMotion,
      })
      : [s.x, s.y, s.z];
    this.pose.position.set(
      cameraPosition[0]! - this.renderOriginState.origin.x,
      cameraPosition[1]! - this.renderOriginState.origin.y,
      cameraPosition[2]! - this.renderOriginState.origin.z,
    );
    this.camera.setPosition(this.pose.position);
    this.qYaw.setFromAxisAngle(pc.Vec3.UP, (s.yaw * 180) / Math.PI);
    this.qPitch.setFromAxisAngle(pc.Vec3.RIGHT, (s.pitch * 180) / Math.PI);
    this.pose.rotation.mul2(this.qYaw, this.qPitch);
    if (this.inspection === null) this.camera.setRotation(this.pose.rotation);
    else {
      const view = this.inspection.view;
      this.inspectionTarget.set(
        this.pose.position.x + view.forward[0],
        this.pose.position.y + view.forward[1],
        this.pose.position.z + view.forward[2],
      );
      this.inspectionUp.set(...view.up);
      this.inspectionMatrix.setLookAt(this.pose.position, this.inspectionTarget, this.inspectionUp);
      this.pose.rotation.setFromMat4(this.inspectionMatrix);
      this.camera.setRotation(this.pose.rotation);
    }

    const cameraAtlas = atlasVec3(s.x, s.y, s.z);
    this.tierState =
      this.mapState === null
        ? resolveTiers(this.scene, this.table, cameraAtlas, this.tierState)
        : mapTierState(this.scene);

    const spatial = classifySpatialPhase(this.navigationWorld, cameraAtlas);
    /*
     * Standing IN the memory, not merely near it.
     *
     * `approaching` reaches 24 metres past the footprint, which over a district is most of a city
     * block and would hand every interact key in that radius to a memory. Inside the footprint is
     * the honest reading of "standing at it", and it is also where the landmark is.
     */
    this.occupied = spatial.phase === 'inside' || spatial.phase === 'dissolve' ? spatial.islandId : null;
    this.activeNeighborhood =
      spatial.islandId === null
        ? (this.activeNeighborhood ?? this.neighborhoodIndex.neighborhoods[0]?.neighborhoodId ?? null)
        : (this.neighborhoodIndex.neighborhoodOf.get(spatial.islandId) ?? this.activeNeighborhood);
    const nextOrigin = renderOriginForNeighborhood(
      this.scene,
      this.neighborhoodIndex,
      this.activeNeighborhood,
      this.renderOriginState,
    );
    if (nextOrigin !== this.renderOriginState) {
      this.renderOriginState = nextOrigin;
      const origin = nextOrigin.origin;
      this.renderRoot.setPosition(-origin.x, -origin.y, -origin.z);
      this.environmentRoot.setPosition(-origin.x, -origin.y, -origin.z);
      this.field.setRenderOrigin(origin.x, origin.z);
      this.pose.position.set(cameraPosition[0]! - origin.x, cameraPosition[1]! - origin.y, cameraPosition[2]! - origin.z);
      this.camera.setPosition(this.pose.position);
    }
    const { view: residencyView, signature } = residencyFrameInputs({
      map: this.mapState !== null,
      activeNeighborhood: this.activeNeighborhood,
      tier: this.tierState,
      target: this.navigationTargetIsland,
      occupied: spatial.islandId,
    });
    if (signature !== this.residencySignature) {
      this.residencySignature = signature;
      const plan = planResidency(
        this.residencyCatalog,
        residencyDemandsForView(this.neighborhoodIndex, residencyView),
        {
          maxCost: this.residencyBudget * this.representationPressure.state.budgetScale,
          maxStage: this.representationPressure.state.maxStage,
        },
        this.residencyState,
      );
      this.residencyState = plan.state;
      // Install pending ids before handing actions to an executor: an honest missing/unsupported
      // descriptor may settle synchronously, and settling against the previous state would leave
      // the later request pending forever.
      this.onResidencyActions?.(plan.actions);
      if (this.onResidencyActions === null) {
        // Predecoded fixture mode has no I/O to await. Production installs a physical executor
        // and settles only after checked fetch, decode, upload, and publication.
        for (const action of plan.actions) {
          if (action.type === 'load') {
            this.residencyState = completeResidencyRequest(
              this.residencyState,
              action.request.requestId,
              true,
            );
          }
        }
      }
      this.residencyAllocated = new Map(
        [...this.residencyState.entries].map(([id, entry]) => [id, entry.current]),
      );
      this.applyResidencyPresentation();
      this.invalidate();
    }

    // Representation density, as one uniform write per island. No material swap, no scene-graph
    // mutation: that is the performance contract, and it is what makes emphasis previewable on
    // every hover.
    const projScale =
      this.device.height / (2 * Math.tan(((this.camera.camera?.fov ?? 70) * Math.PI) / 360));

    for (let i = 0; i < this.islands.length; i += 1) {
      const visual = this.islands[i]!;
      const tier = this.tierState.tier.get(visual.island.islandId) ?? 0;
      const islandIndex = this.table.islandIndexOf.get(visual.island.islandId);
      const emphasis =
        islandIndex === undefined ? 1 : (this.emphasis.islandEmphasis[islandIndex] ?? 1);

      // Tier is representation DENSITY, never scene identity. A tier 0 island is still in the
      // scene and still emphasised; it just carries less of itself.
      const tierDensity = tier === 3 ? 1 : tier === 2 ? 0.7 : tier === 1 ? 0.35 : 0.12;
      const residency = this.residencyAllocated.get(visual.island.islandId) ?? 'stub';
      const residencyDensity =
        residency === 'full' ? 1 : residency === 'coarse' ? 0.7 : residency === 'proxy' ? 0.35 : 0;
      // Inspection compares the complete loaded reconstruction at identical cameras. It must
      // not silently thin samples because a previous view lowered the residency budget.
      const density = visual.island.islandId === this.inspection?.view.islandId
        ? 1 : Math.min(tierDensity, residencyDensity);

      visual.uIsland[0] = visual.island.islandId === this.inspection?.view.islandId
        ? 1 : Math.max(0.001, emphasis / 0.45) * density;
      visual.uPoint[2] = projScale;
      visual.uPoint[3] = this.elapsed;
      visual.cloud.material.setParameter('uIsland', visual.uIsland);
      visual.cloud.material.setParameter('uPoint', visual.uPoint);
      // The proof lens rides the same per-frame write, so it costs one more `setParameter` on a
      // path that already does two and never allocates. Its contents were resolved by the caller
      // in `setProofLens`; this loop only delivers them.
      visual.cloud.material.setParameter('uLens', visual.uLens);
      if (visual.singleViewLocal !== null && visual.printLocal !== null) {
        const world = visual.entity.getWorldTransform();
        world.transformPoint(visual.singleViewLocal, SINGLE_VIEW_SCRATCH);
        world.transformPoint(visual.printLocal, SINGLE_VIEW_PRINT);
        visual.cloud.setCaptureWorld(SINGLE_VIEW_SCRATCH.x, SINGLE_VIEW_SCRATCH.y, SINGLE_VIEW_SCRATCH.z);
        const relief = reliefFor(SINGLE_VIEW_SCRATCH, SINGLE_VIEW_PRINT, this.camera.getPosition(), visual.parallaxPerUnit);
        visual.cloud.setRelief(relief.flatten, relief.behind);
      }
    }
    // The placed estimates flatten against the same camera, on the same frame, through the same
    // relief rule the scene path uses. Nothing else about them moves: they are drawn and that is
    // all, so there is no residency, no emphasis and no lens to deliver.
    this.authoredPointMaps?.frame(this.camera.getPosition());
    this.objects.update(dt);
    this.settleProofLens();

    // The motes read the same emphasis buffer the manifest writes and the same projection scale
    // the shells use, so a recomposition moves both in one frame rather than in two.
    this.motes.uMote[2] = projScale;
    this.motes.material.setParameter('uMote', this.motes.uMote);
    this.motes.update(this.emphasis);

    const resolution = resolveFocus(
      {
        table: this.table,
        emphasis: this.emphasis,
        camera: this.cameraPose(),
        nowMs,
        occurrenceNormalizer: this.normalizer,
        visible: (from, to) => isNavigationLineVisible(this.navigationWorld, from, to),
      },
      this.focusState,
    );
    this.focusState = this.memoryLayerVisible ? resolution.state : INITIAL_FOCUS_STATE;
    this.field.update(nowMs);

    this.centred = this.memoryLayerVisible && this.controls.mode === 'traverse' ? this.findCentredPhotograph() : null;
    const tileForward = this.controls.forward();
    this.googleTiles?.update(
      [s.x, s.y, s.z],
      Math.max(1, this.device.height),
      this.camera.camera?.fov ?? 70,
      [tileForward.x, tileForward.y, tileForward.z],
    );
    const memoryOverlayVisible = this.memoryLayerVisible || this.mapState !== null || this.inspection !== null;
    if (this.overlay) this.overlay.root.hidden = !memoryOverlayVisible;
    const cameraComponent = this.camera.camera;
    if (this.overlay !== null && cameraComponent !== undefined && cameraComponent !== null) {
      this.overlay.update({
        photographPrompt: this.centred !== null,
        memoryPrompt: this.occupied !== null,
        table: this.table,
        emphasis: this.emphasis,
        camera: cameraComponent,
        cameraPosition: cameraAtlas,
        traversalActive: this.controls.mode === 'traverse',
        candidateIndex: this.controls.mode === 'traverse' ? (resolution.best?.index ?? null) : null,
        presentIslands: this.presentIslands,
        focusedDistance:
          this.controls.mode === 'traverse' &&
          resolution.focused !== null &&
          resolution.best?.index === resolution.focused.index
            ? resolution.focused.distance
            : null,
        // Conversation mode is for reading chrome, not for showing whatever happens to sit under
        // the dormant reticle. Focus copy enters only after the person clicks into the world.
        focusedIndex: this.controls.mode === 'traverse' ? this.focusState.focusedIndex : null,
        widthCss: this.device.canvas.clientWidth,
        heightCss: this.device.canvas.clientHeight,
        capturedAt: this.scene.islands[0]?.createdAt ?? Date.now(),
        renderOrigin: [
          this.renderOriginState.origin.x,
          this.renderOriginState.origin.y,
          this.renderOriginState.origin.z,
        ],
      });
      if (this.mapState !== null) {
        this.mapOverlay?.update(
          cameraComponent,
          this.device.canvas.clientWidth,
          this.device.canvas.clientHeight,
          [
            this.renderOriginState.origin.x,
            this.renderOriginState.origin.y,
            this.renderOriginState.origin.z,
          ],
        );
      }
    }

    this.onFrame?.({
      dt,
      mode: this.controls.mode,
      tier: this.tierState,
      focusedIndex: this.focusState.focusedIndex,
      moving: this.controls.movementSpeed > 0.08,
      spatial,
      residency: this.residencyState,
      activeNeighborhood: this.activeNeighborhood,
      navigating,
      recoveryReason: this.controls.consumeRecoveryReason(),
      representationPressure: this.representationPressure.state,
      renderOrigin: this.renderOriginState,
    });
  }

  destroy(): void {
    const canvas = this.device.canvas;
    if (canvas instanceof HTMLCanvasElement) {
      for (const key of ['cameraMode','ownedGeometryBytes','characterTextureBytes','actualDrawCalls','playerPosition','displayCameraPosition','societyRendered','societyNearby']) delete canvas.dataset[key];
    }
    // Authored objects own borrowed representation handles. Release them while the registry is
    // live so points, cloned materials and selection are restored through the ordinary path.
    this.objects.destroy();
    this.authoredPointMaps?.destroy();
    this.authoredPointMaps = null;
    this.representationSelectionObservers.clear();
    this.representation.destroy();
    this.nativeCharacters?.destroy();
    this.playerAvatar?.destroy();
    this.ownedDistrict?.destroy();
    this.generatedTile?.dispose();
    this.generatedTile = null;
    this.googleTiles?.dispose();
    this.googleTiles = null;
    this.controls.destroy();
    this.overlay?.destroy();
    this.mapOverlay?.destroy();
    this.motes.destroy();
    this.field.destroy();
    this.composedWorld.destroy();
    this.regionMass.destroy();
    this.regionRelief.destroy();
    this.segmentOverlay.destroy();
    for (const visual of this.islands) visual.cloud.destroy();
    for (const visual of this.trainedScenes) {
      visual.entity.destroy();
      visual.asset.unload();
      this.app.assets.remove(visual.asset);
    }
    this.app.destroy();
  }
}

/**
 * Where a session opens.
 *
 * The upward framing is gone with the body it framed. This used to pitch the opening camera up at
 * the source veil hanging 3.45 metres over the region, which is the one thing that made an opening
 * shot point at empty air once the veil was removed. A region now opens level, looking at its own
 * ground, where its landmark stands.
 */
export function initialAtlasCameraState(
  scene: AtlasScene,
  navigationWorld: NavigationWorld,
): CameraState {
  const first = scene.islands[0];
  if (first !== undefined && first.rung !== 4 && first.viewpointForwardLocal !== undefined) {
    // A reconstructed region arrives where its first photograph was taken, looking where that
    // camera looked. The display frame put the recovered cameras at eye height, so this is a
    // standing viewpoint, and the first frame is the first photograph's view of the geometry.
    return recoveredCameraState(first, first.viewpointLocal, first.viewpointForwardLocal);
  }
  return first === undefined
    ? {
        x: navigationWorld.centre.x,
        y: (navigationWorld.surface.sample(
          navigationWorld.centre.x,
          navigationWorld.centre.z + 10,
        )?.height ?? 0) + navigationWorld.eyeHeight,
        z: navigationWorld.centre.z + 10,
        yaw: 0,
        pitch: -0.085,
      }
    : (() => {
        const distance = Math.max(3.6, Math.min(4.4, first.footprintRadiusLocal * 0.22));
        const x = first.placement.position.x + Math.sin(first.placement.yaw) * distance;
        const z = first.placement.position.z + Math.cos(first.placement.yaw) * distance;
        const height = navigationWorld.surface.sample(x, z)?.height ?? 0;
        return { x, y: height + navigationWorld.eyeHeight, z, yaw: first.placement.yaw, pitch: -0.085 };
      })();
}

/** Deliberate NYC viewpoints in the independent local metre frame. */
export function cityCameraState(view: 'overview' | 'street'): CameraState {
  return view === 'street'
    ? { x: -25, y: 60, z: -280, yaw: Math.PI, pitch: -0.35 }
    : { x: -45, y: 95, z: -380, yaw: Math.PI, pitch: -0.48 };
}

/** Frame the actual admitted district rather than assuming its local origin is Manhattan. */
export function ownedDistrictOverviewCameraState(district: OwnedDistrict): CameraState {
  if (district.buildings.length === 0) {
    return { x: -45, y: 95, z: -380, yaw: Math.PI, pitch: -0.48 };
  }
  const west = Math.min(...district.buildings.map((building) => building.bbox_cm[0] / 100));
  const north = Math.min(...district.buildings.map((building) => building.bbox_cm[1] / 100));
  const east = Math.max(...district.buildings.map((building) => building.bbox_cm[2] / 100));
  const south = Math.max(...district.buildings.map((building) => building.bbox_cm[3] / 100));
  const tallest = Math.max(...district.buildings.map((building) => building.height_cm / 100));
  const targetX = (west + east) / 2;
  const targetZ = (north + south) / 2;
  const span = Math.max(80, east - west, south - north);
  const horizontal = span * 0.9;
  const x = targetX + horizontal * 0.28;
  const y = Math.max(65, tallest * 1.18, span * 0.52);
  const z = targetZ + horizontal;
  const targetY = Math.min(24, tallest * 0.28);
  const dx = targetX - x;
  const dz = targetZ - z;
  return {
    x, y, z,
    yaw: Math.atan2(-dx, -dz),
    pitch: Math.atan2(targetY - y, Math.hypot(dx, dz)),
  };
}

/** Deterministic clear spawn on visible owned support, never an invisible safety floor. */
export function ownedDistrictCameraState(
  world: NavigationWorld,
  district?: OwnedDistrict,
): CameraState {
  const landmark = district?.buildings
    .filter((building) => building.name !== null)
    .map((building) => {
      const width = Math.max(1, building.bbox_cm[2] - building.bbox_cm[0]);
      const depth = Math.max(1, building.bbox_cm[3] - building.bbox_cm[1]);
      const slenderness = Math.max(width, depth) / Math.min(width, depth);
      return { building, score: building.height_cm * slenderness };
    })
    .sort((a, b) => b.score - a.score || a.building.id.localeCompare(b.building.id))[0]?.building;
  if (landmark !== undefined) {
    const [west, north, east, south] = landmark.bbox_cm.map((value) => value / 100) as [
      number, number, number, number,
    ];
    const targetX = (west + east) / 2;
    const targetZ = (north + south) / 2;
    for (const [offsetX, offsetZ] of [
      [0, -45], [-38, -34], [38, -34], [-48, 34], [46, 36],
    ] as const) {
      const x = targetX + offsetX;
      const z = targetZ + offsetZ;
      const position = atlasVec3(x, world.eyeHeight, z);
      if (
        isNavigationPositionClear(world, position) &&
        world.surface.sample(x - 3, z) !== null &&
        world.surface.sample(x + 3, z) !== null &&
        world.surface.sample(x, z - 3) !== null &&
        world.surface.sample(x, z + 3) !== null
      ) {
        return {
          x,
          y: world.eyeHeight,
          z,
          yaw: Math.atan2(-(targetX - x), -(targetZ - z)),
          pitch: 0.08,
        };
      }
    }
  }
  const segmentDistance = (
    x: number,
    z: number,
    ax: number,
    az: number,
    bx: number,
    bz: number,
  ): number => {
    const dx = bx - ax;
    const dz = bz - az;
    const denominator = dx * dx + dz * dz;
    const t = denominator === 0
      ? 0
      : Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / denominator));
    return Math.hypot(x - (ax + dx * t), z - (az + dz * t));
  };
  let best: { x: number; z: number; score: number } | null = null;
  const extent = Math.min(340, Math.ceil(world.fieldRadius));
  for (let z = world.centre.z - extent; z <= world.centre.z + extent; z += 10) {
    for (let x = world.centre.x - extent; x <= world.centre.x + extent; x += 10) {
      const position = atlasVec3(x, world.eyeHeight, z);
      if (
        !isNavigationPositionClear(world, position) ||
        world.surface.sample(x - 8, z) === null ||
        world.surface.sample(x + 8, z) === null ||
        world.surface.sample(x, z - 8) === null ||
        world.surface.sample(x, z + 8) === null
      ) continue;
      let clearance = 60;
      for (const obstacle of world.polygonObstacles ?? []) {
        for (const ring of obstacle.rings) {
          for (let index = 1; index < ring.length; index += 1) {
            const a = ring[index - 1]!;
            const b = ring[index]!;
            clearance = Math.min(clearance, segmentDistance(x, z, a.x, a.z, b.x, b.z));
          }
        }
      }
      const score = clearance - Math.hypot(x - world.centre.x, z - world.centre.z) * 0.015;
      if (best === null || score > best.score) best = { x, z, score };
    }
  }
  if (best !== null) {
    const dx = world.centre.x - best.x;
    const dz = world.centre.z - best.z;
    return {
      x: best.x,
      y: world.eyeHeight,
      z: best.z,
      yaw: Math.atan2(-dx, -dz),
      pitch: -0.045,
    };
  }
  return {
    x: world.centre.x,
    y: world.eyeHeight,
    z: world.centre.z,
    yaw: 0,
    pitch: 0,
  };
}

/**
 * Residency cost of a region's placed point maps, in budget units, capped so one region always fits.
 *
 * The cost grows with the map count so that many regions compete for the budget, and it is capped
 * at the budget itself so that a single region can never price itself out of view. MEASURED
 * 2026-09-05 on the first real scene: 38 placed maps cost 912 against a budget of 96, even their
 * proxy stage exceeded it, the planner left the region at stub, and the walking view showed the
 * landscape alone while inspection, which bypasses residency, showed the geometry. The decoded
 * maps are uploaded either way; residency only decides what is drawn, and the representation
 * pressure controller still scales the budget down when frames run long.
 */
export function pointMapResidencyCost(mapCount: number, budget: number): ResidencyAsset['cost'] {
  return Object.freeze({
    stub: 0,
    proxy: Math.min(4 * mapCount, budget / 4),
    coarse: Math.min(10 * mapCount, budget / 2),
    full: Math.min(24 * mapCount, budget),
  });
}

/** The controls' pose at a recovered camera: forward is (-sin yaw, 0, -cos yaw), pitch positive up. */
export function recoveredCameraState(island: Island, viewpointLocal: LocalVec3, forwardLocal: LocalVec3): CameraState {
  const position = localToAtlas(island.placement, viewpointLocal);
  const forward = localDirectionToAtlas(island.placement, forwardLocal);
  const horizontal = Math.hypot(forward.x, forward.z);
  return {
    x: position.x,
    y: position.y,
    z: position.z,
    yaw: horizontal < 1e-9 ? island.placement.yaw : Math.atan2(-forward.x, -forward.z),
    pitch: Math.max(-1.3, Math.min(1.3, Math.atan2(forward.y, horizontal))),
  };
}


/** A deterministic overview pose derived only from persisted presentation layout. */
export function mapCameraState(scene: AtlasScene): CameraState {
  const pose = atlasMapPose(scene);
  return {
    x: pose.position.x,
    y: pose.position.y,
    z: pose.position.z,
    yaw: pose.yaw,
    pitch: pose.pitch,
  };
}

/**
 * The presentation transform, and only the presentation transform.
 *
 * Islands are never pitched or rolled, so the up vector stays globally shared. That is why this
 * writes a single yaw rather than a quaternion: a quaternion would make an illegal orientation
 * representable, and atlas-core deliberately does not offer one.
 */
function applyPlacement(entity: pc.Entity, island: Island): void {
  const p = island.placement;
  entity.setLocalPosition(p.position.x, p.position.y, p.position.z);
  entity.setLocalEulerAngles(0, (p.yaw * 180) / Math.PI, 0);
  entity.setLocalScale(p.scale, p.scale, p.scale);
}

/** Convert the receipt's row-major affine transform into PlayCanvas local TRS. */
/**
 * Lift or lower an unmeasured photograph so its camera stands exactly where a walking visitor's
 * eye does over the ground at that spot.
 *
 * A single photograph's depth is right only from its own camera, and every edge, seam and bridge
 * of its surface is drawn on that assumption. The walking controls hold the eye at the navigation
 * surface plus `eyeHeight` wherever the visitor stands, while the display frame put the camera at
 * its own eye height above the photograph's own ground, and nothing makes those the same height:
 * the authored landscape is not flat and the island has its own scale. With this, MEASURED
 * 2026-09-11 on the first personal place, the arrival eye and all three photographs' cameras
 * coincide to float precision. The arrangement is unmeasured, so moving it vertically claims
 * nothing; not moving it would draw every photograph from a viewpoint nobody stood at.
 */
function standOnTheGround(
  entity: pc.Entity,
  pointMap: PlacedScenePointMap,
  island: Island,
  navigationWorld: NavigationWorld,
): void {
  const [x, y, z] = scenePointMapViewpoint(pointMap);
  const camera = localToAtlas(island.placement, localVec3(x, y, z));
  const ground = navigationWorld.surface.sample(camera.x, camera.z);
  if (ground === null || !(island.placement.scale > 0)) return;
  const lift = (ground.height + navigationWorld.eyeHeight - camera.y) / island.placement.scale;
  const at = entity.getLocalPosition();
  entity.setLocalPosition(at.x, at.y + lift, at.z);
}

function applyScenePointMapPlacement(entity: pc.Entity, value: PlacedScenePointMap): void {
  applySceneTransform(entity, value.sceneFromOpmRowMajor, value.localUnitsToSceneUnits);
}

function applySceneTransform(entity: pc.Entity, m: readonly number[], scale: number): void {
  const rotation = new pc.Mat4().set([
    m[0]! / scale, m[4]! / scale, m[8]! / scale, 0,
    m[1]! / scale, m[5]! / scale, m[9]! / scale, 0,
    m[2]! / scale, m[6]! / scale, m[10]! / scale, 0,
    0, 0, 0, 1,
  ]);
  entity.setLocalPosition(m[3]!, m[7]!, m[11]!);
  entity.setLocalRotation(new pc.Quat().setFromMat4(rotation));
  entity.setLocalScale(scale, scale, scale);
}

// -- scene segments ----------------------------------------------------------------------------------

/**
 * Scene segments over trained Gaussian geometry: the proof lens first, then one tint per splat.
 *
 * The same hook as `PROOF_LENS_SPLAT_MODIFIER`, for the same reason: unified gsplat rendering fills
 * one shared work buffer, and `modifySplatColor` is the one place a value can differ between two
 * splats. What makes it per splat rather than per component is `splat.index`, which the copy shader
 * sets from the component's own splat order before this runs, so a splat is addressed by the same
 * number the segment artifact names it by. The artifact is digest-bound to the trained bytes for
 * exactly that reason: the same index is a different Gaussian in a retrained scene.
 *
 * TWO TEXTURES, AND THE SPLIT IS WHAT KEEPS A HOVER CHEAP. `uSegmentSlots` holds one byte per splat,
 * the slot of its segment or zero; `uSegmentPalette` holds one resolved colour and strength per slot.
 * Highlighting a segment rewrites the 1 KB palette and never the per-splat bytes.
 *
 * A splat in no segment reads slot 0, whose palette entry is all zero, and `mix(c, x, 0.0)` is `c`,
 * so it comes out exactly as `PROOF_LENS_SPLAT_MODIFIER` would have left it. The lens term is
 * repeated here rather than chained because a component carries exactly one modifier.
 */
export const SEGMENT_OVERLAY_SPLAT_MODIFIER = Object.freeze({
  glsl: /* glsl */ `
uniform vec4 uProofLens;
uniform sampler2D uSegmentSlots;
uniform sampler2D uSegmentPalette;
void modifySplatCenter(inout vec3 center) {}
void modifySplatRotationScale(vec3 originalCenter, vec3 modifiedCenter, inout vec4 rotation, inout vec3 scale) {}
vec3 exulanicaTint(vec3 rgb, float luma, vec4 tint) {
    vec3 hue = tint.rgb / max(dot(tint.rgb, vec3(0.2126, 0.7152, 0.0722)), 0.004);
    return mix(rgb, clamp(hue * luma, 0.0, 1.0), tint.a);
}
void modifySplatColor(vec3 center, inout vec4 color) {
    float luma = dot(color.rgb, vec3(0.2126, 0.7152, 0.0722));
    vec3 lensed = exulanicaTint(color.rgb, luma, uProofLens);
    int width = textureSize(uSegmentSlots, 0).x;
    int splatIndex = int(splat.index);
    float slot = texelFetch(uSegmentSlots, ivec2(splatIndex % width, splatIndex / width), 0).r;
    vec4 tint = texelFetch(uSegmentPalette, ivec2(int(slot * 255.0 + 0.5), 0), 0);
    color.rgb = exulanicaTint(lensed, luma, tint);
}
`,
  wgsl: /* wgsl */ `
uniform uProofLens : vec4f;
var uSegmentSlots : texture_2d<f32>;
var uSegmentPalette : texture_2d<f32>;
fn modifySplatCenter(center : ptr<function, vec3f>) {}
fn modifySplatRotationScale(originalCenter : vec3f, modifiedCenter : vec3f, rotation : ptr<function, vec4f>, scale : ptr<function, vec3f>) {}
fn exulanicaTint(rgb : vec3f, luma : f32, tint : vec4f) -> vec3f {
    let hue : vec3f = tint.rgb / max(dot(tint.rgb, vec3f(0.2126, 0.7152, 0.0722)), 0.004);
    return mix(rgb, clamp(hue * luma, vec3f(0.0), vec3f(1.0)), tint.a);
}
fn modifySplatColor(center : vec3f, color : ptr<function, vec4f>) {
    let luma : f32 = dot((*color).rgb, vec3f(0.2126, 0.7152, 0.0722));
    let lensed : vec3f = exulanicaTint((*color).rgb, luma, uniform.uProofLens);
    let width : u32 = textureDimensions(uSegmentSlots, 0).x;
    let splatIndex : u32 = splat.index;
    let slot : f32 = textureLoad(uSegmentSlots, vec2i(i32(splatIndex % width), i32(splatIndex / width)), 0).r;
    let tint : vec4f = textureLoad(uSegmentPalette, vec2i(i32(slot * 255.0 + 0.5), 0), 0);
    (*color) = vec4f(exulanicaTint(lensed, luma, tint), (*color).a);
}
`,
});

/** One byte per splat, so 255 segments per region; slot 0 means "in no segment". */
export const SEGMENT_SLOT_LIMIT = 255;
/** Width of the per-splat slot texture. Its height follows the splat count. */
const SEGMENT_SLOT_TEXTURE_WIDTH = 1024;

/** One segment's samples on one drawn asset, under a slot number the caller chose. */
export interface SegmentOverlayTint {
  /** 1 to 255. The caller's own numbering; the palette is keyed by it. */
  readonly slot: number;
  /** A trained scene's or a placed point map's artifact id. */
  readonly artifactId: string;
  /** Ascending sample indices in the asset's own order: the splat index, or the point index. */
  readonly indices: Uint32Array;
}

/** Slot to an already resolved colour and strength. Nothing in this package picks one. */
export type SegmentPalette = ReadonlyMap<number, ProofLensColor>;

export interface SegmentOverlay {
  readonly islandId: IslandId;
  /** In precedence order: a sample that two tints name keeps the first. */
  readonly tints: readonly SegmentOverlayTint[];
  readonly palette: SegmentPalette;
}

/** What one drawn asset now shows, with the tinted samples' atlas positions for a pick. */
export interface SegmentOverlayAsset {
  readonly artifactId: string;
  readonly kind: 'gaussians' | 'points';
  readonly sampleCount: number;
  /** Tinted sample indices in the asset's own numbering: ascending, or grouped by slot for a map. */
  readonly indices: Uint32Array;
  /** The slot of each tinted sample, parallel to `indices`. */
  readonly slots: Uint8Array;
  /**
   * Atlas-space positions, three floats per tinted sample, parallel to `indices`.
   *
   * Null when the engine holds no CPU copy of a trained scene's centres. The tint does not depend
   * on it; only a click can no longer reach those samples, and a caller has to say so.
   */
  readonly positions: Float32Array | null;
}

export interface SegmentOverlayReport {
  readonly islandId: IslandId | null;
  readonly assets: readonly SegmentOverlayAsset[];
  readonly refused: readonly { readonly artifactId: string; readonly reason: string }[];
}

/** The engine calls the overlay makes, gathered so the rules around them run without a GPU. */
export interface SegmentOverlayEngine {
  readonly maxTextureSize: number;
  texture(kind: 'slots' | 'palette', width: number, height: number, bytes: Uint8Array): SegmentOverlayTexture;
  pointGroups(visual: IslandVisual, order: Uint32Array, groups: readonly SegmentPointGroup[]): SegmentPointOverlay;
}

export interface SegmentOverlayTexture {
  readonly texture: unknown;
  write(bytes: Uint8Array): void;
  destroy(): void;
}

export interface SegmentPointGroup {
  readonly slot: number;
  readonly base: number;
  readonly count: number;
}

export interface SegmentPointOverlay {
  setLens(slot: number, color: ProofLensColor): void;
  destroy(): void;
}

interface SegmentOverlayHost {
  /** Whether the proof lens has installed its own modifier on this scene. */
  lensPrepared(entity: pc.Entity): boolean;
  /** Hold the trained scenes' work buffers open, exactly as the lens does. */
  settle(): void;
  invalidate(): void;
}

type SegmentGsplat = Pick<
  pc.GSplatComponent,
  'setWorkBufferModifier' | 'setParameter' | 'getParameter' | 'deleteParameter' | 'workBufferUpdate'
>;
type TrainedSceneVisual = AtlasBinding['trainedScenes'][number];

interface HeldSplats {
  readonly gsplat: SegmentGsplat;
  readonly slots: SegmentOverlayTexture;
  readonly palette: SegmentOverlayTexture;
  /** Whether the overlay supplied `uProofLens` because the lens had not, so it can take it back. */
  readonly addedLens: boolean;
}

interface HeldPoints {
  readonly overlay: SegmentPointOverlay;
  readonly slots: readonly number[];
}

const NO_SEGMENT_OVERLAY: SegmentOverlayReport = Object.freeze({
  islandId: null,
  assets: Object.freeze([]),
  refused: Object.freeze([]),
});

/**
 * One byte per sample: the slot of the first tint that names it, or zero.
 *
 * A tint whose slot is out of range, whose indices are not ascending, or which names a sample past
 * the end of its asset is refused whole rather than drawn in part: an index outside its asset means
 * the segments were computed against different bytes, and part of such a tint is not an answer.
 */
export function segmentSlotsFor(
  sampleCount: number,
  tints: readonly SegmentOverlayTint[],
): { readonly slots: Uint8Array; readonly refused: readonly string[] } {
  const slots = new Uint8Array(sampleCount);
  const refused: string[] = [];
  for (const tint of tints) {
    if (!Number.isInteger(tint.slot) || tint.slot < 1 || tint.slot > SEGMENT_SLOT_LIMIT) {
      refused.push(`Slot ${String(tint.slot)} is outside 1 to ${SEGMENT_SLOT_LIMIT}.`);
      continue;
    }
    let previous = -1;
    let valid = true;
    for (const index of tint.indices) {
      if (index <= previous || index >= sampleCount) { valid = false; break; }
      previous = index;
    }
    if (!valid) {
      refused.push(`Slot ${tint.slot} names samples out of order or beyond this asset's ${sampleCount}.`);
      continue;
    }
    for (const index of tint.indices) if (slots[index] === 0) slots[index] = tint.slot;
  }
  return { slots, refused };
}

/** The palette as 256 RGBA bytes. Slot 0 stays zero, which is what makes "in no segment" exact. */
export function segmentPaletteBytes(palette: SegmentPalette): Uint8Array {
  const bytes = new Uint8Array((SEGMENT_SLOT_LIMIT + 1) * 4);
  for (const [slot, color] of palette) {
    if (!Number.isInteger(slot) || slot < 1 || slot > SEGMENT_SLOT_LIMIT) {
      throw new RangeError(`segment palette slot ${String(slot)} is outside 1 to ${SEGMENT_SLOT_LIMIT}`);
    }
    for (let channel = 0; channel < 4; channel += 1) {
      bytes[slot * 4 + channel] = Math.round(Math.min(1, Math.max(0, color[channel] ?? 0)) * 255);
    }
  }
  return bytes;
}

/**
 * Sample order grouped by slot, the untinted rest first, for drawing a point map one slot per draw.
 *
 * Indexed draws keep `gl_VertexID` equal to the sample's own index, which is what the point shader
 * hashes for its dissolve, so the same samples survive as in the single unindexed draw.
 */
export function segmentPointGroups(slots: Uint8Array): {
  readonly order: Uint32Array;
  readonly groups: readonly SegmentPointGroup[];
} {
  const counts = new Uint32Array(SEGMENT_SLOT_LIMIT + 1);
  for (let index = 0; index < slots.length; index += 1) counts[slots[index]!]! += 1;
  const starts = new Uint32Array(SEGMENT_SLOT_LIMIT + 1);
  const groups: SegmentPointGroup[] = [];
  let base = 0;
  for (let slot = 0; slot <= SEGMENT_SLOT_LIMIT; slot += 1) {
    starts[slot] = base;
    if (counts[slot]! > 0) groups.push(Object.freeze({ slot, base, count: counts[slot]! }));
    base += counts[slot]!;
  }
  const order = new Uint32Array(slots.length);
  for (let index = 0; index < slots.length; index += 1) order[starts[slots[index]!]!++] = index;
  return { order, groups: Object.freeze(groups) };
}

function tintedSamples(slots: Uint8Array): { readonly indices: Uint32Array; readonly slots: Uint8Array } {
  let count = 0;
  for (let index = 0; index < slots.length; index += 1) if (slots[index] !== 0) count += 1;
  const indices = new Uint32Array(count);
  const tinted = new Uint8Array(count);
  let at = 0;
  for (let index = 0; index < slots.length; index += 1) {
    if (slots[index] === 0) continue;
    indices[at] = index;
    tinted[at] = slots[index]!;
    at += 1;
  }
  return { indices, slots: tinted };
}

/** A trained scene's Gaussian centres in its asset frame, when the engine kept a CPU copy. */
function splatCentres(visual: TrainedSceneVisual): Float32Array | null {
  const centres = (visual.asset.resource as { centers?: unknown } | null | undefined)?.centers;
  const length = visual.geometry.pointCount * 3;
  return centres instanceof Float32Array && centres.length >= length ? centres.subarray(0, length) : null;
}

/**
 * Atlas positions of the given samples, through the scene transform and the region placement.
 *
 * `localToAtlas` is a yaw, a uniform scale and a translation, so it composes with the scene
 * transform into one affine, built once here rather than through an allocated vector per sample.
 * MEASURED 2026-09-11 in the browser on 2.9 million tinted samples over 38 placed maps: the
 * per-sample call took about 257 ms of the overlay's first frame, and the whole `apply` about 370 ms.
 * Composed, and with the tinted list read from the draw order, `apply` takes about 130 ms.
 */
function atlasPositions(
  island: Island,
  sceneFromLocal: readonly number[],
  local: Float32Array,
  indices: Uint32Array,
): Float32Array {
  const m = sceneFromLocal;
  const { position, yaw, scale } = island.placement;
  const c = Math.cos(yaw) * scale;
  const s = Math.sin(yaw) * scale;
  // Rows of atlas-from-local: placement (x' = c x + s z, y' = scale y, z' = -s x + c z) after m.
  const a = [
    c * m[0]! + s * m[8]!, c * m[1]! + s * m[9]!, c * m[2]! + s * m[10]!, c * m[3]! + s * m[11]! + position.x,
    scale * m[4]!, scale * m[5]!, scale * m[6]!, scale * m[7]! + position.y,
    -s * m[0]! + c * m[8]!, -s * m[1]! + c * m[9]!, -s * m[2]! + c * m[10]!, -s * m[3]! + c * m[11]! + position.z,
  ] as const;
  const out = new Float32Array(indices.length * 3);
  for (let k = 0; k < indices.length; k += 1) {
    const i = indices[k]! * 3;
    const x = local[i]!;
    const y = local[i + 1]!;
    const z = local[i + 2]!;
    out[k * 3] = a[0] * x + a[1] * y + a[2] * z + a[3];
    out[k * 3 + 1] = a[4] * x + a[5] * y + a[6] * z + a[7];
    out[k * 3 + 2] = a[8] * x + a[9] * y + a[10] * z + a[11];
  }
  return out;
}

/**
 * The scene segment overlay: one region at a time, and nothing at all until a surface asks.
 *
 * THIS DECIDES NOTHING ABOUT WHAT A SEGMENT IS OR WHAT COLOUR IT WEARS. The caller hands over sample
 * indices under slot numbers and one resolved RGBA per slot, exactly as `setProofLens` is handed one
 * per region; this puts those numbers where the renderer reads them and reports what it could not.
 *
 * Trained geometry takes them through `SEGMENT_OVERLAY_SPLAT_MODIFIER`, with the same settle window
 * the lens needed. A point map takes them through its existing `uLens` uniform: the map is drawn as
 * one indexed draw per slot over its own vertex buffer, each draw carrying its slot's colour as a
 * per-instance `uLens`, and the original draw is hidden while they stand in for it. No shader and no
 * vertex byte changes.
 *
 * OFF IS EXACTLY WHAT WAS THERE BEFORE. Leaving a trained scene puts back the lens's own modifier if
 * the lens had installed one and no modifier otherwise, and deletes every parameter the overlay set;
 * leaving a point map removes its draws and shows the original again. A runtime that was never
 * applied touches nothing, which `test/scene-segment-overlay.test.ts` asserts call by call.
 */
export class SegmentOverlayRuntime {
  readonly #islands: readonly IslandVisual[];
  readonly #trained: readonly TrainedSceneVisual[];
  readonly #engineFactory: () => SegmentOverlayEngine;
  readonly #host: SegmentOverlayHost;
  #engine: SegmentOverlayEngine | null = null;
  #report: SegmentOverlayReport | null = null;
  #splats = new Map<pc.Entity, HeldSplats>();
  #points = new Map<IslandVisual, HeldPoints>();

  constructor(
    islands: readonly IslandVisual[],
    trained: readonly TrainedSceneVisual[],
    engine: () => SegmentOverlayEngine,
    host: SegmentOverlayHost,
  ) {
    this.#islands = islands;
    this.#trained = trained;
    this.#engineFactory = engine;
    this.#host = host;
  }

  /** What is tinted now, or null when the overlay is off. */
  get report(): SegmentOverlayReport | null {
    return this.#report;
  }

  /** Whether this trained scene currently carries the segment modifier. */
  covers(entity: pc.Entity): boolean {
    return this.#splats.has(entity);
  }

  /**
   * One drawn asset's samples in its own local frame, three floats each, in the asset's own order.
   *
   * A point map's positions, or a trained scene's Gaussian centres when the engine holds a CPU copy
   * of them; null otherwise. This is what a caller needs to decide which samples a segment covers,
   * and it is read here so the engine's resource stays behind the binding. The overlay itself only
   * ever takes indices.
   */
  localSamples(artifactId: string): { readonly kind: 'gaussians' | 'points'; readonly positions: Float32Array } | null {
    for (const visual of this.#trained) {
      if (visual.geometry.artifactId !== artifactId) continue;
      const centres = splatCentres(visual);
      return centres === null ? null : { kind: 'gaussians', positions: centres };
    }
    for (const visual of this.#islands) {
      if (visual.pointMap.artifactId === artifactId) return { kind: 'points', positions: visual.pointMap.map.position };
    }
    return null;
  }

  /** Tint one region's segments, replacing whatever region was tinted before. Null is off. */
  apply(overlay: SegmentOverlay | null): SegmentOverlayReport {
    if (overlay === null) {
      this.#clear();
      return NO_SEGMENT_OVERLAY;
    }
    const paletteBytes = segmentPaletteBytes(overlay.palette);
    const engine = this.#engine ?? (this.#engine = this.#engineFactory());
    const assets: SegmentOverlayAsset[] = [];
    const refused: { artifactId: string; reason: string }[] = [];
    const drawn = new Set<string>();
    const nextSplats = new Map<pc.Entity, HeldSplats>();
    const nextPoints = new Map<IslandVisual, HeldPoints>();
    const trainedScenes = new Set(this.#trained.map((visual) => visual.geometry.sceneId));

    for (const visual of this.#trained) {
      const artifactId = visual.geometry.artifactId;
      const tints = overlay.tints.filter((tint) => tint.artifactId === artifactId);
      if (visual.island.islandId !== overlay.islandId || tints.length === 0) continue;
      drawn.add(artifactId);
      const sampleCount = visual.geometry.pointCount;
      const height = Math.max(1, Math.ceil(sampleCount / SEGMENT_SLOT_TEXTURE_WIDTH));
      const gsplat = visual.entity.gsplat as SegmentGsplat | null | undefined;
      if (gsplat === null || gsplat === undefined || height > engine.maxTextureSize) {
        refused.push({ artifactId, reason: gsplat == null
          ? 'This trained scene has no drawn Gaussian component to tint.'
          : `${sampleCount} splats need a slot texture taller than this device allows.` });
        continue;
      }
      const { slots, refused: problems } = segmentSlotsFor(sampleCount, tints);
      for (const reason of problems) refused.push({ artifactId, reason });
      const tinted = tintedSamples(slots);
      if (tinted.indices.length === 0) continue;
      const bytes = new Uint8Array(SEGMENT_SLOT_TEXTURE_WIDTH * height);
      bytes.set(slots);
      const held = this.#splats.get(visual.entity);
      const slotTexture = engine.texture('slots', SEGMENT_SLOT_TEXTURE_WIDTH, height, bytes);
      const paletteTexture = engine.texture('palette', SEGMENT_SLOT_LIMIT + 1, 1, paletteBytes);
      gsplat.setParameter('uSegmentSlots', slotTexture.texture as pc.Texture);
      gsplat.setParameter('uSegmentPalette', paletteTexture.texture as pc.Texture);
      // A lens the visitor never switched on has never bound `uProofLens`, and an unbound uniform
      // reads whatever another component last left in the device scope. Off has to be a value.
      const addedLens = held?.addedLens ?? gsplat.getParameter('uProofLens') === undefined;
      if (gsplat.getParameter('uProofLens') === undefined) gsplat.setParameter('uProofLens', [...PROOF_LENS_OFF]);
      if (held === undefined) gsplat.setWorkBufferModifier(SEGMENT_OVERLAY_SPLAT_MODIFIER);
      gsplat.workBufferUpdate = pc.WORKBUFFER_UPDATE_ALWAYS;
      held?.slots.destroy();
      held?.palette.destroy();
      nextSplats.set(visual.entity, { gsplat, slots: slotTexture, palette: paletteTexture, addedLens });
      const centres = splatCentres(visual);
      assets.push(Object.freeze({
        artifactId, kind: 'gaussians' as const, sampleCount, ...tinted,
        positions: centres === null
          ? null
          : atlasPositions(visual.island, visual.geometry.sceneFromAssetRowMajor, centres, tinted.indices),
      }));
    }

    for (const visual of this.#islands) {
      const artifactId = visual.pointMap.artifactId;
      const tints = overlay.tints.filter((tint) => tint.artifactId === artifactId);
      if (visual.island.islandId !== overlay.islandId || tints.length === 0) continue;
      drawn.add(artifactId);
      if (trainedScenes.has(visual.pointMap.sceneId)) {
        refused.push({ artifactId, reason: 'Not drawn: this region draws its trained geometry instead of its point maps.' });
        continue;
      }
      const sampleCount = visual.cloud.pointCount;
      const { slots, refused: problems } = segmentSlotsFor(sampleCount, tints);
      for (const reason of problems) refused.push({ artifactId, reason });
      const { order, groups } = segmentPointGroups(slots);
      // The draw order already lists every tinted sample after the untinted rest, grouped by slot,
      // so the report is read from it rather than from another pass over every sample's byte.
      const rest = groups[0]?.slot === 0 ? groups[0].count : 0;
      const tinted = { indices: order.subarray(rest), slots: new Uint8Array(order.length - rest) };
      for (const group of groups) if (group.slot !== 0) tinted.slots.fill(group.slot, group.base - rest, group.base - rest + group.count);
      if (tinted.indices.length === 0) continue;
      // Taken down before the replacement goes up: its teardown shows the original draw again,
      // and doing that after would draw every sample twice.
      const previous = this.#points.get(visual);
      if (previous !== undefined) {
        previous.overlay.destroy();
        this.#points.delete(visual);
      }
      const pointOverlay = engine.pointGroups(visual, order, groups);
      const used = groups.filter((group) => group.slot !== 0).map((group) => group.slot);
      for (const slot of used) pointOverlay.setLens(slot, overlay.palette.get(slot) ?? PROOF_LENS_OFF);
      nextPoints.set(visual, { overlay: pointOverlay, slots: used });
      assets.push(Object.freeze({
        artifactId, kind: 'points' as const, sampleCount, ...tinted,
        positions: atlasPositions(visual.island, visual.pointMap.sceneFromOpmRowMajor, visual.pointMap.map.position, tinted.indices),
      }));
    }

    for (const tint of overlay.tints) {
      if (drawn.has(tint.artifactId)) continue;
      drawn.add(tint.artifactId);
      refused.push({ artifactId: tint.artifactId, reason: 'Not drawn in this region, so there is nothing of it to tint.' });
    }

    const touchedSplats = this.#splats.size > 0 || nextSplats.size > 0;
    for (const [entity, held] of this.#splats) if (!nextSplats.has(entity)) this.#restore(entity, held);
    for (const [visual, held] of this.#points) if (!nextPoints.has(visual)) held.overlay.destroy();
    this.#splats = nextSplats;
    this.#points = nextPoints;
    this.#report = Object.freeze({
      islandId: overlay.islandId,
      assets: Object.freeze(assets),
      refused: Object.freeze(refused),
    });
    if (touchedSplats) this.#host.settle();
    this.#host.invalidate();
    return this.#report;
  }

  /** Re-colour the slots already tinted, for a hover or a selection. Rebuilds nothing. */
  setPalette(palette: SegmentPalette): void {
    if (this.#report === null) return;
    const bytes = segmentPaletteBytes(palette);
    for (const held of this.#splats.values()) {
      held.palette.write(bytes);
      held.gsplat.workBufferUpdate = pc.WORKBUFFER_UPDATE_ALWAYS;
    }
    for (const held of this.#points.values()) {
      for (const slot of held.slots) held.overlay.setLens(slot, palette.get(slot) ?? PROOF_LENS_OFF);
    }
    if (this.#splats.size > 0) this.#host.settle();
    this.#host.invalidate();
  }

  /** Release every texture and draw without restoring modifiers. The binding is going away. */
  destroy(): void {
    for (const held of this.#splats.values()) {
      held.slots.destroy();
      held.palette.destroy();
    }
    for (const held of this.#points.values()) held.overlay.destroy();
    this.#splats.clear();
    this.#points.clear();
    this.#report = null;
  }

  #clear(): void {
    if (this.#report === null && this.#splats.size === 0 && this.#points.size === 0) return;
    const hadSplats = this.#splats.size > 0;
    for (const [entity, held] of this.#splats) this.#restore(entity, held);
    for (const held of this.#points.values()) held.overlay.destroy();
    this.#splats = new Map();
    this.#points = new Map();
    this.#report = null;
    if (hadSplats) this.#host.settle();
    this.#host.invalidate();
  }

  #restore(entity: pc.Entity, held: HeldSplats): void {
    const lens = this.#host.lensPrepared(entity);
    held.gsplat.setWorkBufferModifier(lens ? PROOF_LENS_SPLAT_MODIFIER : null);
    held.gsplat.deleteParameter('uSegmentSlots');
    held.gsplat.deleteParameter('uSegmentPalette');
    if (held.addedLens && !lens) held.gsplat.deleteParameter('uProofLens');
    // Refilled once more without the tint, inside the same settle window the caller opens.
    held.gsplat.workBufferUpdate = pc.WORKBUFFER_UPDATE_ALWAYS;
    held.slots.destroy();
    held.palette.destroy();
  }
}

/** The overlay's engine calls, made with PlayCanvas. */
function playcanvasSegmentEngine(app: pc.AppBase): SegmentOverlayEngine {
  const device = app.graphicsDevice;
  return {
    maxTextureSize: device.maxTextureSize,
    texture(kind, width, height, bytes) {
      const texture = new pc.Texture(device, {
        name: `segment-${kind}`,
        width,
        height,
        format: kind === 'slots' ? pc.PIXELFORMAT_R8 : pc.PIXELFORMAT_RGBA8,
        mipmaps: false,
        minFilter: pc.FILTER_NEAREST,
        magFilter: pc.FILTER_NEAREST,
        addressU: pc.ADDRESS_CLAMP_TO_EDGE,
        addressV: pc.ADDRESS_CLAMP_TO_EDGE,
        levels: [bytes],
      });
      return {
        texture,
        write(next) {
          (texture.lock() as Uint8Array).set(next);
          texture.unlock();
        },
        destroy: () => texture.destroy(),
      };
    },
    pointGroups(visual, order, groups) {
      const indexBuffer = new pc.IndexBuffer(
        device, pc.INDEXFORMAT_UINT32, order.length, pc.BUFFER_STATIC,
        order.buffer.slice(order.byteOffset, order.byteOffset + order.byteLength) as ArrayBuffer,
      );
      const node = new pc.Entity(`segment-overlay:${visual.pointMap.artifactId}`);
      const draws = groups.map((group) => {
        const mesh = new pc.Mesh(device);
        mesh.vertexBuffer = visual.cloud.vertexBuffer;
        mesh.indexBuffer[0] = indexBuffer;
        mesh.primitive[0] = { type: pc.PRIMITIVE_POINTS, base: group.base, baseVertex: 0, count: group.count, indexed: true };
        mesh.aabb = visual.cloud.mesh.aabb;
        return { slot: group.slot, mesh, instance: new pc.MeshInstance(mesh, visual.cloud.material, node) };
      });
      node.addComponent('render', { meshInstances: draws.map((draw) => draw.instance) });
      visual.entity.addChild(node);
      const original = visual.entity.render?.meshInstances ?? [];
      for (const instance of original) instance.visible = false;
      return {
        setLens(slot, color) {
          for (const draw of draws) if (draw.slot === slot) draw.instance.setParameter('uLens', [...color]);
        },
        destroy() {
          for (const instance of original) instance.visible = true;
          // The vertex buffer is the cloud's and the index buffer is shared by every draw here.
          // Detached before the node goes, or destroying the node's meshes would destroy both.
          for (const draw of draws) {
            (draw.mesh as { vertexBuffer: pc.VertexBuffer | null }).vertexBuffer = null;
            draw.mesh.indexBuffer.length = 0;
          }
          node.destroy();
          indexBuffer.destroy();
        },
      };
    },
  };
}
