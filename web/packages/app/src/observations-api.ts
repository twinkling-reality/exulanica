/**
 * The recorded observations behind click-to-evidence, read one click at a time.
 *
 * `exulanica/graph/observations.py` is the authority on what a point is, which photographs
 * recorded it and what each photograph's consent state says. This file asks two small questions
 * of it and turns the wire's decimal strings into numbers:
 *
 * - `GET /world-read/scenes/{id}/observations/summary`: how many recorded points and observations
 *   a click in this scene resolves against, for the panel's idle sentence.
 * - `GET /world-read/scenes/{id}/observations/resolve`: the one recorded point a cursor selects in
 *   one photograph, and the photographs that observed it.
 *
 * **Why not the whole graph, which this file used to read.** MEASURED 2026-09-11 against a frozen
 * copy of the volcanic scene (210 photographs): the whole graph is 1,015,016,928 bytes of JSON.
 * V8 cannot hold a string that long, so the inspector failed with "Unexpected end of JSON input"
 * and click-to-evidence could never work on a scene that size. The pick it downloaded the graph
 * for now runs on the server, term for term, and a click's answer is kilobytes: 11,277 bytes for a
 * point eight photographs observed, 1,784 for a miss, and bounded by the scene's photograph count
 * rather than its point count. The summary is 781 bytes.
 *
 * **Why the decimals are strings on the wire and numbers here.** The bundle's canonical form
 * admits no floats, because no two implementations agree on how to render one, so every measured
 * value crosses as a fixed-precision decimal string. Nothing in the browser recomputes a digest
 * over these, so parsing them is safe; what would not be safe is letting a float reach a hash, and
 * that never happens on this path.
 *
 * **Nothing here filters.** Every observation carries its photograph's consent state. CORRECTED
 * 2026-09-07: that state used to be `unavailable` on every observation, meaning no per-person
 * consent layer existed in this build. The layer has merged, so the value now describes the
 * PHOTOGRAPH: `unscreened` when nobody has looked at it for people, `recorded` when people are
 * located in it and carry receipts. Neither is a per-person state, and a filter still has nothing
 * to read: withholding a photograph because one person in it forbids it needs that person's state
 * to reach an observation, which it does not, because the resolved state expires against
 * `clock_timestamp()` and this answer is digest-bound. That is P10-A-b's last open box and the
 * blocker is stated in `docs/phase-10-tickets.md` under P10-1-c-2.
 */

import type { PickResult, SparseObservedPoint } from '@exulanica/atlas-core';
import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';

const SUMMARY_PROFILE = 'exulanica.scene-observation-summary/v1';
const RESOLVE_PROFILE = 'exulanica.scene-observation-resolve/v1';
/**
 * The first read of a large scene builds the server's index of it. MEASURED 2026-09-11 on the
 * volcanic scene: 6.3 s cold, then 0.2 to 0.3 s. Either read can be the first.
 */
const OBSERVATIONS_TIMEOUT_MS = 60_000;

/** The screening receipt behind one photograph's consent state, in the server's own words. */
export interface ObservationScreening {
  readonly state: string;
  readonly method: string;
  readonly eligibility: string;
  readonly namedHumanReviewer: boolean;
  readonly sensitiveRegionCount: number;
}

export interface ObservationConsent {
  readonly basis: string;
  readonly screening: ObservationScreening | null;
  readonly personConsent: string;
  readonly personConsentReason: string | null;
}

/** One photograph's recorded sighting of one point, in that photograph's own pixel coordinates. */
export interface ObservedBy {
  readonly captureId: string;
  readonly x: number;
  readonly y: number;
  readonly reprojectionErrorPx: number;
  readonly consent: ObservationConsent;
}

/** What a click in one scene resolves against, as counts. */
export interface ObservationSummary {
  readonly sceneId: string;
  /** Always `recorded` from this route. Kept so a caller states it rather than assuming it. */
  readonly provenance: string;
  readonly method: string;
  readonly sampling: string;
  /** The per-image cap the pose stage applied before any of this was stored. */
  readonly retainedPerImage: number;
  readonly pointCount: number;
  readonly observationCount: number;
}

