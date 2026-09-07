/**
 * The presentation rule, at the points where the safe answer and the obvious answer differ.
 *
 * The design note's third stage says the world never draws pixels for a masked region and the
 * status says how many people are hidden. Both are one-line claims with several ways to be
 * quietly false, and each of those ways has a test here: an unrecognised state defaulting to
 * visible, an empty region list read as "nobody here" rather than "nobody looked", a name drawn
 * beside somebody who consented only to being present, and a count of zero reported for a scene
 * whose regions never loaded.
 */

import { describe, expect, it } from 'vitest';

import {
  drawsName,
  drawsPixels,
  drawsSilhouette,
  hiddenRegions,
  mayDrawPhotograph,
  personPresenceSentence,
  type PersonRegionView,
} from '../src/person-presentation.js';

const region = (over: Partial<PersonRegionView> = {}): PersonRegionView => ({
  region_id: 'aa',
  state: 'unknown',
  silhouette_ppm: [[0, 0], [10, 0], [10, 10]],
  display_name: null,
  subject_id: null,
  ...over,
});

describe('what the world may draw of a person', () => {
  it('draws pixels only for a person who consented to their likeness', () => {
    expect(drawsPixels('shown')).toBe(true);
    for (const state of ['unknown', 'present', 'hidden', 'withdrawn']) {
      expect(drawsPixels(state)).toBe(false);
    }
  });

  it('treats an unrecognised state as not drawable', () => {
    expect(drawsPixels(undefined)).toBe(false);
    expect(drawsPixels('visible')).toBe(false);
    expect(drawsPixels(null)).toBe(false);
  });

  it('outlines a person who is present or hidden, and not one who withdrew', () => {
    expect(drawsSilhouette('unknown')).toBe(true);
    expect(drawsSilhouette('present')).toBe(true);
    expect(drawsSilhouette('hidden')).toBe(true);
    expect(drawsSilhouette('withdrawn')).toBe(false);
    expect(drawsSilhouette('shown')).toBe(false);
  });

  it('draws a name only when one arrived, so presence alone never names anybody', () => {
    expect(drawsName(region({ display_name: null }))).toBe(false);
    expect(drawsName(region({ display_name: '' }))).toBe(false);
    expect(drawsName(region({ display_name: 'Julie' }))).toBe(true);
  });

  it('draws a name on a silhouette, which is what present-and-named looks like', () => {
    const named = region({ state: 'present', display_name: 'Julie' });
    expect(drawsPixels(named.state)).toBe(false);
    expect(drawsSilhouette(named.state)).toBe(true);
    expect(drawsName(named)).toBe(true);
  });
});

describe('whether a photograph may be shown at all', () => {
  it('withholds an unscreened photograph even when it lists no people', () => {
    expect(mayDrawPhotograph('unscreened', [])).toBe(false);
    expect(mayDrawPhotograph(undefined, [])).toBe(false);
    expect(mayDrawPhotograph('stale', [])).toBe(false);
  });

  it('shows a screened photograph with nobody in it', () => {
    expect(mayDrawPhotograph('screened', [])).toBe(true);
  });

  it('withholds a screened photograph containing anybody not shown', () => {
    expect(mayDrawPhotograph('screened', [region({ state: 'present' })])).toBe(false);
  });

  it('shows a screened photograph where everybody consented', () => {
    expect(mayDrawPhotograph('screened', [region({ state: 'shown' })])).toBe(true);
  });

  it('treats a missing region list as nobody having looked', () => {
    expect(mayDrawPhotograph('screened', undefined)).toBe(true);
    expect(mayDrawPhotograph('unscreened', undefined)).toBe(false);
  });
});

describe('the hidden count', () => {
  it('counts every person who is not drawn, including a temporarily hidden one', () => {
    const people = [
      region({ state: 'shown' }),
      region({ state: 'present' }),
      region({ state: 'hidden' }),
    ];
    expect(hiddenRegions(people)).toHaveLength(2);
  });

  it('says how many people are hidden and where', () => {
    expect(
      personPresenceSentence({
        hiddenPersonCount: 2,
        maskedMemberCount: 1,
        unscreenedMemberCount: 0,
      }),
    ).toBe('2 people are hidden across 1 photograph; their regions are blank, not reconstructed.');
  });

  it('reads naturally for a single person', () => {
    expect(
      personPresenceSentence({
        hiddenPersonCount: 1,
        maskedMemberCount: 1,
        unscreenedMemberCount: 0,
      }),
    ).toContain('1 person is hidden across 1 photograph');
  });

  it('says nothing when nobody is hidden and everything was screened', () => {
    expect(
      personPresenceSentence({
        hiddenPersonCount: 0,
        maskedMemberCount: 0,
        unscreenedMemberCount: 0,
      }),
    ).toBeNull();
  });

  it('reports unscreened photographs rather than reassuring that nobody is hidden', () => {
    const sentence = personPresenceSentence({
      hiddenPersonCount: 0,
      maskedMemberCount: 0,
      unscreenedMemberCount: 3,
    });
    expect(sentence).toContain('3 photographs have not been screened');
    expect(sentence).not.toContain('0 people');
  });

  it('says both things when a scene has hidden people and unscreened photographs', () => {
    const sentence = personPresenceSentence({
      hiddenPersonCount: 1,
      maskedMemberCount: 1,
      unscreenedMemberCount: 2,
    });
    expect(sentence).toContain('hidden');
    expect(sentence).toContain('not been screened');
  });
});
