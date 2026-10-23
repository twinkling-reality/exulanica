// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { parseActionPlan, type ActionPlan, type BudgetSheet } from '../src/companion-actions-api.js';
import { PLAN_ACTIONS, plannedEntry, plannedRequest, stepAnswer } from '../src/ui/actions/planned.js';
import { actionSpec, availability, refusalWords } from '../src/ui/actions/registry.js';
import { buildPlanSheet, plannedStepView, stepDetail } from '../src/ui/companion-plan.js';
import {
  PLAN_CLARIFY_WORDS, budgetQuestionWords, budgetSheetWords, erasesWords, mindChoiceWords,
} from '../src/ui/words/companion-plan.js';

/*
 * A world's budget for its AI minds, and a living town taking its newcomers in, through a
 * Companion plan: each one step, sent as the registry's own action, with what it comes to said
 * before the one Confirm. The plans here are the planner's own documents as the route's view
 * serves them (tests/test_companion_budget_plan.py writes them and holds them current): a town of
 * five where one model decides for two, asked for 50 cents an hour, where an answer costs at most
 * $0.0031 and half a dollar pays for 161 answers at that price and 1,765 at the typical one.
 */

const repository = `${process.cwd()}/..`;
const read = (path: string): string => readFileSync(`${repository}/${path}`, 'utf8');
const plan = (name: string): ActionPlan =>
  parseActionPlan(JSON.parse(read(`web/packages/app/test/companion-plans/${name}.json`)));
const BUDGET = 'POST /world/versions/{version_id}/models/{role_key}/budget';
const TAKE_IN = 'POST /world/versions/{version_id}/society/take-in';
const sheetOf = (name: string): BudgetSheet => plan(name).steps[0]!.budget!;
const shown = (name: string, utterance: string): HTMLElement => {
  const document = plan(name);
  const sheet = buildPlanSheet({
    onConfirm: () => undefined, onCancel: () => undefined, onChoose: () => undefined, onPlay: () => undefined,
  });
  sheet.showPlan(document, document.steps.map((step) => plannedStepView(step, (spec) => spec.label, () => null, () => null)), utterance);
  return sheet.root;
};

