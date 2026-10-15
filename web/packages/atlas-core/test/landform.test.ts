import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { pointContact, readHeightfieldGeometry } from '../src/heightfield-geometry.js';
import {
  LAND_CHUNK_MM, LAND_SURFACE_GROUND, LandformError, NearLand, backdropMeshData, chunkHeightMm, landBackdropColour, landBandAt, landBandWeight,
  landChunkGeometry, landChunkLocal, landNoiseShift, readLandBackdrop, readLandChunk, readLandSurfaces, valueNoise,
} from '../src/landform.js';

const digest = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
const fixture = JSON.parse(readFileSync('../tests/fixtures/landform/conformance.json', 'utf8'));
const rational = (value: { numerator: string; denominator: string }) => Number(value.numerator) / Number(value.denominator);

describe('land chunks, held to the server realizer', () => {
  const chunk = readLandChunk(fixture.chunk, digest, fixture.chunk_sha256);

  it('reads the chunk the server made, by its digest', () => {
    expect(fixture.profile).toBe('exulanica.landform-conformance/v1');
    expect([chunk.chunkX, chunk.chunkY]).toEqual([-1, -1]);
    expect(() => readLandChunk(fixture.chunk, digest, '0'.repeat(64))).toThrow(LandformError);
    expect(() => readLandChunk({ ...fixture.chunk, cell_mm: 2000 }, digest)).toThrow(LandformError);
    expect(() => readLandChunk({ ...fixture.chunk, extra: 1 }, digest)).toThrow(LandformError);
    const tooHigh = { ...fixture.chunk, height_mm: [64_001, ...fixture.chunk.height_mm.slice(1)] };
    expect(() => readLandChunk(tooHigh, digest)).toThrow(LandformError);
  });

  it('gives the server exact height, within float precision, at every vector point', () => {
    const near = new NearLand([chunk]);
    expect(fixture.points.length).toBeGreaterThan(5);
    for (const point of fixture.points) {
      const expected = rational(point.height_mm);
      expect(chunkHeightMm(chunk, point.east_mm, point.north_mm)).toBeCloseTo(expected, 6);
      expect(near.groundHeightMm(point.east_mm, point.north_mm)).toBeCloseTo(expected, 6);
    }
    expect(near.groundHeightMm(10, 10)).toBeNull();
  });

  it('is the exact heightfield the server converts it to, so contact agrees with drawing', () => {
    const geometry = readHeightfieldGeometry(landChunkGeometry(chunk), digest);
    for (const point of fixture.points) {
      const contact = pointContact(geometry, landChunkLocal(chunk, point.east_mm, point.north_mm));
      expect(contact?.height_mm, `${point.east_mm},${point.north_mm}`).toEqual(point.height_mm);
    }
  });
});

