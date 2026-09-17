import { describe, expect, it } from 'vitest';
import {
  TILE_LOOK_ID,
  TILE_LOOK_V1,
  TileLookError,
  sunDirection,
  validateTileLook,
} from '../src/playcanvas/generated-tile/look.js';

type Mutable = Record<string, unknown>;
const copy = (): Mutable => structuredClone(TILE_LOOK_V1) as unknown as Mutable;
const refused = (value: unknown): string => {
  try {
    validateTileLook(value);
  } catch (error) {
    if (error instanceof TileLookError) return error.message;
    throw error;
  }
  throw new Error('the look was accepted');
};
const at = (look: Mutable, path: string): Mutable => path.split('.').reduce((node, key) => node[key] as Mutable, look);

describe('generated tile look descriptor', () => {
  it('validates version 1, carries an id and a version, and is frozen', () => {
    const look = validateTileLook(TILE_LOOK_V1);
    expect(look).toEqual(TILE_LOOK_V1);
    expect(look.id).toBe(TILE_LOOK_ID);
    expect(look.version).toBe(1);
    expect(Object.isFrozen(TILE_LOOK_V1)).toBe(true);
    expect(Object.isFrozen(TILE_LOOK_V1.sun.shadow)).toBe(true);
    expect(Object.isFrozen(look.fog)).toBe(true);
  });

  it('holds fog onset to the architecture target of 40 to 60 m', () => {
    for (const start of [40, 50, 60]) {
      const look = copy();
      at(look, 'fog')['startM'] = start;
      expect(() => validateTileLook(look)).not.toThrow();
    }
    for (const start of [39.9, 60.1, 110, 0]) {
      const look = copy();
      at(look, 'fog')['startM'] = start;
      expect(refused(look)).toMatch(/^fog\.startM: must be within 40 to 60/);
    }
    const inverted = copy();
    at(inverted, 'fog')['endM'] = 61;
    at(inverted, 'fog')['startM'] = 60;
    expect(() => validateTileLook(inverted)).not.toThrow();
    at(inverted, 'fog')['endM'] = 45;
    expect(refused(inverted)).toMatch(/^fog\.endM/);
  });

  it('has no switch that turns the probe or the contact shadowing off', () => {
    for (const path of ['environment', 'contactShadow']) {
      const look = copy();
      at(look, path)['enabled'] = false;
      expect(refused(look)).toBe(`${path}: has an unknown key "enabled"`);
    }
    const noRadius = copy();
    at(noRadius, 'contactShadow')['radiusM'] = 0.05;
    expect(refused(noRadius)).toMatch(/radiusM: must be within 0.1 to 3/);
  });

  it('refuses unknown keys, missing keys, wrong kinds and out-of-range values anywhere', () => {
    const unknown = copy();
    unknown['fallbackColour'] = [0.5, 0.5, 0.5];
    expect(refused(unknown)).toBe(': has an unknown key "fallbackColour"');
    const missing = copy();
    delete at(missing, 'sun.shadow')['bias'];
    expect(refused(missing)).toBe('sun.shadow: is missing "bias"');
    const wrongKind = copy();
    at(wrongKind, 'sun')['intensity'] = '2.6';
    expect(refused(wrongKind)).toBe('sun.intensity: must be a finite number');
    const notFinite = copy();
    at(notFinite, 'sun')['intensity'] = Number.NaN;
    expect(refused(notFinite)).toBe('sun.intensity: must be a finite number');
    const colour = copy();
    at(colour, 'sky')['zenith'] = [0.3, 0.4, 1.2];
    expect(refused(colour)).toBe('sky.zenith: must be three linear channels within 0 to 1');
    const shortColour = copy();
    at(shortColour, 'fog')['colour'] = [0.3, 0.4];
    expect(refused(shortColour)).toMatch(/^fog\.colour/);
    const resolution = copy();
    at(resolution, 'sun.shadow')['resolution'] = 3000;
    expect(refused(resolution)).toMatch(/^sun\.shadow\.resolution: must be one of/);
    const spelled = copy();
    at(spelled, 'sun.shadow')['resolution'] = '2048';
    expect(refused(spelled)).toBe('sun.shadow.resolution: must be a number');
    const cascades = copy();
    at(cascades, 'sun.shadow')['cascades'] = 2.5;
    expect(refused(cascades)).toBe('sun.shadow.cascades: must be a whole number');
    const tone = copy();
    tone['toneMapping'] = 'reinhard';
    expect(refused(tone)).toMatch(/^toneMapping: must be one of/);
    const id = copy();
    id['id'] = 'exulanica.world-style';
    expect(refused(id)).toMatch(/^id: must be/);
    expect(refused(null)).toBe(': must be an object');
    expect(refused([])).toBe(': must be an object');
  });

  it('keeps the height map off unless parallax is on', () => {
    const stray = copy();
    at(stray, 'surface')['parallaxFactor'] = 0.2;
    expect(refused(stray)).toBe('surface: parallaxFactor must be 0 while parallax is off');
    at(stray, 'surface')['parallax'] = true;
    expect(validateTileLook(stray).surface.parallaxFactor).toBe(0.2);
  });

  it('returns a copy, so the caller cannot change a validated look', () => {
    const source = copy();
    const look = validateTileLook(source);
    at(source, 'fog')['startM'] = 41;
    expect(look.fog.startM).toBe(TILE_LOOK_V1.fog.startM);
  });

  it('points the sun down and toward its azimuth', () => {
    const [x, y, z] = sunDirection(TILE_LOOK_V1);
    expect(Math.hypot(x, y, z)).toBeCloseTo(1, 12);
    expect(y).toBeCloseTo(-Math.sin((TILE_LOOK_V1.sun.elevationDeg * Math.PI) / 180), 12);
    const overhead = copy();
    at(overhead, 'sun')['elevationDeg'] = 85;
    expect(sunDirection(validateTileLook(overhead))[1]).toBeLessThan(-0.99);
  });
});
