/**
 * The same hour of a saved world, run with each arm of a comparison: planned, started and read.
 *
 * Speaks `/world/versions/{id}/society/comparisons` (`exulanica/api/routes/society_comparisons.py`):
 * a version's comparisons, one comparison's scores and the server's verdict, one run replayed from
 * the requests and receipts it stored, what a start of a comparison would be (its plan), and the
 * start itself. None of the reads asks a model, and a run's read replays it on the server with no
 * call; a started comparison is played by the server off the request, under the bound its owner
 * stated. The page never decides whether two arms differ, or what a comparison may cost: the
 * verdict and the plan are the server's, and this module only carries them. No document here
 * carries a seed: seeds are named by the digest a catalog commits.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import type { ModelRef, NamedModelRef } from './society-models-api.js';
import { openWorldPath } from './world-scope.js';

/**
 * Who decides for the people an arm runs. A model carries the name the server gives it
 * (`Manifest.model_name`), as every read that mentions a model does.
 */
export type Decider =
  | { readonly kind: 'routine' }
  | { readonly kind: 'wait' }
  | ({ readonly kind: 'model' } & NamedModelRef);

/** What an arm is to its comparison: a model compared, the same model again, or an anchor. */
export const ARM_ROLES = ['candidate', 'control', 'one', 'zero'] as const;
export type ArmRole = typeof ARM_ROLES[number];

/** Every verdict the server gives; the page has words for exactly these. */
export const VERDICT_CODES = ['different', 'no_measured_difference', 'not_judged', 'incomplete'] as const;
export type VerdictCode = typeof VERDICT_CODES[number];

export type Phase = 'development' | 'held_out';

/** How a model is asked for a person's choice, by the server's code for each mechanism. */
export const ANSWERING_MECHANISMS = ['tool_call', 'json_schema'] as const;
export type AnsweringMechanism = typeof ANSWERING_MECHANISMS[number];
/** Whose order a model is asked in: its own, measured for it, or the contract's. */
export const ANSWERING_SOURCES = ['model', 'contract'] as const;
export type AnsweringSource = typeof ANSWERING_SOURCES[number];

/**
 * How a model was asked, as its comparison recorded it: the mechanisms in order, the one it was
 * asked by, whose order that is and the record that measured a model's own. The mechanism changes
 * what a model chooses, so it is part of what the model is in a comparison.
 */
export interface Answering {
  readonly order: readonly AnsweringMechanism[];
  readonly mechanism: AnsweringMechanism;
  readonly source: AnsweringSource;
  readonly record: string | null;
}

export interface ComparisonArm {
  readonly key: string;
  readonly role: ArmRole;
  readonly decider: Decider;
  /** How its model was asked; null for an anchor, and for a comparison that did not record it. */
  readonly answering: Answering | null;
  /** The arm in plain words: the model's description as the manifest stated it when it ran. */
  readonly description: string;
}

/** Where a comparison's group came from, by the server's code for it. */
export const GROUP_SOURCES = ['everyone', 'named', 'owner_choice'] as const;
export type GroupSourceKind = typeof GROUP_SOURCES[number];

/** An owner's choice, by its sequence in the world and its digest. */
export interface OwnerChoice {
  readonly choiceSeq: number;
  readonly documentSha256: string;
}

export type GroupSource =
  | { readonly kind: 'everyone' }
  | { readonly kind: 'named' }
  | ({ readonly kind: 'owner_choice' } & OwnerChoice);

/** A person of the world, by id and the name the society gives them. */
export interface NamedPerson {
  readonly id: string;
  readonly name: string;
}

/**
 * The people a comparison's arms decide for. A first-version comparison decided for everybody
 * and named nobody, so its people are null.
 */
export interface ComparisonGroup {
  readonly people: readonly NamedPerson[] | null;
  readonly source: GroupSource;
  readonly size: number;
}

/** Somebody outside the group, and what decides for them in every arm: their owner's choice. */
export interface OtherPerson extends NamedPerson {
  readonly decider: Decider;
  /** How their owner's model was asked; null for their routine. */
  readonly answering: Answering | null;
  readonly choice: OwnerChoice | null;
}

/**
 * Where a comparison started from the application stands, by the server's word: `START_STATES`
 * in `exulanica/world/society_comparison_start_repository.py`, held to it by a parity test.
 */
