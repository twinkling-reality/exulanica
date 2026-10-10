import { describe, expect, it } from 'vitest';
import { rememberTownFurniture, townFurniture } from '../src/composition/town-furniture.js';

const bench = (identity: string) => ({
  identity, eastMm: 0, southMm: 0, facing: [1, 0] as const,
  parts: [{ alongMm: 0, leftMm: 0, bottomMm: 420, sizeAlongMm: 1800, sizeLeftMm: 450, heightMm: 60 }],
});

describe('the open town\'s street furniture', () => {
  it('is kept for the entry it was read for, and for no other', () => {
    expect(townFurniture('town-a')).toEqual([]);
    rememberTownFurniture('town-a', [bench('one')]);
    expect(townFurniture('town-a').map((item) => item.identity)).toEqual(['one']);
    expect(townFurniture('town-b')).toEqual([]);
    expect(townFurniture(null)).toEqual([]);
    expect(townFurniture(undefined)).toEqual([]);
  });

  it('gives way to the next town opened', () => {
    rememberTownFurniture('town-a', [bench('one')]);
    rememberTownFurniture('town-b', [bench('two'), bench('three')]);
    expect(townFurniture('town-a')).toEqual([]);
    expect(townFurniture('town-b').map((item) => item.identity)).toEqual(['two', 'three']);
  });
});
