/**
 * The bounded route: how it is chosen, how the walked trace is resampled, and what is measured
 * along it.
 *
 * **The route is chosen by a rule, before anything is captured.** From the product's own arrival
 * pose, every heading at half-degree steps is tried; a heading qualifies when a 0.34 m capsule can
 * travel the route length plus a stopping margin without touching a collision ring or leaving the
 * walkable field; among those, the heading with the most 1 m samples that have a collision ring
 * within the frontage search distance on BOTH sides wins, then the one most parallel to the
 * frontage those side rays hit, then the smaller angle. So a route cannot be picked to flatter or
 * to damn what it looks at, and a corridor is walked by the same rule from its own arrival pose.
 *
 * Rejected: breaking ties on the longest clear run. A ray skewed a degree or two off a street
 * reaches a far boundary a little later than the ray along it, so that rule walks diagonally
 * across the street it was meant to walk down.
 *
 * Headings use the product's yaw convention: at yaw y the player moves along (-sin y, -cos y).
 */

import {
  pointInRing,
  ringEdgeDistance,
  segmentTriangleDistance,
  type Point2,
  type Vec3,
} from './geometry.js';
import { THRESHOLDS, millimetres } from './keys.js';
import {
  drawnSupport,
  type Classification,
  type ObstaclePrism,
  type RouteRing,
  type SupportSamples,
  type TriangleTable,
} from './scene.js';
import { PlanarGrid } from './grid.js';

export interface RouteRule {
  readonly lengthMm: number;
  /** Extra clear run beyond the route length, so a player released at the end can stop. */
  readonly stopMarginMm: number;
  readonly frontageSearchMm: number;
  readonly headingStepMillidegrees: number;
  readonly frontageSampleSpacingMm: number;
}

export const ROUTE_RULE: RouteRule = Object.freeze({
  lengthMm: THRESHOLDS.routeLengthMm,
  stopMarginMm: 6_000,
  frontageSearchMm: THRESHOLDS.frontageSearchMm,
  headingStepMillidegrees: 500,
  frontageSampleSpacingMm: 1_000,
});

export interface RoutePlan {
  readonly rule: RouteRule;
  readonly start: Point2;
  readonly headingMillidegrees: number;
  readonly yaw: number;
  readonly forward: Point2;
  /** Perpendicular to forward, pointing to the player's right. */
  readonly right: Point2;
  readonly clearRunMm: number;
  readonly frontageSamples: number;
  readonly frontageBothSidesSamples: number;
  /** Mean |sin| between the heading and the frontage edges the side rays hit, in millionths. */
  readonly meanFrontageSkewMillionths: number;
  readonly candidatesTried: number;
  readonly candidatesQualified: number;
  /**
   * How many qualifying headings had frontage on both sides at any sample. A DIAGNOSTIC, read by
   * nothing in the rule.
   *
   * It separates the rule running from the rule deciding. Where this is zero the first tie-break
   * was equal for every candidate and a later one chose, so the heading is the rule's fallback
   * rather than its preference, and a record that showed only the chosen heading would read as a
   * decision either way.
   */
  readonly candidatesWithFrontage: number;
}

/** No clear run is measured beyond this, which is longer than any field the gate walks. */
const CLEAR_RUN_LIMIT = 5_000;

/** The walkable field as the product bounds it: [west, north, east, south] in metres. */
export type FieldBounds = readonly [number, number, number, number];

function forwardOf(yaw: number): Point2 {
  return [-Math.sin(yaw), -Math.cos(yaw)];
}

function rightOf(yaw: number): Point2 {
  return [Math.cos(yaw), -Math.sin(yaw)];
}

interface Edge {
  readonly a: Point2;
  readonly b: Point2;
}

function edgesOf(prisms: readonly RouteRing[]): Edge[] {
  const edges: Edge[] = [];
  for (const prism of prisms) {
    for (let k = 1; k < prism.ring.length; k += 1) {
      const a = prism.ring[k - 1]!;
      const b = prism.ring[k]!;
      if (Math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-9) continue;
      edges.push({ a, b });
    }
  }
  return edges;
}

