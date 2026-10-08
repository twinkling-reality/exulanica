/**
 * Which model runs which people of a saved world, read and chosen by the world's owner.
 *
 * Speaks `/world/versions/{id}/society/models` (`exulanica/api/routes/society_models.py`). Neither
 * request asks a model: the host's playback asks, before a simulated minute, for a workspace its
 * environment lists, and the read says whether this host does. Every request names the open world.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import { openWorldPath } from './world-scope.js';

/** How a model was verified to answer a choice, by the probe the manifest names. */
export type AnsweringMechanism = 'tool_call' | 'json_schema';

/** A model, by the provider that serves it and its identifier there. */
export interface ModelRef {
  readonly provider: string;
  readonly modelId: string;
}

/**
 * A model a read mentions, with the name a person reads for it, as the server names it
 * (`Manifest.model_name` in `exulanica/models/manifest.py`) wherever the read mentions a model. The
 * Companion names a model by the same rule, so one model is never called two things.
 */
export interface NamedModelRef extends ModelRef {
  readonly name: string;
}

/** A model the server may ask for a person's decisions, and whether this process can ask it. */
export interface SocietyModel extends NamedModelRef {
  readonly description: string;
  readonly providerDescription: string;
  readonly mechanism: AnsweringMechanism;
  /**
   * What the manifest says the model costs, in US dollars per million input and output tokens, as
   * the decimal strings the server serves; null where a read names no price.
   */
  readonly price: ModelPrice | null;
  /** Why this process asks nothing its provider serves, by code, or null when it may. */
  readonly refusal: string | null;
}

/** A model's served price, in US dollars per million tokens, as decimal strings. */
export interface ModelPrice {
  readonly input: string;
  readonly output: string;
}

/**
 * Where a person's current choice comes from (`from`): their own (`choice`), or the mind named for a
 * gate's travellers (`travellers`); `_over_bound` where the world already runs as many minds as it
 * may, so their routine decides. Null from a server that predates the field.
 */
export type ChoiceSource = 'choice' | 'choice_over_bound' | 'travellers' | 'travellers_over_bound';

/** A person's current choice: a model, or null for their own routine. */
export interface PersonModelChoice {
  readonly subjectId: string;
  readonly model: NamedModelRef | null;
  readonly choiceSeq: number;
  /** Why their model is not asked here while this host asks others, by code, or null. */
  readonly refusal: string | null;
  /** Where the choice comes from, or null where the read does not say. */
  readonly from?: ChoiceSource | null;
}

/** The mind a gate's travellers get when their arrival says the world decides for them. */
export interface TravellerChoice {
  readonly grantId: string;
  readonly choiceSeq: number;
  /** The decider's kind as recorded: `model` or `routine`. */
  readonly deciderKind: string;
  readonly model: NamedModelRef | null;
}

/** A person's latest decision, and what the minute that consumed it did with it. */
export interface PersonDecision extends NamedModelRef {
  readonly subjectId: string;
  readonly decisionSeq: number;
  readonly baseTick: number;
  /** The minute that took it up, or null while none has. */
  readonly consumedTick: number | null;
  readonly status: 'accepted' | 'rejected' | 'unavailable';
  readonly reason: string;
  /** `applied` or not, or null while no minute has taken it up. */
  readonly disposition: string | null;
  /** Why the minute did not act on an accepted decision, by code, or null. */
  readonly dispositionReason: string | null;
  /** The action the model chose, in its offered words, or null when it chose none. */
  readonly chose: string | null;
}

/** What one model's decisions came to: the numbers a comparison of models reads. */
export interface ModelDecisionSummary extends NamedModelRef {
  readonly decisions: number;
  readonly asked: number;
  readonly accepted: number;
  readonly applied: number;
  /** Receipts by their reason code, and by what their minutes did (`pending` while none has). */
  readonly byReason: Readonly<Record<string, number>>;
  readonly byDisposition: Readonly<Record<string, number>>;
  /** The settled decisions not acted on, each once, by why. */
  readonly notActedOn: Readonly<Record<string, number>>;
  readonly latencyP50Ms: number | null;
  readonly latencyP95Ms: number | null;
  readonly costUsd: string;
  readonly costKnown: boolean;
}

/**
 * Somebody an outside program decides for now, under a door grant that stands, with what the grant
 * view says of that program. Such a person is never also run by a model, and a model chosen for
 * them is refused (`decided_from_outside`) until the grant ends.
 */
