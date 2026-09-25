// People in a square stay a while, stand and talk: what the page reads of it, and what it says.
import { describe, expect, it } from 'vitest';
import { parseSociety } from '../src/society-api.js';
import { inhabitantWords, placeRows, type InhabitedObject } from '../src/ui/world-inhabitants.js';

const target = (overrides: Record<string, unknown> = {}) => ({
  target_id: 't-bench', subject_id: 's-bench', node_id: 'n', affordance: 'rest', activity: 'rest_bench',
  origin: 'authored', object_id: 'bench', version_id: 'version', enabled: true, place_node_ids: ['place:bench:0'],
  ...overrides,
});

const person = (id: string, name: string, overrides: Record<string, unknown> = {}) => ({
  id, synthetic: true, position_mm: [2000, 4000], display_name: name, role: 'steward',
  goal: null, route: null, motion_path_mm: [[2000, 4000]],
  action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
  explanation: { summary: `${name} (simulated) waits.`, event_ids: [] },
  ...overrides,
});

const read = (people: unknown[], targets: unknown[] = [target()]) => parseSociety({
  society_id: 'society', version_id: 'version', branch_id: 'version', place_id: 'p', population_size: people.length,
  current_tick: 9, state_sha256: '9'.repeat(64), input_seq: 3, input_sha256: 'b'.repeat(64),
  state: { profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'version', tick: 9, input_seq: 3,
    input_sha256: 'b'.repeat(64), inhabitants: people },
  places: {
    input_seq: 3, input_sha256: 'b'.repeat(64), availability: 'available', unavailable_reason: null,
    walkable_area: { source: 'declared', centre_mm: [0, 0], half_width_mm: 12000, half_depth_mm: 12000 },
    clearance_mm: 450, targets, unavailable_affordances: [],
  },
});

const talk = (partner: string, overrides: Record<string, unknown> = {}) => ({
  goal: { kind: 'talk', target_id: null, reason: 'stopped_to_talk', partner_id: partner, duration_ticks: 4 },
  action: { kind: 'talk', status: 'active', target_id: null, remaining_ticks: 3, reason: 'talking' },
  ...overrides,
});
const objects: readonly InhabitedObject[] = [{ objectId: 'bench', title: 'Bench', xMm: 0, zMm: 0 }];

describe('a square\'s people, as the page reads them', () => {
  it('reads a target that names its routine\'s activity instead of a fixed duration', () => {
    const snapshot = read([person('a', 'Ada')]);
    expect(snapshot.places!.targets[0]).toMatchObject({ activity: 'rest_bench', durationTicks: null });
    // Exactly one of the two: a target stating both, or neither, is refused.
    expect(() => read([person('a', 'Ada')], [target({ duration_ticks: 3 })])).toThrow('Invalid society place');
    expect(() => read([person('a', 'Ada')], [target({ activity: undefined })])).toThrow('Invalid society place');
  });

  it('reads standing and talking, and refuses a talk with nobody the state holds', () => {
    const snapshot = read([
      person('a', 'Ada', talk('b')),
      person('b', 'Bo', talk('a')),
      person('c', 'Cy', {
        goal: { kind: 'stand', target_id: null, reason: 'stopping_a_while' },
        action: { kind: 'stand', status: 'active', target_id: null, remaining_ticks: 2, reason: 'standing_a_while' },
      }),
    ]);
    expect(snapshot.state.inhabitants.map((held) => held.action?.kind)).toEqual(['talk', 'talk', 'stand']);
    expect(() => read([person('a', 'Ada', talk('nobody'))])).toThrow('Invalid society goal');
    expect(() => read([person('a', 'Ada', talk('a'))])).toThrow('Invalid society goal');
    expect(() => read([person('a', 'Ada', { ...talk('b'), action: { kind: 'juggle', status: 'active', target_id: null,
      remaining_ticks: 1, reason: 'talking' } }), person('b', 'Bo', talk('a'))])).toThrow('Invalid society action');
  });
});

describe('what the inspector says of each new behaviour', () => {
  const words = (people: unknown[], index = 0) => {
    const snapshot = read(people);
    const inhabitants = snapshot.state.inhabitants;
    const said = inhabitantWords(inhabitants[index]!, placeRows(objects, snapshot.places!), inhabitants);
    return `${said.doing} ${said.why}`;
  };

  it('names the other person in a talk, and says nothing of what about', () => {
    // Walking over, the goal says why they set out; from there on, the talk itself says.
    expect(words([person('a', 'Ada', talk('b', {
      action: { kind: 'move', status: 'active', target_id: null, remaining_ticks: 0, reason: 'following_reachable_route' },
    })), person('b', 'Bo', talk('a'))])).toBe('Walking over to talk with Bo. Because they met someone and stopped to talk.');
    expect(words([person('a', 'Ada', talk('b', {
      action: { kind: 'talk', status: 'active', target_id: null, remaining_ticks: 4, reason: 'waiting_for_partner' },
    })), person('b', 'Bo', talk('a'))])).toBe('Waiting for Bo, to talk. Because the person they are meeting is still on the way.');
    expect(words([person('a', 'Ada', talk('b')), person('b', 'Bo', talk('a'))]))
      .toBe('Talking with Bo, 3 more simulated minutes. Because they met and stopped to talk.');
    expect(words([person('a', 'Ada', talk('b', {
      action: { kind: 'talk', status: 'completed', target_id: null, remaining_ticks: 0, reason: 'reviewed_duration_elapsed' },
    })), person('b', 'Bo', talk('a'))])).toBe('Just finished talking with Bo. Because they have been at it as long as they meant to.');
    expect(words([person('a', 'Ada', talk('b', {
      action: { kind: 'talk', status: 'completed', target_id: null, remaining_ticks: 3, reason: 'partner_left' },
    })), person('b', 'Bo')])).toBe('Just finished talking with Bo. Because the person they were talking with left.');
    // Without the people to name them from, the other person is somebody nearby, never guessed.
    const snapshot = read([person('a', 'Ada', talk('b')), person('b', 'Bo', talk('a'))]);
    expect(inhabitantWords(snapshot.state.inhabitants[0]!, []).doing).toBe('Talking with someone nearby, 3 more simulated minutes.');
  });

  it('says someone is standing a while, and walking to stand, in words', () => {
    const standing = (action: Record<string, unknown>) => words([person('c', 'Cy', {
      goal: { kind: 'stand', target_id: null, reason: 'stopping_a_while' }, action,
    })]);
    expect(standing({ kind: 'move', status: 'active', target_id: null, remaining_ticks: 0, reason: 'following_reachable_route' }))
      .toBe('Walking to a spot to stand a while. Because they chose to stop and stand a while.');
    expect(standing({ kind: 'stand', status: 'active', target_id: null, remaining_ticks: 1, reason: 'standing_a_while' }))
      .toBe('Standing a while, one more simulated minute. Because they stopped to stand a while.');
    expect(standing({ kind: 'stand', status: 'completed', target_id: null, remaining_ticks: 0, reason: 'reviewed_duration_elapsed' }))
      .toBe('Just finished standing a while. Because they have been at it as long as they meant to.');
  });

  it('says why a rested person sits or looks around', () => {
    const sitting = words([person('d', 'Di', {
      goal: { kind: 'rest', target_id: 't-bench', reason: 'sitting_a_while' },
      action: { kind: 'rest', status: 'active', target_id: 't-bench', remaining_ticks: 7, reason: 'arrived_at_access_node' },
    })]);
    expect(sitting).toBe('Resting at Bench, 7 more simulated minutes. Because they chose to sit a while.');
  });
});