describe('the backdrop', () => {
  const backdrop = readLandBackdrop(fixture.backdrop, digest, fixture.backdrop_sha256);
  const chunk = readLandChunk(fixture.chunk, digest);

  it('meets the near land on its edge', () => {
    const [x0, y0] = backdrop.nearMm;
    const shared = backdrop.xMm.filter((x) => x >= x0 && x <= x0 + LAND_CHUNK_MM);
    expect(shared.length).toBeGreaterThan(4);
    for (const x of shared) {
      const i = backdrop.xMm.indexOf(x), j = backdrop.yMm.indexOf(y0);
      expect(backdrop.heightMm[j * backdrop.xMm.length + i]).toBe(chunkHeightMm(chunk, x, y0));
    }
  });

  it('is drawn in blocks that face up, its samples under the near land sunk below it', () => {
    const blocks = backdropMeshData(backdrop, { blocks: 4, sinkMm: 3000 });
    expect(blocks.length).toBe(16);
    let sunk = 0;
    const [x0, y0, x1, y1] = backdrop.nearMm;
    for (const { positions, indices } of blocks) {
      expect(indices.length % 3).toBe(0);
      for (let t = 0; t < indices.length; t += 3) {
        const [a, b, c] = [indices[t]!, indices[t + 1]!, indices[t + 2]!].map((k) => [positions[k * 3]!, positions[k * 3 + 1]!, positions[k * 3 + 2]!]);
        // Upward facing: the triangle's normal (b - a) x (c - a) points up (+y).
        const ux = b![0]! - a![0]!, uz = b![2]! - a![2]!, vx = c![0]! - a![0]!, vz = c![2]! - a![2]!;
        expect(uz * vx - ux * vz).toBeGreaterThan(0);
      }
      for (let k = 0; k < positions.length; k += 3) {
        const x = positions[k]! * 1000, y = -positions[k + 2]! * 1000;
        if (x > x0 && x < x1 && y > y0 && y < y1) sunk += 1;
      }
    }
    expect(sunk).toBeGreaterThan(0);
  });

  it('reads its water and refuses a backdrop that does not rise along its axes', () => {
    // The fixture's only water is its cascade.
    expect(new Set(backdrop.water.map((body) => body.kind))).toEqual(new Set(['pool', 'fall']));
    const reversed = { ...fixture.backdrop, x_mm: [...fixture.backdrop.x_mm].reverse() };
    expect(() => readLandBackdrop(reversed, digest)).toThrow(LandformError);
    const sea = { ...fixture.backdrop, water: [{ id: 'sea', kind: 'sea', level_mm: 0, side: 'south' }] };
    expect(readLandBackdrop(sea, digest).water).toEqual([{ id: 'sea', kind: 'sea', levelMm: 0, side: 'south' }]);
  });
  it("reads a cascade's pools and the falls between them, and refuses a fall that does not fall", () => {
    const pools = backdrop.water.filter((body) => body.kind === 'pool');
    const falls = backdrop.water.flatMap((body) => (body.kind === 'fall' ? [body] : []));
    expect(pools.length).toBeGreaterThan(1);
    expect(falls).toHaveLength(pools.length - 1);
    for (const [i, fall] of falls.entries()) {
      expect([fall.levelMm, fall.bottomMm, fall.side]).toEqual([pools[i]!.levelMm, pools[i + 1]!.levelMm, 'south']);
      expect(fall.rectMm[1]).toBe(fall.rectMm[3]);
    }
    const raw = JSON.parse(JSON.stringify(fixture.backdrop)) as { water: Record<string, unknown>[] };
    const fall = raw.water.find((body) => body['kind'] === 'fall')!;
    for (const [change, where] of [
      [{ bottom_mm: fall['level_mm'] }, 'bottom_mm'],
      [{ side: 'south_west' }, 'side'],
      [{ rect_mm: [0, 0, 1000, 1000] }, 'rect_mm'],
      [{ kind: 'stream' }, 'kind'],
    ] as const) {
      const broken = { ...raw, water: raw.water.map((body) => (body === fall ? { ...body, ...change } : body)) };
      expect(() => readLandBackdrop(broken, digest)).toThrow(where);
    }
  });
});

