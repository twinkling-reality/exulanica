import { describe, expect, it } from 'vitest';
import { onSiteSeatsChanged, rememberSiteSeats, siteSeats } from '../src/composition/site-furniture.js';

const seat = { objectId: 'fixture-a', triangles: [], normals: [], heightHintM: .225, maximumHeightM: .46, facing: 0 };
describe('attached site contact', () => {
  it('is exact entry/version scoped and withdrawn on replacement/disposal', () => {
    let changes = 0;
    const stop = onSiteSeatsChanged(() => changes++);
    const old = rememberSiteSeats('entry-a', 'version-a', [seat]);
    expect(siteSeats('entry-a', 'version-a')).toEqual([seat]);
    expect(siteSeats('entry-b', 'version-a')).toEqual([]);
    expect(siteSeats('entry-a', 'version-b')).toEqual([]);
    const next = rememberSiteSeats('entry-a', 'version-a', [{ ...seat, triangles: [1] }]);
    old();
    expect(siteSeats('entry-a', 'version-a')[0]!.triangles).toEqual([1]);
    next(); next();
    expect(siteSeats('entry-a', 'version-a')).toEqual([]);
    expect(changes).toBe(3);
    stop(); rememberSiteSeats('entry-b', 'version-b', [] )();
    expect(changes).toBe(3);
  });
});
