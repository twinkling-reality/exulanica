// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type {
  CompanionSession,
  PersistedAnswer,
  PersistedMemory,
  SelectionOutcome,
  Turn,
} from '@exulanica/companion-runtime';

import {
  COMPOSED_KINDS,
  type CompanionAnswer,
  type CompanionProposal,
  type Composed,
  type ModelCall,
} from '../src/companion-ask-api.js';
import {
  CompanionMemoryClient,
  MemoryUnavailable,
  PROPOSAL_OUTCOME_PROMPT,
  answerToRemember,
  rememberedAsAnswer,
} from '../src/companion-memory-api.js';
import { companionNames } from '../src/companion-names.js';
import { mountCompanion } from '../src/composition/companion.js';
import type { SessionState } from '../src/composition/session-state.js';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import { buildCompanionSpeech, provenanceParagraph } from '../src/ui/companion-speech.js';
import type { ConfirmPanel } from '../src/ui/confirm.js';
import { say } from '../src/ui/copy.js';
import { worldStyleProposalInbox, worldStyleProposalOutcomes } from '../src/world-style-proposals.js';

/**
 * A remembered answer is drawn again under the line it was first drawn under.
 *
 * The line under an answer says who wrote it, and it is drawn from the answer's kind. A row that
 * kept only the model identifiers was redrawn from them, so a proposed change came back after a
 * reload as "Answered by ..." and what became of a proposal as the line of a search. The row keeps
 * the kind now (migration 0112), with the fallback flag and the unanswered requests the same line
 * states, and a row kept before that derives its kind from what it does hold.
 */

/** The repository, from the web workspace vitest runs in, as the other page tests read it. */
const REPOSITORY = `${process.cwd()}/..`;
const WHERE = { baseUrl: 'https://exulanica.test/api', token: 'not-a-real-token' };

const CLASSIFIER = 'deepseek-ai/DeepSeek-V4-Flash-0731';
const DRAFTER = 'Qwen/Qwen3-235B-A22B-Instruct-2507';
const COMPOSER = 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B';

const call = (servedModel: string, latencyMs: number, over: Partial<ModelCall> = {}): ModelCall => ({
  role: 'structured_extraction',
  requestedModel: servedModel,
  servedModel,
  usedFallback: false,
  attempts: 1,
  latencyMs,
  promptTokens: 900,
  completionTokens: 120,
  reasoningTokens: null,
  outcome: 'completed',
  costBasis: 'known',
  ...over,
});

/** An answer as the surface draws it fresh, of one kind. */
function fresh(
  composed: Composed,
  provenance: Partial<CompanionAnswer['provenance']>,
  over: Partial<CompanionAnswer> = {},
): CompanionAnswer {
  return {
    question: `a question answered as ${composed}`,
    clauses: [{ text: `What was said, as ${composed}.`, type: 'meta', citations: [] }],
    text: `What was said, as ${composed}.`,
    abstained: null,
    deterministic: false,
    repaired: false,
    evidence: [],
    provenance: {
      composed,
      servedModel: null,
      plannedBy: null,
      latencyMs: 2400,
      usedFallback: false,
      ...provenance,
    },
    promptVersion: 'selection-9',
    calls: [],
    ...over,
  };
}

/**
 * One fresh answer of every kind a page draws fresh, each with what makes its line its own: the
 * model it names, a fallback, and requests that returned no answer, one of whose cost is unknown.
 * A correction is never drawn fresh (the corrections route writes it), so it is absent here and
 * read back from a row below.
 */
const FRESH: Readonly<Record<Exclude<Composed, 'corrected'>, CompanionAnswer>> = {
  model: fresh('model', { servedModel: COMPOSER, plannedBy: DRAFTER, usedFallback: true }, {
    calls: [
      call(DRAFTER, 1100),
      call(COMPOSER, 900, { outcome: 'timed_out', costBasis: 'unknown' }),
      call(COMPOSER, 1300, { usedFallback: true }),
    ],
  }),
  discarded: fresh('discarded', { servedModel: COMPOSER, plannedBy: DRAFTER }, { deterministic: true }),
  search: fresh('search', { plannedBy: DRAFTER }, { abstained: 'UNANSWERABLE_NOT_CAPTURED' }),
  unreadable: fresh('unreadable', { plannedBy: DRAFTER }, { abstained: 'UNANSWERABLE_NOT_UNDERSTOOD' }),
  none: fresh('none', {}),
  proposed: fresh('proposed', { servedModel: DRAFTER, plannedBy: CLASSIFIER }, {
    promptVersion: 'proposal-3',
    calls: [call(CLASSIFIER, 1200), call(DRAFTER, 2300)],
  }),
  refused: fresh('refused', { plannedBy: CLASSIFIER }, {
    promptVersion: 'proposal-3',
    calls: [call(CLASSIFIER, 1200), call(DRAFTER, 700, { outcome: 'failed', costBasis: 'known' })],
  }),
  undrafted: fresh('undrafted', { plannedBy: CLASSIFIER }, { promptVersion: 'proposal-3' }),
  unshown: fresh('unshown', { servedModel: DRAFTER, plannedBy: CLASSIFIER }, { promptVersion: 'proposal-3' }),
  outcome: fresh('outcome', { latencyMs: 0 }, { promptVersion: PROPOSAL_OUTCOME_PROMPT }),
};

