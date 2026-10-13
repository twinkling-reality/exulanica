import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { at, passivePatch, readHeightfieldContact, sweep, HEIGHTFIELD_PERSON_POLICY } from '../src/heightfield-contact.js';
import { pointContact, readHeightfieldGeometry } from '../src/heightfield-geometry.js';

const digest = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
function terrain(axis = [-2000, 0, 2000], height: (x: number, z: number) => number = () => 1000) {
  return { profile: 'exulanica.heightfield-geometry/v1', component_id: 'terrain:tests', frame: 'region-local-east-up-south-mm', east_mm: axis, south_mm: axis, height_mm: axis.flatMap(z => axis.map(x => height(x, z))), diagonal: 'a-c-b,b-c-d', provenance: { kind: 'generated', source_sha256: 'c'.repeat(64), generator_id: 'fixture:tests', generator_version: 1, input_sha256: 'd'.repeat(64) } };
}
function setup(raw = terrain(), obstructions: unknown[] = []) {
  const g = readHeightfieldGeometry(raw, digest);
  const document = { profile: 'exulanica.heightfield-contact/v1', geometry_sha256: g.sha256, component_id: g.data.component_id, policy: HEIGHTFIELD_PERSON_POLICY, obstructions };
  return { geometry: g, contact: readHeightfieldContact(document, g, digest), document };
}
const box = (bounds_mm: number[], obstruction_id = 'solid:test') => ({ kind: 'aabb', obstruction_id, bounds_mm });
const smallAxis = Array.from({ length: 9 }, (_, i) => -1000 + i * 250);

