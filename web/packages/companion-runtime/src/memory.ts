import type { EntityIdRef, EvidenceHandle } from '@exulanica/graph-client';
import type { Intent } from './intent.js';
import type { EscapeKind } from './turn.js';

/**
 * CONVERSATION MEMORY: what the user has already told the Companion to leave alone.
 *
 * The escape table in interaction-model.md 4.3 assigns each escape a lasting effect, and 5.5
 * makes two of those effects hard gates on spontaneous speech. Both readings live here so that
 * "never within 7 days of a Skip or 14 days of a Not sure on the same entity" is one function
 * with a test rather than a condition copied into two call sites.
 *
 * Two strengths of suppression, deliberately distinct:
 *
 *   HARD  - the question may not be asked at all. Skip, Not sure, and "that is the wrong
 *           question" all produce this for their window.
 *   SOFT  - the question may be asked but ranks lower. 4.3 says Not sure "LOWERS RE-ASK PRIORITY
 *           on this entity for 14 days", which is a ranking statement, while 5.5 says initiative
 *           may never speak within 14 days of one, which is a gate. Both are true of different
 *           channels: the user opening the review queue themselves is not the Companion speaking.
 *
 * The second half of this file is the same memory in a shape a reload survives, and the seam
 * between the two is `memoryFromPersisted`. Read that function's comment before adding a field:
 * it is where the line between "durable" and "this sitting" is drawn, and both sides of the line
 * come from 4.3 and 5.5 rather than from what happens to be easy to store.
 */

export const DAY_MS = 24 * 60 * 60 * 1000;
/** 4.3 and 5.5: "never within ... 14 days of a Not sure on the same entity". */
export const NOT_SURE_COOLDOWN_MS = 14 * DAY_MS;
/** 4.3 and 5.5: "never within 7 days of a Skip". */
export const SKIP_COOLDOWN_MS = 7 * DAY_MS;

export interface TranscriptEntry {
  readonly turnId: string;
  readonly intent: Intent;
  readonly subjectEntityId: EntityIdRef | null;
  readonly optionId: string | null;
  readonly escape: EscapeKind | null;
  /** Verbatim, when the user typed. Never paraphrased (5.1). */
  readonly rawUtterance: string | null;
  readonly atMs: number;
  readonly stateVersion: number;
}

/** `${intent}|${entityId}` - a question is a pair, not just a subject. */
export type QuestionKey = string;

export function questionKey(intent: Intent, entityId: EntityIdRef | null): QuestionKey {
  return `${intent}|${entityId ?? '-'}`;
}

export interface CompanionMemory {
  /** Entity -> instant the Not sure window expires. */
  readonly notSureUntilMs: ReadonlyMap<EntityIdRef, number>;
  /** Entity -> instant the Skip window expires. */
  readonly skipUntilMs: ReadonlyMap<EntityIdRef, number>;
  /**
   * 4.3: a Skip means "initiative cooldown DOUBLES". Multiplicative and unbounded on purpose:
   * a user who skips six times in a row has said something, and the sixth skip should cost the
   * Companion more than the first did.
   */
  readonly initiativeCooldownMultiplier: number;
  /**
   * "That is the wrong question": a negative signal on (intent, entity). "The only channel by
   * which a user can tell the system its framing is off." It does not expire on a timer, because
   * a wrong framing does not become right after a fortnight.
   */
  readonly wrongQuestion: ReadonlySet<QuestionKey>;
  /** Threads closed with Later. No penalty, but not re-opened unprompted in the same session. */
  readonly dismissed: ReadonlySet<QuestionKey>;
  /** Asked at least once this session. Stops the generator looping on one question. */
  readonly askedThisSession: ReadonlySet<QuestionKey>;
  /** Instants at which the Companion spoke spontaneously. Feeds the per-session and per-hour caps. */
  readonly spokeAtMs: readonly number[];
  readonly transcript: readonly TranscriptEntry[];
}