/** The memory route, as far as keeping a row and serving it back: each field the body sent. */
function memoryServer() {
  const rows: Record<string, unknown>[] = [];
  const fetch = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      const row = {
        ...body,
        answer_id: `answer-${rows.length + 1}`,
        asked_at: new Date(Date.UTC(2026, 8, 26, 12, 0, rows.length)).toISOString(),
        origin: 'asked',
        supersedes: null,
        correction_note: null,
      };
      rows.push(row);
      return new Response(JSON.stringify(row), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      });
    }
    return new Response(JSON.stringify({ answers: [...rows].reverse(), escapes: [] }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  });
  return {
    client: new CompanionMemoryClient({ ...WHERE, fetch: fetch as unknown as typeof globalThis.fetch }),
    rows,
  };
}

/** The provenance paragraph the Companion draws under an answer, read off the drawn element. */
function drawnLine(answer: CompanionAnswer): string {
  const speech = buildCompanionSpeech({ speakerName: 'Companion', names: companionNames(() => null) });
  speech.renderAnswer(answer);
  return speech.root.querySelector('.companion-provenance')?.textContent ?? '';
}

/** A row as the route serves one, kept before the kind was kept: no kind, nothing unanswered. */
function keptBefore(over: Partial<PersistedAnswer>): PersistedAnswer {
  return {
    answerId: 'answer-old',
    askedAtMs: Date.UTC(2026, 8, 20, 9, 0, 0),
    question: 'asked before the kind was kept',
    answerText: 'What was said.',
    abstained: null,
    deterministic: false,
    repaired: false,
    servedModel: null,
    plannedBy: null,
    promptVersion: 'selection-3',
    latencyMs: 2400,
    origin: 'asked',
    supersedes: null,
    correctionNote: null,
    citations: [],
    names: {},
    composed: null,
    usedFallback: false,
    unansweredAttempts: 0,
    unansweredCostUnknown: false,
    ...over,
  };
}

describe('the kinds of answer the page draws', () => {
  it('are exactly the kinds the memory route keeps and serves', () => {
    const snapshot = JSON.parse(
      readFileSync(`${REPOSITORY}/tests/snapshots/api-openapi.json`, 'utf8'),
    ) as { components: { schemas: Record<string, { enum?: string[] }> } };
    const served = snapshot.components.schemas['AnswerComposed']?.enum ?? [];
    // A positive control: kinds the page is known to draw are found by the same reading.
    expect(served).toEqual(expect.arrayContaining(['proposed', 'unshown', 'outcome', 'corrected']));
    expect([...COMPOSED_KINDS].sort()).toEqual([...served].sort());
  });
});

