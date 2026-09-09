/**
 * The browser's half of `/companion/memory`: what the Companion is told to keep, and what it is
 * handed back when the tab opens again.
 *
 * `companion-runtime/src/memory.ts` already held the whole model of what a person has told this
 * Companion to leave alone, and every field of it was built at mount and dropped at unload. The
 * consequence was not a missing nicety. `interaction-model.md` 4.3 and 5.5 both say the Companion
 * may never speak "within 7 days of a Skip or 14 days of a Not sure on the same entity", and a
 * fourteen-day window held in a page that a reload discards had never once been enforced past a
 * single page view: the person who said "not sure" and came back tomorrow was asked again. This
 * file is the transport that makes those windows real, and nothing else.
 *
 * **It decides nothing.** The cooldown arithmetic is `memoryFromPersisted`'s, the suppression is
 * `hardSuppression`'s, and the correction lineage is `standingAnswers`'. What happens here is
 * five requests and the rename between the wire's `snake_case` and the runtime's `camelCase`. A
 * client that recomputed a window would be a third implementation of a rule that already has one
 * and is already tested.
 *
 * **The workspace and the actor are never in a body.** Memory is per person: two people sharing a
 * workspace have not had the same conversation, and a client that could name whose memory it
 * wanted would be a client that could read somebody else's. Both come from the session behind the
 * bearer token, on every route, and nothing below sends either.
 *
 * **A correction supersedes and never edits.** There is no PUT here and there is not going to be
 * one. 5.4 fixes that "Nothing is ever silently rewritten": a person saying the answer was wrong
 * is the single most valuable thing in this store, and an update that overwrote the wrong answer
 * would destroy the evidence that the system had been wrong, which is the one record a correction
 * exists to create. `correct` posts a new row naming what it replaces. `withdraw` is the other
 * verb, and it takes the whole lineage rather than one row of it: a correction left standing
 * after its subject was withdrawn would quote the withdrawn answer inside its own text.
 */

import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';
import type {
  AbstentionCode,
  AnswerOrigin,
  EscapeKind,
  Intent,
  PersistedAnswer,
  PersistedCitation,
  PersistedEscape,
  PersistedMemory,
} from '@exulanica/companion-runtime';
import type { CompanionAnswer } from './companion-ask-api.js';

/**
 * An ordinary indexed read, and the deadline says so.
 *
 * `companion-ask-api.ts` waits three minutes because the reasoning core has been measured in tens
 * of seconds on a packet. Nothing on these routes composes anything: the session-open read is one
 * index lookup on `(workspace_id, actor_id, asked_at desc)`. Inheriting the composer's patience
 * here would mean a person waiting three minutes at mount to find out the memory service is down.
 */
const MEMORY_TIMEOUT_MS = 20_000;

/** What the route serves when nobody asked for a number, and the bound it will not exceed. */
const DEFAULT_LIMIT = 50;
const MAX_LIMIT = 200;

const ABSTENTIONS: readonly string[] = [
  'UNANSWERABLE_NOT_CAPTURED',
  'UNANSWERABLE_AMBIGUOUS',
  'UNANSWERABLE_NOT_IN_MODALITY',
  'UNANSWERABLE_NOT_UNDERSTOOD',
];

/** The four escapes of 4.3, spelled as `companion-runtime` spells them. See `escapeOf`. */
const ESCAPES: readonly string[] = ['not_sure', 'skip', 'later', 'wrong_question'];

export type MemoryFailure =
  /** The session is no longer allowed to read or write this person's memory. */
  | 'unauthenticated'
  /** The answer named by a correction or a withdrawal is not there, or is not this person's. */
  | 'unknown_reference'
  | 'refused'
  /** The server answered with something this client cannot read. See `asMs` and `escapeOf`. */
  | 'unreadable'
  /**
   * THIS client refused, and it is the only kind here that names a refusal of our own. An answer
   * whose cited photographs the packet could not locate cannot be stored with its citation set
   * intact, and that set is the join a withdrawal travels along. See `answerToRemember`.
   */
  | 'incomplete'
  | 'unreachable';

/**
 * A memory request that did not happen.
 *
 * Separate from `ApiError` because the surface says this out loud where it matters and "409" is
 * not a sentence, and because the two sides of it are different failures: a read that fails costs
 * the person a Companion that has forgotten them, and a write that fails costs them an answer
 * that was correct and is not kept. `detail` is the server's own wording, shown as it arrived.
 */
