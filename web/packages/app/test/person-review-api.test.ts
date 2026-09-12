// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest';

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

  it('refuses consent without an explicit identity and never creates a subject', async () => {
    const fetch = vi.fn(async () => json({ capture_id: CAPTURE, review_state: 'screened', regions: [wireRegion()] }));
    const api = new PersonReviewApi({ baseUrl: 'https://exulanica.test/api', token: 't', fetch });
    const region = (await api.load(CAPTURE)).regions[0]!;
    await expect(api.consent(CAPTURE, region, 'presence', 'granted')).rejects.toThrow('Identify this person');
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('links matching regions through the atomic route and reconciles an interrupted response', async () => {
    let linked = false;
    const posts: string[] = [];
    const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
      const path = new URL(String(input)).pathname;
      if (init.method === 'POST') {
        posts.push(path);
        expect(JSON.parse(String(init.body))).toEqual({ request_id: expect.any(String), regions: [
          { capture_id: CAPTURE, region_key: 'a'.repeat(64) },
          { capture_id: 'other', region_key: 'a'.repeat(64) },
        ] });
        if (linked) return json({ subject_id: SUBJECT });
        linked = true;
        throw new Error('response interrupted after server commit');
      }
      return json({ capture_id: path.split('/').at(-1), review_state: 'screened',
        regions: [wireRegion({ subject_id: linked ? SUBJECT : null })] });
    });
    const api = new PersonReviewApi({ baseUrl: 'https://exulanica.test/api', token: 't', fetch });
    const regions = [CAPTURE, 'other'].map(capture_id => ({ capture_id, region_key: 'a'.repeat(64) }));
    await expect(api.link(regions)).rejects.toThrow();
    expect(await api.requests.retry()).toEqual({ subject_id: SUBJECT });
    expect(posts).toEqual(['/api/identity/subjects/link', '/api/identity/subjects/link']);
  });

  it('rechecks current identity before recording consent on its existing subject', async () => {
    const posts: { path: string; body: unknown }[] = [];
    const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
      const path = new URL(String(input)).pathname;
      if (init.method === 'POST') { posts.push({ path, body: JSON.parse(String(init.body)) }); return json({ actor_role: 'owner' }); }
      return json({ capture_id: CAPTURE, review_state: 'screened', regions: [wireRegion({ subject_id: SUBJECT, action: 'confirmed' })] });
    });
    const api = new PersonReviewApi({ baseUrl: 'https://exulanica.test/api', token: 't', fetch });
    const region = (await api.load(CAPTURE)).regions[0]!;
    await api.consent(CAPTURE, region, 'temporary_hide', 'granted');
    expect(posts).toEqual([{ path: `/api/person-subjects/${SUBJECT}/consents`,
      body: { request_id: expect.any(String), consent_scope: 'temporary_hide', decision: 'granted', region_key: region.regionKey } }]);
  });

  it('corrects an outline without changing its subject and reuses a completed correction', async () => {
    let shape = wireRegion().silhouette;
    const posts: unknown[] = [];
    const fetch = vi.fn(async (_input: string | URL | Request, init: RequestInit = {}) => {
      if (init.method === 'POST') {
        const body = JSON.parse(String(init.body)); posts.push(body); shape = body.edits[0].silhouette; return json({});
      }
      return json({ capture_id: CAPTURE, review_state: 'screened', regions: [wireRegion({ silhouette: shape, subject_id: SUBJECT })] });
    });
    const api = new PersonReviewApi({ baseUrl: 'https://exulanica.test/api', token: 't', fetch });
    const edit = { region_key: 'a'.repeat(64), silhouette: { kind: 'polygon' as const, points: [[0, 0], [500000, 0], [0, 500000]] } };
    await api.correct(CAPTURE, edit); await api.correct(CAPTURE, edit);
    expect(posts).toEqual([{ request_id: expect.any(String), edits: [{ ...edit, action: 'confirm', shape: 'box' }] }]);
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
      .toContain('does not establish a human no-person attestation');
    expect(nobodyLooked.querySelector('.person-review-unscreened')?.textContent)
      .toContain('No person regions are recorded');
    expect(looked.textContent).not.toEqual(nobodyLooked.textContent);
  });
});

afterEach(() => window.sessionStorage.clear());
