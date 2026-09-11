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
 * **A segment is a set of voxels in the scene's own frame, and only that frame.** Each drawn sample
 * is carried into it by the graph's own placement transform, the one the lift used, and tinted when
 * it lands in one of a segment's cells. Not by the transform the renderer draws with: that has the
 * display frame composed in, and would put every sample in the wrong cell. The artifact is refused
 * unless its scene and its pose, placement and gate receipts are the ones the graph holds for the
 * scene being drawn. The development preview has no receipts to compare, and says so beside the list.
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
 * **A person is shown with the consent the server resolved, and named only by the server.** The
 * backend lifts a person only from a region a reviewer confirmed or drew, naming a subject whose
 * presentation state is `shown`, and sends a display name only while a naming receipt is held; the
 * panel says both in words and invents neither. There is no detector word for a person, so an
 * unnamed one is "Unnamed person" and nothing else.
 *
 * **Colour is a property of the entity.** A pure function of the entity's identifier (a person's
 * subject, an object's linked graph entity, else the segment's own content-derived id), so the same
 * person or object wears the same colour in every region, on every visit and in every build.
 */

import type { Island, IslandId } from '@exulanica/atlas-core';
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
  previewSceneSegments,
  type SceneSegment,
  type SceneSegments,
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

/**
 * FNV-1a over UTF-16 code units, then MurmurHash3's 32-bit finaliser.
 *
 * The finaliser is not decoration. FNV-1a alone barely moves its high bits for a change in the last
 * character, and the hue is read from the high bits, so identifiers that differ only in their final
 * digits (which sequential ones do) all came out the same green in the browser. The finaliser
 * spreads every input bit across the whole word.
 */
function entityHash(text: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  hash ^= hash >>> 16;
  hash = Math.imul(hash, 0x85ebca6b);
  hash ^= hash >>> 13;
  hash = Math.imul(hash, 0xc2b2ae35);
  hash ^= hash >>> 16;
  return hash >>> 0;
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
  const hue = (entityHash(key) / 0x1_0000_0000) * 2 * Math.PI;
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
  const k = canvasProjection(camera, canvas);
  if (k === null) return null;
  const dx = point[0] - k.origin[0];
  const dy = point[1] - k.origin[1];
  const dz = point[2] - k.origin[2];
  const depth = -(dx * k.z[0] + dy * k.z[1] + dz * k.z[2]);
  if (!(depth > NEAR_CLIP)) return null;
  return {
    x: k.sx * ((dx * k.x[0] + dy * k.x[1] + dz * k.x[2]) / depth) + k.ox,
    y: k.sy * ((dx * k.y[0] + dy * k.y[1] + dz * k.y[2]) / depth) + k.oy,
    depth,
  };
}

/** The camera's basis, and the affine from a view-space slope to a canvas pixel on each axis. */
interface CanvasProjection {
  readonly origin: readonly [number, number, number];
  readonly x: Rgb;
  readonly y: Rgb;
  readonly z: Rgb;
  /** Canvas x is `sx * (view x / depth) + ox`, and canvas y the same with `sy` and `oy`. */
  readonly sx: number;
  readonly ox: number;
  readonly sy: number;
  readonly oy: number;
}

/**
 * Everything about the projection that does not depend on the point, worked out once per click.
 *
 * MEASURED 2026-09-11 in the browser: re-deriving the basis and allocating a result for each of 2.9
 * million tinted samples made one click in the inspector take about 380 ms; hoisted, about 30 ms.
 * The arithmetic per sample is the same either way; only where it is done changed.
 */
