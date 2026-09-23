// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import type { LiveSocietyView } from '../src/composition/live-society.js';
import { parseSociety, type SocietyPlaces } from '../src/society-api.js';
import {
  areaWords,
  buildWorldInhabitants,
  placeRows,
  refusalWords,
  type InhabitedObject,
} from '../src/ui/world-inhabitants.js';

const places = (overrides: Partial<SocietyPlaces> = {}): SocietyPlaces => ({
  inputSeq: 2, inputSha256: 'b'.repeat(64), available: true, unavailableReason: null,
  walkableArea: { source: 'declared', centreMm: [0, 0], halfWidthMm: 12000, halfDepthMm: 12000 },
  clearanceMm: 450,
  targets: [{ targetId: 't-near', subjectId: 's-near', objectId: 'near', affordance: 'rest', durationTicks: 3, enabled: true }],
  unreachable: [
    { targetId: 't-far', objectId: 'far', affordance: 'rest', reason: 'authored_affordance_unreachable' },
    { targetId: 't-edge', objectId: 'edge', affordance: 'visit', reason: 'authored_affordance_unreachable' },
  ],
  ...overrides,
});
const objects: readonly InhabitedObject[] = [
  { objectId: 'near', title: 'Marker plate', xMm: 3000, zMm: 5000 },
  { objectId: 'far', title: 'Marker plate', xMm: 0, zMm: 14000 },
  { objectId: 'edge', title: 'Marker pillar', xMm: 11400, zMm: 1000 },
  { objectId: 'new', title: 'Marker cube', xMm: 0, zMm: 2000 },
];

describe('where each object stands for inhabitants', () => {
  it('reads usable, unreachable and not-yet-noticed from the consumed input, never from the browser', () => {
    const rows = placeRows(objects, places());
    expect(rows.map((row) => [row.label, row.status.kind])).toEqual([
      ['Marker plate 1', 'usable'],
      ['Marker plate 2', 'unreachable'],
      ['Marker pillar', 'unreachable'],
      ['Marker cube', 'not-noticed'],
    ]);
    expect(rows[0]!.words).toBe('Inhabitants can rest here.');
    // Outside the square on the south axis: 14,000 mm against 12,000 less the 450 clearance.
    expect(rows[1]!.words).toBe('Inhabitants cannot get close enough to use this: it is outside the area they walk in.');
    // Inside the square yet unreachable: the server says so, and the words claim no more.
    expect(rows[2]!.words).toBe('Inhabitants cannot get close enough to use this.');
    expect(rows[3]!.words).toBe('Inhabitants notice this after the next simulated minute.');
  });

  it('says the area in the server\'s numbers, and says where the ground goes on', () => {
    expect(areaWords(places())).toBe(
      'They walk inside a square about 23 metres across around where you arrive. The ground goes on; they do not.',
    );
    expect(areaWords(places({
      walkableArea: { source: 'ground', centreMm: [0, 0], halfWidthMm: 6000, halfDepthMm: 9000 },
    }))).toBe("They walk on this world's ground, an area about 11 by 17 metres just inside its edge.");
    expect(areaWords(places({ walkableArea: null }))).toBeNull();
  });

  it('says a refusal in words and keeps the code for the details', () => {
    expect(refusalWords({ status: 422, code: 'invalid_society_state', detail: 'initial society requires reachable targets' }))
      .toMatch(/^Nobody came in: there is nowhere in this world they could reach yet/);
    expect(refusalWords({ status: 424, code: 'unavailable_society_input', detail: 'required exact asset bytes are unavailable' }))
      .toBe('Inhabitants cannot come in right now. required exact asset bytes are unavailable');
  });
});

