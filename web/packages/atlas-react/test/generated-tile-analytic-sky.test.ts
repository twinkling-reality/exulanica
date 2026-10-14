import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { StylePackManifest } from '@exulanica/atlas-core';
import { TileLookError, sunDirection, validateRenderLook, type RenderLook } from '../src/playcanvas/generated-tile/look.js';
import { analyticSkyRadiance, renderSkyFaces, renderSkyRadiance } from '../src/playcanvas/generated-tile/sky.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';

/*
 * The analytic sky: an optional model a preset may name in place of the gradient. A look without
 * it draws exactly the faces it drew before.
 */

interface Case { readonly name: string; readonly manifest: StylePackManifest }
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8')) as { cases: Case[] };
const manifestNamed = (name: string): StylePackManifest => CASES.cases.find((c) => c.name === name)!.manifest;
const lookOf = (pack: StylePackManifest): RenderLook => renderLookOfPreset(pack.light!.presets[pack.light!.default_preset]!, pack.shading!, pack.edge);
const PLAIN = lookOf(manifestNamed('a complete pack with no base'));
const ANALYTIC = lookOf(manifestNamed('a preset with an analytic sky'));
const toSun = (look: RenderLook) => { const t = sunDirection(look); return [-t[0], -t[1], -t[2]] as const; };
const luminance = (c: readonly number[]) => 0.2126 * c[0]! + 0.7152 * c[1]! + 0.0722 * c[2]!;

describe('a preset with an analytic sky', () => {
  it('converts the pack\'s whole numbers to the look\'s', () => {
    expect(ANALYTIC.sky.model).toEqual({ kind: 'analytic', turbidity: 2.6, rayleigh: 1.2, mie: 0.006, mieDirection: 0.82 });
    expect('model' in PLAIN.sky).toBe(false);
  });

  it('is bluest overhead and brightest toward the sun', () => {
    const model = ANALYTIC.sky.model!;
    const sun = toSun(ANALYTIC);
    const zenith = analyticSkyRadiance(model, sun, [0, 1, 0]);
    expect(zenith[2]).toBeGreaterThan(zenith[0]);
    const away = analyticSkyRadiance(model, sun, [-sun[0], Math.abs(sun[1]), -sun[2]]);
    const toward = analyticSkyRadiance(model, sun, [sun[0], Math.abs(sun[1]), sun[2]]);
    expect(luminance(toward)).toBeGreaterThan(luminance(away));
  });

  it('gives way to the look\'s ground below the horizon, as the gradient does', () => {
    const down = renderSkyRadiance(ANALYTIC, [0, -1, 0]);
    const ground = ANALYTIC.sky.ground.map((c) => c * ANALYTIC.sky.intensity);
    down.forEach((c, i) => expect(c).toBeCloseTo(ground[i]!, 6));
  });

  it('is refused out of range, naming where', () => {
    const look = structuredClone(ANALYTIC) as unknown as { sky: { model: Record<string, unknown> } };
    look.sky.model['mieDirection'] = 0.99;
    expect(() => validateRenderLook(look)).toThrow(new TileLookError('sky.model.mieDirection: must be within 0 to 0.95'));
  });
});

describe('a look with no sky model', () => {
  it('draws the same faces as one written before the model existed', () => {
    const before = structuredClone(PLAIN) as unknown as Record<string, unknown>;
    const faces = renderSkyFaces(PLAIN, 16);
    const again = renderSkyFaces(validateRenderLook(before), 16);
    faces.forEach((face, i) => expect(Array.from(face)).toEqual(Array.from(again[i]!)));
    // And the analytic model changes them.
    const analytic = renderSkyFaces({ ...PLAIN, sky: { ...PLAIN.sky, model: ANALYTIC.sky.model! } } as RenderLook, 16);
    expect(Array.from(analytic[2]!)).not.toEqual(Array.from(faces[2]!));
  });
});
