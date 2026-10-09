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
import { appearanceWireFromPlan, mountCompanionPlans, WAIT_CODES, type CompanionPlansDeps } from '../src/composition/companion-plan.js';
import type { PlannedRequest } from '../src/ui/actions/planned.js';
import { ACTIONS } from '../src/ui/actions/registry.js';
import type { ActionHost } from '../src/ui/actions/surfaces.js';
import { buildPlanSheet, thingDetail } from '../src/ui/companion-plan.js';
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
  /** What a waiting step's row said under it at each pause. */
  readonly whens: (string | null)[];
}

function harness(options: {
  readonly plan?: () => Promise<unknown>;
  readonly prepare?: () => Promise<unknown>;
  readonly send?: (request: PlannedRequest, index: number) => Promise<unknown>;
  readonly outcome?: unknown;
  readonly capabilities?: OperationDescriptors | null;
  readonly paused?: () => boolean;
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
    prepare: vi.fn(async () => (options.prepare === undefined
      ? plan('world-edit-plan') : parseActionPlan(await options.prepare()))),
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
    // A step that waits for the world's next minute waits no time here.
    pause: async () => { whens.push(sheet.root.querySelector('.companion-plan-step-when')?.textContent ?? null); },
    ...(options.paused === undefined ? {} : { paused: options.paused }),
  };
  const whens: (string | null)[] = [];
  plans = mountCompanionPlans(deps);
  return { plans, sheet, sent, afterTime, onSaid, client, whens };
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
  it('keeps the answer for every step: a plan placing two objects, answered once, sends both', async () => {
    // As the server prepares: with no origin role the bench asks for one; with one it is a step.
    const planned = fixture('world-edit-plan') as { steps: Record<string, unknown>[] };
    const step = planned.steps[0]!;
    const twoBenches = { ...planned, steps: [step, { ...step, index: 1 }] };
    const asking = (actions: unknown[]) => ({ ...planned, outcome: 'clarify', steps: [], clarification: {
      code: 'origin_role_required', step: 0, slot: null,
      candidates: [{ value: 'fictional', title: '', selected: false }, { value: 'personal', title: '', selected: false }],
      actions,
    } });
    const h = harness({ plan: async () => asking([step['action'], step['action']]) });
    h.client.prepare.mockImplementation(async (page: ActionPageContext, actions: unknown[]) => parseActionPlan(
      page.originRole === null ? asking(actions)
        : actions.length === 2 ? twoBenches : { ...planned, steps: [{ ...step, index: 0 }] }));
    await h.plans.route('put two benches here');
    h.sheet.root.querySelector<HTMLButtonElement>('[data-action="plan.choose"]')!.click();
    for (let i = 0; i < 10 && h.sheet.root.querySelector('[data-action="plan.confirm"]') === null; i += 1) await settle();
    await confirmAndWait(h);
    // The second bench is prepared again against the page as it is now, with the role answered.
    expect(h.client.prepare.mock.calls.at(-1)![0]).toMatchObject({ originRole: 'fictional' });
    expect(h.sent.map((request) => request.actionId)).toEqual(['objects.place', 'objects.place']);
    expect(stepStates(h.sheet)).toEqual(['done', 'done']);
  });
});

