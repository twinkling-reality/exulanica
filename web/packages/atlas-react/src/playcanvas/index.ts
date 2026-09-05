/**
 * The PlayCanvas renderer binding for the Atlas, and its bake-off harness.
 *
 * One of the two competing implementations of `@exulanica/atlas-react`'s renderer binding, per
 * ADR-0003. Everything engine-specific in the product is meant to live behind this barrel, so
 * that switching engines is a two-package change rather than a front-end rewrite.
 *
 * Nothing here decides what the world should look like. Tier selection, focus resolution, view
 * manifest application, layout and the coordinate frames all live in `@exulanica/atlas-core`. This
 * package converts those answers into PlayCanvas objects, and that is the whole job.
 */

export type { OpmHeader, OpmSection, OpmSegment, PointMap } from './opm.js';
export { decodeOpm, footprintRadiusOf, packedVertexBytes, sourcePanelEnvelopeOf } from './opm.js';

export type { PlacedScenePointMap } from './scene-point-maps.js';
export type { SceneInspectionView } from './scene-inspection.js';
export { sceneInspectionViews } from './scene-inspection.js';
export type { TrainedSceneGeometry } from './scene-splats.js';
export { validateSogBundle, validateTrainedSceneGeometry, trainedSceneFootprint } from './scene-splats.js';
export {
  opmPointInScene,
  scenePointMapFootprint,
  scenePointMapViewpoint,
  validateScenePointMapPlacement,
} from './scene-point-maps.js';

export type { SegmentSemantics } from './semantics.js';
export {
  MAX_SEGMENTS,
  PROVENANCE_SLOT,
  defaultSemanticsFor,
  isPresenceMarkerOnly,
  packSemantics,
  presenceMarkerSegmentIds,
} from './semantics.js';

export {
  POINT_FRAGMENT_GLSL,
  POINT_FRAGMENT_WGSL,
  POINT_VERTEX_GLSL,
  POINT_VERTEX_WGSL,
} from './point-shader.js';

export type { PointCloud, PointCloudOptions } from './point-cloud.js';
export { createPointCloud } from './point-cloud.js';

export type { CameraState, ControlsConfig, InputMode } from './controls.js';
export { DEFAULT_CONTROLS, FirstPersonControls } from './controls.js';

export type { AnchorMotes, AnchorMotesOptions } from './anchor-motes.js';
export {
  MOTE_FRAGMENT_GLSL,
  anchorKindSlot,
  createAnchorMotes,
  moteAnchorIndices,
} from './anchor-motes.js';

export type { SourceMediaCatalog, SourceMediaDescriptor } from './source-media.js';
export { sourceMediaForIsland } from './source-media.js';

export type { OverlayCounts, OverlayFrame } from './anchor-overlay.js';
export { AnchorOverlay } from './anchor-overlay.js';

export { MapRegionOverlay } from './map-region-overlay.js';

export type { RegionRelief, ReliefCell } from './region-relief.js';
export { createRegionRelief, sampleRelief } from './region-relief.js';

export { worldFieldBufferShape } from './world-field.js';

export type { ComposedWorld } from './composed-world.js';
export { createComposedWorld } from './composed-world.js';

export type { ClaimResult } from './probes.js';
export { probeAll, probeGlobalSort, probeSplatBudget, probeWebGpu } from './probes.js';

export type {
  AtlasBindingOptions,
  FrameReport,
  IslandVisual,
  PlacementCheck,
} from './atlas-binding.js';
export { AtlasBinding, mapCameraState, sourceFirstArrivalPose } from './atlas-binding.js';

export type {
  AssetAvailability,
  AssetBytes,
  AuthenticatedAssetFetchOptions,
  PhysicalAssetDescriptor,
  PhysicalResidencyAdapter,
  RangeOutcome,
  ResidencyPhysicalEvent,
} from './physical-residency.js';
export {
  PhysicalResidencyRuntime,
  fetchAuthenticatedAsset,
} from './physical-residency.js';

export type { BakeoffResult, HarnessConfig, HarnessHandle, PathMode } from './harness.js';
export { POINT_LADDER, fixtureName, parseConfig, runBakeoff } from './harness.js';
