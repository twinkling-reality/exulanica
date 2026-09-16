/**
 * One run, measured: the drawn scene and the walked route in, the eight mechanical keys out.
 *
 * The product's navigation support is sampled by the caller, because only the running page can
 * ask it. This module says which points it needs and waits for the answer; it never guesses a
 * height it was not given.
 */

import {
  CAPTURE_LABELS,
  DECIDED_BY,
  THRESHOLDS,
  decideKeySet,
  type CanonicalKey,
  type CaptureLabel,
  type KeySetValue,
  type MechanicalKey,
  type Measured,
} from './keys.js';
import {
  measureCapsule,
  measureWalk,
  resampleTrace,
  sampleQueryPoints,
  type CapsuleMeasurement,
  type RoutePlan,
  type TracePose,
  type WalkMeasurement,
} from './route.js';
import {
  SupportSamples,
  TriangleTable,
  classify,
  componentQueryPoints,
  components,
  integrity,
  type Classification,
  type DrawnMesh,
  type IntegrityMeasurement,
  type ObstaclePrism,
} from './scene.js';

export interface SceneInput {
  readonly meshes: readonly DrawnMesh[];
  readonly prisms: readonly ObstaclePrism[];
  readonly plan: RoutePlan;
  /** The live per-frame positions of the walk, in order, from the product's own state. */
  readonly poses: readonly TracePose[];
  /** Ask the running product for its navigation support at x/z pairs; null where it has none. */
  readonly sampleSupport: (points: Float64Array) => Promise<readonly (number | null)[]>;
}

export interface SceneMeasurement {
  readonly drawnTriangles: number;
  readonly drawnMeshes: number;
  readonly walkingTriangles: number;
  readonly facadeTriangles: number;
  readonly untexturedWalkingTriangles: number;
  readonly untexturedFacadeTriangles: number;
  readonly classifiedByMesh: Classification['byMesh'];
  readonly texturedMeshes: number;
  readonly supportSamplesQueried: number;
  readonly integrity: IntegrityMeasurement;
  readonly walk: WalkMeasurement;
  readonly capsule: CapsuleMeasurement;
}

