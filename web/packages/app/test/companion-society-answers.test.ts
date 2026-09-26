// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CompanionSession, Turn } from '@exulanica/companion-runtime';

import type { CompanionAnswer } from '../src/companion-ask-api.js';
import { mountCompanion } from '../src/composition/companion.js';
import type { SessionState } from '../src/composition/session-state.js';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import type { ConfirmPanel } from '../src/ui/confirm.js';

/**
 * An answer about the world's simulated people, as the Companion mounts it: asked from the
 * inspector without the appearance classifier, drawn, and never written to the Companion's memory,
 * which holds photograph citations and saved names only. A photograph answer is still kept, the
 * control that makes the absence mean something. Harness as in companion-proposal-memory.test.ts.
 */

const ACKNOWLEDGE = {
  turnId: 'turn-ack', intent: 'acknowledge', subjectEntityId: null, subjectAnchorId: null,
  utteranceKey: 'utterance.acknowledge', utterance: null, evidence: [], choiceSet: null,
  freeTextAllowed: true, escapes: [], stateVersion: 1,
} as unknown as Turn;

const answer = (over: Partial<CompanionAnswer>): CompanionAnswer => ({
  question: 'Why are they there?',
  clauses: [{ text: '[inhabitant A]: Resting.', type: 'simulation', citations: ['T1'] }],
  text: '[inhabitant A]: Resting.',
  abstained: null,
  deterministic: false,
  repaired: false,
  evidence: [],
  provenance: { composed: 'none', servedModel: null, plannedBy: null, latencyMs: 0, usedFallback: false },
  promptVersion: 'selection-9',
  calls: [],
  ...over,
});

const SOCIETY = answer({ aboutSociety: true });
const PHOTOGRAPH = answer({
  question: 'which photographs?',
  clauses: [{ text: 'Nothing matched.', type: 'meta', citations: [] }],
  text: 'Nothing matched.',
});

function harness() {
  const remembered: CompanionAnswer[] = [];
  const classified: string[] = [];
  const stageParent = document.createElement('div');
  document.body.append(stageParent);
  const mounted = mountCompanion({
    state: { preferences: DEFAULT_PREFERENCES } as unknown as SessionState,
    engine: {
      advance: () => ACKNOWLEDGE,
      say: () => ({ kind: 'refused', reasonKey: 'refused.couldNotParse' }),
      adoptPersistedMemory: () => undefined,
      lastAnswer: null,
    } as unknown as CompanionSession,
    evidence: { open: vi.fn() } as never,
    ask: async () => PHOTOGRAPH,
    proposeAppearance: async (utterance) => {
      classified.push(utterance);
      return { utterance, classification: 'question', proposal: null, refusal: null, promptVersion: '', calls: [] };
    },
    rememberAnswer: async (kept) => {
      remembered.push(kept);
    },
    stageParent,
    confirm: () => ({ show: vi.fn(), hide: vi.fn(), reportFailure: vi.fn() }) as unknown as ConfirmPanel,
    reflectShell: vi.fn(),
    onAnswered: vi.fn(),
    isSystemSurfaceOpen: () => false,
  });
  return { mounted, remembered, classified };
}

const settle = async (): Promise<void> => {
  for (let turn = 0; turn < 12; turn += 1) await Promise.resolve();
};

describe('an answer about the world\'s people', () => {
  beforeEach(() => {
    document.body.replaceChildren();
    Object.defineProperty(document, 'pointerLockElement', { value: null, configurable: true });
    (document as unknown as { exitPointerLock: () => void }).exitPointerLock = () => undefined;
  });

  it('is asked from the inspector without the classifier, drawn, and not kept', async () => {
    const { mounted, remembered, classified } = harness();
    mounted.askAbout('Why are they there?', async () => SOCIETY);
    await settle();
    expect(mounted.controller.answer()).toBe(SOCIETY);
    expect(classified).toEqual([]);
    expect(remembered).toEqual([]);
    mounted.dispose();
  });

  it('leaves a photograph answer kept, as it always was', async () => {
    const { mounted, remembered } = harness();
    mounted.summon();
    mounted.controller.say('which photographs?');
    await settle();
    expect(remembered).toEqual([PHOTOGRAPH]);
    mounted.dispose();
  });
});