export class MemoryUnavailable extends Error {
  constructor(
    readonly kind: MemoryFailure,
    readonly detail: string,
  ) {
    super(detail);
    this.name = 'MemoryUnavailable';
  }
}

// -- what the server sends ----------------------------------------------------------------------

interface WireCitation {
  readonly span_id: string;
  readonly capture_id: string;
  readonly ordinal: number;
}

interface WireAnswer {
  readonly answer_id: string;
  readonly asked_at: string;
  readonly question: string;
  readonly answer_text: string;
  readonly abstained: string | null;
  readonly deterministic: boolean;
  readonly repaired: boolean;
  readonly served_model: string | null;
  readonly planned_by: string | null;
  readonly prompt_version: string;
  readonly latency_ms: number;
  readonly origin: string;
  readonly supersedes: string | null;
  readonly correction_note: string | null;
  readonly citations: readonly WireCitation[];
}

interface WireEscape {
  readonly escape_id: string;
  readonly taken_at: string;
  readonly escape: string;
  readonly intent: string;
  readonly entity_id: string | null;
  readonly turn_id: string;
}

interface WireRecent {
  readonly answers: readonly WireAnswer[];
  readonly escapes: readonly WireEscape[];
}

// -- what a caller hands over -------------------------------------------------------------------

/**
 * One answered question, as the answer path already has it.
 *
 * Every field is read off the response body that produced the sentence on the screen and none is
 * read off a manifest, which is `companion-question.md` 4's rule for exactly the case a record
 * derived from configuration reports wrongly and silently: `served_model` differs from the
 * requested one precisely when the fallback fired.
 */
export interface AnswerToRemember {
  readonly question: string;
  readonly answerText: string;
  readonly abstained: AbstentionCode | null;
  readonly deterministic: boolean;
  readonly repaired: boolean;
  readonly servedModel: string | null;
  readonly plannedBy: string | null;
  readonly promptVersion: string;
  /** A whole number of milliseconds. A float rewrites its own last digits on a JSON round trip. */
  readonly latencyMs: number;
  readonly citations: readonly PersistedCitation[];
}

/** One escape, as `CompanionSession` recorded it against the turn it was taken on. */
export interface EscapeToRemember {
  readonly escape: EscapeKind;
  readonly intent: Intent;
  readonly entityId: string | null;
  readonly turnId: string;
}

/** The person's own words about an answer that was wrong, and the answer that stands instead. */
export interface CorrectionToRemember {
  readonly answerText: string;
  readonly correctionNote: string | null;
}

// -- reading the wire -----------------------------------------------------------------------------

/**
 * An ISO instant as milliseconds, refusing rather than yielding `NaN`.
 *
 * This looks like defensiveness and is not. `asked_at` and `taken_at` become `notSureUntilMs` and
 * `skipUntilMs`, and `hardSuppression` asks `nowMs < until`. A `NaN` there compares false, so an
 * unreadable instant does not fail loudly: it silently produces a cooldown that suppresses
 * nothing, which is the exact failure this whole path exists to fix, wearing the disguise of a
 * memory that loaded successfully.
 */
function asMs(instant: string, field: string): number {
  const ms = Date.parse(instant);
  if (Number.isNaN(ms)) {
    throw new MemoryUnavailable(
      'unreadable',
      `The server described ${field} as ${instant}, which is not an instant.`,
    );
  }
  return ms;
}

/**
 * The escape kind, refused when it is not one of the four.
 *
 * `recordEscape` switches over `EscapeKind` exhaustively and has no default branch, which is
 * correct for a closed set and is why an unrecognised value may not be allowed to reach it: the
 * switch would fall through, the fold would take on `undefined` as its memory, and the failure
 * would surface later and somewhere else. The set is closed by 4.3 and by the migration's own
 * enum, so a fifth value means client and server disagree and saying so is the useful move.
 */
function escapeOf(kind: string): EscapeKind {
  if (!ESCAPES.includes(kind)) {
    throw new MemoryUnavailable('unreadable', `The server described an escape as ${kind}.`);
  }
  return kind as EscapeKind;
}

