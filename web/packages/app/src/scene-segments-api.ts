/**
 * What the photographs found, lifted into one reconstructed scene, fetched for the segment overlay.
 *
 * `GET /scene-segments/{scene_id}` (`exulanica/api/routes/scene_segments.py`) serves one scene's
 * segment artifact under the same asset-read policy as its geometry. Each segment is an entity the
 * lift voted onto the scene: an object (a detector label, split into connected pieces) or a person
 * (a reviewed subject whose presentation state is `shown`). What it covers is a set of occupied
 * voxels in the scene's own frame, on a grid whose edge the artifact states, together with how the
 * views voted and which regions in which photographs it rests on.
 *
 * **Voxels, not sample indices, and that is the backend's decision to make.** The brief imagined
 * indices per scene asset. The lift subsamples every placed map and the trained centres, so the
 * samples it voted over are not the samples a browser draws; a voxel set in the scene frame is the
 * answer that survives that. The surface turns it back into drawn samples by carrying each one into
 * the scene frame with the graph's own placement transform and asking which cell it lands in.
 *
 * **The published fixture is the backend's.** `graph-client/test/fixtures/scene-segments.json` is
 * the body the route serves for the scene its own tests build, byte for byte, and this parser is
 * tested against it. Fields may be added on the wire and are ignored here; none may be renamed,
 * retyped or removed, and a body that did any of that is refused rather than read around.
 *
 * **Nothing here decides what may be shown.** A person segment exists only under the backend's own
 * rule, and it carries a subject reference and, only when a naming receipt is held and no withdrawal
 * stands, a display name. This file passes both through in the server's words and invents neither.
 */

import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';

export const SEGMENTS_SCHEMA_VERSION = 1;
const SEGMENTS_TIMEOUT_MS = 30_000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const SHA256 = /^[0-9a-f]{64}$/u;
const SEGMENT_ID = /^[0-9a-f]{32}$/u;

export type SegmentsState = 'available' | 'stale' | 'absent' | 'unavailable';
export type SegmentKind = 'object' | 'person';

export interface SegmentVotes {
  /** How many views the lift could project the segment's samples into. */
  readonly views: number;
  readonly min: number;
  readonly median: number;
  readonly max: number;
  readonly fractionMinMillionths: number;
  readonly fractionMedianMillionths: number;
}

export interface SegmentRegion {
  readonly captureId: string;
  readonly kind: 'object_mask' | 'person_region';
  /** The mask's own evidence span. Null for a person region, whose outline is not evidence. */
  readonly spanId: string | null;
  /** The person region's key, for the review flow. Null for an object mask. */
  readonly regionKey: string | null;
  readonly samples: number;
}

export interface SceneSegment {
  readonly segmentId: string;
  readonly kind: SegmentKind;
  /** A detector's common noun for an object. Always null for a person. */
  readonly label: string | null;
  /** The person subject. Always null for an object. */
  readonly subjectId: string | null;
  /** Present only when a naming receipt is held and no withdrawal stands. */
  readonly displayName: string | null;
  /** Occupied cells as `i, j, k` triples, flattened. */
  readonly voxels: Int32Array;
  readonly boundsMicrounits: { readonly min: readonly number[]; readonly max: readonly number[] };
  readonly centroidMicrounits: readonly number[];
  /** How many lift samples voted it in: a statement about the lift, not about what is drawn. */
  readonly samples: { readonly pointMap: number; readonly gaussian: number };
  readonly votes: SegmentVotes;
  readonly regions: readonly SegmentRegion[];
  /** The vision stage's occurrences of this object, which the naming flow can name. */
  readonly occurrenceIds: readonly string[];
}

