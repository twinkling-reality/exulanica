import { describe, expect, it } from 'vitest';
import {
  DEFAULT_REPRESENTATION_INTENT,
  generatedDressing,
  generatedRecordSubject,
  generatedRecordSubjectV2,
  generatedTileFrameId,
  resolveRepresentation,
  validateRepresentationSubject,
  type GeneratedMaterialStatement,
  type GeneratedRecordEntry,
  type GeneratedRecordPayload,
  type GeneratedRecordRegistrationV2,
  type GeneratedTileReferenceV2,
} from '../src/representation.js';

/**
 * Hand-written records in the shape city grammar version 2 gives them on lane/city-vocabulary
 * (the frame, identity and extent rules in exulanica/grammar/grammars/city/common.py). The values
 * are written for this test; only fields the contract reads, plus a few of each record's own, are
 * present. A test over tests/fixtures/city-v2/ follows once that lane merges.
 */
const CITY = '7bd1a98c-5e69-5356-aa4f-d617c4611c55';
const MASSING = '5488228a-3210-54a7-9517-968a75f4624b';
const FACADE = 'aa54c270-fb04-506f-8f2e-0091574ea1ee';

const extent = (min: readonly number[], max: readonly number[]) => ({
  min_x_mm: min[0], min_y_mm: min[1], min_z_mm: min[2], max_x_mm: max[0], max_y_mm: max[1], max_z_mm: max[2],
});

const massing: GeneratedRecordPayload = {
  kind: 'city.massing', version: 2,
  fields: {
    identity: MASSING, building_ordinal: 0, parcel_identity: '536f9635-2e70-53a7-b8c9-05036e0b9dda',
    storeys: 4, roof_form: 'flat', extent: extent([41_050, 48_950, 135], [53_050, 62_950, 15_285]),
  },
};
const facade: GeneratedRecordPayload = {
  kind: 'city.facade', version: 2,
  fields: {
    identity: FACADE, building_identity: MASSING, edge_ordinal: 0, facade_ordinal: 0, tier_ordinal: 0,
    extent: extent([41_050, 48_950, 285], [52_250, 49_250, 13_785]),
  },
};
const wall: GeneratedRecordPayload = {
  kind: 'city.surface_material', version: 2,
  fields: {
    identity: '019e6b4b-65af-5e80-ba07-93b82797e566', surface_identity: FACADE, surface_kind: 'city.facade',
    role: 'wall', material: 'painted_render', texture_set_id: 'cc0.painted-render',
  },
};
const street: GeneratedRecordPayload = {
  kind: 'city.street', version: 1,
  fields: {
    identity: '95712b96-5d3a-5cdc-97c9-8dc30c772025', name: 'market_street', name_text: 'Market Street',
    street_ordinal: 0, segment_identities: ['3afeee23-e3b3-5cbb-8654-ed114473327c'],
    extent: extent([20_000, 35_250, -95], [100_000, 44_750, 0]),
  },
};
const approach: GeneratedRecordPayload = {
  kind: 'city.junction_approach', version: 1,
  fields: {
    identity: '6b1f2a55-0c1e-5f53-9a4e-0f3c2a1b7d90', approach_ordinal: 0,
    junction_identity: '0e7b4c2d-6a5f-5b1e-8c3d-2f9a1b0c4d5e', segment_identity: '3afeee23-e3b3-5cbb-8654-ed114473327c',
  },
};
const terrain: GeneratedRecordPayload = {
  kind: 'city.terrain', version: 2,
  fields: { identity: 'c4a2e9f0-1b3d-5e7f-8a9b-0c1d2e3f4a5b', tile_ordinal: 0, extent: extent([0, 0, -95], [128_000, 128_000, 0]) },
};

const tile: GeneratedTileReferenceV2 = {
  tileX: 0, tileY: 0, lod: 0, inputsDigest: 'c'.repeat(64),
  grammarId: 'city', grammarVersion: 2, frameName: 'city_local', subjectIdentity: CITY,
};

const drawn = (min: [number, number, number], max: [number, number, number],
  material: GeneratedMaterialStatement): GeneratedRecordEntry =>
  ({ state: 'drawn', extentMm: { min, max }, material });

