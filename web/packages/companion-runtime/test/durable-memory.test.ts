import { describe, expect, it } from 'vitest';
import {
  DAY_MS,
  EMPTY_MEMORY,
  NOT_SURE_COOLDOWN_MS,
  SKIP_COOLDOWN_MS,
  SNAPSHOT_T1,
  CompanionSession,
  hardSuppression,
  latestAnswer,
  memoryFromPersisted,
  priorityPenalty,
  questionKey,
  recordEscape,
  standingAnswers,
} from '../src/index.js';
import type {
  PersistedAnswer,
  PersistedEscape,
  PersistedMemory,
} from '../src/index.js';
import { recordingGate } from './harness.js';

/**
 * DURABLE MEMORY, WHICH IS THE POINT OF THE WHOLE BRANCH.
 *
 * `interaction-model.md` 4.3 and 5.5 both say the Companion may never speak "within 7 days of a
 * Skip or 14 days of a Not sure on the same entity". Before this, memory was built at mount and
 * dropped at unload, so a fourteen-day window had never once been enforced past a single page
 * view: the person who said "not sure" and came back tomorrow was asked the same question again
 * by a system whose own contract said it would not.
 *
 * Every test below is a day count, because a cooldown that is off by a day is a cooldown that
 * either nags somebody or hides their own data from them, and neither shows up as a crash.
 */

const NOW = Date.UTC(2026, 8, 9, 12, 0, 0);
const ENTITY = 'entity-julie';
const INTENT = 'confirm_continuity';

function escape(over: Partial<PersistedEscape> = {}): PersistedEscape {
  return {
    escapeId: 'escape-1',
    takenAtMs: NOW - DAY_MS,
    escape: 'skip',
    intent: INTENT,
    entityId: ENTITY,
    turnId: 'turn-1',
    ...over,
  };
}

function answer(over: Partial<PersistedAnswer> = {}): PersistedAnswer {
  return {
    answerId: 'answer-1',
    askedAtMs: NOW - 60_000,
    question: 'When were these photographs taken?',
    answerText: 'These photographs were taken on 2026-02-01.',
    abstained: null,
    deterministic: false,
    repaired: false,
    servedModel: 'nvidia/Nemotron-3_5-Lightning',
    plannedBy: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
    promptVersion: 'selection-3',
    latencyMs: 40_208,
    origin: 'asked',
    supersedes: null,
    correctionNote: null,
    citations: [],
    ...over,
  };
}

const persisted = (over: Partial<PersistedMemory> = {}): PersistedMemory => ({
  answers: [],
  escapes: [],
  ...over,
});