export const EMPTY_MEMORY: CompanionMemory = Object.freeze({
  notSureUntilMs: new Map<EntityIdRef, number>(),
  skipUntilMs: new Map<EntityIdRef, number>(),
  initiativeCooldownMultiplier: 1,
  wrongQuestion: new Set<QuestionKey>(),
  dismissed: new Set<QuestionKey>(),
  askedThisSession: new Set<QuestionKey>(),
  spokeAtMs: Object.freeze([]),
  transcript: Object.freeze([]),
});

function withMapEntry<K, V>(map: ReadonlyMap<K, V>, key: K, value: V): ReadonlyMap<K, V> {
  const next = new Map(map);
  next.set(key, value);
  return next;
}

function withSetEntry<T>(set: ReadonlySet<T>, value: T): ReadonlySet<T> {
  const next = new Set(set);
  next.add(value);
  return next;
}

export interface EscapeRecord {
  readonly escape: EscapeKind;
  readonly intent: Intent;
  readonly entityId: EntityIdRef | null;
  readonly atMs: number;
}

/**
 * Apply an escape's lasting effect. Pure: returns new memory.
 *
 * `later` deliberately changes nothing except the dismissed set. 4.3: "Closes the thread, NO
 * PENALTY." A user who is busy is not a user who is uninterested, and the single most common way
 * to make an assistant feel punitive is to treat "not now" as "not ever".
 */
export function recordEscape(memory: CompanionMemory, record: EscapeRecord): CompanionMemory {
  const key = questionKey(record.intent, record.entityId);
  const base = { ...memory, dismissed: memory.dismissed, askedThisSession: memory.askedThisSession };

  switch (record.escape) {
    case 'not_sure':
      return Object.freeze({
        ...base,
        notSureUntilMs:
          record.entityId === null
            ? memory.notSureUntilMs
            : withMapEntry(memory.notSureUntilMs, record.entityId, record.atMs + NOT_SURE_COOLDOWN_MS),
        dismissed: withSetEntry(memory.dismissed, key),
      });
    case 'skip':
      return Object.freeze({
        ...base,
        skipUntilMs:
          record.entityId === null
            ? memory.skipUntilMs
            : withMapEntry(memory.skipUntilMs, record.entityId, record.atMs + SKIP_COOLDOWN_MS),
        initiativeCooldownMultiplier: memory.initiativeCooldownMultiplier * 2,
        dismissed: withSetEntry(memory.dismissed, key),
      });
    case 'later':
      return Object.freeze({ ...base, dismissed: withSetEntry(memory.dismissed, key) });
    case 'wrong_question':
      return Object.freeze({
        ...base,
        wrongQuestion: withSetEntry(memory.wrongQuestion, key),
        dismissed: withSetEntry(memory.dismissed, key),
      });
  }
}

export function recordAsked(
  memory: CompanionMemory,
  intent: Intent,
  entityId: EntityIdRef | null,
): CompanionMemory {
  return Object.freeze({
    ...memory,
    askedThisSession: withSetEntry(memory.askedThisSession, questionKey(intent, entityId)),
  });
}

export function recordTranscript(
  memory: CompanionMemory,
  entry: TranscriptEntry,
): CompanionMemory {
  return Object.freeze({ ...memory, transcript: Object.freeze([...memory.transcript, entry]) });
}

/** The Companion opened its mouth without being asked. Feeds the per-session and per-hour caps. */
export function recordSpontaneousSpeech(memory: CompanionMemory, atMs: number): CompanionMemory {
  return Object.freeze({ ...memory, spokeAtMs: Object.freeze([...memory.spokeAtMs, atMs]) });
}

export type SuppressionReason =
  | 'cooldown.notSure'
  | 'cooldown.skip'
  | 'signal.wrongQuestion'
  | 'thread.dismissed'
  | 'asked.thisSession';

/**
 * Why this question may not be asked right now, or null if it may.
 *
 * A closed reason set rather than a boolean, because every one of these reasons is something the
 * runtime may need to say out loud: "unavailable with a reason" is the Yarn Spinner availability
 * semantics the option pool uses (4.4 stage 3), and a bare false cannot fill that in.
 */