/** Distance along a ray until a disc of `radius` first touches an edge, or `limit`. */
export function firstContact(
  start: Point2,
  direction: Point2,
  radius: number,
  edges: readonly Edge[],
  bounds: FieldBounds,
  limit: number,
): number {
  const [sx, sz] = start;
  const [fx, fz] = direction;
  let best = limit;
  for (const { a, b } of edges) {
    for (const p of [a, b]) {
      const ox = sx - p[0];
      const oz = sz - p[1];
      const half = ox * fx + oz * fz;
      const c = ox * ox + oz * oz - radius * radius;
      const disc = half * half - c;
      if (disc < 0) continue;
      const t = -half - Math.sqrt(disc);
      if (t >= 0 && t < best) best = t;
      if (c < 0) best = 0;
    }
    const ex = b[0] - a[0];
    const ez = b[1] - a[1];
    const length = Math.hypot(ex, ez);
    const ux = ex / length;
    const uz = ez / length;
    const nx = -uz;
    const nz = ux;
    for (const side of [1, -1]) {
      const px = a[0] + nx * radius * side;
      const pz = a[1] + nz * radius * side;
      const denominator = fx * nx + fz * nz;
      if (Math.abs(denominator) < 1e-12) continue;
      const t = ((px - sx) * nx + (pz - sz) * nz) / denominator;
      if (t < 0 || t >= best) continue;
      const along = (sx + fx * t - a[0]) * ux + (sz + fz * t - a[1]) * uz;
      if (along >= 0 && along <= length) best = t;
    }
  }
  // THE FACE THE RAY LEAVES BY, one per axis, chosen from the sign of its own component.
  //
  // MEASURED 2026-09-18: this tested all four faces and kept a crossing only where t was strictly
  // positive, so a start lying EXACTLY on a face gave t of zero there and the ray was never bounded
  // by the edge it stood on. A generated tile's default pose is the middle of its southern edge, so
  // 117 southward headings of 720 "cleared" 132 m off the tile and qualified: 153 qualified against
  // the 36 that do one millimetre inside. The same on the west edge, 160 against 43.
  //
  // The inequality alone cannot fix it either way, which is why the faces are chosen rather than the
  // comparison loosened. On a boundary pointing INWARD, edge minus origin is also zero, and a bare
  // `t >= 0` would bound that ray at nothing. Taking the face the ray exits by makes t zero only for
  // a start on the face it is LEAVING through, which is the case that should bound at zero, so
  // `t >= 0` is then correct rather than a guess. For a start strictly inside, the two faces behind
  // the ray give negative t and were already discarded, so this returns the identical answer: pinned
  // at five interior starts, every field of the plan unchanged, and the pin falsified by choosing
  // the wrong face, which moves all five.
  //
  // The vertex branch above has always written `t >= 0`. The two halves of this function disagreed
  // about what a zero distance means, and this is the half that was wrong.
  const [west, north, east, south] = bounds;
  for (const [face, component, origin] of [
    [fx > 0 ? east : west, fx, sx], [fz > 0 ? south : north, fz, sz],
  ] as const) {
    if (Math.abs(component) < 1e-12) continue;
    const t = (face - origin) / component;
    if (t >= 0 && t < best) best = t;
  }
  return best;
}

/** The first edge a ray crosses within `limit`, and how far along it, or null. */
function firstCrossing(
  start: Point2,
  direction: Point2,
  edges: readonly Edge[],
  grid: PlanarGrid,
  limit: number,
): { readonly distance: number; readonly edge: number } | null {
  const [sx, sz] = start;
  const [fx, fz] = direction;
  const ex = sx + fx * limit;
  const ez = sz + fz * limit;
  let best: { distance: number; edge: number } | null = null;
  grid.query(Math.min(sx, ex), Math.min(sz, ez), Math.max(sx, ex), Math.max(sz, ez), (index) => {
    const { a, b } = edges[index]!;
    const dx = b[0] - a[0];
    const dz = b[1] - a[1];
    const denominator = fx * dz - fz * dx;
    if (Math.abs(denominator) < 1e-12) return;
    const t = ((a[0] - sx) * dz - (a[1] - sz) * dx) / denominator;
    const u = ((a[0] - sx) * fz - (a[1] - sz) * fx) / denominator;
    if (t < 0 || t > limit || u < 0 || u > 1) return;
    if (best === null || t < best.distance || (t === best.distance && index < best.edge)) {
      best = { distance: t, edge: index };
    }
  });
  return best;
}

