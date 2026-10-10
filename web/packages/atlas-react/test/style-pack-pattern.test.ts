/**
 * A surface's pattern as the colour chunk draws it: each kind worked from the catalog's own periods
 * and strength, toward the pack's ink or the colour's own shade, in both shader languages.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { SURFACE_PATTERN_KINDS, readSurfacePatterns, type SurfacePattern } from '@exulanica/atlas-core';
import { patternChunks } from '../src/playcanvas/style-pack/pattern-material.js';

// Relative to web/, where the suite runs.
const PATTERNS = readSurfacePatterns(readFileSync('../assets/catalogs/world-kinds/surface-pattern.v1.json', 'utf8'));
const of = (key: string): SurfacePattern => PATTERNS.byMaterial.get(key)!;
const balanced = (text: string): boolean => {
  const closes: Record<string, string> = { ')': '(', '}': '{' };
  const open: string[] = [];
  for (const character of text) {
    if (character === '(' || character === '{') open.push(character);
    else if (character in closes && open.pop() !== closes[character]) return false;
  }
  return open.length === 0;
};

describe('a pattern\'s colour chunk', () => {
  it('works each kind from its own periods in metres and its own strength', () => {
    // Brick: rows 76 mm high of bricks 230 mm long, each row's joints half a brick along from the last.
    const brick = patternChunks(of('brick'), null).glsl;
    expect(brick).toContain('uv.y / 0.076000');
    expect(brick).toContain('uv.x / 0.230000 + 0.5 * (floor(uv.y / 0.076000)');
    expect(brick).toContain(`* ${(of('brick').strengthPermille / 1000).toFixed(6)});`);
    // Timber: boards 180 mm wide, each its own tone. Thatch: streaks 70 mm wide and a line every 450 mm.
    expect(patternChunks(of('timber'), null).glsl).toContain('exuPatternHash(vec2(floor(uv.x / 0.180000), 7.0))');
    const thatch = patternChunks(of('thatch'), null).glsl;
    expect(thatch).toContain('uv.x / 0.070000');
    expect(thatch).toContain('exuPatternLine(uv.y / 0.450000');
    // Canvas: a seam every 1.2 m and nothing else. A lake: ripples. Sand: a grain in two sizes.
    expect(patternChunks(of('canvas'), null).glsl).toContain('float exuPattern = exuPatternLine(uv.x / 1.200000, 0.008000 / 1.200000);');
    expect(patternChunks(of('lake'), null).glsl).toContain('sin(6.283185 * (uv.y / 3.200000');
    const sand = patternChunks(of('sand'), null).glsl;
    expect(sand).toContain('exuPatternNoise(uv / 1.600000)');
    expect(sand).toContain('exuPatternNoise(uv / (1.600000 * 0.23))');
    // Six kinds, six different amounts.
    const amounts = SURFACE_PATTERN_KINDS.map((kind) => {
      const pattern = [...PATTERNS.byMaterial.values()].find((one) => one.kind === kind)!;
      return /float exuPattern = (.*);/.exec(patternChunks({ ...pattern, periodAMm: 500, periodBMm: 250 }, null).glsl)![1];
    });
    expect(new Set(amounts).size).toBe(6);
  });

  it('darkens toward the pack\'s ink where it draws ink, and toward the colour\'s own shade where it does not', () => {
    const inked = patternChunks(of('stone'), [0.05, 0.04, 0.03]);
    expect(inked.glsl).toContain('mix(dAlbedo, vec3(0.050000, 0.040000, 0.030000), clamp(exuPattern, 0.0, 1.0)');
    expect(inked.wgsl).toContain('mix(dAlbedo, vec3f(0.050000, 0.040000, 0.030000), clamp(exuPattern, 0.0, 1.0)');
    const plain = patternChunks(of('stone'), null);
    expect(plain.glsl).toContain('mix(dAlbedo, dAlbedo * 0.500000, clamp(exuPattern, 0.0, 1.0)');
    expect(plain.wgsl).toContain('mix(dAlbedo, dAlbedo * 0.500000, clamp(exuPattern, 0.0, 1.0)');
  });

  it('is worked across the ground for a face that points up and along and up a wall for any other, and fades where it would be finer than the picture', () => {
    const { glsl, wgsl } = patternChunks(of('paving'), null);
    expect(glsl).toContain('n.y > 0.720000 ? vPositionW.xz : (n.x > n.z ? vec2(vPositionW.z, vPositionW.y) : vec2(vPositionW.x, vPositionW.y))');
    expect(wgsl).toContain('select(select(vec2f(vPositionW.x, vPositionW.y), vec2f(vPositionW.z, vPositionW.y), n.x > n.z), vPositionW.xz, n.y > 0.720000)');
    for (const text of [glsl, wgsl]) {
      expect(text).toContain('fwidth(t)');
      expect(text).toContain('clamp(1.0 - fw * 2.0, 0.0, 1.0)');
    }
  });

  it('is written in each language\'s own words, for every material\'s pattern', () => {
    for (const pattern of PATTERNS.byMaterial.values()) {
      const { glsl, wgsl } = patternChunks(pattern, [0.1, 0.1, 0.1]);
      expect(balanced(glsl) && balanced(wgsl), pattern.key).toBe(true);
      expect(glsl, pattern.key).toContain('void getAlbedo()');
      expect(wgsl, pattern.key).toContain('fn getAlbedo()');
      // No GLSL type or ternary in the WGSL, no WGSL type in the GLSL.
      expect(wgsl, pattern.key).not.toMatch(/\bvec[23]\(|\bfloat\b|\?/);
      expect(glsl, pattern.key).not.toMatch(/vec[23]f|\blet\b|\bfn\b/);
    }
  });
});
