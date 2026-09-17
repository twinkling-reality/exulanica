/**
 * @exulanica/atlas-core
 *
 * The scene graph, island frames, focus resolution, view manifest application and the layout
 * solver. Pure TypeScript: no React, no DOM, no renderer.
 *
 * The DOM ban is enforced by `lib: ["ES2022"]` in this package's tsconfig rather than by lint,
 * because `document` is a global and not an import. The React and renderer bans are enforced by
 * `.dependency-cruiser.cjs`.
 *
 * NOTE ON WHAT IS NOT EXPORTED HERE. There is no distance function over `AtlasVec3` in this
 * barrel, and no `atlasToLocal`. An island's atlas position is a layout artifact and reading it
 * as geometry is risk R-48. The layout and focus solvers need atlas-space distance and get it
 * from `@exulanica/atlas-core/presentation-metrics`, which the query layer may not import.
 */

export type { Brand } from './brand.js';

export type {
  AnchorId,
  EntityId,
  EvidenceRef,
  IslandId,
  NeighborhoodId,
  ManifestId,
  OccurrenceId,
  SegmentId,
} from './ids.js';
export {
  anchorId,
  entityId,
  evidenceRef,
  islandId,
  neighborhoodId,
  manifestId,
  occurrenceId,
  segmentId,
} from './ids.js';

export type { AnyVec3, AtlasVec3, IslandPlacement, LocalVec3, MetricVec3 } from './coords.js';
export {
  ATLAS_ORIGIN,
  CAPTURE_FORWARD_LOCAL,
  LOCAL_ORIGIN,
  add,
  atlasVec3,
  dot,
  lengthOf,
  localDirectionToAtlas,
  localDistance,
  localToAtlas,
  localVec3,
  metricAsLocal,
  metricDistance,
  metricVec3,
  normalize,
  placement,
  scale,
  sub,
} from './coords.js';

export type { MovementModel, ReconstructionRung, RungProperties } from './rung.js';
export { SINGLE_PHOTO_RUNG, rungProperties } from './rung.js';

export type { CorridorArtifactWire, ValidatedCorridorRule } from './corridor.js';
export { constrainCorridorLook, corridorRuleFromArtifact } from './corridor.js';

export type { ConfidenceBand, LinkState, ProvenanceClass } from './provenance.js';
export { contributesToLayout, isConfirmed, readsAsUnconfirmed } from './provenance.js';

export type { Anchor, AnchorKind } from './anchor.js';
export { rendersAsPresenceMarker } from './anchor.js';

export type { Island, IslandSpec } from './island.js';
export {
  DISSOLVE_BAND_FRACTION,
  asMetricLocal,
  dissolveBandParameter,
  islandRung,
  makeIsland,
} from './island.js';

export type { AnchorTable, AtlasScene } from './scene.js';
export { anchorAtlasPosition, buildAnchorTable, makeScene } from './scene.js';

export type { EmphasisLevel } from './emphasis.js';
export { EMPHASIS_SCALAR, emphasisImportance, isInteractable, isLabelable } from './emphasis.js';

export type { RepresentationTier, TierState } from './tiers.js';
export {
  EMPTY_TIER_STATE,
  MAX_TIER_3_ISLANDS,
  TIER_DEMOTE_FACTOR,
  TIER_PROMOTE_AU,
  mapTierState,
  resolveTiers,
} from './tiers.js';

export type {
  ManifestCaption,
  ManifestEmphasis,
  ManifestQuery,
  ManifestSummary,
  ManifestThread,
  ManifestTransition,
  QueryKind,
  SummaryCount,
  ThreadStyle,
  ViewManifest,
} from './manifest/types.js';
export { MAX_CAPTIONS, MAX_EDGE_CHEVRONS, MAX_FOCUS_LABELS } from './manifest/types.js';

export type { EmphasisBuffers, EmphasisFrame } from './manifest/apply.js';
export {
  LEVEL_ORDER,
  ManifestValidationError,
  allocateEmphasisBuffers,
  applyViewManifest,
  applyViewManifestInto,
  levelAt,
  neutralEmphasis,
  validateManifest,
} from './manifest/apply.js';