/**
 * The intent, taken as it arrived even when this build does not know the name.
 *
 * Deliberately NOT refused, unlike the escape kind, and the asymmetry is worth stating. An intent
 * this client has never heard of cannot crash anything: `questionKey` is a string pair, and an
 * unknown one simply matches no question. Two of the three effects survive intact anyway, because
 * `notSureUntilMs` and `skipUntilMs` are keyed on the ENTITY alone, so a Skip carrying an intent
 * from a newer server still suppresses that entity for its seven days. Only the wrong-question
 * signal, which is keyed on the pair, would go unmatched. Refusing the whole response over one
 * unrecognised name would trade a memory that is slightly incomplete for no memory at all, which
 * is the worse of the two on every question the person already answered.
 */
function intentOf(intent: string): Intent {
  return intent as Intent;
}

function citationOf(wire: WireCitation): PersistedCitation {
  return Object.freeze({
    spanId: wire.span_id,
    captureId: wire.capture_id,
    ordinal: wire.ordinal,
  });
}

function answerOf(wire: WireAnswer): PersistedAnswer {
  const abstained = wire.abstained;
  return Object.freeze({
    answerId: wire.answer_id,
    askedAtMs: asMs(wire.asked_at, 'asked_at'),
    question: wire.question,
    answerText: wire.answer_text,
    // An abstention code this build does not know is read as "answered", because the alternative
    // is worse: `abstention.<code>` has no sentence in the copy table, so an unmapped code would
    // put the raw identifier on the screen underneath somebody's answer.
    abstained: (ABSTENTIONS.includes(abstained ?? '') ? abstained : null) as AbstentionCode | null,
    deterministic: wire.deterministic === true,
    repaired: wire.repaired === true,
    servedModel: wire.served_model,
    plannedBy: wire.planned_by,
    promptVersion: wire.prompt_version,
    latencyMs: wire.latency_ms,
    origin: (wire.origin === 'correction' ? 'correction' : 'asked') as AnswerOrigin,
    supersedes: wire.supersedes,
    correctionNote: wire.correction_note,
    citations: Object.freeze((wire.citations ?? []).map(citationOf)),
  });
}

function escapeRowOf(wire: WireEscape): PersistedEscape {
  return Object.freeze({
    escapeId: wire.escape_id,
    takenAtMs: asMs(wire.taken_at, 'taken_at'),
    escape: escapeOf(wire.escape),
    intent: intentOf(wire.intent),
    entityId: wire.entity_id,
    turnId: wire.turn_id,
  });
}

function asMemoryFailure(error: unknown): MemoryUnavailable {
  if (error instanceof MemoryUnavailable) return error;
  if (error instanceof ApiError) {
    if (error.isUnauthenticated) return new MemoryUnavailable('unauthenticated', error.message);
    // One code for "not there" and for "not yours", deliberately, so the route is not an
    // existence oracle. The client does not get to reconstruct the distinction the server refuses
    // to make, so both arrive here as the same kind.
    if (error.code === 'unknown_reference' || error.isNotFound) {
      return new MemoryUnavailable('unknown_reference', error.message);
    }
    return new MemoryUnavailable('refused', error.message);
  }
  // A timeout, a dropped connection, or a proxy that answered with nothing. What the surface
  // needs to know is that the request did not arrive, not which layer dropped it.
  return new MemoryUnavailable(
    'unreachable',
    error instanceof Error ? error.message : String(error),
  );
}

export class CompanionMemoryClient {
  readonly #where: TransportOptions;

  constructor(options: TransportOptions) {
    // Narrowed to the fields a request needs, and `fetch` is spread conditionally because
    // `exactOptionalPropertyTypes` is on: an absent option and one set to `undefined` are
    // different types. An inherited `signal` is dropped deliberately; see `#transport`.
    this.#where = options.fetch === undefined
      ? { baseUrl: options.baseUrl, token: options.token }
      : { baseUrl: options.baseUrl, token: options.token, fetch: options.fetch };
  }