export const START_STATES = ['waiting', 'running', 'finished', 'closed'] as const;
export type StartState = typeof START_STATES[number];

/** A comparison's start: the bound its owner stated, what its asks spent, and where it stands. */
export interface ComparisonStart {
  readonly boundUsd: Decimal;
  readonly spentUsd: Decimal;
  /** What servers that stopped were presumed to have spent on asks they never recorded. */
  readonly presumedUsd: Decimal;
  readonly state: StartState;
  /** Why the server closed it before every run was played, by code, or null. */
  readonly closedReason: string | null;
  readonly runsPlanned: number;
  readonly startedAt: string;
  readonly finishedAt: string | null;
}

export interface ComparisonListing {
  readonly comparisonId: string;
  readonly createdAt: string;
  readonly phase: Phase;
  /** The score's version: 1 scored need relief less the turns a model left; 2 need relief alone. */
  readonly scoreVersion: number;
  readonly group: { readonly source: GroupSource; readonly size: number };
  readonly arms: readonly ComparisonArm[];
  readonly seeds: number;
  readonly runs: number;
  readonly runsCompleted: number;
  /** Runs with an outcome, completed or failed. */
  readonly runsFinished: number;
  readonly runsExpected: number;
  /** Its start where it was started from the application; null for one the local command ran. */
  readonly start: ComparisonStart | null;
}

/** A value the server computed exactly and wrote as a decimal: shown as written, never clipped. */
export type Decimal = string;

export interface Interval {
  readonly low: Decimal;
  readonly high: Decimal;
}

export interface Latency {
  readonly p50: number | null;
  readonly p95: number | null;
}

export interface RunCalls {
  readonly asked: number;
  readonly firstAnswersRefused: number;
  readonly costUsd: Decimal;
  readonly costKnown: boolean;
  readonly latencyMs: Latency;
}

export type RunStatus = 'completed' | 'failed' | 'incomplete';

/** Answered, refused and left to the routine, each as a share or a rate the server wrote. */
export interface ReliabilityRates {
  readonly answered: Decimal;
  readonly refused: Decimal;
  readonly leftToRoutine: Decimal;
}

/**
 * What a model answered for the group, served beside every score it carries: its turns, those it
 * answered, those whose answer was refused and those left to the routine, as counts, as shares of
 * the run's own turns, and as rates per choice point the routine's own run of the same seed had.
 */
export interface Reliability {
  readonly turns: number;
  readonly answered: number;
  readonly refused: number;
  readonly leftToRoutine: number;
  /** How the turns left to the routine split, or null where the run did not record it. */
  readonly notAnswered: number | null;
  readonly notApplied: number | null;
  readonly shares: ReliabilityRates | null;
  /** Null where no routine run recorded its choice points: a first-version comparison, an anchor. */
  readonly perRoutineChoice: ReliabilityRates | null;
  readonly routineChoicePoints: number | null;
  /** Every turn not answered and applied, by the reason the receipt or the minute recorded. */
  readonly reasons: Readonly<Record<string, number>>;
}

export interface SeedRun {
  readonly runId: string | null;
  readonly status: RunStatus;
  /** Why the run failed, by the code its outcome records, or null. */
  readonly failure: string | null;
  readonly score: Decimal | null;
  readonly reliability: Reliability | null;
  readonly calls: RunCalls | null;
  /** What asking everybody outside the group took, or null where no model decides for them. */
  readonly othersCalls: RunCalls | null;
}

export interface ComparisonSeed {
  readonly seedDigest: string;
  /** The seed's key in the seed catalog, or null for one the catalog does not name. */
  readonly name: string | null;
  /** Why this seed carries no score, by code, or null. */
  readonly excluded: string | null;
  readonly runs: Readonly<Record<string, SeedRun>>;
}

export interface ArmSummary {
  readonly meanScore: Decimal | null;
  readonly interval: Interval | null;
  readonly reliability: Reliability | null;
  readonly costUsdPerHour: Decimal | null;
  readonly costKnown: boolean;
  readonly othersCostUsdPerHour: Decimal | null;
  readonly latencyMs: Latency;
  /** The measures that carry no weight, by the score catalog's key. */
  readonly heldOut: Readonly<Record<string, Decimal | null>>;
  /** The group's person-minutes by what they were doing, or null where a run did not record it. */
  readonly minutesByActivity: Readonly<Record<string, Decimal>> | null;
}