describe('a remembered answer, drawn again after a reload', () => {
  it('has a fresh answer of every kind but a correction to go round the memory with', () => {
    expect(Object.keys(FRESH).sort()).toEqual(
      COMPOSED_KINDS.filter((kind) => kind !== 'corrected').sort(),
    );
  });

  it.each(Object.entries(FRESH))('is drawn under the line a fresh %s answer had', async (_kind, answer) => {
    const { client } = memoryServer();
    await client.rememberAnswer(answerToRemember(answer));
    const [row] = (await client.recent()).answers;
    if (row === undefined) throw new Error('the memory served no answer');
    const restored = rememberedAsAnswer(row);

    expect(restored.provenance).toEqual(answer.provenance);
    expect(provenanceParagraph(restored)).toBe(provenanceParagraph(answer));
    expect(drawnLine(restored)).toBe(drawnLine(answer));
    // And the line is the one its kind has, never the empty fallback of an unknown one.
    expect(drawnLine(answer)).not.toBe('');
  });

  it('says what went unanswered, as the fresh answer did, though it executed nothing', async () => {
    const { client } = memoryServer();
    await client.rememberAnswer(answerToRemember(FRESH.model));
    const [row] = (await client.recent()).answers;
    const restored = rememberedAsAnswer(row!);

    expect(restored.calls).toEqual([]);
    expect(provenanceParagraph(restored)).toContain(say('provenance.costUnknown'));
    expect(provenanceParagraph(restored)).toContain(`${COMPOSER}`);
    expect(provenanceParagraph(restored)).toContain('fallback');
  });

  it('draws a correction as the person\'s own words', () => {
    const correction = rememberedAsAnswer(
      keptBefore({ origin: 'correction', supersedes: 'answer-1', composed: 'corrected' }),
    );
    expect(drawnLine(correction)).toBe(say('provenance.corrected'));
  });

  it('refuses a kind this page does not draw, rather than drawing it under a guessed line', async () => {
    const fetch = vi.fn(async () => new Response(
      JSON.stringify({
        answers: [{
          answer_id: 'answer-1', asked_at: '2026-09-26T12:00:00Z', question: 'q', answer_text: 'a',
          abstained: null, deterministic: false, repaired: false, served_model: null,
          planned_by: null, prompt_version: 'selection-9', latency_ms: 1, origin: 'asked',
          supersedes: null, correction_note: null, citations: [], names: {},
          composed: 'answered_somehow', used_fallback: false, unanswered_attempts: 0,
          unanswered_cost_unknown: false,
        }],
        escapes: [],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ));
    const client = new CompanionMemoryClient({ ...WHERE, fetch: fetch as unknown as typeof globalThis.fetch });
    await expect(client.recent()).rejects.toMatchObject({ kind: 'unreadable' });
    await expect(client.recent()).rejects.toBeInstanceOf(MemoryUnavailable);
  });
});

describe('an answer kept before its kind was kept', () => {
  const drafterPrompt = (): string => {
    const source = readFileSync(`${REPOSITORY}/exulanica/selection/proposal.py`, 'utf8');
    const stated = /^PROMPT_VERSION: Final = "([^"]+)"$/m.exec(source);
    expect(stated, 'PROMPT_VERSION in exulanica/selection/proposal.py').not.toBeNull();
    return stated![1]!;
  };

  it.each<[string, Partial<PersistedAnswer>, Composed]>([
    ['a correction', { origin: 'correction', supersedes: 'answer-1' }, 'corrected'],
    ['what became of a proposal', { promptVersion: PROPOSAL_OUTCOME_PROMPT }, 'outcome'],
    ['a question no model could read', { abstained: 'UNANSWERABLE_NOT_UNDERSTOOD', plannedBy: DRAFTER }, 'unreadable'],
    ['an answer the search stood in for', { deterministic: true, servedModel: COMPOSER }, 'discarded'],
    ['a deterministic answer no model was asked for', { deterministic: true, latencyMs: 0 }, 'none'],
    ['a deterministic answer a model was asked for and did not write', { deterministic: true, plannedBy: DRAFTER }, 'discarded'],
    ['an answer a model wrote', { servedModel: COMPOSER, plannedBy: DRAFTER }, 'model'],
    ['an answer the search gave', { plannedBy: DRAFTER }, 'search'],
    ['an answer no model was asked for', {}, 'none'],
  ])('reads %s as the kind it was', (_what, row, kind) => {
    expect(rememberedAsAnswer(keptBefore(row)).provenance.composed).toBe(kind);
  });

  it('reads the drafter\'s rows by the version the drafter records', () => {
    const version = drafterPrompt();
    const staged = `The horizon will sit softer. ${say('proposal.staged')}`;
    expect(
      rememberedAsAnswer(keptBefore({ promptVersion: version, servedModel: DRAFTER, answerText: staged }))
        .provenance.composed,
    ).toBe('proposed');
  });

  it('reads a refusal made after a draft as a refusal, by the sentence it opens with', () => {
    const version = drafterPrompt();
    const refused = `${say('proposal.refused.not_in_catalogue')} a different typeface`;
    const undrafted = say('proposal.refused.not_drafted');
    // The drafter's name is on both, which is how a refusal after a draft was kept.
    expect(
      rememberedAsAnswer(keptBefore({ promptVersion: version, servedModel: DRAFTER, answerText: refused }))
        .provenance.composed,
    ).toBe('refused');
    expect(
      rememberedAsAnswer(keptBefore({ promptVersion: version, servedModel: DRAFTER, answerText: undrafted }))
        .provenance.composed,
    ).toBe('undrafted');
    expect(
      rememberedAsAnswer(keptBefore({ promptVersion: version, plannedBy: CLASSIFIER, answerText: 'Reworded.' }))
        .provenance.composed,
    ).toBe('refused');
  });

  it('draws a deterministic answer no model was asked for under the line it first had', () => {
    // A content plan answered from its rows, or a city selection with no place bridge: the server
    // answers these deterministically and calls no model, so the line says no model was asked.
    const restored = rememberedAsAnswer(keptBefore({ deterministic: true, latencyMs: 0 }));
    expect(drawnLine(restored)).toBe(say('provenance.none'));
  });

  it('claims no fallback and nothing unanswered, which those rows did not keep', () => {
    const restored = rememberedAsAnswer(keptBefore({ servedModel: COMPOSER }));
    expect(restored.provenance.usedFallback).toBe(false);
    expect(restored.unanswered).toEqual({ attempts: 0, costUnknown: false });
    expect(drawnLine(restored)).toBe(`Answered by ${COMPOSER} in 2.4 s.`);
  });
});

