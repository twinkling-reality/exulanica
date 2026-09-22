// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import {
  SocietyClient,
  parseSociety,
  parseSocietyActionRecord,
} from '../src/society-api.js';
import {
  buildSocietyDirectedAction,
  describeSocietyActionFailure,
  describeSocietyActionRecord,
  societyDirectedActionGate,
} from '../src/ui/society-directed-action.js';

const digest = 'a'.repeat(64);
const version = '11111111-1111-4111-8111-111111111111';
const subject = '22222222-2222-4222-8222-222222222222';
const requestId = '33333333-3333-4333-8333-333333333333';

const reasonOf = (gate: ReturnType<typeof societyDirectedActionGate>): string | null =>
  gate.ok ? null : gate.reason;

function v2Snapshot(options: { readonly without?: string; readonly societyId?: string } = {}) {
  const inhabitants = Array.from({ length: 100 }, (_, i) => ({
    // A society holds at least 100 inhabitants, so `without` replaces the subject's id.
    id: i === 0 && options.without !== subject ? subject : `person-${i}`,
    synthetic: true as const,
    display_name: `Sim ${i}`,
    role: 'visitor',
    position_mm: [i, 0] as const,
    motion_path_mm: [[i, 0]] as const,
    action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting' },
    explanation: { summary: 'Waiting.', event_ids: [] as string[] },
    goal: null,
    route: null,
  }));
  const societyId = options.societyId ?? 'society';
  return parseSociety({
    society_id: societyId,
    version_id: version,
    place_id: 'place',
    population_size: 100,
    current_tick: 3,
    state_sha256: digest,
    branch_id: version,
    input_seq: 1,
    input_sha256: digest,
    state: {
      profile: 'exulanica-society/v2',
      society_id: societyId,
      branch_id: version,
      tick: 3,
      input_seq: 1,
      input_sha256: digest,
      inhabitants,
    },
  });
}

function actionEnvelope(status: 'pending' | 'consumed' = 'pending') {
  return {
    request: {
      profile: 'exulanica.society-action-request/v1',
      request_id: requestId,
      requested_by: '44444444-4444-4444-8444-444444444444',
      subject_id: subject,
      branch_id: version,
      base_tick: 3,
      base_state_sha256: digest,
      input_seq: 1,
      input_sha256: digest,
      intent: { kind: 'perform', target_id: 'district:marker:visit', affordance: 'visit' },
      target: {
        target_id: 'district:marker:visit',
        subject_id: 'subject',
        node_id: 'n1',
        affordance: 'visit',
        duration_ticks: 1,
        origin: 'district',
        object_id: null,
        version_id: version,
        enabled: true,
      },
      document_sha256: digest,
    },
    status,
    consumption: status === 'consumed' ? { tick: 4, disposition: 'applied' } : null,
  };
}

describe('society directed-action client', () => {
  it('parses the recorded action envelope from record_action', () => {
    const record = parseSocietyActionRecord(actionEnvelope(), version);
    expect(record.status).toBe('pending');
    expect(record.request.intent).toEqual({
      kind: 'perform', target_id: 'district:marker:visit', affordance: 'visit',
    });
    expect(record.request.documentSha256).toBe(digest);
    expect(describeSocietyActionRecord(record)).toMatch(/synthetic society record, not personal evidence/);
    expect(describeSocietyActionRecord(record)).not.toMatch(/personal memory|remembered person/i);
  });

  it('posts perform through SocietyClient.requestAction', async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(actionEnvelope()), {
      status: 200, headers: { 'content-type': 'application/json' },
    }));
    const client = new SocietyClient({
      baseUrl: 'https://example.test', token: 'token', fetch: fetcher as typeof fetch,
    });
    const record = await client.requestAction(v2Snapshot(), subject, {
      kind: 'perform', targetId: 'district:marker:visit', affordance: 'visit',
    }, requestId);
    expect(record.status).toBe('pending');
    expect(fetcher.mock.calls[0]![0]).toBe(
      `https://example.test/world/versions/${version}/society/actions`,
    );
    expect(fetcher.mock.calls[0]![1]?.method).toBe('POST');
    expect(JSON.parse(String(fetcher.mock.calls[0]![1]?.body))).toEqual({
      idempotency_key: requestId,
      base_tick: 3,
      base_state_sha256: digest,
      subject_id: subject,
      intent: { kind: 'perform', target_id: 'district:marker:visit', affordance: 'visit' },
    });
  });
});

