// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import type { LiveSocietyView } from '../src/composition/live-society.js';
import { parseSociety } from '../src/society-api.js';
import { parseSocietyControl, type SocietyPlaybackControl } from '../src/society-control-api.js';
import {
  buildWorldInhabitants,
  everyWords,
  inhabitantWords,
  movedWords,
  noticeWords,
  placeRows,
  type InhabitedObject,
} from '../src/ui/world-inhabitants.js';

const control = (mode: 'paused' | 'playing', host?: unknown, extra: Record<string, unknown> = {}): SocietyPlaybackControl =>
  parseSocietyControl({
    profile: 'exulanica.society-control/v1', society_id: 'society', branch_id: 'version', persisted: true,
    revision: 1, mode, speed: 2, base_tick_interval_ms: 8000, tick_interval_ms: 4000,
    interval_semantics: 'minimum_wait_after_batch_completion', last_batch_execution: null,
    simulated_seconds_per_tick: 60, max_catchup_ticks: 3, next_due_at: null, reason: null,
    lease_expires_at: null, last_event_seq: 0, current_tick: 7, state_sha256: 'a'.repeat(64),
    play_ineligible_reason: null, play_eligible: true,
    ...(host === undefined ? {} : { host_playback: host }), ...extra,
  }, 'version');
const running = { running: true, interval_ms: 4000, reason: null };
const notHere = { running: false, interval_ms: 4000, reason: 'This host does not play this workspace.' };

const person = (overrides: Record<string, unknown> = {}) => ({
  id: 'person-0', synthetic: true, position_mm: [2000, 4000], display_name: 'Ada', role: 'steward',
  goal: null, route: null, motion_path_mm: [[2000, 4000]],
  action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
  explanation: { summary: 'Ada (simulated) waits.', event_ids: [] },
  ...overrides,
});
const snapshot = parseSociety({
  society_id: 'society', version_id: 'version', branch_id: 'version', place_id: 'derived-place',
  population_size: 1, current_tick: 7, state_sha256: '7'.repeat(64), input_seq: 2, input_sha256: 'b'.repeat(64),
  state: { profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'version', tick: 7, input_seq: 2,
    input_sha256: 'b'.repeat(64), inhabitants: [person()] },
  places: {
    input_seq: 2, input_sha256: 'b'.repeat(64), availability: 'available', unavailable_reason: null,
    walkable_area: null, clearance_mm: 450,
    targets: [{ target_id: 't-bench', subject_id: 's-bench', node_id: 'n', affordance: 'rest', duration_ticks: 3,
      origin: 'authored', object_id: 'bench', version_id: 'version', enabled: true }],
    unavailable_affordances: [],
  },
});
const view = (): LiveSocietyView => ({
  mode: 'authenticated', status: 'ready', busy: false, snapshot, events: [], eventsAvailable: true, message: '', refusal: null,
});
const objects: readonly InhabitedObject[] = [{ objectId: 'bench', title: 'Bench', xMm: 2000, zMm: 4000 }];

function panel() {
  const handlers = {
    onBringIn: vi.fn(), onAdvance: vi.fn(), onSendAway: vi.fn(), onBringBack: vi.fn(),
    onPlay: vi.fn(), onPause: vi.fn(), onPace: vi.fn(),
  };
  const built = buildWorldInhabitants(handlers);
  const shown = (node: HTMLElement) => !node.hidden;
  const text = (selector: string) => {
    const node = built.root.querySelector<HTMLElement>(selector)!;
    return node.hidden ? null : node.textContent;
  };
  return { built, handlers, shown, text };
}