/** |sin| of the angle between a heading and an edge, in millionths. Zero means parallel. */
function skewMillionths(forward: Point2, edge: Edge): number {
  const dx = edge.b[0] - edge.a[0];
  const dz = edge.b[1] - edge.a[1];
  const length = Math.hypot(dx, dz);
  return Math.round((Math.abs(forward[0] * dz - forward[1] * dx) / length) * 1_000_000);
}

export function planRoute(
  start: Point2,
  // What the rule reads is the rings, and only the rings: it asks for the type it reads, so a
  // caller with plan regions and no heights is not pushed into inventing a vertical span to pass
  // them. An ObstaclePrism is a RouteRing with a span, so the owned district passes what it always
  // passed and the rule computes exactly what it computed before.
  prisms: readonly RouteRing[],
  bounds: FieldBounds,
  rule: RouteRule = ROUTE_RULE,
): RoutePlan {
  const edges = edgesOf(prisms);
  const grid = new PlanarGrid(8, Math.max(1, edges.length));
  edges.forEach((edge, index) => {
    grid.insert(
      index,
      Math.min(edge.a[0], edge.b[0]), Math.min(edge.a[1], edge.b[1]),
      Math.max(edge.a[0], edge.b[0]), Math.max(edge.a[1], edge.b[1]),
    );
  });
  const radius = THRESHOLDS.capsuleRadiusMm / 1000;
  const length = rule.lengthMm / 1000;
  const required = (rule.lengthMm + rule.stopMarginMm) / 1000;
  const search = rule.frontageSearchMm / 1000;
  const spacing = rule.frontageSampleSpacingMm / 1000;
  const samples = Math.floor(length / spacing) + 1;
  let chosen: RoutePlan | null = null;
  let tried = 0;
  let qualified = 0;
  // Counted, never read: nothing below branches on it, compares against it or orders by it, so the
  // heading this returns is the heading it returned before the count existed.
  let withFrontage = 0;
  for (let millidegrees = 0; millidegrees < 360_000; millidegrees += rule.headingStepMillidegrees) {
    tried += 1;
    const yaw = (millidegrees / 1000) * (Math.PI / 180);
    const forward = forwardOf(yaw);
    const right = rightOf(yaw);
    const clear = firstContact(start, forward, radius, edges, bounds, CLEAR_RUN_LIMIT);
    if (clear < required) continue;
    qualified += 1;
    let both = 0;
    let skewTotal = 0;
    let hits = 0;
    for (let index = 0; index < samples; index += 1) {
      const s = index * spacing;
      const point: Point2 = [start[0] + forward[0] * s, start[1] + forward[1] * s];
      const onRight = firstCrossing(point, right, edges, grid, search);
      const onLeft = firstCrossing(point, [-right[0], -right[1]], edges, grid, search);
      for (const hit of [onRight, onLeft]) {
        if (hit === null) continue;
        skewTotal += skewMillionths(forward, edges[hit.edge]!);
        hits += 1;
      }
      if (onRight !== null && onLeft !== null) both += 1;
    }
    if (both > 0) withFrontage += 1;
    // Integer mean, so the comparison below never depends on float summation order.
    const meanSkew = hits === 0 ? 1_000_000 : Math.floor(skewTotal / hits);
    const better = chosen === null ||
      both > chosen.frontageBothSidesSamples ||
      (both === chosen.frontageBothSidesSamples && meanSkew < chosen.meanFrontageSkewMillionths);
    if (better) {
      chosen = {
        rule,
        start,
        headingMillidegrees: millidegrees,
        yaw,
        forward,
        right,
        clearRunMm: millimetres(clear),
        frontageSamples: samples,
        frontageBothSidesSamples: both,
        meanFrontageSkewMillionths: meanSkew,
        candidatesTried: 0,
        candidatesQualified: 0,
        candidatesWithFrontage: 0,
      };
    }
  }
  if (chosen === null) {
    throw new Error('no heading from the arrival pose clears the route length; the route cannot be walked');
  }
  return { ...chosen, candidatesTried: tried, candidatesQualified: qualified, candidatesWithFrontage: withFrontage };
}

export interface TracePose {
  readonly x: number;
  readonly y: number;
  readonly z: number;
}

export interface RouteSample {
  readonly x: number;
  readonly y: number;
  readonly z: number;
  /** Arc length along the walked trace, metres. */
  readonly s: number;
}