export interface SceneSegments {
  readonly sceneId: string;
  readonly state: SegmentsState;
  readonly reason: string | null;
  readonly artifact: { readonly artifactId: string; readonly contentSha256: string; readonly byteSize: number } | null;
  readonly poseReceiptSha256: string | null;
  readonly placementReceiptSha256: string | null;
  readonly gateReceiptSha256: string | null;
  /** The voxel edge in millionths of a scene unit. Null when the scene has no segments to grid. */
  readonly voxelSizeMicrounits: number | null;
  readonly policy: Readonly<Record<string, unknown>> | null;
  readonly segments: readonly SceneSegment[];
  /** Segments a live check or the read policy took back, counted so none drawn is not "none". */
  readonly withheldSegmentCount: number;
  readonly staleInputs: readonly string[];
}

/** Why a scene has no segments to read, in words a panel can show without inventing a reason. */
export type SegmentsFailure = 'none-recorded' | 'unauthorized' | 'withdrawn' | 'timed-out' | 'unreadable';

export class SegmentsUnavailable extends Error {
  readonly kind: SegmentsFailure;
  constructor(kind: SegmentsFailure, message: string) {
    super(message);
    this.name = 'SegmentsUnavailable';
    this.kind = kind;
  }
}

const unreadable = (message: string): SegmentsUnavailable => new SegmentsUnavailable('unreadable', message);

function record(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw unreadable(`The scene segments' ${what} is not an object.`);
  }
  return value as Record<string, unknown>;
}

function integer(value: unknown, what: string, minimum = Number.MIN_SAFE_INTEGER): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    throw unreadable(`The scene segments' ${what} is not a whole number.`);
  }
  return value as number;
}

function matching(value: unknown, pattern: RegExp, what: string): string {
  if (typeof value !== 'string' || !pattern.test(value)) throw unreadable(`The scene segments' ${what} is malformed.`);
  return value;
}

function nullable<T>(value: unknown, read: (present: unknown) => T): T | null {
  return value === null || value === undefined ? null : read(value);
}

function triple(value: unknown, what: string): readonly number[] {
  if (!Array.isArray(value) || value.length !== 3) throw unreadable(`The scene segments' ${what} is not three numbers.`);
  return Object.freeze(value.map((item) => integer(item, what)));
}

function votesOf(value: unknown): SegmentVotes {
  const wire = record(value, 'votes');
  const votes = {
    views: integer(wire['views'], 'view count', 0),
    min: integer(wire['min'], 'minimum votes', 0),
    median: integer(wire['median'], 'median votes', 0),
    max: integer(wire['max'], 'maximum votes', 0),
    fractionMinMillionths: integer(wire['fraction_min_millionths'], 'minimum vote fraction', 0),
    fractionMedianMillionths: integer(wire['fraction_median_millionths'], 'median vote fraction', 0),
  };
  if (!(votes.min <= votes.median && votes.median <= votes.max && votes.max <= votes.views)) {
    throw unreadable('A segment carries votes out of order or beyond its views.');
  }
  return Object.freeze(votes);
}

function regionOf(value: unknown): SegmentRegion {
  const wire = record(value, 'region');
  const kind = wire['kind'];
  if (kind !== 'object_mask' && kind !== 'person_region') throw unreadable('A segment rests on a region of an unknown kind.');
  return Object.freeze({
    captureId: matching(wire['capture_id'], UUID, 'region capture'),
    kind,
    spanId: nullable(wire['span_id'], (id) => matching(id, UUID, 'region span')),
    regionKey: nullable(wire['region_key'], (key) => matching(key, SHA256, 'region key')),
    samples: integer(wire['samples'], 'region sample count', 0),
  });
}

