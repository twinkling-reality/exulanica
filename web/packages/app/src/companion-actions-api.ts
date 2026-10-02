/**
 * The Companion's world actions: a plan from words, typed actions prepared, and what was recorded.
 *
 * Speaks `POST /selection/actions`, `POST /selection/actions/prepare` and
 * `POST /selection/actions/outcome` (`exulanica/api/routes/selection_actions.py`, profile
 * `exulanica.companion-action-plan/v1`). None of the three changes the world. A plan's steps are
 * the exact requests a direct client sends; this module reads them and never sends one. Sending is
 * the action registry's (`ui/actions/planned.ts` and `perform` in `ui/actions/surfaces.ts`), which
 * takes the route from the registry entry a step maps to and only path values, body and pins from
 * the plan.
 *
 * The contract is read tolerantly: members this client does not use are kept in `raw` and ignored,
 * so a newer server never blanks the plan.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import { openWorldPath } from './world-scope.js';

export type PlanOutcome = 'plan' | 'clarify' | 'refused' | 'capabilities' | 'question';
export type PlanKind = 'question' | 'appearance' | 'world_edit' | 'simulation' | 'capabilities';
export type StepState = 'prepared' | 'pending' | 'blocked' | 'not_permitted';

/** A value taken from an earlier step's response: its index and a dotted path into the body. */
export interface FromEarlier {
  readonly step: number;
  readonly field: string;
}

export interface PlanStep {
  readonly index: number;
  /** The typed action, as the planner states it: `operation` is its vocabulary word. */
  readonly action: Readonly<Record<string, unknown>> & { readonly operation: string };
  readonly state: StepState;
  readonly code: string | null;
  /** The route key the plan says the request goes to. Checked against the registry, never used. */
  readonly operation: string;
  readonly bind: Readonly<Record<string, string | null>>;
  readonly bindFrom: Readonly<Record<string, FromEarlier>> | null;
  readonly query: Readonly<Record<string, string>>;
  readonly body: Readonly<Record<string, unknown>> | null;
  readonly bodyFrom: Readonly<Record<string, FromEarlier>> | null;
  readonly permitted: boolean;
  readonly spends: boolean;
  readonly confirmation: 'required' | 'chained';
  /** The step as the server sent it, for the outcome read and the technical record. */
  readonly raw: Readonly<Record<string, unknown>>;
}

export interface PlanRefusal {
  readonly code: string;
  readonly detail: string;
  readonly step: number | null;
  readonly operation: string | null;
  readonly alternatives: readonly string[];
}

export interface ClarificationCandidate {
  readonly value: string;
  readonly title: string;
  readonly selected: boolean;
}

export interface PlanClarification {
  readonly code: string;
  readonly step: number;
  readonly slot: string | null;
  readonly candidates: readonly ClarificationCandidate[];
  readonly actions: readonly Readonly<Record<string, unknown>>[];
}

export interface ActionPlan {
  readonly outcome: PlanOutcome;
  readonly kind: PlanKind;
  readonly worldId: string;
  readonly versionId: string;
  readonly planSha256: string;
  readonly atomic: boolean;
  readonly steps: readonly PlanStep[];
  /** Whether any step can lead to a hosted model call, said before the one confirmation. */
  readonly spends: boolean;
  /** The decision roles whose chosen models the steps can ask. */
  readonly spendsBy: readonly string[];
  readonly clarification: PlanClarification | null;
  readonly refusal: PlanRefusal | null;
  readonly capabilities: readonly Readonly<Record<string, unknown>>[] | null;
  /** The appearance drafter's own sentence about a proposal: never that anything happened. */
  readonly proposalSpeech: string | null;
  readonly raw: Readonly<Record<string, unknown>>;
}

export interface OutcomeStep {
  readonly index: number | null;
  readonly operation: string | null;
  readonly state: 'applied' | 'not_applied' | 'superseded' | 'pending';
  readonly code: string | null;
}

export interface ActionOutcome {
  readonly state: 'applied' | 'partial' | 'not_applied' | 'superseded' | 'pending';
  readonly steps: readonly OutcomeStep[];
  /** What the person could ask for next, by code: `play` after a chain left the world paused. */
  readonly alternatives: readonly string[];
}

const OUTCOMES: readonly PlanOutcome[] = ['plan', 'clarify', 'refused', 'capabilities', 'question'];
const KINDS: readonly PlanKind[] = ['question', 'appearance', 'world_edit', 'simulation', 'capabilities'];
const STEP_STATES: readonly StepState[] = ['prepared', 'pending', 'blocked', 'not_permitted'];