describe('a budget for the world’s minds, as a planned step', () => {
  it('is the registry’s own action, sent to the budget route with the plan’s body', () => {
    const [step] = plan('budget-plan').steps;
    expect(PLAN_ACTIONS['set_minds_budget']).toBe('minds.budget');
    const entry = plannedEntry(step!);
    expect('spec' in entry && entry.spec.id).toBe('minds.budget');
    expect(actionSpec('minds.budget').operation).toBe(BUDGET);
    expect(read('exulanica/selection/action_budget.py')).toContain(`BUDGET: Final = "${BUDGET}"`);
    expect(actionSpec('minds.budget').placement).toEqual(['companion']);
    const built = plannedRequest(step!, []);
    if ('refused' in built) throw new Error(JSON.stringify(built.refused));
    expect(built.request.method).toBe('POST');
    expect(built.request.path).toBe('/world/versions/00000000-0000-0000-0000-000000000007/models/society_decision/budget');
    // With the budget the plan was made against, so one set since refuses it.
    expect(Object.keys(built.request.body).sort()).toEqual(['after_budget_seq', 'decisions_per_hour', 'idempotency_key', 'usd_per_hour']);
    const kept = JSON.parse(read('web/packages/app/test/companion-plans/budget-plan.json')) as { steps: { budget: { now: { budget_seq: number | null } } }[] };
    expect(built.request.body['after_budget_seq']).toBe(kept.steps[0]!.budget.now.budget_seq ?? 0);
    expect(built.request.body['usd_per_hour']).toBe('0.500000');
    expect(built.request.body['decisions_per_hour']).toBe(600);
  });

  it('is offered whatever the version’s capability read lists, and is never marked as spending', () => {
    // The budget is the world's: no version's capability read states its route.
    const found = availability(actionSpec('minds.budget'), null);
    expect(found.state).toBe('available');
    expect(found.spends).toBe(false);
    expect(plan('budget-plan').spends).toBe(false);
  });

  it('answers the outcome read with the budget its request recorded', () => {
    const body = { profile: 'exulanica.world-minds-budget-read/v1', budget: { budget_seq: 3, usd_per_hour: '0.500000' } };
    expect(stepAnswer(BUDGET, { status: 200, body })).toEqual({ status: 200, code: null, budget_seq: 3 });
    expect(stepAnswer(BUDGET, { status: 409, code: 'budget_key_reused' })).toEqual({ status: 409, code: 'budget_key_reused' });
  });

  it('has words for every code the budget route and the planner can answer the step with', () => {
    const server = [...read('exulanica/world/minds_budget.py').matchAll(/^ {4}"(budget_[a-z_]+)": /gm)].map((m) => m[1]!);
    expect(server.sort()).toEqual(['budget_changed', 'budget_decisions_not_a_figure', 'budget_key_reused', 'budget_usd_not_a_figure']);
    // A budget set by somebody between the plan and its yes: said as that, with nothing changed.
    expect(refusalWords(actionSpec('minds.budget'), 'budget_changed').happened).toContain('Somebody set this world’s budget after you were shown this plan');
    expect(refusalWords(actionSpec('minds.budget'), 'budget_changed').next).toContain('Nothing was changed');
    expect(read('exulanica/api/routes/world_models.py')).toContain('"budget_not_for_this_role"');
    for (const code of [...server, 'budget_not_for_this_role', 'no_change']) {
      expect(actionSpec('minds.budget').refusals?.[code]?.happened, code).toBeTruthy();
    }
    // A caller without the right is told whose the setting is to change, not a general refusal.
    expect(refusalWords(actionSpec('minds.budget'), 'action_not_permitted').happened)
      .toContain('can only be set by someone allowed');
  });

  it('names its two figures on its row', () => {
    expect(stepDetail(plan('budget-plan').steps[0]!)).toBe('$0.50 and 600 decisions an hour');
  });
});