export interface ComparisonDifference {
  readonly first: string;
  readonly second: string;
  readonly mean: Decimal;
  readonly low: Decimal;
  readonly high: Decimal;
  readonly rejected: boolean;
}

export interface Verdict {
  readonly code: VerdictCode;
  readonly higher: string | null;
  /** Why a comparison is not judged, by code, or null. */
  readonly reason: string | null;
  /**
   * Whether the primary pair's answered shares differ by more than the control pair's, or null
   * where an arm of either pair asked nothing or no control was run: the server's, never the page's.
   */
  readonly answeredSharesDiffer: boolean | null;
}

export interface ComparisonResult {
  readonly comparisonId: string;
  readonly createdAt: string;
  readonly phase: Phase;
  readonly scoreVersion: number;
  readonly windowTicks: number;
  readonly population: number;
  readonly group: ComparisonGroup;
  readonly others: readonly OtherPerson[];
  /**
   * Whether a model decides for somebody outside the group, asked in every arm, the anchors
   * included, so the score's 1 and the rates' denominator move with its answers too. Only a
   * development comparison can have one: a held-out one is refused with it.
   */
  readonly othersAsked: boolean;
  readonly preregistration: { readonly record: string; readonly recordSha256: string } | null;
  readonly arms: readonly ComparisonArm[];
  readonly primary: readonly [string, string] | null;
  readonly control: readonly [string, string] | null;
  readonly seeds: readonly ComparisonSeed[];
  readonly summaries: Readonly<Record<string, ArmSummary>>;
  readonly differences: readonly ComparisonDifference[];
  readonly controlBound: Decimal | null;
  readonly verdict: Verdict;
  readonly start: ComparisonStart | null;
}

export interface PlanNode { readonly id: string; readonly x: number; readonly z: number }
export interface PlanTarget {
  readonly targetId: string;
  readonly affordance: string;
  readonly activity: string;
  readonly label: string;
  readonly x: number;
  readonly z: number;
  readonly places: readonly (readonly [number, number])[];
}

export interface RunPerson {
  readonly id: string;
  readonly x: number;
  readonly z: number;
  /** Every point the person walked through this minute, the first where the minute began. */
  readonly path: readonly (readonly [number, number])[];
  readonly action: string;
  readonly status: string;
  readonly reason: string;
  readonly goal: { readonly kind: string; readonly targetId: string | null; readonly reason: string } | null;
  readonly needMilli: number;
}

export interface RunDecision {
  readonly decisionSeq: number;
  readonly subjectId: string;
  /** The minute that consumed the decision. */
  readonly tick: number;
  readonly status: string;
  readonly reason: string;
  readonly disposition: string | null;
  readonly dispositionReason: string | null;
  readonly chose: string | null;
  readonly latencyMs: number | null;
  readonly costUsd: Decimal | null;
}

export interface RunEvent {
  readonly tick: number;
  readonly subjectId: string;
  readonly kind: string;
  readonly reason: string;
  readonly summary: string;
}

export interface RunReplay {
  readonly runId: string;
  readonly arm: string;
  readonly seedDigest: string;
  readonly threshold: number;
  readonly nodes: readonly PlanNode[];
  readonly edges: readonly (readonly [string, string])[];
  readonly targets: readonly PlanTarget[];
  /** What a person's action may be while they do something, in the routine's own words. */
  readonly activities: readonly { readonly kind: string; readonly label: string }[];
  /** Each person, whether the run's arm decides for them, and who does. */
  readonly people: readonly (NamedPerson & { readonly inGroup: boolean; readonly decider: Decider })[];
  /** Minute 0 is the start, then one state per simulated minute. */
  readonly minutes: readonly { readonly tick: number; readonly people: readonly RunPerson[] }[];
  readonly decisions: readonly RunDecision[];
  readonly events: readonly RunEvent[];
}

