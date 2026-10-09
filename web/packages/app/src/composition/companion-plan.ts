/**
 * The Companion's world actions, from a sentence to what happened.
 *
 * **Which sentences.** With a world open, every sentence the Companion is asked to read goes to
 * `POST /selection/actions` first, in the place `POST /selection/appearance` held. The browser does
 * not decide what a sentence asks for (`companion-runtime`'s parse knows names, relations and
 * whether words ask, nothing about world actions); the server's classifier does, in one call,
 * choosing among a question, an appearance change, a world edit, simulated time and "what can I do
 * here" (`classify_action` in `exulanica/selection/action_plan.py`, where any classifier failure is
 * a question). So:
 *
 * - a question goes on to `/selection/ask`, as before;
 * - an appearance change is the proposal the plan's first step carries, read by the same function
 *   as `/selection/appearance`'s answer (`proposalFromWire`) and reviewed in Design as before,
 *   with no second drafting call; the plan's two style steps are never sent from here;
 * - a world edit or simulated time is a plan on the sheet, sent step by step through the action
 *   registry once confirmed (`ui/actions/planned.ts`);
 * - "what can I do here" is said from the registry's words.
 *
 * Where the route cannot answer (no model, unreachable, past the wait), or no world is open, the
 * sentence takes the path it took before this module existed.
 */

import type { CompanionProposal, WireProposal } from '../companion-ask-api.js';
import { callsOf, proposalFromWire, type ModelCall } from '../companion-ask-api.js';
import type {
  ActionPageContext,
  ActionPlan,
  CompanionActionsClient,
  PlanClarification,
  PlanStep,
  StepAnswer,
} from '../companion-actions-api.js';
import { availability, actionSpec, refusalWords, type RefusalWords } from '../ui/actions/registry.js';
import { PLAN_ACTIONS, plannedEntry, plannedRequest, stepAnswer } from '../ui/actions/planned.js';
import { performPlanned, type ActionHost } from '../ui/actions/surfaces.js';
import { plannedStepView, thePlace, type PlanSheet, type PlanStepView } from '../ui/companion-plan.js';
import { OBJECT_ROLE_LABELS, isObjectRole } from '../world-objects-api.js';
import { PLAN_WAITED, PLAN_WORDS, planRefusalWords } from '../ui/words/companion-plan.js';

/**
 * The codes a step asking one of the world's beings is prepared with while it must wait for the
 * world's next minute (`WAIT_CODES` in exulanica/selection/action_things.py): an input the world
 * has not taken in, the being in the middle of something, or the place it is asked to go full this
 * minute (its places free up as visits end).
 */
export const WAIT_CODES: ReadonlySet<string> = new Set(['society_input_queued', 'inhabitant_action_in_progress', 'destination_full']);
/** How often such a step is prepared again while it waits, and for how long at most. */
export const WAIT_POLL_MS = 2_000;
export const WAIT_LIMIT_MS = 90_000;

/**
 * What a step waiting to be sent says it waits for: a free place where it asked to go, else the
 * world's next minute; while the world is paused, how to move it on, whatever it waits for.
 */
function waitingWords(waiting: PlanStep, paused: boolean): string {
  if (paused) return PLAN_WORDS.pausedMinute;
  const place = waiting.titles['place'];
  return waiting.code === 'destination_full' && place !== undefined
    ? PLAN_WORDS.freePlace.replace('{place}', thePlace(place)) : PLAN_WORDS.nextMinute;
}

/** Where a sentence goes after the plan route has read it. */
export type PlanRouting =
  /** The route could not answer, or no world is open: the path the sentence took before. */
  | { readonly route: 'fallback' }
  | { readonly route: 'question' }
  /** An appearance proposal, read as `/selection/appearance`'s would be. */
  | { readonly route: 'appearance'; readonly proposal: CompanionProposal }
  /** Something to say: a plan shown, a question asked, a refusal, what can be done here. */
  | {
    readonly route: 'answer';
    readonly sentences: readonly string[];
    readonly refused: boolean;
    /** The model calls the plan made, so the answer says who answered or that no model did. */
    readonly calls: readonly ModelCall[];
    readonly promptVersion: string;
  };