describe('a plan of things', () => {
  // Real answers from tests/test_companion_things_postgres.py's world: a lantern placed beside
  // the knight, then the knight sent to the well, and the prepare answer that says to wait.
  it('says each step in the words the server’s reads gave it', async () => {
    const h = harness({ plan: async () => fixture('thing-plan') });
    await h.plans.route('put a lantern by the knight and send him to the well');
    const rows = [...h.sheet.root.querySelectorAll('.companion-plan-step')].map((row) => [
      row.querySelector('.companion-plan-step-label')?.textContent,
      row.querySelector('.companion-plan-step-detail')?.textContent,
    ]);
    expect(rows).toEqual([['Add a thing', 'Lantern, beside Knight'], ['Ask someone', 'Knight, go to the well']]);
    expect(h.sheet.root.querySelector('.companion-plan-spends')?.textContent).toBe('Carrying this out asks no model.');
  });

  it('prepares a step asking a being again before it is sent, waiting while it must', async () => {
    const answers = [fixture('thing-direct-waiting'), fixture('thing-direct-waiting'), fixture('thing-direct-plan')];
    const h = harness({
      plan: async () => fixture('thing-direct-plan'),
      prepare: async () => answers.shift(),
      outcome: { profile: 'exulanica.companion-action-outcome/v1', state: 'pending', steps: [], alternatives: [] },
    });
    await h.plans.route('send the knight to the well');
    await confirmAndWait(h);
    expect(h.client.prepare).toHaveBeenCalledTimes(3);
    expect(h.sent.map((request) => request.actionId)).toEqual(['people.direct']);
    expect(stepStates(h.sheet)).toEqual(['done']);
    // While it waited, its row said for what; once sent, that line is gone.
    expect(h.whens).toEqual(['At the world’s next minute', 'At the world’s next minute']);
    expect(h.sheet.root.querySelector('.companion-plan-step-when')).toBeNull();
  });

  it('says how to move a paused world on while a step waits for its next minute', async () => {
    const answers = [fixture('thing-direct-waiting'), fixture('thing-direct-plan')];
    const h = harness({
      plan: async () => fixture('thing-direct-plan'),
      prepare: async () => answers.shift(),
      outcome: { profile: 'exulanica.companion-action-outcome/v1', state: 'pending', steps: [], alternatives: [] },
      paused: () => true,
    });
    await h.plans.route('send the knight to the well');
    await confirmAndWait(h);
    expect(h.whens).toEqual(['At the world’s next minute: the world is paused, so play it or move it on a minute.']);
  });

  it('says a step asking a being to use their hands in words, and who the other person is when asked', () => {
    // CX-2's step shape (AGENTS, 2026-10-08): act and the served titles; no target or place.
    const step = (act: string, titles: Record<string, string>) => {
      const served = structuredClone(fixture('thing-direct-plan')) as { steps: Record<string, unknown>[] };
      served.steps[0] = { ...served.steps[0], action: { operation: 'direct_thing', act, subject_id: 's', thing_id: 'sword' }, titles };
      return parseActionPlan(served).steps[0]!;
    };
    expect([
      thingDetail(step('pick_up', { subject: 'Knight', act: 'pick_up', thing: 'lantern' })),
      thingDetail(step('put_down', { subject: 'Knight', act: 'put_down', thing: 'lantern' })),
      thingDetail(step('give', { subject: 'Knight', act: 'give', thing: 'sword', with: 'Traveller' })),
      thingDetail(step('take', { subject: 'Knight', act: 'take', thing: 'sword', with: 'Traveller' })),
      // A give whose other person the server could not name says nothing rather than half a sentence.
      thingDetail(step('give', { subject: 'Knight', act: 'give', thing: 'sword' })),
    ]).toEqual([
      'Knight, pick up the lantern', 'Knight, put down the lantern',
      'Knight, give the sword to Traveller', 'Knight, take the sword from Traveller', null,
    ]);
    const sheet = buildPlanSheet({ onConfirm: vi.fn(), onCancel: vi.fn(), onChoose: vi.fn(), onPlay: vi.fn() });
    const served = fixture('thing-direct-plan') as Record<string, unknown>;
    const asking = parseActionPlan({ ...served, outcome: 'clarify', steps: [], clarification: {
      code: 'being_required', step: 0, slot: 'with_id', candidates: [], actions: [] } });
    sheet.showClarification(asking, 'give the sword', (_value, title) => title);
    expect(sheet.root.querySelector('.companion-plan-intro')?.textContent)
      .toBe('Who is the other person? Click them in the world, then ask again.');
  });

  it('says why a step asking a being was refused when prepared again, in its own action\'s words', async () => {
    // The answer a prepare gave on slot 6 (10-09) when the well was full that minute.
    const served = fixture('thing-direct-plan') as { steps: Record<string, unknown>[] };
    const full = { ...served, outcome: 'refused', steps: [{ ...served.steps[0], state: 'blocked', code: 'destination_full' }],
      refusal: { code: 'preview_blocked', detail: 'the authority\'s preview refused the step; its code is the step\'s', step: 0,
        operation: 'POST /world/versions/{version_id}/society/actions', capability: null, alternatives: [] } };
    const h = harness({ plan: async () => fixture('thing-direct-plan'), prepare: async () => full });
    await h.plans.route('send the knight to the well');
    confirmButton(h.sheet).click();
    for (let i = 0; i < 50 && h.sheet.root.querySelector('[data-action="plan.close"]') === null; i += 1) await settle();
    expect(h.sent).toEqual([]);
    expect(h.sheet.root.querySelector('.companion-plan-step-held')?.textContent).toBe('Every place there is taken. Ask again when someone leaves.');
  });

  it('says a prepare the server refused by what it answered, and says the world changed only when it did', async () => {
    const said = async (refusal: ApiError): Promise<string | null | undefined> => {
      const h = harness({ plan: async () => fixture('thing-direct-plan'), prepare: async () => { throw refusal; } });
      await h.plans.route('send the knight to the well');
      confirmButton(h.sheet).click();
      for (let i = 0; i < 50 && h.sheet.root.querySelector('[data-action="plan.close"]') === null; i += 1) await settle();
      expect(h.sent).toEqual([]);
      return h.sheet.root.querySelector('.companion-plan-step-held')?.textContent;
    };
    // A request the route will not take (its own 422, no problem code) is not a world that changed.
    expect(await said(new ApiError(422, 'http_422', 'Unprocessable Entity')))
      .toBe('The world did not take the step I prepared. Reload the page, then ask again, or make the change yourself.');
    expect(await said(new ApiError(409, 'stale_society_state', 'the society moved on')))
      .toBe('This world changed while I was reading what you asked. Ask again and I will plan against what it is now.');
    expect(await said(new ApiError(404, 'unknown_reference', 'no such version')))
      .toBe('This world, or something the step names, is no longer there. Reload the page, then ask again.');
  });

  it('says a step waits for a free place where every place is taken, and names an unnamed place plainly', async () => {
    const served = fixture('thing-direct-waiting') as { steps: Record<string, unknown>[] };
    const full = (place: string) => ({ ...served, steps: [{ ...served.steps[0], code: 'destination_full',
      titles: { subject: 'Knight', act: 'go_to', affordance: 'visit', place } }] });
    const answers = [full('bakery at number 12'), full('a place'), fixture('thing-direct-plan')];
    const h = harness({
      plan: async () => fixture('thing-direct-plan'),
      prepare: async () => answers.shift(),
      outcome: { profile: 'exulanica.companion-action-outcome/v1', state: 'pending', steps: [], alternatives: [] },
    });
    await h.plans.route('send the knight to the bakery');
    await confirmAndWait(h);
    expect(h.whens).toEqual(['Waiting for a free place at the bakery at number 12.', 'Waiting for a free place at a place.']);
    expect(stepStates(h.sheet)).toEqual(['done']);
  });

  it('waits on exactly the codes the server prepares a waiting step with', () => {
    // exulanica/selection/action_things.py states them as one frozenset literal.
    const python = readFileSync(`${repository}/exulanica/selection/action_things.py`, 'utf8');
    const stated = /WAIT_CODES: Final = frozenset\(\s*\{([^}]*)\}\s*\)/u.exec(python)?.[1];
    expect(stated).toBeDefined();
    const codes = [...stated!.matchAll(/"([a-z_]+)"/gu)].map((match) => match[1]);
    expect([...WAIT_CODES].sort()).toEqual(codes.sort());
  });

  it('titles a refusal said after a question as the plan, not as the question', () => {
    const sheet = buildPlanSheet({ onConfirm: vi.fn(), onCancel: vi.fn(), onChoose: vi.fn(), onPlay: vi.fn() });
    const served = fixture('thing-direct-plan') as Record<string, unknown>;
    sheet.showClarification(parseActionPlan({ ...served, outcome: 'clarify', steps: [], clarification: {
      code: 'place_required', step: 0, slot: null, candidates: [], actions: [] } }), 'go somewhere', (_v, title) => title);
    sheet.say({ happened: 'There is no free room for it there.', next: 'Make some space, or ask to put it somewhere else.' });
    expect(sheet.root.querySelector('h2, h3, .x-panel-title, [class*=title]')?.textContent).toBe('Check this plan');
  });

  it('sends nothing, and says why, when the world never moves on', async () => {
    const h = harness({
      plan: async () => fixture('thing-direct-plan'),
      prepare: async () => fixture('thing-direct-waiting'),
    });
    await h.plans.route('send the knight to the well');
    confirmButton(h.sheet).click();
    for (let i = 0; i < 200 && h.sheet.root.querySelector('[data-action="plan.close"]') === null; i += 1) await settle();
    expect(h.sent).toEqual([]);
    expect(stepStates(h.sheet)).toEqual(['not-done']);
    expect(h.sheet.root.querySelector('.companion-plan-step-held')?.textContent)
      .toBe('The world did not move on, so this step was not sent. Play the world, or move it on a minute, then ask again.');
  });
});
