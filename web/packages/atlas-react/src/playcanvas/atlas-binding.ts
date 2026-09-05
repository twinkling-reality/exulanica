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
  NavigationWorld,
  NeighborhoodId,
  NeighborhoodIndex,
  NavigationPose,
  ResidencyAction,
  ResidencyAsset,
  ResidencyStage,
  ResidencyState,
  RepresentationPressureState,
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
  atlasLandscapeHeight,
  atlasLandscapeSurface,
  atlasMapPose,
  atlasVec3,
  buildAnchorTable,
  buildNeighborhoodIndex,
  buildNavigationWorld,
  classifySpatialPhase,
  enterAtlasMap,
  exitAtlasMap,
  focusDirectly,
  isNavigationLineVisible,
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
  sourceFirstCardLocalPosition,
  completeResidencyRequest,
  composeAtlasWorld,
  WorldCustomizationController,
  RepresentationPressureController,
  INITIAL_RENDER_ORIGIN,
  renderOriginForNeighborhood,
} from '@exulanica/atlas-core';
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
import {
  SOURCE_VEIL_HEIGHT,
  createSourceFirstGrove,
  type SourceFirstGrove,
} from './source-first-grove.js';
import type { SourceMediaCatalog } from './source-media.js';
import { sourceMediaForIsland } from './source-media.js';
import { createWorldField, type WorldField } from './world-field.js';
import { createComposedWorld, type ComposedWorld } from './composed-world.js';
import { createRegionMass, type RegionMass } from './region-mass.js';
import { createRegionRelief, type RegionRelief } from './region-relief.js';
import type { PointMap } from './opm.js';
import type { PointCloud } from './point-cloud.js';
import { createPointCloud } from './point-cloud.js';
import { defaultSemanticsFor } from './semantics.js';
import { sceneInspectionViews, calibratedCameraFrustum, type SceneInspectionView, type RecoveredSceneCamera } from './scene-inspection.js';
import { createSceneSplatAsset, type TrainedSceneGeometry } from './scene-splats.js';
import {
  opmPointInScene,
  type PlacedScenePointMap,
  validateScenePointMapPlacement,
} from './scene-point-maps.js';

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
 * rewrite, and it is worth being strict about: if a rule is being decided here, it is in the wrong
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
}

export interface AtlasBindingOptions {
  readonly canvas: HTMLCanvasElement;
  readonly overlayParent: HTMLElement;
  readonly scene: AtlasScene;
  /** Legacy unposed point maps, one per island. Islands with no map render as anchors only. */
  readonly pointMaps: ReadonlyMap<IslandId, PointMap>;
  /** Every map in a posed reconstruction scene. Supersedes pointMaps when supplied. */
  readonly placedPointMaps?: readonly PlacedScenePointMap[];
  readonly trainedGeometry?: readonly TrainedSceneGeometry[];
  readonly recoveredCameras?: readonly RecoveredSceneCamera[];
  /** Caller-authorized media presentation keyed by the scene's evidence handles. */
  readonly sourceMedia?: SourceMediaCatalog;
  /** Keep original photographs in the authorized inspector instead of placing optical sheets in the world. */
  readonly sourcePresentation?: 'world' | 'inspection';
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
  readonly sourceFirst: SourceFirstGrove;
  readonly topology: WorldTopologySnapshot;
  readonly composedWorld: ComposedWorld;
  readonly regionMass: RegionMass;
  readonly regionRelief: RegionRelief;
  readonly customization: WorldCustomizationController;
  readonly neighborhoodIndex: NeighborhoodIndex;
  readonly renderRoot: pc.Entity;

  private tierState: TierState = EMPTY_TIER_STATE;
  private focusState: FocusState = INITIAL_FOCUS_STATE;
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
  private readonly sourcePresentation: 'world' | 'inspection';
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
  private styleProposalSequence = 0;
  private readonly skyClearColor = new pc.Color();
  private readonly mapClearColor = new pc.Color();

  onFrame: ((report: FrameReport) => void) | null = null;
  onResidencyActions: ((actions: readonly ResidencyAction[]) => void) | null = null;
  onNavigationArrive: ((target: DirectNavigationTarget) => void) | null = null;
  onMapTarget: ((islandId: IslandId) => void) | null = null;
  onInspectionChange: ((view: SceneInspectionView | null) => void) | null = null;

  /** Called by the physical residency executor after its checked publish or terminal fallback. */
  settleResidencyRequest(requestId: string, ok: boolean): void {
    this.residencyState = completeResidencyRequest(this.residencyState, requestId, ok);
    this.residencyAllocated = new Map(
      [...this.residencyState.entries].map(([id, entry]) => [id, entry.current]),
    );
    this.applyResidencyPresentation();
  }

