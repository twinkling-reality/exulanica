/**
 * @exulanica/loom-gate
 *
 * Visual-gate key vocabulary, thresholds, and mechanical decisions for a browser run.
 * Numbers are pinned to the retained reconciliation record; this package restates them
 * so a harness can decide without a Python process.
 */

export {
  AWAITING_JUDGE,
  CANONICAL_KEYS,
  CAPTURE_LABELS,
  DECIDED_BY,
  GATE_KEY_SET_VERSION,
  GateEvidenceError,
  JUDGED_KEY,
  MELBOURNE_ENVELOPE,
  THRESHOLDS,
  decideKeySet,
  decideMechanical,
  millimetres,
  type CanonicalKey,
  type CaptureLabel,
  type KeySetValue,
  type Measured,
  type MechanicalKey,
} from './keys.js';
export {
  closestPointOnTriangle,
  heightOnTriangle,
  pointInRing,
  pointSegmentDistance2,
  pointTriangleDistance,
  ringEdgeDistance,
  segmentIntersectsTriangle,
  segmentSegmentDistance,
  segmentTriangleDistance,
  triangleNormal,
  type Point2,
  type Vec3,
} from './geometry.js';
export { PlanarGrid } from './grid.js';
export {
  SupportSamples,
  TriangleTable,
  classify,
  componentQueryPoints,
  components,
  drawnSupport,
  integrity,
  type Classification,
  type Component,
  type CullMode,
  type DrawnMesh,
  type IntegrityMeasurement,
  type ObstaclePrism,
  type RouteRing,
} from './scene.js';
export {
  ROUTE_RULE,
  firstContact,
  measureCapsule,
  measureWalk,
  planRoute,
  rankedRoutes,
  resampleTrace,
  sampleQueryPoints,
  type CapsuleMeasurement,
  type FieldBounds,
  type RoutePlan,
  type RouteRule,
  type RouteSample,
  type TracePose,
  type WalkMeasurement,
} from './route.js';
export {
  keySet,
  mechanicalMeasurements,
  measureScene,
  type CaptureObservation,
  type RunObservation,
  type SceneInput,
  type SceneMeasurement,
} from './measure.js';