const invalid = (): never => { throw new Error('Invalid society comparison response'); };
const object = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : invalid();
const list = (value: unknown): readonly unknown[] => (Array.isArray(value) ? value : invalid());
const text = (value: unknown): string => (typeof value === 'string' && value.length > 0 ? value : invalid());
/** Text the server may write empty: a reason or summary an event did not state. */
const words = (value: unknown): string => (typeof value === 'string' ? value : invalid());
const count = (value: unknown): number => (Number.isSafeInteger(value) && (value as number) >= 0 ? value as number : invalid());
const integer = (value: unknown): number => (Number.isSafeInteger(value) ? value as number : invalid());
const flag = (value: unknown): boolean => (typeof value === 'boolean' ? value : invalid());
const maybe = <T>(value: unknown, read: (held: unknown) => T): T | null => (value === null ? null : read(value));
/** A decimal as the server wrote it: an optional sign, digits, and an optional fraction. */
const decimal = (value: unknown): Decimal => (typeof value === 'string' && /^-?\d+(\.\d+)?$/.test(value) ? value : invalid());
const oneOf = <T extends string>(options: readonly T[]) => (value: unknown): T =>
  (options as readonly unknown[]).includes(value) ? value as T : invalid();
const point = (value: unknown): readonly [number, number] => {
  const held = list(value);
  return held.length === 2 ? [integer(held[0]), integer(held[1])] : invalid();
};
const pair = (value: unknown): readonly [string, string] => {
  const held = list(value);
  return held.length === 2 ? [text(held[0]), text(held[1])] : invalid();
};
const latency = (value: unknown): Latency => {
  const held = object(value);
  return { p50: maybe(held['p50'], count), p95: maybe(held['p95'], count) };
};

function decider(value: unknown): Decider {
  const held = object(value);
  switch (held['kind']) {
    case 'routine': return { kind: 'routine' };
    case 'wait': return { kind: 'wait' };
    case 'model': return {
      kind: 'model',
      provider: text(held['provider']),
      modelId: text(held['model_id']),
      name: text(held['name']),
    };
    default: return invalid();
  }
}

function ownerChoice(value: unknown): OwnerChoice {
  const held = object(value);
  return { choiceSeq: count(held['choice_seq']), documentSha256: text(held['document_sha256']) };
}

function groupSource(value: unknown): GroupSource {
  const held = object(value);
  const kind = oneOf<GroupSourceKind>(GROUP_SOURCES)(held['kind']);
  return kind === 'owner_choice' ? { kind, ...ownerChoice(held) } : { kind };
}

function namedPerson(value: unknown): NamedPerson {
  const held = object(value);
  return { id: text(held['id']), name: text(held['name']) };
}

const mechanism = oneOf<AnsweringMechanism>(ANSWERING_MECHANISMS);

function answering(value: unknown): Answering {
  const held = object(value);
  return {
    order: list(held['order']).map(mechanism),
    mechanism: mechanism(held['mechanism']),
    source: oneOf<AnsweringSource>(ANSWERING_SOURCES)(held['source']),
    record: maybe(held['record'], text),
  };
}

function arm(value: unknown): ComparisonArm {
  const held = object(value);
  return {
    key: text(held['key']),
    role: oneOf<ArmRole>(ARM_ROLES)(held['role']),
    decider: decider(held['decider']),
    answering: maybe(held['answering'], answering),
    description: text(held['description']),
  };
}

const phase = oneOf<Phase>(['development', 'held_out']);

function comparisonStart(value: unknown): ComparisonStart {
  const held = object(value);
  return {
    boundUsd: decimal(held['bound_usd']),
    spentUsd: decimal(held['spent_usd']),
    presumedUsd: decimal(held['presumed_usd']),
    state: oneOf(START_STATES)(held['state']),
    closedReason: maybe(held['closed_reason'], text),
    runsPlanned: count(held['runs_planned']),
    startedAt: text(held['started_at']),
    finishedAt: maybe(held['finished_at'], text),
  };
}

export function parseComparisons(value: unknown): readonly ComparisonListing[] {
  const row = object(value);
  if (row['profile'] !== 'exulanica.society-comparisons/v2') invalid();
  return Object.freeze(list(row['comparisons']).map((entry) => {
    const held = object(entry);
    const group = object(held['group']);
    return {
      comparisonId: text(held['comparison_id']),
      createdAt: text(held['created_at']),
      phase: phase(held['phase']),
      scoreVersion: count(held['score_version']),
      group: { source: groupSource(group['source']), size: count(group['size']) },
      arms: list(held['arms']).map(arm),
      seeds: count(held['seeds']),
      runs: count(held['runs']),
      runsCompleted: count(held['runs_completed']),
      runsFinished: count(held['runs_finished']),
      runsExpected: count(held['runs_expected']),
      start: maybe(held['start'], comparisonStart),
    };
  }));
}

