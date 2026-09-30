import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  BLUE_HOUR_THEME,
  DAWN_THEME,
  EXULANICA_WORLD,
  byteRgba,
  pointProvenancePalette,
  unitRgb,
} from '../src/system.js';

const contrast = (foreground: string, background: string): number => {
  const linear = (byte: number): number => {
    const channel = byte / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  };
  const luminance = (hex: string): number => {
    const [r, g, b] = [hex.slice(1, 3), hex.slice(3, 5), hex.slice(5, 7)].map((value) =>
      linear(Number.parseInt(value!, 16)),
    );
    return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
  };
  const [light, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (light! + 0.05) / (dark! + 0.05);
};

describe('Exulanica presentation system', () => {
  it('defines one immutable directional field shared by both exposures', () => {
    expect(EXULANICA_WORLD.field.map(({ role, angleDeg }) => [role, angleDeg])).toEqual([
      ['key', 118],
      ['crosslight', 252],
      ['afterimage', 18],
      ['bounce', 4],
      ['rim', 154],
    ]);
    for (const fieldPlane of EXULANICA_WORLD.field) {
      expect(Object.isFrozen(fieldPlane)).toBe(true);
      expect(Object.isFrozen(fieldPlane.stops)).toBe(true);
      expect(fieldPlane.stops.map((stop) => stop.offsetPct)).toEqual(
        [...fieldPlane.stops].map((stop) => stop.offsetPct).sort((a, b) => a - b),
      );
      for (const stop of fieldPlane.stops) expect(stop.alpha).toBeGreaterThanOrEqual(0);
      for (const stop of fieldPlane.stops) expect(stop.alpha).toBeLessThanOrEqual(1);
    }
    expect(Object.isFrozen(EXULANICA_WORLD)).toBe(true);
    expect(Object.isFrozen(EXULANICA_WORLD.field)).toBe(true);
  });

  it('keeps every provenance class distinct in both exposures', () => {
    for (const theme of [DAWN_THEME, BLUE_HOUR_THEME]) {
      expect(new Set(Object.values(theme.provenance)).size).toBe(4);
    }
  });

  it('turns authored colors into renderer channels without another palette', () => {
    expect(unitRgb('#85aeff')).toEqual([133 / 255, 174 / 255, 1]);
    expect(byteRgba('#e2be79', 0.5)).toEqual([226, 190, 121, 128]);
    expect([...pointProvenancePalette(BLUE_HOUR_THEME)]).toHaveLength(16);
    expect(() => unitRgb('blue')).toThrow(TypeError);
  });

  it('keeps readable and semantic colors above WCAG AA on the world ground', () => {
    for (const theme of [DAWN_THEME, BLUE_HOUR_THEME]) {
      for (const color of [theme.ink, theme.body, theme.muted, ...Object.values(theme.provenance)]) {
        expect(contrast(color, theme.ground)).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it('keeps the user-facing daylight CSS tokens synchronized with renderer colors', () => {
    const css = readFileSync(new URL('../src/tokens.css', import.meta.url), 'utf8');
    for (const theme of [DAWN_THEME]) {
      const values = [
        theme.ground,
        theme.surface,
        theme.raised,
        theme.ink,
        theme.body,
        theme.muted,
        theme.accent,
        theme.secondary,
        theme.focus,
        theme.warning,
        theme.error,
        ...Object.values(theme.atmosphere),
        ...Object.values(theme.provenance),
      ];
      for (const value of values) expect(css).toContain(value);
    }
    expect(css).not.toContain(":root[data-theme='blue-hour']");
    for (const fieldPlane of EXULANICA_WORLD.field) {
      expect(css).toContain(`${fieldPlane.angleDeg}deg`);
      for (const stop of fieldPlane.stops) {
        expect(css).toContain(`${stop.offsetPct}%`);
        if (stop.alpha > 0) expect(css).toContain(`${stop.alpha * 100}%`);
      }
    }
    expect(css.match(/--field-image:/g)).toHaveLength(1);
    const fieldImage = css.match(/--field-image:\s*([^;]+);/)?.[1];
    expect(fieldImage).toBeDefined();
    // The directional world field stays linear; interface materials may use other gradients.
    expect(fieldImage).not.toContain('radial-gradient');
  });
});
