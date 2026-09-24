import { describe, expect, it } from 'vitest';
import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';
import { EVENT_WINDOW, unreadMinutes } from '../src/composition/society-unread-minutes.js';
import type { SocietyEvent } from '../src/society-api.js';

const state = (tick: number, people: Record<string, readonly [number, number]>): OwnedSocietyState => ({
  profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'version', tick,
  movement_budget_mm_per_tick: 60_000,
  inhabitants: Object.entries(people).map(([id, at]) => ({ id, synthetic: true, position_mm: at, motion_path_mm: [at] })),
});
const event = (subject: string, tick: number, order: number, path: readonly (readonly [number, number])[]): SocietyEvent => ({
  event_id: `${subject}-${tick}-${order}`, subject_id: subject, tick, event_kind: 'route_progressed',
  document_sha256: 'e'.repeat(64), document: { synthetic: true, summary: 's', order, motion_path_mm: path },
});

describe('minutes a page never read', () => {
  it('rebuilds each from the last event a person has in it, and keeps still anyone with none', () => {
    const shown = state(4, { walker: [0, 0], sitter: [9000, 0] });
    const next = state(7, { walker: [3000, 0], sitter: [9000, 0] });
    const minutes = unreadMinutes(shown, next, [
      // The goal is chosen before the step, so the first event of the minute holds only its start.
      event('walker', 5, 0, [[0, 0]]),
      event('walker', 5, 1, [[0, 0], [1000, 0]]),
      event('walker', 6, 0, [[1000, 0], [2000, 0]]),
      event('walker', 7, 0, [[2000, 0], [3000, 0]]),
    ]);
    expect(minutes.map((minute) => minute.tick)).toEqual([5, 6]);
    expect(minutes.map((minute) => minute.inhabitants.map((person) => [person.id, person.motion_path_mm, person.position_mm]))).toEqual([
      [['walker', [[0, 0], [1000, 0]], [1000, 0]], ['sitter', [[9000, 0]], [9000, 0]]],
      [['walker', [[1000, 0], [2000, 0]], [2000, 0]], ['sitter', [[9000, 0]], [9000, 0]]],
    ]);
    // Everything else about the minute is the latest state's: its budget and identity.
    expect(minutes[0]!.movement_budget_mm_per_tick).toBe(60_000);
  });

  it('rebuilds nothing when nothing was missed', () => {
    expect(unreadMinutes(state(4, { a: [0, 0] }), state(5, { a: [0, 0] }), [])).toEqual([]);
  });

  it('rebuilds nothing when a full window may have cut an unread minute short', () => {
    const full = Array.from({ length: EVENT_WINDOW }, (_, i) => event(`p${i}`, 6 + Math.floor(i / 128), 0, [[0, 0]]));
    expect(unreadMinutes(state(5, { a: [0, 0] }), state(8, { a: [0, 0] }), full)).toEqual([]);
    // A full window whose oldest minute is before the unread ones holds every event they have.
    const earlier = full.map((held) => ({ ...held, tick: held.tick - 2 }));
    expect(unreadMinutes(state(5, { a: [0, 0] }), state(8, { a: [0, 0] }), earlier)).toHaveLength(2);
  });
});
