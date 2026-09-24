/**
 * Authenticated, read-only access to one controlled society experiment attempt.
 *
 * The public surface is deliberately two GETs: the immutable definition projection followed by
 * its nested attempt. This adapter validates the three path identities and every digest that
 * crosses the response boundary before exposing compact metrics. It never prepares, reserves,
 * executes, finalizes, or asks for checkpoint/evidence bodies.
 */

import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';
import { worldPath } from './world-scope.js';

const DIGEST = /^[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export interface SocietyExperimentBinding {
  /** The world the version belongs to, which every read names. */
  readonly worldId: string;
  readonly versionId: string;
  readonly experimentId: string;
  readonly attemptId: string;
}

export interface ExperimentProblem {
  readonly code: string;
  readonly detail: string;
}

export interface ExperimentDefinition {
  readonly experimentId: string;
  readonly sourceSocietyId: string;
  readonly worldId: string;
  readonly versionId: string;
  readonly definitionSha256: string;
  readonly baselineInputSeq: number;
  readonly baselineInputSha256: string;
  readonly treatmentInputSeq: number;
  readonly treatmentInputSha256: string;
  readonly intervention: {
    readonly kind: 'noop' | 'add_rest_amenity';
    readonly targetId: string | null;
  };
  readonly population: number;
  readonly warmupTicks: number;
  readonly followupTicks: number;
  readonly createdAt: string;
}

export interface RawRatio {
  readonly numerator: number;
  /** Null represents an absent denominator. Zero is retained and presented as unavailable. */
  readonly denominator: number | null;
  readonly scaledBy?: number;
  readonly scaledFloor?: number;
}

export interface UnavailableRatio {
  readonly availability: 'unavailable' | 'not_present';
  readonly reason: string | null;
}

export type ExperimentRatio = RawRatio | UnavailableRatio;

export interface ArmMetrics {
  readonly population: number;
  readonly followupTicks: number;
  readonly highFatiguePersonMinutes: RawRatio;
  readonly completedRestActivities: RawRatio;
  readonly fatigueMilli: {
    readonly observations: number;
    readonly medianNearestRank: number;
    readonly p95NearestRank: number;
  };
  readonly focusRestOccupancy: ExperimentRatio;
  readonly allRestOccupancy: RawRatio;
  readonly travelMmPerInhabitant: RawRatio;
  readonly safety: {
    readonly stationaryCollisions: number;
    readonly overCapacityDestinationTicks: number;
    readonly transitionRefusals: number;
    readonly minimumDistinctPositions: number;
  };
  readonly evidence: {
    readonly stateCount: number;
    readonly eventCount: number;
    readonly finalStateSha256: string;
    readonly eventsSha256: string;
    readonly armEvidenceSha256: string;
  };
}

export interface ExperimentComparison {
  readonly direction: 'left_minus_right';
  readonly highFatigueFraction: RawRatio;
  readonly highFatigueRelativeChange: ExperimentRatio;
  readonly completedRestRate: RawRatio;
  readonly allRestOccupancyFraction: RawRatio;
  readonly travelMmPerInhabitant: RawRatio;
  readonly fatigueMedianMilli: RawRatio;
  readonly fatigueP95Milli: RawRatio;
}

export interface UnsupportedMetric {
  readonly metric: string;
  readonly reason: string;
}

export interface ValidExperimentResult {
  readonly status: 'valid';
  readonly definitionSha256: string;
  readonly checkpointSha256: string;
  readonly seedSha256: string;
  readonly documentSha256: string;
  readonly baseline: ArmMetrics;
  readonly treatment: ArmMetrics;
  readonly comparison: ExperimentComparison;
  readonly unsupportedMetrics: readonly UnsupportedMetric[];
}

export interface InvalidExperimentResult {
  readonly status: 'invalid_pair';
  readonly definitionSha256: string;
  readonly checkpointSha256: string;
  readonly seedSha256: string;
  readonly documentSha256: string;
  readonly reasons: readonly ExperimentProblem[];
  readonly unsupportedMetrics: readonly UnsupportedMetric[];
}

export type ExperimentResult = ValidExperimentResult | InvalidExperimentResult;

interface AttemptBase {
  readonly experimentId: string;
  readonly attemptId: string;
  readonly seedSha256: string;
  readonly definitionSha256: string;
  readonly checkpointSha256: string | null;
  readonly createdAt: string;
}

export type ExperimentAttempt =
  | (AttemptBase & { readonly status: 'incomplete' })
  | (AttemptBase & {
    readonly status: 'failed';
    readonly failureSha256: string;
    readonly terminalRecordedAt: string;
    readonly failure: ExperimentProblem & { readonly documentSha256: string };
  })
  | (AttemptBase & {
    readonly status: 'completed';
    readonly evidenceSha256: string;
    readonly resultSha256: string;
    readonly terminalRecordedAt: string;
    readonly result: ExperimentResult;
  });

export type ExperimentRead =
  | {
    readonly status: 'unavailable';
    readonly binding: SocietyExperimentBinding;
    readonly definition: ExperimentDefinition | null;
    readonly problem: ExperimentProblem;
  }
  | {
    readonly status: 'available';
    readonly binding: SocietyExperimentBinding;
    readonly definition: ExperimentDefinition;
    readonly attempt: ExperimentAttempt;
  };

export interface SocietyExperimentReadPort {
  read(binding: SocietyExperimentBinding, signal?: AbortSignal): Promise<ExperimentRead>;
}

export class SocietyExperimentContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SocietyExperimentContractError';
  }
}