describe('a cooldown survives the reload it used to die on', () => {
  it('suppresses a question skipped two days ago, which no reload could do before', () => {
    const memory = memoryFromPersisted(
      persisted({ escapes: [escape({ takenAtMs: NOW - 2 * DAY_MS })] }),
      NOW,
    );
    expect(hardSuppression(memory, INTENT, ENTITY, NOW)).toBe('cooldown.skip');
  });

  it('does not suppress a Skip that has run its seven days out', () => {
    const memory = memoryFromPersisted(
      persisted({ escapes: [escape({ takenAtMs: NOW - 8 * DAY_MS })] }),
      NOW,
    );
    expect(hardSuppression(memory, INTENT, ENTITY, NOW)).toBeNull();
  });

  it('holds a Not sure for thirteen days and releases it on the fifteenth', () => {
    const thirteen = memoryFromPersisted(
      persisted({ escapes: [escape({ escape: 'not_sure', takenAtMs: NOW - 13 * DAY_MS })] }),
      NOW,
    );
    expect(hardSuppression(thirteen, INTENT, ENTITY, NOW)).toBe('cooldown.notSure');

    const fifteen = memoryFromPersisted(
      persisted({ escapes: [escape({ escape: 'not_sure', takenAtMs: NOW - 15 * DAY_MS })] }),
      NOW,
    );
    expect(hardSuppression(fifteen, INTENT, ENTITY, NOW)).toBeNull();
  });

  it('never expires "that is the wrong question", because a wrong framing does not come right', () => {
    const memory = memoryFromPersisted(
      persisted({
        escapes: [escape({ escape: 'wrong_question', takenAtMs: NOW - 400 * DAY_MS })],
      }),
      NOW,
    );
    expect(hardSuppression(memory, INTENT, ENTITY, NOW)).toBe('signal.wrongQuestion');
  });

  it('carries the boundary exactly, at the millisecond either side of a Skip window', () => {
    const inside = memoryFromPersisted(
      persisted({ escapes: [escape({ takenAtMs: NOW - SKIP_COOLDOWN_MS + 1 })] }),
      NOW,
    );
    expect(hardSuppression(inside, INTENT, ENTITY, NOW)).toBe('cooldown.skip');

    const out = memoryFromPersisted(
      persisted({ escapes: [escape({ takenAtMs: NOW - SKIP_COOLDOWN_MS })] }),
      NOW,
    );
    expect(hardSuppression(out, INTENT, ENTITY, NOW)).toBeNull();
  });

  it('is the same arithmetic as the live path, not a second copy of it', () => {
    // The regression this guards is the sharp one: somebody fixes a cooldown in `recordEscape`
    // and the durable fold keeps the old rule, so the window is one thing in this session and
    // another after a reload. Folding through `recordEscape` is what makes that impossible, and
    // this asserts the two produce the same answer rather than trusting that they do.
    const takenAtMs = NOW - 3 * DAY_MS;
    const live = recordEscape(EMPTY_MEMORY, {
      escape: 'not_sure',
      intent: INTENT,
      entityId: ENTITY,
      atMs: takenAtMs,
    });
    const durable = memoryFromPersisted(
      persisted({ escapes: [escape({ escape: 'not_sure', takenAtMs })] }),
      NOW,
    );
    expect(durable.notSureUntilMs.get(ENTITY)).toBe(live.notSureUntilMs.get(ENTITY));
    expect(durable.notSureUntilMs.get(ENTITY)).toBe(takenAtMs + NOT_SURE_COOLDOWN_MS);
    expect(priorityPenalty(durable, ENTITY, NOW)).toBe(priorityPenalty(live, ENTITY, NOW));
  });

  it('doubles the initiative cooldown once per stored Skip, so six skips cost more than one', () => {
    // 4.3 makes this multiplicative and unbounded on purpose: "a user who skips six times in a
    // row has said something". Dying at unload made the sixth skip cost exactly what the first
    // did, which is the opposite of what the rule says.
    const many = memoryFromPersisted(
      persisted({
        escapes: [0, 1, 2].map((index) =>
          escape({ escapeId: `escape-${index}`, takenAtMs: NOW - (index + 1) * 60_000 }),
        ),
      }),
      NOW,
    );
    expect(many.initiativeCooldownMultiplier).toBe(8);
  });
});

describe('what is durable and what is only this sitting', () => {
  it('does not hydrate askedThisSession, which would silence a question forever', () => {
    // The failure this prevents is total rather than cosmetic. `askedThisSession` exists to stop
    // the generator looping on one question inside one sitting; hydrating it would mean every
    // question ever delivered is permanently suppressed, and the Companion would go quiet for
    // good on the library it knows most about.
    const memory = memoryFromPersisted(persisted({ escapes: [escape({ escape: 'later' })] }), NOW);
    expect(memory.askedThisSession.size).toBe(0);
    expect(hardSuppression(memory, INTENT, ENTITY, NOW)).toBeNull();
  });

  it('does not hydrate a Later, because 4.3 gives it no penalty at all', () => {
    // "Closes the thread, NO PENALTY." A dismissal is "not re-opened unprompted in the same
    // session", and a new session is not the same session. Carrying it over would turn the one
    // escape that costs nothing into the one that lasts forever.
    const memory = memoryFromPersisted(
      persisted({ escapes: [escape({ escape: 'later', takenAtMs: NOW - 1_000 })] }),
      NOW,
    );
    expect(memory.dismissed.has(questionKey(INTENT, ENTITY))) .toBe(false);
    expect(hardSuppression(memory, INTENT, ENTITY, NOW)).toBeNull();
  });

  it('keeps a Skip and a Not sure out of dismissed as well, so only the window suppresses', () => {
    const memory = memoryFromPersisted(persisted({ escapes: [escape()] }), NOW);
    expect(memory.dismissed.size).toBe(0);
    // Suppressed by the cooldown, which is the durable fact, rather than by a dismissal that was
    // about a thread closing in a session that has ended.
    expect(hardSuppression(memory, INTENT, ENTITY, NOW)).toBe('cooldown.skip');
  });

  it('ignores an escape with no subject, which would otherwise suppress every entity', () => {
    const memory = memoryFromPersisted(persisted({ escapes: [escape({ entityId: null })] }), NOW);
    expect(memory.skipUntilMs.size).toBe(0);
    expect(hardSuppression(memory, INTENT, ENTITY, NOW)).toBeNull();
  });
});