/** One cursor in one photograph, in that photograph's pixels, as `canvasToSourcePixel` gives it. */
export interface ResolveRequest {
  readonly captureId: string;
  readonly u: number;
  readonly v: number;
  readonly tolerancePx: number;
  readonly occlusionBandPx: number;
}

/** The selected point, in the shape `observationSentence` reads, with who observed it. */
export interface ResolvedPoint extends PickResult {
  readonly observedBy: readonly ObservedBy[];
}

export interface ResolvedObservation {
  readonly sceneId: string;
  readonly captureId: string;
  /** How many recorded points the click was resolved against. */
  readonly pointCount: number;
  /**
   * Null is a miss, and a miss is an answer: nothing recorded projects within tolerance of the
   * cursor, which is the honest state for a plain surface the reconstruction matched little on.
   */
  readonly hit: ResolvedPoint | null;
}

interface WireConsent {
  readonly basis?: unknown;
  readonly screening?: {
    readonly state?: unknown;
    readonly method?: unknown;
    readonly eligibility?: unknown;
    readonly named_human_reviewer?: unknown;
    readonly sensitive_region_count?: unknown;
  } | null;
  readonly person_consent?: unknown;
  readonly person_consent_reason?: unknown;
}

interface WireObservation {
  readonly capture_id: string;
  readonly x: string;
  readonly y: string;
  readonly reprojection_error_px: string;
  readonly consent: WireConsent;
}

interface WireSummary {
  readonly profile: string;
  readonly scene_id: string;
  readonly provenance: string;
  readonly method: string;
  readonly sampling: string;
  readonly retained_per_image: number;
  readonly point_count_total: number;
  readonly observations_total: number;
}

interface WireResolve {
  readonly profile: string;
  readonly scene_id: string;
  readonly point_count_total: number;
  readonly query: {
    readonly capture_id: string;
    readonly tolerance_px: string;
    readonly projection: string;
  };
  readonly state: string;
  readonly point: {
    readonly point_id: number;
    readonly world_xyz: readonly [string, string, string];
    readonly track_length: number;
    readonly observations_retained: number;
    readonly pixel_distance: string;
    readonly depth: string;
    readonly observations: readonly WireObservation[];
  } | null;
}

const SCENE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;

function decimal(value: string): number {
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new TypeError('an observation coordinate is not a decimal string');
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new TypeError('an observation coordinate is not a number');
  return parsed;
}

function count(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) > 0;
}

function unreadable(message: string): ObservationsUnavailable {
  return new ObservationsUnavailable('unreadable', message);
}

function text(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.length > 0 ? value : fallback;
}

function consentOf(wire: WireConsent): ObservationConsent {
  const screening = wire.screening ?? null;
  return Object.freeze({
    basis: text(wire.basis, 'unstated'),
    screening: screening === null ? null : Object.freeze({
      state: text(screening.state, 'unstated'),
      method: text(screening.method, 'unstated'),
      eligibility: text(screening.eligibility, 'unstated'),
      namedHumanReviewer: screening.named_human_reviewer === true,
      sensitiveRegionCount: typeof screening.sensitive_region_count === 'number'
        ? screening.sensitive_region_count : 0,
    }),
    // DEFAULT-DENY, and the default matters. An answer that omitted the field would otherwise
    // read as "no person consent question arises here", which is the exact confusion the World
    // Read bundle's own release block exists to prevent.
    personConsent: text(wire.person_consent, 'unavailable'),
    personConsentReason: typeof wire.person_consent_reason === 'string'
      ? wire.person_consent_reason : null,
  });
}

/**
 * One photograph's consent state as a sentence, and it says what the basis does not establish.
 *
 * The screening receipt says a named human reviewed a whole photograph. It does not record a
 * decision about any individual person in it, and the 2026-09-05 bowl run is why that distinction
 * is spelled out rather than left implied: the reviewer stated no visible people and the frames
 * contain diners' arms and hands at the edges. So this never says "no people", only what was
 * actually reviewed and what is still unrecorded.
 *
 * Written here rather than in `@exulanica/graph-client/person-presentation.ts`, which belongs to
 * the person-consent branch. When that branch lands with real per-person state, this sentence is
 * the one to replace, and it is one function in one file.
 */
