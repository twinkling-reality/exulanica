// The inspector's words for a simulated person come from the data file the server's Companion
// reads, and the choice among them is held to the cases the server's renderer runs too
// (tests/test_inhabitant_words.py). A change to either side's choice fails one of the two.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { inhabitantWordsFrom, livingInhabitantWords, livingNeedLabel, REASON_WORDS, type PlaceWords, type WordedPerson } from '../src/society-inhabitant-words.js';
import { parseSociety } from '../src/society-api.js';
import { inhabitantWords } from '../src/ui/world-inhabitants.js';

interface Case {
  readonly case: string;
  readonly profile?: string;
  readonly place_words?: PlaceWords;
  readonly person: WordedPerson;
  readonly expected: { readonly who: string; readonly what: string; readonly doing: string; readonly why: string };
}

const CASES = JSON.parse(
  readFileSync(new URL('../../../../tests/fixtures/society-inhabitant-words/cases.json', import.meta.url), 'utf8'),
) as {
  readonly places: Record<string, string>;
  readonly people: Record<string, string>;
  readonly bridges: Record<string, string>;
  readonly cases: readonly Case[];
};
const CATALOG = JSON.parse(
  readFileSync(new URL('../../../../assets/catalogs/society-words/society-inhabitant-words.v1.json', import.meta.url), 'utf8'),
) as { readonly entries: readonly { readonly kind: string; readonly code: string; readonly words: string }[] };

describe('a simulated person in words, as the server says them', () => {
  it('keeps purposeful words for an older saved-world response that also has an ordinal', () => {
    const digest = 'a'.repeat(64);
    const person = { id: 'person-1', synthetic: true, ordinal: 0, display_name: 'Ari Ash 1', role: 'walker',
      position_mm: [0, 0], motion_path_mm: [[0, 0]], goal: null, route: null,
      action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
      explanation: { summary: 'Awaiting a goal.', event_ids: [] } };
    const saved = parseSociety({ society_id: 'society', version_id: 'version', branch_id: 'version',
      place_id: 'place', population_size: 1, current_tick: 0, state_sha256: digest,
      input_seq: 1, input_sha256: digest,
      state: { profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'version',
        tick: 0, input_seq: 1, input_sha256: digest, inhabitants: [person] } });
    expect(inhabitantWordsFrom(saved.state.inhabitants[0]!, () => null, () => null, saved.state.profile))
      .toEqual({ who: 'Ari Ash 1',
        what: 'A simulated walker, invented for this world: not anyone you know, and nothing they do is a memory.',
        doing: 'Standing, deciding where to go.', why: 'Because they have only just arrived.' });
  });
  it('describes a living resident without an identifier or a need level', () => {
    const said = livingInhabitantWords({
      role: 'shopkeeper',
      has_home: true,
      has_work: true,
      action: { kind: 'move', reason: 'following_route' },
      goal: { activity: 'work', reason: 'shift_due' },
    }, 6);
    expect(said).toEqual({
      who: 'Resident 7', what: 'A simulated shopkeeper in this town. They have a home and an assigned workplace.',
      doing: 'walking to work', why: 'Their work shift is due.',
    });
    expect(JSON.stringify(said)).not.toMatch(/of 1000|premises:|[0-9a-f]{8}-[0-9a-f]{4}/);
  });
  it('takes each living need label from the engine catalog', () => {
    const needs = JSON.parse(readFileSync(new URL('../../../../assets/catalogs/society/society-need.v1.json', import.meta.url), 'utf8')) as {
      readonly entries: readonly { readonly key: string; readonly label: string }[];
    };
    expect(needs.entries.length).toBeGreaterThan(0);
    for (const entry of needs.entries) expect(livingNeedLabel(entry.key)).toBe(entry.label);
    expect(livingNeedLabel('unrecognized_code')).toBe('another need');
  });
  it('says what every shared case expects', () => {
    // A positive control: the cases were read, and they reach every branch below.
    expect(CASES.cases.length).toBeGreaterThan(20);
    for (const held of CASES.cases) {
      const said = inhabitantWordsFrom(
        held.person,
        (targetId) => CASES.places[targetId] ?? null,
        (id) => CASES.people[id] ?? null,
        held.profile ?? null,
        held.place_words ?? null,
        false,
        (bridge) => CASES.bridges[bridge] ?? null,
      );
      expect(said, held.case).toEqual(held.expected);
    }
  });

  it('reads its reason words from the catalog, not from a copy', () => {
    const stated = Object.fromEntries(CATALOG.entries.filter((entry) => entry.kind === 'reason').map((entry) => [entry.code, entry.words]));
    expect(REASON_WORDS).toEqual(stated);
  });

  it('draws the inspector through the same words, naming places by the person\'s own objects', () => {
    const held = CASES.cases.find((candidate) => candidate.case === 'walking to rest')!;
    const person = { ...held.person, id: 'p-a' } as unknown as Parameters<typeof inhabitantWords>[0];
    const rows = [{
      object: { objectId: 'bench', title: 'Bench 2', xMm: 0, zMm: 0 },
      label: 'Bench 2',
      status: { kind: 'usable', affordance: 'rest', targetId: 'target:bench', room: null },
      words: '',
    }] as unknown as Parameters<typeof inhabitantWords>[1];
    expect(inhabitantWords(person, rows)).toEqual(held.expected);
  });
});