export interface OutsideDecider {
  readonly subjectId: string;
  /** `run`: one of the world's own people a grant names; `crossed`: a visitor that came in through the door. */
  readonly came: 'run' | 'crossed';
  readonly grantId: string;
  readonly bridge: string;
  /** The bridge's label, who runs its program and whether an AI does, or null where the door does not list it. */
  readonly bridgeLabel: string | null;
  readonly runBy: string | null;
  readonly ai: boolean | null;
  /** Whether its program is connected to the door now. */
  readonly connected: boolean;
  /** What the program declared itself to be, in its own words, or null where it declared nothing. */
  readonly declared: { readonly name: string; readonly maker: string; readonly mind: string | null } | null;
  /**
   * The subject's latest receipt under this grant (among those the read counts): whether the
   * program's answer was taken and why not; null where none is counted, absent from an older server.
   */
  readonly latest?: OutsideReceipt | null;
}

/** One receipt of an outside program's answer, as the models read's outside entry gives it. */
export interface OutsideReceipt {
  readonly decisionSeq: number;
  readonly baseTick: number;
  /** The minute that took it up, or null while none has. */
  readonly consumedTick: number | null;
  readonly status: 'accepted' | 'rejected' | 'unavailable' | 'stale';
  /** The receipt's own reason code (`DECISION_REASONS`). */
  readonly reason: string;
}

export interface SocietyModels {
  readonly societyId: string;
  /** Only a purposeful society's people are run by chosen models. */
  readonly takesModelChoices: boolean;
  /** Why this host asks no model for this world's people, by code, or null when it asks. */
  readonly hostRefusal: string | null;
  readonly modelPeopleMaximum: number;
  readonly models: readonly SocietyModel[];
  readonly choices: readonly PersonModelChoice[];
  readonly latest: readonly PersonDecision[];
  readonly byModel: readonly ModelDecisionSummary[];
  /** How many of the latest decisions the summaries count, and the most one read counts. */
  readonly decisionsCounted: number;
  readonly decisionsMaximum: number;
  /** Everyone an outside program decides for now; empty or absent where nobody is. */
  readonly outside?: readonly OutsideDecider[];
  /** Each gate's traveller mind; empty or absent where no gate names one. */
  readonly travellers?: readonly TravellerChoice[];
}

const invalid = (): never => { throw new Error('Invalid society models response'); };
const object = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : invalid();
const list = (value: unknown): readonly unknown[] => (Array.isArray(value) ? value : invalid());
const text = (value: unknown): string => (typeof value === 'string' && value.length > 0 ? value : invalid());
const count = (value: unknown): number => (Number.isSafeInteger(value) && (value as number) >= 0 ? value as number : invalid());
const maybe = <T>(value: unknown, read: (held: unknown) => T): T | null => (value === null ? null : read(value));
const flag = (value: unknown): boolean => (typeof value === 'boolean' ? value : invalid());

function modelRef(value: unknown): NamedModelRef {
  const held = object(value);
  return { provider: text(held['provider']), modelId: text(held['model_id']), name: text(held['name']) };
}

const DECIMAL = /^\d+(\.\d+)?$/;
function price(value: unknown): ModelPrice {
  const held = object(value);
  const amount = (raw: unknown): string => (typeof raw === 'string' && DECIMAL.test(raw) ? raw : invalid());
  return { input: amount(held['input']), output: amount(held['output']) };
}

function mechanism(value: unknown): AnsweringMechanism {
  return value === 'tool_call' || value === 'json_schema' ? value : invalid();
}

function outsideDecider(value: unknown): OutsideDecider {
  const held = object(value);
  const came = held['came'] === 'run' || held['came'] === 'crossed' ? held['came'] : invalid();
  const declared = maybe(held['declared'], (entry) => {
    const said = object(entry);
    return { name: text(said['name']), maker: text(said['maker']), mind: said['mind'] === undefined ? null : maybe(said['mind'], text) };
  });
  const latest: OutsideReceipt | null | undefined = held['latest'] === undefined ? undefined : maybe(held['latest'], (entry): OutsideReceipt => {
    const receipt = object(entry);
    const state = receipt['status'];
    return {
      decisionSeq: count(receipt['decision_seq']),
      baseTick: count(receipt['base_tick']),
      consumedTick: maybe(receipt['consumed_tick'], count),
      status: state === 'accepted' || state === 'rejected' || state === 'unavailable' || state === 'stale' ? state : invalid(),
      reason: text(receipt['reason']),
    };
  });
  const base: OutsideDecider = {
    subjectId: text(held['subject_id']),
    came,
    grantId: text(held['grant_id']),
    bridge: text(held['bridge']),
    bridgeLabel: maybe(held['bridge_label'], text),
    runBy: maybe(held['run_by'], text),
    ai: maybe(held['ai'], flag),
    connected: flag(held['connected']),
    declared,
  };
  // Present only where the server says it, so a read that predates the field reads as before.
  return latest === undefined ? base : { ...base, latest };
}

const SOURCES: readonly ChoiceSource[] = ['choice', 'choice_over_bound', 'travellers', 'travellers_over_bound'];
function source(value: unknown): ChoiceSource | null {
  if (value === undefined || value === null) return null;
  return (SOURCES as readonly unknown[]).includes(value) ? value as ChoiceSource : invalid();
}