function canvasProjection(
  camera: SegmentPickCamera,
  canvas: { readonly width: number; readonly height: number },
): CanvasProjection | null {
  const [fx, fy, fz] = camera.forward;
  const forwardLength = Math.hypot(fx, fy, fz);
  if (forwardLength < 1e-9) return null;
  const z: Rgb = [-fx / forwardLength, -fy / forwardLength, -fz / forwardLength];
  const [ux, uy, uz] = camera.up;
  const across = [uy * z[2] - uz * z[1], uz * z[0] - ux * z[2], ux * z[1] - uy * z[0]] as const;
  const acrossLength = Math.hypot(...across);
  if (acrossLength < 1e-9) return null;
  const x: Rgb = [across[0] / acrossLength, across[1] / acrossLength, across[2] / acrossLength];
  const y: Rgb = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]];
  const aspect = canvas.width / canvas.height;
  // Normalised device coordinates are `a * slope + b` on each axis.
  let ax: number;
  let bx = 0;
  let ay: number;
  let by = 0;
  if (camera.calibration === null) {
    const focal = 1 / Math.tan((camera.fovYDeg * Math.PI) / 360);
    ax = focal / aspect;
    ay = focal;
  } else {
    const f = calibratedCameraFrustum(camera.calibration, aspect, 1);
    ax = 2 / (f.right - f.left);
    bx = -(f.right + f.left) / (f.right - f.left);
    ay = 2 / (f.top - f.bottom);
    by = -(f.top + f.bottom) / (f.top - f.bottom);
  }
  return {
    origin: camera.position,
    x, y, z,
    sx: (canvas.width / 2) * ax,
    ox: (canvas.width / 2) * (bx + 1),
    sy: -(canvas.height / 2) * ay,
    oy: (canvas.height / 2) * (1 - by),
  };
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
  const k = canvasProjection(camera, canvas);
  if (k === null) return null;
  const [cx, cy, cz] = k.origin;
  const [x0, x1, x2] = k.x;
  const [y0, y1, y2] = k.y;
  const [z0, z1, z2] = k.z;
  const reach = tolerance * tolerance;
  const candidates: SegmentPick[] = [];
  for (const asset of assets) {
    const positions = asset.positions;
    if (positions === null) continue;
    for (let at = 0; at < asset.indices.length; at += 1) {
      const dx = positions[at * 3]! - cx;
      const dy = positions[at * 3 + 1]! - cy;
      const dz = positions[at * 3 + 2]! - cz;
      const depth = -(dx * z0 + dy * z1 + dz * z2);
      if (!(depth > NEAR_CLIP)) continue;
      const offsetX = k.sx * ((dx * x0 + dy * x1 + dz * x2) / depth) + k.ox - cursor.x;
      const offsetY = k.sy * ((dx * y0 + dy * y1 + dz * y2) / depth) + k.oy - cursor.y;
      const squared = offsetX * offsetX + offsetY * offsetY;
      if (squared > reach) continue;
      candidates.push({
        artifactId: asset.artifactId, slot: asset.slots[at]!, sampleIndex: asset.indices[at]!,
        pixelDistance: Math.sqrt(squared), depth,
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
  readonly kind: 'trained_geometry' | 'point_map';
  readonly sampleCount: number;
  /** The transform the renderer draws with, the scene's display frame composed in. */
  readonly drawnSceneFromLocal: readonly number[];
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
      drawnSceneFromLocal: visual.geometry.sceneFromAssetRowMajor,
    });
  }
  for (const visual of binding.islands) {
    if (trained.has(visual.pointMap.sceneId)) continue;
    add(visual.pointMap.sceneId, visual.island.islandId, {
      artifactId: visual.pointMap.artifactId, kind: 'point_map', sampleCount: visual.cloud.pointCount,
      drawnSceneFromLocal: visual.pointMap.sceneFromOpmRowMajor,
    });
  }
  return [...scenes].map(([sceneId, held]) => Object.freeze({ sceneId, ...held }));
}

/** One drawn asset, and the transform that carries its samples into the frame the voxels are in. */
export interface BoundAsset {
  readonly asset: DrawnAsset;
  /** Row-major affine from the asset's own frame into the scene frame the segments are gridded in. */
  readonly sceneFromLocal: readonly number[];
}

export interface SegmentBinding {
  readonly assets: readonly BoundAsset[];
  /** What could not be bound and why, and in the preview what was not checked. */
  readonly notices: readonly string[];
  /** False in the preview, where there is no receipt to compare against. */
  readonly verified: boolean;
}