/** Resample a walked trace by planar arc length. Includes both ends. */
export function resampleTrace(poses: readonly TracePose[], spacing: number): RouteSample[] {
  if (poses.length === 0) return [];
  const samples: RouteSample[] = [{ x: poses[0]!.x, y: poses[0]!.y, z: poses[0]!.z, s: 0 }];
  let travelled = 0;
  let ordinal = 1;
  for (let index = 1; index < poses.length; index += 1) {
    const a = poses[index - 1]!;
    const b = poses[index]!;
    const step = Math.hypot(b.x - a.x, b.z - a.z);
    if (step === 0) continue;
    while (ordinal * spacing <= travelled + step + 1e-12) {
      const next = ordinal * spacing;
      const f = Math.min(1, (next - travelled) / step);
      samples.push({
        x: a.x + (b.x - a.x) * f,
        y: a.y + (b.y - a.y) * f,
        z: a.z + (b.z - a.z) * f,
        s: next,
      });
      ordinal += 1;
    }
    travelled += step;
  }
  const last = poses[poses.length - 1]!;
  const tail = samples[samples.length - 1]!;
  if (Math.hypot(last.x - tail.x, last.z - tail.z) > 1e-9) {
    samples.push({ x: last.x, y: last.y, z: last.z, s: travelled });
  }
  return samples;
}

export function sampleQueryPoints(samples: readonly RouteSample[]): Float64Array {
  const points = new Float64Array(samples.length * 2);
  samples.forEach((sample, index) => {
    points[index * 2] = sample.x;
    points[index * 2 + 1] = sample.z;
  });
  return points;
}

export interface WalkMeasurement {
  readonly walkedDisplacementMm: number;
  readonly walkedPathMm: number;
  readonly maxLateralDeviationMm: number;
  readonly traceSamples: number;
  readonly routeSupportGapSamples: number;
  readonly maxEyeHeightErrorMm: number;
  readonly maxSupportResampleDeltaMm: number;
  readonly eyeHeightAboveDrawnSupportMm: { readonly minimum: number; readonly maximum: number };
}

const mm = millimetres;

/** What the walked trace shows about movement and support. Every sample is measured. */
export function measureWalk(
  plan: RoutePlan,
  poses: readonly TracePose[],
  samples: readonly RouteSample[],
  table: TriangleTable,
  classification: Classification,
  support: SupportSamples,
): WalkMeasurement {
  if (poses.length === 0) throw new Error('an empty trace cannot be measured');
  const first = poses[0]!;
  const last = poses[poses.length - 1]!;
  const displacement = (last.x - first.x) * plan.forward[0] + (last.z - first.z) * plan.forward[1];
  let lateral = 0;
  let path = 0;
  for (let index = 0; index < poses.length; index += 1) {
    const pose = poses[index]!;
    const off = Math.abs((pose.x - first.x) * plan.right[0] + (pose.z - first.z) * plan.right[1]);
    if (off > lateral) lateral = off;
    if (index > 0) {
      const prior = poses[index - 1]!;
      path += Math.hypot(pose.x - prior.x, pose.z - prior.z);
    }
  }
  const eye = THRESHOLDS.eyeHeightMm / 1000;
  const step = THRESHOLDS.stepHeightMm / 1000;
  let gaps = 0;
  let eyeError = 0;
  let resample = 0;
  let minimumEye = Number.POSITIVE_INFINITY;
  let maximumEye = Number.NEGATIVE_INFINITY;
  for (const sample of samples) {
    const drawn = drawnSupport(table, classification, sample.x, sample.z, sample.y);
    const product = support.at(sample.x, sample.z);
    if (drawn === null || product === null || Math.abs(drawn - product) > step) {
      gaps += 1;
      continue;
    }
    const above = sample.y - drawn;
    minimumEye = Math.min(minimumEye, above);
    maximumEye = Math.max(maximumEye, above);
    eyeError = Math.max(eyeError, Math.abs(above - eye));
    resample = Math.max(resample, Math.abs(drawn - product));
  }
  return {
    walkedDisplacementMm: Math.max(0, mm(displacement)),
    walkedPathMm: mm(path),
    maxLateralDeviationMm: mm(lateral),
    traceSamples: samples.length,
    routeSupportGapSamples: gaps,
    maxEyeHeightErrorMm: mm(eyeError),
    maxSupportResampleDeltaMm: mm(resample),
    eyeHeightAboveDrawnSupportMm: {
      minimum: Number.isFinite(minimumEye) ? mm(minimumEye) : 0,
      maximum: Number.isFinite(maximumEye) ? mm(maximumEye) : 0,
    },
  };
}