export function hardSuppression(
  memory: CompanionMemory,
  intent: Intent,
  entityId: EntityIdRef | null,
  nowMs: number,
): SuppressionReason | null {
  const key = questionKey(intent, entityId);
  if (memory.wrongQuestion.has(key)) return 'signal.wrongQuestion';
  if (entityId !== null) {
    const notSure = memory.notSureUntilMs.get(entityId);
    if (notSure !== undefined && nowMs < notSure) return 'cooldown.notSure';
    const skip = memory.skipUntilMs.get(entityId);
    if (skip !== undefined && nowMs < skip) return 'cooldown.skip';
  }
  if (memory.dismissed.has(key)) return 'thread.dismissed';
  if (memory.askedThisSession.has(key)) return 'asked.thisSession';
  return null;
}

/**
 * Ranking penalty, 0..1, multiplied into the value function.
 *
 * This is the SOFT reading of 4.3's "lowers re-ask priority": the entity still appears in the
 * review queue and the user can still open it, it simply stops being the thing the system
 * volunteers first. A hard block here would hide the user's own data from the user, which is a
 * different and much worse failure than asking a question twice.
 */
export function priorityPenalty(
  memory: CompanionMemory,
  entityId: EntityIdRef | null,
  nowMs: number,
): number {
  if (entityId === null) return 1;
  let penalty = 1;
  const notSure = memory.notSureUntilMs.get(entityId);
  if (notSure !== undefined && nowMs < notSure) penalty *= 0.25;
  const skip = memory.skipUntilMs.get(entityId);
  if (skip !== undefined && nowMs < skip) penalty *= 0.5;
  return penalty;
}

// ---------------------------------------------------------------------------------------------
// THE DURABLE HALF
// ---------------------------------------------------------------------------------------------

/**
 * The same memory, in a shape that survives a reload.
 *
 * Everything above is built at mount and dropped at unload, and that is not a missing nicety.
 * 4.3 and 5.5 both say the Companion may never speak "within 7 days of a Skip or 14 days of a Not
 * sure on the same entity", and a fourteen-day window held in a page that a reload discards is a
 * fourteen-day window that has never once been enforced past a single page view. The person who
 * said "not sure" and came back tomorrow was asked again.
 *
 * These interfaces are the browser's reading of `/companion/memory`, in this package rather than
 * in the app because the FOLD below has to live next to `recordEscape`. Nothing here does I/O:
 * the package compiles with `lib: ["ES2022"]` and `types: []`, so it cannot, and the HTTP client
 * that fills these shapes is `packages/app/src/companion-memory-api.ts`.
 */

/**
 * The four abstention codes, carried through rather than collapsed.
 *
 * `evaluation-methodology.md` M3: merging them "lets a system that always says 'I don't know'
 * score perfectly". `companion-ask-api.ts` declares the identical union for the answer route,
 * which is a different route reporting the same closed set. The two are structurally identical
 * string unions on purpose, so an answer flows into a durable row by assignment and the compiler
 * is what keeps the two spellings in step; a divergence is a type error rather than a review.
 */
export type AbstentionCode =
  | 'UNANSWERABLE_NOT_CAPTURED'
  | 'UNANSWERABLE_AMBIGUOUS'
  | 'UNANSWERABLE_NOT_IN_MODALITY'
  | 'UNANSWERABLE_NOT_UNDERSTOOD';

/**
 * Who wrote the row. `asked` is a question the person typed and the answer that came back;
 * `correction` is the person's own words about an answer that was wrong. Both are answers,
 * because a correction is the answer that stands afterwards.
 */
export type AnswerOrigin = 'asked' | 'correction';

/**
 * One photograph an answer quoted.
 *
 * The SPAN, never the per-request citation token. Token namespaces are drawn fresh per request,
 * so a stored token resolves in no later request and would be a chip that opens nothing. The
 * capture is recorded beside it because it is the join a withdrawal travels along.
 */
export interface PersistedCitation {
  readonly spanId: EvidenceHandle;
  readonly captureId: string;
  /** Reading order: which photograph the clauses mentioned first, not which token was minted first. */
  readonly ordinal: number;
}