/**
 * The graph's own placement of one drawn asset in the scene frame, before any display frame.
 *
 * The voxels are in the frame the lift placed samples in: a member's `scene_from_opm`, and the
 * trained delivery's `scene_from_asset`, which the geometry route holds at the identity. The
 * renderer draws with the display frame composed in, so those drawn matrices would put every
 * sample in the wrong cell; the records in the snapshot are the ones the lift used.
 */
function rawSceneFromLocal(record: ReconstructionSceneRecord, asset: DrawnAsset): readonly number[] | null {
  if (asset.kind === 'trained_geometry') {
    return record.trainedGeometry?.artifactId === asset.artifactId ? record.trainedGeometry.sceneFromAssetRowMajor : null;
  }
  return record.members.find((member) => member.placement?.artifactId === asset.artifactId)?.placement?.sceneFromOpmRowMajor ?? null;
}

/**
 * Whether these segments are about the geometry drawn here, and through which transforms.
 *
 * The route already refuses an artifact whose bindings moved and withholds a segment whose inputs
 * changed. This is the second look, on this side: the scene, and the pose and placement receipts
 * the artifact names, against the ones the graph holds for the scene being drawn. Either of them
 * disagreeing means the voxels describe other geometry, and nothing is tinted.
 *
 * Not the gate. The graph's `gateDigest` is the digest of the gate DECISION, from the rung
 * assertion, and the artifact's `gateReceiptSha256` is the SHA-256 of the whole gate receipt, the
 * envelope that decision sits in, so the two differ for every scene. MEASURED on the volcanic scene
 * against a running backend: `1eb52108...` against `57189a4b...`, and comparing them refused every
 * real scene. The gate does not move the frame the voxels are in, which the pose and placement
 * pin, and the route refuses segments bound to another gate receipt before any reach this side.
 *
 * The preview has no scene record and no receipts. Its one map is drawn with the identity transform,
 * which is its scene frame, and the panel says nothing was compared.
 */
export function bindSegments(
  segments: SceneSegments,
  drawn: DrawnScene,
  record: ReconstructionSceneRecord | undefined,
  preview: boolean,
): SegmentBinding {
  if (preview) {
    return {
      assets: drawn.assets.map((asset) => ({ asset, sceneFromLocal: asset.drawnSceneFromLocal })),
      verified: false,
      notices: [
        'Synthetic preview: these are the published fixture’s segments, for a scene this preview does not '
          + 'draw. No receipt was compared, because the preview has none, and a segment is tinted only where '
          + 'a drawn sample falls in one of its voxels.',
      ],
    };
  }
  const refuse = (reason: string): SegmentBinding => ({ assets: [], verified: true, notices: [reason] });
  if (segments.sceneId !== drawn.sceneId) return refuse('These segments were recorded for a different scene.');
  if (record === undefined) {
    return refuse('The graph holds no record of this scene, so nothing the segments are bound to can be checked.');
  }
  if (segments.poseReceiptSha256 !== record.poseReceiptSha256) {
    return refuse('These segments were computed against a different pose receipt, so nothing is tinted.');
  }
  if (segments.placementReceiptSha256 !== record.placementReceiptSha256) {
    return refuse('These segments were computed against a different placement receipt, so nothing is tinted.');
  }
  const assets: BoundAsset[] = [];
  const notices: string[] = [];
  for (const asset of drawn.assets) {
    const sceneFromLocal = rawSceneFromLocal(record, asset);
    if (sceneFromLocal === null) {
      notices.push(`The graph holds no placement for drawn asset ${asset.artifactId}, so its samples cannot be placed on the segment grid.`);
      continue;
    }
    assets.push({ asset, sceneFromLocal });
  }
  return { assets, verified: true, notices };
}

/** The segments' cells as one dense byte grid: the slot of the first segment to claim each cell. */
export interface SegmentGrid {
  readonly edgeMicrounits: number;
  readonly origin: readonly [number, number, number];
  readonly size: readonly [number, number, number];
  readonly slots: Uint8Array;
  /** Cells two segments both occupy, each tinted as the one listed first. */
  readonly contested: number;
}

