/**
 * Scene segments: tint what the photographs found, list it, select it in the inspector, name it.
 *
 * Assembled out of parts that each refuse to do the others' job. `scene-segments-api.ts` reads the
 * segment artifact and knows nothing about a renderer. `ui/scene-segments.ts` builds the panel and
 * holds no client. `AtlasBinding.segmentOverlay` puts indices and resolved colours where the
 * renderer reads them and decides nothing. This module is the one place that knows all three exist,
 * which is the shape every surface in `composition/` has.
 *
 * **One region at a time, and it is the one you are in.** Standing on the ground, that is the drawn
 * region whose footprint holds you; with the inspector open, it is the region the inspector stands
 * in. Moving into another region moves the overlay with you, and the one you left is put back
 * exactly as it was.
 *
 * **Off is nothing.** With the switch off this surface makes no call on the renderer at all, and a
 * click in the inspector goes to click-to-evidence exactly as it did before this surface existed.
 * Switching it off undoes every call switching it on made.
 *
 * **A segment artifact is only an answer about the bytes it was computed against.** It is refused
 * unless its scene, member set, pose receipt and placement receipt are the ones the graph holds, and
 * each asset is tinted only when its digest and sample count are the drawn asset's. The development
 * preview has no receipts to compare, and its binding says so beside the list.
 *
 * **A click resolves to a segment first.** In the inspector the cursor has real coordinates and the
 * camera an exact projection, so a click selects the nearest tinted sample within
 * `SEGMENT_PICK_TOLERANCE_CANVAS_PX` screen pixels, through the same projection the renderer draws
 * with. Only when none is that close does the click fall through to click-to-evidence. As there, it
 * is the nearest tinted sample and not necessarily the surface under the pointer, and the panel
 * shows the distance.
 *
 * **Naming is the index's own flow.** A segment names detections, and naming one is exactly what the
 * Index does with a detection: `draftEdit` in `world-index`, `toUpdateProposal`, `session.stage`,
 * and the write path's own confirmation panel, whose Confirm is the only thing that commits, through
 * the gate, to `POST /identity/name`. The draft is repeated here rather than called because
 * `write-path.ts` reads the name out of the detail pane's form, which this panel is not; proposal
 * ids come from the same session counter, so the two can never collide.
 *
 * **A person is shown with the consent the server resolved, and named only by the graph.** The
 * segment's label is a detector's class word and is never shown as a person's name. A name appears
 * only when the snapshot's entity record carries one, which is the place a withheld name is already
 * absent. A person without recorded presence consent is listed and not tinted.
 *
 * **Colour is a property of the entity.** A pure function of the entity id, so the same person or
 * object wears the same colour in every region, on every visit and in every build.
 */

import { anchorId as toAnchorId, type Island, type IslandId } from '@exulanica/atlas-core';
import {
  calibratedCameraFrustum,
  type AtlasBinding,
  type ProofLensColor,
  type SceneInspectionView,
} from '@exulanica/atlas-react/playcanvas';
import type {
  EntityRecord,
  GraphSnapshot,
  OccurrenceRecord,
  ReconstructionSceneRecord,
} from '@exulanica/graph-client';
import { confirmationFor, draftEdit } from '@exulanica/world-index';

import { toUpdateProposal } from '../proposal.js';
import {
  SceneSegmentsClient,
  SegmentsUnavailable,
  indicesOf,
  previewSceneSegments,
  type ConsentDecision,
  type SceneSegment,
  type SceneSegments,
  type SegmentAssetKind,
} from '../scene-segments-api.js';
import type { Session } from '../session.js';
import type { ConfirmPanel } from '../ui/confirm.js';
import {
  buildSceneSegments,
  type SceneSegmentsModel,
  type SegmentNamingModel,
  type SegmentRowModel,
} from '../ui/scene-segments.js';
import type { AppEnvironment, SessionState } from './session-state.js';

/**
 * How far from the cursor, in screen pixels, a tinted sample may be and still count as clicked.
 *
 * The same eight pixels click-to-evidence allows, so the two answers a click can get are held to
 * one standard of "near", and the band that decides which of several candidates is in front is the
 * same two pixels.
 */
export const SEGMENT_PICK_TOLERANCE_CANVAS_PX = 8;
const SEGMENT_PICK_BAND_CANVAS_PX = 2;
/** How often the surface checks which region you are in while the overlay is on. */
const REGION_POLL_MS = 500;
/** The renderer's near plane. A sample nearer than this is clipped, so it cannot be clicked. */
const NEAR_CLIP = 0.08;
/** One region's slot byte, as the binding counts it. */
const SLOT_LIMIT = 255;

/** Tint strength at rest, for the emphasised segment, and for every other while one is emphasised. */
const TINT_AT_REST = 0.78;
const TINT_EMPHASISED = 1;
const TINT_RECEDED = 0.28;

type Rgb = readonly [number, number, number];
type SegmentOverlayInput = Parameters<AtlasBinding['segmentOverlay']['apply']>[0];
type SegmentOverlayTint = NonNullable<SegmentOverlayInput>['tints'][number];
type SegmentPalette = NonNullable<SegmentOverlayInput>['palette'];
type SegmentOverlayReport = ReturnType<AtlasBinding['segmentOverlay']['apply']>;
type SegmentOverlayAsset = SegmentOverlayReport['assets'][number];

// -- colour -------------------------------------------------------------------------------------------

/** FNV-1a over UTF-16 code units: small, dependency free, and the same in every build. */
function fnv1a(text: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash;
}

