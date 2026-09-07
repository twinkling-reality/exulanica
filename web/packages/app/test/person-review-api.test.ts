// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';

import { PersonReviewApi, ReviewUnavailable } from '../src/person-review-api.js';
import { buildPersonReview } from '../src/ui/person-review.js';

const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), {
  status,
  headers: { 'content-type': 'application/json' },
});

/** One region exactly as `exulanica/ingest/person_review.py::review_list` writes it. */
const wireRegion = (overrides: Record<string, unknown> = {}) => ({
  region_key: 'a'.repeat(64),
  action: 'detected',
  shape: 'box',
  part: 'arm',
  silhouette: { kind: 'polygon', points: [[0, 0], [1000000, 0], [1000000, 1000000]] },
  detector_id: 'recorded-vision-observation/v1',
  confidence: 'low',
  confirmed_by: null,
  subject_id: null,
  state: 'unknown',
  masked: true,
  name_permitted: false,
  ...overrides,
});

const CAPTURE = '11111111-1111-4111-8111-111111111111';
const SUBJECT = '22222222-2222-4222-8222-222222222222';

describe('the review screen boundary', () => {
  it('renames the five snake_case keys and invents no others', async () => {
    const fetch = vi.fn(async () => json({
      capture_id: CAPTURE, review_state: 'screened', regions: [wireRegion()],
    }));
    const review = await new PersonReviewApi({
      baseUrl: 'https://exulanica.test/api', token: 't', fetch,
    }).load(CAPTURE);

    expect(review.reviewState).toBe('screened');
    const region = review.regions[0]!;
    expect(region.regionKey).toBe('a'.repeat(64));
    expect(region.detectorId).toBe('recorded-vision-observation/v1');
    expect(region.confirmedBy).toBeNull();
    expect(region.subjectId).toBeNull();
    expect(region.namePermitted).toBe(false);
    // Taken from the server rather than recomputed. `masked` is not `!drawsPixels(state)`: those
    // two disagree on `hidden`, and the direction they disagree in is a person drawn who should
    // not have been. There is one implementation of that rule and it is in the database.
    expect(region.masked).toBe(true);
  });

  it('says an unscreened photograph is unscreened rather than empty', async () => {
    const fetch = vi.fn(async () => json({
      capture_id: CAPTURE, review_state: 'unscreened', regions: [],
    }));
    const review = await new PersonReviewApi({
      baseUrl: 'https://exulanica.test/api', token: 't', fetch,
    }).load(CAPTURE);
    // The two facts this whole layer exists to keep apart. An empty list is not an answer; the
    // state is, and a caller that read emptiness as "nobody is here" would be making the 2026-09-05
    // bowl screening's mistake in the browser.
    expect(review.reviewState).toBe('unscreened');
    expect(review.regions).toHaveLength(0);
  });

  it('creates and binds a subject before the first consent, in that order', async () => {
    const calls: { path: string; body: unknown }[] = [];
    const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
      const path = new URL(String(input)).pathname;
      calls.push({ path, body: init.body === undefined ? null : JSON.parse(String(init.body)) });
      if (path === '/api/person-subjects') return json({ subject_id: SUBJECT });
      return json({});
    });
    const api = new PersonReviewApi({
      baseUrl: 'https://exulanica.test/api', token: 't', fetch,
    });
    const region = (await new PersonReviewApi({
      baseUrl: 'https://exulanica.test/api',
      token: 't',
      fetch: async () => json({ capture_id: CAPTURE, review_state: 'screened', regions: [wireRegion()] }),
    }).load(CAPTURE)).regions[0]!;

    const subject = await api.consent(CAPTURE, region, 'presence', 'granted');

    expect(subject).toBe(SUBJECT);
    expect(calls.map((call) => call.path)).toEqual([
      '/api/person-subjects',
      `/api/person-regions/${CAPTURE}/edits`,
      `/api/person-subjects/${SUBJECT}/consents`,
    ]);
    // The binding is a confirmation, and it carries the subject the first call created. Without
    // this the consent would be recorded against somebody attached to no outline, and the region
    // would go on resolving to `unknown` while the receipt said otherwise.
    expect(calls[1]!.body).toEqual({
      edits: [{ region_key: 'a'.repeat(64), action: 'confirm', subject_id: SUBJECT }],
    });
    expect(calls[2]!.body).toEqual({
      consent_scope: 'presence', decision: 'granted', region_key: 'a'.repeat(64),
    });
  });

  it('records against an existing subject without creating a second one', async () => {
    const paths: string[] = [];
    const fetch = vi.fn(async (input: string | URL | Request) => {
      paths.push(new URL(String(input)).pathname);
      return json({});
    });
    const region = (await new PersonReviewApi({
      baseUrl: 'https://exulanica.test/api',
      token: 't',
      fetch: async () => json({
        capture_id: CAPTURE,
        review_state: 'screened',
        regions: [wireRegion({ subject_id: SUBJECT, action: 'confirmed' })],
      }),
    }).load(CAPTURE)).regions[0]!;

    await new PersonReviewApi({
      baseUrl: 'https://exulanica.test/api', token: 't', fetch,
    }).consent(CAPTURE, region, 'likeness', 'revoked');

    // One request, not three. A second subject for a person who already has one would split their
    // receipt chain in two, and the fold that resolves their state reads one chain.
    expect(paths).toEqual([`/api/person-subjects/${SUBJECT}/consents`]);
  });

  it('turns a refused edit into a sentence a reviewer can act on', async () => {
    const fetch = vi.fn(async () => json({ detail: 'nothing proposed that region' }, 409));
    const api = new PersonReviewApi({
      baseUrl: 'https://exulanica.test/api', token: 't', fetch,
    });
    await expect(api.edit(CAPTURE, { region_key: 'b'.repeat(64), action: 'confirm' }))
      .rejects.toBeInstanceOf(ReviewUnavailable);
  });

  it('refuses a review state it does not understand rather than rendering it', async () => {
    // `stale` is in the wire vocabulary and nothing emits it. A client that passed an unknown
    // state through would put it in front of a reviewer as though it meant something.
    const fetch = vi.fn(async () => json({
      capture_id: CAPTURE, review_state: 'stale', regions: [],
    }));
    const api = new PersonReviewApi({
      baseUrl: 'https://exulanica.test/api', token: 't', fetch,
    });
    await expect(api.load(CAPTURE)).rejects.toThrow(/stale/u);
  });
});