function calls(value: unknown): RunCalls {
  const held = object(value);
  return {
    asked: count(held['asked']),
    firstAnswersRefused: count(held['first_answers_refused']),
    costUsd: decimal(held['cost_usd']),
    costKnown: flag(held['cost_known']),
    latencyMs: latency(held['latency_ms']),
  };
}

function rates(value: unknown): ReliabilityRates {
  const held = object(value);
  return {
    answered: decimal(held['answered']),
    refused: decimal(held['refused']),
    leftToRoutine: decimal(held['left_to_routine']),
  };
}

function reliability(value: unknown): Reliability {
  const held = object(value);
  return {
    turns: count(held['turns']),
    answered: count(held['answered']),
    refused: count(held['refused']),
    leftToRoutine: count(held['left_to_routine']),
    notAnswered: maybe(held['not_answered'], count),
    notApplied: maybe(held['not_applied'], count),
    shares: maybe(held['shares'], rates),
    perRoutineChoice: maybe(held['per_routine_choice'], rates),
    routineChoicePoints: maybe(held['routine_choice_points'], count),
    reasons: Object.fromEntries(Object.entries(object(held['reasons']))
      .map(([reason, times]) => [text(reason), count(times)])),
  };
}

function seedRun(value: unknown): SeedRun {
  const found = object(value);
  return {
    runId: maybe(found['run_id'], text),
    status: oneOf<RunStatus>(['completed', 'failed', 'incomplete'])(found['status']),
    failure: maybe(found['failure'], text),
    score: maybe(found['score'], decimal),
    reliability: maybe(found['reliability'], reliability),
    calls: maybe(found['calls'], calls),
    othersCalls: maybe(found['others_calls'], calls),
  };
}

function summary(value: unknown): ArmSummary {
  const held = object(value);
  return {
    meanScore: maybe(held['mean_score'], decimal),
    interval: maybe(held['interval'], (found) => {
      const range = object(found);
      return { low: decimal(range['low']), high: decimal(range['high']) };
    }),
    reliability: maybe(held['reliability'], reliability),
    costUsdPerHour: maybe(held['cost_usd_per_hour'], decimal),
    costKnown: flag(held['cost_known']),
    othersCostUsdPerHour: maybe(held['others_cost_usd_per_hour'], decimal),
    latencyMs: latency(held['latency_ms']),
    heldOut: Object.fromEntries(Object.entries(object(held['held_out']))
      .filter(([name]) => name !== MINUTES_BY_ACTIVITY)
      .map(([name, measure]) => [name, maybe(measure, decimal)])),
    minutesByActivity: maybe(object(held['held_out'])[MINUTES_BY_ACTIVITY], (found) =>
      Object.fromEntries(Object.entries(object(found)).map(([kind, share]) => [text(kind), decimal(share)]))),
  };
}

/** The held-out measure that is a share per activity rather than one number. */
const MINUTES_BY_ACTIVITY = 'minutes_by_activity';