export function consentSentence(consent: ObservationConsent): string {
  const screening = consent.screening;
  const reviewed = screening === null
    ? 'No screening receipt accompanies this photograph.'
    : screening.namedHumanReviewer
      ? `Screened by a named human reviewer: ${screening.state}, ${screening.eligibility}.`
      : `Screened without a named human reviewer: ${screening.state}, ${screening.eligibility}.`;
  if (consent.personConsent === 'unavailable') {
    return `${reviewed} No per-person presentation consent is recorded, so no person in it has `
      + 'agreed to be shown; the screening receipt is a review of the whole photograph, not a '
      + 'decision about anyone in it.';
  }
  return `${reviewed} Per-person presentation consent: ${consent.personConsent}.`;
}

/** Why a click has no answer, in words a panel can show without inventing a reason. */
export type ObservationFailure =
  | 'none-recorded'
  /** The scene is readable and holds no recovered camera for the photograph that was named. */
  | 'unresolvable'
  | 'unauthorized'
  | 'withdrawn'
  | 'timed-out'
  | 'unreadable';

export class ObservationsUnavailable extends Error {
  readonly kind: ObservationFailure;
  constructor(kind: ObservationFailure, message: string) {
    super(message);
    this.name = 'ObservationsUnavailable';
    this.kind = kind;
  }
}

function readSummary(wire: WireSummary, sceneId: string): ObservationSummary {
  if (wire?.profile !== SUMMARY_PROFILE) {
    throw unreadable(`This build reads ${SUMMARY_PROFILE}; the server answered ${String(wire?.profile)}.`);
  }
  if (wire.scene_id !== sceneId || !count(wire.retained_per_image) || !count(wire.point_count_total)
    || !count(wire.observations_total) || wire.observations_total < wire.point_count_total) {
    throw unreadable('The server did not return consistent observation counts for this scene.');
  }
  return Object.freeze({
    sceneId: wire.scene_id,
    provenance: wire.provenance,
    method: wire.method,
    sampling: wire.sampling,
    retainedPerImage: wire.retained_per_image,
    pointCount: wire.point_count_total,
    observationCount: wire.observations_total,
  });
}

/**
 * The resolve answer, refused whole if any part of it contradicts another.
 *
 * It is one point, so the checks are about that point: it answers this scene and this photograph,
 * a hit carries a point and a miss does not, the retained count is the rows actually served and
 * never more than the track length, no photograph appears twice, and the point lies inside the
 * tolerance the server says it used. A panel shown a point that failed any of these would be
 * attributing photographs on the strength of an answer that does not agree with itself.
 */
function readResolve(wire: WireResolve, sceneId: string, captureId: string): ResolvedObservation {
  if (wire?.profile !== RESOLVE_PROFILE) {
    throw unreadable(`This build reads ${RESOLVE_PROFILE}; the server answered ${String(wire?.profile)}.`);
  }
  const projection = wire.query?.projection;
  if (wire.scene_id !== sceneId || wire.query?.capture_id !== captureId
    || !count(wire.point_count_total)
    || (projection !== 'pinhole' && projection !== 'pinhole-approximation')) {
    throw unreadable('The server answered a different question than the one this click asked.');
  }
  if (wire.state === 'miss' && wire.point === null) {
    return Object.freeze({ sceneId, captureId, pointCount: wire.point_count_total, hit: null });
  }
  const point = wire.point;
  if (wire.state !== 'hit' || point == null || !Number.isSafeInteger(point.point_id)
    || !Array.isArray(point.observations) || point.observations.length === 0
    || point.observations_retained !== point.observations.length
    || !Number.isSafeInteger(point.track_length) || point.track_length < point.observations.length
    || !Array.isArray(point.world_xyz) || point.world_xyz.length !== 3
    || new Set(point.observations.map((item) => item.capture_id)).size !== point.observations.length) {
    throw unreadable('The resolved point contains inconsistent records.');
  }
  const pixelDistance = decimal(point.pixel_distance);
  const depth = decimal(point.depth);
  if (pixelDistance < 0 || pixelDistance > decimal(wire.query.tolerance_px) || !(depth > 0)) {
    throw unreadable('The resolved point lies outside the tolerance the server says it used.');
  }
  const observedBy = Object.freeze(point.observations.map((item) => Object.freeze({
    captureId: item.capture_id,
    x: decimal(item.x),
    y: decimal(item.y),
    reprojectionErrorPx: decimal(item.reprojection_error_px),
    consent: consentOf(item.consent),
  })));
  const selected: SparseObservedPoint = Object.freeze({
    pointId: point.point_id,
    world: Object.freeze([
      decimal(point.world_xyz[0]),
      decimal(point.world_xyz[1]),
      decimal(point.world_xyz[2]),
    ]) as readonly [number, number, number],
    trackLength: point.track_length,
    // Taken from the served rows rather than from the field beside them, so a caller cannot be
    // told a count the answer does not carry.
    observationsRetained: observedBy.length,
  });
  return Object.freeze({
    sceneId,
    captureId,
    pointCount: wire.point_count_total,
    hit: Object.freeze({ point: selected, pixelDistance, depth, projection, observedBy }),
  });
}

