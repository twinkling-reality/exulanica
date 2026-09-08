/**
 * The review screen's half of the person-consent API.
 *
 * `web/packages/app/src/ui/person-review.ts` draws the panel and decides nothing. This file is
 * the only thing between it and `exulanica/api/routes/person_consent.py`, and it exists for the
 * same reason `observations-api.ts` does: the bearer token belongs in one place, and a panel that
 * built its own requests would be a second place.
 *
 * **Recording a consent is three requests, and that is the shape of the data rather than a
 * clumsy client.** A consent is addressed to a SUBJECT, meaning a person, while the panel is
 * looking at a REGION, meaning an outline in one photograph. A region a detector proposed has no
 * subject: nobody has said the outline is a person, let alone which person. So the first consent
 * recorded against such a region has to create somebody for it to be about, bind them to the
 * outline, and only then record what they agreed to. The binding is an ordinary region edit with
 * `action: "confirm"`, which is also the honest reading of the gesture: attaching a person to an
 * outline IS confirming that the outline is a person.
 *
 * A region that already carries a subject skips straight to the third request, which is the
 * ordinary case once somebody has been given a decision at all.
 *
 * **Nothing here retries.** Each of the three requests is a receipt, and a client that replayed a
 * failed one could write two subjects for one person or two confirmations of one outline. A
 * failure surfaces as an error the panel states; the reviewer decides whether to try again.
 */

import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';

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

  constructor(options: TransportOptions) {
    // Narrowed to the three fields a request needs, and `fetch` is spread conditionally rather
    // than passed as possibly-undefined: `exactOptionalPropertyTypes` is on, so an absent option
    // and an option set to undefined are different types. `signal` is deliberately dropped, since
    // each request below sets its own timeout.
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
      await this.#transport().postJson(`/person-regions/${captureId}/edits`, { edits: [edit] });
    } catch (error) {
      throw asUnavailable(error);
    }
  }

  /** Add only a location. No subject, consent or other capture is changed. */
  async add(captureId: string, region: ManualRegion): Promise<void> {
    validateOutline(region.silhouette);
    if (!/^[0-9a-f]{64}$/u.test(region.region_key)) throw new Error('Invalid region key.');
    try {
      await this.#transport().postJson(`/person-regions/${captureId}/edits`, {
        edits: [{ region_key: region.region_key, action: 'add', shape: 'box',
          silhouette: region.silhouette }],
      });
    } catch (error) {
      throw asUnavailable(error);
    }
  }

  /**
   * Record what one person agreed to, creating and binding them first if nobody has yet.
   *
   * Returns the subject the decision was recorded against, so a caller holding stale regions can
   * tell that a subject now exists without refetching. It refetches anyway, because the resolved
   * state of every other region can move when one receipt lands.
   */
  async consent(
    captureId: string,
    region: ReviewRegion,
    scope: 'presence' | 'naming' | 'likeness',
    decision: 'granted' | 'revoked',
  ): Promise<string> {
    let subjectId = region.subjectId;
    if (subjectId === null) {
      // Nobody has said this outline is a person yet, so there is nobody for a receipt to be
      // about. Creating the subject and binding it are separate requests because the server has
      // no combined writer; if one is ever added, this is the only place that changes.
      let created: { readonly subject_id: string };
      try {
        created = await this.#transport().postJson<{ readonly subject_id: string }>(
          '/person-subjects', {},
        );
      } catch (error) {
        throw asUnavailable(error);
      }
      subjectId = created.subject_id;
      await this.edit(captureId, {
        region_key: region.regionKey, action: 'confirm', subject_id: subjectId,
      });
    }
    try {
      await this.#transport().postJson(`/person-subjects/${subjectId}/consents`, {
        consent_scope: scope, decision, region_key: region.regionKey,
      });
    } catch (error) {
      throw asUnavailable(error);
    }
    return subjectId;
  }
}