function concatenate(parts: readonly Float64Array[]): Float64Array {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Float64Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

export async function measureScene(input: SceneInput): Promise<SceneMeasurement> {
  const table = new TriangleTable(input.meshes);
  const parts = components(table);
  const samples = resampleTrace(input.poses, THRESHOLDS.supportSampleSpacingMm / 1000);
  const points = concatenate([
    table.centroidQueryPoints(),
    componentQueryPoints(parts.list),
    sampleQueryPoints(samples),
  ]);
  const heights = await input.sampleSupport(points);
  const support = new SupportSamples(points, heights);
  const classification = classify(table, input.prisms, support);
  return {
    drawnTriangles: table.count,
    drawnMeshes: input.meshes.length,
    walkingTriangles: classification.walkingTriangles,
    facadeTriangles: classification.facadeTriangles,
    untexturedWalkingTriangles: classification.untexturedWalkingTriangles,
    untexturedFacadeTriangles: classification.untexturedFacadeTriangles,
    classifiedByMesh: classification.byMesh,
    texturedMeshes: input.meshes.filter((mesh) => mesh.hasUv && mesh.decodedTextureBytes > 0).length,
    supportSamplesQueried: heights.length,
    integrity: integrity(table, classification, input.prisms, parts, support),
    walk: measureWalk(input.plan, input.poses, samples, table, classification, support),
    capsule: measureCapsule(samples, table, classification, input.prisms),
  };
}

export interface CaptureObservation {
  readonly label: CaptureLabel;
  readonly companionShown: boolean;
  readonly reticleCentred: boolean;
  readonly inProductShell: boolean;
}

/** What the harness observed in the live page, as counts. */
export interface RunObservation {
  readonly captures: readonly CaptureObservation[];
  readonly foreignListeners: number;
  readonly productWindowKeydownListeners: number;
  readonly interactionsNotCarriedByProduct: number;
  readonly substitutedPages: number;
  readonly recoveryEvents: number;
  readonly harnessPositionWrites: number;
  readonly environmentTransferredBytes: number;
  readonly environmentDecodedTextureBytes: number;
  readonly maxDrawCalls: number;
  readonly gpuErrors: number;
  readonly pageErrors: number;
}

export function mechanicalMeasurements(
  scene: SceneMeasurement,
  run: RunObservation,
): Readonly<Record<MechanicalKey, Measured>> {
  const labels = run.captures.map((capture) => capture.label);
  if (labels.join() !== CAPTURE_LABELS.join()) {
    throw new Error(`captures must be ${CAPTURE_LABELS.join(', ')} in order, got ${labels.join(', ')}`);
  }
  const count = (predicate: (capture: CaptureObservation) => boolean): number =>
    run.captures.filter(predicate).length;
  const all: Readonly<Record<string, number>> = {
    streetAndFacadeTriangles: scene.walkingTriangles + scene.facadeTriangles,
    untexturedStreetAndFacadeTriangles:
      scene.untexturedWalkingTriangles + scene.untexturedFacadeTriangles,
    routeSupportGapSamples: scene.walk.routeSupportGapSamples,
    ringEdgesWithoutDrawnFacade: scene.integrity.ringEdgesWithoutDrawnFacade,
    componentsDetachedFromSupport: scene.integrity.componentsDetachedFromSupport,
    trianglesInsideBuildings: scene.integrity.trianglesInsideBuildings,
    walkedDisplacementMm: scene.walk.walkedDisplacementMm,
    maxLateralDeviationMm: scene.walk.maxLateralDeviationMm,
    recoveryEvents: run.recoveryEvents,
    harnessPositionWrites: run.harnessPositionWrites,
    traceSamples: scene.walk.traceSamples,
    maxEyeHeightErrorMm: scene.walk.maxEyeHeightErrorMm,
    maxSupportResampleDeltaMm: scene.walk.maxSupportResampleDeltaMm,
    capsuleSamples: scene.capsule.capsuleSamples,
    capsuleSamplesChecked: scene.capsule.capsuleSamplesChecked,
    capsuleTriangleContactSamples: scene.capsule.capsuleTriangleContactSamples,
    capsuleRingContactSamples: scene.capsule.capsuleRingContactSamples,
    environmentTransferredBytes: run.environmentTransferredBytes,
    drawnTriangles: scene.drawnTriangles,
    environmentDecodedTextureBytes: run.environmentDecodedTextureBytes,
    maxDrawCalls: run.maxDrawCalls,
    gpuErrors: run.gpuErrors,
    pageErrors: run.pageErrors,
    captures: run.captures.length,
    capturesWithCompanionShown: count((capture) => capture.companionShown),
    capturesWithReticleCentred: count((capture) => capture.reticleCentred),
    capturesInProductShell: count((capture) => capture.inProductShell),
    foreignListeners: run.foreignListeners,
    productWindowKeydownListeners: run.productWindowKeydownListeners,
    interactionsNotCarriedByProduct: run.interactionsNotCarriedByProduct,
    substitutedPages: run.substitutedPages,
  };
  const measured = {} as Record<MechanicalKey, Measured>;
  for (const key of Object.keys(DECIDED_BY) as MechanicalKey[]) {
    const fields: Record<string, number> = {};
    for (const field of DECIDED_BY[key]) {
      const value = all[field];
      if (value === undefined) throw new Error(`${key}: ${field} was not measured`);
      fields[field] = value;
    }
    measured[key] = Object.freeze(fields);
  }
  return Object.freeze(measured);
}

export function keySet(
  measured: Readonly<Record<MechanicalKey, Measured>>,
): Readonly<Record<CanonicalKey, KeySetValue>> {
  return decideKeySet(measured);
}
