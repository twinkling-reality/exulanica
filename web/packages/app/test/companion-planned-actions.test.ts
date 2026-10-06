// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { ApiError } from '@exulanica/graph-client';
import { describe, expect, it, vi } from 'vitest';

import { parseActionPlan, type ActionPlan, type PlanStep } from '../src/companion-actions-api.js';
import { parseWorldCapabilities, type OperationDescriptors } from '../src/capabilities-api.js';
import { PLAN_ACTIONS, plannedEntry, plannedRequest, stepAnswer } from '../src/ui/actions/planned.js';
import { actionSpec } from '../src/ui/actions/registry.js';
import { performPlanned, type ActionHost } from '../src/ui/actions/surfaces.js';
import { toastStack } from '../src/ui/system/components.js';

/*
 * A Companion plan step is sent as a registry action: the entry its typed action maps to gives
 * the route, words and availability; the plan gives only path values, body and pins. The plans
 * here are real `POST /selection/actions` and `/prepare` answers from the scripted model.
 */

// The DOM environment gives no file URL here; vitest runs from web/, as arrangement.test.ts reads.
const repository = `${process.cwd()}/..`;
const fixture = (name: string): unknown =>
  JSON.parse(readFileSync(`${repository}/web/packages/app/test/companion-plans/${name}.json`, 'utf8'));
const plan = (name: string): ActionPlan => parseActionPlan(fixture(name));
const responses = (name: string): unknown[] => (fixture(name) as { body: unknown }[]).map((row) => row.body);
const planner = readFileSync(`${repository}/exulanica/selection/action_plan.py`, 'utf8');
const routes = readFileSync(`${repository}/exulanica/api/routes/selection_actions.py`, 'utf8');

function enumValues(name: string): string[] {
  const start = planner.indexOf(`class ${name}(StrEnum):`);
  const end = planner.indexOf('\n\n\n', start);
  return [...planner.slice(start, end).matchAll(/^\s+[A-Z_]+ = "([a-z_]+)"$/gm)].map((m) => m[1]!);
}

describe('the planner’s vocabulary on the registry', () => {
  it('maps every word the planner can write, or says it is deliberately not sent', () => {
    const words = new Set([
      ...enumValues('WorldEditOperation'),
      ...enumValues('SimulationAction'),
      ...[...planner.matchAll(/"operation": "([a-z_]+_appearance)"/g)].map((m) => m[1]!),
    ]);
    expect(words.size).toBeGreaterThan(10);
    expect([...words].filter((word) => !Object.hasOwn(PLAN_ACTIONS, word))).toEqual([]);
    expect(Object.keys(PLAN_ACTIONS).filter((word) => !words.has(word))).toEqual([]);
  });

  it('sends each mapped word to a route a plan step may name, through an entry with words', () => {
    const allowed = [...routes.slice(routes.indexOf('OutcomeOperation = Literal['), routes.indexOf(']', routes.indexOf('OutcomeOperation = Literal[')))
      .matchAll(/"([A-Z]+ \/[^"]+)"/g)].map((m) => m[1]!);
    for (const id of Object.values(PLAN_ACTIONS)) {
      if (id === null) continue;
      const spec = actionSpec(id);
      expect(allowed, id).toContain(spec.operation);
      expect(spec.label.trim(), id).not.toBe('');
    }
  });
});

describe('a planned step’s request', () => {
  it('goes to its registry entry’s route with the plan’s path values and body', () => {
    const step = plan('world-edit-plan').steps[0]!;
    const built = plannedRequest(step, []);
    if (!('request' in built)) throw new Error(JSON.stringify(built.refused));
    expect(built.request.actionId).toBe('objects.place');
    expect(built.request.method).toBe('POST');
    expect(built.request.path).toBe(`/world/versions/${step.bind['version_id']}/compositions/apply`);
    expect(built.request.body).toEqual(step.body);
  });

  it('is refused, never built, when the plan names another route than the entry’s', () => {
    const step = plan('world-edit-plan').steps[0]!;
    const elsewhere: PlanStep = { ...step, operation: 'POST /world/versions/{version_id}/objects/undo' };
    expect(plannedRequest(elsewhere, [])).toEqual({ refused: {
      kind: 'route-mismatch', action: 'place_object',
      planned: 'POST /world/versions/{version_id}/objects/undo',
      registry: 'POST /world/versions/{version_id}/compositions/apply',
    } });
    const outside: PlanStep = { ...step, operation: 'DELETE /admin/everything' };
    expect('refused' in plannedRequest(outside, [])).toBe(true);
  });

  it('is refused when its typed action maps to no entry', () => {
    const step = plan('world-edit-plan').steps[0]!;
    for (const operation of ['propose_appearance', 'other', 'drop_table']) {
      expect(plannedEntry({ ...step, action: { ...step.action, operation } })).toEqual({ refused: { kind: 'unmapped', action: operation } });
    }
  });

  it('takes a chained step’s bases from the response before it, as the plan says', () => {
    const chain = plan('simulation-plan');
    const sent = responses('simulation-responses');
    const second = plannedRequest(chain.steps[1]!, [sent[0]]);
    if (!('request' in second)) throw new Error(JSON.stringify(second.refused));
    const first = sent[0] as { control: { revision: number }; society: { state_sha256: string; current_tick: number } };
    expect(second.request.actionId).toBe('clock.advance');
    expect(second.request.body).toMatchObject({
      base_revision: first.control.revision,
      base_state_sha256: first.society.state_sha256,
      base_tick: first.society.current_tick,
    });
    // Without the earlier response there is nothing to send it with.
    expect(plannedRequest(chain.steps[1]!, [])).toMatchObject({ refused: { kind: 'missing-value' } });
  });
});