export type {
  ConjunctionQueryResult,
  DisjunctionQueryResult,
  EntityQueryResult,
  ManifestIdentity,
  ProposalPreview,
} from './manifest/build.js';
export {
  buildConjunctionManifest,
  buildDisjunctionManifest,
  buildEntityManifest,
  buildPreviewManifest,
} from './manifest/build.js';

export type { ManifestState } from './manifest/stack.js';
export {
  EMPTY_MANIFEST_STATE,
  clearPreview,
  clearStack,
  pinManifest,
  popManifest,
  pushManifest,
  resolveActive,
  setPreview,
  staleManifests,
} from './manifest/stack.js';

export type {
  CameraPose,
  FocusCandidate,
  FocusConfig,
  FocusInputs,
  FocusResolution,
  FocusState,
  VisibilityTest,
} from './focus/solver.js';
export {
  DEFAULT_FOCUS_CONFIG,
  INITIAL_FOCUS_STATE,
  focusDirectly,
  forwardFromYawPitch,
  latchFocus,
  releaseFocus,
  resolveFocus,
  tabOrder,
} from './focus/solver.js';
export { IMPORTANCE_WEIGHTS, deriveImportance, occurrenceNormalizer } from './focus/importance.js';

export type {
  CircleObstacle,
  CorridorRule,
  GroundMovementInput,
  GroundMovementResolution,
  MapPresentationState,
  NavigationPose,
  NavigationRegion,
  NavigationSurface,
  NavigationWorld,
  PolygonObstacle,
  OpenTraversalRule,
  RegionTraversalRule,
  SemanticTrace,
  SpatialClassification,
  SpatialPhase,
  SurfaceNormal,
  SurfaceSample,
} from './navigation.js';

export type {
  OwnedDistrict,
  OwnedDistrictBuilding,
  OwnedDistrictMaterial,
  OwnedDistrictSidewalk,
} from './owned-district.js';
export { ownedDistrictNavigation, parseOwnedDistrict } from './owned-district.js';
export type {
  PointBasis,
  RepresentationAvailability,
  RepresentationBounds,
  RepresentationIntent,
  RepresentationOrigin,
  RepresentationResolution,
  RepresentationSubject,
} from './representation.js';
export type {
  GeneratedAnonymousRecordKind,
  GeneratedIdentityRecordKind,
  GeneratedRecordPayload,
  GeneratedRecordRegistration,
  GeneratedRecordSubjectResult,
  GeneratedTileReference,
  RepresentationBlend,
  RepresentationBoundsBasis,
  RepresentationRecordReference,
} from './representation.js';
export {
  DEFAULT_REPRESENTATION_INTENT,
  artifactByteWindow,
  districtRepresentationSubjects,
  representationBinaryVisualization,
  representationIntent,
  representationSampleIndices,
  resolveRepresentation,
  validateRepresentationSubject,
} from './representation.js';
export {
  GENERATED_ANONYMOUS_RECORD_KINDS,
  GENERATED_IDENTITY_RECORD_KINDS,
  REPRESENTATION_POINT_BUDGET,
  REPRESENTATION_POINTS_PER_SUBJECT,
  generatedRecordSubject,
  representationColourKey,
} from './representation.js';
export type {
  GeneratedDressing,
  GeneratedMaterialStatement,
  GeneratedRecordEntry,
  GeneratedSurfaceStatement,
  RepresentationRecordSurface,
  GeneratedRecordRegistrationV2,
  GeneratedTileReferenceV2,
} from './representation.js';
export {
  GENERATED_CITY_FRAME,
  generatedDressing,
  generatedRecordSubjectV2,
  generatedTileFrameId,
} from './representation.js';
export type { DataViewHex, DataViewKindKey, DataViewOriginKey, DataViewStyle } from './data-view-style.js';
export {
  DATA_VIEW_STYLE,
  DATA_VIEW_STYLE_V1,
  DATA_VIEW_STYLE_V2,
  dataViewKindColour,
  dataViewRgb,
  dataViewStyle,
  dataViewStyleName,
  isDataViewKindKey,
} from './data-view-style.js';
export {
  DEFAULT_CAMERA_RADIUS_AU,
  DEFAULT_EYE_HEIGHT_AU,
  DEFAULT_MAXIMUM_SLOPE_DEGREES,
  DEFAULT_MAXIMUM_STEP_HEIGHT_AU,
  DEFAULT_SURFACE_SAMPLE_SPACING_AU,
  FIELD_MARGIN_AU,
  RECOVERY_MARGIN_AU,
  REGION_APPROACH_AU,
  atlasMapPose,
  buildNavigationWorld,
  classifySpatialPhase,
  constrainRegionTraversal,
  enterAtlasMap,
  exitAtlasMap,
  flatNavigationSurface,
  isNavigationGroundPathContinuous,
  isNavigationLineVisible,
  isNavigationPathClear,
  isNavigationPositionClear,
  navigationRegionForIsland,
  resolveGroundMovement,
} from './navigation.js';