type Row = Readonly<Record<string, unknown>>;

function row(value: unknown, name: string): Row {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new SocietyExperimentContractError(`${name} is not an object`);
  }
  return value as Row;
}

function exact(value: Row, fields: readonly string[], name: string): void {
  const actual = Object.keys(value).sort();
  const expected = [...fields].sort();
  if (actual.length !== expected.length || actual.some((field, index) => field !== expected[index])) {
    throw new SocietyExperimentContractError(`${name} fields do not match the public contract`);
  }
}

function text(value: unknown, name: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new SocietyExperimentContractError(`${name} is empty`);
  }
  return value;
}

function uuid(value: unknown, name: string, expected?: string): string {
  const parsed = text(value, name);
  if (!UUID.test(parsed) || (expected !== undefined && parsed !== expected)) {
    throw new SocietyExperimentContractError(`${name} does not match the requested identity`);
  }
  return parsed;
}

function digest(value: unknown, name: string, optional = false): string | null {
  if (value === null && optional) return null;
  if (typeof value !== 'string' || !DIGEST.test(value)) {
    throw new SocietyExperimentContractError(`${name} is not a lowercase SHA-256 digest`);
  }
  return value;
}

function integer(value: unknown, name: string, minimum = 0): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    throw new SocietyExperimentContractError(`${name} is not a safe integer`);
  }
  return value as number;
}

function compareCodePoints(left: string, right: string): number {
  const one = [...left], two = [...right];
  for (let index = 0; index < Math.min(one.length, two.length); index += 1) {
    const a = one[index]!.codePointAt(0)!, b = two[index]!.codePointAt(0)!;
    if (a !== b) return a < b ? -1 : 1;
  }
  return one.length - two.length;
}

/** The backend's integer-only, sorted-key canonical JSON over an already-parsed response. */
function canonicalJson(value: unknown, path = '$'): string {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') {
    return JSON.stringify(value);
  }
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) throw new SocietyExperimentContractError(`non-integer digest value at ${path}`);
    return String(value);
  }
  if (Array.isArray(value)) return `[${value.map((item, index) => canonicalJson(item, `${path}[${index}]`)).join(',')}]`;
  if (typeof value === 'object') {
    const object = value as Readonly<Record<string, unknown>>;
    return `{${Object.keys(object).sort(compareCodePoints).map(key => {
      const item = object[key];
      if (item === undefined) throw new SocietyExperimentContractError(`undefined digest value at ${path}.${key}`);
      return `${JSON.stringify(key)}:${canonicalJson(item, `${path}.${key}`)}`;
    }).join(',')}}`;
  }
  throw new SocietyExperimentContractError(`unsupported digest value at ${path}`);
}

async function canonicalSha256(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJson(value));
  const hashed = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes));
  return Array.from(hashed, byte => byte.toString(16).padStart(2, '0')).join('');
}

function nullableDenominator(value: Row, name: string): number | null {
  if (!Object.hasOwn(value, 'denominator') || value['denominator'] === null) return null;
  return integer(value['denominator'], `${name}.denominator`);
}