function segmentOf(value: unknown): SceneSegment {
  const wire = record(value, 'segment');
  const kind = wire['kind'];
  if (kind !== 'object' && kind !== 'person') throw unreadable('A segment is of a kind this build does not know.');
  const label = nullable(wire['label'], (text) => {
    if (typeof text !== 'string' || text.length === 0) throw unreadable('A segment label is not text.');
    return text;
  });
  const subjectId = nullable(wire['subject_id'], (id) => matching(id, UUID, 'person subject'));
  // The two shapes the route promises, held: a person has a subject and no label, an object a
  // label and no subject. A body that mixed them would be describing someone as a thing.
  if (kind === 'person' ? label !== null || subjectId === null : label === null || subjectId !== null) {
    throw unreadable('A segment mixes the person and object shapes.');
  }
  const displayName = nullable(wire['display_name'], (text) => {
    if (typeof text !== 'string' || text.length === 0) throw unreadable('A segment display name is not text.');
    return text;
  });
  if (!Array.isArray(wire['voxels'])) throw unreadable('A segment holds no voxel list.');
  const voxels = new Int32Array(wire['voxels'].length * 3);
  wire['voxels'].forEach((cell, index) => voxels.set(triple(cell, 'voxel'), index * 3));
  if (integer(wire['voxel_count'], 'voxel count', 0) !== wire['voxels'].length) {
    throw unreadable('A segment holds a different number of voxels than it declares.');
  }
  const bounds = record(wire['bounds_microunits'], 'bounds');
  const samples = record(wire['samples'], 'sample counts');
  if (!Array.isArray(wire['regions']) || !Array.isArray(wire['occurrence_ids'])) {
    throw unreadable('A segment holds no region or occurrence list.');
  }
  return Object.freeze({
    segmentId: matching(wire['segment_id'], SEGMENT_ID, 'segment identifier'),
    kind,
    label,
    subjectId,
    displayName,
    voxels,
    boundsMicrounits: Object.freeze({ min: triple(bounds['min'], 'bounds'), max: triple(bounds['max'], 'bounds') }),
    centroidMicrounits: triple(wire['centroid_microunits'], 'centroid'),
    samples: Object.freeze({
      pointMap: integer(samples['point_map'], 'point-map sample count', 0),
      gaussian: integer(samples['gaussian'], 'Gaussian sample count', 0),
    }),
    votes: votesOf(wire['votes']),
    regions: Object.freeze(wire['regions'].map(regionOf)),
    occurrenceIds: Object.freeze(wire['occurrence_ids'].map((id) => matching(id, UUID, 'occurrence'))),
  });
}

/**
 * Parse and check one served body.
 *
 * Refuses rather than repairs. A segment list on a scene that is not `available`, an available one
 * with no grid, or a segment whose shape mixes a person and an object are all signs that the body
 * and this build disagree, and the honest consequence is no overlay rather than a partial one.
 */
