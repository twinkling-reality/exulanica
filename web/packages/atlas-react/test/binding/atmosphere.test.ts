/**
 * The binding's light and air come from one module.
 *
 * `atmosphere.ts` holds both looks as data and is the only place the binding's scene fog, ambient
 * light, exposure, lit end chunk, lights and clear colours are set. The presets are pinned here by
 * value, so a change to a look is a visible diff (and it also moves the GPU scenes' pixels), and
 * the scan keeps the binding from setting any of them itself again.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  CITY_ATMOSPHERE,
  COMPOSED_WORLD_ATMOSPHERE,
  atmosphereFor,
} from '../../src/playcanvas/atmosphere.js';
import { describeWorldKind } from '../../src/playcanvas/world-kind.js';
import { DISTRICT_DOCUMENT, ENDLESS_REGION, stubTileMount } from './world-kinds.js';

describe('the two looks', () => {
  it('are the composed world\'s and the city\'s, as data', () => {
    expect(COMPOSED_WORLD_ATMOSPHERE).toEqual({
      name: 'composed-world', farClip: 1200, clearColour: null, ambient: null, exposure: 1.06,
      fog: { start: 46, end: 220 },
      sun: { intensity: 1.65, shadowDistance: 72, normalOffsetBias: 0, shadowBias: 0.2 },
      skyFill: null,
    });
    expect(CITY_ATMOSPHERE).toEqual({
      name: 'city', farClip: 15_000, clearColour: [0.79, 0.85, 0.88], ambient: [0.64, 0.69, 0.74],
      exposure: 1.12, fog: { start: 110, end: 820 },
      sun: { intensity: 1.1, shadowDistance: 120, normalOffsetBias: 0.25, shadowBias: 0.2 },
      skyFill: { colour: [0.7, 0.82, 1], intensity: 0.72, euler: [28, 145, 0] },
    });
  });

  it('is chosen by city scale alone', () => {
    const district = { document: DISTRICT_DOCUMENT as never, residentBytes: 100 };
    expect(atmosphereFor(describeWorldKind({}))).toBe(COMPOSED_WORLD_ATMOSPHERE);
    expect(atmosphereFor(describeWorldKind({ authoredRegion: ENDLESS_REGION }))).toBe(COMPOSED_WORLD_ATMOSPHERE);
    expect(atmosphereFor(describeWorldKind({ ownedDistrict: district }))).toBe(CITY_ATMOSPHERE);
    expect(atmosphereFor(describeWorldKind({ generatedTile: stubTileMount() }))).toBe(CITY_ATMOSPHERE);
  });
});

/** Every way of setting the scene's air, its lights or the camera's clear colour directly. */
const ATMOSPHERE_CALL = /\bscene\.(fog|ambientLight|exposure)\b|ShaderChunks|addComponent\(\s*'light'|\.light\b|clearColor|toneMapping/g;

describe('where the binding sets its light and air', () => {
  const read = (file: string) => readFileSync(new URL(`../../src/playcanvas/${file}`, import.meta.url), 'utf8');

  it('is never in the binding itself', () => {
    expect(read('atlas-binding.ts').match(ATMOSPHERE_CALL) ?? []).toEqual([]);
  });

  it('is in the atmosphere module (the control: the scan does find a call)', () => {
    expect(new Set(read('atmosphere.ts').match(ATMOSPHERE_CALL))).toEqual(new Set([
      'scene.fog', 'scene.ambientLight', 'scene.exposure', 'ShaderChunks', "addComponent('light'",
      '.light', 'clearColor', 'toneMapping',
    ]));
  });
});