function rawRatio(value: unknown, name: string): RawRatio {
  const ratio = row(value, name);
  const numerator = integer(ratio['numerator'], `${name}.numerator`, Number.MIN_SAFE_INTEGER);
  const denominator = nullableDenominator(ratio, name);
  const scaledBy = Object.hasOwn(ratio, 'scaled_by')
    ? integer(ratio['scaled_by'], `${name}.scaled_by`, 1)
    : undefined;
  const scaledFloor = Object.hasOwn(ratio, 'scaled_floor')
    ? integer(ratio['scaled_floor'], `${name}.scaled_floor`, Number.MIN_SAFE_INTEGER)
    : undefined;
  if ((scaledBy === undefined) !== (scaledFloor === undefined)) {
    throw new SocietyExperimentContractError(`${name} scaled fields must be paired`);
  }
  return Object.freeze({ numerator, denominator, ...(scaledBy === undefined ? {} : { scaledBy }),
    ...(scaledFloor === undefined ? {} : { scaledFloor }) });
}

function ratio(value: unknown, name: string): ExperimentRatio {
  const candidate = row(value, name);
  if (candidate['availability'] === 'unavailable' || candidate['availability'] === 'not_present') {
    const reason = candidate['reason'] === undefined || candidate['reason'] === null
      ? null : text(candidate['reason'], `${name}.reason`);
    return Object.freeze({ availability: candidate['availability'], reason });
  }
  return rawRatio(candidate, name);
}

function problem(value: unknown, name: string): ExperimentProblem {
  const item = row(value, name);
  return Object.freeze({ code: text(item['code'], `${name}.code`), detail: text(item['detail'], `${name}.detail`) });
}

function unsupported(value: unknown): readonly UnsupportedMetric[] {
  if (!Array.isArray(value)) throw new SocietyExperimentContractError('unsupported_metrics is not a list');
  return Object.freeze(value.map((raw, index) => {
    const item = row(raw, `unsupported_metrics[${index}]`);
    exact(item, ['metric', 'reason'], `unsupported_metrics[${index}]`);
    return Object.freeze({ metric: text(item['metric'], 'unsupported metric'), reason: text(item['reason'], 'unsupported reason') });
  }));
}

function parseDefinition(value: unknown, binding: SocietyExperimentBinding): ExperimentDefinition {
  const definition = row(value, 'definition');
  exact(definition, ['record_status', 'experiment_id', 'source_society_id', 'world_id', 'version_id',
    'definition_sha256', 'baseline_input_seq', 'baseline_input_sha256', 'treatment_input_seq',
    'treatment_input_sha256', 'intervention', 'population', 'warmup_ticks', 'followup_ticks', 'created_at'], 'definition');
  if (definition['record_status'] !== 'recorded') throw new SocietyExperimentContractError('definition is not recorded');
  if (definition['world_id'] !== binding.worldId) {
    throw new SocietyExperimentContractError('definition world_id does not match the requested world');
  }
  const intervention = row(definition['intervention'], 'intervention');
  exact(intervention, ['kind', 'target_id'], 'intervention');
  const kind = intervention['kind'];
  if (kind !== 'noop' && kind !== 'add_rest_amenity') throw new SocietyExperimentContractError('unsupported intervention');
  const targetId = intervention['target_id'] === null ? null : text(intervention['target_id'], 'intervention target');
  if ((kind === 'noop' && targetId !== null) || (kind === 'add_rest_amenity' && targetId === null)) {
    throw new SocietyExperimentContractError('intervention target binding is malformed');
  }
  const baselineInputSeq = integer(definition['baseline_input_seq'], 'baseline_input_seq', 1);
  const treatmentInputSeq = integer(definition['treatment_input_seq'], 'treatment_input_seq', 1);
  const baselineInputSha256 = digest(definition['baseline_input_sha256'], 'baseline_input_sha256')!;
  const treatmentInputSha256 = digest(definition['treatment_input_sha256'], 'treatment_input_sha256')!;
  if (kind === 'noop' && (baselineInputSeq !== treatmentInputSeq || baselineInputSha256 !== treatmentInputSha256)) {
    throw new SocietyExperimentContractError('no-op definition changed its exact input');
  }
  if (kind === 'add_rest_amenity' && (treatmentInputSeq !== baselineInputSeq + 1 || baselineInputSha256 === treatmentInputSha256)) {
    throw new SocietyExperimentContractError('rest-amenity definition input binding is malformed');
  }
  return Object.freeze({
    experimentId: uuid(definition['experiment_id'], 'definition experiment_id', binding.experimentId),
    sourceSocietyId: uuid(definition['source_society_id'], 'source_society_id'),
    worldId: text(definition['world_id'], 'world_id'),
    versionId: uuid(definition['version_id'], 'definition version_id', binding.versionId),
    definitionSha256: digest(definition['definition_sha256'], 'definition_sha256')!,
    baselineInputSeq, baselineInputSha256, treatmentInputSeq, treatmentInputSha256,
    intervention: Object.freeze({ kind, targetId }),
    population: integer(definition['population'], 'population', 1),
    warmupTicks: integer(definition['warmup_ticks'], 'warmup_ticks', 1),
    followupTicks: integer(definition['followup_ticks'], 'followup_ticks', 1),
    createdAt: text(definition['created_at'], 'definition created_at'),
  });
}

