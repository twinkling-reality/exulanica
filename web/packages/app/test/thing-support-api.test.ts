import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { parseThingSupport, ThingSupportClient } from '../src/thing-support-api.js';
const saved = JSON.parse(readFileSync(new URL('./fixtures/world-version-supported.v6.json', import.meta.url), 'utf8'));
const wire = () => ({profile: 'exulanica.support-placement-availability/v1', version_id: saved.version_id,
  thing_id: saved.things[0].thing_id, state_sha256: saved.state_sha256, support: saved.things[0].support,
  availability: 'available', code: null, where: null, society: {availability: 'omitted', reason: null}});
describe('supported thing availability reader', () => {
  it('reads support separately from society omission and scopes the authorized abortable GET', async () => {
    const fetch = vi.fn(async (_url: string | URL | Request, _init?: RequestInit) => new Response(JSON.stringify(wire())));
    const signal = new AbortController().signal;
    const result = await new ThingSupportClient({baseUrl: 'https://example.test', token: 'test', worldId: saved.world_id, fetch})
      .read(saved.version_id, saved.things[0].thing_id, signal);
    expect(result.availability).toBe('available'); expect(result.support?.surfaceId).toBe('deck');
    const [url, init] = fetch.mock.calls[0]!;
    expect(String(url)).toContain(`/things/${encodeURIComponent(saved.things[0].thing_id)}/support?world_id=`);
    expect(init?.signal).toBe(signal); expect(init?.headers).toEqual({authorization: 'Bearer test'});
  });
  it.each([{profile: 'other'}, {version_id: 'another'}, {thing_id: 'another'}, {state_sha256: 'bad'},
    {availability: 'maybe'}, {support: null}, {support: {...wire().support, extra: true}},
    {support: {...wire().support, network_sha256: 'bad'}}])('rejects mismatched read %j', change => {
    expect(() => parseThingSupport({...wire(), ...change}, saved.version_id, saved.things[0].thing_id)).toThrow();
  });
  it('preserves nonadmission states', () => {
    for (const availability of ['removed', 'unavailable']) expect(parseThingSupport({...wire(), availability}, saved.version_id, saved.things[0].thing_id).availability).toBe(availability);
    expect(parseThingSupport({...wire(), availability: 'unbound', support: null}, saved.version_id, saved.things[0].thing_id).support).toBeNull();
  });
});
