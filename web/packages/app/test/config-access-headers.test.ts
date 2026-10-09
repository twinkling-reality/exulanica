import { describe, expect, it, vi } from 'vitest';
import { accessHeaders } from '../src/config.js';
import { fetchThingCardRoute, chooseThingLook } from '../src/thing-card-route-api.js';

/*
 * A browser account session runs with an empty token: its cookie carries the session, and the server
 * refuses an empty bearer even beside a valid cookie (401). Direct requests send the bearer only for a
 * token, and a write the session's CSRF token, as graph-client's transport does.
 */

describe('the headers a direct request carries', () => {
  it('sends no bearer for an account session, a bearer for a token, and the CSRF token only on a write', () => {
    expect(accessHeaders({ token: '' })).toEqual({});
    expect(accessHeaders({ token: 'scratch' })).toEqual({ Authorization: 'Bearer scratch' });
    expect(accessHeaders({ token: '', csrfToken: 'c' }, 'GET')).toEqual({});
    expect(accessHeaders({ token: '', csrfToken: 'c' }, 'POST')).toEqual({ 'X-CSRF-Token': 'c' });
  });

  it('reads and writes a thing card from a cookie session with no Authorization header', async () => {
    const access = { baseUrl: 'https://example.test/api', token: '', csrfToken: 'c' };
    const fetcher = vi.fn(async () => new Response(null, { status: 404 }));
    await fetchThingCardRoute(access, 'world', 'version', 'thing', fetcher as unknown as typeof fetch);
    await chooseThingLook(access, 'world', 'version', 'thing', { key: 'look', version: 1, sha256: 'a'.repeat(64) } as never, fetcher as unknown as typeof fetch);
    const sent = fetcher.mock.calls.map((call) => (call as unknown as [string, RequestInit])[1].headers as Record<string, string>);
    expect(sent.every((headers) => !('Authorization' in headers))).toBe(true);
    expect(sent[1]).toMatchObject({ 'X-CSRF-Token': 'c' });
  });
});
