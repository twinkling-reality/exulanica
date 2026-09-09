// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { buildCompanionEncounter } from '../src/ui/companion-encounter.js';
import { say } from '../src/ui/copy.js';
import type { CompanionAnswer } from '../src/companion-ask-api.js';

/**
 * KEEPING AN ANSWER MUST NEVER COST THE ANSWER.
 *
 * An answer that reached the screen is correct and cited whether or not a second request managed
 * to store it, so the two failures are separate and the person is owed both sentences. What this
 * file protects is the ORDER and the INDEPENDENCE of those two facts: the answer is drawn first
 * and unconditionally, the write-back is told about it afterwards, and nothing the host does with
 * it can delay the answer, remove it, or turn a durability failure into "the question failed".
 *
 * The hook lives in the file that RENDERS rather than in the controller, so "after it is on the
 * screen" is a fact at the call site instead of an assumption about microtask ordering somewhere
 * else. These tests are what make that a fact rather than a comment.
 */

const NOOP = {
  onSelect: () => undefined,
  onSubmit: () => undefined,
  onSay: () => undefined,
  onEvidence: () => undefined,
};

function answer(over: Partial<CompanionAnswer> = {}): CompanionAnswer {
  return {
    question: 'When were these photographs taken?',
    clauses: [
      {
        text: 'These photographs were taken on 2026-02-01.',
        type: 'historical',
        citations: ['TOKENAAAA1'],
      },
    ],
    text: 'These photographs were taken on 2026-02-01.',
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
    ],
    provenance: {
      composed: 'model',
      servedModel: 'nvidia/Nemotron-3_5-Lightning',
      plannedBy: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
      latencyMs: 40_208,
      usedFallback: false,
    },
    promptVersion: 'selection-3',
    calls: [],
    ...over,
  } as CompanionAnswer;
}

function opened(options: Parameters<typeof buildCompanionEncounter>[1] = {}) {
  const panel = buildCompanionEncounter(NOOP, options);
  panel.setState('open');
  return panel;
}

describe('the answer is drawn before anything is told to keep it', () => {
  it('fires onAnswerShown after the answer is in the document', () => {
    let textWhenTold: string | null = null;
    const panel = opened({
      onAnswerShown: () => {
        // Read from the DOM rather than from the argument, because the argument would be the
        // same whether or not anything had rendered. This is the assertion that the hook is
        // after the render and not merely after the promise.
        textWhenTold = panel.root.textContent;
      },
    });
    panel.showAnswer(answer());
    expect(textWhenTold).toContain('These photographs were taken on 2026-02-01.');
  });

  it('fires exactly once per answer', () => {
    const told = vi.fn();
    const panel = opened({ onAnswerShown: told });
    panel.showAnswer(answer());
    expect(told).toHaveBeenCalledOnce();
  });

  it('draws the answer even when the host that keeps it throws, and loses no error doing it', () => {
    /*
     * A host defect must not cost the person the thing they asked for, and must not be swallowed
     * either. `companion-encounter.ts` re-raises out of band for a reason worth restating: let
     * through, the throw would reach the `catch` around `showAnswer` in `companion.ts` and be
     * reported as a question that FAILED, which it did not, because the answer is on the screen.
     *
     * The out-of-band raise is captured here rather than allowed to fire. A real uncaught error
     * escaping this test lands on whichever test happens to be running when the timer fires and
     * fails that one instead, which is exactly what happened the first time this was written.
     */
    const scheduled: (() => void)[] = [];
    const timers = vi
      .spyOn(globalThis, 'setTimeout')
      .mockImplementation(((callback: () => void) => {
        scheduled.push(callback);
        return 0;
      }) as unknown as typeof setTimeout);
    try {
      const broken = new Error('the host is broken');
      const panel = opened({
        onAnswerShown: () => {
          throw broken;
        },
      });
      expect(() => panel.showAnswer(answer())).not.toThrow();
      expect(panel.root.textContent).toContain('These photographs were taken on 2026-02-01.');
      expect(panel.showingAnswer()).toBe(true);
      expect(scheduled).toHaveLength(1);
      expect(() => scheduled[0]?.()).toThrow(broken);
    } finally {
      timers.mockRestore();
    }
  });
});

describe('an answer that was not kept says so, under itself', () => {
  it('appends the notice without removing the answer', () => {
    const panel = opened();
    panel.showAnswer(answer());
    panel.noteMemoryFailure('memory.notKept.unreachable', 'the request never arrived');

    const text = panel.root.textContent ?? '';
    // Both sentences, because both are true: the answer is correct and it will not be there next
    // time. Replacing one with the other would take away what the person asked for because a
    // second request went wrong.
    expect(text).toContain('These photographs were taken on 2026-02-01.');
    expect(text).toContain(say('memory.notKept.unreachable'));
    expect(text).toContain('the request never arrived');
  });

  it('says something a person can act on rather than echoing a key', () => {
    // `say` falls back to the key itself for an unknown one, so a missing entry renders as
    // `memory.notKept.unreachable` on screen and nothing fails. This is what catches that.
    for (const kind of [
      'unauthenticated',
      'unknown_reference',
      'refused',
      'unreadable',
      'unreachable',
    ]) {
      const key = `memory.notKept.${kind}`;
      expect(say(key), `${key} has no sentence`).not.toBe(key);
    }
    expect(say('memory.notLoaded')).not.toBe('memory.notLoaded');
  });

  it('does not stack a notice per render', () => {
    const panel = opened();
    panel.showAnswer(answer());
    panel.noteMemoryFailure('memory.notKept.refused', 'no');
    panel.noteMemoryFailure('memory.notKept.refused', 'no');
    const occurrences = (panel.root.textContent ?? '').split(say('memory.notKept.refused')).length - 1;
    expect(occurrences).toBe(1);
  });

  it('drops the notice once the answer it was about is off the screen', () => {
    // Left standing it would read as a statement about whatever is showing now, which is a turn
    // nothing has tried to keep.
    const panel = opened();
    panel.showAnswer(answer());
    panel.noteMemoryFailure('memory.notKept.refused', 'no');
    panel.askStarted('and another question?');
    expect(panel.root.textContent ?? '').not.toContain(say('memory.notKept.refused'));
  });
});
