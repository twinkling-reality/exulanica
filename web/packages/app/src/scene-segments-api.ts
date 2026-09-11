/**
 * What the photographs found, lifted into one reconstructed scene, fetched for the segment overlay.
 *
 * `GET /world-read/scenes/{id}/segments` serves one per-entity segment artifact: for each thing a
 * vision pass found in the scene's photographs and the lift voted onto the geometry, the entity it
 * names, its class, a label, how many views voted for it, and which Gaussians or point-map samples
 * it covers in each scene asset. The artifact is bound to the scene's member set, pose receipt,
 * placement receipt and region set, and to each asset's content digest, because an index is only
 * an answer about the bytes it was computed against: the same number names a different Gaussian in
 * a retrained artifact.
 *
 * **THE ROUTE AND THE SHAPE ARE PROVISIONAL.** They follow `docs/briefs/2026-09-11-scene-segments.md`
 * and were written before the backend published anything. So was
 * `graph-client/test/fixtures/scene-segments.json`, which was authored in the front end against the
 * preview courtyard: its point-map asset is the real `glasshouse-courtyard.opm` and its segments are
 * image-space boxes narrowed by depth; its trained asset is the 512-Gaussian format-only SOG from
 * `web/test-data`, whose runs are arbitrary test data rather than a claim about what those
 * Gaussians depict. When the backend's own fixture lands it replaces that file, and this parser is
 * the one place that has to agree with it.
 *
 * **Indices cross as runs.** `index_runs` is a list of `[start, length]` pairs in ascending order.
 * Samples are stored in a spatially coherent order (image rows for a point map, the compressor's
 * Morton order for a trained scene), so a segment is a few hundred runs rather than tens of
 * thousands of integers.
 *
 * **Nothing here decides what may be shown.** A person segment carries the consent state the server
 * resolved, in the server's words, and this file only defaults what is missing to the hiding answer.
 * It never carries a name: what a person is called is the graph's to say, and the surface reads it
 * from the snapshot, which is the only place a withheld name is already absent.
 */

import { ApiError, Transport, type ConfidenceBand, type TransportOptions } from '@exulanica/graph-client';

export const SEGMENTS_PROFILE = 'exulanica.scene-segments/v1';
const SEGMENTS_TIMEOUT_MS = 30_000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const SHA256 = /^[0-9a-f]{64}$/u;

export type SegmentAssetKind = 'trained_geometry' | 'point_map';
export type SegmentEntityClass = 'person' | 'object' | 'place';
export type ConsentScope = 'presence' | 'naming' | 'likeness';
/** The three decisions the consent route records, and the absence of any. */
export type ConsentDecision = 'granted' | 'revoked' | 'withdrawn' | 'not_recorded';

export interface SegmentAsset {
  readonly artifactId: string;
  readonly kind: SegmentAssetKind;
  readonly contentSha256: string;
  readonly sampleCount: number;
}

export interface SegmentSamples {
  readonly artifactId: string;
  /** Ascending, disjoint `[start, length]` runs, exactly as served. */
  readonly runs: readonly (readonly [number, number])[];
  readonly count: number;
}

/** The consent state behind one person segment, as the server resolved it. Never a name. */
export interface SegmentPerson {
  /** `screened` or anything else; anything else is read as unscreened. */
  readonly reviewState: string;
  /** The resolved presentation state (`shown`, `present`, `hidden`, ...), or `unknown`. */
  readonly state: string;
  readonly consent: Readonly<Record<ConsentScope, ConsentDecision>>;
}

export interface SceneSegment {
  readonly segmentId: string;
  readonly entityId: string | null;
  readonly entityClass: SegmentEntityClass;
  /** What the detector called it. For a person this is a class word and is never shown as a name. */
  readonly label: string;
  readonly voteCount: number;
  readonly confidence: ConfidenceBand;
  /** The detections whose masks voted for this segment, as graph occurrence ids. */
  readonly occurrenceIds: readonly string[];
  readonly person: SegmentPerson | null;
  readonly samples: readonly SegmentSamples[];
}

export interface SegmentModel {
  readonly model: string;
  readonly revision: string;
  readonly licence: string;
}

export interface SceneSegments {
  readonly sceneId: string;
  readonly boundTo: {
    readonly memberDigest: string;
    readonly poseReceiptSha256: string | null;
    readonly placementReceiptSha256: string | null;
    readonly regionDigest: string;
  };
  readonly method: {
    readonly masks: SegmentModel;
    readonly boxes: SegmentModel | null;
    readonly projection: string;
    /** How many photographs the lift projected into. A vote count is out of this. */
    readonly views: number;
  };
  readonly assets: readonly SegmentAsset[];
  readonly segments: readonly SceneSegment[];
}