describe('Play, Pause and pace beside the people', () => {
  it('offers Play only where the host plays this world, and Advance while paused', () => {
    const { built, handlers, shown, text } = panel();
    built.render({ society: view(), objects, walked: 0, advanceBlocked: null, playback: { control: control('paused', running), busy: false } });
    expect(shown(built.play)).toBe(true);
    expect(built.play.textContent).toBe('Play');
    expect(shown(built.advance)).toBe(true);
    expect(text('.world-inhabitants-playback')).toBe('Paused. Press Play to watch them live.');
    // Each pace says how long a simulated minute takes there: the host's 8 s base over the speed.
    expect([...built.pace.options].map((option) => option.textContent)).toEqual([
      '1× · a minute every 8 seconds', '2× · a minute every 4 seconds', '4× · a minute every 2 seconds',
    ]);
    expect(built.pace.value).toBe('2');
    built.play.click();
    expect(handlers.onPlay).toHaveBeenCalledTimes(1);
    built.pace.value = '4';
    built.pace.dispatchEvent(new Event('change'));
    expect(handlers.onPace).toHaveBeenCalledWith(4);
  });

  it('offers Pause while playing, says the pace, and takes Advance away rather than disabling it', () => {
    const { built, handlers, shown, text } = panel();
    built.render({ society: view(), objects, walked: 0, advanceBlocked: 'Pause the simulation to advance one minute by hand.',
      playback: { control: control('playing', running), busy: false } });
    expect(built.play.textContent).toBe('Pause');
    expect(shown(built.advance)).toBe(false);
    expect(text('.world-inhabitants-playback')).toBe('Playing: one simulated minute every 4 seconds.');
    built.play.click();
    expect(handlers.onPause).toHaveBeenCalledTimes(1);
    expect(handlers.onPlay).not.toHaveBeenCalled();
  });

  it('puts the server\'s own words in front of the person where the host does not play', () => {
    const { built, shown } = panel();
    built.render({ society: view(), objects, walked: 0, advanceBlocked: null, playback: { control: control('paused', notHere), busy: false } });
    expect(shown(built.play)).toBe(false);
    expect(shown(built.advance)).toBe(true);
    expect(built.root.textContent).toContain('This host does not play this workspace. Advance one minute at a time instead.');
    // Saved as playing on such a host: Pause stays, so it can be stepped by hand again.
    built.render({ society: view(), objects, walked: 0, advanceBlocked: null, playback: { control: control('playing', notHere), busy: false } });
    expect(built.play.textContent).toBe('Pause');
    expect(built.root.textContent).toContain('Saved as playing, but nothing moves until this host plays it.');
  });

  it('offers no Play where the server says nothing about playing, or the engine cannot', () => {
    const { built, shown } = panel();
    built.render({ society: view(), objects, walked: 0, advanceBlocked: null, playback: { control: control('paused'), busy: false } });
    expect(shown(built.play)).toBe(false);
    expect(built.root.textContent).toContain('This server does not say whether it plays worlds on its own');
    built.render({ society: view(), objects, walked: 0, advanceBlocked: null, playback: {
      control: control('paused', running, { play_eligible: false, play_ineligible_reason: 'This engine records no playback.' }), busy: false } });
    expect(shown(built.play)).toBe(false);
    expect(built.root.textContent).toContain('This engine records no playback.');
  });

  it('holds both controls still while a change is on its way', () => {
    const { built } = panel();
    built.render({ society: view(), objects, walked: 0, advanceBlocked: null, playback: { control: control('paused', running), busy: true } });
    expect(built.play.disabled).toBe(true);
    expect(built.pace.disabled).toBe(true);
  });
});