export interface PersistedAnswer {
  readonly answerId: string;
  readonly askedAtMs: number;
  readonly question: string;
  readonly answerText: string;
  readonly abstained: AbstentionCode | null;
  readonly deterministic: boolean;
  readonly repaired: boolean;
  /**
   * The identifier that WROTE the sentence, read off the response body and never off a manifest.
   * Null is a fact rather than missing data: it is the discarded, search and unreadable
   * provenance cases, where a sentence reached the screen that no model wrote.
   */
  readonly servedModel: string | null;
  readonly plannedBy: string | null;
  readonly promptVersion: string;
  readonly latencyMs: number;
  readonly origin: AnswerOrigin;
  /** The answer this one replaces. Set on a correction and null on everything else. */
  readonly supersedes: string | null;
  readonly correctionNote: string | null;
  readonly citations: readonly PersistedCitation[];
}

export interface PersistedEscape {
  readonly escapeId: string;
  readonly takenAtMs: number;
  readonly escape: EscapeKind;
  readonly intent: Intent;
  /** Null when the turn had no subject. `recordEscape` already treats that as "no window". */
  readonly entityId: EntityIdRef | null;
  readonly turnId: string;
}

export interface PersistedMemory {
  readonly answers: readonly PersistedAnswer[];
  readonly escapes: readonly PersistedEscape[];
}

export const EMPTY_PERSISTED_MEMORY: PersistedMemory = Object.freeze({
  answers: Object.freeze([]),
  escapes: Object.freeze([]),
});

/**
 * Which durable escapes can still be in force at `nowMs`, and therefore which are worth folding.
 *
 * This is what `nowMs` is for, and it is not an optimisation. `recordEscape` doubles
 * `initiativeCooldownMultiplier` on every Skip, multiplicatively and unbounded, which is right
 * for a session: "a user who skips six times in a row has said something". Folding EVERY Skip a
 * person ever took would carry that arithmetic across a year of sessions and produce a cooldown
 * longer than the product, from a signal nobody sent. Restricting the fold to the escapes whose
 * own window has not closed reproduces exactly the set a live session would have been holding,
 * so the durable path and the live path agree about the multiplier as well as about the windows.
 *
 * `wrong_question` is always in force: "a wrong framing does not become right after a fortnight".
 * `later` is never folded, because its only effect is the dismissed set and that set is
 * deliberately session-scoped. See `memoryFromPersisted`.
 */
function stillInForce(escape: PersistedEscape, nowMs: number): boolean {
  switch (escape.escape) {
    case 'wrong_question':
      return true;
    case 'not_sure':
      return escape.takenAtMs + NOT_SURE_COOLDOWN_MS > nowMs;
    case 'skip':
      return escape.takenAtMs + SKIP_COOLDOWN_MS > nowMs;
    case 'later':
      return false;
  }
}