const record = (value: unknown, what: string): Record<string, unknown> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new TypeError(`Invalid plan: ${what}`);
  return value as Record<string, unknown>;
};
const text = (value: unknown, what: string): string => {
  if (typeof value !== 'string' || value.length === 0) throw new TypeError(`Invalid plan: ${what}`);
  return value;
};
const nullableText = (value: unknown): string | null => (typeof value === 'string' && value.length > 0 ? value : null);
const strings = (value: unknown): string[] => (Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []);
const oneOf = <T extends string>(value: unknown, allowed: readonly T[], what: string): T => {
  if (!(allowed as readonly unknown[]).includes(value)) throw new TypeError(`Invalid plan: ${what}`);
  return value as T;
};

function fromEarlier(value: unknown): Readonly<Record<string, FromEarlier>> | null {
  if (value === null || value === undefined) return null;
  const out: Record<string, FromEarlier> = {};
  for (const [key, source] of Object.entries(record(value, 'from earlier'))) {
    const row = record(source, 'from earlier source');
    if (typeof row['step'] !== 'number' || typeof row['field'] !== 'string') throw new TypeError('Invalid plan: from earlier source');
    out[key] = Object.freeze({ step: row['step'], field: row['field'] });
  }
  return Object.freeze(out);
}

function parseStep(value: unknown): PlanStep {
  const row = record(value, 'step');
  const action = record(row['action'], 'step action');
  const bind: Record<string, string | null> = {};
  for (const [key, bound] of Object.entries(row['bind'] === null || row['bind'] === undefined ? {} : record(row['bind'], 'bind'))) {
    bind[key] = typeof bound === 'string' ? bound : null;
  }
  const query: Record<string, string> = {};
  for (const [key, given] of Object.entries(row['query'] === null || row['query'] === undefined ? {} : record(row['query'], 'query'))) {
    if (typeof given === 'string') query[key] = given;
  }
  return Object.freeze({
    index: typeof row['index'] === 'number' ? row['index'] : 0,
    action: Object.freeze({ ...action, operation: text(action['operation'], 'step action operation') }),
    state: oneOf(row['state'], STEP_STATES, 'step state'),
    code: nullableText(row['code']),
    operation: text(row['operation'], 'step operation'),
    bind: Object.freeze(bind),
    bindFrom: fromEarlier(row['bind_from']),
    query: Object.freeze(query),
    body: row['body'] === null || row['body'] === undefined ? null : Object.freeze({ ...record(row['body'], 'step body') }),
    bodyFrom: fromEarlier(row['body_from']),
    permitted: row['permitted'] === true,
    spends: row['spends'] === true,
    confirmation: row['confirmation'] === 'chained' ? 'chained' : 'required',
    raw: Object.freeze({ ...row }),
  });
}

export function parseActionPlan(value: unknown): ActionPlan {
  const row = record(value, 'body');
  if (row['profile'] !== 'exulanica.companion-action-plan/v1') throw new TypeError('Invalid plan: profile');
  const refusal = row['refusal'] === null || row['refusal'] === undefined ? null : record(row['refusal'], 'refusal');
  const clarification = row['clarification'] === null || row['clarification'] === undefined
    ? null : record(row['clarification'], 'clarification');
  return Object.freeze({
    outcome: oneOf(row['outcome'], OUTCOMES, 'outcome'),
    kind: oneOf(row['kind'], KINDS, 'kind'),
    worldId: text(row['world_id'], 'world id'),
    versionId: text(row['version_id'], 'version id'),
    planSha256: text(row['plan_sha256'], 'plan digest'),
    atomic: row['atomic'] === true,
    steps: Object.freeze((Array.isArray(row['steps']) ? row['steps'] : []).map(parseStep)),
    spends: row['spends'] === true,
    spendsBy: Object.freeze(strings(row['spends_by'])),
    clarification: clarification === null ? null : Object.freeze({
      code: text(clarification['code'], 'clarification code'),
      step: typeof clarification['step'] === 'number' ? clarification['step'] : 0,
      slot: nullableText(clarification['slot']),
      candidates: Object.freeze((Array.isArray(clarification['candidates']) ? clarification['candidates'] : []).map((c) => {
        const candidate = record(c, 'candidate');
        return Object.freeze({
          value: text(candidate['value'], 'candidate value'),
          title: typeof candidate['title'] === 'string' ? candidate['title'] : '',
          selected: candidate['selected'] === true,
        });
      })),
      actions: Object.freeze((Array.isArray(clarification['actions']) ? clarification['actions'] : [])
        .map((a) => Object.freeze({ ...record(a, 'clarification action') }))),
    }),
    refusal: refusal === null ? null : Object.freeze({
      code: text(refusal['code'], 'refusal code'),
      detail: typeof refusal['detail'] === 'string' ? refusal['detail'] : '',
      step: typeof refusal['step'] === 'number' ? refusal['step'] : null,
      operation: nullableText(refusal['operation']),
      alternatives: Object.freeze(strings(refusal['alternatives'])),
    }),
    capabilities: Array.isArray(row['capabilities'])
      ? Object.freeze(row['capabilities'].map((c) => Object.freeze({ ...record(c, 'capability') })))
      : null,
    proposalSpeech: nullableText(row['proposal_speech']),
    raw: Object.freeze({ ...row }),
  });
}