  /**
   * A transport with a deadline, built PER REQUEST.
   *
   * `AbortSignal.timeout` starts counting the moment it is created, and a `Transport` holds one
   * signal for its lifetime. A signal built in this constructor would therefore be one stopwatch
   * started at mount: the session-open read would work, and every answer written back more than
   * twenty seconds into the session would abort before it left the browser. The symptom is a
   * Companion that remembers the first thing you asked and nothing after it, on a client whose
   * only fault is a field initialised in the wrong place.
   */
  #transport(): Transport {
    return new Transport({ ...this.#where, signal: AbortSignal.timeout(MEMORY_TIMEOUT_MS) });
  }

  /**
   * What this person has already said, newest first.
   *
   * The one request the session open pays for. `limit` is clamped here rather than sent as the
   * caller wrote it: the route's bound is 1 to 200 and a client that posted 500 would be told no,
   * which turns a caller's arithmetic slip into a Companion with no memory.
   */
  async recent(limit: number = DEFAULT_LIMIT): Promise<PersistedMemory> {
    const bounded = Math.max(1, Math.min(MAX_LIMIT, Math.trunc(limit)));
    let wire: WireRecent;
    try {
      wire = await this.#transport().getJson<WireRecent>('/companion/memory/recent', {
        limit: String(bounded),
      });
    } catch (error) {
      throw asMemoryFailure(error);
    }
    // Read outside the try, so a body this client cannot parse is reported as `unreadable` rather
    // than being caught by the handler that turns everything into `unreachable`.
    return Object.freeze({
      answers: Object.freeze((wire.answers ?? []).map(answerOf)),
      escapes: Object.freeze((wire.escapes ?? []).map(escapeRowOf)),
    });
  }

  /** Keep one answered question. Returns the stored row, which carries the id a correction needs. */
  async rememberAnswer(answer: AnswerToRemember): Promise<PersistedAnswer> {
    return answerOf(await this.#post<WireAnswer>('/companion/memory/answers', {
      question: answer.question,
      answer_text: answer.answerText,
      abstained: answer.abstained,
      deterministic: answer.deterministic,
      repaired: answer.repaired,
      served_model: answer.servedModel,
      planned_by: answer.plannedBy,
      prompt_version: answer.promptVersion,
      latency_ms: Math.round(answer.latencyMs),
      citations: answer.citations.map((citation) => ({
        span_id: citation.spanId,
        capture_id: citation.captureId,
        ordinal: citation.ordinal,
      })),
    }));
  }

  /** Keep one escape, which is what a cooldown is made of. */
  async rememberEscape(escape: EscapeToRemember): Promise<PersistedEscape> {
    return escapeRowOf(await this.#post<WireEscape>('/companion/memory/escapes', {
      escape: escape.escape,
      intent: escape.intent,
      entity_id: escape.entityId,
      turn_id: escape.turnId,
    }));
  }

  /**
   * Say that an answer was wrong, and what stands instead.
   *
   * Returns the NEW row rather than the corrected one. The old answer is still in the store and
   * still says what it said; what changed is which of the two a reader is shown, and that is what
   * `standingAnswers` resolves from the lineage the returned row names.
   */
  async correct(answerId: string, correction: CorrectionToRemember): Promise<PersistedAnswer> {
    return answerOf(await this.#post<WireAnswer>(
      `/companion/memory/answers/${encodeURIComponent(answerId)}/corrections`,
      { answer_text: correction.answerText, correction_note: correction.correctionNote },
    ));
  }

  /**
   * Withdraw an answer and every correction of it.
   *
   * The whole lineage, because half of one is not a deletion: a correction that outlived its
   * subject would quote the withdrawn answer inside its own text, and the person who asked for
   * the answer to go would find it still on the screen wearing the correction's name.
   */
  async withdraw(answerId: string): Promise<void> {
    try {
      await this.#transport().delete(
        `/companion/memory/answers/${encodeURIComponent(answerId)}`,
      );
    } catch (error) {
      throw asMemoryFailure(error);
    }
  }

  async #post<T>(path: string, body: unknown): Promise<T> {
    try {
      return await this.#transport().postJson<T>(path, body);
    } catch (error) {
      throw asMemoryFailure(error);
    }
  }
}

