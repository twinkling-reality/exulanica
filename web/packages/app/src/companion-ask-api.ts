/**
 * Asking the library a question in words, and getting back an answer that cites its evidence.
 *
 * This is the browser's half of `POST /selection/ask`, which existed and which no browser code
 * called. Every Companion utterance in the product was a string from the copy table; the answer
 * path was reachable only with a terminal. So this file is not a refactor of an existing call,
 * it is the first caller.
 *
 * **It reads and it cannot write.** There is no proposal here, no draft, no gate and no route to
 * one: `ProposalGate` lives behind `session.ts` and is never handed out, and nothing this module
 * returns is accepted by anything that stages. `interaction-model.md` 4.3 fixes that "NO
 * FREE-TEXT ANSWER ... EVER MUTATES THE GRAPH DIRECTLY", and free text that turns out to be a
 * question must not become the exception that proves it.
 *
 * **Two requests, and the second one is a consent boundary rather than a convenience.** The
 * answer names its evidence with per-request citation TOKENS, which resolve only inside the
 * response that minted them; `EvidenceCache` opens a photograph by SPAN ID, through
 * `/evidence/{span}/masked`, which is the path that returns the masked derivative when somebody
 * in the frame is hidden and refuses outright when a mask is required and missing. The permalink
 * route `GET /evidence?uri=` would resolve the same citation and would return the ORIGINAL
 * bytes, so pointing a chip at it would be the last path by which an unconsented person reached
 * a viewer's screen. `POST /selection/packet` is what carries both the permalink and the span
 * id, so it is what turns a token into something openable.
 *
 * The two responses are joined on the PERMALINK and never on the token. Token namespaces are
 * random per request, so the packet's tokens are not the answer's tokens and matching them would
 * silently resolve nothing. The permalink is stable for the same evidence, which is what makes
 * it the key.
 *
 * **A failure is reported, never substituted.** A 503 from an instance with no model credential
 * and a request that did not arrive are different facts, and both of them are different from an
 * answer. Nothing here falls back to a sentence from the copy table dressed as a reply.
 */

import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';
import type { EvidenceHandle } from '@exulanica/graph-client';

/** Long enough for the reasoning core, which has been measured at tens of seconds on a packet. */
const ASK_TIMEOUT_MS = 180_000;

/** Locating the cited photographs is a second question; it must not hold the answer hostage. */
const PACKET_TIMEOUT_MS = 20_000;

export type ClauseType = 'historical' | 'uncertain' | 'meta';

/**
 * The three abstention codes, carried through rather than collapsed.
 *
 * `evaluation-methodology.md` M3: merging them "lets a system that always says 'I don't know'
 * score perfectly". They are distinct in the response and they stay distinct here.
 */
export type Abstention =
  | 'UNANSWERABLE_NOT_CAPTURED'
  | 'UNANSWERABLE_AMBIGUOUS'
  | 'UNANSWERABLE_NOT_IN_MODALITY';

export interface AnswerClause {
  readonly text: string;
  readonly type: ClauseType;
  readonly citations: readonly string[];
}

/** One cited photograph, and the handle that opens it through the masked evidence route. */
export interface AnswerEvidence {
  readonly token: string;
  readonly uri: string;
  /** Null when the packet did not name a span for this permalink. The chip then says so. */
  readonly handle: EvidenceHandle | null;
  readonly capturedAt: string | null;
}

export interface ModelCall {
  readonly role: string;
  readonly requestedModel: string;
  readonly servedModel: string;
  readonly usedFallback: boolean;
  readonly attempts: number;
  readonly latencyMs: number;
  readonly promptTokens: number | null;
  readonly completionTokens: number | null;
  readonly reasoningTokens: number | null;
}