function arm(value: unknown, name: string, definition: ExperimentDefinition): ArmMetrics {
  const item = row(value, name);
  exact(item, ['population', 'followup_ticks', 'high_fatigue_person_minutes', 'completed_rest_activities',
    'fatigue_milli', 'focus_rest_occupancy', 'all_rest_occupancy', 'travel_mm_per_inhabitant', 'safety', 'evidence'], name);
  const population = integer(item['population'], `${name}.population`, 1);
  const followupTicks = integer(item['followup_ticks'], `${name}.followup_ticks`, 1);
  if (population !== definition.population || followupTicks !== definition.followupTicks) {
    throw new SocietyExperimentContractError(`${name} population or follow-up binding mismatch`);
  }
  const fatigue = row(item['fatigue_milli'], `${name}.fatigue_milli`);
  exact(fatigue, ['observations', 'median_nearest_rank', 'p95_nearest_rank'], `${name}.fatigue_milli`);
  const safety = row(item['safety'], `${name}.safety`);
  exact(safety, ['stationary_collisions', 'over_capacity_destination_ticks', 'transition_refusals', 'minimum_distinct_positions'], `${name}.safety`);
  const evidence = row(item['evidence'], `${name}.evidence`);
  exact(evidence, ['state_count', 'event_count', 'final_state_sha256', 'events_sha256', 'arm_evidence_sha256'], `${name}.evidence`);
  return Object.freeze({
    population, followupTicks,
    highFatiguePersonMinutes: rawRatio(item['high_fatigue_person_minutes'], `${name}.high fatigue`),
    completedRestActivities: rawRatio(item['completed_rest_activities'], `${name}.completed rest`),
    fatigueMilli: Object.freeze({ observations: integer(fatigue['observations'], `${name}.fatigue observations`, 1),
      medianNearestRank: integer(fatigue['median_nearest_rank'], `${name}.fatigue median`),
      p95NearestRank: integer(fatigue['p95_nearest_rank'], `${name}.fatigue p95`) }),
    focusRestOccupancy: ratio(item['focus_rest_occupancy'], `${name}.focus rest occupancy`),
    allRestOccupancy: rawRatio(item['all_rest_occupancy'], `${name}.all rest occupancy`),
    travelMmPerInhabitant: rawRatio(item['travel_mm_per_inhabitant'], `${name}.travel`),
    safety: Object.freeze({ stationaryCollisions: integer(safety['stationary_collisions'], `${name}.collisions`),
      overCapacityDestinationTicks: integer(safety['over_capacity_destination_ticks'], `${name}.over capacity`),
      transitionRefusals: integer(safety['transition_refusals'], `${name}.transition refusals`),
      minimumDistinctPositions: integer(safety['minimum_distinct_positions'], `${name}.minimum positions`) }),
    evidence: Object.freeze({ stateCount: integer(evidence['state_count'], `${name}.state count`, 1),
      eventCount: integer(evidence['event_count'], `${name}.event count`),
      finalStateSha256: digest(evidence['final_state_sha256'], `${name}.final state`)!,
      eventsSha256: digest(evidence['events_sha256'], `${name}.events`)!,
      armEvidenceSha256: digest(evidence['arm_evidence_sha256'], `${name}.arm evidence`)! }),
  });
}

function comparison(value: unknown): ExperimentComparison {
  const item = row(value, 'comparison');
  exact(item, ['direction', 'high_fatigue_fraction', 'high_fatigue_relative_change', 'completed_rest_rate',
    'all_rest_occupancy_fraction', 'travel_mm_per_inhabitant', 'fatigue_median_milli', 'fatigue_p95_milli'], 'comparison');
  if (item['direction'] !== 'left_minus_right') throw new SocietyExperimentContractError('comparison direction is unsupported');
  return Object.freeze({ direction: 'left_minus_right',
    highFatigueFraction: rawRatio(item['high_fatigue_fraction'], 'comparison high fatigue'),
    highFatigueRelativeChange: ratio(item['high_fatigue_relative_change'], 'comparison relative high fatigue'),
    completedRestRate: rawRatio(item['completed_rest_rate'], 'comparison completed rest'),
    allRestOccupancyFraction: rawRatio(item['all_rest_occupancy_fraction'], 'comparison occupancy'),
    travelMmPerInhabitant: rawRatio(item['travel_mm_per_inhabitant'], 'comparison travel'),
    fatigueMedianMilli: rawRatio(item['fatigue_median_milli'], 'comparison fatigue median'),
    fatigueP95Milli: rawRatio(item['fatigue_p95_milli'], 'comparison fatigue p95') });
}

