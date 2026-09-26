// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CompanionSession, SelectionOutcome, Turn } from '@exulanica/companion-runtime';
import type { GraphSnapshot } from '@exulanica/graph-client';

import {
  CompanionProposalClient,
  type CompanionAnswer,
  type CompanionProposal,
} from '../src/companion-ask-api.js';
import { answerToRemember } from '../src/companion-memory-api.js';
import { NAME_PREDICATE } from '../src/companion-names.js';
import { mountCompanion } from '../src/composition/companion.js';
import type { SessionState } from '../src/composition/session-state.js';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import type { ConfirmPanel } from '../src/ui/confirm.js';
import { fill, say } from '../src/ui/copy.js';
import { worldStyleProposalInbox, worldStyleProposalOutcomes } from '../src/world-style-proposals.js';

/**
 * An appearance proposal reads with names, as an answer does.
 *
 * The appearance route returns the request's placeholder map with the proposal, ids only, and the
 * page restores each name from the library it holds when the words are drawn, through the same
 * resolver an answer goes through. The map is written back with the proposal, so a reload draws
 * the same names, and a rename, a deletion, a withdrawn consent and a library not loaded are each
 * said the way they are for an answer.
 */

const PERSON = '0190a000-0000-7000-8000-00000000000a';
const PLACE = '0190a000-0000-7000-8000-00000000000b';
const NAMES = { '[person A]': PERSON, '[place A]': PLACE };
const DRAFTER = 'Qwen/Qwen3-235B-A22B-Instruct-2507';
const SPOKEN = 'The light will sit warmer where [person A] stands outside place A.';

interface Named {
  readonly entityId: string;
  readonly displayName: string | null;
  readonly assertions?: readonly unknown[];
}

function library(entities: readonly Named[], deleted: readonly string[] = []): GraphSnapshot {
  return {
    entities: entities.map((entity) => ({ mergedInto: null, assertions: [], ...entity })),
    deletedEntityIds: deleted,
  } as unknown as GraphSnapshot;
}

const NAMED = library([
  { entityId: PERSON, displayName: 'Maria Estrada' },
  { entityId: PLACE, displayName: 'Mireland Hall' },
]);

const call = (servedModel: string) => ({
  role: 'structured_extraction',
  requestedModel: DRAFTER,
  servedModel,
  usedFallback: false,
  attempts: 1,
  latencyMs: 1200,
  promptTokens: 900,
  completionTokens: 120,
  reasoningTokens: null,
  outcome: 'completed' as const,
  costBasis: 'known' as const,
});

const PROPOSAL: CompanionProposal = {
  utterance: 'make the light warmer where Maria stands outside the hall',
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
    spoken: SPOKEN,
  },
  refusal: null,
  promptVersion: 'proposal-3',
  calls: [call(DRAFTER), call(DRAFTER)],
  names: NAMES,
};