export interface CompanionPlansDeps {
  /** The client for the open world, or null with none open. */
  readonly client: () => CompanionActionsClient | null;
  /** What the page shows the person now, read fresh for each request. */
  readonly page: () => ActionPageContext | null;
  /** The registry's host, whose `send` sends a planned request and shows its write. */
  readonly host: () => ActionHost | null;
  readonly sheet: PlanSheet;
  /** After a simulation chain's last step: the People panel and clock read again. */
  readonly afterTime: () => Promise<void>;
  /** An object or arrangement a step names, in words, or null. */
  readonly particular: (step: PlanStep) => string | null;
  /** How long a plan may take: the appearance route's own wait, since it drafts the same way. */
  readonly waitMs: number;
  /**
   * How a step asking one of the world's beings waits for the world's next minute before it is
   * prepared again: a pause of `ms`. Left out, the page's own timer.
   */
  readonly pause?: (ms: number) => Promise<void>;
  /** Whether the world's clock is paused now, so a waiting step says how to move it on. */
  readonly paused?: () => boolean;
  /**
   * What the Companion says once a question it asked about a plan is answered on the sheet: the
   * plan now shown, or why there is none. Without it the Companion would still be asking.
   */
  readonly onSaid?: (utterance: string, said: Extract<PlanRouting, { readonly route: 'answer' }>) => void;
}

export interface CompanionPlans {
  route(utterance: string): Promise<PlanRouting>;
  /** The sheet's buttons, wired by the composition root to the sheet it built. */
  confirm(): void;
  cancel(): void;
  choose(clarification: PlanClarification, value: string): void;
}

/**
 * An appearance plan as `/selection/appearance`'s body, so one function reads both and a proposal
 * from either route is handed to Design with the same fields. Null where the plan is not one the
 * appearance route could have given: no first step proposing a change, or a basis other than the
 * evidence the browser always asks from.
 */
export function appearanceWireFromPlan(plan: ActionPlan): WireProposal | null {
  const execution = plan.raw['execution'] as WireProposal['execution'];
  const names = plan.raw['names'] as Readonly<Record<string, string>> | undefined;
  if (plan.outcome === 'refused' && plan.refusal !== null) {
    return { classification: 'appearance', proposal: null, refusal: { code: plan.refusal.code, detail: plan.refusal.detail }, execution, ...(names === undefined ? {} : { names }) };
  }
  const first = plan.steps[0];
  if (plan.outcome !== 'plan' || first === undefined || first.action.operation !== 'propose_appearance') return null;
  const body = first.body ?? {};
  if ((body['appearance_basis'] ?? 'evidence') !== 'evidence') return null;
  const profile = body['profile'] as { profile_id: string; profile_version: number; parameters: Record<string, unknown> } | undefined;
  const drawn = (first.raw['preview'] as { document?: { changed?: string[]; modules?: string[] } } | null)?.document ?? {};
  if (profile === undefined || typeof body['model_id'] !== 'string' || typeof body['prompt_version'] !== 'string') return null;
  return {
    classification: 'appearance',
    proposal: {
      profile: {
        profile_id: profile.profile_id,
        profile_version: profile.profile_version,
        parameters: profile.parameters,
        modules: drawn.modules ?? [],
        changed: drawn.changed ?? [],
      },
      reference_ids: (body['reference_ids'] as string[] | undefined) ?? [],
      model_id: body['model_id'],
      prompt_version: body['prompt_version'],
      spoken: plan.proposalSpeech ?? '',
      base_style_version_id: String(body['base_style_version_id']),
      base_topology_digest: String(body['base_topology_digest']),
    },
    refusal: null,
    execution,
    ...(names === undefined ? {} : { names }),
  };
}

/** A plan refusal in words: the action's own where the refused operation is a registry entry. */
function refusedWords(plan: ActionPlan): RefusalWords {
  const refusal = plan.refusal;
  if (refusal === null) return planRefusalWords('not_drafted');
  // A step its route's preview refused names why in its own code (the well is full this minute):
  // said in that action's words where it has them, else the plan's.
  const own = refusal.code === 'preview_blocked'
    ? plan.steps.find((step) => step.index === refusal.step)?.code ?? null : null;
  if (refusal.operation !== null) {
    const id = Object.values(PLAN_ACTIONS).find((candidate) => candidate !== null && actionSpec(candidate).operation === refusal.operation);
    if (id !== undefined && id !== null) {
      for (const code of [own, refusal.code]) {
        if (code !== null && actionSpec(id).refusals?.[code] !== undefined) return refusalWords(actionSpec(id), code);
      }
    }
  }
  return planRefusalWords(refusal.code);
}

/** "What can I do here", from the registry's words and the plan's capability listing. */
function capabilitySentences(plan: ActionPlan): string[] {
  const now: string[] = [];
  const notNow: string[] = [];
  for (const entry of plan.capabilities ?? []) {
    const action = typeof entry['action'] === 'string' ? entry['action'] : '';
    const id = action === 'change_appearance' ? 'design.open' : PLAN_ACTIONS[action];
    if (id === undefined || id === null) continue;
    const label = action === 'change_appearance' ? 'Change how the world looks' : actionSpec(id).label;
    if (entry['offered'] === false) continue;
    if (entry['state'] === 'available' && entry['permitted'] !== false) now.push(label);
    else notNow.push(label);
  }
  return [
    now.length === 0 ? 'I cannot change anything in this world right now.' : `Here I can: ${now.join(', ')}.`,
    ...(notNow.length === 0 ? [] : [`Not right now: ${notNow.join(', ')}.`]),
  ];
}

