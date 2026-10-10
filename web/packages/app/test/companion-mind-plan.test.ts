// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { parseActionPlan, type ActionPlan } from '../src/companion-actions-api.js';
import { PLAN_ACTIONS, plannedEntry, plannedRequest, stepAnswer } from '../src/ui/actions/planned.js';
import { actionSpec } from '../src/ui/actions/registry.js';
import { buildPlanSheet, plannedStepView, stepDetail } from '../src/ui/companion-plan.js';
import {
  MIND_GREW, PLAN_CLARIFY_WORDS, atMostDollarsWords, midRunQuestionWords, mindChoiceWords, mindDetailWords,
  tooManyForModelsWords,
} from '../src/ui/words/companion-plan.js';

/*
 * A mind chosen through a Companion plan: one step, sent as the registry's own action to the models
 * route, with whom it is for, who is left out and what it may cost said before the one Confirm.
 * The plans here are the planner's own documents as the route's view serves them, written by the
 * scripted planner (tests/test_companion_minds_plan.py's world): three villagers, one of them
 * played and so left out, a knight and a lantern spirit; an answer costs at most $0.0031.
 */

const repository = `${process.cwd()}/..`;
const fixture = (name: string): unknown =>
  JSON.parse(readFileSync(`${repository}/web/packages/app/test/companion-plans/${name}.json`, 'utf8'));
const plan = (name: string): ActionPlan => parseActionPlan(fixture(name));
const MIND = 'POST /world/versions/{version_id}/models/{role_key}';
const planner = readFileSync(`${repository}/exulanica/selection/action_plan.py`, 'utf8');

describe('a mind chosen, as a planned step', () => {
  it('is the registry’s own action, sent to the models route with the plan’s body', () => {
    const [step] = plan('mind-plan').steps;
    expect(PLAN_ACTIONS['choose_mind']).toBe('minds.choose');
    const entry = plannedEntry(step!);
    expect('spec' in entry && entry.spec.id).toBe('minds.choose');
    expect(actionSpec('minds.choose').operation).toBe(MIND);
    expect(actionSpec('minds.choose').placement).toEqual(['companion']);
    const built = plannedRequest(step!, []);
    if ('refused' in built) throw new Error(JSON.stringify(built.refused));
    expect(built.request.method).toBe('POST');
    expect(built.request.path).toBe('/world/versions/00000000-0000-0000-0000-000000000007/models/society_decision');
    expect(Object.keys(built.request.body).sort()).toEqual(['idempotency_key', 'model', 'subjects']);
    expect(built.request.body['model']).toEqual({ provider: 'nebius_token_factory', model_id: 'example/nano' });
    expect((built.request.body['subjects'] as string[]).length).toBe(2);
  });

  it('answers the outcome read with the choice its request recorded', () => {
    expect(stepAnswer(MIND, { status: 200, body: { choice_seq: 5, document_sha256: 'f'.repeat(64) } }))
      .toEqual({ status: 200, code: null, choice_seq: 5 });
    expect(stepAnswer(MIND, { status: 409, code: 'being_played' })).toEqual({ status: 409, code: 'being_played' });
  });

  it('has words for every code the planner can block the step with', () => {
    const own = [...readFileSync(`${repository}/exulanica/selection/action_minds.py`, 'utf8')
      .matchAll(/"(group_not_here|mind_not_offered|too_many_subjects_for_one_choice)"/g)].map((m) => m[1]!);
    const routes = ['too_many_model_people', 'being_played', 'decided_from_outside', 'decider_not_allowed',
      'person_not_in_this_world', 'subject_chosen_under_another_role', 'engine_takes_no_model_choice',
      'model_not_declared', 'model_not_offered', 'model_not_askable', 'society_unavailable'];
    expect(new Set(own).size).toBe(3);
    for (const code of [...own, ...routes]) {
      expect(actionSpec('minds.choose').refusals?.[code]?.happened, code).toBeTruthy();
    }
  });

  it('has a question for every clarification a mind choice can ask', () => {
    for (const code of ['whom_required', 'whom_ambiguous', 'mind_required', 'mind_ambiguous', 'too_many_people_for_models']) {
      expect(planner).toContain(`"${code}"`);
      expect(PLAN_CLARIFY_WORDS[code], code).toBeTruthy();
    }
  });
});