/**
 * An answer the surface has drawn, as the row that keeps it.
 *
 * **An answer whose cited photographs the packet could not locate is not kept at all**, and this
 * is the one place that decides so. `companion-ask-api.ts` renders such a citation as a chip that
 * cannot open, which is the honest thing to do on screen; storing the answer anyway would be a
 * different and worse thing, because the citation set is the join a withdrawal travels along.
 * `companion_answer_citation` is what a capture tombstone reaches an answer through, so an answer
 * stored with a hole in that set is an answer describing somebody's photograph that the deletion
 * of that photograph cannot reach. `domain-and-evidence-model.md` 6.4 names that failure exactly:
 * "Without the recorded set, the name survives its own deletion inside a caption."
 *
 * Dropping the unlocatable citations and keeping the rest would be the same defect wearing a
 * tidier shape. Refusing costs one unstored answer that the person can ask for again, and it is
 * said out loud rather than swallowed.
 */
export function answerToRemember(answer: CompanionAnswer): AnswerToRemember {
  const citations: PersistedCitation[] = [];
  answer.evidence.forEach((evidence, index) => {
    if (evidence.handle === null || evidence.captureId === null) {
      throw new MemoryUnavailable(
        'incomplete',
        `this answer cites ${evidence.uri}, which the packet did not locate`,
      );
    }
    citations.push({ spanId: evidence.handle, captureId: evidence.captureId, ordinal: index });
  });
  return {
    question: answer.question,
    answerText: answer.text,
    abstained: answer.abstained,
    deterministic: answer.deterministic,
    repaired: answer.repaired,
    // The identifier that WROTE the sentence, off the response body. Null in the discarded,
    // search and unreadable provenance cases, where a sentence reached the screen that no model
    // wrote, and null there is a fact rather than a gap.
    servedModel: answer.provenance.servedModel,
    plannedBy: answer.provenance.plannedBy,
    promptVersion: answer.promptVersion,
    // What the person actually waited for, which is every call added up rather than the composer
    // alone. A whole number already, because the route reports whole milliseconds.
    latencyMs: answer.provenance.latencyMs,
    citations,
  };
}

/**
 * A remembered answer, in the shape the surface already knows how to draw.
 *
 * The inverse of `answerToRemember`, and it is deliberately lossy in one direction: the clause
 * breakdown and the per-request citation tokens are NOT stored and are not reconstructed here.
 *
 * Tokens could not be reconstructed even in principle. Their namespaces are drawn fresh per
 * request, so a token from the request that produced this answer resolves in no later one; the
 * span is what was stored and the span is what `/evidence/{span}/masked` opens, which is the
 * only thing a chip needs. The tokens minted below are local labels for the chips and are joined
 * to nothing.
 *
 * The clause breakdown is a real loss and is stated rather than hidden. A restored answer is one
 * `historical` clause carrying the whole sentence, because what was stored is the paragraph the
 * person read. Storing the clauses would let the restored copy be re-validated later, which
 * nothing does today; storing the paragraph is what makes the restored answer say exactly what
 * the original said.
 */
export function rememberedAsAnswer(remembered: PersistedAnswer): CompanionAnswer {
  const evidence = remembered.citations.map((citation) => ({
    token: `REMEMBERED-${citation.ordinal}`,
    // The permalink is not stored, so a restored chip is addressed by span alone. Nothing joins
    // on this value: `EvidenceCache` opens by handle.
    uri: `exulanica://span/${citation.spanId}`,
    handle: citation.spanId,
    captureId: citation.captureId,
    capturedAt: null,
  }));
  return {
    question: remembered.question,
    clauses: [
      { text: remembered.answerText, type: 'historical', citations: evidence.map((e) => e.token) },
    ],
    text: remembered.answerText,
    abstained: remembered.abstained,
    deterministic: remembered.deterministic,
    repaired: remembered.repaired,
    evidence,
    provenance: {
      // A correction has no composing model, and a restored one must not borrow the model that
      // wrote the sentence it replaced. `servedModel` null is what the provenance line reads as
      // "no model wrote this", which is true of a correction and is the honest thing to show.
      composed: remembered.servedModel === null ? 'none' : 'model',
      servedModel: remembered.servedModel,
      plannedBy: remembered.plannedBy,
      latencyMs: remembered.latencyMs,
      // Not stored, because it is a property of the request rather than of the answer, and a
      // restored answer made no request. False is the honest default: it claims nothing.
      usedFallback: false,
    },
    promptVersion: remembered.promptVersion,
    // Empty, and this is the one that must not be faked. `calls` is the record of what was
    // executed, and a restored answer executed nothing. An invented entry here would put a
    // latency and a token count into the execution block for a call that never happened.
    calls: [],
  };
}
