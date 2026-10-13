import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { canonicalJson } from '../src/style-pack.js';
import { pointContact, readHeightfieldGeometry } from '../src/heightfield-geometry.js';

const digest = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
const geometry = (east = [-1000, -250, 500, 2000], south = [-750, 0, 1250]) => ({
  profile: 'exulanica.heightfield-geometry/v1', component_id: 'terrain:inclined', frame: 'region-local-east-up-south-mm',
  east_mm: east, south_mm: south, height_mm: south.flatMap(z => east.map(x => 500 + (x + 1000) / 3 + (z + 750) / 5)),
  diagonal: 'a-c-b,b-c-d', provenance: { kind: 'authored', source_sha256: 'a'.repeat(64), generator_id: 'fixture:inclined', generator_version: 1, input_sha256: 'b'.repeat(64) },
});
function reduced(n: number, d: number) {
  let a = Math.abs(n), b = d;
  while (b) { const r = a % b; a = b; b = r; }
  return { numerator: String(n / a), denominator: String(d / a) };
}
describe('immutable exact heightfield realization', () => {
  it('agrees with an independent affine oracle over nonuniform axes and signed positions', () => {
    const g = readHeightfieldGeometry(geometry(), digest);
    for (let east = -999; east < 2000; east += 83) for (let south = -749; south < 1250; south += 107) {
      const point = pointContact(g, [east, south]);
      expect(point?.height_mm).toEqual(reduced(7500 + 5 * (east + 1000) + 3 * (south + 750), 15));
      expect(point?.normal).toEqual(['-5', '15', '-3']);
    }
    expect(pointContact(g, [-1001, 0])).toBeNull();
    expect(pointContact(g, [0, 1251])).toBeNull();
  });
  it('selects numeric row/column/half order at vertices, shared axes and diagonals', () => {
    const axis = Array.from({ length: 13 }, (_, i) => i * 1000);
    const raw = geometry(axis, axis); raw.height_mm.fill(500);
    const g = readHeightfieldGeometry(raw, digest);
    expect(pointContact(g, [10000, 10000])?.triangle).toEqual([9, 9, 1]);
    expect(pointContact(g, [1000, 500])?.triangle).toEqual([0, 0, 1]);
    expect(pointContact(g, [500, 500])?.triangle).toEqual([0, 0, 0]);
    expect(pointContact(g, [0, 0])?.triangle).toEqual([0, 0, 0]);
    expect(pointContact(g, [12000, 12000])?.triangle).toEqual([11, 11, 1]);
  });
  it('keeps canonical digest, immutable data and independent document exports', () => {
    const raw = geometry(), sha = digest(new TextEncoder().encode(canonicalJson(raw)));
    const g = readHeightfieldGeometry(raw, digest, sha);
    raw.height_mm[0] = 42;
    const copy = g.document(); (copy.height_mm as number[])[0] = 12;
    expect(g.data.height_mm[0]).toBe(500);
    expect(g.sha256).toBe(sha);
    expect(Object.isFrozen(g.data.height_mm)).toBe(true);
    expect(Object.isFrozen(g.data.provenance)).toBe(true);
    expect(() => readHeightfieldGeometry(raw, digest, sha)).toThrow('expected_sha256');
  });
  it.each([
    (raw: any) => { raw.extra = 1; },
    (raw: any) => { raw.provenance.extra = 1; },
    (raw: any) => { raw.height_mm[0] = true; },
    (raw: any) => { raw.height_mm[0] = 64001; },
    (raw: any) => { raw.height_mm.pop(); },
    (raw: any) => { raw.east_mm[1] = raw.east_mm[0]; },
    (raw: any) => { raw.east_mm[1] = raw.east_mm[0] + 249; },
    (raw: any) => { raw.east_mm[0] = -256001; },
    (raw: any) => { raw.south_mm = [0, 2001]; },
    (raw: any) => { raw.component_id = 'terrain/foreign'; },
    (raw: any) => { raw.provenance.generator_version = false; },
    (raw: any) => { raw.diagonal = 'a-b-d,a-d-c'; },
  ])('rejects malformed, unbounded or alternate topology input', mutate => {
    const raw = geometry(); mutate(raw); expect(() => readHeightfieldGeometry(raw, digest)).toThrow();
  });
  it('rejects invalid point types instead of converting them to numeric contact', () => {
    const g = readHeightfieldGeometry(geometry(), digest);
    for (const p of [[true, 0], [0.5, 0], [0, NaN], [512001, 0], [0, 0, 0]]) expect(() => pointContact(g, p as any)).toThrow();
  });
});