describe('what the sheet says of a mind before the yes', () => {
  it('names the mind and whom it decides for on the row', () => {
    const [step] = plan('mind-plan').steps;
    expect(stepDetail(step!)).toBe('Nano decides for every villager');
    expect(mindDetailWords('every knight', 'their own routine', true)).toBe('Every knight: their own routine');
    const [routine] = plan('mind-routine-plan').steps;
    expect(stepDetail(routine!)).toBe('Every knight: their own routine');
    expect(plannedStepView(step!, (spec) => spec.label, () => null, () => null).label).toBe('Choose who decides');
  });

  it('says how many, who was left out and why, the most it may cost and the world’s ceilings', () => {
    const [step] = plan('mind-plan').steps;
    expect(step!.mind).toMatchObject({ subjects: 2, leftOut: { being_played: 1 }, runNow: 0, runAfter: 2, bound: 8 });
    expect(step!.mind!.groupsHere.map((group) => [group.value, group.count])).toEqual([
      ['everyone', 5], ['kind:villager', 3], ['kind:knight', 1], ['kind:lantern_spirit', 1],
    ]);
    expect(step!.cost).toEqual({
      subjects: 2, usdPerAnswerAtMost: '0.003100', usdAtMost: '0.006200', usdTypical: null,
      usdPerWorldHour: '0.250000', decisionsPerWorldHour: 600,
    });
    expect(mindChoiceWords(step!.mind!, step!.cost, false)).toBe(
      'This is for 2 beings (1 left out because someone is playing them). Choosing asks no model. '
      + 'While the world plays, at most $0.0062 a simulated minute (at most $0.0031 each time a being is asked, at most once a minute). '
      + 'No typical figure is measured for this world yet. '
      + 'This world stops asking models at $0.25 or 600 decisions in any hour of real time, whatever is chosen.',
    );
  });

  it('never says the world’s ceiling below itself', () => {
    const [step] = plan('mind-plan').steps;
    expect(mindChoiceWords(step!.mind!, { ...step!.cost!, usdPerWorldHour: '0.254000' }, false))
      .toContain('stops asking models at $0.26 or 600 decisions');
  });

  it('says their own routine asks no AI and spends nothing', () => {
    const [step] = plan('mind-routine-plan').steps;
    expect(step!.cost).toBeNull();
    expect(step!.spends).toBe(false);
    expect(mindChoiceWords(step!.mind!, null, true)).toBe('This is for 1 being. No AI is asked and nothing is spent.');
  });

  it('says so when this server asks no model here, and states no cost it would not meet', () => {
    const [step] = plan('mind-plan').steps;
    const words = mindChoiceWords({ ...step!.mind!, hostRefusal: 'models_not_run_here' }, step!.cost, false);
    expect(words).toContain('This server does not ask this model here now');
    expect(words).not.toContain('$');
  });

  it('draws that line on the sheet under the steps, before Confirm', () => {
    const shown = plan('mind-plan');
    const sheet = buildPlanSheet({
      onConfirm: () => undefined, onCancel: () => undefined, onChoose: () => undefined, onPlay: () => undefined,
    });
    sheet.showPlan(shown, shown.steps.map((step) => plannedStepView(step, (spec) => spec.label, () => null, () => null)), 'give every villager Nano');
    const line = sheet.root.querySelector('.companion-plan-estimate[data-kind="mind"]');
    expect(line?.textContent).toContain('at most $0.0062 a simulated minute');
    expect(sheet.root.querySelector('.companion-plan-spends')?.getAttribute('data-spends')).toBe('true');
    expect(sheet.root.querySelector('.companion-plan-step-detail')?.textContent).toBe('Nano decides for every villager');
  });
});

