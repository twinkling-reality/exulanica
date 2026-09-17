import type { OwnedDistrict } from './owned-district.js';

/** Presentation intent over retained subject capabilities. This grants no source authority. */
export type RepresentationOrigin = 'inferred' | 'authored' | 'generated' | 'external';
export type RepresentationAvailability = 'available' | 'unavailable' | 'withdrawn';
export type PointBasis =
  | 'retained-points'
  | 'gaussian-centres'
  | 'mesh-vertices'
  | 'mesh-surface-samples';

export interface RepresentationIntent {
  readonly pointMix: number;
  readonly boxes: boolean;
  readonly labels: boolean;
  readonly ids: boolean;
  readonly data: boolean;
  readonly binary: 'off' | 'visualization';
}
export const DEFAULT_REPRESENTATION_INTENT: RepresentationIntent = Object.freeze({
  pointMix: 0, boxes: false, labels: false, ids: false, data: false, binary: 'off',
});

export interface RepresentationBounds {
  readonly frameId: string;
  readonly units: 'metres' | 'centimetres' | 'millimetres' | 'scene-units';
  readonly origin: RepresentationOrigin;
  readonly basis: 'segment' | 'source-bounds' | 'authored-bounds';
  readonly min: readonly [number, number, number];
  readonly max: readonly [number, number, number];
}
export interface RepresentationSubject {
  readonly subjectId: string;
  readonly subjectKind: 'scene' | 'object' | 'geometry-group';
  readonly sceneId: string | null;
  readonly frameId: string;
  readonly origin: RepresentationOrigin;
  readonly sourceRefs: readonly string[];
  readonly availability: RepresentationAvailability;
  readonly rendered: boolean;
  readonly points: PointBasis | null;
  readonly compatibleBlend: boolean;
  readonly bounds: RepresentationBounds | null;
  readonly label: string | null;
  readonly dataAvailable: boolean;
  readonly unavailableReason: string | null;
}
export interface RepresentationResolution {
  readonly subjectId: string;
  readonly renderedWeight: number;
  readonly pointWeight: number;
  readonly pointLabel: string | null;
  readonly boxes: boolean;
  readonly labels: boolean;
  readonly ids: boolean;
  readonly data: boolean;
  readonly binary: boolean;
  readonly geometryVisible: boolean;
  readonly reasons: readonly string[];
}

const ORIGINS: readonly RepresentationOrigin[] = ['inferred', 'authored', 'generated', 'external'];
const POINT_LABELS: Readonly<Record<PointBasis, string>> = Object.freeze({
  'retained-points': 'Retained points',
  'gaussian-centres': 'Trained Gaussian centres',
  'mesh-vertices': 'Sampled mesh points',
  'mesh-surface-samples': 'Generated surface samples',
});

export function representationIntent(value: RepresentationIntent): RepresentationIntent {
  const keys = ['pointMix', 'boxes', 'labels', 'ids', 'data', 'binary'];
  if (Object.keys(value).some(key => !keys.includes(key))
    || !Number.isFinite(value.pointMix) || value.pointMix < 0 || value.pointMix > 1
    || [value.boxes, value.labels, value.ids, value.data].some(v => typeof v !== 'boolean')
    || !['off', 'visualization'].includes(value.binary)) {
    throw new TypeError('Unsupported representation intent');
  }
  return Object.freeze({ ...value });
}

export function validateRepresentationSubject(subject: RepresentationSubject): void {
  if (!subject.subjectId || !subject.frameId || !ORIGINS.includes(subject.origin)
    || !['scene', 'object', 'geometry-group'].includes(subject.subjectKind)
    || [subject.rendered, subject.compatibleBlend, subject.dataAvailable].some(v => typeof v !== 'boolean')
    || !['available', 'unavailable', 'withdrawn'].includes(subject.availability)
    || (subject.points !== null && !Object.hasOwn(POINT_LABELS, subject.points))
    || subject.sourceRefs.length > 128 || subject.sourceRefs.some(ref => !ref)
    || (subject.compatibleBlend && (!subject.rendered || subject.points === null))) {
    throw new TypeError('Unsupported representation subject or capabilities');
  }
  const bounds = subject.bounds;
  if (bounds !== null && (!bounds.frameId || !ORIGINS.includes(bounds.origin)
    || !['metres', 'centimetres', 'millimetres', 'scene-units'].includes(bounds.units)
    || !['segment', 'source-bounds', 'authored-bounds'].includes(bounds.basis)
    || bounds.frameId !== subject.frameId
    || bounds.min.length !== 3 || bounds.max.length !== 3
    || ![...bounds.min, ...bounds.max].every(Number.isFinite)
    || bounds.min.some((v, i) => v > bounds.max[i]!))) {
    throw new TypeError('Representation bounds require an explicit supported frame and origin');
  }
}

