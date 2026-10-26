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
  /** Whether its provider serves it from this computer, billing nothing; absent or false where a read does not say. */
  readonly local?: boolean;
  /** What its maker says of it, from its own model card (`exulanica/models/model_cards.py`); null where none is kept or a read does not say. */
  readonly card?: ModelCard | null;
  /** For a model a person's own runner holds, what the runner states of it; absent for every other model. */
  readonly runner?: RunnerDetails | null;
  /** The most one decision with it may cost, in US dollars as a decimal string (E1); absent from an older server. */
  readonly decisionMostUsd?: string;
  /** The most one attempt of a decision with it may cost, which a guest's chooser fades it at (U2); absent from an older server. */
  readonly attemptMostUsd?: string;
  /** How many tokens it reads at once, as its manifest entry states (G2); absent from an older server. */
  readonly contextWindowTokens?: number;
}

/**
 * What a person's own runner states of a model it holds (`exulanica/models/local_runner.py`): its family and size, the
 * name it serves the model by, and the first line of the licence it states, quoted and never classed; each null where
 * it states none.
 */
export interface RunnerDetails {
  readonly family: string | null;
  readonly size: string | null;
  readonly servedAs: string;
  readonly licence: string | null;
  /** How long its check's slowest case took to answer, in milliseconds; null where none was asked. */
  readonly checkedMs: number | null;
}

/** Whether a check on this computer found a runner's model able to decide for a person here, or is still checking. */
export type RunnerState = 'able' | 'checking' | 'not_able';

/**
 * A model a person's own runner serves beside the manifest's: able (and offered among the models), being checked, or
 * not able, with why by code (`text`, `context`, `slow`, `form` or `error`) and the numbers a reason is told by: what
 * it reads at once, and a person's deadline.
 */
export interface RunnerModel extends NamedModelRef, RunnerDetails {
  readonly state: RunnerState;
  readonly reason: string | null;
  readonly contextTokens: number | null;
  readonly deadlineMs: number | null;
}

/**
 * A model's card as the server keeps it: its maker, its parameters as the card states them (null where it states
 * none), its licence, one short quote of what the maker says it is for, and the card's address at the revision read.
 */