/** Reads one scene's recorded observations through the same authenticated transport. */
export class ObservationsClient {
  readonly #options: TransportOptions;

  constructor(options: { readonly baseUrl: string; readonly token: string }) {
    this.#options = { baseUrl: options.baseUrl, token: options.token };
  }

  async summary(sceneId: string): Promise<ObservationSummary> {
    const wire = await this.#get<WireSummary>(sceneId, 'summary');
    return readSummary(wire, sceneId);
  }

  async resolve(sceneId: string, request: ResolveRequest): Promise<ResolvedObservation> {
    const numbers = [request.u, request.v, request.tolerancePx, request.occlusionBandPx];
    if (!numbers.every(Number.isFinite) || !SCENE_ID.test(request.captureId)) {
      // Refused here rather than sent: a NaN cursor compares false against every tolerance.
      throw unreadable('That click has no position in the photograph to resolve.');
    }
    const wire = await this.#get<WireResolve>(sceneId, 'resolve', {
      capture_id: request.captureId,
      u: String(request.u),
      v: String(request.v),
      tolerance_px: String(request.tolerancePx),
      occlusion_band_px: String(request.occlusionBandPx),
    });
    return readResolve(wire, sceneId, request.captureId);
  }

  async #get<T>(sceneId: string, read: string, query?: Record<string, string>): Promise<T> {
    if (!SCENE_ID.test(sceneId)) throw unreadable('That is not a scene identifier.');
    const transport = new Transport({
      ...this.#options,
      signal: AbortSignal.timeout(OBSERVATIONS_TIMEOUT_MS),
    });
    try {
      return await transport.getJson<T>(`/world-read/scenes/${sceneId}/observations/${read}`, query);
    } catch (error) {
      throw asUnavailable(error);
    }
  }
}

function asUnavailable(error: unknown): ObservationsUnavailable {
  if (error instanceof ApiError) {
    if (error.isUnauthenticated) {
      return new ObservationsUnavailable('unauthorized', 'This session is not authorized to read this scene.');
    }
    if (error.status === 410) {
      return new ObservationsUnavailable('withdrawn', 'This reconstructed scene was withdrawn.');
    }
    if (error.status === 404 && error.code === 'unknown_view') {
      // Answered only after the scene passed every check, so it says nothing a stranger could use.
      return new ObservationsUnavailable(
        'unresolvable',
        'This scene holds no recovered camera for that photograph, so a click in it cannot be resolved.',
      );
    }
    if (error.status === 404) {
      // 404 covers a missing scene, a foreign one and one whose pose was never accepted, and the
      // route will not say which. So neither does this: "no recorded observations reached this
      // page" is the whole of what a caller may conclude.
      return new ObservationsUnavailable(
        'none-recorded',
        'No recorded observations are served for this scene.',
      );
    }
    return new ObservationsUnavailable('unreadable', error.message);
  }
  if (error instanceof DOMException && error.name === 'TimeoutError') {
    return new ObservationsUnavailable('timed-out', 'The recorded observations did not arrive in time.');
  }
  return new ObservationsUnavailable(
    'unreadable',
    error instanceof Error ? error.message : 'The recorded observations could not be read.',
  );
}