describe('society directed-action control', () => {
  it('gates v4 and missing selection without inventing a record', () => {
    const v2 = v2Snapshot();
    expect(societyDirectedActionGate(null, subject).ok).toBe(false);
    expect(reasonOf(societyDirectedActionGate(v2, null))).toMatch(/Select a synthetic inhabitant/);
    const living = parseSociety({
      society_id: 'society', version_id: version, branch_id: version, place_id: 'place',
      population_size: 1, current_tick: 0, state_sha256: digest,
      input_seq: 1, input_sha256: digest,
      state: {
        profile: 'exulanica-society/v4', society_id: 'society', branch_id: version,
        tick: 0, tick_seconds: 60, input_seq: 1, input_sha256: digest,
        clock: { start_minute_of_day: 0, minute_of_day: 0, day: 0 },
        routine: {
          catalog_versions: {
            'society-activity': 1, 'society-capacity': 1, 'society-need': 1,
            'society-policy': 1, 'society-use-class': 1,
          },
          sha256: digest,
        },
        population: { size: 1 },
        inhabitants: [{
          id: subject, ordinal: 0, synthetic: true, role: null,
          role_reason: 'place_publishes_no_premises', walk_speed_mm_per_tick: 70000,
          needs: { leisure: 300 }, position_mm: [0, 0], motion_path_mm: [[0, 0]],
          location: { indoors: false },
          action: { kind: 'idle', status: 'active', destination_id: null, reason: 'await' },
          goal: null, explanation: { summary: 'Waiting.', event_ids: [] },
        }],
      },
    });
    expect(reasonOf(societyDirectedActionGate(living, subject))).toMatch(/living society profile/);
    expect(societyDirectedActionGate(v2, subject)).toEqual({ ok: true });
  });

  it('issues perform from the destination control and shows the returned record', async () => {
    document.body.replaceChildren();
    const requestAction = vi.fn(async () => parseSocietyActionRecord(actionEnvelope(), version));
    const control = buildSocietyDirectedAction({
      client: { requestAction },
      getSnapshot: () => v2Snapshot(),
      getSubjectId: () => subject,
      targetId: 'district:marker:visit',
      affordance: 'visit',
    });
    document.body.append(control.root);
    expect(control.button.disabled).toBe(false);
    await control.issue();
    expect(requestAction).toHaveBeenCalledWith(
      expect.objectContaining({ versionId: version, currentTick: 3 }),
      subject,
      { kind: 'perform', targetId: 'district:marker:visit', affordance: 'visit' },
    );
    expect(control.status.textContent).toMatch(/Simulation action request recorded/);
    expect(control.status.textContent).toMatch(/not personal evidence/);
  });

  it('shows an explicit refused state from the API without inventing a memory', async () => {
    const control = buildSocietyDirectedAction({
      client: {
        requestAction: async () => {
          throw new ApiError(409, 'invalid_society_action', 'unknown canonical target');
        },
      },
      getSnapshot: () => v2Snapshot(),
      getSubjectId: () => subject,
      targetId: 'browser:pixel:1,2',
      affordance: 'visit',
    });
    await control.issue();
    expect(control.status.textContent).toBe(
      'Directed action refused: unknown canonical target',
    );
    expect(describeSocietyActionFailure(
      new ApiError(424, 'unavailable_society_input', 'current society input authorization is not configured'),
    )).toMatch(/^Directed action unavailable:/);
  });
});

describe('society directed-action control refresh', () => {
  it('re-gates when the held society or inhabitant changes, keeping a result only while it applies', async () => {
    let snapshot: ReturnType<typeof v2Snapshot> | null = v2Snapshot();
    let selected: string | null = subject;
    const requestAction = vi.fn(async () => parseSocietyActionRecord(actionEnvelope(), version));
    const control = buildSocietyDirectedAction({
      client: { requestAction },
      getSnapshot: () => snapshot,
      getSubjectId: () => selected,
      targetId: 'district:marker:visit',
      affordance: 'visit',
    });
    await control.issue();
    const recorded = control.status.textContent;
    expect(recorded).toMatch(/Simulation action request recorded/);

    // A newer state of the same society, same inhabitant: the record stays shown.
    snapshot = v2Snapshot();
    control.reflect();
    expect(control.status.textContent).toBe(recorded);
    expect(control.button.disabled).toBe(false);

    // The inhabitant left the society: refused, and the old record is not shown as current.
    snapshot = v2Snapshot({ without: subject });
    control.reflect();
    expect(control.button.disabled).toBe(true);
    expect(control.status.textContent).toBe('The selected inhabitant is not in the current society state.');

    // No inhabitant selected, then no society at all.
    snapshot = v2Snapshot();
    selected = null;
    control.reflect();
    expect(control.status.textContent).toMatch(/Select a synthetic inhabitant/);
    snapshot = null;
    control.reflect();
    expect(control.button.disabled).toBe(true);
    expect(control.status.textContent).toMatch(/Connect a persisted society/);

    // Back to an eligible selection in a different society: enabled, and the record is gone.
    snapshot = v2Snapshot({ societyId: 'another-society' });
    selected = subject;
    control.reflect();
    expect(control.button.disabled).toBe(false);
    expect(control.status.textContent).not.toBe(recorded);
    expect(requestAction).toHaveBeenCalledTimes(1);
  });
});