describe('a bound in dollars', () => {
  it('is never said below itself: rounded up at the precision shown', () => {
    expect(atMostDollarsWords('0.014900')).toBe('$0.02');
    expect(atMostDollarsWords('0.250000')).toBe('$0.25');
    expect(atMostDollarsWords('0.250001')).toBe('$0.26');
    expect(atMostDollarsWords('1.000000')).toBe('$1.00');
    expect(atMostDollarsWords('0.003100')).toBe('$0.0031');
    expect(atMostDollarsWords('0.003101')).toBe('$0.0032');
    expect(atMostDollarsWords('0.000001')).toBe('$0.0001');
    expect(atMostDollarsWords('0')).toBe('$0.00');
    for (const usd of ['0.014900', '0.003101', '0.000001', '0.099999', '0.010000']) {
      expect(Number(atMostDollarsWords(usd).slice(1)), usd).toBeGreaterThanOrEqual(Number(usd));
    }
  });
});

describe('two minds chosen in one sentence', () => {
  it('shows each step’s count, who is left out and cost under the steps, before the one Confirm', () => {
    const shown = plan('mind-two-steps-plan');
    expect(shown.steps.map((step) => [step.state, step.mind?.subjects ?? null])).toEqual([['prepared', 1], ['pending', 2]]);
    expect(shown.steps[1]!.cost).toMatchObject({ subjects: 2, usdAtMost: '0.006200' });
    expect(shown.steps[1]!.mind!.leftOut).toEqual({ being_played: 1 });
    const sheet = buildPlanSheet({
      onConfirm: () => undefined, onCancel: () => undefined, onChoose: () => undefined, onPlay: () => undefined,
    });
    sheet.showPlan(shown, shown.steps.map((step) => plannedStepView(step, (spec) => spec.label, () => null, () => null)), 'both');
    const lines = [...sheet.root.querySelectorAll('.companion-plan-estimate[data-kind="mind"]')].map((line) => line.textContent ?? '');
    expect(lines.length).toBe(2);
    expect(lines[0]).toContain('This is for 1 being.');
    expect(lines[1]).toContain('This is for 2 beings (1 left out because someone is playing them).');
    expect(lines[1]).toContain('at most $0.0062 a simulated minute');
  });

  it('has words for a later step that grew and for a question in the middle of a plan', () => {
    expect(MIND_GREW.happened).toContain('more beings than you were shown');
    expect(midRunQuestionWords('too_many_people_for_models', { asked: 9, bound: 8, run_now: 1 }).happened).toBe(
      'This step needs an answer first: You asked for 9, and AI models decide for at most 8 beings here at once, and 1 has one already. Who instead?',
    );
    expect(midRunQuestionWords('mind_required', {}).happened).toContain(PLAN_CLARIFY_WORDS['mind_required']);
  });
});

describe('a choice past the world’s bound', () => {
  it('is asked about with its figures and the groups that fit, never trimmed', () => {
    const asked = plan('mind-too-many');
    expect(asked.outcome).toBe('clarify');
    expect(asked.clarification).toMatchObject({ code: 'too_many_people_for_models', slot: 'whom' });
    expect(asked.clarification!.facts).toEqual({ asked: 3, bound: 8, run_now: 7 });
    expect(asked.clarification!.candidates.map((candidate) => candidate.title)).toEqual([
      'every knight (1)', 'every lantern spirit (1)',
    ]);
    expect(tooManyForModelsWords(asked.clarification!.facts)).toBe(
      'You asked for 3, and AI models decide for at most 8 beings here at once, and 7 have one already. Who instead?',
    );
    expect(tooManyForModelsWords({})).toBe(PLAN_CLARIFY_WORDS['too_many_people_for_models']);
    const sheet = buildPlanSheet({
      onConfirm: () => undefined, onCancel: () => undefined, onChoose: () => undefined, onPlay: () => undefined,
    });
    sheet.showClarification(asked, 'give every villager Nano', (_value, title) => title);
    expect(sheet.root.querySelector('.companion-plan-intro')?.textContent).toContain('at most 8 beings here at once');
    expect([...sheet.root.querySelectorAll('[data-action="plan.choose"]')].map((button) => button.textContent))
      .toEqual(['every knight (1)', 'every lantern spirit (1)']);
  });
});

describe('a plan made before a mind could be chosen', () => {
  it('reads as it always did: no mind, no cost, no figures on a question', () => {
    for (const name of ['thing-plan', 'world-edit-plan', 'simulation-plan', 'play-plan', 'bring-people-plan']) {
      for (const step of plan(name).steps) {
        expect(step.mind, name).toBeNull();
        expect(step.cost, name).toBeNull();
      }
    }
  });
});
