// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { ApiError } from '@exulanica/graph-client';
import { describe, expect, it, vi } from 'vitest';

import { proposalFromWire, type WireProposal } from '../src/companion-ask-api.js';
import {
  parseActionOutcome,
  parseActionPlan,
  type ActionPageContext,
  type ActionPlan,
  type CompanionActionsClient,
} from '../src/companion-actions-api.js';
import { parseWorldCapabilities, type OperationDescriptors } from '../src/capabilities-api.js';
import { appearanceWireFromPlan, mountCompanionPlans, type CompanionPlansDeps } from '../src/composition/companion-plan.js';
import type { PlannedRequest } from '../src/ui/actions/planned.js';
import { ACTIONS } from '../src/ui/actions/registry.js';
import type { ActionHost } from '../src/ui/actions/surfaces.js';
import { buildPlanSheet } from '../src/ui/companion-plan.js';
import { toastStack } from '../src/ui/system/components.js';

/*
 * The Companion's plans from the routing of a sentence to what each step came to. The plans,
 * the chain's responses and the outcome reads are real answers from the scripted model
 * (test/companion-plans/); the routes they are sent to are stood in for here.
 */

const repository = `${process.cwd()}/..`;
const fixture = (name: string): unknown =>
  JSON.parse(readFileSync(`${repository}/web/packages/app/test/companion-plans/${name}.json`, 'utf8'));
const plan = (name: string): ActionPlan => parseActionPlan(fixture(name));
const responses = (name: string): { status: number; body: unknown }[] => fixture(name) as { status: number; body: unknown }[];

const PAGE: ActionPageContext = {
  versionId: 'v', baseStateSha256: '0'.repeat(64), originRole: null, context: {}, savedEntry: null,
};

/** Every registry operation available, as a world that offers them all would read. */
const everything: OperationDescriptors = parseWorldCapabilities({
  profile: 'exulanica.world-capabilities/v1', world_id: 'world:test', version_id: 'v', kind: 'authored-starter',
  society: { held: true, engine: 'exulanica-society/v2' },
  operations: [...new Set(ACTIONS.flatMap((spec) => (spec.operation === undefined ? [] : [spec.operation])))]
    .map((operation) => ({ operation, bind: {}, permitted: true, state: 'available', code: null, spends: false,
      writes: true, effects: [], dependencies: [], preview: null })),
});

interface Harness {
  readonly plans: ReturnType<typeof mountCompanionPlans>;
  readonly sheet: ReturnType<typeof buildPlanSheet>;
  readonly sent: PlannedRequest[];
  readonly afterTime: ReturnType<typeof vi.fn>;
  readonly onSaid: ReturnType<typeof vi.fn>;
  readonly client: { plan: ReturnType<typeof vi.fn>; prepare: ReturnType<typeof vi.fn>; outcome: ReturnType<typeof vi.fn> };
}

