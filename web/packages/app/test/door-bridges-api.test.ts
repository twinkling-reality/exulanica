import { describe, expect, it, vi } from 'vitest';
import { DOOR_BRIDGES_PATH, DoorBridgesClient, parseDoorBridges } from '../src/door-bridges-api.js';

/*
 * The door's bridges, read strictly. The body is the door route's (`GET /door/bridges`: each
 * offered bridge's key, label, game, who runs it and whether an AI does), with the agents bridge's
 * entry as its example file states it (bridges/agents/examples/bridge-entry.json).
 */

const SERVED = {
  bridges: [
    { bridge: 'agents', label: 'Outside AI agents', game: 'AI agents, through MCP or the agent library', run_by: 'owner', ai: true },
    { bridge: 'blockgame', label: 'Block Game', game: 'Block Game', run_by: 'server', ai: false },
  ],
};

describe('the bridges the door offers here', () => {
  it('reads each bridge by its key, with whether an AI runs it', async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(SERVED), {
      status: 200, headers: { 'content-type': 'application/json' },
    }));
    const bridges = await new DoorBridgesClient({ baseUrl: 'http://host.test/', token: 'token-1', fetch }).read();
    expect([...bridges.keys()]).toEqual(['agents', 'blockgame']);
    expect(bridges.get('agents')).toEqual({ bridge: 'agents', label: 'Outside AI agents', game: 'AI agents, through MCP or the agent library', runBy: 'owner', ai: true });
    expect(bridges.get('blockgame')!.ai).toBe(false);
    const [url, init] = fetch.mock.calls[0]!;
    expect(String(url)).toBe(`http://host.test${DOOR_BRIDGES_PATH}`);
    expect(new Headers(init?.headers).get('authorization')).toBe('Bearer token-1');
  });

  it('reads a door that offers nothing as no bridges', () => {
    expect(parseDoorBridges({ bridges: [] })).toEqual([]);
  });

  it('refuses an entry that does not say whether an AI runs it, who runs it or what it is', () => {
    const entry = SERVED.bridges[1]!;
    expect(() => parseDoorBridges({ bridges: [{ ...entry, ai: 'no' }] })).toThrow(/whether an AI runs it/u);
    expect(() => parseDoorBridges({ bridges: [{ ...entry, run_by: 'anyone' }] })).toThrow(/who runs it/u);
    expect(() => parseDoorBridges({ bridges: [{ ...entry, label: '  ' }] })).toThrow(/a label/u);
    expect(() => parseDoorBridges({ bridge: entry })).toThrow(/not a list/u);
  });
});