export function parseSceneSegments(value: unknown, expectedSceneId?: string): SceneSegments {
  const wire = record(value, 'body');
  if (wire['schema_version'] !== SEGMENTS_SCHEMA_VERSION) {
    throw unreadable(`This build reads scene segments schema ${SEGMENTS_SCHEMA_VERSION}; the server answered ${String(wire['schema_version'])}.`);
  }
  const sceneId = matching(wire['scene_id'], UUID, 'scene');
  if (expectedSceneId !== undefined && sceneId !== expectedSceneId) {
    throw unreadable('The scene segments are for a different scene than the one asked about.');
  }
  const state = wire['state'];
  if (state !== 'available' && state !== 'stale' && state !== 'absent' && state !== 'unavailable') {
    throw unreadable('The scene segments are in a state this build does not know.');
  }
  const grid = nullable(wire['grid'], (value) => {
    const held = record(value, 'grid');
    if (held['frame'] !== 'scene') throw unreadable('The scene segments are gridded in a frame other than the scene.');
    return integer(held['voxel_size_microunits'], 'voxel size', 1);
  });
  if (!Array.isArray(wire['segments']) || !Array.isArray(wire['stale_inputs'])) {
    throw unreadable('The scene segments hold no segment or stale-input list.');
  }
  const segments = wire['segments'].map(segmentOf);
  if (state !== 'available' && segments.length > 0) throw unreadable('Segments were served for a scene that is not available.');
  if (segments.length > 0 && grid === null) throw unreadable('Segments were served with no grid to place them on.');
  if (new Set(segments.map((segment) => segment.segmentId)).size !== segments.length) {
    throw unreadable('The scene segments name one segment twice.');
  }
  return Object.freeze({
    sceneId,
    state,
    reason: nullable(wire['reason'], (text) => String(text)),
    artifact: nullable(wire['artifact'], (value) => {
      const held = record(value, 'artifact');
      return Object.freeze({
        artifactId: matching(held['artifact_id'], UUID, 'artifact'),
        contentSha256: matching(held['content_sha256'], SHA256, 'artifact digest'),
        byteSize: integer(held['byte_size'], 'artifact size', 0),
      });
    }),
    poseReceiptSha256: nullable(wire['pose_receipt_sha256'], (value) => matching(value, SHA256, 'pose receipt digest')),
    placementReceiptSha256: nullable(wire['placement_receipt_sha256'], (value) => matching(value, SHA256, 'placement receipt digest')),
    gateReceiptSha256: nullable(wire['gate_receipt_sha256'], (value) => matching(value, SHA256, 'gate receipt digest')),
    voxelSizeMicrounits: grid,
    policy: nullable(wire['policy'], (value) => Object.freeze({ ...record(value, 'policy') })),
    segments: Object.freeze(segments),
    withheldSegmentCount: integer(wire['withheld_segment_count'], 'withheld segment count', 0),
    staleInputs: Object.freeze(wire['stale_inputs'].map((item) => String(item))),
  });
}

/** Reads one scene's segments through the same authenticated transport. */
export class SceneSegmentsClient {
  readonly #options: TransportOptions;

  constructor(options: { readonly baseUrl: string; readonly token: string }) {
    this.#options = { baseUrl: options.baseUrl, token: options.token };
  }

  async load(sceneId: string): Promise<SceneSegments> {
    if (!UUID.test(sceneId)) throw unreadable('That is not a scene identifier.');
    const transport = new Transport({ ...this.#options, signal: AbortSignal.timeout(SEGMENTS_TIMEOUT_MS) });
    let wire: unknown;
    try {
      wire = await transport.getJson<unknown>(`/scene-segments/${sceneId}`);
    } catch (error) {
      throw asUnavailable(error);
    }
    return parseSceneSegments(wire, sceneId);
  }
}

/**
 * The published fixture, for the development preview only.
 *
 * Guarded on `import.meta.env.DEV` as well as the caller's preview flag, so a production build
 * drops the import and the fixture never enters a bundle that could be deployed.
 */
export async function previewSceneSegments(): Promise<SceneSegments> {
  if (!import.meta.env.DEV) throw new SegmentsUnavailable('none-recorded', 'The preview fixture exists in development builds only.');
  const raw = (await import('../../graph-client/test/fixtures/scene-segments.json?raw')).default;
  return parseSceneSegments(JSON.parse(raw) as unknown);
}

function asUnavailable(error: unknown): SegmentsUnavailable {
  if (error instanceof ApiError) {
    if (error.isUnauthenticated) {
      return new SegmentsUnavailable('unauthorized', 'This session is not authorized to read this scene.');
    }
    if (error.status === 410) return new SegmentsUnavailable('withdrawn', 'This reconstructed scene was withdrawn.');
    if (error.status === 404) {
      // The route answers 404 for a scene this workspace does not hold and will not say more, so
      // neither does this.
      return new SegmentsUnavailable('none-recorded', 'This scene is not one this session can read segments for.');
    }
    return new SegmentsUnavailable('unreadable', error.message);
  }
  if (error instanceof DOMException && error.name === 'TimeoutError') {
    return new SegmentsUnavailable('timed-out', 'The scene segments did not arrive in time.');
  }
  return new SegmentsUnavailable('unreadable', error instanceof Error ? error.message : 'The scene segments could not be read.');
}