describe('what the sheet says of a budget before the yes', () => {
  it('reads the server’s figures and adds none of its own', () => {
    const sheet = sheetOf('budget-plan');
    expect(sheet.now).toEqual({ usdPerHour: '0.250000', decisionsPerHour: 600, setByAPerson: false, setByYou: false });
    expect(sheet.asked).toEqual({ usdPerHour: '0.500000', decisionsPerHour: 600 });
    expect(sheet.named).toEqual(['usd_per_hour']);
    expect(sheet.answersForUsd).toEqual({ atMostPrice: 161, atTypicalPrice: 1765 });
    expect(sheet.binds).toEqual({ atMostPrice: 'usd', atTypicalPrice: 'decisions' });
    expect([sheet.beings, sheet.minded]).toEqual([5, 2]);
    expect(sheet.demand).toEqual({
      minded: { beings: 2, asksPerRealHour: 233, minutesCovered: 60 },
      everyone: { beings: 5, asksPerRealHour: 582, minutesCovered: 60 },
      estimate: true,
    });
  });

  it('says the budget now and after, both ceilings and which runs out first, both ways', () => {
    expect(budgetSheetWords(sheetOf('budget-plan'))).toEqual([
      'Now: $0.25 and 600 decisions in any hour of real time (what every world starts with).',
      'After: $0.50 and 600 decisions. You named the money; the decisions stay as they are.',
      'With Nano deciding here: at the typical price of an answer the 600 decisions run out first. '
      + 'If answers cost the most they can, the $0.50 runs out first, after about 161 answers. '
      + 'The server sets aside the most before each ask, so both are true.',
      'This world has 5 beings; an AI model decides for 2. They make about 233 asks an hour at this speed (an estimate), which this budget covers. '
      + 'With that model for all 5: about 582 asks an hour at this speed (an estimate), which this budget covers. '
      + 'When a budget is used up, everyone follows their own routine until the hour moves on.',
      'In the last hour this world asked AI models 12 times, for $0.0034.',
      'This server’s own limits still apply above any budget.',
      'Setting a budget asks no AI and spends nothing. It is this world’s, for everyone in it, until someone allowed to change it sets another.',
    ]);
  });

  it('says whose the budget is, truly, for the one who set it and for a visitor', () => {
    const sheet = sheetOf('budget-plan');
    const mine = budgetSheetWords({ ...sheet, now: { ...sheet.now, setByAPerson: true, setByYou: true } });
    expect(mine[0]).toContain('(you set this)');
    const theirs = budgetSheetWords({ ...sheet, now: { ...sheet.now, setByAPerson: true, setByYou: false } });
    expect(theirs[0]).toContain('(someone with the right to change this world set this)');
  });

  it('says how long a short budget lasts, by the server’s own minutes', () => {
    const sheet = sheetOf('budget-plan');
    const words = budgetSheetWords({
      ...sheet,
      demand: {
        minded: { beings: 2, asksPerRealHour: 233, minutesCovered: 60 },
        everyone: { beings: 128, asksPerRealHour: 14890, minutesCovered: 2 }, estimate: false,
      },
    });
    expect(words[3]).toContain('With that model for all 128: about 14,890 asks an hour at this speed, so this budget is used up after about 2 minutes of each hour.');
    expect(words[3]).not.toContain('estimate');
  });

  it('says one ceiling where both prices agree, and no typical price where none is measured', () => {
    const sheet = sheetOf('budget-plan');
    expect(budgetSheetWords({ ...sheet, binds: { atMostPrice: 'decisions', atTypicalPrice: 'decisions' } })[2])
      .toBe('With Nano deciding here: the 600 decisions run out before the $0.50 does, even if every answer costs the most it can.');
    expect(budgetSheetWords({ ...sheet, binds: { atMostPrice: 'usd', atTypicalPrice: 'usd' } })[2])
      .toBe('With Nano deciding here: the $0.50 runs out before the 600 decisions do: after about 1,765 answers at the typical price, 161 if every answer costs the most it can.');
    const unmeasured = budgetSheetWords({
      ...sheet, answersForUsd: { atMostPrice: 161, atTypicalPrice: null }, binds: { atMostPrice: 'usd', atTypicalPrice: null }, demand: null,
    });
    expect(unmeasured[2]).toBe('With Nano deciding here: if every answer costs the most it can, $0.50 pays for about 161 answers, so the money would run out first. No typical price is measured for this model here yet.');
    expect(unmeasured[3]).toBe('This world has 5 beings; an AI model decides for 2.');
  });

  it('never sets one model’s figures beside another’s', () => {
    const sheet = sheetOf('budget-plan');
    const several = budgetSheetWords({
      ...sheet, models: [...sheet.models, { name: 'Ultra', beings: 1, typical: true, free: false }],
    }).join(' ');
    expect(several).toContain('Several AI models decide here; by the dearest of them:');
    expect(several).not.toContain('Nano');
    expect(several).not.toContain('Ultra');
  });

  it('says only the decisions run out where every model here answers for nothing, even with no money', () => {
    // The server's own sheet for a model whose answer costs at most nothing (a model on this computer).
    const json = read('web/packages/app/test/companion-plans/budget-plan.json')
      .replace('"usd_per_answer_at_most": "0.00310000"', '"usd_per_answer_at_most": "0.00000000"');
    const parsed = parseActionPlan(JSON.parse(json)).steps[0]!.budget!;
    expect(parsed.models.map((model) => model.free)).toEqual([true]);
    expect(sheetOf('budget-plan').models.map((model) => model.free)).toEqual([false]);
    const free: BudgetSheet = {
      ...parsed, models: [{ ...parsed.models[0]!, name: 'Qwen3 4B Instruct', typical: false }], demand: null,
      answersForUsd: { atMostPrice: null, atTypicalPrice: null }, binds: { atMostPrice: 'decisions', atTypicalPrice: 'decisions' },
    };
    const line = 'With Qwen3 4B Instruct deciding here: its answers cost nothing, so the money never runs out; only the 600 decisions can.';
    expect(budgetSheetWords(free)[2]).toBe(line);
    expect(budgetSheetWords({ ...free, models: [...free.models, { name: 'Mini', beings: 1, typical: false, free: true }] })[2])
      .toBe('The AI models deciding here cost nothing to answer, so the money never runs out; only the 600 decisions can.');
    // No money and decisions above none: they are still asked, and a used-up hour is still said.
    const noMoney = budgetSheetWords({
      ...free, asked: { usdPerHour: '0.000000', decisionsPerHour: 600 }, refusedNow: 'world_hour_decisions_spent',
    });
    expect(noMoney[2]).toBe(line);
    expect(noMoney.join(' ')).toContain('Even under this budget no AI model is asked right now: the last hour’s decisions already reach it.');
    expect(noMoney.join(' ')).not.toContain('With nothing to spend');
    // No decisions: nobody is asked, whatever an answer costs.
    expect(budgetSheetWords({ ...free, asked: { usdPerHour: '0.500000', decisionsPerHour: 0 } })[2])
      .toBe('With nothing to spend, no AI model is asked: everyone follows their own routine. The models you chose are kept.');
    // Beside a priced model, the dearest decides, as before.
    const sheet = sheetOf('budget-plan');
    const mixed: BudgetSheet = { ...sheet, models: [...sheet.models, { name: 'Mini', beings: 1, typical: false, free: true }] };
    expect(budgetSheetWords(mixed)[2]).toContain('Several AI models decide here; by the dearest of them:');
    // With no money only the free ones are asked: the dearest's refusal of the hour and its rates are not said.
    const mixedNoMoney = budgetSheetWords({
      ...mixed, asked: { usdPerHour: '0.000000', decisionsPerHour: 600 }, refusedNow: 'world_hour_spend_spent',
      answersForUsd: { atMostPrice: 0, atTypicalPrice: 0 },
    });
    expect(mixedNoMoney[2]).toBe('With no money to spend, only the AI models that cost nothing are asked; people with a priced model follow their own routine. The models you chose are kept.');
    expect(mixedNoMoney[3]).toBe('This world has 5 beings; an AI model decides for 2.');
    expect(mixedNoMoney.join(' ')).not.toContain('Even under this budget');
    // No decisions: nobody is asked, free or priced.
    expect(budgetSheetWords({ ...mixed, asked: { usdPerHour: '0.000000', decisionsPerHour: 0 } })[2])
      .toBe('With nothing to spend, no AI model is asked: everyone follows their own routine. The models you chose are kept.');
  });

  it('says a budget of nothing asks nobody, and that nothing is asked where no model is chosen', () => {
    const sheet = sheetOf('budget-plan');
    const nothing = budgetSheetWords({
      ...sheet, asked: { usdPerHour: '0.000000', decisionsPerHour: 0 }, refusedNow: 'world_hour_decisions_spent',
      answersForUsd: { atMostPrice: 0, atTypicalPrice: 0 },
    });
    expect(nothing[1]).toBe('After: $0.00 and 0 decisions. You named the money; the decisions stay as they are.');
    expect(nothing[2]).toBe('With nothing to spend, no AI model is asked: everyone follows their own routine. The models you chose are kept.');
    // Said once: a budget of nothing is not also "used up for now".
    // Nor is it said to be used up after 0 minutes: the head count is said and no more.
    expect(nothing[3]).toBe('This world has 5 beings; an AI model decides for 2.');
    expect(nothing.join(' ')).not.toContain('minutes of each hour');
    expect(nothing.join(' ')).not.toContain('Even under this budget');
    const nobody = budgetSheetWords({
      ...sheet, models: [], minded: 0, demand: null, answersForUsd: { atMostPrice: null, atTypicalPrice: null },
      binds: { atMostPrice: null, atTypicalPrice: null },
    });
    expect(nobody[2]).toContain('No being here has an AI model yet');
    expect(nobody[3]).toBe('This world has 5 beings; an AI model decides for none of them.');
    // A model is chosen here but cannot be priced now: never said as nobody having one.
    const unpriced = budgetSheetWords({
      ...sheet, models: [], demand: null, answersForUsd: { atMostPrice: null, atTypicalPrice: null },
      binds: { atMostPrice: null, atTypicalPrice: null },
    });
    expect(unpriced[2]).toBe('This server cannot price an answer of the AI model chosen here right now, so which of the two runs out first cannot be said.');
    expect(unpriced.join(' ')).not.toContain('No being here has an AI model yet');
    expect(unpriced[3]).toBe('This world has 5 beings; an AI model decides for 2.');
  });

  it('says so when the last hour already reaches the budget, and when the server or an allowance stops it first', () => {
    const sheet = sheetOf('budget-plan');
    expect(budgetSheetWords({ ...sheet, refusedNow: 'world_hour_decisions_spent' }).join(' '))
      .toContain('Even under this budget no AI model is asked right now: the last hour’s decisions already reach it.');
    expect(budgetSheetWords({ ...sheet, hostRefusal: 'models_not_run_here' }).join(' '))
      .toContain('This server does not ask AI models in this world right now, whatever the budget.');
    expect(budgetSheetWords({ ...sheet, allowanceLeftUsd: '0.120000', allowanceBelowBudget: true }).join(' '))
      .toContain('Your allowance on this server has $0.12 left in all, which stops the asking before this budget does.');
  });

  it('draws those lines on the sheet under the steps, before Confirm', () => {
    const root = shown('budget-plan', 'let this town spend up to 50 cents an hour on minds');
    const lines = [...root.querySelectorAll('.companion-plan-estimate[data-kind="budget"]')].map((line) => line.textContent);
    expect(lines).toEqual(budgetSheetWords(sheetOf('budget-plan')));
    expect(root.querySelector('.companion-plan-spends')?.getAttribute('data-spends')).toBe('false');
    expect(root.querySelector('.companion-plan-step-detail')?.textContent).toBe('$0.50 and 600 decisions an hour');
    expect(root.querySelector<HTMLButtonElement>('[data-action="plan.confirm"]')?.disabled).toBe(false);
  });

  it('asks for a figure against the budget the world has now, and never converts a span', () => {
    const question = plan('budget-question');
    expect(question.clarification?.code).toBe('budget_required');
    expect(budgetQuestionWords('budget_required', question.clarification!.facts)).toBe(
      'How much may this world spend on AI minds in an hour? Say an amount, such as 50 cents an hour, or a number of decisions an hour. '
      + 'Now it is $0.25 and 600 decisions an hour.',
    );
    expect(budgetQuestionWords('budget_period', {})).toBe(PLAN_CLARIFY_WORDS['budget_period']);
    expect(PLAN_CLARIFY_WORDS['budget_period']).toContain('I will not work an hour’s figure out of another span');
    const vocabulary = read('exulanica/selection/action_vocabulary.py');
    for (const code of ['budget_required', 'budget_ambiguous', 'budget_period']) {
      expect(vocabulary).toContain(`"${code}"`);
      expect(PLAN_CLARIFY_WORDS[code], code).toBeTruthy();
    }
  });

  it('tells a mind chosen while the world’s hour is used up that nobody is asked for now', () => {
    const [step] = plan('mind-plan').steps;
    const words = mindChoiceWords(step!.mind!, { ...step!.cost!, refusedNow: 'world_hour_decisions_spent' }, false);
    expect(words).toBe(
      'This is for 2 beings (1 left out because someone is playing them). '
      + 'This world’s budget of AI decisions for the hour is used up, so no AI model is asked until the hour moves on or the budget is raised. '
      + 'Until then they keep their own routine. The choice is kept.',
    );
    const typical = mindChoiceWords(step!.mind!, { ...step!.cost!, usdTypical: '0.00014500', typicalIsEstimate: true }, false);
    expect(typical).toContain('Typically about $0.0001 a minute of this world, an estimate from a measurement that was cut short.');
  });
});