describe('sending a planned step', () => {
  const version = (state: string, code: string | null, operation: string) => parseWorldCapabilities({
    profile: 'exulanica.world-capabilities/v1', world_id: 'world:test', version_id: 'v1', kind: 'authored-starter',
    society: { held: true, engine: 'exulanica-society/v2' },
    operations: [{ operation, bind: { version_id: 'v1' }, permitted: true, state, code, spends: false, writes: true,
      effects: [], dependencies: [], preview: null }],
  });
  const host = (read: OperationDescriptors | null, send: NonNullable<ActionHost['send']>): ActionHost => ({
    binding: () => undefined, capabilities: () => read, onChange: () => () => undefined, toasts: toastStack(), send,
  });
  const advance = () => {
    const built = plannedRequest(plan('simulation-plan').steps[0]!, []);
    if (!('request' in built)) throw new Error('not built');
    return built.request;
  };

  it('is not sent where the action is not available, and says why in the action’s words', async () => {
    const send = vi.fn();
    const result = await performPlanned(host(version('unavailable', 'society_unavailable', actionSpec('clock.advance').operation!), send), advance());
    expect(send).not.toHaveBeenCalled();
    expect(result).toMatchObject({ kind: 'not-run', words: { happened: 'Nobody lives in this world yet.' } });
    expect((await performPlanned(host(null, send), advance())).kind).toBe('not-run');
  });

  it('returns the route’s answer, or its refusal in the same words the rail would use', async () => {
    const available = version('available', null, actionSpec('clock.advance').operation!);
    const ran = await performPlanned(host(available, async () => ({ status: 200, body: { ok: true } })), advance());
    expect(ran).toEqual({ kind: 'ran', status: 200, response: { ok: true } });
    const refused = await performPlanned(host(available, async () => {
      throw new ApiError(409, 'stale_society_state', 'stale_society_state: society changed; reload before advancing');
    }), advance());
    expect(refused).toMatchObject({ kind: 'refused', status: 409, code: 'stale_society_state',
      words: { happened: 'The world moved on while you were deciding, so its clock did not change.' } });
  });
});

describe('a sent step’s own answer, as the outcome read takes it', () => {
  // Expected shapes from deliveries/UIB/outcome-answer-shape.txt: which fields each route answers
  // with, and where in its body they are.
  const sha = (c: string) => c.repeat(64);
  it('takes an edit’s sequence and digest from the top of its body, or from its version', () => {
    expect(stepAnswer('POST /world/versions/{version_id}/compositions/apply',
      { status: 201, body: { edit_seq: 3, state_sha256: sha('a'), objects: [] } }))
      .toEqual({ status: 201, code: null, edit_seq: 3, state_sha256: sha('a') });
    expect(stepAnswer('POST /world/versions/{version_id}/objects/undo',
      { status: 200, body: { edit_seq: 4, state_sha256: sha('b') } }))
      .toEqual({ status: 200, code: null, edit_seq: 4, state_sha256: sha('b') });
    expect(stepAnswer('POST /world/versions/{version_id}/arrangements/apply',
      { status: 201, body: { version: { edit_seq: 5, state_sha256: sha('c') }, edit_seq: 99 } }))
      .toEqual({ status: 201, code: null, edit_seq: 5, state_sha256: sha('c') });
  });

  it('takes a clock step’s receipt, a clock setting’s revision and a society’s id', () => {
    expect(stepAnswer('POST /world/versions/{version_id}/society/control/steps',
      { status: 200, body: { receipt: { event_seq: 7, document_sha256: sha('d') }, control: { revision: 2 } } }))
      .toEqual({ status: 200, code: null, event_seq: 7, document_sha256: sha('d') });
    expect(stepAnswer('PUT /world/versions/{version_id}/society/control',
      { status: 200, body: { revision: 6, last_event_seq: 12, mode: 'playing' } }))
      .toEqual({ status: 200, code: null, revision: 6, last_event_seq: 12 });
    expect(stepAnswer('POST /world/versions/{version_id}/society',
      { status: 201, body: { society_id: '11111111-1111-4111-8111-111111111111' } }))
      .toEqual({ status: 201, code: null, society_id: '11111111-1111-4111-8111-111111111111' });
  });

  it('answers a refusal, and any other route, with its status and code only', () => {
    expect(stepAnswer('POST /world/versions/{version_id}/compositions/apply', { status: 409, code: 'stale_version' }))
      .toEqual({ status: 409, code: 'stale_version' });
    expect(stepAnswer('POST /world/styles/previews', { status: 201, body: { preview_id: 'p', edit_seq: 1 } }))
      .toEqual({ status: 201, code: null });
  });

  it('leaves out a field the body lacks rather than guessing it', () => {
    expect(stepAnswer('POST /world/versions/{version_id}/society/control/steps',
      { status: 200, body: { control: { revision: 1 } } }))
      .toEqual({ status: 200, code: null });
  });
});