async function parseResult(value: unknown, definition: ExperimentDefinition, checkpoint: string, seed: string, resultDigest: string): Promise<ExperimentResult> {
  const result = row(value, 'result');
  exact(result, ['profile', 'status', 'definition_sha256', 'checkpoint_sha256', 'seed_sha256', 'invalid_pairs',
    'arms', 'comparison', 'unsupported_metrics', 'document_sha256'], 'result');
  if (result['profile'] !== 'exulanica.society-experiment-result/v1') throw new SocietyExperimentContractError('unsupported result profile');
  if (digest(result['definition_sha256'], 'result definition') !== definition.definitionSha256 ||
      digest(result['checkpoint_sha256'], 'result checkpoint') !== checkpoint ||
      digest(result['seed_sha256'], 'result seed') !== seed ||
      digest(result['document_sha256'], 'result document') !== resultDigest) {
    throw new SocietyExperimentContractError('result digest binding mismatch');
  }
  const canonical = Object.fromEntries(Object.entries(result).filter(([key]) => key !== 'document_sha256'));
  if (await canonicalSha256(canonical) !== resultDigest) {
    throw new SocietyExperimentContractError('result canonical digest mismatch');
  }
  const unsupportedMetrics = unsupported(result['unsupported_metrics']);
  if (result['status'] === 'invalid_pair') {
    if (!Array.isArray(result['invalid_pairs']) || result['invalid_pairs'].length === 0 ||
        result['arms'] !== null || result['comparison'] !== null) {
      throw new SocietyExperimentContractError('invalid-pair result shape is malformed');
    }
    return Object.freeze({ status: 'invalid_pair', definitionSha256: definition.definitionSha256,
      checkpointSha256: checkpoint, seedSha256: seed, documentSha256: resultDigest,
      reasons: Object.freeze(result['invalid_pairs'].map((reason, index) => problem(reason, `invalid_pairs[${index}]`))), unsupportedMetrics });
  }
  if (result['status'] !== 'valid' || !Array.isArray(result['invalid_pairs']) || result['invalid_pairs'].length !== 0) {
    throw new SocietyExperimentContractError('result status is unsupported');
  }
  const arms = row(result['arms'], 'arms');
  exact(arms, ['baseline', 'treatment'], 'arms');
  return Object.freeze({ status: 'valid', definitionSha256: definition.definitionSha256,
    checkpointSha256: checkpoint, seedSha256: seed, documentSha256: resultDigest,
    baseline: arm(arms['baseline'], 'baseline', definition), treatment: arm(arms['treatment'], 'treatment', definition),
    comparison: comparison(result['comparison']), unsupportedMetrics });
}

