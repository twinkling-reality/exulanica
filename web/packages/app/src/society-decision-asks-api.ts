/**
 * A person's recorded decisions asked again (migration 0216's asks, docs/decision-roles-contract.md,
 * "The same decision, asked of another model"): what asking them again would be, one ask, and every
 * answer beside an original. An ask is sent the identical request the original model read and its
 * answer is kept beside the original, never applied.
 *
 * - `offer` reads `GET .../society/people/{subject_id}/asks-again?model=P/M`: the person's last
 *   answered decisions (at most the server's `most`), or the one decision `requestId` names at any
 *   age, each with the least bound of an ask of the chosen model and of an ask once more of the
 *   model that answered it, and `mostUsd`, the most it all can cost. It asks nothing.
 * - `ask` posts one ask under the bound the offer named; a repeated idempotency key answers the first.
 * - `read` reads the original answer and every ask of one decision.
 *
 * A refusal arrives as the transport's error with the server's code.
 */
import { Transport, type TransportOptions } from '@exulanica/graph-client';
import { openWorldPath } from './world-scope.js';

export interface AskedModel {
  readonly provider: string;
  readonly modelId: string;
}

/** One recorded decision as the offer states it. */
export interface OfferedDecision {
  readonly requestId: string;
  readonly baseTick: number | null;
  /** The model that answered it; null where the record names none. */
  readonly model: AskedModel | null;
  readonly chose: string | null;
  readonly line: string | null;
  /** The least bound of each ask, decimal strings; null where it cannot be asked again. */
  readonly askUsd: { readonly chosen: string; readonly again: string | null } | null;
  /** Why it cannot be asked again, by code, or null. */
  readonly refusal: string | null;
  /** Why it cannot be asked once more of its own model, by code, or null. */
  readonly againRefusal: string | null;
}

export interface AskAgainOffer {
  readonly most: number;
  readonly model: AskedModel;
  /** Why the chosen model may not be asked here, by code; nothing is then offered. */
  readonly refusal: string | null;
  /** Oldest first. */
  readonly decisions: readonly OfferedDecision[];
  readonly askable: number;
  readonly mostUsd: string;
}

/** What one answer chose and what it cost. */
export interface DecisionAnswer {
  readonly provider: string | null;
  readonly modelId: string | null;
  readonly status: string | null;
  readonly reason: string | null;
  readonly chose: string | null;
  readonly kind: string | null;
  readonly line: string | null;
  readonly costUsd: string | null;
  readonly costKnown: boolean | null;
  readonly latencyMs: number | null;
}

/** One ask beside its original. */
export interface DecisionAsk extends DecisionAnswer {
  readonly askId: string;
  readonly sameChoice: boolean;
  readonly sameKind: boolean;
  readonly sameMessages: boolean;
  readonly boundUsd: string;
  readonly askedAt: string;
}

export interface DecisionAsks {
  readonly requestId: string;
  readonly baseTick: number | null;
  readonly original: DecisionAnswer;
  /** Oldest first. */
  readonly asks: readonly DecisionAsk[];
}

type Held = Readonly<Record<string, unknown>>;

const invalid = (): never => { throw new Error('Invalid decision asks response'); };
const object = (value: unknown): Held =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Held : invalid();
const text = (value: unknown): string => (typeof value === 'string' && value !== '' ? value : invalid());
const maybeText = (value: unknown): string | null => (value === null || value === undefined ? null : text(value));
const usd = (value: unknown): string => (typeof value === 'string' && /^\d+(\.\d+)?$/.test(value) ? value : invalid());
const maybeUsd = (value: unknown): string | null => (value === null || value === undefined ? null : usd(value));
const whole = (value: unknown): number => (Number.isSafeInteger(value) && (value as number) >= 0 ? value as number : invalid());
const maybeWhole = (value: unknown): number | null => (value === null || value === undefined ? null : whole(value));
const flag = (value: unknown): boolean => (typeof value === 'boolean' ? value : invalid());
const maybeFlag = (value: unknown): boolean | null => (value === null || value === undefined ? null : flag(value));
const list = (value: unknown): readonly unknown[] => (Array.isArray(value) ? value : invalid());