/**
 * Who wrote the sentence on the screen, which is not always a model.
 *
 * `discarded` is the case worth naming. `architecture-overview.md` 5.3 makes the deterministic
 * answer "a first-class output, not an error page": when the composer fails validation twice its
 * output is thrown away and the answer is rendered from the query result. That answer is correct
 * and cited, and it was not written by the model whose name the call list carries, so a
 * provenance line that named the model anyway would be attributing a sentence to something that
 * did not write it.
 */
export type Composed = 'model' | 'discarded' | 'search' | 'none';

export interface AnswerProvenance {
  readonly composed: Composed;
  /** The identifier that WROTE the sentence, from the response body. Null when none did. */
  readonly servedModel: string | null;
  /** The identifier that turned the question into a Selection, when one was asked. */
  readonly plannedBy: string | null;
  /** Every call this answer made, added up. What the person actually waited for. */
  readonly latencyMs: number;
  readonly usedFallback: boolean;
}

export interface CompanionAnswer {
  readonly question: string;
  readonly clauses: readonly AnswerClause[];
  /** The clauses as one paragraph, which is what `architecture-overview.md` 5.3 renders. */
  readonly text: string;
  readonly abstained: Abstention | null;
  readonly deterministic: boolean;
  readonly repaired: boolean;
  readonly evidence: readonly AnswerEvidence[];
  readonly provenance: AnswerProvenance;
  readonly promptVersion: string;
  readonly calls: readonly ModelCall[];
}

export type AskFailure =
  /** The instance has no model credential. Every other route works; this one will not guess. */
  | 'no_model'
  | 'unauthenticated'
  | 'refused'
  | 'unreachable';

/**
 * A question that did not reach an answer, with the kind the surface branches on.
 *
 * Separate from `ApiError` because the encounter says this out loud where an answer would have
 * been, and "503" is not a sentence. `detail` is the server's own wording and is shown as it
 * arrived: the API authors that sentence and this file does not get to improve it.
 */
export class AskUnavailable extends Error {
  constructor(
    readonly kind: AskFailure,
    readonly detail: string,
  ) {
    super(detail);
    this.name = 'AskUnavailable';
  }
}

// -- what the server sends ------------------------------------------------------------------

interface WireClause {
  readonly text: string;
  readonly type: string;
  readonly citations: readonly string[];
  readonly value_refs: readonly string[];
}

interface WireCall {
  readonly role: string;
  readonly requested_model: string;
  readonly served_model: string;
  readonly used_fallback: boolean;
  readonly attempts: number;
  readonly latency_ms: number;
  readonly prompt_tokens: number | null;
  readonly completion_tokens: number | null;
  readonly reasoning_tokens: number | null;
}

interface WireAnswer {
  readonly answer: { readonly clauses: readonly WireClause[] };
  readonly plan: unknown;
  readonly citations: Readonly<Record<string, string>>;
  readonly abstained: string | null;
  readonly deterministic: boolean;
  readonly repaired: boolean;
  readonly execution: { readonly prompt_version: string; readonly calls: readonly WireCall[] };
}

interface WirePacketItem {
  readonly token: string;
  readonly uri: string;
  readonly span_id: string;
  readonly captured_at: string | null;
}

interface WirePacket {
  readonly items: readonly WirePacketItem[];
}

const CLAUSE_TYPES: readonly string[] = ['historical', 'uncertain', 'meta'];
const ABSTENTIONS: readonly string[] = [
  'UNANSWERABLE_NOT_CAPTURED',
  'UNANSWERABLE_AMBIGUOUS',
  'UNANSWERABLE_NOT_IN_MODALITY',
];

export interface CompanionAskOptions extends TransportOptions {
  /** Injectable so a test drives the whole path without a server and without a global. */
  readonly now?: () => number;
}

export class CompanionAskClient {
  readonly #where: CompanionAskOptions;

  constructor(options: CompanionAskOptions) {
    this.#where = options;
  }

