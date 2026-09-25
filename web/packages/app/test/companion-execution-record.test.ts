// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { toApiError } from '@exulanica/graph-client';

import { AskUnavailable, CompanionAskClient } from '../src/companion-ask-api.js';
import { companionNames } from '../src/companion-names.js';
import { buildCompanionSpeech } from '../src/ui/companion-speech.js';
import { fill, say } from '../src/ui/copy.js';

/**
 * Every attempt a question paid for, as the page reads and shows it.
 *
 * The server's execution record lists each call that returned a result and each attempt that
 * timed out, failed or came back refused, with its outcome and whether its cost is known. The page
 * finds the composer by its role and outcome, never by its position, says how many attempts
 * returned nothing, and shows a failed question's record where an answer's provenance would be:
 * the problem body carries it as its `execution` member, which `ApiError` keeps.
 */

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const WHERE = { baseUrl: 'https://exulanica.test/api', token: 'not-a-real-token', worldId: null };
const COMPOSER = 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B';
const PLANNER = 'Qwen/Qwen3-235B-A22B-Instruct-2507';

const wireCall = (over: Record<string, unknown> = {}) => ({
  role: 'reasoning_cheap',
  requested_model: COMPOSER,
  served_model: COMPOSER,
  used_fallback: false,
  attempts: 1,
  latency_ms: 4000,
  prompt_tokens: 900,
  completion_tokens: 300,
  reasoning_tokens: 210,
  usd: '0.00010000',
  served_model_unavailable: null,
  outcome: 'completed',
  cost_basis: 'known',
  ...over,
});

const timedOut = wireCall({
  served_model: null,
  served_model_unavailable: 'result_not_returned',
  latency_ms: 60_000,
  prompt_tokens: null,
  completion_tokens: null,
  reasoning_tokens: null,
  usd: null,
  outcome: 'timed_out',
  cost_basis: 'unknown',
});

const answerBody = (calls: unknown[]) => ({
  answer: { clauses: [{ text: 'Nothing is named.', type: 'meta', citations: [], value_refs: [] }] },
  plan: { intent: 'captures', limit: 5 },
  selection: null,
  citations: {},
  abstained: null,
  deterministic: false,
  repaired: false,
  execution: { prompt_version: 'selection-8', calls },
});

const PROBLEM = {
  code: 'model_refused',
  detail: 'the read timed out',
  execution: {
    prompt_version: 'selection-8',
    calls: [wireCall({ role: 'structured_extraction', requested_model: PLANNER, served_model: PLANNER, latency_ms: 2000 }), timedOut],
    rejections: [],
  },
};

function client(response: Response) {
  const fetch = vi.fn(async () => response);
  return new CompanionAskClient({ ...WHERE, fetch: fetch as unknown as typeof globalThis.fetch });
}

describe('a problem body that has more to say', () => {
  it('keeps every member beside code and detail', async () => {
    const error = await toApiError(json(PROBLEM, 502));

    expect(error.code).toBe('model_refused');
    expect(error.extensions['execution']).toEqual(PROBLEM.execution);
    expect(Object.keys(error.extensions)).toEqual(['execution']);
  });
});

describe('a question that failed after paying for attempts', () => {
  it('carries the execution record on the failure', async () => {
    const failure = await client(json(PROBLEM, 502)).ask('where was I?').catch((error) => error);

    expect(failure).toBeInstanceOf(AskUnavailable);
    const execution = (failure as AskUnavailable).execution;
    expect(execution?.promptVersion).toBe('selection-8');
    expect(execution?.calls.map((call) => [call.role, call.outcome, call.costBasis])).toEqual([
      ['structured_extraction', 'completed', 'known'],
      ['reasoning_cheap', 'timed_out', 'unknown'],
    ]);
  });

  it('shows it where an answer shows who wrote it', async () => {
    const failure = (await client(json(PROBLEM, 502)).ask('where was I?').catch(
      (error) => error,
    )) as AskUnavailable;
    const speech = buildCompanionSpeech({ speakerName: 'Companion', names: companionNames(() => null) });

    speech.reportAskFailure(failure);

    const provenance = speech.root.querySelector('.companion-provenance')?.textContent ?? '';
    expect(provenance).toBe(
      `${fill('provenance.failed.timed_out', { model: COMPOSER, duration: '62.0 s' })} `
        + say('provenance.costUnknown'),
    );
  });

  it('shows no line for a failure the server sent no record with', () => {
    const speech = buildCompanionSpeech({ speakerName: 'Companion', names: companionNames(() => null) });

    speech.reportAskFailure(new AskUnavailable('unreachable', 'the network is down'));

    expect(speech.root.querySelector('.companion-provenance')).toBeNull();
  });
});