function status(value: unknown): PersonDecision['status'] {
  return value === 'accepted' || value === 'rejected' || value === 'unavailable' ? value : invalid();
}

export function parseSocietyModels(value: unknown): SocietyModels {
  const row = object(value);
  if (row['profile'] !== 'exulanica.society-models/v1') invalid();
  const contract = object(row['contract']);
  const window = object(row['decisions_read']);
  return Object.freeze({
    societyId: text(row['society_id']),
    takesModelChoices: flag(row['takes_model_choices']),
    hostRefusal: maybe(row['host_refusal'], text),
    modelPeopleMaximum: count(contract['model_people_maximum']),
    models: list(row['models']).map((entry) => {
      const held = object(entry);
      return {
        ...modelRef(held),
        description: text(held['description']),
        providerDescription: text(held['provider_description']),
        mechanism: mechanism(held['mechanism']),
        price: held['usd_per_mtok'] === undefined ? null : maybe(held['usd_per_mtok'], price),
        refusal: maybe(held['refusal'], text),
      };
    }),
    choices: list(row['choices']).map((entry) => {
      const held = object(entry);
      return {
        subjectId: text(held['subject_id']),
        model: maybe(held['model'], modelRef),
        choiceSeq: count(held['choice_seq']),
        refusal: maybe(held['refusal'], text),
        from: source(held['from']),
      };
    }),
    latest: list(row['latest']).map((entry) => {
      const held = object(entry);
      return {
        ...modelRef(held),
        subjectId: text(held['subject_id']),
        decisionSeq: count(held['decision_seq']),
        baseTick: count(held['base_tick']),
        consumedTick: maybe(held['consumed_tick'], count),
        status: status(held['status']),
        reason: text(held['reason']),
        disposition: maybe(held['disposition'], text),
        dispositionReason: maybe(held['disposition_reason'], text),
        chose: maybe(held['chose'], text),
      };
    }),
    byModel: list(row['by_model']).map((entry) => {
      const held = object(entry);
      const latency = object(held['latency_ms']);
      const counts = (value: unknown): Record<string, number> =>
        Object.fromEntries(Object.entries(object(value)).map(([code, n]) => [code, count(n)]));
      return {
        ...modelRef(held),
        decisions: count(held['decisions']),
        asked: count(held['asked']),
        accepted: count(held['accepted']),
        applied: count(held['applied']),
        byReason: counts(held['by_reason']),
        byDisposition: counts(held['by_disposition']),
        notActedOn: counts(held['not_acted_on']),
        latencyP50Ms: maybe(latency['p50'], count),
        latencyP95Ms: maybe(latency['p95'], count),
        costUsd: text(held['cost_usd']),
        costKnown: flag(held['cost_known']),
      };
    }),
    decisionsCounted: count(window['counted']),
    decisionsMaximum: count(window['maximum']),
    // Added to the profile as an optional field: absent means nobody.
    outside: row['outside'] === undefined ? [] : list(row['outside']).map(outsideDecider),
    travellers: row['travellers'] === undefined ? [] : list(row['travellers']).map((entry) => {
      const held = object(entry);
      return {
        grantId: text(held['grant_id']),
        choiceSeq: count(held['choice_seq']),
        deciderKind: text(object(held['decider'])['kind']),
        model: maybe(held['model'], modelRef),
      };
    }),
  });
}

export interface SocietyModelsClientOptions extends TransportOptions {
  /** The open world the versions belong to; null where none is open, which sends nothing. */
  readonly worldId: string | null;
}

export class SocietyModelsClient {
  readonly #transport: Transport;
  readonly #worldId: string | null;
  constructor(options: SocietyModelsClientOptions) {
    this.#transport = new Transport(options);
    this.#worldId = options.worldId;
  }

  async read(versionId: string): Promise<SocietyModels> {
    return this.#transport.getJson<unknown>(this.#path(versionId)).then(parseSocietyModels);
  }

  /**
   * Choose `model`, or their own routine with null, for `people`. One idempotency key per choice,
   * so a retried request records it once.
   */
  async choose(
    versionId: string, people: readonly string[], model: ModelRef | null,
    idempotencyKey: string = crypto.randomUUID(),
  ): Promise<void> {
    await this.#transport.postJson<unknown>(this.#path(versionId), {
      idempotency_key: idempotencyKey,
      people,
      model: model === null ? null : { provider: model.provider, model_id: model.modelId },
    });
  }

  #path(versionId: string): string {
    const path = `/world/versions/${encodeURIComponent(versionId)}/society/models`;
    return openWorldPath(path, this.#worldId, 'choice of who decides for this world\'s people');
  }
}
