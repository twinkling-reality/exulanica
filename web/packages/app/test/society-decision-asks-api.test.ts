import { describe, expect, it, vi } from 'vitest';
import { DecisionAsksClient, parseAskAgainOffer, parseDecisionAsk, parseDecisionAsks } from '../src/society-decision-asks-api.js';

const MODEL = { provider: 'nebius_token_factory', modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507' };
const decision = {
  request_id: 'request-1', base_tick: 52, provider: 'nebius_token_factory', model_id: 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',
  chose: 'say something to Ines', line: 'Calm water today, Ines.',
  ask_usd: { chosen: '0.00698440', again: '0.00041620' }, refusal: null, again_refusal: null,
};
const offer = {
  most: 12, model: { provider: MODEL.provider, model_id: MODEL.modelId }, refusal: null,
  decisions: [decision, { ...decision, request_id: 'request-2', ask_usd: null, refusal: 'decision_not_reproducible' }],
  askable: 1, most_usd: '0.00740060',
};
const ask = {
  ask_id: 'ask-1', provider: MODEL.provider, model_id: MODEL.modelId, mechanism: 'tool_call', status: 'accepted',
  reason: 'validated_choice', chose: 'walk to the lower pools', kind: 'target', line: null, served_model_id: MODEL.modelId,
  cost_usd: '0.00017000', cost_known: true, prompt_tokens: 900, completion_tokens: 10, latency_ms: 670,
  same_choice: false, same_kind: false, same_messages: true, bound_usd: '0.00698440', asked_at: '2026-10-15T06:00:00+00:00',
};

const answering = (body: unknown) => vi.fn(async (_url: unknown, _init?: RequestInit) =>
  new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } }));

describe('a person\'s recorded decisions asked again', () => {
  it('reads the offer as the server states it, the count and the most it can cost its own', () => {
    const read = parseAskAgainOffer(offer);
    expect(read.most).toBe(12);
    expect(read.mostUsd).toBe('0.00740060');
    expect(read.decisions[0]).toEqual({
      requestId: 'request-1', baseTick: 52, model: { provider: 'nebius_token_factory', modelId: 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B' },
      chose: 'say something to Ines', line: 'Calm water today, Ines.', askUsd: { chosen: '0.00698440', again: '0.00041620' },
      refusal: null, againRefusal: null,
    });
    expect(read.decisions[1]).toMatchObject({ askUsd: null, refusal: 'decision_not_reproducible' });
    // A count that disagrees with its own decisions, or an amount in exponent form, is not read.
    expect(() => parseAskAgainOffer({ ...offer, askable: 2 })).toThrow('decision asks');
    expect(() => parseAskAgainOffer({ ...offer, most_usd: '1E-8' })).toThrow('decision asks');
    expect(parseAskAgainOffer({ ...offer, refusal: 'model_not_declared', decisions: [], askable: 0, most_usd: '0.00000000' }).refusal)
      .toBe('model_not_declared');
  });

  it('asks the offer for the chosen model in the open world, and posts one ask under its bound and key', async () => {
    const fetcher = answering(offer);
    const client = new DecisionAsksClient({ baseUrl: 'https://example.test', token: 'token', worldId: 'world:personal:asks', fetch: fetcher as typeof fetch });
    await client.offer('version', 'person-1', MODEL);
    const url = new URL(String(fetcher.mock.calls[0]![0]));
    expect(url.pathname).toBe('/world/versions/version/society/people/person-1/asks-again');
    expect(url.searchParams.get('model')).toBe(`${MODEL.provider}/${MODEL.modelId}`);
    expect(url.searchParams.get('world_id')).toBe('world:personal:asks');
    expect(url.searchParams.has('request_id')).toBe(false);
    // One decision, from its own page, whatever its age.
    await client.offer('version', 'person-1', MODEL, 'request-1');
    expect(new URL(String(fetcher.mock.calls[1]![0])).searchParams.get('request_id')).toBe('request-1');

    const posting = answering(ask);
    const asking = new DecisionAsksClient({ baseUrl: 'https://example.test', token: 'token', worldId: 'world:personal:asks', fetch: posting as typeof fetch });
    const answered = await asking.ask('version', 'request-1', MODEL, '0.00698440', 'key-1');
    expect(posting.mock.calls[0]![1]?.method).toBe('POST');
    expect(JSON.parse(String(posting.mock.calls[0]![1]?.body))).toEqual({
      model: { provider: MODEL.provider, model_id: MODEL.modelId }, bound_usd: '0.00698440', idempotency_key: 'key-1',
    });
    expect(answered).toMatchObject({ askId: 'ask-1', chose: 'walk to the lower pools', sameChoice: false, costUsd: '0.00017000' });
  });

  it('reads one decision\'s original answer and its asks, oldest first', () => {
    const read = parseDecisionAsks({
      request_id: 'request-1', base_tick: 52,
      original: { provider: 'nebius_token_factory', model_id: 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B', status: 'accepted', reason: 'validated_choice',
        chose: 'say something to Ines', kind: 'say', line: 'Calm water today, Ines.', served_model_id: null, cost_usd: '0.00030000', cost_known: true,
        prompt_tokens: 800, completion_tokens: 20, latency_ms: 900 },
      asks: [ask],
    });
    expect(read.original).toMatchObject({ chose: 'say something to Ines', line: 'Calm water today, Ines.', costUsd: '0.00030000' });
    expect(read.asks.map((one) => one.askId)).toEqual(['ask-1']);
    expect(() => parseDecisionAsk({ ...ask, same_choice: 'no' })).toThrow('decision asks');
  });
});