/** A grid larger than this is refused rather than allocated. 128 cells a side is what the lift uses. */
const GRID_CELL_LIMIT = 16_777_216;

/**
 * Rasterise the segments' voxels into one grid, in the artifact's own order.
 *
 * The artifact lists people before objects, which is the lift's own precedence: a reviewed person
 * takes a sample an object ties for. A cell two segments share follows the same rule here, so a
 * drawn sample is tinted as the entity the lift would have given it to.
 */
export function segmentGrid(
  segments: readonly SceneSegment[],
  slotOf: ReadonlyMap<string, number>,
  edgeMicrounits: number,
): SegmentGrid | null {
  const low = [Infinity, Infinity, Infinity];
  const high = [-Infinity, -Infinity, -Infinity];
  for (const segment of segments) {
    if (!slotOf.has(segment.segmentId)) continue;
    for (let at = 0; at < segment.voxels.length; at += 3) {
      for (let axis = 0; axis < 3; axis += 1) {
        low[axis] = Math.min(low[axis]!, segment.voxels[at + axis]!);
        high[axis] = Math.max(high[axis]!, segment.voxels[at + axis]!);
      }
    }
  }
  if (low[0] === Infinity) return null;
  const size = [0, 1, 2].map((axis) => high[axis]! - low[axis]! + 1) as [number, number, number];
  if (size[0] * size[1] * size[2] > GRID_CELL_LIMIT) return null;
  const slots = new Uint8Array(size[0] * size[1] * size[2]);
  let contested = 0;
  for (const segment of segments) {
    const slot = slotOf.get(segment.segmentId);
    if (slot === undefined) continue;
    for (let at = 0; at < segment.voxels.length; at += 3) {
      const cell = ((segment.voxels[at]! - low[0]!) * size[1] + (segment.voxels[at + 1]! - low[1]!)) * size[2]
        + (segment.voxels[at + 2]! - low[2]!);
      if (slots[cell] === 0) slots[cell] = slot;
      else if (slots[cell] !== slot) contested += 1;
    }
  }
  return { edgeMicrounits, origin: [low[0]!, low[1]!, low[2]!], size, slots, contested };
}

/**
 * The slot of every sample, by the cell it lands in: `floor(x * 1e6 / edge)` along each axis.
 *
 * The lift's own rule, spelled in `exulanica/ingest/scene_segments.py` as `_voxels`, applied to each
 * drawn sample carried into the scene frame by the same row-major transform the lift used. A sample
 * outside every segment's cells is slot 0, and so is every sample when there is no grid.
 */
export function classifySamples(positions: Float32Array, sceneFromLocal: readonly number[], grid: SegmentGrid): Uint8Array {
  const m = sceneFromLocal;
  const scale = 1_000_000 / grid.edgeMicrounits;
  const [ox, oy, oz] = grid.origin;
  const [sx, sy, sz] = grid.size;
  const slots = new Uint8Array(positions.length / 3);
  for (let index = 0; index < slots.length; index += 1) {
    const x = positions[index * 3]!;
    const y = positions[index * 3 + 1]!;
    const z = positions[index * 3 + 2]!;
    const i = Math.floor((m[0]! * x + m[1]! * y + m[2]! * z + m[3]!) * scale) - ox;
    const j = Math.floor((m[4]! * x + m[5]! * y + m[6]! * z + m[7]!) * scale) - oy;
    const k = Math.floor((m[8]! * x + m[9]! * y + m[10]! * z + m[11]!) * scale) - oz;
    if (i < 0 || j < 0 || k < 0 || i >= sx || j >= sy || k >= sz) continue;
    slots[index] = grid.slots[(i * sy + j) * sz + k]!;
  }
  return slots;
}

export interface SegmentPlan {
  /** Every segment in the artifact's own order. The list and the slot numbers both follow it. */
  readonly ordered: readonly SceneSegment[];
  readonly slotOf: ReadonlyMap<string, number>;
  readonly segmentOfSlot: ReadonlyMap<number, SceneSegment>;
  /** Why a listed segment is not tinted. */
  readonly untinted: ReadonlyMap<string, string>;
  readonly tints: readonly SegmentOverlayTint[];
  /** Cells two segments both occupy. */
  readonly contested: number;
  /** Drawn samples that fell in some segment's cells. */
  readonly tintedSamples: number;
  /** Drawn assets whose samples the binding could not read, so they could not be placed. */
  readonly unread: readonly string[];
}

