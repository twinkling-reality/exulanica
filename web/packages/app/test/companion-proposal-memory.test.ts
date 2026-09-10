// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CompanionSession, SelectionOutcome, Turn } from '@exulanica/companion-runtime';

import type { CompanionAnswer, CompanionProposal } from '../src/companion-ask-api.js';
import { mountCompanion } from '../src/composition/companion.js';
import type { SessionState } from '../src/composition/session-state.js';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import type { ConfirmPanel } from '../src/ui/confirm.js';
import { say } from '../src/ui/copy.js';
import { worldStyleProposalInbox, worldStyleProposalOutcomes } from '../src/world-style-proposals.js';

/**
 * What the Companion does with a sentence that turns out to be a request, and what it keeps.
 *
 * Three things are under test and they are separate facts:
 *
 * *   a question still reaches the answer path, and the classifier can never be the reason one
 *     goes unanswered;
 * *   a request reaches the INBOX with model provenance on it, and never reaches a write;
 * *   what the Companion proposed and what became of it are both kept, through the write-back
 *     that already existed, so a reload does not forget that it offered to change somebody's
 *     world.
 *
 * The turn engine is a script. What it decides is not what this file is about: `askQuestion` is
 * reached only once the engine has said this free text is not an answer to an open question, and
 * that gate is tested where it lives, in `companion-controller.test.ts`.
 */

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

const ANSWER: CompanionAnswer = {
  question: 'who is in these photographs?',
  clauses: [{ text: 'Nobody has been named yet.', type: 'meta', citations: [] }],
  text: 'Nobody has been named yet.',
  abstained: 'UNANSWERABLE_NOT_CAPTURED',
  deterministic: false,
  repaired: false,
  evidence: [],
  provenance: {
    composed: 'model',
    servedModel: 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',
    plannedBy: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
    latencyMs: 3200,
    usedFallback: false,
  },
  promptVersion: 'selection-3',
  calls: [],
};

const DRAFTER = 'Qwen/Qwen3-235B-A22B-Instruct-2507';

const call = (latency: number) => ({
  role: 'structured_extraction',
  requestedModel: DRAFTER,
  servedModel: DRAFTER,
  usedFallback: false,
  attempts: 1,
  latencyMs: latency,
  promptTokens: 900,
  completionTokens: 120,
  reasoningTokens: null,
});

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
    promptVersion: 'proposal-1',
    spoken: 'The horizon will sit softer, so the far edge reads as distance.',
  },
  refusal: null,
  promptVersion: 'proposal-1',
  calls: [call(1200), call(2300)],
};

const REFUSED: CompanionProposal = {
  utterance: 'use a serif typeface everywhere',
  classification: 'appearance',
  proposal: null,
  refusal: { code: 'not_in_catalogue', detail: 'a different typeface for the menus' },
  promptVersion: 'proposal-1',
  calls: [call(1100), call(1900)],
};

const QUESTION: CompanionProposal = {
  utterance: 'who is in these photographs?',
  classification: 'question',
  proposal: null,
  refusal: null,
  promptVersion: '',
  calls: [],
};

/** A session that treats every free text as a question, which is the branch that reaches `ask`. */
function questioning(): CompanionSession {
  return {
    advance: () => ACKNOWLEDGE,
    say: () => ({ kind: 'refused', reasonKey: 'refused.couldNotParse' }) as SelectionOutcome,
    adoptPersistedMemory: () => undefined,
    lastAnswer: null,
  } as unknown as CompanionSession;
}

interface Harness {
  readonly mounted: ReturnType<typeof mountCompanion>;
  readonly asked: string[];
  readonly proposed: string[];
  readonly remembered: CompanionAnswer[];
  readonly received: unknown[];
}

const cleanups: (() => void)[] = [];

