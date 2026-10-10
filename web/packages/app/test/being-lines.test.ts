// The lines a being of a society of things said and heard. Shapes are the society's own
// (docs/synthetic-society-contract.md, the society of things: a `said` event's thing holds the
// line, whom it was said to or null for everyone near, their kinds and numbers, who heard it and
// the decider kind, model or external; a being states `heard` as {tick, from, from_kind,
// from_number, to, line}); only a decider says a line, never a routine.
import { describe, expect, it } from 'vitest';
import { heardBy, LINES_SHOWN, saidBy, type LineNames } from '../src/composition/being-lines.js';
import type { SocietyEvent } from '../src/society-api.js';
import type { MarkInput } from '../src/composition/thing-marks.js';

const KNIGHT = { kind: 'knight', version: 2, sha256: 'a'.repeat(64) };
const TRAVELLER = { kind: 'traveller', version: 1, sha256: 'b'.repeat(64) };
const VISITOR_NOW: MarkInput = { running: null, crossing: { bridge: 'blockgame' }, bridge: { label: 'Block Game', ai: false }, declared: null };

const people = [
  { id: 'knight-0', display_name: 'Knight', kind: KNIGHT, came_by: 'placed' },
  { id: 'traveller-0', display_name: 'Traveller', kind: TRAVELLER, came_by: 'placed' },
  { id: 'visitor-0', display_name: 'Visitor', kind: TRAVELLER, came_by: 'crossed', crossing: { arrival_id: 'a', bridge: 'blockgame', grant_id: 'g' } },
] as never[];

const names: LineNames = {
  person: (id) => (people as { id: string; display_name: string }[]).find((one) => one.id === id)?.display_name ?? null,
  kindLabel: (kind) => ({ knight: 'knight', traveller: 'traveller' } as Record<string, string>)[kind.kind ?? ''] ?? null,
  speaker: (id) => (id === 'visitor-0' ? VISITOR_NOW : id === 'gone-0' ? null : { running: null }),
};

let order = 0;
const said = (speaker: string, tick: number, line: string, to: string | null, decider: 'model' | 'external', extra: Record<string, unknown> = {}): SocietyEvent => {
  order += 1;
  return {
    event_id: `said-${order}`, subject_id: speaker, tick, event_kind: 'said', document_sha256: 'e'.repeat(64),
    document: {
      synthetic: true, summary: 'said', reason: 'chose_to_say', order,
      thing: { line, to, to_kind: to === null ? null : TRAVELLER, to_number: to === null ? null : 2, from_kind: KNIGHT, from_number: 1, heard_by: [], decider, ...extra },
    },
  } as SocietyEvent;
};

describe('the lines a being said', () => {
  it('are its own said events, newest first, at most a few, each to whom and decided by whom', () => {
    const events = [
      said('knight-0', 3, 'Welcome, traveller.', 'traveller-0', 'model'),
      said('traveller-0', 4, 'Thank you.', 'knight-0', 'model'),
      said('knight-0', 5, 'Take this sword.', 'traveller-0', 'model', { model: { provider: 'nebius', model_id: 'Qwen/Qwen3-235B-A22B-Instruct-2507' } }),
      said('knight-0', 6, 'Safe roads.', null, 'model'),
      said('knight-0', 7, 'Rest by the well.', null, 'model'),
    ];
    const lines = saidBy('knight-0', events, names);
    expect(lines).toHaveLength(LINES_SHOWN);
    expect(lines.map((line) => [line.tick, line.line, line.to])).toEqual([
      [7, 'Rest by the well.', null], [6, 'Safe roads.', null], [5, 'Take this sword.', 'Traveller'],
    ]);
    // The model is named only where the event names it.
    expect([lines[2]!.decider, lines[2]!.model]).toEqual(['model', { provider: 'nebius', modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507' }]);
    expect([lines[0]!.decider, lines[0]!.model]).toEqual(['model', null]);
    expect(lines[0]!.speaker).toEqual({ running: null });
  });

  it('carry the speaker as it is now where its program said them, and name one who left by kind', () => {
    const lines = saidBy('visitor-0', [said('visitor-0', 4, 'Hello there.', 'gone-0', 'external')], names);
    expect([lines[0]!.decider, lines[0]!.speaker]).toEqual(['external', VISITOR_NOW]);
    expect(lines[0]!.to).toBe('Traveller');
  });
});

describe('the lines a being heard', () => {
  it('take who decided a heard line only from that same line\'s said event', () => {
    const listener = { id: 'traveller-0', display_name: 'Traveller', kind: TRAVELLER, came_by: 'placed',
      heard: [{ tick: 3, from: 'visitor-0', from_kind: TRAVELLER, from_number: 3, to: null, line: 'An older line.' }] } as never;
    // The window holds only a later, different line by the same speaker.
    const later = [said('visitor-0', 5, 'A later line.', null, 'external')];
    expect(heardBy(listener, later, names)[0]!.decider).toBeNull();
  });

  it('come from its state, newest first, decided only as the speaker\'s said event says', () => {
    const heard = [
      { tick: 3, from: 'knight-0', from_kind: KNIGHT, from_number: 1, to: 'traveller-0', line: 'Welcome, traveller.' },
      { tick: 4, from: 'visitor-0', from_kind: TRAVELLER, from_number: 3, to: null, line: 'Hello there.' },
      { tick: 4, from: 'traveller-0', from_kind: TRAVELLER, from_number: 2, to: null, line: 'Good day.', model: { provider: 'nebius', model_id: 'n' } },
      { tick: 5, from: 'gone-0', from_kind: KNIGHT, from_number: 4, to: 'traveller-0', line: 'Farewell.' },
    ];
    const listener = { id: 'traveller-0', display_name: 'Traveller', kind: TRAVELLER, came_by: 'placed', heard } as never;
    const events = [said('knight-0', 3, 'Welcome, traveller.', 'traveller-0', 'model', { model: { provider: 'nebius', model_id: 'm' } })];
    const lines = heardBy(listener, events, names);
    // Only a said event read says who decided a heard line; with none, nothing is claimed.
    expect(lines.map((line) => [line.speakerName, line.toId, line.decider])).toEqual([
      ['Knight', 'traveller-0', null],
      ['Traveller', null, null],
      ['Visitor', null, null],
    ]);
    // A heard line names its model where it carries one.
    expect(lines[1]!.model).toEqual({ provider: 'nebius', modelId: 'n' });
    // The knight's line, the oldest, falls past the few shown; alone, its said event decides it.
    expect(lines).toHaveLength(LINES_SHOWN);
    const one = heardBy({ ...(listener as object), heard: [heard[0]] } as never, events, names);
    expect([one[0]!.decider, one[0]!.model]).toEqual(['model', { provider: 'nebius', modelId: 'm' }]);
  });
});