/**
 * Slot numbers, and the drawn samples each segment covers, for every bound asset.
 *
 * `localSamples` is the binding's read of an asset's samples in its own frame; an asset it cannot
 * read is skipped and said to be. A segment none of whose cells holds a drawn sample stays in the
 * list and is not tinted, with that reason beside it.
 */
export function planSegmentTints(
  segments: SceneSegments,
  binding: SegmentBinding,
  localSamples: (artifactId: string) => Float32Array | null,
): SegmentPlan {
  const ordered = segments.segments;
  const slotOf = new Map<string, number>();
  const segmentOfSlot = new Map<number, SceneSegment>();
  const untinted = new Map<string, string>();
  for (const segment of ordered) {
    if (slotOf.size >= SLOT_LIMIT) {
      untinted.set(segment.segmentId, `Not tinted: one region can carry ${SLOT_LIMIT} tinted segments.`);
      continue;
    }
    slotOf.set(segment.segmentId, slotOf.size + 1);
  }
  const grid = segments.voxelSizeMicrounits === null ? null : segmentGrid(ordered, slotOf, segments.voxelSizeMicrounits);
  const perSlot = new Map<number, SegmentOverlayTint[]>();
  const unread: string[] = [];
  let tintedSamples = 0;
  for (const { asset, sceneFromLocal } of grid === null ? [] : binding.assets) {
    const positions = localSamples(asset.artifactId);
    if (positions === null) {
      unread.push(asset.artifactId);
      continue;
    }
    const slots = classifySamples(positions, sceneFromLocal, grid!);
    // Counted, then filled: two passes over bytes and no lookup per sample. MEASURED 2026-09-11 at
    // 7.2 million drawn samples, pushing each index through a map of growing arrays made planning
    // about 186 ms; this takes it to about 112, of which the voxel lookup itself is about 62.
    const counts = new Uint32Array(SLOT_LIMIT + 1);
    for (let index = 0; index < slots.length; index += 1) counts[slots[index]!]! += 1;
    const lists: (Uint32Array | undefined)[] = [];
    for (let slot = 1; slot <= SLOT_LIMIT; slot += 1) {
      if (counts[slot] === 0) continue;
      tintedSamples += counts[slot]!;
      lists[slot] = new Uint32Array(counts[slot]!);
    }
    const filled = new Uint32Array(SLOT_LIMIT + 1);
    for (let index = 0; index < slots.length; index += 1) {
      const slot = slots[index]!;
      if (slot !== 0) lists[slot]![filled[slot]!++] = index;
    }
    lists.forEach((indices, slot) => {
      if (indices === undefined) return;
      const held = perSlot.get(slot) ?? [];
      perSlot.set(slot, held);
      held.push({ slot, artifactId: asset.artifactId, indices });
    });
  }
  const tints: SegmentOverlayTint[] = [];
  for (const segment of ordered) {
    const slot = slotOf.get(segment.segmentId);
    if (slot === undefined) continue;
    const held = perSlot.get(slot);
    if (held === undefined) {
      slotOf.delete(segment.segmentId);
      untinted.set(segment.segmentId, 'Not tinted: no sample drawn here falls in any of its voxels.');
      continue;
    }
    segmentOfSlot.set(slot, segment);
    tints.push(...held);
  }
  return { ordered, slotOf, segmentOfSlot, untinted, tints, contested: grid?.contested ?? 0, tintedSamples, unread };
}

/**
 * The key a segment's colour is derived from: the entity it is.
 *
 * A person is their subject. An object is the graph entity its detections are linked to, when any
 * is; otherwise the segment itself, whose identifier the lift derives from its kind, label and
 * voxels, so it is stable for as long as the segment is the same segment.
 */
