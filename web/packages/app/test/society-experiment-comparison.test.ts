// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  mountSocietyExperimentComparison,
  type MountedSocietyExperimentComparison,
} from '../src/composition/society-experiment-comparison.js';
import type {
  ArmMetrics,
  ExperimentAttempt,
  ExperimentDefinition,
  ExperimentRead,
  ExperimentResult,
  SocietyExperimentBinding,
  SocietyExperimentReadPort,
  ValidExperimentResult,
} from '../src/society-experiment-api.js';

const d = (letter: string) => letter.repeat(64);
const binding: SocietyExperimentBinding = {
  versionId: '11111111-1111-4111-8111-111111111111',
  experimentId: '22222222-2222-4222-8222-222222222222',
  attemptId: '33333333-3333-4333-8333-333333333333',
};
const definition: ExperimentDefinition = {
  experimentId: binding.experimentId, sourceSocietyId: '44444444-4444-4444-8444-444444444444',
  worldId: 'fixture-world', versionId: binding.versionId, definitionSha256: d('a'),
  baselineInputSeq: 7, baselineInputSha256: d('b'), treatmentInputSeq: 8,
  treatmentInputSha256: d('c'), intervention: { kind: 'add_rest_amenity', targetId: 'fixture:bench' },
  population: 12, warmupTicks: 4, followupTicks: 6, createdAt: '2026-09-19T12:00:00Z',
};

function arm(kind: 'baseline' | 'treatment'): ArmMetrics {
  const treatment = kind === 'treatment';
  return {
    population: 12, followupTicks: 6,
    highFatiguePersonMinutes: { numerator: treatment ? 1 : 3, denominator: 72, scaledBy: 1000, scaledFloor: treatment ? 13 : 41 },
    completedRestActivities: { numerator: treatment ? 5 : 2, denominator: 72, scaledBy: 1000, scaledFloor: treatment ? 69 : 27 },
    fatigueMilli: { observations: 72, medianNearestRank: treatment ? 340 : 420, p95NearestRank: treatment ? 700 : 820 },
    focusRestOccupancy: treatment ? { numerator: 5, denominator: null } : { availability: 'not_present', reason: null },
    allRestOccupancy: { numerator: 0, denominator: treatment ? 0 : 24 },
    travelMmPerInhabitant: { numerator: treatment ? 9100 : 8700, denominator: 12 },
    safety: { stationaryCollisions: 0, overCapacityDestinationTicks: treatment ? 1 : 0,
      transitionRefusals: 0, minimumDistinctPositions: 12 },
    evidence: { stateCount: 7, eventCount: treatment ? 9 : 7, finalStateSha256: d(treatment ? 'e' : 'f'),
      eventsSha256: d(treatment ? '1' : '2'), armEvidenceSha256: d(treatment ? '3' : '4') },
  };
}

const validResult: ValidExperimentResult = {
  status: 'valid', definitionSha256: d('a'), checkpointSha256: d('5'), seedSha256: d('d'), documentSha256: d('6'),
  baseline: arm('baseline'), treatment: arm('treatment'),
  comparison: { direction: 'left_minus_right', highFatigueFraction: { numerator: -1, denominator: 36 },
    highFatigueRelativeChange: { numerator: -2, denominator: 3 }, completedRestRate: { numerator: 1, denominator: 24 },
    allRestOccupancyFraction: { numerator: 0, denominator: 0 }, travelMmPerInhabitant: { numerator: 100, denominator: 3 },
    fatigueMedianMilli: { numerator: -80, denominator: 1 }, fatigueP95Milli: { numerator: -120, denominator: 1 } },
  unsupportedMetrics: [{ metric: 'human_outcome', reason: 'Synthetic agents do not predict real-human outcomes.' }],
};

function completed(result: ExperimentResult = validResult): ExperimentAttempt {
  return { status: 'completed', experimentId: binding.experimentId, attemptId: binding.attemptId,
    seedSha256: d('d'), definitionSha256: d('a'), checkpointSha256: d('5'), evidenceSha256: d('7'),
    resultSha256: d('6'), createdAt: '2026-09-19T12:01:00Z', terminalRecordedAt: '2026-09-19T12:02:00Z', result };
}

const available = (attempt: ExperimentAttempt): ExperimentRead => ({ status: 'available', binding, definition, attempt });
const client = (read: ExperimentRead): SocietyExperimentReadPort => ({ read: vi.fn(async () => read) });
const mounts: MountedSocietyExperimentComparison[] = [];
afterEach(() => { for (const mounted of mounts.splice(0)) mounted.dispose(); document.body.replaceChildren(); });

function mount(port: SocietyExperimentReadPort): MountedSocietyExperimentComparison {
  const mounted = mountSocietyExperimentComparison({ parent: document.body, client: port });
  mounts.push(mounted); return mounted;
}

