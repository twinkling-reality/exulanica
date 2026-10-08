// What a program let into a world says it is, as GET /door/grants serves it (exulanica/api/routes/door.py,
// _grant_view: the grant's own fields and "declared", the program's words at its last hello, or null).
import { describe, expect, it, vi } from 'vitest';
import { DoorGrantsClient, parseDoorGrants } from '../src/door-grants-api.js';

const row = (grantId: string, declared: unknown) => ({
  grant_id: grantId, world_id: 'world:authored:w', bridge: 'agents', grant_seq: 1, state: 'issued', scope: {},
  expires_at: '2026-10-08T05:00:00Z', issued_at: '2026-10-08T01:00:00Z', ended: false, bridge_label: 'Agents',
  run_by: 'owner', ai: true, connected: true, adapter_version: '1.0', declared,
});

describe('the world\'s grants', () => {
  it('reads each grant\'s program in its own words, or none where it said nothing', () => {
    const grants = parseDoorGrants({ grants: [
      row('g-1', { name: 'Scout', maker: 'Acme', mind: 'Qwen3 235B Instruct' }),
      row('g-2', { name: 'Pathfinder', maker: 'Acme' }),
      row('g-3', null),
    ] });
    expect(grants).toEqual([
      { grantId: 'g-1', bridge: 'agents', declared: { name: 'Scout', maker: 'Acme', mind: 'Qwen3 235B Instruct' } },
      { grantId: 'g-2', bridge: 'agents', declared: { name: 'Pathfinder', maker: 'Acme', mind: null } },
      { grantId: 'g-3', bridge: 'agents', declared: null },
    ]);
  });

  it('refuses an answer that is not a list, or a declaration without a name', () => {
    expect(() => parseDoorGrants({})).toThrow(/not a list/u);
    expect(() => parseDoorGrants({ grants: [row('g-1', { maker: 'Acme' })] })).toThrow(/a name/u);
  });

  it('asks for the open world\'s grants by its id, and nothing where no world is open', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ grants: [row('g-1', null)] }), { status: 200 }));
    const read = await new DoorGrantsClient({ baseUrl: 'https://host.test', token: 'token', fetch: fetcher as never, worldId: 'world:authored:w' }).read();
    expect([...read.keys()]).toEqual(['g-1']);
    expect(String((fetcher.mock.calls[0] as unknown[])[0])).toBe('https://host.test/door/grants?world_id=world%3Aauthored%3Aw');
    await expect(new DoorGrantsClient({ baseUrl: 'https://host.test', token: 'token', fetch: fetcher as never, worldId: null }).read()).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
