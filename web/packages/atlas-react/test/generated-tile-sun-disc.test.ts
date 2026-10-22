import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { StylePackManifest } from '@exulanica/atlas-core';
import { sunDirection, validateRenderLook, type RenderLook } from '../src/playcanvas/generated-tile/look.js';
import { SUN_DISC_COS, cubeTexelWorldDirection, renderSkyFaces, renderSkyRadiance, skyClearShare, sunDiscRadiance } from '../src/playcanvas/generated-tile/sky.js';
import { SKY_BLOCK, SKY_DECLARATIONS, STAR_FULL_PIXEL, setSkyMarks, sunDiscSkyChunk } from '../src/playcanvas/generated-tile/sun-disc.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';

/*
 * The sun's disc drawn by the sky's shader: the faces are baked without it, and the shader draws it
 * where the faces did, as bright, and behind the same cloud.
 */

interface Case { readonly name: string; readonly manifest: StylePackManifest }
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8')) as { cases: Case[] };
const manifestNamed = (name: string): StylePackManifest => CASES.cases.find((c) => c.name === name)!.manifest;
const lookOf = (pack: StylePackManifest): RenderLook => renderLookOfPreset(pack.light!.presets[pack.light!.default_preset]!, pack.shading!, pack.edge);
const LOOK = lookOf(manifestNamed('a preset with an analytic sky'));
const toSun = (look: RenderLook) => { const t = sunDirection(look); return [-t[0], -t[1], -t[2]] as const; };

// The engine's own skybox chunk, so an engine upgrade that changes it fails here first.
const ENGINE = readFileSync(new URL('../node_modules/playcanvas/build/playcanvas/src/scene/shader-lib/glsl/chunks/skybox/frag/skybox.js', import.meta.url), 'utf8');
const SKYBOX = ENGINE.slice(ENGINE.indexOf('`') + 1, ENGINE.lastIndexOf('`'));