describe('mounted society experiment comparison', () => {
  it('shows exact baseline/treatment fractions and labelled stored deltas without turning zero into an effect', async () => {
    const mounted = mount(client(available(completed()))); await mounted.load(binding);
    expect(mounted.status).toBe('available');
    expect(mounted.root.dataset['status']).toBe('available');
    expect(mounted.root.textContent).toContain('3 / 72');
    expect(mounted.root.textContent).toContain('1 / 72');
    expect(mounted.root.textContent).not.toContain('floor(');
    expect(mounted.root.textContent).toContain('-1 / 36');
    expect(mounted.root.textContent).toContain('Unavailable: 0 / 0');
    expect(mounted.root.textContent).toContain('Unavailable: 5 / denominator absent');
    expect(mounted.root.textContent).toContain('Treatment − baseline');
    expect(mounted.root.textContent).toContain('Server-recorded pair validation');
    expect(mounted.root.textContent).toContain('not an independent arithmetic proof, scientific significance, or a prediction of real people');
    expect(mounted.root.textContent).toContain('do not contain enough evidence to replay the simulation');
    expect(mounted.root.textContent).toContain('Synthetic agents do not predict real-human outcomes.');
    const exact = mounted.root.querySelector('details')!;
    expect(exact.open).toBe(false);
    expect(exact.textContent).toContain(binding.versionId);
    expect(exact.textContent).toContain(d('a'));
  });

  it.each([
    ['incomplete', available({ status: 'incomplete', experimentId: binding.experimentId, attemptId: binding.attemptId,
      seedSha256: d('d'), definitionSha256: d('a'), checkpointSha256: null, createdAt: 'time' }), 'Attempt is incomplete'],
    ['failed', available({ status: 'failed', experimentId: binding.experimentId, attemptId: binding.attemptId,
      seedSha256: d('d'), definitionSha256: d('a'), checkpointSha256: null, createdAt: 'time',
      failureSha256: d('8'), terminalRecordedAt: 'later', failure: { code: 'simulation_refused', detail: 'Fixture refusal', documentSha256: d('8') } }), 'Attempt failed'],
    ['invalid', available(completed({ status: 'invalid_pair', definitionSha256: d('a'), checkpointSha256: d('5'),
      seedSha256: d('d'), documentSha256: d('9'), reasons: [{ code: 'intervention_unreachable', detail: 'Target was unreachable.' }],
      unsupportedMetrics: [] })), 'Comparison is invalid'],
    ['unavailable', { status: 'unavailable' as const, binding, definition: null,
      problem: { code: 'unknown_reference', detail: 'Experiment is unavailable.' } }, 'Experiment unavailable'],
  ] as const)('renders the %s lifecycle state without reinterpreting it', async (status, read, title) => {
    const mounted = mount(client(read)); await mounted.load(binding);
    expect(mounted.status).toBe(status);
    expect(mounted.root.textContent).toContain(title);
    expect(mounted.root.querySelector('.experiment-ledger')).toBeNull();
  });

  it('aborts a stale binding and ignores its late reply', async () => {
    let firstResolve!: (read: ExperimentRead) => void;
    let secondResolve!: (read: ExperimentRead) => void;
    const signals: AbortSignal[] = [];
    const port: SocietyExperimentReadPort = { read: vi.fn((next: SocietyExperimentBinding, signal?: AbortSignal) => {
      if (signal) signals.push(signal);
      return new Promise<ExperimentRead>(resolve => {
        if (next.attemptId === binding.attemptId) firstResolve = resolve;
        else secondResolve = resolve;
      });
    }) };
    const mounted = mount(port);
    const first = mounted.load(binding); await Promise.resolve();
    const nextBinding = { ...binding, attemptId: '99999999-9999-4999-8999-999999999999' };
    const second = mounted.load(nextBinding); await Promise.resolve();
    expect(signals[0]?.aborted).toBe(true);
    secondResolve({ status: 'unavailable', binding: nextBinding, definition: null,
      problem: { code: 'unknown_reference', detail: 'Current binding wins.' } });
    await second;
    firstResolve(available(completed())); await first;
    expect(mounted.binding).toEqual(nextBinding);
    expect(mounted.root.textContent).toContain('Current binding wins.');
    expect(mounted.root.textContent).not.toContain('Server-recorded pair validation');
  });

  it('aborts an in-flight read and removes its surface on disposal', async () => {
    let signal: AbortSignal | undefined;
    const port: SocietyExperimentReadPort = { read: vi.fn((_binding, supplied) => {
      signal = supplied; return new Promise<ExperimentRead>(() => undefined);
    }) };
    const mounted = mount(port); void mounted.load(binding); await Promise.resolve(); mounted.dispose();
    expect(signal?.aborted).toBe(true); expect(document.body.contains(mounted.root)).toBe(false);
    await expect(mounted.load(binding)).rejects.toThrow(/disposed/);
  });
});