/** Why a scene has no segments, in words a panel can show without inventing a reason. */
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
    throw unreadable(`The segment artifact's ${what} is not an object.`);
  }
  return value as Record<string, unknown>;
}

function text(value: unknown, what: string): string {
  if (typeof value !== 'string' || value.length === 0) throw unreadable(`The segment artifact's ${what} is missing.`);
  return value;
}

function digest(value: unknown, what: string): string {
  if (typeof value !== 'string' || !SHA256.test(value)) throw unreadable(`The segment artifact's ${what} is not a SHA-256 digest.`);
  return value;
}

function nullableDigest(value: unknown, what: string): string | null {
  return value === null ? null : digest(value, what);
}

function uuid(value: unknown, what: string): string {
  if (typeof value !== 'string' || !UUID.test(value)) throw unreadable(`The segment artifact's ${what} is not an identifier.`);
  return value;
}

function count(value: unknown, what: string, minimum = 0): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    throw unreadable(`The segment artifact's ${what} is not a whole number.`);
  }
  return value as number;
}

function modelOf(value: unknown, what: string): SegmentModel {
  const wire = record(value, what);
  return Object.freeze({
    model: text(wire['model'], `${what} model`),
    revision: text(wire['revision'], `${what} revision`),
    licence: text(wire['licence'], `${what} licence`),
  });
}

/** Missing and unrecognised decisions are both `not_recorded`: a default has to hide, not show. */
function decision(value: unknown): ConsentDecision {
  return value === 'granted' || value === 'revoked' || value === 'withdrawn' ? value : 'not_recorded';
}

function personOf(value: unknown): SegmentPerson {
  const wire = record(value, 'person block');
  const consent = wire['consent'] === undefined || wire['consent'] === null ? {} : record(wire['consent'], 'person consent');
  return Object.freeze({
    reviewState: typeof wire['review_state'] === 'string' ? wire['review_state'] : 'unscreened',
    state: typeof wire['state'] === 'string' ? wire['state'] : 'unknown',
    consent: Object.freeze({
      presence: decision(consent['presence']),
      naming: decision(consent['naming']),
      likeness: decision(consent['likeness']),
    }),
  });
}

function runsOf(value: unknown, sampleCount: number, what: string): SegmentSamples['runs'] {
  if (!Array.isArray(value) || value.length === 0) throw unreadable(`${what} names no samples.`);
  const runs: (readonly [number, number])[] = [];
  let end = 0;
  for (const run of value) {
    if (!Array.isArray(run) || run.length !== 2) throw unreadable(`${what} holds a run that is not a pair.`);
    const start = count(run[0], `${what} run start`);
    const length = count(run[1], `${what} run length`, 1);
    // Ascending and disjoint, so a sample is named at most once by one segment.
    if (start < end) throw unreadable(`${what} holds runs out of order or overlapping.`);
    end = start + length;
    if (end > sampleCount) throw unreadable(`${what} names a sample beyond the asset's ${sampleCount}.`);
    runs.push(Object.freeze([start, length] as const));
  }
  return Object.freeze(runs);
}

/**
 * Parse and check one served segment artifact.
 *
 * Refuses rather than repairs. A run past the end of its asset, an asset named by no segment's
 * binding, or a sample the artifact claims for two assets at once are all signs that the artifact
 * and the geometry disagree, and the honest consequence of that is no overlay rather than an
 * overlay of whatever happened to line up.
 */
