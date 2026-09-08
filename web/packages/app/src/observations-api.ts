/**
 * The recorded observation graph, fetched for click-to-evidence.
 *
 * `GET /world-read/scenes/{id}/observations` serves the sparse tracks COLMAP actually recorded:
 * for each retained point, which photographs saw it, where in each of them, and each photograph's
 * consent state. `exulanica/graph/observations.py` is the authority on all of that; this file only
 * gets it into the browser and turns the wire's decimal strings into numbers.
 *
 * **Why the decimals are strings on the wire and numbers here.** The bundle's canonical form
 * admits no floats, because no two implementations agree on how to render one, so every measured
 * value crosses as a fixed-precision decimal string. Nothing in the browser recomputes a digest
 * over these, so parsing them is safe; what would not be safe is letting a float reach a hash, and
 * that never happens on this path.
 *
 * **The inspector still needs a whole-scene read.** MEASURED 2026-09-08, read-only against
 * the retained reference: the bowl graph is 97,633,587 canonical bytes, 15,005 points and 71,214
 * observations. A 500-point page is 4,973,392 bytes. Paging bounds each answer, but the server
 * still groups the entire receipt for each request. Loading every page would repeat that work
 * 31 times and retain the same complete graph here. The inspector cannot display partial state,
 * so returning only the first page would silently make clicks miss recorded evidence.
 *
 * Keep the single complete request until a different read contract can improve that tradeoff.
 * The route also supplies no snapshot identity: an immutable receipt does not freeze the scene's
 * current job, membership or consent across requests. Assembling pages could mix those states.
 * A response must therefore prove completeness before reaching the inspector. This choice does
 * not solve large-scene browser memory use; it avoids disguising a partial answer as the graph.
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

import type { SparseObservedPoint } from '@exulanica/atlas-core';
import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';

const OBSERVATIONS_PROFILE = 'exulanica.scene-sparse-observations/v1';
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

export interface ObservationGraph {
  readonly sceneId: string;
  /** Always `recorded` from this route. Kept so a caller states it rather than assuming it. */
  readonly provenance: string;
  readonly method: string;
  readonly sampling: string;
  /** The per-image cap the pose stage applied before any of this was stored. */
  readonly retainedPerImage: number;
  /** Every retained point, in the shape `pickObservedPoint` takes. */
  readonly points: readonly SparseObservedPoint[];
  /** Which photographs saw each point, by point id. */
  readonly observedBy: ReadonlyMap<number, readonly ObservedBy[]>;
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

interface WirePoint {
  readonly point_id: number;
  readonly world_xyz: readonly [string, string, string];
  readonly track_length: number;
  readonly observations_retained: number;
  readonly observations: readonly WireObservation[];
}

interface WireBounds {
  readonly state: string;
  readonly after_point_id: number | null;
  readonly next_point_id: number | null;
  readonly point_count_total: number;
  readonly point_count_returned: number;
  readonly point_count_not_returned: number;
  readonly observations_total: number;
  readonly observations_returned: number;
}

interface WireObservations {
  readonly profile: string;
  readonly scene_id: string;
  readonly provenance: string;
  readonly method: string;
  readonly sampling: string;
  readonly retained_per_image: number;
  readonly bounds: WireBounds;
  readonly point_count: number;
  readonly points: readonly WirePoint[];
}

function decimal(value: string): number {
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new TypeError('an observation coordinate is not a decimal string');
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new TypeError('an observation coordinate is not a number');
  return parsed;
}