async function parseAttempt(value: unknown, binding: SocietyExperimentBinding, definition: ExperimentDefinition): Promise<ExperimentAttempt> {
  const attempt = row(value, 'attempt');
  exact(attempt, ['reservation_status', 'status', 'experiment_id', 'attempt_id', 'phase', 'seed_sha256',
    'definition_sha256', 'checkpoint_sha256', 'evidence_sha256', 'result_sha256', 'failure_sha256',
    'result', 'failure', 'created_at', 'terminal_recorded_at'], 'attempt');
  if (attempt['reservation_status'] !== 'reserved' || attempt['phase'] !== 'development') {
    throw new SocietyExperimentContractError('attempt is not a reserved development record');
  }
  const experimentId = uuid(attempt['experiment_id'], 'attempt experiment_id', binding.experimentId);
  const attemptId = uuid(attempt['attempt_id'], 'attempt attempt_id', binding.attemptId);
  const definitionSha256 = digest(attempt['definition_sha256'], 'attempt definition')!;
  if (definitionSha256 !== definition.definitionSha256) throw new SocietyExperimentContractError('attempt definition binding mismatch');
  const seedSha256 = digest(attempt['seed_sha256'], 'attempt seed')!;
  const checkpointSha256 = digest(attempt['checkpoint_sha256'], 'attempt checkpoint', true);
  const evidenceSha256 = digest(attempt['evidence_sha256'], 'attempt evidence', true);
  const resultSha256 = digest(attempt['result_sha256'], 'attempt result', true);
  const failureSha256 = digest(attempt['failure_sha256'], 'attempt failure', true);
  const createdAt = text(attempt['created_at'], 'attempt created_at');
  const base = { experimentId, attemptId, seedSha256, definitionSha256, checkpointSha256, createdAt };
  if (attempt['status'] === 'incomplete') {
    if ([evidenceSha256, resultSha256, failureSha256, attempt['result'], attempt['failure'], attempt['terminal_recorded_at']].some(value => value !== null)) {
      throw new SocietyExperimentContractError('incomplete attempt carries terminal material');
    }
    return Object.freeze({ ...base, status: 'incomplete' });
  }
  if (attempt['status'] === 'failed') {
    if (evidenceSha256 !== null || resultSha256 !== null || attempt['result'] !== null || failureSha256 === null) {
      throw new SocietyExperimentContractError('failed attempt shape is malformed');
    }
    const failure = row(attempt['failure'], 'failure');
    exact(failure, ['code', 'detail', 'document_sha256'], 'failure');
    if (digest(failure['document_sha256'], 'failure document') !== failureSha256) throw new SocietyExperimentContractError('failure digest binding mismatch');
    return Object.freeze({ ...base, status: 'failed', failureSha256,
      terminalRecordedAt: text(attempt['terminal_recorded_at'], 'terminal_recorded_at'),
      failure: Object.freeze({ ...problem(failure, 'failure'), documentSha256: failureSha256 }) });
  }
  if (attempt['status'] !== 'completed' || checkpointSha256 === null || evidenceSha256 === null || resultSha256 === null ||
      failureSha256 !== null || attempt['failure'] !== null) {
    throw new SocietyExperimentContractError('completed attempt binding is incomplete');
  }
  return Object.freeze({ ...base, status: 'completed', evidenceSha256, resultSha256,
    terminalRecordedAt: text(attempt['terminal_recorded_at'], 'terminal_recorded_at'),
    result: await parseResult(attempt['result'], definition, checkpointSha256, seedSha256, resultSha256) });
}

function checkedBinding(binding: SocietyExperimentBinding): SocietyExperimentBinding {
  return Object.freeze({ worldId: text(binding.worldId, 'world_id'), versionId: uuid(binding.versionId, 'version_id'),
    experimentId: uuid(binding.experimentId, 'experiment_id'), attemptId: uuid(binding.attemptId, 'attempt_id') });
}

function unavailable(error: unknown): ExperimentProblem | null {
  return error instanceof ApiError && [404, 424].includes(error.status)
    ? Object.freeze({ code: error.code, detail: error.message.replace(`${error.code}: `, '') })
    : null;
}

export class SocietyExperimentClient implements SocietyExperimentReadPort {
  readonly #options: TransportOptions;

  constructor(options: TransportOptions) {
    this.#options = options;
  }

  async read(supplied: SocietyExperimentBinding, signal?: AbortSignal): Promise<ExperimentRead> {
    const binding = checkedBinding(supplied);
    const parent = this.#options.signal;
    const combined = parent && signal ? AbortSignal.any([parent, signal]) : (signal ?? parent);
    const transport = new Transport({ ...this.#options, ...(combined === undefined ? {} : { signal: combined }) });
    const root = `/world/versions/${encodeURIComponent(binding.versionId)}/society/experiments/${encodeURIComponent(binding.experimentId)}`;
    const inWorld = (path: string): string => worldPath(path, binding.worldId);
    let definition: ExperimentDefinition;
    try {
      definition = parseDefinition(await transport.getJson<unknown>(inWorld(root)), binding);
    } catch (error) {
      const issue = unavailable(error);
      if (issue) return Object.freeze({ status: 'unavailable', binding, definition: null, problem: issue });
      throw error;
    }
    try {
      const attempt = await parseAttempt(await transport.getJson<unknown>(
        inWorld(`${root}/attempts/${encodeURIComponent(binding.attemptId)}`),
      ), binding, definition);
      return Object.freeze({ status: 'available', binding, definition, attempt });
    } catch (error) {
      const issue = unavailable(error);
      if (issue) return Object.freeze({ status: 'unavailable', binding, definition, problem: issue });
      throw error;
    }
  }
}