export function colourKeyOf(
  segment: Pick<SceneSegment, 'segmentId' | 'kind' | 'subjectId' | 'occurrenceIds'>,
  snapshot: Pick<GraphSnapshot, 'occurrences'>,
): string {
  if (segment.kind === 'person' && segment.subjectId !== null) return segment.subjectId;
  for (const occurrenceId of segment.occurrenceIds) {
    const entityId = snapshot.occurrences.find((candidate) => candidate.occurrenceId === occurrenceId)?.entityId;
    if (entityId !== null && entityId !== undefined) return entityId;
  }
  return segment.segmentId;
}

/** One resolved colour per tinted slot; the emphasised segment full, the rest receded. */
export function segmentPalette(
  plan: Pick<SegmentPlan, 'slotOf' | 'segmentOfSlot'>,
  emphasis: string | null,
  snapshot: Pick<GraphSnapshot, 'occurrences'>,
): SegmentPalette {
  const palette = new Map<number, ProofLensColor>();
  const emphasised = emphasis !== null && plan.slotOf.has(emphasis) ? emphasis : null;
  for (const [segmentId, slot] of plan.slotOf) {
    const segment = plan.segmentOfSlot.get(slot);
    if (segment === undefined) continue;
    const [r, g, b] = segmentColor(colourKeyOf(segment, snapshot));
    const strength = emphasised === null ? TINT_AT_REST : segmentId === emphasised ? TINT_EMPHASISED : TINT_RECEDED;
    palette.set(slot, Object.freeze([r, g, b, strength]) as ProofLensColor);
  }
  return palette;
}

// -- naming ---------------------------------------------------------------------------------------------

export type NamingTarget =
  | { readonly kind: 'named'; readonly name: string; readonly by: 'graph' | 'person-review' }
  | { readonly kind: 'offer'; readonly occurrence: OccurrenceRecord }
  | { readonly kind: 'unavailable'; readonly reason: string };

/** The graph entity a segment's detections are linked to, when any is. */
function linkedEntity(segment: SceneSegment, snapshot: Pick<GraphSnapshot, 'entities' | 'occurrences'>): EntityRecord | undefined {
  for (const occurrenceId of segment.occurrenceIds) {
    const entityId = snapshot.occurrences.find((candidate) => candidate.occurrenceId === occurrenceId)?.entityId;
    if (entityId === null || entityId === undefined) continue;
    const entity = snapshot.entities.find((candidate) => candidate.entityId === entityId);
    if (entity !== undefined) return entity;
  }
  return undefined;
}

/**
 * What the naming flow can do with this segment, and on which detection.
 *
 * The API names a detection and creates the entity; it refuses a detection already linked, and it
 * has no rename. So a segment whose detections the graph already names shows that name, a segment
 * with an unlinked detection offers to name it (preferring the one in the photograph the inspector
 * stands on), and anything else says why nothing can be named here.
 *
 * A person segment's name is the one the server sends beside it, which it sends only while a naming
 * receipt is held and no withdrawal stands. A person the vision stage never detected has no
 * detection to name, and their name belongs to the person review, where their consent is recorded.
 */