/** A page cannot enter the inspector's whole-graph cache, even if its profile is familiar. */
function requireComplete(wire: WireObservations, sceneId: string): void {
  const bounds = wire?.bounds;
  if (wire?.scene_id !== sceneId || !Array.isArray(wire.points) || bounds == null
    || bounds.state !== 'complete' || bounds.after_point_id !== null
    || bounds.next_point_id !== null || bounds.point_count_not_returned !== 0
    || wire.point_count !== wire.points.length
    || bounds.point_count_total !== wire.points.length
    || bounds.point_count_returned !== wire.points.length) {
    throw new ObservationsUnavailable('unreadable', 'The server did not return a complete observation graph for this scene.');
  }
  let observations = 0;
  let previous = -1;
  for (const point of wire.points) {
    if (!Number.isSafeInteger(point.point_id) || point.point_id <= previous
      || !Array.isArray(point.observations) || point.observations.length === 0
      || point.observations_retained !== point.observations.length
      || !Number.isSafeInteger(point.track_length) || point.track_length < point.observations.length
      || !Array.isArray(point.world_xyz) || point.world_xyz.length !== 3) {
      throw new ObservationsUnavailable('unreadable', 'The observation graph contains inconsistent point records.');
    }
    previous = point.point_id;
    observations += point.observations.length;
  }
  if (bounds.observations_total !== observations || bounds.observations_returned !== observations) {
    throw new ObservationsUnavailable('unreadable', 'The observation graph does not hold the observations its counts declare.');
  }
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

/** Why a scene has no observation graph, in words a panel can show without inventing a reason. */
export type ObservationFailure =
  | 'none-recorded'
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

/** Reads one scene's recorded observation graph through the same authenticated transport. */
export class ObservationsClient {
  readonly #options: TransportOptions;

  constructor(options: { readonly baseUrl: string; readonly token: string }) {
    this.#options = { baseUrl: options.baseUrl, token: options.token };
  }

  async load(sceneId: string): Promise<ObservationGraph> {
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(sceneId)) {
      throw new ObservationsUnavailable('unreadable', 'That is not a scene identifier.');
    }
    const transport = new Transport({
      ...this.#options,
      signal: AbortSignal.timeout(OBSERVATIONS_TIMEOUT_MS),
    });
    let wire: WireObservations;
    try {
      wire = await transport.getJson<WireObservations>(`/world-read/scenes/${sceneId}/observations`);
    } catch (error) {
      throw asUnavailable(error);
    }
    requireComplete(wire, sceneId);
    if (wire.profile !== OBSERVATIONS_PROFILE) {
      throw new ObservationsUnavailable(
        'unreadable',
        `This build reads ${OBSERVATIONS_PROFILE}; the server answered ${String(wire.profile)}.`,
      );
    }
    const points: SparseObservedPoint[] = [];
    const observedBy = new Map<number, readonly ObservedBy[]>();
    for (const point of wire.points) {
      const seen = point.observations.map((item) => Object.freeze({
        captureId: item.capture_id,
        x: decimal(item.x),
        y: decimal(item.y),
        reprojectionErrorPx: decimal(item.reprojection_error_px),
        consent: consentOf(item.consent),
      }));
      points.push(Object.freeze({
        pointId: point.point_id,
        world: Object.freeze([
          decimal(point.world_xyz[0]),
          decimal(point.world_xyz[1]),
          decimal(point.world_xyz[2]),
        ]) as readonly [number, number, number],
        trackLength: point.track_length,
        // Never larger than the track length, and taken from the served rows rather than from the
        // field beside them, so a caller cannot be told a count the answer does not carry.
        observationsRetained: seen.length,
      }));
      observedBy.set(point.point_id, Object.freeze(seen));
    }
    return Object.freeze({
      sceneId: wire.scene_id,
      provenance: wire.provenance,
      method: wire.method,
      sampling: wire.sampling,
      retainedPerImage: wire.retained_per_image,
      points: Object.freeze(points),
      observedBy,
    });
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
    if (error.status === 404) {
      // 404 covers a missing scene, a foreign one and one whose pose was never accepted, and the
      // route will not say which. So neither does this: "no recorded observations reached this
      // page" is the whole of what a caller may conclude.
      return new ObservationsUnavailable(
        'none-recorded',
        'No recorded observation graph is served for this scene.',
      );
    }
    return new ObservationsUnavailable('unreadable', error.message);
  }
  if (error instanceof DOMException && error.name === 'TimeoutError') {
    return new ObservationsUnavailable('timed-out', 'The observation graph did not arrive in time.');
  }
  return new ObservationsUnavailable(
    'unreadable',
    error instanceof Error ? error.message : 'The observation graph could not be read.',
  );
}