/**
 * Rebuild the suppression state from durable escape rows.
 *
 * **The cooldown arithmetic is not repeated here.** It would have been three lines to write
 * `takenAtMs + SKIP_COOLDOWN_MS` into a map directly, and those three lines would be a second
 * implementation of a rule that already has one. The durable path folds `recordEscape` over the
 * rows in chronological order instead, so a change to what a Skip means changes what a Skip means
 * on both paths at once, and the failure this prevents is the sharp one: a fix to the live
 * cooldown that quietly leaves the reloaded cooldown on the old rule, visible only to somebody
 * who closed the tab.
 *
 * Chronological because `recordEscape` is order-sensitive in one place that matters: the
 * multiplier is a product over the Skips it sees, and a later escape on the same entity must
 * overwrite an earlier window rather than the other way round. The wire says newest first, so
 * this sorts rather than trusting the order it was handed.
 *
 * WHICH FIELDS ARE DURABLE, AND WHY THE OTHERS ARE NOT. Every field below is on one side of a
 * line drawn by 4.3 and 5.5 rather than by convenience:
 *
 *   notSureUntilMs, skipUntilMs   DURABLE. 5.5 states them in days. A window measured in
 *                                 fortnights that a page reload resets is not a window.
 *   wrongQuestion                 DURABLE. 4.3 calls it "the only channel by which a user can
 *                                 tell the system its framing is off", and it has no expiry at
 *                                 all; forgetting it at unload would make the one channel the
 *                                 shortest-lived signal in the product.
 *   initiativeCooldownMultiplier  DURABLE, bounded by the fold above. 4.3 attaches it to Skip,
 *                                 and it is derived from the same rows as the Skip windows.
 *   dismissed                     SESSION. 4.3: Later "Closes the thread, NO PENALTY", and the
 *                                 field's own contract is "not re-opened unprompted IN THE SAME
 *                                 SESSION". A durable dismissed set turns "not now" into "not
 *                                 ever", which is precisely the punitive reading the no-penalty
 *                                 rule exists to forbid. A person who said Later yesterday came
 *                                 back today, and coming back is the opposite of a refusal.
 *   askedThisSession              SESSION, and the sharpest one. The field means what its name
 *                                 says: it stops the generator looping on one question inside a
 *                                 sitting. Hydrating it would make every question the Companion
 *                                 has ever asked once unaskable forever, so the first "not now"
 *                                 answer, the first mis-click, and every question interrupted by
 *                                 a reload would be silently retired. That is a worse failure
 *                                 than re-asking, and it is invisible: the questions do not
 *                                 appear, so nobody reports them missing.
 *   spokeAtMs                     SESSION. It feeds the per-session and per-hour speech caps
 *                                 (5.5), and a per-session cap fed by other sessions is a
 *                                 different cap.
 *   transcript                    NOT CARRIED. The durable escape row records the turn id, the
 *                                 intent and the subject and nothing else; a `TranscriptEntry`
 *                                 also carries the option, the raw utterance and the state
 *                                 version. Rebuilding one from an escape row would put entries
 *                                 with invented nulls into the log 5.4 governs, so the transcript
 *                                 starts empty and says so rather than starting wrong.
 */
export function memoryFromPersisted(persisted: PersistedMemory, nowMs: number): CompanionMemory {
  const chronological = [...persisted.escapes]
    .filter((escape) => stillInForce(escape, nowMs))
    .sort((a, b) => a.takenAtMs - b.takenAtMs);

  let memory = EMPTY_MEMORY;
  for (const escape of chronological) {
    memory = recordEscape(memory, {
      escape: escape.escape,
      intent: escape.intent,
      entityId: escape.entityId,
      atMs: escape.takenAtMs,
    });
  }

  // `recordEscape` adds every folded escape to `dismissed`, which is correct inside a session and
  // wrong across one. Cleared here rather than by not folding, because the alternative would mean
  // duplicating the parts of `recordEscape` that are durable, which is the duplication this whole
  // function exists to avoid.
  return Object.freeze({
    ...memory,
    dismissed: EMPTY_MEMORY.dismissed,
    askedThisSession: EMPTY_MEMORY.askedThisSession,
  });
}

/**
 * The answers that still stand, newest first.
 *
 * A correction never edits: `interaction-model.md` 5.4 fixes that "Nothing is ever silently
 * rewritten", so a person correcting an answer writes a NEW row naming the one it replaces, and
 * the wrong answer stays in the record where it belongs. What must not happen is that the wrong
 * answer stays on the SCREEN, so anything another row supersedes is dropped here.
 *
 * The route already excludes superseded rows, and this is deliberately not a reason to skip the
 * check. Rendering a corrected answer as though the correction had not happened is the one
 * failure this feature cannot be allowed to have, and the client holds the lineage in its hand:
 * asserting it locally costs one pass and does not depend on a filter in another process.
 */
export function standingAnswers(persisted: PersistedMemory): readonly PersistedAnswer[] {
  const superseded = new Set<string>();
  for (const answer of persisted.answers) {
    if (answer.supersedes !== null) superseded.add(answer.supersedes);
  }
  return Object.freeze(
    persisted.answers
      .filter((answer) => !superseded.has(answer.answerId))
      .sort((a, b) => b.askedAtMs - a.askedAtMs),
  );
}

/** The most recent answer that still stands, or null when the person has asked nothing. */
export function latestAnswer(persisted: PersistedMemory): PersistedAnswer | null {
  return standingAnswers(persisted)[0] ?? null;
}