export interface ModelCard {
  readonly maker: string;
  readonly parameters: { readonly total: string; readonly active: string | null } | null;
  readonly licence: string;
  readonly says: string;
  readonly source: string;
  readonly readOn: string;
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
  /**
   * Set while a person plays them (the choice's decider is a person): whether that person is the
   * one reading. Absent otherwise, and from a server that predates playing.
   */
  readonly played?: { readonly byYou: boolean };
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
  /** The authorized request/receipt read; absent in responses from older servers. */
  readonly requestId?: string;
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

/** Stored role documents retain their versioned fields; the server validates their contracts. */
export interface SocietyDecisionDetail {
  readonly status: 'in_progress' | 'completed';
  readonly request: Readonly<Record<string, unknown>>;
  readonly decision: Readonly<Record<string, unknown>> | null;
}

/** Check the read's identity and receipt binding without interpreting a role's observation. */
export function parseSocietyDecisionDetail(value: unknown, requestId: string): SocietyDecisionDetail {
  const row = object(value);
  const request = object(row['request']);
  const decision = maybe(row['decision'], object);
  const digest = text(request['document_sha256']);
  if (request['request_id'] !== requestId || !/^[a-f0-9]{64}$/.test(digest)) invalid();
  if (row['status'] !== (decision === null ? 'in_progress' : 'completed')) invalid();
  if (decision !== null && (decision['request_id'] !== requestId || decision['request_sha256'] !== digest)) invalid();
  return {
    status: decision === null ? 'in_progress' : 'completed',
    request,
    decision,
  };
}

/**
 * A rate with what it is made of. `value` is null below `minimum`, never 0: too few to say.
 */
export interface MeasuredRate {
  readonly numerator: number;
  readonly denominator: number;
  readonly minimum: number;
  readonly value: number | null;
}

/**
 * What a model's decisions came to, as the server measures them (`exulanica/world/decision_measures.py`),
 * its one authority: read, never recomputed here. No measure is combined into a score.
 */
export interface DecisionMeasures {
  readonly counts: {
    readonly decisions: number;
    readonly answered: number;
    readonly refused: number;
    readonly unavailable: number;
    readonly timeouts: number;
    readonly stale: number;
    readonly applied: number;
    readonly notApplied: number;
    /** Answers no minute has taken up yet; an ask left without an answer is never counted here. */
    readonly pending: number;
  };
  readonly rates: {
    readonly acceptance: MeasuredRate;
    readonly applied: MeasuredRate;
    readonly repeatedChoice: MeasuredRate;
    readonly repeatedLine: MeasuredRate;
  };
  readonly timeouts: { readonly longestStreak: number; readonly currentStreak: number };
  readonly repetition: { readonly longestChoiceRun: number; readonly longestLineRun: number };
  /** Percentiles are null below `minimum` timed calls. */
  readonly latencyMs: {
    readonly n: number;
    readonly minimum: number;
    readonly p50: number | null;
    readonly p95: number | null;
    readonly longest: number | null;
  };
  /**
   * `computed` from reported tokens at the listed price, or `bounded` where some call's cost is
   * unknown and its reservation stands in. Never a provider's bill.
   */
  readonly cost: {
    /** `knownUsd` plus `reservedUsd`. */
    readonly usd: string;
    /** Computed from the provider's reported tokens at the listed price. */
    readonly knownUsd: string;
    /** Charged as reservations for calls whose tokens were not reported: the most they can have cost. */
    readonly reservedUsd: string;
    readonly basis: 'computed' | 'bounded';
    readonly unknownCalls: number;
    readonly calls: number;
  };
}

/** One being's measures under one model. */
export interface BeingDecisionMeasures extends NamedModelRef {
  readonly subjectId: string;
  readonly measures: DecisionMeasures;
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
  /**
   * The middle of its decisions' known costs here, one of them (the lower of two), in US dollars as a decimal string,
   * and how many it is the middle of (G2's "about $Y a decision"); null with none, absent from an older server.
   */
  readonly costMedianUsd?: string | null;
  readonly costsCounted?: number;
  /** Absent from a server that predates the measures. */
  readonly measures?: DecisionMeasures;
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
  /** Whether a person's recorded decisions may be asked again of another model here (Compare); absent, they may. */
  readonly asksAgain?: boolean;
  readonly modelPeopleMaximum: number;
  /** The largest request a decision here may send, in tokens as its reserve counts them (G2); null where none is stated, absent from an older server. */
  readonly requestTokensAtMost?: number | null;
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
  /** Each being's measures under each model; absent from a server that predates them. */
  readonly byBeing?: readonly BeingDecisionMeasures[];
  /** Every model a person's own runner serves beside the manifest's, with its check's state; absent from an older server. */
  readonly runnerModels?: readonly RunnerModel[];
  /**
   * On a guest's page only: what they have left for AI models here, by provider, in US dollars as decimal strings
   * (U2); absent on a person's own install and from an older server.
   */
  readonly spendHereUsd?: Readonly<Record<string, string>>;
}

const invalid = (): never => { throw new Error('Invalid society models response'); };
const object = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : invalid();
const list = (value: unknown): readonly unknown[] => (Array.isArray(value) ? value : invalid());
const text = (value: unknown): string => (typeof value === 'string' && value.length > 0 ? value : invalid());
const count = (value: unknown): number => (Number.isSafeInteger(value) && (value as number) >= 0 ? value as number : invalid());
const maybe = <T>(value: unknown, read: (held: unknown) => T): T | null => (value === null ? null : read(value));

function modelCard(value: unknown): ModelCard {
  const held = object(value);
  const parameters = maybe(held['parameters'], (counts) => {
    const stated = object(counts);
    return Object.freeze({ total: text(stated['total']), active: maybe(stated['active'], text) });
  });
  return Object.freeze({
    maker: text(held['maker']), parameters, licence: text(held['licence']), says: text(held['says']),
    source: text(held['source']), readOn: text(held['read_on']),
  });
}
const flag = (value: unknown): boolean => (typeof value === 'boolean' ? value : invalid());

function runnerDetails(value: unknown): RunnerDetails {
  const held = object(value);
  return Object.freeze({
    family: maybe(held['family'], text), size: maybe(held['size'], text), servedAs: text(held['served_as']),
    licence: maybe(held['licence'], text), checkedMs: held['checked_ms'] === undefined ? null : maybe(held['checked_ms'], count),
  });
}

const RUNNER_STATES: ReadonlySet<unknown> = new Set(['able', 'checking', 'not_able']);
function runnerModel(value: unknown): RunnerModel {
  const held = object(value);
  return Object.freeze({
    ...modelRef(held),
    ...runnerDetails(held),
    state: RUNNER_STATES.has(held['state']) ? held['state'] as RunnerState : invalid(),
    reason: maybe(held['reason'], text),
    contextTokens: maybe(held['context_tokens'], count),
    deadlineMs: maybe(held['deadline_ms'], count),
  });
}

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

function measuredRate(value: unknown): MeasuredRate {
  const held = object(value);
  const ratio = held['value'];
  return {
    numerator: count(held['numerator']),
    denominator: count(held['denominator']),
    minimum: count(held['minimum']),
    value: ratio === null ? null : typeof ratio === 'number' && Number.isFinite(ratio) ? ratio : invalid(),
  };
}

const amount = (value: unknown): string => (typeof value === 'string' && DECIMAL.test(value) ? value : invalid());

/** The server's measures, exactly; the session read parses its own with this same reader. */
export function decisionMeasures(value: unknown): DecisionMeasures {
  const held = object(value);
  const counts = object(held['counts']);
  const rates = object(held['rates']);
  const timeouts = object(held['timeouts']);
  const repetition = object(held['repetition']);
  const latency = object(held['latency_ms']);
  const cost = object(held['cost']);
  const basis = cost['basis'] === 'computed' || cost['basis'] === 'bounded' ? cost['basis'] : invalid();
  return {
    counts: {
      decisions: count(counts['decisions']),
      answered: count(counts['answered']),
      refused: count(counts['refused']),
      unavailable: count(counts['unavailable']),
      timeouts: count(counts['timeouts']),
      stale: count(counts['stale']),
      applied: count(counts['applied']),
      notApplied: count(counts['not_applied']),
      pending: count(counts['pending']),
    },
    rates: {
      acceptance: measuredRate(rates['acceptance']),
      applied: measuredRate(rates['applied']),
      repeatedChoice: measuredRate(rates['repeated_choice']),
      repeatedLine: measuredRate(rates['repeated_line']),
    },
    timeouts: { longestStreak: count(timeouts['longest_streak']), currentStreak: count(timeouts['current_streak']) },
    repetition: { longestChoiceRun: count(repetition['longest_choice_run']), longestLineRun: count(repetition['longest_line_run']) },
    latencyMs: {
      n: count(latency['n']),
      minimum: count(latency['minimum']),
      p50: maybe(latency['p50'], count),
      p95: maybe(latency['p95'], count),
      longest: maybe(latency['longest'], count),
    },
    cost: {
      usd: amount(cost['usd']),
      knownUsd: amount(cost['known_usd']),
      reservedUsd: amount(cost['reserved_usd']),
      basis,
      unknownCalls: count(cost['unknown_calls']),
      calls: count(cost['calls']),
    },
  };
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
    asksAgain: row['asks_again'] === undefined ? true : flag(row['asks_again']),
    modelPeopleMaximum: count(contract['model_people_maximum']),
    ...(contract['request_tokens_at_most'] === undefined ? {} : { requestTokensAtMost: maybe(contract['request_tokens_at_most'], count) }),
    models: list(row['models']).map((entry) => {
      const held = object(entry);
      return {
        ...modelRef(held),
        description: text(held['description']),
        providerDescription: text(held['provider_description']),
        mechanism: mechanism(held['mechanism']),
        price: held['usd_per_mtok'] === undefined ? null : maybe(held['usd_per_mtok'], price),
        refusal: maybe(held['refusal'], text),
        local: held['on_this_computer'] === true,
        card: held['card'] === undefined ? null : maybe(held['card'], modelCard),
        ...(held['runner'] === undefined ? {} : { runner: maybe(held['runner'], runnerDetails) }),
        ...(held['decision_most_usd'] === undefined ? {} : { decisionMostUsd: amount(held['decision_most_usd']) }),
        ...(held['attempt_most_usd'] === undefined ? {} : { attemptMostUsd: amount(held['attempt_most_usd']) }),
        ...(held['context_window_tokens'] === undefined ? {} : { contextWindowTokens: count(held['context_window_tokens']) }),
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
        // A person playing them is said by whether it is the reader, never by account.
        ...(held['decider'] !== undefined && held['decider'] !== null && object(held['decider'])['kind'] === 'person'
          ? { played: { byYou: flag(held['played_by_you']) } } : {}),
      };
    }),
    latest: list(row['latest']).map((entry) => {
      const held = object(entry);
      return {
        ...modelRef(held),
        subjectId: text(held['subject_id']),
        ...(held['request_id'] === undefined ? {} : { requestId: text(held['request_id']) }),
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
        ...(held['costs_counted'] === undefined ? {} : { costMedianUsd: maybe(held['cost_median_usd'], amount), costsCounted: count(held['costs_counted']) }),
        // Added to the profile as an optional field: absent from an older server.
        ...(held['measures'] === undefined ? {} : { measures: decisionMeasures(held['measures']) }),
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
    ...(row['by_being'] === undefined ? {} : {
      byBeing: list(row['by_being']).map((entry): BeingDecisionMeasures => {
        const held = object(entry);
        return { ...modelRef(held), subjectId: text(held['subject_id']), measures: decisionMeasures(held['measures']) };
      }),
    }),
    // Added to the profile as an optional field: absent from an older server.
    ...(row['runner_models'] === undefined ? {} : { runnerModels: list(row['runner_models']).map(runnerModel) }),
    ...(row['spend_here_usd'] === undefined ? {} : {
      spendHereUsd: Object.freeze(Object.fromEntries(Object.entries(object(row['spend_here_usd'])).map(([provider, usd]) => [provider, amount(usd)]))),
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

  /** Read under current world authorization; withdrawal and absence remain server refusals. */
  async readDecision(versionId: string, requestId: string): Promise<SocietyDecisionDetail> {
    text(requestId);
    const path = `/world/versions/${encodeURIComponent(versionId)}/society/decisions/${encodeURIComponent(requestId)}`;
    const scoped = openWorldPath(path, this.#worldId, 'the recorded decision for this world');
    return this.#transport.getJson<unknown>(scoped).then((value) => parseSocietyDecisionDetail(value, requestId));
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