export function parseActionOutcome(value: unknown): ActionOutcome {
  const row = record(value, 'outcome body');
  if (row['profile'] !== 'exulanica.companion-action-outcome/v1') throw new TypeError('Invalid outcome: profile');
  return Object.freeze({
    state: oneOf(row['state'], ['applied', 'partial', 'not_applied', 'superseded', 'pending'] as const, 'outcome state'),
    steps: Object.freeze((Array.isArray(row['steps']) ? row['steps'] : []).map((s) => {
      const step = record(s, 'outcome step');
      return Object.freeze({
        index: typeof step['index'] === 'number' ? step['index'] : null,
        operation: nullableText(step['operation']),
        state: oneOf(step['state'], ['applied', 'not_applied', 'superseded', 'pending'] as const, 'outcome step state'),
        code: nullableText(step['code']),
      });
    })),
    alternatives: Object.freeze(strings(row['alternatives'])),
  });
}

/** What the page shows the person, as `ActionBase` takes it. Snake case is the wire's. */
export interface ActionPageContext {
  readonly versionId: string;
  readonly baseStateSha256: string;
  readonly originRole: 'fictional' | 'personal' | null;
  readonly context: Readonly<Record<string, unknown>>;
  readonly savedEntry: Readonly<Record<string, unknown>> | null;
}

const base = (page: ActionPageContext): Record<string, unknown> => ({
  version_id: page.versionId,
  base_state_sha256: page.baseStateSha256,
  origin_role: page.originRole,
  context: page.context,
  saved_entry: page.savedEntry,
});

export interface CompanionActionsClientOptions extends TransportOptions {
  readonly worldId: string;
}

export class CompanionActionsClient {
  readonly #transport: Transport;
  readonly #worldId: string;

  constructor(options: CompanionActionsClientOptions) {
    this.#transport = new Transport(options);
    this.#worldId = options.worldId;
  }

  #path(path: string): string {
    return openWorldPath(path, this.#worldId, 'a Companion plan');
  }

  /** One utterance read as a plan, or declined; asks the classifier and changes nothing. */
  async plan(page: ActionPageContext, utterance: string): Promise<ActionPlan> {
    return parseActionPlan(await this.#transport.postJson<unknown>(this.#path('/selection/actions'), { ...base(page), utterance }));
  }

  /** Typed actions prepared with no model: a clarification answered, or a later edit step. */
  async prepare(page: ActionPageContext, actions: readonly Readonly<Record<string, unknown>>[]): Promise<ActionPlan> {
    return parseActionPlan(await this.#transport.postJson<unknown>(this.#path('/selection/actions/prepare'), { ...base(page), actions }));
  }

  /** What the authorities recorded for the plan's steps; a client's own answer, no proof. */
  async outcome(plan: ActionPlan): Promise<ActionOutcome> {
    return parseActionOutcome(await this.#transport.postJson<unknown>(this.#path('/selection/actions/outcome'), {
      version_id: plan.versionId,
      plan_sha256: plan.planSha256,
      steps: plan.steps.map((step) => step.raw),
    }));
  }

  /** Send one planned request the registry built (`ui/actions/planned.ts`). */
  async send(request: { readonly method: string; readonly path: string; readonly body: unknown }): Promise<unknown> {
    if (request.method === 'PUT') return this.#transport.putJson<unknown>(request.path, request.body);
    if (request.method === 'POST') return this.#transport.postJson<unknown>(request.path, request.body);
    throw new TypeError(`A planned step may not use ${request.method}`);
  }
}