export type {
  DirectNavigationFailureReason,
  DirectNavigationResolution,
  DirectNavigationTarget,
  DirectNavigationTransition,
} from './direct-navigation.js';
export {
  DIRECT_NAVIGATION_DURATION_MS,
  planDirectNavigationTransition,
  resolveDirectNavigation,
  sampleDirectNavigationTransition,
} from './direct-navigation.js';

export type {
  Neighborhood,
  NeighborhoodIndex,
  NeighborhoodOptions,
  NeighborhoodRoute,
  NeighborhoodSnapshotVersion,
} from './neighborhood.js';
export {
  DEFAULT_MAX_SEMANTIC_ROUTES_PER_NEIGHBORHOOD,
  DEFAULT_NEIGHBORHOOD_CAPACITY,
  DEFAULT_SEMANTIC_ENTITY_FANOUT_LIMIT,
  buildNeighborhoodIndex,
  snapshotNeighborhoodIndex,
} from './neighborhood.js';

export type {
  AtlasNeighborhoodMembership,
  AtlasNeighborhoodReason,
  AtlasNeighborhoodSnapshot,
  NeighborhoodCoverage,
} from './neighborhood-snapshot.js';
export {
  ATLAS_NEIGHBORHOOD_SCHEMA_VERSION,
  AtlasNeighborhoodValidationError,
  inspectNeighborhoodCoverage,
  makeAtlasNeighborhoodSnapshot,
  parseAtlasNeighborhoodSnapshot,
} from './neighborhood-snapshot.js';

export type {
  ResidencyAction,
  ResidencyAsset,
  ResidencyBudget,
  ResidencyCost,
  ResidencyDemand,
  ResidencyEntry,
  ResidencyPlan,
  ResidencyRequest,
  ResidencyStage,
  ResidencyState,
  ResidencyView,
} from './residency.js';

export type {
  PressureSample,
  RepresentationPressureState,
} from './performance-pressure.js';
export { RepresentationPressureController } from './performance-pressure.js';

export type { RenderOriginState } from './render-origin.js';
export {
  INITIAL_RENDER_ORIGIN,
  renderOriginForNeighborhood,
} from './render-origin.js';
export {
  DEFAULT_RESIDENCY_GRACE_REVISIONS,
  EMPTY_RESIDENCY_STATE,
  RESIDENCY_STAGE_ORDER,
  completeResidencyRequest,
  planResidency,
  residencyDemandsForView,
} from './residency.js';

export type {
  LayoutConfig,
  LayoutFrame,
  LayoutInputIsland,
  LayoutMove,
  LayoutResult,
  LayoutStrategy,
} from './layout/solver.js';
export {
  DEFAULT_LAYOUT_CONFIG,
  LAYOUT_FRAME,
  LAYOUT_GLIDE_MS,
  LayoutScopeError,
  MAX_ISLANDS,
  solveLayout,
} from './layout/solver.js';
export { GOLDEN_ANGLE, phyllotaxisSeed } from './layout/phyllotaxis.js';
export type { SeedPoint } from './layout/phyllotaxis.js';
export {
  layoutEntitiesOf,
  semanticSimilarity,
  sharedLayoutEntityCount,
} from './layout/similarity.js';
export type {
  AtlasLayoutEntry,
  AtlasLayoutReason,
  AtlasLayoutSnapshot,
  LayoutCoverage,
} from './layout/snapshot.js';
export {
  ATLAS_LAYOUT_SCHEMA_VERSION,
  AtlasLayoutValidationError,
  inspectLayoutCoverage,
  layoutCreationOrdinals,
  layoutPlacements,
  makeAtlasLayoutSnapshot,
  nextCreationOrdinal,
  parseAtlasLayoutSnapshot,
} from './layout/snapshot.js';

