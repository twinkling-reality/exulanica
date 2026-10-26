import { describe, expect, it, vi } from 'vitest';
import { parseReferenceCapability, parseReferenceRequest, referenceHasNotes, ReferencesClient } from '../src/references-api.js';

/*
 * The reference routes' answers as exulanica/api/routes/references.py writes them, written here by
 * hand: one request with its steps and notes, and the read that says whether one may be asked.
 */

const request = {
  reference_id: 'ref-1', purpose: 'things', web: true, status: 'complete',
  steps: [{ step: 'plan', state: 'done', subjects: 3 }, { step: 'search', state: 'done', sent: 3, found: 3, withheld: 0 }, { step: 'read', state: 'done' }, { step: 'bundle', state: 'done' }],
  notes: [{ aspect: 'anatomy', text: 'A round body with short wings and a flat bill', basis: 'web_description' }],
  missed: [], failure: null,
  searches: [{ source: 'tavily_search', outcome: 'sent', result_count: 5, credits: 1, sent_at: '2026-10-26T15:00:00+00:00' }],
  bundle_sha256: 'c'.repeat(64), cancel_requested: false, created_at: '2026-10-26T15:00:00+00:00', finished_at: '2026-10-26T15:00:12+00:00',
};

const capability = (permitted: boolean, state: string, code: string | null) => ({
  references: [request],
  capabilities: [{ operation: 'POST /worlds/references', permitted, state, code }],
  pictures: { offered: false, code: 'reference_pictures_not_offered', maximum: 4 },
  web_pictures: { offered: false, code: 'web_pictures_not_offered', words: 8 },
});

describe('web notes for a draft, as the server answers them', () => {
  it('reads a request: its steps with their facts, its notes, and our record of each search', () => {
    const read = parseReferenceRequest(request);
    expect(read.steps[1]).toEqual({ step: 'search', state: 'done', reason: null, facts: { sent: 3, found: 3, withheld: 0 } });
    expect(read.notes).toEqual([{ aspect: 'anatomy', text: 'A round body with short wings and a flat bill', basis: 'web_description' }]);
    expect(read.searches).toEqual([{ source: 'tavily_search', outcome: 'sent', resultCount: 5, credits: 1, sentAt: '2026-10-26T15:00:00+00:00' }]);
    expect(referenceHasNotes(read)).toBe(true);
    expect(referenceHasNotes(parseReferenceRequest({ ...request, status: 'failed' }))).toBe(false);
    expect(referenceHasNotes(parseReferenceRequest({ ...request, notes: [] }))).toBe(false);
    expect(() => parseReferenceRequest({ ...request, notes: [{ aspect: 'anatomy', text: '' }] })).toThrow(TypeError);
    expect(() => parseReferenceRequest({ ...request, steps: 'done' })).toThrow(TypeError);
  });

  it('offers a request only where its capability is available and this person may make one', () => {
    expect(parseReferenceCapability(capability(true, 'available', null)).ask).toEqual({ offered: true, code: null });
    expect(parseReferenceCapability(capability(false, 'available', null)).ask).toEqual({ offered: false, code: 'references_not_permitted' });
    expect(parseReferenceCapability(capability(true, 'unavailable', 'references_operator_only')).ask).toEqual({ offered: false, code: 'references_operator_only' });
    expect(parseReferenceCapability(capability(true, 'available', null)).webPictures).toEqual({ offered: false, code: 'web_pictures_not_offered', words: 8 });
  });

  it('asks for web notes on the words under one key, stating web on every request', async () => {
    const posting = vi.fn(async (_url: unknown, _init?: RequestInit) => new Response(JSON.stringify({ ...request, status: 'queued', notes: [], searches: [], bundle_sha256: null, finished_at: null }), { status: 202, headers: { 'content-type': 'application/json' } }));
    const client = new ReferencesClient({ baseUrl: 'https://example.test', token: 'token', fetch: posting as typeof fetch });
    await client.request({ purpose: 'things', description: 'a little yellow robot duck', idempotencyKey: 'key-1' });
    expect(new URL(String(posting.mock.calls[0]![0])).pathname).toBe('/worlds/references');
    expect(JSON.parse(String(posting.mock.calls[0]![1]?.body))).toEqual({ purpose: 'things', description: 'a little yellow robot duck', web: true, idempotency_key: 'key-1' });
  });
});
