// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CompanionSession, SelectionOutcome, Turn } from '@exulanica/companion-runtime';

import type { CompanionAnswer, CompanionProposal } from '../src/companion-ask-api.js';
import { mountCompanion } from '../src/composition/companion.js';
import type { SessionState } from '../src/composition/session-state.js';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import type { ConfirmPanel } from '../src/ui/confirm.js';
import { say } from '../src/ui/copy.js';

/**
 * A model failure is not said as a limit of the reviewed design.
 *
 * Measured in the rehearsal of the personal path: every draft of "Make the horizon softer and the
 * colours warmer" came back as a reply the server could not read, the server refused it
 * `not_drafted`, and the page said "The reviewed design has no way to make that change." The
 * design could make it. That sentence stays for a request the design cannot express, and an
 * unreadable reply gets its own words.
 */

const DESIGN_LIMIT = 'The reviewed design has no way to make that change.';
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
  requestedModel: CLASSIFIER,
  servedModel: CLASSIFIER,
  usedFallback: false,
  attempts: 1,
  latencyMs: 1100,
  promptTokens: 400,
  completionTokens: 8,
  reasoningTokens: null,
};

function refused(utterance: string, code: 'not_drafted' | 'not_in_catalogue'): CompanionProposal {
  return {
    utterance,
    classification: 'appearance',
    proposal: null,
    refusal: { code, detail: 'the server said why' },
    promptVersion: 'proposal-3',
    calls: code === 'not_drafted' ? [classified] : [classified, { ...classified, latencyMs: 1900 }],
  };
}

const UNREADABLE = refused('Make the horizon softer and the colours warmer', 'not_drafted');
const IMPOSSIBLE = refused('use a serif typeface everywhere', 'not_in_catalogue');

function questioning(): CompanionSession {
  return {
    advance: () => ACKNOWLEDGE,
    say: () => ({ kind: 'refused', reasonKey: 'refused.couldNotParse' }) as SelectionOutcome,
    adoptPersistedMemory: () => undefined,
    lastAnswer: null,
  } as unknown as CompanionSession;
}

const cleanups: (() => void)[] = [];

function mounted(outcomes: readonly CompanionProposal[]) {
  const stageParent = document.createElement('div');
  document.body.append(stageParent);
  const companion = mountCompanion({
    state: { preferences: DEFAULT_PREFERENCES } as unknown as SessionState,
    engine: questioning(),
    evidence: { open: vi.fn() } as never,
    ask: async () => {
      throw new Error('an appearance request never reaches the answer path');
    },
    proposeAppearance: async (utterance) => {
      const found = outcomes.find((outcome) => outcome.utterance === utterance);
      if (found === undefined) throw new Error(`no outcome scripted for ${utterance}`);
      return found;
    },
    rememberAnswer: async (_answer: CompanionAnswer) => undefined,
    stageParent,
    confirm: () => ({ show: vi.fn(), hide: vi.fn(), reportFailure: vi.fn() }) as unknown as
      ConfirmPanel,
    reflectShell: vi.fn(),
    onAnswered: vi.fn(),
    isSystemSurfaceOpen: () => false,
  });
  cleanups.push(() => companion.dispose());
  return companion;
}

const settle = async (): Promise<void> => {
  for (let turn = 0; turn < 12; turn += 1) await Promise.resolve();
};

async function spokenFor(outcome: CompanionProposal) {
  const companion = mounted([outcome]);
  companion.summon();
  companion.controller.say(outcome.utterance);
  await settle();
  return {
    spoken: companion.panel.root.textContent ?? '',
    composed: companion.controller.answer()?.provenance.composed,
  };
}

describe('the words after an appearance request that produced no proposal', () => {
  beforeEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.replaceChildren();
    Object.defineProperty(document, 'pointerLockElement', { value: null, configurable: true });
    (document as unknown as { exitPointerLock: () => void }).exitPointerLock = () => undefined;
  });

  it('say a reply could not be read, and claim no limit of the design, when nothing was drafted', async () => {
    const { spoken, composed } = await spokenFor(UNREADABLE);
    expect(composed).toBe('undrafted');
    expect(spoken).toContain(say('proposal.refused.not_drafted'));
    expect(spoken).toContain(say('provenance.undrafted'));
    expect(spoken).not.toContain(DESIGN_LIMIT);
  });

  it('still say the design has no way to make a change the catalogue cannot express', async () => {
    const { spoken, composed } = await spokenFor(IMPOSSIBLE);
    expect(composed).toBe('refused');
    expect(spoken).toContain(DESIGN_LIMIT);
    expect(spoken).not.toContain(say('provenance.undrafted'));
  });
});