function harness(
  outcomes: readonly CompanionProposal[],
  over: { rememberFails?: boolean; noInbox?: boolean } = {},
): Harness {
  const asked: string[] = [];
  const proposed: string[] = [];
  const remembered: CompanionAnswer[] = [];
  const received: unknown[] = [];
  if (over.noInbox !== true) {
    cleanups.push(worldStyleProposalInbox.subscribe((proposal) => {
      received.push(proposal);
    }));
  }
  const stageParent = document.createElement('div');
  document.body.append(stageParent);
  const state = { preferences: DEFAULT_PREFERENCES } as unknown as SessionState;
  const mounted = mountCompanion({
    state,
    engine: questioning(),
    evidence: { open: vi.fn() } as never,
    ask: async (question) => {
      asked.push(question);
      return ANSWER;
    },
    proposeAppearance: async (utterance) => {
      proposed.push(utterance);
      const found = outcomes.find((outcome) => outcome.utterance === utterance);
      return found ?? { ...QUESTION, utterance };
    },
    rememberAnswer: async (answer) => {
      if (over.rememberFails === true) throw new Error('the library would not keep it');
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
  return { mounted, asked, proposed, remembered, received };
}

const settle = async (): Promise<void> => {
  for (let turn = 0; turn < 12; turn += 1) await Promise.resolve();
};

/**
 * happy-dom has no Pointer Lock, and `summon` releases a real one before it draws.
 *
 * Stubbed here rather than guarded in the source: that line is correct in a browser and the
 * browser is where it runs. `pointerLockElement` is defined as null because happy-dom leaves it
 * undefined, and `!== null` is true of undefined.
 */
function withoutPointerLock(): void {
  Object.defineProperty(document, 'pointerLockElement', { value: null, configurable: true });
  (document as unknown as { exitPointerLock: () => void }).exitPointerLock = () => undefined;
}

describe('a sentence that turns out to be a request to change the world', () => {
  beforeEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.replaceChildren();
    withoutPointerLock();
  });

  it('reaches the inbox with model provenance, and reaches no write', async () => {
    const { mounted, received, asked } = harness([PROPOSAL]);
    mounted.summon();

    mounted.controller.say(PROPOSAL.utterance);
    await settle();

    expect(received).toHaveLength(1);
    expect(received[0]).toMatchObject({
      origin: 'companion',
      scope: { kind: 'global' },
      profile: { profileId: 'origin-landscape', profileVersion: 1 },
      referenceIds: ['00000000-0000-0000-0000-000000000001'],
      modelId: DRAFTER,
      promptVersion: 'proposal-1',
    });
    // Minted per utterance, and non-empty, because the world authority refuses a companion
    // proposal that carries no origin reference.
    expect(
      (received[0] as { readonly originReference: string }).originReference,
    ).toMatch(/^companion-utterance:/);
    // Not a question, so the answer path was never asked.
    expect(asked).toEqual([]);
  });

  it('says what it proposed and that nothing has changed yet', async () => {
    const { mounted } = harness([PROPOSAL]);
    mounted.summon();

    mounted.controller.say(PROPOSAL.utterance);
    await settle();

    const spoken = mounted.panel.root.textContent ?? '';
    expect(spoken).toContain(PROPOSAL.proposal!.spoken);
    expect(spoken).toContain('Nothing has changed yet');
    // The model that drew it, out of the response body rather than off any manifest.
    expect(mounted.controller.answer()?.provenance.servedModel).toBe(DRAFTER);
    expect(mounted.controller.answer()?.promptVersion).toBe('proposal-1');
  });

  it('keeps the proposal through the write-back that already existed', async () => {
    const { mounted, remembered } = harness([PROPOSAL]);
    mounted.summon();

    mounted.controller.say(PROPOSAL.utterance);
    await settle();

    expect(remembered).toHaveLength(1);
    expect(remembered[0]?.question).toBe(PROPOSAL.utterance);
    expect(remembered[0]?.promptVersion).toBe('proposal-1');
    expect(remembered[0]?.text).toContain('The horizon will sit softer');
    // Nothing is claimed about the library, so nothing is cited and nothing is abstained from.
    expect(remembered[0]?.evidence).toEqual([]);
    expect(remembered[0]?.abstained).toBeNull();
  });

  it('keeps what became of it as a second remembered answer to the same sentence', async () => {
    const { mounted, remembered, received } = harness([PROPOSAL]);
    mounted.summon();
    mounted.controller.say(PROPOSAL.utterance);
    await settle();
    const originReference = (received[0] as { readonly originReference: string }).originReference;

    worldStyleProposalOutcomes.report({
      originReference,
      kind: 'accepted',
      detail: 'Applied as revision 1.',
    });
    await settle();

    expect(remembered).toHaveLength(2);
    expect(remembered[1]?.question).toBe(PROPOSAL.utterance);
    expect(remembered[1]?.text).toContain(say('proposal.outcome.accepted'));
    expect(remembered[1]?.text).toContain('Applied as revision 1.');
    // No model decided this. A person did, and a provenance line naming one would name the
    // wrong author.
    expect(remembered[1]?.provenance).toMatchObject({ composed: 'none', servedModel: null });
    expect(remembered[1]?.promptVersion).toBe('proposal-outcome');
  });

  it('keeps a discard too, because a proposal nobody took is still something that happened', async () => {
    const { mounted, remembered, received } = harness([PROPOSAL]);
    mounted.summon();
    mounted.controller.say(PROPOSAL.utterance);
    await settle();

    worldStyleProposalOutcomes.report({
      originReference: (received[0] as { readonly originReference: string }).originReference,
      kind: 'discarded',
      detail: 'The proposed design was not kept.',
    });
    await settle();

    expect(remembered).toHaveLength(2);
    expect(remembered[1]?.text).toContain(say('proposal.outcome.discarded'));
  });

  it('keeps nothing extra for a preview, which is a proposal nobody has decided about', async () => {
    const { mounted, remembered, received } = harness([PROPOSAL]);
    mounted.summon();
    mounted.controller.say(PROPOSAL.utterance);
    await settle();

    // Reported on every stale-base recovery. One row per recovery for a decision nobody has
    // made would be a memory of the authority's retries rather than of the conversation.
    for (let attempt = 0; attempt < 3; attempt += 1) {
      worldStyleProposalOutcomes.report({
        originReference: (received[0] as { readonly originReference: string }).originReference,
        kind: 'previewed',
        detail: 'Waiting to be confirmed in Customize.',
      });
    }
    await settle();

    expect(remembered).toHaveLength(1);
  });

  it('ignores an outcome for a proposal this Companion never made', async () => {
    const { mounted, remembered } = harness([PROPOSAL]);
    mounted.summon();
    mounted.controller.say(PROPOSAL.utterance);
    await settle();

    worldStyleProposalOutcomes.report({
      originReference: 'companion-utterance:somebody-elses',
      kind: 'accepted',
      detail: 'Applied as revision 9.',
    });
    await settle();

    expect(remembered).toHaveLength(1);
  });

  it('says an outcome that could not be kept, under the outcome rather than instead of it', async () => {
    const { mounted, received } = harness([PROPOSAL], { rememberFails: true });
    mounted.summon();
    mounted.controller.say(PROPOSAL.utterance);
    await settle();

    worldStyleProposalOutcomes.report({
      originReference: (received[0] as { readonly originReference: string }).originReference,
      kind: 'accepted',
      detail: 'Applied as revision 1.',
    });
    await settle();

    const spoken = mounted.panel.root.textContent ?? '';
    expect(spoken).toContain(say('memory.notKept.unreachable'));
    // And what the Companion said about the change is still on the screen.
    expect(spoken).toContain(PROPOSAL.proposal!.spoken);
  });
});

describe('a request the reviewed design cannot express', () => {
  beforeEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.replaceChildren();
    withoutPointerLock();
  });

  it('is refused out loud, in reviewed words, rather than silently', async () => {
    const { mounted, received, asked } = harness([REFUSED]);
    mounted.summon();

    mounted.controller.say(REFUSED.utterance);
    await settle();

    const spoken = mounted.panel.root.textContent ?? '';
    expect(spoken).toContain(say('proposal.refused.not_in_catalogue'));
    // The model's own account of what was asked for is shown under it, because it is more use
    // to the person than any general sentence this table could write.
    expect(spoken).toContain('a different typeface for the menus');
    expect(received).toEqual([]);
    expect(asked).toEqual([]);
  });

  it('does not attribute a reviewed sentence to the model that did not write it', async () => {
    const { mounted } = harness([REFUSED]);
    mounted.summon();

    mounted.controller.say(REFUSED.utterance);
    await settle();

    expect(mounted.controller.answer()?.provenance.composed).toBe('discarded');
  });

  it('keeps the refusal, so the Companion does not offer the same impossible thing twice', async () => {
    const { mounted, remembered } = harness([REFUSED]);
    mounted.summon();

    mounted.controller.say(REFUSED.utterance);
    await settle();

    expect(remembered).toHaveLength(1);
    expect(remembered[0]?.question).toBe(REFUSED.utterance);
    expect(remembered[0]?.text).toContain(say('proposal.refused.not_in_catalogue'));
  });

  it('says so when there is no surface to put a proposal in front of anybody', async () => {
    const { mounted, received } = harness([PROPOSAL], { noInbox: true });
    mounted.summon();

    mounted.controller.say(PROPOSAL.utterance);
    await settle();

    expect(received).toEqual([]);
    expect(mounted.panel.root.textContent ?? '').toContain(say('proposal.unavailable'));
  });
});