  /**
   * A transport with a deadline, built PER REQUEST.
   *
   * `AbortSignal.timeout` starts counting the moment it is created, and a `Transport` holds one
   * signal for its lifetime. Two transports built in this constructor would therefore be two
   * stopwatches started at mount: the first question would work, and every question asked more
   * than three minutes into the session would abort before it left the browser, on a client
   * whose only symptom is that asking stopped working after a while.
   *
   * Two deadlines rather than one, because the two requests are not the same kind of wait. The
   * composer has been measured in TENS OF SECONDS on this chain; locating the cited photographs
   * afterwards is an ordinary indexed read and must not inherit that patience.
   */
  #transport(timeoutMs: number): Transport {
    return new Transport({ ...this.#where, signal: AbortSignal.timeout(timeoutMs) });
  }

  /**
   * Ask, then locate what the answer cited.
   *
   * The second request is allowed to fail on its own. An answer whose evidence could not be
   * located is still an answer and still says what it says; what it must not do is offer a chip
   * that opens nothing, so those entries carry a null handle and the surface renders them as
   * unavailable rather than pretending.
   */
  async ask(question: string): Promise<CompanionAnswer> {
    let body: WireAnswer;
    try {
      body = await this.#transport(ASK_TIMEOUT_MS).postJson<WireAnswer>('/selection/ask', {
        question,
      });
    } catch (error) {
      throw asAskFailure(error);
    }

    const clauses = (body.answer?.clauses ?? []).map(
      (clause): AnswerClause => ({
        text: clause.text,
        type: (CLAUSE_TYPES.includes(clause.type) ? clause.type : 'uncertain') as ClauseType,
        citations: [...(clause.citations ?? [])],
      }),
    );

    // Asked only when a clause actually cited something. An answer that cited nothing has no
    // photograph to locate, and asking the packet route what it points at would be a query
    // whose answer is already known.
    const cited = clauses.some((clause) => clause.citations.length > 0);
    const spans = cited
      ? await this.#spansByUri(body.plan)
      : new Map<string, { handle: EvidenceHandle; capturedAt: string | null }>();

    /*
     * Only what the answer actually CITED, and one chip per photograph.
     *
     * Two things make the obvious version wrong. `citations` is a map over every item in the
     * packet, cited or not, so appending all of it would offer chips for photographs no clause
     * points at. And `build_packet` mints a token per `(span_id, assertion_id)` pair while the
     * permalink is derived from the span alone, so one photograph carrying a caption and an
     * entity link arrives as several tokens with ONE permalink: deduping by token would show
     * the same photograph three times, each chip opening the same bytes.
     *
     * Ordered by first mention, so the first chip is the first photograph the sentence points
     * at. Packet order is the server's token-minting order, which is not reading order.
     */
    const seen = new Set<string>();
    const evidence: AnswerEvidence[] = [];
    for (const token of clauses.flatMap((clause) => clause.citations)) {
      const uri = body.citations[token];
      if (uri === undefined || seen.has(uri)) continue;
      seen.add(uri);
      const span = spans.get(uri);
      evidence.push({
        token,
        uri,
        handle: span?.handle ?? null,
        capturedAt: span?.capturedAt ?? null,
      });
    }

    const calls = (body.execution?.calls ?? []).map(
      (call): ModelCall => ({
        role: call.role,
        requestedModel: call.requested_model,
        servedModel: call.served_model,
        usedFallback: call.used_fallback,
        attempts: call.attempts,
        latencyMs: call.latency_ms,
        promptTokens: call.prompt_tokens,
        completionTokens: call.completion_tokens,
        reasoningTokens: call.reasoning_tokens,
      }),
    );

