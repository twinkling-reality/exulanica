/**
 * The same hour of a saved world, run with each arm of a comparison: read, never run.
 *
 * Speaks `/world/versions/{id}/society/comparisons` (`exulanica/api/routes/society_comparisons.py`):
 * a version's comparisons, one comparison's scores and the server's verdict, and one run replayed
 * from the requests and receipts it stored. None of these asks a model; a comparison is defined
 * and run by the local command, and a run's read replays it on the server with no call. The page
 * never decides whether two arms differ: the verdict is the server's, and this module only carries
 * its code. No document here carries a seed: seeds are named by the digest a catalog commits.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import type { NamedModelRef } from './society-models-api.js';
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

export interface ComparisonArm {
  readonly key: string;
  readonly role: ArmRole;
  readonly decider: Decider;
  /** The arm in plain words: the model's description as the manifest stated it when it ran. */
  readonly description: string;
}

export interface ComparisonListing {
  readonly comparisonId: string;
  readonly createdAt: string;
  readonly phase: Phase;
  readonly arms: readonly ComparisonArm[];
  readonly seeds: number;
  readonly runs: number;
  readonly runsCompleted: number;
  readonly runsExpected: number;
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

export interface SeedRun {
  readonly runId: string | null;
  readonly status: RunStatus;
  /** Why the run failed, by the code its outcome records, or null. */
  readonly failure: string | null;
  readonly score: Decimal | null;
  readonly turns: number;
  readonly notApplied: number;
  readonly calls: RunCalls | null;
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
  readonly notAppliedShare: Decimal | null;
  readonly costUsdPerHour: Decimal | null;
  readonly costKnown: boolean;
  readonly latencyMs: Latency;
  /** The measures that carry no weight, by the score catalog's key. */
  readonly heldOut: Readonly<Record<string, Decimal | null>>;
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
}

export interface ComparisonResult {
  readonly comparisonId: string;
  readonly createdAt: string;
  readonly phase: Phase;
  readonly windowTicks: number;
  readonly population: number;
  readonly preregistration: { readonly record: string; readonly recordSha256: string } | null;
  readonly arms: readonly ComparisonArm[];
  readonly primary: readonly [string, string] | null;
  readonly control: readonly [string, string] | null;
  readonly seeds: readonly ComparisonSeed[];
  readonly summaries: Readonly<Record<string, ArmSummary>>;
  readonly differences: readonly ComparisonDifference[];
  readonly controlBound: Decimal | null;
  readonly verdict: Verdict;
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
  readonly people: readonly { readonly id: string; readonly name: string }[];
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

function arm(value: unknown): ComparisonArm {
  const held = object(value);
  return {
    key: text(held['key']),
    role: oneOf<ArmRole>(ARM_ROLES)(held['role']),
    decider: decider(held['decider']),
    description: text(held['description']),
  };
}

const phase = oneOf<Phase>(['development', 'held_out']);

export function parseComparisons(value: unknown): readonly ComparisonListing[] {
  const row = object(value);
  if (row['profile'] !== 'exulanica.society-comparisons/v1') invalid();
  return Object.freeze(list(row['comparisons']).map((entry) => {
    const held = object(entry);
    return {
      comparisonId: text(held['comparison_id']),
      createdAt: text(held['created_at']),
      phase: phase(held['phase']),
      arms: list(held['arms']).map(arm),
      seeds: count(held['seeds']),
      runs: count(held['runs']),
      runsCompleted: count(held['runs_completed']),
      runsExpected: count(held['runs_expected']),
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

function seedRun(value: unknown): SeedRun {
  const found = object(value);
  return {
    runId: maybe(found['run_id'], text),
    status: oneOf<RunStatus>(['completed', 'failed', 'incomplete'])(found['status']),
    failure: maybe(found['failure'], text),
    score: maybe(found['score'], decimal),
    turns: count(found['turns']),
    notApplied: count(found['not_applied']),
    calls: maybe(found['calls'], calls),
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
    notAppliedShare: maybe(held['not_applied_share'], decimal),
    costUsdPerHour: maybe(held['cost_usd_per_hour'], decimal),
    costKnown: flag(held['cost_known']),
    latencyMs: latency(held['latency_ms']),
    heldOut: Object.fromEntries(Object.entries(object(held['held_out']))
      .map(([name, measure]) => [name, maybe(measure, decimal)])),
  };
}

export function parseComparison(value: unknown): ComparisonResult {
  const row = object(value);
  if (row['profile'] !== 'exulanica.society-comparison-result/v1') invalid();
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
    windowTicks: count(row['window_ticks']),
    population: count(row['population']),
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
    },
  });
}

export function parseRunReplay(value: unknown): RunReplay {
  const row = object(value);
  if (row['profile'] !== 'exulanica.society-comparison-run-replay/v1') invalid();
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
      return { id: text(held['id']), name: text(held['name']) };
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

export class SocietyComparisonClient implements SocietyComparisonReadPort {
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

  #path(versionId: string, rest: string): string {
    const path = `/world/versions/${encodeURIComponent(versionId)}/society/comparisons${rest}`;
    return openWorldPath(path, this.#worldId, 'comparison of the models that ran this world');
  }
}