describe('the skybox chunk with the disc', () => {
  it('adds the declarations and one guarded block, and leaves every other line as it was', () => {
    const chunk = sunDiscSkyChunk(SKYBOX)!;
    expect(chunk.split('if (exuSunDisc.w > 0.0)').length).toBe(2);
    expect(chunk.indexOf('uniform vec4 exuSunDisc;')).toBeLessThan(chunk.indexOf('void main(void)'));
    // The block sits after the sky is sampled and before its highlight and tone mapping.
    expect(chunk.indexOf('exuSunDisc.w > 0.0')).toBeGreaterThan(chunk.indexOf('dir.x *= -1.0;'));
    expect(chunk.indexOf('exuSunDisc.w > 0.0')).toBeLessThan(chunk.indexOf('greaterThanEqual(linear, vec3(64.0))'));
    // The night's two branches are guarded by what a look states, so a day look skips them.
    expect(chunk.split('if (exuStars.w > 0.0)').length).toBe(2);
    expect(chunk.split('exuMoon.z > 0.0 ? exuMoonFace(exuDir) : 1.0').length).toBe(2);
    const removed = chunk.replace(SKY_DECLARATIONS, '').replace(SKY_BLOCK.trimStart() + ' '.repeat(12), '');
    expect(removed).toBe(SKYBOX);
  });

  it('takes every derivative where a pixel and its neighbours take the same branches', () => {
    // A derivative inside a branch a pixel decides for itself is undefined in GLSL; the block may branch
    // there only on what a look states, the same for every pixel.
    const open: string[] = [];
    let derivatives = 0;
    for (const line of SKY_BLOCK.split('\n')) {
      if (/\b(fwidth|dFdx|dFdy)\(/.test(line)) {
        derivatives += 1;
        for (const branch of open) expect(branch).toMatch(/^if \(exu(SunDisc|Stars)\.w > 0\.0\)$/);
      }
      let from = 0;
      for (let at = 0; at < line.length; at += 1) {
        if (line[at] === '{') open.push(line.slice(from, at).trim());
        if (line[at] === '}') open.pop();
        if (line[at] === '{' || line[at] === '}' || line[at] === ';') from = at + 1;
      }
    }
    expect(open).toEqual([]);
    expect(derivatives).toBeGreaterThanOrEqual(2);
  });

  it('works out the moon\'s face only inside its disc', () => {
    const line = SKY_BLOCK.split('\n').find((l) => l.includes('exuMoonFace(exuDir)'))!;
    expect(line.trim().startsWith('if (inDisc > 0.0)')).toBe(true);
  });

  it('draws a star dimmer, never brighter, where a pixel spans more of the sky than a full-size view\'s', () => {
    // The block compares its pixel angle (two screen steps) with STAR_FULL_PIXEL measured the same way.
    const stated = Number(/const float EXU_STAR_PIXEL = ([^;]+);/.exec(SKY_DECLARATIONS)![1]);
    expect(stated).toBeCloseTo(Math.SQRT2 * STAR_FULL_PIXEL, 10);
    expect(SKY_BLOCK).toContain('float starLight = min(1.0, (EXU_STAR_PIXEL / pixelAngle) * (EXU_STAR_PIXEL / pixelAngle));');
    const star = SKY_BLOCK.split('\n').find((l) => l.includes('linear += exuStars.y'))!;
    expect(star).toContain('* starLight *');
  });

  it('declines a chunk it was not written for', () => {
    expect(sunDiscSkyChunk('void main(void) { gl_FragColor = vec4(1.0); }')).toBeNull();
  });
});

describe('faces baked without the disc', () => {
  const size = 64;
  const withDisc = renderSkyFaces(LOOK, size);
  const without = renderSkyFaces(LOOK, size, false, false);
  const sun = toSun(LOOK);

  it('differ only where the disc was', () => {
    let changed = 0;
    for (let face = 0; face < 6; face += 1) {
      for (let row = 0; row < size; row += 1) {
        for (let column = 0; column < size; column += 1) {
          const at = (row * size + column) * 4;
          if (withDisc[face]![at] === without[face]![at]) continue;
          changed += 1;
          const d = cubeTexelWorldDirection(face, ((column + 0.5) / size) * 2 - 1, ((row + 0.5) / size) * 2 - 1);
          const cos = (d[0] * sun[0] + d[1] * sun[1] + d[2] * sun[2]) / Math.hypot(d[0], d[1], d[2]);
          expect(cos).toBeGreaterThan(SUN_DISC_COS);
        }
      }
    }
    expect(changed).toBeGreaterThan(0);
  });

  it('keep the glow round the sun', () => {
    const glow = renderSkyRadiance(LOOK, sun, false, false);
    const away = renderSkyRadiance(LOOK, [-sun[0], Math.abs(sun[1]), -sun[2]], false, false);
    expect(glow[0]).toBeGreaterThan(away[0]);
  });
});

describe('the disc the shader draws', () => {
  it('is as bright as the baked disc above its glow', () => {
    const sun = toSun(LOOK);
    const baked = renderSkyRadiance(LOOK, sun);
    const bare = renderSkyRadiance(LOOK, sun, false, false);
    sunDiscRadiance(LOOK).forEach((c, i) => expect(c).toBeCloseTo(baked[i]! - bare[i]!, 6));
  });

  it('is dimmed by cloud in front of the sun as the baked one was', () => {
    const clouds = { cover: 1, colour: [1, 1, 1] as const, shade: [0.5, 0.5, 0.5] as const, scale: 1, seed: 3 };
    const cloudy = { ...LOOK, sky: { ...LOOK.sky, clouds } } as RenderLook;
    const sun = toSun(cloudy);
    const dimmed = sunDiscRadiance(cloudy);
    expect(dimmed[0]).toBeLessThan(sunDiscRadiance(LOOK)[0]);
    const baked = renderSkyRadiance(cloudy, sun);
    const bare = renderSkyRadiance(cloudy, sun, false, false);
    dimmed.forEach((c, i) => expect(c).toBeCloseTo(baked[i]! - bare[i]!, 6));
  });
});

describe('the night a look states', () => {
  const size = 32;
  const clouds = { cover: 0.6, colour: [0.2, 0.2, 0.25] as const, shade: [0.1, 0.1, 0.12] as const, scale: 1, seed: 9 };
  const NIGHT = { ...LOOK, sky: { ...LOOK.sky, clouds, stars: { density: 0.07, intensity: 1.2, seed: 5 }, moon: { maria: 0.3, seed: 3 } } } as RenderLook;
  const DAY = { ...LOOK, sky: { ...LOOK.sky, clouds } } as RenderLook;

  it('leaves a look without stars exactly as it was: every face the same and opaque', () => {
    const day = renderSkyFaces(DAY, size, false, false);
    const night = renderSkyFaces(NIGHT, size, false, false);
    for (let face = 0; face < 6; face += 1) {
      for (let at = 0; at < size * size * 4; at += 4) {
        expect(day[face]![at + 3]).toBe(1);
        // The stars change no colour the faces hold, only what their alpha says.
        for (let channel = 0; channel < 3; channel += 1) expect(night[face]![at + channel]).toBe(day[face]![at + channel]);
      }
    }
  });

  it('carries the share of the sky its clouds leave clear in the drawn sky, and none in the image light', () => {
    const faces = renderSkyFaces(NIGHT, size, false, false);
    const light = renderSkyFaces(NIGHT, size, true, false);
    let clouded = 0;
    for (let face = 0; face < 6; face += 1) {
      for (let row = 0; row < size; row += 1) {
        for (let column = 0; column < size; column += 1) {
          const d = cubeTexelWorldDirection(face, ((column + 0.5) / size) * 2 - 1, ((row + 0.5) / size) * 2 - 1);
          const length = Math.hypot(d[0], d[1], d[2]);
          const unit = [d[0] / length, d[1] / length, d[2] / length] as const;
          const alpha = faces[face]![(row * size + column) * 4 + 3]!;
          expect(alpha).toBeCloseTo(skyClearShare(NIGHT, unit), 6);
          if (unit[1] < 0) expect(alpha).toBe(1);
          if (alpha < 0.5) clouded += 1;
          expect(light[face]![(row * size + column) * 4 + 3]).toBe(1);
        }
      }
    }
    expect(clouded).toBeGreaterThan(0);
  });

  it('hands the shader its stars and moon, and nothing for a look that states none', () => {
    const values = new Map<string, readonly number[]>();
    const device = { scope: { resolve: (name: string) => ({ setValue: (value: readonly number[]) => values.set(name, value) }) } };
    setSkyMarks(device as never, { ...NIGHT.sky, intensity: 0.5, stars: { density: 0.07, intensity: 1.2, seed: 16_777_221 } });
    expect(values.get('exuStars')).toEqual([0.07, 0.6, 5, 1]);
    expect(values.get('exuMoon')).toEqual([0.3, 3, 1, 0]);
    setSkyMarks(device as never, DAY.sky);
    expect(values.get('exuStars')).toEqual([0, 0, 0, 0]);
    expect(values.get('exuMoon')).toEqual([0, 0, 0, 0]);
    setSkyMarks(device as never, NIGHT.sky);
    setSkyMarks(device as never, null);
    expect(values.get('exuStars')).toEqual([0, 0, 0, 0]);
    expect(values.get('exuMoon')).toEqual([0, 0, 0, 0]);
  });

  it('is bounded as a look is', () => {
    expect(() => validateRenderLook(NIGHT)).not.toThrow();
    expect(() => validateRenderLook({ ...NIGHT, sky: { ...NIGHT.sky, stars: { density: 0, intensity: 1, seed: 1 } } } as RenderLook)).toThrow();
    expect(() => validateRenderLook({ ...NIGHT, sky: { ...NIGHT.sky, moon: { maria: 1.5, seed: 1 } } } as RenderLook)).toThrow();
  });
});
