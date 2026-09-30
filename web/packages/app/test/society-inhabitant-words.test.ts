// The inspector's words for a simulated person come from the data file the server's Companion
// reads, and the choice among them is held to the cases the server's renderer runs too
// (tests/test_inhabitant_words.py). A change to either side's choice fails one of the two.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { inhabitantWordsFrom, livingInhabitantWords, livingNeedLabel, REASON_WORDS, type WordedPerson } from '../src/society-inhabitant-words.js';
import { inhabitantWords } from '../src/ui/world-inhabitants.js';

interface Case {
  readonly case: string;
  readonly person: WordedPerson;
  readonly expected: { readonly who: string; readonly what: string; readonly doing: string; readonly why: string };
}

const CASES = JSON.parse(
  readFileSync(new URL('../../../../tests/fixtures/society-inhabitant-words/cases.json', import.meta.url), 'utf8'),
) as { readonly places: Record<string, string>; readonly people: Record<string, string>; readonly cases: readonly Case[] };
const CATALOG = JSON.parse(
  readFileSync(new URL('../../../../assets/catalogs/society-words/society-inhabitant-words.v1.json', import.meta.url), 'utf8'),
) as { readonly entries: readonly { readonly kind: string; readonly code: string; readonly words: string }[] };

describe('a simulated person in words, as the server says them', () => {
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
