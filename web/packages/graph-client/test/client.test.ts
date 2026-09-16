import { describe, expect, it } from 'vitest';

import { ApiError, ExulanicaClient, Transport } from '../src/index.js';
import { ProposalGate, httpCommitTransport } from '../src/mutations/index.js';
import type { UpdateProposal } from '../src/index.js';

describe('the transport', () => {
  const ok = (body: unknown, headers: Record<string, string> = {}) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'content-type': 'application/json', ...headers },
    });

  it('sends the bearer token in a header and never in the url', async () => {
    let seen: { url: string; init: RequestInit } | null = null;
    const transport = new Transport({
      baseUrl: 'https://example.invalid/',
      token: 'secret-token',
      fetch: async (url, init) => {
        seen = { url: String(url), init: init ?? {} };
        return ok({ ok: true });
      },
    });
    await transport.getJson('/graph');
    expect(seen!.url).toBe('https://example.invalid/graph');
    expect(seen!.url).not.toContain('secret-token');
    expect((seen!.init.headers as Record<string, string>).authorization).toBe(
      'Bearer secret-token',
    );
    expect(seen!.init.credentials).toBe('include');
  });

  it('uses the browser session without emitting an empty bearer and binds writes to CSRF', async () => {
    const seen: RequestInit[] = [];
    const transport = new Transport({
      baseUrl: 'https://example.invalid', token: '', csrfToken: 'csrf-session-value',
      fetch: async (_url, init) => { seen.push(init ?? {}); return ok({ ok: true }); },
    });
    await transport.getJson('/graph');
    await transport.putJson('/world/control', { mode: 'playing' });
    expect((seen[0]!.headers as Record<string, string>).authorization).toBeUndefined();
    expect((seen[0]!.headers as Record<string, string>)['x-csrf-token']).toBeUndefined();
    expect(seen[0]!.credentials).toBe('include');
    expect(seen[1]!.method).toBe('PUT');
    expect((seen[1]!.headers as Record<string, string>)['x-csrf-token']).toBe('csrf-session-value');
  });

  it('turns a problem body into an error carrying the code, not the status', async () => {
    const transport = new Transport({
      baseUrl: 'https://example.invalid',
      token: 't',
      fetch: async () =>
        new Response(JSON.stringify({ code: 'unknown_reference', detail: 'no such evidence' }), {
          status: 404,
          headers: { 'content-type': 'application/json' },
        }),
    });
    await expect(transport.getJson('/evidence/x')).rejects.toBeInstanceOf(ApiError);
    await transport.getJson('/evidence/x').catch((error: ApiError) => {
      expect(error.code).toBe('unknown_reference');
      expect(error.isNotFound).toBe(true);
    });
  });

  it('survives a failure that is not JSON, which is what a proxy returns', async () => {
    const transport = new Transport({
      baseUrl: 'https://example.invalid',
      token: 't',
      fetch: async () => new Response('<html>502</html>', { status: 502, statusText: 'Bad Gateway' }),
    });
    await transport.getJson('/graph').catch((error: ApiError) => {
      expect(error.status).toBe(502);
      expect(error.code).toBe('http_502');
      expect(error.message).toContain('Bad Gateway');
    });
  });

  it('sends authenticated deletes without trying to parse an empty response', async () => {
    let seen: RequestInit | undefined;
    const transport = new Transport({
      baseUrl: 'https://example.invalid',
      token: 'secret',
      fetch: async (_url, init) => {
        seen = init;
        return new Response(null, { status: 204 });
      },
    });
    await transport.delete('/world/styles/previews/p1');
    expect(seen?.method).toBe('DELETE');
    expect((seen?.headers as Record<string, string>).authorization).toBe('Bearer secret');
  });

  it('reads the modality and the clock uncertainty the evidence response carries', async () => {
    const client = new ExulanicaClient({
      baseUrl: 'https://example.invalid',
      token: 't',
      fetch: async () =>
        new Response(new Uint8Array([0xff, 0xd8]), {
          status: 200,
          headers: {
            'content-type': 'image/jpeg',
            'x-exulanica-modality': 'frame_region',
            'x-exulanica-captured-at': '2026-03-04T10:00:00+00:00',
            'x-exulanica-captured-at-uncertainty-ms': '3600000',
          },
        }),
    });
    const [resolved] = await client.resolve(['s1' as never]);
    expect(resolved!.modality).toBe('frame_region');
    expect(resolved!.capturedAtUncertaintyMs).toBe(3_600_000);
    expect(resolved!.capturedAtMs).toBe(Date.parse('2026-03-04T10:00:00+00:00'));
  });
});

describe('the commit transport', () => {
  const proposal = (op: string, payload: Record<string, unknown>): UpdateProposal => ({
    proposalId: 'p1',
    turnId: 't1',
    origin: 'user_choice',
    rawUtterance: 'yes, the same person',
    operations: [{ op, tier: 1, affectedAnchorIds: [], affectedIslandIds: [], payload }],
    provenanceSummary: '',
    maxTier: 1,
    reversible: true,
    expiresAtStateVersion: 7,
  });

  const transportWith = (calls: string[]) =>
    new Transport({
      baseUrl: 'https://example.invalid',
      token: 't',
      fetch: async (url) => {
        calls.push(new URL(String(url)).pathname);
        return new Response(JSON.stringify({ state_version: 8, link_id: 'l1' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      },
    });

  it('commits an approved proposal and reads the new state version from the server', async () => {
    const calls: string[] = [];
    const gate = new ProposalGate(httpCommitTransport(transportWith(calls)), 7);
    const staged = proposal('confirm', { occurrence_id: 'o1', entity_id: 'e1' });
    gate.stage(staged);
    const result = await gate.commit('p1');
    expect(calls).toEqual(['/identity/confirm', '/graph']);
    expect(result.stateVersion).toBe(8);
    expect(gate.pendingCount).toBe(0);
  });

  it('refuses an operation it has no transport for, before sending anything', async () => {
    const calls: string[] = [];
    const gate = new ProposalGate(httpCommitTransport(transportWith(calls)), 7);
    gate.stage(proposal('teleport', {}));
    await expect(gate.commit('p1')).rejects.toThrow('has no transport');
    expect(calls).toEqual([]);
  });

  it('refuses a malformed payload before sending anything', async () => {
    const calls: string[] = [];
    const gate = new ProposalGate(httpCommitTransport(transportWith(calls)), 7);
    gate.stage(proposal('confirm', { occurrence_id: 'o1' }));
    await expect(gate.commit('p1')).rejects.toThrow('missing entity_id');
    expect(calls).toEqual([]);
  });

  it('still refuses a proposal that was never staged, which is the gate and not the transport', async () => {
    const gate = new ProposalGate(httpCommitTransport(transportWith([])), 7);
    await expect(gate.commit('never-staged')).rejects.toThrow('not in the pending set');
  });
});