describe('lines about what the person sees', () => {
  it('names anyone moved without walking, and when a new object is noticed', () => {
    const { built, text } = panel();
    built.render({ society: view(), objects, walked: 0, advanceBlocked: null,
      moved: [{ inhabitantId: 'a', reason: 'minutes-not-read', unreadTicks: 2 }, { inhabitantId: 'b', reason: 'minutes-not-read', unreadTicks: 2 }],
      noticing: { label: 'Bench', minute: 8, noticed: false } });
    expect(text('.world-inhabitants-moved')).toBe(
      '2 people moved without walking: this page missed 2 simulated minutes, so they are shown where they are now.');
    expect(text('.world-inhabitants-notice')).toBe('They notice Bench at simulated minute 8, the next one.');
    built.render({ society: view(), objects, walked: 0, advanceBlocked: null, moved: [] });
    expect(text('.world-inhabitants-moved')).toBeNull();
    expect(text('.world-inhabitants-notice')).toBeNull();
  });

  it('words every reason the crowd names, and names one it does not know instead of guessing', () => {
    // The words table is typed by the crowd's reasons, so a reason without words fails typecheck;
    // this is the runtime side of the same list.
    for (const reason of ['minutes-not-read', 'path-starts-elsewhere', 'too-far-behind', 'no-recorded-path', 'not-newer'] as const) {
      expect(movedWords([{ inhabitantId: 'a', reason, unreadTicks: 1 }]), reason).not.toMatch(/no words for/);
    }
    expect(movedWords([{ inhabitantId: 'a', reason: 'teleported' as never, unreadTicks: 0 }]))
      .toBe('Someone moved without walking: of a reason this page has no words for (teleported).');
    expect(movedWords([
      { inhabitantId: 'a', reason: 'too-far-behind', unreadTicks: 0 },
      { inhabitantId: 'b', reason: 'not-newer', unreadTicks: 0 },
    ])).toMatch(/Others moved for other reasons\.$/);
    expect(noticeWords({ label: 'Bench', minute: 8, noticed: true })).toBe('They noticed Bench at simulated minute 8.');
    expect(everyWords(60_000)).toBe('every minute');
    expect(everyWords(120_000)).toBe('every 2 minutes');
    expect(everyWords(1_000)).toBe('every second');
    expect(everyWords(2_500)).toBe('every 2.5 seconds');
  });
});

describe('who a person is and what they are doing, in words', () => {
  const rows = placeRows(objects, snapshot.places!);
  const words = (overrides: Record<string, unknown>) =>
    inhabitantWords(parseSociety({
      ...JSON.parse(JSON.stringify({
        society_id: 'society', version_id: 'version', branch_id: 'version', place_id: 'p', population_size: 1,
        current_tick: 7, state_sha256: '7'.repeat(64), input_seq: 2, input_sha256: 'b'.repeat(64),
      })),
      state: { profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'version', tick: 7, input_seq: 2,
        input_sha256: 'b'.repeat(64), inhabitants: [person(overrides)] },
    }).state.inhabitants[0]!, rows);

  it('names places by the titles of the person\'s objects and turns reason codes into words', () => {
    expect(words({})).toEqual({
      who: 'Ada',
      what: 'A simulated steward, invented for this world: not anyone you know, and nothing they do is a memory.',
      doing: 'Standing, deciding where to go.',
      why: 'Because they have only just arrived.',
    });
    const walking = words({
      goal: { kind: 'rest', target_id: 't-bench', reason: 'restore_need' },
      action: { kind: 'move', status: 'active', target_id: 't-bench', remaining_ticks: 0, reason: 'following_reachable_route' },
    });
    expect(`${walking.doing} ${walking.why}`).toBe(
      'Walking to Bench to rest. Because they need a rest, and it is the nearest place to rest they have not just used.');
    const resting = words({
      goal: { kind: 'rest', target_id: 't-bench', reason: 'remembered_target_selected' },
      action: { kind: 'rest', status: 'active', target_id: 't-bench', remaining_ticks: 1, reason: 'arrived_at_access_node' },
    });
    expect(`${resting.doing} ${resting.why}`).toBe('Resting at Bench, one more simulated minute. Because you asked them to go there.');
    const blocked = words({
      goal: { kind: 'visit', target_id: 't-gone', reason: 'visit_place' },
      action: { kind: 'idle', status: 'blocked', target_id: 't-gone', remaining_ticks: 0, reason: 'no_room_at_destination' },
    });
    expect(`${blocked.doing} ${blocked.why}`).toBe('Waiting. Because every place they could use is taken.');
    const done = words({
      goal: { kind: 'visit', target_id: 't-gone', reason: 'visit_place' },
      action: { kind: 'visit', status: 'completed', target_id: 't-gone', remaining_ticks: 0, reason: 'reviewed_duration_elapsed' },
    });
    // A place the person's objects no longer name is said to be gone, never guessed at.
    expect(done.doing).toBe('Just finished visiting a place that is no longer there.');
  });

  it('names a reason code it has no words for rather than guessing', () => {
    const odd = words({ action: { kind: 'idle', status: 'blocked', target_id: null, remaining_ticks: 0, reason: 'a_new_reason' } });
    expect(odd.why).toBe('Because of a reason this page has no words for (a_new_reason).');
  });
});
