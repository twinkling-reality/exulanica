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
  /** What a point's colour says: where the subject came from, or what kind of subject it is. */
  readonly colour: 'origin' | 'kind';
}
export const DEFAULT_REPRESENTATION_INTENT: RepresentationIntent = Object.freeze({
  pointMix: 0, boxes: false, labels: false, ids: false, data: false, binary: 'off', colour: 'origin',
});

/**
 * The point budget of the data view, MEASURED rather than chosen, in
 * `web/packages/atlas-react/src/playcanvas/data-view/frame-budget.log.txt`: the owned district with
 * every point on, at 1440x900 in Chrome 152 on an Apple M3 Pro (ANGLE Metal, WebGL2), at street
 * level and from above with the whole district in view. 4,110,676 points kept every frame on the
 * 60 Hz presentation in both views (p95 16.7 to 16.8 ms, no interval above 16.8 ms); 8,221,358 kept
 * it at street level and fell to a 66.7 ms p95 from above. The budget is the largest power of two
 * that held both views.
 */
export const REPRESENTATION_POINT_BUDGET = 4_194_304;
/** One subject may hold at most this many; a larger demand is scaled, never truncated by order. */
export const REPRESENTATION_POINTS_PER_SUBJECT = 2_097_152;

/**
 * `generated-extent` is the extent of triangles the world generated from its own records: an
 * aggregate district batch's mesh, or the triangle ranges a tessellator produced from one grammar
 * record. The three older bases cannot say that. `segment` is a recovered segmentation,
 * `source-bounds` is an extent a source or artifact declared, and `authored-bounds` is one a
 * person drew; a generated extent is none of those and must not read as a measurement.
 */
export type RepresentationBoundsBasis = 'segment' | 'source-bounds' | 'authored-bounds' | 'generated-extent';

export interface RepresentationBounds {
  readonly frameId: string;
  readonly units: 'metres' | 'centimetres' | 'millimetres' | 'scene-units';
  readonly origin: RepresentationOrigin;
  readonly basis: RepresentationBoundsBasis;
  readonly min: readonly [number, number, number];
  readonly max: readonly [number, number, number];
}

/**
 * How a subject that holds both forms moves between them.
 *
 * `crossfade`: the rendered surface fades out as its points fade in. `overlay`: the rendered look
 * has no fade this view can drive (a trained splat, a point-map surface, a point map's own look),
 * so it stays whole while its points fade in over it, and leaves only at the points end.
 */
export type RepresentationBlend = 'crossfade' | 'overlay';