function harness(options: {
  readonly plan?: () => Promise<unknown>;
  readonly send?: (request: PlannedRequest, index: number) => Promise<unknown>;
  readonly outcome?: unknown;
  readonly capabilities?: OperationDescriptors | null;
}): Harness {
  const sent: PlannedRequest[] = [];
  const host: ActionHost = {
    binding: () => undefined,
    capabilities: () => (options.capabilities === undefined ? everything : options.capabilities),
    onChange: () => () => undefined,
    toasts: toastStack(),
    send: async (request) => {
      sent.push(request);
      return { status: 200, body: (await options.send?.(request, sent.length - 1)) ?? {} };
    },
  };
  const client = {
    plan: vi.fn(async () => parseActionPlan(await (options.plan ?? (async () => fixture('world-edit-plan')))())),
    prepare: vi.fn(async () => plan('world-edit-plan')),
    outcome: vi.fn(async () => parseActionOutcome(options.outcome ?? fixture('world-edit-outcome'))),
  };
  let plans!: ReturnType<typeof mountCompanionPlans>;
  const sheet = buildPlanSheet({
    onConfirm: () => plans.confirm(),
    onCancel: () => plans.cancel(),
    onChoose: (c, v) => plans.choose(c, v),
    onPlay: vi.fn(),
  });
  document.body.replaceChildren(sheet.root);
  const afterTime = vi.fn(async () => undefined);
  const onSaid = vi.fn();
  const deps: CompanionPlansDeps = {
    client: () => client as unknown as CompanionActionsClient,
    page: () => PAGE,
    host: () => host,
    sheet,
    afterTime,
    particular: (step) => (step.action['asset_key'] === 'cc0.bench' ? 'Bench' : null),
    waitMs: 1000,
    onSaid,
  };
  plans = mountCompanionPlans(deps);
  return { plans, sheet, sent, afterTime, onSaid, client };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const confirmButton = (sheet: Harness['sheet']) => sheet.root.querySelector<HTMLButtonElement>('[data-action="plan.confirm"]')!;
const stepStates = (sheet: Harness['sheet']) =>
  [...sheet.root.querySelectorAll<HTMLElement>('.companion-plan-step')].map((row) => row.dataset['progress'] ?? 'shown');
async function confirmAndWait(h: Harness): Promise<void> {
  confirmButton(h.sheet).click();
  for (let i = 0; i < 20 && h.sheet.root.querySelector('[data-action="plan.close"]') === null; i += 1) await settle();
}

describe('where a sentence goes', () => {
  it('takes the path it took before when the plan route cannot answer', async () => {
    const unscripted = fixture('unscripted-refusal') as { status: number; code: string };
    const h = harness({ plan: async () => { throw new ApiError(unscripted.status, unscripted.code, `${unscripted.code}: no`); } });
    expect(await h.plans.route('what is this place')).toEqual({ route: 'fallback' });
    const slow = harness({ plan: () => new Promise(() => undefined) });
    expect(await slow.plans.route('anything')).toEqual({ route: 'fallback' });
  });

  it('sends a question on to the answer path', async () => {
    const question = { ...(fixture('world-edit-plan') as object), outcome: 'question', kind: 'question', steps: [] };
    expect(await harness({ plan: async () => question }).plans.route('who lives here?')).toEqual({ route: 'question' });
  });

  it('shows a world edit as its registry actions, with its spending said before Confirm', async () => {
    const h = harness({});
    const routed = await h.plans.route('put a bench here');
    expect(routed).toMatchObject({ route: 'answer', sentences: ['Here is what I would do. Check it, then confirm.'], refused: false });
    expect(h.sheet.root.hidden).toBe(false);
    const row = h.sheet.root.querySelector('.companion-plan-step')!;
    expect(row.querySelector('.companion-plan-step-label')?.textContent).toBe('Place an object');
    expect(row.querySelector('.companion-plan-step-detail')?.textContent).toBe('Bench');
    expect(h.sheet.root.querySelector('.companion-plan-spends')?.textContent).toBe('Carrying this out asks no model.');
    expect(h.sent).toEqual([]);
    // Nothing important sits in a closed disclosure: only the technical record does.
    expect([...h.sheet.root.querySelectorAll('details')].every((d) => d.classList.contains('x-technical'))).toBe(true);
  });

  it('holds Confirm, in the action’s words, where a step is not available now', async () => {
    const h = harness({ capabilities: null });
    await h.plans.route('put a bench here');
    expect(confirmButton(h.sheet).disabled).toBe(true);
    expect(h.sheet.root.querySelector('.companion-plan-step-held')?.textContent).toContain('Can’t tell yet');
  });
});

describe('an appearance change from a plan', () => {
  // A plan as `_appearance_document` (exulanica/selection/action_plan.py) writes one.
  const appearancePlan = (basis: string): unknown => ({
    profile: 'exulanica.companion-action-plan/v1', outcome: 'plan', kind: 'appearance',
    world_id: 'world:authored:x', version_id: 'v', plan_sha256: 'a'.repeat(64), atomic: false,
    spends: false, spends_by: [], clarification: null, refusal: null, capabilities: null,
    proposal_speech: 'I would warm the light a little.', clock: null, names: {},
    execution: { prompt_version: 'companion-actions/v3', calls: [] },
    steps: [{
      index: 0, action: { operation: 'propose_appearance', appearance_basis: basis }, state: 'prepared', code: null,
      operation: 'POST /world/styles/previews', bind: {}, query: { world_id: 'world:authored:x' },
      body: {
        proposal_id: 'p', origin: 'companion', origin_reference: 'companion-action-plan:p', scope: { kind: 'global', region_id: null },
        base_style_version_id: 's1', base_topology_digest: 'd1',
        profile: { profile_id: 'origin-landscape', profile_version: 1, parameters: { warmth: 0.7, veil: 0.4 } },
        reference_ids: ['ref-1'], model_id: 'Qwen/Qwen3-235B-A22B-Instruct-2507', prompt_version: 'companion-appearance/v9',
        refines_proposal_id: null, appearance_basis: basis,
      },
      requires: ['world.write'], permitted: true, spends: false,
      preview: { operation: null, body: null, document: { changed: ['warmth'], modules: ['light'] }, document_sha256: 'b'.repeat(64) },
      pins: { base_style_version_id: 's1', base_topology_digest: 'd1' }, effects: [], confirmation: 'required',
      replay: 'proposal_id_refused', receipt: 'style_preview', compensation: null,
    }],
  });
  // The same proposal as `POST /selection/appearance` answers it.
  const appearanceRoute: WireProposal = {
    classification: 'appearance',
    proposal: {
      profile: { profile_id: 'origin-landscape', profile_version: 1, parameters: { warmth: 0.7, veil: 0.4 }, modules: ['light'], changed: ['warmth'] },
      reference_ids: ['ref-1'], model_id: 'Qwen/Qwen3-235B-A22B-Instruct-2507', prompt_version: 'companion-appearance/v9',
      spoken: 'I would warm the light a little.', base_style_version_id: 's1', base_topology_digest: 'd1',
    },
    refusal: null,
    execution: { prompt_version: 'companion-actions/v3', calls: [] } as unknown as WireProposal['execution'],
  };

  it('is the proposal the appearance route would have given, field for field', async () => {
    const fromPlan = appearanceWireFromPlan(parseActionPlan(appearancePlan('evidence')))!;
    expect(proposalFromWire('warmer', fromPlan)).toEqual(proposalFromWire('warmer', appearanceRoute));
    const routed = await harness({ plan: async () => appearancePlan('evidence') }).plans.route('warmer');
    expect(routed).toMatchObject({ route: 'appearance', proposal: {
      proposal: { modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507', promptVersion: 'companion-appearance/v9' },
    } });
  });

  it('is never sent from the plan, and takes the old path where its basis is not the evidence', async () => {
    const h = harness({ plan: async () => appearancePlan('authored_design') });
    expect(await h.plans.route('a new look')).toEqual({ route: 'fallback' });
    expect(h.sent).toEqual([]);
  });
});

describe('a confirmed plan', () => {
  it('sends a world edit through its registry entry and says it happened', async () => {
    const h = harness({});
    await h.plans.route('put a bench here');
    await confirmAndWait(h);
    expect(h.sent.map((request) => [request.actionId, request.method])).toEqual([['objects.place', 'POST']]);
    expect(stepStates(h.sheet)).toEqual(['done']);
    expect(h.sheet.root.querySelector('.companion-plan-summary')?.textContent?.trim()).toBe('Done. Every step happened.');
  });

  it('runs a chain, each step with its bases from the response before it', async () => {
    const answered = responses('simulation-responses');
    const h = harness({
      plan: async () => fixture('simulation-plan'),
      send: async (_request, index) => answered[index]!.body,
      outcome: fixture('simulation-outcome'),
    });
    await h.plans.route('move time on three minutes');
    await confirmAndWait(h);
    expect(h.sent.map((request) => request.actionId)).toEqual(['clock.advance', 'clock.advance', 'clock.advance']);
    const first = answered[0]!.body as { control: { revision: number }; society: { state_sha256: string } };
    expect(h.sent[1]!.body).toMatchObject({ base_revision: first.control.revision, base_state_sha256: first.society.state_sha256 });
    expect(stepStates(h.sheet)).toEqual(['done', 'done', 'done']);
    expect(h.afterTime).toHaveBeenCalledOnce();
  });

  it('reports each sent step’s own answer with the outcome, and none for a step not reached', async () => {
    // The server's step answer carries a receipt (society_control_repository.manual_step); the
    // recorded responses predate it, so each is given one here.
    const answered = responses('stopped-responses');
    const receipt = { event_seq: 41, document_sha256: 'd'.repeat(64), kind: 'manual_step' };
    const h = harness({
      plan: async () => fixture('simulation-plan'),
      send: async (_request, index) => {
        if (index === 0) return { ...(answered[0]!.body as object), receipt };
        throw new ApiError(409, 'stale_society_state', 'stale_society_state: society changed; reload before advancing');
      },
      outcome: { ...(fixture('stopped-outcome') as object), state: 'partial', alternatives: ['play'] },
    });
    await h.plans.route('move time on three minutes');
    await confirmAndWait(h);
    expect(h.client.outcome).toHaveBeenCalledOnce();
    const answers = h.client.outcome.mock.calls[0]![1] as Record<number, unknown>;
    expect(answers).toEqual({
      0: { status: 200, code: null, event_seq: 41, document_sha256: 'd'.repeat(64) },
      1: { status: 409, code: 'stale_society_state' },
    });
  });

  it('stops where a step is refused, shows what happened and what was not reached, and offers Play', async () => {
    const answered = responses('stopped-responses');
    const h = harness({
      plan: async () => fixture('simulation-plan'),
      send: async (_request, index) => {
        if (index === 0) return answered[0]!.body;
        throw new ApiError(409, 'stale_society_state', 'stale_society_state: society changed; reload before advancing');
      },
      outcome: { ...(fixture('stopped-outcome') as object), state: 'partial', alternatives: ['play'] },
    });
    await h.plans.route('move time on three minutes');
    await confirmAndWait(h);
    expect(h.sent).toHaveLength(2);
    expect(stepStates(h.sheet)).toEqual(['done', 'not-done', 'not-reached']);
    expect(h.sheet.root.textContent).toContain('The world moved on while you were deciding, so its clock did not change.');
    expect(h.sheet.root.querySelector('.companion-plan-summary')?.textContent).toContain('Partly done: 1 of 3 steps happened.');
    expect(h.sheet.root.querySelector('[data-action="clock.play"]')).not.toBeNull();
    // The code is in the technical record, not in the words.
    expect(h.sheet.root.querySelector('.x-technical')?.textContent).toContain('stale_society_state');
  });

  it('never sends a step whose plan names another route than its registry entry', async () => {
    const tampered = fixture('world-edit-plan') as { steps: { operation: string }[] };
    tampered.steps[0]!.operation = 'POST /world/versions/{version_id}/objects/undo';
    const h = harness({ plan: async () => tampered });
    await h.plans.route('put a bench here');
    expect(confirmButton(h.sheet).disabled).toBe(true);
    await h.plans.confirm();
    await settle();
    expect(h.sent).toEqual([]);
  });
});

describe('a question asked before a plan', () => {
  // The plan the planner gives when it needs the person's own role for the bench first.
  const clarify = (): unknown => {
    const planned = fixture('world-edit-plan') as { steps: { action: object }[] };
    return { ...planned, outcome: 'clarify', steps: [], clarification: {
      code: 'origin_role_required', step: 0, slot: null,
      candidates: [{ value: 'fictional', title: '', selected: false }, { value: 'personal', title: '', selected: false }],
      actions: [planned.steps[0]!.action],
    } };
  };

  it('asks it on the sheet in words, then shows the plan and says so once answered', async () => {
    const h = harness({ plan: async () => clarify() });
    // Preparing the answered question asks no model, as /selection/actions/prepare does not.
    const prepared = fixture('world-edit-plan') as { execution: object };
    h.client.prepare.mockResolvedValueOnce(parseActionPlan({ ...prepared, execution: { ...prepared.execution, calls: [] } }));
    const routed = await h.plans.route('put a bench here');
    expect(routed).toMatchObject({ route: 'answer', refused: false });
    const choices = [...h.sheet.root.querySelectorAll<HTMLButtonElement>('[data-action="plan.choose"]')];
    expect(choices.map((b) => b.textContent)).toEqual(['Invented for this world', 'Connected to something I experienced']);
    choices[0]!.click();
    for (let i = 0; i < 10 && h.onSaid.mock.calls.length === 0; i += 1) await settle();
    // The role chosen is sent as the person's own choice, with no model.
    expect(h.client.prepare).toHaveBeenCalledWith(expect.objectContaining({ originRole: 'fictional' }), expect.any(Array));
    expect(h.sheet.root.querySelector('[data-action="plan.confirm"]')).not.toBeNull();
    // And the Companion stops asking: it now says what the sheet shows.
    expect(h.onSaid).toHaveBeenCalledWith('put a bench here', expect.objectContaining({
      sentences: ['Here is what I would do. Check it, then confirm.'],
    }));
    // Under it, the model that read the sentence, not "no model was asked".
    const said = h.onSaid.mock.calls[0]![1] as { calls: readonly unknown[] };
    const read = (fixture('world-edit-plan') as { execution: { calls: unknown[] } }).execution.calls;
    expect(said.calls.length).toBe(read.length);
    expect(read.length).toBeGreaterThan(0);
  });
});