/** Residency, parent visibility and current rights win; fallback never makes hidden data visible. */
export function resolveRepresentation(
  intent: RepresentationIntent, subject: RepresentationSubject, parentVisible = true,
): RepresentationResolution {
  representationIntent(intent);
  validateRepresentationSubject(subject);
  const live = subject.availability === 'available';
  const visible = live && parentVisible;
  let renderedWeight = 0;
  let pointWeight = 0;
  const reasons: string[] = [];
  if (!live) reasons.push(subject.unavailableReason ?? `Subject is ${subject.availability}.`);
  else if (!parentVisible) reasons.push('Geometry is hidden by its existing parent or residency state.');
  if (visible) {
    if (subject.rendered && subject.points !== null) {
      if (subject.compatibleBlend) {
        renderedWeight = 1 - intent.pointMix;
        pointWeight = intent.pointMix;
      } else {
        pointWeight = intent.pointMix === 1 ? 1 : 0;
        renderedWeight = 1 - pointWeight;
        if (intent.pointMix > 0 && intent.pointMix < 1) reasons.push('This subject supports endpoint switching only.');
      }
    } else if (subject.rendered) {
      renderedWeight = 1;
      if (intent.pointMix > 0) reasons.push(subject.unavailableReason ?? 'No compatible retained point buffer is available.');
    } else if (subject.points !== null) {
      pointWeight = 1;
      if (intent.pointMix < 1) reasons.push('Only a point representation is available.');
    } else reasons.push('No drawable representation is available.');
  }
  if (live && intent.boxes && subject.bounds === null) reasons.push('No supported subject bounds are available.');
  if (live && intent.labels && subject.label === null) reasons.push('No semantic label is available.');
  if (live && intent.data && !subject.dataAvailable) reasons.push('Selected source records are unavailable.');
  return Object.freeze({
    subjectId: subject.subjectId, renderedWeight, pointWeight,
    pointLabel: subject.points === null ? null : POINT_LABELS[subject.points],
    boxes: visible && intent.boxes && subject.bounds !== null,
    labels: visible && intent.labels && subject.label !== null,
    ids: visible && intent.ids,
    data: live && intent.data && subject.dataAvailable,
    binary: visible && intent.binary === 'visualization',
    geometryVisible: renderedWeight > 0 || pointWeight > 0,
    reasons: Object.freeze(reasons),
  });
}

/** Even addresses in the existing buffer; no interpolation or synthesized surface points. */
export function representationSampleIndices(sourceCount: number, limit: number): Uint32Array {
  if (!Number.isSafeInteger(sourceCount) || sourceCount < 0 || sourceCount > 0xffff_ffff
    || !Number.isSafeInteger(limit) || limit < 0 || limit > 65_536) {
    throw new TypeError('Point sampling exceeds its bounded address budget');
  }
  const n = Math.min(sourceCount, limit);
  return Uint32Array.from({ length: n }, (_, i) => Math.floor(i * sourceCount / n));
}

/** Actual district feature records, never aggregate render batches presented as segmentation. */
export function districtRepresentationSubjects(
  district: OwnedDistrict,
  availability: RepresentationAvailability = 'available',
): readonly RepresentationSubject[] {
  const frameId = `${district.frame?.name ?? `district:${district.district_id}:local`}:render-metres`;
  const sourceRefs = Object.freeze(district.source_records.map(source => source.sha256));
  const dataAvailable = availability === 'available' && district.source_records.length > 0
    && district.source_records.every(source => source.operation_rights.display === true);
  return Object.freeze(district.buildings.map(building => Object.freeze({
    subjectId: building.id,
    subjectKind: 'object' as const,
    sceneId: null,
    frameId,
    origin: 'external' as const,
    sourceRefs,
    availability,
    rendered: true,
    points: null,
    // Every district building shares one aggregate draw, so per-building point switching is not supported.
    compatibleBlend: false,
    bounds: Object.freeze({
      frameId,
      units: 'metres' as const,
      origin: 'external' as const,
      basis: 'source-bounds' as const,
      min: Object.freeze([
        building.bbox_cm[0] / 100,
        0,
        building.bbox_cm[1] / 100,
      ]) as readonly [number, number, number],
      max: Object.freeze([
        building.bbox_cm[2] / 100,
        building.height_cm / 100,
        building.bbox_cm[3] / 100,
      ]) as readonly [number, number, number],
    }),
    label: building.name,
    dataAvailable,
    unavailableReason: availability === 'available'
      ? 'Building geometry shares an aggregate district draw; no per-feature point buffer.'
      : `District feature is ${availability}.`,
  })));
}

/** Formats actual supplied bytes only. Caller must authorize the selected artifact before reading it. */
export function artifactByteWindow(bytes: Uint8Array, offset = 0, length = 64): {
  readonly offset: number; readonly totalBytes: number; readonly hex: string; readonly binary: string;
} {
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > bytes.byteLength
    || !Number.isSafeInteger(length) || length < 1 || length > 256) {
    throw new TypeError('Selected artifact inspection is limited to 256 bytes per window');
  }
  const values = bytes.subarray(offset, offset + length);
  return Object.freeze({ offset, totalBytes: bytes.byteLength,
    hex: Array.from(values, v => v.toString(16).padStart(2, '0')).join(' '),
    binary: Array.from(values, v => v.toString(2).padStart(8, '0')).join(' '),
  });
}

/** Decorative identity-derived bits. They are never represented as artifact or reconstruction bytes. */
export function representationBinaryVisualization(subjectId: string, count = 64): {
  readonly label: 'Generated binary visualization, not artifact bytes'; readonly bits: string;
} {
  if (!subjectId || !Number.isSafeInteger(count) || count < 1 || count > 256) {
    throw new TypeError('Binary visualization exceeds its bounded character budget');
  }
  let seed = 2166136261;
  for (const character of subjectId) seed = Math.imul(seed ^ character.charCodeAt(0), 16777619);
  let bits = '';
  for (let i = 0; i < count; i += 1) {
    seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5;
    bits += String(seed & 1);
  }
  return Object.freeze({ label: 'Generated binary visualization, not artifact bytes', bits });
}
