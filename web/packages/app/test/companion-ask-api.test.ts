// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';

import { AskUnavailable, CompanionAskClient, type Abstention } from '../src/companion-ask-api.js';
import { say } from '../src/ui/copy.js';

/**
 * The browser's half of the answer path, against the shapes the API actually sends.
 *
 * Every wire body below is written from `exulanica/api/routes/selection.py`. That matters more
 * than usual here: the answer carries per-request CITATION TOKENS and the packet carries SPAN
 * IDS, they are different namespaces, and the only thing that joins them is the permalink. A
 * test that invented its own shapes could pass while the join silently resolved nothing.
 */

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const WHERE = { baseUrl: 'https://exulanica.test/api', token: 'not-a-real-token' };

const URI_A = 'exulanica://blob/ni:///sha-256;aaaa';
const URI_B = 'exulanica://blob/ni:///sha-256;bbbb';
const SPAN_A = '11111111-1111-4111-8111-111111111111';
const SPAN_B = '22222222-2222-4222-8222-222222222222';

const call = (over: Record<string, unknown> = {}) => ({
  role: 'reasoning_cheap',
  requested_model: 'nvidia/Nemotron-3_5-Lightning',
  served_model: 'nvidia/Nemotron-3_5-Lightning',
  used_fallback: false,
  attempts: 1,
  latency_ms: 12_400,
  prompt_tokens: 900,
  completion_tokens: 300,
  reasoning_tokens: 210,
  ...over,
});

const answerBody = (over: Record<string, unknown> = {}) => ({
  answer: {
    clauses: [
      {
        text: 'You were beside a waterfall.',
        type: 'historical',
        citations: ['TOKENAAAA1'],
        value_refs: [],
      },
    ],
  },
  plan: { intent: 'captures', limit: 5 },
  selection: { captures: [], entities: [], total_matched: 1, truncated: false, includes_proposals: false },
  citations: { TOKENAAAA1: URI_A },
  abstained: null,
  deterministic: false,
  repaired: false,
  execution: { prompt_version: 'selection-1', calls: [call()] },
  ...over,
});

const packetBody = (items: unknown[]) => ({
  citable: true,
  total_matched: 1,
  truncated: false,
  items,
  values: [],
});

const packetItem = (token: string, uri: string, span: string) => ({
  token,
  uri,
  span_id: span,
  capture_id: '33333333-3333-4333-8333-333333333333',
  captured_at: '2026-02-01T10:00:00+00:00',
  trust: 'capture_supported',
  text: null,
});

function transport(...responses: Response[]) {
  const seen: { url: string; body: unknown }[] = [];
  const fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    seen.push({
      url: String(url),
      body: init?.body === undefined ? null : JSON.parse(String(init.body)),
    });
    return responses[seen.length - 1] ?? json({}, 500);
  });
  return { fetch: fetch as unknown as typeof globalThis.fetch, seen };
}