describe('a living town taking its newcomers in, as a planned step', () => {
  it('is the registry’s own action, sent to the take-in route with no body of its own', () => {
    const [step] = plan('take-in-plan').steps;
    expect(PLAN_ACTIONS['take_in']).toBe('people.take-in');
    expect(actionSpec('people.take-in').operation).toBe(TAKE_IN);
    expect(read('exulanica/selection/action_vocabulary.py')).toContain('TAKE_IN: Final = f"POST {_VERSION}/society/take-in"');
    const built = plannedRequest(step!, []);
    if ('refused' in built) throw new Error(JSON.stringify(built.refused));
    expect(built.request.path).toBe('/world/versions/00000000-0000-0000-0000-000000000007/society/take-in');
    expect(built.request.body).toEqual({});
    expect(stepAnswer(TAKE_IN, { status: 201, body: { society_id: 's', profile: 'exulanica-society/v7' } }))
      .toEqual({ status: 201, code: null, society_id: 's' });
  });

  it('has words for every loss and every thing kept that the planner states', () => {
    const [step] = plan('take-in-plan').steps;
    const vocabulary = read('exulanica/selection/action_vocabulary.py');
    const codes = (name: string): string[] => [...vocabulary.slice(vocabulary.indexOf(`${name}: Final = (`)).split(')')[0]!.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]!);
    expect(step!.erases).toEqual({ undo: false, loses: codes('TAKE_IN_LOSES'), keeps: codes('TAKE_IN_KEEPS') });
    expect(step!.erases!.loses.length).toBe(7);
    expect(erasesWords(step!.erases!, 12)).toEqual([
      'The people of this town take the newcomers in and live with them from now on. They stay who they are. Their day so far is 12 minutes long.',
      'Not kept: what everybody has done so far; where the clock stands (their day starts again); whether the town was playing, and how fast; '
      + 'the AI models chosen for people; the looks saved for residents; comparisons and experiments run with these people; the Companion’s answers about them.',
      'Kept: the same people, with their homes, jobs, roles and shifts; the world; everything placed in it; door grants and programs; the world’s look.',
      'This cannot be undone.',
    ]);
  });

  it('never understates a loss it has no words for, and claims a way back only where the server states one', () => {
    const words = erasesWords({ undo: false, loses: ['day_so_far', 'something_new'], keeps: [] }, null);
    expect(words[1]).toBe('Not kept: what everybody has done so far; and more that this page cannot name.');
    expect(words.at(-1)).toBe('This cannot be undone.');
    // A step that states no loss says none, and never an empty list.
    expect(erasesWords({ undo: false, loses: [], keeps: ['world'] }, null).join(' ')).not.toContain('Not kept');
    expect(parseActionPlan({ ...JSON.parse(read('web/packages/app/test/companion-plans/take-in-plan.json')) }).steps[0]!.erases!.undo).toBe(false);
  });

  it('draws the loss on the sheet before Confirm', () => {
    const root = shown('take-in-plan', 'let the townspeople take the knight in');
    const lines = [...root.querySelectorAll('.companion-plan-estimate[data-kind="erases"]')].map((line) => line.textContent);
    expect(lines).toEqual(erasesWords(plan('take-in-plan').steps[0]!.erases!, 12));
  });

  it('has words for every code the route can answer, each saying nothing was erased where nothing was', () => {
    const own = [...read('exulanica/api/society_making.py').matchAll(/^ {4}"(society_unavailable|society_takes_in_already|nothing_to_take_in|restore_sealed)": /gm)].map((m) => m[1]!);
    expect(own.length).toBe(4);
    const making = ['society_engine_not_offered', 'society_engine_differs', 'unavailable_society_input', 'no_reachable_targets',
      'engine_not_for_this_ground', 'society_engine_retired', 'society_lives_elsewhere', 'population_not_recorded',
      'population_over_tick_budget', 'world_holds_no_residents', 'invalid_society_state'];
    for (const code of [...own, ...making]) {
      expect(actionSpec('people.take-in').refusals?.[code]?.happened, code).toBeTruthy();
    }
    for (const code of making) {
      expect(actionSpec('people.take-in').refusals?.[code]?.next, code).toContain('Nothing was erased');
    }
    // A code with no words of its own still says nothing was changed.
    expect(refusalWords(actionSpec('people.take-in'), 'a_waiting_code').next).toContain('Nothing was changed');
  });
});