    const abstained = body.abstained;
    return {
      question,
      clauses,
      text: clauses.map((clause) => clause.text).join(' '),
      abstained: (ABSTENTIONS.includes(abstained ?? '') ? abstained : null) as Abstention | null,
      deterministic: body.deterministic === true,
      repaired: body.repaired === true,
      evidence,
      provenance: provenanceOf(calls, body.deterministic === true),
      promptVersion: body.execution?.prompt_version ?? '',
      calls,
    };
  }

  /**
   * The permalink-to-span map for one plan, or an empty map.
   *
   * The plan is echoed by the answer and posted back verbatim: `POST /selection/packet` runs the
   * same validator and the same executor, so this asks the server what the answer's own
   * Selection resolved to rather than reconstructing it here.
   */
  async #spansByUri(
    plan: unknown,
  ): Promise<ReadonlyMap<string, { handle: EvidenceHandle; capturedAt: string | null }>> {
    const located = new Map<string, { handle: EvidenceHandle; capturedAt: string | null }>();
    if (plan === null || typeof plan !== 'object') return located;
    try {
      const packet = await this.#transport(PACKET_TIMEOUT_MS).postJson<WirePacket>(
        '/selection/packet',
        plan,
      );
      for (const item of packet.items ?? []) {
        if (!located.has(item.uri)) {
          located.set(item.uri, { handle: item.span_id, capturedAt: item.captured_at });
        }
      }
    } catch {
      // Reported by absence rather than by throwing. The answer is already in hand and it is
      // the thing the person asked for; a chip that cannot open renders as one that cannot.
    }
    return located;
  }
}

/**
 * Who did what, from the call list alone.
 *
 * **The four cases are four different sentences and collapsing any two of them prints a lie.**
 * This function got that wrong in a way worth recording, because the wrong version looked
 * obviously right: it treated "no composing model in the list" as "no model was asked".
 *
 * The browser never sends a plan, so `answer_question` ALWAYS runs the planner first and always
 * records it. On a question that matches nothing the packet is empty, the composer is never
 * called, and the list holds exactly one `structured_extraction` call. The old branch found no
 * `reasoning` call, returned a null model, and the speech band printed "No model was asked" over
 * an answer a model had just been asked to plan. Every abstention through the interface said it.
 *
 * `search` is that case, named. A model read the question; the answer under it was rendered from
 * the query result, and the line says both.
 */
function provenanceOf(calls: readonly ModelCall[], deterministic: boolean): AnswerProvenance {
  const latencyMs = calls.reduce((total, call) => total + call.latencyMs, 0);
  const usedFallback = calls.some((call) => call.usedFallback);
  // The composing call is the LAST reasoning call rather than the first: a repair replaces the
  // attempt before it, and it is the repair whose sentence is on the screen.
  const composing = [...calls].reverse().find((call) => call.role.startsWith('reasoning')) ?? null;
  const planning = calls.find((call) => !call.role.startsWith('reasoning')) ?? null;
  const plannedBy = planning?.servedModel ?? null;

  if (calls.length === 0) {
    return { composed: 'none', servedModel: null, plannedBy: null, latencyMs, usedFallback };
  }
  if (deterministic) {
    // Asked, answered, and the answer was not supported by the evidence. `servedModel` may still
    // be null here: a composer whose reply the endpoint truncated raises before any result
    // reaches the recorder, so the call that failed is not in the list.
    return {
      composed: 'discarded',
      servedModel: composing?.servedModel ?? null,
      plannedBy,
      latencyMs,
      usedFallback,
    };
  }
  if (composing === null) {
    return { composed: 'search', servedModel: null, plannedBy, latencyMs, usedFallback };
  }
  return {
    composed: 'model',
    servedModel: composing.servedModel,
    plannedBy,
    latencyMs,
    usedFallback,
  };
}

function asAskFailure(error: unknown): AskUnavailable {
  if (error instanceof ApiError) {
    if (error.status === 503) return new AskUnavailable('no_model', error.message);
    if (error.isUnauthenticated) return new AskUnavailable('unauthenticated', error.message);
    return new AskUnavailable('refused', error.message);
  }
  // A timeout, a dropped connection, or a proxy that answered with nothing. The distinction the
  // person needs is that the question did not arrive, not which layer dropped it.
  return new AskUnavailable('unreachable', error instanceof Error ? error.message : String(error));
}