function offered(value: unknown): OfferedDecision {
  const held = object(value);
  const provider = maybeText(held['provider']), modelId = maybeText(held['model_id']);
  const ask = held['ask_usd'] === null ? null : object(held['ask_usd']);
  return {
    requestId: text(held['request_id']),
    baseTick: maybeWhole(held['base_tick']),
    model: provider !== null && modelId !== null ? { provider, modelId } : null,
    chose: maybeText(held['chose']),
    line: maybeText(held['line']),
    askUsd: ask === null ? null : { chosen: usd(ask['chosen']), again: maybeUsd(ask['again']) },
    refusal: maybeText(held['refusal']),
    againRefusal: maybeText(held['again_refusal']),
  };
}

/** The offer as the server states it; any other shape is refused. */
export function parseAskAgainOffer(value: unknown): AskAgainOffer {
  const held = object(value);
  const model = object(held['model']);
  const decisions = list(held['decisions']).map(offered);
  const askable = whole(held['askable']);
  if (askable !== decisions.filter((decision) => decision.askUsd !== null).length) invalid();
  return {
    most: whole(held['most']),
    model: { provider: text(model['provider']), modelId: text(model['model_id']) },
    refusal: maybeText(held['refusal']),
    decisions,
    askable,
    mostUsd: usd(held['most_usd']),
  };
}

function answer(held: Held): DecisionAnswer {
  return {
    provider: maybeText(held['provider']),
    modelId: maybeText(held['model_id']),
    status: maybeText(held['status']),
    reason: maybeText(held['reason']),
    chose: maybeText(held['chose']),
    kind: maybeText(held['kind']),
    line: maybeText(held['line']),
    costUsd: maybeUsd(held['cost_usd']),
    costKnown: maybeFlag(held['cost_known']),
    latencyMs: maybeWhole(held['latency_ms']),
  };
}

/** One ask as the server states it. */
export function parseDecisionAsk(value: unknown): DecisionAsk {
  const held = object(value);
  return {
    ...answer(held),
    askId: text(held['ask_id']),
    sameChoice: flag(held['same_choice']),
    sameKind: flag(held['same_kind']),
    sameMessages: flag(held['same_messages']),
    boundUsd: usd(held['bound_usd']),
    askedAt: text(held['asked_at']),
  };
}

/** One decision's original answer and its asks. */
export function parseDecisionAsks(value: unknown): DecisionAsks {
  const held = object(value);
  return {
    requestId: text(held['request_id']),
    baseTick: maybeWhole(held['base_tick']),
    original: answer(object(held['original'])),
    asks: list(held['asks']).map(parseDecisionAsk),
  };
}

export interface DecisionAsksClientOptions extends TransportOptions {
  readonly worldId: string | null;
}

export class DecisionAsksClient {
  readonly #transport: Transport;
  readonly #worldId: string | null;

  constructor(options: DecisionAsksClientOptions) {
    this.#transport = new Transport(options);
    this.#worldId = options.worldId;
  }

  #path(versionId: string, suffix: string): string {
    return openWorldPath(`/world/versions/${encodeURIComponent(versionId)}/society${suffix}`, this.#worldId, 'the asked decisions for this world');
  }

  /** What asking the person's last answered decisions (or the one `requestId` names) again of `model` would be; asks nothing. */
  async offer(versionId: string, subjectId: string, model: AskedModel, requestId: string | null = null): Promise<AskAgainOffer> {
    return this.#transport.getJson<unknown>(this.#path(versionId, `/people/${encodeURIComponent(subjectId)}/asks-again`), {
      model: `${model.provider}/${model.modelId}`,
      ...(requestId === null ? {} : { request_id: requestId }),
    }).then(parseAskAgainOffer);
  }

  /** Ask `model` one recorded decision again, once, under `boundUsd`. */
  async ask(versionId: string, requestId: string, model: AskedModel, boundUsd: string, idempotencyKey: string): Promise<DecisionAsk> {
    return this.#transport.postJson<unknown>(this.#path(versionId, `/decisions/${encodeURIComponent(requestId)}/asks`), {
      model: { provider: model.provider, model_id: model.modelId },
      bound_usd: boundUsd,
      idempotency_key: idempotencyKey,
    }).then(parseDecisionAsk);
  }

  /** The original answer of one recorded decision and every ask beside it. */
  async read(versionId: string, requestId: string): Promise<DecisionAsks> {
    return this.#transport.getJson<unknown>(this.#path(versionId, `/decisions/${encodeURIComponent(requestId)}/asks`))
      .then(parseDecisionAsks);
  }
}