export type {
  ModuleAccessibilityContract,
  ModuleBounds,
  ModuleCollisionContract,
  ModuleEvidenceRequirement,
  ModuleLodVariants,
  ModuleNavigationContract,
  ModuleSocket,
  WorldCustomizationAxis,
  WorldModuleDefinition,
  WorldModuleRole,
} from './world/module-registry.js';
export { WorldModuleRegistry } from './world/module-registry.js';
export type {
  WorldEvidenceFormKind,
  WorldExpansionFormKind,
  WorldLandmarkFormKind,
  WorldModuleForm,
  WorldModuleFormKind,
} from './world/module-form.js';
export {
  WORLD_DECLARABLE_FORM_KINDS,
  WORLD_EVIDENCE_FORM_KINDS,
  WORLD_EXPANSION_FORM_KINDS,
  WORLD_FORM_KINDS_BY_ROLE,
  WORLD_LANDMARK_FORM_KINDS,
  WORLD_MODULE_FORM_KINDS,
  WORLD_UNRENDERED_FORM_KINDS,
  moduleFormFailure,
} from './world/module-form.js';

export type {
  WorldRecipeAttachment,
  WorldRecipeDefinition,
  WorldRecipeSlot,
} from './world/recipe-registry.js';
export { WorldRecipeRegistry } from './world/recipe-registry.js';

export {
  DEFAULT_WORLD_MODULE_CATALOG_VERSION,
  DEFAULT_WORLD_MODULES,
  DEFAULT_WORLD_RECIPE_CATALOG_VERSION,
  DEFAULT_WORLD_RECIPES,
} from './world/default-catalog.js';

export type {
  ComposeWorldOptions,
  WorldElementCause,
  WorldElementOrigin,
  WorldElementOwner,
  WorldElementProvenance,
  WorldModuleAttachment,
  WorldModuleInstance,
  WorldNavigationDestination,
  WorldNavigationEdge,
  WorldNavigationGraph,
  WorldPathGeometry,
  WorldTopologyDiagnostic,
  WorldTopologySnapshot,
  WorldTransform,
} from './world/composer.js';
export {
  ATLAS_COMPOSER_KEY,
  ATLAS_COMPOSER_VERSION,
  DEFAULT_WORLD_ID,
  WORLD_TOPOLOGY_SCHEMA_VERSION,
  WorldTopologyValidationError,
  composeAtlasWorld,
  topologyReachability,
  validateWorldTopology,
} from './world/composer.js';

export type {
  SpatialAuthorityCandidateDraft,
  SpatialAuthorityDraftOptions,
  SpatialDependency,
  SpatialEvidenceBinding,
} from './world/persistence.js';
export { toSpatialAuthorityCandidateDraft } from './world/persistence.js';

export type {
  WorldAppearanceProposal,
  WorldCustomizationControllerOptions,
  WorldCustomizationProposal,
  WorldPreviewSession,
  WorldProposalIssue,
  WorldProposalIssueCode,
  WorldProposalKind,
  WorldProposalOrigin,
  WorldProposalScope,
  WorldProposalValidation,
  WorldRegionStyleOverride,
  WorldStructuralProposal,
  WorldStyleCatalog,
  WorldStyleDescriptor,
  WorldStyleParameterDefinition,
  WorldStyleParameterValue,
  WorldStyleReference,
  WorldStyleResolution,
  WorldStyleVersion,
} from './world/customization.js';
export {
  WorldCustomizationController,
  resolveWorldStyleVersion,
} from './world/customization.js';

export type { FanVec3, UnmeasuredFanInput } from './unmeasured-fan.js';
export {
  UNMEASURED_FAN_GAP_DEG,
  UNMEASURED_FAN_MAX_SWEEP_DEG,
  frameFraction,
  horizontalFovDeg,
  unmeasuredFan,
} from './unmeasured-fan.js';

