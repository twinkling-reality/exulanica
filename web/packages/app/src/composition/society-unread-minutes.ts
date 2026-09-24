/**
 * The minutes a page never read, rebuilt from the server's own event documents so the crowd can
 * walk them instead of jumping over them.
 *
 * A society read returns only the current state, whose `motion_path_mm` covers the last tick. The
 * v2 engine records a walker's path in every tick it moves: each event document carries the
 * `motion_path_mm` walked so far in that tick, and the last event a person has in a tick carries
 * the whole of it (`advance_purposeful_society` in `exulanica/world/society_planner.py` emits after
 * each step it takes). A person with no event in a tick did not move in it: resting, blocked
 * without a new reason, or waiting. Nothing here decides where anybody is; every point is one the
 * server recorded, and a minute the event window does not fully cover is not rebuilt at all, which
 * leaves the crowd to name the jump.
 */

import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';
import { SOCIETY_EVENT_WINDOW, type SocietyEvent } from '../society-api.js';

/** The events endpoint returns at most this many, newest first (`SOCIETY_EVENT_WINDOW`). */
export const EVENT_WINDOW = SOCIETY_EVENT_WINDOW;

type Point = readonly [number, number];

const point = (value: unknown): value is Point =>
  Array.isArray(value) && value.length === 2 && value.every(Number.isSafeInteger);

/**
 * One state per tick strictly between `shown` and `next`, oldest first, carrying only what the crowd
 * walks: each person's position and the path recorded for that tick. Empty when nothing is unread,
 * or when the event window cannot vouch for every unread tick.
 */
export function unreadMinutes(
  shown: OwnedSocietyState,
  next: OwnedSocietyState,
  events: readonly SocietyEvent[],
): readonly OwnedSocietyState[] {
  const first = shown.tick + 1;
  if (next.tick - first < 1) return [];
  // A full window may have cut its oldest tick short; only ticks after it are known whole.
  const oldest = events.reduce((least, event) => Math.min(least, event.tick), Number.POSITIVE_INFINITY);
  if (events.length >= EVENT_WINDOW && oldest >= first) return [];
  const last = new Map<string, { order: number; path: readonly Point[] }>();
  for (const event of events) {
    if (event.tick < first || event.tick >= next.tick) continue;
    const order = event.document['order'];
    const path = event.document['motion_path_mm'];
    if (typeof order !== 'number' || !Array.isArray(path) || path.length === 0 || !path.every(point)) continue;
    const key = `${event.tick}:${event.subject_id}`;
    const held = last.get(key);
    if (held === undefined || order > held.order) last.set(key, { order, path: path as readonly Point[] });
  }
  const minutes: OwnedSocietyState[] = [];
  let people = shown.inhabitants;
  for (let tick = first; tick < next.tick; tick += 1) {
    people = people.map((person) => {
      const recorded = last.get(`${tick}:${person.id}`);
      const path = recorded?.path ?? [person.position_mm];
      return { ...person, position_mm: path[path.length - 1]!, motion_path_mm: path };
    });
    minutes.push({ ...next, tick, inhabitants: people });
  }
  return minutes;
}