describe('a person a program from outside decides for', () => {
  // A decider's choice is recorded as chosen_by_their_model whichever decider made it; for a person
  // whose own program decides, no model of this world was asked, so the words must not credit one.
  const phrase = (code: string) => CATALOG.entries.find((entry) => entry.kind === 'phrase' && entry.code === code)!.words;
  const reason = (code: string) => CATALOG.entries.find((entry) => entry.kind === 'reason' && entry.code === code)!.words;
  const chosen = CASES.cases.find((one) => one.person.goal !== null && typeof one.person.goal === 'object' &&
    'reason' in one.person.goal && (one.person.goal as { reason: string }).reason === 'chosen_by_their_model');

  it('says its own program chose, where a model is credited for anyone else', () => {
    const person = chosen?.person ?? ({
      display_name: 'Visitor', role: null, goal: null,
      action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'chosen_by_their_model' },
    } as unknown as WordedPerson);
    const because = (words: string) => phrase('because').replace('{reason}', words);
    const ours = inhabitantWordsFrom(person, () => 'the well', () => 'Knight', null, null, false);
    const outside = inhabitantWordsFrom(person, () => 'the well', () => 'Knight', null, null, true);
    expect(ours.why).toBe(because(reason('chosen_by_their_model')));
    expect(outside.why).toBe(because(phrase('chosen_by_their_program')));
    expect(outside.why).not.toMatch(/model/u);
    // Nothing else changes.
    expect({ ...outside, why: '' }).toEqual({ ...ours, why: '' });
  });

  it('leaves every other reason as it is', () => {
    const person = {
      display_name: 'Visitor', role: null, goal: null,
      action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
    } as unknown as WordedPerson;
    expect(inhabitantWordsFrom(person, () => null, () => null, null, null, true).why)
      .toBe(inhabitantWordsFrom(person, () => null, () => null, null, null, false).why);
  });
});

