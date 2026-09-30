// The start form says, before Start, how many of a town's people a model may decide for in one
// comparison, and, for a chosen model deciding for more people than one minute's asks can have
// answered, that the rest of a busy minute follow their routine. Both figures are the server's.
import { describe, expect, it } from 'vitest';
import { parsePlan, type ComparisonPlan, type PlanFigures } from '../src/society-comparison-api.js';
import { decidedWords, finishingWords, minuteWords, START_REFUSAL_WORDS } from '../src/ui/society-comparison-start.js';

function plan(population: number, decidedMost: number): ComparisonPlan {
  return parsePlan({
    profile: 'exulanica.society-comparison-plan/v1',
    refusal: null,
    running: null,
    roles: [],
    seeds_available: 8,
    models_most: 2,
    window_ticks: 60,
    population,
    population_most: 110,
    decided_most: decidedMost,
    people: [],
    typical_record: 'docs/evaluation/2026-09-26-society-group-comparison.json',
    plan: null,
    plan_refusal: null,
  });
}

function figures(
  minutes: readonly Record<string, unknown>[],
  suggested: string | null = '0.0277',
  matches = true,
): PlanFigures {
  return parsePlan({
    profile: 'exulanica.society-comparison-plan/v1', refusal: null, running: null, roles: [],
    seeds_available: 8, models_most: 2, window_ticks: 60, population: 58, population_most: 110,
    decided_most: 40, people: [], typical_record: 'record', plan_refusal: null,
    plan: {
      runs: 5, asks_most: 100, calls_most: 200, most_usd: '1.0', typical_usd: '0.02',
      typical_record: 'record', minutes, held_usd: '0.0158', suggested_usd: suggested,
      typical_matches: matches,
    },
  }).plan!;
}

describe('the bounds a town\'s comparison states before Start', () => {
  it('says how many people a model may decide for only where that is fewer than everybody', () => {
    expect(decidedWords(plan(58, 40))).toBe(
      'A model can decide for at most 40 of this world\'s 58 people in one comparison, so that each of its hours can be replayed and shown within seconds.',
    );
    expect(decidedWords(plan(8, 8))).toBeNull();
  });

  it('says a busy minute leaves the rest to their routine, once per model, only where it does', () => {
    const minutes = [
      { arm: 'model_a', model_id: 'm/one', name: 'Model One', decided: 50, answers_per_minute: 32 },
      { arm: 'model_a_again', model_id: 'm/one', name: 'Model One', decided: 50, answers_per_minute: 32 },
      { arm: 'model_b', model_id: 'm/two', name: 'Model Two', decided: 50, answers_per_minute: 136 },
      { arm: 'model_c', model_id: 'm/three', name: 'Model Three', decided: 50, answers_per_minute: null },
    ];
    expect(minuteWords(figures(minutes))).toBe(
      'Model One can answer about 32 of the 50 people it decides for in one minute; in a minute when more of them have a choice, the rest follow their routine.',
    );
    expect(minuteWords(figures(minutes.slice(2)))).toBe('');
  });

  it('has words for the refusal a comparison beyond the bound meets', () => {
    expect(START_REFUSAL_WORDS['decided_over_comparison_bound']).toContain('Choose a smaller group');
  });

  it('suggests the least bound that lets it finish, as the server derived it', () => {
    expect(finishingWords(figures([]))).toBe(
      ' At least $0.0277 lets it finish, since each ask is held at its most until its cost is known.',
    );
    expect(finishingWords(figures([], null))).toBe('');
  });

  it('never promises a finish where the typical figure was measured on another kind of ground', () => {
    const words = finishingWords(figures([], '0.0277', false));
    expect(words).toContain('based on recorded comparisons on other grounds');
    expect(words).toContain('may stop it before it finishes');
    expect(words).not.toContain('lets it finish');
  });
});