export function parseComparison(value: unknown): ComparisonResult {
  const row = object(value);
  if (row['profile'] !== 'exulanica.society-comparison-result/v2') invalid();
  const verdict = object(row['verdict']);
  const arms = list(row['arms']).map(arm);
  const keys = new Set(arms.map((entry) => entry.key));
  const armKey = (value: unknown): string => (keys.has(text(value)) ? text(value) : invalid());
  const armPair = (value: unknown): readonly [string, string] => {
    const [first, second] = pair(value);
    return [armKey(first), armKey(second)];
  };
  return Object.freeze({
    comparisonId: text(row['comparison_id']),
    createdAt: text(row['created_at']),
    phase: phase(row['phase']),
    scoreVersion: count(row['score_version']),
    windowTicks: count(row['window_ticks']),
    population: count(row['population']),
    group: ((held) => ({
      people: maybe(held['people'], (people) => list(people).map(namedPerson)),
      source: groupSource(held['source']),
      size: count(held['size']),
    }))(object(row['group'])),
    others: list(row['others']).map((entry) => {
      const held = object(entry);
      return {
        ...namedPerson(held),
        decider: decider(held['decider']),
        answering: maybe(held['answering'], answering),
        choice: maybe(held['choice'], ownerChoice),
      };
    }),
    othersAsked: flag(row['others_asked']),
    preregistration: maybe(row['preregistration'], (held) => {
      const record = object(held);
      return { record: text(record['record']), recordSha256: text(record['record_sha256']) };
    }),
    arms,
    primary: maybe(row['primary'], armPair),
    control: maybe(row['control'], armPair),
    seeds: list(row['seeds']).map((entry) => {
      const held = object(entry);
      return {
        seedDigest: text(held['seed_digest']),
        name: maybe(held['name'], text),
        excluded: maybe(held['excluded'], text),
        runs: Object.fromEntries(Object.entries(object(held['runs']))
          .map(([key, run]) => [armKey(key), seedRun(run)])),
      };
    }),
    summaries: Object.fromEntries(Object.entries(object(row['summaries']))
      .map(([key, entry]) => [armKey(key), summary(entry)])),
    differences: list(row['differences']).map((entry) => {
      const held = object(entry);
      return {
        first: armKey(held['first']),
        second: armKey(held['second']),
        mean: decimal(held['mean']),
        low: decimal(held['low']),
        high: decimal(held['high']),
        rejected: flag(held['rejected']),
      };
    }),
    controlBound: maybe(row['control_bound'], decimal),
    verdict: {
      code: oneOf<VerdictCode>(VERDICT_CODES)(verdict['code']),
      higher: maybe(verdict['higher'], armKey),
      reason: maybe(verdict['reason'], text),
      answeredSharesDiffer: maybe(verdict['answered_shares_differ'], flag),
    },
    start: maybe(row['start'], comparisonStart),
  });
}

export function parseRunReplay(value: unknown): RunReplay {
  const row = object(value);
  if (row['profile'] !== 'exulanica.society-comparison-run-replay/v2') invalid();
  // The server replays a run from its record and says so; a read that could not is an error.
  if (row['replay_verified'] !== true) invalid();
  const place = object(row['place']);
  return Object.freeze({
    runId: text(row['run_id']),
    arm: text(row['arm']),
    seedDigest: text(row['seed_digest']),
    threshold: count(row['threshold']),
    nodes: list(place['nodes']).map((entry) => {
      const held = object(entry);
      return { id: text(held['id']), x: integer(held['x']), z: integer(held['z']) };
    }),
    edges: list(place['edges']).map(pair),
    targets: list(place['targets']).map((entry) => {
      const held = object(entry);
      return {
        targetId: text(held['target_id']),
        affordance: text(held['affordance']),
        activity: text(held['activity']),
        label: text(held['label']),
        x: integer(held['x']),
        z: integer(held['z']),
        places: list(held['places']).map(point),
      };
    }),
    activities: list(row['activities']).map((entry) => {
      const held = object(entry);
      return { kind: text(held['kind']), label: text(held['label']) };
    }),
    people: list(row['people']).map((entry) => {
      const held = object(entry);
      return { ...namedPerson(held), inGroup: flag(held['in_group']), decider: decider(held['decider']) };
    }),
    minutes: list(row['minutes']).map((entry) => {
      const held = object(entry);
      return {
        tick: count(held['tick']),
        people: list(held['people']).map((person) => {
          const found = object(person);
          return {
            id: text(found['id']),
            x: integer(found['x']),
            z: integer(found['z']),
            path: list(found['path']).map(point),
            action: text(found['action']),
            status: text(found['status']),
            reason: text(found['reason']),
            goal: maybe(found['goal'], (goal) => {
              const aim = object(goal);
              return {
                kind: text(aim['kind']),
                targetId: maybe(aim['target_id'], text),
                reason: text(aim['reason']),
              };
            }),
            needMilli: count(found['need_milli']),
          };
        }),
      };
    }),
    decisions: list(row['decisions']).map((entry) => {
      const held = object(entry);
      return {
        decisionSeq: count(held['decision_seq']),
        subjectId: text(held['subject_id']),
        tick: count(held['tick']),
        status: text(held['status']),
        reason: text(held['reason']),
        disposition: maybe(held['disposition'], text),
        dispositionReason: maybe(held['disposition_reason'], text),
        chose: maybe(held['chose'], text),
        latencyMs: maybe(held['latency_ms'], count),
        costUsd: maybe(held['cost_usd'], decimal),
      };
    }),
    events: list(row['events']).map((entry) => {
      const held = object(entry);
      return {
        tick: count(held['tick']),
        subjectId: text(held['subject_id']),
        kind: text(held['kind']),
        reason: words(held['reason']),
        summary: words(held['summary']),
      };
    }),
  });
}