describe('the answers that still stand', () => {
  it('hides an answer a correction replaced, and keeps the correction', () => {
    const original = answer();
    const correction = answer({
      answerId: 'answer-2',
      askedAtMs: NOW - 30_000,
      answerText: 'No, the spring ones.',
      origin: 'correction',
      supersedes: 'answer-1',
      servedModel: null,
      correctionNote: 'Wrong roll.',
    });
    const standing = standingAnswers(persisted({ answers: [original, correction] }));
    expect(standing.map((a) => a.answerId)).toEqual(['answer-2']);
    expect(latestAnswer(persisted({ answers: [original, correction] }))?.answerText).toBe(
      'No, the spring ones.',
    );
  });

  it('orders newest first regardless of the order the route returned them in', () => {
    const older = answer({ answerId: 'a', askedAtMs: NOW - 10 * DAY_MS });
    const newer = answer({ answerId: 'b', askedAtMs: NOW - 1_000 });
    expect(standingAnswers(persisted({ answers: [older, newer] })).map((a) => a.answerId)).toEqual([
      'b',
      'a',
    ]);
  });

  it('has no last answer when nothing has been asked', () => {
    expect(latestAnswer(persisted())).toBeNull();
  });
});

describe('a session opened with durable memory', () => {
  const openWith = (memory: PersistedMemory): CompanionSession => {
    const { gate } = recordingGate(SNAPSHOT_T1.stateVersion);
    return new CompanionSession({
      snapshot: SNAPSHOT_T1,
      gate,
      persisted: { memory, nowMs: NOW },
    });
  };

  it('starts already suppressing what the person skipped before the reload', () => {
    const session = openWith(persisted({ escapes: [escape({ takenAtMs: NOW - DAY_MS })] }));
    expect(hardSuppression(session.memory, INTENT, ENTITY, NOW)).toBe('cooldown.skip');
  });

  it('can be told about memory that arrived after it opened', () => {
    // The root builds the engine while `GET /graph` is the only thing it has waited for, so the
    // memory usually lands second. A session that could only take it at construction would force
    // the mount to wait on a second request before anything could be drawn.
    const session = openWith(persisted());
    expect(hardSuppression(session.memory, INTENT, ENTITY, NOW)).toBeNull();
    session.adoptPersistedMemory(persisted({ escapes: [escape()] }), NOW);
    expect(hardSuppression(session.memory, INTENT, ENTITY, NOW)).toBe('cooldown.skip');
  });

  it('puts the last answer back, which is what a reload keeping the answer means', () => {
    const session = openWith(persisted({ answers: [answer()] }));
    expect(session.lastAnswer?.answerText).toBe('These photographs were taken on 2026-02-01.');
    expect(session.rememberedAnswers).toHaveLength(1);
  });

  it('writes nothing to the graph while adopting memory', () => {
    // The invariant the whole package exists for, checked on the one new path that could break
    // it. 5.1: nothing reaches the graph without an explicit confirmation, and durable memory
    // decides which questions may be ASKED and never what may be written.
    const { gate, committed } = recordingGate(SNAPSHOT_T1.stateVersion);
    const session = new CompanionSession({ snapshot: SNAPSHOT_T1, gate });
    session.adoptPersistedMemory(persisted({ answers: [answer()], escapes: [escape()] }), NOW);
    expect(committed).toEqual([]);
    expect(session.pendingProposalIds).toEqual([]);
  });
});
