// What a program let into a world says it is, as GET /door/grants serves it (exulanica/api/routes/door.py,
// _grant_view: the grant's own fields and "declared", the program's words at its last hello, or null).
import { describe, expect, it, vi } from 'vitest';
import { DoorGrantsClient, parseDoorGrants } from '../src/door-grants-api.js';

const row = (grantId: string, declared: unknown, extra: Record<string, unknown> = {}) => ({
  grant_id: grantId, world_id: 'world:authored:w', bridge: 'agents', grant_seq: 1, state: 'active', scope: {},
  expires_at: '2026-10-08T05:00:00Z', issued_at: '2026-10-08T01:00:00Z', ended: null, bridge_label: 'Agents',
  run_by: 'owner', ai: true, connected: true, adapter_version: '1.0', declared, ...extra,
});
/** What every grant below keeps beside its program's words: its world, that it stands, and an AI's program. */
const kept = { worldId: 'world:authored:w', ended: null, ai: true, versionId: null, things: [] };

describe('the world\'s grants', () => {
  it('reads each grant\'s program in its own words, or none where it said nothing', () => {
    const grants = parseDoorGrants({ grants: [
      row('g-1', { name: 'Scout', maker: 'Acme', mind: 'Qwen3 235B Instruct' }),
      row('g-2', { name: 'Pathfinder', maker: 'Acme' }),
      row('g-3', null),
    ] });
    expect(grants).toEqual([
      { grantId: 'g-1', bridge: 'agents', declared: { name: 'Scout', maker: 'Acme', mind: 'Qwen3 235B Instruct' }, ...kept },
      { grantId: 'g-2', bridge: 'agents', declared: { name: 'Pathfinder', maker: 'Acme', mind: null }, ...kept },
      { grantId: 'g-3', bridge: 'agents', declared: null, ...kept },
    ]);
  });

  it('keeps whether each grant stands, whether its program is an AI\'s, and the people it was given for', () => {
    const [ended, game, named] = parseDoorGrants({ grants: [
      row('g-1', null, { state: 'revoked', ended: 'revoked' }),
      row('g-2', null, { bridge: 'a-game', ai: false, ended: 'expired' }),
      row('g-3', null, { scope: { things: ['p-1', 'p-2'], version_id: 'v-1', visitors_maximum: 0 } }),
    ] });
    expect([ended!.ended, ended!.ai]).toEqual(['revoked', true]);
    expect([game!.ended, game!.ai]).toEqual(['expired', false]);
    expect([named!.ended, named!.versionId, named!.things]).toEqual([null, 'v-1', ['p-1', 'p-2']]);
  });

  it('refuses an answer that is not a list, or a declaration without a name', () => {
    expect(() => parseDoorGrants({})).toThrow(/not a list/u);
    expect(() => parseDoorGrants({ grants: [row('g-1', { maker: 'Acme' })] })).toThrow(/a name/u);
    expect(() => parseDoorGrants({ grants: [row('g-1', null, { world_id: '' })] })).toThrow(/its world/u);
  });

  it('asks for the open world\'s grants by its id, and nothing where no world is open', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ grants: [row('g-1', null)] }), { status: 200 }));
    const read = await new DoorGrantsClient({ baseUrl: 'https://host.test', token: 'token', fetch: fetcher as never, worldId: 'world:authored:w' }).read();
    expect([...read.keys()]).toEqual(['g-1']);
    expect(String((fetcher.mock.calls[0] as unknown[])[0])).toBe('https://host.test/door/grants?world_id=world%3Aauthored%3Aw');
    await expect(new DoorGrantsClient({ baseUrl: 'https://host.test', token: 'token', fetch: fetcher as never, worldId: null }).read()).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('ends a grant through the door\'s own revoke, with the session\'s CSRF token, and reads it as it then stands', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ grant: row('g 1', null, { state: 'revoked', ended: 'revoked' }) }), { status: 200 }));
    const ended = await new DoorGrantsClient({ baseUrl: 'https://host.test', token: '', csrfToken: 'csrf', fetch: fetcher as never, worldId: null }).revoke('g 1');
    const [address, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(address)).toBe('https://host.test/door/grants/g%201/revoke');
    expect(init.method).toBe('POST');
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf');
    expect([ended.grantId, ended.ended]).toEqual(['g 1', 'revoked']);
  });
});