describe('a person who came in from outside', () => {
  // Never called invented for this world: where they came from, as the door lists their bridge, and
  // who decides for them here, from their arrival's record (root's ruling 2026-10-08). The words are
  // the catalog's.
  const phrase = (code: string) => CATALOG.entries.find((entry) => entry.kind === 'phrase' && entry.code === code)!.words;
  const fill = (text: string, values: Record<string, string>) => text.replace(/\{(\w+)\}/gu, (_all, key: string) => values[key]!);
  const person = (extra: Record<string, unknown>) => ({
    display_name: 'Visitor', role: 'traveller', goal: null,
    action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' }, ...extra,
  } as unknown as WordedPerson);
  const listed = (bridge: string) => (bridge === 'blockgame' ? 'Block Game' : null);
  const words = (extra: Record<string, unknown>) => inhabitantWordsFrom(person(extra), () => null, () => null, null, null, false, listed);

  it('says the world decides, or the program they came with, from their arrival', () => {
    expect(words({ came_by: 'crossed', crossing: { bridge: 'blockgame', decided_by: 'world' } }).what)
      .toBe(fill(phrase('what_crossed_world'), { role: 'traveller', from: 'Block Game' }));
    expect(words({ came_by: 'crossed', crossing: { bridge: 'blockgame' } }).what)
      .toBe(fill(phrase('what_crossed_program'), { role: 'traveller', from: 'Block Game' }));
    // A bridge the door does not list, or no writer at all, is not guessed at.
    expect(words({ came_by: 'crossed', crossing: { bridge: 'elsewhere' } }).what)
      .toBe(fill(phrase('what_crossed_program'), { role: 'traveller', from: phrase('from_outside') }));
    expect(inhabitantWordsFrom(person({ came_by: 'crossed', crossing: { bridge: 'blockgame' } }), () => null, () => null).what)
      .toBe(fill(phrase('what_crossed_program'), { role: 'traveller', from: phrase('from_outside') }));
  });

  it('changes nothing else, and nothing for anyone who did not cross', () => {
    const plain = words({ came_by: 'placed' });
    expect(plain.what).toBe(fill(phrase('what'), { role: 'traveller' }));
    expect(words({}).what).toBe(plain.what);
    // Only how they came decides: a crossing record on anyone who did not cross is not read.
    expect(words({ came_by: 'placed', crossing: { bridge: 'blockgame' } }).what).toBe(plain.what);
    expect({ ...words({ came_by: 'crossed', crossing: { bridge: 'blockgame', decided_by: 'world' } }), what: '' }).toEqual({ ...plain, what: '' });
  });
});

describe('a place the input lists that no object of the person names', () => {
  // A town's premises is still there: said plainly, never as gone (root 6's ruling, 2026-10-08).
  const phrase = (code: string) => CATALOG.entries.find((entry) => entry.kind === 'phrase' && entry.code === code)!.words;
  const target = 'city.premises:p1:visit';
  const visitor = {
    id: 'p-a', display_name: 'Ari Ash 1', role: 'resident',
    goal: { kind: 'visit', reason: 'looking_around', target_id: target },
    action: { kind: 'move', status: 'active', target_id: target, remaining_ticks: 0, reason: 'following_reachable_route' },
  } as unknown as Parameters<typeof inhabitantWords>[0];

  it('is a place where the input lists it, and gone only where it does not', () => {
    const gone = inhabitantWords(visitor, []).doing;
    expect(gone).toContain(phrase('place_gone'));
    expect(inhabitantWords(visitor, [], [], null, false, null, new Map([['city.premises:other:visit', null]])).doing).toBe(gone);
    const said = (name: { useClass: string; label: string | null; addressNumber: number | null } | null) =>
      inhabitantWords(visitor, [], [], null, false, null, new Map([[target, name]])).doing;
    expect(said(null)).toBe(gone.replace(phrase('place_gone'), phrase('place_listed')));
    // Named by its town where the input says: its label, with its address number where the town gives one.
    expect(said({ useClass: 'bakery', label: 'bakery', addressNumber: null }))
      .toBe(gone.replace(phrase('place_gone'), phrase('place_named').replace('{label}', 'bakery')));
    expect(said({ useClass: 'bakery', label: 'bakery', addressNumber: 12 }))
      .toBe(gone.replace(phrase('place_gone'), phrase('place_named_at').replace('{label}', 'bakery').replace('{number}', '12')));
    expect(said({ useClass: 'bakery', label: null, addressNumber: 12 })).toBe(said(null));
  });
});
