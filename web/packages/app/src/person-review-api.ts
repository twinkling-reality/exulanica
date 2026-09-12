/** Person review writes use server policy. Identity linking is an explicit, separate decision. */
import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';

import { PersonalRequestClient } from './personal-admission-api.js';
import { validateOutline, type ManualRegion } from './ui/person-region-editor.js';

import type { ReviewRegion } from './ui/person-review.js';

const REVIEW_TIMEOUT_MS = 20_000;

/** What the GET route answers about one photograph. */
export interface PersonReview {
  readonly captureId: string;
  /** `unscreened` means nobody has looked, never that there is nobody here. */
  readonly reviewState: 'unscreened' | 'screened';
  readonly regions: readonly ReviewRegion[];
}

/** One region exactly as `exulanica/ingest/person_review.py::review_list` reports it. */
interface WireRegion {
  readonly region_key: string;
  readonly action: string;
  readonly shape: string;
  readonly part: string | null;
  readonly silhouette: { readonly kind: string; readonly points: readonly (readonly number[])[] };
  readonly detector_id: string | null;
  readonly confidence: string | null;
  readonly confirmed_by: string | null;
  readonly subject_id: string | null;
  readonly state: string;
  readonly masked: boolean;
  readonly name_permitted: boolean;
}

interface WireReview {
  readonly capture_id: string;
  readonly review_state: string;
  readonly regions: readonly WireRegion[];
}

/**
 * A review request that did not happen, with a sentence a reviewer can act on.
 *
 * Separate from `ApiError` because the panel says this out loud beside the outlines, and "403" is
 * not a sentence. The `kind` is what the caller branches on; the message is what it prints.
 */
export class ReviewUnavailable extends Error {
  readonly kind: 'forbidden' | 'missing' | 'conflict' | 'unreachable' | 'unreadable';

  constructor(kind: ReviewUnavailable['kind'], message: string) {
    super(message);
    this.name = 'ReviewUnavailable';
    this.kind = kind;
  }
}

function asUnavailable(error: unknown): ReviewUnavailable {
  if (error instanceof ReviewUnavailable) return error;
  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 403) {
      return new ReviewUnavailable('forbidden', 'This session may not review this photograph.');
    }
    if (error.status === 404) {
      return new ReviewUnavailable('missing', 'That photograph is not in this workspace.');
    }
    // 409 is the server refusing an edit that would be dishonest, for example confirming a region
    // nothing ever proposed. Its own words are better than anything written here.
    if (error.status === 409) return new ReviewUnavailable('conflict', error.message);
  }
  return new ReviewUnavailable('unreachable', 'The review service did not answer.');
}

/** The five renames between the route's words and the panel's. Nothing else is translated. */
function regionOf(wire: WireRegion): ReviewRegion {
  return Object.freeze({
    regionKey: wire.region_key,
    action: wire.action as ReviewRegion['action'],
    shape: wire.shape as ReviewRegion['shape'],
    silhouette: wire.silhouette,
    detectorId: wire.detector_id,
    part: wire.part as ReviewRegion['part'],
    confidence: wire.confidence as ReviewRegion['confidence'],
    confirmedBy: wire.confirmed_by,
    subjectId: wire.subject_id,
    state: wire.state as ReviewRegion['state'],
    masked: wire.masked,
    namePermitted: wire.name_permitted,
  });
}

export class PersonReviewApi {
  readonly #options: TransportOptions;
  readonly requests: PersonalRequestClient;

  constructor(options: TransportOptions) {
    // Narrowed to the three fields a request needs, and `fetch` is spread conditionally rather
    // than passed as possibly-undefined: `exactOptionalPropertyTypes` is on, so an absent option
    // and an option set to undefined are different types. `signal` is deliberately dropped, since
    // each request below sets its own timeout.
    this.requests = new PersonalRequestClient(options);
    this.#options = options.fetch === undefined
      ? { baseUrl: options.baseUrl, token: options.token }
      : { baseUrl: options.baseUrl, token: options.token, fetch: options.fetch };
  }

