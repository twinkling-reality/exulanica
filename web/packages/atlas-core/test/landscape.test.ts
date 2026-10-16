/**
 * The landscape readers: the server's landscape drawing and volume chunks read as served, every
 * bound and digest held, the level a page draws a volume at, and a volume point placed by its turn.
 * The documents are `packages/atlas-react/test/fixtures/landscape.v1.json`, the server's own output.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  LandscapeError, placedPointMm, readLandscapeDrawing, readVolumeChunk, volumeDrawnCellMm,
  type PlacedVolume,
} from '../src/landscape.js';

const digest = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');
const FIXTURE = JSON.parse(readFileSync('packages/atlas-react/test/fixtures/landscape.v1.json', 'utf8')) as {
  drawing: Record<string, unknown>; drawing_sha256: string; chunks: Record<string, Record<string, unknown>>;
};
const drawing = (): Record<string, unknown> => structuredClone(FIXTURE.drawing);
const [firstSha, firstChunk] = Object.entries(FIXTURE.chunks)[0]!;
const chunk = (): Record<string, unknown> => structuredClone(firstChunk);

const refusal = (read: () => unknown): string => {
  try {
    read();
  } catch (error) {
    expect(error).toBeInstanceOf(LandscapeError);
    return (error as LandscapeError).where;
  }
  throw new Error('read without a refusal');
};

describe('the landscape drawing', () => {
  it('reads the server\'s drawing, held to its digest', () => {
    const read = readLandscapeDrawing(drawing(), digest, FIXTURE.drawing_sha256);
    expect(read.sha256).toBe(FIXTURE.drawing_sha256);
    const [island] = read.volumes;
    expect(island!.atMm).toEqual([32000, -60000, 70000]);
    expect(island!.yawMdeg).toBe(30000);
    expect(island!.chunks.every((one) => one.cellMm === 4000)).toBe(true);
    expect(island!.tops.map((top) => top.surface)).toEqual(['top:0']);
    // A drawing made before drawings named a volume's looks: rock, and no top of its own.
    expect([island!.look, island!.topLook]).toEqual(['rock', null]);
  });

  it('reads the looks a drawing names for a volume, together and in the volume catalog\'s words', () => {
    const looked = (look: unknown, topLook: unknown): Record<string, unknown> => {
      const raw = drawing();
      const volume = (raw['volumes'] as Record<string, unknown>[])[0]!;
      if (look !== undefined) volume['look'] = look;
      if (topLook !== undefined) volume['top_look'] = topLook;
      return raw;
    };
    const [island] = readLandscapeDrawing(looked('rock', 'grass'), digest).volumes;
    expect([island!.look, island!.topLook]).toEqual(['rock', 'grass']);
    expect(readLandscapeDrawing(looked('wall', 'sand'), digest).volumes[0]!.topLook).toBe('sand');
    expect(refusal(() => readLandscapeDrawing(looked('rock', 'lawn'), digest))).toBe('landscape.volumes[0].top_look');
    expect(refusal(() => readLandscapeDrawing(looked('glass', 'grass'), digest))).toBe('landscape.volumes[0].look');
    expect(refusal(() => readLandscapeDrawing(looked(undefined, 'grass'), digest))).toBe('landscape.volumes[0]');
    expect(refusal(() => readLandscapeDrawing(looked('rock', undefined), digest))).toBe('landscape.volumes[0]');
  });

  it('refuses each broken bound by where it broke, and another document than its digest names', () => {
    const changed = (change: (raw: Record<string, unknown>) => void): Record<string, unknown> => {
      const raw = drawing();
      change(raw);
      return raw;
    };
    const volume = (raw: Record<string, unknown>) => (raw['volumes'] as Record<string, unknown>[])[0]!;
    expect(refusal(() => readLandscapeDrawing(drawing(), digest, '0'.repeat(64)))).toBe('landscape');
    expect(refusal(() => readLandscapeDrawing(changed((raw) => { raw['profile'] = 'exulanica.landscape-drawing/v2'; }), digest))).toBe('landscape.profile');
    expect(refusal(() => readLandscapeDrawing(changed((raw) => { raw['sky'] = []; }), digest))).toBe('landscape');
    expect(refusal(() => readLandscapeDrawing(changed((raw) => { volume(raw)['at_mm'] = [0, 0, 2_000_000]; }), digest))).toBe('landscape.volumes[0].at_mm[2]');
    expect(refusal(() => readLandscapeDrawing(changed((raw) => { volume(raw)['yaw_mdeg'] = 360_000; }), digest))).toBe('landscape.volumes[0].yaw_mdeg');
    expect(refusal(() => readLandscapeDrawing(changed((raw) => { volume(raw)['id'] = 'Island'; }), digest))).toBe('landscape.volumes[0].id');
    expect(refusal(() => readLandscapeDrawing(changed((raw) => {
      ((volume(raw)['chunks'] as Record<string, unknown>[])[0]!)['cell_mm'] = 3000;
    }), digest))).toBe('landscape.volumes[0].chunks[0].cell_mm');
    expect(refusal(() => readLandscapeDrawing(changed((raw) => {
      ((volume(raw)['tops'] as Record<string, unknown>[])[0]!)['surface'] = 'top:01';
    }), digest))).toBe('landscape.volumes[0].tops[0].surface');
    expect(refusal(() => readLandscapeDrawing(changed((raw) => {
      raw['volumes'] = [volume(raw), volume(raw)];
    }), digest))).toBe('landscape.volumes');
  });
});

describe('a volume chunk', () => {
  it('reads the server\'s chunk, held to its digest', () => {
    const read = readVolumeChunk(chunk(), digest, firstSha);
    expect(read.sha256).toBe(firstSha);
    expect(read.positionsMm.length).toBe(read.normals.length);
    expect(read.vertexLooks.length * 3).toBe(read.positionsMm.length);
    expect(Math.max(...read.triangles)).toBeLessThan(read.vertexLooks.length);
  });

  it('refuses each broken bound by where it broke', () => {
    const changed = (name: string, value: (raw: unknown) => unknown): Record<string, unknown> => {
      const raw = chunk();
      raw[name] = value(raw[name]);
      return raw;
    };
    expect(refusal(() => readVolumeChunk(chunk(), digest, '0'.repeat(64)))).toBe('volume chunk');
    expect(refusal(() => readVolumeChunk(changed('rules_version', () => 4), digest))).toBe('volume chunk.rules_version');
    expect(refusal(() => readVolumeChunk(changed('rules_version', () => '1'), digest))).toBe('volume chunk.rules_version');
    expect(readVolumeChunk(changed('rules_version', () => 2), digest).sha256).not.toBe(firstSha);
    expect(readVolumeChunk(changed('rules_version', () => 3), digest).sha256).not.toBe(firstSha);
    expect(refusal(() => readVolumeChunk(changed('cell_mm', () => 3000), digest))).toBe('volume chunk.cell_mm');
    expect(refusal(() => readVolumeChunk(changed('looks', () => ['rock']), digest))).toBe('volume chunk.looks');
    expect(refusal(() => readVolumeChunk(changed('positions_mm', (p) => [(p as number[])[0]! + 200_000, ...(p as number[]).slice(1)]), digest))).toBe('volume chunk.positions_mm');
    expect(refusal(() => readVolumeChunk(changed('normals', (n) => (n as number[]).slice(3)), digest))).toBe('volume chunk.normals');
    expect(refusal(() => readVolumeChunk(changed('vertex_looks', (v) => [2, ...(v as number[]).slice(1)]), digest))).toBe('volume chunk.vertex_looks[0]');
    expect(refusal(() => readVolumeChunk(changed('triangles', (t) => [...(t as number[]).slice(0, -1), 1_000_000]), digest))).toMatch(/^volume chunk\.triangles/);
  });
});

describe('where a page draws a volume', () => {
  const placed = (cells: number[], yawMdeg = 0): PlacedVolume => ({
    id: 'probe', volumeSha256: '0'.repeat(64), inputSha256: '0'.repeat(64), atMm: [1000, 2000, 3000], yawMdeg,
    look: 'rock', topLook: null,
    chunks: cells.map((cellMm) => ({ chunk: [0, 0, 0], cellMm, sha256: '0'.repeat(64) })), tops: [],
  });

  it('draws the finest level not finer than the landscape\'s default, else the coarsest it names', () => {
    expect(volumeDrawnCellMm(placed([4000, 2000, 1000]))).toBe(2000);
    expect(volumeDrawnCellMm(placed([4000]))).toBe(4000);
    expect(volumeDrawnCellMm(placed([1000, 500]))).toBe(1000);
    expect(volumeDrawnCellMm(placed([4000, 2000, 1000]), 1000)).toBe(1000);
    expect(volumeDrawnCellMm(placed([]))).toBeNull();
  });

  it('turns a volume counterclockwise seen from above, east toward north', () => {
    const [east, north, up] = placedPointMm(placed([4000], 90_000), 1000, 0, 0);
    expect(east).toBeCloseTo(1000, 6);
    expect(north).toBeCloseTo(3000, 6);
    expect(up).toBe(3000);
  });
});