/** The grammar record a generated subject stands for, exactly as the record states it. */
export interface RepresentationRecordReference {
  readonly kind: GeneratedIdentityRecordKind;
  readonly version: number;
  /** The canonical lowercase UUID the record carries. Never minted here. */
  readonly identity: string;
  /** The record's own ordinal fields, `name.value` joined by `/`, for example `edge_ordinal.3`. */
  readonly key: string;
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
  /** Absent means `crossfade`. Only meaningful, and only accepted, with `compatibleBlend`. */
  readonly blend?: RepresentationBlend;
  /** Present only for a subject that stands for one generated grammar record. */
  readonly record?: RepresentationRecordReference;
}
export interface RepresentationResolution {
  readonly subjectId: string;
  readonly renderedWeight: number;
  readonly pointWeight: number;
  readonly pointLabel: string | null;
  /** How this subject moves between its forms in this view, or `none` when it holds one form. */
  readonly blend: RepresentationBlend | 'endpoint' | 'none';
  /** A box is drawn: the subject is visible, boxes are on, and it has bounds of its own. */
  readonly boxes: boolean;
  /** A label tag is drawn: its own label, placed at a corner of its own bounds. */
  readonly labels: boolean;
  /** An id tag is drawn: its own id, placed at a corner of its own bounds. */
  readonly ids: boolean;
  readonly data: boolean;
  readonly binary: boolean;
  /** The palette key the subject's points are coloured by: its origin, or its own kind. */
  readonly colourKey: string;
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
const BOUNDS_BASES: readonly RepresentationBoundsBasis[] = ['segment', 'source-bounds', 'authored-bounds', 'generated-extent'];
const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const RECORD_KEY = /^(?:[a-z][a-z0-9_]*\.(?:0|[1-9][0-9]{0,15})(?:\/[a-z][a-z0-9_]*\.(?:0|[1-9][0-9]{0,15}))*)?$/;

export function representationIntent(value: RepresentationIntent): RepresentationIntent {
  const keys = ['pointMix', 'boxes', 'labels', 'ids', 'data', 'binary', 'colour'];
  if (Object.keys(value).some(key => !keys.includes(key))
    || !Number.isFinite(value.pointMix) || value.pointMix < 0 || value.pointMix > 1
    || [value.boxes, value.labels, value.ids, value.data].some(v => typeof v !== 'boolean')
    || !['off', 'visualization'].includes(value.binary)
    || !['origin', 'kind'].includes(value.colour)) {
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
    || (subject.compatibleBlend && (!subject.rendered || subject.points === null))
    || (subject.blend !== undefined
      && (!subject.compatibleBlend || !['crossfade', 'overlay'].includes(subject.blend)))) {
    throw new TypeError('Unsupported representation subject or capabilities');
  }
  const record = subject.record;
  if (record !== undefined && (!(GENERATED_IDENTITY_RECORD_KINDS as readonly string[]).includes(record.kind)
    || !Number.isSafeInteger(record.version) || record.version < 1
    || !CANONICAL_UUID.test(record.identity) || !RECORD_KEY.test(record.key)
    || subject.origin !== 'generated' || subject.subjectKind !== 'object')) {
    throw new TypeError('A record subject names a generated identity record exactly as it states itself');
  }
  const bounds = subject.bounds;
  if (bounds !== null && (!bounds.frameId || !ORIGINS.includes(bounds.origin)
    || !['metres', 'centimetres', 'millimetres', 'scene-units'].includes(bounds.units)
    || !BOUNDS_BASES.includes(bounds.basis)
    || (bounds.basis === 'generated-extent' && bounds.origin !== 'generated')
    || bounds.frameId !== subject.frameId
    || bounds.min.length !== 3 || bounds.max.length !== 3
    || ![...bounds.min, ...bounds.max].every(Number.isFinite)
    || bounds.min.some((v, i) => v > bounds.max[i]!))) {
    throw new TypeError('Representation bounds require an explicit supported frame and origin');
  }
}

/** The palette key a subject's points take: its closed origin, or its own declared kind. */
export function representationColourKey(intent: RepresentationIntent, subject: RepresentationSubject): string {
  return intent.colour === 'origin' ? subject.origin : subject.record?.kind ?? subject.subjectKind;
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
  let blend: RepresentationResolution['blend'] = 'none';
  const reasons: string[] = [];
  if (!live) reasons.push(subject.unavailableReason ?? `Subject is ${subject.availability}.`);
  else if (!parentVisible) reasons.push('Geometry is hidden by its existing parent or residency state.');
  if (visible) {
    if (subject.rendered && subject.points !== null) {
      if (subject.compatibleBlend && (subject.blend ?? 'crossfade') === 'crossfade') {
        blend = 'crossfade';
        renderedWeight = 1 - intent.pointMix;
        pointWeight = intent.pointMix;
      } else if (subject.compatibleBlend) {
        blend = 'overlay';
        pointWeight = intent.pointMix;
        renderedWeight = intent.pointMix === 1 ? 0 : 1;
        if (intent.pointMix > 0 && intent.pointMix < 1) {
          reasons.push('The rendered look cannot fade here, so its points fade in over it and it leaves at the points end.');
        }
      } else {
        blend = 'endpoint';
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
  const bounded = subject.bounds !== null;
  if (live && !bounded && (intent.boxes || intent.labels || intent.ids)) {
    reasons.push('No supported subject bounds are available, so no box or tag is drawn.');
  }
  if (live && intent.labels && subject.label === null) reasons.push('No semantic label is available.');
  if (live && intent.data && !subject.dataAvailable) reasons.push('Selected source records are unavailable.');
  return Object.freeze({
    subjectId: subject.subjectId, renderedWeight, pointWeight,
    pointLabel: subject.points === null ? null : POINT_LABELS[subject.points],
    blend,
    boxes: visible && intent.boxes && bounded,
    labels: visible && intent.labels && subject.label !== null && bounded,
    ids: visible && intent.ids && bounded,
    data: live && intent.data && subject.dataAvailable,
    binary: visible && intent.binary === 'visualization',
    colourKey: representationColourKey(intent, subject),
    geometryVisible: renderedWeight > 0 || pointWeight > 0,
    reasons: Object.freeze(reasons),
  });
}

/** Even addresses in the existing buffer; no interpolation or synthesized surface points. */
export function representationSampleIndices(sourceCount: number, limit: number): Uint32Array {
  if (!Number.isSafeInteger(sourceCount) || sourceCount < 0 || sourceCount > 0xffff_ffff
    || !Number.isSafeInteger(limit) || limit < 0 || limit > REPRESENTATION_POINTS_PER_SUBJECT) {
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

/**
 * THE GENERATED STREET SUBJECT CONTRACT. Types and one pure constructor; nothing is wired to a tile.
 *
 * A baked tile registers one subject per grammar record that STATES an identity. In city.v1 those
 * are the five building records below, each carrying `building_identity`. The others state none,
 * so they get no subject, no box and no tag: the container's "no identity" marker is honoured, and
 * no id is minted for them here. Trees and lamps (`city.street_furniture`) gain a subject only when
 * the grammar gives the record an identity of its own; adding that kind to the first list is then
 * a version of this contract.
 */
export const GENERATED_IDENTITY_RECORD_KINDS = [
  'city.massing', 'city.facade', 'city.surface_material', 'city.vitrine', 'city.premises',
] as const;
export const GENERATED_ANONYMOUS_RECORD_KINDS = [
  'city.terrain', 'city.street_node', 'city.street_segment', 'city.curb_edge', 'city.parcel',
  'city.street_furniture', 'city.tile',
] as const;
export type GeneratedIdentityRecordKind = (typeof GENERATED_IDENTITY_RECORD_KINDS)[number];
export type GeneratedAnonymousRecordKind = (typeof GENERATED_ANONYMOUS_RECORD_KINDS)[number];

/** The ordinal fields that tell two records of one kind and one identity apart, in record order. */
const GENERATED_RECORD_ORDINALS: Readonly<Record<GeneratedIdentityRecordKind, readonly string[]>> = Object.freeze({
  'city.massing': ['parcel_ordinal'],
  'city.facade': ['edge_ordinal'],
  'city.surface_material': ['edge_ordinal'],
  'city.vitrine': ['edge_ordinal', 'bay_ordinal'],
  'city.premises': ['unit_ordinal'],
});

/** A record in `exulanica.grammar.records.record_payload` form, as the tile document holds it. */
export interface GeneratedRecordPayload {
  readonly kind: string;
  readonly version: number;
  readonly fields: Readonly<Record<string, unknown>>;
}

/** The tile a registration belongs to. The runtime that draws the tile supplies all of it. */
export interface GeneratedTileReference {
  readonly tileX: number;
  readonly tileY: number;
  readonly lod: number;
  /** The frame the tile's render batches are drawn in: metres, the container's own axes. */
  readonly frameId: string;
  /** `tile_inputs_digest` of the tile, lowercase hex. The subject's source reference. */
  readonly inputsDigest: string;
}

export interface GeneratedRecordRegistration {
  readonly record: GeneratedRecordPayload;
  /**
   * Integer millimetres in the tile's frame: the extent of the triangle ranges the container
   * attributes to this record. Null when the record produced no triangles; the subject then has
   * no bounds, and so no box and no tag.
   */
  readonly extentMm: {
    readonly min: readonly [number, number, number];
    readonly max: readonly [number, number, number];
  } | null;
  /** True when the runtime draws this record's ranges as their own draw, so they can fade alone. */
  readonly drawnSeparately: boolean;
  readonly availability: RepresentationAvailability;
}

export type GeneratedRecordSubjectResult =
  | { readonly subject: RepresentationSubject; readonly reason: null }
  | { readonly subject: null; readonly reason: string };

/**
 * The one subject a generated record may have, or the stated reason it has none.
 *
 * The subject id is `generated:<kind>:<identity>` followed by the record's own ordinals, because
 * five records share one building identity and a registry holds each subject once. The identity
 * itself is carried verbatim in `record.identity` and never altered.
 */
export function generatedRecordSubject(
  tile: GeneratedTileReference, registration: GeneratedRecordRegistration,
): GeneratedRecordSubjectResult {
  const { record } = registration;
  if (!Number.isSafeInteger(tile.tileX) || !Number.isSafeInteger(tile.tileY)
    || !Number.isSafeInteger(tile.lod) || tile.lod < 0 || !tile.frameId
    || !/^[0-9a-f]{64}$/.test(tile.inputsDigest)) {
    throw new TypeError('A generated tile reference needs integer coordinates, a frame and its inputs digest');
  }
  if (typeof record.kind !== 'string' || !Number.isSafeInteger(record.version) || record.version < 1
    || typeof record.fields !== 'object' || record.fields === null) {
    throw new TypeError('A generated record is a record_payload with a kind, a version and fields');
  }
  if ((GENERATED_ANONYMOUS_RECORD_KINDS as readonly string[]).includes(record.kind)) {
    return Object.freeze({ subject: null, reason: `${record.kind} states no identity, so it has no subject, box or tag.` });
  }
  if (!(GENERATED_IDENTITY_RECORD_KINDS as readonly string[]).includes(record.kind)) {
    throw new TypeError(`Unknown generated record kind ${record.kind}`);
  }
  const kind = record.kind as GeneratedIdentityRecordKind;
  const identity = record.fields['building_identity'];
  if (typeof identity !== 'string' || !CANONICAL_UUID.test(identity)) {
    throw new TypeError(`${kind} must state building_identity as a canonical lowercase UUID`);
  }
  const key = GENERATED_RECORD_ORDINALS[kind].map(field => {
    const value = record.fields[field];
    if (!Number.isSafeInteger(value) || (value as number) < 0) {
      throw new TypeError(`${kind} must state ${field} as a non-negative integer`);
    }
    return `${field}.${value as number}`;
  }).join('/');
  const extent = registration.extentMm;
  if (extent !== null && (extent.min.length !== 3 || extent.max.length !== 3
    || ![...extent.min, ...extent.max].every(Number.isSafeInteger)
    || extent.min.some((value, axis) => value > extent.max[axis]!))) {
    throw new TypeError('A generated record extent is an ordered box of integer millimetres');
  }
  const available = registration.availability === 'available';
  const subject: RepresentationSubject = Object.freeze({
    subjectId: `generated:${kind}:${identity}:${key}`,
    subjectKind: 'object' as const,
    sceneId: null,
    frameId: tile.frameId,
    origin: 'generated' as const,
    sourceRefs: Object.freeze([tile.inputsDigest]),
    availability: registration.availability,
    rendered: true,
    points: 'mesh-surface-samples' as const,
    compatibleBlend: registration.drawnSeparately,
    bounds: extent === null ? null : Object.freeze({
      frameId: tile.frameId,
      units: 'metres' as const,
      origin: 'generated' as const,
      basis: 'generated-extent' as const,
      min: Object.freeze(extent.min.map(value => value / 1000)) as readonly [number, number, number],
      max: Object.freeze(extent.max.map(value => value / 1000)) as readonly [number, number, number],
    }),
    label: null,
    dataAvailable: available,
    unavailableReason: !available
      ? `Generated record is ${registration.availability}.`
      : registration.drawnSeparately
        ? 'Sampled points are generated surface samples of this record, not measurements.'
        : 'This record shares a tile batch draw, so it switches to points only at the points end.',
    record: Object.freeze({ kind, version: record.version, identity, key }),
  });
  validateRepresentationSubject(subject);
  return Object.freeze({ subject, reason: null });
}
