import { describe, expect, it } from 'vitest';
import {
  DATA_VIEW_STYLE,
  DATA_VIEW_STYLE_V1,
  DATA_VIEW_STYLE_V2,
  dataViewKindColour,
  dataViewRgb,
  dataViewStyle,
  dataViewStyleName,
} from '../src/data-view-style.js';

const copy = (): Record<string, any> => JSON.parse(JSON.stringify(DATA_VIEW_STYLE_V1));

/** Every city grammar version 2 record kind that states an extent, from lane 20's tile document. */
const V2_SPATIAL_KINDS = [
  'city.block', 'city.crossing', 'city.curb_edge', 'city.district', 'city.entrance', 'city.facade',
  'city.ground_bay', 'city.junction', 'city.lane', 'city.lane_connection', 'city.massing', 'city.parcel',
  'city.parking_space', 'city.premises', 'city.road_marking', 'city.rooftop_object', 'city.street',
  'city.street_furniture', 'city.street_node', 'city.street_segment', 'city.street_tree', 'city.terrain',
  'city.vitrine',
];
const copyV2 = (): Record<string, any> => JSON.parse(JSON.stringify(DATA_VIEW_STYLE_V2));

describe('data view style descriptor', () => {
  it('validates version 2, the current look, and keeps every version 1 value', () => {
    expect(DATA_VIEW_STYLE).toEqual(DATA_VIEW_STYLE_V2);
    expect(dataViewStyle(copyV2())).toEqual(DATA_VIEW_STYLE);
    expect(dataViewStyleName(DATA_VIEW_STYLE)).toBe('exulanica.data-view@2');
    const v1 = dataViewStyle(copy());
    for (const [key, colour] of Object.entries(v1.palette.kind)) expect(DATA_VIEW_STYLE.palette.kind[key]).toBe(colour);
    expect({ ...DATA_VIEW_STYLE, version: 1, palette: undefined }).toEqual({ ...v1, palette: undefined });
    for (const kind of V2_SPATIAL_KINDS) expect(dataViewKindColour(DATA_VIEW_STYLE, kind)).toMatch(/^#[0-9a-f]{6}$/);
    for (const kind of ['city.junction_approach', 'city.signal', 'city.tile', 'window', 'toString']) {
      expect(dataViewKindColour(DATA_VIEW_STYLE, kind)).toBeUndefined();
    }
    expect(dataViewKindColour(v1, 'city.street')).toBeUndefined();
  });

  it('reads the version 2 kind palette as declared data, and refuses what is not a kind', () => {
    const declared = copyV2();
    declared['palette']['kind']['city.bus_shelter'] = '#123456';
    expect(dataViewKindColour(dataViewStyle(declared), 'city.bus_shelter')).toBe('#123456');
    const cases: [(value: Record<string, any>) => void, RegExp][] = [
      [value => { value['palette']['kind']['window'] = '#ffffff'; }, /palette.kind.window is not a known key/],
      [value => { value['palette']['kind']['city.tile'] = '#ffffff'; }, /palette.kind.city.tile is not a known key/],
      [value => { value['palette']['kind']['city.Street'] = '#ffffff'; }, /is not a known key/],
      [value => { delete value['palette']['kind']['geometry-group']; }, /geometry-group is missing/],
      [value => { value['palette']['kind']['city.street'] = '#FFFFFF'; }, /city.street is not a lowercase/],
      [value => { for (let i = 0; i < 130; i += 1) value['palette']['kind'][`city.k${i}`] = '#000000'; }, /more than 128 kinds/],
      [value => { value['version'] = 3; }, /style.version/],
    ];
    for (const [change, message] of cases) {
      const value = copyV2();
      change(value);
      expect(() => dataViewStyle(value)).toThrow(message);
    }
    const v1 = copy();
    v1['palette']['kind']['city.street'] = '#ffffff';
    expect(() => dataViewStyle(v1)).toThrow('palette.kind.city.street is not a known key');
  });

  it('validates version 1 into one frozen, JSON-shaped look with a name for display records', () => {
    const v1 = dataViewStyle(copy());
    expect(v1).toEqual(DATA_VIEW_STYLE_V1);
    expect(Object.isFrozen(v1.palette.origin)).toBe(true);
    expect(dataViewStyleName(v1)).toBe('exulanica.data-view@1');
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