describe('an answer whose record holds attempts that returned nothing', () => {
  it('names the composer that answered, found by role and outcome rather than position', async () => {
    const answer = await client(json(answerBody([
      wireCall({ role: 'structured_extraction', requested_model: PLANNER, served_model: PLANNER }),
      wireCall(),
      // An attempt after the one that answered, which a positional reading would name.
      wireCall({ outcome: 'reply_refused', served_model: null, cost_basis: 'known' }),
    ]))).ask('where was I?');

    expect(answer.provenance.composed).toBe('model');
    expect(answer.provenance.servedModel).toBe(COMPOSER);
    expect(answer.provenance.plannedBy).toBe(PLANNER);
  });

  it('says how many returned nothing, and that what they cost is not known', async () => {
    const answer = await client(json(answerBody([timedOut, wireCall()]))).ask('where was I?');
    const speech = buildCompanionSpeech({ speakerName: 'Companion', names: companionNames(() => null) });

    speech.renderAnswer(answer);

    const provenance = speech.root.querySelector('.companion-provenance')?.textContent ?? '';
    expect(provenance).toContain(fill('provenance.model', { model: COMPOSER, duration: '64.0 s' }));
    expect(provenance).toContain(fill('provenance.unanswered', { count: '1' }));
    expect(provenance).toContain(say('provenance.costUnknown'));
  });

  it('reads an outcome it has no words for as an attempt that returned nothing', async () => {
    const answer = await client(json(answerBody([
      wireCall(),
      wireCall({ outcome: 'lost_in_space', cost_basis: 'galactic' }),
    ]))).ask('where was I?');

    expect(answer.calls.map((call) => [call.outcome, call.costBasis])).toEqual([
      ['completed', 'known'],
      ['failed', 'unknown'],
    ]);
  });
});

describe('a failure whose record holds no failed attempt, or one never sent', () => {
  it('names the models that read the question before something else stopped it', () => {
    const speech = buildCompanionSpeech({ speakerName: 'Companion', names: companionNames(() => null) });
    const planner = {
      role: 'structured_extraction', requestedModel: PLANNER, servedModel: PLANNER, usedFallback: false,
      attempts: 1, latencyMs: 2000, promptTokens: 400, completionTokens: 20, reasoningTokens: null,
      outcome: 'completed' as const, costBasis: 'known' as const,
    };

    speech.reportAskFailure(new AskUnavailable('refused', 'budget_exceeded: ceiling', {
      promptVersion: 'selection-8', calls: [planner],
    }));

    expect(speech.root.querySelector('.companion-provenance')?.textContent).toBe(
      fill('provenance.failed.afterAnswers', { models: PLANNER, duration: '2.0 s' }),
    );
  });

  it('never says a model was asked when the request was never sent', () => {
    const speech = buildCompanionSpeech({ speakerName: 'Companion', names: companionNames(() => null) });
    const unsent = {
      role: 'reasoning_cheap', requestedModel: COMPOSER, servedModel: null, usedFallback: false,
      attempts: 1, latencyMs: 5, promptTokens: null, completionTokens: null, reasoningTokens: null,
      outcome: 'failed' as const, costBasis: 'not_sent' as const,
    };

    speech.reportAskFailure(new AskUnavailable('refused', 'model_refused: unreachable', {
      promptVersion: 'selection-8', calls: [unsent],
    }));

    const line = speech.root.querySelector('.companion-provenance')?.textContent ?? '';
    expect(line).toBe(fill('provenance.failed.not_sent', { model: COMPOSER, duration: '5 ms' }));
    expect(line).not.toContain('was asked');
  });
});