export interface CapsuleMeasurement {
  readonly capsuleSamples: number;
  readonly capsuleSamplesChecked: number;
  readonly capsuleTriangleContactSamples: number;
  readonly capsuleRingContactSamples: number;
  readonly minCapsuleTriangleClearanceMm: number | null;
  readonly minCapsuleRingClearanceMm: number | null;
  readonly contactExamples: readonly {
    readonly sMm: number;
    readonly kind: 'triangle' | 'ring';
    readonly meshOrPrism: string;
  }[];
}

/** Report clearances this far out, so the minimum says something when nothing touches. */
const REPORT_RADIUS = 1.5;

export function measureCapsule(
  samples: readonly RouteSample[],
  table: TriangleTable,
  classification: Classification,
  prisms: readonly ObstaclePrism[],
): CapsuleMeasurement {
  const radius = THRESHOLDS.capsuleRadiusMm / 1000;
  const height = THRESHOLDS.capsuleHeightMm / 1000;
  const step = THRESHOLDS.stepHeightMm / 1000;
  const prismGrid = new PlanarGrid(16, Math.max(1, prisms.length));
  prisms.forEach((prism, index) => {
    let minX = Number.POSITIVE_INFINITY;
    let minZ = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxZ = Number.NEGATIVE_INFINITY;
    for (const [x, z] of prism.ring) {
      minX = Math.min(minX, x);
      minZ = Math.min(minZ, z);
      maxX = Math.max(maxX, x);
      maxZ = Math.max(maxZ, z);
    }
    prismGrid.insert(index, minX, minZ, maxX, maxZ);
  });
  let checked = 0;
  let triangleContacts = 0;
  let ringContacts = 0;
  let minTriangle = Number.POSITIVE_INFINITY;
  let minRing = Number.POSITIVE_INFINITY;
  const examples: CapsuleMeasurement['contactExamples'][number][] = [];
  for (const sample of samples) {
    const floor = drawnSupport(table, classification, sample.x, sample.z, sample.y);
    if (floor === null) continue;
    checked += 1;
    const bottom: Vec3 = [sample.x, floor + radius, sample.z];
    const top: Vec3 = [sample.x, floor + height - radius, sample.z];
    let touched: string | null = null;
    table.grid.query(
      sample.x - REPORT_RADIUS, sample.z - REPORT_RADIUS,
      sample.x + REPORT_RADIUS, sample.z + REPORT_RADIUS,
      (t) => {
        if (table.maxY(t) <= floor + step) return;
        if (table.minY(t) > floor + height + REPORT_RADIUS) return;
        const distance = segmentTriangleDistance(
          bottom, top, table.vertex(t, 0), table.vertex(t, 1), table.vertex(t, 2),
        );
        if (distance < minTriangle) minTriangle = distance;
        if (distance < radius && touched === null) touched = table.meshes[table.meshOf[t]!]!.id;
      },
    );
    if (touched !== null) {
      triangleContacts += 1;
      if (examples.length < 12) examples.push({ sMm: mm(sample.s), kind: 'triangle', meshOrPrism: touched });
    }
    let ring: string | null = null;
    prismGrid.query(
      sample.x - REPORT_RADIUS, sample.z - REPORT_RADIUS,
      sample.x + REPORT_RADIUS, sample.z + REPORT_RADIUS,
      (p) => {
        const prism = prisms[p]!;
        if (prism.topY <= floor || prism.baseY >= floor + height) return;
        const inside = pointInRing(sample.x, sample.z, prism.ring);
        const distance = inside ? 0 : ringEdgeDistance(sample.x, sample.z, prism.ring);
        if (distance < minRing) minRing = distance;
        if (distance < radius && ring === null) ring = prism.id;
      },
    );
    if (ring !== null) {
      ringContacts += 1;
      if (examples.length < 12) examples.push({ sMm: mm(sample.s), kind: 'ring', meshOrPrism: ring });
    }
  }
  return {
    capsuleSamples: samples.length,
    capsuleSamplesChecked: checked,
    capsuleTriangleContactSamples: triangleContacts,
    capsuleRingContactSamples: ringContacts,
    minCapsuleTriangleClearanceMm: Number.isFinite(minTriangle) ? mm(minTriangle) : null,
    minCapsuleRingClearanceMm: Number.isFinite(minRing) ? mm(minRing) : null,
    contactExamples: examples,
  };
}