export function parseSceneSegments(value: unknown, expectedSceneId?: string): SceneSegments {
  const wire = record(value, 'body');
  if (wire['profile'] !== SEGMENTS_PROFILE) {
    throw unreadable(`This build reads ${SEGMENTS_PROFILE}; the server answered ${String(wire['profile'])}.`);
  }
  const sceneId = uuid(wire['scene_id'], 'scene');
  if (expectedSceneId !== undefined && sceneId !== expectedSceneId) {
    throw unreadable('The segment artifact is for a different scene than the one asked about.');
  }
  const bound = record(wire['bound_to'], 'binding');
  const method = record(wire['method'], 'method');
  const assets = new Map<string, SegmentAsset>();
  if (!Array.isArray(wire['assets']) || wire['assets'].length === 0) throw unreadable('The segment artifact names no scene asset.');
  for (const item of wire['assets']) {
    const asset = record(item, 'asset');
    const kind = asset['kind'];
    if (kind !== 'trained_geometry' && kind !== 'point_map') throw unreadable('The segment artifact names an asset of an unknown kind.');
    const artifactId = uuid(asset['artifact_id'], 'asset');
    if (assets.has(artifactId)) throw unreadable('The segment artifact names one asset twice.');
    assets.set(artifactId, Object.freeze({
      artifactId,
      kind,
      contentSha256: digest(asset['content_sha256'], 'asset digest'),
      sampleCount: count(asset['sample_count'], 'asset sample count', 1),
    }));
  }
  const views = count(method['views'], 'view count', 1);
  if (!Array.isArray(wire['segments'])) throw unreadable('The segment artifact holds no segment list.');
  const seen = new Set<string>();
  const segments = wire['segments'].map((item): SceneSegment => {
    const segment = record(item, 'segment');
    const segmentId = uuid(segment['segment_id'], 'segment');
    if (seen.has(segmentId)) throw unreadable('The segment artifact names one segment twice.');
    seen.add(segmentId);
    const entityClass = segment['entity_class'];
    if (entityClass !== 'person' && entityClass !== 'object' && entityClass !== 'place') {
      throw unreadable('A segment names an entity class this build does not know.');
    }
    const confidence = segment['confidence'];
    if (confidence !== 'low' && confidence !== 'medium' && confidence !== 'high') {
      throw unreadable('A segment carries no qualitative confidence.');
    }
    const voteCount = count(segment['vote_count'], 'vote count', 1);
    if (voteCount > views) throw unreadable('A segment carries more votes than the lift had views.');
    const occurrenceIds = Array.isArray(segment['occurrence_ids'])
      ? segment['occurrence_ids'].map((id) => uuid(id, 'occurrence'))
      : [];
    if (!Array.isArray(segment['samples']) || segment['samples'].length === 0) throw unreadable('A segment covers no samples.');
    const bySample = new Set<string>();
    const samples = segment['samples'].map((entry): SegmentSamples => {
      const samplesWire = record(entry, 'sample list');
      const artifactId = uuid(samplesWire['artifact_id'], 'sample asset');
      const asset = assets.get(artifactId);
      if (asset === undefined) throw unreadable('A segment names samples in an asset the artifact does not bind.');
      if (bySample.has(artifactId)) throw unreadable('A segment names one asset twice.');
      bySample.add(artifactId);
      const runs = runsOf(samplesWire['index_runs'], asset.sampleCount, 'A segment');
      return Object.freeze({ artifactId, runs, count: runs.reduce((sum, [, length]) => sum + length, 0) });
    });
    return Object.freeze({
      segmentId,
      entityId: segment['entity_id'] === null ? null : uuid(segment['entity_id'], 'entity'),
      entityClass,
      label: text(segment['label'], 'segment label'),
      voteCount,
      confidence,
      occurrenceIds: Object.freeze(occurrenceIds),
      // A person segment without a person block is refused rather than drawn with no consent
      // state: the brief says one exists only for someone whose consent is recorded.
      person: entityClass === 'person' ? personOf(segment['person']) : null,
      samples: Object.freeze(samples),
    });
  });
  return Object.freeze({
    sceneId,
    boundTo: Object.freeze({
      memberDigest: digest(bound['member_digest'], 'member digest'),
      poseReceiptSha256: nullableDigest(bound['pose_receipt_sha256'] ?? null, 'pose receipt digest'),
      placementReceiptSha256: nullableDigest(bound['placement_receipt_sha256'] ?? null, 'placement receipt digest'),
      regionDigest: digest(bound['region_digest'], 'region digest'),
    }),
    method: Object.freeze({
      masks: modelOf(method['masks'], 'mask model'),
      boxes: method['boxes'] === undefined || method['boxes'] === null ? null : modelOf(method['boxes'], 'box model'),
      projection: text(method['projection'], 'projection method'),
      views,
    }),
    assets: Object.freeze([...assets.values()]),
    segments: Object.freeze(segments),
  });
}

/** Expand one segment's runs on one asset into ascending sample indices. */
export function indicesOf(samples: SegmentSamples): Uint32Array {
  const out = new Uint32Array(samples.count);
  let at = 0;
  for (const [start, length] of samples.runs) {
    for (let index = start; index < start + length; index += 1) out[at++] = index;
  }
  return out;
}

/** Reads one scene's segment artifact through the same authenticated transport. */
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
      wire = await transport.getJson<unknown>(`/world-read/scenes/${sceneId}/segments`);
    } catch (error) {
      throw asUnavailable(error);
    }
    return parseSceneSegments(wire, sceneId);
  }
}

/**
 * The provisional fixture, for the development preview only.
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
      // A missing scene, a foreign one and one nobody has segmented all answer 404, and the route
      // will not say which, so neither does this.
      return new SegmentsUnavailable('none-recorded', 'No segments are recorded for this scene.');
    }
    return new SegmentsUnavailable('unreadable', error.message);
  }
  if (error instanceof DOMException && error.name === 'TimeoutError') {
    return new SegmentsUnavailable('timed-out', 'The scene segments did not arrive in time.');
  }
  return new SegmentsUnavailable('unreadable', error instanceof Error ? error.message : 'The scene segments could not be read.');
}