export function mountCompanionPlans(deps: CompanionPlansDeps): CompanionPlans {
  let shown: { readonly plan: ActionPlan; readonly utterance: string; readonly page: ActionPageContext } | null = null;
  let running = false;
  const pause = deps.pause ?? ((ms: number) => new Promise<void>((resolve) => { setTimeout(resolve, ms); }));

  const held = (actionId: string): PlanStepView['held'] => {
    const found = availability(actionSpec(actionId), deps.host()?.capabilities() ?? null);
    return found.state === 'available' ? null : { state: found.state, words: found.words ?? planRefusalWords('action_unavailable') };
  };

  function stepView(step: PlanStep): PlanStepView {
    const view = plannedStepView(step, (spec) => spec.label, held, deps.particular);
    if (view.held !== null) return view;
    if (step.state === 'blocked') {
      // The step's own words where its entry has them (a thing step's checks are the route's).
      const entry = plannedEntry(step);
      const own = 'spec' in entry && step.code !== null ? entry.spec.refusals?.[step.code] : undefined;
      return { ...view, held: { state: 'unavailable', words: own ?? planRefusalWords('preview_blocked') } };
    }
    if (step.state === 'not_permitted') return { ...view, held: { state: 'not-permitted', words: planRefusalWords('action_not_permitted') } };
    return view;
  }

  /** Show a plan, or a refusal or question, and say so. */
  function present(plan: ActionPlan, utterance: string, page: ActionPageContext): PlanRouting {
    const execution = plan.raw['execution'] as { calls?: Parameters<typeof callsOf>[0]; prompt_version?: string } | undefined;
    const said = (sentences: readonly string[], refused: boolean): PlanRouting => ({
      route: 'answer', sentences, refused, calls: callsOf(execution?.calls), promptVersion: execution?.prompt_version ?? '',
    });
    if (plan.outcome === 'capabilities') return said(capabilitySentences(plan), false);
    if (plan.outcome === 'refused') {
      const words = refusedWords(plan);
      return said([words.happened, words.next], true);
    }
    if (plan.outcome === 'clarify' && plan.clarification !== null) {
      shown = { plan, utterance, page };
      deps.sheet.showClarification(plan, utterance, (value, title) =>
        title.length > 0 ? title : isObjectRole(value) ? OBJECT_ROLE_LABELS[value] : value);
      return said([deps.sheet.root.querySelector('.companion-plan-intro')?.textContent ?? ''], false);
    }
    if (plan.outcome === 'plan' && plan.steps.length > 0) {
      shown = { plan, utterance, page };
      deps.sheet.showPlan(plan, plan.steps.map(stepView), utterance);
      return said([PLAN_WORDS.spoken], false);
    }
    return said([PLAN_REFUSED_SENTENCE.happened, PLAN_REFUSED_SENTENCE.next], true);
  }

  async function run(plan: ActionPlan, page: ActionPageContext): Promise<void> {
    const host = deps.host();
    const client = deps.client();
    if (host === null || client === null) return;
    running = true;
    const earlier: unknown[] = [];
    // Each sent step's own answer, by step index, for the outcome read (`stepAnswer`).
    const answers: Record<number, StepAnswer> = {};
    let done = 0;
    let stopped = false;
    for (const step of plan.steps) deps.sheet.setStep(step.index, { kind: 'waiting' });
    for (const step of plan.steps) {
      if (stopped) { deps.sheet.setStep(step.index, { kind: 'not-reached' }); continue; }
      deps.sheet.setStep(step.index, { kind: 'running' });
      let sending: PlanStep | null = step;
      // A later world edit is prepared against the state the one before it left, and a step asking
      // one of the world's beings always just before it is sent: the world moves on every minute.
      const asking = step.action.operation === 'direct_thing';
      if ((plan.kind === 'world_edit' && step.index > 0) || asking) {
        try {
          let again = await client.prepare(deps.page() ?? page, [step.action]);
          let waited = 0;
          // While it must wait for the world's next minute, it is prepared again now and then.
          while (asking && again.outcome === 'plan' && again.steps[0]?.state === 'pending'
            && WAIT_CODES.has(again.steps[0].code ?? '') && waited < WAIT_LIMIT_MS) {
            deps.sheet.setStep(step.index, {
              kind: 'waiting', when: waitingWords(again.steps[0], deps.paused?.() === true),
            });
            await pause(WAIT_POLL_MS);
            waited += WAIT_POLL_MS;
            again = await client.prepare(deps.page() ?? page, [step.action]);
          }
          sending = again.outcome === 'plan' ? again.steps[0] ?? null : null;
          if (sending !== null && sending.state === 'pending') {
            deps.sheet.setStep(step.index, { kind: 'not-done', words: PLAN_WAITED, code: sending.code });
            stopped = true;
            continue;
          }
          if (sending === null) {
            deps.sheet.setStep(step.index, { kind: 'not-done', words: refusedWords(again), code: again.refusal?.code ?? null });
            stopped = true;
            continue;
          }
          deps.sheet.setStep(step.index, { kind: 'running' });
        } catch {
          deps.sheet.setStep(step.index, { kind: 'not-done', words: planRefusalWords('stale_version'), code: null });
          stopped = true;
          continue;
        }
      }
      if (sending.state === 'blocked' || sending.state === 'not_permitted') {
        const view = stepView(sending);
        deps.sheet.setStep(step.index, { kind: 'not-done', words: view.held?.words ?? planRefusalWords('preview_blocked'), code: sending.code });
        stopped = true;
        continue;
      }
      const built = plannedRequest(sending, earlier);
      if ('refused' in built) {
        deps.sheet.setStep(step.index, {
          kind: 'not-done', code: built.refused.kind,
          words: { happened: PLAN_WORDS.notSentRoute, next: PLAN_WORDS.none },
        });
        stopped = true;
        continue;
      }
      const result = await performPlanned(host, { ...built.request, stepIndex: step.index });
      const operation = actionSpec(built.request.actionId).operation ?? '';
      if (result.kind === 'ran') {
        answers[step.index] = stepAnswer(operation, { status: result.status, body: result.response });
      } else if (result.kind === 'refused' && result.status !== null) {
        answers[step.index] = stepAnswer(operation, { status: result.status, code: result.code });
      }
      if (result.kind === 'ran') {
        earlier[step.index] = result.response;
        done += 1;
        deps.sheet.setStep(step.index, { kind: 'done' });
      } else {
        deps.sheet.setStep(step.index, { kind: 'not-done', words: result.words, code: result.code });
        stopped = true;
      }
    }
    if (plan.kind === 'simulation' && done > 0) await deps.afterTime().catch(() => undefined);
    let offerPlay = false;
    if (done > 0) {
      try {
        offerPlay = (await client.outcome(plan, answers)).alternatives.includes('play');
      } catch {
        // What was recorded could not be read back; each step's own answer is already shown.
      }
    }
    deps.sheet.finish(done, plan.steps.length, offerPlay);
    running = false;
  }

  return {
    async route(utterance) {
      const client = deps.client();
      const page = deps.page();
      if (client === null || page === null) return { route: 'fallback' };
      let plan: ActionPlan;
      try {
        plan = await Promise.race([
          client.plan(page, utterance),
          new Promise<never>((_, reject) => setTimeout(() => reject(new Error('plan wait')), deps.waitMs)),
        ]);
      } catch {
        return { route: 'fallback' };
      }
      if (plan.outcome === 'question') return { route: 'question' };
      if (plan.kind === 'appearance') {
        const wire = appearanceWireFromPlan(plan);
        return wire === null ? { route: 'fallback' } : { route: 'appearance', proposal: proposalFromWire(utterance, wire) };
      }
      return present(plan, utterance, page);
    },
    confirm() {
      if (shown === null || running || shown.plan.outcome !== 'plan') return;
      void run(shown.plan, shown.page);
    },
    cancel() {
      if (running) return;
      shown = null;
      deps.sheet.close();
    },
    choose(clarification, value) {
      const asked = shown;
      const client = deps.client();
      if (asked === null || client === null || running) return;
      const page = deps.page() ?? asked.page;
      const actions = clarification.actions.map((action, index) =>
        index === clarification.step && clarification.slot !== null ? { ...action, [clarification.slot]: value } : action);
      const answered = clarification.code === 'origin_role_required' && isObjectRole(value)
        ? { ...page, originRole: value } : page;
      void client.prepare(answered, actions).then(
        (next) => {
          const said = present(next, asked.utterance, answered);
          if (said.route !== 'answer') return;
          if (said.refused) deps.sheet.say(refusedWords(next));
          // The answer is to the person's sentence, which a model read before the question was
          // asked; preparing the answer asks none. Both are said under it.
          const first = asked.plan.raw['execution'] as { calls?: Parameters<typeof callsOf>[0] } | undefined;
          deps.onSaid?.(asked.utterance, { ...said, calls: [...callsOf(first?.calls), ...said.calls] });
        },
        () => deps.sheet.say(planRefusalWords('stale_version')),
      );
    },
  };
}

const PLAN_REFUSED_SENTENCE = planRefusalWords('not_drafted');