const REFUSED: CompanionProposal = {
  ...PROPOSAL,
  utterance: 'paint a mural of Maria on the hall',
  proposal: null,
  refusal: { code: 'not_in_catalogue', detail: 'a mural of [person A] on [place A]' },
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

function drawn(outcome: CompanionProposal, snapshot: GraphSnapshot | null) {
  const remembered: CompanionAnswer[] = [];
  // A surface that shows every proposal, as the appearance surface does when the world style
  // authority accepts one: the Companion speaks a proposal's own words only then.
  cleanups.push(worldStyleProposalInbox.subscribe((proposal) => {
    worldStyleProposalOutcomes.report({
      originReference: proposal.originReference ?? '',
      kind: 'previewed',
      detail: 'Waiting to be confirmed in Customize.',
    });
  }));
  const stageParent = document.createElement('div');
  document.body.append(stageParent);
  const state = { preferences: DEFAULT_PREFERENCES, snapshot } as unknown as SessionState;
  const mounted = mountCompanion({
    state,
    engine: {
      advance: () => ACKNOWLEDGE,
      say: () => ({ kind: 'refused', reasonKey: 'refused.couldNotParse' }) as SelectionOutcome,
      adoptPersistedMemory: () => undefined,
      lastAnswer: null,
    } as unknown as CompanionSession,
    evidence: { open: vi.fn() } as never,
    ask: async () => {
      throw new Error('a proposal never reaches the answer path');
    },
    proposeAppearance: async () => outcome,
    rememberAnswer: async (answer) => {
      remembered.push(answer);
    },
    stageParent,
    confirm: () => ({ show: vi.fn(), hide: vi.fn(), reportFailure: vi.fn() }) as unknown as
      ConfirmPanel,
    reflectShell: vi.fn(),
    onAnswered: vi.fn(),
    isSystemSurfaceOpen: () => false,
  });
  cleanups.push(() => mounted.dispose());
  return { mounted, remembered };
}

const settle = async (): Promise<void> => {
  for (let turn = 0; turn < 12; turn += 1) await Promise.resolve();
};

async function spoken(outcome: CompanionProposal, snapshot: GraphSnapshot | null) {
  const { mounted, remembered } = drawn(outcome, snapshot);
  mounted.summon();
  mounted.controller.say(outcome.utterance);
  await settle();
  return { text: mounted.panel.root.textContent ?? '', remembered };
}

const unresolved = (reason: string, thing: string): string =>
  fill(`name.unresolved.${reason}`, { thing: say(`name.class.${thing}`) });

describe('an appearance proposal, read with names', () => {
  beforeEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.replaceChildren();
    Object.defineProperty(document, 'pointerLockElement', { value: null, configurable: true });
    (document as unknown as { exitPointerLock: () => void }).exitPointerLock = () => undefined;
  });

  it('takes the route’s map with the proposal, ids only', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({
      classification: 'appearance',
      proposal: {
        profile: {
          profile_id: 'origin-landscape',
          profile_version: 1,
          parameters: {},
          modules: [],
          changed: [],
        },
        reference_ids: ['00000000-0000-0000-0000-000000000001'],
        model_id: DRAFTER,
        prompt_version: 'proposal-3',
        spoken: SPOKEN,
      },
      refusal: null,
      execution: { prompt_version: 'proposal-3', calls: [] },
      names: NAMES,
    }), { status: 200, headers: { 'content-type': 'application/json' } }));
    const client = new CompanionProposalClient({
      baseUrl: 'https://exulanica.test/api',
      token: 'not-a-real-token',
      worldId: 'world:personal:test',
      fetch: fetch as unknown as typeof globalThis.fetch,
    });

    const outcome = await client.propose('make it warmer');

    expect(outcome.names).toEqual(NAMES);
  });

  it('draws each placeholder, the bare one included, with the library’s name', async () => {
    const { text } = await spoken(PROPOSAL, NAMED);

    expect(text).toContain(
      'The light will sit warmer where Maria Estrada stands outside Mireland Hall.',
    );
    expect(text).not.toContain('[person A]');
    expect(text).not.toContain(unresolved('not_identified', 'person'));
  });

  it('draws the not_in_catalogue detail with names too', async () => {
    const { text } = await spoken(REFUSED, NAMED);

    expect(text).toContain('a mural of Maria Estrada on Mireland Hall');
  });

  it('writes the map back with the proposal, and no name', async () => {
    const { remembered } = await spoken(PROPOSAL, NAMED);

    expect(remembered).toHaveLength(1);
    const kept = answerToRemember(remembered[0]!);
    expect(kept.names).toEqual(NAMES);
    // The words are kept as the server wrote them, placeholders and all; the question is the
    // person's own sentence.
    expect(kept.answerText).toContain('[person A]');
    expect(kept.answerText).not.toContain('Maria');
    expect(kept.answerText).not.toContain('Mireland');
  });

  it('shows a rename, a deletion, a withdrawn consent and an unloaded library in words', async () => {
    const renamed = library([
      { entityId: PERSON, displayName: 'Maria Estrada-Lind' },
      { entityId: PLACE, displayName: 'Mireland Hall' },
    ]);
    expect((await spoken(PROPOSAL, renamed)).text).toContain(
      'where Maria Estrada-Lind stands outside Mireland Hall.',
    );

    const deleted = library([{ entityId: PLACE, displayName: 'Mireland Hall' }], [PERSON]);
    expect((await spoken(PROPOSAL, deleted)).text).toContain(
      `where ${unresolved('removed', 'person')} stands outside Mireland Hall.`,
    );

    const withdrawn = library([
      {
        entityId: PERSON,
        displayName: null,
        assertions: [{ predicateKey: NAME_PREDICATE, status: 'active', objectValue: null }],
      },
      { entityId: PLACE, displayName: 'Mireland Hall' },
    ]);
    expect((await spoken(PROPOSAL, withdrawn)).text).toContain(
      `where ${unresolved('withdrawn', 'person')} stands outside Mireland Hall.`,
    );

    expect((await spoken(PROPOSAL, null)).text).toContain(
      `where ${unresolved('not_loaded', 'person')} stands outside ` +
        `${unresolved('not_loaded', 'place')}.`,
    );
  });
});
