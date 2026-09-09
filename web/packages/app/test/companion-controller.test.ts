// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import type {
  CompanionSession,
  ConfirmationSummary,
  SelectionOutcome,
  Turn,
} from '@exulanica/companion-runtime';

import { AskUnavailable, type CompanionAnswer } from '../src/companion-ask-api.js';
import { createCompanionController } from '../src/companion.js';
import { buildCompanionEncounter } from '../src/ui/companion-encounter.js';

const ANSWER: CompanionAnswer = {
  question: 'when were these taken?',
  clauses: [
    { text: 'The earliest of them is from that winter.', type: 'historical', citations: ['TOKENAAAA1'] },
  ],
  text: 'The earliest of them is from that winter.',
  abstained: null,
  deterministic: false,
  repaired: false,
  evidence: [
    {
      token: 'TOKENAAAA1',
      uri: 'exulanica://blob/ni:///sha-256;aaaa',
      handle: 'span-a',
      captureId: 'capture-a',
      capturedAt: null,
    },
    // The packet located neither the span nor the capture for this one, so it renders as a
    // chip that cannot open and it is not something a stored answer may claim to have quoted.
    {
      token: 'TOKENBBBB2',
      uri: 'exulanica://blob/ni:///sha-256;bbbb',
      handle: null,
      captureId: null,
      capturedAt: null,
    },
  ],
  provenance: {
    composed: 'model',
    servedModel: 'nvidia/Nemotron-3_5-Lightning',
    plannedBy: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
    latencyMs: 12_400,
    usedFallback: false,
  },
  promptVersion: 'selection-1',
  calls: [],
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

/** A session that refuses free text for the named reason and can do nothing else. */
function refusing(reasonKey: string, turn: Turn = ACKNOWLEDGE): CompanionSession {
  return {
    advance: () => turn,
    say: () => ({ kind: 'refused', reasonKey }) as SelectionOutcome,
  } as unknown as CompanionSession;
}

describe('Companion confirmation handoff', () => {
  it('passes the selected answer wording instead of the question', () => {
    const turn = {
      turnId: 'turn-1',
      intent: 'confirm_continuity',
      subjectEntityId: 'entity-1',
      subjectAnchorId: 'anchor-1',
      utteranceKey: 'utterance.confirmContinuity',
      utterance: 'These two moments may show the same person. Do they?',
      evidence: [],
      choiceSet: {
        mode: 'single',
        submitRequired: false,
        options: [{
          optionId: 'same-person',
          kind: 'exclusive',
          textKey: 'option.yesSamePerson',
          phrasing: 'Yes, the same person',
          available: true,
          unavailableReasonKey: null,
          tier: 2,
          draft: null,
          escape: null,
        }],
      },
      freeTextAllowed: true,
      escapes: [],
      stateVersion: 1,
    } as unknown as Turn;
    const outcome = {
      kind: 'awaiting_confirmation',
      proposal: { proposalId: 'proposal-1' },
      confirmation: {},
    } as unknown as SelectionOutcome;
    const companion = {
      advance: () => turn,
      select: () => outcome,
    } as unknown as CompanionSession;
    let answer = '';
    const controller = createCompanionController({
      companion,
      onAwaitingConfirmation: (_proposalId, _summary: ConfirmationSummary, utterance) => {
        answer = utterance;
      },
    });

    controller.summon(0);
    controller.select('same-person');

    expect(answer).toBe('Yes, the same person');
    expect(answer).not.toBe(turn.utterance);
  });
});

/**
 * The question branch, which is a READ and has to stay one.
 *
 * `interaction-model.md` 4.3 fixes that free text "is parsed into the same update proposal draft
 * that a choice would produce and goes through the IDENTICAL confirmation flow". That is still
 * true of every utterance the parser can turn into a change. These tests are about the ones it
 * cannot, which were previously answered with "I could not tell what that meant" while
 * `POST /selection/ask` sat there able to answer them.
 */
describe('free text that turns out to be a question', () => {
  it('routes an unparseable utterance to the answer path instead of refusing', async () => {
    const askQuestion = vi.fn(async () => ANSWER);
    const controller = createCompanionController({
      companion: refusing('refused.couldNotParse'),
      onAwaitingConfirmation: () => expect.unreachable('an answer must not stage a proposal'),
      askQuestion,
    });
    const panel = buildCompanionEncounter({ onSelect: () => undefined, onSubmit: () => undefined, onSay: () => undefined, onEvidence: () => undefined });
    controller.attach(panel);
    panel.setState('open');

    controller.summon(0);
    controller.say('when were these taken?');
    await vi.waitFor(() => expect(controller.answer()).not.toBeNull());

    expect(askQuestion).toHaveBeenCalledWith('when were these taken?');
    expect(panel.root.textContent).toContain('The earliest of them is from that winter.');
  });

  it('routes the refusal a library with no named entities actually produces', async () => {
    // `generateTurn` returns the acknowledge turn when nothing is open, its `subjectEntityId` is
    // null, and `session.say` refuses with `refused.noSubject` BEFORE the parser runs. That is
    // the reference workspace exactly: zero entities and zero captions. Routing only
    // `couldNotParse` would leave the answer path unreachable on the library it exists for.
    const askQuestion = vi.fn(async () => ANSWER);
    const controller = createCompanionController({
      companion: refusing('refused.noSubject'),
      onAwaitingConfirmation: () => expect.unreachable('an answer must not stage a proposal'),
      askQuestion,
    });
    controller.summon(0);
    controller.say('how many photographs are there?');
    await vi.waitFor(() => expect(askQuestion).toHaveBeenCalledTimes(1));
  });

  it('leaves every other refusal a refusal', () => {
    const askQuestion = vi.fn(async () => ANSWER);
    for (const reasonKey of ['refused.noTurn', 'refused.useSubmit', 'refused.tierNotOfferableHere']) {
      const controller = createCompanionController({
        companion: refusing(reasonKey),
        onAwaitingConfirmation: () => undefined,
        askQuestion,
      });
      controller.summon(0);
      controller.say('anything');
    }
    expect(askQuestion).not.toHaveBeenCalled();
  });

  it('asks nothing at all when no answer path was injected', () => {
    const controller = createCompanionController({
      companion: refusing('refused.couldNotParse'),
      onAwaitingConfirmation: () => undefined,
    });
    const panel = buildCompanionEncounter({ onSelect: () => undefined, onSubmit: () => undefined, onSay: () => undefined, onEvidence: () => undefined });
    controller.attach(panel);
    panel.setState('open');
    controller.summon(0);
    controller.say('when were these taken?');

    // The old behaviour, unchanged, on an instance with no answer route.
    expect(panel.root.textContent).toContain('I could not tell what that meant.');
  });

  it('reports the presence as working after the caller reflects, not during it', async () => {
    /*
     * The ordering that cost eighteen seconds of a still avatar in the running app.
     *
     * `main.ts` calls `say(text)` and then `reflectTurnState(current())` on the very next line.
     * The open turn is `acknowledge`, which sets the presence to `resting`. Reporting `working`
     * synchronously inside `say` put it there first and the host put it straight back.
     *
     * `host` below is that call site: it does what main.ts does, in the same order.
     */
    let resolve = (_: CompanionAnswer) => undefined as void;
    const working: boolean[] = [];
    const controller = createCompanionController({
      companion: refusing('refused.couldNotParse'),
      onAwaitingConfirmation: () => undefined,
      askQuestion: () => new Promise<CompanionAnswer>((r) => { resolve = r; }),
      onWorking: (state) => { working.push(state); },
    });
    controller.summon(0);

    const host = (text: string): void => {
      controller.say(text);
      working.push(false); // stands in for reflectTurnState putting the presence back
    };
    host('when were these taken?');
    expect(working).toEqual([false]);

    await vi.waitFor(() => expect(working).toEqual([false, true]));

    resolve(ANSWER);
    await vi.waitFor(() => expect(working).toEqual([false, true, false]));
  });

  it('says a failed question failed rather than saying something else', async () => {
    const controller = createCompanionController({
      companion: refusing('refused.couldNotParse'),
      onAwaitingConfirmation: () => undefined,
      askQuestion: async () => {
        throw new AskUnavailable('no_model', 'no model credential is configured on this instance.');
      },
    });
    const panel = buildCompanionEncounter({ onSelect: () => undefined, onSubmit: () => undefined, onSay: () => undefined, onEvidence: () => undefined });
    controller.attach(panel);
    panel.setState('open');
    controller.summon(0);
    controller.say('when were these taken?');

    await vi.waitFor(() => {
      expect(panel.root.textContent).toContain('running without a model');
    });
    // The server's own sentence, alongside the kind. Not replaced by it.
    expect(panel.root.textContent).toContain('no model credential is configured on this instance.');
    expect(controller.answer()).toBeNull();
  });

  it('points E and the chips at the answer\'s citations while an answer is showing', async () => {
    const controller = createCompanionController({
      companion: refusing('refused.couldNotParse'),
      onAwaitingConfirmation: () => undefined,
      askQuestion: async () => ANSWER,
    });
    const opened: (string | null)[] = [];
    const panel = buildCompanionEncounter({
      onSelect: () => undefined,
      onSubmit: () => undefined,
      onSay: () => undefined,
      onEvidence: (index) => opened.push(controller.evidenceAt(index)),
    });
    controller.attach(panel);
    panel.setState('open');
    controller.summon(0);
    controller.say('when were these taken?');
    await vi.waitFor(() => expect(controller.answer()).not.toBeNull());

    expect(panel.openEvidence()).toBe(true);
    expect(opened).toEqual(['span-a']);
    // The second citation had no span, so its chip is present, disabled, and says why.
    const chips = panel.root.querySelectorAll('.companion-evidence-chip');
    expect(chips).toHaveLength(2);
    expect(chips[1]!.hasAttribute('disabled')).toBe(true);
    expect(panel.root.textContent).toContain('could not be located');
  });

  it('names the served model and the measured latency under the answer', async () => {
    const controller = createCompanionController({
      companion: refusing('refused.couldNotParse'),
      onAwaitingConfirmation: () => undefined,
      askQuestion: async () => ANSWER,
    });
    const panel = buildCompanionEncounter({ onSelect: () => undefined, onSubmit: () => undefined, onSay: () => undefined, onEvidence: () => undefined });
    controller.attach(panel);
    panel.setState('open');
    controller.summon(0);
    controller.say('when were these taken?');
    await vi.waitFor(() => expect(controller.answer()).not.toBeNull());

    const provenance = panel.root.querySelector('.companion-provenance')?.textContent ?? '';
    expect(provenance).toContain('nvidia/Nemotron-3_5-Lightning');
    expect(provenance).toContain('12.4 s');
  });

  it('drops a slow answer that a newer question has already replaced', async () => {
    const pending: ((answer: CompanionAnswer) => void)[] = [];
    const controller = createCompanionController({
      companion: refusing('refused.couldNotParse'),
      onAwaitingConfirmation: () => undefined,
      askQuestion: () => new Promise<CompanionAnswer>((resolve) => pending.push(resolve)),
    });
    controller.summon(0);
    controller.say('first question');
    controller.say('second question');

    pending[1]!({ ...ANSWER, question: 'second question', text: 'second answer' });
    await vi.waitFor(() => expect(controller.answer()?.question).toBe('second question'));
    pending[0]!({ ...ANSWER, question: 'first question', text: 'first answer' });
    await Promise.resolve();

    expect(controller.answer()?.question).toBe('second question');
  });

  it('holds a late answer instead of drawing it over a dismissed Companion', async () => {
    /*
     * A question can be out for as long as `ASK_TIMEOUT_MS`, and the reasoning core has been
     * measured in tens of seconds. In that time the person can press Escape or open the Index,
     * both of which dismiss the Companion. Without this the answer replaced "Press X to call"
     * with a paragraph nobody had asked to see any more.
     */
    let resolve = (_: CompanionAnswer) => undefined as void;
    const controller = createCompanionController({
      companion: refusing('refused.couldNotParse'),
      onAwaitingConfirmation: () => undefined,
      askQuestion: () => new Promise<CompanionAnswer>((r) => { resolve = r; }),
    });
    const panel = buildCompanionEncounter({ onSelect: () => undefined, onSubmit: () => undefined, onSay: () => undefined, onEvidence: () => undefined });
    controller.attach(panel);
    panel.setState('open');
    controller.summon(0);
    controller.say('when were these taken?');

    controller.dismiss();
    expect(panel.state()).toBe('summon');
    resolve(ANSWER);
    await vi.waitFor(() => expect(controller.answer()).not.toBeNull());

    expect(panel.root.textContent).not.toContain('The earliest of them is from that winter.');
    expect(panel.root.textContent).toContain('to call');

    // Not discarded. It is what they asked for, so summoning again shows it.
    panel.setState('open');
    expect(panel.root.textContent).toContain('The earliest of them is from that winter.');
  });

  it('takes the numbered options off the keyboard while the question is out', async () => {
    /*
     * THE READ-ONLY GUARANTEE, at the one place it could have been broken.
     *
     * While a question is out the rail is detached, but it still holds the open turn and
     * `main.ts` routes every digit to `pressNumber`. Submitting the composer removes the focused
     * input from the document, so focus falls to `body` and the host's "is the user typing"
     * guard stops firing. A person typing a next question that starts with a digit would then
     * select an option they cannot see; on an identity question that option is tier 2, and the
     * confirmation surface would open over "Looking through your library" for a claim about a
     * person nobody chose.
     */
    const turn = {
      ...ACKNOWLEDGE,
      subjectEntityId: 'entity-1',
      evidence: ['span-turn'],
      choiceSet: {
        mode: 'single',
        submitRequired: false,
        options: [{
          optionId: 'same-person', kind: 'exclusive', textKey: 'option.yesSamePerson',
          phrasing: 'Yes, the same person', available: true, unavailableReasonKey: null,
          tier: 2, draft: null, escape: null,
        }],
      },
    } as unknown as Turn;
    const selected: string[] = [];
    const controller = createCompanionController({
      companion: refusing('refused.couldNotParse', turn),
      onAwaitingConfirmation: () => expect.unreachable('a question must not stage a proposal'),
      askQuestion: () => new Promise<CompanionAnswer>(() => undefined),
    });
    const panel = buildCompanionEncounter({
      onSelect: (optionId) => selected.push(optionId),
      onSubmit: () => undefined,
      onSay: () => undefined,
      onEvidence: () => selected.push('evidence'),
    });
    controller.attach(panel);
    panel.setState('open');
    controller.summon(0);
    expect(panel.pressNumber(1)).toBe(true);
    selected.length = 0;

    controller.say('1955, or was it later?');
    expect(panel.mode()).toBe('asking');
    expect(panel.root.textContent).toContain('Looking through your library.');

    expect(panel.pressNumber(1)).toBe(false);
    expect(panel.openEvidence()).toBe(false);
    expect(selected).toEqual([]);
  });

  it('goes back to the unanswered question without consuming a new one', async () => {
    const advance = vi.fn(() => ACKNOWLEDGE);
    const controller = createCompanionController({
      companion: { advance, say: () => ({ kind: 'refused', reasonKey: 'refused.couldNotParse' }) } as unknown as CompanionSession,
      onAwaitingConfirmation: () => undefined,
      askQuestion: async () => ANSWER,
    });
    const panel = buildCompanionEncounter({ onSelect: () => undefined, onSubmit: () => undefined, onSay: () => undefined, onEvidence: () => undefined });
    controller.attach(panel);
    panel.setState('open');
    controller.summon(0);
    expect(advance).toHaveBeenCalledTimes(1);

    controller.say('when were these taken?');
    await vi.waitFor(() => expect(controller.answer()).not.toBeNull());
    panel.root.querySelector<HTMLButtonElement>('.companion-answer-back')!.click();

    expect(controller.answer()).toBeNull();
    expect(panel.root.textContent).toContain('Noted.');
    expect(advance).toHaveBeenCalledTimes(1);
  });
});
