// @vitest-environment happy-dom

/**
 * Words typed while the Companion's own question is open: an answer to it is staged for the person
 * to confirm, and the person's own question or request is asked.
 *
 * Sixteen fixed utterances at the four open questions that take free text, each routed through the
 * real parser (`parseUtterance` and `draftFromParse`) and the real controller. The session here
 * stages whatever the parser drafts and refuses words it drafts nothing from, as `CompanionSession.say`
 * does. Before the parser read a reply's yes or no and whether words ask, 8 of the 16 went the other
 * way: a question holding a relation word was staged as a relation to record, a question with a
 * comma typed at "How do you know them?" was staged as a note, and "Maybe not" was asked.
 */

import { describe, expect, it, vi } from 'vitest';
import {
  draftFromParse,
  parseUtterance,
  type CompanionSession,
  type ConfirmationSummary,
  type SelectionOutcome,
  type Turn,
} from '@exulanica/companion-runtime';

import type { CompanionAnswer } from '../src/companion-ask-api.js';
import { createCompanionController } from '../src/companion.js';

const ANSWER = {
  question: 'q',
  clauses: [{ text: 'An answer.', type: 'meta', citations: [] }],
  text: 'An answer.',
  abstained: null,
  deterministic: true,
  repaired: false,
  evidence: [],
  provenance: {
    composed: 'deterministic',
    servedModel: null,
    servedModelName: null,
    plannedBy: null,
    plannedByName: null,
    latencyMs: 0,
    usedFallback: false,
  },
  promptVersion: 'selection-1',
  calls: [],
} as unknown as CompanionAnswer;

/** The open turn whose question is `utteranceKey`, about one subject. */
function openTurn(utteranceKey: string): Turn {
  return {
    turnId: `turn-${utteranceKey}`,
    intent: 'enrich_relation',
    subjectEntityId: 'entity-1',
    subjectAnchorId: null,
    utteranceKey,
    utterance: null,
    evidence: [],
    choiceSet: null,
    freeTextAllowed: true,
    escapes: [],
    stateVersion: 1,
  } as unknown as Turn;
}

/** A session that stages what the parser drafts from the words, as `CompanionSession.say` does. */
function parsing(turn: Turn) {
  const cancelled: string[] = [];
  const session = {
    advance: () => turn,
    say: (text: string) => {
      const draft = draftFromParse(parseUtterance(text), {
        ids: (kind) => `${kind}-1`,
        subjectEntityId: 'entity-1',
        anchorIds: [],
        islandIds: [],
        captureEvidence: [],
      });
      if (draft === null) return { kind: 'refused', reasonKey: 'refused.couldNotParse' };
      return {
        kind: 'awaiting_confirmation',
        proposal: {
          proposalId: 'proposal-1',
          turnId: turn.turnId,
          origin: 'user_utterance',
          rawUtterance: text,
          operations: draft.operations.map((operation) => ({
            op: operation.op,
            tier: 1,
            affectedAnchorIds: [],
            affectedIslandIds: [],
            payload: operation.payload,
          })),
          provenanceSummary: 'provenance.userUtterance',
          maxTier: 1,
          reversible: true,
          expiresAtStateVersion: 2,
        },
        confirmation: {} as ConfirmationSummary,
      } as unknown as SelectionOutcome;
    },
    cancel: (proposalId: string) => {
      cancelled.push(proposalId);
    },
  } as unknown as CompanionSession;
  return { session, cancelled };
}

const NAME_SCOPE = 'utterance.nameScope';
const RELATION = 'utterance.relation';
const RESOLVE = 'utterance.resolveIdentity';
const CONTINUITY = 'utterance.confirmContinuity';

/** Turn, words, and where they go. Fixed before the change they measure. */
const TABLE: readonly (readonly [string, string, 'staged' | 'asked'])[] = [
  [
    NAME_SCOPE,
    'Make the light warmer where Maria Estrada stands outside Mireland Hall, and say who stands there and where.',
    'asked',
  ],
  [NAME_SCOPE, 'Is my mother in any of these photographs?', 'asked'],
  [NAME_SCOPE, 'Show me every photograph with my sister in it', 'asked'],
  [NAME_SCOPE, 'Call her Maria, from the harbour', 'staged'],
  [RELATION, 'we met at work, years ago', 'staged'],
  [RELATION, 'She is my friend from school', 'staged'],
  [RELATION, 'Which photographs show the harbour, and when were they taken?', 'asked'],
  [RELATION, 'Who else was at the wedding, my family or my friends?', 'asked'],
  [RESOLVE, "No, that's her daughter", 'staged'],
  [RESOLVE, 'Maybe not', 'staged'],
  [RESOLVE, 'Probably not, she looks younger', 'staged'],
  [RESOLVE, 'Where was the earlier photograph taken?', 'asked'],
  [CONTINUITY, 'Yes, the same woman, years later', 'staged'],
  [CONTINUITY, 'I think so, same coat', 'staged'],
  [CONTINUITY, 'No, different people', 'staged'],
  [CONTINUITY, 'Is my brother in the second one?', 'asked'],
];

describe('words typed while the Companion\'s own question is open', () => {
  it('holds sixteen fixed utterances', () => {
    expect(TABLE).toHaveLength(16);
  });

  it.each(TABLE)('at %s, %j is %s', async (key, words, expected) => {
    const { session, cancelled } = parsing(openTurn(key));
    const askQuestion = vi.fn(async () => ANSWER);
    const staged = vi.fn();
    const controller = createCompanionController({
      companion: session,
      onAwaitingConfirmation: staged,
      askQuestion,
    });
    controller.summon(0);

    controller.say(words);

    if (expected === 'asked') {
      await vi.waitFor(() => expect(askQuestion).toHaveBeenCalledWith(words));
      expect(staged).not.toHaveBeenCalled();
    } else {
      expect(staged).toHaveBeenCalledWith('proposal-1', expect.anything(), words);
      expect(cancelled).toEqual([]);
      expect(askQuestion).not.toHaveBeenCalled();
    }
  });

  it('keeps a reply whole, its yes or no with it, as the note it records', () => {
    for (const [words, reply] of [
      ["No, that's her daughter", 'no'],
      ['Maybe not', 'no'],
      ['I think so, same coat', 'yes'],
      ['Not sure, she looks older', 'maybe'],
    ] as const) {
      const parse = parseUtterance(words);
      expect(parse.reply, words).toBe(reply);
      const draft = draftFromParse(parse, {
        ids: (kind) => `${kind}-1`,
        subjectEntityId: 'entity-1',
        anchorIds: [],
        islandIds: [],
        captureEvidence: [],
      });
      expect(draft?.operations.map((operation) => operation.payload), words).toEqual([
        { predicateKey: 'note', text: words },
      ]);
    }
  });

  it('reads no reply from a word that only begins like one', () => {
    for (const words of ['Nobody was there, it was early', 'Yesterday, at the harbour']) {
      expect(parseUtterance(words).reply, words).toBeNull();
    }
  });

  it('reads words as asking by their question mark or by the word they open with', () => {
    expect(parseUtterance('She was at the harbour?').asks).toBe(true);
    expect(parseUtterance('Tell me who is in the second one').asks).toBe(true);
    expect(parseUtterance('She is my friend from school').asks).toBe(false);
    expect(parseUtterance('Call her Maria, from the harbour').asks).toBe(false);
  });
});