describe('a sentence that is still a question', () => {
  beforeEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.replaceChildren();
    withoutPointerLock();
  });

  it('reaches the answer path exactly as it did before this path existed', async () => {
    const { mounted, asked, received, proposed } = harness([QUESTION]);
    mounted.summon();

    mounted.controller.say(QUESTION.utterance);
    await settle();

    expect(proposed).toEqual([QUESTION.utterance]);
    expect(asked).toEqual([QUESTION.utterance]);
    expect(received).toEqual([]);
    expect(mounted.panel.root.textContent ?? '').toContain('Nobody has been named yet.');
  });

  it('goes straight to the answer path on a host that cannot propose at all', async () => {
    const asked: string[] = [];
    const stageParent = document.createElement('div');
    document.body.append(stageParent);
    const mounted = mountCompanion({
      state: { preferences: DEFAULT_PREFERENCES } as unknown as SessionState,
      engine: questioning(),
      evidence: { open: vi.fn() } as never,
      ask: async (question) => {
        asked.push(question);
        return ANSWER;
      },
      // No `proposeAppearance`. Absent means the host has not opted in, which is NOT the same as
      // a registered function that answers "question" for everything: that would make "this
      // build cannot propose" and "this sentence was a question" the same observation.
      stageParent,
      confirm: () => ({ show: vi.fn(), hide: vi.fn(), reportFailure: vi.fn() }) as unknown as
        ConfirmPanel,
      reflectShell: vi.fn(),
      onAnswered: vi.fn(),
      isSystemSurfaceOpen: () => false,
    });
    cleanups.push(() => mounted.dispose());
    mounted.summon();

    mounted.controller.say('who is in these photographs?');
    await settle();

    expect(asked).toEqual(['who is in these photographs?']);
  });
});
