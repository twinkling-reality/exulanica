// How a making the world-count policy refused is said: the bound that refused, and when room
// returns as a person reads a clock, in their own time, never as a count of tiles.
import { ApiError } from '@exulanica/graph-client';
import { describe, expect, it } from 'vitest';
import { problemSentence } from '../src/ui/words/problems.js';
import { whenWords, worldBudgetWords } from '../src/ui/words/world-budgets.js';

// Local times, as the viewer's clock shows them, whatever zone the test runs in.
const local = (day: number, hour: number, minute: number): Date => new Date(2026, 9, day, hour, minute);

describe('when room returns', () => {
  it('is said as today, tomorrow or the date, with the hour and minute in the viewer\'s time', () => {
    const now = local(10, 11, 30);
    expect(whenWords(local(10, 23, 5), now)).toBe('today at 23:05');
    expect(whenWords(local(11, 9, 14), now)).toBe('tomorrow at 09:14');
    expect(whenWords(local(11, 0, 0), now)).toBe('tomorrow at 00:00');
    expect(whenWords(local(12, 9, 14), now)).toBe('on 12 October at 09:14');
    // An instant already past is still said as today: room is there now.
    expect(whenWords(local(10, 9, 0), now)).toBe('today at 09:00');
  });
});

describe('a making the count policy refused', () => {
  const refused = (code: string, extensions: Record<string, unknown> = {}): ApiError => (
    new ApiError(409, code, 'the server\'s own words, with a count of tiles in them', extensions));
  const now = local(10, 11, 30);

  it('names the day\'s budget and says when another town can be made, with no tile count', () => {
    const error = refused('tile_budget_reached', { returns_at: local(11, 9, 14).toISOString() });
    const said = problemSentence(error, worldBudgetWords(error, now));
    expect(said).toBe('This workspace has made as many towns as it may in one day. You can make another town tomorrow at 09:14.');
    expect(said).not.toMatch(/tile/i);
  });

  it('says within a day where the answer gave no instant it can read', () => {
    for (const extensions of [{}, { returns_at: 'soon' }, { returns_at: 7 }]) {
      const error = refused('tile_budget_reached', extensions);
      expect(problemSentence(error, worldBudgetWords(error, now)))
        .toBe('This workspace has made as many towns as it may in one day. You can make another town within a day.');
    }
  });

  it('names the worlds held and what to do instead', () => {
    const error = refused('world_limit_reached');
    expect(problemSentence(error, worldBudgetWords(error, now)))
      .toBe('This workspace already holds as many towns as it may at once. Open one of the towns you already have instead.');
  });

  it('leaves every other refusal to the words it already has', () => {
    const error = refused('busy');
    expect(problemSentence(error, worldBudgetWords(error, now))).toBe('The world was busy for a moment, so nothing was changed. Try again.');
  });
});
