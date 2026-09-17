import { describe, expect, it } from 'vitest';
import {
  DATA_VIEW_STYLE,
  DATA_VIEW_STYLE_V1,
  dataViewRgb,
  dataViewStyle,
  dataViewStyleName,
} from '../src/data-view-style.js';

const copy = (): Record<string, any> => JSON.parse(JSON.stringify(DATA_VIEW_STYLE_V1));

describe('data view style descriptor', () => {
  it('validates version 1 into one frozen, JSON-shaped look with a name for display records', () => {
    expect(DATA_VIEW_STYLE).toEqual(DATA_VIEW_STYLE_V1);
    expect(dataViewStyle(JSON.parse(JSON.stringify(DATA_VIEW_STYLE_V1)))).toEqual(DATA_VIEW_STYLE);
    expect(Object.isFrozen(DATA_VIEW_STYLE.palette.origin)).toBe(true);
    expect(dataViewStyleName(DATA_VIEW_STYLE)).toBe('exulanica.data-view@1');
    expect(Object.keys(DATA_VIEW_STYLE.palette.origin)).toEqual(['inferred', 'authored', 'generated', 'external']);
  });

  it('refuses unknown keys at every level', () => {
    for (const path of [[], ['points'], ['points', 'glow'], ['points', 'thinning'], ['palette', 'origin'], ['palette', 'kind'], ['tags']]) {
      const value = copy();
      let target = value;
      for (const key of path) target = target[key];
      target['shimmer'] = 1;
      expect(() => dataViewStyle(value)).toThrow(/shimmer is not a known key/);
    }
    const guessed = copy();
    guessed['palette']['kind']['window'] = '#ffffff';
    expect(() => dataViewStyle(guessed)).toThrow('palette.kind.window is not a known key');
  });

  it('refuses missing keys, out-of-range values, wrong types and malformed colours', () => {
    const cases: [(value: Record<string, any>) => void, RegExp][] = [
      [value => { delete value['points']['sizeMetres']; }, /sizeMetres is missing/],
      [value => { delete value['palette']['origin']['external']; }, /external is missing/],
      [value => { value['points']['intensity'] = 1.5; }, /intensity is not a number from 0 to 1/],
      [value => { value['points']['thinning']['maxGain'] = 0.5; }, /thinning.maxGain/],
      [value => { value['ground']['rise'] = 0; }, /ground.rise/],
      [value => { value['points']['maxPixels'] = 0.5; }, /maxPixels/],
      [value => { value['points']['minPixels'] = 9; value['points']['maxPixels'] = 8; }, /maxPixels is below minPixels/],
      [value => { value['points']['depthFade']['endMetres'] = 10; }, /endMetres is not beyond startMetres/],
      [value => { value['points']['sizeMetres'] = Number.NaN; }, /sizeMetres/],
      [value => { value['points']['sizeMetres'] = '0.3'; }, /sizeMetres/],
      [value => { value['tags']['maxCount'] = 2.5; }, /maxCount is not an integer/],
      [value => { value['boxes']['colour'] = '#FFD79A'; }, /lowercase #rrggbb/],
      [value => { value['ground']['colour'] = 'black'; }, /lowercase #rrggbb/],
      [value => { value['tags']['fontFamily'] = 'x; background:url(y)'; }, /fontFamily is not supported text/],
      [value => { value['id'] = 'another.look'; }, /style.id/],
      [value => { value['version'] = 0; }, /style.version/],
      [value => { value['dashes'] = []; }, /style.dashes is not an object/],
    ];
    for (const [change, message] of cases) {
      const value = copy();
      change(value);
      expect(() => dataViewStyle(value)).toThrow(message);
    }
    expect(() => dataViewStyle(null)).toThrow(/style is not an object/);
  });

  it('turns a validated colour into display components and nothing else', () => {
    expect(dataViewRgb('#ff8000')).toEqual([1, 128 / 255, 0]);
    expect(() => dataViewRgb('orange')).toThrow();
  });
});