describe('the client and the panel, joined', () => {
  const load = async (body: unknown) => new PersonReviewApi({
    baseUrl: 'https://exulanica.test/api',
    token: 't',
    fetch: async () => json(body),
  }).load(CAPTURE);

  const render = (review: Awaited<ReturnType<typeof load>>) => buildPersonReview({
    captureId: review.captureId, reviewState: review.reviewState, regions: review.regions,
  });

  it('drives the panel from the mapped answer without any further translation', async () => {
    // The seam this file exists for. The mapper and the panel were written apart and never met:
    // person-review.ts had no importer at all until 2026-09-07, so nothing had ever checked that
    // what the route sends satisfies what the panel reads.
    const panel = render(await load({
      capture_id: CAPTURE,
      review_state: 'screened',
      regions: [wireRegion(), wireRegion({ region_key: 'c'.repeat(64), state: 'shown', masked: false })],
    }));
    const rendered = [...panel.querySelectorAll('.person-review-region')] as HTMLElement[];
    expect(rendered).toHaveLength(2);
    expect(rendered[0]!.dataset.regionKey).toBe('a'.repeat(64));
    expect(rendered[0]!.dataset.state).toBe('unknown');
    expect(rendered[1]!.dataset.state).toBe('shown');
    // The detector's own words reach the reviewer, so a proposal is legible as a proposal.
    expect(panel.textContent).toContain('recorded-vision-observation/v1');
    expect(panel.textContent).toContain('A proposal, not a decision.');
    // And the panel never claims the decision is the subject's.
    expect(panel.textContent).toContain('not the decision of the person in the photograph');
  });

  it('renders "somebody looked and found nobody", which was unreachable before today', async () => {
    // This branch of person-review.ts was dead code. The route derived review_state from whether
    // the live region list was empty, so `screened` with no regions could not be produced, and a
    // reviewer who deleted every false positive was told nobody had looked. The route now asks
    // whether any region row has ever existed, which is the same question the graph payload asks,
    // so the two answers below are both reachable and they differ.
    const looked = render(await load({
      capture_id: CAPTURE, review_state: 'screened', regions: [],
    }));
    const nobodyLooked = render(await load({
      capture_id: CAPTURE, review_state: 'unscreened', regions: [],
    }));
    expect(looked.querySelector('.person-review-empty')?.textContent)
      .toContain('nobody was found');
    expect(nobodyLooked.querySelector('.person-review-unscreened')?.textContent)
      .toContain('Nobody has looked');
    expect(looked.textContent).not.toEqual(nobodyLooked.textContent);
  });
});
