import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { seatingLayout } from '../src/composition/seating-layout.js';
import { parseAsset, type AlternateVersion, type ReviewedAsset } from '../src/world-objects-api.js';
import type { SocietyPlaces } from '../src/society-api.js';

/*
 * The registry rows the page reads carry each kind's use as the server serves it. These tests
 * parse the use the server wrote into the seating fixture (tests/test_society_seating_fixture.py
 * writes it from the route's own derivation) and build the crowd's layout from what the page holds.
 */

const FIXTURE = JSON.parse(readFileSync(
  new URL('../../atlas-react/test/fixtures/society-seating.json', import.meta.url), 'utf8',
)) as { cases: { asset_key: string; use: unknown }[] };

const row = (assetKey: string, use: unknown) => ({
  asset_key: assetKey, title: assetKey, summary: '', media_type: 'model/gltf-binary',
  content_sha256: 'c'.repeat(64), byte_size: 1, licence_id: 'CC0-1.0', licence_sha256: 'd'.repeat(64),
  availability: 'available', placeable: true, use,
});

describe('a served use', () => {
  it('parses as the server derived it, seats and all', () => {
    const bench = FIXTURE.cases.find((item) => item.asset_key === 'cc0.bench')!;
    const asset = parseAsset(row('cc0.bench', bench.use));
    const wire = bench.use as { affordance: string; places: { position_mm: number[]; faces: string; seat: { position_mm: number[]; faces: string } }[] };
    expect(asset.use?.affordance).toBe(wire.affordance);
    expect(asset.use?.places?.map((place) => [place.positionMm, place.faces, place.seat?.positionMm, place.seat?.faces]))
      .toEqual(wire.places.map((place) => [place.position_mm, place.faces, place.seat.position_mm, place.seat.faces]));
  });

  it('reads a marker as having no places, an unstated asset as having no use, and a version row as silent', () => {
    expect(parseAsset(row('cc0.marker-plate', { affordance: 'rest', places: null })).use).toEqual({ affordance: 'rest', places: null });
    expect(parseAsset(row('makehuman.people.feminine.base.v3', null)).use).toBeNull();
    const { use: _use, ...embedded } = row('cc0.bench', null);
    expect('use' in parseAsset(embedded)).toBe(false);
  });

  it('refuses a side the part frame does not have, or a seat point of the wrong size', () => {
    const bench = FIXTURE.cases.find((item) => item.asset_key === 'cc0.bench')!;
    const wrongSide = JSON.parse(JSON.stringify(bench.use));
    wrongSide.places[0].faces = 'up';
    expect(() => parseAsset(row('cc0.bench', wrongSide))).toThrow();
    const flatSeat = JSON.parse(JSON.stringify(bench.use));
    flatSeat.places[0].seat.position_mm = [0, 20];
    expect(() => parseAsset(row('cc0.bench', flatSeat))).toThrow();
  });
});

describe('the seating layout', () => {
  const bench = FIXTURE.cases.find((item) => item.asset_key === 'cc0.bench')!;
  const assets: ReviewedAsset[] = [
    parseAsset(row('cc0.bench', bench.use)),
    // A row read embedded in a version carries no use at all.
    parseAsset((({ use: _use, ...embedded }) => embedded)(row('cc0.lamp-post', null))),
  ];
  const object = (objectId: string, removed = false) => ({
    objectId, removed, asset: assets[0]!,
    transform: { coordinateSpace: 'region_local', coordinateUnit: 'millimetre', xMm: 1000, yMm: 0, zMm: -2000, yawMicroradians: 7, scaleMilli: 1000 },
  });
  const version = { objects: [object('kept'), object('gone', true)] } as unknown as AlternateVersion;
  const places = { targets: [{ targetId: 'authored:v:kept:rest', objectId: 'kept' }, { targetId: 'district:x:visit', objectId: null }] } as unknown as SocietyPlaces;

  it('holds each kind that has a use, every object still in the version, and each target\'s object', () => {
    const layout = seatingLayout(assets, version, places)!;
    expect([...layout.uses.keys()]).toEqual(['cc0.bench']);
    expect(layout.objects).toEqual([{ objectId: 'kept', assetKey: 'cc0.bench', xMm: 1000, yMm: 0, zMm: -2000, yawMicroradians: 7, scaleMilli: 1000 }]);
    expect([...layout.targets.entries()]).toEqual([['authored:v:kept:rest', 'kept'], ['district:x:visit', null]]);
  });

  it('is absent until both the version and the places are read', () => {
    expect(seatingLayout(assets, null, places)).toBeNull();
    expect(seatingLayout(assets, version, null)).toBeNull();
  });
});