  #transport(): Transport {
    return new Transport({ ...this.#options, signal: AbortSignal.timeout(REVIEW_TIMEOUT_MS) });
  }

  /** Who is in this photograph, and whether anybody has looked. */
  async load(captureId: string): Promise<PersonReview> {
    let wire: WireReview;
    try {
      wire = await this.#transport().getJson<WireReview>(`/person-regions/${captureId}`);
    } catch (error) {
      throw asUnavailable(error);
    }
    if (wire.review_state !== 'unscreened' && wire.review_state !== 'screened') {
      throw new ReviewUnavailable(
        'unreadable',
        `The server described this photograph as ${String(wire.review_state)}.`,
      );
    }
    return Object.freeze({
      captureId: wire.capture_id,
      reviewState: wire.review_state,
      regions: Object.freeze(wire.regions.map(regionOf)),
    });
  }

  /** One region edit, as its own receipt. */
  async edit(
    captureId: string,
    edit: { readonly region_key: string; readonly action: 'confirm' | 'delete';
      readonly subject_id?: string },
  ): Promise<void> {
    try {
      await this.requests.post(`/person-regions/${captureId}/edits`, { edits: [edit] });
    } catch (error) {
      throw asUnavailable(error);
    }
  }

  /** Add only a location. No subject, consent or other capture is changed. */
  async add(captureId: string, region: ManualRegion): Promise<void> {
    validateOutline(region.silhouette);
    if (!/^[0-9a-f]{64}$/u.test(region.region_key)) throw new Error('Invalid region key.');
    try {
      await this.requests.post(`/person-regions/${captureId}/edits`, {
        edits: [{ region_key: region.region_key, action: 'add', shape: 'box',
          silhouette: region.silhouette }],
      });
    } catch (error) {
      throw asUnavailable(error);
    }
  }

  /** The server atomically binds the selected regions and reuses their existing person. */
  async link(regions: readonly { capture_id: string; region_key: string }[], subjectId?: string): Promise<string> {
    if (!regions.length) throw new Error('Select the regions that show the same person.');
    try {
      const result = await this.requests.post<{ subject_id: string }>('/identity/subjects/link', {
        regions, ...(subjectId ? { subject_id: subjectId } : {}),
      });
      return result.subject_id;
    } catch (error) { throw asUnavailable(error); }
  }

  async unlink(captureId: string, region: ReviewRegion): Promise<void> {
    if (!region.subjectId) return;
    try {
      await this.requests.post('/identity/subjects/unlink', {
        subject_id: region.subjectId,
        regions: [{ capture_id: captureId, region_key: region.regionKey }],
      });
    } catch (error) { throw asUnavailable(error); }
  }

  /** Correct the same region, preserving its identity and receipt history. */
  async correct(captureId: string, region: ManualRegion): Promise<void> {
    validateOutline(region.silhouette);
    const latest = (await this.load(captureId)).regions.find(r => r.regionKey === region.region_key);
    if (!latest) throw new Error('The region is no longer available. Reload review.');
    if (JSON.stringify(latest.silhouette) === JSON.stringify(region.silhouette)) return;
    try {
      await this.requests.post(`/person-regions/${captureId}/edits`, {
        edits: [{ ...region, action: 'confirm', shape: 'box' }],
      });
    } catch (error) { throw asUnavailable(error); }
  }

  /** Never infer identity from a consent gesture or manufacture a subject's authentication. */
  async consent(
    captureId: string,
    region: ReviewRegion,
    scope: 'presence' | 'naming' | 'likeness' | 'temporary_hide',
    decision: 'granted' | 'revoked',
  ): Promise<string> {
    const latest = (await this.load(captureId)).regions.find(r => r.regionKey === region.regionKey);
    if (!latest?.subjectId || latest.subjectId !== region.subjectId) {
      throw new Error('Identify this person explicitly and reload review before recording a decision.');
    }
    try {
      await this.requests.post(`/person-subjects/${latest.subjectId}/consents`, {
        consent_scope: scope, decision, region_key: region.regionKey,
      });
    } catch (error) { throw asUnavailable(error); }
    return latest.subjectId;
  }
}