function srgbEncode(linear: number): number {
  const value = Math.min(1, Math.max(0, linear));
  return value <= 0.0031308 ? 12.92 * value : 1.055 * value ** (1 / 2.4) - 0.055;
}

/**
 * The colour one entity wears, as sRGB in 0 to 1.
 *
 * A hue from the entity id at one fixed lightness and chroma in OKLCH, so every entity is equally
 * legible and none reads as more important than another. It depends on the id and nothing else:
 * not on which other segments share the region, not on the order they were listed in, and not on
 * the theme. Two entities can land on neighbouring hues, and the list's swatches and the hover
 * highlight are how they are told apart.
 */
export function segmentColor(key: string): Rgb {
  const hue = (fnv1a(key) / 0x1_0000_0000) * 2 * Math.PI;
  const lightness = 0.74;
  const chroma = 0.13;
  const a = chroma * Math.cos(hue);
  const b = chroma * Math.sin(hue);
  const l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (lightness - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return Object.freeze([
    srgbEncode(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    srgbEncode(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    srgbEncode(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ]) as Rgb;
}

/** The key a segment's colour is derived from: its entity, or itself when it names none. */
export function colourKeyOf(segment: Pick<SceneSegment, 'entityId' | 'segmentId'>): string {
  return segment.entityId ?? segment.segmentId;
}

function cssColour([r, g, b]: Rgb): string {
  return `rgb(${Math.round(r * 255)} ${Math.round(g * 255)} ${Math.round(b * 255)})`;
}

// -- projection and the pick --------------------------------------------------------------------------

/** The camera a pick projects through: the inspection view the renderer is drawing. */
export type SegmentPickCamera = Pick<SceneInspectionView, 'position' | 'forward' | 'up' | 'fovYDeg' | 'calibration'>;

/**
 * Where an atlas point lands on the canvas, in CSS pixels from its top left, or null behind the near
 * plane.
 *
 * The same camera the renderer draws the inspection with: `setLookAt(position, position + forward,
 * up)` for the orientation, and either the calibrated frustum or a vertical field of view for the
 * projection. Using anything else would select a sample by where it would be drawn by some other
 * camera, which is a click on a picture nobody is looking at.
 */
export function projectToCanvas(
  camera: SegmentPickCamera,
  canvas: { readonly width: number; readonly height: number },
  point: readonly [number, number, number],
): { readonly x: number; readonly y: number; readonly depth: number } | null {
  const [fx, fy, fz] = camera.forward;
  const forwardLength = Math.hypot(fx, fy, fz);
  const z: Rgb = [-fx / forwardLength, -fy / forwardLength, -fz / forwardLength];
  const [ux, uy, uz] = camera.up;
  let x: Rgb = [uy * z[2] - uz * z[1], uz * z[0] - ux * z[2], ux * z[1] - uy * z[0]];
  const xLength = Math.hypot(...x);
  if (xLength < 1e-9 || forwardLength < 1e-9) return null;
  x = [x[0] / xLength, x[1] / xLength, x[2] / xLength];
  const y: Rgb = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]];
  const dx = point[0] - camera.position[0];
  const dy = point[1] - camera.position[1];
  const dz = point[2] - camera.position[2];
  const depth = -(dx * z[0] + dy * z[1] + dz * z[2]);
  if (!(depth > NEAR_CLIP)) return null;
  const tx = (dx * x[0] + dy * x[1] + dz * x[2]) / depth;
  const ty = (dx * y[0] + dy * y[1] + dz * y[2]) / depth;
  const aspect = canvas.width / canvas.height;
  let ndcX: number;
  let ndcY: number;
  if (camera.calibration === null) {
    const focal = 1 / Math.tan((camera.fovYDeg * Math.PI) / 360);
    ndcX = (focal / aspect) * tx;
    ndcY = focal * ty;
  } else {
    const f = calibratedCameraFrustum(camera.calibration, aspect, 1);
    ndcX = (2 / (f.right - f.left)) * tx - (f.right + f.left) / (f.right - f.left);
    ndcY = (2 / (f.top - f.bottom)) * ty - (f.top + f.bottom) / (f.top - f.bottom);
  }
  return { x: ((ndcX + 1) / 2) * canvas.width, y: ((1 - ndcY) / 2) * canvas.height, depth };
}

export interface SegmentPick {
  readonly artifactId: string;
  readonly slot: number;
  readonly sampleIndex: number;
  readonly pixelDistance: number;
  readonly depth: number;
}

/**
 * The tinted sample a click selects, or null when none is within the tolerance.
 *
 * The rule click-to-evidence uses, over tinted samples: every candidate within the tolerance, then
 * of those within the band of the nearest, the one in front. Ties break on asset and sample index,
 * so the same click on the same view always selects the same sample.
 */
export function pickSegmentSample(
  assets: readonly Pick<SegmentOverlayAsset, 'artifactId' | 'indices' | 'slots' | 'positions'>[],
  camera: SegmentPickCamera,
  canvas: { readonly width: number; readonly height: number },
  cursor: { readonly x: number; readonly y: number },
  options: { readonly tolerancePx?: number; readonly bandPx?: number } = {},
): SegmentPick | null {
  const tolerance = options.tolerancePx ?? SEGMENT_PICK_TOLERANCE_CANVAS_PX;
  const band = options.bandPx ?? SEGMENT_PICK_BAND_CANVAS_PX;
  const candidates: SegmentPick[] = [];
  for (const asset of assets) {
    const positions = asset.positions;
    if (positions === null) continue;
    for (let k = 0; k < asset.indices.length; k += 1) {
      const projected = projectToCanvas(camera, canvas,
        [positions[k * 3]!, positions[k * 3 + 1]!, positions[k * 3 + 2]!]);
      if (projected === null) continue;
      const pixelDistance = Math.hypot(projected.x - cursor.x, projected.y - cursor.y);
      if (pixelDistance > tolerance) continue;
      candidates.push({
        artifactId: asset.artifactId, slot: asset.slots[k]!, sampleIndex: asset.indices[k]!,
        pixelDistance, depth: projected.depth,
      });
    }
  }
  if (candidates.length === 0) return null;
  const nearest = Math.min(...candidates.map((candidate) => candidate.pixelDistance));
  return candidates
    .filter((candidate) => candidate.pixelDistance <= nearest + band)
    .reduce((best, candidate) => {
      if (candidate.depth !== best.depth) return candidate.depth < best.depth ? candidate : best;
      if (candidate.artifactId !== best.artifactId) return candidate.artifactId < best.artifactId ? candidate : best;
      return candidate.sampleIndex < best.sampleIndex ? candidate : best;
    });
}

/**
 * The inspector surface with a segment asked first.
 *
 * Everything else about `status` is untouched: only `resolveEvidenceAt`, the canvas click, goes to
 * the segment resolver before it goes to the observation graph. The inspector's own "resolve the
 * centre" button still asks for evidence directly, and the segment list is the keyboard route to
 * a segment.
 */
export function segmentsFirst<T extends { resolveEvidenceAt(clientX: number, clientY: number): void }>(
  status: T,
  resolveSegmentAt: (clientX: number, clientY: number) => boolean,
): T {
  return Object.create(status, {
    resolveEvidenceAt: {
      value: (clientX: number, clientY: number): void => {
        if (!resolveSegmentAt(clientX, clientY)) status.resolveEvidenceAt(clientX, clientY);
      },
    },
  }) as T;
}

// -- which geometry a segment artifact is about ------------------------------------------------------

/** One asset the renderer is drawing for a scene, as the binding holds it. */
export interface DrawnAsset {
  readonly artifactId: string;
  readonly kind: SegmentAssetKind;
  readonly sampleCount: number;
}

export interface DrawnScene {
  readonly sceneId: string;
  readonly islandId: IslandId;
  readonly assets: readonly DrawnAsset[];
}

/** What each scene is actually drawing: its trained geometry when it has any, else its point maps. */
export function drawnScenesOf(binding: Pick<AtlasBinding, 'islands' | 'trainedScenes'>): readonly DrawnScene[] {
  const scenes = new Map<string, { islandId: IslandId; assets: DrawnAsset[] }>();
  const add = (sceneId: string, islandId: IslandId, asset: DrawnAsset): void => {
    const held = scenes.get(sceneId);
    if (held === undefined) scenes.set(sceneId, { islandId, assets: [asset] });
    else held.assets.push(asset);
  };
  const trained = new Set(binding.trainedScenes.map((visual) => visual.geometry.sceneId));
  for (const visual of binding.trainedScenes) {
    add(visual.geometry.sceneId, visual.island.islandId, {
      artifactId: visual.geometry.artifactId, kind: 'trained_geometry', sampleCount: visual.geometry.pointCount,
    });
  }
  for (const visual of binding.islands) {
    if (trained.has(visual.pointMap.sceneId)) continue;
    add(visual.pointMap.sceneId, visual.island.islandId, {
      artifactId: visual.pointMap.artifactId, kind: 'point_map', sampleCount: visual.cloud.pointCount,
    });
  }
  return [...scenes].map(([sceneId, held]) => Object.freeze({ sceneId, ...held }));
}

export interface SegmentBinding {
  /** Segment artifact asset id to the drawn asset its indices address. */
  readonly assets: ReadonlyMap<string, DrawnAsset>;
  /** What could not be bound and why, and in the preview what was not checked. */
  readonly notices: readonly string[];
  /** False in the preview, where there is no receipt to compare against. */
  readonly verified: boolean;
}

function expectedDigest(record: ReconstructionSceneRecord, artifactId: string, kind: SegmentAssetKind): string | null {
  if (kind === 'trained_geometry') {
    return record.trainedGeometry?.artifactId === artifactId ? record.trainedGeometry.contentSha256 : null;
  }
  return record.members.find((member) => member.placement?.artifactId === artifactId)?.placement?.contentSha256 ?? null;
}

/**
 * Which drawn asset each of the artifact's assets is, or why it is none.
 *
 * Production compares everything the artifact says it was computed against with what the graph
 * holds, and refuses the whole artifact when a scene-level digest disagrees: indices computed under
 * another pose or placement are about other geometry, however well they happen to line up.
 *
 * The preview has no scene record and its point map carries no digest, so it binds by kind and
 * sample count alone, exactly as the preview's loader skips the digest check, and says so.
 */
export function bindSegments(
  segments: SceneSegments,
  drawn: DrawnScene,
  record: ReconstructionSceneRecord | undefined,
  preview: boolean,
): SegmentBinding {
  const assets = new Map<string, DrawnAsset>();
  if (preview) {
    const unused = [...drawn.assets];
    for (const asset of segments.assets) {
      const match = unused.findIndex((candidate) => candidate.kind === asset.kind && candidate.sampleCount === asset.sampleCount);
      if (match < 0) continue;
      assets.set(asset.artifactId, unused[match]!);
      unused.splice(match, 1);
    }
    return {
      assets,
      verified: false,
      notices: [
        'Synthetic preview: the segments are bound to the drawn map by sample count only. No receipt '
          + 'or digest was compared, because the preview has none.',
        ...(assets.size === 0 ? ['No asset in the preview fixture has the sample count of anything drawn here.'] : []),
      ],
    };
  }
  const refuse = (reason: string): SegmentBinding => ({ assets, verified: true, notices: [reason] });
  if (segments.sceneId !== drawn.sceneId) return refuse('These segments were recorded for a different scene.');
  if (record === undefined) {
    return refuse('The graph holds no record of this scene, so nothing the segments are bound to can be checked.');
  }
  if (segments.boundTo.memberDigest !== record.memberDigest) {
    return refuse('These segments were computed over a different set of photographs, so nothing is tinted.');
  }
  if (segments.boundTo.poseReceiptSha256 !== record.poseReceiptSha256) {
    return refuse('These segments were computed against a different pose receipt, so nothing is tinted.');
  }
  if (segments.boundTo.placementReceiptSha256 !== record.placementReceiptSha256) {
    return refuse('These segments were computed against a different placement receipt, so nothing is tinted.');
  }
  const refusals: string[] = [];
  let undrawn = 0;
  for (const asset of segments.assets) {
    const match = drawn.assets.find((candidate) => candidate.artifactId === asset.artifactId);
    if (match === undefined) {
      undrawn += 1;
      continue;
    }
    if (match.kind !== asset.kind) {
      refusals.push(`Asset ${asset.artifactId} is drawn as a different kind of geometry than the segments name.`);
    } else if (expectedDigest(record, asset.artifactId, asset.kind) !== asset.contentSha256) {
      refusals.push(`The drawn bytes of asset ${asset.artifactId} are not the ones the segments were computed against.`);
    } else if (match.sampleCount !== asset.sampleCount) {
      refusals.push(`Asset ${asset.artifactId} draws ${match.sampleCount} samples and the segments index ${asset.sampleCount}.`);
    } else {
      assets.set(asset.artifactId, match);
    }
  }
  if (undrawn > 0) {
    refusals.push(undrawn === 1
      ? 'One asset the segments index is not drawn here, so its samples are not tinted.'
      : `${undrawn} assets the segments index are not drawn here, so their samples are not tinted.`);
  }
  return { assets, verified: true, notices: refusals };
}

export interface SegmentPlan {
  /** Every segment, most votes first. The list and the slot numbers both follow this order. */
  readonly ordered: readonly SceneSegment[];
  readonly slotOf: ReadonlyMap<string, number>;
  readonly segmentOfSlot: ReadonlyMap<number, SceneSegment>;
  /** Why a listed segment is not tinted. */
  readonly untinted: ReadonlyMap<string, string>;
  readonly tints: readonly SegmentOverlayTint[];
  /** Samples two segments both claimed, each tinted as the one with more votes. */
  readonly contested: number;
}

/**
 * Slot numbers and disjoint sample sets, in vote order.
 *
 * A sample two segments both claim is tinted as the one with more votes, and the count of such
 * samples is reported rather than hidden. The binding would resolve a collision the same way, but
 * doing it here is what lets the panel say how many there were.
 */
export function planSegmentTints(segments: SceneSegments, binding: SegmentBinding): SegmentPlan {
  const ordered = [...segments.segments].sort((left, right) =>
    right.voteCount - left.voteCount || (left.segmentId < right.segmentId ? -1 : 1));
  const slotOf = new Map<string, number>();
  const segmentOfSlot = new Map<number, SceneSegment>();
  const untinted = new Map<string, string>();
  const tints: SegmentOverlayTint[] = [];
  const claimed = new Map<string, Uint8Array>();
  let contested = 0;
  for (const segment of ordered) {
    if (segment.person !== null && segment.person.consent.presence !== 'granted') {
      untinted.set(segment.segmentId, 'Not tinted: no presence consent is recorded for this person.');
      continue;
    }
    const drawn = segment.samples.filter((samples) => binding.assets.has(samples.artifactId));
    if (drawn.length === 0) {
      untinted.set(segment.segmentId, 'Not tinted: none of its samples are in geometry drawn here.');
      continue;
    }
    if (slotOf.size >= SLOT_LIMIT) {
      untinted.set(segment.segmentId, `Not tinted: one region can carry ${SLOT_LIMIT} tinted segments.`);
      continue;
    }
    const slot = slotOf.size + 1;
    const own: SegmentOverlayTint[] = [];
    for (const samples of drawn) {
      const asset = binding.assets.get(samples.artifactId)!;
      const taken = claimed.get(asset.artifactId) ?? new Uint8Array(asset.sampleCount);
      claimed.set(asset.artifactId, taken);
      const indices = indicesOf(samples);
      const kept = new Uint32Array(indices.length);
      let count = 0;
      for (const index of indices) {
        if (taken[index] !== 0) { contested += 1; continue; }
        taken[index] = 1;
        kept[count++] = index;
      }
      if (count > 0) own.push({ slot, artifactId: asset.artifactId, indices: kept.subarray(0, count) });
    }
    if (own.length === 0) {
      untinted.set(segment.segmentId, 'Not tinted: every one of its samples belongs to a segment with more votes.');
      continue;
    }
    tints.push(...own);
    slotOf.set(segment.segmentId, slot);
    segmentOfSlot.set(slot, segment);
  }
  return { ordered, slotOf, segmentOfSlot, untinted, tints, contested };
}

/** One resolved colour per tinted slot; the emphasised segment full, the rest receded. */
export function segmentPalette(plan: SegmentPlan, emphasis: string | null): SegmentPalette {
  const palette = new Map<number, ProofLensColor>();
  const emphasised = emphasis !== null && plan.slotOf.has(emphasis) ? emphasis : null;
  for (const [segmentId, slot] of plan.slotOf) {
    const segment = plan.segmentOfSlot.get(slot)!;
    const [r, g, b] = segmentColor(colourKeyOf(segment));
    const strength = emphasised === null ? TINT_AT_REST : segmentId === emphasised ? TINT_EMPHASISED : TINT_RECEDED;
    palette.set(slot, Object.freeze([r, g, b, strength]) as ProofLensColor);
  }
  return palette;
}

// -- naming ---------------------------------------------------------------------------------------------

export type NamingTarget =
  | { readonly kind: 'named'; readonly name: string }
  | { readonly kind: 'offer'; readonly occurrence: OccurrenceRecord }
  | { readonly kind: 'unavailable'; readonly reason: string };

/**
 * What the naming flow can do with this segment, and on which detection.
 *
 * The API names a detection and creates the entity; it refuses a detection that is already linked,
 * and it has no rename. So a segment whose entity the graph already names shows that name, a
 * segment with an unlinked detection offers to name it (preferring the one in the photograph the
 * inspector stands on), and anything else says why nothing can be named here.
 */
export function namingTargetFor(
  segment: SceneSegment,
  snapshot: Pick<GraphSnapshot, 'entities' | 'occurrences'>,
  captureId: string | null,
): NamingTarget {
  const entity = segment.entityId === null
    ? undefined
    : snapshot.entities.find((candidate) => candidate.entityId === segment.entityId);
  if (entity !== undefined && typeof entity.displayName === 'string' && entity.displayName.length > 0) {
    return { kind: 'named', name: entity.displayName };
  }
  const detections = segment.occurrenceIds
    .map((occurrenceId) => snapshot.occurrences.find((candidate) => candidate.occurrenceId === occurrenceId))
    .filter((occurrence): occurrence is OccurrenceRecord => occurrence !== undefined);
  const unlinked = detections.filter((occurrence) => occurrence.entityId === null);
  const chosen = unlinked.find((occurrence) => captureId !== null && occurrence.captureId === captureId) ?? unlinked[0];
  if (chosen !== undefined) return { kind: 'offer', occurrence: chosen };
  if (detections.length === 0) {
    return {
      kind: 'unavailable',
      reason: 'No detection behind this segment is in the graph this session reads, so there is nothing the '
        + 'naming flow can name here.',
    };
  }
  return {
    kind: 'unavailable',
    reason: 'Every detection behind this segment is already linked to an entity, and this instance has no '
      + 'rename, so there is nothing to name here.',
  };
}

/**
 * The entity naming a bare detection would create, for the draft and its confirmation to describe.
 *
 * The same record `write-path.ts` builds for the Index, field for field, so the draft and the words
 * in the confirmation panel are the ones naming this detection from the Index would produce.
 */
function syntheticEntityFor(occurrence: OccurrenceRecord): EntityRecord {
  return {
    entityId: occurrence.entityId ?? occurrence.occurrenceId,
    kind: occurrence.kind === 'voice' || occurrence.kind === 'conversation'
      ? 'object'
      : (occurrence.kind as 'person' | 'place' | 'object' | 'event'),
    displayName: null,
    status: 'inferred_only',
    occurrenceCount: 1,
    islandIds: [occurrence.islandId],
    firstSeenMs: occurrence.capturedAtMs,
    lastSeenMs: occurrence.capturedAtMs,
    confidence: occurrence.confidence,
    openQuestionCount: 0,
    citingAnswerCount: 0,
    assertions: [],
    relations: [],
    contradictions: [],
    history: [],
    mergedInto: null,
  };
}

// -- the surface ----------------------------------------------------------------------------------------

/**
 * What survives a remount. Created once by the composition root, beside the session state.
 *
 * A committed name re-reads the graph and remounts every surface, and a visitor who has just named a
 * segment should come back to the overlay they had on and the segment they had selected.
 */
export interface SegmentSession {
  overlay: boolean;
  selectedSegmentId: string | null;
  /** Stops the previous mount's timer and listeners. */
  mount: AbortController | null;
}

export function createSegmentSession(): SegmentSession {
  return { overlay: false, selectedSegmentId: null, mount: null };
}

export interface SegmentsDependencies {
  readonly env: AppEnvironment;
  readonly state: SessionState;
  readonly snapshot: GraphSnapshot;
  readonly segmentSession: SegmentSession;
  /** Staging only. Committing belongs to the confirmation panel's own Confirm. */
  readonly session: Pick<Session, 'stage' | 'stateVersion'>;
  /** The write path's confirmation panel: the Index's, and the only thing that commits a name. */
  readonly confirm: ConfirmPanel;
  /** Other confirmation panels, hidden first so exactly one is ever open. */
  readonly hideOtherConfirms: () => void;
  /** Open the reconstruction inspector on a scene. */
  readonly inspect: (sceneId: string) => void;
  readonly showWorld: () => void;
  readonly showTravelStatus: (message: string, kind?: 'progress' | 'failure') => void;
  readonly travelUsesReducedMotion: () => boolean;
  /** Injectable for tests. Production reads the route, the preview the provisional fixture. */
  readonly load?: (sceneId: string) => Promise<SceneSegments>;
}

export interface MountedSegments {
  readonly root: HTMLElement;
  /** Resolve a click in the inspector to a segment. True when it did, and the click is answered. */
  resolveAt(clientX: number, clientY: number): boolean;
  /** Apply the overlay to the renderer this mount drew. Called once the renderer exists. */
  begin(): Promise<void>;
  dispose(): void;
}

type RegionLoad =
  | { readonly kind: 'loading' }
  | { readonly kind: 'failed'; readonly reason: string }
  | {
    readonly kind: 'ready';
    readonly segments: SceneSegments;
    readonly binding: SegmentBinding;
    readonly plan: SegmentPlan;
    report: SegmentOverlayReport | null;
  };

interface Region {
  readonly key: string;
  readonly islandId: IslandId;
  readonly sceneId: string;
  readonly inspecting: boolean;
  load: RegionLoad;
}

export function mountSegments(deps: SegmentsDependencies): MountedSegments {
  const { env, state, segmentSession: kept } = deps;
  kept.mount?.abort();
  const listeners = new AbortController();
  kept.mount = listeners;

  const loads = new Map<string, Promise<SceneSegments>>();
  const loadScene = (sceneId: string): Promise<SceneSegments> => {
    const held = loads.get(sceneId);
    if (held !== undefined) return held;
    const started = deps.load !== undefined
      ? deps.load(sceneId)
      : env.preview
        ? previewSceneSegments()
        : state.credentials === null
          ? Promise.reject(new SegmentsUnavailable('unauthorized', 'This session has no credentials to read segments with.'))
          : new SceneSegmentsClient(state.credentials).load(sceneId);
    loads.set(sceneId, started);
    // A failed read is asked again next time rather than remembered, so switching the overlay off
    // and on is a retry.
    started.catch(() => loads.delete(sceneId));
    return started;
  };

  let region: Region | null = null;
  /** The overlay the renderer currently holds, by region key. Null means the renderer holds none. */
  let appliedKey: string | null = null;
  let hovered: string | null = null;
  let picked: { readonly segmentId: string; readonly pixelDistance: number } | null = null;
  let timer: number | null = null;
  /** False until `begin`: before it, the renderer in `state.atlas` is the previous mount's. */
  let begun = false;

  const panel = buildSceneSegments({
    onToggle: (on) => {
      kept.overlay = on;
      if (!on) {
        picked = null;
        hovered = null;
      }
      void sync();
    },
    onHover: (segmentId) => {
      hovered = segmentId;
      recolour();
    },
    onSelect: (segmentId) => {
      kept.selectedSegmentId = kept.selectedSegmentId === segmentId ? null : segmentId;
      if (picked?.segmentId !== kept.selectedSegmentId) picked = null;
      recolour();
      render();
    },
    onTravel: (segmentId) => travel(segmentId),
    onInspect: () => { if (region !== null) deps.inspect(region.sceneId); },
    onName: (segmentId, displayName) => name(segmentId, displayName),
  });

  // -- where the visitor is -----------------------------------------------------------------------

  /** The region the list is about: the inspector's, or the drawn region whose footprint holds you. */
  function whereNow(binding: AtlasBinding): { islandId: IslandId; sceneId: string; inspecting: boolean } | null {
    const scenes = drawnScenesOf(binding);
    const view = binding.inspectionView;
    if (view !== null) {
      const scene = scenes.find((candidate) => candidate.sceneId === view.sceneId)
        ?? scenes.find((candidate) => candidate.islandId === view.islandId);
      return scene === undefined ? null : { islandId: scene.islandId, sceneId: scene.sceneId, inspecting: true };
    }
    const pose = binding.cameraPose();
    let best: { islandId: IslandId; sceneId: string; inspecting: boolean } | null = null;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const scene of scenes) {
      const island: Island | undefined = binding.scene.islands.find((candidate) => candidate.islandId === scene.islandId);
      if (island === undefined) continue;
      const distance = Math.hypot(island.placement.position.x - pose.position.x, island.placement.position.z - pose.position.z);
      // Inside the footprint, with the same reach the object surface allows: nearest alone would
      // put the overlay on a region across the world from someone standing in an empty one.
      const reach = island.footprintRadiusLocal * island.placement.scale * 1.5;
      if (distance <= reach && distance < bestDistance) {
        bestDistance = distance;
        best = { islandId: scene.islandId, sceneId: scene.sceneId, inspecting: false };
      }
    }
    return best;
  }

  // -- the renderer ---------------------------------------------------------------------------------

  const emphasis = (): string | null => hovered ?? kept.selectedSegmentId;

  function recolour(): void {
    const binding = state.atlas?.binding;
    if (binding === undefined || region?.load.kind !== 'ready' || appliedKey !== region.key) return;
    binding.segmentOverlay.setPalette(segmentPalette(region.load.plan, emphasis()));
  }

  /** Take the overlay off the renderer, if and only if this surface put one there. */
  function takeOff(): void {
    if (appliedKey === null) return;
    appliedKey = null;
    state.atlas?.binding.segmentOverlay.apply(null);
  }

  function applyRegion(current: Region): void {
    const binding = state.atlas?.binding;
    if (binding === undefined || current.load.kind !== 'ready') return;
    const load = current.load;
    if (load.plan.tints.length === 0) {
      takeOff();
      load.report = null;
      return;
    }
    load.report = binding.segmentOverlay.apply({
      islandId: current.islandId,
      tints: load.plan.tints,
      palette: segmentPalette(load.plan, emphasis()),
    });
    appliedKey = current.key;
  }

  async function sync(): Promise<void> {
    const binding = begun ? state.atlas?.binding : undefined;
    if (!kept.overlay || binding === undefined) {
      stopPolling();
      takeOff();
      region = null;
      render();
      return;
    }
    startPolling();
    const here = whereNow(binding);
    const key = here === null ? null : `${here.islandId}|${here.sceneId}`;
    if (key !== null && region?.key === key) {
      if (region.inspecting !== here!.inspecting) {
        region = { ...region, inspecting: here!.inspecting };
        render();
      }
      return;
    }
    takeOff();
    picked = null;
    if (here === null || key === null) {
      region = null;
      render();
      return;
    }
    const current: Region = { key, ...here, load: { kind: 'loading' } };
    region = current;
    render();
    try {
      const segments = await loadScene(here.sceneId);
      if (region !== current || !kept.overlay) return;
      const drawn = drawnScenesOf(binding).find((scene) => scene.sceneId === here.sceneId);
      if (drawn === undefined) {
        current.load = { kind: 'failed', reason: 'This scene is no longer drawn.' };
      } else {
        const record = deps.snapshot.reconstructionScenes?.find((scene) => scene.sceneId === here.sceneId);
        const segmentBinding = bindSegments(segments, drawn, record, env.preview);
        current.load = {
          kind: 'ready', segments, binding: segmentBinding, plan: planSegmentTints(segments, segmentBinding), report: null,
        };
        applyRegion(current);
      }
    } catch (error) {
      if (region !== current) return;
      current.load = {
        kind: 'failed',
        reason: error instanceof SegmentsUnavailable || error instanceof Error
          ? error.message
          : 'The scene segments could not be read.',
      };
    }
    render();
  }

  function startPolling(): void {
    if (timer !== null) return;
    timer = window.setInterval(() => void sync(), REGION_POLL_MS);
  }

  function stopPolling(): void {
    if (timer === null) return;
    window.clearInterval(timer);
    timer = null;
  }

  listeners.signal.addEventListener('abort', () => stopPolling(), { once: true });

  // -- the panel ------------------------------------------------------------------------------------

  function consentWords(decision: ConsentDecision): string {
    return decision === 'not_recorded' ? 'not recorded' : decision;
  }

  function headingOf(segment: SceneSegment): string {
    const entity = segment.entityId === null
      ? undefined
      : deps.snapshot.entities.find((candidate) => candidate.entityId === segment.entityId);
    const name = typeof entity?.displayName === 'string' && entity.displayName.length > 0 ? entity.displayName : null;
    // A person's heading comes from the graph or says it has none. The detector's word for them is
    // a class, not a name, and showing it as one is how a withheld name would leak back in.
    if (segment.entityClass === 'person') return name ?? 'Unnamed person';
    return name ?? segment.label;
  }

  function rowOf(segment: SceneSegment, load: Extract<RegionLoad, { kind: 'ready' }>, captureId: string | null): SegmentRowModel {
    const views = load.segments.method.views;
    const slot = load.plan.slotOf.get(segment.segmentId);
    const selected = kept.selectedSegmentId === segment.segmentId;
    const facts: string[] = [];
    if (selected) {
      if (segment.entityClass !== 'person') facts.push(`Detector label: ${segment.label}.`);
      facts.push(segment.entityId === null
        ? 'Linked to no entity in the graph.'
        : deps.snapshot.entities.some((candidate) => candidate.entityId === segment.entityId)
          ? 'Linked to an entity in the graph.'
          : 'Linked to an entity this session cannot see.');
      if (segment.person !== null) {
        facts.push(segment.person.reviewState === 'screened'
          ? 'Screened for people by a reviewer.'
          : 'Not screened for people.');
        facts.push(`Presence consent: ${consentWords(segment.person.consent.presence)}. `
          + `Naming consent: ${consentWords(segment.person.consent.naming)}. `
          + `Likeness consent: ${consentWords(segment.person.consent.likeness)}.`);
      }
      if (picked?.segmentId === segment.segmentId) {
        facts.push(`Selected by a click: the nearest tinted sample was ${picked.pixelDistance.toFixed(1)} screen `
          + 'pixels from the pointer. That is the nearest tinted sample, not necessarily the surface under it.');
      }
    }
    const target = namingTargetFor(segment, deps.snapshot, captureId);
    const naming: SegmentNamingModel = target.kind === 'named'
      ? { kind: 'named', sentence: `The graph names this ${segment.entityClass} ${target.name}.` }
      : target.kind === 'unavailable'
        ? { kind: 'unavailable', reason: target.reason }
        : env.preview
          ? { kind: 'preview' }
          : { kind: 'offer', sentence: 'Naming it names one detection behind it, exactly as naming it from the Index would.' };
    return {
      segmentId: segment.segmentId,
      heading: headingOf(segment),
      summary: `${segment.entityClass}, ${segment.confidence} confidence, `
        + `${segment.voteCount} of ${views} ${views === 1 ? 'photograph' : 'photographs'} voted for it`,
      swatch: slot === undefined ? null : cssColour(segmentColor(colourKeyOf(segment))),
      untinted: load.plan.untinted.get(segment.segmentId) ?? null,
      selected,
      facts,
      naming,
    };
  }

  function modelNow(): SceneSegmentsModel {
    const pickSentence = `In the inspector, a click selects the nearest tinted sample within `
      + `${SEGMENT_PICK_TOLERANCE_CANVAS_PX} screen pixels before it asks for evidence.`;
    const base = { rows: [], notices: [], pickSentence, canInspect: false, where: null, message: null };
    if (!kept.overlay) return { ...base, on: false, state: 'off' };
    if (region === null) {
      return {
        ...base, on: true, state: 'nowhere',
        message: !begun || state.atlas === null
          ? 'The Atlas is still forming.'
          : 'You are not standing in a region that draws reconstructed geometry, so nothing is tinted.',
      };
    }
    const where = region.inspecting ? 'In the region the inspector stands in.' : 'In the region you stand in.';
    const canInspect = !region.inspecting;
    if (region.load.kind === 'loading') return { ...base, on: true, state: 'loading', where, canInspect, message: 'Reading the segments…' };
    if (region.load.kind === 'failed') return { ...base, on: true, state: 'failed', where, canInspect, message: region.load.reason };
    const load = region.load;
    const captureId = state.atlas?.binding.inspectionView?.captureIds[0] ?? null;
    const notices = [...load.binding.notices, ...(load.report?.refused.map((item) => item.reason) ?? [])];
    if (load.plan.contested > 0) {
      notices.push(`${load.plan.contested} samples are claimed by two segments and tinted as the one with more votes.`);
    }
    if (load.report?.assets.some((asset) => asset.positions === null)) {
      notices.push('This device holds no copy of the trained Gaussians\' centres, so a click cannot select them; the list still can.');
    }
    const empty = load.segments.segments.length === 0;
    return {
      on: true,
      state: 'ready',
      where,
      canInspect,
      message: empty ? 'No segments are recorded for this scene.' : null,
      rows: load.plan.ordered.map((segment) => rowOf(segment, load, captureId)),
      notices,
      pickSentence,
    };
  }

  function render(): void {
    panel.render(modelNow());
  }

  // -- the click --------------------------------------------------------------------------------------

  function resolveAt(clientX: number, clientY: number): boolean {
    if (!kept.overlay) return false;
    const binding = state.atlas?.binding;
    const view = binding?.inspectionView ?? null;
    if (binding === undefined || view === null || region?.load.kind !== 'ready') return false;
    const report = region.load.report;
    if (report === null || appliedKey !== region.key || report.islandId !== view.islandId) return false;
    const rect = env.canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    const pick = pickSegmentSample(report.assets, view, { width: rect.width, height: rect.height },
      { x: clientX - rect.left, y: clientY - rect.top });
    if (pick === null) return false;
    const segment = region.load.plan.segmentOfSlot.get(pick.slot);
    if (segment === undefined) return false;
    kept.selectedSegmentId = segment.segmentId;
    picked = { segmentId: segment.segmentId, pixelDistance: pick.pixelDistance };
    recolour();
    render();
    panel.revealSelected();
    return true;
  }

  // -- travel and naming -----------------------------------------------------------------------------

  function segmentById(segmentId: string): SceneSegment | undefined {
    return region?.load.kind === 'ready'
      ? region.load.segments.segments.find((segment) => segment.segmentId === segmentId)
      : undefined;
  }

  function travel(segmentId: string): void {
    const binding = state.atlas?.binding;
    const segment = segmentById(segmentId);
    if (binding === undefined || segment === undefined || region === null) {
      deps.showTravelStatus('The Atlas is still forming. Try again in a moment.', 'failure');
      return;
    }
    const reduced = deps.travelUsesReducedMotion();
    const anchor = segment.occurrenceIds
      .map((occurrenceId) => deps.snapshot.occurrences.find((candidate) => candidate.occurrenceId === occurrenceId))
      .find((occurrence) => occurrence !== undefined && binding.table.indexOf.has(toAnchorId(occurrence.anchorId)));
    const resolution = anchor === undefined
      ? binding.navigateToIsland(region.islandId, reduced)
      : binding.navigateToAnchor(toAnchorId(anchor.anchorId), reduced);
    if (!resolution.ok) {
      deps.showTravelStatus({
        'unknown-target': 'That segment is not in this Atlas.',
        'outside-resident-field': 'That region is outside the resident field.',
        'no-safe-surface': 'No safe arrival point is available near that segment. Open Map to approach its region.',
        occluded: 'That segment is present, but no clear arrival point is available.',
      }[resolution.reason], 'failure');
      return;
    }
    deps.showWorld();
    deps.showTravelStatus(reduced ? 'Located the segment.' : 'Moving to the segment…');
  }

  function name(segmentId: string, displayName: string): void {
    const segment = segmentById(segmentId);
    if (segment === undefined || env.preview) return;
    const target = namingTargetFor(segment, deps.snapshot, state.atlas?.binding.inspectionView?.captureIds[0] ?? null);
    if (target.kind !== 'offer') return;
    const occurrence = target.occurrence;
    const trimmed = displayName.trim();
    if (trimmed.length === 0) return;

    state.issued += 1;
    const issued = state.issued;
    const proposalId = `proposal-${issued}`;
    const entity = syntheticEntityFor(occurrence);
    const draft = draftEdit(deps.snapshot, entity, trimmed, (kind) => `${kind}-${issued}`);
    const translated = toUpdateProposal(draft, {
      proposalId,
      turnId: `turn-${issued}`,
      stateVersion: deps.session.stateVersion(),
      occurrenceId: occurrence.occurrenceId,
    });
    deps.hideOtherConfirms();
    if (!translated.ok) {
      deps.confirm.reportFailure(translated.reason);
      return;
    }
    deps.session.stage(translated.proposal);
    deps.confirm.show(proposalId, confirmationFor(draft, entity), trimmed);
  }

  render();

  return {
    root: panel.root,
    resolveAt,
    async begin() {
      // A new renderer holds no overlay, whatever the previous one held.
      begun = true;
      appliedKey = null;
      region = null;
      await sync();
    },
    dispose() {
      listeners.abort();
      takeOff();
    },
  };
}