const register = (record: GeneratedRecordPayload, entry: GeneratedRecordEntry,
  changes: Partial<GeneratedRecordRegistrationV2> = {}) => generatedRecordSubjectV2(tile, {
  record, membership: 'owned', entry, drawnSeparately: false, availability: 'available', ...changes,
});

const facadeDrawn = drawn([41_050, 48_950, 285], [52_250, 49_250, 13_785], { state: 'record', record: wall });

describe('generated street subject contract v2', () => {
  it('composes the frame from the stated frame name and city subject identity, and refuses either missing', () => {
    expect(generatedTileFrameId(tile)).toBe(`city_local:${CITY}`);
    expect(() => generatedTileFrameId({ ...tile, frameName: '' })).toThrow('city_local');
    expect(() => generatedTileFrameId({ ...tile, frameName: 'render-metres' })).toThrow('city_local');
    expect(() => generatedTileFrameId({ ...tile, subjectIdentity: '' })).toThrow('city subject identity');
    const { subjectIdentity: _dropped, ...noSubject } = tile;
    expect(() => generatedTileFrameId(noSubject as GeneratedTileReferenceV2)).toThrow('city subject identity');
    expect(() => generatedTileFrameId({ ...tile, grammarVersion: 1 })).toThrow('version 2 only');
    expect(() => generatedTileFrameId({ ...tile, inputsDigest: 'x' })).toThrow('inputs digest');
  });

  it('gives a drawn record one subject whose id is its kind and its own identity, with no ordinal suffix', () => {
    const { subject, reason } = register(facade, facadeDrawn);
    expect(reason).toBeNull();
    expect(subject).toMatchObject({
      subjectId: `generated:city.facade:${FACADE}`, subjectKind: 'object', origin: 'generated',
      frameId: `city_local:${CITY}`, sourceRefs: [tile.inputsDigest], rendered: true,
      points: 'mesh-surface-samples', sceneId: null, label: null,
      record: { kind: 'city.facade', version: 2, identity: FACADE, key: '', material: 'record' },
    });
    expect(subject!.bounds).toEqual({
      frameId: `city_local:${CITY}`, units: 'metres', origin: 'generated', basis: 'generated-extent',
      min: [41.05, 48.95, 0.285], max: [52.25, 49.25, 13.785],
    });
    expect(() => validateRepresentationSubject(subject!)).not.toThrow();
  });

  it('decides from the record: no extent means no spatial subject, whatever the kind', () => {
    const relation = register(approach, { state: 'not_in_projection' });
    expect(relation).toEqual({
      subject: null, reason: 'city.junction_approach states no extent, so it is a relation, not a spatial subject, and has no box or tag.',
    });
    const withExtent = { ...approach, fields: { ...approach.fields, extent: extent([0, 0, 0], [1, 1, 1]) } };
    expect(register(withExtent, drawn([0, 0, 0], [1, 1, 1], { state: 'none-exists' })).subject).not.toBeNull();
    const extentless = { ...massing, fields: { ...massing.fields } };
    delete (extentless.fields as Record<string, unknown>)['extent'];
    expect(register(extentless, { state: 'not_in_projection' }).subject).toBeNull();
    expect(() => register(extentless, drawn([41_050, 48_950, 135], [41_050, 48_950, 135], { state: 'none-exists' })))
      .toThrow('drawn but states no extent');
  });

  it('lists a dressing under the subject it dresses and never makes it a subject', () => {
    expect(register(wall, { state: 'not_in_projection' })).toEqual({
      subject: null, reason: 'A surface material is a dressing, not a spatial subject; it is listed under the subject it dresses.',
    });
    expect(generatedDressing(wall)).toEqual({
      identity: wall.fields['identity'], version: 2, role: 'wall', dressesSubjectId: `generated:city.facade:${FACADE}`,
    });
    expect(generatedDressing(wall).dressesSubjectId).toBe(register(facade, facadeDrawn).subject!.subjectId);
    expect(() => generatedDressing(facade)).toThrow('not a dressing');
    expect(() => generatedDressing({ ...wall, fields: { ...wall.fields, surface_identity: 'FACADE' } })).toThrow('dresses');
    const elsewhere = { ...wall, fields: { ...wall.fields, surface_identity: MASSING } };
    expect(() => register(facade, drawn([41_050, 48_950, 285], [52_250, 49_250, 13_785], { state: 'record', record: elsewhere })))
      .toThrow('dresses another record');
  });

  it('draws undressed exact geometry with a box and says no material dresses it', () => {
    const { subject } = register(terrain, drawn([0, 0, -95], [128_000, 128_000, 0], { state: 'none-exists' }));
    expect(subject!.record!.material).toBe('none-exists');
    expect(subject!.bounds).not.toBeNull();
    expect(subject!.unavailableReason).toContain('No material dresses this geometry');
    expect(() => register(terrain, { state: 'drawn', extentMm: { min: [0, 0, -95], max: [1, 1, 0] } } as unknown as GeneratedRecordEntry))
      .toThrow('either one material or its surfaces');
  });

  it('lists an owd/3 range\'s surfaces with their dressings, and refuses a material for another record or role', () => {
    const fascia = { ...wall, fields: { ...wall.fields, identity: '7a0c1d2e-3f40-5a6b-8c7d-9e0f1a2b3c4d', role: 'fascia' } };
    const extentMm = { min: [41_050, 48_950, 285], max: [52_250, 49_250, 13_785] } as const;
    const withSurfaces = (surfaces: unknown): GeneratedRecordEntry =>
      ({ state: 'drawn', extentMm, surfaces } as unknown as GeneratedRecordEntry);
    const { subject } = register(facade, withSurfaces([
      { role: 'wall', orientation: 'vertical', material: { state: 'record', record: wall } },
      { role: 'fascia', orientation: 'vertical', material: { state: 'record', record: fascia } },
      { role: 'trim', orientation: 'vertical', material: { state: 'none-exists' } },
    ]));
    expect(subject!.subjectId).toBe(`generated:city.facade:${FACADE}`);
    expect(subject!.record).toEqual({
      kind: 'city.facade', version: 2, identity: FACADE, key: '',
      surfaces: [
        { role: 'wall', orientation: 'vertical', material: 'record', dressingIdentity: wall.fields['identity'] },
        { role: 'fascia', orientation: 'vertical', material: 'record', dressingIdentity: fascia.fields['identity'] },
        { role: 'trim', orientation: 'vertical', material: 'none-exists', dressingIdentity: null },
      ],
    });
    expect(subject!.unavailableReason).toContain('No material dresses its trim surface');
    expect(() => validateRepresentationSubject(subject!)).not.toThrow();
    const elsewhere = { ...wall, fields: { ...wall.fields, surface_identity: MASSING } };
    expect(() => register(facade, withSurfaces([{ role: 'wall', orientation: 'vertical', material: { state: 'record', record: elsewhere } }])))
      .toThrow('dresses another record');
    expect(() => register(facade, withSurfaces([{ role: 'fascia', orientation: 'vertical', material: { state: 'record', record: wall } }])))
      .toThrow('its fascia surface cites a material for the wall role');
    expect(() => register(facade, withSurfaces([
      { role: 'wall', orientation: 'vertical', material: { state: 'none-exists' } },
      { role: 'wall', orientation: 'vertical', material: { state: 'none-exists' } },
    ]))).toThrow('each surface role once');
    expect(() => register(facade, withSurfaces([]))).toThrow('at least one');
    expect(() => register(facade, { ...withSurfaces([{ role: 'wall', orientation: 'vertical', material: { state: 'none-exists' } }]),
      material: { state: 'none-exists' } } as GeneratedRecordEntry)).toThrow('not both or neither');
    expect(() => register(facade, withSurfaces([{ role: 'Wall', orientation: 'vertical', material: { state: 'none-exists' } }])))
      .toThrow('names its role and orientation');
  });

  it('gives a halo record no subject, and refuses a halo entry for an owned record or the reverse', () => {
    expect(register(street, { state: 'halo' }, { membership: 'halo' })).toEqual({
      subject: null, reason: 'city.street is halo: context this tile carries and never draws, so it has no subject here.',
    });
    expect(() => register(street, { state: 'halo' })).toThrow('halo exactly when');
    expect(() => register(street, { state: 'not_in_projection' }, { membership: 'halo' })).toThrow('halo exactly when');
  });

  it('takes a label only from the record\'s own name text', () => {
    const owned = register(street, drawn([20_000, 35_250, -95], [100_000, 44_750, 0], { state: 'none-exists' }));
    expect(owned.subject!.label).toBe('Market Street');
    expect(register(massing, drawn([41_050, 48_950, 135], [53_050, 62_950, 15_285], { state: 'none-exists' })).subject!.label).toBeNull();
  });

  it('refuses a drawn extent outside the extent the record declares', () => {
    expect(() => register(massing, drawn([41_049, 48_950, 135], [53_050, 62_950, 15_285], { state: 'none-exists' })))
      .toThrow('outside the extent the record declares');
    expect(() => register(massing, drawn([41_050, 48_950, 135], [53_050, 62_950, 15_286], { state: 'none-exists' })))
      .toThrow('outside the extent the record declares');
    expect(() => register(massing, drawn([41_050, 48_950, 135.5], [53_050, 62_950, 15_285], { state: 'none-exists' })))
      .toThrow('integer millimetres');
    const unordered = { ...massing, fields: { ...massing.fields, extent: extent([2, 0, 0], [1, 1, 1]) } };
    expect(() => register(unordered, { state: 'not_in_projection' })).toThrow('not ordered');
    const extra = { ...massing, fields: { ...massing.fields, extent: { ...extent([0, 0, 0], [1, 1, 1]), w: 1 } } };
    expect(() => register(extra, { state: 'not_in_projection' })).toThrow('six integer millimetre corners');
  });

  it('keeps an undrawn spatial record listed with no box and no points, and says why', () => {
    const { subject } = register(terrain, { state: 'unavailable', needs: ['ground_coverage'] });
    expect(subject).toMatchObject({ rendered: false, points: null, bounds: null, compatibleBlend: false });
    expect(subject!.unavailableReason).toBe('The tile did not draw this record; it needs ground_coverage. No box and no points.');
    const resolved = resolveRepresentation({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1, boxes: true, ids: true }, subject!);
    expect(resolved).toMatchObject({ boxes: false, ids: false, geometryVisible: false });
    expect(() => register(terrain, { state: 'unavailable', needs: [] })).toThrow('names what it needs');
    expect(register(terrain, { state: 'not_admitted' }).subject!.unavailableReason).toContain('did not admit');
  });

  it('crossfades only a record drawn on its own, and rights win', () => {
    expect(register(facade, facadeDrawn).subject!.compatibleBlend).toBe(false);
    expect(register(facade, facadeDrawn, { drawnSeparately: true }).subject!.compatibleBlend).toBe(true);
    const withdrawn = register(facade, facadeDrawn, { availability: 'withdrawn' }).subject!;
    expect(withdrawn).toMatchObject({ dataAvailable: false, unavailableReason: 'Generated record is withdrawn.' });
    for (const pointMix of [0, 0.5, 1]) {
      expect(resolveRepresentation({ ...DEFAULT_REPRESENTATION_INTENT, pointMix, boxes: true, ids: true, labels: true }, withdrawn))
        .toMatchObject({ geometryVisible: false, boxes: false, ids: false, labels: false });
    }
  });

  it('refuses records it cannot read exactly', () => {
    expect(() => register({ ...massing, kind: 'city.tile' }, { state: 'not_in_projection' })).toThrow('not a city record kind');
    expect(() => register({ ...massing, kind: 'town.massing' }, { state: 'not_in_projection' })).toThrow('not a city record kind');
    expect(() => register({ ...massing, fields: { ...massing.fields, identity: MASSING.toUpperCase() } }, { state: 'not_in_projection' }))
      .toThrow('canonical lowercase UUID');
    expect(() => register(massing, { state: 'mystery' } as unknown as GeneratedRecordEntry)).toThrow('render batch entry');
  });

  it('leaves contract v1 as it was', () => {
    const v1 = { kind: 'city.massing', version: 1, fields: { building_identity: MASSING, parcel_ordinal: 3 } };
    const { subject } = generatedRecordSubject(
      { tileX: 0, tileY: 0, lod: 0, frameId: 'city.v1:tile:0:0:render-metres', inputsDigest: 'c'.repeat(64) },
      { record: v1, extentMm: null, drawnSeparately: false, availability: 'available' },
    );
    expect(subject!.subjectId).toBe(`generated:city.massing:${MASSING}:parcel_ordinal.3`);
    expect(subject!.record).toEqual({ kind: 'city.massing', version: 1, identity: MASSING, key: 'parcel_ordinal.3' });
  });
});