/** A request the Companion drew a change for. */
const PROPOSAL: CompanionProposal = {
  utterance: 'could the horizon be softer in here',
  classification: 'appearance',
  proposal: {
    profileId: 'origin-landscape',
    profileVersion: 1,
    parameters: { 'horizon-softness': 0.8 },
    modules: ['aeroheart-optics-v1'],
    changed: ['horizon-softness'],
    referenceIds: ['00000000-0000-0000-0000-000000000001'],
    modelId: DRAFTER,
    promptVersion: 'proposal-3',
    spoken: 'The horizon will sit softer, so the far edge reads as distance.',
  },
  refusal: null,
  promptVersion: 'proposal-3',
  calls: [call(CLASSIFIER, 1200), call(DRAFTER, 2300)],
};

const ACKNOWLEDGE = {
  turnId: 'turn-ack',
  intent: 'acknowledge',
  subjectEntityId: null,
  subjectAnchorId: null,
  utteranceKey: 'utterance.acknowledge',
  utterance: null,
  evidence: [],
  choiceSet: null,
  freeTextAllowed: true,
  escapes: [],
  stateVersion: 1,
} as unknown as Turn;

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length > 0) cleanups.pop()?.();
});

/** One page of the Companion over `client`: what it draws is kept, and it opens on `persisted`. */
function page(client: CompanionMemoryClient, persisted: PersistedMemory | null) {
  Object.defineProperty(document, 'pointerLockElement', { value: null, configurable: true });
  (document as unknown as { exitPointerLock: () => void }).exitPointerLock = () => undefined;
  const lastAnswer = persisted?.answers[0] ?? null;
  const mounted = mountCompanion({
    state: { preferences: DEFAULT_PREFERENCES } as unknown as SessionState,
    engine: {
      advance: () => ACKNOWLEDGE,
      say: () => ({ kind: 'refused', reasonKey: 'refused.couldNotParse' }) as SelectionOutcome,
      adoptPersistedMemory: () => undefined,
      lastAnswer,
    } as unknown as CompanionSession,
    persistedMemory: persisted,
    evidence: { open: vi.fn() } as never,
    ask: async () => {
      throw new Error('a request to change the world is not asked as a question');
    },
    proposeAppearance: async () => PROPOSAL,
    rememberAnswer: async (answer) => {
      await client.rememberAnswer(answerToRemember(answer));
    },
    confirm: () => ({ show: vi.fn(), hide: vi.fn(), reportFailure: vi.fn() }) as unknown as
      ConfirmPanel,
    reflectShell: vi.fn(),
    onAnswered: vi.fn(),
    isSystemSurfaceOpen: () => false,
  });
  cleanups.push(() => mounted.dispose());
  return mounted;
}

const settle = async (): Promise<void> => {
  for (let turn = 0; turn < 16; turn += 1) await Promise.resolve();
};

const line = (root: HTMLElement): string =>
  root.querySelector('.companion-provenance')?.textContent ?? '';

describe('a proposal the Companion drew, after a reload', () => {
  it.each<['previewed' | 'refused', string]>([
    ['previewed', 'Nothing is applied until you apply it.'],
    ['refused', 'It was never shown'],
  ])('is drawn under the line it had when the authority %s it', async (kind, words) => {
    const { client } = memoryServer();
    cleanups.push(worldStyleProposalInbox.subscribe((proposal) => {
      worldStyleProposalOutcomes.report({
        originReference: proposal.originReference ?? '',
        kind,
        detail: kind === 'refused' ? 'The world changed before this could be shown.' : '',
      });
    }));
    const first = page(client, null);
    first.summon();
    first.controller.say(PROPOSAL.utterance);
    await settle();
    const fresh = line(first.panel.root);
    expect(fresh).toContain(words);

    const reloaded = page(client, await client.recent());
    reloaded.summon();
    expect(reloaded.panel.root.getAttribute('data-remembered')).toBe('true');
    expect(line(reloaded.panel.root)).toBe(fresh);
  });
});
