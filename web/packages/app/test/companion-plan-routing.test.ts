// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CompanionSession, SelectionOutcome, Turn } from '@exulanica/companion-runtime';

import type { CompanionAnswer, CompanionProposal } from '../src/companion-ask-api.js';
import { mountCompanion } from '../src/composition/companion.js';
import type { PlanRouting } from '../src/composition/companion-plan.js';
import type { SessionState } from '../src/composition/session-state.js';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import type { ConfirmPanel } from '../src/ui/confirm.js';

/**
 * With a world open the Companion asks the plan route first (composition/companion-plan.ts), and
 * each answer it gives sends the sentence on the one path it names: a question to the answer path,
 * an appearance proposal to Design without a second draft, a plan or refusal said, and anything
 * the route could not answer down the path it took before.
 */

const CLASSIFIER = 'Qwen/Qwen3-235B-A22B-Instruct-2507';

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

/** The classifier's call, which is the only one a not-drafted outcome carries. */
const classified = {
  role: 'structured_extraction',
  requestedModel: CLASSIFIER, requestedModelName: CLASSIFIER,
  servedModel: CLASSIFIER, servedModelName: CLASSIFIER,
  usedFallback: false,
  attempts: 1,
  latencyMs: 1100,
  promptTokens: 400,
  completionTokens: 8,
  reasoningTokens: null,
  outcome: 'completed' as const,
  costBasis: 'known' as const,
};


function questioning(): CompanionSession {
  return {
    advance: () => ACKNOWLEDGE,
    say: () => ({ kind: 'refused', reasonKey: 'refused.couldNotParse' }) as SelectionOutcome,
    adoptPersistedMemory: () => undefined,
    lastAnswer: null,
  } as unknown as CompanionSession;
}

const ANSWERED: CompanionAnswer = {
  question: 'q', clauses: [{ text: 'An answer from the library.', type: 'meta', citations: [] }],
  text: 'An answer from the library.', abstained: null, deterministic: false, repaired: false, evidence: [],
  content: { rows: [], placeConfirmed: false, totalMatched: 0 },
} as unknown as CompanionAnswer;

const NOT_A_PROPOSAL: CompanionProposal = {
  utterance: 'u', classification: 'question', proposal: null, refusal: null, promptVersion: '', calls: [],
};

const cleanups: (() => void)[] = [];

function mounted(routing: PlanRouting) {
  const stageParent = document.createElement('div');
  document.body.append(stageParent);
  const ask = vi.fn(async () => ANSWERED);
  const proposeAppearance = vi.fn(async () => NOT_A_PROPOSAL);
  const planActions = vi.fn(async () => routing);
  const rememberAnswer = vi.fn(async () => undefined);
  const companion = mountCompanion({
    state: { preferences: DEFAULT_PREFERENCES } as unknown as SessionState,
    engine: questioning(),
    evidence: { open: vi.fn() } as never,
    ask,
    proposeAppearance,
    planActions,
    rememberAnswer,
    stageParent,
    confirm: () => ({ show: vi.fn(), hide: vi.fn(), reportFailure: vi.fn() }) as unknown as ConfirmPanel,
    reflectShell: vi.fn(),
    onAnswered: vi.fn(),
    isSystemSurfaceOpen: () => false,
  });
  cleanups.push(() => companion.dispose());
  return { companion, ask, proposeAppearance, planActions, rememberAnswer };
}

const settle = async (): Promise<void> => {
  for (let turn = 0; turn < 12; turn += 1) await Promise.resolve();
};

async function said(routing: PlanRouting, utterance = 'put a bench here') {
  const m = mounted(routing);
  m.companion.summon();
  m.companion.controller.say(utterance);
  await settle();
  return { ...m, spoken: m.companion.panel.root.textContent ?? '' };
}

describe('the plan route first', () => {
  beforeEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.replaceChildren();
    Object.defineProperty(document, 'pointerLockElement', { value: null, configurable: true });
    (document as unknown as { exitPointerLock: () => void }).exitPointerLock = () => undefined;
  });

  it('sends a question on to the answer path, and nothing to the appearance route', async () => {
    const m = await said({ route: 'question' }, 'who lives here?');
    expect(m.planActions).toHaveBeenCalledWith('who lives here?');
    expect(m.ask).toHaveBeenCalledOnce();
    expect(m.proposeAppearance).not.toHaveBeenCalled();
  });

  it('says a plan it showed, with the model it asked, and asks nothing else', async () => {
    const m = await said({ route: 'answer', sentences: ['Here is what I would do. Check it, then confirm.'],
      refused: false, calls: [classified], promptVersion: 'companion-actions/v3' });
    expect(m.spoken).toContain('Here is what I would do. Check it, then confirm.');
    // The classifier that read the sentence is reported as the model that planned the answer.
    expect(m.companion.controller.answer()?.provenance.plannedBy).toBe(CLASSIFIER);
    expect(m.companion.controller.answer()?.calls).toHaveLength(1);
    // Its own line, not the appearance proposal's, and it is not kept as a remembered answer.
    expect(m.spoken).toContain('read that in');
    expect(m.spoken).toContain('Nothing changes unless you confirm a plan.');
    expect(m.spoken).not.toContain('until you apply it');
    expect(m.rememberAnswer).not.toHaveBeenCalled();
    expect(m.ask).not.toHaveBeenCalled();
    expect(m.proposeAppearance).not.toHaveBeenCalled();
  });

  it('takes the path it took before when the route could not answer', async () => {
    const m = await said({ route: 'fallback' }, 'make it warmer');
    expect(m.proposeAppearance).toHaveBeenCalledWith('make it warmer');
    // The appearance route called it a question, so it is answered, as before.
    expect(m.ask).toHaveBeenCalledOnce();
  });

  it('reads an appearance proposal from the plan without asking the appearance route', async () => {
    const m = await said({ route: 'appearance', proposal: { ...NOT_A_PROPOSAL, utterance: 'make it warmer',
      classification: 'appearance', refusal: { code: 'not_drafted', detail: 'no' }, calls: [classified] } }, 'make it warmer');
    expect(m.proposeAppearance).not.toHaveBeenCalled();
    expect(m.ask).not.toHaveBeenCalled();
  });
});