  private applyResidencyPresentation(): void {
    this.sourceFirst.setResidency(this.residencyAllocated, this.mapState !== null);
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
    sourceFirst: SourceFirstGrove,
    topology: WorldTopologySnapshot,
    composedWorld: ComposedWorld,
    regionMass: RegionMass,
    regionRelief: RegionRelief,
    customization: WorldCustomizationController,
    neighborhoodIndex: NeighborhoodIndex,
    renderRoot: pc.Entity,
    initialProfile: WorldArtProfile,
    residencyCatalog: readonly ResidencyAsset[],
    residencyBudget: number,
    sourcePresentation: 'world' | 'inspection',
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
    this.sourcePresentation = sourcePresentation;
    this.navigationWorld = navigationWorld;
    this.field = field;
    this.sourceFirst = sourceFirst;
    this.topology = topology;
    this.composedWorld = composedWorld;
    this.regionMass = regionMass;
    this.regionRelief = regionRelief;
    this.customization = customization;
    this.neighborhoodIndex = neighborhoodIndex;
    this.renderRoot = renderRoot;
    this.setClearColours(initialProfile);
    this.residencyCatalog = residencyCatalog;
    this.residencyBudget = residencyBudget;
    this.emphasis = neutralEmphasis(table);
    this.normalizer = occurrenceNormalizer(table.anchors);
  }

  private dirty = true;
  private reducedMotion = false;
  private lastRenderMs = -1;
  private readonly renderedPose = { x: NaN, y: NaN, z: NaN, yaw: NaN, pitch: NaN };

