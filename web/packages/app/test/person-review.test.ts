// @vitest-environment happy-dom

/**
 * The review screen, at the points where a convenient design would collect a worthless answer.
 *
 * The old gate failed not because anybody lied but because its only usable answer was "nobody is
 * here". So these tests are less about rendering than about what the screen refuses to make easy:
 * it never shows the photograph, it never offers to confirm everything at once, it distinguishes
 * "nobody looked" from "looked and found nobody", and it says out loud that the account holder is
 * deciding on somebody else's behalf.
 */

import { describe, expect, it } from 'vitest';

import { buildPersonReview, type ReviewRegion } from '../src/ui/person-review.js';

const OUTLINE = {
  kind: 'polygon',
  points: [
    [200_000, 200_000],
    [500_000, 200_000],
    [500_000, 700_000],
    [200_000, 700_000],
  ],
};

const detected = (over: Partial<ReviewRegion> = {}): ReviewRegion => ({
  regionKey: 'aa'.repeat(32),
  action: 'detected',
  shape: 'box',
  silhouette: OUTLINE,
  detectorId: 'recorded-vision-observation/v1',
  confidence: 'medium',
  confirmedBy: null,
  subjectId: null,
  state: 'unknown',
  masked: true,
  namePermitted: false,
  ...over,
});

const panel = (over: Partial<Parameters<typeof buildPersonReview>[0]> = {}) =>
  buildPersonReview({
    captureId: 'c0ffee00-0000-4000-8000-000000000000',
    reviewState: 'screened',
    regions: [detected()],
    ...over,
  });

describe('the person review screen', () => {
  it('never renders the photograph it is reviewing', () => {
    const node = panel();
    expect(node.querySelector('img')).toBeNull();
    expect(node.querySelector('canvas')).toBeNull();
    expect(node.innerHTML).not.toContain('/evidence/');
    expect(node.querySelector('svg polygon')).not.toBeNull();
  });

  it('distinguishes a photograph nobody has looked at from one found empty', () => {
    const unscreened = panel({ reviewState: 'unscreened', regions: [] });
    expect(unscreened.textContent).toContain('Nobody has looked');
    const empty = panel({ reviewState: 'screened', regions: [] });
    expect(empty.textContent).toContain('found');
    expect(empty.textContent).not.toContain('Nobody has looked');
  });

  it('offers no way to confirm every region at once', () => {
    const node = panel({ regions: [detected(), detected({ regionKey: 'bb'.repeat(32) })] });
    const labels = [...node.querySelectorAll('button')].map((b) => b.textContent ?? '');
    expect(labels.some((l) => /all|everything/i.test(l))).toBe(false);
    expect(labels.filter((l) => l === 'This is a person')).toHaveLength(2);
  });

  it('says whose decision is being recorded', () => {
    expect(panel().textContent).toContain('not the decision of the person in the photograph');
  });

  it('presents a detection as a proposal rather than a finding', () => {
    expect(panel().textContent).toContain('A proposal, not a decision.');
  });

  it('lets a reviewer reject a false positive', () => {
    const deleted: string[] = [];
    const node = panel({ onDelete: (key) => deleted.push(key) });
    const reject = [...node.querySelectorAll('button')].find(
      (b) => b.textContent === 'Not a person',
    );
    reject?.dispatchEvent(new Event('click'));
    expect(deleted).toEqual(['aa'.repeat(32)]);
  });

  it('does not offer consent controls before somebody is confirmed to be a person', () => {
    const node = panel();
    const labels = [...node.querySelectorAll('button')].map((b) => b.textContent ?? '');
    expect(labels.some((l) => /consent/i.test(l))).toBe(false);
  });

  it('offers the three consents separately once a person is confirmed', () => {
    const node = panel({ regions: [detected({ action: 'confirmed', confirmedBy: 'someone' })] });
    const labels = [...node.querySelectorAll('button')].map((b) => b.textContent ?? '');
    for (const scope of ['presence', 'naming', 'likeness']) {
      expect(labels.some((l) => l.includes(scope))).toBe(true);
    }
  });

  it('records a likeness consent and offers to withdraw it afterwards', () => {
    const calls: unknown[] = [];
    const confirmed = detected({ action: 'confirmed', confirmedBy: 'someone' });
    const node = panel({ regions: [confirmed], onConsent: (...a) => calls.push(a) });
    [...node.querySelectorAll('button')]
      .find((b) => b.textContent === 'Record likeness consent')
      ?.dispatchEvent(new Event('click'));
    expect(calls).toEqual([['aa'.repeat(32), 'likeness', 'granted']]);

    const shown = panel({
      regions: [detected({ action: 'confirmed', state: 'shown', masked: false })],
    });
    const labels = [...shown.querySelectorAll('button')].map((b) => b.textContent ?? '');
    expect(labels).toContain('Withdraw likeness');
  });

  it('draws a hidden person opaquely, never as a translucent veil over pixels', () => {
    const node = panel();
    const shape = node.querySelector('svg polygon');
    expect(shape?.getAttribute('class')).toBe('person-outline-hidden');
    expect(node.innerHTML).not.toContain('opacity');
  });

  it('states plainly that an undecided person is hidden', () => {
    expect(panel().textContent).toContain('Nobody has decided about this person');
  });

  it('carries the region key so an action names the region it came from', () => {
    const node = panel();
    const region = node.querySelector('.person-review-region') as HTMLElement;
    expect(region.dataset.regionKey).toBe('aa'.repeat(32));
    expect(region.dataset.state).toBe('unknown');
  });
});
