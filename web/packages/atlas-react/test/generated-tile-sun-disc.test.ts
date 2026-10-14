import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { StylePackManifest } from '@exulanica/atlas-core';
import { sunDirection, type RenderLook } from '../src/playcanvas/generated-tile/look.js';
import { SUN_DISC_COS, cubeTexelWorldDirection, renderSkyFaces, renderSkyRadiance, sunDiscRadiance } from '../src/playcanvas/generated-tile/sky.js';
import { sunDiscSkyChunk } from '../src/playcanvas/generated-tile/sun-disc.js';
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
    const removed = chunk
      .replace(/\nuniform vec4 exuSunDisc;[^\n]*\nuniform vec3 exuSunDiscColour;[^\n]*\n/, '')
      .replace(/if \(exuSunDisc\.w > 0\.0\) \{[\s\S]*?\n {12}\}\n {12}/, '');
    expect(removed).toBe(SKYBOX);
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