describe('the inhabitants panel', () => {
  const view = (patch: Partial<LiveSocietyView>): LiveSocietyView => ({
    mode: 'authenticated', status: 'absent', busy: false, snapshot: null, events: [], eventsAvailable: false,
    message: 'Nobody lives in this world yet.', refusal: null, ...patch,
  });

  it('before anyone lives here: says so, says what they need, and offers only the request', () => {
    const onBringIn = vi.fn();
    const panel = buildWorldInhabitants({ onBringIn, onAdvance: vi.fn() });
    panel.render({ society: view({}), objects: [], walked: 0, advanceBlocked: null });
    expect(panel.root.dataset['state']).toBe('absent');
    expect(panel.root.querySelector('.world-inhabitants-summary')?.textContent).toBe('Nobody lives here yet.');
    expect(panel.root.textContent).toMatch(/simulated people/);
    expect(panel.root.textContent).toMatch(/never a memory/);
    expect(panel.bringIn.hidden).toBe(false);
    expect(panel.advance.hidden).toBe(true);
    panel.bringIn.click();
    expect(onBringIn).toHaveBeenCalledTimes(1);
  });

  it('shows a refusal until the next request, with its code only in the details', () => {
    const panel = buildWorldInhabitants({ onBringIn: vi.fn(), onAdvance: vi.fn() });
    panel.render({
      society: view({ refusal: { status: 422, code: 'invalid_society_state', detail: 'initial society requires reachable targets' } }),
      objects: [], walked: 0, advanceBlocked: null,
    });
    const refusal = panel.root.querySelector('.world-inhabitants-refusal') as HTMLElement;
    expect(refusal.hidden).toBe(false);
    expect(refusal.textContent).not.toMatch(/invalid_society_state/);
    expect(panel.root.querySelector('details code')?.textContent).toBe('invalid_society_state: initial society requires reachable targets');
  });

  it('with inhabitants: counts them, lists each object in the server\'s words, and offers the minute', () => {
    const snapshot = parseSociety({
      society_id: 'society', version_id: 'branch', branch_id: 'branch', place_id: 'place', population_size: 100,
      current_tick: 7, state_sha256: 'a'.repeat(64), input_seq: 2, input_sha256: 'b'.repeat(64),
      state: { profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'branch', tick: 7, input_seq: 2,
        input_sha256: 'b'.repeat(64), inhabitants: Array.from({ length: 100 }, (_, i) => ({
          id: `person-${i}`, synthetic: true, position_mm: [i, 0], display_name: `Person ${i}`, role: 'steward',
          goal: null, route: null, motion_path_mm: [[i, 0]],
          action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
          explanation: { summary: 'Awaiting a supported goal.', event_ids: [] } })) },
      places: {
        input_seq: 2, input_sha256: 'b'.repeat(64), availability: 'available', unavailable_reason: null,
        walkable_area: { source: 'declared', centre_mm: [0, 0], half_width_mm: 12000, half_depth_mm: 12000 },
        clearance_mm: 450,
        targets: [{ target_id: 't-near', subject_id: 's-near', node_id: 'n', affordance: 'rest', duration_ticks: 3,
          origin: 'authored', object_id: 'near', version_id: 'branch', enabled: true }],
        unavailable_affordances: [{ target_id: 't-far', subject_id: 's-far', object_id: 'far', version_id: 'branch',
          affordance: 'rest', reason: 'authored_affordance_unreachable' }],
      },
    });
    const onAdvance = vi.fn();
    const panel = buildWorldInhabitants({ onBringIn: vi.fn(), onAdvance });
    panel.render({ society: view({ status: 'ready', snapshot, eventsAvailable: true }), objects, walked: 3, advanceBlocked: null });
    expect(panel.root.dataset['state']).toBe('present');
    expect(panel.root.querySelector('.world-inhabitants-summary')?.textContent)
      .toBe('100 inhabitants live here. 3 walked in the last minute. Simulated minute 7.');
    expect(panel.bringIn.hidden).toBe(true);
    const items = [...panel.root.querySelectorAll('.world-inhabitants-places li')] as HTMLElement[];
    expect(items.map((item) => [item.dataset['objectId'], item.dataset['status']])).toEqual([
      ['near', 'usable'], ['far', 'unreachable'], ['edge', 'not-noticed'], ['new', 'not-noticed'],
    ]);
    expect(items[1]!.textContent).toMatch(/outside the area they walk in/);
    panel.advance.click();
    expect(onAdvance).toHaveBeenCalledTimes(1);
    panel.render({ society: view({ status: 'ready', snapshot, eventsAvailable: true }), objects, walked: 0,
      advanceBlocked: 'Pause the simulation to advance one minute by hand.' });
    expect(panel.advance.disabled).toBe(true);
  });
});
