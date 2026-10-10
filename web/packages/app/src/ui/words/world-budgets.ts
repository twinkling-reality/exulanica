/**
 * How a making the world-count policy refused is said, in the person's own terms.
 *
 * The policy holds a workspace to two budgets (`exulanica/world/world-count-policy.v3.json`): the
 * generated worlds it may hold at once, and the tiles its towns may come to in a day. A making
 * past the first is `world_limit_reached`; past the second it is `tile_budget_reached`, whose
 * answer carries `returns_at`, the instant room returns. The page says that instant as a person
 * reads a clock, in their own time ("tomorrow at 09:14"), and never as a count of tiles.
 */

import { ApiError } from '@exulanica/graph-client';
import type { ProblemWords } from './problems.js';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
  'October', 'November', 'December'] as const;
const two = (value: number): string => String(value).padStart(2, '0');

/** `at` as a person says a time near now: today, tomorrow, or the date, in the viewer's own time. */
export function whenWords(at: Date, now: Date): string {
  const clock = `${two(at.getHours())}:${two(at.getMinutes())}`;
  const day = (date: Date): number => Date.UTC(date.getFullYear(), date.getMonth(), date.getDate());
  const days = Math.round((day(at) - day(now)) / 86_400_000);
  if (days <= 0) return `today at ${clock}`;
  if (days === 1) return `tomorrow at ${clock}`;
  return `on ${at.getDate()} ${MONTHS[at.getMonth()]} at ${clock}`;
}

/**
 * The words for each budget's refusal of this making, keyed by its code, for
 * `problemSentence(error, worldBudgetWords(error))`. The day's budget says when another town can
 * be made where the answer gave the instant, and that it is within a day where it did not.
 */
export function worldBudgetWords(error: unknown, now: Date = new Date()): Readonly<Record<string, ProblemWords>> {
  const stated = error instanceof ApiError ? error.extensions['returns_at'] : undefined;
  const at = typeof stated === 'string' ? new Date(stated) : null;
  const when = at === null || Number.isNaN(at.getTime()) ? 'within a day' : whenWords(at, now);
  return {
    world_limit_reached: {
      happened: 'This workspace already holds as many towns as it may at once.',
      next: 'Open one of the towns you already have instead.',
    },
    tile_budget_reached: {
      happened: 'This workspace has made as many towns as it may in one day.',
      next: `You can make another town ${when}.`,
    },
  };
}
