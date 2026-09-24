import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import {
  SocietyExperimentClient,
  SocietyExperimentContractError,
  type SocietyExperimentBinding,
} from '../src/society-experiment-api.js';

const binding: SocietyExperimentBinding = {
  worldId: 'fixture-world',
  versionId: '11111111-1111-4111-8111-111111111111',
  experimentId: '22222222-2222-4222-8222-222222222222',
  attemptId: '33333333-3333-4333-8333-333333333333',
};
const d = (letter: string) => letter.repeat(64);
const producerResult = JSON.parse(readFileSync(
  new URL('fixtures/society-experiment-compact-result.json', import.meta.url), 'utf8',
)) as Record<string, any>;

function definition(overrides: Record<string, unknown> = {}) {
  return {
    record_status: 'recorded', experiment_id: binding.experimentId,
    source_society_id: '44444444-4444-4444-8444-444444444444', world_id: 'fixture-world',
    version_id: binding.versionId, definition_sha256: d('a'), baseline_input_seq: 7,
    baseline_input_sha256: d('b'), treatment_input_seq: 8, treatment_input_sha256: d('c'),
    intervention: { kind: 'add_rest_amenity', target_id: 'fixture:bench' },
    population: 12, warmup_ticks: 4, followup_ticks: 6, created_at: '2026-09-19T12:00:00Z',
    ...overrides,
  };
}

function incomplete() {
  return {
    reservation_status: 'reserved', status: 'incomplete', experiment_id: binding.experimentId,
    attempt_id: binding.attemptId, phase: 'development', seed_sha256: d('d'),
    definition_sha256: d('a'), checkpoint_sha256: null, evidence_sha256: null,
    result_sha256: null, failure_sha256: null, result: null, failure: null,
    created_at: '2026-09-19T12:01:00Z', terminal_recorded_at: null,
  };
}

function completed(result: Record<string, any> = producerResult) {
  return {
    reservation_status: 'reserved', status: 'completed', experiment_id: binding.experimentId,
    attempt_id: binding.attemptId, phase: 'development', seed_sha256: result.seed_sha256,
    definition_sha256: result.definition_sha256, checkpoint_sha256: result.checkpoint_sha256,
    evidence_sha256: d('8'), result_sha256: result.document_sha256, failure_sha256: null, failure: null,
    created_at: '2026-09-19T12:01:00Z', terminal_recorded_at: '2026-09-19T12:02:00Z',
    result,
  };
}

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'content-type': 'application/json' },
});

describe('society experiment read client', () => {
  it('uses only the exact definition and nested-attempt GETs with authenticated transport', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response(definition()))
      .mockResolvedValueOnce(response(incomplete()));
    const client = new SocietyExperimentClient({ baseUrl: 'https://fixture.test/api/', token: 'secret', fetch });

    const read = await client.read(binding);

    expect(read.status).toBe('available');
    if (read.status !== 'available') throw new Error('fixture did not produce an available read');
    expect(read.definition.versionId).toBe(binding.versionId);
    expect(read.attempt.status).toBe('incomplete');
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls.map(([url]) => String(url))).toEqual([
      `https://fixture.test/api/world/versions/${binding.versionId}/society/experiments/${binding.experimentId}?world_id=fixture-world`,
      `https://fixture.test/api/world/versions/${binding.versionId}/society/experiments/${binding.experimentId}/attempts/${binding.attemptId}?world_id=fixture-world`,
    ]);
    for (const [, init] of fetch.mock.calls) {
      expect(init).toMatchObject({ method: 'GET', credentials: 'include', headers: { authorization: 'Bearer secret' } });
    }
  });

  it('retains a verified definition when the nested attempt is non-disclosing unavailable', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response(definition()))
      .mockResolvedValueOnce(response({ code: 'unknown_reference', detail: 'attempt is unavailable' }, 404));
    const read = await new SocietyExperimentClient({ baseUrl: 'https://fixture.test', token: '', fetch }).read(binding);
    expect(read).toMatchObject({ status: 'unavailable', binding, definition: { definitionSha256: d('a') },
      problem: { code: 'unknown_reference', detail: 'attempt is unavailable' } });
  });

  it('preserves the producer-generated compact result as exact raw integers', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response(definition({
      definition_sha256: producerResult.definition_sha256, population: 4, followup_ticks: 6,
    }))).mockResolvedValueOnce(response(completed()));
    const read = await new SocietyExperimentClient({ baseUrl: 'https://fixture.test', token: '', fetch }).read(binding);
    if (read.status !== 'available' || read.attempt.status !== 'completed' || read.attempt.result.status !== 'valid') {
      throw new Error('fixture did not produce a valid completed result');
    }
    expect(read.attempt.result.baseline.highFatiguePersonMinutes).toEqual({ numerator: 0, denominator: 24, scaledBy: 1000, scaledFloor: 0 });
    expect(read.attempt.result.treatment.focusRestOccupancy).toEqual({ numerator: 4, denominator: 6, scaledBy: 1000, scaledFloor: 666 });
    expect(read.attempt.result.comparison.travelMmPerInhabitant).toEqual({ numerator: -1000, denominator: 1 });
  });

  it('rejects a changed producer metric when the recorded canonical digest is left unchanged', async () => {
    const changed = structuredClone(producerResult);
    changed.arms.treatment.travel_mm_per_inhabitant.numerator += 1;
    const fetch = vi.fn().mockResolvedValueOnce(response(definition({
      definition_sha256: producerResult.definition_sha256, population: 4, followup_ticks: 6,
    }))).mockResolvedValueOnce(response(completed(changed)));
    await expect(new SocietyExperimentClient({ baseUrl: 'https://fixture.test', token: '', fetch }).read(binding))
      .rejects.toThrow(/canonical digest mismatch/);
  });

  it('refuses a successful response bound to any other path identity or definition digest', async () => {
    for (const fixture of [
      { definition: { ...definition(), version_id: '99999999-9999-4999-8999-999999999999' }, attempt: incomplete() },
      { definition: definition(), attempt: { ...incomplete(), definition_sha256: d('e') } },
    ]) {
      const fetch = vi.fn().mockResolvedValueOnce(response(fixture.definition)).mockResolvedValueOnce(response(fixture.attempt));
      await expect(new SocietyExperimentClient({ baseUrl: 'https://fixture.test', token: '', fetch }).read(binding))
        .rejects.toBeInstanceOf(SocietyExperimentContractError);
    }
  });

  it('cancels both reads through the supplied request signal', async () => {
    let signal: AbortSignal | null | undefined;
    const fetch = vi.fn(async (_input: unknown, init?: RequestInit) => {
      signal = init?.signal;
      return new Promise<Response>(() => undefined);
    });
    const controller = new AbortController();
    void new SocietyExperimentClient({ baseUrl: 'https://fixture.test', token: '', fetch }).read(binding, controller.signal);
    await Promise.resolve(); controller.abort();
    expect(signal?.aborted).toBe(true);
  });
});