export function namingTargetFor(
  segment: SceneSegment,
  snapshot: Pick<GraphSnapshot, 'entities' | 'occurrences'>,
  captureId: string | null,
): NamingTarget {
  if (segment.kind === 'person' && segment.displayName !== null) {
    return { kind: 'named', name: segment.displayName, by: 'person-review' };
  }
  const entity = linkedEntity(segment, snapshot);
  if (segment.kind === 'object' && entity !== undefined && typeof entity.displayName === 'string' && entity.displayName.length > 0) {
    return { kind: 'named', name: entity.displayName, by: 'graph' };
  }
  const detections = segment.occurrenceIds
    .map((occurrenceId) => snapshot.occurrences.find((candidate) => candidate.occurrenceId === occurrenceId))
    .filter((occurrence): occurrence is OccurrenceRecord => occurrence !== undefined);
  const unlinked = detections.filter((occurrence) => occurrence.entityId === null);
  const chosen = unlinked.find((occurrence) => captureId !== null && occurrence.captureId === captureId) ?? unlinked[0];
  if (chosen !== undefined) return { kind: 'offer', occurrence: chosen };
  if (segment.kind === 'person' && segment.occurrenceIds.length === 0) {
    return {
      kind: 'unavailable',
      reason: 'This person’s segment rests on reviewed outlines, not on a detection the graph holds, so the '
        + 'naming flow has nothing to name. A person’s name is recorded in the person review, with their consent.',
    };
  }
  if (detections.length === 0) {
    return {
      kind: 'unavailable',
      reason: segment.occurrenceIds.length === 0
        ? 'This segment was prompted by the local detector and names no detection the graph holds, so there '
          + 'is nothing the naming flow can name here.'
        : 'No detection behind this segment is in the graph this session reads, so there is nothing the '
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
  /** Injectable for tests. Production reads the route, the preview the published fixture. */
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
    binding.segmentOverlay.setPalette(segmentPalette(region.load.plan, emphasis(), deps.snapshot));
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
      palette: segmentPalette(load.plan, emphasis(), deps.snapshot),
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
        const plan = planSegmentTints(segments, segmentBinding,
          (artifactId) => binding.segmentOverlay.localSamples(artifactId)?.positions ?? null);
        current.load = { kind: 'ready', segments, binding: segmentBinding, plan, report: null };
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

  function headingOf(segment: SceneSegment): string {
    const target = namingTargetFor(segment, deps.snapshot, null);
    // A person's heading is the name the server sent beside them or says there is none. There is no
    // detector word for a person to fall back on, and inventing one is how a withheld name would
    // leak back in as a description.
    if (segment.kind === 'person') return target.kind === 'named' ? target.name : 'Unnamed person';
    return target.kind === 'named' ? target.name : segment.label ?? 'Unlabelled object';
  }

  function rowOf(segment: SceneSegment, load: Extract<RegionLoad, { kind: 'ready' }>, captureId: string | null): SegmentRowModel {
    const votes = segment.votes;
    const slot = load.plan.slotOf.get(segment.segmentId);
    const selected = kept.selectedSegmentId === segment.segmentId;
    const photographs = new Set(segment.regions.map((region) => region.captureId)).size;
    const facts: string[] = [];
    if (selected) {
      if (segment.kind === 'object') facts.push(`Detector label: ${segment.label ?? 'none'}.`);
      facts.push(`Confidence: at the median sample ${votes.median} of the ${votes.views} views that could see it `
        + `voted for it, and never fewer than ${votes.min}.`);
      facts.push(`Rests on ${segment.regions.length} ${segment.regions.length === 1 ? 'region' : 'regions'} in `
        + `${photographs} ${photographs === 1 ? 'photograph' : 'photographs'}, and ${segment.voxels.length / 3} voxels of the scene.`);
      if (segment.kind === 'person') {
        facts.push('Consent: a reviewer confirmed or drew this person’s outline and their presentation state is '
          + 'shown, which is the only person the server lifts into a scene.');
        facts.push(segment.displayName === null
          ? 'No naming receipt is held for this person, so no name is shown.'
          : 'A naming receipt is held for this person, and the name shown is the one it records.');
      } else {
        const entity = linkedEntityOf(segment);
        facts.push(entity === undefined ? 'Linked to no entity in the graph.' : 'Its detections are linked to an entity in the graph.');
      }
      if (picked?.segmentId === segment.segmentId) {
        facts.push(`Selected by a click: the nearest tinted sample was ${picked.pixelDistance.toFixed(1)} screen `
          + 'pixels from the pointer. That is the nearest tinted sample, not necessarily the surface under it.');
      }
    }
    const target = namingTargetFor(segment, deps.snapshot, captureId);
    const naming: SegmentNamingModel = target.kind === 'named'
      ? {
        kind: 'named',
        sentence: target.by === 'person-review'
          ? `The person review names this person ${target.name}.`
          : `The graph names this ${segment.label ?? 'object'} ${target.name}.`,
      }
      : target.kind === 'unavailable'
        ? { kind: 'unavailable', reason: target.reason }
        : env.preview
          ? { kind: 'preview' }
          : { kind: 'offer', sentence: 'Naming it names one detection behind it, exactly as naming it from the Index would.' };
    return {
      segmentId: segment.segmentId,
      heading: headingOf(segment),
      summary: `${segment.kind}, ${votes.median} of ${votes.views} views agree at the median`,
      swatch: slot === undefined ? null : cssColour(segmentColor(colourKeyOf(segment, deps.snapshot))),
      untinted: load.plan.untinted.get(segment.segmentId) ?? null,
      selected,
      facts,
      naming,
    };
  }

  function linkedEntityOf(segment: SceneSegment): string | undefined {
    for (const occurrenceId of segment.occurrenceIds) {
      const entityId = deps.snapshot.occurrences.find((candidate) => candidate.occurrenceId === occurrenceId)?.entityId;
      if (entityId !== null && entityId !== undefined) return entityId;
    }
    return undefined;
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
    const segments = load.segments;
    const notices: string[] = [];
    if (segments.withheldSegmentCount > 0) {
      notices.push(segments.withheldSegmentCount === 1
        ? 'One segment was withheld by a live consent check or the read policy, and is not listed.'
        : `${segments.withheldSegmentCount} segments were withheld by a live consent check or the read policy, and are not listed.`);
    }
    if (segments.staleInputs.length > 0) notices.push(`Stale inputs: ${segments.staleInputs.join(', ')}.`);
    notices.push(...load.binding.notices, ...(load.report?.refused.map((item) => item.reason) ?? []));
    if (load.plan.unread.length > 0) {
      notices.push('This device holds no copy of some drawn samples, so they cannot be placed on the segment grid.');
    }
    if (load.plan.contested > 0) {
      notices.push(`${load.plan.contested} voxels are occupied by two segments and tinted as the one listed first.`);
    }
    if (segments.segments.length > 0 && load.plan.tintedSamples === 0 && load.binding.assets.length > 0) {
      notices.push('No sample drawn here falls in any segment’s voxels, so nothing is tinted.');
    }
    if (load.report?.assets.some((asset) => asset.positions === null)) {
      notices.push('This device holds no copy of the trained Gaussians’ centres, so a click cannot select them; the list still can.');
    }
    const message = segments.state !== 'available'
      ? `Segments for this scene are ${segments.state}${segments.reason === null ? '.' : `: ${segments.reason}`}`
      : segments.segments.length === 0 ? 'No segments are recorded for this scene.' : null;
    return {
      on: true,
      state: 'ready',
      where,
      canInspect,
      message,
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

  /**
   * Travel to the segment's region, arriving where that region's first photograph was taken, with
   * the segment emphasised.
   *
   * Not to its detection's anchor, which the browser check tried first: anchors are seeded on a
   * presentation disc and say nothing about where the geometry is, so arriving at one left the
   * visitor facing empty ground beside the thing they asked for. The region's arrival is the one
   * recorded viewpoint direct travel can reach, and it looks at the reconstruction.
   */
  function travel(segmentId: string): void {
    const binding = state.atlas?.binding;
    const segment = segmentById(segmentId);
    if (binding === undefined || segment === undefined || region === null) {
      deps.showTravelStatus('The Atlas is still forming. Try again in a moment.', 'failure');
      return;
    }
    const reduced = deps.travelUsesReducedMotion();
    const resolution = binding.navigateToIsland(region.islandId, reduced);
    if (!resolution.ok) {
      deps.showTravelStatus({
        'unknown-target': 'That segment is not in this Atlas.',
        'outside-resident-field': 'That region is outside the resident field.',
        'no-safe-surface': 'No safe arrival point is available near that segment. Open Map to approach its region.',
        occluded: 'That segment is present, but no clear arrival point is available.',
      }[resolution.reason], 'failure');
      return;
    }
    kept.selectedSegmentId = segment.segmentId;
    picked = null;
    recolour();
    render();
    deps.showWorld();
    deps.showTravelStatus(reduced
      ? 'Arrived where this region was photographed, with the segment highlighted.'
      : 'Moving to where this region was photographed…');
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