export type { CameraPoseSample, SceneDisplayFrame, UpMethod } from './display-frame.js';
export {
  DISPLAY_EYE_HEIGHT,
  colmapCameraSample,
  composeDisplayFrame,
  displayCameraTransform,
  identityDisplayFrame,
  opmCameraSample,
  sceneDisplayFrame,
  transformDirection,
  transformPoint,
  transformedBoxCorners,
} from './display-frame.js';

export type {
  PickCalibration,
  PickResult,
  SparseObservedPoint,
} from './observation-pick.js';
export {
  canvasToSourcePixel,
  observationSentence,
} from './observation-pick.js';

export type {
  BehaviourDefinition,
  BehaviourParameterDescriptor,
  BehaviourParameterResolution,
  BehaviourParameters,
  BehaviourResolution,
} from './behaviour/registry.js';
export {
  BEHAVIOUR_REGISTRY,
  BOUNDED_PATH_KEY,
  BOUNDED_PATH_VERSION,
  BehaviourRegistry,
} from './behaviour/registry.js';

export type {
  BoundedPath,
  MotionAxis,
  MotionEasing,
  MotionOffset,
  MotionState,
} from './behaviour/bounded-motion.js';
export {
  BoundedMotion,
  NO_MOTION_OFFSET,
  boundedPathOf,
  isAtAuthoredOffset,
  motionOffsetAt,
  motionTransform,
  travelFraction,
} from './behaviour/bounded-motion.js';

export type { DistrictPoint } from './district-geometry.js';
export { districtSegmentSupported } from './district-geometry.js';
export type {
  DistrictRecipe, DistrictSubject, DistrictFrame, DistrictNavigation, DistrictInterpretation,
} from './district-interpretation.js';
export {
  districtCanonicalJson, parseDistrictInterpretation,
  districtInterpretationAvailability, districtShortestRoute,
} from './district-interpretation.js';

// Shared character representation; subject identity and appearance remain separate.
export {
  CHARACTER_PROFILE,
  ABSTRACT_CHARACTER_RIG,
  DEFAULT_CHARACTER_BODY,
  DEFAULT_CHARACTER_APPEARANCE,
  parseCharacterRepresentation,
  characterSubjectKey,
  validateCharacterReplacement,
  resolveCharacterRepresentation,
} from './character.js';
export type {
  CharacterSubject,
  CharacterOrigin,
  CharacterMotion,
  CharacterSourceRef,
  CharacterBodyTrait,
  CharacterTraitProvenance,
  CharacterBody,
  AbstractCharacterAppearance,
  CharacterAppearance,
  CharacterRepresentation,
  CharacterSourceAvailability,
  CharacterResolutionContext,
  ResolvedCharacterRepresentation,
} from './character.js';

export type {
  DecodedTextureSet,
  MakerKind,
  MaterialClass,
  TextureManifestProfile,
  TextureMapName,
  TextureSetChannel,
  TextureSetClassParameters,
  TextureSetDigest,
  TextureSetManifest,
  TextureSetManifestEntry,
  TextureSetProfile,
  TextureSetRefusalReason,
  TextureSetSurface,
} from './texture-set.js';
export {
  MAKER_KINDS,
  MATERIAL_CLASSES,
  TEXTURE_MANIFEST_PROFILE_V1,
  TEXTURE_MANIFEST_PROFILE_V2,
  TEXTURE_SET_ALPHA_CUTOFF,
  TEXTURE_SET_GLAZING_IOR_MILLIONTHS,
  TEXTURE_SET_LICENCE_ID,
  TEXTURE_SET_MAGIC,
  TEXTURE_SET_MEDIA_TYPE,
  TEXTURE_SET_NORMAL_CONVENTION,
  TEXTURE_SET_PROFILE_V1,
  TEXTURE_SET_PROFILE_V2,
  TEXTURE_SET_TRUTH,
  TextureSetRefusal,
  decodeTextureSet,
  ambientTextureSetDigest,
  parseTextureSetManifest,
  textureSetBlobPath,
} from './texture-set.js';