/** A group a comparison may decide for: everybody, or the people one of the owner's choices named. */
export interface PlanGroup {
  readonly kind: GroupSourceKind;
  readonly choiceSeq: number | null;
  readonly size: number;
  readonly people: readonly NamedPerson[] | null;
  /** The model that choice named, or null for their routine and for everybody. */
  readonly model: NamedModelRef | null;
}

/** A model a comparison may ask, whether this server can ask it, and what it typically cost. */
export interface PlanModel extends NamedModelRef {
  readonly description: string;
  /** Why this server cannot ask it now, by code, or null. */
  readonly refusal: string | null;
  /**
   * What one person cost for a simulated hour under it in a recorded comparison
   * (`typicalRecord`), or null where none measured it: a measurement, never a bound.
   */
  readonly typicalUsdPerPersonHour: Decimal | null;
}

/** A decision role a comparison of this society may ask, with the groups and models it offers. */
export interface PlanRole {
  readonly key: string;
  /** The word the role's subjects are known by. */
  readonly subject: string;
  readonly groups: readonly PlanGroup[];
  readonly models: readonly PlanModel[];
}

/** What a selection would run and what it can cost: the most, derived, and the typical, measured. */
export interface PlanFigures {
  readonly runs: number;
  readonly asksMost: number;
  readonly callsMost: number;
  readonly mostUsd: Decimal;
  readonly typicalUsd: Decimal | null;
  readonly typicalRecord: string;
}

export interface Refusal {
  readonly code: string;
  readonly detail: string;
}

/** What this server offers a comparison of a version's society, and a selection's plan. */
export interface ComparisonPlan {
  /** Why this server starts no comparison here, or null. */
  readonly refusal: Refusal | null;
  /** The comparison of this world still running, by id, or null. */
  readonly running: string | null;
  readonly roles: readonly PlanRole[];
  readonly seedsAvailable: number;
  readonly modelsMost: number;
  readonly windowTicks: number;
  readonly typicalRecord: string;
  readonly plan: PlanFigures | null;
  /** Why a start of the selection would be refused, or null. */
  readonly planRefusal: Refusal | null;
}

/** What a person chose to compare. */
export interface ComparisonSelection {
  readonly role: string;
  readonly group: { readonly kind: GroupSourceKind; readonly choiceSeq?: number; readonly people?: readonly string[] };
  readonly models: readonly ModelRef[];
  readonly control: boolean;
  readonly seeds: number;
}

/** A comparison started: what it compares, its id, and the most its asks may spend. */
export interface StartRequest extends ComparisonSelection {
  readonly comparisonId: string;
  readonly boundUsd: Decimal;
}

const refusal = (value: unknown): Refusal => {
  const held = object(value);
  return { code: text(held['code']), detail: words(held['detail']) };
};

const namedModel = (value: unknown): NamedModelRef => {
  const held = object(value);
  return { provider: text(held['provider']), modelId: text(held['model_id']), name: text(held['name']) };
};

function planFigures(value: unknown): PlanFigures {
  const held = object(value);
  return {
    runs: count(held['runs']),
    asksMost: count(held['asks_most']),
    callsMost: count(held['calls_most']),
    mostUsd: decimal(held['most_usd']),
    typicalUsd: maybe(held['typical_usd'], decimal),
    typicalRecord: text(held['typical_record']),
  };
}

export function parsePlan(value: unknown): ComparisonPlan {
  const row = object(value);
  if (row['profile'] !== 'exulanica.society-comparison-plan/v1') invalid();
  return Object.freeze({
    refusal: maybe(row['refusal'], refusal),
    running: maybe(row['running'], text),
    roles: list(row['roles']).map((entry) => {
      const held = object(entry);
      return {
        key: text(held['key']),
        subject: text(held['subject']),
        groups: list(held['groups']).map((group) => {
          const offered = object(group);
          return {
            kind: oneOf<GroupSourceKind>(GROUP_SOURCES)(offered['kind']),
            choiceSeq: maybe(offered['choice_seq'], count),
            size: count(offered['size']),
            people: maybe(offered['people'], (people) => list(people).map(namedPerson)),
            model: maybe(offered['model'], namedModel),
          };
        }),
        models: list(held['models']).map((model) => {
          const offered = object(model);
          return {
            ...namedModel(offered),
            description: words(offered['description']),
            refusal: maybe(offered['refusal'], text),
            typicalUsdPerPersonHour: maybe(offered['typical_usd_per_person_hour'], decimal),
          };
        }),
      };
    }),
    seedsAvailable: count(row['seeds_available']),
    modelsMost: count(row['models_most']),
    windowTicks: count(row['window_ticks']),
    typicalRecord: text(row['typical_record']),
    plan: maybe(row['plan'], planFigures),
    planRefusal: maybe(row['plan_refusal'], refusal),
  });
}