describe('asking the library a question', () => {
  it('joins the answer to the packet on the permalink, never on the token', async () => {
    // The two namespaces are deliberately disjoint here, which is what the server does: tokens
    // are drawn per request and the packet call is a second request. Matching by token would
    // find nothing and every chip would open nothing.
    const { fetch, seen } = transport(
      json(answerBody()),
      json(packetBody([packetItem('DIFFERENT1', URI_A, SPAN_A)])),
    );
    const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask('where was I?');

    expect(seen.map((request) => request.url)).toEqual([
      'https://exulanica.test/api/selection/ask',
      'https://exulanica.test/api/selection/packet',
    ]);
    expect(seen[0]!.body).toEqual({ question: 'where was I?' });
    // The plan the answer reported, posted back verbatim, so the packet resolves the same
    // Selection through the same validator rather than one rebuilt in the browser.
    expect(seen[1]!.body).toEqual({ intent: 'captures', limit: 5 });
    expect(answer.evidence).toHaveLength(1);
    expect(answer.evidence[0]!.token).toBe('TOKENAAAA1');
    expect(answer.evidence[0]!.handle).toBe(SPAN_A);
  });

  it('orders the evidence by first mention rather than by packet order', async () => {
    const body = answerBody({
      answer: {
        clauses: [
          { text: 'The second one first.', type: 'historical', citations: ['TOKENBBBB2'], value_refs: [] },
          { text: 'Then the first.', type: 'historical', citations: ['TOKENAAAA1'], value_refs: [] },
        ],
      },
      citations: { TOKENAAAA1: URI_A, TOKENBBBB2: URI_B },
    });
    const { fetch } = transport(
      json(body),
      json(packetBody([packetItem('X', URI_A, SPAN_A), packetItem('Y', URI_B, SPAN_B)])),
    );
    const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask('which ones?');

    expect(answer.evidence.map((cited) => cited.handle)).toEqual([SPAN_B, SPAN_A]);
  });

  it('keeps a citation whose span the packet did not name, with no handle', async () => {
    // Not dropped. A chip missing from a cited answer reads as an answer that cited less than
    // it did, so the citation survives and the surface renders it as one that cannot open.
    const { fetch } = transport(json(answerBody()), json(packetBody([])));
    const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask('where was I?');

    expect(answer.evidence).toHaveLength(1);
    expect(answer.evidence[0]!.handle).toBeNull();
  });

  it('still returns the answer when locating the evidence fails outright', async () => {
    const { fetch } = transport(json(answerBody()), json({ code: 'oops', detail: 'no' }, 500));
    const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask('where was I?');

    expect(answer.text).toBe('You were beside a waterfall.');
    expect(answer.evidence[0]!.handle).toBeNull();
  });

  it('carries the executed model and the measured latency through unchanged', async () => {
    const { fetch } = transport(
      json(answerBody({
        execution: {
          prompt_version: 'selection-1',
          calls: [
            call({ role: 'structured_extraction', requested_model: 'Qwen/Qwen3-235B-A22B-Instruct-2507', served_model: 'Qwen/Qwen3-235B-A22B-Instruct-2507', latency_ms: 5600 }),
            call({ served_model: 'nvidia/Nemotron-3_5-Lightning', latency_ms: 80_400 }),
          ],
        },
      })),
      json(packetBody([packetItem('X', URI_A, SPAN_A)])),
    );
    const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask('where was I?');

    expect(answer.promptVersion).toBe('selection-1');
    expect(answer.calls).toHaveLength(2);
    // The COMPOSING call names the answer, and the total is what the person waited through.
    expect(answer.provenance.composed).toBe('model');
    expect(answer.provenance.servedModel).toBe('nvidia/Nemotron-3_5-Lightning');
    expect(answer.provenance.latencyMs).toBe(86_000);
  });

  it('says the model was asked and its answer discarded, rather than crediting it', async () => {
    const { fetch } = transport(
      json(answerBody({ deterministic: true, repaired: false })),
      json(packetBody([packetItem('X', URI_A, SPAN_A)])),
    );
    const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask('where was I?');

    // architecture-overview.md 5.3: the deterministic answer is "a first-class output, not an
    // error page". It is also not the model's sentence, and the provenance may not say it is.
    expect(answer.deterministic).toBe(true);
    expect(answer.provenance.composed).toBe('discarded');
  });

  it('says a model READ the question when one planned and none composed', async () => {
    /*
     * The shape every abstention actually has, and the one the first version got wrong.
     *
     * `ask` sends no plan, so the server always runs the planner and always records it. On an
     * empty packet the composer is never called, so the list holds one `structured_extraction`
     * entry and no reasoning entry. Reading "no composing model" as "no model was asked" printed
     * a false sentence over every abstention the interface could produce.
     */
    const { fetch } = transport(json(answerBody({
      answer: {
        clauses: [{ text: 'I have no evidence for that.', type: 'meta', citations: [], value_refs: [] }],
      },
      citations: {},
      abstained: 'UNANSWERABLE_NOT_CAPTURED',
      execution: {
        prompt_version: 'selection-1',
        calls: [call({
          role: 'structured_extraction',
          requested_model: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
          served_model: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
          latency_ms: 5600,
        })],
      },
    })));
    const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask('was I in Antarctica?');

    expect(answer.provenance.composed).toBe('search');
    expect(answer.provenance.plannedBy).toBe('Qwen/Qwen3-235B-A22B-Instruct-2507');
    expect(answer.provenance.servedModel).toBeNull();
    expect(answer.provenance.latencyMs).toBe(5600);
  });

  it('offers one chip per photograph, and only for what a clause cited', async () => {
    /*
     * Two traps in one body, both of them shapes the server really sends.
     *
     * `citations` maps EVERY packet item, cited or not, so an answer citing one photograph
     * arrives with entries for the others. And `build_packet` mints a token per
     * (span, assertion) pair while the permalink comes from the span alone, so one photograph
     * carrying a caption and an entity link is several tokens with one permalink. Deduping by
     * token would show the same photograph twice; appending the whole map would offer a chip
     * for a photograph no clause points at.
     */
    const { fetch } = transport(
      json(answerBody({
        answer: {
          clauses: [{
            text: 'You were beside a waterfall.',
            type: 'historical',
            citations: ['TOKENAAAA1', 'TOKENAAAA2'],
            value_refs: [],
          }],
        },
        citations: {
          TOKENAAAA1: URI_A,
          TOKENAAAA2: URI_A,
          TOKENUNCITED: URI_B,
        },
      })),
      json(packetBody([packetItem('X', URI_A, SPAN_A), packetItem('Y', URI_B, SPAN_B)])),
    );
    const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask('where was I?');

    expect(answer.evidence).toHaveLength(1);
    expect(answer.evidence[0]!.handle).toBe(SPAN_A);
  });

  it('does not go looking for evidence when no clause cited any', async () => {
    const { fetch, seen } = transport(json(answerBody({
      answer: {
        clauses: [{ text: 'Some photographs match.', type: 'meta', citations: [], value_refs: [] }],
      },
    })));
    const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask('how many?');

    expect(answer.evidence).toHaveLength(0);
    expect(seen).toHaveLength(1);
  });

  it('reports an abstention with its code and with no model call', async () => {
    const { fetch } = transport(
      json(answerBody({
        answer: {
          clauses: [{ text: 'I have no evidence for that.', type: 'meta', citations: [], value_refs: [] }],
        },
        citations: {},
        abstained: 'UNANSWERABLE_NOT_CAPTURED',
        execution: { prompt_version: 'selection-1', calls: [] },
      })),
    );
    const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask('was I in Antarctica?');

    expect(answer.abstained).toBe('UNANSWERABLE_NOT_CAPTURED');
    expect(answer.provenance.composed).toBe('none');
    expect(answer.provenance.servedModel).toBeNull();
    // No citations, so no second request. Asking the packet route what an empty answer cited
    // would be a query with a known answer.
    expect(answer.evidence).toHaveLength(0);
  });

  it('does not say "no model was asked" when a model was asked and failed', async () => {
    /*
     * The planner-failure abstention, whose calls are usually NOT in the list: both attempts
     * raise inside the client before any result reaches the recorder. The empty list used to
     * fall through to `none`, which prints "No model was asked" over an answer two models had
     * just been asked to produce.
     */
    const { fetch, seen } = transport(json(answerBody({
      answer: {
        clauses: [{
          text: 'I could not turn that into a search of your photographs, so I have not looked.',
          type: 'meta', citations: [], value_refs: [],
        }],
      },
      plan: null,
      selection: null,
      citations: {},
      abstained: 'UNANSWERABLE_NOT_UNDERSTOOD',
      execution: { prompt_version: 'selection-2', calls: [], rejections: ['not a plan'] },
    })));
    const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask('exchange rate?');

    expect(answer.abstained).toBe('UNANSWERABLE_NOT_UNDERSTOOD');
    expect(answer.provenance.composed).toBe('unreadable');
    expect(answer.provenance.servedModel).toBeNull();
    // A null plan must not be posted to the packet route, and there is nothing cited anyway.
    expect(seen).toHaveLength(1);
    expect(answer.evidence).toHaveLength(0);
  });

  it('names the planner when the Selection it produced could not be run', async () => {
    const { fetch } = transport(json(answerBody({
      answer: {
        clauses: [{ text: 'I could not turn that into a search.', type: 'meta', citations: [], value_refs: [] }],
      },
      selection: null,
      citations: {},
      abstained: 'UNANSWERABLE_NOT_UNDERSTOOD',
      execution: {
        prompt_version: 'selection-2',
        rejections: ['unknown_reference'],
        calls: [call({
          role: 'structured_extraction',
          requested_model: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
          served_model: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
          latency_ms: 2100,
        })],
      },
    })));
    const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask('who was with me?');

    expect(answer.provenance.composed).toBe('unreadable');
    expect(answer.provenance.plannedBy).toBe('Qwen/Qwen3-235B-A22B-Instruct-2507');
    expect(answer.provenance.latencyMs).toBe(2100);
  });

  it('names the fallback when the primary was the one that was withdrawn', async () => {
    const { fetch } = transport(
      json(answerBody({
        execution: {
          prompt_version: 'selection-1',
          calls: [call({
            served_model: 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',
            requested_model: 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',
            used_fallback: true,
            attempts: 2,
          })],
        },
      })),
      json(packetBody([packetItem('X', URI_A, SPAN_A)])),
    );
    const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask('where was I?');

    expect(answer.provenance.usedFallback).toBe(true);
    expect(answer.provenance.servedModel).toBe('nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B');
  });

  it('reports an instance with no model as exactly that', async () => {
    const { fetch } = transport(json({
      code: 'http_503',
      detail: 'no model credential is configured on this instance.',
    }, 503));

    await expect(new CompanionAskClient({ ...WHERE, fetch }).ask('where was I?'))
      .rejects.toMatchObject({ kind: 'no_model' });
  });

  it('distinguishes a refusal, a lost session and a request that never arrived', async () => {
    const cases: [Response | Error, string][] = [
      [json({ code: 'invalid', detail: 'no' }, 400), 'refused'],
      [json({ code: 'unauthenticated', detail: 'no' }, 401), 'unauthenticated'],
      [new TypeError('network down'), 'unreachable'],
    ];
    for (const [outcome, kind] of cases) {
      const fetch = vi.fn(async () => {
        if (outcome instanceof Error) throw outcome;
        return outcome;
      }) as unknown as typeof globalThis.fetch;
      const failure = await new CompanionAskClient({ ...WHERE, fetch })
        .ask('where was I?')
        .catch((error: unknown) => error);
      expect(failure).toBeInstanceOf(AskUnavailable);
      expect((failure as AskUnavailable).kind).toBe(kind);
    }
  });

  it('gives every request its own deadline rather than one started at construction', async () => {
    // `AbortSignal.timeout` starts counting when it is CREATED. A signal built in the
    // constructor and reused would make the client work once and then stop: `main.ts` builds one
    // per mount, so every question asked more than three minutes into a session would abort
    // before leaving the browser. The symptom is asking quietly ceasing to work after a while,
    // which is exactly the kind of failure nobody attributes to a constructor.
    const signals: (AbortSignal | null | undefined)[] = [];
    const fetch = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      signals.push(init?.signal);
      return signals.length % 2 === 1 ? json(answerBody()) : json(packetBody([]));
    }) as unknown as typeof globalThis.fetch;

    const client = new CompanionAskClient({ ...WHERE, fetch });
    await client.ask('first');
    await client.ask('second');

    expect(signals).toHaveLength(4);
    expect(new Set(signals).size).toBe(4);
    for (const signal of signals) expect(signal?.aborted).toBe(false);
  });

  it('has a sentence for every abstention code the server can send', () => {
    /*
     * An unmapped key renders AS THE KEY, visibly, which is copy.ts's deliberate choice. That
     * makes this the guard that matters when a fourth code is added to the backend enum and the
     * table is not: the screen would read "abstention.UNANSWERABLE_NOT_UNDERSTOOD" to somebody
     * who asked a question.
     */
    const codes: readonly Abstention[] = [
      'UNANSWERABLE_NOT_CAPTURED',
      'UNANSWERABLE_AMBIGUOUS',
      'UNANSWERABLE_NOT_IN_MODALITY',
      'UNANSWERABLE_NOT_UNDERSTOOD',
    ];
    for (const code of codes) {
      const key = `abstention.${code}`;
      expect(say(key), `${key} has no sentence`).not.toBe(key);
    }
  });

  it('never sends the token in a query string', async () => {
    const { fetch, seen } = transport(json(answerBody()), json(packetBody([])));
    await new CompanionAskClient({ ...WHERE, fetch }).ask('where was I?');
    for (const request of seen) expect(request.url).not.toContain('not-a-real-token');
  });
});
