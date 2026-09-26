import { describe, expect, it } from 'vitest';
import type { KindPlace, KindUse } from '@exulanica/atlas-react/playcanvas';

import { objectUseWords } from '../src/ui/object-placement.js';
import type { KindActivity } from '../src/world-objects-api.js';

/**
 * What the Create panel says inhabitants do with a kind, from the fields `GET /world/assets` serves.
 *
 * Every figure in a sentence below is a figure in its row: changing the row changes the words, and
 * nothing about a kind, an activity or a duration is written in the page.
 */

const place = (x: number): KindPlace => Object.freeze({ positionMm: [x, 450] as const, faces: '-y', seat: null });
const use = (count: number | null): KindUse => Object.freeze({
  affordance: 'visit',
  places: count === null ? null : Object.freeze(Array.from({ length: count }, (_, index) => place(index * 800))),
});
const activity = (label: string, shortest: number, longest: number): KindActivity => Object.freeze({
  key: 'an_entry', label, durationMinimumTicks: shortest, durationMaximumTicks: longest,
});

describe('what inhabitants do with a kind, in words', () => {
  it('says a bench as its row states it: three places, resting on a bench, five to fifteen minutes', () => {
    expect(objectUseWords(use(3), activity('resting on a bench', 5, 15)))
      .toBe('Up to 3 inhabitants at a time spend 5 to 15 minutes here, resting on a bench.');
  });

  it('counts the places, names the activity and gives the stay, from the row', () => {
    expect(objectUseWords(use(2), activity('at a market stall', 2, 6)))
      .toBe('Up to 2 inhabitants at a time spend 2 to 6 minutes here, at a market stall.');
    // A different row, different words: the figures are the row's, not the page's.
    expect(objectUseWords(use(4), activity('by a tree', 1, 4)))
      .toBe('Up to 4 inhabitants at a time spend 1 to 4 minutes here, by a tree.');
    expect(objectUseWords(use(1), activity('reading', 7, 9)))
      .toBe('One inhabitant at a time spends 7 to 9 minutes here, reading.');
  });

  it('says no number for a marker, whose places the society derives', () => {
    expect(objectUseWords(use(null), activity('resting', 3, 10)))
      .toBe('Inhabitants spend 3 to 10 minutes here, resting.');
    expect(objectUseWords(use(null), activity('visiting', 1, 3)))
      .toBe('Inhabitants spend 1 to 3 minutes here, visiting.');
  });

  it('says one stay where the shortest and the longest are the same', () => {
    expect(objectUseWords(use(3), activity('resting', 3, 3)))
      .toBe('Up to 3 inhabitants at a time spend 3 minutes here, resting.');
    expect(objectUseWords(use(null), activity('visiting', 1, 1)))
      .toBe('Inhabitants spend a minute here, visiting.');
  });

  it('says a kind the row gives no activity is one inhabitants do not use', () => {
    expect(objectUseWords(Object.freeze({ affordance: 'none', places: Object.freeze([]) }), null))
      .toBe('Inhabitants do not use this.');
  });

  it('says nothing where the row states no use, or was read without its activity', () => {
    expect(objectUseWords(null, null)).toBeNull();
    expect(objectUseWords(undefined, undefined)).toBeNull();
    expect(objectUseWords(use(2), undefined)).toBeNull();
  });
});