/** A selection as the plan route's query names it. */
export function planQuery(selection: ComparisonSelection): URLSearchParams {
  const query = new URLSearchParams({
    role: selection.role,
    group: selection.group.kind,
    control: String(selection.control),
    seeds: String(selection.seeds),
  });
  if (selection.group.choiceSeq !== undefined) query.set('choice_seq', String(selection.group.choiceSeq));
  for (const person of selection.group.people ?? []) query.append('person', person);
  for (const model of selection.models) query.append('model', `${model.provider}/${model.modelId}`);
  return query;
}

/** A start as the start route's body states it. */
export function startBody(request: StartRequest): Record<string, unknown> {
  return {
    comparison_id: request.comparisonId,
    role: request.role,
    group: {
      kind: request.group.kind,
      ...(request.group.choiceSeq === undefined ? {} : { choice_seq: request.group.choiceSeq }),
      ...(request.group.people === undefined ? {} : { people: [...request.group.people] }),
    },
    models: request.models.map((model) => ({ provider: model.provider, model_id: model.modelId })),
    control: request.control,
    seeds: request.seeds,
    bound_usd: request.boundUsd,
  };
}

export interface SocietyComparisonClientOptions extends TransportOptions {
  /** The open world the versions belong to; null where none is open, which sends nothing. */
  readonly worldId: string | null;
}

/** The three reads; there is no write, and nothing here asks a model. */
export interface SocietyComparisonReadPort {
  list(versionId: string): Promise<readonly ComparisonListing[]>;
  read(versionId: string, comparisonId: string): Promise<ComparisonResult>;
  run(versionId: string, comparisonId: string, runId: string): Promise<RunReplay>;
}

/** What starts a comparison: its plan, and the start. */
export interface SocietyComparisonStartPort {
  plan(versionId: string, selection: ComparisonSelection | null): Promise<ComparisonPlan>;
  start(versionId: string, request: StartRequest): Promise<readonly ComparisonListing[]>;
}

export class SocietyComparisonClient implements SocietyComparisonReadPort, SocietyComparisonStartPort {
  readonly #transport: Transport;
  readonly #worldId: string | null;
  constructor(options: SocietyComparisonClientOptions) {
    this.#transport = new Transport(options);
    this.#worldId = options.worldId;
  }

  async list(versionId: string): Promise<readonly ComparisonListing[]> {
    return this.#transport.getJson<unknown>(this.#path(versionId, '')).then(parseComparisons);
  }

  async read(versionId: string, comparisonId: string): Promise<ComparisonResult> {
    return this.#transport.getJson<unknown>(
      this.#path(versionId, `/${encodeURIComponent(comparisonId)}`),
    ).then(parseComparison);
  }

  async run(versionId: string, comparisonId: string, runId: string): Promise<RunReplay> {
    return this.#transport.getJson<unknown>(this.#path(
      versionId, `/${encodeURIComponent(comparisonId)}/runs/${encodeURIComponent(runId)}`,
    )).then(parseRunReplay);
  }

  async plan(versionId: string, selection: ComparisonSelection | null): Promise<ComparisonPlan> {
    const query = selection === null ? '' : `?${planQuery(selection).toString()}`;
    return this.#transport.getJson<unknown>(this.#path(versionId, `/plan${query}`)).then(parsePlan);
  }

  async start(versionId: string, request: StartRequest): Promise<readonly ComparisonListing[]> {
    return this.#transport.postJson<unknown>(this.#path(versionId, ''), startBody(request))
      .then(parseComparisons);
  }

  #path(versionId: string, rest: string): string {
    const path = `/world/versions/${encodeURIComponent(versionId)}/society/comparisons${rest}`;
    return openWorldPath(path, this.#worldId, 'comparison of the models that ran this world');
  }
}