  static async create(options: AtlasBindingOptions): Promise<AtlasBinding> {
    const theme = options.theme ?? DAWN_THEME;
    const initialArtProfile = options.artProfile ?? DEFAULT_WORLD_ART_PROFILE;
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
      pc.CameraComponentSystem,
      pc.LightComponentSystem,
      pc.GSplatComponentSystem,
    ];
    appOptions.resourceHandlers = [pc.TextureHandler, pc.GSplatHandler];
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
      farClip: 1200,
      clearColor: new pc.Color(skyR, skyG, skyB, 1),
    });
    if (camera.camera !== undefined && camera.camera !== null) {
      camera.camera.toneMapping = pc.TONEMAP_ACES;
    }
    app.root.addChild(camera);

    const [hazeR, hazeG, hazeB] = unitRgb(initialArtProfile.palette.haze);
    app.scene.ambientLight = new pc.Color(hazeR * 0.58, hazeG * 0.58, hazeB * 0.58);
    app.scene.exposure = 1.06;
    app.scene.fog.type = pc.FOG_LINEAR;
    app.scene.fog.color.set(hazeR, hazeG, hazeB);
    app.scene.fog.start = 46;
    app.scene.fog.end = 220;

    const worldLight = new pc.Entity('atlas-directional-light');
    const [lr, lg, lb] = unitRgb(initialArtProfile.palette.sun);
    worldLight.addComponent('light', {
      type: 'directional',
      color: new pc.Color(lr, lg, lb),
      intensity: 1.65,
      castShadows: true,
      shadowDistance: 72,
      shadowResolution: 2048,
    });
    worldLight.setEulerAngles(48, 132, 0);
    app.root.addChild(worldLight);

    const table = buildAnchorTable(options.scene);
    const renderRoot = new pc.Entity('atlas-render-origin');
    app.root.addChild(renderRoot);
    const navigationWorld = buildNavigationWorld(options.scene, atlasLandscapeSurface());
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
    const residencyCatalog: ResidencyAsset[] = options.scene.islands.map((island) => ({
      islandId: island.islandId,
      cost: trainedIslandIds.has(island.islandId)
        ? Object.freeze({ stub: 0, proxy: 24, coarse: 24, full: 24 })
        : pointMapsByIsland.has(island.islandId)
        ? Object.freeze({
            stub: 0,
            proxy: 4 * pointMapsByIsland.get(island.islandId)!.length,
            coarse: 10 * pointMapsByIsland.get(island.islandId)!.length,
            full: 24 * pointMapsByIsland.get(island.islandId)!.length,
          })
        : Object.freeze({ stub: 0, proxy: 2, coarse: 2, full: 2 }),
    }));
    const field = createWorldField(
      device,
      navigationWorld,
      initialArtProfile,
      theme,
      options.reducedMotion ?? false,
    );
    renderRoot.addChild(field.entity);
    const sourceFirst = createSourceFirstGrove(
      app,
      sourceGroveScene(options.scene, availableReconstruction, options.sourcePresentation),
      options.sourceMedia ?? new Map(),
      initialArtProfile,
      theme,
      options.reducedMotion ?? false,
    );
    renderRoot.addChild(sourceFirst.entity);
    const topology = composeAtlasWorld(options.scene, {
      availableReconstruction,
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

    for (const island of options.scene.islands) {
      const islandEntity = new pc.Entity(`island:${island.islandId}`);
      applyPlacement(islandEntity, island);
      renderRoot.addChild(islandEntity);
      for (const [geometry, { asset, entity }] of trainedAssets) {
        if (geometry.islandId !== island.islandId) continue;
        islandEntity.addChild(entity);
        trainedScenes.push({ island, entity, asset, geometry });
      }

      for (const pointMap of pointMapsByIsland.get(island.islandId) ?? []) {
        const entity = new pc.Entity(`point-map:${pointMap.artifactId}`);
        applyScenePointMapPlacement(entity, pointMap);
        const map = pointMap.map;
        const cloud = createPointCloud({
          device,
          map,
          semantics: defaultSemanticsFor(map.header),
          ...(options.sizeGain === undefined ? {} : { sizeGain: options.sizeGain }),
          ...(options.maxSizePx === undefined ? {} : { maxSizePx: options.maxSizePx }),
          ...(options.blend === undefined ? {} : { blend: options.blend }),
          theme,
        });
        const instance = new pc.MeshInstance(cloud.mesh, cloud.material, entity);
        entity.addComponent('render', { meshInstances: [instance] });
        islandEntity.addChild(entity);

        visuals.push({
          island,
          entity,
          cloud,
          pointMap,
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
        });
      }
    }

    const start = initialAtlasCameraState(options.scene, navigationWorld, options.sourcePresentation);

    const controls = new FirstPersonControls(options.canvas, start, DEFAULT_CONTROLS, navigationWorld);
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

    return new AtlasBinding(
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
      sourceFirst,
      topology,
      composedWorld,
      regionMass,
      regionRelief,
      customization,
      neighborhoodIndex,
      renderRoot,
      initialArtProfile,
      Object.freeze(residencyCatalog),
      options.residencyBudget ?? 96,
      options.sourcePresentation ?? 'world',
    );
  }

  setTheme(theme: PresentationTheme): void {
    this.invalidate();
    this.motes.setTheme(theme);
    this.field.setTheme(theme);
    this.sourceFirst.setTheme(theme);
    this.composedWorld.setTheme(theme);
    for (const visual of this.islands) visual.cloud.setTheme(theme);
  }

  setReducedMotion(reduced: boolean): void {
    this.reducedMotion = reduced;
    this.field.setReducedMotion(reduced);
    this.sourceFirst.setReducedMotion(reduced);
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
      dirty: this.dirty,
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
    this.sourceFirst.setProfile(profile);
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
      this.sourceFirst.setResidency(this.residencyAllocated, true);
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
    this.sourceFirst.setResidency(this.residencyAllocated, false);
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
    if (this.mapState !== null) this.setMapMode(false);
    const planned = planDirectNavigationTransition(resolution, state, reducedMotion);
    if (target.kind === 'island') {
      const island = this.scene.islands.find((candidate) => candidate.islandId === target.islandId);
      if (island?.rung === 4) {
        // Keep atlas-core's validated destination POSITION exactly. Only turn the arrival camera
        // toward the canonical source body, so Map travel cannot deposit someone facing empty
        // layout space while the memory sits behind them.
        this.navigationTransition = Object.freeze({
          ...planned,
          to: sourceFirstArrivalPose(island, planned.to, this.sourcePresentation),
        });
      } else {
        this.navigationTransition = planned;
      }
    } else {
      this.navigationTransition = planned;
    }
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

  /** Engage exactly the one settled reticle target. The application decides which panel opens. */
  engageFocusedAnchor(): number | null {
    if (this.controls.mode !== 'traverse' || this.focusState.focusedIndex === null) return null;
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

  cameraPose(): CameraPose {
    const s = this.controls.state;
    return { position: atlasVec3(s.x, s.y, s.z), forward: this.controls.forward() };
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

    const s = this.controls.state;
    this.pose.position.set(
      s.x - this.renderOriginState.origin.x,
      s.y - this.renderOriginState.origin.y,
      s.z - this.renderOriginState.origin.z,
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
      this.field.setRenderOrigin(origin.x, origin.z);
      this.pose.position.set(s.x - origin.x, s.y - origin.y, s.z - origin.z);
      this.camera.setPosition(this.pose.position);
    }
    const signature = [
      this.mapState === null ? 'ground' : 'map',
      this.activeNeighborhood ?? '',
      this.navigationTargetIsland ?? '',
      ...[...this.tierState.tier.entries()].map(([id, tier]) => `${id}:${tier}`),
    ].join('|');
    if (signature !== this.residencySignature) {
      this.residencySignature = signature;
      const plan = planResidency(
        this.residencyCatalog,
        residencyDemandsForView(this.neighborhoodIndex, {
          map: this.mapState !== null,
          activeNeighborhood: this.activeNeighborhood,
          tier: this.tierState,
          target: this.navigationTargetIsland,
        }),
        {
          maxCost: this.residencyBudget * this.representationPressure.state.budgetScale,
          maxStage: this.representationPressure.state.maxStage,
        },
        this.residencyState,
      );
      this.residencyState = plan.state;
      // Install pending ids before handing actions to an executor: an honest missing/unsupported
      // descriptor may settle synchronously, and settling against the previous state would leave
      // the new request pending forever.
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
    }

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
    this.focusState = resolution.state;
    const focusedIslandId = this.controls.mode !== 'traverse' || this.focusState.focusedIndex === null
      ? null
      : (this.table.anchors[this.focusState.focusedIndex]?.islandId ?? null);
    this.sourceFirst.update(nowMs, cameraAtlas, focusedIslandId);
    this.field.update(nowMs);

    const cameraComponent = this.camera.camera;
    if (this.overlay !== null && cameraComponent !== undefined && cameraComponent !== null) {
      this.overlay.update({
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
    this.controls.destroy();
    this.overlay?.destroy();
    this.mapOverlay?.destroy();
    this.motes.destroy();
    this.field.destroy();
    this.sourceFirst.destroy();
    this.composedWorld.destroy();
    this.regionMass.destroy();
    this.regionRelief.destroy();
    for (const visual of this.islands) visual.cloud.destroy();
    for (const visual of this.trainedScenes) {
      visual.entity.destroy();
      visual.asset.unload();
      this.app.assets.remove(visual.asset);
    }
    this.app.destroy();
  }
}

/** Only this renderer input changes; the authoritative scene, source catalog, and topology stay intact. */
export function sourceGroveScene(
  scene: AtlasScene,
  availableReconstruction: ReadonlySet<IslandId>,
  sourcePresentation: 'world' | 'inspection' = 'world',
): AtlasScene {
  return { ...scene, islands: sourcePresentation === 'inspection' ? [] : scene.islands.map((island) =>
    availableReconstruction.has(island.islandId) ? island : { ...island, rung: 4 as const }) };
}

/** Preserve safe startup positions; only a visible in-world source may own the upward framing. */
export function initialAtlasCameraState(
  scene: AtlasScene,
  navigationWorld: NavigationWorld,
  sourcePresentation: 'world' | 'inspection' = 'world',
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
        if (sourcePresentation === 'inspection') {
          return { x, y: height + navigationWorld.eyeHeight, z, yaw: first.placement.yaw, pitch: -0.085 };
        }
        const sourceLocal = sourceFirstCardLocalPosition(first);
        const source = localToAtlas(first.placement, sourceLocal);
        const sourceHeight = atlasLandscapeHeight(source.x, source.z) +
          SOURCE_VEIL_HEIGHT * first.placement.scale;
        const horizontal = Math.max(1, Math.hypot(source.x - x, source.z - z));
        return {
          x,
          y: height + navigationWorld.eyeHeight,
          z,
          yaw: first.placement.yaw,
          pitch: Math.atan2(sourceHeight - (height + navigationWorld.eyeHeight), horizontal),
        };
      })();
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

/** Preserve the validated destination position while facing a rung-4 arrival toward its source. */
export function sourceFirstArrivalPose(
  island: Island,
  pose: NavigationPose,
  sourcePresentation: 'world' | 'inspection' = 'world',
): NavigationPose {
  if (sourcePresentation === 'inspection' || island.rung !== 4) return pose;
  const card = localToAtlas(island.placement, sourceFirstCardLocalPosition(island));
  const source = atlasVec3(
    card.x,
    atlasLandscapeHeight(card.x, card.z) + SOURCE_VEIL_HEIGHT * island.placement.scale,
    card.z,
  );
  const dx = source.x - pose.position.x;
  const dy = source.y - pose.position.y;
  const dz = source.z - pose.position.z;
  const horizontal = Math.max(1e-9, Math.hypot(dx, dz));
  return Object.freeze({
    position: pose.position,
    yaw: Math.atan2(-dx, -dz),
    pitch: Math.atan2(dy, horizontal),
  });
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
