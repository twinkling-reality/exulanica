// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import { buildCompanionEncounter } from '../src/ui/companion-encounter.js';
import { answerToRemember, rememberedAsAnswer } from '../src/companion-memory-api.js';
import type { CompanionAnswer } from '../src/companion-ask-api.js';

/**
 * A remembered answer is drawn as the fresh one was: one paragraph per clause. The page keeps the
 * paragraphs apart in the text it remembers, and draws them apart again when the answer comes back
 * after a reload, so the same words never collapse into one paragraph.
 */

const NOOP = {
  onSelect: () => undefined,
  onSubmit: () => undefined,
  onSay: () => undefined,
  onEvidence: () => undefined,
};

const FIRST = 'Ari Ash 1 is talking with Bela Ash 2.';
const SECOND = 'Their model chose it at simulated minute 4.';

const fresh: CompanionAnswer = {
  question: 'What is Ari doing?',
  clauses: [
    { text: FIRST, type: 'meta', citations: [] },
    { text: SECOND, type: 'meta', citations: [] },
  ],
  text: `${FIRST} ${SECOND}`,
  abstained: null,
  deterministic: false,
  repaired: false,
  evidence: [],
  provenance: {
    composed: 'model',
    servedModel: 'nvidia/Nemotron-3_5-Lightning', servedModelName: 'Nemotron 3.5 Lightning',
    plannedBy: null, plannedByName: null,
    latencyMs: 4_800,
    usedFallback: false,
  },
  promptVersion: 'selection-3',
  calls: [],
} as CompanionAnswer;

function drawn(draw: (panel: ReturnType<typeof buildCompanionEncounter>) => void): string[] {
  const panel = buildCompanionEncounter(NOOP, {});
  panel.setState('open');
  draw(panel);
  return [...panel.root.querySelectorAll('[data-clause]')].map((node) => node.textContent ?? '');
}

function remembered(answerText: string) {
  const kept = answerToRemember(fresh);
  return rememberedAsAnswer({
    ...kept,
    answerText,
    answerId: 'answer-1',
    askedAtMs: Date.UTC(2026, 8, 29, 12, 0, 0),
    servedModelName: 'Nemotron 3.5 Lightning',
    plannedByName: null,
    origin: 'asked',
    supersedes: null,
    correctionNote: null,
    citations: [],
    names: {},
    composed: 'model',
  });
}

describe('a remembered answer keeps its paragraphs', () => {
  it('draws the paragraphs the fresh answer drew, with the same words', () => {
    const before = drawn((panel) => panel.showAnswer(fresh));
    // A positive control: the fresh answer is two paragraphs.
    expect(before).toEqual([FIRST, SECOND]);
    const kept = answerToRemember(fresh).answerText;
    const after = drawn((panel) => panel.restoreAnswer(remembered(kept)));
    expect(after).toEqual(before);
    // Its one-paragraph text is the fresh answer's, too.
    expect(remembered(kept).text).toBe(fresh.text);
  });

  it('draws a row kept as one paragraph as the one paragraph it was', () => {
    expect(drawn((panel) => panel.restoreAnswer(remembered(fresh.text)))).toEqual([fresh.text]);
  });
});
