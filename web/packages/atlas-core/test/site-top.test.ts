/**
 * A world on a volume's top: the graded top read as the server serves it, every bound and its
 * digest held, and its heights between and beyond lattice points the server's own, pinned by the
 * server-made `tests/fixtures/landform/site-top-conformance.json`.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { SiteTopError, readSiteTop, siteTopCellHeld, siteTopHeightMm } from '../src/site-top.js';

const digest = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');
const FIXTURE = JSON.parse(readFileSync('../tests/fixtures/landform/site-top-conformance.json', 'utf8')) as {
  site_top: Record<string, unknown>; sha256: string; points: [number, number, number][];
};
const top = (): Record<string, unknown> => structuredClone(FIXTURE.site_top);

const refusal = (read: () => unknown): string => {
  try {
    read();
  } catch (error) {
    expect(error).toBeInstanceOf(SiteTopError);
    return (error as SiteTopError).where;
  }
  throw new Error('read without a refusal');
};

describe('a graded top', () => {
  it('reads the server\'s top, held to its digest', () => {
    const read = readSiteTop(top(), digest, FIXTURE.sha256);
    expect(read.sha256).toBe(FIXTURE.sha256);
    expect([read.columns, read.rows]).toEqual([45, 45]);
    expect(read.heightMm.length).toBe(45 * 45);
    expect(read.originMm.every((v) => v % 1000 === 0)).toBe(true);
  });

  it('stands every point at the server\'s height, between and beyond its lattice', () => {
    const read = readSiteTop(top(), digest);
    expect(FIXTURE.points.length).toBeGreaterThan(100);
    for (const [east, north, height] of FIXTURE.points) expect(siteTopHeightMm(read, east, north)).toBe(height);
  });

  it('refuses a top that breaks a bound, by where it broke it', () => {
    const changed = (key: string, value: unknown): Record<string, unknown> => ({ ...top(), [key]: value });
    expect(refusal(() => readSiteTop({ ...top(), extra: 1 }, digest))).toBe('site top');
    expect(refusal(() => readSiteTop(changed('profile', 'exulanica.site-top/v2'), digest))).toBe('site top.profile');
    expect(refusal(() => readSiteTop(changed('cell_mm', 500), digest))).toBe('site top.cell_mm');
    expect(refusal(() => readSiteTop(changed('origin_mm', [500, 0]), digest))).toBe('site top.origin_mm');
    expect(refusal(() => readSiteTop(changed('columns', 1), digest))).toBe('site top.columns');
    expect(refusal(() => readSiteTop(changed('height_mm', [0]), digest))).toBe('site top.height_mm');
    const high = top();
    (high['height_mm'] as number[])[3] = 64_001;
    expect(refusal(() => readSiteTop(high, digest))).toBe('site top.height_mm[3]');
    expect(refusal(() => readSiteTop(top(), digest, '0'.repeat(64)))).toBe('site top');
  });

  it('says whether a cell is in a drawing\'s runs', () => {
    const runs = [[0, 2, 4], [3, 0, 0]] as const;
    expect(siteTopCellHeld(runs, 0, 2)).toBe(true);
    expect(siteTopCellHeld(runs, 0, 5)).toBe(false);
    expect(siteTopCellHeld(runs, 3, 0)).toBe(true);
    expect(siteTopCellHeld(runs, 1, 2)).toBe(false);
  });
});