describe('shared Python and BigInt vectors', () => {
  it('matches every retained cross-language point, sweep and passive patch', () => {
    const fixture = JSON.parse(readFileSync('../tests/fixtures/heightfield/conformance.json', 'utf8'));
    expect(fixture.profile).toBe('exulanica.heightfield-conformance/v1');
    expect(fixture.cases.length).toBeGreaterThan(0);
    for (const row of fixture.cases) {
    const g = readHeightfieldGeometry(row.geometry, digest, row.geometry_sha256);
    const c = readHeightfieldContact(row.contact, g, digest, row.contact_sha256);
    for (const p of row.points) expect(pointContact(g, p.position)).toEqual(p.expected);
    for (const q of row.sweeps) expect(sweep(c, q.start, q.end)).toEqual(q.expected);
    for (const q of row.patches) expect(passivePatch(c, q.position, q.half_width_mm, q.height_mm), row.name).toEqual(q.expected);
    }
  });
});
describe('independent conservative footprint and sweep cases', () => {
  it('finds a wet corner sliver although centre and four radius probes are dry', () => {
    const { geometry, contact } = setup(terrain(smallAxis, (x, z) => x === 250 && z === 250 ? 0 : 1000));
    for (const p of ([[0, 0], [340, 0], [-340, 0], [0, 340], [0, -340]] as const)) expect(pointContact(geometry, p)?.height_mm).toEqual({ numerator: '1000', denominator: '1' });
    expect(at(contact, [0, 0])).toMatchObject({ status: 'blocked', reason: 'wet', height_range_mm: [{ numerator: '0', denominator: '1' }, { numerator: '1000', denominator: '1' }] });
  });
  it('finds a steep corner sliver although all five sampled points are flat', () => {
    const { contact } = setup(terrain(smallAxis, (x, z) => x === 250 && z === 250 ? 1500 : 1000));
    expect(at(contact, [0, 0]).reason).toBe('steep');
    expect(passivePatch(contact, [0, 0], 340, 50).reason).toBe('not_flat');
  });
  it('finds a mid-route diagonal barrier between two fully clear endpoints', () => {
    const { contact } = setup(terrain(), [box([-20, 1200, -20, 20, 1250, 20])]);
    expect(at(contact, [-600, -600]).status).toBe('clear');
    expect(at(contact, [600, 600]).status).toBe('clear');
    expect(sweep(contact, [-600, -600], [600, 600]).reason).toBe('obstructed');
  });
  it('covers square corners at the domain edge and leaves its immutable source unchanged', () => {
    const { contact } = setup(); const before = contact.document();
    expect(at(contact, [1660, 1660]).status).toBe('clear');
    expect(at(contact, [1661, 1660])).toMatchObject({ reason: 'outside_domain', contact: null, triangles: 0 });
    expect(sweep(contact, [-1500, 0], [1500, 0]).reason).toBe('segment_limit');
    expect(contact.document()).toEqual(before);
  });
  it('blocks horizontal and vertical tangency, including finite zero-volume proxies', () => {
    expect(at(setup(terrain(), [box([340, 1000, 0, 340, 1000, 0])]).contact, [0, 0]).reason).toBe('obstructed');
    expect(at(setup(terrain(), [box([0, 2800, 0, 0, 2800, 0])]).contact, [0, 0]).reason).toBe('obstructed');
    expect(at(setup(terrain(), [box([0, 2801, 0, 0, 2801, 0])]).contact, [0, 0]).status).toBe('clear');
    expect(at(setup(terrain(), [box([0, 1000, 1000, 0, 2000, 1100])]).contact, [0, 0]).status).toBe('clear');
  });
  it('includes zero-area steep boundary contact without rejecting a flat passive patch', () => {
    const raw = terrain([-1000, 0, 1000], x => x <= 0 ? 1000 : 2000), { contact } = setup(raw);
    expect(at(contact, [-340, 0]).reason).toBe('steep');
    expect(passivePatch(contact, [-340, 0], 340, 100).status).toBe('clear');
    expect(passivePatch(contact, [-339, 0], 340, 100).reason).toBe('not_flat');
  });
  it('treats work refusal and unknown occupancy as unavailable with preflight priority', () => {
    const axis = Array.from({ length: 81 }, (_, i) => -10000 + i * 250);
    const { contact } = setup(terrain(axis), [{ kind: 'unknown', obstruction_id: 'solid:unknown' }]);
    expect(passivePatch(contact, [0, 0], 8000, 100)).toEqual({ status: 'unavailable', reason: 'work_limit', contact: null, height_range_mm: null, triangles: 0 });
    expect(at(contact, [0, 0]).reason).toBe('unknown_obstruction');
    expect(at(contact, [10000, 0]).reason).toBe('outside_domain');
    expect(sweep(contact, [10000, 0], [13000, 0]).reason).toBe('segment_limit');
    const crowded = setup(terrain(axis), Array.from({ length: 512 }, (_, i) => box([0, 9000, 0, 0, 9000, 0], `solid:${String(i).padStart(3, '0')}`))).contact;
    expect(passivePatch(crowded, [0, 0], 4000, 100).reason).toBe('work_limit');
  });
  it('accepts the exact rational slope limit and refuses one millimetre more rise', () => {
    const axis = [0, 1250, 2500];
    const allowed = setup(terrain(axis, x => 1000 + x * 781 / 1250)).contact;
    const steep = setup(terrain(axis, x => 1000 + x * 782 / 1250)).contact;
    expect(at(allowed, [1250, 1250]).status).toBe('clear');
    expect(at(steep, [1250, 1250]).reason).toBe('steep');
  });
  it('keeps squared slope authority exact beyond the safe Number integer range', () => {
    const raw = terrain([0, 1999]); raw.south_mm = [0, 1997];
    raw.height_mm = [1000, 2248, 1001, 2249];
    const { geometry, contact } = setup(raw);
    expect(pointContact(geometry, [1000, 1000])?.normal).toEqual(['-2492256', '3992003', '-1999']);
    expect(2492256n ** 2n * 10000n ** 2n).toBeGreaterThan(BigInt(Number.MAX_SAFE_INTEGER));
    expect(at(contact, [1000, 1000]).status).toBe('clear');
    raw.height_mm = [1000, 2249, 1001, 2250];
    expect(at(setup(raw).contact, [1000, 1000]).reason).toBe('steep');
  });
  it('uses the whole swept floor envelope for conservative overhead clearance', () => {
    const raw = terrain([-2000, 0, 2000], x => 2000 + x / 2);
    const { contact } = setup(raw, [box([300, 2020, -20, 310, 2030, 20])]);
    // The box is below its local floor, but overlaps the whole footprint's conservative floor range.
    expect(at(contact, [0, 0])).toMatchObject({ reason: 'obstructed', height_range_mm: [{ numerator: '1830', denominator: '1' }, { numerator: '2170', denominator: '1' }] });
  });
  it('covers the uphill-centred body above its lower neighbouring terrain piece', () => {
    const raw = terrain([0, 1000, 2000], x => 1000 + x / 2);
    const { contact } = setup(raw, [box([950, 3350, 990, 960, 3360, 1010])]);
    // The centre's floor is 1625 and head is 3425. The box reaches that body even though
    // its own terrain triangle ends at floor 1500 (a piece-local head envelope ends at 3300).
    expect(at(contact, [1250, 1000])).toMatchObject({
      reason: 'obstructed', contact: { height_mm: { numerator: '1625', denominator: '1' } },
      height_range_mm: [{ numerator: '1455', denominator: '1' }, { numerator: '1795', denominator: '1' }],
    });
  });
  it('does not accept edited source identity, unknown fields or invalid proxies', () => {
    const { geometry, document } = setup();
    for (const change of [
      { geometry_sha256: 'e'.repeat(64) }, { component_id: 'terrain:other' }, { extra: 1 },
      { obstructions: [box([1, 0, 0, 0, 1, 1])] },
      { obstructions: [box([0, 0, 0, 1, 1, 1], 'solid:z'), box([0, 0, 0, 1, 1, 1], 'solid:a')] },
      { obstructions: [box([0, 0, 0, 1, 1, 1]), box([0, 0, 0, 1, 1, 1])] },
    ]) expect(() => readHeightfieldContact({ ...document, ...change }, geometry, digest)).toThrow();
    const { contact } = setup();
    expect(() => passivePatch(contact, [0, 0], 0, 100)).toThrow();
    expect(() => passivePatch(contact, [0, 0], 1, 0)).toThrow();
    expect(() => at(contact, [true, 0] as any)).toThrow();
  });
});