describe("the land's own surfaces", () => {
  // Relative to web/, where the suite runs: the catalog a deployment ships.
  const text = readFileSync('../assets/catalogs/landform/landform-surface.v1.json', 'utf8');
  const surfaces = readLandSurfaces(text);
  const band = (key: string) => surfaces.bands.find((one) => one.key === key)!;

  it('reads the shipped catalog: its bands, where each is worn, and its noise', () => {
    expect(surfaces.bands.map((one) => one.key)).toEqual(['sand', 'wooded', 'planted', 'rock', 'scree']);
    expect(band('planted')).toMatchObject({ near: true, backdrop: false });
    expect(band('wooded')).toMatchObject({ near: false, backdrop: true });
    expect(band('sand').needsSea).toBe(true);
    // Linear albedos a lit scene reads as plausible ground: woods darkest, scree palest of the land.
    const luminance = (key: string) => 0.2126 * band(key).linear[0] + 0.7152 * band(key).linear[1] + 0.0722 * band(key).linear[2];
    expect(luminance('wooded')).toBeLessThan(0.1);
    expect(luminance('rock')).toBeGreaterThan(0.18);
    expect(luminance('rock')).toBeLessThan(0.3);
    expect(surfaces.noise.jitter).toBeGreaterThan(0);
  });

  it.each([
    ['another catalog', (d: Record<string, unknown>) => { d['catalog_id'] = 'exulanica.other'; }, 'is exulanica.landform-surface'],
    ['a key twice', (d: Record<string, unknown>) => { (d['entries'] as { key: string }[])[1]!.key = 'sand'; }, 'is a new key'],
    ['a slope that falls', (d: Record<string, unknown>) => { (d['entries'] as { slope_permille: number[] }[])[3]!.slope_permille = [900, 800]; }, 'rises'],
    ['a band worn nowhere', (d: Record<string, unknown>) => { (d['entries'] as { applies: string[] }[])[0]!.applies = []; }, 'names near or backdrop'],
  ])('refuses %s by name', (_name, change, words) => {
    const document = JSON.parse(text) as Record<string, unknown>;
    change(document);
    expect(() => readLandSurfaces(JSON.stringify(document))).toThrow(words);
  });

  it('wears rock only on steep faces, sand only by a sea, scree only high up', () => {
    const { jitter } = surfaces.noise;
    expect(landBandWeight(band('rock'), jitter, 200, 10_000, 0)).toBe(0);
    expect(landBandWeight(band('rock'), jitter, 1500, 10_000, 0)).toBe(1);
    const halfway = landBandWeight(band('rock'), jitter, 920, 10_000, 0);
    expect(halfway).toBeGreaterThan(0);
    expect(halfway).toBeLessThan(1);
    // The noise moves the threshold: the same slope is more rock or less where it shifts.
    expect(landBandWeight(band('rock'), jitter, 920, 10_000, -1)).toBeGreaterThan(halfway);
    expect(landBandWeight(band('rock'), jitter, 920, 10_000, 1)).toBeLessThan(halfway);
    expect(landBandWeight(band('sand'), jitter, 50, 800, 0)).toBe(1);
    expect(landBandWeight(band('sand'), jitter, 50, 9_000, 0)).toBe(0);
    expect(landBandWeight(band('scree'), jitter, 300, 400_000, 0)).toBe(1);
    expect(landBandWeight(band('scree'), jitter, 300, 50_000, 0)).toBe(0);
  });

  it('colours the backdrop by the bands over its ground: sand by the sea, darker woods on hillsides, its ground elsewhere', () => {
    const ground = [0.15, 0.22, 0.07] as const;
    const close = (actual: readonly number[], expected: readonly number[]) => actual.forEach((v, k) => expect(v).toBeCloseTo(expected[k]!, 6));
    expect(landBackdropColour(surfaces, ground, 30, 20_000, 0, true)).toEqual([...ground]);
    close(landBackdropColour(surfaces, ground, 30, 800, 0, true), band('sand').linear);
    expect(landBackdropColour(surfaces, ground, 30, 800, 0, false)).toEqual([...ground]);
    const wooded = landBackdropColour(surfaces, ground, 400, 90_000, 0, true);
    close(wooded, band('wooded').linear);
    expect(wooded[1]!).toBeLessThan(ground[1]);
    // Near-land bands are not the backdrop's: planting is worn on the near land alone.
    expect(landBackdropColour(surfaces, ground, 550, 5_000, 0, true)).toEqual([...ground]);
  });

  it('names the surface role the land is drawn in at a point: the last band worn there by half or more, else its ground', () => {
    expect(landBandAt(surfaces, 'near', 30, 20_000, 0, true)).toBe(LAND_SURFACE_GROUND);
    expect(landBandAt(surfaces, 'near', 30, 800, 0, true)).toBe('sand');
    expect(landBandAt(surfaces, 'near', 30, 800, 0, false)).toBe(LAND_SURFACE_GROUND);
    expect(landBandAt(surfaces, 'near', 550, 5_000, 0, true)).toBe('planted');
    expect(landBandAt(surfaces, 'near', 1500, 5_000, 0, true)).toBe('rock');
    // A steep face is planted and rock at once; rock comes later in the catalog, so rock wins as it does when drawn.
    expect(landBandWeight(band('planted'), surfaces.noise.jitter, 1500, 5_000, 0)).toBe(1);
    // The backdrop's bands are its own: woods on a hillside there, planting nowhere.
    expect(landBandAt(surfaces, 'backdrop', 400, 90_000, 0, true)).toBe('wooded');
    expect(landBandAt(surfaces, 'backdrop', 550, 5_000, 0, true)).toBe(LAND_SURFACE_GROUND);
    // The noise moves a threshold: a slope just under halfway into rock is rock where the noise shifts it down.
    const halfway = band('rock').slopePermille!.reduce((a, b) => a + b) / 2;
    expect(landBandAt(surfaces, 'near', halfway - 20, 5_000, 0, true)).toBe('planted');
    expect(landBandAt(surfaces, 'near', halfway - 20, 5_000, -1, true)).toBe('rock');
  });

  it('shares the noise the shader draws by: 0 to 1, the same at a point every time, and a shift from -1 to 1', () => {
    for (const [x, z] of [[0.3, 0.7], [12.5, -3.25], [-100.1, 44.9]] as const) {
      const v = valueNoise(x, z);
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
      expect(valueNoise(x, z)).toBe(v);
      const shift = landNoiseShift(surfaces.noise, x * 1000, z * 1000);
      expect(Math.abs(shift)).toBeLessThanOrEqual(1);
    }
    // At whole cells the noise is the cell's hash: fract(sin(127.1 i + 311.7 j) * 43758.5453), as exuLandHash states it.
    const hash = (i: number, j: number) => { const v = Math.sin(i * 127.1 + j * 311.7) * 43758.5453; return v - Math.floor(v); };
    expect(valueNoise(3, 5)).toBeCloseTo(hash(3, 5), 12);
  });
});
